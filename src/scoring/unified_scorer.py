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

# Common short abbreviations that must NOT be matched as substrings of longer
# tokens (e.g. "BA" must not match "MBA", "BS" must not match "BSE"). Word
# boundaries (`\b`) `re.search(r"\bba\b", "mba")` is False, so this is the
# correct primitive for education/cert matching.
def _token_boundary_match(needle: str, haystack: str) -> bool:
    """Match ``needle`` against ``haystack`` using whole-token boundaries.

    The match is case-insensitive and respects word boundaries (`\b`) so
    short tokens like "BA", "BS", "MA", "BE" do NOT match longer tokens
    that merely contain them as a substring (e.g. "BA" vs "MBA", "BS" vs
    "BSE", "BE" vs "between"). The legacy education matcher used a bare
    ``in`` check on the whole string; the legacy cert matcher did
    ``any(kw in cert for kw in needle.split())``. We preserve the same
    ANY-token semantic but upgrade the primitive from substring to
    word-boundary regex, so "PMP" still matches "PMP Certified" while no
    longer matching "PMPI".

    Matching rules (in order):
      1. Whole-phrase match ``\\b<needle>\\b`` — short-circuits to True
         when the requirement appears verbatim in the candidate string.
      2. ANY-token match — split ``needle`` on whitespace and return True
         if any token matches ``haystack`` with word boundaries. A token
         that survives stop-word filtering (very short connectives like
         "of" or "in") retains the boundary matching; otherwise it is
         ignored to avoid near-zero-signal matches.

    Args:
        needle: The requirement string (e.g. "BTech", "AWS Certified",
            "Bachelor's Degree (CS/Stats)").
        haystack: The candidate's degree/certification text.

    Returns:
        True if the whole phrase matches with word boundaries, or any
        token of ``needle`` matches with word boundaries. False otherwise
        (including when either argument is empty).
    """
    if not needle or not haystack:
        return False
    n = needle.lower()
    h = haystack.lower()
    # Whole-phrase match with word boundaries first (highest signal).
    try:
        if re.search(r"\b" + re.escape(n) + r"\b", h):
            return True
    except re.error:
        pass
    # Token-level match: ANY whitespace-separated token of the
    # requirement matches the candidate text with word boundaries.
    # Stop-words of 2 or fewer characters (e.g. "of", "in", "is") are
    # skipped because they carry near-zero signal and would otherwise
    # match many candidate strings spuriously.
    tokens = [t for t in re.split(r"\s+", n) if len(t) > 2]
    if not tokens:
        # Fall back to all tokens if the needle only had stop-words.
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
    ThresholdRetriever,
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

    The SubQuery file marks type as one of ``"Binary"``, ``"Float"``,
    ``"Linear"``. Years-proportional SQs are ``"Float"`` (or
    ``"Linear"``) AND have ``"years"`` or ``"relative"`` in the sub-query
    text. Pure binary presence SQs (``"Binary"``) are answered by
    :func:`_score_presence_sq` below; depth/judgment SQs (``"Float"``
    without years phrasing) are answered by the rubric-bound LLM.
    """
    txt = (sq.get("text") or "").lower()
    scale = (sq.get("scale") or "").lower()
    if "year" in txt or "relative" in txt or "year" in scale:
        return True
    return False


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


# ---------------------------------------------------------------------------
# Main entry point: composed Mode1 × Mode2 scoring per REQ.
# ---------------------------------------------------------------------------


def evaluate_candidate_composed(
    profile: Dict[str, Any],
    weights: Dict[str, Any],
    retriever: Optional[ThresholdRetriever],
    structured_profile: Any = None,
    llm_caller: Optional[Callable[[str], str]] = None,
    role_subqueries: Optional[Dict[str, Any]] = None,
    role_name: Optional[str] = None,
    threshold: float = DEFAULT_THRESHOLD,
    max_chunks_per_query: Optional[int] = None,
    audit_flags_path: Optional[str] = None,
    chunker_id: str = "Recursive",
    sq_embedder: Optional[Callable[[List[Tuple[str, str]]], "np.ndarray"]] = None,
) -> ComposedCandidateEvaluation:
    """Score a candidate with the canonical Mode1 × Mode2 composition.

    For each REQ in the weight config:

        1. Look up the REQ's sub-queries from the SubQuery file (parsed
           by :mod:`src.services.subquery_parser`).
        2. Classify each sub-query:
             * Binary type → code-only presence gate.
             * Float/Linear type with "years" in text → code-only
               years-proportional ``min(years / expected, 1.0)``.
             * Other Float/Linear type → rubric-bound LLM judge.
        3. Score code-only SQs against the parsed profile using the
           legacy :func:`graded_scorer._search_profile` helpers
           (synonym match, regex years detection).
        4. Score rubric SQs with a single LLM call per REQ after
           retrieving evidence via
           :func:`per_req_retrieval.retrieve_evidence_for_req`. The
           rubric LLM's ``normalized_score`` is used directly as the
           entire ``Rubric_LLM_part`` (one LLM call per REQ, not per
           SQ — rubric templates score multiple sub-questions in one
           call).
        5. Aggregate:

             Code_only_part  = Π code_only_sq_scores     (1.0 if none)
             Rubric_LLM_part = rubric_normalized_score   (1.0 if none)
             Sub-Score       = Code_only_part × Rubric_LLM_part
             Contribution    = weight_percentage × Sub-Score
             Total           = Σ Contribution            (lands in [0, 100])

    Blocking rules:
        * A years-type code-only SQ with no ``expected_years`` (from
          weight config or recoverable via regex on the SubQuery text)
          blocks the entire REQ: ``code_only_part = 0`` and
          ``contribution = 0``, with a flag.
        * A rubric REQ with zero retrieved evidence OR no LLM caller
          blocks the rubric part: ``rubric_llm_part = 0`` and
          ``contribution = 0``, with a flag written to
          ``audit_flags_path`` (default
          ``reports/audit/no_evidence_flags.jsonl``).
        * A REQ with no sub-queries at all (parser mismatch) is treated
          as fully blocked and flagged.

    Args:
        profile: The parsed candidate profile dict.
        weights: The recruiter weight config dict with a
            ``requirements_weights`` flat list.
        retriever: The :class:`ThresholdRetriever` for per-REQ
            evidence retrieval. May be ``None``, in which case all
            rubric SQs get score 0 (the rubric path is bypassed but
            the code-only path still runs).
        structured_profile: The deterministic structured profile
            (unused at present — kept for forward-compat with tier
            lookups that the LLM part might need). May be ``None``.
        llm_caller: Optional callable for the rubric-bound LLM judge.
            When ``None``, rubric SQs get score 0 (zero-out).
        role_subqueries: Pre-loaded SubQuery data for the candidate's
            role (as returned by
            :func:`subquery_parser.get_all_role_subqueries`). When
            ``None``, the parser is invoked lazily using
            ``role_name``.
        role_name: Role bucket to look up the SubQuery file when
            ``role_subqueries`` is ``None``. Falls back to
            ``weights["role"]``.
        threshold: Cosine threshold for ``retrieve_evidence_for_req``.
            Defaults to :data:`retriever.DEFAULT_THRESHOLD`.
        max_chunks_per_query: Optional cap on retrieved chunks per REQ.
            Defaults to the retriever's own ``max_chunks_per_query``.
        audit_flags_path: Path to the JSONL audit log for zero-evidence
            flags. When ``None`` the default
            ``reports/audit/no_evidence_flags.jsonl`` is used.
        chunker_id: Human-readable chunker identifier for the audit
            log (e.g. ``"Recursive(chunk_size=500, chunk_overlap=100)"``).
        sq_embedder: Optional callable that takes a list of
            ``(sq_key, sq_text)`` tuples and returns an
            ``(N, D)`` float32 numpy matrix of sub-query embeddings.
            When ``None``, the default
            :func:`per_req_retrieval.embed_sub_queries` is used (loads
            MiniLM-L6-v2 on first call). Tests pass a stub embedder
            that returns vectors aligned to a synthetic toy index so
            the rubric path can be exercised without loading the real
            model.

    Returns:
        :class:`ComposedCandidateEvaluation`.
    """
    candidate_id = (
        profile.get("candidate_id")
        or profile.get("id")
        or Path(profile.get("source_file", "")).stem
        or "unknown"
    )
    role = role_name or weights.get("role", "")

    # ------------------------------------------------------------------
    # Resolve the SubQuery data: each REQ's ``sub_queries`` list.
    # ------------------------------------------------------------------
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
    # ``role_subqueries`` may be passed in two equivalent shapes:
    #   (a) single-role: ``{requirements: [...], role_name: ...}``
    #       (as produced by ``get_all_role_subqueries().get(role)``).
    #   (b) all-roles: ``{DataScience: {requirements: ...}, ...}``
    #       (as produced by ``get_all_role_subqueries()`` directly — the
    #       shape the ``scripts/score_batch_composed.py`` CLI passes).
    # Detect the all-roles shape by the absence of a ``requirements``
    # key, then slice out the single-role dict post-hoc so that
    # downstream code uniformly sees shape (a).
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
                f"all-roles dict but role {role!r} is not present. "
                f"Check the role name spelling or SubQuery files."
            )
        role_subqueries = single
    subquery_reqs = role_subqueries.get("requirements", [])
    sq_by_id: Dict[str, Dict[str, Any]] = {
        r.get("req_id"): r for r in subquery_reqs
    }

    reqs_results: List[ComposedREQResult] = []

    for req in weights.get("requirements_weights", []):
        req_id = req.get("requirement_id") or req.get("req_id") or ""
        name = req.get("requirement_name") or req.get("name") or ""
        cat = req.get("category", "")
        weight_pct = float(req.get("weight_percentage") or 0.0)

        sq_data = sq_by_id.get(req_id)
        sub_queries = sq_data.get("sub_queries", []) if sq_data else []
        scoring_formula = sq_data.get("scoring_formula", "") if sq_data else ""

        result = ComposedREQResult(
            requirement_id=req_id,
            requirement_name=name,
            category=cat,
            weight_percentage=weight_pct,
            sub_queries=sub_queries,
        )

        # ==============================================================
        # 1. Code-only SQ scoring (binary presence + years-proportional).
        #
        # Code-only path is reserved for table-lookup REQs (institute
        # tier, cert tier, degree, location) where a regex/lookup is
        # the right tool. For skill + experience REQs the code-only
        # regex-based presence/years detectors are unreliable (the
        # monolithic alias regex misses resume prose; the years regex
        # can only match literal "N years" phrases, not date ranges),
        # so those REQs route SOLELY through the rubric LLM. Setting
        # code_only_part = 1.0 (identity) means sub_score becomes the
        # rubric LLM's verdict directly.
        # ==============================================================
        req_dim_type = classify_requirement_type(cat, name)
        code_only_sq_scores: Dict[str, float] = {}
        years_blocked = False
        years_blocked_reason = ""
        skip_code_only = req_dim_type in ("skill", "experience",
                                          "same_role", "leadership", "domain")

        # Check for expected_years block on any years-proportional SQ
        # (even if skip_code_only is True, because missing expected_years
        # is a hard contract violation that blocks the entire REQ).
        for sq in sub_queries:
            if _is_years_subquery(sq):
                ey = extract_expected_years(sq.get("text") or "")
                if ey is None:
                    years_blocked = True
                    years_blocked_reason = (
                        f"Years-proportional SQ {sq.get('key') or ''!r} for {req_id} "
                        f"has no recoverable expected_years from its "
                        f"text (SQ text: {(sq.get('text') or '')[:80]!r}). REQ blocked."
                    )
                    break

        if skip_code_only:
            # Skill/experience REQs: rubric LLM is the sole judge.
            # code_only_part stays 1.0 (identity), code_only_sq_scores
            # stays empty so no AND-gate is applied to these REQs.
            if years_blocked:
                result.code_only_part = 0.0
                result.blocked = True
                result.blocked_reason = years_blocked_reason
            else:
                result.code_only_part = 1.0
        else:
            for sq in sub_queries:
                sq_key = sq.get("key") or ""
                sq_txt = sq.get("text") or ""

                if _is_binary_subquery(sq):
                    code_only_sq_scores[sq_key] = _score_presence_sq(
                        sq, requirement_name=name, profile=profile,
                    )
                elif _is_years_subquery(sq):
                    score, years_detected, expected = _score_years_sq(
                        sq, requirement_name=name, profile=profile,
                    )
                    code_only_sq_scores[sq_key] = score
                    if expected is None:
                        years_blocked = True
                        years_blocked_reason = (
                            f"Years-proportional SQ {sq_key!r} for {req_id} "
                            f"has no recoverable expected_years from its "
                            f"text (SQ text: {sq_txt[:80]!r}). REQ blocked."
                        )
                # Else: it's a rubric SQ; skip here.
            # Compute the code-only part.
            if years_blocked:
                result.code_only_part = 0.0
                result.blocked = True
                result.blocked_reason = years_blocked_reason
            elif code_only_sq_scores:
                prod = 1.0
                for v in code_only_sq_scores.values():
                    prod *= float(v)
                result.code_only_part = round(prod, 4)
            else:
                # No code-only SQs on this REQ — multiplicative identity.
                result.code_only_part = 1.0
        result.code_only_sq_scores = code_only_sq_scores

        # ==============================================================
        # 2. Rubric LLM scoring (one call per REQ, after per-REQ retrieval).
        #
        # When code-only is skipped (skill/experience REQs), EVERY SQ
        # on the REQ is rubric-bound — both the binary presence gate
        # and the linear years question go to the LLM, and the LLM's
        # verdict on each becomes the rubric sub-score.
        # ==============================================================
        if skip_code_only:
            rubric_sq_keys = [sq.get("key") for sq in sub_queries]
        else:
            rubric_sq_keys = [
                sq.get("key") for sq in sub_queries
                if _is_rubric_subquery(sq)
            ]
        rubric_sq_scores: Dict[str, float] = {}

        if not rubric_sq_keys:
            # No rubric SQs on this REQ — multiplicative identity.
            result.rubric_llm_part = 1.0
            result.rubric_sq_scores = {}
        elif llm_caller is None or retriever is None:
            # Rubric SQs exist but no LLM / no retriever → zero out
            # the rubric part. NOT flagged (when no LLM caller is
            # supplied the user explicitly opted out of rubric scoring).
            result.rubric_llm_part = 0.0
            result.rubric_skipped = True
            for k in rubric_sq_keys:
                rubric_sq_scores[k] = 0.0
            result.rubric_sq_scores = rubric_sq_scores
        else:
            # ---- The real rubric path: retrieve evidence, call LLM. ----
            sq_pairs: List[Tuple[str, str]] = [
                (sq.get("key") or "", sq.get("text") or "") for sq in sub_queries
            ]
            try:
                sq_vecs = (
                    sq_embedder(sq_pairs)
                    if sq_embedder is not None
                    else embed_sub_queries(sq_pairs)
                )
            except Exception as e:
                logger.warning(
                    "composed: embed_sub_queries failed for %s %s: %s — "
                    "rubric part zeroed",
                    candidate_id, req_id, e,
                )
                result.rubric_llm_part = 0.0
                for k in rubric_sq_keys:
                    rubric_sq_scores[k] = 0.0
                result.rubric_sq_scores = rubric_sq_scores
                reqs_results.append(result)
                continue

            retrieved = retrieve_evidence_for_req(
                retriever=retriever,
                candidate_id=candidate_id,
                sub_queries=sq_pairs,
                sub_query_vectors=sq_vecs,
                threshold=threshold,
                max_chunks_per_query=max_chunks_per_query,
            )
            result.retrieved_chunks = retrieved

            if not retrieved:
                # Zero-evidence block: write a flag and zero out the
                # rubric part. The contribution will land at 0 because
                # Sub-Score = code_only_part × 0 = 0.
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
                    f"Zero retrieved evidence for {req_id} at θ={threshold:.3f}. "
                    f"Rubric part zeroed; flagged for human review."
                )
                for k in rubric_sq_keys:
                    rubric_sq_scores[k] = 0.0
            else:
                # Build a SectionEvidence-compatible wrapper from the
                # retrieved ScoredChunks so the existing rubric_scorer
                # can consume them unchanged.
                section_evidence = _build_section_evidence(
                    req_id=req_id,
                    requirement_name=name,
                    dim_type=classify_requirement_type(cat, name),
                    retrieved=retrieved,
                )
                # target_years recovered from any years-type SQ on
                # this REQ (if any) → pass to the rubric LLM.
                target_years: Optional[float] = None
                for sq in sub_queries:
                    if _is_years_subquery(sq):
                        ey = extract_expected_years(sq.get("text") or "")
                        if ey is not None:
                            target_years = ey
                            break
                # Extract expected_years from the weight config item.
                explicit_ey = req.get("expected_years")
                if explicit_ey is not None:
                    try:
                        target_years = float(explicit_ey)
                    except (TypeError, ValueError):
                        pass
                try:
                    trace = score_requirement_with_rubric(
                        requirement_name=name,
                        dimension_type=classify_requirement_type(cat, name),
                        weight=weight_pct,
                        evidence=section_evidence,
                        target_years=target_years,
                        llm_caller=llm_caller,
                        employment_history=(
                            structured_profile.employment_history
                            if structured_profile is not None
                            else None
                        ),
                    )
                except Exception as e:
                    logger.warning(
                        "composed: rubric LLM call failed for %s %s: %s — "
                        "rubric part zeroed",
                        candidate_id, req_id, e,
                    )
                    result.rubric_llm_part = 0.0
                    for k in rubric_sq_keys:
                        rubric_sq_scores[k] = 0.0
                    result.rubric_sq_scores = rubric_sq_scores
                    reqs_results.append(result)
                    continue

                result.rubric_trace = trace
                # The rubric LLM scores multiple sub-questions and
                # produces a normalized_score (the product across
                # rubric-template sub-questions). We use it directly as
                # the entire Rubric_LLM_part for this REQ. ALL rubric
                # SQs in the SubQuery file get the same score (the LLM
                # is called once per REQ, not per SubQuery-SQ).
                rubric_normalized = float(trace.normalized_score or 0.0)
                rubric_normalized = max(0.0, min(1.0, rubric_normalized))
                result.rubric_llm_part = round(rubric_normalized, 4)
                for k in rubric_sq_keys:
                    rubric_sq_scores[k] = result.rubric_llm_part
            result.rubric_sq_scores = rubric_sq_scores

        # ==============================================================
        # 3. Sub-Score + Contribution.
        # ==============================================================
        if result.blocked:
            # Either years_blocked or zero_evidence_blocked — the
            # contribution is forced to 0 for audit loudness.
            result.sub_score = 0.0
            result.contribution = 0.0
        else:
            result.sub_score = round(
                result.code_only_part * result.rubric_llm_part, 4,
            )
            result.contribution = round(weight_pct * result.sub_score, 4)

        reqs_results.append(result)

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
