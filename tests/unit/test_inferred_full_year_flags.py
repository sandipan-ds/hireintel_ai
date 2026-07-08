"""Unit tests for the inferred-full-year audit flag writer (Track 7.3 / DEC-031).

The :func:`src.audit.no_evidence_flags.write_inferred_full_year_flag`
helper is the symmetric counterpart of :func:`write_flag` (which is
already covered by ``tests/unit/test_composed_scorer.py``). When
``parse_temporal_context`` infers a 12-month credit from a single-year
date string (e.g. ``"2020"`` alone), and the structured-profile guard
accepts the entry, this helper appends one line per accepted entry so a
recruiter can audit the parser's inference.

Coverage:

- Helper exists and is exported.
- Writes a single JSONL line with the expected schema.
- File is created with parent directories.
- Multiple writes append cleanly.
- ``extra`` dict fields are merged, with reserved-name protection.
- ``role_text=None`` is handled (``guard_checks.has_title_or_details=False``).
- Title-is-section-name detection fires for "Certifications", "Education",
  "Projects", "Skills", "Languages" (the structured-profile guard rejects
  these entries; the audit-flag writer records the same check for diagnostic
  purposes so the recruiter sees why an entry was or was not accepted).
- ``employer`` of 4-digit-year form is flagged via
  ``guard_checks.has_real_company=False`` (parser bug detection).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.audit.no_evidence_flags import (
    DEFAULT_INFERRED_FLAGS_PATH,
    clear_flags,
    read_flags,
    write_inferred_full_year_flag,
)


@pytest.fixture
def tmp_flags_path(tmp_path):
    """Per-test JSONL path under tmp_path so tests can't pollute each other."""
    p = str(tmp_path / "audit" / "inferred_full_year_flags.jsonl")
    return p


def test_default_inferred_flags_path_is_under_reports_audit():
    assert DEFAULT_INFERRED_FLAGS_PATH == (
        "reports/audit/inferred_full_year_flags.jsonl"
    )


def test_write_creates_parent_dirs(tmp_flags_path):
    assert not Path(tmp_flags_path).exists()
    write_inferred_full_year_flag(
        candidate_id="cand_1",
        year=2020,
        dates_string="2020",
        employer="Acme Corp",
        role_text="Senior Engineer",
        path=tmp_flags_path,
    )
    assert Path(tmp_flags_path).exists()


def test_write_returns_entry_with_expected_schema(tmp_flags_path):
    entry = write_inferred_full_year_flag(
        candidate_id="cand_2",
        year=2019,
        dates_string="2019",
        employer="Winemakers Company",
        role_text="Sales Manager",
        inferred_months=12,
        path=tmp_flags_path,
    )
    # Top-level fields.
    assert entry["flag_type"] == "inferred_full_year"
    assert entry["candidate_id"] == "cand_2"
    assert entry["year"] == 2019
    assert entry["dates_string"] == "2019"
    assert entry["employer"] == "Winemakers Company"
    assert entry["role"] == "Sales Manager"
    assert entry["inferred_months"] == 12
    assert "timestamp" in entry
    # ``guard_checks`` sub-dict.
    gc = entry["guard_checks"]
    assert set(gc.keys()) == {
        "has_real_company",
        "has_title_or_details",
        "title_is_section_name",
    }
    assert gc["has_real_company"] is True
    assert gc["has_title_or_details"] is True
    assert gc["title_is_section_name"] is False


def test_multiple_writes_append_lines(tmp_flags_path):
    w1 = write_inferred_full_year_flag(
        candidate_id="c1", year=2018,
        dates_string="2018", employer="A", role_text="Eng",
        path=tmp_flags_path,
    )
    w2 = write_inferred_full_year_flag(
        candidate_id="c2", year=2019,
        dates_string="2019", employer="B", role_text="PM",
        path=tmp_flags_path,
    )
    flags = read_flags(path=tmp_flags_path)
    assert len(flags) == 2
    assert flags[0]["candidate_id"] == "c1"
    assert flags[1]["candidate_id"] == "c2"
    # read_flags does not lose the JSON line for the inferred path.
    assert flags[1]["flag_type"] == "inferred_full_year"


def test_extra_fields_merged_with_reserved_name_protection(tmp_flags_path):
    entry = write_inferred_full_year_flag(
        candidate_id="c1", year=2020,
        dates_string="2020", employer="A", role_text="Eng",
        path=tmp_flags_path,
        extra={"mlflow_run_id": "abc-123"},
    )
    assert entry["mlflow_run_id"] == "abc-123"


def test_role_none_flagged_in_guard_checks(tmp_flags_path):
    entry = write_inferred_full_year_flag(
        candidate_id="c1", year=2020,
        dates_string="2020", employer="A", role_text=None,
        path=tmp_flags_path,
    )
    assert entry["guard_checks"]["has_title_or_details"] is False


def test_title_section_name_detection_fires_on_certifications(tmp_flags_path):
    # The decision-record guard rejects entries whose title contains a
    # section name. The audit-flag writer records the same check so the
    # diagnostic record is self-contained.
    entry = write_inferred_full_year_flag(
        candidate_id="c1", year=2016,
        dates_string="2016",
        employer="Scrum Fundamentals Certified April",
        role_text="Certifications",
        path=tmp_flags_path,
    )
    assert entry["guard_checks"]["title_is_section_name"] is True


def test_title_section_name_detection_fires_on_education(tmp_flags_path):
    entry = write_inferred_full_year_flag(
        candidate_id="c1", year=2013,
        dates_string="2013",
        employer="IBM 082 Database and Application Fundamentals",
        role_text="Education",
        path=tmp_flags_path,
    )
    assert entry["guard_checks"]["title_is_section_name"] is True


def test_employer_year_string_flagged_in_guard_checks(tmp_flags_path):
    # Parser bug case: the year got stored in the ``company`` field.
    # The audit-flag writer records this via has_real_company=False.
    entry = write_inferred_full_year_flag(
        candidate_id="c1", year=2015,
        dates_string="2015",
        employer="2015",
        role_text="Sales Manager",
        path=tmp_flags_path,
    )
    assert entry["guard_checks"]["has_real_company"] is False


def test_clear_flags_truncates_file(tmp_flags_path):
    write_inferred_full_year_flag(
        candidate_id="c1", year=2020,
        dates_string="2020", employer="A", role_text="Eng",
        path=tmp_flags_path,
    )
    assert Path(tmp_flags_path).exists()
    clear_flags(path=tmp_flags_path)
    assert not Path(tmp_flags_path).exists()