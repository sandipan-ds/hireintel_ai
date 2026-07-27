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
ROOT = Path(__file__).resolve().parent.parent.parent.parent
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
        """Upload a local file to a Google Drive folder using robust 2-step REST API calls."""
        logger.info("GDrive: uploading file '%s' (%d bytes)...", file_path.name, file_path.stat().st_size)
        
        # Step 1: Create file metadata on Google Drive
        meta_url = "https://www.googleapis.com/drive/v3/files"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        body = {
            "name": file_path.name,
            "parents": [parent_id],
        }
        resp = requests.post(meta_url, headers=headers, json=body, timeout=30)
        resp.raise_for_status()
        file_id = resp.json()["id"]

        # Step 2: Upload raw file content via media PATCH endpoint
        media_url = f"https://www.googleapis.com/upload/drive/v3/files/{file_id}?uploadType=media"
        with file_path.open("rb") as f:
            file_data = f.read()

        media_headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/octet-stream",
        }
        resp2 = requests.patch(media_url, headers=media_headers, data=file_data, timeout=60)
        resp2.raise_for_status()

        logger.info("GDrive: successfully uploaded '%s' (ID: %s).", file_path.name, file_id)
        return file_id

    def upload_directory_recursive(self, local_dir: Path, remote_parent_id: str) -> None:
        """Recursively upload a local directory to Google Drive with file-level error resilience."""
        remote_folder_id = self.create_folder(local_dir.name, remote_parent_id)
        
        for item in local_dir.iterdir():
            if item.is_dir():
                self.upload_directory_recursive(item, remote_folder_id)
            elif item.is_file():
                try:
                    self.upload_file(item, remote_folder_id)
                except Exception as fe:
                    logger.error("GDrive: failed to upload file '%s': %s", item.name, fe)


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

    log_update(f"Initializing job dataset packaging for slug='{slug}'...")
    log_update(f"DIAG ROOT={ROOT}")
    log_update(f"DIAG JOBS_DIR={JOBS_DIR}  exists={JOBS_DIR.exists()}")
    log_update(f"DIAG JD_DIR={JD_DIR}  exists={JD_DIR.exists()}")
    log_update(f"DIAG PROCESSED_DIR={PROCESSED_DIR}  exists={PROCESSED_DIR.exists()}")
    log_update(f"DIAG SCORES_DIR={SCORES_DIR}  exists={SCORES_DIR.exists()}")
    log_update(f"DIAG orig_base={ROOT / 'recruiter' / 'data' / 'original'}  exists={(ROOT / 'recruiter' / 'data' / 'original').exists()}")
    
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

    # Helper: Case-insensitive and fuzzy slug matching for Linux & Windows path consistency
    def _norm_slug(s: str) -> str:
        clean = s.lower().replace(" ", "_").replace("-", "_")
        return clean.split("_202")[0] if "_202" in clean else clean

    def _get_matching_slug_dirs(base_dir: Path, target_slug: str) -> List[Path]:
        if not base_dir.exists():
            return []
        matches = []
        t_norm = _norm_slug(target_slug)
        for child in base_dir.iterdir():
            if child.is_dir():
                c_norm = _norm_slug(child.name)
                if c_norm == t_norm or t_norm in c_norm or c_norm in t_norm:
                    matches.append(child)
        return matches

    def _get_matching_score_items(scores_dir: Path, target_slug: str) -> List[Path]:
        if not scores_dir.exists():
            return []
        t_norm = _norm_slug(target_slug)
        matched_items = []
        for item in scores_dir.iterdir():
            i_norm = _norm_slug(item.name)
            if t_norm in i_norm or i_norm in t_norm:
                matched_items.append(item)
        return matched_items

    # 4. Copy matching files
    n_jds, n_resumes, n_scores = 0, 0, 0

    # DIAG: Dump directory listings for all base dirs
    for _label, _base in [("JOBS_DIR", JOBS_DIR), ("JD_DIR", JD_DIR), ("PROCESSED_DIR", PROCESSED_DIR), ("SCORES_DIR", SCORES_DIR), ("ORIGINAL", ROOT / "recruiter" / "data" / "original")]:
        if _base.exists():
            children = [c.name for c in _base.iterdir()]
            log_update(f"DIAG {_label} children ({len(children)}): {children[:30]}")
        else:
            log_update(f"DIAG {_label} DOES NOT EXIST")

    # A. Job Metadata and extracted JD/REQs (from JOBS_DIR)
    job_dirs = set(_get_matching_slug_dirs(JOBS_DIR, slug))
    if (JOBS_DIR / slug).is_dir():
        job_dirs.add(JOBS_DIR / slug)
    log_update(f"Found {len(job_dirs)} job directories for JD metadata: {[str(d) for d in job_dirs]}")
    for jdir in job_dirs:
        log_update(f"DIAG scanning job dir: {jdir}, children: {[c.name for c in jdir.iterdir()] if jdir.exists() else 'N/A'}")
        for file_name in ["jd.md", "requirements.json", "subqueries.json", "metadata.json"]:
            src_file = jdir / file_name
            if src_file.exists():
                shutil.copy(src_file, dest_dir / file_name)
                n_jds += 1
        # Also copy raw uploaded/downloaded resumes if stored under JOBS_DIR/<slug>/resumes
        raw_sub = jdir / "resumes"
        if raw_sub.exists():
            for item in raw_sub.iterdir():
                if item.is_file():
                    shutil.copy(item, resumes_dest / item.name)
                    n_resumes += 1

    # B. SubQuery Markdown definition
    sq_dirs = set(_get_matching_slug_dirs(JD_DIR, slug))
    if (JD_DIR / slug).is_dir():
        sq_dirs.add(JD_DIR / slug)
    search_jd_dirs = list(sq_dirs) if sq_dirs else ([JD_DIR / slug] if (JD_DIR / slug).exists() else [JD_DIR])
    for sdir in search_jd_dirs:
        if sdir.is_dir():
            for item in sdir.iterdir():
                if item.is_file() and item.name.endswith(".md"):
                    shutil.copy(item, dest_dir / item.name)
                    n_jds += 1

    # C. Processed candidate JSON profiles & raw original source resumes
    proc_dirs = set(_get_matching_slug_dirs(PROCESSED_DIR, slug))
    if (PROCESSED_DIR / slug).is_dir():
        proc_dirs.add(PROCESSED_DIR / slug)
    log_update(f"Found {len(proc_dirs)} processed resume directories: {[str(d) for d in proc_dirs]}")
    for pdir in proc_dirs:
        pdir_children = [c.name for c in pdir.iterdir()] if pdir.exists() else []
        log_update(f"DIAG proc dir {pdir.name} has {len(pdir_children)} files: {pdir_children[:20]}")
        for item in pdir.iterdir():
            if item.is_file() and item.suffix == ".json":
                shutil.copy(item, resumes_dest / item.name)
                n_resumes += 1

    orig_base = ROOT / "recruiter" / "data" / "original"
    orig_dirs = set(_get_matching_slug_dirs(orig_base, slug))
    if (orig_base / slug).is_dir():
        orig_dirs.add(orig_base / slug)
    log_update(f"Found {len(orig_dirs)} original source resume directories: {[str(d) for d in orig_dirs]}")
    for odir in orig_dirs:
        odir_children = [c.name for c in odir.iterdir()] if odir.exists() else []
        log_update(f"DIAG orig dir {odir.name} has {len(odir_children)} files: {odir_children[:20]}")
        for item in odir.iterdir():
            if item.is_file() and item.suffix.lower() in (".pdf", ".docx", ".doc", ".txt", ".png", ".jpg", ".jpeg"):
                shutil.copy(item, resumes_dest / item.name)
                n_resumes += 1

    # D. Candidate Rankings, RAG Evaluation, Performance Profile, and Trace JSONs
    score_items = set(_get_matching_score_items(SCORES_DIR, slug))
    if (SCORES_DIR / f"{slug}_ranked.json").exists():
        score_items.add(SCORES_DIR / f"{slug}_ranked.json")
    if (SCORES_DIR / slug).is_dir():
        score_items.add(SCORES_DIR / slug)
    log_update(f"Found {len(score_items)} score files/directories: {[str(s) for s in score_items]}")

    for sitem in score_items:
        log_update(f"DIAG score item: {sitem}  is_file={sitem.is_file()}  is_dir={sitem.is_dir()}")
        if sitem.is_file():
            if sitem.name.endswith("_ranked.json"):
                shutil.copy(sitem, dest_dir / f"{slug}_ranked.json")
                shutil.copy(sitem, scores_dest / f"{slug}_ranked.json")
                shutil.copy(sitem, scores_dest / sitem.name)
                n_scores += 1
            elif sitem.name.endswith("_rag_evaluation.json"):
                shutil.copy(sitem, dest_dir / f"{slug}_rag_evaluation.json")
                shutil.copy(sitem, scores_dest / f"{slug}_rag_evaluation.json")
                shutil.copy(sitem, scores_dest / sitem.name)
                n_scores += 1
            elif sitem.name.endswith("_performance_profile.json"):
                shutil.copy(sitem, dest_dir / f"{slug}_performance_profile.json")
                shutil.copy(sitem, scores_dest / f"{slug}_performance_profile.json")
                shutil.copy(sitem, scores_dest / sitem.name)
                n_scores += 1
            elif sitem.suffix == ".json":
                shutil.copy(sitem, scores_dest / sitem.name)
                n_scores += 1
        elif sitem.is_dir():
            dir_children = [c.name for c in sitem.iterdir()]
            log_update(f"DIAG score subdir {sitem.name} has {len(dir_children)} files: {dir_children[:20]}")
            for trace_file in sitem.iterdir():
                if trace_file.is_file() and trace_file.suffix == ".json":
                    shutil.copy(trace_file, scores_dest / trace_file.name)
                    n_scores += 1

    log_update(f"Packaged {n_jds} JD files, {n_resumes} resume files, and {n_scores} score files into export bundle.")

    # DIAG: List what ended up in the local export bundle
    for _sub_name, _sub_path in [("resumes", resumes_dest), ("scores", scores_dest)]:
        if _sub_path.exists():
            _contents = [c.name for c in _sub_path.iterdir()]
            log_update(f"DIAG export/{folder_name}/{_sub_name}/ contains {len(_contents)} files: {_contents[:30]}")
        else:
            log_update(f"DIAG export/{folder_name}/{_sub_name}/ DOES NOT EXIST")

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
        if "#" in val:
            val = val.partition("#")[0].strip()
        if "?" in val:
            val = val.partition("?")[0].strip()
        if "/" in val:
            val = val.rstrip("/").split("/")[-1].strip()
        val = val.strip('"\'')
        return val if val else None

    # 5. Connect to Google Drive if environment variables are set
    client_id = os.getenv("OWNER_GDRIVE_CLIENT_ID")
    client_secret = os.getenv("OWNER_GDRIVE_CLIENT_SECRET")
    refresh_token = os.getenv("OWNER_GDRIVE_REFRESH_TOKEN")
    
    raw_user_data_folder = os.getenv("OWNER_GDRIVE_FOR_USER_DATA")
    if raw_user_data_folder:
        folder_id = clean_folder_id_helper(raw_user_data_folder)
    else:
        folder_id = clean_folder_id_helper(os.getenv("OWNER_GDRIVE_FOLDER_ID"))

    log_update(f"DIAG env: CLIENT_ID={'set' if client_id else 'MISSING'}, SECRET={'set' if client_secret else 'MISSING'}, REFRESH={'set' if refresh_token else 'MISSING'}, FOLDER_ID={folder_id}, RAW_USER_DATA={raw_user_data_folder}")

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
            log_update("✓ GDrive access token obtained successfully.")
            
            log_update(f"Uploading folder '{folder_name}' to Google Drive data folder ({folder_id})...")
            uploader.upload_directory_recursive(dest_dir, folder_id)

            # Upload session log to dedicated OWNER_GDRIVE_FOR_USER_LOGS folder if configured
            user_logs_folder = os.getenv("OWNER_GDRIVE_FOR_USER_LOGS")
            if user_logs_folder and log_file and log_file.exists():
                user_logs_folder_id = clean_folder_id_helper(user_logs_folder)
                if user_logs_folder_id:
                    try:
                        # Copy to a unique timestamped file name so logs in Google Drive don't collide
                        unique_log_file = dest_dir / f"{folder_name}_scoring_run_log.txt"
                        shutil.copy(log_file, unique_log_file)
                        log_update(f"Uploading session log '{unique_log_file.name}' to dedicated logs folder ({user_logs_folder_id})...")
                        uploader.upload_file(unique_log_file, user_logs_folder_id)
                    except Exception as log_exc:
                        logger.error("GDrive: session log upload error: %s", log_exc)
                        log_update(f"⚠ Dedicated session log upload notice: {log_exc}")

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
