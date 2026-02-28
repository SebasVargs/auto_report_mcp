from datetime import date
from app.models.report_model import DailyInput, ReportType
from app.services.data_service import DataService


class FetchDailyDataTool:
    def execute(self, target_date: date, report_type: ReportType) -> DailyInput:
        return DataService().load_daily_input(target_date, report_type)
