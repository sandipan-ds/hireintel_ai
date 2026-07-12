"""Score comparison engine for True Score Evaluation.

Compares production scorer JSON output against multimodal judge LLM JSON outputs.
Computes the 8 metrics defined in the implementation plan:
1. Schema Agreement
2. Arithmetic Consistency
3. Per-Criterion Absolute Error
4. Total Score Absolute Error
5. Relative Percentage Error
6. Deviation Direction
7. Bias Direction
8. Aggregate Error Stats (MAE, RMSE, StdDev, Max Deviation)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class CandidateComparison:
    """Comparison results for a single candidate."""

    candidate_id: str
    role: str
    schema_agreement: bool
    scorer_arithmetic_consistent: bool
    judge_arithmetic_consistent: bool
    total_score_absolute_error: float
    relative_percentage_error: float
    deviation_direction: float  # scorer_total - judge_ref_total
    scorer_total: float
    judge_ref_total: float
    per_criterion_absolute_error: Dict[str, float] = field(default_factory=dict)
    flagged: bool = False
    flag_reason: str = ""


@dataclass
class BatchEvaluationReport:
    """Aggregate evaluation report for a batch of candidates."""

    mean_absolute_error: float
    root_mean_squared_error: float
    error_std_dev: float
    max_deviation: float
    bias_direction: float
    schema_agreement_rate: float
    arithmetic_consistency_rate: float
    flagged_count: int
    total_sampled: int
    candidate_comparisons: List[CandidateComparison] = field(default_factory=list)


def check_schema_agreement(scorer_data: Dict[str, Any], judge_data: Dict[str, Any]) -> bool:
    """Verify that scorer and judge outputs have the same REQs and SQ keys.

    Args:
        scorer_data: The scorer JSON output.
        judge_data: The judge JSON output.

    Returns:
        True if the requirements and sub-question keys match exactly, False otherwise.
    """
    try:
        scorer_reqs = scorer_data.get("reqs", [])
        judge_reqs = judge_data.get("reqs", [])

        if len(scorer_reqs) != len(judge_reqs):
            return False

        scorer_map = {r.get("requirement_id"): r for r in scorer_reqs if r.get("requirement_id")}
        judge_map = {r.get("requirement_id"): r for r in judge_reqs if r.get("requirement_id")}

        if set(scorer_map.keys()) != set(judge_map.keys()):
            return False

        for req_id, s_req in scorer_map.items():
            j_req = judge_map[req_id]
            s_sq = s_req.get("rubric_sq_scores", {})
            j_sq = j_req.get("rubric_sq_scores", {})
            if set(s_sq.keys()) != set(j_sq.keys()):
                return False

        return True
    except Exception:
        return False


def verify_arithmetic_consistency(data: Dict[str, Any]) -> bool:
    """Verify if the declared total score matches the sum of requirement contributions.

    Args:
        data: Scorer or judge JSON output.

    Returns:
        True if arithmetically consistent.
    """
    try:
        declared_total = float(data.get("total", 0.0))
        reqs = data.get("reqs", [])
        if not reqs:
            return False

        computed_total = 0.0
        for req in reqs:
            contrib = float(req.get("contribution", 0.0))
            computed_total += contrib

        return abs(declared_total - computed_total) < 0.001
    except Exception:
        return False


def recompute_total(data: Dict[str, Any]) -> float:
    """Recompute candidate total score deterministically in code from sub-scores.

    Args:
        data: Candidate score dictionary.

    Returns:
        Recomputed total score float.
    """
    try:
        total = 0.0
        reqs = data.get("reqs", [])
        for r in reqs:
            weight = float(r.get("weight_percentage", 0.0))
            sq_scores = r.get("rubric_sq_scores", {})
            if sq_scores:
                n_queries = len(sq_scores)
                sub_score_sum = sum(float(v) for v in sq_scores.values())
                contrib = weight * (sub_score_sum / n_queries) if n_queries > 0 else 0.0
                total += contrib
            else:
                total += float(r.get("contribution", 0.0))
        return round(total, 4)
    except Exception:
        return 0.0


def compute_candidate_metrics(
    candidate_id: str,
    role: str,
    scorer_data: Dict[str, Any],
    judge_gemini: Optional[Dict[str, Any]],
    judge_minimax: Optional[Dict[str, Any]],
) -> CandidateComparison:
    """Compute all evaluation metrics for a single candidate.

    Args:
        candidate_id: ID of the candidate.
        role: Candidate's role name.
        scorer_data: JSON output from the production scorer.
        judge_gemini: Optional JSON output from Gemini.
        judge_minimax: Optional JSON output from Minimax.

    Returns:
        CandidateComparison object.
    """
    # 1. Establish reference scores
    # If both judges succeeded, the reference is the median (average of the two for N=2)
    # If only one succeeded, use that one. If both failed, raise ValueError.
    judge_list = []
    if judge_gemini:
        judge_list.append(judge_gemini)
    if judge_minimax:
        judge_list.append(judge_minimax)

    if not judge_list:
        return CandidateComparison(
            candidate_id=candidate_id,
            role=role,
            schema_agreement=False,
            scorer_arithmetic_consistent=verify_arithmetic_consistency(scorer_data),
            judge_arithmetic_consistent=False,
            total_score_absolute_error=0.0,
            relative_percentage_error=0.0,
            deviation_direction=0.0,
            scorer_total=float(scorer_data.get("total", 0.0)),
            judge_ref_total=0.0,
            flagged=True,
            flag_reason="Both judges failed to evaluate candidate.",
        )

    # Scorer details (recomputed to protect against scorer arithmetic errors)
    scorer_total = recompute_total(scorer_data)
    scorer_arithmetic = verify_arithmetic_consistency(scorer_data)

    # Resolve Reference Total (based on recomputed values to clear LLM arithmetic errors)
    totals = [recompute_total(j) for j in judge_list]
    ref_total = sum(totals) / len(totals)  # Median of 1 or 2 is just the mean

    # Schema agreement (scorer vs all successful judges)
    schema_agreement = True
    for judge in judge_list:
        if not check_schema_agreement(scorer_data, judge):
            schema_agreement = False
            break

    # Judge arithmetic consistency
    judge_arithmetic = True
    for judge in judge_list:
        if not verify_arithmetic_consistency(judge):
            judge_arithmetic = False
            break

    # Calculate absolute and relative errors
    abs_error = abs(scorer_total - ref_total)
    rel_error = (abs_error / ref_total * 100.0) if ref_total > 0.0 else 0.0
    deviation = scorer_total - ref_total

    # Per-criterion subscore errors (SQ keys)
    per_criterion_absolute_error: Dict[str, float] = {}
    if schema_agreement:
        # Build map of judge SQ scores
        # We average SQ scores from successful judges to form the reference SQ score
        scorer_reqs = scorer_data.get("reqs", [])
        for s_req in scorer_reqs:
            req_id = s_req.get("requirement_id")
            s_sq_scores = s_req.get("rubric_sq_scores", {})
            for sq_key, s_val in s_sq_scores.items():
                j_vals = []
                for judge in judge_list:
                    # Find corresponding req in judge
                    j_req = next((r for r in judge.get("reqs", []) if r.get("requirement_id") == req_id), None)
                    if j_req:
                        j_val = j_req.get("rubric_sq_scores", {}).get(sq_key)
                        if j_val is not None:
                            j_vals.append(float(j_val))
                if j_vals:
                    ref_sq_val = sum(j_vals) / len(j_vals)
                    per_criterion_absolute_error[f"{req_id}_{sq_key}"] = abs(float(s_val) - ref_sq_val)

    # Escalation policy
    flagged = False
    flag_reasons = []

    if rel_error > 10.0:
        flagged = True
        flag_reasons.append(f"Relative error ({rel_error:.2f}%) exceeds 10% threshold")
    if not schema_agreement:
        flagged = True
        flag_reasons.append("Schema mismatch between scorer and judge")
    if not scorer_arithmetic:
        flagged = True
        flag_reasons.append("Scorer output is arithmetically inconsistent")
    if not judge_arithmetic:
        flagged = True
        flag_reasons.append("One or more judge outputs are arithmetically inconsistent")
    if len(judge_list) < 2:
        # Don't flag purely because one judge is missing, but log it
        pass

    return CandidateComparison(
        candidate_id=candidate_id,
        role=role,
        schema_agreement=schema_agreement,
        scorer_arithmetic_consistent=scorer_arithmetic,
        judge_arithmetic_consistent=judge_arithmetic,
        total_score_absolute_error=abs_error,
        relative_percentage_error=rel_error,
        deviation_direction=deviation,
        scorer_total=scorer_total,
        judge_ref_total=ref_total,
        per_criterion_absolute_error=per_criterion_absolute_error,
        flagged=flagged,
        flag_reason="; ".join(flag_reasons) if flagged else "",
    )


def generate_batch_report(comparisons: List[CandidateComparison]) -> BatchEvaluationReport:
    """Compile aggregate batch evaluation statistics across all candidate comparisons.

    Args:
        comparisons: List of computed CandidateComparison objects.

    Returns:
        BatchEvaluationReport object.
    """
    total = len(comparisons)
    if total == 0:
        return BatchEvaluationReport(
            mean_absolute_error=0.0,
            root_mean_squared_error=0.0,
            error_std_dev=0.0,
            max_deviation=0.0,
            bias_direction=0.0,
            schema_agreement_rate=0.0,
            arithmetic_consistency_rate=0.0,
            flagged_count=0,
            total_sampled=0,
        )

    errors = [c.total_score_absolute_error for c in comparisons]
    deviations = [c.deviation_direction for c in comparisons]
    squared_errors = [e**2 for e in errors]

    mae = sum(errors) / total
    rmse = math.sqrt(sum(squared_errors) / total)
    bias = sum(deviations) / total
    max_dev = max(errors) if errors else 0.0

    # Variance and Standard Deviation of the error
    # Variance = mean(e^2) - mean(e)^2
    variance = (sum(squared_errors) / total) - (mae**2)
    std_dev = math.sqrt(max(0.0, variance))

    schema_agreements = sum(1 for c in comparisons if c.schema_agreement)
    arithmetic_consistencies = sum(
        1 for c in comparisons if c.scorer_arithmetic_consistent and c.judge_arithmetic_consistent
    )
    flagged_count = sum(1 for c in comparisons if c.flagged)

    return BatchEvaluationReport(
        mean_absolute_error=mae,
        root_mean_squared_error=rmse,
        error_std_dev=std_dev,
        max_deviation=max_dev,
        bias_direction=bias,
        schema_agreement_rate=(schema_agreements / total * 100.0),
        arithmetic_consistency_rate=(arithmetic_consistencies / total * 100.0),
        flagged_count=flagged_count,
        total_sampled=total,
        candidate_comparisons=comparisons,
    )
