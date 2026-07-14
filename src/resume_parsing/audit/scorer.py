# This module computes the final extraction-quality scores and determines
# the review status of the audited resume JSON.
#
# It applies a weighted quality formula using multiple scoring dimensions:
# schema validity, field completeness, section completeness, evidence coverage,
# parser agreement, and OCR confidence.
#
# This allows the system to route candidates to the appropriate processing pipeline
# (automatic pass, human review queue, or failed/re-extract).

"""Scoring and status assignment for quality audit (DEC-036)."""

from typing import List, Dict, Any
from src.resume_parsing.audit.models import AuditCheck, QualityScores

# Weights mapped to individual audit layers per 08_JSON_QUALITY_AUDIT_SPEC.md §14.2
WEIGHTS = {
    "schema_validity":      0.20,
    "field_completeness":   0.25,
    "section_completeness": 0.20,
    "evidence_coverage":    0.20,
    "parser_agreement":     0.10,
    "ocr_quality":          0.05,
}

def compute_scores(
    schema_score: float,
    field_score: float,
    section_score: float,
    evidence_score: float,
    agreement_score: float,
    ocr_score: float,
) -> QualityScores:
    """
    Calculate the overall extraction quality score using the weighted formula.

    Returns:
        A QualityScores object containing individual dimension scores and overall score.
    """
    overall = (
        WEIGHTS["schema_validity"] * schema_score +
        WEIGHTS["field_completeness"] * field_score +
        WEIGHTS["section_completeness"] * section_score +
        WEIGHTS["evidence_coverage"] * evidence_score +
        WEIGHTS["parser_agreement"] * agreement_score +
        WEIGHTS["ocr_quality"] * ocr_score
    )
    # Clip overall score to [0.0, 1.0] range
    overall = max(0.0, min(1.0, overall))

    return QualityScores(
        schema_validity=schema_score,
        field_completeness=field_score,
        section_completeness=section_score,
        evidence_coverage=evidence_score,
        parser_agreement=agreement_score,
        ocr_quality=ocr_score,
        overall_extraction_quality=overall
    )

def assign_status(scores: QualityScores, all_checks: List[AuditCheck]) -> str:
    """
    Determine the audit status ('passed', 'review_required', 'failed') based on scores and severity.

    Rules:
        - Score < 0.65 -> 'failed'
        - Score < 0.85 or any 'critical' check -> 'review_required'
        - Otherwise -> 'passed'
    """
    overall = scores.overall_extraction_quality
    
    if overall < 0.65:
        return "failed"

    # Promotes status to review_required if any critical severity issues exist
    has_critical = any(c.severity == "critical" for c in all_checks)
    if has_critical:
        return "review_required"

    if overall < 0.85:
        return "review_required"

    return "passed"

def extract_review_triggers(all_checks: List[AuditCheck]) -> List[AuditCheck]:
    """
    Filters and returns checks that are severe enough to trigger a review queue action.
    Triggers are any findings with severity 'critical' or 'error', or select warnings.
    """
    triggers = []
    for check in all_checks:
        if check.severity in ("critical", "error"):
            triggers.append(check)
        # Select warnings that are high value
        elif check.severity == "warning" and check.layer in ("section", "schema"):
            triggers.append(check)
    return triggers
