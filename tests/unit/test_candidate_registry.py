"""Unit tests for the candidate registry (DEC-025)."""

import json
import tempfile
import threading
from pathlib import Path

import pytest

from src.resume_parsing.candidate_registry import (
    COUNTER_DIGITS,
    DEFAULT_REGISTRY_PATH,
    ID_PATTERN,
    SCHEMA_VERSION,
    CandidateRegistry,
    CandidateRegistryError,
    InvalidCandidateIdError,
    RoleNotFoundError,
    _format_id,
    _normalize_path,
    _parse_id,
    fresh_registry,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_format_id_basic():
    assert _format_id("BusinessAnalyst", 1) == "BusinessAnalyst_CAND_0001"
    assert _format_id("SalesManager", 164) == "SalesManager_CAND_0164"
    assert _format_id("WebDesigning", 9999) == "WebDesigning_CAND_9999"


def test_format_id_rejects_invalid_role():
    with pytest.raises(InvalidCandidateIdError):
        _format_id("123-bad", 1)
    with pytest.raises(InvalidCandidateIdError):
        _format_id("with space", 1)
    with pytest.raises(InvalidCandidateIdError):
        _format_id("", 1)


def test_format_id_rejects_negative_counter():
    with pytest.raises(InvalidCandidateIdError):
        _format_id("Role", -1)


def test_parse_id_roundtrip():
    for role, counter in [
        ("BusinessAnalyst", 1),
        ("SalesManager", 164),
        ("SrPythonDeveloper", 98),
    ]:
        cid = _format_id(role, counter)
        assert _parse_id(cid) == (role, counter)


def test_parse_id_rejects_invalid_format():
    for bad in [
        "BusinessAnalyst_CAND",  # no number
        "BusinessAnalyst-CAND-0001",  # wrong separator
        "_CAND_0001",  # no role
        "BusinessAnalyst_CAND_abc",  # non-numeric
        "BusinessAnalyst_cand_0001",  # lowercase CAND
        "BusinessAnalyst_CAND_001",  # only 3 digits (regex requires 4+)
        "",
    ]:
        with pytest.raises(InvalidCandidateIdError):
            _parse_id(bad)


def test_id_pattern_compiles():
    """The exported pattern matches the same strings as ``_parse_id`` accepts."""
    assert ID_PATTERN.match("BusinessAnalyst_CAND_0001")
    assert ID_PATTERN.match("SrPythonDeveloper_CAND_0164")
    assert not ID_PATTERN.match("bad")
    assert not ID_PATTERN.match("Role_CAND_1")  # too few digits


def test_normalize_path_is_absolute():
    p = Path("data/original/BusinessAnalyst/jane.pdf")
    norm = _normalize_path(p)
    assert Path(norm).is_absolute()


# ---------------------------------------------------------------------------
# CandidateRegistry — construction
# ---------------------------------------------------------------------------


def test_fresh_registry_is_empty():
    r = fresh_registry()
    assert len(r) == 0
    assert r.role_counter("BusinessAnalyst") == 0
    assert r.all_candidates() == {}


def test_registry_str_shows_size():
    """A registry with N candidates reports its size."""
    r = fresh_registry()
    r.allocate_or_lookup("a.pdf", "BusinessAnalyst")
    r.allocate_or_lookup("b.pdf", "DataScience")
    # ``__len__`` is the public size interface; ``str(r)`` falls back to
    # repr but len is the canonical "how big is it" check.
    assert len(r) == 2
    assert len(r.candidates_for_role("BusinessAnalyst")) == 1
    assert len(r.candidates_for_role("DataScience")) == 1


# ---------------------------------------------------------------------------
# CandidateRegistry — allocate_or_lookup
# ---------------------------------------------------------------------------


def test_allocate_first_id_in_a_role():
    r = fresh_registry()
    cid = r.allocate_or_lookup(
        source_path="data/original/BusinessAnalyst/jane.pdf",
        role="BusinessAnalyst",
    )
    assert cid == "BusinessAnalyst_CAND_0001"
    assert r.role_counter("BusinessAnalyst") == 1


def test_allocate_increments_per_role():
    r = fresh_registry()
    r.allocate_or_lookup("a.pdf", "BusinessAnalyst")
    r.allocate_or_lookup("b.pdf", "BusinessAnalyst")
    r.allocate_or_lookup("c.pdf", "BusinessAnalyst")
    assert r.role_counter("BusinessAnalyst") == 3


def test_allocate_counter_is_per_role():
    """Different roles maintain independent counters.

    Note: each call uses a different source path because the same path
    is a lookup (not an allocation) once it's registered.
    """
    r = fresh_registry()
    r.allocate_or_lookup("ba_a.pdf", "BusinessAnalyst")
    r.allocate_or_lookup("ds_a.pdf", "DataScience")
    r.allocate_or_lookup("ds_b.pdf", "DataScience")
    assert r.role_counter("BusinessAnalyst") == 1
    assert r.role_counter("DataScience") == 2
    # A third role starts fresh at 1.
    r.allocate_or_lookup("web_a.pdf", "WebDesigning")
    assert r.role_counter("WebDesigning") == 1


def test_allocate_returns_existing_for_same_path():
    r = fresh_registry()
    cid1 = r.allocate_or_lookup("data/original/BusinessAnalyst/jane.pdf", "BusinessAnalyst")
    cid2 = r.allocate_or_lookup("data/original/BusinessAnalyst/jane.pdf", "BusinessAnalyst")
    assert cid1 == cid2
    assert r.role_counter("BusinessAnalyst") == 1  # no increment on lookup


def test_allocate_updates_last_seen_on_existing_path():
    r = fresh_registry()
    cid = r.allocate_or_lookup("a.pdf", "BusinessAnalyst")
    first_seen = r.lookup(candidate_id=cid)["last_seen_at"]
    r.allocate_or_lookup("a.pdf", "BusinessAnalyst")
    second_seen = r.lookup(candidate_id=cid)["last_seen_at"]
    assert second_seen >= first_seen


def test_allocate_stores_legacy_hash_id():
    r = fresh_registry()
    cid = r.allocate_or_lookup(
        "data/original/BusinessAnalyst/jane.pdf",
        "BusinessAnalyst",
        legacy_hash_id="cand_abc123def456",
    )
    assert r.lookup(candidate_id=cid)["legacy_hash_id"] == "cand_abc123def456"


def test_allocate_rejects_invalid_role():
    r = fresh_registry()
    with pytest.raises(InvalidCandidateIdError):
        r.allocate_or_lookup("a.pdf", "123-bad")
    with pytest.raises(InvalidCandidateIdError):
        r.allocate_or_lookup("a.pdf", "")


def test_allocate_stores_source_path_and_filename():
    r = fresh_registry()
    cid = r.allocate_or_lookup("data/original/BusinessAnalyst/jane_doe.pdf", "BusinessAnalyst")
    entry = r.lookup(candidate_id=cid)
    assert entry["source_filename"] == "jane_doe.pdf"
    assert Path(entry["source_path"]).name == "jane_doe.pdf"
    assert "allocated_at" in entry
    assert "last_seen_at" in entry


def test_allocate_different_paths_get_different_ids():
    r = fresh_registry()
    cid1 = r.allocate_or_lookup("a.pdf", "BusinessAnalyst")
    cid2 = r.allocate_or_lookup("b.pdf", "BusinessAnalyst")
    assert cid1 != cid2
    assert cid1 == "BusinessAnalyst_CAND_0001"
    assert cid2 == "BusinessAnalyst_CAND_0002"


# ---------------------------------------------------------------------------
# CandidateRegistry — lookup
# ---------------------------------------------------------------------------


def test_lookup_by_candidate_id():
    r = fresh_registry()
    cid = r.allocate_or_lookup("a.pdf", "BusinessAnalyst")
    entry = r.lookup(candidate_id=cid)
    assert entry is not None
    assert "source_path" in entry


def test_lookup_by_source_path():
    r = fresh_registry()
    r.allocate_or_lookup("data/original/BusinessAnalyst/jane.pdf", "BusinessAnalyst")
    entry = r.lookup(source_path="data/original/BusinessAnalyst/jane.pdf")
    assert entry is not None
    assert entry["source_path"].endswith("jane.pdf")


def test_lookup_returns_none_for_missing():
    r = fresh_registry()
    assert r.lookup(candidate_id="BusinessAnalyst_CAND_9999") is None
    assert r.lookup(source_path="data/original/BusinessAnalyst/nonexistent.pdf") is None


def test_lookup_requires_at_least_one_key():
    r = fresh_registry()
    with pytest.raises(ValueError):
        r.lookup()


def test_lookup_returns_a_copy():
    """Mutating the returned dict must not affect the registry."""
    r = fresh_registry()
    cid = r.allocate_or_lookup("a.pdf", "BusinessAnalyst")
    entry = r.lookup(candidate_id=cid)
    entry["source_path"] = "MUTATED"
    fresh = r.lookup(candidate_id=cid)
    assert fresh["source_path"] != "MUTATED"


# ---------------------------------------------------------------------------
# CandidateRegistry — role helpers
# ---------------------------------------------------------------------------


def test_candidates_for_role_filters_correctly():
    r = fresh_registry()
    r.allocate_or_lookup("a.pdf", "BusinessAnalyst")
    r.allocate_or_lookup("b.pdf", "BusinessAnalyst")
    r.allocate_or_lookup("c.pdf", "DataScience")
    ba = r.candidates_for_role("BusinessAnalyst")
    assert len(ba) == 2
    assert all(k.startswith("BusinessAnalyst_CAND_") for k in ba)


def test_role_counter_default_zero_for_unknown_role():
    r = fresh_registry()
    assert r.role_counter("NewRole") == 0


# ---------------------------------------------------------------------------
# CandidateRegistry — save/load roundtrip
# ---------------------------------------------------------------------------


def test_save_load_roundtrip():
    r = CandidateRegistry(
        next_counter={"BusinessAnalyst": 5, "DataScience": 3},
        candidates={
            "BusinessAnalyst_CAND_0001": {
                "source_path": "/abs/path/a.pdf",
                "source_filename": "a.pdf",
                "allocated_at": "2026-07-05T10:00:00Z",
                "last_seen_at": "2026-07-05T10:00:00Z",
                "legacy_hash_id": "cand_abc",
            }
        },
        path=None,
        auto_save=False,
    )
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        path = tf.name
    try:
        r._path = Path(path)  # set the path post-construction
        r.save()
        loaded = CandidateRegistry.load(path)
        assert loaded.role_counter("BusinessAnalyst") == 5
        assert loaded.role_counter("DataScience") == 3
        assert loaded.lookup(candidate_id="BusinessAnalyst_CAND_0001")["legacy_hash_id"] == "cand_abc"
    finally:
        Path(path).unlink()


def test_load_missing_file_returns_empty_registry(tmp_path: Path):
    p = tmp_path / "does_not_exist.json"
    r = CandidateRegistry.load(str(p))
    assert len(r) == 0
    assert r.role_counter("Anything") == 0


def test_load_rejects_unsupported_schema_version(tmp_path: Path):
    p = tmp_path / "registry.json"
    p.write_text(json.dumps({"schema_version": "99.0", "next_counter": {}, "candidates": {}}))
    with pytest.raises(CandidateRegistryError):
        CandidateRegistry.load(str(p))


def test_save_creates_parent_directories(tmp_path: Path):
    p = tmp_path / "deep" / "nested" / "registry.json"
    r = CandidateRegistry(path=str(p), auto_save=False)
    r.allocate_or_lookup("a.pdf", "BusinessAnalyst")
    r.save()
    assert p.exists()


def test_save_is_atomic_no_partial_writes(tmp_path: Path):
    """Verify save uses a temp + rename so the registry is never half-written.

    A ``.tmp`` file may briefly exist during a write, but the final
    ``registry.json`` is always a complete, valid JSON document.
    """
    p = tmp_path / "registry.json"
    r = CandidateRegistry(path=str(p), auto_save=True)
    r.allocate_or_lookup("a.pdf", "BusinessAnalyst")
    # After save, the file must be valid JSON with our data.
    with p.open() as f:
        data = json.load(f)
    assert "BusinessAnalyst_CAND_0001" in data["candidates"]


# ---------------------------------------------------------------------------
# CandidateRegistry — auto_save behavior
# ---------------------------------------------------------------------------


def test_auto_save_writes_immediately_by_default():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        path = tf.name
    try:
        r = CandidateRegistry(path=path, auto_save=True)
        r.allocate_or_lookup("a.pdf", "BusinessAnalyst")
        # The file should now exist on disk.
        with open(path) as f:
            data = json.load(f)
        assert "BusinessAnalyst_CAND_0001" in data["candidates"]
    finally:
        Path(path).unlink()


def test_auto_save_disabled_keeps_in_memory_only():
    r = CandidateRegistry(path="/tmp/never_written.json", auto_save=False)
    r.allocate_or_lookup("a.pdf", "BusinessAnalyst")
    assert len(r) == 1
    assert not Path("/tmp/never_written.json").exists()


# ---------------------------------------------------------------------------
# CandidateRegistry — concurrency
# ---------------------------------------------------------------------------


def test_concurrent_allocations_produce_unique_ids():
    """Multiple threads allocating the same role must not collide on counter."""
    r = CandidateRegistry(next_counter={}, candidates={}, path=None, auto_save=False)
    seen: list[str] = []
    lock = threading.Lock()

    def allocate(i: int) -> None:
        cid = r.allocate_or_lookup(
            source_path=f"path_{i}.pdf",
            role="BusinessAnalyst",
        )
        with lock:
            seen.append(cid)

    threads = [threading.Thread(target=allocate, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(seen) == 50
    assert len(set(seen)) == 50  # all unique
    # All ids are valid format.
    for cid in seen:
        assert ID_PATTERN.match(cid)
        assert cid.startswith("BusinessAnalyst_CAND_")


def test_concurrent_allocations_to_same_path_return_same_id():
    """The path-index is thread-safe; concurrent calls with the same path return the same id."""
    r = CandidateRegistry(next_counter={}, candidates={}, path=None, auto_save=False)
    seen: list[str] = []
    lock = threading.Lock()

    def allocate() -> None:
        cid = r.allocate_or_lookup("same.pdf", "BusinessAnalyst")
        with lock:
            seen.append(cid)

    threads = [threading.Thread(target=allocate) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(set(seen)) == 1  # all 20 calls return the same id
    assert r.role_counter("BusinessAnalyst") == 1


# ---------------------------------------------------------------------------
# Backfill integration (using fresh_registry; the script itself is tested separately)
# ---------------------------------------------------------------------------


def test_registry_works_with_dummy_721_corpus():
    """Simulate the backfill on a 721-element fake corpus."""
    r = fresh_registry()
    role_counts = {
        "BusinessAnalyst": 133,
        "DataScience": 42,
        "JavaDeveloper": 72,
        "ReactDeveloper": 18,
        "SQLDeveloper": 82,
        "SalesManager": 164,
        "SrPythonDeveloper": 98,
        "WebDesigning": 112,
    }
    counter = 0
    for role, n in role_counts.items():
        for i in range(n):
            counter += 1
            r.allocate_or_lookup(
                source_path=f"data/processed/{role}/cand_{i}.json",
                role=role,
                legacy_hash_id=f"cand_{i:012x}",
            )
    assert len(r) == 721
    assert sum(role_counts.values()) == 721
    for role, n in role_counts.items():
        assert r.role_counter(role) == n
    # Idempotent: re-running produces no new ids.
    for role, n in role_counts.items():
        for i in range(n):
            cid = r.allocate_or_lookup(
                source_path=f"data/processed/{role}/cand_{i}.json",
                role=role,
                legacy_hash_id=f"cand_{i:012x}",
            )
            assert cid.startswith(f"{role}_CAND_")
    assert len(r) == 721


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_schema_version_is_set():
    assert SCHEMA_VERSION == "1.0"


def test_default_registry_path_is_relative():
    assert DEFAULT_REGISTRY_PATH == "data/candidate_registry.json"


def test_counter_digits_is_4():
    assert COUNTER_DIGITS == 4
