#!/usr/bin/env python
"""Parallel batch extraction launcher.

Runs 2 batch_extract_resumes.py workers simultaneously, each handling a
different group of roles and leading with a different NVIDIA NIM API key
(via LLM_WORKER_ID env var which rotates the provider list).

Worker split (by role count / expected workload):
    Worker 0  ->  BusinessAnalyst, DataScience, JavaDeveloper, ReactDeveloper
                  (leads with NVIDIA NIM key 1)
    Worker 1  ->  SrPythonDeveloper, SQLDeveloper, SalesManager, WebDesigning
                  (leads with NVIDIA NIM key 2 via LLM_WORKER_ID=1 rotation)

Registry safety:
    Each worker writes to data/candidate_registry_worker_N.json (separate
    files, zero conflict). After all workers finish, the launcher merges
    them into the main data/candidate_registry.json.

Usage:
    python scripts/parallel_batch_extract.py [--batch-size N] [--overwrite]
"""

import os
import sys
import json
import time
import argparse
import logging
import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("parallel_extract")

# ---------------------------------------------------------------------------
# 2-worker role split
# ---------------------------------------------------------------------------
WORKER_GROUPS = [
    {
        "worker_id": 0,
        "roles": ["BusinessAnalyst", "DataScience", "JavaDeveloper", "ReactDeveloper"],
        "description": "NVIDIA NIM key 1 (LLM_WORKER_ID=0)",
    },
    {
        "worker_id": 1,
        "roles": ["SrPythonDeveloper", "SQLDeveloper", "SalesManager", "WebDesigning"],
        "description": "NVIDIA NIM key 2 (LLM_WORKER_ID=1, rotated)",
    },
]


def parse_args():
    p = argparse.ArgumentParser(description="Parallel batch extraction: 2 workers.")
    p.add_argument("--overwrite", action="store_true",
                   help="Re-extract even if JSON already exists.")
    p.add_argument("--batch-size", type=int, default=10, dest="batch_size",
                   help="Resumes per chunk per worker (default: 10).")
    p.add_argument("--dry-run", action="store_true",
                   help="Pass --dry-run to both workers.")
    return p.parse_args()


def worker_registry_path(worker_id):
    return _PROJECT_ROOT / "data" / f"candidate_registry_worker_{worker_id}.json"


def launch_worker(group, batch_size, dry_run, overwrite):
    worker_id = group["worker_id"]
    roles     = group["roles"]

    reg_path  = worker_registry_path(worker_id)
    log_dir   = _PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file  = log_dir / f"worker_{worker_id}.log"

    # Seed the worker registry from the main one so skip-existing logic works
    main_reg = _PROJECT_ROOT / "data" / "candidate_registry.json"
    if main_reg.exists() and not reg_path.exists():
        reg_path.write_text(main_reg.read_text(encoding="utf-8"), encoding="utf-8")

    cmd = [
        sys.executable,
        str(_PROJECT_ROOT / "scripts" / "batch_extract_resumes.py"),
        "--roles", ",".join(roles),
        "--registry-path", str(reg_path),
        "--batch-size", str(batch_size),
    ]
    if dry_run:
        cmd.append("--dry-run")
    if overwrite:
        cmd.append("--overwrite")

    env = os.environ.copy()
    env["LLM_WORKER_ID"] = str(worker_id)

    log_fh = log_file.open("w", encoding="utf-8")
    logger.info("Launching worker %d -> roles=%s | key_slot=%d | log=%s",
                worker_id, roles, worker_id, log_file.name)

    proc = subprocess.Popen(cmd, env=env, stdout=log_fh, stderr=subprocess.STDOUT,
                            cwd=str(_PROJECT_ROOT))
    proc._log_fh   = log_fh
    proc._log_path = log_file
    proc._worker_id = worker_id
    proc._roles    = roles
    return proc


def merge_registries():
    main_path = _PROJECT_ROOT / "data" / "candidate_registry.json"
    main_data = json.loads(main_path.read_text(encoding="utf-8")) if main_path.exists() else {"candidates": {}, "role_counters": {}}

    merged_cands    = dict(main_data.get("candidates", {}))
    merged_counters = dict(main_data.get("role_counters", {}))
    total_new = 0

    for g in WORKER_GROUPS:
        wid = g["worker_id"]
        wp  = worker_registry_path(wid)
        if not wp.exists():
            logger.warning("Worker %d registry missing: %s", wid, wp)
            continue
        wdata = json.loads(wp.read_text(encoding="utf-8"))
        new = 0
        for cid, meta in wdata.get("candidates", {}).items():
            if cid not in merged_cands:
                merged_cands[cid] = meta
                new += 1
            else:
                merged_cands[cid].update(meta)
        for role, cnt in wdata.get("role_counters", {}).items():
            merged_counters[role] = max(merged_counters.get(role, 0), cnt)
        total_new += new
        logger.info("Worker %d: merged %d entries", wid, len(wdata.get("candidates", {})))
        wp.unlink()

    main_data["candidates"]    = merged_cands
    main_data["role_counters"] = merged_counters
    main_path.write_text(json.dumps(main_data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Registry merged: %d total candidates (%d new added) -> %s",
                len(merged_cands), total_new, main_path)


def tail_log(log_path, n=5):
    """Return last n lines of a log file for progress display."""
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-n:] if len(lines) >= n else lines
    except Exception:
        return []


def main():
    args = parse_args()

    logger.info("=" * 60)
    logger.info("Parallel Extraction: %d workers | batch_size=%d | overwrite=%s",
                len(WORKER_GROUPS), args.batch_size, args.overwrite)
    for g in WORKER_GROUPS:
        roles = g["roles"]
        orig  = _PROJECT_ROOT / "data" / "original"
        total_pdfs = sum(len(list((orig / r).glob("*.pdf"))) for r in roles if (orig / r).is_dir())
        proc_root  = _PROJECT_ROOT / "data" / "processed"
        done       = sum(len(list((proc_root / r).glob("*.json"))) for r in roles if (proc_root / r).is_dir())
        logger.info("  Worker %d: %s  |  %d PDFs total, %d already done, ~%d to extract",
                    g["worker_id"], roles, total_pdfs, done, total_pdfs - done)
    logger.info("=" * 60)

    processes = []
    for g in WORKER_GROUPS:
        proc = launch_worker(g, args.batch_size, args.dry_run, args.overwrite)
        processes.append(proc)
        time.sleep(1.0)  # stagger launches slightly

    logger.info("Both workers running. Check logs in logs/worker_N.log")
    logger.info("Press Ctrl+C to abort all workers.")

    start_time = time.time()
    try:
        while True:
            time.sleep(60)
            alive = [p for p in processes if p.poll() is None]
            done  = [p for p in processes if p.poll() is not None]
            elapsed = int(time.time() - start_time)
            logger.info("[%dm%ds] Running: %d | Done: %d",
                        elapsed // 60, elapsed % 60, len(alive), len(done))
            # Show last 3 lines from each running worker's log
            for p in alive:
                for line in tail_log(p._log_path, 3):
                    try:
                        clean_line = line.strip().encode(sys.stdout.encoding or 'utf-8', errors='replace').decode(sys.stdout.encoding or 'utf-8')
                        logger.info("  [W%d] %s", p._worker_id, clean_line)
                    except Exception:
                        pass
            if not alive:
                break
    except KeyboardInterrupt:
        logger.warning("Interrupted — terminating all workers...")
        for p in processes:
            try: p.terminate()
            except Exception: pass

    for p in processes:
        try: p._log_fh.close()
        except Exception: pass

    success = sum(1 for p in processes if p.poll() == 0)
    failed  = len(processes) - success
    logger.info("Workers done: %d succeeded, %d failed", success, failed)

    if not args.dry_run:
        logger.info("Merging registries...")
        merge_registries()

    logger.info("All done. Check data/processed/ for results.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
