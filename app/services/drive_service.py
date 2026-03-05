from __future__ import annotations

import io
import json
from datetime import date
from pathlib import Path
from typing import Optional

import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/drive"]


class DriveService:
    """
    Handles all Google Drive interactions for auto-report-mcp.

    Responsibilities:
    - Download .docx historical reports from Drive (raw_reports folder)
    - Download daily input JSON files from Drive (daily_inputs folder)
    - Upload generated .docx reports to Drive (output_reports folder)
    - Download context report .docx files for knowledge ingestion (context_reports folder)

    Usage is transparent: files are downloaded to local temp dirs,
    existing service logic remains unchanged.
    """

    def __init__(self):
        settings = get_settings()
        self._settings = settings

        creds      = None
        token_path = Path("token.json")
        client_secret_path = Path("client_secret.json")

        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), _SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not client_secret_path.exists():
                    raise FileNotFoundError(
                        "client_secret.json no encontrado. Asegúrate de colocar el archivo "
                        "descargado de Google Cloud en la raíz del proyecto."
                    )
                flow  = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), _SCOPES)
                creds = flow.run_local_server(port=0)

            with open(token_path, "w") as token:
                token.write(creds.to_json())

        self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
        logger.info("DriveService initialized — connected via OAuth2 (User Account)")

    # ─────────────────────────────────────────────────
    # Download helpers
    # ─────────────────────────────────────────────────

    def sync_raw_reports(self, local_dir: Optional[Path] = None) -> list[Path]:
        """
        Download all .docx files from the raw_reports Drive folder
        into local_dir (defaults to settings.raw_reports_dir).
        Skips files already present locally with the same name.
        Returns list of local paths that were downloaded.
        """
        target = local_dir or Path(self._settings.raw_reports_dir)
        target.mkdir(parents=True, exist_ok=True)

        folder_id = self._settings.drive_raw_reports_folder_id
        files = self._list_files(
            folder_id,
            mime_filter="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        downloaded: list[Path] = []
        for f in files:
            local_path = target / f["name"]
            if local_path.exists():
                logger.debug(f"⏭  Skipping (exists locally): {f['name']}")
                continue
            self._download_file(f["id"], local_path)
            downloaded.append(local_path)
            logger.info(f"⬇️  Downloaded from Drive: {f['name']}")

        logger.info(
            f"sync_raw_reports: {len(downloaded)} new files, "
            f"{len(files) - len(downloaded)} already local"
        )
        return downloaded

    def sync_context_reports(self, local_dir: Optional[Path] = None) -> list[Path]:
        """
        Download all .docx (and native Google Docs exported as .docx) from the
        context_reports Drive folder (DRIVE_CONTEXT_REPORTS_FOLDER_ID) into
        local_dir (defaults to settings.context_reports_dir).
        Skips files already present locally.
        Returns list of Paths for newly downloaded files.
        """
        target = local_dir or Path(self._settings.context_reports_dir)
        target.mkdir(parents=True, exist_ok=True)

        folder_id = getattr(self._settings, "drive_context_reports_folder_id", "")
        if not folder_id:
            logger.warning("No drive_context_reports_folder_id configured.")
            return []

        valid_mimes = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.google-apps.document",
        )

        files      = self._list_files(folder_id)
        files      = [f for f in files if f.get("mimeType") in valid_mimes]
        downloaded: list[Path] = []

        for f in files:
            # Google Docs exported as .docx get a .docx suffix appended if missing
            name       = f["name"]
            mime       = f.get("mimeType", "")
            local_name = name if name.endswith(".docx") else f"{name}.docx"
            local_path = target / local_name

            if local_path.exists():
                logger.debug(f"⏭  Skipping context report (exists locally): {local_name}")
                continue

            self._download_file(f["id"], local_path, mime_type=mime)
            downloaded.append(local_path)
            logger.info(f"⬇️  Downloaded context report: {local_name}")

        if downloaded:
            logger.info(f"sync_context_reports: {len(downloaded)} new file(s) downloaded.")
        return downloaded

    def download_daily_input(
        self,
        report_date: date,
        report_type: str,
        local_dir: Optional[Path] = None,
    ) -> Path:
        """
        Download the daily input JSON for a given date+type from Drive.
        Filename convention: YYYY-MM-DD_{report_type}.json
        Returns the local path where the file was saved.
        Raises FileNotFoundError if the file doesn't exist in Drive.
        """
        filename  = f"{report_date}_{report_type}.json"
        target    = local_dir or Path(self._settings.daily_inputs_dir)
        target.mkdir(parents=True, exist_ok=True)
        local_path = target / filename

        folder_id = self._settings.drive_daily_inputs_folder_id
        files     = self._list_files(folder_id, name_filter=filename)

        if not files:
            raise FileNotFoundError(
                f"Daily input '{filename}' not found in Drive folder {folder_id}. "
                "Upload it to Drive and try again."
            )

        self._download_file(files[0]["id"], local_path)
        logger.info(f"⬇️  Downloaded daily input from Drive: {filename}")
        return local_path

    # ─────────────────────────────────────────────────
    # Upload helpers
    # ─────────────────────────────────────────────────

    def upload_report(self, local_path: Path) -> str:
        """
        Upload a generated .docx report to the output_reports Drive folder.
        Returns the Drive file URL.
        """
        folder_id = self._settings.drive_output_folder_id
        existing  = self._list_files(folder_id)
        existing_id = next(
            (f["id"] for f in existing if f["name"] == local_path.name), None
        )

        media = MediaFileUpload(
            str(local_path),
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            resumable=True,
        )

        if existing_id:
            result = (
                self._service.files()
                .update(
                    fileId=existing_id,
                    media_body=media,
                    fields="id,webViewLink",
                    supportsAllDrives=True,
                )
                .execute()
            )
        else:
            file_metadata = {"name": local_path.name, "parents": [folder_id]}
            result = (
                self._service.files()
                .create(
                    body=file_metadata,
                    media_body=media,
                    fields="id,webViewLink",
                    supportsAllDrives=True,
                )
                .execute()
            )

        url = result.get("webViewLink", "")
        logger.info(f"⬆️  Uploaded to Drive: {local_path.name} → {url}")
        return url

    def upload_daily_input(self, local_path: Path) -> str:
        """
        Upload a generated daily input .json file to the daily_inputs Drive folder.
        Returns the Drive file URL.
        """
        folder_id   = self._settings.drive_daily_inputs_folder_id
        existing    = self._list_files(folder_id)
        existing_id = next(
            (f["id"] for f in existing if f["name"] == local_path.name), None
        )

        media = MediaFileUpload(str(local_path), mimetype="application/json", resumable=True)

        if existing_id:
            result = (
                self._service.files()
                .update(
                    fileId=existing_id,
                    media_body=media,
                    fields="id,webViewLink",
                    supportsAllDrives=True,
                )
                .execute()
            )
        else:
            file_metadata = {"name": local_path.name, "parents": [folder_id]}
            result = (
                self._service.files()
                .create(
                    body=file_metadata,
                    media_body=media,
                    fields="id,webViewLink",
                    supportsAllDrives=True,
                )
                .execute()
            )

        url = result.get("webViewLink", "")
        logger.info(f"⬆️  Uploaded daily input to Drive: {local_path.name} → {url}")
        return url

    def sync_input_images(self, local_dir: Optional[Path] = None) -> dict[Path, str]:
        """
        Download all image files from the input_images Drive folder.
        Returns a dict mapping the local Path to the Drive file ID.
        """
        target = local_dir or Path(self._settings.input_images_dir)
        target.mkdir(parents=True, exist_ok=True)

        folder_id = self._settings.drive_input_images_folder_id
        if not folder_id:
            return {}

        files   = self._list_files(folder_id, mime_filter="")
        mapping: dict[Path, str] = {}

        for f in files:
            mime = f.get("mimeType", "")
            if not mime.startswith("image/"):
                continue
            local_path = target / f["name"]
            self._download_file(f["id"], local_path)
            mapping[local_path] = f["id"]
            logger.info(f"⬇️  Downloaded image from Drive: {f['name']}")

        return mapping

    def move_file(self, file_id: str, new_parent_id: str) -> None:
        """Move a file in Google Drive to a new folder."""
        if not new_parent_id:
            return
        file = (
            self._service.files()
            .get(fileId=file_id, fields="parents", supportsAllDrives=True)
            .execute()
        )
        previous_parents = ",".join(file.get("parents", []))
        self._service.files().update(
            fileId=file_id,
            addParents=new_parent_id,
            removeParents=previous_parents,
            fields="id, parents",
            supportsAllDrives=True,
        ).execute()
        logger.info(f"🚚 Moved Drive file {file_id} to folder {new_parent_id}")

    def move_input_images_to_repo(self) -> int:
        """Moves all image files from the input_images folder to repository_images in Drive."""
        folder_in   = self._settings.drive_input_images_folder_id
        folder_repo = self._settings.drive_repository_images_folder_id
        if not folder_in or not folder_repo:
            return 0

        files = self._list_files(folder_in)
        count = 0
        for f in files:
            if not f.get("mimeType", "").startswith("image/"):
                continue
            self.move_file(f["id"], folder_repo)
            count += 1
        return count

    # ─────────────────────────────────────────────────
    # Knowledge Base Backup / Restore
    # ─────────────────────────────────────────────────

    def backup_knowledge(self) -> str:
        """
        Creates a timestamped .zip of the vector_db directory and the knowledge
        registry file, then uploads it to the Drive backup folder.

        Returns the Drive webViewLink of the uploaded backup.
        Raises ValueError when DRIVE_KNOWLEDGE_BACKUP_FOLDER_ID is not configured.
        """
        import shutil
        import tempfile
        from datetime import datetime, timezone

        folder_id = getattr(self._settings, "drive_knowledge_backup_folder_id", "")
        if not folder_id:
            raise ValueError(
                "DRIVE_KNOWLEDGE_BACKUP_FOLDER_ID no está configurado en el .env. "
                "Crea una carpeta en Drive para backups y agrega su ID."
            )

        now_label = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_name = f"knowledge_backup_{now_label}"

        with tempfile.TemporaryDirectory() as tmp:
            stage_dir = Path(tmp) / backup_name
            stage_dir.mkdir()

            # Copy vector_db/
            vector_db = Path(self._settings.chroma_persist_dir)
            if vector_db.exists():
                shutil.copytree(str(vector_db), str(stage_dir / "vector_db"))

            # Copy knowledge registry JSON
            registry = Path("./data/knowledge_processed.json")
            if registry.exists():
                shutil.copy2(str(registry), str(stage_dir / "knowledge_processed.json"))

            # Zip everything
            zip_base = Path(tmp) / backup_name
            zip_path = Path(shutil.make_archive(str(zip_base), "zip", tmp, backup_name))

            # Upload to Drive
            media = MediaFileUpload(
                str(zip_path),
                mimetype="application/zip",
                resumable=True,
            )
            file_metadata = {
                "name": zip_path.name,
                "parents": [folder_id],
            }
            result = (
                self._service.files()
                .create(
                    body=file_metadata,
                    media_body=media,
                    fields="id,webViewLink",
                    supportsAllDrives=True,
                )
                .execute()
            )

        url = result.get("webViewLink", "")
        logger.info(f"☁️  Knowledge backup uploaded: {zip_path.name} → {url}")
        return url

    def list_knowledge_backups(self) -> list[dict]:
        """
        List all knowledge backup zips in the Drive backup folder,
        ordered by name descending (most recent first).
        """
        folder_id = getattr(self._settings, "drive_knowledge_backup_folder_id", "")
        if not folder_id:
            return []
        files = self._list_files(folder_id, mime_filter="application/zip")
        return sorted(files, key=lambda f: f.get("name", ""), reverse=True)

    def restore_knowledge(self, file_id: str, file_name: str) -> None:
        """
        Download a backup zip from Drive and restore it to the local paths:
        - vector_db/ (the ChromaDB persistence directory)
        - data/knowledge_processed.json (the ingestion registry)

        WARNING: existing local data will be overwritten.
        """
        import shutil
        import tempfile
        import zipfile

        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / file_name
            self._download_file(file_id, zip_path)

            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmp)

            # The zip contains a folder named like "knowledge_backup_YYYYMMDD_HHMMSS"
            extracted_dirs = [d for d in Path(tmp).iterdir() if d.is_dir()]
            if not extracted_dirs:
                raise FileNotFoundError("El archivo de backup está vacío o tiene un formato inesperado.")
            source = extracted_dirs[0]

            # Restore vector_db
            src_vdb = source / "vector_db"
            dst_vdb = Path(self._settings.chroma_persist_dir)
            if src_vdb.exists():
                if dst_vdb.exists():
                    shutil.rmtree(dst_vdb)
                shutil.copytree(str(src_vdb), str(dst_vdb))
                logger.info(f"✅ vector_db/ restored from {file_name}")

            # Restore registry
            src_reg = source / "knowledge_processed.json"
            dst_reg = Path("./data/knowledge_processed.json")
            if src_reg.exists():
                dst_reg.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src_reg), str(dst_reg))
                logger.info(f"✅ knowledge_processed.json restored from {file_name}")

    # ─────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────

    def _list_files(
        self,
        folder_id: str,
        mime_filter: str = "",
        name_filter: str = "",
    ) -> list[dict]:
        """List files in a Drive folder with optional mime/name filters."""
        query = f"'{folder_id}' in parents and trashed = false"
        if mime_filter:
            query += f" and mimeType = '{mime_filter}'"
        if name_filter:
            query += f" and name = '{name_filter}'"

        results = (
            self._service.files()
            .list(
                q=query,
                fields="files(id, name, mimeType, modifiedTime)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        return results.get("files", [])

    def _download_file(self, file_id: str, dest: Path, mime_type: str = "") -> None:
        """
        Download a Drive file by ID to a local path.
        If it's a native Google Doc, export it as .docx.
        """
        if mime_type == "application/vnd.google-apps.document":
            request = self._service.files().export_media(
                fileId=file_id,
                mimeType="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            if dest.suffix != ".docx":
                dest = dest.with_name(f"{dest.name}.docx")
        else:
            request = self._service.files().get_media(
                fileId=file_id, supportsAllDrives=True
            )

        buf        = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done       = False
        while not done:
            _, done = downloader.next_chunk()
        dest.write_bytes(buf.getvalue())