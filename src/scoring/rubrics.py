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
# Shared anchor sets.
# ---------------------------------------------------------------------------

# Binary gate: 0 or 1.
BINARY_ANCHORS = [
    Anchor(0.0, "No — the requirement is not met"),
    Anchor(1.0, "Yes — the requirement is met"),
]

# Project relevance anchored scale (per WORKING_LOGIC.md).
RELEVANCE_ANCHORS = [
    Anchor(0.0, "No relevant projects or experience"),
    Anchor(0.25, "Tangential mention, no real project work in this area"),
    Anchor(0.5, "One project partially relevant to the JD requirement"),
    Anchor(0.75, "Multiple projects clearly relevant to the JD requirement"),
    Anchor(1.0, "Projects directly match the JD requirement (exact match)"),
]

# Project complexity / depth anchored scale.
COMPLEXITY_ANCHORS = [
    Anchor(0.0, "No project work demonstrated"),
    Anchor(0.25, "Simple/tutorial-level projects only"),
    Anchor(0.5, "One substantial project with real complexity"),
    Anchor(0.75, "Multiple projects with clear depth and ownership"),
    Anchor(1.0, "Complex, production-grade projects with significant impact"),
]

# Language proficiency anchored scale.
PROFICIENCY_ANCHORS = [
    Anchor(0.0, "No knowledge of this language"),
    Anchor(0.25, "Basic — can read simple text"),
    Anchor(0.5, "Intermediate — can converse on familiar topics"),
    Anchor(0.75, "Professional working proficiency"),
    Anchor(1.0, "Native or bilingual proficiency"),
]

# Communication quality anchored scale (subjective).
COMMUNICATION_ANCHORS = [
    Anchor(0.0, "Resume is disorganized, unclear, or poorly written"),
    Anchor(0.25, "Resume has significant clarity issues"),
    Anchor(0.5, "Resume is adequately written but lacks polish"),
    Anchor(0.75, "Resume is well-organized with clear, professional language"),
    Anchor(1.0, "Exceptional communication — concise, impactful, well-structured"),
]

# Resume organization anchored scale (subjective).
ORGANIZATION_ANCHORS = [
    Anchor(0.0, "No clear structure — sections blend together"),
    Anchor(0.25, "Minimal structure, hard to find key information"),
    Anchor(0.5, "Basic structure present but inconsistent"),
    Anchor(0.75, "Clear section structure, easy to navigate"),
    Anchor(1.0, "Excellent organization — every section clearly labeled and ordered"),
]


# ---------------------------------------------------------------------------
# Rubric templates — one per dimension type.
# ---------------------------------------------------------------------------

SKILL_RUBRIC = RubricTemplate(
    dimension_type="skill",
    description=(
        "Evaluates a skill requirement (e.g., Python, Power BI). "
        "The LLM extracts every role/project where the skill appears, "
        "then scores presence, years, and project relevance."
    ),
    sections=["Experience", "Projects", "Skills"],
    formula="gate * years_ratio * relevance",
    sub_questions=[
        SubQuestion(
            key="skill_presence",
            question="Does the candidate know {skill}?",
            type="binary",
            anchors=BINARY_ANCHORS,
            extract_first=True,
        ),
        SubQuestion(
            key="years_experience",
            question="How many years of relevant experience does the candidate have with {skill}?",
            type="linear",
            target_field="expected_years",
            extract_first=True,
        ),
        SubQuestion(
            key="project_relevance",
            question="How relevant are the candidate's projects to the JD requirement for {skill}?",
            type="anchored",
            anchors=RELEVANCE_ANCHORS,
            extract_first=True,
        ),
    ],
)

EXPERIENCE_RUBRIC = RubricTemplate(
    dimension_type="experience",
    description=(
        "Evaluates a general experience requirement (e.g., '5+ years in data science'). "
        "The LLM extracts all relevant experience and scores presence, years, and relevance."
    ),
    sections=["Experience"],
    formula="gate * years_ratio * relevance",
    sub_questions=[
        SubQuestion(
            key="experience_presence",
            question="Is the candidate experienced in this area?",
            type="binary",
            anchors=BINARY_ANCHORS,
            extract_first=True,
        ),
        SubQuestion(
            key="years_experience",
            question="How many years of relevant experience does the candidate have?",
            type="linear",
            target_field="expected_years",
            extract_first=True,
        ),
        SubQuestion(
            key="project_relevance",
            question="How relevant is the candidate's experience to the JD requirement?",
            type="anchored",
            anchors=RELEVANCE_ANCHORS,
            extract_first=True,
        ),
    ],
)

LEADERSHIP_RUBRIC = RubricTemplate(
    dimension_type="leadership",
    description=(
        "Evaluates a leadership experience requirement (e.g., '6 years in a leadership role'). "
        "Adds a binary leadership gate on top of the experience rubric."
    ),
    sections=["Experience"],
    formula="gate * years_ratio * leadership_gate * relevance",
    sub_questions=[
        SubQuestion(
            key="experience_presence",
            question="Is the candidate experienced?",
            type="binary",
            anchors=BINARY_ANCHORS,
            extract_first=True,
        ),
        SubQuestion(
            key="years_experience",
            question="How many years of relevant experience?",
            type="linear",
            target_field="expected_years",
            extract_first=True,
        ),
        SubQuestion(
            key="leadership_gate",
            question="Has the candidate served in a leadership or similar responsible role? (e.g., team lead, project owner, senior IC with mentoring)",
            type="binary",
            anchors=BINARY_ANCHORS,
            extract_first=True,
        ),
        SubQuestion(
            key="project_relevance",
            question="How relevant are the candidate's projects to the JD requirement?",
            type="anchored",
            anchors=RELEVANCE_ANCHORS,
            extract_first=True,
        ),
    ],
)

SAME_ROLE_RUBRIC = RubricTemplate(
    dimension_type="same_role",
    description=(
        "Evaluates same/similar-role experience (e.g., 'has worked as a Business Analyst'). "
        "The binary gate checks for a similar role — not necessarily identical. "
        "The relevance sub-score then judges how close the match is."
    ),
    sections=["Experience"],
    formula="gate * years_ratio * relevance",
    sub_questions=[
        SubQuestion(
            key="role_presence",
            question="Has the candidate served in a similar role? (not necessarily the same title — e.g., 'Business Analyst' is similar to 'Data Analyst')",
            type="binary",
            anchors=BINARY_ANCHORS,
            extract_first=True,
        ),
        SubQuestion(
            key="years_experience",
            question="How many years has the candidate spent in a similar role?",
            type="linear",
            target_field="expected_years",
            extract_first=True,
        ),
        SubQuestion(
            key="project_relevance",
            question="How relevant is this role experience to the JD requirement? (This judges the actual degree of similarity.)",
            type="anchored",
            anchors=RELEVANCE_ANCHORS,
            extract_first=True,
        ),
    ],
)

DOMAIN_RUBRIC = RubricTemplate(
    dimension_type="domain",
    description=(
        "Evaluates industry/domain experience (e.g., 'healthcare domain experience'). "
        "The binary gate checks for a similar domain — not necessarily identical. "
        "The relevance sub-score then judges how close the domain match is "
        "(e.g., 'finance' and 'banking' are similar, not the same)."
    ),
    sections=["Experience", "Projects"],
    formula="gate * years_ratio * relevance",
    sub_questions=[
        SubQuestion(
            key="domain_presence",
            question="Has the candidate served in a similar domain/industry? (not necessarily the same — e.g., 'finance' is similar to 'banking')",
            type="binary",
            anchors=BINARY_ANCHORS,
            extract_first=True,
        ),
        SubQuestion(
            key="years_experience",
            question="How many years of experience in a similar domain?",
            type="linear",
            target_field="expected_years",
            extract_first=True,
        ),
        SubQuestion(
            key="project_relevance",
            question="How relevant are the domain-specific projects to the JD requirement? (This judges the actual degree of domain similarity.)",
            type="anchored",
            anchors=RELEVANCE_ANCHORS,
            extract_first=True,
        ),
    ],
)

EDUCATION_RUBRIC = RubricTemplate(
    dimension_type="education",
    description=(
        "Evaluates an education requirement (e.g., 'BTech in Computer Science'). "
        "Code-only: degree match from structured profile + institute tier lookup. "
        "The LLM is NOT involved — this is fully deterministic."
    ),
    sections=["Education"],
    formula="degree_match * institute_tier_points",
    sub_questions=[
        SubQuestion(
            key="degree_match",
            question="Does the candidate hold the required degree?",
            type="binary",
            anchors=BINARY_ANCHORS,
            extract_first=False,
        ),
        SubQuestion(
            key="institute_tier",
            question="What is the tier of the candidate's institute? (code-only lookup)",
            type="anchored",
            anchors=[
                Anchor(1.0, "Tier 1 — premier institute (IIT, NIT, IISc, world top 100)"),
                Anchor(0.75, "Tier 2 — recognized institute (state university, good private)"),
                Anchor(0.50, "Tier 3 — regional/accredited institute or not listed"),
            ],
            target_field=None,
            extract_first=False,
        ),
    ],
)

CERTIFICATION_RUBRIC = RubricTemplate(
    dimension_type="certification",
    description=(
        "Evaluates a certification requirement (e.g., 'AWS Certified'). "
        "Code-only: cert match + provider tier lookup. The LLM is NOT involved."
    ),
    sections=["Certifications"],
    formula="cert_match * provider_tier_points",
    sub_questions=[
        SubQuestion(
            key="cert_match",
            question="Does the candidate hold the required certification?",
            type="binary",
            anchors=BINARY_ANCHORS,
            extract_first=False,
        ),
        SubQuestion(
            key="provider_tier",
            question="What is the tier of the certification provider? (code-only lookup)",
            type="anchored",
            anchors=[
                Anchor(1.0, "Tier 1 — top-tier cert (AWS, Microsoft, Google, PMP, etc.)"),
                Anchor(0.75, "Tier 2 — second-grade cert (Coursera, NPTEL, etc.)"),
                Anchor(0.50, "Tier 3 — local/bootcamp or not listed"),
            ],
            target_field=None,
            extract_first=False,
        ),
    ],
)

PROJECT_RUBRIC = RubricTemplate(
    dimension_type="project",
    description=(
        "Evaluates project relevance and depth. "
        "The LLM extracts project descriptions and scores relevance and complexity."
    ),
    sections=["Projects", "Experience"],
    formula="presence * relevance * complexity",
    sub_questions=[
        SubQuestion(
            key="project_presence",
            question="Does the candidate have any projects?",
            type="binary",
            anchors=BINARY_ANCHORS,
            extract_first=True,
        ),
        SubQuestion(
            key="project_relevance",
            question="How relevant are the candidate's projects to the JD requirement?",
            type="anchored",
            anchors=RELEVANCE_ANCHORS,
            extract_first=True,
        ),
        SubQuestion(
            key="project_complexity",
            question="What is the complexity/depth of the candidate's projects?",
            type="anchored",
            anchors=COMPLEXITY_ANCHORS,
            extract_first=True,
        ),
    ],
)

LANGUAGE_RUBRIC = RubricTemplate(
    dimension_type="language",
    description=(
        "Evaluates a language requirement (e.g., 'English proficiency'). "
        "The LLM checks presence and proficiency level."
    ),
    sections=["Languages"],
    formula="presence * proficiency",
    sub_questions=[
        SubQuestion(
            key="language_presence",
            question="Does the candidate know this language?",
            type="binary",
            anchors=BINARY_ANCHORS,
            extract_first=True,
        ),
        SubQuestion(
            key="language_proficiency",
            question="What is the candidate's proficiency level in this language?",
            type="anchored",
            anchors=PROFICIENCY_ANCHORS,
            extract_first=True,
        ),
    ],
)

LOCATION_RUBRIC = RubricTemplate(
    dimension_type="location",
    description=(
        "Evaluates a location requirement. Code-only — binary match from "
        "the structured profile. No LLM involved."
    ),
    sections=["Personal_Info"],
    formula="match",
    sub_questions=[
        SubQuestion(
            key="location_match",
            question="Does the candidate's location match the JD requirement?",
            type="binary",
            anchors=BINARY_ANCHORS,
            extract_first=False,
        ),
    ],
)

COMMUNICATION_RUBRIC = RubricTemplate(
    dimension_type="communication",
    description=(
        "Evaluates communication quality (subjective). "
        "The LLM assesses the resume's writing quality, clarity, and structure."
    ),
    sections=["Experience", "Personal_Info"],
    formula="communication_score",
    sub_questions=[
        SubQuestion(
            key="communication_score",
            question="How would you rate the candidate's communication quality based on the resume?",
            type="anchored",
            anchors=COMMUNICATION_ANCHORS,
            extract_first=True,
        ),
    ],
)

RESUME_ORGANIZATION_RUBRIC = RubricTemplate(
    dimension_type="resume_organization",
    description=(
        "Evaluates resume organization (subjective). "
        "The LLM assesses the structure, labeling, and navigability of the resume."
    ),
    sections=["Experience", "Education", "Projects", "Skills",
              "Certifications", "Languages", "Personal_Info"],
    formula="organization_score",
    sub_questions=[
        SubQuestion(
            key="organization_score",
            question="How would you rate the resume's organization and structure?",
            type="anchored",
            anchors=ORGANIZATION_ANCHORS,
            extract_first=True,
        ),
    ],
)


# ---------------------------------------------------------------------------
# Registry — maps dimension type → rubric template.
# ---------------------------------------------------------------------------

RUBRIC_REGISTRY: Dict[str, RubricTemplate] = {
    "skill": SKILL_RUBRIC,
    "experience": EXPERIENCE_RUBRIC,
    "leadership": LEADERSHIP_RUBRIC,
    "same_role": SAME_ROLE_RUBRIC,
    "domain": DOMAIN_RUBRIC,
    "education": EDUCATION_RUBRIC,
    "certification": CERTIFICATION_RUBRIC,
    "project": PROJECT_RUBRIC,
    "language": LANGUAGE_RUBRIC,
    "location": LOCATION_RUBRIC,
    "communication": COMMUNICATION_RUBRIC,
    "resume_organization": RESUME_ORGANIZATION_RUBRIC,
}


def get_rubric(dimension_type: str) -> RubricTemplate:
    """Retrieve the rubric template for a dimension type.

    Args:
        dimension_type: One of the keys in ``RUBRIC_REGISTRY``
            (e.g., "skill", "education", "certification").

    Returns:
        ``RubricTemplate`` for the given dimension type.

    Raises:
        KeyError: If no rubric exists for the dimension type.
    """
    if dimension_type not in RUBRIC_REGISTRY:
        raise KeyError(
            f"No rubric template for dimension type '{dimension_type}'. "
            f"Available types: {list(RUBRIC_REGISTRY.keys())}"
        )
    return RUBRIC_REGISTRY[dimension_type]


def is_code_only(dimension_type: str) -> bool:
    """Check whether a dimension type is scored code-only (no LLM).

    Code-only dimensions use structured-profile lookups and tier databases.
    The LLM is not involved at all.

    Args:
        dimension_type: The dimension type to check.

    Returns:
        True if the dimension is code-only, False if it requires the LLM judge.
    """
    return dimension_type in ("education", "certification", "location")


def is_rubric_bound_llm(dimension_type: str) -> bool:
    """Check whether a dimension type requires the rubric-bound LLM judge.

    Args:
        dimension_type: The dimension type to check.

    Returns:
        True if the dimension requires the LLM judge, False if it's code-only.
    """
    return not is_code_only(dimension_type)


def all_rubric_types() -> List[str]:
    """Return all registered dimension types.

    Returns:
        List of dimension type strings.
    """
    return list(RUBRIC_REGISTRY.keys())
