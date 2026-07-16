#!/usr/bin/env python
"""Batch extraction script to parse all original resumes into schema-compliant JSON.

Usage:
    # Process all roles sequentially:
    python scripts/batch_extract_resumes.py [--batch-size N] [--overwrite]

    # Process specific roles only (used by parallel launcher):
    python scripts/batch_extract_resumes.py --roles JavaDeveloper,ReactDeveloper

    # Use a custom registry path (used by parallel launcher to avoid conflicts):
    python scripts/batch_extract_resumes.py --registry-path data/registry_worker_0.json

This script:
1. Loads the candidate registry (default: data/candidate_registry.json).
2. Finds raw resume PDFs under data/original/<role>/.
3. Runs the Stage 3 routed extraction pipeline (Docling/Unstructured/OCR -> JSON)
   with LLM key rotation across providers defined in llm_normalizer.py.
4. Saves JSONs to data/processed/<role>/<candidate_id>.json.
5. Saves the updated candidate registry after every batch chunk (default: 10).
6. Skips already-extracted resumes by default (pass --overwrite to force re-run).
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

# Make the local recruiter/src package importable
_LOCAL_DIR = Path(__file__).resolve().parent
if str(_LOCAL_DIR) not in sys.path:
    sys.path.insert(0, str(_LOCAL_DIR))

from src.resume_parsing.candidate_registry import CandidateRegistry, DEFAULT_REGISTRY_PATH
from src.resume_parsing.extraction.pipeline import extract_resume

# Set up logging to console only to keep output clean
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("batch_extract")

def discover_original_roles() -> list[str]:
    orig_dir = Path("recruiter/data/original")
    if orig_dir.is_dir():
        return sorted([d.name for d in orig_dir.iterdir() if d.is_dir()])
    return []

ROLES = discover_original_roles()

def parse_args():
    parser = argparse.ArgumentParser(description="Batch extract resumes using Stage 3 routed pipeline.")
    parser.add_argument(
        "--role",
        help="Run extraction for a single specific role."
    )
    parser.add_argument(
        "--roles",
        type=str,
        default=None,
        help="Comma-separated list of roles to process (e.g. JavaDeveloper,ReactDeveloper). "
             "Used by the parallel launcher to assign role groups to workers."
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit the number of resumes processed per role (useful for testing)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the pipeline but do not write output JSON or modify the candidate registry."
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-extract even if a processed JSON already exists (default: skip existing)."
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        dest="batch_size",
        help="Number of resumes per processing chunk. Registry is saved after each chunk. "
             "Use smaller values (e.g. 5) with slow APIs (default: 10)."
    )
    parser.add_argument(
        "--registry-path",
        type=str,
        default=None,
        dest="registry_path",
        help="Path to the candidate registry JSON file. Defaults to recruiter/data/candidate_registry.json. "
             "Set to a worker-specific path when running parallel workers to avoid write conflicts."
    )
    return parser.parse_args()

def main():
    args = parse_args()

    # Resolve registry path: use --registry-path if supplied, else default.
    if args.registry_path:
        registry_path = Path(args.registry_path)
    else:
        registry_path = Path("recruiter/data/candidate_registry.json")

    if args.dry_run:
        logger.info("[DRY RUN] In-memory registry used; changes will not be saved.")
        registry = CandidateRegistry()
    else:
        logger.info("Loading candidate registry from %s", registry_path)
        if not registry_path.exists():
            registry_path.parent.mkdir(parents=True, exist_ok=True)
            registry = CandidateRegistry(path=str(registry_path))
            registry.save()
        else:
            registry = CandidateRegistry.load(registry_path)

    # Resolve which roles to process.
    # Priority: --roles (parallel launcher) > --role (single) > all roles.
    if args.roles:
        roles_to_process = [r.strip() for r in args.roles.split(",") if r.strip() in ROLES]
        invalid = [r.strip() for r in args.roles.split(",") if r.strip() not in ROLES]
        if invalid:
            logger.warning("Unknown roles ignored: %s", invalid)
    elif args.role:
        roles_to_process = [args.role]
    else:
        roles_to_process = ROLES
    
    total_processed = 0
    total_failed = 0

    for role in roles_to_process:
        original_dir = Path("recruiter/data/original") / role
        processed_dir = Path("recruiter/data/processed") / role

        if not original_dir.is_dir():
            logger.warning("Original resume folder not found for role %s: %s", role, original_dir)
            continue

        if not args.dry_run:
            processed_dir.mkdir(parents=True, exist_ok=True)

        resume_paths = sorted(
            list(original_dir.glob("*.pdf"))
            + list(original_dir.glob("*.docx"))
            + list(original_dir.glob("*.txt"))
        )

        if args.limit:
            resume_paths = resume_paths[:args.limit]

        if not resume_paths:
            logger.info("No resumes found for role %s", role)
            continue

        logger.info("Processing %d resumes for role %s in batches of %d...",
                    len(resume_paths), role, args.batch_size)

        # Split into chunks so registry is saved incrementally and
        # local-model warmup cost is amortised over smaller groups.
        chunks = [
            resume_paths[i: i + args.batch_size]
            for i in range(0, len(resume_paths), args.batch_size)
        ]

        for chunk_idx, chunk in enumerate(chunks):
            chunk_label = f"{role} chunk {chunk_idx+1}/{len(chunks)}"
            logger.info("--- %s (%d resumes) ---", chunk_label, len(chunk))

            def process_resume(path):
                try:
                    # Skip if output already exists (makes runs safely resumable)
                    if not args.dry_run and not args.overwrite:
                        existing_entry = registry.lookup(source_path=path)
                        if existing_entry:
                            existing_id_candidates = [
                                cid for cid, meta in registry.all_candidates().items()
                                if meta.get("source_path") == str(path.resolve())
                            ]
                            if existing_id_candidates:
                                cid = existing_id_candidates[0]
                                check_path = processed_dir / f"{cid}.json"
                                if check_path.exists():
                                    logger.info("Skipping %s — already extracted as %s", path.name, cid)
                                    return "skipped"

                    # Run extraction pipeline
                    result = extract_resume(path, registry=registry)

                    candidate_id = result["candidate_id"]
                    output_path = processed_dir / f"{candidate_id}.json"

                    if not args.dry_run:
                        with output_path.open("w", encoding="utf-8") as f:
                            json.dump(result, f, indent=2, ensure_ascii=False)

                    logger.info("Saved %s", output_path.name)
                    return "success"

                except Exception as exc:
                    logger.error("Failed %s: %s", path.name, exc, exc_info=True)
                    return "failed"

            # Execute chunk in parallel using ThreadPoolExecutor
            logger.info("Starting parallel extraction for %s with up to 10 threads", chunk_label)
            with ThreadPoolExecutor(max_workers=min(len(chunk), 10)) as pool:
                futures = {pool.submit(process_resume, p): p for p in chunk}
                for fut in as_completed(futures):
                    res = fut.result()
                    if res == "skipped":
                        total_processed += 1
                    elif res == "success":
                        total_processed += 1
                    elif res == "failed":
                        total_failed += 1

            # Save registry after every chunk so progress is never lost
            if not args.dry_run:
                registry.save()
                logger.info("%s complete — registry saved. Total so far: %d OK / %d failed",
                            chunk_label, total_processed, total_failed)

    # Final registry save
    if not args.dry_run:
        logger.info("Final registry save to %s", registry_path)
        registry.save()

    logger.info("Batch extraction complete. Success: %d, Failed: %d", total_processed, total_failed)
    return 0

if __name__ == "__main__":
    sys.exit(main())
