from __future__ import annotations

from app.config import get_settings
from app.models.report_model import DailyInput, StyleChunk, StyleContext
from app.rag.embedding_service import EmbeddingService
from app.rag.vector_store import VectorStore
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


class StyleRetriever:
    """
    Retrieves style-relevant chunks from historical reports
    to provide RAG context for new report generation.

    Strategy:
    1. Build multiple focused queries from input data
    2. Embed each query
    3. Query ChromaDB per query
    4. Deduplicate and rerank by combined relevance
    5. Return top-K as StyleContext
    """

    def __init__(self):
        self._embedding_service = EmbeddingService()
        self._vector_store = VectorStore()

    def retrieve_style_context(
        self, daily_input: DailyInput, top_k: int | None = None
    ) -> StyleContext:
        """
        Main entry point for style retrieval.
        Builds context-aware queries from the daily input.
        """
        k = top_k or settings.rag_top_k
        queries = self._build_queries(daily_input)

        logger.info(f"Retrieving style context with {len(queries)} queries, top_k={k}")

        # Per-query retrieval
        raw_results: dict[str, dict] = {}  # id → result (dedup)
        for query_text in queries:
            embedding = self._embedding_service.embed(query_text)
            results = self._vector_store.query(
                collection_name=settings.chroma_collection_style,
                query_embedding=embedding,
                top_k=k,
            )
            for r in results:
                chunk_id = r["id"]
                if chunk_id not in raw_results or r["relevance_score"] > raw_results[chunk_id]["relevance_score"]:
                    raw_results[chunk_id] = r

        # Rerank: score by frequency of retrieval + relevance
        ranked = sorted(
            raw_results.values(),
            key=lambda x: x["relevance_score"],
            reverse=True,
        )[:k]

        chunks = [
            StyleChunk(
                chunk_id=r["id"],
                source_document=r["metadata"].get("source_document", "unknown"),
                content=r["content"],
                relevance_score=r["relevance_score"],
                section_type=self._classify_section(r["metadata"].get("section", "")),
            )
            for r in ranked
        ]

        logger.info(
            f"Retrieved {len(chunks)} style chunks "
            f"(avg relevance: {sum(c.relevance_score for c in chunks) / max(len(chunks), 1):.3f})"
        )

        return StyleContext(
            chunks=chunks,
            total_tokens_estimate=sum(len(c.content.split()) * 4 // 3 for c in chunks),
        )

    # ─────────────────────────────────────────────────
    # Query construction
    # ─────────────────────────────────────────────────

    def _build_queries(self, daily_input: DailyInput) -> list[str]:
        """
        Multiple focused queries capture different aspects of style:
        - Executive summary style
        - Technical description of results
        - Conclusions / recommendations style
        """
        queries = [
            f"resumen ejecutivo informe {daily_input.report_type.value} {daily_input.project_name}",
            f"resultados pruebas funcionales ambiente {daily_input.environment}",
            f"conclusiones recomendaciones informe técnico",
            f"avance proyecto estado tareas sprint",
        ]

        # Add domain-specific queries from content
        if daily_input.test_cases:
            failed = [t for t in daily_input.test_cases if t.status == "FAIL"]
            if failed:
                queries.append(f"descripción defectos encontrados {failed[0].module}")

        if daily_input.tasks:
            blocked = [t for t in daily_input.tasks if t.status == "BLOCKED"]
            if blocked:
                queries.append("bloqueos impedimentos plan acción")

        if daily_input.risks:
            queries.append("gestión riesgos plan mitigación proyecto")

        return queries

    @staticmethod
    def _classify_section(section_name: str) -> str:
        """Heuristic classification of section type from heading name."""
        name = section_name.lower()
        if any(k in name for k in ["resumen", "ejecutivo", "abstract"]):
            return "summary"
        if any(k in name for k in ["conclus", "hallazgo"]):
            return "conclusions"
        if any(k in name for k in ["intro", "objeto", "alcance"]):
            return "intro"
        return "body"
