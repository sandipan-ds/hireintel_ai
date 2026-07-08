"""RAG helper modules.

Public API after the 2026-07-05 RAG pivot (DEC-017/018/019):

* Active chunker:  :class:`src.rag.recursive_chunker.RecursiveChunker`
* Legacy chunker:  :class:`src.rag.chunker.DocumentAwareChunker`
* Active retriever: :class:`src.rag.retriever.ThresholdRetriever`
* Vector index:     :class:`src.rag.retriever.VectorIndex`
* Convenience:       :func:`src.rag.retriever.load_default_retriever`

The legacy ``chunk_profile`` function and ``ChunkRecord`` class in
:mod:`src.rag.chunker` are preserved as a backward-compat shim for one
release. New code should import the classes above.
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
    DEFAULT_THRESHOLD,
    IndexedChunk,
    ScoredChunk,
    ThresholdRetriever,
    VectorIndex,
    load_default_retriever,
)

__all__ = [
    # Active chunker
    "RecursiveChunker",
    "recursive_split_text",
    "RECURSIVE_CHUNK_SIZE",
    "RECURSIVE_CHUNK_OVERLAP",
    "DEFAULT_SEPARATORS",
    # Legacy chunker (DEC-019 migration aid)
    "DocumentAwareChunker",
    "ChunkRecord",
    "chunk_profile",
    # Active retriever (DEC-018)
    "ThresholdRetriever",
    "VectorIndex",
    "IndexedChunk",
    "ScoredChunk",
    "load_default_retriever",
    "DEFAULT_THRESHOLD",
    "DEFAULT_MAX_CHUNKS_PER_QUERY",
    "DEFAULT_INDEX_PATH",
]
