"""
structural_chunker.py — Chunking estructural por unidad lógica para RAG v2.

La unidad mínima de chunk es la unidad lógica del código (un test completo,
un método completo), nunca un conteo arbitrario de tokens.
"""

from __future__ import annotations

import re
from dataclasses import asdict

from app.rag.rag_schema import DocType, DocumentMetadata
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Delimitadores de tests por lenguaje ─────────────────────────

_PY_TEST_SPLIT   = re.compile(r"(?=\ndef test_|\nclass Test|\n    def test_)")
_JS_TEST_SPLIT   = re.compile(r"(?=\s*(?:it|test)\s*\()")
_JAVA_TEST_SPLIT = re.compile(r"(?=\s*@Test)")

# ── Detección de secciones arrange/act/assert ───────────────────

_ARRANGE_MARKERS = re.compile(r"(# Arrange|// Arrange|// Given|# Given|# Setup)", re.IGNORECASE)
_ACT_MARKERS     = re.compile(r"(# Act|// Act|// When|# When)", re.IGNORECASE)

# ── Detección de métodos documentados ───────────────────────────

_METHOD_SPLIT_PY   = re.compile(r"(?=\n(?:    )?def \w+\s*\()")
_METHOD_SPLIT_JS   = re.compile(r"(?=\n\s*(?:async\s+)?(?:function\s+\w+|(?:public|private|protected|static)\s+))")
_METHOD_SPLIT_JAVA = re.compile(r"(?=\n\s*(?:public|private|protected)\s+)")

# Signature detection
_HAS_SIGNATURE = re.compile(
    r"(def \w+\(.*?\)\s*(?:->|:)|function \w+\(|(?:public|private|protected)\s+\w+\s+\w+\()",
    re.DOTALL,
)

# ── Constantes ──────────────────────────────────────────────────

_MAX_TEST_TOKENS    = 800
_MAX_METHOD_TOKENS  = 1200
_PROJECT_CHUNK_SIZE = 400   # conservative: leaves headroom vs 8192-token embed limit
_PROJECT_OVERLAP    = 60
_MAX_NOTE_TOKENS    = 1200

# Hard safety cap: ~6000 tokens in chars (~4 chars/token). We never embed more.
_MAX_EMBED_CHARS    = 24_000


def _token_count(text: str) -> int:
    """Aproximación rápida: 1 token ≈ 0.75 palabras."""
    return int(len(text.split()) * 4 / 3)


class StructuralChunker:
    """Chunking estructural que respeta unidades lógicas de código."""

    # ─────────────────────────────────────────────────
    # Router principal
    # ─────────────────────────────────────────────────

    def chunk_document(
        self, content: str, metadata: DocumentMetadata
    ) -> list[dict]:
        """Enruta al método de chunking correcto según doc_type."""
        handlers = {
            DocType.UNIT_TEST:        self.chunk_test_file,
            DocType.INTEGRATION_TEST: self.chunk_test_file,
            DocType.FUNCTIONAL_TEST:  self.chunk_test_file,
            DocType.METHOD_DOC:       self.chunk_method_doc,
            DocType.PROJECT_DOC:      self.chunk_project_doc,
            DocType.DAILY_NOTE:       self.chunk_daily_note,
        }
        handler = handlers.get(metadata.doc_type, self.chunk_project_doc)
        chunks = handler(content, metadata)
        logger.debug(
            f"Chunked {metadata.source_file} ({metadata.doc_type.value}) "
            f"→ {len(chunks)} chunk(s)"
        )
        return chunks

    # ─────────────────────────────────────────────────
    # Test files
    # ─────────────────────────────────────────────────

    def chunk_test_file(
        self, content: str, metadata: DocumentMetadata
    ) -> list[dict]:
        """Un test completo = un chunk. Nunca corta dentro de un assert."""
        lang = metadata.language.lower()

        if lang in ("python", ""):
            splitter = _PY_TEST_SPLIT
        elif lang in ("java", "kotlin"):
            splitter = _JAVA_TEST_SPLIT
        else:
            splitter = _JS_TEST_SPLIT

        raw_parts = splitter.split(content)
        # Re-join preamble (imports, fixtures) with first test
        parts: list[str] = []
        preamble = ""
        for part in raw_parts:
            stripped = part.strip()
            if not stripped:
                continue
            if not parts and not self._looks_like_test(stripped, lang):
                preamble = stripped + "\n\n"
            else:
                parts.append(part.strip())

        chunks: list[dict] = []
        for idx, part in enumerate(parts):
            test_name = self._extract_test_name(part, lang)
            text = (preamble + part) if idx == 0 and preamble else part

            if _token_count(text) > _MAX_TEST_TOKENS:
                sub_chunks = self._split_test_by_sections(text, test_name)
                for sub_idx, (sub_text, chunk_type) in enumerate(sub_chunks):
                    chunks.append(self._build_chunk(
                        content=sub_text,
                        metadata=metadata,
                        chunk_index=len(chunks),
                        extra={
                            "chunk_type": chunk_type,
                            "test_name": test_name,
                        },
                    ))
            else:
                chunks.append(self._build_chunk(
                    content=text,
                    metadata=metadata,
                    chunk_index=len(chunks),
                    extra={
                        "chunk_type": "full_test",
                        "test_name": test_name,
                    },
                ))

        if not chunks and content.strip():
            chunks.append(self._build_chunk(
                content=content.strip(),
                metadata=metadata,
                chunk_index=0,
                extra={"chunk_type": "full_test", "test_name": ""},
            ))

        return chunks

    # ─────────────────────────────────────────────────
    # Method documentation
    # ─────────────────────────────────────────────────

    def chunk_method_doc(
        self, content: str, metadata: DocumentMetadata
    ) -> list[dict]:
        """Un método = un chunk. Nunca corta dentro de una firma."""
        # Try heading-based split first (for DocxContent-style text)
        heading_chunks = self._split_by_headings(content, level=2)

        if len(heading_chunks) > 1:
            parts = heading_chunks
        else:
            lang = metadata.language.lower()
            if lang in ("python", ""):
                splitter = _METHOD_SPLIT_PY
            elif lang in ("java", "kotlin"):
                splitter = _METHOD_SPLIT_JAVA
            else:
                splitter = _METHOD_SPLIT_JS
            parts = [p.strip() for p in splitter.split(content) if p.strip()]

        chunks: list[dict] = []
        for part in parts:
            has_sig = bool(_HAS_SIGNATURE.search(part))
            extra = {"has_incomplete_signature": not has_sig}

            if _token_count(part) > _MAX_METHOD_TOKENS:
                sub_parts = self._split_by_headings(part, level=3)
                if len(sub_parts) <= 1:
                    sub_parts = self._split_by_paragraphs(
                        part, _MAX_METHOD_TOKENS
                    )
                for sp in sub_parts:
                    chunks.append(self._build_chunk(
                        content=sp,
                        metadata=metadata,
                        chunk_index=len(chunks),
                        extra=extra,
                    ))
            else:
                chunks.append(self._build_chunk(
                    content=part,
                    metadata=metadata,
                    chunk_index=len(chunks),
                    extra=extra,
                ))

        return chunks or [self._build_chunk(
            content=content.strip(),
            metadata=metadata,
            chunk_index=0,
            extra={"has_incomplete_signature": True},
        )]

    # ─────────────────────────────────────────────────
    # Project docs
    # ─────────────────────────────────────────────────

    def chunk_project_doc(
        self, content: str, metadata: DocumentMetadata
    ) -> list[dict]:
        """Sliding window respetando párrafos completos.

        Garantiza que ningún chunk exceda _PROJECT_CHUNK_SIZE tokens.
        Si un párrafo individual ya excede el límite (ej. un docx sin saltos
        de línea), se divide por palabras en sub-párrafos.
        """
        raw_paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        if not raw_paragraphs:
            raw_paragraphs = [content.strip()] if content.strip() else []

        # ── Aplanar párrafos gigantes ──────────────────────────────────
        # Si un párrafo individual supera el tamaño objetivo, lo fragmentamos
        # en sub-párrafos de palabras para evitar superar el límite de tokens.
        paragraphs: list[str] = []
        for para in raw_paragraphs:
            if _token_count(para) > _PROJECT_CHUNK_SIZE:
                words = para.split()
                chunk_words = int(_PROJECT_CHUNK_SIZE * 0.75)  # tokens → words
                for i in range(0, len(words), chunk_words):
                    sub = " ".join(words[i : i + chunk_words])
                    if sub.strip():
                        paragraphs.append(sub)
            else:
                paragraphs.append(para)

        chunks: list[dict] = []
        current_parts: list[str] = []
        current_tokens = 0

        for para in paragraphs:
            para_tokens = _token_count(para)

            if current_tokens + para_tokens > _PROJECT_CHUNK_SIZE and current_parts:
                chunk_text = "\n\n".join(current_parts)
                chunks.append(self._build_chunk(
                    content=chunk_text,
                    metadata=metadata,
                    chunk_index=len(chunks),
                ))
                # Overlap: keep last parts up to _PROJECT_OVERLAP tokens
                overlap_parts: list[str] = []
                overlap_tokens = 0
                for p in reversed(current_parts):
                    pt = _token_count(p)
                    if overlap_tokens + pt > _PROJECT_OVERLAP:
                        break
                    overlap_parts.insert(0, p)
                    overlap_tokens += pt
                current_parts = overlap_parts
                current_tokens = overlap_tokens

            current_parts.append(para)
            current_tokens += para_tokens

        if current_parts:
            chunk_text = "\n\n".join(current_parts)
            chunks.append(self._build_chunk(
                content=chunk_text,
                metadata=metadata,
                chunk_index=len(chunks),
            ))

        return chunks

    # ─────────────────────────────────────────────────
    # Daily notes
    # ─────────────────────────────────────────────────

    def chunk_daily_note(
        self, content: str, metadata: DocumentMetadata
    ) -> list[dict]:
        """Una nota = un chunk. Si >1200 tokens, divide por headers ##."""
        if _token_count(content) <= _MAX_NOTE_TOKENS:
            return [self._build_chunk(
                content=content.strip(),
                metadata=metadata,
                chunk_index=0,
            )]

        sections = self._split_by_headings(content, level=2)
        chunks: list[dict] = []
        for section in sections:
            chunks.append(self._build_chunk(
                content=section,
                metadata=metadata,
                chunk_index=len(chunks),
            ))
        return chunks

    # ─────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────

    @staticmethod
    def _build_chunk(
        content: str,
        metadata: DocumentMetadata,
        chunk_index: int,
        extra: dict | None = None,
    ) -> dict:
        meta_dict = metadata.to_chroma_dict()
        meta_dict["chunk_index"] = chunk_index
        if extra:
            meta_dict.update(extra)
        return {
            "content": content,
            "metadata": meta_dict,
        }

    @staticmethod
    def _looks_like_test(text: str, lang: str) -> bool:
        if lang in ("python", ""):
            return bool(re.match(r"(def test_|class Test)", text))
        if lang in ("java", "kotlin"):
            return "@Test" in text
        return bool(re.match(r"\s*(it|test|describe)\s*\(", text))

    @staticmethod
    def _extract_test_name(text: str, lang: str) -> str:
        if lang in ("python", ""):
            m = re.search(r"def (test_\w+)", text)
            return m.group(1) if m else ""
        if lang in ("java", "kotlin"):
            m = re.search(r"void\s+(\w+)\s*\(", text)
            return m.group(1) if m else ""
        m = re.search(r"(?:it|test)\s*\(\s*['\"](.+?)['\"]", text)
        return m.group(1) if m else ""

    @staticmethod
    def _split_test_by_sections(
        text: str, test_name: str
    ) -> list[tuple[str, str]]:
        """Split large test into arrange/assert sections."""
        act_match = _ACT_MARKERS.search(text)
        if act_match:
            arrange = text[: act_match.start()].strip()
            act_assert = text[act_match.start() :].strip()
            return [
                (arrange, "test_arrange"),
                (act_assert, "test_assert"),
            ]
        # Fallback: split in half by lines
        lines = text.split("\n")
        mid = len(lines) // 2
        return [
            ("\n".join(lines[:mid]), "test_arrange"),
            ("\n".join(lines[mid:]), "test_assert"),
        ]

    @staticmethod
    def _split_by_headings(text: str, level: int = 2) -> list[str]:
        pattern = re.compile(rf"(?=^{'#' * level}\s)", re.MULTILINE)
        parts = pattern.split(text)
        return [p.strip() for p in parts if p.strip()]

    @staticmethod
    def _split_by_paragraphs(text: str, max_tokens: int) -> list[str]:
        paragraphs = text.split("\n\n")
        chunks: list[str] = []
        current: list[str] = []
        current_tokens = 0
        for para in paragraphs:
            pt = _token_count(para)
            if current_tokens + pt > max_tokens and current:
                chunks.append("\n\n".join(current))
                current = []
                current_tokens = 0
            current.append(para)
            current_tokens += pt
        if current:
            chunks.append("\n\n".join(current))
        return chunks
