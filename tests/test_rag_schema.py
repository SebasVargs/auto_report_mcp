"""
Tests unitarios para rag_schema.py

Valida todos los mappings de get_collection_for_doc_type,
la estructura de DocumentMetadata y su serialización a/desde ChromaDB.
"""

import pytest

from app.rag.rag_schema import (
    CollectionName,
    DocType,
    DocumentMetadata,
    get_collection_for_doc_type,
)


# ─────────────────────────────────────────────────
# Tests de get_collection_for_doc_type
# ─────────────────────────────────────────────────


class TestGetCollectionForDocType:
    """Valida todos los mappings DocType → CollectionName."""

    def test_unit_test_maps_to_unit_tests(self):
        assert get_collection_for_doc_type(DocType.UNIT_TEST) == CollectionName.UNIT_TESTS

    def test_integration_test_maps_to_integration_tests(self):
        assert get_collection_for_doc_type(DocType.INTEGRATION_TEST) == CollectionName.INTEGRATION_TESTS

    def test_functional_test_maps_to_functional_tests(self):
        assert get_collection_for_doc_type(DocType.FUNCTIONAL_TEST) == CollectionName.FUNCTIONAL_TESTS

    def test_method_doc_maps_to_project_docs(self):
        assert get_collection_for_doc_type(DocType.METHOD_DOC) == CollectionName.PROJECT_DOCS

    def test_project_doc_maps_to_project_docs(self):
        assert get_collection_for_doc_type(DocType.PROJECT_DOC) == CollectionName.PROJECT_DOCS

    def test_daily_note_maps_to_project_docs(self):
        assert get_collection_for_doc_type(DocType.DAILY_NOTE) == CollectionName.PROJECT_DOCS

    def test_all_doc_types_have_mapping(self):
        """Garantiza que ningún DocType futuro quede sin mapeo."""
        for doc_type in DocType:
            result = get_collection_for_doc_type(doc_type)
            assert isinstance(result, CollectionName)


# ─────────────────────────────────────────────────
# Tests de DocumentMetadata
# ─────────────────────────────────────────────────


class TestDocumentMetadata:

    def test_default_values(self):
        meta = DocumentMetadata(doc_type=DocType.PROJECT_DOC)
        assert meta.doc_type == DocType.PROJECT_DOC
        assert meta.test_type == ""
        assert meta.component == ""
        assert meta.method_name == ""
        assert meta.language == ""
        assert meta.framework == ""
        assert meta.is_daily_note is False
        assert meta.note_date == ""
        assert meta.source_file == ""
        assert meta.priority_score == 1.0

    def test_daily_note_metadata(self):
        meta = DocumentMetadata(
            doc_type=DocType.DAILY_NOTE,
            is_daily_note=True,
            note_date="2024-01-15",
            component="UserService",
            priority_score=2.0,
        )
        assert meta.is_daily_note is True
        assert meta.note_date == "2024-01-15"
        assert meta.priority_score == 2.0

    def test_unit_test_metadata(self):
        meta = DocumentMetadata(
            doc_type=DocType.UNIT_TEST,
            test_type="unit",
            component="AuthController",
            method_name="login",
            language="python",
            framework="pytest",
            source_file="tests/test_auth.py",
        )
        assert meta.test_type == "unit"
        assert meta.framework == "pytest"
        assert meta.source_file == "tests/test_auth.py"

    def test_to_chroma_dict(self):
        meta = DocumentMetadata(
            doc_type=DocType.METHOD_DOC,
            component="OrderService",
            method_name="createOrder",
            language="typescript",
        )
        d = meta.to_chroma_dict()
        assert d["doc_type"] == "method_doc"
        assert d["component"] == "OrderService"
        assert d["method_name"] == "createOrder"
        assert d["language"] == "typescript"
        assert d["priority_score"] == 1.0
        assert d["is_daily_note"] is False

    def test_from_chroma_dict_roundtrip(self):
        original = DocumentMetadata(
            doc_type=DocType.INTEGRATION_TEST,
            test_type="integration",
            component="PaymentGateway",
            method_name="processPayment",
            language="java",
            framework="junit",
            is_daily_note=False,
            note_date="",
            source_file="src/test/PaymentGatewayTest.java",
            priority_score=1.0,
        )
        chroma_dict = original.to_chroma_dict()
        restored = DocumentMetadata.from_chroma_dict(chroma_dict)
        assert restored == original


# ─────────────────────────────────────────────────
# Tests de los Enums
# ─────────────────────────────────────────────────


class TestEnums:

    def test_doc_type_values(self):
        assert DocType.UNIT_TEST.value == "unit_test"
        assert DocType.INTEGRATION_TEST.value == "integration_test"
        assert DocType.FUNCTIONAL_TEST.value == "functional_test"
        assert DocType.METHOD_DOC.value == "method_doc"
        assert DocType.PROJECT_DOC.value == "project_doc"
        assert DocType.DAILY_NOTE.value == "daily_note"

    def test_collection_name_values(self):
        assert CollectionName.UNIT_TESTS.value == "unit_tests"
        assert CollectionName.INTEGRATION_TESTS.value == "integration_tests"
        assert CollectionName.FUNCTIONAL_TESTS.value == "functional_tests"
        assert CollectionName.PROJECT_DOCS.value == "project_docs"

    def test_doc_type_is_str_enum(self):
        """Los enums heredan de str para ser directamente serializables."""
        assert isinstance(DocType.UNIT_TEST, str)
        assert isinstance(CollectionName.UNIT_TESTS, str)
