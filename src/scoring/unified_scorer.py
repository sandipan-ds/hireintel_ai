"""Unified scoring engine — orchestrates code-only and rubric-bound LLM modes.

Per ``WORKING_LOGIC.md`` ("Fundamental Rule"), the scoring engine operates in
two modes, both of which compute weight application and final aggregation in
code — never in the LLM:

* **Code-only scoring** — for fully measurable requirements: total experience,
  institute tier (lookup table), certification tier (lookup table), degree
  match, location match. No LLM is involved.

* **Rubric-bound LLM evidence scoring** — for requirements requiring judgment:
  skill depth, relevant experience, project complexity, domain expertise. The
  LLM reads the full content of the mapped section(s) via Section-Routed
  Evidence Retrieval and scores against a recruiter-defined rubric. The LLM
  never sees the weight and never computes the final weighted contribution.

This module routes each requirement to the correct mode, collects the results,
and produces a ``UnifiedCandidateEvaluation`` with per-item evidence, cached
scoring traces, and a deterministic 0–100 total.

The existing ``graded_scorer.py`` remains the Mode 1 engine for code-only
items. This module wraps it and adds Mode 2 for rubric-bound items.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.rag.chunker import ChunkRecord
from src.rag.section_routed import (
    SectionEvidence,
    classify_requirement_type,
    retrieve_evidence_for_requirement,
)
from src.scoring.graded_scorer import (
    CandidateEvaluation,
    CategoryEvaluation,
    ItemEvaluation,
    DEFAULT_EXPECTED_YEARS,
)
from src.scoring.rubric_scorer import (
    CachedScoringTrace,
    SubScoreResult,
    score_requirement_with_rubric,
)
from src.scoring.rubrics import is_code_only, get_rubric
from src.scoring.tier_lookup import get_institute_tier_points, get_certificate_tier_points
from src.resume_parsing.structured_profile import StructuredCandidateProfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Extended data classes — add scoring traces to the existing contract.
# ---------------------------------------------------------------------------

@dataclass
class UnifiedItemEvaluation(ItemEvaluation):
    """Per-item evaluation with an optional cached scoring trace.

    Extends ``ItemEvaluation`` with a ``scoring_trace`` field for items
    scored by the rubric-bound LLM. Code-only items may also carry a trace
    (from tier lookups) but it's simpler.

    The ``scoring_mode`` field records which mode scored this item:
    "code_only" or "rubric_llm".
    """

    scoring_mode: str = "code_only"
    scoring_trace: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base["scoring_mode"] = self.scoring_mode
        base["scoring_trace"] = self.scoring_trace
        return base


@dataclass
class UnifiedCategoryEvaluation:
    """Category-level evaluation with unified items."""

    name: str
    items: List[UnifiedItemEvaluation] = field(default_factory=list)

    @property
    def raw_score(self) -> float:
        return sum(i.raw_score for i in self.items)

    @property
    def max_score(self) -> float:
        return sum(i.importance for i in self.items)

    @property
    def score(self) -> float:
        return sum(i.score for i in self.items)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "raw_score": round(self.raw_score, 2),
            "max_score": round(self.max_score, 2),
            "score": round(self.score, 2),
            "items": [i.to_dict() for i in self.items],
        }


@dataclass
class UnifiedCandidateEvaluation:
    """Full candidate evaluation with both code-only and rubric-bound items.

    Backward-compatible with ``CandidateEvaluation.to_dict()`` output, with
    additional ``scoring_mode`` and ``scoring_trace`` fields per item.
    """

    candidate_id: str
    role: str
    total_raw: float
    total_max: float
    total: float
    categories: List[UnifiedCategoryEvaluation] = field(default_factory=list)
    has_flagged_institute: bool = False
    flagged_institutes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "role": self.role,
            "total_raw": round(self.total_raw, 2),
            "total_max": round(self.total_max, 2),
            "total": round(self.total, 2),
            "categories": [c.to_dict() for c in self.categories],
            "has_flagged_institute": self.has_flagged_institute,
            "flagged_institutes": self.flagged_institutes,
        }


# ---------------------------------------------------------------------------
# Code-only scoring for education, certification, location.
# ---------------------------------------------------------------------------

def _score_education_code_only(
    item_name: str,
    importance: float,
    structured_profile: StructuredCandidateProfile,
) -> UnifiedItemEvaluation:
    """Score an education requirement using code-only tier lookup.

    Uses the structured profile's degree list and the institute tier database.
    No LLM, no retrieval.

    Args:
        item_name: The education requirement (e.g., "BTech").
        importance: The recruiter-assigned weight.
        structured_profile: The deterministic structured profile.

    Returns:
        ``UnifiedItemEvaluation`` with degree match + institute tier.
    """
    # Check if the candidate has any degree that matches the requirement.
    degree_matched = False
    matched_degree = ""
    matched_institution = ""

    for degree_entry in structured_profile.degrees:
        # Simple keyword match — does the requirement appear in the degree?
        if item_name.lower() in degree_entry.degree.lower() or \
           degree_entry.degree.lower() in item_name.lower():
            degree_matched = True
            matched_degree = degree_entry.degree
            matched_institution = degree_entry.institution
            break

    # If no specific degree match, check if any degree exists.
    if not degree_matched and structured_profile.degrees:
        # Generic "degree required" — any degree matches.
        if any(kw in item_name.lower() for kw in ("degree", "graduation", "bachelor", "master", "education")):
            degree_matched = True
            matched_degree = structured_profile.degrees[0].degree
            matched_institution = structured_profile.degrees[0].institution

    # Institute tier lookup.
    tier_points = 0.50  # default for not listed
    if matched_institution:
        tier_points = get_institute_tier_points(matched_institution)

    # Check if the institute is flagged as fake/unknown.
    is_flagged = False
    if matched_institution:
        from src.scoring.tier_lookup import is_institute_flagged
        is_flagged = is_institute_flagged(matched_institution)

    # Score: degree_match (0 or 1) × institute_tier_points × importance.
    # If institute is flagged, apply a penalty (reduce score by 50%).
    degree_gate = 1.0 if degree_matched else 0.0
    flagged_penalty = 0.5 if is_flagged else 1.0
    raw_score = round(degree_gate * tier_points * importance * flagged_penalty, 2)

    # Build trace.
    trace = {
        "dimension_type": "education",
        "formula": "degree_match * institute_tier_points * flagged_penalty",
        "sub_scores": [
            {"key": "degree_match", "sub_score": degree_gate,
             "evidence": matched_degree if degree_matched else "No matching degree found"},
            {"key": "institute_tier", "sub_score": tier_points,
             "evidence": matched_institution or "No institution found"},
            {"key": "flagged_penalty", "sub_score": flagged_penalty,
             "evidence": "Institute flagged as fake/unknown" if is_flagged else "Institute not flagged"},
        ],
        "normalized_score": round(degree_gate * tier_points * flagged_penalty, 4),
    }

    reason = f"Degree match: {'Yes' if degree_matched else 'No'}"
    if matched_institution:
        reason += f" (Institute: {matched_institution}, tier points: {tier_points})"
    if is_flagged:
        reason += " [FLAGGED: Institute appears to be fake/unknown]"

    return UnifiedItemEvaluation(
        category="Education",
        item_name=item_name,
        description="",
        importance=importance,
        expected_years=0,
        matched=degree_matched,
        years_detected=0,
        raw_score=raw_score,
        score=raw_score,  # normalization applied at aggregate level
        section="Education",
        snippet=matched_degree,
        reason=reason,
        scoring_mode="code_only",
        scoring_trace=trace,
    )


def _score_certification_code_only(
    item_name: str,
    importance: float,
    structured_profile: StructuredCandidateProfile,
) -> UnifiedItemEvaluation:
    """Score a certification requirement using code-only tier lookup.

    Args:
        item_name: The certification requirement (e.g., "AWS Certified").
        importance: The recruiter-assigned weight.
        structured_profile: The deterministic structured profile.

    Returns:
        ``UnifiedItemEvaluation`` with cert match + provider tier.
    """
    # Check if the candidate has any certification that matches.
    cert_matched = False
    matched_cert = ""

    for cert_entry in structured_profile.certifications:
        if item_name.lower() in cert_entry.name.lower() or \
           any(kw in cert_entry.name.lower() for kw in item_name.lower().split()):
            cert_matched = True
            matched_cert = cert_entry.name
            break

    # Provider tier lookup.
    tier_points = 0.50  # default for not listed
    if matched_cert:
        tier_points = get_certificate_tier_points(matched_cert)

    # Score: cert_match (0 or 1) × provider_tier_points × importance.
    cert_gate = 1.0 if cert_matched else 0.0
    raw_score = round(cert_gate * tier_points * importance, 2)

    trace = {
        "dimension_type": "certification",
        "formula": "cert_match * provider_tier_points",
        "sub_scores": [
            {"key": "cert_match", "sub_score": cert_gate,
             "evidence": matched_cert if cert_matched else "No matching certification found"},
            {"key": "provider_tier", "sub_score": tier_points,
             "evidence": matched_cert or "No certification found"},
        ],
        "normalized_score": round(cert_gate * tier_points, 4),
    }

    reason = f"Certification match: {'Yes' if cert_matched else 'No'}"
    if matched_cert:
        reason += f" ({matched_cert}, tier points: {tier_points})"

    return UnifiedItemEvaluation(
        category="Certifications",
        item_name=item_name,
        description="",
        importance=importance,
        expected_years=0,
        matched=cert_matched,
        years_detected=0,
        raw_score=raw_score,
        score=raw_score,
        section="Certifications",
        snippet=matched_cert,
        reason=reason,
        scoring_mode="code_only",
        scoring_trace=trace,
    )


def _score_location_code_only(
    item_name: str,
    importance: float,
    profile: Dict[str, Any],
) -> UnifiedItemEvaluation:
    """Score a location requirement using code-only profile lookup.

    Args:
        item_name: The location requirement (e.g., "Mumbai").
        importance: The recruiter-assigned weight.
        profile: The parsed candidate profile (for contact/location info).

    Returns:
        ``UnifiedItemEvaluation`` with location match (binary).
    """
    # Extract location from the profile's contact or raw text.
    raw_text = profile.get("raw_text", "")
    contact = profile.get("contact", {})

    # Simple check: does the requirement appear in the raw text?
    item_lower = item_name.lower()
    raw_lower = raw_text.lower()

    # Strip common prefixes like "Location:" from the requirement.
    location_term = item_lower
    for prefix in ("location:", "location", "city:", "city"):
        if location_term.startswith(prefix):
            location_term = location_term[len(prefix):].strip()
            break

    matched = bool(location_term) and location_term in raw_lower
    raw_score = round(importance * (1.0 if matched else 0.0), 2)

    trace = {
        "dimension_type": "location",
        "formula": "match",
        "sub_scores": [
            {"key": "location_match", "sub_score": 1.0 if matched else 0.0,
             "evidence": f"Location '{location_term}' {'found' if matched else 'not found'} in resume"},
        ],
        "normalized_score": 1.0 if matched else 0.0,
    }

    return UnifiedItemEvaluation(
        category="Location",
        item_name=item_name,
        description="",
        importance=importance,
        expected_years=0,
        matched=matched,
        years_detected=0,
        raw_score=raw_score,
        score=raw_score,
        section="Personal_Info",
        snippet=location_term if matched else "",
        reason=f"Location {'match' if matched else 'no match'}: {location_term}",
        scoring_mode="code_only",
        scoring_trace=trace,
    )


# ---------------------------------------------------------------------------
# Unified scoring — the main entry point.
# ---------------------------------------------------------------------------

def evaluate_candidate_unified(
    profile: Dict[str, Any],
    weights: Dict[str, Any],
    candidate_chunks: List[ChunkRecord],
    structured_profile: StructuredCandidateProfile,
    llm_caller: Optional[Callable[[str], str]] = None,
    default_expected_years: int = DEFAULT_EXPECTED_YEARS,
) -> UnifiedCandidateEvaluation:
    """Score a candidate using both code-only and rubric-bound LLM modes.

    This is the main entry point for the unified scoring engine. It:
    1. Iterates through the weight config's categories and items.
    2. For each item, classifies the dimension type.
    3. Routes to code-only or rubric-bound LLM based on the dimension type.
    4. Collects results into a ``UnifiedCandidateEvaluation``.
    5. Aggregates to a 0–100 total deterministically.

    Args:
        profile: The parsed candidate profile dict.
        weights: The recruiter weight config dict.
        candidate_chunks: Chunks for this candidate (from the chunker).
        structured_profile: The deterministic structured profile.
        llm_caller: Optional callable for the rubric-bound LLM judge.
            If None, rubric-bound items get zero scores.
        default_expected_years: Default expected years when not in config.

    Returns:
        ``UnifiedCandidateEvaluation`` with per-item evidence, cached traces,
        and a deterministic 0–100 total.
    """
    candidate_id = (
        profile.get("candidate_id")
        or profile.get("id")
        or "unknown"
    )
    role = weights.get("role", "")

    # Normalization factor.
    total_max_cfg = float(weights.get("max_score") or 0)
    scale = float(
        weights.get("scale_factor")
        or (100.0 / total_max_cfg if total_max_cfg else 0.0)
    )

    total_raw = 0.0
    total_max = 0.0
    categories: List[UnifiedCategoryEvaluation] = []

    for category in weights.get("categories", []):
        cat_name = category.get("name", "Unknown")
        cat_eval = UnifiedCategoryEvaluation(name=cat_name)

        for item in category.get("items", []):
            item_name = item.get("name", "Unknown")
            importance = float(item.get("importance", 10)) or 10.0
            expected_years = float(
                item.get("expected_years")
                or item.get("expected_years", default_expected_years)
            )

            # Classify the dimension type for this item.
            dim_type = classify_requirement_type(cat_name, item_name)

            if is_code_only(dim_type):
                # ---- Code-only mode ----
                if dim_type == "education":
                    item_eval = _score_education_code_only(
                        item_name, importance, structured_profile,
                    )
                elif dim_type == "certification":
                    item_eval = _score_certification_code_only(
                        item_name, importance, structured_profile,
                    )
                elif dim_type == "location":
                    item_eval = _score_location_code_only(
                        item_name, importance, profile,
                    )
                else:
                    # Fallback: treat as code-only with zero score.
                    item_eval = UnifiedItemEvaluation(
                        category=cat_name,
                        item_name=item_name,
                        description=item.get("description", ""),
                        importance=importance,
                        expected_years=expected_years,
                        matched=False,
                        years_detected=0,
                        raw_score=0.0,
                        score=0.0,
                        scoring_mode="code_only",
                    )
            else:
                # ---- Rubric-bound LLM mode ----
                # Retrieve section-routed evidence.
                evidence = retrieve_evidence_for_requirement(
                    item_name, cat_name, candidate_chunks,
                )

                # Score with the rubric-bound LLM.
                trace = score_requirement_with_rubric(
                    requirement_name=item_name,
                    dimension_type=dim_type,
                    weight=importance,
                    evidence=evidence,
                    target_years=expected_years if expected_years > 0 else None,
                    llm_caller=llm_caller,
                )

                # Convert trace to ItemEvaluation-compatible format.
                raw_score = round(trace.weighted_score, 2)
                matched = trace.normalized_score > 0

                # Build snippet from cited evidence.
                snippet = ""
                section = ", ".join(trace.sections_read)
                if trace.sub_scores:
                    cited = [s.cited_text for s in trace.sub_scores if s.cited_text]
                    if cited:
                        snippet = cited[0][:200]

                # Build reason from trace.
                reason_parts = []
                for ss in trace.sub_scores:
                    reason_parts.append(f"{ss.key}: {ss.sub_score:.2f}")
                reason = f"[{dim_type}] " + " | ".join(reason_parts)
                reason += f" → normalized: {trace.normalized_score:.2f}"

                item_eval = UnifiedItemEvaluation(
                    category=cat_name,
                    item_name=item_name,
                    description=item.get("description", ""),
                    importance=importance,
                    expected_years=expected_years,
                    matched=matched,
                    years_detected=trace.sub_scores[0].extracted_years
                        if trace.sub_scores and trace.sub_scores[0].extracted_years
                        else 0.0,
                    raw_score=raw_score,
                    score=raw_score,
                    section=section,
                    snippet=snippet,
                    reason=reason,
                    scoring_mode="rubric_llm",
                    scoring_trace=trace.to_dict(),
                )

            cat_eval.items.append(item_eval)
            total_raw += item_eval.raw_score
            total_max += importance

        categories.append(cat_eval)

    total = round(total_raw * scale, 2) if total_max else 0.0

    return UnifiedCandidateEvaluation(
        candidate_id=candidate_id,
        role=role,
        total_raw=total_raw,
        total_max=total_max,
        total=total,
        categories=categories,
        has_flagged_institute=structured_profile.has_flagged_institute,
        flagged_institutes=structured_profile.flagged_institutes,
    )
