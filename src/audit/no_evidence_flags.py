"""Audit flag writer for the composed RAG scorer + experience parser (Track 2, DEC-028 + Track 7, DEC-031).

This module writes the audit log at ``reports/audit/no_evidence_flags.jsonl``
and ``reports/audit/inferred_full_year_flags.jsonl``. It is the single writer
of those audit logs.

Two flag categories share the same JSONL writer pattern:

1. **No-evidence flags (Track 2-S / DEC-028)** — when
   ``retrieve_evidence_for_req`` from :mod:`src.rag.per_req_retrieval` returns
   zero chunks for a (candidate, REQ) pair, the rubric-bound LLM has nothing
   to read. Per the :file:`WORKING_LOGIC.md` RAG-grounding rule, the system
   must NOT speculate or fabricate evidence; the REQ must score 0 for the
   rubric portion (``Rubric_LLM_part``) and be flagged for human review so an
   operator can diagnose the cause (parser silent drop, hyper-aggressive
   ``theta``, chunker too small, etc.).

2. **Inferred-full-year flags (Track 7.2 / DEC-031)** — when the parser sees
   a single-year date string (e.g. ``"2020"`` alone, no ``-`` separator),
   :func:`src.rag.document_aware_chunker.parse_temporal_context` infers
   "the candidate worked here during 2020" and emits a 12-month credit
   ``calculated_duration_months`` with ``inferred_full_year: True``. The
   structured-profile extractor applies a guard against cert/education
   mis-bucketing before accepting the inference; the entries that pass the
   guard are surfaced as audit flags so a recruiter can verify the credit was
   warranted (resume gaming cost: max ≈ 1 year of false credit per single-year
   entry; recruiter-visible on the rendered resume).

Schema (one line per flag, both categories):

    {
      "flag_type": "no_evidence" / "inferred_full_year",
      "timestamp": "<ISO 8601 UTC>",
      "candidate_id": "cand_xxx",
      "role": "DataScience",
      ... (category-specific fields)
    }

No-evidence flag entry adds:

    {
      "req_id": "REQ-001",
      "requirement_name": "Python & Data Science Libraries ...",
      "sub_query_keys": ["SQ001", "SQ002", "SQ003", "SQ004"],
      "sub_query_count": 4,
      "theta": 0.30,
      "chunker": "Recursive(chunk_size=500, chunk_overlap=100)"
    }

Inferred-full-year flag entry adds:

    {
      "year": 2020,
      "dates_string": "2020",
      "employer": "Acme Corp",
      "role": "Senior Engineer",
      "inferred_months": 12,
      "guard_checks": {
          "has_real_company": true,
          "has_title_or_details": true,
          "title_is_section_name": false
      }
    }

The writer is intentionally stateless and file-lock-free: callers append one
line at a time and accept that two concurrent writers will interleave their
lines (JSONL parsers tolerate that as long as no single line is split —
``write`` on a single line is atomic on POSIX and Windows for lines < 4 KB).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

#: Default path for the no-evidence flags JSONL log. Per AGENTS.md the
#: ``reports/`` folder is committed to git, but the per-run audit logs
#: at ``reports/audit/`` are git-ignored (they are run-time artifacts).
DEFAULT_FLAGS_PATH: str = "reports/audit/no_evidence_flags.jsonl"

#: Default path for the inferred-full-year flags JSONL log. Symmetric
#: to ``DEFAULT_FLAGS_PATH``; the structural-profile extractor writes
#: one line per accepted inferred-full-year entry (Track 7.3 / DEC-031)
#: so the recruiter can audit the parser's "12-month credit for a
#: single-year date string" inference.
DEFAULT_INFERRED_FLAGS_PATH: str = "reports/audit/inferred_full_year_flags.jsonl"


def write_flag(
    candidate_id: str,
    role: str,
    req_id: str,
    requirement_name: str,
    sub_query_keys: List[str],
    theta: float,
    chunker: str = "Recursive",
    path: Union[str, Path] = DEFAULT_FLAGS_PATH,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Append one no-evidence flag entry to the audit JSONL log.

    Args:
        candidate_id: The candidate whose resume yielded zero evidence.
        role: The role bucket (e.g. ``"DataScience"``).
        req_id: The REQ identifier (e.g. ``"REQ-001"``).
        requirement_name: Human-readable requirement name.
        sub_query_keys: The sub-query keys that produced zero retrieval
            (e.g. ``["SQ001", "SQ002", "SQ003", "SQ004"]``).
        theta: The cosine threshold used for the retrieval attempt.
        chunker: Human-readable identifier of the chunker that produced
            the indexed chunks (default ``"Recursive"``).
        path: Path to the JSONL audit log. Parent dirs are created.
        extra: Optional flat dict of additional fields to merge into
            the JSON entry (e.g. ``{"mlflow_run_id": "abc123"}``).

    Returns:
        The dict that was written to the log line.
    """
    entry: Dict[str, Any] = {
        "flag_type": "no_evidence",
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "candidate_id": candidate_id,
        "role": role,
        "req_id": req_id,
        "requirement_name": requirement_name,
        "sub_query_keys": list(sub_query_keys),
        "sub_query_count": len(sub_query_keys),
        "theta": round(float(theta), 4) if theta is not None else None,
        "chunker": chunker,
    }
    if extra:
        for k, v in extra.items():
            if k not in entry:
                entry[k] = v

    flags_path = Path(path)
    try:
        flags_path.parent.mkdir(parents=True, exist_ok=True)
        with open(flags_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except OSError as e:
        # The audit log is best-effort: if we can't write it (e.g.
        # disk full), we log loudly but do not crash the scoring run.
        logger.error(
            "no_evidence_flags: failed to append entry for (%s, %s, %s): %s",
            candidate_id, req_id, path, e,
        )
    return entry


def write_inferred_full_year_flag(
    candidate_id: str,
    year: int,
    dates_string: str,
    employer: str,
    role_text: Optional[str],
    inferred_months: int = 12,
    path: Union[str, Path] = DEFAULT_INFERRED_FLAGS_PATH,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Append one inferred-full-year flag entry to the audit JSONL log.

    Track 7.2 / DEC-031: when ``parse_temporal_context`` sees a
    single-year date string (e.g. ``"2020"`` alone, no ``-`` separator),
    it infers "the candidate worked here during 2020" and emits 12
    months of credit. The structured-profile extractor applies a guard
    against cert/education mis-bucketing (no real company / no
    title-or-details / title-is-section-name) before accepting the
    inference. Entries that pass the guard are surfaced here so a
    recruiter can audit the inference — the resume's single-year dates
    are visible on the rendered PDF, so the gaming cost is
    recruiter-visible (max ≈ 1 year of false credit per entry).

    Args:
        candidate_id: The candidate whose resume produced this entry.
        year: The 4-digit year parsed from the date string.
        dates_string: The raw date string as it appeared on the resume
            (e.g. ``"2020"``; valuable for debugging parser bugs).
        employer: The employer / company name recorded by the parser.
        role_text: The job title / role recorded by the parser, if any.
        inferred_months: Defaults to 12 (single-year inference = full
            year of credit). Pass an override only for testing.
        path: Path to the JSONL audit log. Parent dirs are created.
        extra: Optional flat dict of additional fields to merge into
            the JSON entry.

    Returns:
        The dict that was written to the log line.
    """
    entry: Dict[str, Any] = {
        "flag_type": "inferred_full_year",
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "candidate_id": candidate_id,
        "year": int(year),
        "dates_string": str(dates_string),
        "employer": employer,
        "role": role_text,
        "inferred_months": int(inferred_months),
        "guard_checks": {
            "has_real_company": bool(employer) and not (
                len(employer) == 4 and employer.isdigit()
                and 1950 <= int(employer) <= 2100
            ),
            "has_title_or_details": bool(role_text),
            "title_is_section_name": bool(role_text) and any(
                tok and tok in {
                    "certifications", "certification", "education",
                    "projects", "project", "skills", "skill",
                    "languages", "language", "academic", "summary",
                }
                for tok in role_text.lower().replace("/", " ").split()
            ),
        },
    }
    if extra:
        for k, v in extra.items():
            if k not in entry:
                entry[k] = v

    flags_path = Path(path)
    try:
        flags_path.parent.mkdir(parents=True, exist_ok=True)
        with open(flags_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except OSError as e:
        logger.error(
            "inferred_full_year_flags: failed to append entry for "
            "(%s, %s, %s): %s",
            candidate_id, year, path, e,
        )
    return entry


def clear_flags(path: Union[str, Path] = DEFAULT_FLAGS_PATH) -> None:
    """Truncate the audit log. Used by tests to start each case cleanly.

    Production callers do NOT use this — the log is append-only by
    design. Exposed for the test suite.
    """
    flags_path = Path(path)
    if flags_path.exists():
        flags_path.unlink()
    else:
        flags_path.parent.mkdir(parents=True, exist_ok=True)


def read_flags(path: Union[str, Path] = DEFAULT_FLAGS_PATH) -> List[Dict[str, Any]]:
    """Read all entries from the audit log. Used by tests + the dashboard.

    Args:
        path: Path to the JSONL audit log.

    Returns:
        A list of dicts parsed from each JSONL line. Returns an empty
        list when the log does not exist.
    """
    flags_path = Path(path)
    if not flags_path.exists():
        return []
    out: List[Dict[str, Any]] = []
    with open(flags_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning(
                    "no_evidence_flags: skipping malformed line in %s: %s",
                    path, e,
                )
    return out


__all__ = [
    "DEFAULT_FLAGS_PATH",
    "DEFAULT_INFERRED_FLAGS_PATH",
    "write_flag",
    "write_inferred_full_year_flag",
    "clear_flags",
    "read_flags",
]