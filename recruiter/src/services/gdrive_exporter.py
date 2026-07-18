# Service for packaging job run results and exporting them to the project owner's Google Drive.
#
# It resolves serial numbers per role per day, structures all run outputs
# (JD, subqueries, parsed resumes, ranking tables, and scoring traces),
# and uses the Google Drive REST API to upload them dynamically.

import datetime
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests

logger = logging.getLogger(__name__)

# Base directories
ROOT = Path(__file__).resolve().parent.parent.parent
EXPORT_DIR = ROOT / "recruiter" / "data" / "export"
JOBS_DIR = ROOT / "recruiter" / "data" / "jobs"
JD_DIR = ROOT / "recruiter" / "data" / "job_descriptions"
PROCESSED_DIR = ROOT / "recruiter" / "data" / "processed"
SCORES_DIR = ROOT / "recruiter" / "data" / "scores" / "composed"


class GoogleDriveUploader:
    """Handles folder creation and file uploads to Google Drive via lightweight REST API calls."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        parent_folder_id: str,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.parent_folder_id = parent_folder_id
        self.access_token: Optional[str] = None

    def refresh_access_token(self) -> None:
        """Obtain a short-lived access token using the refresh token."""
        logger.info("GDrive: refreshing access token...")
        url = "https://oauth2.googleapis.com/token"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
        }
        resp = requests.post(url, data=payload, timeout=30)
        resp.raise_for_status()
        self.access_token = resp.json()["access_token"]
        logger.info("GDrive: successfully authenticated access token.")

    def create_folder(self, name: str, parent_id: str) -> str:
        """Create a folder on Google Drive and return its ID."""
        logger.info("GDrive: creating remote folder '%s' under parent '%s'...", name, parent_id)
        url = "https://www.googleapis.com/drive/v3/files"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        body = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        }
        resp = requests.post(url, headers=headers, json=body, timeout=30)
        resp.raise_for_status()
        folder_id = resp.json()["id"]
        logger.info("GDrive: created folder '%s' (ID: %s).", name, folder_id)
        return folder_id

    def upload_file(self, file_path: Path, parent_id: str) -> str:
        """Upload a local file to a Google Drive folder and return its ID."""
        logger.info("GDrive: uploading file '%s'...", file_path.name)
        url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
        }
        
        metadata = {
            "name": file_path.name,
            "parents": [parent_id],
        }
        
        # Read file contents
        with file_path.open("rb") as f:
            file_data = f.read()

        # Build multipart payload
        files = {
            "metadata": ("metadata", json.dumps(metadata), "application/json; charset=UTF-8"),
            "file": (file_path.name, file_data, "application/octet-stream"),
        }
        
        resp = requests.post(url, headers=headers, files=files, timeout=60)
        resp.raise_for_status()
        file_id = resp.json()["id"]
        logger.info("GDrive: successfully uploaded '%s' (ID: %s).", file_path.name, file_id)
        return file_id

    def upload_directory_recursive(self, local_dir: Path, remote_parent_id: str) -> None:
        """Recursively upload a local directory to Google Drive."""
        remote_folder_id = self.create_folder(local_dir.name, remote_parent_id)
        
        for item in local_dir.iterdir():
            if item.is_dir():
                self.upload_directory_recursive(item, remote_folder_id)
            elif item.is_file():
                self.upload_file(item, remote_folder_id)


def package_and_export_job_run(slug: str, job_log: Optional[List[str]] = None) -> None:
    """Pack all JDs, subqueries, resumes, scores, and rankings, and export to GDrive.

    Args:
        slug: Role slug (e.g. "civilengineer").
        job_log: Reference to background job logs list for writing pipeline updates.
    """
    def log_update(msg: str):
        logger.info("[%s] Export: %s", slug, msg)
        if job_log is not None:
            job_log.append(f"Export: {msg}")

    log_update("Initializing job dataset packaging...")
    
    # 1. Resolve role name from metadata
    meta_file = JOBS_DIR / slug / "metadata.json"
    role_name = slug
    if meta_file.exists():
        try:
            with meta_file.open("r", encoding="utf-8") as f:
                meta = json.load(f)
            role_name = meta.get("role_name", slug)
        except Exception as e:
            logger.warning("Failed to parse metadata for role name override: %s", e)

    # 2. Compute date and next serial number
    # Format: civil_engineer_YYYYMMDD_N
    normalized_role = role_name.lower().replace(" ", "_")
    date_str = datetime.datetime.now().strftime("%Y%m%d")
    
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    
    existing_serials = []
    for child in EXPORT_DIR.iterdir():
        if child.is_dir() and child.name.startswith(f"{normalized_role}_{date_str}_"):
            parts = child.name.split("_")
            if parts:
                try:
                    existing_serials.append(int(parts[-1]))
                except ValueError:
                    pass
                    
    serial = max(existing_serials) + 1 if existing_serials else 1
    folder_name = f"{normalized_role}_{date_str}_{serial}"
    dest_dir = EXPORT_DIR / folder_name
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    log_update(f"Packaging files locally to data/export/{folder_name} ...")

    # 3. Create subdirectories
    resumes_dest = dest_dir / "resumes"
    scores_dest = dest_dir / "scores"
    resumes_dest.mkdir(exist_ok=True)
    scores_dest.mkdir(exist_ok=True)

    # 4. Copy matching files
    # A. Job Metadata and extracted JD/REQs
    job_src = JOBS_DIR / slug
    if job_src.exists():
        for file_name in ["jd.md", "requirements.json", "subqueries.json", "metadata.json"]:
            src_file = job_src / file_name
            if src_file.exists():
                shutil.copy(src_file, dest_dir / file_name)

    # B. SubQuery Markdown definition
    sq_file = JD_DIR / slug / f"{slug}_SubQuery.md"
    if sq_file.exists():
        shutil.copy(sq_file, dest_dir / f"{slug}_SubQuery.md")

    # C. Processed candidate resumes (JSON)
    proc_src = PROCESSED_DIR / slug
    if proc_src.exists():
        for item in proc_src.iterdir():
            if item.is_file() and item.suffix == ".json":
                shutil.copy(item, resumes_dest / item.name)

    # D. Final candidate rankings
    ranked_file = SCORES_DIR / f"{slug}_ranked.json"
    if ranked_file.exists():
        shutil.copy(ranked_file, dest_dir / f"{slug}_ranked.json")

    # D2. RAG evaluation report (correctness audit)
    eval_file = SCORES_DIR / f"{slug}_rag_evaluation.json"
    if eval_file.exists():
        shutil.copy(eval_file, dest_dir / f"{slug}_rag_evaluation.json")

    # E. Detailed candidate score traces
    traces_src = SCORES_DIR / slug
    if traces_src.exists():
        for item in traces_src.iterdir():
            if item.is_file() and item.suffix == ".json":
                shutil.copy(item, scores_dest / item.name)

    if job_log is not None:
        log_file = dest_dir / "scoring_run_log.txt"
        log_file.write_text("\n".join(job_log), encoding="utf-8")
    else:
        log_file = None

    log_update("✓ Locally packaged successfully.")

    def clean_folder_id_helper(val: Optional[str]) -> Optional[str]:
        if not val:
            return None
        val = val.strip()
        if "?" in val:
            val = val.partition("?")[0]
        if "/" in val:
            val = val.rstrip("/").split("/")[-1]
        return val

    # 5. Connect to Google Drive if environment variables are set
    client_id = os.getenv("OWNER_GDRIVE_CLIENT_ID")
    client_secret = os.getenv("OWNER_GDRIVE_CLIENT_SECRET")
    refresh_token = os.getenv("OWNER_GDRIVE_REFRESH_TOKEN")
    
    raw_user_data_folder = os.getenv("OWNER_GDRIVE_FOR_USER_DATA")
    if raw_user_data_folder:
        folder_id = clean_folder_id_helper(raw_user_data_folder)
    else:
        folder_id = os.getenv("OWNER_GDRIVE_FOLDER_ID")

    if all([client_id, client_secret, refresh_token, folder_id]):
        log_update("Connecting to owner's Google Drive...")
        try:
            uploader = GoogleDriveUploader(
                client_id=client_id,
                client_secret=client_secret,
                refresh_token=refresh_token,
                parent_folder_id=folder_id,
            )
            uploader.refresh_access_token()
            
            log_update(f"Uploading folder '{folder_name}' to Google Drive...")
            uploader.upload_directory_recursive(dest_dir, folder_id)

            # Upload session log directly to OWNER_GDRIVE_FOR_USER_LOGS folder if configured
            user_logs_folder = os.getenv("OWNER_GDRIVE_FOR_USER_LOGS")
            if user_logs_folder and log_file and log_file.exists():
                user_logs_folder_id = clean_folder_id_helper(user_logs_folder)
                if user_logs_folder_id:
                    log_update("Uploading user session log to dedicated logs folder...")
                    uploader.upload_file(log_file, user_logs_folder_id)

            # Sync SQLite DB to Google Drive
            try:
                from recruiter.src.services.gdrive_syncer import backup_db_to_gdrive
                backup_db_to_gdrive()
            except Exception as dbe:
                logger.warning("Failed to trigger DB backup from exporter: %s", dbe)
            
            log_update("✓ Upload complete. Cleaning up local export cache...")
            shutil.rmtree(dest_dir)
            log_update("✓ Local export folder cleaned up.")
        except Exception as exc:
            logger.exception("Google Drive upload failed")
            log_update(f"⚠ Google Drive upload failed: {exc}. Files preserved locally.")
    else:
        log_update(
            "Notice: OWNER_GDRIVE_* variables are not fully set in .env. "
            "Skipping Google Drive transfer. Files preserved locally."
        )
