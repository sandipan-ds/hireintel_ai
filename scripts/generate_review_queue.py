# This script aggregates all JSON Quality Audit findings across all roles and
# compiles a prioritized, human-readable review queue report in run_reports/review_queue.md.
#
# Candidates are categorized under "Critical (Failed / Blocked)" and "Warning (Review Recommended)".
# For each candidate, it extracts the exact field path, issue, and source evidence
# to assist a recruiter or auditor in correcting the parsed data.

"""Review Queue Report Generator (DEC-036)."""

import os
import sys
import json
import logging
from datetime import datetime
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger("scripts.generate_review_queue")

AUDIT_ROOT = Path("data/audit")
REPORTS_ROOT = Path("run_reports")

def main() -> None:
    if not AUDIT_ROOT.is_dir():
        print(f"Error: Audit results folder '{AUDIT_ROOT}' does not exist. Run scripts/run_audit.py first.")
        sys.exit(1)

    REPORTS_ROOT.mkdir(parents=True, exist_ok=True)

    failed_candidates = []
    review_candidates = []

    # Gather all audit results
    for role_dir in sorted(AUDIT_ROOT.iterdir()):
        if not role_dir.is_dir():
            continue
        role = role_dir.name
        for audit_file in sorted(role_dir.glob("*_audit.json")):
            try:
                with open(audit_file, "r", encoding="utf-8") as fh:
                    result = json.load(fh)
            except Exception as e:
                logger.error("Failed to read audit file %s: %s", audit_file.name, e)
                continue

            status = result.get("audit_status")
            candidate_id = result.get("candidate_id")
            score = result.get("quality_scores", {}).get("overall_extraction_quality", 0.0)

            # Combine all checks
            all_checks = (
                result.get("schema_checks", []) +
                result.get("field_checks", []) +
                result.get("section_checks", []) +
                result.get("evidence_coverage_checks", []) +
                result.get("semantic_checks", [])
            )

            # Gather issues
            issues = []
            for check in all_checks:
                if check.get("severity") in ("critical", "error", "warning"):
                    issues.append({
                        "field": check.get("field"),
                        "issue": check.get("issue"),
                        "severity": check.get("severity"),
                        "expected": check.get("expected"),
                        "actual": check.get("actual")
                    })

            record = {
                "candidate_id": candidate_id,
                "role": role,
                "score": score,
                "issues": issues,
                "missing": result.get("missing_candidates", [])
            }

            if status == "failed":
                failed_candidates.append(record)
            elif status == "review_required":
                review_candidates.append(record)

    # Generate Markdown Report
    output_path = REPORTS_ROOT / "review_queue.md"
    
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write("# Extraction Quality Review Queue\n")
        fh.write(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        fh.write("This report compiles candidates whose resume JSON extraction failed quality audits or ")
        fh.write("requires manual inspection before candidate scoring/matching.\n\n")

        fh.write("## Overview Metrics\n")
        fh.write(f"- **Failed / Blocked Candidates**: {len(failed_candidates)}\n")
        fh.write(f"- **Review Recommended Candidates**: {len(review_candidates)}\n\n")

        fh.write("---\n\n")

        # 1. Critical Failed Section
        fh.write("## 1. Critical (Failed / Blocked from Scoring)\n")
        fh.write("These candidates scored below the threshold of `0.65` and should be skipped or re-extracted.\n\n")
        
        if not failed_candidates:
            fh.write("*No failed candidates.*\n\n")
        else:
            for c in sorted(failed_candidates, key=lambda x: x["score"]):
                fh.write(f"### 🛑 {c['candidate_id']} [{c['role']}] - Quality Score: {c['score']:.2f}\n")
                fh.write("#### Flagged Issues:\n")
                for issue in c["issues"]:
                    fh.write(f"- **[{issue['severity'].upper()}]** `{issue['field']}`: {issue['issue']}\n")
                    if issue.get("expected"):
                        fh.write(f"  - *Expected*: {issue['expected']} | *Actual*: {issue['actual']}\n")
                if c["missing"]:
                    fh.write("#### Semantic Omissions:\n")
                    for m in c["missing"]:
                        fh.write(f"- **[{m.get('field_family').upper()}]**: {m.get('reason')}\n")
                        fh.write(f"  - *Evidence snippet*: `{m.get('resume_evidence')}`\n")
                fh.write("\n")

        fh.write("---\n\n")

        # 2. Review Required Section
        fh.write("## 2. Warning (Review Recommended / Provisional Scoring)\n")
        fh.write("These candidates scored between `0.65` and `0.84`, or triggered a critical issue. They can ")
        fh.write("be scored provisionally but their data might have minor completeness anomalies.\n\n")

        if not review_candidates:
            fh.write("*No warning candidates.*\n\n")
        else:
            for c in sorted(review_candidates, key=lambda x: x["score"]):
                fh.write(f"### ⚠️ {c['candidate_id']} [{c['role']}] - Quality Score: {c['score']:.2f}\n")
                fh.write("#### Flagged Issues:\n")
                for issue in c["issues"]:
                    fh.write(f"- **[{issue['severity'].upper()}]** `{issue['field']}`: {issue['issue']}\n")
                    if issue.get("expected"):
                        fh.write(f"  - *Expected*: {issue['expected']} | *Actual*: {issue['actual']}\n")
                if c["missing"]:
                    fh.write("#### Semantic Omissions:\n")
                    for m in c["missing"]:
                        fh.write(f"- **[{m.get('field_family').upper()}]**: {m.get('reason')}\n")
                        fh.write(f"  - *Evidence snippet*: `{m.get('resume_evidence')}`\n")
                fh.write("\n")

    print(f"Review queue report successfully generated at: {output_path}")

if __name__ == "__main__":
    main()
