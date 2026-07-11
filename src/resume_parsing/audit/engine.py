# This module is the central orchestrator for the JSON Quality Audit Layer.
#
# It exposes the public audit_resume() API, which runs the five audit layers
# (Schema, Completeness, Evidence, Semantic, and Cross-Parser) in sequence.
# It then invokes the scorer to calculate final scores, assign status,
# and extract review triggers.

"""Audit Orchestrator Engine for JSON Quality Audit (DEC-036)."""

import logging
from typing import Dict, Any, List
from src.resume_parsing.audit.models import AuditResult, AuditCheck
from src.resume_parsing.audit import (
    layer_a_schema,
    layer_b_completeness,
    layer_c_evidence,
    layer_d_semantic,
    layer_e_cross_parser,
    scorer
)

logger = logging.getLogger(__name__)

def audit_resume(
    resume_json: Dict[str, Any],
    source_path: str,
    run_semantic: bool = True,
    run_cross_parser: bool = False,
) -> AuditResult:
    """
    Run the full JSON Quality Audit for one candidate.

    Args:
        resume_json:      Extracted candidate JSON dictionary.
        source_path:      Original PDF/DOCX file path.
        run_semantic:     Whether to call the LLM for Layer D.
        run_cross_parser: Whether to compare against old parser output (Layer E).

    Returns:
        An AuditResult object representing the full audit findings and status.
    """
    # Defensive checks on top-level structure
    if not isinstance(resume_json, dict):
        raise ValueError("resume_json must be a dictionary")
    
    candidate_id = resume_json.get("candidate_id") or "cand_unknown"
    doc_id = resume_json.get("document", {}).get("document_id") or f"doc_{candidate_id}"

    # 1. Run Layer A: Schema Validation
    schema_checks, schema_score = layer_a_schema.run(resume_json)

    # 2. Run Layer B: Field & Section Completeness
    field_checks, field_score = layer_b_completeness.run(resume_json)

    # Separate section checks from field checks
    section_checks = [c for c in field_checks if c.layer == "section"]
    # Adjust section score based on failed section checks (3 main section checks: exp, edu, skills)
    section_score = max(0.0, 1.0 - (len(section_checks) / 3.0))

    # 3. Run Layer C: Evidence Coverage
    evidence_checks, evidence_score = layer_c_evidence.run(resume_json)

    # Accumulate prior checks to help Layer D make skip decisions
    prior_checks = schema_checks + field_checks + evidence_checks

    # 4. Run Layer D: Semantic Missing-Info (LLM-assisted)
    semantic_checks: List[AuditCheck] = []
    missing_candidates = []
    semantic_score = 1.0
    if run_semantic:
        try:
            semantic_checks, missing_candidates, semantic_score = layer_d_semantic.run(
                resume_json=resume_json,
                skip_if_clean=True,
                prior_checks=prior_checks
            )
        except Exception as e:
            logger.error("Layer D (semantic audit) encountered an unhandled error: %s", e)

    # 5. Run Layer E: Cross-Parser Consistency
    conflicts = []
    agreement_score = 1.0
    if run_cross_parser:
        try:
            conflicts, agreement_score = layer_e_cross_parser.run(resume_json, source_path)
        except Exception as e:
            logger.error("Layer E (cross-parser audit) encountered an unhandled error: %s", e)

    # 6. OCR Quality check
    ocr_score = 1.0
    raw_info = resume_json.get("raw", {})
    ocr_text = raw_info.get("ocr_text")
    if ocr_text is not None and str(ocr_text).strip():
        # OCR route was used; try to get OCR confidence
        conf_info = resume_json.get("confidence", {})
        doc_conf = conf_info.get("document_confidence")
        if doc_conf is not None:
            ocr_score = float(doc_conf)
        else:
            field_conf = conf_info.get("field_confidence") or {}
            if field_conf:
                ocr_score = sum(float(v) for v in field_conf.values()) / len(field_conf)

    # 7. Compute Quality Scores
    scores = scorer.compute_scores(
        schema_score=schema_score,
        field_score=field_score,
        section_score=section_score,
        evidence_score=evidence_score,
        agreement_score=agreement_score,
        ocr_score=ocr_score
    )

    # Gather all checks for status and trigger extraction
    all_checks = prior_checks + semantic_checks
    
    # 8. Assign review status and triggers
    status = scorer.assign_status(scores, all_checks)
    triggers = scorer.extract_review_triggers(all_checks)

    # 9. Build summary metadata dict
    summary_data = {
        "human_action_recommended": status != "passed",
        "error_count": len([c for c in all_checks if c.severity == "error"]),
        "warning_count": len([c for c in all_checks if c.severity == "warning"]),
        "critical_count": len([c for c in all_checks if c.severity == "critical"]),
        "high_risk_sections": list(set(c.field.split(".")[-1] for c in all_checks if c.severity in ("error", "critical")))
    }

    return AuditResult(
        audit_version="1.0.0",
        document_id=doc_id,
        candidate_id=candidate_id,
        audit_status=status,
        schema_checks=schema_checks,
        field_checks=[c for c in field_checks if c.layer == "field"],
        section_checks=section_checks,
        evidence_coverage_checks=evidence_checks,
        semantic_checks=semantic_checks,
        missing_candidates=missing_candidates,
        conflicts=conflicts,
        quality_scores=scores,
        review_triggers=triggers,
        summary=summary_data
    )
