import pytest
from datetime import date
from unittest.mock import patch, PropertyMock
from app.models.report_model import DailyInput, ReportType, TestCaseResult


def make_input(tmp_path):
    return DailyInput(
        report_date=date(2025, 1, 15),
        report_type=ReportType.FUNCTIONAL_TESTS,
        project_name="Test Project",
        prepared_by="QA",
        test_cases=[TestCaseResult(test_id="TC-001", test_name="Login", module="Auth", status="PASS")],
    )


class TestDataServiceRoundtrip:
    def test_save_and_load(self, tmp_path):
        with patch("app.services.data_service.settings") as mock_s:
            mock_s.daily_inputs_dir = str(tmp_path)
            from app.services.data_service import DataService
            svc = DataService()
            svc.save_daily_input(make_input(tmp_path))
            loaded = svc.load_daily_input(date(2025, 1, 15), ReportType.FUNCTIONAL_TESTS)
            assert loaded.project_name == "Test Project"
            assert loaded.test_cases[0].test_id == "TC-001"

    def test_raises_for_missing_date(self, tmp_path):
        with patch("app.services.data_service.settings") as mock_s:
            mock_s.daily_inputs_dir = str(tmp_path)
            from app.services.data_service import DataService
            svc = DataService()
            with pytest.raises(FileNotFoundError):
                svc.load_daily_input(date(2099, 12, 31), ReportType.FUNCTIONAL_TESTS)
