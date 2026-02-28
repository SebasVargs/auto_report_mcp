from __future__ import annotations

import re
import unicodedata


class TextCleaner:
    """Cleans and normalizes text for RAG ingestion."""

    def clean(self, text: str) -> str:
        text = self._normalize_unicode(text)
        text = self._remove_control_characters(text)
        text = self._collapse_whitespace(text)
        text = self._remove_page_numbers(text)
        return text.strip()

    @staticmethod
    def _normalize_unicode(text: str) -> str:
        return unicodedata.normalize("NFKC", text)

    @staticmethod
    def _remove_control_characters(text: str) -> str:
        return "".join(ch for ch in text if unicodedata.category(ch)[0] != "C" or ch in "\n\t")

    @staticmethod
    def _collapse_whitespace(text: str) -> str:
        text = re.sub(r"\t", " ", text)
        text = re.sub(r" {2,}", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text

    @staticmethod
    def _remove_page_numbers(text: str) -> str:
        # Remove standalone page numbers like "- 12 -" or "Página 3 de 20"
        text = re.sub(r"[-–]\s*\d+\s*[-–]", "", text)
        text = re.sub(r"[Pp]ágina\s+\d+\s+de\s+\d+", "", text)
        return text
