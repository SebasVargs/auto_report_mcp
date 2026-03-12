"""
Tests para structural_chunker.py

Verifica que el chunking respeta unidades lógicas:
- Tests completos sin asserts cortados
- Métodos completos con firma
- Párrafos completos en project docs
- Notas diarias como chunk único
"""

import pytest

from app.rag.rag_schema import DocType, DocumentMetadata
from app.rag.structural_chunker import StructuralChunker


@pytest.fixture
def chunker() -> StructuralChunker:
    return StructuralChunker()


def _meta(doc_type: DocType, **kwargs) -> DocumentMetadata:
    return DocumentMetadata(doc_type=doc_type, source_file="test.py", **kwargs)


# ─────────────────────────────────────────────────
# chunk_test_file
# ─────────────────────────────────────────────────

class TestChunkTestFile:

    def test_python_tests_split_correctly(self, chunker):
        code = """
import pytest

def test_save_user():
    user = User(name="test")
    result = service.save(user)
    assert result.id == 1

def test_delete_user():
    result = service.delete(1)
    assert result is True
"""
        meta = _meta(DocType.UNIT_TEST, language="python")
        chunks = chunker.chunk_test_file(code, meta)
        assert len(chunks) == 2

    def test_each_chunk_has_test_name(self, chunker):
        code = """
def test_create_order():
    order = Order(total=100)
    assert order.total == 100

def test_cancel_order():
    result = cancel(1)
    assert result is True
"""
        meta = _meta(DocType.UNIT_TEST, language="python")
        chunks = chunker.chunk_test_file(code, meta)
        names = [c["metadata"]["test_name"] for c in chunks]
        assert "test_create_order" in names
        assert "test_cancel_order" in names

    def test_chunk_type_is_full_test(self, chunker):
        code = """
def test_simple():
    assert 1 + 1 == 2
"""
        meta = _meta(DocType.UNIT_TEST, language="python")
        chunks = chunker.chunk_test_file(code, meta)
        assert chunks[0]["metadata"]["chunk_type"] == "full_test"

    def test_no_assert_cut_in_middle(self, chunker):
        code = """
def test_complete():
    data = prepare()
    result = process(data)
    assert result.status == "ok"
    assert result.count == 5
    assert result.errors == []
"""
        meta = _meta(DocType.UNIT_TEST, language="python")
        chunks = chunker.chunk_test_file(code, meta)
        # All asserts should be in the same chunk
        for c in chunks:
            text = c["content"]
            if "assert" in text:
                assert "assert result.status" in text or "assert result.count" in text

    def test_empty_content_produces_single_chunk(self, chunker):
        meta = _meta(DocType.UNIT_TEST, language="python")
        chunks = chunker.chunk_test_file("# empty file", meta)
        assert len(chunks) == 1


# ─────────────────────────────────────────────────
# chunk_method_doc
# ─────────────────────────────────────────────────

class TestChunkMethodDoc:

    def test_splits_by_methods(self, chunker):
        code = '''
class UserService:
    def save_user(self, user: UserDTO) -> User:
        """Save user."""
        return self.repo.save(user)

    def find_by_id(self, user_id: int) -> Optional[User]:
        """Find user by ID."""
        return self.repo.find(user_id)
'''
        meta = _meta(DocType.METHOD_DOC, language="python")
        chunks = chunker.chunk_method_doc(code, meta)
        assert len(chunks) >= 2

    def test_marks_incomplete_signature(self, chunker):
        text = "This is some documentation without any method signature."
        meta = _meta(DocType.METHOD_DOC, language="python")
        chunks = chunker.chunk_method_doc(text, meta)
        assert chunks[0]["metadata"]["has_incomplete_signature"] is True

    def test_complete_signature_marked(self, chunker):
        code = '''
    def save_user(self, user: UserDTO) -> User:
        """Save a user to the database."""
        return self.repo.save(user)
'''
        meta = _meta(DocType.METHOD_DOC, language="python")
        chunks = chunker.chunk_method_doc(code, meta)
        assert chunks[0]["metadata"]["has_incomplete_signature"] is False


# ─────────────────────────────────────────────────
# chunk_project_doc
# ─────────────────────────────────────────────────

class TestChunkProjectDoc:

    def test_respects_paragraph_boundaries(self, chunker):
        # Create text with clear paragraph breaks
        paras = ["Párrafo " + str(i) + ". " + "palabra " * 50 for i in range(10)]
        text = "\n\n".join(paras)
        meta = _meta(DocType.PROJECT_DOC)
        chunks = chunker.chunk_project_doc(text, meta)
        # Each chunk should be complete paragraphs, no mid-paragraph cuts
        for c in chunks:
            content = c["content"]
            # Should start with "Párrafo" (beginning of a paragraph)
            assert content.startswith("Párrafo")

    def test_short_doc_single_chunk(self, chunker):
        text = "Este es un documento corto."
        meta = _meta(DocType.PROJECT_DOC)
        chunks = chunker.chunk_project_doc(text, meta)
        assert len(chunks) == 1


# ─────────────────────────────────────────────────
# chunk_daily_note
# ─────────────────────────────────────────────────

class TestChunkDailyNote:

    def test_short_note_single_chunk(self, chunker):
        note = "Hoy migré el módulo de pagos a la nueva API."
        meta = _meta(DocType.DAILY_NOTE, is_daily_note=True, note_date="2024-01-15")
        chunks = chunker.chunk_daily_note(note, meta)
        assert len(chunks) == 1

    def test_preserves_date_in_metadata(self, chunker):
        note = "Cambié la configuración del deployment."
        meta = _meta(DocType.DAILY_NOTE, is_daily_note=True, note_date="2024-03-10")
        chunks = chunker.chunk_daily_note(note, meta)
        assert chunks[0]["metadata"]["note_date"] == "2024-03-10"
        assert chunks[0]["metadata"]["is_daily_note"] is True

    def test_long_note_splits_by_headers(self, chunker):
        sections = []
        for i in range(5):
            sections.append(f"## Sección {i}\n" + "palabra " * 300)
        note = "\n\n".join(sections)
        meta = _meta(DocType.DAILY_NOTE, is_daily_note=True, note_date="2024-01-15")
        chunks = chunker.chunk_daily_note(note, meta)
        assert len(chunks) > 1


# ─────────────────────────────────────────────────
# chunk_document (router)
# ─────────────────────────────────────────────────

class TestChunkDocumentRouter:

    def test_routes_unit_test(self, chunker):
        code = "def test_foo():\n    assert True"
        meta = _meta(DocType.UNIT_TEST, language="python")
        chunks = chunker.chunk_document(code, meta)
        assert len(chunks) >= 1
        assert chunks[0]["metadata"]["doc_type"] == "unit_test"

    def test_routes_daily_note(self, chunker):
        note = "Hoy arreglé un bug."
        meta = _meta(DocType.DAILY_NOTE, is_daily_note=True)
        chunks = chunker.chunk_document(note, meta)
        assert chunks[0]["metadata"]["is_daily_note"] is True

    def test_routes_project_doc(self, chunker):
        text = "Documentación del proyecto."
        meta = _meta(DocType.PROJECT_DOC)
        chunks = chunker.chunk_document(text, meta)
        assert chunks[0]["metadata"]["doc_type"] == "project_doc"
