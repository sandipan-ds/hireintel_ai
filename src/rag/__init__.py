"""RAG helper modules.

Public API after the 2026-07-13 architecture overhaul (DEC-035):

* Active chunker:   :class:`src.rag.document_aware_chunker.DocumentAwareChunker`
* Retired chunker:  :class:`src.rag.recursive_chunker.RecursiveChunker` (retained for ref)
* Active retrieval: :meth:`src.rag.retriever.VectorIndex.retrieve_top_k` (top-K, no threshold)
* Vector index:     :class:`src.rag.retriever.VectorIndex`
* Convenience:      :func:`src.rag.retriever.load_default_index`

The retired ThresholdRetriever and load_default_retriever are preserved as backward-compat
shims but should not be used by new code (see BUG-RC-001 in 24_TROUBLESHOOTING.md).
"""

from src.rag.document_aware_chunker import ChunkRecord, DocumentAwareChunker, chunk_profile
from src.rag.recursive_chunker import (
    DEFAULT_SEPARATORS,
    RECURSIVE_CHUNK_OVERLAP,
    RECURSIVE_CHUNK_SIZE,
    RecursiveChunker,
    recursive_split_text,
)
from src.rag.retriever import (
    DEFAULT_INDEX_PATH,
    DEFAULT_MAX_CHUNKS_PER_QUERY,
    DEFAULT_THRESHOLD,  # retired by DEC-035, kept for backward compat
    DEFAULT_TOP_K,
    IndexedChunk,
    ScoredChunk,
    ThresholdRetriever,
    VectorIndex,
    load_default_index,
    load_default_retriever,
)

__all__ = [
    # Active chunker (DEC-035)
    "DocumentAwareChunker",
    "ChunkRecord",
    "chunk_profile",
    # Retired chunker (DEC-019, retained for reference)
    "RecursiveChunker",
    "recursive_split_text",
    "RECURSIVE_CHUNK_SIZE",
    "RECURSIVE_CHUNK_OVERLAP",
    "DEFAULT_SEPARATORS",
    # Active retrieval (DEC-035) — top-K via VectorIndex.retrieve_top_k
    "VectorIndex",
    "IndexedChunk",
    "ScoredChunk",
    "load_default_index",
    "DEFAULT_TOP_K",
    "DEFAULT_MAX_CHUNKS_PER_QUERY",
    "DEFAULT_INDEX_PATH",
    # Retired retriever (DEC-017/018, retained for backward compat)
    "ThresholdRetriever",
    "load_default_retriever",
]
