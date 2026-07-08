"""Per-REQ retrieval — embed the REQ's sub-query SET, retrieve chunks per sub-query, union them.

This is the regular-RAG retrieval path per ``docs/WORKING_LOGIC.md`` "Threshold-Based
Retrieval (Regular RAG)" and DEC-017/018/019. It replaces the legacy
``src.services.subquery_retrieval`` module, which is retained as a migration
aid (DEC-017) but should not be called by new code.

What this module does, end-to-end, for one (candidate, REQ) pair:

    1. Take the REQ's sub-query SET — a list of ``(sub_query_key, sub_query_text)``
       tuples parsed from ``<Role>_SubQuery.md`` by
       :func:`src.services.subquery_parser.parse_subquery_document`.

    2. Embed each sub-query with the same embedding model that produced the
       chunk index (``sentence-transformers/all-MiniLM-L6-v2``, 384-dim).
       Embeddings are L2-normalized.

    3. For each sub-query vector, compute cosine similarity against the
       candidate's chunk vectors in the :class:`src.rag.retriever.VectorIndex`
       (filtered by ``candidate_id``). Return every chunk with
       ``cosine >= threshold``, sorted by similarity descending.

    4. Union the per-sub-query hit sets, deduplicating by ``chunk_id`` and
       keeping the highest similarity seen across the sub-query set. Hard-cap
       the union at ``max_chunks_per_query`` (safety net; warn on cap-hit).

    5. Return the unioned chunks as :class:`src.rag.retriever.ScoredChunk`
       objects, ready to feed the rubric-bound LLM scorer as the evidence set
       for this REQ.

A single sub-query does NOT evaluate a sub-score on its own — the whole SET is
the evidence-gathering query for the REQ. The rubric scores the sub-questions
against the unioned evidence, never per-sub-query (the LLM sees the whole
evidence set at once and answers all anchored sub-questions in one call).

Important: a zero-retrieval result (no chunks meet ``threshold`` for any
sub-query in the set) is NOT silently scored as 0 — the caller is expected to
raise a "no evidence" flag for human review per the
``reports/audit/no_evidence_flags.jsonl`` contract (Track 2 of M0.5a). This
module returns an empty list in that case; the caller decides what to do with
it.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.rag.retriever import (
    DEFAULT_MAX_CHUNKS_PER_QUERY,
    DEFAULT_THRESHOLD,
    ScoredChunk,
    ThresholdRetriever,
    VectorIndex,
)

logger = logging.getLogger(__name__)

# Embedding model is the same one used to build the chunk index
# (``data/embeddings/index.npz``). The retriever itself does not embed;
# embedding is the caller's responsibility so this module doesn't pull in the
# (heavy) sentence-transformers dependency at import time.
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


# ---------------------------------------------------------------------------
# Sub-query set — the small data class the caller passes in.
# ---------------------------------------------------------------------------


SubQuery = Tuple[str, str]
"""A (key, text) tuple for one sub-query. ``key`` is e.g. ``"SQ001"``."""


# ---------------------------------------------------------------------------
# Embedding helper — lazy-loaded so the module imports without torch.
# ---------------------------------------------------------------------------

# Cached model instance. Loaded on first call to ``embed_sub_queries``.
_EMBED_MODEL = None
_EMBED_MODEL_NAME: Optional[str] = None


def _load_embed_model(model_name: str):
    """Load the sentence-transformers model (lazy, cached)."""
    global _EMBED_MODEL, _EMBED_MODEL_NAME
    if _EMBED_MODEL is not None and _EMBED_MODEL_NAME == model_name:
        return _EMBED_MODEL
    # Local import so the module imports without torch loaded.
    from sentence_transformers import SentenceTransformer

    _EMBED_MODEL = SentenceTransformer(model_name)
    _EMBED_MODEL_NAME = model_name
    return _EMBED_MODEL


def embed_sub_queries(
    sub_queries: Sequence[SubQuery],
    model_name: str = DEFAULT_EMBEDDING_MODEL,
):
    """Embed each sub-query text with the chunk-index embedding model.

    Args:
        sub_queries: ``[(key, text), ...]``. The ``key`` is not embedded; only
            ``text`` is. Keys are preserved so callers can map hits back to
            the sub-query that produced them.
        model_name: HuggingFace model id. Must match the model used to build
            the chunk index at ``data/embeddings/index.npz``.

    Returns:
        A ``(n_sub_queries, embedding_dim)`` float32 numpy array,
        L2-normalized (the :class:`VectorIndex` expects normalized queries for
        cosine = dot product).
    """
    import numpy as np

    if not sub_queries:
        return np.zeros((0, 1), dtype=np.float32)

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
    retriever: ThresholdRetriever,
    candidate_id: str,
    sub_queries: Sequence[SubQuery],
    threshold: Optional[float] = None,
    max_chunks_per_query: Optional[int] = None,
    sub_query_vectors: Optional[Any] = None,
) -> List[ScoredChunk]:
    """Retrieve unioned evidence chunks for one (candidate, REQ) pair.

    Embeds each sub-query in ``sub_queries`` (or uses pre-supplied
    ``sub_query_vectors``), retrieves chunks per sub-query via the
    :class:`ThresholdRetriever` (which already handles ``candidate_id``
    filtering, the threshold filter, the cap, and the cap-hit warning),
    then unions the per-sub-query hits — deduped by ``chunk_id``, keeping the
    highest similarity seen across the sub-query set, re-sorted desc.

    The result is the evidence set for the REQ — the chunks the rubric-bound
    LLM scorer reads to score this REQ's anchored sub-questions.

    Args:
        retriever:
            A :class:`ThresholdRetriever` wrapping a :class:`VectorIndex`
            built over the candidate corpus. Must have been built with the
            same embedding model as ``sub_query_vectors`` (or as
            :func:`embed_sub_queries` will use).
        candidate_id:
            Restrict retrieval to this candidate's chunks. Per DEC-018, the
            ``candidate_id`` filter is what makes this "per-candidate
            scoring" rather than pool search.
        sub_queries:
            ``[(key, text), ...]`` for this REQ. The whole SET is the query;
            a single sub-query does NOT eval a sub-score alone. Parsed from
            ``<Role>_SubQuery.md`` by
            :func:`src.services.subquery_parser.parse_subquery_document`.
        threshold:
            Cosine floor. ``None`` → use the retriever's configured threshold.
            Must be in ``[THRESHOLD_LOWER, THRESHOLD_UPPER]`` (default
            ``[0.10, 0.50]``); Optuna tunes this.
        max_chunks_per_query:
            Optional hard cap on the UNIONED result size. ``None`` → use the
            retriever's configured cap. The cap is a SAFETY net, not the
            primary control — the primary control is ``threshold``.
        sub_query_vectors:
            Optional pre-computed sub-query embeddings as a
            ``(n_sub_queries, dim)`` float32 array. Pass this when you're
            re-running the same REQ against many candidates (the embeddings
            don't change between candidates) — saves recomputation. ``None``
            → the function embeds the sub-queries itself via
            :func:`embed_sub_queries`.

    Returns:
        A list of :class:`ScoredChunk` objects, deduped by ``chunk_id``,
        sorted by cosine descending, capped at ``max_chunks_per_query``.

        Empty list means no chunks met ``threshold`` for ANY sub-query in the
        set — the caller should raise a "no evidence" flag for human review
        per the ``reports/audit/no_evidence_flags.jsonl`` contract; the score
        for this REQ is 0 pending that review.
    """
    if not sub_queries:
        return []

    # Resolve threshold / cap. If the caller overrides either, we use a
    # lightweight copy of the retriever with the override applied — the
    # retriever's ``retrieve_scored`` reads its own ``threshold`` and
    # ``max_chunks_per_query`` attributes, so we cannot just thread the
    # override through as a per-call arg.
    if threshold is not None:
        from copy import copy
        retriever = copy(retriever)
        retriever.threshold = float(threshold)
    if max_chunks_per_query is not None:
        from copy import copy as _copy
        if threshold is None:
            retriever = _copy(retriever)
        retriever.max_chunks_per_query = int(max_chunks_per_query)

    eff_threshold = retriever.threshold
    eff_cap = retriever.max_chunks_per_query

    # Embed the sub-queries (or use caller-supplied vectors).
    if sub_query_vectors is None:
        sq_vectors = embed_sub_queries(sub_queries)
    else:
        import numpy as np

        sq_vectors = np.asarray(sub_query_vectors, dtype=np.float32)

    if sq_vectors.shape[0] == 0:
        return []

    # ------------------------------------------------------------------
    # Per-sub-query retrieval + union-with-dedup-by-chunk_id.
    #
    # We call the retriever once per sub-query (each call applies the
    # candidate_id filter + threshold filter + its own cap). We then merge:
    # for each chunk_id, keep the highest cosine seen across the sub-query
    # set, and remember WHICH sub-query produced that highest score (for
    # auditability). Re-sort the union desc and apply the final cap.
    # ------------------------------------------------------------------

    # Best-known (cosine, source sub-query key) per chunk_id across the set.
    best: Dict[str, Tuple[float, str, ScoredChunk]] = {}

    for sq_idx, (sq_key, _sq_text) in enumerate(sub_queries):
        q_vec = sq_vectors[sq_idx]
        # The retriever already filters to candidate_id and threshold >= theta
        # and applies its own cap. We pass it the single vector.
        hits = retriever.retrieve_scored(q_vec, candidate_id=candidate_id)
        for hit in hits:
            cur = best.get(hit.chunk_id)
            if cur is None or hit.cosine > cur[0]:
                best[hit.chunk_id] = (hit.cosine, sq_key, hit)

    if not best:
        # Zero-retrieval result. Caller raises the no-evidence flag.
        return []

    # Sort unioned hits by cosine desc.
    union_sorted = sorted(best.values(), key=lambda t: t[0], reverse=True)

    # Final cap on the UNION (the per-sub-query caps already applied inside
    # the retriever, but the union can exceed ``eff_cap`` — that's the
    # cap we warn on here).
    if len(union_sorted) > eff_cap:
        logger.warning(
            "per-REQ cap hit: unioned %d chunks (candidate=%s, threshold=%.3f, "
            "n_sub_queries=%d) capped to %d",
            len(union_sorted),
            candidate_id,
            eff_threshold,
            len(sub_queries),
            eff_cap,
        )
        union_sorted = union_sorted[:eff_cap]

    return [t[2] for t in union_sorted]


__all__ = [
    "SubQuery",
    "DEFAULT_EMBEDDING_MODEL",
    "embed_sub_queries",
    "retrieve_evidence_for_req",
]