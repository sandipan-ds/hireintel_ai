"""Unit tests for per-REQ retrieval (the top-K RAG evidence path, DEC-035).

These tests exercise :func:`src.rag.per_req_retrieval.retrieve_evidence_for_req`
without loading the real sentence-transformers model — sub-query vectors are
supplied directly via the ``sub_query_vectors`` argument.

Covered behaviors (DEC-035 top-K semantics):
  - union across the REQ's sub-query set, deduped by ``chunk_id``
  - highest similarity wins when the same chunk is hit by multiple sub-queries
  - ``candidate_id`` filter is applied (per-candidate scoring, not pool search)
  - zero-retrieval result when candidate has no chunks in the index
  - the union cap kicks in when many sub-queries each retrieve many chunks
  - empty sub-query set returns ``[]``
  - results are sorted by cosine similarity descending
"""

from __future__ import annotations

import numpy as np
import pytest

from src.rag.per_req_retrieval import retrieve_evidence_for_req
from src.rag.retriever import IndexedChunk, VectorIndex


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def small_index() -> VectorIndex:
    """A 6-chunk index across 2 candidates (3 chunks each).

    Chunks for cand_001 are deliberately aligned so that:
      - c0 is an exact vector match for sq_vec_A
      - c1 is an exact vector match for sq_vec_B
      - c2 is noise (low cosine with sq_vec_A and sq_vec_B)
    Chunks for cand_002 mirror the pattern to verify candidate filtering.
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
    return small_index._matrix[0].copy()


@pytest.fixture
def sq_vec_b(small_index) -> np.ndarray:
    """A vector that exactly matches cand_001's chunk c1 (cosine = 1.0)."""
    return small_index._matrix[1].copy()


@pytest.fixture
def sq_vec_noise() -> np.ndarray:
    """A noise vector (low cosine with vec_a and vec_b)."""
    rng = np.random.default_rng(seed=99)
    dim = 16
    v = rng.standard_normal(dim).astype(np.float32)
    return v / np.linalg.norm(v)


# ---------------------------------------------------------------------------
# retrieve_evidence_for_req — top-K semantics (DEC-035)
# ---------------------------------------------------------------------------


def test_empty_sub_queries_returns_empty(small_index):
    """No sub-queries → empty result."""
    out = retrieve_evidence_for_req(small_index, "cand_001", sub_queries=[], sub_query_vectors=np.zeros((0, 16)))
    assert out == []


def test_single_sub_query_returns_matching_chunks(small_index, sq_vec_a):
    """One sub-query with top_k=1 returns the closest chunk for that candidate.

    sq_vec_a matches chunk c0 at cosine=1.0; with top_k=1 only c0 is returned.
    """
    sub_queries = [("SQ001", "Does the candidate know Python?")]
    sq_vectors = np.array([sq_vec_a])
    out = retrieve_evidence_for_req(
        small_index, "cand_001",
        sub_queries=sub_queries,
        sub_query_vectors=sq_vectors,
        top_k=1,
    )
    chunk_ids = {h.chunk_id for h in out}
    assert "cand_001__0" in chunk_ids
    c0_hit = next(h for h in out if h.chunk_id == "cand_001__0")
    assert c0_hit.cosine == pytest.approx(1.0, abs=1e-5)


def test_candidate_id_filter_excludes_other_candidates(small_index, sq_vec_a, sq_vec_b):
    """Retrieving for cand_001 must NOT return chunks from cand_002,
    even when those chunks have cosine=1.0 with a sub-query.
    """
    sub_queries = [("SQ001", "Q1"), ("SQ002", "Q2")]
    sq_vectors = np.array([sq_vec_a, sq_vec_b])
    out = retrieve_evidence_for_req(small_index, "cand_001", sub_queries, sub_query_vectors=sq_vectors)
    chunk_ids = {h.chunk_id for h in out}
    # Only cand_001 chunks
    assert all(cid.startswith("cand_001__") for cid in chunk_ids)
    assert "cand_002__0" not in chunk_ids
    assert "cand_002__1" not in chunk_ids


def test_union_dedups_by_chunk_id(small_index, sq_vec_a):
    """Two sub-queries that both match the SAME chunk: output has the chunk once."""
    sub_queries = [("SQ001", "Q1"), ("SQ002", "Q2")]
    # Both sub-query vectors point at chunk c0
    sq_vectors = np.array([sq_vec_a, sq_vec_a])
    out = retrieve_evidence_for_req(small_index, "cand_001", sub_queries, sub_query_vectors=sq_vectors)
    chunk_ids = [h.chunk_id for h in out]
    assert chunk_ids.count("cand_001__0") == 1  # deduped


def test_union_keeps_highest_similarity(small_index, sq_vec_a):
    """When two sub-queries hit the same chunk, the highest cosine wins."""
    slightly_off = sq_vec_a + 0.01 * np.ones_like(sq_vec_a)
    slightly_off = slightly_off / np.linalg.norm(slightly_off)
    sub_queries = [("SQ001", "Q1"), ("SQ002", "Q2")]
    sq_vectors = np.array([sq_vec_a, slightly_off])
    out = retrieve_evidence_for_req(small_index, "cand_001", sub_queries, sub_query_vectors=sq_vectors, top_k=3)
    hits_for_c0 = [h for h in out if h.chunk_id == "cand_001__0"]
    assert len(hits_for_c0) == 1
    assert hits_for_c0[0].cosine == pytest.approx(1.0, abs=1e-4)


def test_zero_retrieval_returns_empty_list():
    """A candidate with no chunks in the index → empty list."""
    # Build an index with only cand_002 chunks
    rng = np.random.default_rng(seed=42)
    dim = 16
    vec = rng.standard_normal(dim).astype(np.float32)
    vec = vec / np.linalg.norm(vec)
    index = VectorIndex([
        IndexedChunk(chunk_id="cand_002__0", vector=vec, text="x", metadata={"candidate_id": "cand_002"}),
    ])
    out = retrieve_evidence_for_req(index, "cand_001", sub_queries=[("SQ001", "Q")],
                                   sub_query_vectors=np.array([vec]))
    assert out == []


def test_cap_on_union(small_index, sq_vec_a, sq_vec_b):
    """When the union of hits exceeds max_chunks_per_req, it is capped."""
    sub_queries = [("SQ001", "Q1"), ("SQ002", "Q2")]
    sq_vectors = np.array([sq_vec_a, sq_vec_b])
    # top_k=3 → all 3 cand_001 chunks per sub-query; union=3; cap=2
    out = retrieve_evidence_for_req(small_index, "cand_001", sub_queries,
                                   sub_query_vectors=sq_vectors, top_k=3, max_chunks_per_req=2)
    assert len(out) == 2


def test_results_are_sorted_by_cosine_descending(small_index, sq_vec_a, sq_vec_b):
    """Output is sorted by cosine similarity descending."""
    sub_queries = [("SQ001", "Q1"), ("SQ002", "Q2")]
    sq_vectors = np.array([sq_vec_a, sq_vec_b])
    out = retrieve_evidence_for_req(small_index, "cand_001", sub_queries, sub_query_vectors=sq_vectors, top_k=3)
    cosines = [h.cosine for h in out]
    assert cosines == sorted(cosines, reverse=True)


def test_top_k_override_per_call(small_index, sq_vec_a):
    """Caller can control how many chunks are retrieved via top_k argument."""
    sub_queries = [("SQ001", "Q1")]
    sq_vectors = np.array([sq_vec_a])
    # top_k=1 → only best chunk returned
    out_1 = retrieve_evidence_for_req(small_index, "cand_001", sub_queries,
                                      sub_query_vectors=sq_vectors, top_k=1)
    assert len(out_1) == 1
    assert out_1[0].chunk_id == "cand_001__0"

    # top_k=3 → all 3 cand_001 chunks returned
    out_3 = retrieve_evidence_for_req(small_index, "cand_001", sub_queries,
                                      sub_query_vectors=sq_vectors, top_k=3)
    assert len(out_3) == 3