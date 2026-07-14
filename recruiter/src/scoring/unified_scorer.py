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
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.rag.document_aware_chunker import ChunkRecord
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
from src.scoring.rubrics import RubricTemplate, SubQuestion


def is_code_only(dim_type: str) -> bool:
    """Check whether a dimension type is scored code-only (no LLM)."""
    return dim_type in ("education", "certification", "location")


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

def _token_boundary_match(needle: str, haystack: str) -> bool:
    """True when ``needle`` phrase or any of its tokens match ``haystack``.

    Case-insensitive. Respects word boundaries (``\\b``) so short tokens like
    "BA", "BS", "BE" do NOT match longer tokens that contain them as substrings
    (e.g. "BA" vs "MBA", "BS" vs "BSE").

    BUG-3 FIX: Now also performs alias-aware degree tier matching so that
    a requirement like "Bachelor's Degree" correctly matches a resume that
    says "B.Tech", "B.E.", or "BS". The canonical tier of both needle and
    haystack are compared; when they share the same tier (bachelor/master/phd)
    the match is accepted even if no raw token overlaps.

    Rules:
        1. Whole-phrase regex match (``\\b...\\b``) — highest signal.
        2. Token-level regex match — any whitespace-separated token of
           ``needle`` that is longer than 2 chars matches ``haystack``
           (stop-words <= 2 chars are skipped unless the needle is only
           stop-words, in which case all tokens are tried as fallback).
        3. Alias-tier match — both sides are mapped to a canonical degree
           tier (bachelor / master / phd) and the tiers are compared.

    Args:
        needle: The requirement string (e.g. "BTech", "AWS Certified",
            "Bachelor's Degree (CS/Stats)").
        haystack: The candidate's degree/certification text.

    Returns:
        True if any rule above fires. False otherwise (including when
        either argument is empty).
    """
    if not needle or not haystack:
        return False
    n = needle.lower()
    h = haystack.lower()

    # Rule 1 — whole-phrase word-boundary match.
    try:
        if re.search(r"\b" + re.escape(n) + r"\b", h):
            return True
    except re.error:
        pass

    # Rule 2 — token-level word-boundary match.
    tokens = [t for t in re.split(r"\s+", n) if len(t) > 2]
    if not tokens:
        tokens = [t for t in re.split(r"\s+", n) if t]
    if not tokens:
        return False
    for tok in tokens:
        try:
            if re.search(r"\b" + re.escape(tok) + r"\b", h):
                return True
        except re.error:
            if tok in h:
                return True

    # Rule 3 — alias-tier match (BUG-3 FIX).
    # Map both sides to their canonical degree tier and compare.
    #
    # GUARD: Do NOT apply alias-tier matching when the needle is a short degree
    # abbreviation (<=5 chars, e.g. "BA", "BS", "BE", "MBA", "MSc", "BTech"
    # that fits in 5 chars). These MUST match via word-boundary regex only.
    # Without this guard, "BA" (bachelor tier) matches "MBA" (also bachelor tier),
    # causing a false positive. Short abbreviations are specific enough that
    # only exact token matches are meaningful.
    if len(n.replace(" ", "")) > 5:
        from src.resume_parsing.structured_profile import degree_canonical_tier
        needle_tier = degree_canonical_tier(needle)
        haystack_tier = degree_canonical_tier(haystack)
        if needle_tier and haystack_tier:
            # "Advanced Degree" should match any tier >= master.
            _senior_tiers = {"master", "phd"}
            if needle_tier == haystack_tier:
                return True
            # Requirement says "advanced degree" (master or phd tier) and
            # candidate holds a phd — phd satisfies master requirement.
            if needle_tier == "master" and haystack_tier == "phd":
                return True

    return False


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
        # Word-boundary match — does the requirement match the degree as a
        # whole token (so "BA" no longer matches "MBA", "BS" no longer
        # matches "BSE")? Both directions are checked because requirement
        # phrases like "Bachelor's Degree (CS/Stats)" may be longer or
        # shorter than the degree string "BTech"/"BS".
        if _token_boundary_match(item_name, degree_entry.degree) or \
           _token_boundary_match(degree_entry.degree, item_name):
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
        # Word-boundary match — see _score_education_code_only above. The
        # legacy token-split clause is subsumed by _token_boundary_match
        # (it splits the needle on whitespace and checks each token with
        # `\b...\b`), so "PMP" no longer matches "PMPI" but "AWS Certified"
        # still matches "AWS Solutions Architect Associate" (via "aws").
        if _token_boundary_match(item_name, cert_entry.name):
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


# ===========================================================================
# Track 2 (2026-07-06, DEC-028): composed Mode1 × Mode2 scoring.
#
# The canonical WORKING_LOGIC.md formula (lines 1254-1266):
#
#     Sub-Score_REQ  = SQ1 × SQ2 × ... × SQN    (aN anchored floats ∈ [0, 1])
#     Contribution    = weight_percentage × Sub-Score
#     Total           = Σ Contribution
#
# Each REQ is decomposed by the SubQuery file into 2-6 sub-queries. The
# owner's framing collapses these into two groups:
#
#     Code_only_part  = Π SQ_scores answered by code (binary presence,
#                        years-proportional, tier lookup). ∈ [0, 1].
#     Rubric_LLM_part = Π SQ_scores answered by the rubric-bound LLM
#                        (skill depth, project complexity, etc.). ∈ [0, 1].
#
#     Sub-Score = Code_only_part × Rubric_LLM_part
#     Contribution = weight_percentage × Sub-Score
#     Total = Σ Contribution         (lands in [0, 100] because the
#                                      recruiter weights sum to 100)
#
# There is no ``scale_factor``. There is no ``DEFAULT_EXPECTED_YEARS``.
# Missing ``expected_years`` on a years-type REQ blocks the REQ (score 0
# + flag). Zero retrieved evidence on a rubric REQ blocks the rubric
# part (score 0 + flag at ``reports/audit/no_evidence_flags.jsonl``).
#
# The legacy :func:`evaluate_candidate_unified` is kept above as a
# backwards-compat shim. New code should call
# :func:`evaluate_candidate_composed` below.
# ===========================================================================


import numpy as np  # noqa: F401 — imported below for type hints; guarded

from src.rag.per_req_retrieval import (
    retrieve_evidence_for_req,
    embed_sub_queries,
)
from src.rag.retriever import (
    DEFAULT_THRESHOLD,
    DEFAULT_TOP_K,
    ThresholdRetriever,  # retained for backward compat — not used in new path
    VectorIndex,
    ScoredChunk,
)
from src.services.subquery_parser import get_all_role_subqueries
from src.scoring.graded_scorer import (
    CodeOnlyCandidateEvaluation,
    CodeOnlyItemResult,
    evaluate_candidate_code_only_v2,
    extract_expected_years,
    _aliases_for,
    _search_profile,
    _is_years_requirement,
)
from src.audit.no_evidence_flags import write_flag as write_no_evidence_flag


# ---------------------------------------------------------------------------
# Per-SQ classification.
# ---------------------------------------------------------------------------


def _is_years_subquery(sq: Dict[str, Any]) -> bool:
    """Heuristic: does this sub-query ask for a years-proportional score?

    A sub-query is years-proportional when it satisfies BOTH conditions:
      1. Its text or scale contains ``"year"`` or ``"relative"`` (indicating
         a years-based question).
      2. Its ``assessment_method`` contains ``"formula"`` (indicating it uses
         a mathematical ratio formula like ``min(years / expected, 1.0)``).

    This two-signal requirement prevents false positives on rubric-bound Float
    SQs whose question text incidentally mentions years as context
    (e.g. "How strong is their expertise (years and complexity level)?").
    Such SQs have ``"Rubric:"`` in their ``assessment_method``, not
    ``"Formula:"``, so they correctly fall through to the rubric-LLM path.

    A sub-query classified as years-proportional is scored code-only via
    :func:`_score_years_sq`; a sub-query that fails this check (but is not
    binary) is scored by the rubric-bound LLM in :func:`_score_rubric_sq`.
    """
    txt = (sq.get("text") or "").lower()
    scale = (sq.get("scale") or "").lower()
    has_years_signal = "year" in txt or "relative" in txt or "year" in scale

    if not has_years_signal:
        return False

    # Strong text-only signal: "relative to expected N years" or "how many years … expected"
    # are canonical SQ004-style formulas that don't need an assessment_method tag.
    has_strong_text_signal = (
        ("relative to expected" in txt)
        or ("how many years" in txt and "expected" in txt)
        or ("years of" in txt and "relative to" in txt)
    )
    if has_strong_text_signal:
        return True

    # Fallback: only classify as years-proportional when the assessment
    # method explicitly uses a formula (not a rubric anchor table).
    assessment = (sq.get("assessment_method") or "").lower()
    has_formula = "formula" in assessment or "min(" in assessment
    return has_formula


def _is_binary_subquery(sq: Dict[str, Any]) -> bool:
    """Heuristic: is this sub-query a binary presence gate?

    The SubQuery parser exposes ``type`` (``"Binary"`` / ``"Float"`` /
    ``"Linear"``). Binary SQs are code-only presence gates.
    """
    sq_type = (sq.get("type") or "").lower()
    return sq_type in ("binary", "boolean", "bool")


def _is_rubric_subquery(sq: Dict[str, Any]) -> bool:
    """Heuristic: does this sub-query require the rubric-bound LLM?

    A sub-query is rubric-bound if it is NOT code-only. Code-only SQs
    are binary presence gates + years-proportional float SQs.
    """
    return not _is_binary_subquery(sq) and not _is_years_subquery(sq)


# ---------------------------------------------------------------------------
# Per-SQ scoring (code-only branches).
# ---------------------------------------------------------------------------


def _score_presence_sq(
    sq: Dict[str, Any],
    requirement_name: str,
    profile: Dict[str, Any],
) -> float:
    """Score a binary presence sub-query against the candidate profile.

    Uses the legacy :func:`graded_scorer._search_profile` helper so we
    inherit the existing synonym dictionary + regex years detection.

    Args:
        sq: The sub-query dict (with ``text`` and
            ``assessment_method``).
        requirement_name: The REQ name from the weight config (used as
            the search alias when the SQ text is more specific, e.g.
            "pandas, NumPy, scikit-learn" — we want to find ANY of
            these tokens, so we also scan the SQ text for
            comma-separated skill tokens).
        profile: The parsed candidate profile dict.

    Returns:
        ``1.0`` when a presence match is found, else ``0.0``.
    """
    # First try the REQ name as-is (inherits synonym dict).
    patterns = _aliases_for(requirement_name)
    matched, _, _, _ = _search_profile(profile, patterns, allow_summary_years=False)
    if matched:
        return 1.0

    # Fall back to comma-separated tokens inside the SQ text — true for
    # SQs like "Has the candidate used data science libraries (pandas,
    # NumPy, scikit-learn, TensorFlow, PyTorch)?" where none of the
    # individual library names are in the synonym dictionary.
    sq_text = sq.get("text") or ""
    assessment = sq.get("assessment_method") or ""
    blob = f"{sq_text} {assessment}"
    # Extract candidate tokens (Noun-like, ≥3 chars, alphanumeric).
    import re
    tokens = re.findall(r"\b[a-zA-Z][a-zA-Z0-9.+#-]{2,}\b", blob)
    # Remove stop-words + the SQ scaffolding verbs.
    stop = {
        "the", "and", "for", "with", "has", "have", "candidate", "evidence",
        "look", "look-for", "yes", "no", "binary", "float", "linear",
        "year", "years", "relative", "expected", "minimum", "stated",
        "assessment", "method", "skill", "skills",
    }
    for tok in tokens:
        if tok.lower() in stop:
            continue
        # Don't re-try the requirement_name itself (already tried above).
        if tok.lower() == requirement_name.lower():
            continue
        patterns = _aliases_for(tok)
        matched, _, _, _ = _search_profile(
            profile, patterns, allow_summary_years=False,
        )
        if matched:
            return 1.0
    return 0.0


def _score_years_sq(
    sq: Dict[str, Any],
    requirement_name: str,
    profile: Dict[str, Any],
) -> Tuple[float, float, Optional[float]]:
    """Score a years-proportional sub-query.

    Returns ``(score, years_detected, expected_years)``.

    * ``expected_years`` is extracted from the SQ text via
      :func:`graded_scorer.extract_expected_years`. When the regex
      finds nothing the caller treats this REQ as **blocked** (returns
      score 0 with a flag).
    * ``years_detected`` is the highest years value found near an
      alias match in the candidate's profile (legacy
      :func:`graded_scorer._detect_years_in_text`).
    * ``score = min(years_detected / expected_years, 1.0)`` when both
      numbers are positive. ``0.0`` when no years can be detected in
      the profile.
    """
    expected = extract_expected_years(sq.get("text") or "")
    if expected is None or expected <= 0:
        # Caller handles the block (return 0 score; expected=None to signal).
        return 0.0, 0.0, None
    patterns = _aliases_for(requirement_name)
    _, _, _, years_detected = _search_profile(
        profile, patterns, allow_summary_years=True,
    )
    if years_detected <= 0:
        return 0.0, 0.0, expected
    score = round(min(years_detected / expected, 1.0), 4)
    return score, years_detected, expected


# ---------------------------------------------------------------------------
# Per-REQ result for the composed scorer.
# ---------------------------------------------------------------------------


@dataclass
class ComposedREQResult:
    """Per-REQ result for the composed Mode1 × Mode2 scorer.

    Attributes:
        requirement_id: From the weight config (e.g. ``"REQ-001"``).
        requirement_name: From the weight config.
        category: From the weight config.
        weight_percentage: 0-100.
        sub_queries: List of sub-query dicts from the SubQuery file.
        code_only_sq_scores: ``{sq_key: score}`` for code-only SQs.
        rubric_sq_scores:    ``{sq_key: score}`` for rubric-LLM SQs (0
            when LLM unavailable or zero retrieved evidence).
        code_only_part: ``Π code_only_sq_scores`` (1.0 when no code-only
            SQs exist on this REQ).
        rubric_llm_part: ``Π rubric_sq_scores`` (1.0 when no rubric SQs
            exist; 0.0 when no LLM, no evidence, or any rubric SQ
            scored 0).
        sub_score: ``code_only_part × rubric_llm_part``.
        contribution: ``weight_percentage × sub_score``.
        blocked: ``True`` when the REQ was blocked (missing
            expected_years on a years-type SQ, OR zero retrieved
            evidence when an LLM is available).
        blocked_reason: Human-readable explanation when ``blocked``.
        retrieved_chunks: ``List[ScoredChunk]`` retrieved by
            ``per_req_retrieval`` for this REQ (empty when no rubric SQs
            exist on this REQ OR zero retrieval).
        rubric_trace: ``CachedScoringTrace`` when the rubric LLM was
            called, else ``None``.
        rubric_skipped: ``True`` when the rubric LLM path was bypassed
            because the caller passed ``llm_caller=None`` (``--no-llm``
            smoke tests) or no retriever was configured. The
            ``rubric_llm_part`` is forced to 0 in this case. Distinct
            from a "zero-evidence" condition because NO retrieval was
            even attempted.
    """

    requirement_id: str
    requirement_name: str
    category: str
    weight_percentage: float
    sub_queries: List[Dict[str, Any]]
    code_only_sq_scores: Dict[str, float] = field(default_factory=dict)
    rubric_sq_scores: Dict[str, float] = field(default_factory=dict)
    code_only_part: float = 1.0
    rubric_llm_part: float = 1.0
    sub_score: float = 0.0
    contribution: float = 0.0
    blocked: bool = False
    blocked_reason: str = ""
    retrieved_chunks: List[Any] = field(default_factory=list)
    rubric_trace: Optional[Any] = None
    # True when the rubric LLM path was intentionally skipped because
    # either the caller passed ``llm_caller=None`` (--no-llm smoke
    # tests) or no retriever was configured. The ``rubric_llm_part``
    # is forced to 0 in this case, but this BRANCH is not a
    # "zero-evidence" condition — no retrieval was even attempted
    # (see ``zero_evidence_reqs`` which excludes this branch).
    rubric_skipped: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "requirement_name": self.requirement_name,
            "category": self.category,
            "weight_percentage": self.weight_percentage,
            "code_only_sq_scores": dict(self.code_only_sq_scores),
            "rubric_sq_scores": dict(self.rubric_sq_scores),
            "code_only_part": round(self.code_only_part, 4),
            "rubric_llm_part": round(self.rubric_llm_part, 4),
            "sub_score": round(self.sub_score, 4),
            "contribution": round(self.contribution, 4),
            "blocked": self.blocked,
            "blocked_reason": self.blocked_reason,
            "rubric_skipped": self.rubric_skipped,
            "retrieved_chunk_count": len(self.retrieved_chunks),
            "rubric_trace": (
                self.rubric_trace.to_dict() if self.rubric_trace else None
            ),
        }


@dataclass
class ComposedCandidateEvaluation:
    """Result of :func:`evaluate_candidate_composed` for one candidate.

    ``total`` is in [0, 100] by construction (the recruiter weights sum
    to exactly 100 per spec; each ``contribution = weight% ×
    sub_score`` with ``sub_score ∈ [0, 1]``).
    """

    candidate_id: str
    role: str
    total: float
    reqs: List[ComposedREQResult] = field(default_factory=list)

    @property
    def blocked_reqs(self) -> List[ComposedREQResult]:
        return [r for r in self.reqs if r.blocked]

    @property
    def zero_evidence_reqs(self) -> List["ComposedREQResult"]:
        """REQs where the rubric LLM was called but got zero chunks."""
        return [r for r in self.reqs
                if r.rubric_sq_scores
                and r.rubric_llm_part == 0.0
                and not r.blocked
                and not r.rubric_skipped]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "role": self.role,
            "total": round(self.total, 4),
            "blocked_count": len(self.blocked_reqs),
            "zero_evidence_count": len(self.zero_evidence_reqs),
            "reqs": [r.to_dict() for r in self.reqs],
        }

def classify_subquery_type(sq: Dict[str, Any]) -> str:
    """Classify the sub-query type based on text and key.

    BUG-7 FIX: The original patterns ("tier of the institute", "tier of the
    certificate") were too narrow and never matched real SubQuery.md text such
    as "institute tier (Tier 1, Tier 2, Tier 3)" or "certification prestige
    level".  Replaced with broader keyword-presence checks that fire whenever
    both 'tier' (or 'prestige') AND an institution/cert term are present in the
    SQ text or key.

    Args:
        sq: Sub-query dict.

    Returns:
        One of "binary", "cgpa", "institution_rank", "certificate_rank", "four_band".
    """
    text = (sq.get("text") or "").lower()
    key = (sq.get("key") or "").lower()
    sq_type = (sq.get("type") or "").lower()

    if sq_type in ("binary", "boolean", "bool"):
        return "binary"

    if "cgpa" in text or "percentage" in text or "marks" in text or "grade" in text:
        return "cgpa"

    # Institution-rank: triggered when any tier/prestige keyword appears
    # alongside any institution keyword (in either the text or the SQ key).
    _TIER_WORDS = ("tier", "prestige", "ranking", "ranked")
    _INST_WORDS = ("institute", "institution", "university", "college", "school")
    _CERT_WORDS = ("certif", "provider", "certification", "credential")

    has_tier_word = any(w in text or w in key for w in _TIER_WORDS)
    has_inst_word = any(w in text or w in key for w in _INST_WORDS)
    has_cert_word = any(w in text or w in key for w in _CERT_WORDS)

    # Explicit key shortcuts (legacy compat)
    if "institute_tier" in key or "institution_rank" in key:
        return "institution_rank"
    if "provider_tier" in key or "certificate_rank" in key or "cert_tier" in key:
        return "certificate_rank"

    # When BOTH institution and cert keywords are present (e.g. SQ042:
    # "institute tier or certification prestige level"), prefer cert_rank
    # because combined phrasing always signals "cert quality" context.
    if has_tier_word and has_cert_word and has_inst_word:
        return "certificate_rank"

    if has_tier_word and has_inst_word:
        return "institution_rank"

    if has_tier_word and has_cert_word:
        return "certificate_rank"

    return "four_band"



def extract_cgpa_from_profile(profile: Dict[str, Any]) -> Optional[float]:
    """Scan the education entries or the raw text of the resume for CGPA or percentage marks.

    BUG-4 FIX: The function previously tried ``profile.get("education")`` and
    ``profile.get("raw_text")`` but both fields live one level deeper in the
    production candidate JSON:
      - education is at ``profile["candidate_profile"]["education"]``
      - raw_text is at ``profile["raw"]["raw_text"]``
    Both layouts (production and legacy parser) are now handled.

    Args:
        profile: Root candidate JSON dict or legacy parser profile dict.

    Returns:
        Extracted CGPA / percentage float, or ``None`` when not found.
    """
    import re
    text = ""

    # Unpack nested sub-dicts (production layout).
    cand_profile = profile.get("candidate_profile") or {}
    raw_block = profile.get("raw") or {}

    # Use candidate_profile if it exists (production), otherwise root (legacy).
    profile_data = cand_profile if isinstance(cand_profile, dict) and cand_profile else profile

    # Collect text from education entries.
    education_raw = profile_data.get("education") or {}
    if isinstance(education_raw, list):
        for entry in education_raw:
            if isinstance(entry, dict):
                # Try all text-bearing fields in the normalised entry.
                for key in ("description", "specialization", "degree", "institution_raw"):
                    text += " " + (entry.get(key) or "")
    else:
        for entry in (education_raw.get("entries") or []):
            if isinstance(entry, dict):
                text += " " + (entry.get("description") or "")

    # Append raw resume text (production: raw.raw_text; legacy: raw_text at root).
    if isinstance(raw_block, dict):
        text += " " + (raw_block.get("raw_text") or "")
    text += " " + profile.get("raw_text", "")

    # Try to find CGPA or GPA out of 10 or 4
    cgpa_matches = re.findall(r'\b(?:cgpa|gpa|marks|percentage)?\s*(?::|of)?\s*([0-9]+(?:\.[0-9]+)?)\s*(?:/\s*(10|4))?\b', text, re.IGNORECASE)
    pct_matches = re.findall(r'\b([0-9]+(?:\.[0-9]+)?)\s*(?:%|\s*percent)\b', text, re.IGNORECASE)

    for val_str, scale in cgpa_matches:
        try:
            val = float(val_str)
            if scale == "10":
                return val
            if scale == "4":
                return val
            if 0.0 < val <= 10.0:
                return val
        except ValueError:
            continue

    for val_str in pct_matches:
        try:
            val = float(val_str)
            if 0.0 < val <= 100.0:
                return val
        except ValueError:
            continue

    return None


def _evaluate_code_only_sq(
    sq: Dict[str, Any],
    requirement_name: str,
    profile: Dict[str, Any],
    structured_profile: StructuredCandidateProfile,
) -> float:
    """Evaluate a code-only sub-query in Python using structured_profile and tier lookup databases."""
    from src.scoring.rubrics import (
        score_binary,
        score_cgpa,
        score_institution_rank,
        score_certificate_rank,
    )

    sq_type = classify_subquery_type(sq)

    if sq_type == "binary":
        # Check matching degree
        degree_matched = False
        for degree_entry in structured_profile.degrees:
            if _token_boundary_match(requirement_name, degree_entry.degree) or \
               _token_boundary_match(degree_entry.degree, requirement_name):
                degree_matched = True
                break
        if not degree_matched and structured_profile.degrees:
            if any(kw in requirement_name.lower() for kw in ("degree", "graduation", "bachelor", "master", "education")):
                degree_matched = True

        # Check matching certification
        cert_matched = False
        for cert_entry in structured_profile.certifications:
            if _token_boundary_match(requirement_name, cert_entry.name):
                cert_matched = True
                break

        # Check matching location
        location_matched = False
        raw_text = profile.get("raw_text", "")
        location_term = requirement_name.lower()
        for prefix in ("location:", "location", "city:", "city"):
            if location_term.startswith(prefix):
                location_term = location_term[len(prefix):].strip()
                break
        if location_term and location_term in raw_text.lower():
            location_matched = True

        condition_met = degree_matched or cert_matched or location_matched
        return score_binary(condition_met)

    elif sq_type == "cgpa":
        extracted_cgpa = extract_cgpa_from_profile(profile)
        # Default target CGPA
        target = 7.0
        # Check if the subquery specifies a custom target
        sq_text = sq.get("text") or ""
        import re
        m = re.search(r"(\d+(?:\.\d+)?)", sq_text)
        if m:
            target = float(m.group(1))
        return score_cgpa(extracted_cgpa, target)

    elif sq_type == "institution_rank":
        matched_institution = ""
        for degree_entry in structured_profile.degrees:
            matched_institution = degree_entry.institution
            if matched_institution:
                break
        return score_institution_rank(matched_institution)

    elif sq_type == "certificate_rank":
        matched_provider = ""
        for cert_entry in structured_profile.certifications:
            matched_provider = cert_entry.provider or cert_entry.name
            if matched_provider:
                break
        return score_certificate_rank(matched_provider)

    return 0.01


# ---------------------------------------------------------------------------
# Main entry point: composed Mode1 × Mode2 scoring per REQ.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Per-REQ evaluation helper.
#
# Extracted from evaluate_candidate_composed so it can be dispatched as a
# standalone callable to a ThreadPoolExecutor. Each REQ is fully independent
# of all other REQs — the only shared state is the read-only retriever,
# llm_caller (thread-safe _KeyPool), and sq_embedder (stateless cache lookup).
# ---------------------------------------------------------------------------


def _evaluate_single_req(
    req: Dict[str, Any],
    sq_by_id: Dict[str, Dict[str, Any]],
    candidate_id: str,
    role: str,
    profile: Dict[str, Any],
    structured_profile: Any,
    retriever: Optional["VectorIndex"],
    llm_caller: Optional[Callable[[str], str]],
    top_k: int,
    threshold: float,
    max_chunks_per_query: Optional[int],
    sq_embedder: Optional[Callable[[List[Tuple[str, str]]], "np.ndarray"]],
    audit_flags_path: Optional[str],
    chunker_id: str,
) -> "ComposedREQResult":
    """Evaluate a single REQ for one candidate and return a ComposedREQResult.

    This is the body of the old ``for req in requirements_weights:`` loop,
    extracted verbatim so it can run inside a thread pool. All arguments are
    either immutable scalars, read-only shared objects, or per-call copies.

    Args:
        req: The requirement weight config dict for this REQ.
        sq_by_id: Pre-built map from req_id to its SubQuery data dict.
        candidate_id: Candidate identifier string (for logging / audit).
        role: Role name (for audit flag writing).
        profile: Root candidate JSON profile dict.
        structured_profile: Pre-extracted StructuredCandidateProfile.
        retriever: Shared read-only ThresholdRetriever (thread-safe).
        llm_caller: Shared LLM caller with thread-safe key pool.
        threshold: Cosine similarity threshold for retrieval.
        max_chunks_per_query: Hard cap on retrieved chunks per SQ.
        sq_embedder: Cached sub-query embedder (thread-safe read path).
        audit_flags_path: Path for no-evidence audit flag file.
        chunker_id: Chunker identifier string for audit records.

    Returns:
        A fully populated ComposedREQResult for this REQ.
    """
    req_id = req.get("requirement_id") or req.get("req_id") or ""
    name = req.get("requirement_name") or req.get("name") or ""
    cat = req.get("category", "")
    weight_pct = float(req.get("weight_percentage") or 0.0)

    sq_data = sq_by_id.get(req_id)
    sub_queries = sq_data.get("sub_queries", []) if sq_data else []

    result = ComposedREQResult(
        requirement_id=req_id,
        requirement_name=name,
        category=cat,
        weight_percentage=weight_pct,
        sub_queries=sub_queries,
    )

    if not sub_queries:
        result.blocked = True
        result.blocked_reason = f"No sub-queries found/parsed for {req_id} ({name})."
        result.sub_score = 0.0
        result.contribution = 0.0
        return result

    # Check for years-proportional SQs that lack expected_years.
    #
    # When a SQ is classified as years-proportional (contains "how many years"
    # or similar) but no expected_years can be recovered from either the SQ
    # text or the weight config, we CANNOT apply the formula-based scorer.
    # Instead of blocking the entire REQ (which causes score=0 for every
    # candidate regardless of their actual Java/backend experience), we
    # downgrade those specific SQs to the rubric-LLM path.  The LLM still
    # receives the resume evidence and scores them as qualitative evidence
    # questions ("how many years?" becomes a rubric question scored 0–1).
    #
    # This fixes the false-positive block on JavaDeveloper REQ-001 (SQ004)
    # and REQ-013 (SQ034) where the SQ text triggers the years heuristic but
    # no expected_years is set in the weight config.
    years_downgraded: set = set()   # SQ keys to treat as rubric SQs
    for sq in sub_queries:
        if _is_years_subquery(sq):
            ey = extract_expected_years(sq.get("text") or "")
            if ey is None:
                explicit_ey = req.get("expected_years")
                if explicit_ey is not None:
                    try:
                        ey = float(explicit_ey)
                    except (TypeError, ValueError):
                        pass
            if ey is None:
                sq_key = sq.get("key") or ""
                years_downgraded.add(sq_key)
                logger.warning(
                    "[%s] %s: years-proportional SQ %r has no expected_years in "
                    "text or config — downgrading to rubric-LLM path instead of "
                    "blocking the REQ.",
                    req_id, name, sq_key,
                )

    req_dim_type = classify_requirement_type(cat, name)
    skip_code_only = req_dim_type not in ("education", "certification", "location")

    # ------------------------------------------------------------------
    # 1. Code-Only Path (Education, Certifications, Location)
    # ------------------------------------------------------------------
    if not skip_code_only:
        code_only_sq_scores = {}
        for sq in sub_queries:
            sq_key = sq.get("key") or ""
            sq_score = _evaluate_code_only_sq(
                sq=sq,
                requirement_name=name,
                profile=profile,
                structured_profile=structured_profile,
            )
            code_only_sq_scores[sq_key] = sq_score

        result.code_only_sq_scores = code_only_sq_scores
        result.rubric_sq_scores = {}

        sub_score_sum = sum(code_only_sq_scores.values())
        result.code_only_part = sub_score_sum
        result.rubric_llm_part = 1.0
        result.sub_score = sub_score_sum

        n_queries = len(code_only_sq_scores)
        result.contribution = round(weight_pct * (sub_score_sum / n_queries), 4) if n_queries > 0 else 0.0
        return result

    # ------------------------------------------------------------------
    # 2. Rubric LLM Path (Skills, Experience, Leadership, Domain, etc.)
    # ------------------------------------------------------------------
    rubric_sq_keys = [sq.get("key") for sq in sub_queries]
    rubric_sq_scores = {}
    result.code_only_sq_scores = {}

    if llm_caller is None or retriever is None:
        result.rubric_llm_part = 0.0
        result.rubric_skipped = True
        for k in rubric_sq_keys:
            rubric_sq_scores[k] = 0.0
        result.rubric_sq_scores = rubric_sq_scores
        result.sub_score = 0.0
        result.contribution = 0.0
        return result

    sq_pairs = [(sq.get("key") or "", sq.get("text") or "") for sq in sub_queries]
    try:
        sq_vecs = sq_embedder(sq_pairs) if sq_embedder is not None else embed_sub_queries(sq_pairs)
    except Exception as e:
        logger.warning(
            "composed: embed_sub_queries failed for %s %s: %s — rubric part floor",
            candidate_id, req_id, e,
        )
        result.rubric_llm_part = 0.01 * len(rubric_sq_keys)
        for k in rubric_sq_keys:
            rubric_sq_scores[k] = 0.01
        result.rubric_sq_scores = rubric_sq_scores
        result.sub_score = 0.01 * len(rubric_sq_keys)
        result.contribution = round(weight_pct * 0.01, 4)
        return result

    retrieved = retrieve_evidence_for_req(
        retriever=retriever,
        candidate_id=candidate_id,
        sub_queries=sq_pairs,
        sub_query_vectors=sq_vecs,
        top_k=top_k,
        max_chunks_per_req=max_chunks_per_query,
    )
    result.retrieved_chunks = retrieved

    if not retrieved:
        write_no_evidence_flag(
            candidate_id=candidate_id,
            role=role,
            req_id=req_id,
            requirement_name=name,
            sub_query_keys=rubric_sq_keys,
            theta=threshold,
            chunker=chunker_id,
            path=audit_flags_path or "reports/audit/no_evidence_flags.jsonl",
        )
        result.rubric_llm_part = 0.0
        result.blocked = True
        result.blocked_reason = (
            f"Zero retrieved evidence for {req_id} (top_k={top_k}). "
            f"Rubric part zeroed; flagged for human review."
        )
        for k in rubric_sq_keys:
            rubric_sq_scores[k] = 0.01
        result.rubric_sq_scores = rubric_sq_scores
        result.sub_score = 0.0
        result.contribution = 0.0
        return result

    section_evidence = _build_section_evidence(
        req_id=req_id,
        requirement_name=name,
        dim_type=req_dim_type,
        retrieved=retrieved,
    )
    target_years = None
    for sq in sub_queries:
        if "years" in (sq.get("text") or "").lower():
            ey = extract_expected_years(sq.get("text") or "")
            if ey is not None:
                target_years = ey
                break
    explicit_ey = req.get("expected_years")
    if explicit_ey is not None:
        try:
            target_years = float(explicit_ey)
        except (TypeError, ValueError):
            pass

    try:
        trace = score_requirement_with_rubric(
            requirement_name=name,
            dimension_type=req_dim_type,
            weight=weight_pct,
            evidence=section_evidence,
            target_years=target_years,
            llm_caller=llm_caller,
            employment_history=(
                structured_profile.employment_history
                if structured_profile is not None
                else None
            ),
            sub_queries=sub_queries,
        )
    except Exception as e:
        logger.warning(
            "composed: rubric LLM call failed for %s %s: %s — rubric part floor",
            candidate_id, req_id, e,
        )
        result.rubric_llm_part = 0.01 * len(rubric_sq_keys)
        for k in rubric_sq_keys:
            rubric_sq_scores[k] = 0.01
        result.rubric_sq_scores = rubric_sq_scores
        result.sub_score = 0.01 * len(rubric_sq_keys)
        result.contribution = round(weight_pct * 0.01, 4)
        return result

    result.rubric_trace = trace

    for ss in trace.sub_scores:
        rubric_sq_scores[ss.key] = ss.sub_score
    result.rubric_sq_scores = rubric_sq_scores

    sub_score_sum = sum(rubric_sq_scores.values())
    result.rubric_llm_part = sub_score_sum
    result.code_only_part = 1.0
    result.sub_score = sub_score_sum

    n_queries = len(rubric_sq_scores)
    result.contribution = round(weight_pct * (sub_score_sum / n_queries), 4) if n_queries > 0 else 0.0
    return result

def evaluate_candidate_composed(
    profile: Dict[str, Any],
    weights: Dict[str, Any],
    retriever: Optional[VectorIndex],
    structured_profile: Any = None,
    llm_caller: Optional[Callable[[str], str]] = None,
    role_subqueries: Optional[Dict[str, Any]] = None,
    role_name: Optional[str] = None,
    top_k: int = DEFAULT_TOP_K,
    threshold: float = DEFAULT_THRESHOLD,
    max_chunks_per_query: Optional[int] = None,
    audit_flags_path: Optional[str] = None,
    chunker_id: str = "DocumentAware",
    sq_embedder: Optional[Callable[[List[Tuple[str, str]]], "np.ndarray"]] = None,
    n_workers: int = 10,
) -> ComposedCandidateEvaluation:
    """Score a candidate with the new composed Mode1 / Mode2 scoring logic.

    Aggregates sub-queries additively: Sub-Score = SQ1 + SQ2 + ...
    Scales contribution: Weight * (Sub-Score / Number of Sub-Queries).

    Args:
        profile: Parsed candidate JSON profile (root dict).
        weights: Weight config dict (requirements_weights list).
        retriever: Shared ThresholdRetriever (read-only; thread-safe).
        structured_profile: Pre-extracted StructuredCandidateProfile.
        llm_caller: LLM caller for rubric scoring (thread-safe _KeyPool).
        role_subqueries: Pre-loaded SubQuery dict for this role.
        role_name: Override for role name (else resolved from weights).
        threshold: Cosine similarity threshold for retrieval.
        max_chunks_per_query: Hard cap on retrieved chunks per sub-query.
        audit_flags_path: Path for no-evidence audit JSONL flag file.
        chunker_id: Chunker ID string recorded in audit flags.
        sq_embedder: Cached sub-query embedder closure (thread-safe).
        n_workers: Number of REQs to evaluate in parallel via
            ``ThreadPoolExecutor``.  Each REQ is fully independent so
            thread-safety is guaranteed.  Default 5 — at 6 s / LLM call
            and 15 REQs this cuts wall-clock from ~90 s to ~20 s.
            Set to 1 to force sequential execution (debug / rate-limit).
    """
    candidate_id = (
        profile.get("candidate_id")
        or profile.get("id")
        or Path(profile.get("source_file", "")).stem
        or "unknown"
    )
    role = role_name or weights.get("role", "")

    # Resolve the SubQuery data
    if role_subqueries is None:
        if not role:
            raise ValueError(
                "evaluate_candidate_composed: role_subqueries is None and "
                "role_name could not be resolved from weights['role']."
            )
        role_subqueries = get_all_role_subqueries().get(role)
        if role_subqueries is None:
            raise ValueError(
                f"evaluate_candidate_composed: no SubQuery data for role "
                f"{role!r}. Check data/job_descriptions/{role}/{role}_SubQuery.md."
            )

    if "requirements" not in role_subqueries:
        if not role:
            raise ValueError(
                "evaluate_candidate_composed: role_subqueries has no "
                "'requirements' key and role_name could not be resolved "
                "from weights['role'] — cannot slice out a single role."
            )
        single = role_subqueries.get(role)
        if single is None:
            raise ValueError(
                f"evaluate_candidate_composed: role_subqueries is the "
                f"all-roles dict but role {role!r} is not present."
            )
        role_subqueries = single
    subquery_reqs = role_subqueries.get("requirements", [])
    sq_by_id: Dict[str, Dict[str, Any]] = {
        r.get("req_id"): r for r in subquery_reqs
    }


    req_list = weights.get("requirements_weights", [])

    # Shared kwargs forwarded unchanged to every _evaluate_single_req call.
    # All objects here are either immutable scalars, read-only shared data
    # structures, or internally thread-safe (retriever uses numpy read-only
    # ops; llm_caller uses _KeyPool with threading.Lock; sq_embedder is a
    # stateless cache lookup populated before scoring begins).
    _ctx: Dict[str, Any] = dict(
        sq_by_id=sq_by_id,
        candidate_id=candidate_id,
        role=role,
        profile=profile,
        structured_profile=structured_profile,
        retriever=retriever,
        llm_caller=llm_caller,
        top_k=top_k,
        threshold=threshold,
        max_chunks_per_query=max_chunks_per_query,
        sq_embedder=sq_embedder,
        audit_flags_path=audit_flags_path,
        chunker_id=chunker_id,
    )

    # ------------------------------------------------------------------
    # Parallel path — ThreadPoolExecutor dispatches N REQs concurrently.
    #
    # REQs are mutually independent: no REQ reads the score of another,
    # so thread-safety is structurally guaranteed.  as_completed() is
    # used so fast REQs (code-only, blocked) don't wait for slow LLM
    # calls.  Results are re-sorted to the original weight-config order
    # before aggregation so the output JSON is deterministic.
    # ------------------------------------------------------------------
    if n_workers > 1 and len(req_list) > 1:
        effective_workers = min(n_workers, len(req_list))
        logger.debug(
            "composed[%s/%s]: launching %d REQs across %d workers",
            role, candidate_id, len(req_list), effective_workers,
        )

        future_to_idx: Dict[Any, int] = {}
        reqs_results_map: Dict[int, ComposedREQResult] = {}

        with ThreadPoolExecutor(max_workers=effective_workers) as pool:
            for idx, req in enumerate(req_list):
                future = pool.submit(_evaluate_single_req, req, **_ctx)
                future_to_idx[future] = idx

            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    reqs_results_map[idx] = future.result()
                except Exception as exc:
                    # Hard fallback: zero one REQ rather than crash the
                    # entire candidate evaluation.
                    bad_req = req_list[idx]
                    req_id = bad_req.get("requirement_id") or bad_req.get("req_id") or ""
                    name = bad_req.get("requirement_name") or bad_req.get("name") or ""
                    logger.error(
                        "composed[%s/%s]: unhandled exception in REQ %s — "
                        "zeroing contribution. Error: %s",
                        role, candidate_id, req_id, exc,
                    )
                    fallback = ComposedREQResult(
                        requirement_id=req_id,
                        requirement_name=name,
                        category=bad_req.get("category", ""),
                        weight_percentage=float(bad_req.get("weight_percentage") or 0.0),
                        sub_queries=[],
                    )
                    fallback.blocked = True
                    fallback.blocked_reason = f"Unhandled thread exception: {exc}"
                    fallback.sub_score = 0.0
                    fallback.contribution = 0.0
                    reqs_results_map[idx] = fallback

        # Restore original weight-config order after as_completed().
        reqs_results: List[ComposedREQResult] = [
            reqs_results_map[i] for i in sorted(reqs_results_map)
        ]

    # ------------------------------------------------------------------
    # Sequential path — n_workers == 1 or a single-REQ role.
    # Identical semantics to the old loop; used for debugging or when
    # the API rate-limit is too tight for concurrent calls.
    # ------------------------------------------------------------------
    else:
        reqs_results = [_evaluate_single_req(req, **_ctx) for req in req_list]

    total = round(sum(r.contribution for r in reqs_results), 4)
    return ComposedCandidateEvaluation(
        candidate_id=candidate_id, role=role, total=total, reqs=reqs_results,
    )


def _build_section_evidence(
    req_id: str,
    requirement_name: str,
    dim_type: str,
    retrieved: List[Any],
) -> SectionEvidence:
    """Adapt the per_req_retrieval ScoredChunk list to rubric_scorer's
    SectionEvidence input.

    The legacy :class:`SectionEvidence` from
    :mod:`src.rag.section_routed` was designed for Section-Routed
    retrieval (with section labels). For the new per-REQ retrieval
    pipeline we synthesize one pseudo-section per chunk using the
    chunk's ``metadata["section"]`` tag and concatenate all chunk
    text into ``full_text``. The rubric LLM reads the full_text; it
    does not care about section labels.
    """
    sections: List[str] = []
    chunks: List[ChunkRecord] = []
    full_text_parts: List[str] = []
    for sc in retrieved:
        section = sc.metadata.get("section") or "document"
        sections.append(section)
        chunk = ChunkRecord(
            chunk_id=sc.chunk_id,
            candidate_id=sc.metadata.get("candidate_id", ""),
            role_bucket=sc.metadata.get("role_bucket", ""),
            source_file=sc.metadata.get("source_file", ""),
            section=section,
            chunk_index=sc.metadata.get("chunk_index", 0),
            text=sc.text,
            char_span=(0, len(sc.text)),
            section_type=section,
            parent_structure={},
            skills_asserted=[],
            experience_type="unknown",
        )
        chunks.append(chunk)
        full_text_parts.append(sc.text)
    return SectionEvidence(
        requirement_type=dim_type,
        requirement_name=requirement_name,
        sections=sorted(set(sections)),
        chunks=chunks,
        full_text="\n\n---\n\n".join(full_text_parts),
        chunk_count=len(retrieved),
    )
