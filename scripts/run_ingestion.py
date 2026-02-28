import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.rag.ingest_documents import DocumentIngestionPipeline
from app.rag.vector_store import VectorStore
from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger("run_ingestion")
settings = get_settings()


def sync_from_drive() -> None:
    """Download new .docx files from Drive before ingesting."""
    try:
        from app.services.drive_service import DriveService
        downloaded = DriveService().sync_raw_reports()
        if downloaded:
            print(f"\n☁️  Synced {len(downloaded)} new file(s) from Google Drive:")
            for p in downloaded:
                print(f"   {p.name}")
        else:
            print("\n☁️  Drive sync: no new files found")
    except Exception as e:
        logger.warning(f"Drive sync failed (continuing with local files): {e}")


def main():
    parser = argparse.ArgumentParser(description="Ingest historical reports into ChromaDB")
    parser.add_argument("--file", type=str, help="Ingest a specific file")
    parser.add_argument("--stats", action="store_true", help="Show collection stats and exit")
    parser.add_argument("--no-drive", action="store_true", help="Skip Google Drive sync")
    args = parser.parse_args()

    if args.stats:
        vs = VectorStore()
        style_count = vs.collection_count(settings.chroma_collection_style)
        print(f"\n📊 Vector Store Statistics:")
        print(f"   Style chunks: {style_count}")
        print(f"   Persist dir:  {settings.chroma_persist_dir}\n")
        return

    # Sync from Drive first (if enabled and not skipped)
    if settings.drive_enabled and not args.no_drive:
        sync_from_drive()

    pipeline = DocumentIngestionPipeline()

    if args.file:
        path = Path(args.file)
        if not path.exists():
            logger.error(f"File not found: {path}")
            sys.exit(1)
        n = pipeline.ingest_file(path)
        logger.info(f"Ingested {n} chunks from {path.name}")
    else:
        results = pipeline.ingest_all()
        if results:
            print(f"\n✅ Ingestion complete:")
            for filename, count in results.items():
                print(f"   {filename}: {count} chunks")
        else:
            print("\n⏭  All files already ingested (no changes)")


if __name__ == "__main__":
    main()
