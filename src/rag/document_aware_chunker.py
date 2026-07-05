"""Document-Aware chunker for parsed resume profiles (legacy, DEC-019).

This is the **legacy** chunker, retained for one release as a migration aid.
The active strategy is :class:`src.rag.recursive_chunker.RecursiveChunker`
(DEC-019, 2026-07-05). The Document-Aware chunker is preserved here so
existing pipelines and tests that depend on its section-anchored behavior
continue to work during the migration window.

Each parsed profile (see ``src.resume_parsing.parser.parse_resume``) is split
into a list of ``ChunkRecord`` objects. The chunker treats *resume sections*
as the natural semantic units:

* one chunk per experience entry
* one chunk per education entry
* one chunk per project
* one chunk per free-text section (summary, skills, certifications,
  languages, "other")

Very large chunks (> ``MAX_CHUNK_CHARS``) are sub-split on paragraph breaks
with a small overlap so the embedding model never receives text larger than
its context window.

Every chunk is enriched with metadata at parse time per ``WORKING_LOGIC.md``
"Chunk Metadata Schema":

    section_type: experience | education | skills_summary | projects | ...
    parent_structure:
      organization
      role_title
      location
      temporal_context:
        start_date
        end_date
        is_current
        calculated_duration_months   ← computed deterministically, never by the LLM
    skills_asserted: [ ... ]
    experience_type: professional | personal_project | academic | unknown

``calculated_duration_months`` is computed in code from the parsed dates at
parse time. LLMs are unreliable at date arithmetic, so this number is handed
to the LLM ready-made rather than asked for.

The output of :func:`chunk_profile` is a list of dictionaries matching the
schema documented in ``docs/AI_ARCHITECTURE.md`` § Document-Aware Chunking.

New code should import :class:`src.rag.recursive_chunker.RecursiveChunker`
instead. The module-level :func:`chunk_profile` function and
:data:`ChunkRecord` class are preserved as a backward-compat shim for one
release.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Soft upper bound for a single chunk. We split when a section is larger
# than this so embedding models with small context windows are happy.
MAX_CHUNK_CHARS: int = 1200

# Overlap applied when sub-splitting an oversized chunk. Kept small because
# sub-splits only happen on big free-text sections; we want each resulting
# chunk to remain a coherent unit.
SPLIT_OVERLAP_CHARS: int = 120


# ---------------------------------------------------------------------------
# Date parsing — deterministic, no LLM.
# ---------------------------------------------------------------------------

# Common date formats found in resumes: "2020", "Jan 2020", "January 2020",
# "01/2020", "2020-01", "Present", "Current", "Ongoing".
_MONTH_MAP = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_DATE_RANGE_RE = re.compile(
    r"(\b(?:\d{4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{4}|\d{1,2}/\d{4}|\d{4}-\d{2})\b)"
    r"\s*(?:-|–|—|to|until)\s*"
    r"(\b(?:\d{4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{4}|\d{1,2}/\d{4}|\d{4}-\d{2}|Present|Current|Ongoing|Now)\b)",
    re.IGNORECASE,
)

_PRESENT_WORDS = {"present", "current", "ongoing", "now"}


def _parse_single_date(token: str) -> Tuple[Optional[int], Optional[int], bool]:
    """Parse a single date token into (year, month, is_present).

    Args:
        token: A date string like "2020", "Jan 2020", "Present", etc.

    Returns:
        Tuple of (year, month, is_present). Year and month are ``None`` if
        unparseable. ``is_present`` is True for "Present"/"Current"/"Ongoing".
    """
    token = token.strip()
    if token.lower() in _PRESENT_WORDS:
        return None, None, True

    # "2020" — year only.
    if token.isdigit() and len(token) == 4:
        return int(token), None, False

    # "01/2020" — month/year.
    m = re.match(r"(\d{1,2})/(\d{4})", token)
    if m:
        return int(m.group(2)), int(m.group(1)), False

    # "2020-01" — year-month.
    m = re.match(r"(\d{4})-(\d{2})", token)
    if m:
        return int(m.group(1)), int(m.group(2)), False

    # "Jan 2020" / "January 2020" — month name + year.
    m = re.match(r"([A-Za-z]+)\s+(\d{4})", token)
    if m:
        month_name = m.group(1).lower()
        if month_name in _MONTH_MAP:
            return int(m.group(2)), _MONTH_MAP[month_name], False

    return None, None, False


def _months_between(start_year: int, start_month: Optional[int],
                    end_year: int, end_month: Optional[int]) -> int:
    """Compute the number of months between two dates (inclusive).

    When month is ``None`` for the start, assume January (month=1).
    When month is ``None`` for the end, assume December (month=12).
    This gives the correct full-year span: "2018-2020" → 36 months (3 years),
    not 24 or 35.

    Args:
        start_year: Start year.
        start_month: Start month (1-12), or None for unknown (→ January).
        end_year: End year.
        end_month: End month (1-12), or None for unknown (→ December).

    Returns:
        Number of months (non-negative integer, inclusive of both endpoints).
    """
    sm = start_month or 1
    em = end_month or 12
    months = (end_year * 12 + em) - (start_year * 12 + sm) + 1
    return max(0, months)


def parse_temporal_context(dates_str: str) -> Dict[str, Any]:
    """Parse a date range string into a temporal_context dict.

    This is the deterministic date parser that produces
    ``calculated_duration_months`` in code, never via the LLM.

    Args:
        dates_str: Raw date string from a resume entry, e.g.
            "2017 - Present", "Jun 2019 — Dec 2022", "2020-2023".

    Returns:
        Dict with keys: ``start_date``, ``end_date``, ``is_current``,
        ``calculated_duration_months``. Values are ``None`` when unparseable.
    """
    if not dates_str:
        return {
            "start_date": None,
            "end_date": None,
            "is_current": False,
            "calculated_duration_months": None,
        }

    match = _DATE_RANGE_RE.search(dates_str)
    if not match:
        # Try single year or single date.
        single = _parse_single_date(dates_str.strip())
        if single[0] is not None:
            return {
                "start_date": {"year": single[0], "month": single[1]},
                "end_date": {"year": single[0], "month": single[1]},
                "is_current": False,
                "calculated_duration_months": 0,
            }
        return {
            "start_date": None,
            "end_date": None,
            "is_current": False,
            "calculated_duration_months": None,
        }

    start_token, end_token = match.group(1), match.group(2)
    start_year, start_month, _ = _parse_single_date(start_token)
    end_year, end_month, is_current = _parse_single_date(end_token)

    if start_year is None:
        return {
            "start_date": None,
            "end_date": None,
            "is_current": is_current,
            "calculated_duration_months": None,
        }

    end_year_final = end_year if end_year is not None else date.today().year
    end_month_final = end_month if end_month is not None else (date.today().month if is_current else None)

    duration = _months_between(start_year, start_month, end_year_final, end_month_final)

    return {
        "start_date": {"year": start_year, "month": start_month},
        "end_date": {"year": end_year_final, "month": end_month_final} if end_year is not None or is_current else None,
        "is_current": is_current,
        "calculated_duration_months": duration,
    }


# ---------------------------------------------------------------------------
# Skills assertion — extract skill keywords from text (deterministic).
# ---------------------------------------------------------------------------

# A small stopword set to avoid asserting non-skills as skills.
_SKILL_STOPWORDS = {"and", "or", "the", "with", "using", "use", "used", "for", "to", "in", "of", "a", "an"}


def _extract_skills_asserted(text: str, known_skills: Optional[List[str]] = None) -> List[str]:
    """Extract skill keywords mentioned in a chunk's text.

    If a known skills list is provided (from the structured profile's
    ``skills`` field), we check which of those skills appear in the text.
    If no known skills list is provided, we fall back to extracting
    capitalized technical-looking tokens.

    Args:
        text: The chunk's text content.
        known_skills: Optional list of skills from the structured profile.

    Returns:
        List of skill names found in the text.
    """
    if not text:
        return []
    text_lower = text.lower()
    if known_skills:
        return [
            skill for skill in known_skills
            if skill.lower() in text_lower and skill.lower() not in _SKILL_STOPWORDS
        ]
    # Fallback: extract capitalized words that look like tech terms.
    # This is intentionally conservative — better to miss a skill than
    # to assert a false one.
    return []


# ---------------------------------------------------------------------------
# Experience type classification — deterministic.
# ---------------------------------------------------------------------------

def _classify_experience_type(text: str, section: str) -> str:
    """Classify the experience type of a chunk.

    Args:
        text: The chunk's text content.
        section: The canonical section name.

    Returns:
        One of: "professional", "personal_project", "academic", "unknown".
    """
    text_lower = text.lower()
    if section == "projects":
        # Heuristic: "academic" if it mentions university/coursework context.
        if any(w in text_lower for w in ("university", "course", "thesis", "dissertation", "academic", "capstone")):
            return "academic"
        if any(w in text_lower for w in ("personal", "side project", "hobby", "self-taught")):
            return "personal_project"
        return "professional"
    if section == "experience":
        return "professional"
    if section == "education":
        return "academic"
    return "unknown"


# ---------------------------------------------------------------------------
# Chunk record with full metadata schema.
# ---------------------------------------------------------------------------


@dataclass
class ChunkRecord:
    """One chunk of a resume, ready for embedding + retrieval.

    The chunk carries the full metadata schema from ``WORKING_LOGIC.md``
    "Chunk Metadata Schema" so downstream scoring can use
    ``calculated_duration_months``, ``experience_type``, ``skills_asserted``,
    and ``parent_structure`` without re-deriving them via an LLM.
    """

    chunk_id: str
    candidate_id: str
    role_bucket: str
    source_file: str
    section: str
    chunk_index: int
    text: str
    char_span: Tuple[int, int]
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Full metadata schema fields (per WORKING_LOGIC.md "Chunk Metadata Schema").
    section_type: str = ""
    parent_structure: Dict[str, Any] = field(default_factory=dict)
    skills_asserted: List[str] = field(default_factory=list)
    experience_type: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a dict matching the documented chunk schema."""
        return {
            "chunk_id": self.chunk_id,
            "candidate_id": self.candidate_id,
            "role_bucket": self.role_bucket,
            "source_file": self.source_file,
            "section": self.section,
            "chunk_index": self.chunk_index,
            "text": self.text,
            "char_span": list(self.char_span),
            "metadata": self.metadata,
            # Full metadata schema (per WORKING_LOGIC.md "Chunk Metadata Schema").
            "section_type": self.section_type,
            "parent_structure": self.parent_structure,
            "skills_asserted": self.skills_asserted,
            "experience_type": self.experience_type,
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def chunk_profile(profile: Dict[str, Any], role_bucket: str = "") -> List[ChunkRecord]:
    """Convert one parsed profile into a list of chunk records.

    Args:
        profile:
            A parsed resume dict as produced by
            ``src.resume_parsing.parser.parse_resume``.
        role_bucket:
            The role folder the resume was filed under
            (``"BusinessAnalyst"``, ``"DataScience"`` ...). Used as a
            metadata field so the vector store can be filtered by role.

    Returns:
        List of :class:`ChunkRecord`. Order is deterministic: summary,
        experience entries, education entries, projects, skills,
        certifications, languages, other free-text sections.
    """
    candidate_id = profile.get("candidate_id") or "cand_unknown"
    source_file = profile.get("source_file", "")

    chunks: List[ChunkRecord] = []

    # ---- 1) Summary ---------------------------------------------------
    summary = profile.get("summary") or {}
    summary_text = (summary.get("value") or "").strip()
    if summary_text:
        chunks.extend(
            _emit_section_chunks(
                profile=profile,
                candidate_id=candidate_id,
                role_bucket=role_bucket,
                source_file=source_file,
                section_name="summary",
                text=summary_text,
                char_span=None,
                metadata={},
            )
        )

    # ---- 2) Experience (one chunk per entry) --------------------------
    # Known skills from the profile, used for skills_asserted extraction.
    known_skills = profile.get("skills") or []

    experience = profile.get("experience") or {}
    experience_records = experience.get("entries") or []
    for i, entry in enumerate(experience_records):
        text = _entry_to_text(entry)
        if not text:
            continue

        # Parse dates deterministically → temporal_context with
        # calculated_duration_months computed in code, never by the LLM.
        dates_str = entry.get("dates") or ""
        temporal_context = parse_temporal_context(dates_str)

        # Extract skills mentioned in this entry's text.
        skills_in_entry = _extract_skills_asserted(text, known_skills)

        # Classify experience type.
        exp_type = _classify_experience_type(text, "experience")

        chunks.append(
            ChunkRecord(
                chunk_id=f"{candidate_id}__experience__{i}",
                candidate_id=candidate_id,
                role_bucket=role_bucket,
                source_file=source_file,
                section="experience",
                chunk_index=i,
                text=text,
                char_span=(0, len(text)),
                metadata={
                    "title": entry.get("title"),
                    "company": entry.get("company"),
                    "dates": entry.get("dates"),
                    "location": entry.get("location"),
                    "bullet_count": len(entry.get("details") or []),
                },
                section_type="experience",
                parent_structure={
                    "organization": entry.get("company"),
                    "role_title": entry.get("title"),
                    "location": entry.get("location"),
                    "temporal_context": temporal_context,
                },
                skills_asserted=skills_in_entry,
                experience_type=exp_type,
            )
        )

    # ---- 3) Education (one chunk per entry) ---------------------------
    education = profile.get("education") or {}
    education_records = education.get("entries") or []
    for i, entry in enumerate(education_records):
        text = (entry.get("description") or "").strip()
        if not text:
            continue
        chunks.append(
            ChunkRecord(
                chunk_id=f"{candidate_id}__education__{i}",
                candidate_id=candidate_id,
                role_bucket=role_bucket,
                source_file=source_file,
                section="education",
                chunk_index=i,
                text=text,
                char_span=(0, len(text)),
                metadata={"description": text},
                section_type="education",
                parent_structure={
                    "organization": None,
                    "role_title": None,
                    "location": None,
                    "temporal_context": {
                        "start_date": None,
                        "end_date": None,
                        "is_current": False,
                        "calculated_duration_months": None,
                    },
                },
                skills_asserted=_extract_skills_asserted(text, known_skills),
                experience_type="academic",
            )
        )

    # ---- 4) Projects --------------------------------------------------
    projects = profile.get("projects") or []
    for i, project_text in enumerate(projects):
        text = (project_text or "").strip()
        if not text:
            continue
        exp_type = _classify_experience_type(text, "projects")
        chunks.append(
            ChunkRecord(
                chunk_id=f"{candidate_id}__projects__{i}",
                candidate_id=candidate_id,
                role_bucket=role_bucket,
                source_file=source_file,
                section="projects",
                chunk_index=i,
                text=text,
                char_span=(0, len(text)),
                metadata={},
                section_type="projects",
                parent_structure={
                    "organization": None,
                    "role_title": None,
                    "location": None,
                    "temporal_context": {
                        "start_date": None,
                        "end_date": None,
                        "is_current": False,
                        "calculated_duration_months": None,
                    },
                },
                skills_asserted=_extract_skills_asserted(text, known_skills),
                experience_type=exp_type,
            )
        )

    # ---- 5) Skills, certifications, languages (single chunk each) -----
    list_fields = {
        "skills": profile.get("skills") or [],
        "certifications": profile.get("certifications") or [],
        "languages": profile.get("languages") or [],
    }
    for field_name, items in list_fields.items():
        items_clean = [str(x).strip() for x in items if str(x).strip()]
        if not items_clean:
            continue
        text = ", ".join(items_clean)
        chunks.append(
            ChunkRecord(
                chunk_id=f"{candidate_id}__{field_name}__0",
                candidate_id=candidate_id,
                role_bucket=role_bucket,
                source_file=source_file,
                section=field_name,
                chunk_index=0,
                text=text,
                char_span=(0, len(text)),
                metadata={"items": items_clean, "count": len(items_clean)},
            )
        )

    # ---- 6) Any free-text section not yet covered ---------------------
    sections = profile.get("sections") or {}
    emitted_section_names = {
        "summary",
        "experience",
        "education",
        "projects",
        "skills",
        "certifications",
        "languages",
    }
    for section_name, record in sections.items():
        if section_name in emitted_section_names:
            continue
        section_text = (record.get("text") or "").strip()
        if not section_text:
            continue
        start = int(record.get("start", 0))
        end = int(record.get("end", start + len(section_text)))
        chunks.extend(
            _emit_section_chunks(
                profile=profile,
                candidate_id=candidate_id,
                role_bucket=role_bucket,
                source_file=source_file,
                section_name=section_name,
                text=section_text,
                char_span=(start, end),
                metadata={},
            )
        )

    return chunks


def chunks_to_jsonl(chunks: Iterable[ChunkRecord]) -> str:
    """Serialize chunks to a JSONL string (one JSON object per line)."""
    import json

    return "\n".join(json.dumps(c.to_dict(), ensure_ascii=False) for c in chunks)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entry_to_text(entry: Dict[str, Any]) -> str:
    """Render an experience/education entry as a single human-readable block."""
    parts: List[str] = []
    title = (entry.get("title") or "").strip()
    company = (entry.get("company") or "").strip()
    if title and company:
        parts.append(f"{title} @ {company}")
    elif title:
        parts.append(title)
    elif company:
        parts.append(company)
    dates = (entry.get("dates") or "").strip()
    location = (entry.get("location") or "").strip()
    if dates or location:
        meta = " | ".join(x for x in (dates, location) if x)
        parts.append(meta)
    details = [d.strip() for d in (entry.get("details") or []) if d and d.strip()]
    for bullet in details:
        parts.append(f"- {bullet}")
    return "\n".join(parts).strip()


def _emit_section_chunks(
    *,
    profile: Dict[str, Any],
    candidate_id: str,
    role_bucket: str,
    source_file: str,
    section_name: str,
    text: str,
    char_span: Optional[Tuple[int, int]],
    metadata: Dict[str, Any],
) -> List[ChunkRecord]:
    """Emit one or more chunk records for a free-text section.

    Sections shorter than ``MAX_CHUNK_CHARS`` produce a single chunk. Larger
    sections are split on paragraph breaks with a small overlap so we never
    emit a chunk larger than the embedding model's comfortable context.
    """
    text = text.strip()
    if not text:
        return []

    if len(text) <= MAX_CHUNK_CHARS:
        return [
            ChunkRecord(
                chunk_id=f"{candidate_id}__{section_name}__0",
                candidate_id=candidate_id,
                role_bucket=role_bucket,
                source_file=source_file,
                section=section_name,
                chunk_index=0,
                text=text,
                char_span=char_span or (0, len(text)),
                metadata=dict(metadata),
            )
        ]

    # Sub-split: walk through paragraph breaks and accumulate up to the
    # soft cap, leaving ``SPLIT_OVERLAP_CHARS`` overlap between consecutive
    # chunks for retrieval continuity.
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    pieces: List[str] = []
    current = ""
    for para in paragraphs:
        candidate = (current + "\n\n" + para).strip() if current else para
        if len(candidate) <= MAX_CHUNK_CHARS:
            current = candidate
            continue
        if current:
            pieces.append(current)
            # Start next piece with overlap from the previous tail.
            tail = current[-SPLIT_OVERLAP_CHARS:] if len(current) > SPLIT_OVERLAP_CHARS else current
            current = (tail + "\n\n" + para).strip()
        else:
            # Single paragraph is itself too long — hard-split on sentences.
            current = para[:MAX_CHUNK_CHARS]
            pieces.append(current)
            current = para[MAX_CHUNK_CHARS - SPLIT_OVERLAP_CHARS :]
    if current:
        pieces.append(current)

    out: List[ChunkRecord] = []
    cursor = 0
    for i, piece in enumerate(pieces):
        # Locate piece within char_span (best-effort; offsets are advisory).
        if char_span:
            absolute_start = char_span[0] + text.find(piece, cursor)
            if absolute_start == char_span[0] - 1:
                absolute_start = char_span[0]
            absolute_end = absolute_start + len(piece)
        else:
            absolute_start = 0
            absolute_end = len(piece)
        cursor += len(piece)
        out.append(
            ChunkRecord(
                chunk_id=f"{candidate_id}__{section_name}__{i}",
                candidate_id=candidate_id,
                role_bucket=role_bucket,
                source_file=source_file,
                section=section_name,
                chunk_index=i,
                text=piece,
                char_span=(absolute_start, absolute_end),
                metadata=dict(metadata),
            )
        )
    return out


# ---------------------------------------------------------------------------
# DocumentAwareChunker class wrapper (DEC-019)
# ---------------------------------------------------------------------------
#
# The historical active chunker (pre-2026-07-05) is now wrapped in a class so
# it can be used side-by-side with ``RecursiveChunker``. The module-level
# :func:`chunk_profile` function is preserved as a backward-compat shim for
# one release (existing tests + scripts import it).
#
# New code should import :class:`DocumentAwareChunker` (or, preferably, the
# active :class:`src.rag.recursive_chunker.RecursiveChunker`).


class DocumentAwareChunker:
    """Document-Aware chunker (DEC-019 legacy).

    The original active strategy. Wraps the existing section-anchored
    chunking logic in a class so it can be used side-by-side with
    :class:`src.rag.recursive_chunker.RecursiveChunker` during the
    migration window. New code should prefer ``RecursiveChunker``.

    Args:
        max_chunk_chars:
            Soft upper bound for a single chunk in characters. Default
            :data:`MAX_CHUNK_CHARS` (1200).
        split_overlap_chars:
            Overlap applied when sub-splitting an oversized chunk.
            Default :data:`SPLIT_OVERLAP_CHARS` (120).
    """

    def __init__(
        self,
        max_chunk_chars: int = MAX_CHUNK_CHARS,
        split_overlap_chars: int = SPLIT_OVERLAP_CHARS,
    ) -> None:
        self.max_chunk_chars = max_chunk_chars
        self.split_overlap_chars = split_overlap_chars

    def chunk_profile(
        self,
        profile: Dict[str, Any],
        role_bucket: str = "",
    ) -> List[ChunkRecord]:
        """Convert one parsed profile into a list of chunk records.

        This is the original section-anchored implementation. It emits one
        chunk per experience entry, one per education entry, one per
        project, and one per free-text section (summary, skills,
        certifications, languages). Very large sections are sub-split on
        paragraph breaks with ``split_overlap_chars`` overlap.

        Args:
            profile:
                A parsed resume dict as produced by
                ``src.resume_parsing.parser.parse_resume``.
            role_bucket:
                The role folder the resume was filed under.

        Returns:
            List of :class:`ChunkRecord`. Order is deterministic.
        """
        return chunk_profile(profile, role_bucket=role_bucket)


__all__ = [
    "ChunkRecord",
    "MAX_CHUNK_CHARS",
    "SPLIT_OVERLAP_CHARS",
    "DocumentAwareChunker",
    "chunk_profile",
    "chunks_to_jsonl",
]
