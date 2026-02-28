from __future__ import annotations

import asyncio
from datetime import date

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings
from app.models.report_model import GenerateReportRequest, ReportType
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


class SchedulerService:
    """
    Wraps APScheduler. Registered in FastAPI lifespan.
    """

    def __init__(self):
        self._scheduler = BackgroundScheduler(
            timezone=settings.scheduler_timezone
        )
        self._configure_jobs()

    def start(self) -> None:
        self._scheduler.start()
        logger.info(
            f"⏰ Scheduler started. Daily generation at "
            f"{settings.scheduler_hour:02d}:{settings.scheduler_minute:02d} "
            f"({settings.scheduler_timezone})"
        )

    def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)
        logger.info("⏹  Scheduler stopped")

    def _configure_jobs(self) -> None:
        # Daily functional test report
        self._scheduler.add_job(
            func=self._run_daily_generation,
            trigger=CronTrigger(
                hour=settings.scheduler_hour,
                minute=settings.scheduler_minute,
                timezone=settings.scheduler_timezone,
            ),
            id="daily_functional_tests",
            name="Daily Functional Tests Report",
            replace_existing=True,
            misfire_grace_time=3600,  # tolerate up to 1h delay
        )

    @staticmethod
    def _run_daily_generation() -> None:
        """
        Called by APScheduler in a background thread.
        Creates a new event loop for async code.
        """
        from app.mcp.tools.generate_report_tool import GenerateReportTool

        logger.info("⏰ Scheduler triggered daily report generation")
        try:
            tool = GenerateReportTool()
            request = GenerateReportRequest(
                report_date=date.today(),
                report_type=ReportType.FUNCTIONAL_TESTS,
            )
            # APScheduler runs sync; wrap async in new loop
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(tool.execute(request))
            loop.close()
            logger.info(f"✅ Scheduled report completed: {result.output_path}")
        except Exception as e:
            logger.error(f"❌ Scheduled report failed: {e}", exc_info=True)
