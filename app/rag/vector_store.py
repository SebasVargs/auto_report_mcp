from __future__ import annotations

from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


class VectorStore:
    """
    Encapsulates all ChromaDB interactions.
    Consumers never import chromadb directly — only this class.
    """

    _instance: "VectorStore | None" = None
    _client: chromadb.PersistentClient | None = None

    def __new__(cls) -> "VectorStore":
        """Singleton pattern — one ChromaDB client per process."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._client is None:
            persist_dir = Path(settings.chroma_persist_dir)
            persist_dir.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=str(persist_dir),
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            logger.info(f"ChromaDB initialised at {persist_dir}")

    # ─────────────────────────────────────────────────
    # Collection management
    # ─────────────────────────────────────────────────

    def get_or_create_collection(
        self, collection_name: str
    ) -> chromadb.Collection:
        return self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},  # cosine for semantic similarity
        )

    # ─────────────────────────────────────────────────
    # Write operations
    # ─────────────────────────────────────────────────

    def add_chunks(
        self,
        collection_name: str,
        chunks: list[dict],
        embeddings: list[list[float]],
    ) -> None:
        """
        Upsert chunks with precomputed embeddings.
        Uses upsert to be idempotent on re-ingestion.
        """
        collection = self.get_or_create_collection(collection_name)
        collection.upsert(
            ids=[c["id"] for c in chunks],
            documents=[c["content"] for c in chunks],
            metadatas=[c["metadata"] for c in chunks],
            embeddings=embeddings,
        )
        logger.debug(f"Upserted {len(chunks)} chunks into '{collection_name}'")

    def delete_chunks(self, collection_name: str, ids: list[str]) -> None:
        """
        Delete specific chunks by ID from a collection.
        Used during note consolidation to remove superseded notes.
        """
        if not ids:
            return
        collection = self.get_or_create_collection(collection_name)
        collection.delete(ids=ids)
        logger.debug(f"Deleted {len(ids)} chunk(s) from '{collection_name}'")

    # ─────────────────────────────────────────────────
    # Read operations
    # ─────────────────────────────────────────────────

    def query(
        self,
        collection_name: str,
        query_embedding: list[float],
        top_k: int = 8,
        where: dict | None = None,
    ) -> list[dict]:
        """
        Similarity search.
        Returns list of { id, content, metadata, distance }
        """
        collection = self.get_or_create_collection(collection_name)
        kwargs: dict = {
            "query_embeddings": [query_embedding],
            "n_results": min(top_k, collection.count() or 1),
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        results = collection.query(**kwargs)

        output = []
        for i, (doc, meta, dist) in enumerate(
            zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            )
        ):
            output.append(
                {
                    "id": results["ids"][0][i],
                    "content": doc,
                    "metadata": meta,
                    "distance": dist,
                    "relevance_score": 1 - dist,  # cosine: 1=identical, 0=orthogonal
                }
            )

        return sorted(output, key=lambda x: x["relevance_score"], reverse=True)

    def collection_count(self, collection_name: str) -> int:
        return self.get_or_create_collection(collection_name).count()

    def delete_collection(self, collection_name: str) -> None:
        self._client.delete_collection(collection_name)
        logger.warning(f"Deleted collection: {collection_name}")