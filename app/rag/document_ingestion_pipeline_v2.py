"""
document_ingestion_pipeline_v2.py — Pipeline de ingestión con clasificación automática.

Orquesta DocxReader, DocumentClassifier, StructuralChunker y las 4 colecciones
de ChromaDB para clasificar, chunkear e indexar documentos automáticamente.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.rag.collection_manager import initialize_collections, get_collection
from app.rag.docx_reader import DocxReader
from app.rag.document_classifier import DocumentClassifier
from app.rag.embedding_service import EmbeddingService
from app.rag.rag_schema import DocType, DocumentMetadata, get_collection_for_doc_type
from app.rag.structural_chunker import StructuralChunker
from app.rag.vector_store import VectorStore
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SUPPORTED_EXTENSIONS = {".py", ".ts", ".js", ".java", ".kt", ".md", ".txt", ".docx"}
_DUPLICATE_THRESHOLD = 0.98


@dataclass
class IngestResult:
    """Resultado de ingestar un archivo o nota."""
    source: str
    collection: str
    chunks_created: int
    doc_type: DocType
    is_duplicate: bool = False


class IngestionPipelineV2:
    """
    Pipeline v2 que clasifica, chunkea e indexa documentos en las
    4 colecciones separadas de ChromaDB.
    """

    def __init__(
        self,
        vector_store: VectorStore | None = None,
        classifier: DocumentClassifier | None = None,
        chunker: StructuralChunker | None = None,
        docx_reader: DocxReader | None = None,
        embedding_service: EmbeddingService | None = None,
        collections: dict | None = None,
    ):
        self._vs = vector_store or VectorStore()
        self._classifier = classifier or DocumentClassifier()
        self._chunker = chunker or StructuralChunker()
        self._docx_reader = docx_reader or DocxReader()
        self._emb = embedding_service or EmbeddingService()
        self._collections = collections or initialize_collections(self._vs)

    # ─────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────

    def ingest_file(self, file_path: str) -> IngestResult:
        """Ingest a single file: classify → chunk → embed → store."""
        path = Path(file_path)
        ext = path.suffix.lower()

        if ext not in _SUPPORTED_EXTENSIONS:
            logger.warning(f"Unsupported extension '{ext}': {path.name}")
            return IngestResult(
                source=path.name, collection="", chunks_created=0,
                doc_type=DocType.PROJECT_DOC,
            )

        # Read content
        if ext == ".docx":
            logger.info(f"Procesando Word: {path.name}")
            docx_content = self._docx_reader.read(str(path))
            content_for_classifier = docx_content
            text_for_chunking = docx_content.raw_text
        else:
            text = path.read_text(encoding="utf-8", errors="replace")
            content_for_classifier = text
            text_for_chunking = text

        # Classify
        metadata = self._classifier.classify_document(
            content_for_classifier, path.name
        )
        metadata.source_file = str(path)

        # Override priority for daily notes
        if self._classifier.is_daily_note(content_for_classifier, path.name):
            metadata.is_daily_note = True
            metadata.priority_score = 2.0
            metadata.doc_type = DocType.DAILY_NOTE

        # Determine target collection
        col_name = get_collection_for_doc_type(metadata.doc_type)

        # Check duplicate
        if self.check_duplicate(text_for_chunking, col_name.value):
            logger.debug(f"Duplicate detected, skipping: {path.name}")
            return IngestResult(
                source=path.name, collection=col_name.value,
                chunks_created=0, doc_type=metadata.doc_type,
                is_duplicate=True,
            )

        # Chunk
        chunks = self._chunker.chunk_document(text_for_chunking, metadata)

        # Embed and store
        if chunks:
            self._embed_and_store(chunks, col_name.value, path.name)

        logger.info(
            f"Ingested '{path.name}' → {col_name.value} "
            f"({len(chunks)} chunks, type={metadata.doc_type.value})"
        )
        return IngestResult(
            source=path.name,
            collection=col_name.value,
            chunks_created=len(chunks),
            doc_type=metadata.doc_type,
        )

    def ingest_directory(
        self, dir_path: str, recursive: bool = True
    ) -> list[IngestResult]:
        """Ingest all supported files from a directory."""
        directory = Path(dir_path)
        if not directory.exists():
            logger.warning(f"Directory not found: {dir_path}")
            return []

        pattern = "**/*" if recursive else "*"
        results: list[IngestResult] = []

        for file_path in sorted(directory.glob(pattern)):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in _SUPPORTED_EXTENSIONS:
                logger.debug(f"Ignoring unsupported file: {file_path.name}")
                continue
            try:
                result = self.ingest_file(str(file_path))
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to ingest {file_path.name}: {e}")

        total = sum(r.chunks_created for r in results)
        logger.info(
            f"Directory ingest complete: {len(results)} files, {total} total chunks"
        )
        return results

    def ingest_daily_note(
        self, content: str, date: str | None = None
    ) -> IngestResult:
        """Ingest a daily note directly (no file needed)."""
        if not date:
            date = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

        metadata = DocumentMetadata(
            doc_type=DocType.DAILY_NOTE,
            is_daily_note=True,
            note_date=date,
            priority_score=2.0,
            source_file=f"daily_note_{date}",
        )

        col_name = get_collection_for_doc_type(DocType.DAILY_NOTE)
        chunks = self._chunker.chunk_daily_note(content, metadata)

        if chunks:
            self._embed_and_store(chunks, col_name.value, f"note_{date}")

        return IngestResult(
            source=f"daily_note_{date}",
            collection=col_name.value,
            chunks_created=len(chunks),
            doc_type=DocType.DAILY_NOTE,
        )

    def check_duplicate(
        self, content: str, collection_name: str
    ) -> bool:
        """Check if very similar content already exists (cosine > 0.98)."""
        try:
            snippet = content[:500]
            embedding = self._emb.embed(snippet)
            results = self._vs.query(
                collection_name=collection_name,
                query_embedding=embedding,
                top_k=1,
            )
            if results and results[0].get("relevance_score", 0) > _DUPLICATE_THRESHOLD:
                return True
        except Exception:
            pass
        return False

    # ─────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────

    # Hard cap: ~6000 tokens ≈ 24 000 chars (4 chars/token avg)
    _MAX_EMBED_CHARS = 24_000

    def _embed_and_store(
        self, chunks: list[dict], collection_name: str, source_label: str
    ) -> None:
        """Generate embeddings and upsert chunks into ChromaDB."""
        # Truncate any oversized chunk content before embedding to avoid
        # the OpenAI 8192-token hard limit on embedding inputs.
        texts = [c["content"][: self._MAX_EMBED_CHARS] for c in chunks]
        embeddings = self._emb.embed_batch(texts)

        # Generate stable IDs
        store_chunks = []
        for i, chunk in enumerate(chunks):
            chunk_id = hashlib.md5(
                f"{source_label}_{i}_{chunk['content'][:80]}".encode()
            ).hexdigest()
            store_chunks.append({
                "id": chunk_id,
                "content": chunk["content"],
                "metadata": chunk["metadata"],
            })

        self._vs.add_chunks(
            collection_name=collection_name,
            chunks=store_chunks,
            embeddings=embeddings,
        )
