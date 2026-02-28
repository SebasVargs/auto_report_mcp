from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.config import get_settings
from app.models.report_model import GeneratedReport
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


class SaveReportTool:
    """
    Persists a GeneratedReport as a JSON manifest alongside the .docx.
    Useful for audit trails and re-generation without AI calls.
    """

    def __init__(self):
        self._output_dir = Path(settings.output_reports_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def save_manifest(self, report: GeneratedReport) -> Path:
        """
        Save a JSON manifest of the generated report.
        Manifest contains all structured data (excluding the binary .docx).
        """
        filename = (
            f"{report.report_date}_{report.report_type}_{report.project_name}"
            .replace(" ", "_")
            .lower()
            + "_manifest.json"
        )
        path = self._output_dir / filename
        path.write_text(
            report.model_dump_json(indent=2),
            encoding="utf-8"
        )
        logger.info(f"Manifest saved: {path}")
        return path

    def list_manifests(self) -> list[dict]:
        """List all saved manifests ordered by date descending."""
        manifests = []
        for p in sorted(self._output_dir.glob("*_manifest.json"), reverse=True):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                manifests.append({"file": p.name, **data})
            except Exception:
                pass
        return manifests
