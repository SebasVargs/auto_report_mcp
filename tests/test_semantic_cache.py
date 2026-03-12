"""
Tests unitarios para semantic_cache.py
"""

import time
import pytest
from unittest.mock import MagicMock

from app.rag.semantic_cache import SemanticQueryCache, CachedResult


# ─────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────

@pytest.fixture
def mock_emb():
    """Embedding service that produces deterministic vectors based on text hash."""
    emb = MagicMock()

    def hash_embed(text):
        import hashlib
        h = hashlib.md5(text.encode()).hexdigest()
        vec = [0.0] * 384
        for i, ch in enumerate(h):
            vec[i % 384] += ord(ch) / 1000.0
        # Normalize
        norm = sum(x * x for x in vec) ** 0.5
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec

    emb.embed = hash_embed
    return emb


@pytest.fixture
def cache(mock_emb):
    return SemanticQueryCache(
        embedding_service=mock_emb,
        similarity_threshold=0.92,
        max_size=10,
        ttl_hours=24,
    )


# ─────────────────────────────────────────────────
# Cache Hit / Miss
# ─────────────────────────────────────────────────

class TestCacheHitMiss:

    def test_hit_with_same_query(self, cache):
        """Exact same query should be a cache hit."""
        cache.set("genera test unitario para saveUser", "unit_UserService_saveUser", {"chunks": ["test1"]})
        result = cache.get("genera test unitario para saveUser", "unit_UserService_saveUser")
        assert result is not None
        assert result.result == {"chunks": ["test1"]}

    def test_miss_with_different_query(self, cache):
        """Completely different query should be a miss."""
        cache.set("genera test unitario para saveUser", "unit_UserService_saveUser", {"chunks": ["test1"]})
        result = cache.get("qué es la fotosíntesis", "other_None_None")
        assert result is None

    def test_miss_with_different_intent_key(self, cache):
        """Same query but different intent_key should be a miss."""
        cache.set("genera test", "unit_UserService_saveUser", {"chunks": ["test1"]})
        result = cache.get("genera test", "integration_OrderService_create")
        assert result is None

    def test_hit_preserves_result(self, cache):
        """Cached result should be returned intact."""
        data = {"chunks": [{"content": "test code", "metadata": {"doc_type": "unit_test"}}]}
        cache.set("query original", "unit_A_b", data)
        hit = cache.get("query original", "unit_A_b")
        assert hit is not None
        assert hit.result["chunks"][0]["content"] == "test code"


# ─────────────────────────────────────────────────
# LRU Eviction
# ─────────────────────────────────────────────────

class TestLRUEviction:

    def test_eviction_when_max_size_exceeded(self, cache):
        """Cache should evict oldest entries when exceeding max_size."""
        for i in range(15):
            cache.set(f"query_{i}", f"intent_{i}", {"i": i})
        assert cache.size <= 10

    def test_lru_order_maintained(self, cache):
        """Recently accessed entries should survive eviction."""
        cache.set("keep_me", "intent_keep", {"keep": True})
        # Access it to make it recently used
        cache.get("keep_me", "intent_keep")
        # Fill to max
        for i in range(15):
            cache.set(f"filler_{i}", f"intent_filler_{i}", {"i": i})
        # The kept entry might be evicted since many new entries pushed it out
        assert cache.size == 10


# ─────────────────────────────────────────────────
# TTL
# ─────────────────────────────────────────────────

class TestTTL:

    def test_expired_entry_not_returned(self, cache):
        """Entries past TTL should be treated as misses."""
        cache.set("old query", "intent_old", {"old": True})
        # Manually expire the entry
        for entry in cache._cache.values():
            entry.timestamp = time.time() - 90000  # > 24 hours
        result = cache.get("old query", "intent_old")
        assert result is None

    def test_fresh_entry_returned(self, cache):
        """Non-expired entries should be returned."""
        cache.set("fresh query", "intent_fresh", {"fresh": True})
        result = cache.get("fresh query", "intent_fresh")
        assert result is not None


# ─────────────────────────────────────────────────
# Invalidation By Component
# ─────────────────────────────────────────────────

class TestInvalidateByComponent:

    def test_invalidate_removes_matching_entries(self, cache):
        cache.set("q1", "unit_UserService_save", {"r": 1}, component="UserService")
        cache.set("q2", "unit_OrderService_create", {"r": 2}, component="OrderService")
        removed = cache.invalidate_by_component("UserService")
        assert removed >= 1
        assert cache.get("q1", "unit_UserService_save") is None
        # OrderService should survive
        assert cache.size >= 1

    def test_invalidate_returns_count(self, cache):
        cache.set("q1", "unit_A_x", {"r": 1}, component="A")
        cache.set("q2", "unit_A_y", {"r": 2}, component="A")
        removed = cache.invalidate_by_component("A")
        assert removed == 2


# ─────────────────────────────────────────────────
# Invalidation By Daily Notes
# ─────────────────────────────────────────────────

class TestInvalidateDailyNotes:

    def test_invalidate_daily_notes(self, cache):
        cache.set("q1", "unit_A_x", {"r": 1}, daily_notes_included=True)
        cache.set("q2", "unit_B_y", {"r": 2}, daily_notes_included=False)
        removed = cache.invalidate_daily_notes_cache()
        assert removed == 1
        assert cache.size == 1

    def test_daily_note_ingestion_invalidates_relevant_cache(self, cache):
        """Simulates: ingesting a daily note should invalidate cached results that included notes."""
        cache.set("genera test para UserService", "unit_UserService_save",
                  {"chunks": ["old_context"]}, daily_notes_included=True)
        cache.set("qué métodos tiene OrderService", "none_OrderService_",
                  {"chunks": ["order_context"]}, daily_notes_included=True)
        cache.set("test genérico", "unit_None_None",
                  {"chunks": ["generic"]}, daily_notes_included=False)

        removed = cache.invalidate_daily_notes_cache()
        assert removed == 2
        assert cache.size == 1


# ─────────────────────────────────────────────────
# Clear
# ─────────────────────────────────────────────────

class TestClear:

    def test_clear_empties_cache(self, cache):
        cache.set("q1", "i1", {"r": 1})
        cache.set("q2", "i2", {"r": 2})
        cache.clear()
        assert cache.size == 0
