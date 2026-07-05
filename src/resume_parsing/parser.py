"""Parse structured information from resumes.

The parser produces two layers of output that together are RAG-ready:

1. **Structured profile** – name, contact, summary, experience entries,
   education entries, and list-style fields (skills, certifications, projects,
   languages).
2. **Evidence layer** – the full extracted ``raw_text`` plus per-section
   ``sections`` map with character offsets. Phase 6 (Resume Chat / RAG) uses
   the sections map to chunk resumes deterministically and to cite retrieved
   evidence.

Every profile carries a stable ``candidate_id`` allocated by the
:class:`src.resume_parsing.candidate_registry.CandidateRegistry` (DEC-025).
The id is human-readable, role-encoded, and sequential per role
(``BusinessAnalyst_CAND_0001``). The legacy SHA1-hash-based id is still
available via :func:`candidate_id_from_path` for the 6,377 existing
Document-Aware chunks; new candidates use the registry-allocated id.
"""

from hashlib import sha1
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

from .candidate_registry import CandidateRegistry, fresh_registry

# ``.ocr`` is the optional PDF→text bridge. It is missing in some
# environments (e.g. minimal CI); we import lazily so the rest of this
# module remains importable for testing the non-OCR paths (id allocation,
# text parsing helpers, etc.).
try:
    from .ocr import extract_text_hybrid  # type: ignore[import-not-found]
    _HAS_OCR = True
except ImportError:  # pragma: no cover - exercised by the env, not a test
    extract_text_hybrid = None  # type: ignore[assignment]
    _HAS_OCR = False

EMAIL_REGEX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_REGEX = re.compile(
    r"(?:(?:\+?\d{1,3}[\s\-\.])?(?:\(\d{2,4}\)[\s\-\.]?)?\d{2,4}[\s\-\.]{1,2}\d{2,4}[\s\-\.]{1,2}\d{2,4})"
)
DATE_RANGE_REGEX = re.compile(
    r"\b(?:\d{4}|Present|Current|Ongoing)(?:\s*(?:-|–|—|to)\s*(?:\d{4}|Present|Current|Ongoing))?\b",
    re.IGNORECASE,
)
SECTION_HEADERS = {
    "summary": ["summary", "professional summary", "profile", "about me"],
    "experience": ["experience", "work experience", "professional experience", "employment history"],
    "education": ["education", "academic background", "academic qualifications"],
    "skills": ["skills", "technical skills", "tools", "competencies"],
    "certifications": ["certifications", "certificates", "licenses"],
    "projects": ["projects", "selected projects", "project experience"],
    "languages": ["languages", "language skills"],
}


def parse_experience_date_line(line: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    match = DATE_RANGE_REGEX.search(line)
    if not match:
        return None, None, None
    dates = match.group().strip()
    before = line[: match.start()].strip(" -:=, ")
    after = line[match.end() :].strip(" -:=, ")
    company = before if before else None
    location = after if after else None
    return company, dates, location


def candidate_id_from_path(path: Path) -> str:
    """Legacy SHA1-hash-based identifier for a resume (DEC-025 superseded).

    Returns the pre-DEC-025 hash id (``cand_<12hex>``) for the given source
    path. Used by the 6,377 existing Document-Aware chunks and by the
    candidate-registry backfill script (``scripts/backfill_candidate_registry.py``).

    For new candidates, use the :class:`CandidateRegistry`-allocated id
    via :func:`parse_resume` instead. This function is preserved for one
    release as a backward-compat shim.

    The id is derived from the *absolute* source path so the same file
    maps to the same id across runs, even if the working directory
    changes.
    """
    digest = sha1(str(path.resolve()).encode("utf-8")).hexdigest()
    return f"cand_{digest[:12]}"


def _role_from_path(path: Path) -> Optional[str]:
    """Best-effort: extract the role folder name from a path under ``data/original/<role>/...``."""
    parts = path.resolve().parts
    for i, part in enumerate(parts):
        if part == "original" and i + 1 < len(parts):
            return parts[i + 1]
    return None


def parse_resume(
    path: Path,
    registry: Optional[CandidateRegistry] = None,
) -> Dict[str, Any]:
    """Parse a resume from a file path into a structured profile.

    The returned dictionary contains:

    * ``candidate_id`` – stable id for downstream joins. Allocated by
      the supplied ``registry`` (DEC-025); defaults to a fresh in-memory
      registry if not provided, which is appropriate for one-off
      scripts. Production code should pass
      :meth:`CandidateRegistry.load`.
    * ``source_file`` – absolute path to the original PDF/text file.
    * ``raw_text`` – full extracted text (preserved for retrieval & audit).
    * ``sections`` – mapping of section name -> ``{"text": ..., "start": int,
      "end": int}`` so chunkers can split deterministically.
    * Structured fields: ``name``, ``contact``, ``summary``, ``experience``
      (raw + entries), ``education`` (raw + entries), ``skills``,
      ``certifications``, ``projects``, ``languages``.
    """
    text = extract_text_from_path(path)
    profile = parse_resume_text(text)
    profile["source_file"] = str(path.resolve())

    # Allocate the candidate id via the registry (DEC-025). The role is
    # inferred from the path; if it can't be inferred, fall back to a
    # generic "Unknown" bucket so the id is still well-formed.
    role = _role_from_path(path) or "Unknown"
    legacy = candidate_id_from_path(path)
    if registry is None:
        registry = fresh_registry()
    profile["candidate_id"] = registry.allocate_or_lookup(
        source_path=path,
        role=role,
        legacy_hash_id=legacy,
    )
    return profile


def extract_text_from_path(path: Path) -> str:
    """Extract plain text from a supported resume file."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        if not _HAS_OCR:
            raise RuntimeError(
                "PDF extraction requires src.resume_parsing.ocr which is "
                "not installed in this environment."
            )
        return extract_text_hybrid(path)
    if suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="ignore")
    raise ValueError(f"Unsupported resume format: {path.suffix}")


def parse_resume_text(text: str) -> Dict[str, Any]:
    """Convert raw resume text into a structured profile with evidence.

    The returned profile contains:

    * ``raw_text`` – the full normalized text. Required for RAG retrieval so
      chunks can be traced back to source content.
    * ``sections`` – per-section ``{"text": str, "start": int, "end": int}``
      map. ``start``/``end`` are character offsets into ``raw_text`` so the
      chunker can compute deterministic spans and cite evidence.
    * Structured fields with empty-list / null-safe defaults so downstream
      scoring code never has to special-case missing data.
    """
    cleaned_text = normalize_text(text)
    lines = [line.strip() for line in cleaned_text.splitlines() if line.strip()]
    section_records = sectionize(lines, cleaned_text)

    # Plain-text map (name -> text) kept for backward compatibility with the
    # existing batch output shape.
    sections_text: Dict[str, str] = {
        name: record["text"] for name, record in section_records.items()
    }

    name, name_source = extract_name(lines, sections_text)
    contact = extract_contact(cleaned_text)
    summary_text = sections_text.get("summary") or extract_summary(lines)
    experience_text = sections_text.get("experience", "")
    education_text = sections_text.get("education", "")
    skills = extract_list_from_section(sections_text.get("skills"))
    certifications = extract_list_from_section(sections_text.get("certifications"))
    projects = extract_list_from_section(sections_text.get("projects"))
    languages = extract_list_from_section(sections_text.get("languages"))

    experience_entries = extract_experience_entries(experience_text)
    education_entries = extract_education_entries(education_text)

    return {
        "raw_text": cleaned_text,
        "sections": section_records,
        "name": {"value": name, "source": name_source},
        "contact": contact,
        "summary": {
            "value": summary_text,
            "source": "summary section" if summary_text and "summary" in section_records else "top of document",
        },
        "experience": {
            "raw": experience_text,
            "entries": experience_entries,
            "count": len(experience_entries),
        },
        "education": {
            "raw": education_text,
            "entries": education_entries,
            "count": len(education_entries),
        },
        "skills": skills,
        "certifications": certifications,
        "projects": projects,
        "languages": languages,
    }


def normalize_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"^\[--- Page \d+ ---\]\s*$", "", normalized, flags=re.MULTILINE)
    return normalized.strip()


def sectionize(lines: List[str], cleaned_text: str) -> Dict[str, Dict[str, Any]]:
    """Split text lines into logical sections based on common resume headings.

    Returns a mapping of section name to ``{"text": str, "start": int,
    "end": int}``. ``start`` and ``end`` are character offsets into the
    original ``cleaned_text``.

    Sections are detected only on lines that *are themselves* the heading
    (whole-line, anchored match — see :func:`identify_section_heading`). Each
    section spans from its first body line up to the **next heading line**,
    which guarantees non-overlapping sections regardless of OCR quirks that
    cause body anchors to repeat downstream.
    """
    section_positions: List[Tuple[int, str, int]] = []
    seen: set = set()
    for index, line in enumerate(lines):
        candidate = identify_section_heading(line)
        if candidate and candidate not in seen:
            seen.add(candidate)
            section_positions.append((index, candidate, 0))

    # Map each heading line to its absolute char offset in ``cleaned_text``.
    # This anchor is the boundary that closes the *previous* section.
    heading_offsets: Dict[int, int] = {}
    cursor = 0
    for idx, _, _ in section_positions:
        heading_text = lines[idx]
        offset = cleaned_text.find(heading_text, cursor)
        if offset == -1:
            offset = cleaned_text.find(heading_text)
        heading_offsets[idx] = offset if offset != -1 else 0
        cursor = offset if offset != -1 else cursor

    sections: Dict[str, Dict[str, Any]] = {}
    for i, (idx, name, _) in enumerate(section_positions):
        next_offset = (
            heading_offsets[section_positions[i + 1][0]]
            if i + 1 < len(section_positions)
            else len(cleaned_text)
        )
        body_lines = lines[idx + 1 :]
        body_text = "\n".join(body_lines).strip()
        if not body_text:
            continue
        first_anchor = body_lines[0] if body_lines else ""
        if not first_anchor:
            continue
        # Section starts at the heading position itself (so the chunk can
        # include the heading for context) and ends right before the next
        # heading — never overlapping.
        start = heading_offsets[idx]
        end = next_offset
        if start == -1 or end <= start:
            continue
        start = max(0, start)
        end = min(len(cleaned_text), end)
        sections[name] = {"text": body_text, "start": start, "end": end}
    return sections


def identify_section_heading(line: str) -> Optional[str]:
    """Return the section name if ``line`` *is* a heading (not just contains
    the keyword somewhere in a body sentence).

    Heuristics:

    * Strip common decorations (``:``, ``-``, ``=``, bullets, whitespace).
    * Match the cleaned line as a whole token against the configured
      ``SECTION_HEADERS`` set, OR a token-prefix match for headings like
      ``"Skills & Tools"`` -> ``"skills"``.
    * Reject lines that are obviously sentences (more than 5 words after
      cleaning).
    """
    if not line:
        return None
    cleaned = line.strip().strip(" :*-=#•·").strip()
    if not cleaned:
        return None
    words = cleaned.split()
    if len(words) > 5:
        return None
    lower_line = cleaned.lower()
    for section, tokens in SECTION_HEADERS.items():
        for token in tokens:
            token_words = token.split()
            # Exact match OR first-word match (e.g. "Skills & Tools" -> skills).
            if lower_line == token or lower_line.startswith(token + " ") or lower_line.startswith(token + "&"):
                return section
            if words and words[0].lower() == token:
                return section
    return None


# Phrases that frequently appear at the top of a resume but are NOT a name.
# Comparing lower-cased forms avoids brittle capitalization issues with OCR.
_NON_NAME_PHRASES = {
    "curriculum vitae",
    "resume",
    "resume / cv",
    "resume/cv",
    "date of birth",
    "nationality",
    "address",
    "email",
    "phone",
    "telephone",
    "contact",
    "personal details",
    "personal information",
    "profile",
    "about me",
    "professional summary",
    "summary",
    "objective",
    "career objective",
    "skills",
    "experience",
    "education",
    "references",
    # Single-word form labels commonly emitted by template-style resumes.
    "details",
    "personal",
    "information",
    "links",
    "location",
    "about",
    "overview",
    "highlights",
    "contact information",
    "contact details",
    "links & contact",
    "links and contact",
    "links/contact",
    "top skills",
    "core skills",
    "key skills",
}

# Tokens that strongly suggest a non-name line.
_NON_NAME_TOKENS = {
    "@",  # email
    "http://", "https://", "www.",
    "street", "st.", "st,", "road", "rd.", "avenue", "ave.", "city,",
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
    "male", "female", "single", "married", "dob:",
}


def _looks_like_name(candidate: str) -> bool:
    """Return True if ``candidate`` plausibly looks like a person's name."""
    if not candidate:
        return False
    stripped = candidate.strip().strip(":*#-= ")
    if not stripped:
        return False
    if len(stripped) > 80:
        return False
    lower = stripped.lower()
    if lower in _NON_NAME_PHRASES:
        return False
    # Common location strings that an OCR-fronted parser will occasionally
    # surface as a "candidate name" because each word is a capitalized
    # alpha-only token.
    _NON_NAME_LOCATION_PHRASES = {
        "new york", "new york, ny", "ny, ny",
        "united states", "united kingdom",
        "san francisco", "los angeles", "las vegas",
        "hong kong", "sao paulo", "kuala lumpur",
    }
    if lower in _NON_NAME_LOCATION_PHRASES:
        return False
    if any(token in lower for token in _NON_NAME_TOKENS):
        return False
    # Must contain at least one letter and no digits in the actual name body.
    if not re.search(r"[A-Za-z]", stripped):
        return False
    if re.search(r"\d", stripped):
        return False
    # Names almost always start with a capital letter; if every word is lower-
    # case it is most likely a heading that slipped through.
    words = [w for w in re.split(r"\s+", stripped) if w]
    if not words or len(words) > 6:
        return False
    if not any(w[0].isupper() for w in words):
        return False
    # Reject obvious phrase fragments like "Date of birth", "Email:" etc.
    if ":" in stripped:
        return False
    # Real names rarely contain commas, slashes, ampersands, pipes, or "@".
    # "Dallas, TX", "Senior Web Developer & jonn.doe", "Name / Title" all fail
    # this check.
    if any(ch in stripped for ch in (",", "&", "|", "/", "\\", "@", "#")):
        return False
    # Every word must be alpha-only (no punctuation inside).
    if not all(re.fullmatch(r"[A-Za-z][A-Za-z'\-]*", w) for w in words):
        return False
    # Length per word sanity check: real names have at least 2 chars per word
    # (handles initials poorly but avoids "TX", "NJ", etc. being accepted).
    if any(len(w) < 2 for w in words):
        return False
    return True


def extract_name(lines: List[str], sections: Dict[str, str]) -> Tuple[Optional[str], str]:
    """Pick the most plausible name from the resume.

    Some resumes put the name deep in the document (after contact + skills
    blocks). We therefore scan *all* lines rather than only the first 10,
    but require each candidate to pass :func:`_looks_like_name`.

    Returns ``(name, source)``. ``name`` is ``None`` when nothing qualifies —
    callers MUST handle the ``None`` case (it is more honest than fabricating
    a name).
    """
    # First, try the very top of the document.
    for line in lines[:10]:
        candidate = line.strip()
        if not candidate:
            continue
        if EMAIL_REGEX.search(candidate) or PHONE_REGEX.search(candidate):
            continue
        if identify_section_heading(candidate):
            continue
        if _looks_like_name(candidate):
            return candidate, "first non-contact line"
    # Fall back to scanning every line (some resumes put the name mid-page).
    for line in lines:
        candidate = line.strip()
        if not candidate:
            continue
        if EMAIL_REGEX.search(candidate) or PHONE_REGEX.search(candidate):
            continue
        if identify_section_heading(candidate):
            continue
        if _looks_like_name(candidate):
            return candidate, "found mid-document"
    return None, "not found"


def extract_contact(text: str) -> Dict[str, Any]:
    emails = EMAIL_REGEX.findall(text)
    phones = PHONE_REGEX.findall(text)
    return {"emails": list(dict.fromkeys(emails)), "phones": list(dict.fromkeys(phones))}


def extract_section_text(sections: Dict[str, str], name: str) -> str:
    return sections.get(name, "")


def extract_summary(lines: List[str]) -> str:
    for line in lines[:10]:
        if any(keyword in line.lower() for keyword in SECTION_HEADERS["summary"]):
            return line
    return ""


def extract_list_from_section(section_text: str) -> List[str]:
    if not section_text:
        return []
    items: List[str] = []
    for line in section_text.splitlines():
        normalized = line.strip("•*+- ")
        if not normalized:
            continue
        if "," in normalized:
            items.extend([item.strip() for item in normalized.split(",") if item.strip()])
        elif len(normalized.split()) <= 10:
            items.append(normalized)
    return items


def _entry_has_signal(entry: Dict[str, Any]) -> bool:
    """Return True if an experience/education entry actually carries data.

    Entries that are entirely ``None`` (or contain only empty details) used to
    pollute downstream retrieval by producing noise chunks that matched no
    semantic query. They are now dropped.
    """
    for key, value in entry.items():
        if key == "details":
            if value:  # non-empty list of bullet points
                return True
            continue
        if value:
            return True
    return False


def _looks_like_job_title(line: str) -> bool:
    """Return True if ``line`` plausibly contains a job title.

    Job titles are short, capitalized phrases like "Senior Data Scientist",
    "Marketing Manager", "Software Engineer Intern". They generally don't
    contain full sentences (commas followed by verbs), URLs, or long runs
    of lowercase prose.
    """
    if not line:
        return False
    stripped = line.strip().strip("•*+- ")
    if not stripped:
        return False
    if len(stripped) > 80:
        return False
    if stripped.endswith((".", "!", "?")):
        return False
    # Reject lines that look like prose: contain a comma followed by a lowercase
    # word (e.g. "Work directly with business users, ...") — those are bullet
    # content that escaped the bullet marker. A title like "Business Analyst,
    # Lexagon" is fine because the comma is followed by a Capitalized word.
    if re.search(r",\s+[a-z]", stripped):
        return False
    # No digits in titles (years etc. live on the dates line).
    if re.search(r"\d", stripped):
        return False
    words = [w for w in re.split(r"\s+", stripped) if w]
    if not words or len(words) > 10:
        return False
    # Most title words are capitalized; at least one word must start uppercase.
    if not any(w[0].isupper() for w in words):
        return False
    return True


def extract_experience_entries(section_text: str) -> List[Dict[str, Any]]:
    """Extract per-job experience entries.

    Each entry typically looks like::

        <title line, possibly "Title, Company">
        <dates line, e.g. "Jun 2019 — Present New York">
        - bullet
        - bullet
        ...

    The dates line **closes** the previous entry. If we see a dates line
    while a title is still pending, we attach it to the same entry instead
    of starting a new one (which would orphan the title).
    """
    if not section_text:
        return []
    lines = [line.strip() for line in section_text.splitlines() if line.strip()]
    entries: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {"title": None, "company": None, "dates": None, "location": None, "details": []}
    pending_title: Optional[str] = None

    def flush() -> None:
        if pending_title and current["title"] is None:
            current["title"] = pending_title
        if _entry_has_signal(current):
            entries.append(current)

    for line in lines:
        if DATE_RANGE_REGEX.search(line) and not line.lower().startswith("summary"):
            # Attach the pending title to the current entry (which is still
            # open because no dates arrived yet).
            if pending_title and current["title"] is None:
                current["title"] = pending_title
            elif pending_title and current["title"] is not None:
                current["details"].append(pending_title)
            company, dates, location = parse_experience_date_line(line)
            if current["dates"] is None and (current["title"] or current["details"]):
                # Attach dates to the *current* entry — the dates line is the
                # natural continuation of the title line above.
                current["company"] = company
                current["dates"] = dates
                current["location"] = location
                pending_title = None
                continue
            # Otherwise the dates line starts a new entry.
            flush()
            current = {"title": None, "company": None, "dates": None, "location": None, "details": []}
            current["company"] = company
            current["dates"] = dates
            current["location"] = location
            pending_title = None
            continue
        if line.startswith(("+", "-", "•", "*")):
            bullet = line.lstrip("+*-• ").strip()
            if bullet:
                current["details"].append(bullet)
            continue
        if _looks_like_job_title(line):
            # If a title is already set without dates, the previous line was
            # actually a detail and this is the real title.
            if pending_title and current["title"] is None:
                current["details"].append(pending_title)
            elif pending_title and current["title"] is not None:
                current["details"].append(pending_title)
            pending_title = line
        else:
            if pending_title:
                current["details"].append(pending_title)
                pending_title = None
            current["details"].append(line)
    flush()
    return entries


def extract_education_entries(section_text: str) -> List[Dict[str, Any]]:
    """Group consecutive non-blank lines into one education entry.

    OCR frequently renders a single education block across many short lines.
    We treat each contiguous paragraph (separated by blank lines) as one
    entry, and we further split on a date-bearing line because most resumes
    list multiple degrees and each degree has its own date range.
    """
    if not section_text:
        return []

    entries: List[Dict[str, Any]] = []
    current_lines: List[str] = []

    def flush_current() -> None:
        if not current_lines:
            return
        joined = " ".join(line.strip() for line in current_lines if line.strip())
        joined = " ".join(joined.split())  # collapse whitespace
        if joined:
            entries.append({"description": joined})
        current_lines.clear()

    for raw_line in section_text.splitlines():
        line = raw_line.strip()
        if not line:
            flush_current()
            continue
        # A new date-bearing line usually marks the start of a new degree.
        if current_lines and DATE_RANGE_REGEX.search(line):
            flush_current()
            current_lines.append(line)
            continue
        current_lines.append(line)
    flush_current()
    return entries
