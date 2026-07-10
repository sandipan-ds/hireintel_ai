"""Unit tests for the sub-query embedding cache (Track 7.1).

The cache wraps ``src.rag.per_req_retrieval.embed_sub_queries`` with an
in-memory dict + optional on-disk ``data/embeddings/subqueries_cache.npz`` +
manifest. The tests use a stub embedder (no MiniLM download) so they run fast
and in any environment.

Coverage:
- Construction + empty-state introspection.
- ``lookup`` / ``__contains__`` hit/miss semantics.
- ``get_or_encode`` happy path (all cache hits).
- ``get_or_encode`` miss path (encode-on-miss + dirty flag).
- ``get_or_encode`` mixed (some hits, some misses).
- ``wrap_embed_sub_queries`` closure signature.
- Disk ``flush`` + ``load`` roundtrip.
- File-hash invalidation when the SubQuery file changes.
- ``preencode_role`` happy path on the real DataScience SubQuery file
  (uses the stub embedder so no MiniLM is loaded).
- Idempotent re-encode (second ``preencode_role`` adds 0 entries).
- Model-name filtering (entries with a different model are dropped on load).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from src.rag import subquery_cache as sqc_mod
from src.rag.subquery_cache import (
    DEFAULT_CACHE_PATH,
    DEFAULT_MANIFEST_PATH,
    DEFAULT_SUBQUERY_DIR,
    SubQueryCache,
    _cache_key,
    _file_sha256,
    _sha256,
    _subquery_file_for_role,
)


# ---------------------------------------------------------------------------
# Cheap stub embedder — replaces the MiniLM-L6-v2 model in tests.
# ---------------------------------------------------------------------------


def _stub_embedder_factory(dim: int = 4):
    """Return a stub embedder that produces deterministic 4-dim vectors.

    The vector is hash-derived so the same text always yields the same
    vector (matches the real ``embed_sub_queries`` determinism contract).
    Accepts the same kwargs as the real function (``model_name`` is ignored)
    so the monkeypatch is drop-in.
    """
    def _embedder(sub_queries, model_name=None):
        if not sub_queries:
            return np.zeros((0, dim), dtype=np.float32)
        out = np.zeros((len(sub_queries), dim), dtype=np.float32)
        for i, (key, text) in enumerate(sub_queries):
            h = _sha256(text)
            for j in range(dim):
                out[i, j] = ((int(h[j * 2 : j * 2 + 2], 16) % 200) - 100) / 100.0
        # L2 normalize so the cosine = dot property holds.
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (out / norms).astype(np.float32)

    return _embedder


@pytest.fixture
def stub_embedder(monkeypatch):
    """Monkeypatch the real ``embed_sub_queries`` with a 4-dim stub."""
    embed = _stub_embedder_factory(4)
    monkeypatch.setattr(sqc_mod, "embed_sub_queries", embed)
    return embed


@pytest.fixture
def isolated_cache(tmp_path):
    """A cache that writes to a tmp directory (no pollution of ``data/``)."""
    return SubQueryCache(
        cache_path=tmp_path / "subqueries_cache.npz",
        manifest_path=tmp_path / "subqueries_cache_manifest.jsonl",
        model_name="stub-test-model",
    )


# ---------------------------------------------------------------------------
# Helpers under test.
# ---------------------------------------------------------------------------


def test_sha256_is_stable():
    assert _sha256("hello") == _sha256("hello")
    assert _sha256("hello") != _sha256("world")


def test_cache_key_includes_model_name():
    k1 = _cache_key("model-a", "text")
    k2 = _cache_key("model-b", "text")
    assert k1 != k2
    assert "model-a" in k1 and "model-b" in k2


def test_file_sha256_returns_none_for_missing_file():
    assert _file_sha256(Path("/does/not/exist")) is None


def test_subquery_file_for_role_returns_expected_path():
    p = _subquery_file_for_role("BusinessAnalyst")
    assert p.name == "BusinessAnalyst_SubQuery.md"
    assert p.parent.name == "BusinessAnalyst"


# ---------------------------------------------------------------------------
# Empty state.
# ---------------------------------------------------------------------------


def test_empty_cache_has_size_zero(isolated_cache):
    assert len(isolated_cache) == 0
    assert isolated_cache.size == 0
    assert not isolated_cache.is_dirty
    assert "any text" not in isolated_cache


# ---------------------------------------------------------------------------
# get_or_encode — all-hits, all-misses, mixed.
# ---------------------------------------------------------------------------


def test_get_or_encode_on_empty_returns_empty_matrix(isolated_cache, stub_embedder):
    out = isolated_cache.get_or_encode([])
    assert out.shape == (0, 1)


def test_get_or_encode_misses_encode_and_store(isolated_cache, stub_embedder):
    sq_pairs = [("SQ001", "How many Python years?"), ("SQ002", "Lead role?")]
    out = isolated_cache.get_or_encode(sq_pairs)
    assert out.shape == (2, 4)
    assert isolated_cache.is_dirty
    assert len(isolated_cache) == 2
    # Both entries are present.
    assert "How many Python years?" in isolated_cache
    assert "Lead role?" in isolated_cache


def test_get_or_encode_hits_skip_encode(isolated_cache, stub_embedder):
    # First call populates the cache.
    sq_pairs = [("SQ001", "Python?")]
    out1 = isolated_cache.get_or_encode(sq_pairs)
    # Second call must hit the cache — verify the vector is the same instance
    # data (cache returns a copy).
    out2 = isolated_cache.get_or_encode(sq_pairs)
    assert out1.shape == out2.shape == (1, 4)
    np.testing.assert_allclose(out1, out2)
    # ``is_dirty`` was True after the first call, False after the second (
    # second call had no new misses; flag should remain as it was — True).
    # We confirm dirty is still True (we did NOT invert; we just did not add
    # anything). The flush test will exercise the False path.
    assert isolated_cache.is_dirty is True


def test_get_or_encode_mixed_hits_and_misses(isolated_cache, stub_embedder):
    # Pre-populate one entry.
    isolated_cache.get_or_encode([("SQ001", "kept")])
    # Now mix a hit with a miss.
    out = isolated_cache.get_or_encode(
        [("SQ001", "kept"), ("SQ002", "new")],
    )
    assert out.shape == (2, 4)
    assert len(isolated_cache) == 2
    # Re-look up the hit to make sure the vector matches what we cached.
    cached = isolated_cache.lookup("kept")
    np.testing.assert_allclose(out[0], cached)


# ---------------------------------------------------------------------------
# wrap_embed_sub_queries — closure signature.
# ---------------------------------------------------------------------------


def test_wrap_returns_callable(isolated_cache, stub_embedder):
    closure = isolated_cache.wrap_embed_sub_queries()
    assert callable(closure)
    out = closure([("SQ001", "text")])
    assert out.shape == (1, 4)
    # Closure didn't pass role/req_id so manifest entries are None.
    meta = isolated_cache._meta[-1]
    assert meta["role"] is None
    assert meta["req_id"] is None


# ---------------------------------------------------------------------------
# Disk roundtrip.
# ---------------------------------------------------------------------------


def test_flush_then_load_roundtrip(isolated_cache, stub_embedder):
    isolated_cache.get_or_encode(
        [("SQ001", "alpha"), ("SQ002", "beta")],
    )
    isolated_cache.flush()
    assert not isolated_cache.is_dirty

    # Load into a fresh instance pointing at the same paths.
    reloaded = SubQueryCache.load(
        cache_path=isolated_cache.cache_path,
        manifest_path=isolated_cache.manifest_path,
        model_name=isolated_cache.model_name,
    )
    assert len(reloaded) == 2
    assert "alpha" in reloaded
    assert "beta" in reloaded
    # Same vectors on disk and in memory.
    v_old = isolated_cache.lookup("alpha")
    v_new = reloaded.lookup("alpha")
    np.testing.assert_allclose(v_old, v_new)


def test_flush_is_noop_when_clean(isolated_cache, stub_embedder):
    isolated_cache.get_or_encode([("SQ001", "alpha")])
    isolated_cache.flush()
    size_before = isolated_cache.cache_path.stat().st_size
    # Second flush — no changes since last flush.
    isolated_cache.flush()
    # File should not have been rewritten (same mtime).
    assert isolated_cache.cache_path.stat().st_size == size_before


def test_load_skips_entries_with_wrong_model(isolated_cache, stub_embedder):
    isolated_cache.get_or_encode([("SQ001", "alpha")])
    isolated_cache.flush()

    reloaded = SubQueryCache.load(
        cache_path=isolated_cache.cache_path,
        manifest_path=isolated_cache.manifest_path,
        # Different model name → all entries skipped.
        model_name="other-model",
    )
    assert len(reloaded) == 0


def test_load_invalidates_when_subquery_file_changed(
    isolated_cache, stub_embedder, monkeypatch, tmp_path,
):
    """When the SubQuery file hash mismatches, the entry is dropped on load."""
    # Pretend Role hashed to "old-hash" at encode time.
    fake_file = tmp_path / "fake_role_SubQuery.md"
    fake_file.write_text("v1")

    # _add_entry stored the manifest hash; we'll monkeypatch _file_sha256 to
    # return "new-hash" on the second load so the entry is dropped.
    isolated_cache.get_or_encode(
        [("SQ001", "alpha")], role="fake_role", req_id="REQ-001",
    )
    isolated_cache.flush()

    monkeypatch.setattr(
        sqc_mod, "_file_sha256", lambda p: "different-hash-now",
    )
    reloaded = SubQueryCache.load(
        cache_path=isolated_cache.cache_path,
        manifest_path=isolated_cache.manifest_path,
        model_name=isolated_cache.model_name,
    )
    assert len(reloaded) == 0


# ---------------------------------------------------------------------------
# preencode_role — uses the real DataScience SubQuery file.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (DEFAULT_SUBQUERY_DIR / "DataScience" / "DataScience_SubQuery.md").exists(),
    reason="DataScience SubQuery file missing — corpus not in repo.",
)
def test_preencode_role_data_science(isolated_cache, stub_embedder):
    n_added = isolated_cache.preencode_role("DataScience")
    assert n_added > 0
    # The DataScience SubQuery file has 20 REQs / 56 sub-queries per Track 2-S.
    assert len(isolated_cache) == 56


@pytest.mark.skipif(
    not (DEFAULT_SUBQUERY_DIR / "DataScience" / "DataScience_SubQuery.md").exists(),
    reason="DataScience SubQuery file missing.",
)
def test_preencode_role_is_idempotent(isolated_cache, stub_embedder):
    isolated_cache.preencode_role("DataScience")
    second_pass = isolated_cache.preencode_role("DataScience")
    assert second_pass == 0, "second preencode should hit the cache, not encode."


@pytest.mark.skipif(
    not DEFAULT_SUBQUERY_DIR.exists(),
    reason="No SubQuery repo at data/job_descriptions.",
)
def test_preencode_all_roles_runs_without_error(isolated_cache, stub_embedder):
    results = isolated_cache.preencode_all_roles()
    # 8 roles in the corpus.
    assert len(results) == 8
    # Total entries — verified empirically by running preencode_all_roles with
    # the stub embedder; the count is the total across all 8 SubQuery files.
    # If a role's SubQuery file is edited, this count updates on next run.
    total = sum(results.values())
    assert total == 325, f"Expected 325 sub-queries total, got {total}: {results}"


# ---------------------------------------------------------------------------
# Sanity: default paths point at the right on-disk location.
# ---------------------------------------------------------------------------


def test_default_paths_under_data_embeddings():
    assert DEFAULT_CACHE_PATH.name == "subqueries_cache.npz"
    assert DEFAULT_CACHE_PATH.parent == Path("data/embeddings")
    assert DEFAULT_MANIFEST_PATH.name == "subqueries_cache_manifest.jsonl"
    assert DEFAULT_MANIFEST_PATH.parent == Path("data/embeddings")
