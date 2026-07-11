#!/usr/bin/env python3
"""Post-scoring run report generator for composed mode evaluations.

This script parses the ranked score outputs under `data/scores/composed/`
and diagnostic files under `run_reports/` to construct a comprehensive,
human-readable Markdown summary of the entire scoring batch run.

Usage:
    python scripts/generate_run_report.py             # Summarizes all 8 roles
    python scripts/generate_run_report.py --role DataScience
"""

import argparse
import collections
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
import statistics

# Setup logging
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("generate_run_report")

SCORES_DIR = Path("data/scores/composed")
RUN_REPORTS_DIR = Path("run_reports")
REVIEW_QUEUE_FILE = RUN_REPORTS_DIR / "review_queue.md"

ALL_ROLES = [
    "BusinessAnalyst",
    "DataScience",
    "JavaDeveloper",
    "ReactDeveloper",
    "SalesManager",
    "SQLDeveloper",
    "SrPythonDeveloper",
    "WebDesigning"
]

def parse_review_queue() -> dict[str, dict]:
    """Parse review_queue.md to identify failed/review candidate IDs with full detail.

    Handles the actual review_queue.md format:
        ### 🛑 WebDesigning_CAND_0016 [WebDesigning] - Quality Score: 0.62
        ### ⚠️  SalesManager_CAND_0046 [SalesManager] - Quality Score: 0.82

    Returns:
        Dict mapping candidate_id to a detail dict with keys:
            'severity': 'CRITICAL' | 'WARNING'
            'quality_score': float extraction quality score
            'issues': list[str] of short flagged-issue strings
    """
    flagged: dict[str, dict] = {}
    if not REVIEW_QUEUE_FILE.exists():
        logger.warning("review_queue.md not found at %s", REVIEW_QUEUE_FILE)
        return flagged

    content = REVIEW_QUEUE_FILE.read_text(encoding="utf-8")

    # Determine section boundaries
    critical_end = len(content)
    warning_start = len(content)
    m = re.search(r"^## 2\.", content, re.MULTILINE)
    if m:
        critical_end = m.start()
        warning_start = m.start()

    critical_block = content[:critical_end]
    warning_block = content[warning_start:]

    # Regex: matches header line, e.g.
    #   ### 🛑 WebDesigning_CAND_0016 [WebDesigning] - Quality Score: 0.62
    #   ### ⚠️  SalesManager_CAND_0046 [SalesManager] - Quality Score: 0.82
    header_re = re.compile(
        r"^### .+?([A-Za-z]+_CAND_\d+).*?Quality Score:\s*([0-9.]+)",
        re.MULTILINE,
    )
    issue_re = re.compile(r"- \*\*\[(WARNING|ERROR)\]\*\* `([^`]+)`:(.*?)(?=\n\s*- \*\*\[|\n###|$)", re.DOTALL)

    def _extract_issues(block: str, start: int, next_start: int) -> list[str]:
        """Pull short issue strings from the block between two header positions."""
        segment = block[start:next_start]
        issues = []
        for m in issue_re.finditer(segment):
            severity, field, desc = m.group(1), m.group(2), m.group(3).strip()
            # Shorten desc to first sentence
            short_desc = desc.split("\n")[0].strip().lstrip(":- ").split("  ")[0]
            issues.append(f"[{severity}] {field}: {short_desc}")
        return issues

    for block, severity in ((critical_block, "CRITICAL"), (warning_block, "WARNING")):
        matches = list(header_re.finditer(block))
        for idx, hm in enumerate(matches):
            cand_id = hm.group(1)
            try:
                quality_score = float(hm.group(2))
            except ValueError:
                quality_score = 0.0
            next_pos = matches[idx + 1].start() if idx + 1 < len(matches) else len(block)
            issues = _extract_issues(block, hm.end(), next_pos)
            flagged[cand_id] = {
                "severity": severity,
                "quality_score": quality_score,
                "issues": issues,
            }

    logger.info("review_queue.md: found %d flagged candidates", len(flagged))
    return flagged

def parse_diagnostics(role: str) -> dict[str, Any]:
    """Parse the zero-score diagnostics text file for a given role.
    
    Returns:
        Dict containing counts and requirement breakdown.
    """
    diag_file = RUN_REPORTS_DIR / f"score_diagnostic_{role}.txt"
    out = {
        "total_no_evidence": 0,
        "total_wrong_inference": 0,
        "by_req": collections.defaultdict(lambda: {"no_evidence": 0, "wrong_inference": 0}),
        "by_sub_query": collections.defaultdict(int)
    }
    
    if not diag_file.exists():
        return out
        
    with diag_file.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            # Format: [ZERO_NO_EVIDENCE]       cand_X REQ-001 skill_presence — no matching text found
            match = re.match(r"\[(ZERO_NO_EVIDENCE|ZERO_WRONG_INFERENCE)\]\s+(\S+)\s+(\S+)\s+(\S+)", line)
            if match:
                tag, cand_id, req_name, sq_key = match.groups()
                is_no_ev = (tag == "ZERO_NO_EVIDENCE")
                
                if is_no_ev:
                    out["total_no_evidence"] += 1
                    out["by_req"][req_name]["no_evidence"] += 1
                else:
                    out["total_wrong_inference"] += 1
                    out["by_req"][req_name]["wrong_inference"] += 1
                    
                out["by_sub_query"][f"{req_name} ({sq_key})"] += 1
                
    return out

def generate_report(target_roles: list[str]) -> Path:
    """Read all results, generate the Markdown report, and write it to disk.
    
    Returns:
        Path to the generated report file.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = RUN_REPORTS_DIR / f"run_report_{timestamp}.md"
    
    flagged_candidates = parse_review_queue()
    
    role_summaries = []
    global_total_scored = 0
    global_scores = []
    
    # Load scoring metadata for each role
    for role in target_roles:
        ranked_file = SCORES_DIR / f"{role}_ranked.json"
        if not ranked_file.exists():
            logger.warning("Scoring output not found for role '%s' at %s", role, ranked_file)
            continue
            
        with ranked_file.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
            
        rankings = data.get("rankings", [])
        scores = [item["total"] for item in rankings]
        global_scores.extend(scores)
        global_total_scored += len(rankings)
        
        # Parse diagnostics
        diags = parse_diagnostics(role)
        
        role_summaries.append({
            "role": role,
            "n_candidates": len(rankings),
            "min_score": min(scores) if scores else 0.0,
            "max_score": max(scores) if scores else 0.0,
            "mean_score": data.get("mean_score", 0.0),
            "median_score": statistics.median(scores) if scores else 0.0,
            "std_dev": statistics.stdev(scores) if len(scores) > 1 else 0.0,
            "top_candidates": rankings[:10],
            "diags": diags,
            "theta": data.get("theta", 0.0),
            "max_chunks": data.get("max_chunks_per_query", 0)
        })
        
    if not role_summaries:
        logger.error("No scoring summaries found under %s. Run score_batch_composed.py first.", SCORES_DIR)
        sys.exit(1)
        
    # Write report content
    lines = []
    lines.append("# HireIntel AI — Composed Scoring Run Report")
    lines.append(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # Overall summary metrics
    lines.append("## 1. Overall Run Summary")
    lines.append(f"- **Total Candidates Scored**: {global_total_scored}")
    lines.append(f"- **Global Mean Score**: {round(statistics.mean(global_scores), 2) if global_scores else 0.0}")
    lines.append(f"- **Global Median Score**: {round(statistics.median(global_scores), 2) if global_scores else 0.0}")
    
    # Table of roles
    lines.append("\n### Per-Role Scoring Profiles")
    lines.append("| Role | Candidates Scored | Mean Score | Median Score | Min / Max Score | Std Dev | Theta |")
    lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: |")
    for summary in role_summaries:
        lines.append(
            f"| {summary['role']} | {summary['n_candidates']} | {round(summary['mean_score'], 2)} | "
            f"{round(summary['median_score'], 2)} | {round(summary['min_score'], 2)} / {round(summary['max_score'], 2)} | "
            f"{round(summary['std_dev'], 2)} | {summary['theta']} |"
        )
        
    # Zero-score diagnostic summary table
    lines.append("\n### Zero-Score Diagnostic Summary")
    lines.append("| Role | `ZERO_NO_EVIDENCE` | `ZERO_WRONG_INFERENCE` | Most Prone REQ |")
    lines.append("| :--- | :---: | :---: | :--- |")
    for summary in role_summaries:
        diags = summary["diags"]
        most_prone = "None"
        if diags["by_sub_query"]:
            top_sq = max(diags["by_sub_query"].items(), key=lambda x: x[1])
            most_prone = f"{top_sq[0]} ({top_sq[1]} occurrences)"
            
        lines.append(
            f"| {summary['role']} | {diags['total_no_evidence']} | "
            f"{diags['total_wrong_inference']} | {most_prone} |"
        )
        
    # --- Section 2: Audit-Flagged Candidates cross-referenced with scoring results ---
    # Build a full candidate_id → (rank, total_score) lookup across ALL ranked candidates
    all_ranked_lookup: dict[str, dict] = {}  # cand_id → {rank, total, role}
    for summary in role_summaries:
        ranked_file = SCORES_DIR / f"{summary['role']}_ranked.json"
        if ranked_file.exists():
            with ranked_file.open("r", encoding="utf-8") as fh:
                full_data = json.load(fh)
            for item in full_data.get("rankings", []):
                all_ranked_lookup[item["candidate_id"]] = {
                    "rank": item.get("rank", "-"),
                    "total": item.get("total", 0.0),
                    "role": summary["role"],
                }

    lines.append("\n## 2. Quality Audit Flagged Candidates — Scoring Cross-Reference")
    lines.append(
        f"All **{len(flagged_candidates)}** candidates flagged in "
        "`review_queue.md` are listed below with their actual scoring rank and "
        "provisional score. Scores are computed from whatever data was extracted; "
        "gaps may suppress rubric contributions."
    )

    if not flagged_candidates:
        lines.append("\n*No flagged candidates found in `review_queue.md`.*")
    else:
        lines.append("\n| Candidate ID | Role | Severity | Extr. Quality | Scoring Rank | Provisional Score | Top Extraction Issues |")
        lines.append("| :--- | :--- | :---: | :---: | :---: | :---: | :--- |")
        # Sort: CRITICAL first, then by quality score ascending (worst first)
        sorted_flagged = sorted(
            flagged_candidates.items(),
            key=lambda kv: (0 if kv[1]["severity"] == "CRITICAL" else 1, kv[1]["quality_score"]),
        )
        for cid, detail in sorted_flagged:
            icon = "🛑" if detail["severity"] == "CRITICAL" else "⚠️"
            sev = detail["severity"]
            q_score = round(detail["quality_score"], 2)
            scored = all_ranked_lookup.get(cid)
            rank_str = str(scored["rank"]) if scored else "not scored"
            score_str = str(round(scored["total"], 3)) if scored else "—"
            role_str = scored["role"] if scored else "unknown"
            # Truncate issues to first 2 for table readability
            issues_short = "; ".join(detail["issues"][:2]) if detail["issues"] else "—"
            lines.append(
                f"| {icon} {cid} | {role_str} | {sev} | {q_score} | "
                f"{rank_str} | {score_str} | {issues_short} |"
            )
            
    # Section for detailed role rank lists
    lines.append("\n## 3. Top Ranked Candidates (Top 10 per Role)")
    for summary in role_summaries:
        lines.append(f"\n### {summary['role']}")
        lines.append(f"*Evaluated {summary['n_candidates']} candidates (theta={summary['theta']}, max_chunks={summary['max_chunks']})*")
        lines.append("\n| Rank | Candidate ID | Total Score | Audit Warning? | Top Gaps / Notes |")
        lines.append("| :---: | :--- | :---: | :---: | :--- |")
        for cand in summary["top_candidates"]:
            cid = cand["candidate_id"]
            warning = ""
            if cid in flagged_candidates:
                warning = "🛑 CRITICAL" if flagged_candidates[cid] == "CRITICAL" else "⚠️ WARNING"
                
            # Collect details about candidate gaps from their trace if present
            gap_summary = "N/A"
            reqs = cand.get("reqs", [])
            if reqs:
                # Find requirements with lowest score
                low_scored = sorted(reqs, key=lambda x: x.get("normalized_score", 1.0))
                gaps = [f"{r['requirement_name']} ({round(r['normalized_score'], 2)})" for r in low_scored[:2] if r.get("normalized_score", 1.0) < 0.5]
                if gaps:
                    gap_summary = "Lowest: " + ", ".join(gaps)
                else:
                    gap_summary = "Solid profile across requirements"
                    
            lines.append(f"| {cand['rank']} | {cid} | {round(cand['total'], 2)} | {warning} | {gap_summary} |")
            
    # Detail on diagnostics for validation
    lines.append("\n## 4. Zero-Score Diagnostic Analysis (Top Calibration Gaps)")
    lines.append("Sub-questions flagged with `ZERO_WRONG_INFERENCE` suggest candidates have the text in their resume, but the LLM judge did not infer a score. These are prompt-calibration candidates:")
    
    calibration_issues = []
    for summary in role_summaries:
        diags = summary["diags"]
        for sq, count in diags["by_sub_query"].items():
            # Check if this sub-query has wrong_inference flags
            req_name = sq.split()[0]
            wrong_inf_count = diags["by_req"][req_name]["wrong_inference"]
            if wrong_inf_count > 0:
                calibration_issues.append((summary["role"], sq, count, wrong_inf_count))
                
    if calibration_issues:
        # Sort by total occurrences desc
        calibration_issues.sort(key=lambda x: x[2], reverse=True)
        lines.append("\n| Role | Sub-Question | Total Zero Score Events | of which Wrong Inferences |")
        lines.append("| :--- | :--- | :---: | :---: |")
        for role, sq, total, wrong in calibration_issues[:15]:
            lines.append(f"| {role} | {sq} | {total} | {wrong} |")
    else:
        lines.append("\nNo `ZERO_WRONG_INFERENCE` events detected. Scoring alignment is fully clean!")
        
    report_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Wrote run report to %s", report_file)
    return report_file

def main():
    parser = argparse.ArgumentParser(description="Composed Scoring Run Report Generator")
    parser.add_argument(
        "--role", default=None,
        help="Specific role to summarize (default: all roles)."
    )
    args = parser.parse_args()
    
    if args.role:
        if args.role not in ALL_ROLES:
            logger.error("Role '%s' is not a valid HireIntel role. Choose from: %s", args.role, ALL_ROLES)
            sys.exit(1)
        target_roles = [args.role]
    else:
        target_roles = ALL_ROLES
        
    generate_report(target_roles)
    
if __name__ == "__main__":
    main()
