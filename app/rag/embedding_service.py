from __future__ import annotations

import hashlib

from app.providers.base import EmbeddingProvider
from app.providers import get_embedding_provider
from app.utils.logger import get_logger

logger = get_logger(__name__)

_EMBED_CACHE: dict[str, list[float]] = {}
_MAX_CACHE_SIZE = 2000


class EmbeddingService:
    """
    Wraps any EmbeddingProvider with:
    - Automatic batching (handled by the provider itself)
    - In-memory LRU-style cache
    Provider is resolved from settings (EMBEDDING_PROVIDER env var) by default,
    but can be injected for testing or custom usage.
    """

    def __init__(self, provider: EmbeddingProvider | None = None):
        self._provider = provider or get_embedding_provider()

    def embed(self, text: str) -> list[float]:
        """Embed a single text string."""
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Embed multiple texts efficiently.
        Uses in-memory cache and delegates uncached texts to the provider.
        """
        results: list[list[float] | None] = [None] * len(texts)
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        for i, text in enumerate(texts):
            cache_key = self._cache_key(text)
            if cache_key in _EMBED_CACHE:
                results[i] = _EMBED_CACHE[cache_key]
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)

        if uncached_texts:
            logger.debug(f"Embedding {len(uncached_texts)} new texts (cache miss)")
            embeddings = self._provider.embed_batch(uncached_texts)
            for original_i, embedding in zip(uncached_indices, embeddings):
                results[original_i] = embedding
                self._store_cache(texts[original_i], embedding)

        return [r for r in results if r is not None]

    # ─────────────────────────────────────────────────
    # Cache helpers
    # ─────────────────────────────────────────────────

    @staticmethod
    def _cache_key(text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()

    @staticmethod
    def _store_cache(text: str, embedding: list[float]) -> None:
        global _EMBED_CACHE
        if len(_EMBED_CACHE) >= _MAX_CACHE_SIZE:
            # Evict oldest half
            keys = list(_EMBED_CACHE.keys())
            for k in keys[: _MAX_CACHE_SIZE // 2]:
                del _EMBED_CACHE[k]
        _EMBED_CACHE[EmbeddingService._cache_key(text)] = embedding
