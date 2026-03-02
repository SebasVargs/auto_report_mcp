from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────

class ReportType(str, Enum):
    FUNCTIONAL_TESTS   = "functional_tests"
    INTEGRATION_TESTS  = "integration_tests"
    UNIT_TESTS         = "unit_tests"
    PROJECT_PROGRESS   = "project_progress"


class ReportStatus(str, Enum):
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


# ─────────────────────────────────────────────────
# Daily Input Schema
# ─────────────────────────────────────────────────

class TestCaseResult(BaseModel):
    """Individual test execution result."""
    test_id: str
    test_name: str
    module: str
    status: str  # PASS | FAIL | BLOCKED | SKIP
    execution_time_s: float = 0.0
    defects: list[str] = Field(default_factory=list)
    notes: str = ""

    # Common narrative fields
    description: str = ""
    prepared_by: str = ""
    prepare_date: str = ""
    tested_by: str = ""
    test_date: str = ""
    preconditions: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    expected_results: list[str] = Field(default_factory=list)
    actual_results: list[str] = Field(default_factory=list)
    evidence_image_filename: str = ""

    # ── Black-Box fields (functional_tests + integration_tests) ──
    test_technique: str = ""          # ej. partición equivalencia, valores límite
    test_level: str = ""              # Acceptance / System / Integration / Unit
    input_data: list[str] = Field(default_factory=list)  # datos de entrada específicos

    # ── White-Box fields (integration_tests + unit_tests) ────────
    covered_method: str = ""          # método o endpoint bajo prueba
    covered_class: str = ""           # clase o módulo (ruta)
    coverage_type: str = ""           # branch / statement / condition / path
    coverage_pct: float = 0.0         # % de cobertura logrado
    test_framework: str = ""          # pytest / JUnit / Mocha / etc.


class ProjectTask(BaseModel):
    """Task progress entry for project reports."""
    task_id: str
    title: str
    assignee: str
    status: str  # TODO | IN_PROGRESS | DONE | BLOCKED
    progress_pct: int = Field(ge=0, le=100)
    sprint: str = ""
    blockers: list[str] = Field(default_factory=list)
    notes: str = ""


class DailyInput(BaseModel):
    """
    Structured daily data consumed by data_service.py.
    Stored as JSON in data/daily_inputs/YYYY-MM-DD.json
    """
    report_date: date
    report_type: ReportType
    project_name: str
    project_version: str = ""
    environment: str = "QA"
    prepared_by: str

    # Functional Tests
    test_cases: list[TestCaseResult] = Field(default_factory=list)

    # Project Progress
    tasks: list[ProjectTask] = Field(default_factory=list)
    general_notes: str = ""
    risks: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)

    @field_validator("report_date", mode="before")
    @classmethod
    def parse_date(cls, v: Any) -> date:
        if isinstance(v, str):
            return date.fromisoformat(v)
        return v


# ─────────────────────────────────────────────────
# RAG / Style context
# ─────────────────────────────────────────────────

class StyleChunk(BaseModel):
    """A retrieved chunk from the vector store."""
    chunk_id: str
    source_document: str
    content: str
    relevance_score: float
    section_type: str = ""  # intro | body | conclusions | summary


class StyleContext(BaseModel):
    """Aggregated style context passed to ai_service."""
    chunks: list[StyleChunk]
    total_tokens_estimate: int = 0

    @property
    def as_context_string(self) -> str:
        return "\n\n---\n\n".join(
            f"[{c.section_type.upper() or 'FRAGMENT'}]\n{c.content}"
            for c in self.chunks
        )


# ─────────────────────────────────────────────────
# Generated Report
# ─────────────────────────────────────────────────

class ReportSection(BaseModel):
    """A rendered section of the final report."""
    title: str
    content: str
    section_order: int


class GeneratedReport(BaseModel):
    """Full generated report before Word rendering."""
    report_id: str = Field(default_factory=lambda: str(uuid4()))
    report_date: date
    report_type: ReportType
    project_name: str
    environment: str

    executive_summary: str
    sections: list[ReportSection]
    conclusions: str
    next_steps: list[str]

    generated_at: datetime = Field(default_factory=datetime.utcnow)
    output_path: str = ""
    status: ReportStatus = ReportStatus.PENDING

    model_config = {"use_enum_values": True}


# ─────────────────────────────────────────────────
# MCP Tool Request/Response models
# ─────────────────────────────────────────────────

class GenerateReportRequest(BaseModel):
    report_date: date | None = None  # defaults to today
    report_type: ReportType = ReportType.FUNCTIONAL_TESTS
    force_regenerate: bool = False
    skip_drive_sync: bool = False


class GenerateReportResponse(BaseModel):
    success: bool
    report_id: str
    output_path: str
    message: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
