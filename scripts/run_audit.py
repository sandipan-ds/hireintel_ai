# This script executes a batch JSON Quality Audit over all processed resumes.
#
# It walks the candidate JSON files under data/processed/<role>/*.json, resolves
# the original PDF/DOCX path under data/original/<role>/<file_name>, runs the
# audit orchestrator engine, saves individual audit results, and generates a
# summary report in run_reports/.
#
# Running this before candidate scoring prevents invalid, incomplete, or corrupted
# extractions from entering candidate evaluation workflows.

"""Batch JSON Quality Audit launcher script (DEC-036)."""

import os
import sys
import json
import argparse
import logging
from datetime import datetime
from pathlib import Path
from dataclasses import asdict

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.resume_parsing.audit.engine import audit_resume

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("scripts.run_audit")

# Default processed and original roots
PROCESSED_ROOT = Path("data/processed")
ORIGINAL_ROOT = Path("data/original")
AUDIT_ROOT = Path("data/audit")
REPORTS_ROOT = Path("run_reports")

ROLES = [
    "BusinessAnalyst",
    "DataScience",
    "JavaDeveloper",
    "ReactDeveloper",
    "SQLDeveloper",
    "SalesManager",
    "SrPythonDeveloper",
    "WebDesigning"
]

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run batch JSON Quality Audit on extracted resumes.")
    parser.add_argument(
        "--role",
        choices=ROLES,
        help="Specify a single role to audit (runs all roles if omitted)."
    )
    parser.add_argument(
        "--no-semantic",
        action="store_true",
        help="Disable Layer D (LLM semantic audit) to save time and API costs."
    )
    parser.add_argument(
        "--cross-parser",
        action="store_true",
        help="Enable Layer E (Cross-Parser agreement checks against legacy parser)."
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit the number of audited resumes per role (useful for testing)."
    )
    return parser.parse_args()

def main() -> None:
    args = parse_args()

    # Determine roles to run
    roles_to_run = [args.role] if args.role else ROLES
    
    # Ensure directories exist
    AUDIT_ROOT.mkdir(parents=True, exist_ok=True)
    REPORTS_ROOT.mkdir(parents=True, exist_ok=True)

    total_files_audited = 0
    passed_total = 0
    review_total = 0
    failed_total = 0
    scores_total = 0.0

    global_start_time = datetime.now()

    for role in roles_to_run:
        role_processed_dir = PROCESSED_ROOT / role
        if not role_processed_dir.is_dir():
            logger.warning("Processed directory for role '%s' not found, skipping.", role)
            continue

        role_audit_dir = AUDIT_ROOT / role
        role_audit_dir.mkdir(parents=True, exist_ok=True)

        # Discover candidate files
        _SKIP_SUFFIXES = ("_intelligence_report", "_structured_profile")
        json_files = sorted([
            f for f in role_processed_dir.glob("*.json")
            if not any(f.stem.endswith(suf) for suf in _SKIP_SUFFIXES)
        ])
        if args.limit:
            json_files = json_files[:args.limit]

        if not json_files:
            logger.info("No candidates found for role '%s'.", role)
            continue

        logger.info("Auditing %d candidates for role '%s'...", len(json_files), role)

        role_passed = 0
        role_review = 0
        role_failed = 0
        role_score_sum = 0.0
        role_results = []

        for jf in json_files:
            try:
                with open(jf, "r", encoding="utf-8") as fh:
                    resume_json = json.load(fh)
            except Exception as e:
                logger.error("Failed to read JSON file %s: %s", jf.name, e)
                continue

            # Resolve original source file path
            file_name = resume_json.get("document", {}).get("file_name") or ""
            source_path = os.path.join("data", "original", role, file_name)

            # Run Audit Orchestrator
            result = audit_resume(
                resume_json=resume_json,
                source_path=source_path,
                run_semantic=not args.no_semantic,
                run_cross_parser=args.cross_parser
            )

            # Accumulate scores and stats
            overall_score = result.quality_scores.overall_extraction_quality
            role_score_sum += overall_score
            scores_total += overall_score
            total_files_audited += 1

            if result.audit_status == "passed":
                role_passed += 1
                passed_total += 1
            elif result.audit_status == "review_required":
                role_review += 1
                review_total += 1
            else:
                role_failed += 1
                failed_total += 1

            # Save per-candidate audit JSON
            audit_file = role_audit_dir / f"{result.candidate_id}_audit.json"
            with open(audit_file, "w", encoding="utf-8") as fh:
                json.dump(asdict(result), fh, indent=2, ensure_ascii=False)

            role_results.append(result)

        # Write role-level summary report in run_reports/
        avg_score = role_score_sum / len(json_files) if json_files else 0.0
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = REPORTS_ROOT / f"audit_{role}_{timestamp}.md"
        
        with open(report_file, "w", encoding="utf-8") as fh:
            fh.write(f"# JSON Quality Audit Summary - {role}\n")
            fh.write(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            fh.write("## Execution Stats\n")
            fh.write(f"- **Candidates Audited**: {len(json_files)}\n")
            fh.write(f"- **Passed**: {role_passed} ({role_passed/len(json_files)*100:.1f}%)\n")
            fh.write(f"- **Review Required**: {role_review} ({role_review/len(json_files)*100:.1f}%)\n")
            fh.write(f"- **Failed**: {role_failed} ({role_failed/len(json_files)*100:.1f}%)\n")
            fh.write(f"- **Average Quality Score**: {avg_score:.2f}\n\n")
            
            fh.write("## Detailed Candidate Results\n")
            fh.write("| Candidate ID | Status | Quality Score | Error Count | Warning Count | Critical Count |\n")
            fh.write("|---|---|---|---|---|---|\n")
            for r in role_results:
                sum_data = r.summary
                fh.write(
                    f"| {r.candidate_id} | {r.audit_status} | "
                    f"{r.quality_scores.overall_extraction_quality:.2f} | "
                    f"{sum_data.get('error_count', 0)} | "
                    f"{sum_data.get('warning_count', 0)} | "
                    f"{sum_data.get('critical_count', 0)} |\n"
                )

        logger.info(
            "Role '%s' audit complete: passed=%d, review=%d, failed=%d, avg_score=%.2f",
            role, role_passed, role_review, role_failed, avg_score
        )

    # Print final global summary
    elapsed_time = datetime.now() - global_start_time
    global_avg = scores_total / total_files_audited if total_files_audited > 0 else 0.0
    
    print("\n" + "="*60)
    print("GLOBAL BATCH AUDIT COMPLETE")
    print("="*60)
    print(f"Total Files Audited: {total_files_audited}")
    print(f"Passed:              {passed_total} ({(passed_total/total_files_audited*100) if total_files_audited > 0 else 0.0:.1f}%)")
    print(f"Review Required:     {review_total} ({(review_total/total_files_audited*100) if total_files_audited > 0 else 0.0:.1f}%)")
    print(f"Failed:              {failed_total} ({(failed_total/total_files_audited*100) if total_files_audited > 0 else 0.0:.1f}%)")
    print(f"Avg Quality Score:   {global_avg:.2f}")
    print(f"Elapsed Time:        {elapsed_time.total_seconds():.1f}s")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()
