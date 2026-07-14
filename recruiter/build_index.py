"""Build the canonical resume embedding index (DEC-035, DocumentAware + BGE-base-en-v1.5).

This is the production build script for the RAG pipeline's vector store. It
walks every parsed-resume JSON under ``data/processed/<role>/*.json``, chunks
each profile with the active :class:`src.rag.document_aware_chunker.DocumentAwareChunker`
(DEC-035, reverted from RecursiveChunker per BUG-RC-001), embeds every chunk with
``BAAI/bge-base-en-v1.5`` (768-dim, retrieval-trained), and writes two artifacts
to ``data/embeddings/document_aware/``:

* ``index.npz``  — the :class:`src.rag.retriever.VectorIndex` binary
  (``vectors`` + ``chunk_ids`` + ``texts`` + ``metadatas``).
* ``chunks.jsonl`` — one line per chunk, the human-readable companion to the
  ``.npz`` so audits and debugger sessions can read chunk text without numpy.

Why DocumentAware chunker (DEC-035):
    RecursiveChunker produced 1000-char overlapping flat-text blobs with no section
    metadata, causing 56–89% binary SQ zero rates (BUG-RC-001). DocumentAwareChunker
    reads the already-normalized structured profile JSON and creates one chunk per
    experience entry, one for skills, one for education, one for certifications, each
    carrying ``section_type`` metadata for section-aware retrieval.

Usage::

    python -m src.rag.build_index                # defaults
    python -m src.rag.build_index --dry-run       # report counts, do not write
    python -m src.rag.build_index --batch-size 64

Side effects:
    * Writes ``data/embeddings/document_aware/index.npz`` and
      ``data/embeddings/document_aware/chunks.jsonl``.
    * Creates ``data/embeddings/document_aware/`` as needed.
    * Downloads ``BAAI/bge-base-en-v1.5`` (~440 MB) to HF cache on first run.

Inputs:
    * Parsed resume JSONs in ``data/processed/<role>/*.json`` produced by
      :func:`src.resume_parsing.parser.parse_resume`.

Outputs:
    * ``data/embeddings/document_aware/index.npz`` — numpy
      ``np.savez_compressed`` archive with fields ``vectors`` (float32
      ``(N, 768)``), ``chunk_ids`` (object array of str), ``texts`` (object
      array of str), ``metadatas`` (object array of dict).
    * ``data/embeddings/document_aware/chunks.jsonl`` — one JSON line per
      chunk with keys ``chunk_id``, ``candidate_id``, ``role_bucket``,
      ``source_file``, ``section_type``, ``text``, ``metadata``.

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

import sys
# Make the local recruiter/src package importable
_LOCAL_DIR = Path(__file__).resolve().parent
if str(_LOCAL_DIR) not in sys.path:
    sys.path.insert(0, str(_LOCAL_DIR))

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
from src.rag.document_aware_chunker import (
    DocumentAwareChunker,
    chunk_profile,
)


logger = logging.getLogger("src.rag.build_index")

RECRUITER_INDEX_PATH: str = "recruiter/data/embeddings/index.npz"
RECRUITER_CHUNKS_PATH: str = "recruiter/data/embeddings/chunks.jsonl"
PROCESSED_ROOT: str = "recruiter/data/processed"

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


def discover_profiles(root: str = PROCESSED_ROOT, role: Optional[str] = None) -> List[Tuple[str, Path]]:
    """Return ``[(role_bucket, json_path), ...]`` for every parsed resume.

    The parsed-resume tree is laid out as ``recruiter/data/processed/<role>/*.json``.
    If role is specified, only that role folder is scanned.
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

    if role:
        role_dir = root_path / role
        if not role_dir.is_dir():
            raise FileNotFoundError(f"Role folder not found: {role_dir}")
        for jf in sorted(role_dir.glob("*.json")):
            stem = jf.stem
            if any(stem.endswith(suf) for suf in _SKIP_SUFFIXES):
                continue
            out.append((role, jf))
    else:
        for role_dir in sorted(p for p in root_path.iterdir() if p.is_dir()):
            r = role_dir.name
            for jf in sorted(role_dir.glob("*.json")):
                stem = jf.stem
                if any(stem.endswith(suf) for suf in _SKIP_SUFFIXES):
                    continue
                out.append((r, jf))
    if not out:
        raise FileNotFoundError(
            f"No parsed resumes under {root!r}. Expected "
            "data/processed/<role>/*.json."
        )
    return out


# ---------------------------------------------------------------------------
# Chunking — one profile -> many ChunkRecords.
# ---------------------------------------------------------------------------


def _adapt_profile_for_chunker(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Adapt the current production profile schema to the format expected by
    :func:`chunk_profile` in ``document_aware_chunker``.

    The production profile written by ``src.resume_parsing.parser`` has the
    shape::

        {
            "candidate_id": "...",
            "candidate_profile": {
                "summary": "<str>",
                "experience": [{"job_title": ..., "company": ..., "start_date": ...,
                                "end_date": ..., "responsibilities": [...],
                                "tools_and_skills": [...], ...}, ...],
                "education": [...],
                "skills": [{"name_canonical": ..., ...}, ...],
                "projects": [...],
                "certifications": [...],
            },
            "source_file": "...",
        }

    The document_aware_chunker's ``chunk_profile`` function expects the FLAT
    shape (legacy parser output)::

        {
            "candidate_id": "...",
            "summary": {"value": "<str>"},
            "experience": {"entries": [{"title": ..., "company": ...,
                                        "dates": "start_date - end_date",
                                        "details": [...], ...}]},
            "education": {"entries": [{"description": ...}]},
            "skills": ["skill_name", ...],
            "projects": ["project text", ...],
            "certifications": ["cert text", ...],
            "source_file": "...",
        }

    This function performs the translation so the chunker receives the format
    it was designed for, without modifying the chunker or the parser.
    """
    cp = profile.get("candidate_profile") or {}

    # ---- Summary ---
    summary_raw = cp.get("summary") or ""
    summary = {"value": summary_raw} if isinstance(summary_raw, str) else summary_raw

    # ---- Experience ---
    exp_raw = cp.get("experience") or []
    if isinstance(exp_raw, list):
        exp_entries = []
        for e in exp_raw:
            start = e.get("start_date") or ""
            end = e.get("end_date") or ("Present" if e.get("is_current") else "")
            dates = f"{start} - {end}".strip(" -") if (start or end) else ""
            details = []
            if isinstance(e.get("responsibilities"), list):
                details.extend(e["responsibilities"])
            if isinstance(e.get("tools_and_skills"), list):
                details.extend(e["tools_and_skills"])
            exp_entries.append({
                "title": e.get("job_title") or e.get("title") or "",
                "company": e.get("company") or "",
                "dates": dates,
                "location": e.get("location") or "",
                "details": details,
            })
        experience = {"entries": exp_entries}
    else:
        experience = exp_raw  # already in legacy format

    # ---- Education ---
    edu_raw = cp.get("education") or []
    if isinstance(edu_raw, list):
        edu_entries = []
        for e in edu_raw:
            if isinstance(e, dict):
                parts = [
                    e.get("degree") or "",
                    e.get("field_of_study") or e.get("major") or "",
                    e.get("institution") or "",
                ]
                description = " | ".join(p for p in parts if p)
                edu_entries.append({"description": description})
            elif isinstance(e, str):
                edu_entries.append({"description": e})
        education = {"entries": edu_entries}
    else:
        education = edu_raw

    # ---- Skills ---
    skills_raw = cp.get("skills") or []
    if skills_raw and isinstance(skills_raw[0], dict):
        # New schema: list of {"name_canonical": ..., ...}
        skills = [
            s.get("name_canonical") or s.get("name_raw") or ""
            for s in skills_raw
            if s
        ]
    else:
        skills = skills_raw  # already list of strings

    # ---- Projects ---
    projects_raw = cp.get("projects") or []
    if projects_raw and isinstance(projects_raw[0], dict):
        def _project_to_text(p: Dict[str, Any]) -> str:
            title = p.get("title") or p.get("name") or ""
            desc = p.get("description") or ""
            if isinstance(desc, list):
                desc = " ".join(str(x) for x in desc if x)
            return f"{title} {desc}".strip()
        projects = [_project_to_text(p) for p in projects_raw if p]
    else:
        projects = projects_raw  # already list of strings

    # ---- Certifications ---
    certs_raw = cp.get("certifications") or []
    if certs_raw and isinstance(certs_raw[0], dict):
        certifications = [
            c.get("name") or c.get("title") or str(c)
            for c in certs_raw
        ]
    else:
        certifications = certs_raw

    return {
        "candidate_id": profile.get("candidate_id") or "cand_unknown",
        "source_file": profile.get("source_file") or cp.get("source_file") or "",
        "summary": summary,
        "experience": experience,
        "education": education,
        "skills": skills,
        "projects": projects,
        "certifications": certifications,
        "languages": cp.get("languages") or [],
        "evidence_chunks": profile.get("evidence_chunks") or [],
    }


def _local_chunk_profile(
    profile: Dict[str, Any],
    role_bucket: str,
) -> List[Any]:
    """Chunk a single parsed profile using the active DocumentAware chunker.

    Adapts the current production profile schema to the format expected by
    :func:`chunk_profile` from ``document_aware_chunker``, then delegates.

    Args:
        profile:
            Parsed resume dict (must contain ``candidate_id`` at top level
            or inside ``candidate_profile``).
        role_bucket:
            Role folder the resume was filed under. Stored on every chunk.

    Returns:
        List of :class:`ChunkRecord` objects.

    Raises:
        ValueError:
            If ``profile`` is missing ``candidate_id``.
    """
    candidate_id = (
        profile.get("candidate_id")
        or (profile.get("candidate_profile") or {}).get("candidate_id")
    )
    if not candidate_id:
        raise ValueError(
            f"Parsed profile missing 'candidate_id' (source_file="
            f"{profile.get('source_file', '<unknown>')!r}); cannot index."
        )
    # Translate from production schema → chunker legacy schema.
    adapted = _adapt_profile_for_chunker(profile)
    # chunk_profile is imported from document_aware_chunker at module top.
    return chunk_profile(adapted, role_bucket=role_bucket)



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

    BGE-base-en-v1.5 with ``normalize_embeddings=True`` returns unit vectors
    ready for cosine similarity via dot product.

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
        ``np.ndarray`` of shape ``(len(texts), D)`` with dtype float32,
        where D=768 for ``BAAI/bge-base-en-v1.5``.
    """
    dim = 768  # BGE-base-en-v1.5
    if not texts:
        return np.zeros((0, dim), dtype=np.float32)
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
    index_path: str = RECRUITER_INDEX_PATH,
    chunks_path: str = RECRUITER_CHUNKS_PATH,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    batch_size: int = 32,
    dry_run: bool = False,
    backup: bool = True,
    role: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the full chunk → embed → persist pipeline (DEC-035).

    Uses DocumentAwareChunker (one chunk per section entry) + BGE-base-en-v1.5
    (768-dim, retrieval-trained). Chunk-size and overlap parameters have been
    removed — DocumentAware chunking is not configurable by character count;
    it is driven by the parsed resume's section structure.

    Args:
        processed_root:
            Parsed-resume tree root.
        index_path:
            Output ``.npz`` path.
        chunks_path:
            Output ``.jsonl`` path.
        model_name:
            Sentence-Transformers model id (DEC-035 = bge-base-en-v1.5).
        batch_size:
            Encode batch size.
        dry_run:
            If True, chunk + count but do not embed or write. Used to
            sanity-check counts and bounds without paying the embedding cost.
        backup:
            If True (default), move any pre-existing ``index.npz`` /
            ``chunks.jsonl`` into a backup sub-folder before overwriting.

    Returns:
        Dict with build stats: ``profiles``, ``chunks``, ``dim``,
        ``roles``, ``elapsed_s``, ``index_path``, ``chunks_path``.
    """
    start = time.time()
    profiles = discover_profiles(processed_root, role=role)
    roles = sorted({r for r, _ in profiles})
    logger.info(
        "discovered %d parsed profiles across %d roles: %s",
        len(profiles), len(roles), ", ".join(roles),
    )
    logger.info("chunker=DocumentAwareChunker (DEC-035) — one chunk per section entry")

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
            chunks = _local_chunk_profile(profile, role_bucket=role)
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
        description="Build the canonical resume embedding index (DocumentAwareChunker + BGE-base-en-v1.5, DEC-035).",
    )
    p.add_argument(
        "--processed-root", default=PROCESSED_ROOT,
        help=f"Parsed-resume tree root (default: {PROCESSED_ROOT}).",
    )
    p.add_argument(
        "--index-path", default=RECRUITER_INDEX_PATH,
        help=f"Output .npz path (default: {RECRUITER_INDEX_PATH}).",
    )
    p.add_argument(
        "--chunks-path", default=RECRUITER_CHUNKS_PATH,
        help=f"Output .jsonl path (default: {RECRUITER_CHUNKS_PATH}).",
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
        "--role", default=None,
        help="Build index for a single role folder only (e.g. React_Developer_20260714).",
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
        model_name=args.model_name,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        backup=args.backup,
        role=args.role,
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
