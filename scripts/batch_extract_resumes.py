#!/usr/bin/env python
"""Batch extraction script to parse all original resumes into schema-compliant JSON.

Usage:
    python scripts/batch_extract_resumes.py [--role RoleName] [--limit N] [--batch-size N] [--dry-run] [--overwrite]

This script:
1. Loads the candidate registry from data/candidate_registry.json.
2. Finds raw resume PDFs under data/original/<role>/.
3. Runs the Stage 3 routed extraction pipeline (Docling/Unstructured/OCR -> JSON)
   with LLM key rotation across Ollama, OpenCode×3, OpenRouter, NVIDIA NIM.
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

# Make the src package importable
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.resume_parsing.candidate_registry import CandidateRegistry, DEFAULT_REGISTRY_PATH
from src.resume_parsing.extraction.pipeline import extract_resume

# Set up logging to console only to keep output clean
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("batch_extract")

ROLES = [
    "BusinessAnalyst",
    "DataScience",
    "JavaDeveloper",
    "ReactDeveloper",
    "SalesManager",
    "SQLDeveloper",
    "SrPythonDeveloper",
    "WebDesigning"
]

def parse_args():
    parser = argparse.ArgumentParser(description="Batch extract resumes using Stage 3 routed pipeline.")
    parser.add_argument(
        "--role",
        choices=ROLES,
        help="Run extraction for a specific role only (runs all if not specified)."
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
             "Use smaller values (e.g. 5) with slow local models (default: 10)."
    )
    return parser.parse_args()

def main():
    args = parse_args()
    
    # Load candidate registry
    registry_path = Path(_PROJECT_ROOT) / DEFAULT_REGISTRY_PATH
    if args.dry_run:
        logger.info("[DRY RUN] In-memory registry used; changes will not be saved.")
        registry = CandidateRegistry()
    else:
        logger.info("Loading candidate registry from %s", registry_path)
        # Create empty registry if it doesn't exist yet
        if not registry_path.exists():
            registry_path.parent.mkdir(parents=True, exist_ok=True)
            registry = CandidateRegistry(path=str(registry_path))
            registry.save()
        else:
            registry = CandidateRegistry.load(registry_path)

    roles_to_process = [args.role] if args.role else ROLES
    
    total_processed = 0
    total_failed = 0

    for role in roles_to_process:
        original_dir = Path(_PROJECT_ROOT) / "data" / "original" / role
        processed_dir = Path(_PROJECT_ROOT) / "data" / "processed" / role

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

            for path in tqdm(chunk, desc=chunk_label):
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
                                    total_processed += 1
                                    continue

                    # Run extraction pipeline
                    result = extract_resume(path, registry=registry)

                    candidate_id = result["candidate_id"]
                    output_path = processed_dir / f"{candidate_id}.json"

                    if not args.dry_run:
                        with output_path.open("w", encoding="utf-8") as f:
                            json.dump(result, f, indent=2, ensure_ascii=False)

                    total_processed += 1
                    logger.info("Saved %s", output_path.name)

                except Exception as exc:
                    total_failed += 1
                    logger.error("Failed %s: %s", path.name, exc, exc_info=True)

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
