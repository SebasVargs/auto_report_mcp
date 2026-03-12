"""
test_rag_system.py — Orquestador principal del RAG v2.

Integra todos los componentes: DocxReader, DocumentClassifier,
StructuralChunker, IngestionPipeline, QueryRouter, MethodValidator,
SemanticCache y las 4 colecciones de ChromaDB.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.rag.collection_manager import initialize_collections
from app.rag.docx_reader import DocxReader
from app.rag.document_classifier import DocumentClassifier
from app.rag.document_ingestion_pipeline_v2 import IngestionPipelineV2, IngestResult
from app.rag.embedding_service import EmbeddingService
from app.rag.method_validator import (
    MethodRegistry,
    MethodGroundingFilter,
    build_system_prompt,
    FilterResult,
)
from app.rag.query_router import TestAwareQueryRouter, QueryIntent, RetrievalResult
from app.rag.rag_schema import DocType
from app.rag.semantic_cache import SemanticQueryCache
from app.rag.structural_chunker import StructuralChunker
from app.rag.vector_store import VectorStore
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class RAGResponse:
    """Respuesta final del sistema RAG v2."""
    answer: str
    chunks_used: list[dict] = field(default_factory=list)
    has_hallucinations: bool = False
    hallucinated_methods: list[str] = field(default_factory=list)
    served_from_cache: bool = False
    intent: QueryIntent | None = None


class TestRAGSystem:
    """
    Orquestador principal del RAG v2.

    Flujo de query:
    1. SemanticQueryCache → si hit, retornar
    2. Detectar intent con QueryRouter
    3. Recuperar chunks con QueryRouter.route()
    4. Si wants_test: system prompt con métodos reales
    5. Llamar al LLM
    6. Si wants_test: filtrar con MethodGroundingFilter
    7. Guardar en caché
    8. Retornar RAGResponse
    """

    def __init__(
        self,
        vector_store: VectorStore | None = None,
        embedding_service: EmbeddingService | None = None,
        llm_callable=None,
    ):
        self._vs = vector_store or VectorStore()
        self._emb = embedding_service or EmbeddingService()
        self._llm = llm_callable  # function(system_prompt, context, query) -> str

        # Initialize components
        self._collections = initialize_collections(self._vs)
        self._classifier = DocumentClassifier()
        self._chunker = StructuralChunker()
        self._docx_reader = DocxReader()

        self._pipeline = IngestionPipelineV2(
            vector_store=self._vs,
            classifier=self._classifier,
            chunker=self._chunker,
            docx_reader=self._docx_reader,
            embedding_service=self._emb,
            collections=self._collections,
        )

        self._router = TestAwareQueryRouter(
            vector_store=self._vs,
            embedding_service=self._emb,
        )

        self._method_registry = MethodRegistry()
        self._grounding_filter = MethodGroundingFilter()

        self._cache = SemanticQueryCache(
            embedding_service=self._emb,
            similarity_threshold=0.92,
            max_size=300,
            ttl_hours=24,
        )

        # Build initial method registry from existing data
        try:
            self._method_registry.build_registry(
                vector_store=self._vs,
                collection_name="project_docs",
            )
        except Exception as e:
            logger.warning(f"Initial method registry build failed: {e}")

        logger.info("TestRAGSystem v2 initialized")

    # ─────────────────────────────────────────────────
    # Query
    # ─────────────────────────────────────────────────

    def query(self, user_query: str) -> RAGResponse:
        """Procesa una consulta del usuario a través del pipeline completo."""

        # 1. Detectar intent
        intent = self._router.detect_query_intent(user_query)
        intent_key = self._build_intent_key(intent)

        # 2. Revisar caché
        cached = self._cache.get(user_query, intent_key)
        if cached:
            logger.info(f"Cache HIT for: {user_query[:50]}...")
            return RAGResponse(
                answer=cached.result.get("answer", ""),
                chunks_used=cached.result.get("chunks", []),
                served_from_cache=True,
                intent=intent,
            )

        # 3. Recuperar chunks con routing
        retrieval = self._router.route(
            user_query, self._collections, top_k=8
        )

        # 4. Construir contexto para LLM
        context_text = self._build_context(retrieval.chunks)
        system_prompt = ""

        if intent.wants_test and intent.target_component:
            system_prompt = build_system_prompt(
                intent.target_component, self._method_registry
            )

        # 5. Llamar al LLM
        if self._llm:
            answer = self._llm(system_prompt, context_text, user_query)
        else:
            answer = f"[LLM not configured] Context retrieved: {len(retrieval.chunks)} chunks"

        # 6. Filtrar métodos alucinados
        has_hallucinations = False
        hallucinated = []

        if intent.wants_test and intent.target_component:
            filter_result = self._grounding_filter.filter_hallucinated_methods(
                answer, intent.target_component, self._method_registry
            )
            answer = filter_result.filtered_response
            has_hallucinations = filter_result.has_hallucinations
            hallucinated = filter_result.hallucinated_methods

        # 7. Guardar en caché
        self._cache.set(
            user_query,
            intent_key,
            {"answer": answer, "chunks": retrieval.chunks},
            daily_notes_included=retrieval.daily_notes_included,
            component=intent.target_component,
        )

        return RAGResponse(
            answer=answer,
            chunks_used=retrieval.chunks,
            has_hallucinations=has_hallucinations,
            hallucinated_methods=hallucinated,
            served_from_cache=False,
            intent=intent,
        )

    # ─────────────────────────────────────────────────
    # Document ingestion
    # ─────────────────────────────────────────────────

    def add_daily_note(
        self, content: str, date: str | None = None
    ) -> IngestResult:
        """Ingesta una nota diaria y actualiza el caché."""
        if not date:
            date = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

        result = self._pipeline.ingest_daily_note(content, date)
        invalidated = self._cache.invalidate_daily_notes_cache()
        logger.info(f"Daily note ingested, {invalidated} cache entries invalidated")

        # Rebuild registry in case note mentions new methods
        try:
            self._method_registry.build_registry(
                vector_store=self._vs,
                collection_name="project_docs",
            )
        except Exception:
            pass

        return result

    def add_document(self, file_path: str) -> IngestResult:
        """Ingesta un documento individual y actualiza componentes."""
        result = self._pipeline.ingest_file(file_path)

        # Invalidar caché del componente
        if result.doc_type == DocType.METHOD_DOC:
            # Rebuild method registry
            try:
                self._method_registry.build_registry(
                    vector_store=self._vs,
                    collection_name="project_docs",
                )
            except Exception:
                pass

        # Invalidar caché si tiene componente
        # Use the classifier to get metadata for component extraction
        self._cache.invalidate_by_component(result.source)

        return result

    def add_directory(
        self, dir_path: str, recursive: bool = True
    ) -> list[IngestResult]:
        """Ingesta un directorio completo."""
        results = self._pipeline.ingest_directory(dir_path, recursive)

        # Rebuild registry after batch ingestion
        try:
            self._method_registry.build_registry(
                vector_store=self._vs,
                collection_name="project_docs",
            )
        except Exception:
            pass

        return results

    # ─────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────

    @staticmethod
    def _build_intent_key(intent: QueryIntent) -> str:
        test_type = intent.test_type.value if intent.test_type else "none"
        return f"{test_type}_{intent.target_component}_{intent.target_method}"

    @staticmethod
    def _build_context(chunks: list[dict]) -> str:
        parts: list[str] = []
        for i, chunk in enumerate(chunks):
            meta = chunk.get("metadata", {})
            header = f"--- Chunk {i + 1}"
            if meta.get("doc_type"):
                header += f" ({meta['doc_type']})"
            if meta.get("component"):
                header += f" [{meta['component']}]"
            header += " ---"
            parts.append(header)
            parts.append(chunk.get("content", ""))
        return "\n\n".join(parts)
