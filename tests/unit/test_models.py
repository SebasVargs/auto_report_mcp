import pytest
from datetime import date
from app.models.report_model import (
    DailyInput, ReportType, TestCaseResult, ProjectTask,
    StyleChunk, StyleContext,
)

class TestDailyInputValidation:
    def test_valid_functional_test_input(self):
        data = DailyInput(
            report_date=date(2025, 1, 15),
            report_type=ReportType.FUNCTIONAL_TESTS,
            project_name="Test Project",
            prepared_by="QA Team",
            test_cases=[
                TestCaseResult(test_id="TC-001", test_name="Login", module="Auth", status="PASS")
            ],
        )
        assert data.report_type == ReportType.FUNCTIONAL_TESTS
        assert len(data.test_cases) == 1

    def test_task_progress_out_of_bounds(self):
        with pytest.raises(Exception):
            ProjectTask(task_id="T1", title="Task", assignee="Dev", status="DONE", progress_pct=150)

    def test_date_parsing_from_string(self):
        data = DailyInput(
            report_date="2025-01-15",
            report_type=ReportType.PROJECT_PROGRESS,
            project_name="Project",
            prepared_by="PM",
        )
        assert data.report_date == date(2025, 1, 15)


class TestStyleContext:
    def test_as_context_string_has_section_labels(self):
        context = StyleContext(chunks=[
            StyleChunk(chunk_id="1", source_document="x.docx", content="Texto A", relevance_score=0.9, section_type="summary"),
            StyleChunk(chunk_id="2", source_document="x.docx", content="Texto B", relevance_score=0.8, section_type="body"),
        ])
        result = context.as_context_string
        assert "[SUMMARY]" in result
        assert "[BODY]" in result
