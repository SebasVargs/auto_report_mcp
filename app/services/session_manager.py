"""
session_manager.py
------------------
Manages a persistent checkpoint file (.report_session.json) so that if the
computer crashes or freezes during report generation, the user can resume
from the last completed test case instead of starting over.

Usage in cli.py:
    session = ReportSessionManager()

    # Check at startup
    if session.exists():
        data = session.load()

    # Save after each test case
    session.save(metadata, image_names, completed_cases)

    # Clear after successful report generation
    session.clear()
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


# Session file lives at the project root next to cli.py / .env
_SESSION_FILE = Path(__file__).parent.parent.parent / ".report_session.json"


class ReportSessionManager:
    """Checkpoint manager for the interactive report generation flow."""

    def __init__(self, session_path: Path | None = None) -> None:
        self._path = session_path or _SESSION_FILE

    # ─────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────

    def exists(self) -> bool:
        """Return True if there is a session file on disk."""
        return self._path.exists()

    def save(
        self,
        metadata: dict,
        image_names: list[str],
        completed_cases: list[dict],
    ) -> None:
        """
        Persist the current progress to disk.

        Called immediately after every test case is submitted so that
        even a crash right after will not lose that case.
        """
        payload = {
            "session_id": metadata.get("report_date", "unknown"),
            "report_type": metadata.get("report_type", "functional_tests"),
            "metadata": metadata,
            "image_names": image_names,
            "completed_cases": completed_cases,
            "last_saved_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self) -> dict:
        """
        Load and return the session payload.

        Returns an empty dict if the file does not exist or is corrupt.
        """
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def clear(self) -> None:
        """Delete the session file (called after a successful report generation)."""
        try:
            self._path.unlink(missing_ok=True)
        except OSError:
            pass  # non-fatal — file may already be gone

    # ─────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────

    @property
    def path(self) -> Path:
        return self._path

    def summary(self) -> str:
        """
        Return a human-readable one-liner with session progress, e.g.:
            '8 de 16 casos completados  |  proyecto: MiApp  |  guardado: 2026-03-02T17:10:43'
        """
        data = self.load()
        if not data:
            return "(sin sesión guardada)"
        completed = len(data.get("completed_cases", []))
        total = len(data.get("image_names", []))
        project = data.get("metadata", {}).get("project_name", "—")
        saved_at = data.get("last_saved_at", "—")
        return (
            f"{completed} de {total} casos completados  "
            f"|  proyecto: {project}  "
            f"|  guardado: {saved_at}"
        )
