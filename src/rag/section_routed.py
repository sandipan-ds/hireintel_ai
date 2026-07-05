"""Section-Routed Evidence Retrieval — the per-candidate evidence path for scoring.

Per ``WORKING_LOGIC.md`` ("Section-Routed Evidence Retrieval"):

A JD requirement does not need to be searched for inside a resume — a resume
is one short document (typically 1,000–3,000 tokens), and once it is chunked
and header-normalized, the system already knows exactly where each
requirement's evidence lives. Similarity ranking is the wrong tool here: a
single resume isn't a corpus to search, it's something to read.

Each requirement is mapped to the canonical section(s) it depends on, by a
**fixed table**, not a model decision:

    Education requirement      → Education chunk(s)
    Skill / experience depth   → Experience + Projects + Skills chunks
    Certification requirement  → Certifications chunk(s)
    ...

Retrieval here is an **exact label match** — fetch every chunk tagged with
the mapped section(s) — never a ranked top-K subset. Nothing is filtered out,
and the same requirement against the same resume always returns the same
content, every time: no embeddings, no cosine similarity, and no risk of a
relevant chunk silently falling below a similarity cutoff.

If a section turns out to be unusually long (a senior candidate's multi-page
Experience history), deterministic metadata filtering
(``skills_asserted contains "Python"``) narrows it further — still an exact
filter, not a similarity rank.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from rag.document_aware_chunker import ChunkRecord

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fixed requirement → section mapping table (NOT a model decision).
#
# This table is the heart of Section-Routed Evidence Retrieval. It defines
# which canonical section(s) each requirement type depends on. The mapping
# is fixed and recruiter-visible — the LLM never decides which sections to
# read for a given requirement.
#
# Canonical sections (from Header Normalization):
#   Personal_Info | Education | Experience | Projects
#   | Skills | Certifications | Languages
# ---------------------------------------------------------------------------

REQUIREMENT_TO_SECTIONS: Dict[str, List[str]] = {
    # Skill requirements (e.g., "Python", "Power BI") — evidence lives in
    # Experience (where the skill was used), Projects (where it was applied),
    # and Skills (where it's asserted).
    "skill": ["Experience", "Projects", "Skills"],

    # Experience requirements (e.g., "5+ years in data science") — evidence
    # lives in the Experience section.
    "experience": ["Experience"],
    "leadership": ["Experience"],
    "same_role": ["Experience"],
    "domain": ["Experience", "Projects"],

    # Education requirements (e.g., "BTech") — evidence lives in Education.
    "education": ["Education"],

    # Certification requirements (e.g., "AWS Certified") — evidence lives in
    # Certifications.
    "certification": ["Certifications"],

    # Project relevance — evidence lives in Projects and Experience.
    "project": ["Projects", "Experience"],

    # Language requirements — evidence lives in Languages.
    "language": ["Languages"],

    # Location — evidence lives in Personal_Info (contact/header).
    "location": ["Personal_Info"],

    # Communication quality (subjective) — evidence lives in Experience
    # (bullet points, descriptions) and Personal_Info (summary).
    "communication": ["Experience", "Personal_Info"],

    # Resume organization (subjective) — read the full resume.
    "resume_organization": ["Experience", "Education", "Projects", "Skills",
                            "Certifications", "Languages", "Personal_Info"],
}

# Default fallback: if a requirement type is unknown, read everything.
_DEFAULT_SECTIONS: List[str] = ["Experience", "Projects", "Skills",
                                 "Education", "Certifications", "Languages",
                                 "Personal_Info"]

# ---------------------------------------------------------------------------
# Weight-config category → requirement type mapping.
#
# The recruiter's weight config groups items into categories like "Core
# Skills", "Education", "Certifications". This maps those human-readable
# category names to the requirement types used by the routing table above.
# ---------------------------------------------------------------------------

CATEGORY_TO_TYPE: Dict[str, str] = {
    # Skill categories
    "core skills": "skill",
    "core skills & technologies": "skill",
    "technology & tools": "skill",
    "technology and tools": "skill",
    "technical skills": "skill",
    "skills": "skill",
    "tools": "skill",
    "programming": "skill",
    "programming languages": "skill",

    # Experience categories
    "experience": "experience",
    "relevant experience": "experience",
    "overall relevant experience": "experience",
    "same role experience": "same_role",
    "same-role experience": "same_role",
    "leadership experience": "leadership",
    "leadership": "leadership",
    "industry experience": "domain",
    "management experience": "leadership",
    "product company experience": "domain",
    "technology stack experience": "skill",

    # Education categories
    "education": "education",
    "education fit": "education",
    "academic": "education",

    # Certification categories
    "certifications": "certification",
    "certification": "certification",
    "certification alignment": "certification",

    # Project categories
    "projects": "project",
    "project relevance": "project",
    "project experience": "project",

    # Language categories
    "languages": "language",
    "language": "language",
    "language capabilities": "language",

    # Location
    "location": "location",

    # Subjective
    "communication quality": "communication",
    "communication": "communication",
    "resume organization": "resume_organization",
}

# ---------------------------------------------------------------------------
# Threshold for metadata filtering.
#
# If the total character count of the retrieved chunks exceeds this threshold,
# and a skill filter is available, we narrow the chunks using deterministic
# metadata filtering (skills_asserted). This only happens for unusually long
# sections (e.g., a senior candidate's multi-page Experience history).
# ---------------------------------------------------------------------------

MAX_FULL_CONTENT_CHARS: int = 6000


# ---------------------------------------------------------------------------
# Data class for the retrieval result.
# ---------------------------------------------------------------------------

@dataclass
class SectionEvidence:
    """Evidence retrieved via Section-Routed Evidence Retrieval.

    This is the input to the rubric-bound LLM evidence scorer (Phase 4).
    It contains the full, intact section content for a requirement — not a
    similarity-ranked subset.

    Attributes:
        requirement_type: The type of requirement (e.g., "skill", "education").
        requirement_name: The original requirement name from the JD/weight config.
        sections: The canonical section(s) that were fetched.
        chunks: All matching chunks (full content, not top-K).
        full_text: Concatenated text of all chunks — this is what the LLM reads.
        chunk_count: Number of chunks retrieved.
        filtered_by_skill: Whether metadata filtering was applied.
        skill_filter: The skill used for filtering, if any.
    """

    requirement_type: str
    requirement_name: str
    sections: List[str]
    chunks: List[ChunkRecord]
    full_text: str
    chunk_count: int
    filtered_by_skill: bool = False
    skill_filter: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requirement_type": self.requirement_type,
            "requirement_name": self.requirement_name,
            "sections": self.sections,
            "chunk_count": self.chunk_count,
            "full_text_length": len(self.full_text),
            "filtered_by_skill": self.filtered_by_skill,
            "skill_filter": self.skill_filter,
            "chunk_ids": [c.chunk_id for c in self.chunks],
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def route_requirement_to_sections(requirement_type: str) -> List[str]:
    """Look up which canonical section(s) a requirement type maps to.

    This is the fixed routing table — NOT a model decision. The same
    requirement type always maps to the same sections.

    Args:
        requirement_type: One of the keys in ``REQUIREMENT_TO_SECTIONS``
            (e.g., "skill", "education", "certification").

    Returns:
        List of canonical section names to fetch.
    """
    return REQUIREMENT_TO_SECTIONS.get(requirement_type, _DEFAULT_SECTIONS)


def classify_requirement_type(
    category: Optional[str] = None,
    requirement_name: Optional[str] = None,
) -> str:
    """Classify a requirement into a type for section routing.

    Tries the weight-config category first (most reliable), then falls back
    to keyword matching on the requirement name.

    Args:
        category: The category from the weight config (e.g., "Core Skills").
        requirement_name: The requirement name (e.g., "Python").

    Returns:
        Requirement type string (e.g., "skill", "education").
    """
    # Try category first.
    if category:
        cat_lower = category.lower().strip()
        if cat_lower in CATEGORY_TO_TYPE:
            return CATEGORY_TO_TYPE[cat_lower]

    # Fallback: infer from requirement name keywords.
    if requirement_name:
        name_lower = requirement_name.lower()

        # Location keywords (check first — avoids false positives like
        # "mumbai" matching "mba" in the education check below).
        if any(kw in name_lower for kw in ("location", "city", "relocate",
                                            "remote", "onsite", "hybrid")):
            return "location"

        # Language keywords.
        if any(kw in name_lower for kw in ("language", "english", "hindi",
                                            "spanish", "french", "german",
                                            "chinese", "japanese")):
            return "language"

        # Certification keywords.
        if any(kw in name_lower for kw in ("certification", "certificate",
                                            "certified", "aws ", "azure", "gcp",
                                            "pmp", "cissp", "cfa", "cpa",
                                            "licensed", "license")):
            return "certification"

        # Education keywords (use word-boundary-safe checks to avoid false
        # positives like "mba" matching inside "mumbai").
        import re
        if any(re.search(r"\b" + re.escape(kw) + r"\b", name_lower)
               for kw in ("degree", "b.tech", "btech", "b.e.", "m.tech", "mtech",
                          "mba", "b.sc", "m.sc", "bba", "bca", "mca", "diploma",
                          "phd", "graduation", "education", "university", "college")):
            return "education"

        # Leadership keywords.
        if any(kw in name_lower for kw in ("leadership", "team lead",
                                            "manager", "managing", "lead")):
            return "leadership"

        # Experience keywords.
        if any(kw in name_lower for kw in ("experience", "years", "exp")):
            return "experience"

        # Default: treat as a skill.
        return "skill"

    # No category and no name — default to skill (most common).
    return "skill"


def section_routed_retrieval(
    requirement_type: str,
    requirement_name: str,
    candidate_chunks: List[ChunkRecord],
    skill_filter: Optional[str] = None,
) -> SectionEvidence:
    """Fetch all chunks tagged with the mapped section(s) for a requirement.

    This is the main entry point for Section-Routed Evidence Retrieval.
    It performs an **exact label match** on canonical section names — no
    embeddings, no cosine similarity, no top-K ranking. The same requirement
    against the same resume always returns the same content.

    If the total content exceeds ``MAX_FULL_CONTENT_CHARS`` and a
    ``skill_filter`` is provided, deterministic metadata filtering
    (``skills_asserted contains skill_filter``) narrows the chunks — still
    an exact filter, not a similarity rank.

    Args:
        requirement_type: The type of requirement (e.g., "skill", "education").
            See ``classify_requirement_type`` for how to determine this.
        requirement_name: The original requirement name from the JD/weight config.
        candidate_chunks: All chunks for this candidate (from the chunker).
        skill_filter: Optional skill name to filter by when the section is too
            long. The filter checks ``chunk.skills_asserted`` — an exact
            metadata match, not a similarity score.

    Returns:
        ``SectionEvidence`` containing the full section content for the LLM
        judge to read.
    """
    # Step 1: Route the requirement to canonical section(s) via the fixed table.
    sections = route_requirement_to_sections(requirement_type)

    # Step 2: Fetch ALL chunks tagged with any of the mapped sections.
    # Matching is case-insensitive to handle both "Experience" (canonical)
    # and "experience" (legacy parser) section names.
    sections_lower = {s.lower() for s in sections}
    matched_chunks = [
        chunk for chunk in candidate_chunks
        if chunk.section.lower() in sections_lower
    ]

    # Step 3: If the section is unusually long and a skill filter is available,
    # narrow with deterministic metadata filtering.
    filtered = False
    total_chars = sum(len(c.text) for c in matched_chunks)

    if total_chars > MAX_FULL_CONTENT_CHARS and skill_filter:
        skill_lower = skill_filter.lower()
        filtered_chunks = [
            chunk for chunk in matched_chunks
            if any(skill_lower == s.lower() for s in chunk.skills_asserted)
        ]
        # Only apply the filter if it actually narrows the results.
        # If the filter removes everything (skill not in any chunk's
        # skills_asserted), keep the original chunks — better to send
        # too much than nothing.
        if filtered_chunks and len(filtered_chunks) < len(matched_chunks):
            matched_chunks = filtered_chunks
            filtered = True

    # Step 4: Concatenate full text.
    full_text = "\n\n---\n\n".join(chunk.text for chunk in matched_chunks)

    return SectionEvidence(
        requirement_type=requirement_type,
        requirement_name=requirement_name,
        sections=sections,
        chunks=matched_chunks,
        full_text=full_text,
        chunk_count=len(matched_chunks),
        filtered_by_skill=filtered,
        skill_filter=skill_filter if filtered else None,
    )


def retrieve_evidence_for_requirement(
    requirement_name: str,
    category: Optional[str],
    candidate_chunks: List[ChunkRecord],
) -> SectionEvidence:
    """Convenience: classify + route + retrieve in one call.

    Args:
        requirement_name: The requirement name from the weight config.
        category: The category from the weight config (e.g., "Core Skills").
        candidate_chunks: All chunks for this candidate.

    Returns:
        ``SectionEvidence`` with the full section content.
    """
    req_type = classify_requirement_type(category, requirement_name)

    # For skill requirements, use the requirement name as the skill filter
    # so that long Experience sections can be narrowed.
    skill_filter = requirement_name if req_type == "skill" else None

    return section_routed_retrieval(
        requirement_type=req_type,
        requirement_name=requirement_name,
        candidate_chunks=candidate_chunks,
        skill_filter=skill_filter,
    )
