"""Threshold-based cosine retrieval for HireIntel AI (DEC-018, active 2026-07-05).

The active retrieval strategy for the platform: given a query embedding,
return every chunk whose cosine similarity to the query is at least
``threshold`` (default ``0.25``), sorted by similarity descending and capped
at ``max_chunks_per_query`` (default ``20``) for safety. The deterministic
scoring engine is the only ranking signal — this module just supplies the
chunks the LLM judge reads.

Why threshold, not top-K:
    A fixed ``top_k`` does not adapt to query difficulty. A hard query
    (where only 3 chunks are relevant) and an easy query (where 20 are)
    both get ``top_k=5``. Threshold-based retrieval returns more chunks
    when the corpus is generous and fewer when it is not, with a single
    intuitive knob. See ``docs/AI_DESIGN_RATIONALE.md`` §6 for the
    full rationale.

Why cosine:
    Embeddings are L2-normalized so dot product equals cosine similarity.
    The numpy inner product is fast and dependency-free.

Two layers:
    1. :class:`VectorIndex` — a thin wrapper over a numpy matrix of chunk
       vectors with optional metadata. Builds from a list of ``(chunk_id,
       vector, text)`` tuples. The pre-built index at
       ``data/embeddings/index.npz`` is compatible.
    2. :class:`ThresholdRetriever` — wraps a ``VectorIndex`` and exposes
       :meth:`retrieve` (returns chunks) and :meth:`retrieve_scored`
       (returns chunks with similarity scores).
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Tunables (DEC-018 defaults; Optuna hyperparameters per DEC-021).
#
# Owner guidance (2026-07-07): threshold bounds stay permissive at
# [0.10, 0.50] so the smoke test can sweep the low end and see how retrieval
# breadth affects ranking. The default has been lowered from 0.30 to 0.25
# to surface more date-bearing chunks per REQ (mitigating the failure mode
# where the date line landed in a chunk that did not pass the higher theta).
# Combined with the larger chunk_size (1000) and overlap (500), this should
# drastically reduce the chance that the rubric LLM sees a skill mention
# without its corresponding date context.
#
# Optuna search-space bounds (owner-specified, 2026-07-07):
#   threshold      ∈ [0.10, 0.50]   — relevance floor; chunks below this are dropped
#   chunk_size     ∈ [500, 1000]    — RecursiveCharacterTextSplitter chunk size (chars)
#   chunk_overlap  ∈ [floor(0.50 * chunk_size), floor(0.60 * chunk_size)]
#                                    — overlap is 50-60% of chunk_size
# The shipped defaults below sit INSIDE the search ranges so a default-config
# run is a valid point in the Optuna sweep. Promoting a new "Active" config
# via M0.5d replaces these defaults with the Optuna-recommended values.
# ---------------------------------------------------------------------------

#: Default number of top-K chunks to return per REQ (DEC-035).
#: Replaces threshold-based retrieval — always returns K results, no floor.
#: Guarantees the LLM always receives evidence, regardless of cosine scores.
DEFAULT_TOP_K: int = 10

#: Hard cap on returned chunks per query (safety limit).
DEFAULT_MAX_CHUNKS_PER_QUERY: int = 20

#: Path to the canonical embedding index produced by ``src.rag.build_index``.
#: DocumentAware chunker index (DEC-035, rebuilt with BGE-base-en-v1.5, 768-dim).
DEFAULT_INDEX_PATH: str = "recruiter/data/embeddings/index.npz"

#: Path to the line-delimited JSONL metadata file produced alongside the index.
DEFAULT_CHUNKS_PATH: str = "recruiter/data/embeddings/chunks.jsonl"

#: Embedding model identifier — updated from text-embedding-004 (DEC-036, retired/404)
#: to gemini-embedding-001 (DEC-037). Same REST endpoint, same 768-dim output when
#: outputDimensionality=768 is set in the payload. All callers via GeminiEmbedder stay in sync.
DEFAULT_EMBEDDING_MODEL: str = "gemini-embedding-001"

#: Retired by DEC-035. Retained for backward-compat with tests and callers not yet
#: updated to top-K retrieval. Do not use in new code.
DEFAULT_THRESHOLD: float = 0.10




logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Vector index
# ---------------------------------------------------------------------------


@dataclass
class IndexedChunk:
    """One chunk in a ``VectorIndex``: id + vector + text + optional metadata."""

    chunk_id: str
    vector: np.ndarray  # 1-D float32 array, L2-normalized
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class VectorIndex:
    """In-memory numpy index of chunk vectors with cosine retrieval.

    The index stores chunk vectors in an ``(N, D)`` float32 matrix and
    computes cosine via a single batched ``A @ B.T`` matrix multiply.
    This is dependency-free (no FAISS) and is fast enough for our scale
    (~7k chunks × 384 dims ≪ 1 ms per query).

    The pre-built index file at ``DEFAULT_INDEX_PATH`` uses the same
    format (``vectors`` + ``chunk_ids`` + ``texts`` + ``metadatas``) and
    can be loaded with :meth:`load_npz`.

    Args:
        chunks:
            Iterable of :class:`IndexedChunk` to add to the index. Vectors
            are L2-normalized on insertion.
        normalize:
            If True (default), L2-normalize each vector on insertion. Set
            to False only if the caller has already normalized.
    """

    def __init__(
        self,
        chunks: Optional[Iterable[IndexedChunk]] = None,
        normalize: bool = True,
    ) -> None:
        self._lock = threading.RLock()
        self._ids: List[str] = []
        self._texts: List[str] = []
        self._metadatas: List[Dict[str, Any]] = []
        self._matrix: Optional[np.ndarray] = None
        self._normalize = normalize
        if chunks is not None:
            for c in chunks:
                self.add(c)

    def add(self, chunk: IndexedChunk) -> None:
        """Append a single chunk to the index."""
        with self._lock:
            v = np.asarray(chunk.vector, dtype=np.float32).reshape(-1)
            if v.ndim != 1:
                raise ValueError(f"chunk.vector must be 1-D, got shape {v.shape}")
            if self._normalize:
                norm = np.linalg.norm(v)
                if norm > 0:
                    v = v / norm
            self._ids.append(chunk.chunk_id)
            self._texts.append(chunk.text)
            self._metadatas.append(dict(chunk.metadata))
            if self._matrix is None:
                self._matrix = v.reshape(1, -1)
            else:
                self._matrix = np.vstack([self._matrix, v.reshape(1, -1)])

    def __len__(self) -> int:
        return len(self._ids)

    @property
    def dim(self) -> int:
        if self._matrix is None or self._matrix.size == 0:
            return 0
        return int(self._matrix.shape[1])

    @property
    def chunk_ids(self) -> List[str]:
        return list(self._ids)

    @property
    def texts(self) -> List[str]:
        return list(self._texts)

    @property
    def metadatas(self) -> List[Dict[str, Any]]:
        return [dict(m) for m in self._metadatas]

    def cosine(self, query_vector: np.ndarray) -> np.ndarray:
        """Return cosine similarity between ``query_vector`` and every chunk.

        Args:
            query_vector:
                1-D float array. Will be L2-normalized internally.

        Returns:
            1-D float32 array of length ``len(self)`` with one similarity
            score per chunk, in insertion order.
        """
        with self._lock:
            if self._matrix is None or self._matrix.size == 0:
                return np.zeros(0, dtype=np.float32)
            q = np.asarray(query_vector, dtype=np.float32).reshape(-1)
            if q.shape[0] != self._matrix.shape[1]:
                raise ValueError(
                    f"query dim {q.shape[0]} != index dim {self._matrix.shape[1]}"
                )
            qn = np.linalg.norm(q)
            if qn > 0:
                q = q / qn
            # Matrix is already L2-normalized; cosine = (A @ B.T) / 1.
            sims = self._matrix @ q
            return sims.astype(np.float32, copy=False)

    def save_npz(self, path: str) -> None:
        """Persist the index to a single .npz file at ``path``."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            np.savez_compressed(
                p,
                vectors=self._matrix if self._matrix is not None else np.zeros((0, 0), dtype=np.float32),
                chunk_ids=np.asarray(self._ids, dtype=object),
                texts=np.asarray(self._texts, dtype=object),
                metadatas=np.asarray(self._metadatas, dtype=object),
            )

    @classmethod
    def load_npz(cls, path: str) -> "VectorIndex":
        """Load an index saved by :meth:`save_npz`."""
        data = np.load(path, allow_pickle=True)
        vectors = data["vectors"]
        chunk_ids = list(data["chunk_ids"].tolist())
        texts = list(data["texts"].tolist())
        metadatas = [dict(m) for m in data["metadatas"].tolist()]

        index = cls.__new__(cls)
        index._lock = threading.RLock()
        index._ids = chunk_ids
        index._texts = texts
        index._metadatas = metadatas
        index._matrix = None
        index._normalize = True
        if vectors.size > 0:
            index._matrix = vectors.astype(np.float32, copy=False)
        return index

    def retrieve_top_k(
        self,
        query_vector: np.ndarray,
        candidate_id: Optional[str] = None,
        k: int = DEFAULT_TOP_K,
    ) -> List["ScoredChunk"]:
        """Return the top-K highest-cosine chunks, regardless of cosine floor.

        This is the DEC-035 retrieval method. Unlike the retired
        :meth:`ThresholdRetriever.retrieve_scored`, this ALWAYS returns
        up to K chunks — there is no threshold floor. The LLM then
        determines relevance from the chunk content.

        Args:
            query_vector:
                1-D float array. Will be L2-normalized internally.
            candidate_id:
                If provided, restrict the candidate set to chunks whose
                ``metadata["candidate_id"]`` matches. Used for per-candidate
                scoring (DEC-035). When ``None``, the entire index is searched.
            k:
                Number of top chunks to return. Default :data:`DEFAULT_TOP_K`.

        Returns:
            A list of up to K :class:`ScoredChunk`, sorted by cosine
            descending. Empty list only if the index is empty or no chunks
            match the candidate filter.
        """
        sims = self.cosine(query_vector)
        if sims.size == 0:
            return []

        # Build the candidate mask.
        if candidate_id is not None:
            mask = np.fromiter(
                (
                    m.get("candidate_id") == candidate_id
                    for m in self._metadatas
                ),
                dtype=bool,
                count=len(self._metadatas),
            )
        else:
            mask = np.ones(len(self._metadatas), dtype=bool)

        # Apply the mask by setting masked-out scores to -inf.
        masked_score = np.float32(-np.inf)
        sims_filtered = np.where(mask, sims, masked_score)

        # Get eligible indices (those not -inf) sorted by similarity desc.
        eligible = sims_filtered > np.float32(-np.inf)
        if not np.any(eligible):
            return []

        eligible_indices = np.flatnonzero(eligible)
        eligible_indices = eligible_indices[np.argsort(-sims_filtered[eligible_indices])]
        eligible_indices = eligible_indices[:k]

        out: List[ScoredChunk] = []
        for idx in eligible_indices.tolist():
            out.append(
                ScoredChunk(
                    chunk_id=self._ids[idx],
                    text=self._texts[idx],
                    metadata=dict(self._metadatas[idx]),
                    cosine=float(sims_filtered[idx]),
                )
            )
        return out


# ---------------------------------------------------------------------------
# Retriever
# ---------------------------------------------------------------------------


@dataclass
class ScoredChunk:
    """A chunk plus its cosine similarity to the query."""

    chunk_id: str
    text: str
    metadata: Dict[str, Any]
    cosine: float


class ThresholdRetriever:
    """Threshold-based cosine retriever (DEC-018, the active strategy).

    Given a pre-built :class:`VectorIndex`, returns every chunk whose
    cosine similarity to the query is at least ``threshold``, sorted by
    similarity descending and capped at ``max_chunks_per_query``.

    Args:
        index:
            The vector index to retrieve from.
        threshold:
            Minimum cosine similarity for a chunk to be returned.
            Default :data:`DEFAULT_THRESHOLD` (0.70).
        max_chunks_per_query:
            Hard cap on returned chunks. A safety net, not a primary
            control — the cap is hit on > 10% of queries, ``threshold``
            is too low. Default :data:`DEFAULT_MAX_CHUNKS_PER_QUERY` (20).

    Examples:
        Build a retriever from the on-disk index and query it::

            from src.rag.retriever import ThresholdRetriever, VectorIndex
            index = VectorIndex.load_npz("data/embeddings/recursive_chunking/index.npz")
            retriever = ThresholdRetriever(index)
            query_vec = embed("5+ years of Python experience")
            hits = retriever.retrieve_scored(query_vec, candidate_id="cand_042")
    """

    def __init__(
        self,
        index: VectorIndex,
        threshold: float = DEFAULT_THRESHOLD,  # 0.10 — retired by DEC-035
        max_chunks_per_query: int = DEFAULT_MAX_CHUNKS_PER_QUERY,
    ) -> None:
        if not -1.0 <= threshold <= 1.0:
            raise ValueError(
                f"threshold must be in [-1, 1] (cosine range), got {threshold}"
            )
        if max_chunks_per_query < 1:
            raise ValueError(
                f"max_chunks_per_query must be >= 1, got {max_chunks_per_query}"
            )
        self.index = index
        self.threshold = threshold
        self.max_chunks_per_query = max_chunks_per_query

    def retrieve_scored(
        self,
        query_vector: np.ndarray,
        candidate_id: Optional[str] = None,
    ) -> List[ScoredChunk]:
        """Return chunks with cosine >= threshold, sorted desc, capped.

        Args:
            query_vector:
                1-D float array. Will be L2-normalized internally.
            candidate_id:
                If provided, restrict the candidate set to chunks whose
                ``metadata["candidate_id"]`` matches. Used for
                per-candidate scoring (DEC-018). When ``None``, the
                entire index is searched (pool search / chat).

        Returns:
            A list of :class:`ScoredChunk`, sorted by cosine descending,
            capped at ``max_chunks_per_query``. Returns an empty list
            when no chunk meets the threshold; the caller is responsible
            for the "Information not found in candidate documents."
            fallback.
        """
        sims = self.index.cosine(query_vector)
        if sims.size == 0:
            return []

        # Build the candidate mask. None means "search everything".
        if candidate_id is not None:
            mask = np.fromiter(
                (
                    m.get("candidate_id") == candidate_id
                    for m in self.index.metadatas
                ),
                dtype=bool,
                count=len(self.index.metadatas),
            )
        else:
            mask = np.ones(len(self.index.metadatas), dtype=bool)

        # Apply the mask by setting masked-out scores to -inf. Using -inf
        # (not -1.0) means no valid threshold can let a masked chunk
        # through — important for the ``candidate_id`` filter when
        # ``threshold`` is set to -1.0 in tests.
        masked_score = np.float32(-np.inf)
        sims_filtered = np.where(mask, sims, masked_score)
        eligible = sims_filtered >= np.float32(self.threshold)
        if not np.any(eligible):
            return []

        # Get the top-k eligible indices by similarity, then cap.
        eligible_indices = np.flatnonzero(eligible)
        # ``argsort`` is ascending; we want descending.
        eligible_indices = eligible_indices[np.argsort(-sims_filtered[eligible_indices])]

        cap_hit = len(eligible_indices) > self.max_chunks_per_query
        if cap_hit:
            eligible_indices = eligible_indices[: self.max_chunks_per_query]
            logger.warning(
                "threshold cap hit: %d chunks >= theta=%s, capped to %d",
                int(eligible.sum()),
                self.threshold,
                self.max_chunks_per_query,
            )

        out: List[ScoredChunk] = []
        for idx in eligible_indices.tolist():
            out.append(
                ScoredChunk(
                    chunk_id=self.index.chunk_ids[idx],
                    text=self.index.texts[idx],
                    metadata=dict(self.index.metadatas[idx]),
                    cosine=float(sims_filtered[idx]),
                )
            )
        return out

    def retrieve(
        self,
        query_vector: np.ndarray,
        candidate_id: Optional[str] = None,
    ) -> List[Tuple[str, str]]:
        """Return ``(chunk_id, text)`` pairs, sorted by cosine desc, capped.

        Convenience wrapper around :meth:`retrieve_scored` for callers
        that don't need the similarity score or metadata.
        """
        return [
            (sc.chunk_id, sc.text) for sc in self.retrieve_scored(query_vector, candidate_id)
        ]


# ---------------------------------------------------------------------------
# Convenience: build a retriever from the canonical on-disk index.
# ---------------------------------------------------------------------------


def load_default_index(
    index_path: str = DEFAULT_INDEX_PATH,
) -> VectorIndex:
    """Load the canonical embedding index and return a VectorIndex (DEC-035).

    This is the entry point for top-K retrieval (DEC-035). The VectorIndex's
    :meth:`retrieve_top_k` method replaces the retired ThresholdRetriever.

    Args:
        index_path:
            Path to a ``.npz`` file produced by :meth:`VectorIndex.save_npz`.

    Returns:
        A ready-to-use :class:`VectorIndex`.

    Raises:
        FileNotFoundError:
            If ``index_path`` does not exist. Build the index first with
            ``python -m src.rag.build_index``.
    """
    if not os.path.exists(index_path):
        raise FileNotFoundError(
            f"Embedding index not found at {index_path!r}. "
            "Build it first with `python -m src.rag.build_index`."
        )
    return VectorIndex.load_npz(index_path)


def load_default_retriever(
    index_path: str = DEFAULT_INDEX_PATH,
    threshold: float = 0.25,
    max_chunks_per_query: int = DEFAULT_MAX_CHUNKS_PER_QUERY,
) -> "ThresholdRetriever":
    """Load the canonical embedding index and return a ThresholdRetriever.

    .. deprecated::
        Retired by DEC-035. Use :func:`load_default_index` + ``retrieve_top_k``
        instead. Retained for backward compatibility with existing tests.
    """
    if not os.path.exists(index_path):
        raise FileNotFoundError(
            f"Embedding index not found at {index_path!r}. "
            "Build it first with `python -m src.rag.build_index`."
        )
    index = VectorIndex.load_npz(index_path)
    return ThresholdRetriever(
        index=index,
        threshold=threshold,
        max_chunks_per_query=max_chunks_per_query,
    )


__all__ = [
    # DEC-035 (active)
    "DEFAULT_TOP_K",
    "DEFAULT_MAX_CHUNKS_PER_QUERY",
    "DEFAULT_INDEX_PATH",
    "DEFAULT_CHUNKS_PATH",
    "DEFAULT_EMBEDDING_MODEL",
    "IndexedChunk",
    "VectorIndex",
    "ScoredChunk",
    "load_default_index",
    # Retired by DEC-035 (retained for backward compat)
    "DEFAULT_THRESHOLD",
    "ThresholdRetriever",
    "load_default_retriever",
]
