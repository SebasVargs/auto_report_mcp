from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import docx

from app.config import get_settings
from app.rag.embedding_service import EmbeddingService
from app.rag.vector_store import VectorStore
from app.utils.logger import get_logger
from app.utils.text_cleaner import TextCleaner

logger = get_logger(__name__)
settings = get_settings()


class DocumentIngestionPipeline:
    """
    Orchestrates the full ingestion flow:
    1. Discover .docx files in raw_reports/
    2. Extract text by sections
    3. Chunk intelligently (respect sentence boundaries)
    4. Embed with OpenAI
    5. Persist in ChromaDB with metadata
    6. Track ingested files to avoid duplicates
    """

    INGESTION_REGISTRY = Path(settings.processed_chunks_dir) / ".ingestion_registry.json"

    def __init__(self):
        self.embedding_service = EmbeddingService()
        self.vector_store = VectorStore()
        self.text_cleaner = TextCleaner()
        self._registry: dict[str, str] = self._load_registry()

    # ─────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────

    def ingest_all(self) -> dict[str, int]:
        """Scan raw_reports/ and ingest all new .docx. Returns { filename: chunks_added }."""
        return self.ingest_from_dir(Path(settings.raw_reports_dir))

    def ingest_from_dir(self, directory: Path) -> dict[str, int]:
        """
        Scan any directory for .docx files and ingest new ones into report_style_chunks.
        Skips files already in the registry (based on content hash).
        Returns { filename: chunks_added }.
        """

        docx_files = list(directory.glob("**/*.docx"))
        logger.info(f"Found {len(docx_files)} .docx files in {directory}")

        results = {}
        for docx_path in docx_files:
            file_hash = self._hash_file(docx_path)
            registry_key = f"style:{docx_path.name}"  # prefix to not conflict with knowledge registry
            if self._already_ingested(registry_key, file_hash):
                logger.debug(f"⏭  Skipping style ingest (already done): {docx_path.name}")
                continue
            try:
                chunks_added = self._ingest_file(docx_path)
                self._mark_ingested(registry_key, file_hash)
                results[docx_path.name] = chunks_added
                logger.info(f"✅ Style-ingested '{docx_path.name}' → {chunks_added} chunks")
            except Exception as e:
                logger.error(f"❌ Failed to style-ingest {docx_path.name}: {e}", exc_info=True)

        self._save_registry()
        return results

    def ingest_file(self, path: Path) -> int:
        """Force-ingest a single file (ignores registry)."""
        return self._ingest_file(path)

    # ─────────────────────────────────────────────────
    # Core ingestion logic
    # ─────────────────────────────────────────────────

    def _ingest_file(self, path: Path) -> int:
        """Extract → clean → chunk → embed → store."""
        sections = self._extract_sections(path)
        all_chunks = []

        for section_title, section_text in sections.items():
            clean_text = self.text_cleaner.clean(section_text)
            if not clean_text.strip():
                continue
            chunks = self._chunk_text(clean_text, path.stem, section_title)
            all_chunks.extend(chunks)

        if not all_chunks:
            logger.warning(f"No content extracted from {path.name}")
            return 0

        # Batch embed for efficiency
        texts = [c["content"] for c in all_chunks]
        embeddings = self.embedding_service.embed_batch(texts)

        self.vector_store.add_chunks(
            collection_name=settings.chroma_collection_style,
            chunks=all_chunks,
            embeddings=embeddings,
        )
        return len(all_chunks)

    def _extract_sections(self, path: Path) -> dict[str, str]:
        """
        Parse .docx extracting both paragraphs and table content (table-aware XML extractor).
        Mirrors KnowledgeIngestionPipeline._extract_sections for consistency.
        """
        doc = docx.Document(str(path))
        sections: dict[str, list[str]] = {"__intro__": []}
        current = "__intro__"
        table_idx = 0

        from docx.oxml.ns import qn as _qn
        body = doc.element.body

        for child in body.iterchildren():
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

            if tag == "p":
                para_text = "".join(r.text or "" for r in child.iter(_qn("w:t"))).strip()
                if not para_text:
                    continue
                pPr = child.find(_qn("w:pPr"))
                style_val = ""
                if pPr is not None:
                    pStyle = pPr.find(_qn("w:pStyle"))
                    if pStyle is not None:
                        style_val = pStyle.get(_qn("w:val"), "").lower()
                is_heading = (
                    "heading" in style_val
                    or "título" in style_val
                    or "encabezado" in style_val
                )
                if not is_heading:
                    runs = list(child.iter(_qn("w:r")))
                    if runs:
                        rPr = runs[0].find(_qn("w:rPr"))
                        if rPr is not None and rPr.find(_qn("w:b")) is not None:
                            if len(para_text) < 100:
                                is_heading = True
                if is_heading:
                    current = para_text
                    sections.setdefault(current, [])
                else:
                    sections.setdefault(current, []).append(para_text)

            elif tag == "tbl":
                table_idx += 1
                rows_text: list[str] = []
                seen_cells: set[str] = set()
                for row in child.iter(_qn("w:tr")):
                    cell_texts: list[str] = []
                    for cell in row.iter(_qn("w:tc")):
                        cell_content = "".join(
                            t.text or "" for t in cell.iter(_qn("w:t"))
                        ).strip()
                        if cell_content and cell_content not in seen_cells:
                            cell_texts.append(cell_content)
                            seen_cells.add(cell_content)
                    if cell_texts:
                        rows_text.append(" | ".join(cell_texts))
                if rows_text:
                    section_name = rows_text[0] if len(rows_text[0]) <= 80 else f"tabla_{table_idx}"
                    body_text = " ".join(rows_text[1:]) if len(rows_text) > 1 else rows_text[0]
                    sections.setdefault(section_name, []).append(body_text)

        return {k: " ".join(v) for k, v in sections.items() if v}

    def _chunk_text(
        self, text: str, source: str, section: str
    ) -> list[dict]:
        """
        Sentence-aware chunking.
        Respects chunk_size and overlap from config.
        """
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks = []
        current = []
        current_len = 0
        chunk_size = settings.rag_chunk_size
        overlap = settings.rag_chunk_overlap

        for sentence in sentences:
            sentence_len = len(sentence.split())
            if current_len + sentence_len > chunk_size and current:
                chunk_text = " ".join(current)
                chunks.append(
                    self._build_chunk_record(chunk_text, source, section, len(chunks))
                )
                # Overlap: keep last N words
                overlap_words = " ".join(current).split()[-overlap:]
                current = overlap_words
                current_len = len(overlap_words)

            current.append(sentence)
            current_len += sentence_len

        if current:
            chunk_text = " ".join(current)
            chunks.append(
                self._build_chunk_record(chunk_text, source, section, len(chunks))
            )

        return chunks

    @staticmethod
    def _build_chunk_record(
        content: str, source: str, section: str, index: int
    ) -> dict:
        chunk_id = hashlib.md5(f"{source}_{section}_{index}_{content[:50]}".encode()).hexdigest()
        return {
            "id": chunk_id,
            "content": content,
            "metadata": {
                "source_document": source,
                "section": section,
                "chunk_index": index,
                "word_count": len(content.split()),
            },
        }

    # ─────────────────────────────────────────────────
    # Registry helpers
    # ─────────────────────────────────────────────────

    def _load_registry(self) -> dict[str, str]:
        self.INGESTION_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
        if self.INGESTION_REGISTRY.exists():
            return json.loads(self.INGESTION_REGISTRY.read_text())
        return {}

    def _save_registry(self) -> None:
        self.INGESTION_REGISTRY.write_text(json.dumps(self._registry, indent=2))

    def _already_ingested(self, filename: str, file_hash: str) -> bool:
        return self._registry.get(filename) == file_hash

    def _mark_ingested(self, filename: str, file_hash: str) -> None:
        self._registry[filename] = file_hash

    @staticmethod
    def _hash_file(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()
