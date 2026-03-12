"""
rag_schema.py — Esquema de metadata y constantes para el RAG v2.

Define los tipos de documento, colecciones de ChromaDB,
el mapeo entre ambos, y la estructura de metadata por chunk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# ── Tipos de documento ───────────────────────────────────────────

class DocType(str, Enum):
    """Tipo semántico de cada documento indexado."""
    UNIT_TEST        = "unit_test"
    INTEGRATION_TEST = "integration_test"
    FUNCTIONAL_TEST  = "functional_test"
    METHOD_DOC       = "method_doc"
    PROJECT_DOC      = "project_doc"
    DAILY_NOTE       = "daily_note"


# ── Colecciones de ChromaDB ──────────────────────────────────────

class CollectionName(str, Enum):
    """Nombre de cada colección de ChromaDB."""
    UNIT_TESTS        = "unit_tests"
    INTEGRATION_TESTS = "integration_tests"
    FUNCTIONAL_TESTS  = "functional_tests"
    PROJECT_DOCS      = "project_docs"


# ── Mapeo DocType → CollectionName ───────────────────────────────

_DOC_TYPE_TO_COLLECTION: dict[DocType, CollectionName] = {
    DocType.UNIT_TEST:        CollectionName.UNIT_TESTS,
    DocType.INTEGRATION_TEST: CollectionName.INTEGRATION_TESTS,
    DocType.FUNCTIONAL_TEST:  CollectionName.FUNCTIONAL_TESTS,
    DocType.METHOD_DOC:       CollectionName.PROJECT_DOCS,
    DocType.PROJECT_DOC:      CollectionName.PROJECT_DOCS,
    DocType.DAILY_NOTE:       CollectionName.PROJECT_DOCS,
}


def get_collection_for_doc_type(doc_type: DocType) -> CollectionName:
    """Retorna la colección de ChromaDB correspondiente a un DocType.

    Raises:
        ValueError: Si el DocType no tiene un mapeo definido.
    """
    try:
        return _DOC_TYPE_TO_COLLECTION[doc_type]
    except KeyError:
        raise ValueError(f"DocType no soportado: {doc_type!r}")


# ── Metadata por chunk ──────────────────────────────────────────

@dataclass
class DocumentMetadata:
    """Metadata estructurada que acompaña a cada chunk almacenado en ChromaDB.

    Args:
        doc_type:       Tipo semántico del documento fuente.
        test_type:      Sub-tipo de test ("unit" | "integration" | "functional").
                        Solo se usa cuando doc_type es un tipo de test; de lo
                        contrario dejarlo vacío.
        component:      Nombre de la clase o módulo al que pertenece el chunk
                        (ej. "UserService").
        method_name:    Método específico que describe el chunk, si aplica.
        language:       Lenguaje de programación del código fuente
                        (ej. "python", "typescript").
        framework:      Framework de testing detectado
                        (ej. "pytest", "jest", "junit").
        is_daily_note:  True si el chunk proviene de una nota diaria.
        note_date:      Fecha ISO de la nota diaria (ej. "2024-01-15").
        source_file:    Ruta del archivo original que se indexó.
        priority_score: Peso de prioridad. 1.0 por defecto; 2.0 para notas
                        diarias (daily notes).
    """

    doc_type:       DocType
    test_type:      str   = ""
    component:      str   = ""
    method_name:    str   = ""
    language:       str   = ""
    framework:      str   = ""
    is_daily_note:  bool  = False
    note_date:      str   = ""
    source_file:    str   = ""
    priority_score: float = 1.0

    def to_chroma_dict(self) -> dict:
        """Convierte la metadata a un dict plano compatible con ChromaDB.

        ChromaDB solo acepta str, int, float y bool como valores de metadata.
        """
        return {
            "doc_type":       self.doc_type.value,
            "test_type":      self.test_type,
            "component":      self.component,
            "method_name":    self.method_name,
            "language":       self.language,
            "framework":      self.framework,
            "is_daily_note":  self.is_daily_note,
            "note_date":      self.note_date,
            "source_file":    self.source_file,
            "priority_score": self.priority_score,
        }

    @classmethod
    def from_chroma_dict(cls, data: dict) -> "DocumentMetadata":
        """Reconstruye una instancia desde un dict de ChromaDB."""
        return cls(
            doc_type=DocType(data["doc_type"]),
            test_type=data.get("test_type", ""),
            component=data.get("component", ""),
            method_name=data.get("method_name", ""),
            language=data.get("language", ""),
            framework=data.get("framework", ""),
            is_daily_note=data.get("is_daily_note", False),
            note_date=data.get("note_date", ""),
            source_file=data.get("source_file", ""),
            priority_score=data.get("priority_score", 1.0),
        )
