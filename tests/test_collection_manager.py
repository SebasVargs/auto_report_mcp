"""
Tests de integración para collection_manager.py

Usa un ChromaDB EphemeralClient (in-memory) para validar
la creación de las 4 colecciones y el mapeo DocType → Collection.
"""

import pytest
import chromadb
from chromadb.config import Settings as ChromaSettings
from unittest.mock import patch, MagicMock

from app.rag.rag_schema import CollectionName, DocType
from app.rag.collection_manager import initialize_collections, get_collection


# ─────────────────────────────────────────────────
# Fixture: VectorStore mock con ChromaDB efímero
# ─────────────────────────────────────────────────

@pytest.fixture
def ephemeral_vector_store():
    """
    Crea un mock de VectorStore que usa un EphemeralClient real
    para que las colecciones existan de verdad en memoria.
    """
    client = chromadb.EphemeralClient(
        settings=ChromaSettings(anonymized_telemetry=False)
    )

    mock_vs = MagicMock()
    mock_vs.get_or_create_collection = lambda name: client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )
    return mock_vs, client


# ─────────────────────────────────────────────────
# Tests de initialize_collections
# ─────────────────────────────────────────────────

class TestInitializeCollections:

    def test_creates_four_collections(self, ephemeral_vector_store):
        mock_vs, client = ephemeral_vector_store
        collections = initialize_collections(vector_store=mock_vs)
        assert len(collections) == 4

    def test_collection_names_match_enum(self, ephemeral_vector_store):
        mock_vs, client = ephemeral_vector_store
        collections = initialize_collections(vector_store=mock_vs)
        expected = {"unit_tests", "integration_tests", "functional_tests", "project_docs"}
        assert set(collections.keys()) == expected

    def test_collections_are_chroma_collection_instances(self, ephemeral_vector_store):
        mock_vs, client = ephemeral_vector_store
        collections = initialize_collections(vector_store=mock_vs)
        for name, col in collections.items():
            assert hasattr(col, "add")
            assert hasattr(col, "query")

    def test_collections_use_cosine_distance(self, ephemeral_vector_store):
        mock_vs, client = ephemeral_vector_store
        collections = initialize_collections(vector_store=mock_vs)
        for name, col in collections.items():
            metadata = col.metadata
            assert metadata.get("hnsw:space") == "cosine"

    def test_idempotent_creation(self, ephemeral_vector_store):
        """Calling initialize twice doesn't create duplicates."""
        mock_vs, client = ephemeral_vector_store
        collections1 = initialize_collections(vector_store=mock_vs)
        collections2 = initialize_collections(vector_store=mock_vs)
        assert set(collections1.keys()) == set(collections2.keys())


# ─────────────────────────────────────────────────
# Tests de get_collection
# ─────────────────────────────────────────────────

class TestGetCollection:

    def test_unit_test_maps_correctly(self, ephemeral_vector_store):
        mock_vs, _ = ephemeral_vector_store
        collections = initialize_collections(vector_store=mock_vs)
        col = get_collection(collections, DocType.UNIT_TEST)
        assert col.name == "unit_tests"

    def test_integration_test_maps_correctly(self, ephemeral_vector_store):
        mock_vs, _ = ephemeral_vector_store
        collections = initialize_collections(vector_store=mock_vs)
        col = get_collection(collections, DocType.INTEGRATION_TEST)
        assert col.name == "integration_tests"

    def test_functional_test_maps_correctly(self, ephemeral_vector_store):
        mock_vs, _ = ephemeral_vector_store
        collections = initialize_collections(vector_store=mock_vs)
        col = get_collection(collections, DocType.FUNCTIONAL_TEST)
        assert col.name == "functional_tests"

    def test_method_doc_maps_to_project_docs(self, ephemeral_vector_store):
        mock_vs, _ = ephemeral_vector_store
        collections = initialize_collections(vector_store=mock_vs)
        col = get_collection(collections, DocType.METHOD_DOC)
        assert col.name == "project_docs"

    def test_project_doc_maps_to_project_docs(self, ephemeral_vector_store):
        mock_vs, _ = ephemeral_vector_store
        collections = initialize_collections(vector_store=mock_vs)
        col = get_collection(collections, DocType.PROJECT_DOC)
        assert col.name == "project_docs"

    def test_daily_note_maps_to_project_docs(self, ephemeral_vector_store):
        mock_vs, _ = ephemeral_vector_store
        collections = initialize_collections(vector_store=mock_vs)
        col = get_collection(collections, DocType.DAILY_NOTE)
        assert col.name == "project_docs"

    def test_all_doc_types_resolve(self, ephemeral_vector_store):
        """Every DocType should resolve to a valid collection."""
        mock_vs, _ = ephemeral_vector_store
        collections = initialize_collections(vector_store=mock_vs)
        for doc_type in DocType:
            col = get_collection(collections, doc_type)
            assert col is not None
            assert col.name in collections
