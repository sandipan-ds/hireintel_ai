"""Structured Candidate Profile extraction — deterministic, no LLM, no retrieval.

Per ``WORKING_LOGIC.md`` ("Structured Candidate Profile Extraction"), facts
that are exact and unambiguous — a degree name, a certification title, total
years of experience — are read directly from the structured profile rather
than re-derived through search. Similarity search can miss or under-rank a
chunk containing an exact fact; a structured lookup cannot.

This module extracts:

* Degrees and institutions
* Certifications
* Total experience (years) — computed deterministically from parsed dates
* Companies and roles
* Employment dates

The output is stored as its own structured record, separate from the chunked
sections. Requirements that are purely factual (e.g. "Does the candidate hold
a Bachelor's degree?") may be answered entirely from this record, bypassing
Section-Routed Evidence Retrieval.

Requirements that require interpretation (e.g. "How deep is the candidate's
Power BI expertise?") still rely on Section-Routed Evidence Retrieval and
rubric-bound LLM evidence scoring.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.audit.no_evidence_flags import write_inferred_full_year_flag
from src.rag.document_aware_chunker import parse_temporal_context

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Regex patterns for degree and institution extraction.
# ---------------------------------------------------------------------------

# Common degree patterns — covers most Indian and international degrees.
_DEGREE_PATTERNS = [
    re.compile(
        r"\b(B\.?\s?Tech|B\.?\s?E|B\.?\s?Sc|Bachelor\s*(?:of|in)?|BBA|BCom|B\.?\s?Com|"
        r"B\.?\s?A|BS|BSc|MCA|BCA|Diploma|Associate)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(M\.?\s?Tech|M\.?\s?E|M\.?\s?Sc|Master\s*(?:of|in)?|MBA|M\.?\s?A|MS|MSc|"
        r"PhD|Ph\.?\s?D|Post\s*Graduate|Postgraduate|PG)\b",
        re.IGNORECASE,
    ),
]

# Institution indicators — lines that look like a university/college name.
_INSTITUTION_KEYWORDS = (
    "university", "institute", "college", "school", "academy",
    "polytechnic", "iit", "nit", "iim", "bits", "iiit",
)

# Certification keywords — ordered from most specific to least.
# "certified" and "certification" are generic and should be checked last.
_CERT_KEYWORDS = [
    "aws", "azure", "gcp", "google cloud", "pmp", "cissp", "cfa", "cpa",
    "tableau", "power bi", "scrum", "agile", "itil", "six sigma",
    "ccna", "ccnp", "ceh", "comptia", "oci", "microsoft",
    "certified", "certification", "certificate",
]


# ---------------------------------------------------------------------------
# Data classes for the structured profile.
# ---------------------------------------------------------------------------

@dataclass
class DegreeEntry:
    """One degree entry extracted from the education section.

    Attributes:
        degree: Degree name (e.g. "BTech", "MBA", "BS").
        field: Field of study if extractable (e.g. "Computer Science").
        institution: Institution name if extractable.
        year: Year or date range string if present.
    """

    degree: str = ""
    field: str = ""
    institution: str = ""
    year: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "degree": self.degree,
            "field": self.field,
            "institution": self.institution,
            "year": self.year,
        }


@dataclass
class CertificationEntry:
    """One certification entry.

    Attributes:
        name: Certification name.
        provider: Issuing organization if extractable.
    """

    name: str = ""
    provider: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "provider": self.provider}


@dataclass
class EmploymentEntry:
    """One employment entry from the experience section.

    Attributes:
        company: Company name.
        role: Job title / role.
        dates: Raw date range string.
        calculated_duration_months: Duration in months, computed in code.
        is_current: Whether this is the current role.
        inferred_full_year: True when the duration was inferred from a
            single-year date string alone (per Track 7.2 / DEC-031).
            The structured-profile extractor applies a guard against
            cert/education mis-bucketing before accepting the inference;
            when the guard rejects it, this flag is False and the duration
            is reset to 0. Callers (the audit log writer, the scorer)
            use this flag to decide whether to surface the entry for human
            review.
    """

    company: str = ""
    role: str = ""
    dates: str = ""
    calculated_duration_months: Optional[int] = None
    is_current: bool = False
    inferred_full_year: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "company": self.company,
            "role": self.role,
            "dates": self.dates,
            "calculated_duration_months": self.calculated_duration_months,
            "is_current": self.is_current,
            "inferred_full_year": self.inferred_full_year,
        }


@dataclass
class StructuredCandidateProfile:
    """Deterministic structured profile — separate from chunks, no LLM needed.

    This is the record that code-only scoring reads from: total experience,
    institute tier lookup, certification tier lookup, degree match.

    Attributes:
        candidate_id: Stable candidate identifier.
        degrees: List of extracted degree entries.
        certifications: List of extracted certification entries.
        total_experience_years: Total years of professional experience,
            computed deterministically from employment date ranges.
        companies: List of company names.
        roles: List of job titles.
        employment_history: List of employment entries with computed durations.
        flagged_institutes: List of institutes flagged as fake/unknown.
        has_flagged_institute: Whether any institute is flagged.
    """

    candidate_id: str = ""
    degrees: List[DegreeEntry] = field(default_factory=list)
    certifications: List[CertificationEntry] = field(default_factory=list)
    total_experience_years: float = 0.0
    companies: List[str] = field(default_factory=list)
    roles: List[str] = field(default_factory=list)
    employment_history: List[EmploymentEntry] = field(default_factory=list)
    flagged_institutes: List[str] = field(default_factory=list)
    has_flagged_institute: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "degrees": [d.to_dict() for d in self.degrees],
            "certifications": [c.to_dict() for c in self.certifications],
            "total_experience_years": self.total_experience_years,
            "companies": self.companies,
            "roles": self.roles,
            "employment_history": [e.to_dict() for e in self.employment_history],
            "flagged_institutes": self.flagged_institutes,
            "has_flagged_institute": self.has_flagged_institute,
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_structured_profile(profile: Dict[str, Any]) -> StructuredCandidateProfile:
    """Extract a deterministic structured profile from a parsed resume.

    This is the main entry point. It reads from the already-parsed profile
    dict (produced by ``src.resume_parsing.parser.parse_resume``) and
    produces a ``StructuredCandidateProfile`` record that code-only scoring
    can use without any LLM or retrieval.

    Args:
        profile: A parsed resume dict with ``experience``, ``education``,
            ``certifications``, ``skills``, and ``candidate_id`` fields.

    Returns:
        ``StructuredCandidateProfile`` with extracted degrees, certifications,
        employment history, and computed total experience.
    """
    candidate_id = profile.get("candidate_id", "")
    structured = StructuredCandidateProfile(candidate_id=candidate_id)

    # ---- Degrees and institutions from education entries ----
    education = profile.get("education") or {}
    for entry in education.get("entries") or []:
        text = entry.get("description") or ""
        degree_entry = _parse_degree_entry(text)
        if degree_entry.degree:
            structured.degrees.append(degree_entry)

    # ---- Check for flagged institutes (fake/unknown universities) ----
    from src.scoring.tier_lookup import is_institute_flagged
    for degree in structured.degrees:
        if degree.institution and is_institute_flagged(degree.institution):
            structured.flagged_institutes.append(degree.institution)
            structured.has_flagged_institute = True

    # ---- Certifications from the certifications list ----
    for cert_text in profile.get("certifications") or []:
        cert_entry = _parse_certification_entry(str(cert_text))
        structured.certifications.append(cert_entry)

    # ---- Employment history from experience entries ----
    # Track 7.2 / DEC-031: single-year date strings ("2020" alone) are
    # now inferred to mean "the candidate worked here during 2020" and
    # receive 12 months of credit from ``parse_temporal_context``. Apply
    # a guard here — the structured-profile extractor has the full entry
    # context (company, role, details) which the temporal parser does not.
    # When ``inferred_full_year`` is True but the entry fails the guard
    # (no real company + (role OR details), or the role string looks
    # like a section name rather than a job title —Certifications,
    # Education, Projects, Skills, Languages—), we reject the inference:
    # reset ``calculated_duration_months`` to 0 and ``inferred_full_year``
    # to False. The mis-bucketed records are typically certification /
    # education noise that the parser mis-attributed to the experience
    # section; accepting their inferred months would inflate total
    # experience years with parser-quality artifacts. The guard is the
    # human-in-the-loop safety net before audit-flag wiring in 7.3.
    _SECTION_NAME_TOKENS = {
        "certifications", "certification", "education",
        "projects", "project", "skills", "skill",
        "languages", "language", "academic", "summary",
    }
    experience = profile.get("experience") or {}
    for entry in experience.get("entries") or []:
        dates_str = entry.get("dates") or ""
        temporal_ctx = parse_temporal_context(dates_str)
        inferred_full_year = bool(temporal_ctx.get("inferred_full_year"))
        duration = temporal_ctx.get("calculated_duration_months")

        if inferred_full_year:
            # The entry was the parser's best guess from a single-year
            # date string. Apply the human-in-the-loop guard:
            #   1. There must be a real-looking ``company`` field that
            #      is not itself a 4-digit year (parser bug: sometimes
            #      puts the year in ``company``).
            #   2. There must be at least one of (``title`` |
            #      ``details``-non-empty) — a single-year date with no
            #      job-title text is almost always parser noise.
            #   3. The ``title`` must not be a section name (Certifications,
            #      Education, Projects, Skills, Languages — these are
            #      mis-bucketed entries from the resume's other sections).
            company = (entry.get("company") or "").strip()
            title = (entry.get("title") or "").strip()
            details = entry.get("details") or []
            title_is_section_name = any(
                tok and tok in _SECTION_NAME_TOKENS
                for tok in title.lower().replace("/", " ").split()
            )
            company_is_year = (
                len(company) == 4 and company.isdigit()
                and 1950 <= int(company) <= 2100
            )
            has_real_company = bool(company) and not company_is_year
            has_title_or_details = bool(title) or bool(details)
            if not has_real_company or not has_title_or_details or title_is_section_name:
                # Reject the inference — this is parser noise, not a
                # real single-year job. Reset to 0 months.
                inferred_full_year = False
                duration = 0

        emp_entry = EmploymentEntry(
            company=entry.get("company") or "",
            role=entry.get("title") or "",
            dates=dates_str,
            calculated_duration_months=duration,
            is_current=temporal_ctx.get("is_current", False),
            inferred_full_year=inferred_full_year,
        )
        structured.employment_history.append(emp_entry)
        if emp_entry.company:
            structured.companies.append(emp_entry.company)
        if emp_entry.role:
            structured.roles.append(emp_entry.role)

        # Track 7.3 / DEC-031: surface accepted inferred-full-year entries
        # to the audit log so a recruiter can verify the parser's 12-month
        # credit was warranted. The audit log is best-effort; failures are
        # logged but never crash the structured-extraction path.
        if inferred_full_year:
            try:
                year_int = int(dates_str.strip())
            except (TypeError, ValueError):
                year_int = 0
            write_inferred_full_year_flag(
                candidate_id=structured.candidate_id or "",
                year=year_int,
                dates_string=dates_str,
                employer=emp_entry.company,
                role_text=emp_entry.role or None,
                inferred_months=duration or 12,
            )

    # ---- Total experience years — computed deterministically ----
    structured.total_experience_years = _compute_total_experience_years(
        structured.employment_history
    )

    return structured


# ---------------------------------------------------------------------------
# Helpers — degree parsing
# ---------------------------------------------------------------------------

def _parse_degree_entry(text: str) -> DegreeEntry:
    """Parse a single education entry text into a DegreeEntry.

    Args:
        text: Raw education entry text, e.g.
            "BS in Computer Science, MIT, 2016-2020".

    Returns:
        ``DegreeEntry`` with extracted degree, field, institution, and year.
    """
    entry = DegreeEntry()

    # Extract degree.
    for pattern in _DEGREE_PATTERNS:
        match = pattern.search(text)
        if match:
            entry.degree = match.group().strip().replace(". ", ".").replace(" .", ".")
            # Normalize common variants: "B. Tech" → "BTech", "B. E" → "BE".
            entry.degree = re.sub(r"\.\s*", "", entry.degree)
            break

    # Extract field of study — text after "in" or "of" following the degree.
    if entry.degree:
        field_match = re.search(
            r"(?:in|of)\s+(.+?)(?:,|$)", text, re.IGNORECASE
        )
        if field_match:
            entry.field = field_match.group(1).strip()

    # Extract institution — look for institution keywords.
    for keyword in _INSTITUTION_KEYWORDS:
        pattern = re.compile(
            r"([A-Z][A-Za-z\s&.]*(?:" + keyword + r")[A-Za-z\s&.]*)",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if match:
            entry.institution = match.group().strip()
            break

    # Extract year/date.
    year_match = re.search(r"(\d{4}\s*[-–—]\s*\d{4}|\d{4})", text)
    if year_match:
        entry.year = year_match.group().strip()

    return entry


# ---------------------------------------------------------------------------
# Helpers — certification parsing
# ---------------------------------------------------------------------------

def _parse_certification_entry(text: str) -> CertificationEntry:
    """Parse a certification text into a CertificationEntry.

    Args:
        text: Raw certification text, e.g. "AWS Solutions Architect Associate".

    Returns:
        ``CertificationEntry`` with name and provider if extractable.
    """
    entry = CertificationEntry(name=text.strip())

    # Try to identify the provider from known keywords.
    text_lower = text.lower()
    for keyword in _CERT_KEYWORDS:
        if keyword in text_lower:
            # Map common keywords to provider names.
            provider_map = {
                "aws": "Amazon Web Services",
                "azure": "Microsoft",
                "gcp": "Google Cloud",
                "google cloud": "Google Cloud",
                "microsoft": "Microsoft",
                "pmp": "Project Management Institute",
                "cissp": "ISC2",
                "cfa": "CFA Institute",
                "cpa": "AICPA",
                "tableau": "Tableau",
                "power bi": "Microsoft",
                "scrum": "Scrum Alliance",
                "itil": "AXELOS",
                "ccna": "Cisco",
                "ccnp": "Cisco",
                "ceh": "EC-Council",
                "comptia": "CompTIA",
                "oci": "Oracle",
            }
            if keyword in provider_map:
                entry.provider = provider_map[keyword]
            break

    return entry


# ---------------------------------------------------------------------------
# Helpers — total experience computation
# ---------------------------------------------------------------------------

def _compute_total_experience_years(employment: List[EmploymentEntry]) -> float:
    """Compute total years of experience from employment entries.

    This sums the durations of all employment entries, but does NOT
    double-count overlapping periods. If two roles overlap (e.g. candidate
    worked at company A from 2018-2022 and company B from 2020-2023),
    the overlapping period (2020-2022) is counted only once.

    Per ``WORKING_LOGIC.md`` "Objective Candidate Evaluation" → Experience:
    "both shouldn't be added to get 12 years of experience" when the
    experiences overlap.

    Args:
        employment: List of employment entries with computed durations.

    Returns:
        Total years of experience (float), with no double-counting.
    """
    if not employment:
        return 0.0

    # Build a list of (start_month, end_month) intervals. Entries without
    # a valid duration are skipped.
    # When month is unknown, assume January for start dates and December
    # for end dates — this gives the correct full-year span and prevents
    # false overlaps between consecutive year-only ranges like
    # "2018-2020" and "2020-2023".
    intervals: List[tuple] = []
    for entry in employment:
        if entry.calculated_duration_months is None or entry.calculated_duration_months <= 0:
            continue
        ctx = parse_temporal_context(entry.dates)
        start = ctx.get("start_date")
        end = ctx.get("end_date")
        if start is None or start.get("year") is None:
            continue
        start_month = start["year"] * 12 + (start.get("month") or 1)
        if end and end.get("year"):
            end_month = end["year"] * 12 + (end.get("month") or 12)
        elif ctx.get("is_current"):
            from datetime import date
            end_month = date.today().year * 12 + date.today().month
        else:
            continue
        intervals.append((start_month, end_month))

    if not intervals:
        # Fallback: sum durations (may double-count, but better than 0).
        total_months = sum(
            e.calculated_duration_months for e in employment
            if e.calculated_duration_months and e.calculated_duration_months > 0
        )
        return round(total_months / 12.0, 1)

    # Merge overlapping intervals and sum the unique months.
    intervals.sort()
    merged: List[tuple] = [intervals[0]]
    for start, end in intervals[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))

    total_months = sum(end - start + 1 for start, end in merged)
    return round(total_months / 12.0, 1)
