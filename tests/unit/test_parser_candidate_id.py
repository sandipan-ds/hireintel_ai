"""Unit tests for the parser's candidate-id integration (DEC-025)."""

from pathlib import Path

import pytest

from src.resume_parsing.candidate_registry import (
    CandidateRegistry,
    fresh_registry,
)
from src.resume_parsing.parser import (
    _role_from_path,
    candidate_id_from_path,
    parse_resume,
)


# ---------------------------------------------------------------------------
# _role_from_path
# ---------------------------------------------------------------------------


def test_role_from_path_extracts_role_folder():
    p = Path("data/original/BusinessAnalyst/jane.pdf")
    assert _role_from_path(p) == "BusinessAnalyst"


def test_role_from_path_handles_absolute_paths():
    p = Path("/Users/sandi/data/original/SalesManager/jane.pdf")
    assert _role_from_path(p) == "SalesManager"


def test_role_from_path_returns_none_for_paths_outside_data_original():
    assert _role_from_path(Path("/tmp/random.pdf")) is None
    assert _role_from_path(Path("docs/some_file.md")) is None


# ---------------------------------------------------------------------------
# candidate_id_from_path (legacy)
# ---------------------------------------------------------------------------


def test_legacy_candidate_id_from_path_is_stable():
    """The legacy hash-based id is stable across runs and paths."""
    p = Path("data/original/BusinessAnalyst/jane.pdf")
    cid1 = candidate_id_from_path(p)
    cid2 = candidate_id_from_path(p)
    assert cid1 == cid2
    assert cid1.startswith("cand_")
    # 12 hex chars after the prefix.
    assert len(cid1) == len("cand_") + 12


def test_legacy_candidate_id_format():
    p = Path("data/original/BusinessAnalyst/jane.pdf")
    cid = candidate_id_from_path(p)
    assert cid.startswith("cand_")
    hex_part = cid[len("cand_"):]
    assert len(hex_part) == 12
    int(hex_part, 16)  # must be valid hex


# ---------------------------------------------------------------------------
# parse_resume — id allocation integration
# ---------------------------------------------------------------------------


def test_parse_resume_allocates_id_via_registry(tmp_path: Path):
    """A .txt file is parsed; the id is allocated via the registry."""
    txt = tmp_path / "data" / "original" / "BusinessAnalyst" / "jane.txt"
    txt.parent.mkdir(parents=True)
    txt.write_text(
        "Experienced analyst with 10 years of experience.\n"
        "Worked at Acme and Beta.",
        encoding="utf-8",
    )

    registry = fresh_registry()
    profile = parse_resume(txt, registry=registry)

    # Profile has the new id format.
    assert profile["candidate_id"] == "BusinessAnalyst_CAND_0001"
    # Registry has the entry with the legacy id.
    entry = registry.lookup(candidate_id=profile["candidate_id"])
    assert entry is not None
    assert entry["legacy_hash_id"] == candidate_id_from_path(txt)
    # Source file is set.
    assert profile["source_file"] == str(txt.resolve())


def test_parse_resume_uses_existing_id_for_seen_path(tmp_path: Path):
    """Re-parsing the same file returns the same id (no new allocation)."""
    txt = tmp_path / "data" / "original" / "BusinessAnalyst" / "jane.txt"
    txt.parent.mkdir(parents=True)
    txt.write_text("Senior analyst", encoding="utf-8")

    registry = fresh_registry()
    profile1 = parse_resume(txt, registry=registry)
    profile2 = parse_resume(txt, registry=registry)

    assert profile1["candidate_id"] == profile2["candidate_id"]
    assert registry.role_counter("BusinessAnalyst") == 1


def test_parse_resume_allocates_distinct_ids_per_role(tmp_path: Path):
    """Two files in two roles get ids in the right buckets."""
    base = tmp_path / "data" / "original"
    (base / "BusinessAnalyst").mkdir(parents=True)
    (base / "DataScience").mkdir(parents=True)
    (base / "BusinessAnalyst" / "a.txt").write_text("Analyst", encoding="utf-8")
    (base / "DataScience" / "b.txt").write_text("Scientist", encoding="utf-8")

    registry = fresh_registry()
    p1 = parse_resume(base / "BusinessAnalyst" / "a.txt", registry=registry)
    p2 = parse_resume(base / "DataScience" / "b.txt", registry=registry)

    assert p1["candidate_id"] == "BusinessAnalyst_CAND_0001"
    assert p2["candidate_id"] == "DataScience_CAND_0001"
    assert registry.role_counter("BusinessAnalyst") == 1
    assert registry.role_counter("DataScience") == 1


def test_parse_resume_falls_back_to_unknown_role_for_paths_outside_data_original(
    tmp_path: Path,
):
    """A file outside ``data/original/<role>/`` still gets a valid id, in the ``Unknown`` bucket."""
    txt = tmp_path / "scratch.txt"
    txt.write_text("Some content", encoding="utf-8")

    registry = fresh_registry()
    profile = parse_resume(txt, registry=registry)
    assert profile["candidate_id"] == "Unknown_CAND_0001"


def test_parse_resume_creates_fresh_registry_if_none_provided(tmp_path: Path):
    """When called without a registry, parse_resume creates an in-memory one."""
    txt = tmp_path / "data" / "original" / "BusinessAnalyst" / "jane.txt"
    txt.parent.mkdir(parents=True)
    txt.write_text("Content", encoding="utf-8")

    # No registry passed.
    profile = parse_resume(txt)
    # The id is still in the new format.
    assert profile["candidate_id"].startswith("BusinessAnalyst_CAND_")


# ---------------------------------------------------------------------------
# Cross-version compatibility
# ---------------------------------------------------------------------------


def test_legacy_id_does_not_collide_with_new_id():
    """A path's hash id (``cand_abc``) and new id (``BusinessAnalyst_CAND_0001``) live in different namespaces.

    The registry stores both via ``legacy_hash_id`` and ``candidate_id``;
    they never collide.
    """
    p = Path("data/original/BusinessAnalyst/jane.pdf")
    legacy = candidate_id_from_path(p)
    assert not legacy.startswith("BusinessAnalyst_CAND_")
    assert legacy.startswith("cand_")
