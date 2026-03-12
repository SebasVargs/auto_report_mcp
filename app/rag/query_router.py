"""
query_router.py — Query Router para RAG v2.

Reemplaza el Multi-Query Retrieval: en lugar de expandir la consulta
semánticamente, la enruta al destino correcto directamente.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.rag.embedding_service import EmbeddingService
from app.rag.rag_schema import DocType, CollectionName, get_collection_for_doc_type
from app.rag.vector_store import VectorStore
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Patrones de detección de intent ─────────────────────────────

_WANTS_TEST = re.compile(
    r"\b(tests?|pruebas?|testear|spec|genera|crea un test|escribe un test|"
    r"unit test|mock|generar test|generar prueba)\b",
    re.IGNORECASE,
)

_UNIT_KEYWORDS = re.compile(
    r"\b(unit|unitaria|unitario|mock|aislado|sin dependencias|stub)\b",
    re.IGNORECASE,
)
_INT_KEYWORDS = re.compile(
    r"\b(integración|integration|base de datos|api|http|endpoint|repository)\b",
    re.IGNORECASE,
)
_FUNC_KEYWORDS = re.compile(
    r"\b(funcional|e2e|end to end|flujo completo|scenario|browser)\b",
    re.IGNORECASE,
)

# Buscar target component/method en la query
_COMPONENT_IN_QUERY = re.compile(
    r"(?:para|for|de|del|en)\s+(\w+(?:Service|Repository|Controller|Manager|Handler|Module|Component))",
    re.IGNORECASE,
)
_METHOD_IN_QUERY = re.compile(
    r"(?:para|for|de|del|método|method)\s+(?:\w+\.)?(\w+)\s*\(?",
    re.IGNORECASE,
)
_DOTTED_METHOD = re.compile(r"(\w+)\.(\w+)")


# ── Dataclasses ─────────────────────────────────────────────────

@dataclass
class QueryIntent:
    """Intención detectada de la query del usuario."""
    wants_test: bool = False
    test_type: DocType | None = None
    target_component: str = ""
    target_method: str = ""
    needs_method_context: bool = False


@dataclass
class RetrievalResult:
    """Resultado de la recuperación con routing."""
    chunks: list[dict] = field(default_factory=list)
    primary_source: str = ""
    method_context_found: bool = False
    daily_notes_included: bool = False


class TestAwareQueryRouter:
    """
    Enruta queries a las colecciones correctas en lugar de expandir
    semánticamente. Tres casos:
    - CASO A: usuario pide generar un test
    - CASO B: usuario busca un test existente
    - CASO C: usuario pregunta sobre un método o funcionalidad
    """

    def __init__(
        self,
        vector_store: VectorStore | None = None,
        embedding_service: EmbeddingService | None = None,
    ):
        self._vs = vector_store or VectorStore()
        self._emb = embedding_service or EmbeddingService()

    # ─────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────

    def detect_query_intent(self, query: str) -> QueryIntent:
        """Detecta la intención de la query."""
        wants_test = bool(_WANTS_TEST.search(query))

        test_type: DocType | None = None
        if _UNIT_KEYWORDS.search(query):
            test_type = DocType.UNIT_TEST
        elif _INT_KEYWORDS.search(query):
            test_type = DocType.INTEGRATION_TEST
        elif _FUNC_KEYWORDS.search(query):
            test_type = DocType.FUNCTIONAL_TEST

        target_component = ""
        target_method = ""

        # Try Component.method pattern first
        dot_match = _DOTTED_METHOD.search(query)
        if dot_match:
            target_component = dot_match.group(1)
            target_method = dot_match.group(2)
        else:
            comp_match = _COMPONENT_IN_QUERY.search(query)
            if comp_match:
                target_component = comp_match.group(1)
            meth_match = _METHOD_IN_QUERY.search(query)
            if meth_match:
                target_method = meth_match.group(1)

        return QueryIntent(
            wants_test=wants_test,
            test_type=test_type,
            target_component=target_component,
            target_method=target_method,
            needs_method_context=wants_test,
        )

    def route(
        self,
        query: str,
        collections: dict,
        top_k: int = 8,
    ) -> RetrievalResult:
        """Enruta la query a las colecciones correctas."""
        intent = self.detect_query_intent(query)
        embedding = self._emb.embed(query)

        if intent.wants_test and intent.test_type:
            # CASO A — generar un test
            return self._route_generate_test(
                embedding, intent, collections, top_k
            )
        elif intent.wants_test:
            # CASO B — buscar test existente (sin tipo específico)
            return self._route_search_tests(
                embedding, intent, collections, top_k
            )
        else:
            # CASO C — pregunta sobre método o funcionalidad
            return self._route_method_query(
                embedding, intent, collections, top_k
            )

    # ─────────────────────────────────────────────────
    # CASO A — Generar test
    # ─────────────────────────────────────────────────

    def _route_generate_test(
        self, embedding, intent: QueryIntent, collections: dict, top_k: int
    ) -> RetrievalResult:
        all_chunks: list[dict] = []
        method_found = False
        notes_included = False

        # Paso 1: buscar docs de métodos en project_docs
        if CollectionName.PROJECT_DOCS.value in collections:
            where = {"doc_type": "method_doc"}
            if intent.target_component:
                where["component"] = intent.target_component
            method_chunks = self._query_collection(
                CollectionName.PROJECT_DOCS.value, embedding, 3, where
            )
            if method_chunks:
                method_found = True
                all_chunks.extend(method_chunks)

        # Paso 2: buscar tests del mismo tipo
        col_name = get_collection_for_doc_type(intent.test_type).value
        if col_name in collections:
            where = {}
            if intent.target_component:
                where["component"] = intent.target_component
            test_chunks = self._query_collection(
                col_name, embedding, 4, where if where else None
            )
            all_chunks.extend(test_chunks)

        # Paso 3: buscar daily notes
        if CollectionName.PROJECT_DOCS.value in collections:
            where = {"is_daily_note": True}
            if intent.target_component:
                where["component"] = intent.target_component
            note_chunks = self._query_collection(
                CollectionName.PROJECT_DOCS.value, embedding, 2, where
            )
            if note_chunks:
                notes_included = True
                # Daily notes SIEMPRE van primero
                all_chunks = note_chunks + all_chunks

        # Apply priority scoring
        all_chunks = self._apply_priority_scoring(all_chunks, intent)

        return RetrievalResult(
            chunks=all_chunks[:top_k],
            primary_source=col_name,
            method_context_found=method_found,
            daily_notes_included=notes_included,
        )

    # ─────────────────────────────────────────────────
    # CASO B — Buscar test existente
    # ─────────────────────────────────────────────────

    def _route_search_tests(
        self, embedding, intent: QueryIntent, collections: dict, top_k: int
    ) -> RetrievalResult:
        all_chunks: list[dict] = []

        # Search across all test collections
        for col_name_enum in [
            CollectionName.UNIT_TESTS,
            CollectionName.INTEGRATION_TESTS,
            CollectionName.FUNCTIONAL_TESTS,
        ]:
            if col_name_enum.value in collections:
                chunks = self._query_collection(
                    col_name_enum.value, embedding, top_k
                )
                all_chunks.extend(chunks)

        all_chunks = self._apply_priority_scoring(all_chunks, intent)
        all_chunks.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

        return RetrievalResult(
            chunks=all_chunks[:top_k],
            primary_source="multi_test",
            method_context_found=False,
            daily_notes_included=False,
        )

    # ─────────────────────────────────────────────────
    # CASO C — Pregunta sobre método/funcionalidad
    # ─────────────────────────────────────────────────

    def _route_method_query(
        self, embedding, intent: QueryIntent, collections: dict, top_k: int
    ) -> RetrievalResult:
        all_chunks: list[dict] = []
        notes_included = False

        if CollectionName.PROJECT_DOCS.value not in collections:
            return RetrievalResult()

        # Daily notes first
        note_chunks = self._query_collection(
            CollectionName.PROJECT_DOCS.value, embedding, 3,
            where={"is_daily_note": True},
        )
        if note_chunks:
            notes_included = True
            all_chunks.extend(note_chunks)

        # Method docs
        method_chunks = self._query_collection(
            CollectionName.PROJECT_DOCS.value, embedding, top_k,
            where={"doc_type": "method_doc"},
        )
        all_chunks.extend(method_chunks)

        # General project docs
        general_chunks = self._query_collection(
            CollectionName.PROJECT_DOCS.value, embedding, top_k,
        )
        all_chunks.extend(general_chunks)

        # Deduplicate
        seen: set[str] = set()
        unique: list[dict] = []
        for c in all_chunks:
            cid = c.get("id", id(c))
            if cid not in seen:
                seen.add(cid)
                unique.append(c)
        all_chunks = unique

        all_chunks = self._apply_priority_scoring(all_chunks, intent)

        return RetrievalResult(
            chunks=all_chunks[:top_k],
            primary_source=CollectionName.PROJECT_DOCS.value,
            method_context_found=bool(method_chunks),
            daily_notes_included=notes_included,
        )

    # ─────────────────────────────────────────────────
    # Priority scoring
    # ─────────────────────────────────────────────────

    def _apply_priority_scoring(
        self, chunks: list[dict], intent: QueryIntent
    ) -> list[dict]:
        """Re-score chunks based on metadata matching."""
        scored: list[dict] = []
        for chunk in chunks:
            score = chunk.get("relevance_score", 0.5)
            meta = chunk.get("metadata", {})

            # Daily notes get priority boost
            if meta.get("is_daily_note"):
                score *= meta.get("priority_score", 2.0)

            # Incomplete signatures get penalized
            if meta.get("has_incomplete_signature"):
                score *= 0.3

            # Exact component match
            if (intent.target_component
                    and meta.get("component") == intent.target_component):
                score *= 1.5

            # Exact method match
            if (intent.target_method
                    and meta.get("method_name") == intent.target_method):
                score *= 2.0

            scored.append({**chunk, "relevance_score": score})

        scored.sort(key=lambda x: x["relevance_score"], reverse=True)
        return scored

    # ─────────────────────────────────────────────────
    # ChromaDB query helper
    # ─────────────────────────────────────────────────

    def _query_collection(
        self,
        collection_name: str,
        embedding: list[float],
        top_k: int,
        where: dict | None = None,
    ) -> list[dict]:
        """Query a collection, return empty list on error."""
        try:
            return self._vs.query(
                collection_name=collection_name,
                query_embedding=embedding,
                top_k=top_k,
                where=where,
            ) or []
        except Exception as e:
            logger.debug(f"Query to '{collection_name}' failed: {e}")
            return []
