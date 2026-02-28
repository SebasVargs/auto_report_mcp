import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.mcp.tools.generate_report_tool import GenerateReportTool
from app.models.report_model import GenerateReportRequest, ReportType
from app.utils.logger import get_logger

logger = get_logger("run_daily_generation")


async def main():
    parser = argparse.ArgumentParser(description="Generate a report for a given date")
    parser.add_argument(
        "--date",
        type=str,
        default=str(date.today()),
        help="Date in YYYY-MM-DD format (default: today)",
    )
    parser.add_argument(
        "--type",
        type=str,
        default="functional_tests",
        choices=[t.value for t in ReportType],
        help="Report type",
    )
    args = parser.parse_args()

    target_date = date.fromisoformat(args.date)
    report_type = ReportType(args.type)

    logger.info(f"Generating {report_type.value} report for {target_date}")

    tool = GenerateReportTool()
    result = await tool.execute(
        GenerateReportRequest(report_date=target_date, report_type=report_type)
    )

    if result.success:
        print(f"\n✅ Report generated successfully!")
        print(f"   Report ID:   {result.report_id}")
        print(f"   Output path: {result.output_path}")
        print(f"   Generated:   {result.generated_at}")
    else:
        print(f"\n❌ Report generation failed: {result.message}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
