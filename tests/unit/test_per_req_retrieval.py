"""Unit tests for per-REQ retrieval (the regular-RAG evidence path, M0.5a Step 3).

These tests exercise :func:`src.rag.per_req_retrieval.retrieve_evidence_for_req`
without loading the real sentence-transformers model — sub-query vectors are
supplied directly via the ``sub_query_vectors`` argument.

Covered behaviors:
  - union across the REQ's sub-query set, deduped by ``chunk_id``
  - highest similarity wins when the same chunk is hit by multiple sub-queries
  - ``candidate_id`` filter is applied (per-candidate scoring, not pool search)
  - zero-retrieval result returns ``[]`` (caller raises the no-evidence flag)
  - threshold floor filters out sub-threshold chunks
  - the union cap kicks in when many sub-queries each retrieve many chunks
  - empty sub-query set returns ``[]``
"""

from __future__ import annotations

import numpy as np
import pytest

from src.rag.per_req_retrieval import retrieve_evidence_for_req
from src.rag.retriever import IndexedChunk, ThresholdRetriever, VectorIndex


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def small_index() -> VectorIndex:
    """A 6-chunk index across 2 candidates (3 chunks each).

    Chunks for cand_001 are deliberately aligned so that:
      - c0 is an exact vector match for sq_vec_A
      - c1 is an exact vector match for sq_vec_B
      - c2 is noise (never meets threshold for any sub-query)
    Chunks for cand_002 mirror the pattern, so we can verify candidate filtering.
    """
    rng = np.random.default_rng(seed=42)
    dim = 16

    def unit(v):
        n = np.linalg.norm(v)
        return v / n if n > 0 else v

    vec_a = unit(rng.standard_normal(dim).astype(np.float32))
    vec_b = unit(rng.standard_normal(dim).astype(np.float32))
    noise1 = unit(rng.standard_normal(dim).astype(np.float32))
    noise2 = unit(rng.standard_normal(dim).astype(np.float32))
    noise3 = unit(rng.standard_normal(dim).astype(np.float32))
    noise4 = unit(rng.standard_normal(dim).astype(np.float32))

    chunks = [
        # cand_001 — 3 chunks
        IndexedChunk(chunk_id="cand_001__0", vector=vec_a, text="A-match", metadata={"candidate_id": "cand_001"}),
        IndexedChunk(chunk_id="cand_001__1", vector=vec_b, text="B-match", metadata={"candidate_id": "cand_001"}),
        IndexedChunk(chunk_id="cand_001__2", vector=noise1, text="noise", metadata={"candidate_id": "cand_001"}),
        # cand_002 — 3 chunks
        IndexedChunk(chunk_id="cand_002__0", vector=vec_a, text="A-match", metadata={"candidate_id": "cand_002"}),
        IndexedChunk(chunk_id="cand_002__1", vector=vec_b, text="B-match", metadata={"candidate_id": "cand_002"}),
        IndexedChunk(chunk_id="cand_002__2", vector=noise2, text="noise", metadata={"candidate_id": "cand_002"}),
    ]
    return VectorIndex(chunks)


@pytest.fixture
def sq_vec_a(small_index) -> np.ndarray:
    """A vector that exactly matches cand_001's chunk c0 (cosine = 1.0)."""
    # small_index's c0 is vec_a, so retrieving with that vector gives cosine=1.0
    return small_index._matrix[0].copy()


@pytest.fixture
def sq_vec_b(small_index) -> np.ndarray:
    """A vector that exactly matches cand_001's chunk c1 (cosine = 1.0)."""
    return small_index._matrix[1].copy()


@pytest.fixture
def sq_vec_noise() -> np.ndarray:
    """A vector that matches nothing above a high threshold."""
    rng = np.random.default_rng(seed=99)
    dim = 16
    v = rng.standard_normal(dim).astype(np.float32)
    return v / np.linalg.norm(v)


# ---------------------------------------------------------------------------
# retrieve_evidence_for_req
# ---------------------------------------------------------------------------


def test_empty_sub_queries_returns_empty(small_index):
    retriever = ThresholdRetriever(small_index, threshold=0.30)
    out = retrieve_evidence_for_req(retriever, "cand_001", sub_queries=[], sub_query_vectors=np.zeros((0, 16)))
    assert out == []


def test_single_sub_query_returns_matching_chunks(small_index, sq_vec_a):
    """One sub-query: returns the chunks for that candidate that meet threshold.

    sq_vec_a matches chunk c0 at cosine=1.0 and c2 (noise) at a much lower
    cosine (~0.31). With threshold=0.50, only c0 passes — c2 is dropped.
    """
    retriever = ThresholdRetriever(small_index, threshold=0.50)
    sub_queries = [("SQ001", "Does the candidate know Python?")]
    sq_vectors = np.array([sq_vec_a])  # matches chunk c0 with cosine=1.0
    out = retrieve_evidence_for_req(
        retriever, "cand_001",
        sub_queries=sub_queries,
        sub_query_vectors=sq_vectors,
    )
    chunk_ids = {h.chunk_id for h in out}
    assert "cand_001__0" in chunk_ids
    assert "cand_001__2" not in chunk_ids  # noise c2 below threshold
    c0_hit = next(h for h in out if h.chunk_id == "cand_001__0")
    assert c0_hit.cosine == pytest.approx(1.0, abs=1e-5)


def test_candidate_id_filter_excludes_other_candidates(small_index, sq_vec_a, sq_vec_b):
    """Retrieving for cand_001 must NOT return chunks from cand_002,
    even when those chunks have cosine=1.0 with a sub-query.
    """
    retriever = ThresholdRetriever(small_index, threshold=0.30)
    sub_queries = [("SQ001", "Q1"), ("SQ002", "Q2")]
    sq_vectors = np.array([sq_vec_a, sq_vec_b])  # both A and B matches
    out = retrieve_evidence_for_req(retriever, "cand_001", sub_queries, sub_query_vectors=sq_vectors)
    chunk_ids = {h.chunk_id for h in out}
    # Only cand_001 chunks
    assert all(cid.startswith("cand_001__") for cid in chunk_ids)
    assert "cand_002__0" not in chunk_ids
    assert "cand_002__1" not in chunk_ids


def test_union_dedups_by_chunk_id(small_index, sq_vec_a):
    """Two sub-queries that both match the SAME chunk: output has the chunk once."""
    retriever = ThresholdRetriever(small_index, threshold=0.30)
    sub_queries = [("SQ001", "Q1"), ("SQ002", "Q2")]
    # Both sub-query vectors point at chunk c0
    sq_vectors = np.array([sq_vec_a, sq_vec_a])
    out = retrieve_evidence_for_req(retriever, "cand_001", sub_queries, sub_query_vectors=sq_vectors)
    chunk_ids = [h.chunk_id for h in out]
    assert chunk_ids.count("cand_001__0") == 1  # deduped


def test_union_keeps_highest_similarity(small_index, sq_vec_a):
    """When two sub-queries hit the same chunk, the highest cosine wins."""
    retriever = ThresholdRetriever(small_index, threshold=0.10)
    # sq_vec_a matches chunk c0 with cosine=1.0; a slightly perturbed version
    # matches the same chunk at a lower cosine (~0.95). Both sub-queries point
    # at the same chunk; the output's cosine should be the max (1.0).
    slightly_off = sq_vec_a + 0.01 * np.ones_like(sq_vec_a)
    slightly_off = slightly_off / np.linalg.norm(slightly_off)
    sub_queries = [("SQ001", "Q1"), ("SQ002", "Q2")]
    sq_vectors = np.array([sq_vec_a, slightly_off])
    out = retrieve_evidence_for_req(retriever, "cand_001", sub_queries, sub_query_vectors=sq_vectors)
    hits_for_c0 = [h for h in out if h.chunk_id == "cand_001__0"]
    assert len(hits_for_c0) == 1
    assert hits_for_c0[0].cosine == pytest.approx(1.0, abs=1e-4)


def test_threshold_filter_drops_low_score_chunks(small_index, sq_vec_a):
    """A chunk below threshold is dropped, even if it's the only one hit."""
    # sq_vec_a matches c0 at 1.0 and c2 at a low cosine.
    retriever = ThresholdRetriever(small_index, threshold=0.99)  # very high
    sub_queries = [("SQ001", "Q1")]
    sq_vectors = np.array([sq_vec_a])
    out = retrieve_evidence_for_req(retriever, "cand_001", sub_queries, sub_query_vectors=sq_vectors)
    # c0 cosine is 1.0 (>= 0.99 threshold); c2 is noise (< 0.99)
    chunk_ids = {h.chunk_id for h in out}
    assert "cand_001__0" in chunk_ids
    assert "cand_001__2" not in chunk_ids


def test_zero_retrieval_returns_empty_list(small_index, sq_vec_noise):
    """No sub-query hits any chunk above threshold → empty list.

    The caller is responsible for raising the no-evidence flag for this
    (candidate, REQ) pair per the reports/audit/no_evidence_flags.jsonl
    contract. This test verifies the retrieval returns [] in that case.
    """
    retriever = ThresholdRetriever(small_index, threshold=0.99)
    sub_queries = [("SQ001", "Q that matches nothing")]
    sq_vectors = np.array([sq_vec_noise])
    out = retrieve_evidence_for_req(retriever, "cand_001", sub_queries, sub_query_vectors=sq_vectors)
    assert out == []


def test_cap_on_union(small_index, sq_vec_a, sq_vec_b):
    """When the union of hits exceeds max_chunks_per_query, it is capped."""
    # Lower threshold so every chunk passes — that gives many hits across
    # candidates; we still filter to one candidate.
    retriever = ThresholdRetriever(small_index, threshold=-1.0, max_chunks_per_query=2)
    sub_queries = [("SQ001", "Q1"), ("SQ002", "Q2")]
    sq_vectors = np.array([sq_vec_a, sq_vec_b])
    out = retrieve_evidence_for_req(retriever, "cand_001", sub_queries, sub_query_vectors=sq_vectors)
    # cand_001 has 3 chunks (c0, c1, c2); cap=2 → only top-2 returned.
    assert len(out) == 2


def test_results_are_sorted_by_cosine_descending(small_index, sq_vec_a, sq_vec_b):
    """Output is sorted by cosine similarity descending."""
    retriever = ThresholdRetriever(small_index, threshold=-1.0)
    sub_queries = [("SQ001", "Q1"), ("SQ002", "Q2")]
    # sq_vec_a → c0 at 1.0; sq_vec_b → c1 at 1.0; c2 (noise) at some low value.
    sq_vectors = np.array([sq_vec_a, sq_vec_b])
    out = retrieve_evidence_for_req(retriever, "cand_001", sub_queries, sub_query_vectors=sq_vectors)
    cosines = [h.cosine for h in out]
    assert cosines == sorted(cosines, reverse=True)


def test_threshold_override_per_call(small_index, sq_vec_a):
    """Caller can override threshold per call without re-constructing retriever."""
    retriever = ThresholdRetriever(small_index, threshold=0.99)
    sub_queries = [("SQ001", "Q1")]
    sq_vectors = np.array([sq_vec_a])
    # With default threshold 0.99: only c0 passes.
    strict = retrieve_evidence_for_req(retriever, "cand_001", sub_queries, sub_query_vectors=sq_vectors)
    assert {h.chunk_id for h in strict} == {"cand_001__0"}
    # With override threshold -1.0: c0 AND c2 pass (c2 was noise but -1.0 lets it through).
    relaxed = retrieve_evidence_for_req(
        retriever, "cand_001",
        sub_queries=sub_queries,
        sub_query_vectors=sq_vectors,
        threshold=-1.0,
    )
    assert "cand_001__2" in {h.chunk_id for h in relaxed}