#!/usr/bin/env python3
"""Generate comparative reports for True Score Evaluation.

Reads scorer and judge outputs from a batch directory, computes metrics,
and writes comparison_report.json, flagged_for_review.json, and comparison_report.md.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.score_comparator import (
    CandidateComparison,
    compute_candidate_metrics,
    generate_batch_report,
)

logger = logging.getLogger("generate_judge_eval_report")
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

JUDGE_EVAL_DIR = ROOT / "data/eval/judge_eval"


def compile_report_for_batch(batch_dir: Path) -> None:
    """Compile comparative reports for a specific evaluation batch.

    Args:
        batch_dir: Path to the batch folder.
    """
    if not batch_dir.exists():
        logger.error("Batch folder %s does not exist.", batch_dir)
        return

    config_file = batch_dir / "config.json"
    progress_file = batch_dir / "progress.json"

    if not config_file.exists() or not progress_file.exists():
        logger.error("Missing batch configuration config.json or progress.json in %s", batch_dir)
        return

    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
        progress = json.loads(progress_file.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("Failed to parse batch configuration JSON files: %s", e)
        return

    # Find completed samples
    samples_dir = batch_dir / "samples"
    if not samples_dir.exists():
        logger.error("No samples directory found under %s", batch_dir)
        return

    candidate_ids = [d.name for d in samples_dir.iterdir() if d.is_dir()]
    if not candidate_ids:
        logger.error("No candidate sample folders found under %s", samples_dir)
        return

    comparisons: List[CandidateComparison] = []
    skipped_count = 0

    # Requirement metrics accumulator for requirement-level gap analysis
    req_errors: Dict[str, List[float]] = defaultdict(list)
    req_names: Dict[str, str] = {}

    for cid in sorted(candidate_ids):
        sample_folder = samples_dir / cid
        scorer_file = sample_folder / "scorer_output.json"
        gemini_file = sample_folder / "judge_gemini.json"
        minimax_file = sample_folder / "judge_minimax.json"

        if not scorer_file.exists():
            logger.warning("Scorer output missing for candidate %s, skipping.", cid)
            skipped_count += 1
            continue

        try:
            scorer_data = json.loads(scorer_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error("Failed to parse scorer output for %s: %s", cid, e)
            skipped_count += 1
            continue

        # Load successful judge outputs
        gemini_data = None
        minimax_data = None

        if gemini_file.exists():
            try:
                gemini_data = json.loads(gemini_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("Gemini output corrupt for %s: %s", cid, e)

        if minimax_file.exists():
            try:
                minimax_data = json.loads(minimax_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("Minimax output corrupt for %s: %s", cid, e)

        # Compute candidate comparison
        role = progress.get("candidates", {}).get(cid, {}).get("role", "Unknown")
        comp = compute_candidate_metrics(cid, role, scorer_data, gemini_data, minimax_data)
        comparisons.append(comp)

        # Extract requirement-level errors for schema-aligned candidates
        if comp.schema_agreement:
            for s_req in scorer_data.get("reqs", []):
                req_id = s_req.get("requirement_id")
                req_name = s_req.get("requirement_name", "")
                if req_id:
                    req_names[req_id] = req_name
                    # Find matching requirement in judges to compute difference
                    j_vals = []
                    for j_data in [gemini_data, minimax_data]:
                        if j_data:
                            j_req = next((r for r in j_data.get("reqs", []) if r.get("requirement_id") == req_id), None)
                            if j_req and j_req.get("sub_score") is not None:
                                j_vals.append(float(j_req["sub_score"]))

                    if j_vals:
                        ref_sub_score = sum(j_vals) / len(j_vals)
                        scorer_sub_score = float(s_req.get("sub_score", 0.0))
                        req_errors[req_id].append(abs(scorer_sub_score - ref_sub_score))

    if not comparisons:
        logger.error("No valid candidate comparisons could be computed.")
        return

    # Generate aggregate batch report
    batch_report = generate_batch_report(comparisons)

    # 1. Output comparison_report.json
    comparisons_json = []
    for c in comparisons:
        comparisons_json.append({
            "candidate_id": c.candidate_id,
            "role": c.role,
            "schema_agreement": c.schema_agreement,
            "scorer_arithmetic_consistent": c.scorer_arithmetic_consistent,
            "judge_arithmetic_consistent": c.judge_arithmetic_consistent,
            "total_score_absolute_error": round(c.total_score_absolute_error, 4),
            "relative_percentage_error": round(c.relative_percentage_error, 2),
            "deviation_direction": round(c.deviation_direction, 4),
            "scorer_total": round(c.scorer_total, 4),
            "judge_ref_total": round(c.judge_ref_total, 4),
            "flagged": c.flagged,
            "flag_reason": c.flag_reason,
            "per_criterion_absolute_error": {k: round(v, 4) for k, v in c.per_criterion_absolute_error.items()},
        })

    report_json = {
        "batch_id": batch_report.total_sampled,
        "metrics": {
            "mean_absolute_error": round(batch_report.mean_absolute_error, 4),
            "root_mean_squared_error": round(batch_report.root_mean_squared_error, 4),
            "error_std_dev": round(batch_report.error_std_dev, 4),
            "max_deviation": round(batch_report.max_deviation, 4),
            "bias_direction": round(batch_report.bias_direction, 4),
            "schema_agreement_rate": round(batch_report.schema_agreement_rate, 2),
            "arithmetic_consistency_rate": round(batch_report.arithmetic_consistency_rate, 2),
            "flagged_count": batch_report.flagged_count,
            "total_sampled": batch_report.total_sampled,
            "skipped_count": skipped_count,
        },
        "candidates": comparisons_json,
    }

    (batch_dir / "comparison_report.json").write_text(json.dumps(report_json, indent=2), encoding="utf-8")
    logger.info("Saved comparison_report.json")

    # 2. Output flagged_for_review.json
    flagged_candidates = [c for c in comparisons_json if c["flagged"]]
    flagged_json = {
        "batch_id": config.get("batch_id"),
        "flagged_count": len(flagged_candidates),
        "candidates": flagged_candidates,
    }
    (batch_dir / "flagged_for_review.json").write_text(json.dumps(flagged_json, indent=2), encoding="utf-8")
    logger.info("Saved flagged_for_review.json")

    # 3. Output comparison_report.md
    md_lines = [
        f"# True Score Evaluation Report: {config.get('batch_id')}",
        "",
        f"**Generated At:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Random Seed:** {config.get('seed')}",
        f"**Scorer Model:** Ollama qwen2.5:3b (production)",
        f"**Judge Models:** {config.get('judge_models', {}).get('gemini')} (Google) & {config.get('judge_models', {}).get('minimax')} (Minimax-M3)",
        "",
        "## Executive Summary",
        "",
        "This sample-based evaluation protocol checks whether the production scoring engine matches the score judgment of advanced multimodal frontier-grade LLMs reading the original resumes directly.",
        "",
        "| Metric | Value | Interpretation |",
        "|---|---|---|",
        f"| **Mean Absolute Error (MAE)** | **{batch_report.mean_absolute_error:.4f}** | Average deviation in total score (0.0 - 100.0) |",
        f"| **Root Mean Squared Error (RMSE)** | **{batch_report.root_mean_squared_error:.4f}** | Penalizes larger deviations |",
        f"| **Error Standard Deviation** | **{batch_report.error_std_dev:.4f}** | Consistency/spread of scorer errors |",
        f"| **Maximum Deviation** | **{batch_report.max_deviation:.4f}** | Largest single candidate score discrepancy |",
        f"| **Bias Direction** | **{batch_report.bias_direction:.4f}** | Positive = scorer overscores; Negative = underscores vs judges |",
        f"| **Schema Agreement Rate** | **{batch_report.schema_agreement_rate:.1f}%** | Percent of outputs matching structural JSON expectations |",
        f"| **Arithmetic Consistency Rate** | **{batch_report.arithmetic_consistency_rate:.1f}%** | Percent of outputs with mathematically consistent total totals |",
        f"| **Flagged for Human Review** | **{batch_report.flagged_count}** / {batch_report.total_sampled} | Candidates with relative error >10% or syntax errors |",
        "",
    ]

    # Add flagged warnings
    if batch_report.flagged_count > 0:
        md_lines.extend([
            f"> [!WARNING]",
            f"> **{batch_report.flagged_count} candidate evaluations have been flagged** due to exceeding the ±10% score error threshold or schema/arithmetic discrepancies. Please inspect the flagged candidate details below.",
            "",
        ])

    # Per-Candidate Comparison Table
    md_lines.extend([
        "## Candidate Comparison Details",
        "",
        "| Candidate ID | Role | Scorer Total | Ref Total | Abs Error | Rel Error % | Flagged? | Reasons / Discrepancies |",
        "|---|---|---|---|---|---|---|---|",
    ])

    for c in comparisons:
        flag_cell = "⚠️ **Yes**" if c.flagged else "No"
        flag_reason = c.flag_reason if c.flagged else ""
        md_lines.append(
            f"| `{c.candidate_id}` | {c.role} | {c.scorer_total:.4f} | {c.judge_ref_total:.4f} | {c.total_score_absolute_error:.4f} | {c.relative_percentage_error:.2f}% | {flag_cell} | {flag_reason} |"
        )

    md_lines.append("")

    # Requirement Divergence
    md_lines.extend([
        "## Requirement-Level Divergence Analysis",
        "",
        "Shows which job requirements have the highest discrepancy between the production scorer and the judge models. Higher MAE indicates areas where RAG retrieval or scoring rubrics require adjustment.",
        "",
        "| Requirement ID | Requirement Name | Average Sub-Score MAE | Candidate Samples |",
        "|---|---|---|---|",
    ])

    sorted_reqs = sorted(req_errors.items(), key=lambda x: sum(x[1])/len(x[1]) if x[1] else 0.0, reverse=True)
    for req_id, errs in sorted_reqs:
        avg_err = sum(errs) / len(errs)
        name = req_names.get(req_id, "Unknown")
        md_lines.append(f"| `{req_id}` | {name} | **{avg_err:.4f}** | {len(errs)} |")

    md_lines.append("")

    # Flagged candidates list
    if flagged_candidates:
        md_lines.extend([
            "## Flagged Candidate Summary",
            "",
        ])
        for c in comparisons:
            if c.flagged:
                md_lines.extend([
                    f"### Candidate: `{c.candidate_id}` ({c.role})",
                    f"- **Scorer Total:** `{c.scorer_total:.4f}`",
                    f"- **Judge Reference Total:** `{c.judge_ref_total:.4f}`",
                    f"- **Deviation:** `{c.deviation_direction:+.4f}` (Relative Error: `{c.relative_percentage_error:.2f}%`)",
                    f"- **Flag Reasons:** {c.flag_reason}",
                    "",
                ])

    (batch_dir / "comparison_report.md").write_text("\n".join(md_lines), encoding="utf-8")
    logger.info("Saved comparison_report.md")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Judge LLM comparison reports.")
    parser.add_argument("--batch", type=str, help="Timestamp or folder name of the batch to compile.")
    args = parser.parse_args()

    # Find the target batch directory
    if args.batch:
        batch_dir = JUDGE_EVAL_DIR / args.batch
        if not batch_dir.exists():
            batch_dir = JUDGE_EVAL_DIR / f"batch_{args.batch}"
    else:
        # Find latest batch run directory
        if JUDGE_EVAL_DIR.exists():
            batches = sorted(JUDGE_EVAL_DIR.glob("batch_*"))
            if batches:
                batch_dir = batches[-1]
            else:
                batch_dir = None
        else:
            batch_dir = None

    if not batch_dir or not batch_dir.exists():
        logger.error("No valid batch directory found to generate reports.")
        return

    logger.info("Compiling reports for batch: %s", batch_dir)
    compile_report_for_batch(batch_dir)


if __name__ == "__main__":
    main()
