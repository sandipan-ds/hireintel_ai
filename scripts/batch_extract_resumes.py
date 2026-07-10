#!/usr/bin/env python
"""Batch extraction script to parse all original resumes into schema-compliant JSON.

Usage:
    python scripts/batch_extract_resumes.py [--role RoleName] [--limit N] [--dry-run]

This script:
1. Loads the candidate registry from data/candidate_registry.json.
2. Finds raw resume PDFs under data/original/<role>/.
3. Runs the Stage 3 routed extraction pipeline (Docling/Unstructured/OCR -> JSON).
4. Saves the final schema-compliant JSONs to data/processed/<role>/<candidate_id>.json.
5. Saves the updated candidate registry.
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
            
        resume_paths = sorted(list(original_dir.glob("*.pdf")) + list(original_dir.glob("*.docx")) + list(original_dir.glob("*.txt")))
        
        if args.limit:
            resume_paths = resume_paths[:args.limit]
            
        if not resume_paths:
            logger.info("No resumes found for role %s", role)
            continue
            
        logger.info("Processing %d resumes for role %s...", len(resume_paths), role)
        
        for path in tqdm(resume_paths, desc=role):
            try:
                # 1. Run extraction pipeline
                result = extract_resume(path, registry=registry)
                
                candidate_id = result["candidate_id"]
                output_path = processed_dir / f"{candidate_id}.json"
                
                # 2. Save JSON output
                if not args.dry_run:
                    with output_path.open("w", encoding="utf-8") as f:
                        json.dump(result, f, indent=2, ensure_ascii=False)
                
                total_processed += 1
                
            except Exception as exc:
                total_failed += 1
                logger.error("Failed to extract resume at %s: %s", path.name, exc, exc_info=True)

    # Save registry if not dry-run
    if not args.dry_run:
        logger.info("Saving candidate registry to %s", registry_path)
        registry.save()

    logger.info("Batch extraction complete. Success: %d, Failed: %d", total_processed, total_failed)
    return 0

if __name__ == "__main__":
    sys.exit(main())
