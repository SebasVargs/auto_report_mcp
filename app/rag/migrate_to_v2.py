"""
migrate_to_v2.py — Script de migración de colección legacy a las 4 nuevas.

Lee todos los documentos de la colección anterior, los reclasifica con
DocumentClassifier, los rechunkea con StructuralChunker, y los ingesta
en la colección nueva correcta.

Uso:
    python -m app.rag.migrate_to_v2
"""

from __future__ import annotations

import sys

from app.rag.collection_manager import initialize_collections
from app.rag.document_classifier import DocumentClassifier
from app.rag.embedding_service import EmbeddingService
from app.rag.rag_schema import get_collection_for_doc_type, CollectionName
from app.rag.structural_chunker import StructuralChunker
from app.rag.vector_store import VectorStore
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Nombre de la colección legacy (la que usaba antes el sistema)
LEGACY_COLLECTION_NAME = "project_knowledge"


def migrate(
    vector_store: VectorStore | None = None,
    legacy_collection_name: str = LEGACY_COLLECTION_NAME,
    dry_run: bool = False,
) -> dict:
    """
    Migra datos de la colección legacy a las 4 nuevas.

    Returns:
        dict con resumen: {"total_migrated", "by_collection", "errors"}
    """
    vs = vector_store or VectorStore()
    emb = EmbeddingService()
    classifier = DocumentClassifier()
    chunker = StructuralChunker()

    # Inicializar las 4 colecciones nuevas
    collections = initialize_collections(vs)

    # Obtener la colección legacy
    try:
        legacy_col = vs.get_or_create_collection(legacy_collection_name)
    except Exception as e:
        logger.error(f"Cannot access legacy collection '{legacy_collection_name}': {e}")
        return {"total_migrated": 0, "by_collection": {}, "errors": [str(e)]}

    total_count = legacy_col.count()
    if total_count == 0:
        logger.info("Legacy collection is empty, nothing to migrate")
        return {"total_migrated": 0, "by_collection": {}, "errors": []}

    logger.info(f"Starting migration of {total_count} documents from '{legacy_collection_name}'")

    # Leer todos los documentos en batches
    batch_size = 100
    migrated = 0
    errors: list[str] = []
    by_collection: dict[str, int] = {col.value: 0 for col in CollectionName}

    offset = 0
    while offset < total_count:
        try:
            results = legacy_col.get(
                limit=batch_size,
                offset=offset,
                include=["documents", "metadatas"],
            )
        except Exception as e:
            errors.append(f"Batch read failed at offset {offset}: {e}")
            offset += batch_size
            continue

        documents = results.get("documents", [])
        metadatas = results.get("metadatas", [])
        ids = results.get("ids", [])

        if not documents:
            break

        for doc_id, doc_text, old_meta in zip(ids, documents, metadatas):
            if not doc_text:
                continue

            try:
                source_file = old_meta.get("source_file", old_meta.get("filename", ""))

                # Reclasificar
                metadata = classifier.classify_document(doc_text, source_file)
                metadata.source_file = source_file

                # Determinar colección destino
                col_name = get_collection_for_doc_type(metadata.doc_type)

                if dry_run:
                    by_collection[col_name.value] = by_collection.get(col_name.value, 0) + 1
                    migrated += 1
                    continue

                # Rechunkear
                chunks = chunker.chunk_document(doc_text, metadata)

                if chunks:
                    texts = [c["content"] for c in chunks]
                    embeddings = emb.embed_batch(texts)

                    import hashlib
                    store_chunks = []
                    for i, chunk in enumerate(chunks):
                        chunk_id = hashlib.md5(
                            f"migrated_{doc_id}_{i}".encode()
                        ).hexdigest()
                        store_chunks.append({
                            "id": chunk_id,
                            "content": chunk["content"],
                            "metadata": chunk["metadata"],
                        })

                    vs.add_chunks(col_name.value, store_chunks, embeddings)

                by_collection[col_name.value] = by_collection.get(col_name.value, 0) + len(chunks)
                migrated += 1

            except Exception as e:
                errors.append(f"Failed to migrate '{doc_id}': {e}")

        offset += batch_size

    summary = {
        "total_migrated": migrated,
        "by_collection": by_collection,
        "errors": errors,
    }

    # Imprimir resumen
    logger.info("=" * 60)
    logger.info("MIGRATION SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total documents migrated: {migrated}/{total_count}")
    for col, count in by_collection.items():
        logger.info(f"  {col}: {count} chunks")
    if errors:
        logger.warning(f"  Errors: {len(errors)}")
        for err in errors[:5]:
            logger.warning(f"    - {err}")
    logger.info("=" * 60)
    logger.info(
        "NOTE: Legacy collection NOT deleted (kept as backup). "
        "Delete manually after verifying migration."
    )

    return summary


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("DRY RUN — no data will be written")
    result = migrate(dry_run=dry_run)
    print(f"\nResult: {result}")
