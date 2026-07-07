"""Unit tests for the threshold-based retriever (DEC-018)."""

import logging
import os
import tempfile

import numpy as np
import pytest

from src.rag import (
    DEFAULT_MAX_CHUNKS_PER_QUERY,
    DEFAULT_THRESHOLD,
    IndexedChunk,
    ScoredChunk,
    ThresholdRetriever,
    VectorIndex,
    load_default_retriever,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def toy_index() -> VectorIndex:
    """A 5-chunk index where one chunk is an exact match for the query.

    Two chunks belong to cand_001, two to cand_002, one to cand_003.
    The "exact match" vector is normalized; the rest are random noise.
    """
    rng = np.random.default_rng(seed=0)
    dim = 32
    target = rng.standard_normal(dim).astype(np.float32)
    target = target / np.linalg.norm(target)

    def noise() -> np.ndarray:
        v = rng.standard_normal(dim).astype(np.float32)
        return v / np.linalg.norm(v)

    chunks = [
        IndexedChunk(chunk_id="c0", vector=target, text="exact match", metadata={"candidate_id": "cand_001"}),
        IndexedChunk(chunk_id="c1", vector=noise(), text="noise 1", metadata={"candidate_id": "cand_001"}),
        IndexedChunk(chunk_id="c2", vector=noise(), text="noise 2", metadata={"candidate_id": "cand_002"}),
        IndexedChunk(chunk_id="c3", vector=noise(), text="noise 3", metadata={"candidate_id": "cand_002"}),
        IndexedChunk(chunk_id="c4", vector=noise(), text="noise 4", metadata={"candidate_id": "cand_003"}),
    ]
    return VectorIndex(chunks)


@pytest.fixture
def query_vector() -> np.ndarray:
    """A unit-norm 32-D vector."""
    rng = np.random.default_rng(seed=1)
    v = rng.standard_normal(32).astype(np.float32)
    return v / np.linalg.norm(v)


# ---------------------------------------------------------------------------
# VectorIndex
# ---------------------------------------------------------------------------


def test_index_dim_and_length(toy_index):
    assert len(toy_index) == 5
    assert toy_index.dim == 32


def test_index_chunk_ids_and_texts(toy_index):
    assert toy_index.chunk_ids == ["c0", "c1", "c2", "c3", "c4"]
    assert toy_index.texts == ["exact match", "noise 1", "noise 2", "noise 3", "noise 4"]


def test_empty_index_has_zero_dim():
    idx = VectorIndex()
    assert len(idx) == 0
    assert idx.dim == 0
    assert idx.cosine(np.zeros(4, dtype=np.float32)).size == 0


def test_cosine_returns_per_chunk_scores(toy_index, query_vector):
    sims = toy_index.cosine(query_vector)
    assert sims.shape == (5,)
    assert sims.dtype == np.float32
    # All scores in [-1, 1].
    assert np.all(sims >= -1.0) and np.all(sims <= 1.0)


def test_cosine_with_matching_vector_is_one(toy_index):
    # c0's vector is unit-norm. Querying with the same vector returns cosine=1.
    sims = toy_index.cosine(toy_index._matrix[0])
    assert sims[0] == pytest.approx(1.0, abs=1e-5)


def test_cosine_raises_on_dim_mismatch(toy_index):
    with pytest.raises(ValueError):
        toy_index.cosine(np.zeros(8, dtype=np.float32))


def test_save_and_load_roundtrip(toy_index):
    with tempfile.NamedTemporaryFile(suffix=".npz", delete=False) as tf:
        path = tf.name
    try:
        toy_index.save_npz(path)
        assert os.path.getsize(path) > 0
        loaded = VectorIndex.load_npz(path)
        assert len(loaded) == len(toy_index)
        assert loaded.dim == toy_index.dim
        assert loaded.chunk_ids == toy_index.chunk_ids
        assert loaded.texts == toy_index.texts
        # Cosine on the same query should match.
        rng = np.random.default_rng(seed=2)
        q = rng.standard_normal(32).astype(np.float32)
        np.testing.assert_allclose(loaded.cosine(q), toy_index.cosine(q), atol=1e-6)
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# ThresholdRetriever — construction
# ---------------------------------------------------------------------------


def test_default_threshold_matches_owner_spec_2026_07_06():
    """Default threshold = 0.25 (slightly below midpoint of [0.10, 0.50]).

    DEC-018 originally shipped 0.70; the owner refined the Optuna search
    space to [0.10, 0.50] on 2026-07-06. On 2026-07-07 the default was
    lowered from 0.30 to 0.25 to surface more date-bearing chunks per REQ
    during smoke testing (mitigating the failure mode where the date line
    landed in a chunk that did not pass the higher theta).
    """
    r = ThresholdRetriever(VectorIndex())
    assert r.threshold == DEFAULT_THRESHOLD
    assert DEFAULT_THRESHOLD == 0.25
    assert r.max_chunks_per_query == DEFAULT_MAX_CHUNKS_PER_QUERY
    assert DEFAULT_MAX_CHUNKS_PER_QUERY == 20


def test_invalid_threshold_raises():
    with pytest.raises(ValueError):
        ThresholdRetriever(VectorIndex(), threshold=-1.1)
    with pytest.raises(ValueError):
        ThresholdRetriever(VectorIndex(), threshold=1.1)


def test_invalid_cap_raises():
    with pytest.raises(ValueError):
        ThresholdRetriever(VectorIndex(), max_chunks_per_query=0)


# ---------------------------------------------------------------------------
# ThresholdRetriever — retrieval
# ---------------------------------------------------------------------------


def test_retrieve_returns_empty_when_threshold_excludes_all(toy_index, query_vector):
    r = ThresholdRetriever(toy_index, threshold=0.99, max_chunks_per_query=20)
    # query_vector is a random unit-norm vector; cosine with random chunks is ~0.
    hits = r.retrieve_scored(query_vector)
    # Could be empty or non-empty depending on the seed; the test asserts behavior
    # at threshold=1.0 is always empty.
    r_strict = ThresholdRetriever(toy_index, threshold=1.0, max_chunks_per_query=20)
    assert r_strict.retrieve_scored(query_vector) == []


def test_retrieve_finds_exact_match(toy_index):
    """Querying with c0's vector returns c0 with cosine=1.0."""
    target_v = toy_index._matrix[0].copy()
    r = ThresholdRetriever(toy_index, threshold=0.5, max_chunks_per_query=20)
    hits = r.retrieve_scored(target_v)
    assert len(hits) >= 1
    assert hits[0].chunk_id == "c0"
    assert hits[0].cosine == pytest.approx(1.0, abs=1e-5)
    assert isinstance(hits[0], ScoredChunk)


def test_retrieve_sorts_by_similarity_descending(toy_index):
    """When multiple chunks meet the threshold, they're returned cosine-desc."""
    target_v = toy_index._matrix[0].copy()
    r = ThresholdRetriever(toy_index, threshold=-1.0, max_chunks_per_query=20)
    hits = r.retrieve_scored(target_v)
    cosines = [h.cosine for h in hits]
    assert cosines == sorted(cosines, reverse=True)


def test_candidate_id_filter(toy_index):
    target_v = toy_index._matrix[0].copy()
    r = ThresholdRetriever(toy_index, threshold=-1.0, max_chunks_per_query=20)
    hits_c1 = r.retrieve_scored(target_v, candidate_id="cand_001")
    assert all(h.metadata["candidate_id"] == "cand_001" for h in hits_c1)
    # c0 (cand_001) is in the result; c2/c3 (cand_002) and c4 (cand_003) are not.
    chunk_ids = {h.chunk_id for h in hits_c1}
    assert "c0" in chunk_ids
    assert "c1" in chunk_ids
    assert "c2" not in chunk_ids
    assert "c3" not in chunk_ids
    assert "c4" not in chunk_ids


def test_candidate_id_filter_excludes_even_at_threshold_minus_one(toy_index):
    """Regression: the candidate_id filter must hold even at threshold=-1.0.

    Earlier the implementation set masked scores to -1.0, which still
    passed the ``>= -1.0`` threshold. The fix is to use -inf.
    """
    target_v = toy_index._matrix[0].copy()
    r = ThresholdRetriever(toy_index, threshold=-1.0, max_chunks_per_query=20)
    hits = r.retrieve_scored(target_v, candidate_id="cand_002")
    assert all(h.metadata["candidate_id"] == "cand_002" for h in hits)
    # Only c2 and c3 belong to cand_002.
    assert {h.chunk_id for h in hits} <= {"c2", "c3"}


def test_cap_is_enforced(toy_index, caplog):
    target_v = toy_index._matrix[0].copy()
    r = ThresholdRetriever(toy_index, threshold=-1.0, max_chunks_per_query=2)
    with caplog.at_level(logging.WARNING, logger="src.rag.retriever"):
        hits = r.retrieve_scored(target_v)
    assert len(hits) == 2
    assert any("cap hit" in rec.message.lower() for rec in caplog.records)


def test_retrieve_no_cap_hit_returns_all_above_threshold(toy_index, caplog):
    """When the cap is not hit, no warning is logged."""
    target_v = toy_index._matrix[0].copy()
    r = ThresholdRetriever(toy_index, threshold=-1.0, max_chunks_per_query=20)
    with caplog.at_level(logging.WARNING, logger="src.rag.retriever"):
        hits = r.retrieve_scored(target_v)
    assert not any("cap hit" in rec.message.lower() for rec in caplog.records)
    assert len(hits) == 5  # all 5 chunks pass threshold=-1.0


def test_retrieve_convenience_returns_tuples(toy_index):
    """The ``retrieve`` convenience method returns ``(chunk_id, text)`` tuples."""
    target_v = toy_index._matrix[0].copy()
    r = ThresholdRetriever(toy_index, threshold=0.5, max_chunks_per_query=20)
    out = r.retrieve(target_v)
    assert all(isinstance(t, tuple) and len(t) == 2 for t in out)
    for chunk_id, text in out:
        assert isinstance(chunk_id, str)
        assert isinstance(text, str)


# ---------------------------------------------------------------------------
# load_default_retriever
# ---------------------------------------------------------------------------


def test_load_default_retriever_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_default_retriever(index_path=str(tmp_path / "does_not_exist.npz"))


def test_load_default_retriever_happy_path(tmp_path):
    # Build a small index on disk and load it back.
    idx = VectorIndex(
        [
            IndexedChunk(
                chunk_id="c0",
                vector=np.ones(8, dtype=np.float32) / np.sqrt(8),
                text="hello",
                metadata={"candidate_id": "cand_x"},
            )
        ]
    )
    path = tmp_path / "idx.npz"
    idx.save_npz(str(path))

    r = load_default_retriever(
        index_path=str(path),
        threshold=0.5,
        max_chunks_per_query=5,
    )
    assert r.threshold == 0.5
    assert r.max_chunks_per_query == 5
    assert len(r.index) == 1
