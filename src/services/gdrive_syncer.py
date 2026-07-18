"""Service for syncing SQLite database and restoring candidate results from Google Drive."""

from __future__ import annotations

import datetime
import json
import logging
import os
import pathlib
import re
import shutil
from typing import Any, Dict, List, Optional
import requests

logger = logging.getLogger(__name__)

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
DATABASE_PATH = ROOT / "data" / "hireintel.db"

# Folders inside recruiter/data
JOBS_DIR = ROOT / "recruiter" / "data" / "jobs"
PROCESSED_DIR = ROOT / "recruiter" / "data" / "processed"
SCORES_DIR = ROOT / "recruiter" / "data" / "scores" / "composed"


def clean_folder_id(val: Optional[str]) -> Optional[str]:
    """Clean sharing link or folder ID to extract the exact ID token."""
    if not val:
        return None
    val = val.strip()
    if "?" in val:
        val = val.partition("?")[0]
    if "/" in val:
        val = val.rstrip("/").split("/")[-1]
    return val


class GoogleDriveStorage:
    """Wrapper around Google Drive API for download, search, and sync operations."""

    def __init__(self) -> None:
        self.client_id = os.getenv("OWNER_GDRIVE_CLIENT_ID")
        self.client_secret = os.getenv("OWNER_GDRIVE_CLIENT_SECRET")
        self.refresh_token = os.getenv("OWNER_GDRIVE_REFRESH_TOKEN")
        self.access_token: Optional[str] = None

    def is_configured(self) -> bool:
        """Check if essential OAuth credentials are present."""
        return bool(self.client_id and self.client_secret and self.refresh_token)

    def refresh_access_token(self) -> bool:
        """Authenticate or refresh the access token."""
        if not self.is_configured():
            return False
        try:
            url = "https://oauth2.googleapis.com/token"
            payload = {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            }
            resp = requests.post(url, data=payload, timeout=20)
            resp.raise_for_status()
            self.access_token = resp.json()["access_token"]
            return True
        except Exception as e:
            logger.warning("GDrive Storage: Auth refresh failed: %s", e)
            return False

    def get_headers(self) -> Dict[str, str]:
        """Return authorization headers."""
        return {"Authorization": f"Bearer {self.access_token}"}

    def search_file(self, name: str, parent_id: str) -> Optional[str]:
        """Find a file/folder under parent and return its ID."""
        if not self.refresh_access_token():
            return None
        try:
            url = "https://www.googleapis.com/drive/v3/files"
            q = f"name = '{name}' and '{parent_id}' in parents and trashed = false"
            params = {"q": q, "fields": "files(id)"}
            resp = requests.get(url, headers=self.get_headers(), params=params, timeout=20)
            resp.raise_for_status()
            files = resp.json().get("files", [])
            return files[0]["id"] if files else None
        except Exception as e:
            logger.warning("GDrive Storage: Search failed for '%s': %s", name, e)
            return None

    def upload_file_media(self, local_path: pathlib.Path, parent_id: str, remote_file_id: Optional[str] = None) -> Optional[str]:
        """Upload local file content to Google Drive (update if exists, else create)."""
        if not self.refresh_access_token():
            return None
        try:
            if not local_path.exists():
                return None
            
            with local_path.open("rb") as f:
                data = f.read()

            headers = self.get_headers()
            if remote_file_id:
                # Update existing file content
                url = f"https://www.googleapis.com/upload/drive/v3/files/{remote_file_id}?uploadType=media"
                resp = requests.patch(url, headers=headers, data=data, timeout=60)
                resp.raise_for_status()
                return remote_file_id
            else:
                # Create new file
                url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
                metadata = {
                    "name": local_path.name,
                    "parents": [parent_id]
                }
                files = {
                    "metadata": ("metadata", json.dumps(metadata), "application/json; charset=UTF-8"),
                    "file": (local_path.name, data, "application/octet-stream")
                }
                resp = requests.post(url, headers=headers, files=files, timeout=60)
                resp.raise_for_status()
                return resp.json()["id"]
        except Exception as e:
            logger.warning("GDrive Storage: File upload failed for '%s': %s", local_path.name, e)
            return None

    def download_file(self, file_id: str, dest_path: pathlib.Path) -> bool:
        """Download file content from Google Drive to local destination."""
        if not self.refresh_access_token():
            return False
        try:
            url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
            resp = requests.get(url, headers=self.get_headers(), timeout=60, stream=True)
            resp.raise_for_status()
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with dest_path.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            return True
        except Exception as e:
            logger.warning("GDrive Storage: File download failed for ID %s: %s", file_id, e)
            return False

    def list_files_in_folder(self, folder_id: str) -> List[Dict[str, Any]]:
        """List all files and folders immediately inside the parent folder."""
        if not self.refresh_access_token():
            return []
        try:
            url = "https://www.googleapis.com/drive/v3/files"
            q = f"'{folder_id}' in parents and trashed = false"
            params = {"q": q, "fields": "files(id, name, mimeType)", "pageSize": 1000}
            resp = requests.get(url, headers=self.get_headers(), params=params, timeout=20)
            resp.raise_for_status()
            return resp.json().get("files", [])
        except Exception as e:
            logger.warning("GDrive Storage: Folder listing failed for ID %s: %s", folder_id, e)
            return []


# ---------------------------------------------------------------------------
# High-level Sync Functions
# ---------------------------------------------------------------------------

def restore_db_from_gdrive() -> None:
    """Download db file from GDrive to restore runtime roles and configurations."""
    folder_id = clean_folder_id(os.getenv("OWNER_GDRIVE_FOR_USER_DATA"))
    if not folder_id:
        logger.info("GDrive Sync: OWNER_GDRIVE_FOR_USER_DATA not set. Skipping DB restore.")
        return

    storage = GoogleDriveStorage()
    db_file_id = storage.search_file("hireintel.db", folder_id)
    if db_file_id:
        logger.info("GDrive Sync: Restoring hireintel.db from Google Drive...")
        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Create a temporary backup just in case
        temp_backup = DATABASE_PATH.with_suffix(".db.backup")
        if DATABASE_PATH.exists():
            shutil.copy(DATABASE_PATH, temp_backup)
        
        success = storage.download_file(db_file_id, DATABASE_PATH)
        if success:
            logger.info("GDrive Sync: SQLite database successfully restored.")
            if temp_backup.exists():
                temp_backup.unlink()
        else:
            logger.warning("GDrive Sync: Failed to restore DB. Reverting to local state.")
            if temp_backup.exists():
                shutil.copy(temp_backup, DATABASE_PATH)
                temp_backup.unlink()
    else:
        logger.info("GDrive Sync: No existing hireintel.db backup found in Google Drive.")


def backup_db_to_gdrive() -> None:
    """Backup local SQLite db file to GDrive folder."""
    folder_id = clean_folder_id(os.getenv("OWNER_GDRIVE_FOR_USER_DATA"))
    if not folder_id:
        return

    if not DATABASE_PATH.exists():
        return

    storage = GoogleDriveStorage()
    db_file_id = storage.search_file("hireintel.db", folder_id)
    logger.info("GDrive Sync: Backing up SQLite database to Google Drive...")
    file_id = storage.upload_file_media(DATABASE_PATH, folder_id, db_file_id)
    if file_id:
        logger.info("GDrive Sync: SQLite database successfully backed up (ID: %s).", file_id)


def restore_role_files_from_gdrive(role: str) -> bool:
    """Find and restore all JDs, subqueries, processed resumes, and rankings for a role on-demand."""
    parent_folder_id = clean_folder_id(os.getenv("OWNER_GDRIVE_FOLDER_ID"))
    if not parent_folder_id:
        return False

    slug = role.lower().replace(" ", "_")
    storage = GoogleDriveStorage()
    if not storage.refresh_access_token():
        return False

    # 1. Search for remote directories matching {slug}_*
    logger.info("GDrive Sync: Searching for role folder '%s_*' on Google Drive...", slug)
    try:
        url = "https://www.googleapis.com/drive/v3/files"
        q = f"mimeType = 'application/vnd.google-apps.folder' and '{parent_folder_id}' in parents and name contains '{slug}_' and trashed = false"
        params = {"q": q, "fields": "files(id, name)"}
        resp = requests.get(url, headers=storage.get_headers(), params=params, timeout=20)
        resp.raise_for_status()
        folders = resp.json().get("files", [])
    except Exception as e:
        logger.warning("GDrive Sync: Search failed: %s", e)
        return False

    if not folders:
        logger.info("GDrive Sync: No backup folder found for role '%s'.", slug)
        return False

    # Sort to pick the latest run folder
    folders = sorted(folders, key=lambda f: f["name"], reverse=True)
    target_folder = folders[0]
    folder_id = target_folder["id"]
    logger.info("GDrive Sync: Found latest run folder '%s' (ID: %s). Restoring...", target_folder["name"], folder_id)

    # 2. List all files under the main run folder
    files = storage.list_files_in_folder(folder_id)
    
    # Pre-create folders
    role_jobs_dir = JOBS_DIR / slug
    role_jobs_dir.mkdir(parents=True, exist_ok=True)
    SCORES_DIR.mkdir(parents=True, exist_ok=True)

    for f in files:
        name = f["name"]
        fid = f["id"]
        mime = f["mimeType"]

        if mime == "application/vnd.google-apps.folder":
            if name == "resumes":
                # Restore processed candidate JSONs
                resumes_dir = PROCESSED_DIR / slug
                resumes_dir.mkdir(parents=True, exist_ok=True)
                candidate_files = storage.list_files_in_folder(fid)
                for cf in candidate_files:
                    if cf["name"].endswith(".json"):
                        logger.info("GDrive Sync: Downloading candidate JSON '%s'...", cf["name"])
                        storage.download_file(cf["id"], resumes_dir / cf["name"])
            elif name == "scores":
                # Restore detailed scoring traces JSONs
                traces_dir = SCORES_DIR / slug
                traces_dir.mkdir(parents=True, exist_ok=True)
                trace_files = storage.list_files_in_folder(fid)
                for tf in trace_files:
                    if tf["name"].endswith(".json"):
                        logger.info("GDrive Sync: Downloading score trace JSON '%s'...", tf["name"])
                        storage.download_file(tf["id"], traces_dir / tf["name"])
        else:
            # Main folder files: metadata, jd, rankings
            if name in ("jd.md", "requirements.json", "subqueries.json", "metadata.json"):
                storage.download_file(fid, role_jobs_dir / name)
            elif name == f"{slug}_ranked.json":
                storage.download_file(fid, SCORES_DIR / f"{slug}_ranked.json")

    logger.info("GDrive Sync: Role '%s' files successfully restored from Google Drive.", slug)
    return True
