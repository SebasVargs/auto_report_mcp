"""
collection_manager.py — Gestión de las 4 colecciones ChromaDB para RAG v2.

Crea y accede a las colecciones separadas por tipo de documento,
reutilizando el VectorStore singleton existente.
"""

from __future__ import annotations

import chromadb

from app.rag.rag_schema import CollectionName, DocType, get_collection_for_doc_type
from app.rag.vector_store import VectorStore
from app.utils.logger import get_logger

logger = get_logger(__name__)


def initialize_collections(
    vector_store: VectorStore | None = None,
) -> dict[str, chromadb.Collection]:
    """
    Crea las 4 colecciones del RAG v2 usando get_or_create.
    Reutiliza el VectorStore singleton existente.

    Returns:
        dict con las 4 colecciones accesibles por su nombre de enum.
    """
    vs = vector_store or VectorStore()
    collections: dict[str, chromadb.Collection] = {}

    for col_name in CollectionName:
        collection = vs.get_or_create_collection(col_name.value)
        collections[col_name.value] = collection
        logger.info(f"Collection ready: '{col_name.value}'")

    logger.info(
        f"Initialized {len(collections)} RAG v2 collections: "
        f"{list(collections.keys())}"
    )
    return collections


def get_collection(
    collections: dict[str, chromadb.Collection],
    doc_type: DocType,
) -> chromadb.Collection:
    """
    Retorna la colección correcta para un DocType dado.
    Usa el mapeo definido en rag_schema.py.

    Args:
        collections: dict retornado por initialize_collections()
        doc_type:    tipo de documento a buscar

    Returns:
        La Collection de ChromaDB correspondiente.

    Raises:
        KeyError: si la colección no fue inicializada.
    """
    collection_name = get_collection_for_doc_type(doc_type)
    return collections[collection_name.value]
