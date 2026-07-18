"""Per-REQ retrieval — embed the REQ's sub-query SET, retrieve top-K chunks per sub-query, union them.

This is the top-K regular-RAG retrieval path per ``docs/14_MODEL_REGISTRY.md`` and DEC-035.
Replaces the threshold-based retrieval introduced by DEC-017/018 (which caused 50–89% binary
SQ zero rates due to weak cosine alignment — see BUG-RC-001 in 24_TROUBLESHOOTING.md).

Key change (DEC-035): top-K retrieval ALWAYS returns the best K chunks, regardless of their
cosine score. This guarantees the LLM always receives evidence to reason over. The LLM then
determines relevance, not a cosine floor.

Embedding model: ``text-embedding-004`` via the Gemini REST API (768-dim, free tier).
Replaces the previous local ``BAAI/bge-base-en-v1.5`` SentenceTransformer (DEC-036).
Output dimensionality is identical (768), so the existing index.npz format is compatible.

What this module does, end-to-end, for one (candidate, REQ) pair:

    1. Take the REQ's sub-query SET — a list of ``(sub_query_key, sub_query_text)``
       tuples parsed from ``<Role>_SubQuery.md`` by
       :func:`src.services.subquery_parser.parse_subquery_document`.

    2. Embed each sub-query with the same embedding model that produced the
       chunk index (``text-embedding-004`` via Gemini API, 768-dim). Embeddings
       are L2-normalized.

    3. For each sub-query vector, compute cosine similarity against the
       candidate's chunk vectors in the :class:`src.rag.retriever.VectorIndex`
       (filtered by ``candidate_id``). Return the top-K highest-cosine chunks
       regardless of cosine floor.

    4. Union the per-sub-query hit sets, deduplicating by ``chunk_id`` and
       keeping the highest similarity seen across the sub-query set. Cap the
       union at ``max_chunks_per_req`` (default: ``DEFAULT_TOP_K``).

    5. Return the unioned chunks as :class:`src.rag.retriever.ScoredChunk`
       objects, ready to feed the rubric-bound LLM scorer as the evidence set
       for this REQ.

A single sub-query does NOT evaluate a sub-score on its own — the whole SET is
the evidence-gathering query for the REQ. The rubric scores the sub-questions
against the unioned evidence, never per-sub-query.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.rag.retriever import (
    DEFAULT_MAX_CHUNKS_PER_QUERY,
    DEFAULT_TOP_K,
    ScoredChunk,
    VectorIndex,
)

logger = logging.getLogger(__name__)

# Embedding model used to build the chunk index and embed sub-queries (DEC-037).
# Must match the model used in ``recruiter/build_index.py``.
# BAAI/bge-base-en-v1.5: 768-dim, local ONNX model.
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-base-en-v1.5"

#: Default top-K per REQ. Each REQ retrieves its top-K chunks from the
#: candidate's DocumentAware index. Callers may override per-call.
DEFAULT_TOP_K: int = DEFAULT_TOP_K


# ---------------------------------------------------------------------------
# Sub-query set — the small data class the caller passes in.
# ---------------------------------------------------------------------------


SubQuery = Tuple[str, str]
"""A (key, text) tuple for one sub-query. ``key`` is e.g. ``"SQ001"``."""


# ---------------------------------------------------------------------------
# Embedding helper — uses GeminiEmbedder (DEC-036, replaces SentenceTransformer).
# The singleton is lazy-loaded so the module imports without any heavy ML libs.
# ---------------------------------------------------------------------------

# Singleton FastEmbedder instance — created on first call to embed_sub_queries.
_EMBED_MODEL = None
_EMBED_MODEL_NAME: Optional[str] = None


def _load_embed_model(model_name: str):
    """Return the cached FastEmbedder, creating it on first call."""
    global _EMBED_MODEL, _EMBED_MODEL_NAME
    if _EMBED_MODEL is not None and _EMBED_MODEL_NAME == model_name:
        return _EMBED_MODEL

    from src.rag.local_embedder import FastEmbedder

    _EMBED_MODEL = FastEmbedder(
        model_name=model_name,
        task_type="RETRIEVAL_QUERY",  # Sub-queries are search queries, not docs.
    )
    _EMBED_MODEL_NAME = model_name
    logger.info("FastEmbedder loaded for per-req retrieval (model=%s).", model_name)
    return _EMBED_MODEL


def embed_sub_queries(
    sub_queries: Sequence[SubQuery],
    model_name: str = DEFAULT_EMBEDDING_MODEL,
):
    """Embed each sub-query text with the chunk-index embedding model.

    Uses ``FastEmbedder`` (``BAAI/bge-base-en-v1.5``, 768-dim) running locally
    via ONNX Runtime. No external REST API calls or local PyTorch/SentenceTransformer
    installation required (DEC-036).

    Args:
        sub_queries: ``[(key, text), ...]``. The ``key`` is not embedded; only
            ``text`` is. Keys are preserved so callers can map hits back to
            the sub-query that produced them.
        model_name: Gemini embedding model id. Must match the model used to
            build the chunk index at ``data/embeddings/index.npz``.
            Defaults to ``text-embedding-004``.

    Returns:
        A ``(n_sub_queries, 768)`` float32 numpy array, L2-normalized
        (the :class:`VectorIndex` expects normalized queries for
        cosine = dot product).
    """
    import numpy as np

    if not sub_queries:
        return np.zeros((0, 768), dtype=np.float32)

    texts = [sq[1] for sq in sub_queries]
    model = _load_embed_model(model_name)
    vecs = model.encode(
        texts,
        batch_size=32,
        normalize_embeddings=True,
        convert_to_numpy=True,
    ).astype(np.float32)
    return vecs


# ---------------------------------------------------------------------------
# Per-REQ retrieval — the main entry point.
# ---------------------------------------------------------------------------


def retrieve_evidence_for_req(
    retriever: VectorIndex,
    candidate_id: str,
    sub_queries: Sequence[SubQuery],
    top_k: Optional[int] = None,
    max_chunks_per_req: Optional[int] = None,
    sub_query_vectors: Optional[Any] = None,
) -> List[ScoredChunk]:
    """Retrieve unioned top-K evidence chunks for one (candidate, REQ) pair.

    Embeds each sub-query in ``sub_queries`` (or uses pre-supplied
    ``sub_query_vectors``), retrieves the top-K highest-cosine chunks
    per sub-query from the candidate's DocumentAware chunk index, then
    unions the per-sub-query hits — deduped by ``chunk_id``, keeping the
    highest similarity seen across the sub-query set, re-sorted desc.

    Unlike the retired threshold-based retrieval (DEC-017/018), this function
    ALWAYS returns chunks — the top-K regardless of cosine score. The LLM
    then determines relevance from the content. This eliminates retrieval
    misses caused by cosine scores sitting uniformly below theta (BUG-RC-001).

    Args:
        retriever:
            A :class:`VectorIndex` built over the candidate corpus with the
            DocumentAware chunker and ``BAAI/bge-base-en-v1.5`` embeddings.
        candidate_id:
            Restrict retrieval to this candidate's chunks.
        sub_queries:
            ``[(key, text), ...]`` for this REQ. The whole SET is the query;
            a single sub-query does NOT eval a sub-score alone.
        top_k:
            Number of top-K chunks to return per sub-query. ``None`` → uses
            ``DEFAULT_TOP_K`` (10). Unioned across the sub-query set.
        max_chunks_per_req:
            Optional hard cap on the UNIONED result size. ``None`` → uses
            ``DEFAULT_MAX_CHUNKS_PER_QUERY`` (20).
        sub_query_vectors:
            Optional pre-computed sub-query embeddings as a
            ``(n_sub_queries, dim)`` float32 array. Pass this when re-running
            the same REQ across many candidates to avoid recomputation.

    Returns:
        A list of :class:`ScoredChunk` objects, deduped by ``chunk_id``,
        sorted by cosine descending, capped at ``max_chunks_per_req``.
        Never empty — returns the best available chunks for the candidate.
    """
    if not sub_queries:
        return []

    eff_top_k = int(top_k) if top_k is not None else DEFAULT_TOP_K
    eff_cap = int(max_chunks_per_req) if max_chunks_per_req is not None else DEFAULT_MAX_CHUNKS_PER_QUERY

    # Embed the sub-queries (or use caller-supplied vectors).
    if sub_query_vectors is None:
        sq_vectors = embed_sub_queries(sub_queries)
    else:
        import numpy as np
        sq_vectors = np.asarray(sub_query_vectors, dtype=np.float32)

    if sq_vectors.shape[0] == 0:
        return []

    # ------------------------------------------------------------------
    # Per-sub-query top-K retrieval + union-with-dedup-by-chunk_id (DEC-035).
    #
    # For each sub-query, retrieve the top-K highest-cosine chunks for this
    # candidate regardless of absolute cosine value. Union across the
    # sub-query set: keep the highest cosine seen per chunk_id. Re-sort desc
    # and apply the final cap.
    # ------------------------------------------------------------------

    # Best-known (cosine, source sub-query key) per chunk_id across the set.
    best: Dict[str, Tuple[float, str, ScoredChunk]] = {}

    for sq_idx, (sq_key, _sq_text) in enumerate(sub_queries):
        q_vec = sq_vectors[sq_idx]
        # retrieve_top_k returns the top-K chunks for this candidate, sorted
        # by cosine descending. No threshold floor is applied.
        hits = retriever.retrieve_top_k(q_vec, candidate_id=candidate_id, k=eff_top_k)
        for hit in hits:
            cur = best.get(hit.chunk_id)
            if cur is None or hit.cosine > cur[0]:
                best[hit.chunk_id] = (hit.cosine, sq_key, hit)

    if not best:
        # Should not happen with top-K retrieval (always returns chunks if candidate
        # has any indexed chunks). If it does, return empty for the caller to handle.
        logger.warning(
            "per-REQ top-K retrieval returned no chunks "
            "(candidate=%s, n_sub_queries=%d) — candidate may not be indexed.",
            candidate_id, len(sub_queries),
        )
        return []

    # Sort unioned hits by cosine desc.
    union_sorted = sorted(best.values(), key=lambda t: t[0], reverse=True)

    # Final cap on the UNION.
    if len(union_sorted) > eff_cap:
        logger.debug(
            "per-REQ cap applied: unioned %d chunks capped to %d "
            "(candidate=%s, n_sub_queries=%d)",
            len(union_sorted), eff_cap, candidate_id, len(sub_queries),
        )
        union_sorted = union_sorted[:eff_cap]

    return [t[2] for t in union_sorted]


__all__ = [
    "SubQuery",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_TOP_K",
    "embed_sub_queries",
    "retrieve_evidence_for_req",
]