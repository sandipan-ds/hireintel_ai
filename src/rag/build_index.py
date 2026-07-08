"""Build the canonical resume embedding index (DEC-019 + DEC-007).

This is the production build script for the RAG pipeline's vector store. It
walks every parsed-resume JSON under ``data/processed/<role>/*.json``, chunks
each profile with the active :class:`src.rag.recursive_chunker.RecursiveChunker`
(DEC-019), embeds every chunk with ``sentence-transformers/all-MiniLM-L6-v2``
(DEC-007), and writes two artifacts to ``data/embeddings/recursive_chunking/``:

* ``index.npz``  — the :class:`src.rag.retriever.VectorIndex` binary
  (``vectors`` + ``chunk_ids`` + ``texts`` + ``metadatas``).
* ``chunks.jsonl`` — one line per chunk, the human-readable companion to the
  ``.npz`` so audits and debugger sessions can read chunk text without numpy.

The previous index built under the Document-Aware chunker is preserved by
moving it to ``data/embeddings/document_aware_backup/`` before overwriting.
Per DEC-022 the legacy chunks also persist at
``data/document_aware_chunking/`` for one release as a migration aid.

Usage::

    python -m src.rag.build_index                # defaults
    python -m src.rag.build_index --dry-run       # report counts, do not write
    python -m src.rag.build_index --batch-size 64
    python -m src.rag.build_index --chunk-size 400 --chunk-overlap 120

Side effects:
    * Overwrites ``data/embeddings/recursive_chunking/index.npz`` and
      ``data/embeddings/recursive_chunking/chunks.jsonl`` (subfolder introduced
      2026-07-06 to separate the active Recursive artifacts from the legacy
      Document-Aware index backup at ``data/embeddings/document_aware_backup/``).
    * Creates ``data/embeddings/recursive_chunking/`` and
      ``data/embeddings/document_aware_backup/`` (both as needed).
    * Loads the MiniLM-L6-v2 model (first run downloads ~90 MB to the HF cache).

Inputs:
    * Parsed resume JSONs in ``data/processed/<role>/*.json`` produced by
      :func:`src.resume_parsing.parser.parse_resume`.

Outputs:
    * ``data/embeddings/recursive_chunking/index.npz`` — numpy
      ``np.savez_compressed`` archive with fields ``vectors`` (float32
      ``(N, 384)``), ``chunk_ids`` (object array of str), ``texts`` (object
      array of str), ``metadatas`` (object array of dict).
    * ``data/embeddings/recursive_chunking/chunks.jsonl`` — one JSON line per
      chunk with keys ``chunk_id``, ``candidate_id``, ``role_bucket``,
      ``source_file``, ``section``, ``text``, ``metadata``.

Raises:
    FileNotFoundError:
        If ``data/processed/`` is missing or empty.
    ValueError:
        If a parsed profile is missing ``candidate_id``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np

# The retriever module owns the canonical paths + the VectorIndex class
# that knows how to serialize itself to ``.npz``. Importing it keeps the
# on-disk format consistent regardless of which script wrote the file.
from src.rag.retriever import (
    DEFAULT_CHUNKS_PATH,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_INDEX_PATH,
    IndexedChunk,
    VectorIndex,
)
from src.rag.recursive_chunker import (
    RECURSIVE_CHUNK_OVERLAP,
    RECURSIVE_CHUNK_SIZE,
    RecursiveChunker,
)


logger = logging.getLogger("src.rag.build_index")

#: Root of the parsed-resume tree (one sub-folder per role bucket).
PROCESSED_ROOT: str = "data/processed"

#: Chunk metadata keys copied from ChunkRecord into the JSONL line and the
#: VectorIndex ``metadata`` dict. Keeping this list explicit prevents
#: accidentally leaking parser-internal fields into the index.
_CHUNK_FIELDS: Tuple[str, ...] = (
    "chunk_id",
    "candidate_id",
    "role_bucket",
    "source_file",
    "section",
    "chunk_index",
)


# ---------------------------------------------------------------------------
# Discovery — walk the parsed-resume tree.
# ---------------------------------------------------------------------------


def discover_profiles(root: str = PROCESSED_ROOT) -> List[Tuple[str, Path]]:
    """Return ``[(role_bucket, json_path), ...]`` for every parsed resume.

    The parsed-resume tree is laid out as ``data/processed/<role>/*.json``.
    Only the top-level role sub-folders are enumerated; nested folders are
    ignored (the parser writes flat per-role). The role name is the folder
    name (e.g. ``"DataScience"``) and is stored on every chunk as
    ``role_bucket`` so the retriever can filter by role.

    Args:
        root:
            Path to the parsed-resume tree. Defaults to
            :data:`PROCESSED_ROOT` (relative to the project root).

    Returns:
        A list of ``(role_bucket, Path)`` tuples, sorted by role then by
        file name. Deterministic ordering keeps the index reproducible.

    Raises:
        FileNotFoundError:
            If ``root`` does not exist or contains no role sub-folders.
    """
    root_path = Path(root)
    if not root_path.is_dir():
        raise FileNotFoundError(
            f"Parsed-resume root not found: {root!r}. Run the resume parser "
            "first (it writes to data/processed/<role>/*.json)."
        )

    # The parser emits 3 artifacts per candidate:
    #   <cand_id>.json                  -> canonical parsed resume (we want this)
    #   <cand_id>_intelligence_report.json -> downstream LLM-derived summary
    #   <cand_id>_structured_profile.json   -> downstream structured profile
    # Re-chunking the downstream artifacts would double-count the underlying
    # resume text in the index, so we skip the suffixed files. The chokepoint
    # is the stem: real resumes have no ``_`` suffix.
    _SKIP_SUFFIXES = ("_intelligence_report", "_structured_profile")

    out: List[Tuple[str, Path]] = []
    for role_dir in sorted(p for p in root_path.iterdir() if p.is_dir()):
        role = role_dir.name
        for jf in sorted(role_dir.glob("*.json")):
            stem = jf.stem
            if any(stem.endswith(suf) for suf in _SKIP_SUFFIXES):
                continue
            out.append((role, jf))
    if not out:
        raise FileNotFoundError(
            f"No parsed resumes under {root!r}. Expected "
            "data/processed/<role>/*.json."
        )
    return out


# ---------------------------------------------------------------------------
# Chunking — one profile -> many ChunkRecords.
# ---------------------------------------------------------------------------


def chunk_profile(
    profile: Dict[str, Any],
    role_bucket: str,
    chunker: RecursiveChunker,
) -> List[Any]:
    """Chunk a single parsed profile using the active Recursive chunker.

    Thin wrapper around :meth:`RecursiveChunker.chunk_profile` so the build
    script can swap chunkers without touching the loop.

    Args:
        profile:
            Parsed resume dict (must contain ``candidate_id``).
        role_bucket:
            Role folder the resume was filed under. Stored on every chunk.
        chunker:
            The chunker instance to use.

    Returns:
        List of :class:`ChunkRecord` objects.

    Raises:
        ValueError:
            If ``profile`` is missing ``candidate_id``.
    """
    if not profile.get("candidate_id"):
        raise ValueError(
            f"Parsed profile missing 'candidate_id' (source_file="
            f"{profile.get('source_file', '<unknown>')!r}); cannot index."
        )
    return chunker.chunk_profile(profile, role_bucket=role_bucket)


# ---------------------------------------------------------------------------
# Embedding — text -> L2-normalized float32 vector.
# ---------------------------------------------------------------------------


def _load_embedder(model_name: str):
    """Lazily import sentence_transformers and load the embedding model.

    The import is deferred so ``--help`` and ``--dry-run`` work without the
    (optional-at-test-time) sentence-transformers dependency. The model
    download only happens on the first real build.
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        raise ImportError(
            "sentence-transformers is required to build the index. "
            "Install it with: pip install sentence-transformers"
        ) from e
    return SentenceTransformer(model_name)


def embed_texts(
    texts: List[str],
    embedder,
    batch_size: int,
) -> np.ndarray:
    """Embed a list of chunk texts into an ``(N, D)`` float32 matrix.

    The embedder already L2-normalizes MiniLM-L6-v2 output by default, so
    the resulting rows are ready for cosine similarity via dot product.

    Args:
        texts:
            Chunk text strings to embed. Empty strings are allowed and
            produce zero-vector embeddings (they will never match a query
            because cosine of a zero vector is 0).
        embedder:
            A loaded ``SentenceTransformer`` instance.
        batch_size:
            Number of texts per forward pass. 32 is a good default on a
            CPU-only laptop; raise to 64-128 on GPU.

    Returns:
        ``np.ndarray`` of shape ``(len(texts), 384)`` with dtype float32.
    """
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    vecs = embedder.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    return vecs.astype(np.float32, copy=False)


# ---------------------------------------------------------------------------
# Persistence — write index.npz + chunks.jsonl, backing up any prior index.
# ---------------------------------------------------------------------------


def _backup_existing(
    index_path: str,
    chunks_path: str,
    backup_dir: str = "data/embeddings/document_aware_backup",
) -> None:
    """Move an existing index + chunks.jsonl into the backup directory.

    Per DEC-022 the prior Document-Aware index is retained for one release.
    If the backup already exists we add a ``.1`` / ``.2`` suffix rather than
    overwriting it, so repeated builds don't destroy older snapshots.

    Args:
        index_path:
            Path to the existing ``index.npz`` (or None-shaped if absent).
        chunks_path:
            Path to the existing ``chunks.jsonl``.
        backup_dir:
            Directory to move the old files into.
    """
    src_index = Path(index_path)
    src_chunks = Path(chunks_path)
    if not src_index.exists() and not src_chunks.exists():
        return
    dst = Path(backup_dir)
    dst.mkdir(parents=True, exist_ok=True)

    def _move_with_suffix(src: Path) -> None:
        if not src.exists():
            return
        target = dst / src.name
        if target.exists():
            i = 1
            while True:
                cand = dst / f"{src.stem}.{i}{src.suffix}"
                if not cand.exists():
                    target = cand
                    break
                i += 1
        shutil.move(str(src), str(target))
        logger.info("backed up %s -> %s", src, target)

    _move_with_suffix(src_index)
    _move_with_suffix(src_chunks)


def write_index(
    chunks: List[Any],
    vectors: np.ndarray,
    index_path: str,
    chunks_path: str,
) -> None:
    """Serialize the built index to ``index.npz`` and ``chunks.jsonl``.

    Args:
        chunks:
            List of :class:`ChunkRecord` (dataclass). The order MUST match
            the row order of ``vectors``; this is guaranteed by the build
            loop chunking-then-embedding in the same sequence.
        vectors:
            ``np.ndarray`` of shape ``(N, 384)`` float32. Must be
            L2-normalized.
        index_path:
            Output ``.npz`` path. Parent dirs are created.
        chunks_path:
            Output ``.jsonl`` path. Parent dirs are created.
    """
    if len(chunks) != vectors.shape[0]:
        raise ValueError(
            f"chunks/vectors length mismatch: {len(chunks)} vs {vectors.shape[0]}"
        )

    # Build the VectorIndex. We pass ``normalize=False`` because the embedder
    # already normalized; double-normalizing is fine numerically but wasteful.
    indexed = [
        IndexedChunk(
            chunk_id=c.chunk_id,
            vector=vectors[i],
            text=c.text,
            metadata=_chunk_metadata(c),
        )
        for i, c in enumerate(chunks)
    ]
    index = VectorIndex(indexed, normalize=False)
    index.save_npz(index_path)

    # JSONL companion: one line per chunk for human-readable audits.
    with open(chunks_path, "w", encoding="utf-8") as fh:
        for c in chunks:
            line = {
                "chunk_id": c.chunk_id,
                "candidate_id": c.candidate_id,
                "role_bucket": c.role_bucket,
                "source_file": c.source_file,
                "section": c.section,
                "chunk_index": c.chunk_index,
                "text": c.text,
                "metadata": dict(c.metadata),
            }
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")


def _chunk_metadata(chunk: Any) -> Dict[str, Any]:
    """Build the metadata dict stored on every chunk in the VectorIndex.

    The retriever filters by ``metadata["candidate_id"]`` when scoring a
    single candidate. ``role_bucket`` and ``section`` are retained for
    audit and for the (future) role-filtered pool search.
    """
    return {
        "candidate_id": chunk.candidate_id,
        "role_bucket": chunk.role_bucket,
        "source_file": chunk.source_file,
        "section": chunk.section,
        "chunk_index": chunk.chunk_index,
        **dict(chunk.metadata),
    }


# ---------------------------------------------------------------------------
# Main pipeline.
# ---------------------------------------------------------------------------


def build(
    processed_root: str = PROCESSED_ROOT,
    index_path: str = DEFAULT_INDEX_PATH,
    chunks_path: str = DEFAULT_CHUNKS_PATH,
    chunk_size: int = RECURSIVE_CHUNK_SIZE,
    chunk_overlap: int = RECURSIVE_CHUNK_OVERLAP,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    batch_size: int = 32,
    dry_run: bool = False,
    backup: bool = True,
) -> Dict[str, Any]:
    """Run the full chunk → embed → persist pipeline.

    Args:
        processed_root:
            Parsed-resume tree root.
        index_path:
            Output ``.npz`` path.
        chunks_path:
            Output ``.jsonl`` path.
        chunk_size:
            RecursiveChunker chunk_size (chars). Must be in [200, 500].
        chunk_overlap:
            RecursiveChunker chunk_overlap (chars). Must be in
            [100, floor(0.60 * chunk_size)].
        model_name:
            Sentence-Transformers model id (DEC-007 = MiniLM-L6-v2).
        batch_size:
            Encode batch size.
        dry_run:
            If True, chunk + count but do not embed or write. Used to
            sanity-check counts and bounds without paying the embedding cost.
        backup:
            If True (default), move any pre-existing ``index.npz`` /
            ``chunks.jsonl`` into ``data/embeddings/document_aware_backup/``.

    Returns:
        Dict with build stats: ``profiles``, ``chunks``, ``dim``,
        ``roles``, ``elapsed_s``, ``index_path``, ``chunks_path``.
    """
    start = time.time()
    profiles = discover_profiles(processed_root)
    roles = sorted({r for r, _ in profiles})
    logger.info(
        "discovered %d parsed profiles across %d roles: %s",
        len(profiles), len(roles), ", ".join(roles),
    )

    chunker = RecursiveChunker(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    logger.info(
        "chunker=Recursive chunk_size=%d chunk_overlap=%d",
        chunk_size, chunk_overlap,
    )

    # ------------------------------------------------------------------
    # Phase 1: chunk every profile. Counts per role are printed as we go so
    # a stuck run is easy to localize. The all-chunks list is kept in memory
    # (~7k chunks × ~300 chars ≈ 2 MB) so we can embed in a single batched
    # pass; at our scale this is cheaper than streaming.
    # ------------------------------------------------------------------
    all_chunks: List[Any] = []
    per_role_counts: Dict[str, int] = {r: 0 for r in roles}
    per_role_profiles: Dict[str, int] = {r: 0 for r in roles}
    skipped = 0
    for role, jpath in profiles:
        try:
            with open(jpath, "r", encoding="utf-8") as fh:
                profile = json.load(fh)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("skip unreadable profile %s: %s", jpath, e)
            skipped += 1
            continue
        try:
            chunks = chunk_profile(profile, role_bucket=role, chunker=chunker)
        except ValueError as e:
            logger.warning("skip profile %s: %s", jpath, e)
            skipped += 1
            continue
        all_chunks.extend(chunks)
        per_role_counts[role] += len(chunks)
        per_role_profiles[role] += 1

    logger.info("chunked %d profiles -> %d chunks (skipped=%d)",
                len(profiles) - skipped, len(all_chunks), skipped)
    for role in roles:
        logger.info("  %-22s profiles=%4d chunks=%5d",
                    role, per_role_profiles[role], per_role_counts[role])

    if dry_run:
        elapsed = time.time() - start
        return {
            "profiles": len(profiles) - skipped,
            "chunks": len(all_chunks),
            "dim": 0,
            "roles": roles,
            "per_role_chunks": per_role_counts,
            "per_role_profiles": per_role_profiles,
            "skipped": skipped,
            "elapsed_s": elapsed,
            "index_path": None,
            "chunks_path": None,
            "dry_run": True,
        }

    if not all_chunks:
        raise RuntimeError(
            "No chunks produced. Check that data/processed/<role>/*.json "
            "contains valid parsed profiles."
        )

    # ------------------------------------------------------------------
    # Phase 2: embed every chunk. The whole chunk list is embedded in one
    # batched call — sentence-transformers handles the actual batching
    # internally and shows its own progress if show_progress_bar=True.
    # ------------------------------------------------------------------
    embedder = _load_embedder(model_name)
    texts = [c.text for c in all_chunks]
    logger.info("embedding %d chunks with %s (batch_size=%d) ...",
                len(texts), model_name, batch_size)
    vectors = embed_texts(texts, embedder, batch_size)
    dim = int(vectors.shape[1])
    logger.info("embedded -> shape=%s dtype=%s", vectors.shape, vectors.dtype)

    # ------------------------------------------------------------------
    # Phase 3: persist. Back up any prior index first, then write the new
    # index.npz and chunks.jsonl atomically-ish (write to a .tmp then rename).
    # ------------------------------------------------------------------
    if backup:
        _backup_existing(index_path, chunks_path)

    write_index(all_chunks, vectors, index_path, chunks_path)
    elapsed = time.time() - start
    logger.info(
        "wrote %s and %s (chunks=%d, dim=%d, elapsed=%.1fs)",
        index_path, chunks_path, len(all_chunks), dim, elapsed,
    )

    return {
        "profiles": len(profiles) - skipped,
        "chunks": len(all_chunks),
        "dim": dim,
        "roles": roles,
        "per_role_chunks": per_role_counts,
        "per_role_profiles": per_role_profiles,
        "skipped": skipped,
        "elapsed_s": elapsed,
        "index_path": index_path,
        "chunks_path": chunks_path,
        "dry_run": False,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m src.rag.build_index",
        description="Build the canonical resume embedding index (RecursiveChunker + MiniLM-L6-v2).",
    )
    p.add_argument(
        "--processed-root", default=PROCESSED_ROOT,
        help=f"Parsed-resume tree root (default: {PROCESSED_ROOT}).",
    )
    p.add_argument(
        "--index-path", default=DEFAULT_INDEX_PATH,
        help=f"Output .npz path (default: {DEFAULT_INDEX_PATH}).",
    )
    p.add_argument(
        "--chunks-path", default=DEFAULT_CHUNKS_PATH,
        help=f"Output .jsonl path (default: {DEFAULT_CHUNKS_PATH}).",
    )
    p.add_argument(
        "--chunk-size", type=int, default=RECURSIVE_CHUNK_SIZE,
        help=f"RecursiveChunker chunk_size in [200, 500] (default: {RECURSIVE_CHUNK_SIZE}).",
    )
    p.add_argument(
        "--chunk-overlap", type=int, default=RECURSIVE_CHUNK_OVERLAP,
        help=f"RecursiveChunker chunk_overlap (default: {RECURSIVE_CHUNK_OVERLAP}).",
    )
    p.add_argument(
        "--model-name", default=DEFAULT_EMBEDDING_MODEL,
        help=f"Sentence-Transformers model id (default: {DEFAULT_EMBEDDING_MODEL}).",
    )
    p.add_argument(
        "--batch-size", type=int, default=32,
        help="Encode batch size (default: 32).",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Chunk + report counts, do not embed or write.",
    )
    p.add_argument(
        "--no-backup", dest="backup", action="store_false",
        help="Do not back up the prior index; overwrite in place.",
    )
    p.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO).",
    )
    return p.parse_args()


def main() -> None:
    """CLI entry point. Configures logging and runs :func:`build`."""
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    stats = build(
        processed_root=args.processed_root,
        index_path=args.index_path,
        chunks_path=args.chunks_path,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        model_name=args.model_name,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        backup=args.backup,
    )
    # Final one-line summary so the operator can see it at a glance.
    print(
        f"[build_index] profiles={stats['profiles']} "
        f"chunks={stats['chunks']} dim={stats['dim']} "
        f"roles={len(stats['roles'])} skipped={stats['skipped']} "
        f"elapsed={stats['elapsed_s']:.1f}s "
        f"index={stats['index_path']} chunks={stats['chunks_path']}"
    )


if __name__ == "__main__":
    main()
