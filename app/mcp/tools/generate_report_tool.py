from __future__ import annotations

from datetime import date

from app.config import get_settings
from app.models.report_model import (
    GenerateReportRequest,
    GenerateReportResponse,
    ReportStatus,
)
from app.rag.retriever import StyleRetriever
from app.services.ai_service import AIService
from app.services.data_service import DataService
from app.services.word_service import WordService
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


class GenerateReportTool:
    """
    Orchestration tool for full report generation.

    Steps:
    1. [Drive] Download daily input JSON from Google Drive (if DRIVE_ENABLED)
    2. Load daily structured input from local disk
    3. Retrieve style context from RAG
    4. Generate narrative with AI
    5. Build Word document
    6. [Drive] Upload generated .docx to Google Drive (if DRIVE_ENABLED)
    7. Return result with Drive URL if available
    """

    def __init__(self):
        self._data_service = DataService()
        self._retriever = StyleRetriever()
        self._ai_service = AIService()
        self._word_service = WordService()

    async def execute(self, request: GenerateReportRequest) -> GenerateReportResponse:
        target_date = request.report_date or date.today()

        logger.info(f"🚀 Starting report generation for {target_date} | {request.report_type}")

        # Step 1: Sync from Drive if enabled and not skipped
        drive_url = ""
        if settings.drive_enabled and not request.skip_drive_sync:
            drive_url = await self._sync_input_from_drive(target_date, request.report_type.value)

        # Step 2: Load structured daily data from local disk
        daily_input = self._data_service.load_daily_input(target_date, request.report_type)
        logger.info(f"📂 Loaded daily input: {len(daily_input.test_cases)} tests, {len(daily_input.tasks)} tasks")

        # Step 3: Retrieve style context
        style_context = self._retriever.retrieve_style_context(daily_input)
        logger.info(f"🔍 Retrieved {len(style_context.chunks)} style chunks")

        # Step 4: Generate AI narrative
        generated_report = self._ai_service.generate_report(daily_input, style_context)
        generated_report.status = ReportStatus.GENERATING
        logger.info(f"🤖 AI narrative generated for report {generated_report.report_id}")

        # Step 5: Build Word document
        output_path = self._word_service.generate_docx(generated_report, daily_input)
        generated_report.output_path = str(output_path)
        generated_report.status = ReportStatus.COMPLETED

        # Step 6: Upload to Drive and clean local files if enabled
        if settings.drive_enabled:
            try:
                from app.services.drive_service import DriveService
                drive_svc = DriveService()
                
                drive_url = drive_svc.upload_report(output_path)
                logger.info(f"☁️  Report uploaded to Drive: {drive_url}")
                if output_path.exists():
                    output_path.unlink()
                    logger.info("🗑️  Deleted local .docx file (Cloud-only mode)")

                json_path = self._data_service._resolve_path(target_date, request.report_type)
                if json_path.exists():
                    drive_svc.upload_daily_input(json_path)
                    json_path.unlink()
                    logger.info("🗑️  Deleted local .json file (Cloud-only mode)")
                    
                message = f"Report saved in Google Drive: {output_path.name} | URL: {drive_url}"
                
            except Exception as e:
                logger.warning(f"Drive upload failed (files saved locally): {e}")
                message = f"Report generated locally: {output_path.name} (Upload failed)"
        else:
            message = f"Report generated locally: {output_path.name}"

        logger.info("✅ Report generation pipeline complete.")

        # Step 7: Cleanup input images
        self._cleanup_input_images()

        return GenerateReportResponse(
            success=True,
            report_id=generated_report.report_id,
            output_path=str(output_path),
            message=message,
        )

    def _cleanup_input_images(self) -> None:
        """Moves processed images in Drive to repository, then deletes local copies."""
        input_dir = settings.input_images_path
        
        # Clean up Drive first if enabled
        if settings.drive_enabled and getattr(settings, "drive_input_images_folder_id", "") and getattr(settings, "drive_repository_images_folder_id", ""):
            try:
                from app.services.drive_service import DriveService
                moved_drive = DriveService().move_input_images_to_repo()
                if moved_drive > 0:
                    logger.info(f"☁️  Moved {moved_drive} processed image(s) to Drive repository")
            except Exception as e:
                logger.warning(f"Failed to move images in Drive: {e}")

        if not input_dir.exists():
            return
            
        deleted_count = 0
        for img in input_dir.iterdir():
            if img.is_file() and img.suffix.lower() in ('.png', '.jpg', '.jpeg'):
                try:
                    img.unlink()
                    deleted_count += 1
                except Exception as e:
                    logger.warning(f"Failed to delete local image {img.name}: {e}")
                
        if deleted_count > 0:
            logger.info(f"🧹 Deleted {deleted_count} processed local image(s) from {input_dir.name}")

    async def _sync_input_from_drive(self, target_date: date, report_type: str) -> str:
        """Download daily input JSON from Drive before processing."""
        try:
            from app.services.drive_service import DriveService
            DriveService().download_daily_input(target_date, report_type)
            logger.info(f"☁️  Daily input synced from Drive: {target_date}_{report_type}.json")
        except FileNotFoundError as e:
            logger.warning(f"Daily input not in Drive, will try local: {e}")
        except Exception as e:
            logger.warning(f"Drive sync failed, will try local: {e}")
        return ""
