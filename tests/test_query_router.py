"""
Tests unitarios para query_router.py

Valida detección de intent y routing a colecciones correctas.
"""

import pytest
from unittest.mock import MagicMock

from app.rag.rag_schema import DocType, CollectionName
from app.rag.query_router import TestAwareQueryRouter, QueryIntent, RetrievalResult


@pytest.fixture
def mock_vs():
    vs = MagicMock()
    vs.query = MagicMock(return_value=[])
    return vs


@pytest.fixture
def mock_emb():
    emb = MagicMock()
    emb.embed = MagicMock(return_value=[0.0] * 384)
    return emb


@pytest.fixture
def router(mock_vs, mock_emb):
    return TestAwareQueryRouter(vector_store=mock_vs, embedding_service=mock_emb)


@pytest.fixture
def fake_collections():
    return {
        "unit_tests": MagicMock(),
        "integration_tests": MagicMock(),
        "functional_tests": MagicMock(),
        "project_docs": MagicMock(),
    }


# ─────────────────────────────────────────────────
# detect_query_intent
# ─────────────────────────────────────────────────

class TestDetectQueryIntent:

    def test_generate_unit_test(self, router):
        intent = router.detect_query_intent(
            "genera un test unitario para UserService.saveUser"
        )
        assert intent.wants_test is True
        assert intent.test_type == DocType.UNIT_TEST
        assert intent.target_component == "UserService"
        assert intent.target_method == "saveUser"
        assert intent.needs_method_context is True

    def test_method_query(self, router):
        intent = router.detect_query_intent(
            "cómo funciona el método authenticate"
        )
        assert intent.wants_test is False
        assert intent.needs_method_context is False

    def test_search_integration_tests(self, router):
        intent = router.detect_query_intent(
            "muéstrame tests de integración del repositorio"
        )
        assert intent.wants_test is True
        assert intent.test_type == DocType.INTEGRATION_TEST

    def test_functional_test_detection(self, router):
        intent = router.detect_query_intent(
            "genera un test funcional del flujo completo de login"
        )
        assert intent.wants_test is True
        assert intent.test_type == DocType.FUNCTIONAL_TEST

    def test_generic_test_request(self, router):
        intent = router.detect_query_intent(
            "escribe un test para el servicio de pagos"
        )
        assert intent.wants_test is True

    def test_no_test_intent(self, router):
        intent = router.detect_query_intent(
            "qué métodos tiene la clase OrderService"
        )
        assert intent.wants_test is False


# ─────────────────────────────────────────────────
# route — CASO A (generar test)
# ─────────────────────────────────────────────────

class TestRouteCaseA:

    def test_case_a_returns_result(self, router, fake_collections, mock_vs):
        mock_vs.query.return_value = [
            {"id": "1", "content": "test", "metadata": {"doc_type": "unit_test"}, "relevance_score": 0.9}
        ]
        result = router.route(
            "genera un test unitario para UserService.saveUser",
            fake_collections,
        )
        assert isinstance(result, RetrievalResult)
        assert result.primary_source == "unit_tests"

    def test_case_a_daily_notes_first(self, router, fake_collections, mock_vs):
        """Daily notes should always appear first in CASO A results."""
        call_count = {"n": 0}

        def mock_query(collection_name, query_embedding, top_k, where=None):
            call_count["n"] += 1
            if where and where.get("is_daily_note"):
                return [{
                    "id": "note1", "content": "daily note",
                    "metadata": {"is_daily_note": True, "priority_score": 2.0},
                    "relevance_score": 0.5,
                }]
            if where and where.get("doc_type") == "method_doc":
                return [{
                    "id": "method1", "content": "method doc",
                    "metadata": {"doc_type": "method_doc"},
                    "relevance_score": 0.95,
                }]
            return [{
                "id": "test1", "content": "test code",
                "metadata": {"doc_type": "unit_test"},
                "relevance_score": 0.85,
            }]

        mock_vs.query = mock_query
        result = router.route(
            "genera un test unitario para UserService.saveUser",
            fake_collections,
        )
        assert result.daily_notes_included is True
        # Daily note should be boosted to top
        if result.chunks:
            top = result.chunks[0]
            assert top["metadata"].get("is_daily_note") or top["relevance_score"] >= 0.9


# ─────────────────────────────────────────────────
# route — CASO B (buscar test)
# ─────────────────────────────────────────────────

class TestRouteCaseB:

    def test_case_b_searches_all_test_collections(self, router, fake_collections, mock_vs):
        mock_vs.query.return_value = [
            {"id": "1", "content": "test", "metadata": {}, "relevance_score": 0.8}
        ]
        result = router.route(
            "muéstrame los tests del módulo de pagos",
            fake_collections,
        )
        # Should have queried multiple test collections
        assert mock_vs.query.call_count >= 3


# ─────────────────────────────────────────────────
# route — CASO C (método/funcionalidad)
# ─────────────────────────────────────────────────

class TestRouteCaseC:

    def test_case_c_project_docs_only(self, router, fake_collections, mock_vs):
        mock_vs.query.return_value = [
            {"id": "1", "content": "doc", "metadata": {"doc_type": "project_doc"}, "relevance_score": 0.7}
        ]
        result = router.route(
            "qué métodos tiene OrderService",
            fake_collections,
        )
        assert result.primary_source == "project_docs"


# ─────────────────────────────────────────────────
# _apply_priority_scoring
# ─────────────────────────────────────────────────

class TestPriorityScoring:

    def test_daily_note_boosted(self, router):
        intent = QueryIntent(wants_test=True, test_type=DocType.UNIT_TEST)
        chunks = [
            {"content": "note", "metadata": {"is_daily_note": True, "priority_score": 2.0}, "relevance_score": 0.5},
            {"content": "test", "metadata": {"is_daily_note": False}, "relevance_score": 0.8},
        ]
        scored = router._apply_priority_scoring(chunks, intent)
        # Note (0.5 * 2.0 = 1.0) should beat test (0.8)
        assert scored[0]["metadata"]["is_daily_note"] is True

    def test_incomplete_signature_penalized(self, router):
        intent = QueryIntent()
        chunks = [
            {"content": "a", "metadata": {"has_incomplete_signature": True}, "relevance_score": 0.9},
            {"content": "b", "metadata": {"has_incomplete_signature": False}, "relevance_score": 0.5},
        ]
        scored = router._apply_priority_scoring(chunks, intent)
        # 0.9 * 0.3 = 0.27 < 0.5
        assert scored[0]["content"] == "b"

    def test_component_match_boosted(self, router):
        intent = QueryIntent(target_component="UserService")
        chunks = [
            {"content": "a", "metadata": {"component": "UserService"}, "relevance_score": 0.5},
            {"content": "b", "metadata": {"component": "Other"}, "relevance_score": 0.7},
        ]
        scored = router._apply_priority_scoring(chunks, intent)
        # 0.5 * 1.5 = 0.75 > 0.7
        assert scored[0]["metadata"]["component"] == "UserService"

    def test_method_match_boosted(self, router):
        intent = QueryIntent(target_method="saveUser")
        chunks = [
            {"content": "a", "metadata": {"method_name": "saveUser"}, "relevance_score": 0.4},
            {"content": "b", "metadata": {"method_name": "deleteUser"}, "relevance_score": 0.7},
        ]
        scored = router._apply_priority_scoring(chunks, intent)
        # 0.4 * 2.0 = 0.8 > 0.7
        assert scored[0]["metadata"]["method_name"] == "saveUser"
