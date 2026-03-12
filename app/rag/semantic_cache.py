"""
semantic_cache.py — Caché semántico de resultados completos para RAG v2.

Reemplaza el LRU Cache de embeddings individuales con uno que cachea
resultados completos de búsqueda y se invalida automáticamente.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from app.rag.embedding_service import EmbeddingService
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Similitud coseno entre dos vectores."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


@dataclass
class CachedResult:
    """Entrada individual del caché."""
    query: str
    intent_key: str
    embedding: list[float]
    result: Any
    timestamp: float = field(default_factory=time.time)
    daily_notes_included: bool = False
    component: str = ""


class SemanticQueryCache:
    """
    Caché semántico que almacena resultados completos de búsqueda.
    - Agrupado por intent_key para separar cachés de intents distintos
    - Similitud coseno > threshold = cache hit
    - LRU eviction al superar max_size
    - TTL por entrada
    - Invalidación por componente y por daily notes
    """

    def __init__(
        self,
        embedding_service: EmbeddingService | None = None,
        similarity_threshold: float = 0.92,
        max_size: int = 300,
        ttl_hours: int = 24,
    ):
        self._emb = embedding_service or EmbeddingService()
        self._threshold = similarity_threshold
        self._max_size = max_size
        self._ttl_seconds = ttl_hours * 3600
        self._cache: OrderedDict[str, CachedResult] = OrderedDict()
        self._counter = 0

    # ─────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────

    def get(self, query: str, intent_key: str) -> CachedResult | None:
        """
        Busca un resultado cacheado para la query + intent_key.

        Proceso:
        a. Embedear la query entrante
        b. Comparar con embeddings cacheados del mismo intent_key
        c. Si similitud > threshold y no expirado: retornar resultado
        d. Si no: retornar None
        """
        query_embedding = self._emb.embed(query)
        now = time.time()

        best_match: CachedResult | None = None
        best_similarity = 0.0
        expired_keys: list[str] = []

        for key, entry in self._cache.items():
            # Solo comparar mismo intent_key
            if entry.intent_key != intent_key:
                continue

            # TTL check
            if now - entry.timestamp > self._ttl_seconds:
                expired_keys.append(key)
                continue

            similarity = _cosine_similarity(query_embedding, entry.embedding)
            if similarity > self._threshold and similarity > best_similarity:
                best_similarity = similarity
                best_match = entry

        # Clean expired entries
        for key in expired_keys:
            del self._cache[key]

        if best_match:
            # Move to end (most recently used)
            cache_key = self._find_key(best_match)
            if cache_key:
                self._cache.move_to_end(cache_key)
            logger.debug(
                f"Cache HIT for intent={intent_key}, "
                f"similarity={best_similarity:.3f}"
            )
            return best_match

        logger.debug(f"Cache MISS for intent={intent_key}")
        return None

    def set(
        self,
        query: str,
        intent_key: str,
        result: Any,
        daily_notes_included: bool = False,
        component: str = "",
    ) -> None:
        """
        Guarda query + embedding + resultado en el caché.
        LRU eviction si se supera max_size.
        """
        embedding = self._emb.embed(query)

        self._counter += 1
        cache_key = f"{intent_key}_{self._counter}"

        entry = CachedResult(
            query=query,
            intent_key=intent_key,
            embedding=embedding,
            result=result,
            timestamp=time.time(),
            daily_notes_included=daily_notes_included,
            component=component,
        )

        self._cache[cache_key] = entry
        self._cache.move_to_end(cache_key)

        # LRU eviction
        while len(self._cache) > self._max_size:
            evicted_key, _ = self._cache.popitem(last=False)
            logger.debug(f"Cache evicted: {evicted_key}")

        logger.debug(
            f"Cache SET for intent={intent_key}, "
            f"size={len(self._cache)}/{self._max_size}"
        )

    def invalidate_by_component(self, component: str) -> int:
        """
        Invalida entradas del caché que involucren un componente específico.
        Llamar cuando se reingesta un documento.
        Retorna número de entradas invalidadas.
        """
        keys_to_remove = [
            key for key, entry in self._cache.items()
            if entry.component == component
            or component.lower() in entry.intent_key.lower()
        ]

        for key in keys_to_remove:
            del self._cache[key]

        if keys_to_remove:
            logger.info(
                f"Cache invalidated {len(keys_to_remove)} entries "
                f"for component={component}"
            )
        return len(keys_to_remove)

    def invalidate_daily_notes_cache(self) -> int:
        """
        Invalida entradas donde daily_notes_included = True.
        Llamar cada vez que se ingesta una daily note nueva.
        """
        keys_to_remove = [
            key for key, entry in self._cache.items()
            if entry.daily_notes_included
        ]

        for key in keys_to_remove:
            del self._cache[key]

        if keys_to_remove:
            logger.info(
                f"Cache invalidated {len(keys_to_remove)} daily-note entries"
            )
        return len(keys_to_remove)

    def clear(self) -> None:
        """Limpia todo el caché."""
        self._cache.clear()
        logger.info("Cache cleared")

    @property
    def size(self) -> int:
        return len(self._cache)

    # ─────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────

    def _find_key(self, entry: CachedResult) -> str | None:
        for key, val in self._cache.items():
            if val is entry:
                return key
        return None
