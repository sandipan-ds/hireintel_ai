"""Rubric templates — fixed, recruiter-visible scoring rules per dimension type.

Per ``WORKING_LOGIC.md`` ("Scoring Rubrics"):

Every scoring dimension must resolve to an explicit, recruiter-visible rule
before it is used. The system must never let the LLM invent a rubric at
evaluation time.

Each rubric template defines:

* **Sub-questions** — the specific questions the LLM judge must answer for
  this requirement type. The LLM does not decide *what* to score — the rubric
  tells it exactly what to look for.

* **Anchored scales** — each sub-question resolves to a fixed numeric scale
  (0.0, 0.25, 0.5, 0.75, 1.0) with explicit definitions for each anchor.
  The LLM never uses free-form labels like "Advanced" or "Strong".

* **Formula** — how the sub-scores combine into a single normalized score
  (0.0–1.0). This formula is applied in code, never by the LLM.

The LLM's job: read the routed section content (from Section-Routed Evidence
Retrieval), extract what's relevant, then score each sub-question against
the anchored scale. The LLM never sees the weight and never computes the
final weighted contribution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.scoring.tier_lookup import lookup_institute_tier, lookup_certificate_tier


# ---------------------------------------------------------------------------
# Data classes for rubric structure.
# ---------------------------------------------------------------------------

@dataclass
class Anchor:
    """One anchor point on an anchored scale.

    Attributes:
        value: The numeric value (e.g., 0.0, 0.25, 0.5, 0.75, 1.0).
        description: Human-readable definition of when this anchor applies.
    """

    value: float
    description: str


@dataclass
class SubQuestion:
    """One sub-question within a rubric template.

    Attributes:
        key: Short identifier (e.g., "skill_presence", "years_experience").
        question: The question the LLM must answer.
        type: One of "binary" (0 or 1), "linear" (ratio computed in code),
            "anchored" (LLM picks from anchor points).
        anchors: For "anchored" type, the list of valid anchor points.
            For "binary" type, [Anchor(0, "No"), Anchor(1, "Yes")].
            For "linear" type, empty (code computes the ratio).
        target_field: For "linear" type, the name of the target/ideal field
            from the weight config (e.g., "expected_years").
        extract_first: If True, the LLM must first extract evidence before
            scoring (prevents holistic bias).
    """

    key: str
    question: str
    type: str  # "binary" | "linear" | "anchored"
    anchors: List[Anchor] = field(default_factory=list)
    target_field: Optional[str] = None
    extract_first: bool = True

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "question": self.question,
            "type": self.type,
            "anchors": [{"value": a.value, "description": a.description}
                        for a in self.anchors],
            "target_field": self.target_field,
            "extract_first": self.extract_first,
        }


@dataclass
class RubricTemplate:
    """A complete rubric for one dimension type.

    Attributes:
        dimension_type: The requirement type this rubric applies to
            (e.g., "skill", "experience", "education").
        sub_questions: The ordered list of sub-questions the LLM must answer.
        formula: How sub-scores combine (e.g., "gate * years_ratio * relevance").
            Applied in code, never by the LLM.
        sections: Which canonical section(s) this rubric reads from
            (same as the Section-Routed mapping).
        description: Human-readable summary.
    """

    dimension_type: str
    sub_questions: List[SubQuestion]
    formula: str
    sections: List[str]
    description: str

    def to_dict(self) -> dict:
        return {
            "dimension_type": self.dimension_type,
            "description": self.description,
            "sections": self.sections,
            "formula": self.formula,
            "sub_questions": [sq.to_dict() for sq in self.sub_questions],
        }


# ---------------------------------------------------------------------------
# Anchors
# ---------------------------------------------------------------------------

BINARY_ANCHORS = [
    Anchor(0.0, "No — the requirement is not met"),
    Anchor(1.0, "Yes — the requirement is met"),
]


# ---------------------------------------------------------------------------
# Named Rubric Scoring Functions
# ---------------------------------------------------------------------------

def score_binary(condition_met: bool) -> float:
    """
    Binary gate: 1.0 if condition met, 0.0 otherwise.

    Args:
        condition_met: True if condition is met.

    Returns:
        1.0 or 0.0 float value.
    """
    return 1.0 if condition_met else 0.0


def score_four_band_qualitative(level: str) -> float:
    """
    4-band scale for qualitative experience (no timelines/dates mentioned).

    Args:
        level: Level of experience/tasks ("substantial", "some", "few", "none").

    Returns:
        Mapped points multiplier: 1.00 / 0.50 / 0.25 / 0.01.
    """
    if not level:
        return 0.01
    val = level.lower().strip()
    if any(x in val for x in ("substantial", "high", "strong", "expert", "meets-or-exceeds")):
        return 1.00
    elif any(x in val for x in ("some", "moderate", "medium", "partial")):
        return 0.50
    elif any(x in val for x in ("few", "basic", "low", "limited", "minimal")):
        return 0.25
    return 0.01


def score_four_band_quantitative(
    extracted_years: Optional[float],
    target_years: float,
) -> float:
    """
    4-band scale for quantitative experience (timeline/duration present).

    Args:
        extracted_years: Years detected in resume.
        target_years: Expectation target years.

    Returns:
        Banded points multiplier: 1.00 / 0.50 / 0.25 / 0.01.
    """
    if extracted_years is None or target_years <= 0:
        return 0.01
    if extracted_years >= target_years:
        return 1.00
    if extracted_years >= 0.5 * target_years:
        return 0.50
    if extracted_years >= 0.25 * target_years:
        return 0.25
    return 0.01


def score_cgpa(score: Optional[float], target: float) -> float:
    """
    2-band check for CGPA / percentage marks against academic target.

    BUG-5 FIX: When ``score`` is ``None`` the CGPA was not found on the
    resume (many candidates simply don't include it). Returning 0.01
    previously penalised every such candidate as if they had a red-flag
    academic history. The correct behaviour is to return 0.50 — a neutral
    "no data" score that does not unfairly disadvantage the candidate but
    also doesn't award them full credit.

    Args:
        score: Extracted CGPA or percentage marks, or ``None`` if absent.
        target: Target marks criterion (e.g. 7.0 on a 10-pt scale,
            or 70.0 as a percentage).

    Returns:
        1.00 if score >= target.
        0.50 if score < target (partial credit — below threshold but present).
        0.50 if score is None (neutral — no CGPA data on resume).
    """
    if score is None:
        # No CGPA found on the resume — neutral score, do not penalise.
        return 0.50

    # Scale normalisation:
    # If target is a percentage (e.g. 70) but score is a CGPA (e.g. 8.5),
    # convert CGPA → percentage for comparison.
    s = float(score)
    t = float(target)
    if t > 10.0 and s <= 10.0:
        s = s * 10.0
    # If target is a CGPA (e.g. 7.0) but score is a percentage (e.g. 85.0),
    # convert percentage → CGPA.
    elif t <= 10.0 and s > 10.0:
        s = s / 10.0

    return 1.00 if s >= t else 0.50


def score_institution_rank(institute_name: str) -> float:
    """
    Tier lookup points multiplier for a university / institute.

    BUG-6 FIX: When ``institute_name`` is empty (not extracted from the
    resume due to a parsing bug) this previously returned 0.01 — the same
    score as a fake or flagged institution. The correct behaviour is 0.50:
    the candidate has not been penalised for an unknown / unlisted
    institution, but has not been awarded credit either. The ``lookup_institute_tier``
    function handles explicitly flagged institutions and returns 0.01 for
    those; the empty-name case is a data-absence situation, not a flag.

    Args:
        institute_name: Name of the institute.

    Returns:
        1.00 (Tier 1) / 0.75 (Tier 2) / 0.50 (Tier 3 or unlisted) /
        0.01 (flagged / fake institution).
    """
    if not institute_name:
        # Empty name means extraction failed, not that the institute is fake.
        # Return neutral score to avoid penalising the candidate.
        return 0.50
    _, points = lookup_institute_tier(institute_name)
    # If the tier lookup returns 0.01 for an unlisted institute, upgrade to
    # 0.50 (neutral) — only keep 0.01 for explicitly flagged institutions.
    return points if points > 0.01 else 0.50


def score_certificate_rank(provider_name: str) -> float:
    """
    Tier lookup points multiplier for a certification provider.

    BUG-6 FIX (parallel to ``score_institution_rank``): Empty provider name
    means the provider wasn't extracted, not that it is a low-quality cert.
    Return 0.50 (neutral) instead of 0.01 (penalising).

    Args:
        provider_name: Name of the provider.

    Returns:
        1.00 (Tier 1) / 0.75 (Tier 2) / 0.50 (Tier 3 or unlisted or absent) /
        0.01 (flagged / fake provider).
    """
    if not provider_name:
        # Empty name means extraction failed — neutral, don't penalise.
        return 0.50
    _, points = lookup_certificate_tier(provider_name)
    # If the tier lookup returns 0.01 for an unlisted provider, upgrade to
    # 0.50 — only keep 0.01 for explicitly flagged providers.
    return points if points > 0.01 else 0.50

