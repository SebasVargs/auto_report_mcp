from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from app.config import get_settings
from app.models.report_model import DailyInput, ReportType
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


class DataService:
    """
    Loads and validates daily input data.
    Convention: data/daily_inputs/YYYY-MM-DD_{report_type}.json
    """

    def __init__(self):
        self._base_dir = Path(settings.daily_inputs_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def load_daily_input(
        self, target_date: date, report_type: ReportType
    ) -> DailyInput:
        """
        Load and validate daily input for a given date and report type.
        Raises FileNotFoundError if no input exists.
        """
        path = self._resolve_path(target_date, report_type)

        if not path.exists():
            raise FileNotFoundError(
                f"No daily input found for {target_date} / {report_type.value}. "
                f"Expected: {path}"
            )

        raw = json.loads(path.read_text(encoding="utf-8"))
        daily_input = DailyInput.model_validate(raw)
        logger.info(f"Loaded daily input from {path}")
        return daily_input

    def save_daily_input(self, daily_input: DailyInput) -> Path:
        """Persist a DailyInput as JSON (used by ingestion scripts / tests)."""
        path = self._resolve_path(daily_input.report_date, daily_input.report_type)
        path.write_text(
            daily_input.model_dump_json(indent=2), encoding="utf-8"
        )
        logger.info(f"Saved daily input to {path}")
        return path

    def list_available_inputs(self) -> list[Path]:
        return sorted(self._base_dir.glob("*.json"))

    def _resolve_path(self, target_date: date, report_type: ReportType | str) -> Path:
        # If the model holds a string instead of the enum due to use_enum_values=True
        rt_str = getattr(report_type, "value", str(report_type))
        filename = f"{target_date}_{rt_str}.json"
        return self._base_dir / filename
