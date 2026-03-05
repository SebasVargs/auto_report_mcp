from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.rag.embedding_service import EmbeddingService
from app.rag.vector_store import VectorStore
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

_REGISTRY_PATH = Path("./data/knowledge_processed.json")
_CHUNK_WORDS   = 150   # smaller chunks keep method names + context together
_CHUNK_OVERLAP = 30


class KnowledgeIngestionPipeline:
    """
    Ingests two types of sources into the `project_knowledge` ChromaDB collection:
    - Free-text notes written by the user  → ingest_text_note()
    - .docx context reports in context_reports/ → ingest_all_context_reports()

    Already-processed files are tracked via a local JSON registry so they are
    never ingested twice.

    Metadata strategy (Recency Weighting):
    - Every chunk carries a `timestamp` (ISO-8601) and a `type` field.
      type="note"           → manual user note  (highest priority at retrieval time)
      type="context_report" → auto-generated .docx report
    - Each chunk is prefixed with a dated tag so the LLM reads the recency signal
      inline before extracting information.
    """

    def __init__(self) -> None:
        self._vs         = VectorStore()
        self._emb        = EmbeddingService()
        self._collection = settings.chroma_collection_knowledge

    # ─────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────

    def ingest_text_note(self, note: str) -> int:
        """
        Chunk, embed and store a free-text note in the knowledge collection.
        Each chunk is prefixed with [NOTA DEL USUARIO - <datetime>] so the LLM
        reads the recency signal before processing content.
        Returns the number of chunks stored.
        """
        if not note.strip():
            return 0

        now       = datetime.now(tz=timezone.utc)
        now_iso   = now.isoformat()
        now_label = now.strftime("%Y-%m-%d %H:%M UTC")

        chunks = self._chunk_text(note)
        all_chunks: list[dict] = []
        for chunk in chunks:
            dated_chunk = f"[NOTA DEL USUARIO - {now_label}]\n{chunk}"
            chunk_id    = f"note_{hashlib.md5(dated_chunk.encode()).hexdigest()}"
            
            all_chunks.append({
                "id": chunk_id,
                "content": dated_chunk,
                "metadata": {
                    "source":    "user_note",
                    "type":      "note",
                    "timestamp": now_iso,
                }
            })

        if all_chunks:
            texts = [c["content"] for c in all_chunks]
            embeddings = self._emb.embed_batch(texts)
            self._vs.add_chunks(
                collection_name=self._collection,
                chunks=all_chunks,
                embeddings=embeddings,
            )

        logger.info(
            f"Ingested user note ({now_label}) → {len(chunks)} chunk(s) "
            f"into '{self._collection}'"
        )
        return len(chunks)

    def find_similar_notes(self, text: str, threshold: float = 0.5) -> list[dict]:
        """
        Embed ``text`` and search the knowledge collection for existing note
        chunks (type="note") with a relevance_score >= threshold.

        Returns a list of matching chunk dicts (id, content, metadata,
        relevance_score), sorted by relevance descending.
        Only notes are searched — context_report chunks are excluded.
        """
        if not text.strip():
            return []

        query_embedding = self._emb.embed_batch([text])[0]
        results = self._vs.query(
            collection_name=self._collection,
            query_embedding=query_embedding,
            top_k=5,
            where={"type": "note"},
        )
        similar = [r for r in results if r["relevance_score"] >= threshold]
        logger.debug(
            f"find_similar_notes: {len(similar)} match(es) above threshold {threshold}"
        )
        return similar

    def delete_notes(self, note_ids: list[str]) -> None:
        """
        Remove specific note chunks from the knowledge collection by their IDs.
        Called during smart consolidation after the user confirms a merge.
        """
        if not note_ids:
            return
        self._vs.delete_chunks(
            collection_name=self._collection,
            ids=note_ids,
        )
        logger.info(f"Deleted {len(note_ids)} note chunk(s) from '{self._collection}'")

    def ingest_all_context_reports(self, force: bool = False) -> dict[str, int]:
        """
        Scan context_reports/ for .docx files not yet in the registry.
        Each chunk is prefixed with [REPORTE: <filename> - <date>] using the
        file's modification date so relative recency is visible to the LLM.
        Returns {filename: chunk_count} for newly ingested files.

        Args:
            force: If True, skip the registry check and always re-ingest every file.
        """
        context_dir = Path(settings.context_reports_dir)
        if not context_dir.exists():
            logger.warning(f"context_reports dir not found: {context_dir}")
            return {}

        registry = self._load_registry()
        results: dict[str, int] = {}

        for docx_path in sorted(context_dir.glob("*.docx")):
            file_hash = self._file_hash(docx_path)
            if not force and file_hash in registry:
                logger.debug(f"Skipping already-ingested: {docx_path.name}")
                continue

            mtime       = datetime.fromtimestamp(docx_path.stat().st_mtime, tz=timezone.utc)
            mtime_iso   = mtime.isoformat()
            mtime_label = mtime.strftime("%Y-%m-%d")

            text = self._extract_docx_text(docx_path)
            if not text.strip():
                logger.warning(f"Empty text from {docx_path.name}, skipping.")
                continue

            chunks = self._chunk_text(text)
            all_chunks: list[dict] = []
            for idx, chunk in enumerate(chunks):
                dated_chunk = f"[REPORTE: {docx_path.name} - {mtime_label}]\n{chunk}"
                # ID = file hash prefix + chunk index → unique per file, no content collisions
                chunk_id    = f"report_{file_hash[:16]}_{idx:04d}"

                all_chunks.append({
                    "id": chunk_id,
                    "content": dated_chunk,
                    "metadata": {
                        "source":    docx_path.name,
                        "type":      "context_report",
                        "timestamp": mtime_iso,
                    }
                })


            if all_chunks:
                texts = [c["content"] for c in all_chunks]
                embeddings = self._emb.embed_batch(texts)
                self._vs.add_chunks(
                    collection_name=self._collection,
                    chunks=all_chunks,
                    embeddings=embeddings,
                )

            registry[file_hash] = docx_path.name
            results[docx_path.name] = len(chunks)
            logger.info(f"Ingested '{docx_path.name}' ({mtime_label}) → {len(chunks)} chunk(s)")

        self._save_registry(registry)
        return results

    def force_reingest_file(self, docx_path: Path) -> int:
        """
        Remove the registry entry for a specific .docx file and re-ingest it.
        Useful when a file was downloaded but ChromaDB never received its chunks,
        or after manually updating the file.
        Returns the number of new chunks stored.
        """
        registry  = self._load_registry()
        file_hash = self._file_hash(docx_path)
        removed   = registry.pop(file_hash, None)
        if removed:
            logger.info(f"Cleared registry entry for '{docx_path.name}' (hash: {file_hash[:8]}…)")
        self._save_registry(registry)
        # Now ingest normally — it will no longer be skipped
        result = self.ingest_all_context_reports()
        return result.get(docx_path.name, 0)

    # ─────────────────────────────────────────────────
    # Text extraction
    # ─────────────────────────────────────────────────

    @staticmethod
    def _extract_docx_text(path: Path) -> str:
        try:
            from docx import Document
            doc        = Document(str(path))
            paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        if cell.text.strip():
                            paragraphs.append(cell.text.strip())
            return "\n\n".join(paragraphs)
        except Exception as e:
            logger.error(f"Failed to extract text from {path.name}: {e}")
            return ""

    # ─────────────────────────────────────────────────
    # Chunking
    # ─────────────────────────────────────────────────

    @staticmethod
    def _chunk_text(
        text: str,
        chunk_words: int = _CHUNK_WORDS,
        overlap_words: int = _CHUNK_OVERLAP,
    ) -> list[str]:
        words  = text.split()
        chunks = []
        i      = 0
        while i < len(words):
            chunk = " ".join(words[i : i + chunk_words])
            if chunk.strip():
                chunks.append(chunk)
            i += chunk_words - overlap_words
        return chunks

    # ─────────────────────────────────────────────────
    # Registry helpers
    # ─────────────────────────────────────────────────

    @staticmethod
    def _file_hash(path: Path) -> str:
        return hashlib.md5(path.read_bytes()).hexdigest()

    @staticmethod
    def _load_registry() -> dict:
        if _REGISTRY_PATH.exists():
            try:
                return json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
        return {}

    @staticmethod
    def _save_registry(registry: dict) -> None:
        _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        _REGISTRY_PATH.write_text(
            json.dumps(registry, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )