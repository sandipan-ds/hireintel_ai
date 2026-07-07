"""Sub-query embedding cache — wraps ``embed_sub_queries`` with lookup + persist.

The corpus embedding index (``data/embeddings/index.npz``) is built once at
index-build time. The corpus embeddings are NEVER recomputed per query — that
is the whole point of a RAG index.

Sub-queries are different. They are tied to a ROLE, not to a candidate. The
same ``(role, req_id, sq_key)`` triple produces the same sub-query text and the
same embedding every time. Without this cache, the production batch CLI would
re-encode the same ~55 sub-queries per role over and over again, once per
candidate (Track 7 perf optimization).

This module transparently wraps :func:`src.rag.per_req_retrieval.embed_sub_queries`
with two cache layers:

1. **In-memory dict** — ``Dict[cache_key, np.ndarray]`` keyed by
   ``(model_name, sha256(sq_text))``. Survives within a process; cleared on
   restart. Fast.
2. **Optional on-disk cache** — ``data/embeddings/subqueries_cache.npz`` for the
   embedding matrix + ``data/embeddings/subqueries_cache_manifest.json`` for the
   cache-key → (role, req_id, sq_key, sq_text, subquery_file_hash) mapping.
   Loaded into the in-memory dict at ``SubQueryCache.load()`` time; appended on
   miss.

**File-hash-aware invalidation.** The manifest stores the SHA-256 hash of each
``<Role>_SubQuery.md`` file. When the file changes (recruiter edits the JD), the
``load()`` call detects the mismatch, drops the stale entries, and falls back to
re-encoding on first call. The new embeddings land in the manifest on next
``flush()``.

**Path through the batch CLI:**

    cache = SubQueryCache.load(model_name=DEFAULT_EMBEDDING_MODEL)
    cached_embedder = cache.wrap_embed_sub_queries()
    for role in roles:
        for candidate_id in candidates:
            evaluation = evaluate_candidate_composed(
                ...,
                sq_embedder=cached_embedder,
            )

The ``cached_embedder`` callable has the same signature as
:func:`embed_sub_queries` — ``Sequence[SubQuery] -> np.ndarray`` — so it drops
into the existing call site at :mod:`src.scoring.unified_scorer` line ~1146
without any change to the composed scorer.

Cache hits are free (a dict lookup + array index). Cache misses encode the
text via the same ``embed_sub_queries`` machinery (model load is shared across
the cache and the standalone ``embed_sub_queries`` via the module-level
``_EMBED_MODEL`` in :mod:`per_req_retrieval`).

Schema (manifest JSONL line):

    {
        "cache_key": "sha256:abc...",
        "model_name": "sentence-transformers/all-MiniLM-L6-v2",
        "role": "BusinessAnalyst",
        "req_id": "REQ-001",
        "sq_key": "SQ001",
        "sq_text": "Is there evidence that the candidate has served...",
        "subquery_file_hash": "sha256:def...",
        "last_encoded_at": "2026-07-06T20:14:12Z",
        "index": 42  // row index into subqueries_cache.npz
    }

Schema (.npz):

    arr_0: (n_entries, embedding_dim) float32, L2-normalized, one row per
        manifest entry, indexed by ``manifest[index]``.

Manifest and npz are written together on ``flush()``; partial writes are
atomic via the temp-file rename pattern.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from src.rag.per_req_retrieval import (
    DEFAULT_EMBEDDING_MODEL,
    SubQuery,
    embed_sub_queries,
)

logger = logging.getLogger(__name__)


# Default on-disk cache location. Lives next to the chunk index
# (``data/embeddings/``) since it is the same model and the same lifecycle.
DEFAULT_CACHE_PATH = Path("data/embeddings/subqueries_cache.npz")
DEFAULT_MANIFEST_PATH = Path("data/embeddings/subqueries_cache_manifest.jsonl")

# How the SubQuery source file is partitioned in the manifest. We hash the
# ``<Role>_SubQuery.md`` file once at build time so that an edit invalidates
# only the affected role's sub-queries, not all of them. This keeps the eval
# sets stable when one role is updated.
DEFAULT_SUBQUERY_DIR = Path("data/job_descriptions")


def _sha256(text: str) -> str:
    """Return the SHA-256 hex digest of ``text`` (UTF-8)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> Optional[str]:
    """Return the SHA-256 hex digest of ``path`` contents, or ``None`` if missing."""
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO 8601 (Z suffix)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cache_key(model_name: str, sq_text: str) -> str:
    """Stable cache key per (model, sub-query text).

    The sub-query text is the only varying input — keys/role/req_id are routing
    metadata, not embedding inputs, so they don't enter the key. Quantized to
    the SHA-256 of the lowercased + stripped text so trivial whitespace changes
    don't invalidate unnecessarily.
    """
    normalized = " ".join(sq_text.lower().strip().split())
    return f"{model_name}:{_sha256(normalized)}"


def _subquery_file_for_role(role: str) -> Path:
    """Return the canonical SubQuery ``.md`` path for ``role``."""
    return DEFAULT_SUBQUERY_DIR / role / f"{role}_SubQuery.md"


class SubQueryCache:
    """In-memory + on-disk cache for sub-query embeddings.

    Construction is cheap (no I/O). The heavy work happens at ``load()`` time
    (read the on-disk cache + manifest into memory) and on the first miss
    (load the sentence-transformers model and encode the text).

    The cache is **per-process** — concurrent processes have independent
    in-memory dicts but share the on-disk store via ``flush()``. The on-disk
    store is append-mostly (no row-level updates), so concurrent flushes are
    safe-ish; the worst case is duplicate entries, which the lookup layer
    dedupes by ``cache_key``.
    """

    def __init__(
        self,
        cache_path: Path = DEFAULT_CACHE_PATH,
        manifest_path: Path = DEFAULT_MANIFEST_PATH,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
    ) -> None:
        # On-disk paths. None means "in-memory only, never persist".
        self.cache_path: Optional[Path] = Path(cache_path) if cache_path else None
        self.manifest_path: Optional[Path] = (
            Path(manifest_path) if manifest_path else None
        )
        self.model_name: str = model_name
        # In-memory state.
        # _vectors: list of np.ndarray rows, indexed by the order they were
        # added. The .npz stores them stacked into a single matrix.
        self._vectors: List[np.ndarray] = []
        # _meta: list of dicts (one per row) parallel to _vectors.
        self._meta: List[Dict[str, Any]] = []
        # _key_to_index: cache_key → row index for O(1) lookup + dedup.
        self._key_to_index: Dict[str, int] = {}
        # _dirty: True when in-memory differs from the last flushed disk state.
        self._dirty: bool = False

    # ------------------------------------------------------------------
    # Properties for introspection.
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        """Number of cached entries currently in memory."""
        return len(self._vectors)

    @property
    def is_dirty(self) -> bool:
        """True iff the in-memory state has unsaved changes."""
        return self._dirty

    def __len__(self) -> int:
        return len(self._vectors)

    def __contains__(self, sq_text: str) -> bool:
        return _cache_key(self.model_name, sq_text) in self._key_to_index

    # ------------------------------------------------------------------
    # Loading + flushing (disk I/O).
    # ------------------------------------------------------------------

    @classmethod
    def load(
        cls,
        cache_path: Path = DEFAULT_CACHE_PATH,
        manifest_path: Path = DEFAULT_MANIFEST_PATH,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        subquery_dir: Path = DEFAULT_SUBQUERY_DIR,
    ) -> "SubQueryCache":
        """Construct the cache and re-hydrate from disk if present.

        Reads ``manifest_path`` line-by-line; for each entry, verifies the
        role's SubQuery file hash still matches the manifest. Entries whose
        source file changed (or whose model no longer matches) are skipped.
        Valid entries populate the in-memory dict; the surviving rows are
        re-stacked into a fresh ``_vectors`` list so the dirty flag can be
        set correctly.

        Args:
            cache_path: Path to the ``.npz`` matrix. Neither file needs to
                exist; missing files just yield an empty cache.
            manifest_path: Path to the JSONL manifest.
            model_name: Embedding model name. Entries with a different model
                are skipped.
            subquery_dir: Root directory for ``<role>/<role>_SubQuery.md``
                files. Used for file-hash invalidation.

        Returns:
            A populated :class:`SubQueryCache`. Empty if no on-disk cache
            exists or if every entry was invalidated.
        """
        cache = cls(
            cache_path=cache_path,
            manifest_path=manifest_path,
            model_name=model_name,
        )
        if not cache_path.exists() or not manifest_path.exists():
            logger.info(
                "subquery_cache: no on-disk cache at %s / %s — starting empty.",
                cache_path,
                manifest_path,
            )
            return cache

        # Load the matrix rows.
        try:
            matrix = np.load(cache_path, allow_pickle=False)
            arr_key = list(matrix.keys())[0]
            all_rows: np.ndarray = matrix[arr_key]
        except Exception as exc:  # noqa: BLE001
            logger.warning("subquery_cache: failed to load %s: %s", cache_path, exc)
            return cache

        # Load the manifest and filter entries.
        kept_rows: List[np.ndarray] = []
        kept_meta: List[Dict[str, Any]] = []
        kept_keys: Dict[str, int] = {}
        with manifest_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Filter by model.
                if entry.get("model_name") != model_name:
                    continue
                # Filter by source-file hash (invalidation).
                role = entry.get("role")
                if role:
                    current_hash = _file_sha256(_subquery_file_for_role(role))
                    manifest_hash = entry.get("subquery_file_hash")
                    if current_hash is None or current_hash != manifest_hash:
                        logger.info(
                            "subquery_cache: dropping stale entry for %s/%s "
                            "(file changed: %s → %s)",
                            role, entry.get("sq_key"),
                            (manifest_hash or "—")[:8], (current_hash or "—")[:8],
                        )
                        continue
                idx = entry.get("index")
                if not isinstance(idx, int) or idx < 0 or idx >= len(all_rows):
                    continue
                key = entry["cache_key"]
                if key in kept_keys:
                    # Skip duplicate (concurency-safety; last writer wins).
                    continue
                kept_keys[key] = len(kept_rows)
                kept_rows.append(all_rows[idx])
                kept_meta.append(entry)
        cache._vectors = kept_rows
        cache._meta = kept_meta
        cache._key_to_index = kept_keys
        cache._dirty = False
        logger.info(
            "subquery_cache: loaded %d valid entries from %s (%d skipped).",
            len(cache), manifest_path, len(all_rows) - len(kept_rows),
        )
        return cache

    def flush(self) -> None:
        """Persist the in-memory cache to disk atomically.

        Writes ``cache_path`` (NumPy .npz) + ``manifest_path`` (JSONL) using
        the temp-file + rename pattern so a crash mid-flush never leaves a
        partially-written file. After the write, ``is_dirty`` is False.

        No-op if ``cache_path`` or ``manifest_path`` is None (in-memory-only
        cache) or if the cache hasn't changed since the last flush.
        """
        if self.cache_path is None or self.manifest_path is None:
            return
        if not self._dirty and self.cache_path.exists() and self.manifest_path.exists():
            return
        if not self._vectors:
            return

        # Stack vectors into a single matrix of shape (N, dim).
        matrix = np.stack(self._vectors, axis=0).astype(np.float32)

        # Ensure the parent directory exists.
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write: temp file in same directory, then rename.
        for target, write_fn in (
            (self.cache_path, lambda p: np.savez(p, embeddings=matrix)),
            (self.manifest_path, self._write_manifest_jsonl),
        ):
            with tempfile.NamedTemporaryFile(
                mode="wb" if target == self.cache_path else "w",
                dir=str(target.parent),
                prefix=target.name + ".",
                suffix=".tmp",
                delete=False,
                encoding=None if target == self.cache_path else "utf-8",
            ) as tmp:
                tmp_name = tmp.name
                if target == self.cache_path:
                    np.savez(tmp, embeddings=matrix)
                else:
                    self._write_manifest_jsonl(tmp)
            shutil.move(tmp_name, str(target))

        self._dirty = False
        logger.info(
            "subquery_cache: flushed %d entries to %s + %s",
            len(self), self.cache_path, self.manifest_path,
        )

    def _write_manifest_jsonl(self, fh) -> None:
        """Write the in-memory manifest to ``fh`` as one JSON object per line."""
        for idx, meta in enumerate(self._meta):
            entry = {**meta, "index": idx}
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------
    # Lookup + miss handling (the main cache API).
    # ------------------------------------------------------------------

    def lookup(self, sq_text: str) -> Optional[np.ndarray]:
        """Return the cached embedding for ``sq_text`` or ``None`` on miss."""
        key = _cache_key(self.model_name, sq_text)
        idx = self._key_to_index.get(key)
        if idx is None:
            return None
        return self._vectors[idx].copy()

    def get_or_encode(
        self,
        sub_queries: Sequence[SubQuery],
        role: Optional[str] = None,
        req_id: Optional[str] = None,
    ) -> np.ndarray:
        """Encode the given sub-queries, hitting the cache for known texts.

        Args:
            sub_queries: ``[(key, text), ...]``. The key is metadata only;
                embedding is by ``text``.
            role: Optional role name; recorded in the manifest for
                invalidation. ``None`` is allowed for ad-hoc calls.
            req_id: Optional REQ id; recorded in the manifest.

        Returns:
            ``(n_sub_queries, embedding_dim)`` float32 array,
            L2-normalized, in the same order as ``sub_queries``.
        """
        if not sub_queries:
            return np.zeros((0, 1), dtype=np.float32)

        results: List[Optional[np.ndarray]] = [None] * len(sub_queries)
        miss_indices: List[int] = []
        miss_subqueries: List[SubQuery] = []

        for i, (sq_key, sq_text) in enumerate(sub_queries):
            vec = self.lookup(sq_text)
            if vec is not None:
                results[i] = vec
            else:
                miss_indices.append(i)
                miss_subqueries.append((sq_key, sq_text))

        if miss_subqueries:
            # Encode all misses in one batch (the model call amortizes the
            # vectorized forward pass).
            encoded = embed_sub_queries(miss_subqueries, model_name=self.model_name)
            # Stash each new vector both in the cache and the result list.
            subquery_file_hash: Optional[str] = None
            if role is not None:
                subquery_file_hash = _file_sha256(_subquery_file_for_role(role))
            for j, (sq_key, sq_text) in enumerate(miss_subqueries):
                vec = encoded[j]
                self._add_entry(
                    sq_key=sq_key,
                    sq_text=sq_text,
                    vec=vec,
                    role=role,
                    req_id=req_id,
                    subquery_file_hash=subquery_file_hash,
                )
                # ``results[i]`` was None for misses — fill it in now.
                i = miss_indices[j]
                results[i] = vec

        # Stack in the original order. All entries in ``results`` are now
        # populated (None only if miss_subqueries was empty, which we handled
        # above by the early return).
        return np.stack(results, axis=0).astype(np.float32)

    def _add_entry(
        self,
        sq_key: str,
        sq_text: str,
        vec: np.ndarray,
        role: Optional[str],
        req_id: Optional[str],
        subquery_file_hash: Optional[str],
    ) -> None:
        """Append a new entry to the in-memory cache and mark dirty."""
        key = _cache_key(self.model_name, sq_text)
        if key in self._key_to_index:
            # Already cached (concurrent miss in the same batch). Return
            # silently rather than raise — the existing vector wins.
            return
        self._key_to_index[key] = len(self._vectors)
        self._vectors.append(vec)
        self._meta.append(
            {
                "cache_key": key,
                "model_name": self.model_name,
                "role": role,
                "req_id": req_id,
                "sq_key": sq_key,
                "sq_text": sq_text,
                "subquery_file_hash": subquery_file_hash,
                "last_encoded_at": _utc_now_iso(),
            }
        )
        self._dirty = True

    # ------------------------------------------------------------------
    # Pre-encoding all SubQuery files for one role (build-time warmup).
    # ------------------------------------------------------------------

    def preencode_role(
        self,
        role: str,
        subquery_dir: Path = DEFAULT_SUBQUERY_DIR,
    ) -> int:
        """Pre-encode every sub-query in ``<role>_SubQuery.md``.

        Walks the parsed SubQuery file for ``role``, looks up REQs and their
        sub-queries, encodes any missing entries, and returns the number of
        newly-cached entries. Idempotent: a second call returns 0.

        Args:
            role: Role bucket name (e.g. ``"BusinessAnalyst"``).
            subquery_dir: Root directory for SubQuery files.

        Returns:
            Number of newly-cached entries (cache misses inserted).
        """
        from src.services.subquery_parser import parse_subquery_document

        sq_path = subquery_dir / role / f"{role}_SubQuery.md"
        parsed = parse_subquery_document(sq_path)
        # ``parse_subquery_document`` returns a dict with ``requirements`` list.
        reqs = parsed.get("requirements", []) if isinstance(parsed, dict) else []
        total_new = 0
        for req in reqs:
            req_id = req.get("req_id") or ""
            sub_queries: List[SubQuery] = [
                (sq.get("key") or "", sq.get("text") or "")
                for sq in req.get("sub_queries", [])
            ]
            if not sub_queries:
                continue
            before = len(self)
            self.get_or_encode(
                sub_queries, role=role, req_id=req_id,
            )
            total_new += len(self) - before
        logger.info(
            "subquery_cache: preencode_role(%s) added %d entries (total=%d).",
            role, total_new, len(self),
        )
        return total_new

    def preencode_all_roles(
        self,
        subquery_dir: Path = DEFAULT_SUBQUERY_DIR,
    ) -> Dict[str, int]:
        """Pre-encode every SubQuery file under ``subquery_dir``.

        Returns a ``{role_name: n_new_entries}`` dict.

        The role list is taken from the SubQuery directory (every folder
        that contains a ``<Role>_SubQuery.md`` file). This matches the
        :func:`src.services.subquery_parser.get_all_role_subqueries` contract.
        """
        results: Dict[str, int] = {}
        for role_dir in sorted(subquery_dir.iterdir()):
            if not role_dir.is_dir():
                continue
            sq_file = role_dir / f"{role_dir.name}_SubQuery.md"
            if not sq_file.exists():
                continue
            results[role_dir.name] = self.preencode_role(
                role_dir.name, subquery_dir=subquery_dir,
            )
        return results

    # ------------------------------------------------------------------
    # The wrap helper — drop-in replacement for ``embed_sub_queries``.
    # ------------------------------------------------------------------

    def wrap_embed_sub_queries(self):
        """Return a callable matching :func:`embed_sub_queries` signature.

        The returned closure accepts ``Sequence[SubQuery]`` and returns the
        cached embedding per sub-query (encoding on miss). It is meant to
        be passed as the ``sq_embedder`` kwarg to
        :func:`src.scoring.unified_scorer.evaluate_candidate_composed` so the
        batch CLI gets the cache benefit without touching the scorer's
        call signature.

        The optional ``role`` and ``req_id`` routing metadata is NOT
        available at the closure's call site (the scorer just passes the
        sub-query list). Manifest entries written via the wrapped path will
        have ``role=None, req_id=None`` — that's a trade for API symmetry.
        For full manifest metadata, use :meth:`preencode_role` at batch start;
        the wrapped path then re-hits the cache (free) instead of re-encoding.
        """
        def _embedder(sub_queries: Sequence[SubQuery]) -> np.ndarray:
            return self.get_or_encode(sub_queries, role=None, req_id=None)
        return _embedder


__all__ = [
    "DEFAULT_CACHE_PATH",
    "DEFAULT_MANIFEST_PATH",
    "DEFAULT_SUBQUERY_DIR",
    "SubQueryCache",
]
