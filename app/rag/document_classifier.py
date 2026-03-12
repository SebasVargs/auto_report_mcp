"""
document_classifier.py — Clasificador automático de tipo de documento para RAG v2.

Determina el DocType de un documento basándose en su contenido y nombre
de archivo, produciendo DocumentMetadata completa para indexación.
"""

from __future__ import annotations

import re
from typing import Union

from app.rag.rag_schema import DocType, DocumentMetadata
from app.rag.docx_reader import DocxContent
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Patrones de clasificación ──────────────────────────────────

_UNIT_FILENAME   = re.compile(r"(unit|\.unit\.|_unit|unit_)", re.IGNORECASE)
_UNIT_CONTENT    = re.compile(
    r"\b(mock|stub|spy|patch|MagicMock|jest\.fn\(\)|vi\.fn\(\)|@patch|unittest)\b",
    re.IGNORECASE,
)
_UNIT_NEGATIVE   = re.compile(
    r"\b(database|http|api|integration|e2e|browser|selenium|playwright)\b",
    re.IGNORECASE,
)

_INT_FILENAME    = re.compile(r"(integration|\.int\.|_int|int_)", re.IGNORECASE)
_INT_CONTENT     = re.compile(
    r"\b(database|db\.|repository|http|axios|fetch|requests\.get|TestClient|supertest)\b",
    re.IGNORECASE,
)

_FUNC_FILENAME   = re.compile(r"(e2e|functional|feature|scenario)", re.IGNORECASE)
_FUNC_CONTENT    = re.compile(
    r"(browser|page\.|selenium|playwright|cypress|Scenario:|\"Given |\"When |\"Then )",
    re.IGNORECASE,
)

_IS_TEST_FILENAME = re.compile(r"(test|spec|_test\.|\.test\.|Test\.|Spec\.)", re.IGNORECASE)
_IS_TEST_CONTENT  = re.compile(
    r"(def test_|it\(\"|\bit\(\'|describe\(|@Test|\[Test\])", re.IGNORECASE,
)

_METHOD_DOC_PATTERNS = re.compile(
    r"(def \w+\(.*?\)\s*->|def \w+\(.*?\)\s*:|:param |:returns?:|@param |@return |Parameters|Returns|Args:)",
    re.MULTILINE | re.IGNORECASE,
)

_DOCSTRING_PATTERN = re.compile(r'"""[\s\S]*?"""', re.MULTILINE)

_DAILY_NOTE_DATE   = re.compile(r"\d{4}-\d{2}-\d{2}")
_DAILY_NOTE_WORDS  = re.compile(r"(daily|note|diario|nota)", re.IGNORECASE)
_DAILY_NOTE_HEADER = re.compile(r"^#\s*\d{4}-\d{2}-\d{2}")

# ── Detección de lenguaje ──────────────────────────────────────

_LANG_PATTERNS = {
    "python":     re.compile(r"(import \w+|from \w+ import|def \w+|class \w+.*:)", re.IGNORECASE),
    "typescript": re.compile(r"(import \{|export (class|function|interface|type)|: string|: number|: boolean)"),
    "javascript": re.compile(r"(const \w+|let \w+|var \w+|require\(|module\.exports)"),
    "java":       re.compile(r"(public class|private \w+|@Override|System\.out|import java\.)"),
    "kotlin":     re.compile(r"(fun \w+|val \w+|var \w+|class \w+|import kotlin\.)"),
}

_FRAMEWORK_PATTERNS = {
    "pytest":    re.compile(r"(def test_|@pytest|import pytest|pytest\.)", re.IGNORECASE),
    "unittest":  re.compile(r"(unittest\.TestCase|self\.assert)", re.IGNORECASE),
    "jest":      re.compile(r"(describe\(|it\(|expect\(|jest\.)", re.IGNORECASE),
    "vitest":    re.compile(r"(vi\.fn|vi\.mock|import.*vitest)", re.IGNORECASE),
    "junit":     re.compile(r"(@Test|import org\.junit|assertEquals)", re.IGNORECASE),
    "mocha":     re.compile(r"(describe\(|it\(|chai|assert\.)", re.IGNORECASE),
}

# Patrón para extraer componente desde el contenido
_COMPONENT_PATTERNS = [
    re.compile(r"(?:class|Clase|Módulo|Module)\s+(\w+)", re.IGNORECASE),
    re.compile(r"(\w+(?:Service|Repository|Controller|Manager|Handler|Factory|Provider|Adapter))", re.IGNORECASE),
]

_METHOD_NAME_PATTERNS = [
    re.compile(r"def\s+(\w+)\s*\("),
    re.compile(r"function\s+(\w+)\s*\("),
    re.compile(r"(?:public|private|protected)\s+\w+\s+(\w+)\s*\("),
]


class DocumentClassifier:
    """Clasifica documentos en DocTypes y produce DocumentMetadata."""

    # ─────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────

    def classify_test_type(
        self,
        content: Union[str, DocxContent],
        filename: str = "",
    ) -> DocType:
        """Clasifica el sub-tipo de test: UNIT, INTEGRATION o FUNCTIONAL."""
        text = self._get_text(content)

        scores = {
            DocType.UNIT_TEST:        0.0,
            DocType.INTEGRATION_TEST: 0.0,
            DocType.FUNCTIONAL_TEST:  0.0,
        }

        # Puntaje por filename
        if _UNIT_FILENAME.search(filename):
            scores[DocType.UNIT_TEST] += 0.5
        if _INT_FILENAME.search(filename):
            scores[DocType.INTEGRATION_TEST] += 0.5
        if _FUNC_FILENAME.search(filename):
            scores[DocType.FUNCTIONAL_TEST] += 0.5

        # Puntaje por contenido
        unit_hits = len(_UNIT_CONTENT.findall(text))
        if unit_hits:
            scores[DocType.UNIT_TEST] += min(unit_hits * 0.25, 0.6)
        if _UNIT_NEGATIVE.search(text):
            scores[DocType.UNIT_TEST] -= 0.3

        int_hits = len(_INT_CONTENT.findall(text))
        if int_hits:
            scores[DocType.INTEGRATION_TEST] += min(int_hits * 0.25, 0.6)

        func_hits = len(_FUNC_CONTENT.findall(text))
        if func_hits:
            scores[DocType.FUNCTIONAL_TEST] += min(func_hits * 0.25, 0.6)

        best_type = max(scores, key=scores.get)  # type: ignore
        best_score = scores[best_type]

        if best_score < 0.3:
            logger.warning(
                f"Low confidence ({best_score:.2f}) classifying test type for "
                f"'{filename}', defaulting to UNIT_TEST"
            )
            return DocType.UNIT_TEST

        return best_type

    def classify_document(
        self,
        content: Union[str, DocxContent],
        filename: str = "",
    ) -> DocumentMetadata:
        """Clasifica el documento completo y genera DocumentMetadata."""
        text = self._get_text(content)

        # Daily note check first
        is_note = self.is_daily_note(content, filename)
        if is_note:
            note_date = self._extract_date(filename, text)
            component = self._extract_component(content, text)
            return DocumentMetadata(
                doc_type=DocType.DAILY_NOTE,
                component=component,
                is_daily_note=True,
                note_date=note_date,
                source_file=filename,
                priority_score=2.0,
                language=self._detect_language(text),
            )

        # Test check
        is_test = bool(
            _IS_TEST_FILENAME.search(filename) or _IS_TEST_CONTENT.search(text)
        )
        if is_test:
            doc_type = self.classify_test_type(content, filename)
            test_type_str = {
                DocType.UNIT_TEST: "unit",
                DocType.INTEGRATION_TEST: "integration",
                DocType.FUNCTIONAL_TEST: "functional",
            }.get(doc_type, "unit")
            return DocumentMetadata(
                doc_type=doc_type,
                test_type=test_type_str,
                component=self._extract_component(content, text),
                method_name=self._extract_method_name(text),
                language=self._detect_language(text),
                framework=self._detect_framework(text),
                source_file=filename,
            )

        # Method doc check
        doc_count = len(_METHOD_DOC_PATTERNS.findall(text))
        docstring_count = len(_DOCSTRING_PATTERN.findall(text))
        doc_count += docstring_count
        if doc_count >= 3:
            return DocumentMetadata(
                doc_type=DocType.METHOD_DOC,
                component=self._extract_component(content, text),
                method_name=self._extract_method_name(text),
                language=self._detect_language(text),
                source_file=filename,
            )

        # Default: project doc
        return DocumentMetadata(
            doc_type=DocType.PROJECT_DOC,
            component=self._extract_component(content, text),
            language=self._detect_language(text),
            source_file=filename,
        )

    def is_daily_note(
        self,
        content: Union[str, DocxContent],
        filename: str = "",
    ) -> bool:
        """Detecta si el documento es una nota diaria."""
        text = self._get_text(content)

        if _DAILY_NOTE_WORDS.search(filename) and _DAILY_NOTE_DATE.search(filename):
            return True
        if _DAILY_NOTE_WORDS.search(filename):
            return True
        if _DAILY_NOTE_HEADER.search(text):
            return True
        return False

    # ─────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────

    @staticmethod
    def _get_text(content: Union[str, DocxContent]) -> str:
        if isinstance(content, DocxContent):
            return content.raw_text
        return content

    @staticmethod
    def _extract_component(
        content: Union[str, DocxContent], text: str
    ) -> str:
        # DocxContent tiene hints
        if isinstance(content, DocxContent):
            hint = content.metadata_hints.get("possible_component", "")
            if hint:
                return hint

        for pattern in _COMPONENT_PATTERNS:
            match = pattern.search(text)
            if match:
                return match.group(1)
        return ""

    @staticmethod
    def _extract_method_name(text: str) -> str:
        for pattern in _METHOD_NAME_PATTERNS:
            match = pattern.search(text)
            if match:
                name = match.group(1)
                if name not in {"test", "setUp", "tearDown", "setup", "teardown"}:
                    return name
        return ""

    @staticmethod
    def _detect_language(text: str) -> str:
        best = ""
        best_count = 0
        for lang, pattern in _LANG_PATTERNS.items():
            count = len(pattern.findall(text))
            if count > best_count:
                best = lang
                best_count = count
        return best

    @staticmethod
    def _detect_framework(text: str) -> str:
        best = ""
        best_count = 0
        for fw, pattern in _FRAMEWORK_PATTERNS.items():
            count = len(pattern.findall(text))
            if count > best_count:
                best = fw
                best_count = count
        return best

    @staticmethod
    def _extract_date(filename: str, text: str) -> str:
        match = _DAILY_NOTE_DATE.search(filename)
        if match:
            return match.group(0)
        match = _DAILY_NOTE_DATE.search(text)
        if match:
            return match.group(0)
        return ""
