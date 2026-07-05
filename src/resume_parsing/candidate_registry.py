"""Candidate registry: stable, role-encoded candidate identifiers (DEC-025).

Replaces the SHA1-hash-based candidate id (``cand_<12hex>``) with a
human-readable, role-encoded, sequential id (``BusinessAnalyst_CAND_0001``).
The registry is the source of truth for the mapping; the id is allocated
once and never renumbers, even if a candidate is deleted.

Public API:
    :func:`allocate_or_lookup` — given a source path, return the
        candidate's id (existing or newly allocated).
    :func:`lookup` — given a source path or id, return the registry
        entry (or None).
    :func:`save` / :func:`load` — registry persistence.

Stability guarantees:
    * The same source path always returns the same id.
    * Two different source paths never share an id.
    * Deleting a candidate's source file does not free its id.
    * The counter is monotonic per role; numbers are never reused.

The registry file is committed to git (``data/candidate_registry.json``)
because it is the source of truth for downstream joins (chunks,
per-resume reasoning, scores). It contains source paths but no PII
beyond the file system layout; treat it as semi-sensitive.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Current schema version. Bump on any breaking change to the registry shape.
SCHEMA_VERSION: str = "1.0"

#: Path to the registry file. Created on first write.
DEFAULT_REGISTRY_PATH: str = "data/candidate_registry.json"

#: ID format: ``<Role>_CAND_<NNNN>`` where N is one or more digits.
#: Role name follows Python identifier rules (letter, then letters/digits/underscores).
ID_PATTERN: re.Pattern[str] = re.compile(r"^[A-Za-z][A-Za-z0-9]*_CAND_\d{4,}$")

#: Default number of zero-padded digits for the counter. Bump to 5 if a
#: role ever crosses 9999 candidates.
COUNTER_DIGITS: int = 4

#: Default starting value for a new role's counter (i.e. the first
#: candidate allocated in a fresh role gets the number ``STARTING_COUNTER + 1``).
#: Stored as a private constant; callers never see this.
_STARTING_COUNTER: int = 0


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CandidateRegistryError(Exception):
    """Base class for registry errors."""


class InvalidCandidateIdError(CandidateRegistryError):
    """Raised when a candidate id does not match the expected format."""


class RoleNotFoundError(CandidateRegistryError):
    """Raised when a role has no entry in ``next_counter``."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """Return the current UTC timestamp as an ISO 8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_path(path: str | Path) -> str:
    """Return an absolute, resolved, platform-stable string for ``path``.

    Uses :meth:`Path.resolve` to canonicalize the path. The result is the
    registry's canonical key for the file, so all allocation and lookup
    flows must go through this function.
    """
    return str(Path(path).resolve())


def _format_id(role: str, counter: int) -> str:
    """Format a role + counter as the canonical candidate id."""
    if not re.match(r"^[A-Za-z][A-Za-z0-9]*$", role):
        raise InvalidCandidateIdError(
            f"role name must be a Python identifier: got {role!r}"
        )
    if counter < _STARTING_COUNTER:
        raise InvalidCandidateIdError(
            f"counter must be >= {_STARTING_COUNTER}, got {counter}"
        )
    return f"{role}_CAND_{counter:0{COUNTER_DIGITS}d}"


def _parse_id(candidate_id: str) -> tuple[str, int]:
    """Split a candidate id into ``(role, counter)``.

    Raises:
        InvalidCandidateIdError: If ``candidate_id`` does not match the
            expected format.
    """
    if not ID_PATTERN.match(candidate_id):
        raise InvalidCandidateIdError(
            f"candidate id does not match format ``<Role>_CAND_<NNNN>``: "
            f"got {candidate_id!r}"
        )
    role, _, tail = candidate_id.rpartition("_CAND_")
    return role, int(tail)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class CandidateRegistry:
    """The candidate registry (DEC-025).

    A ``CandidateRegistry`` wraps the on-disk JSON file. All mutations
    are persisted via :meth:`save` (called automatically after
    :meth:`allocate_or_lookup`). The registry is thread-safe — internal
    mutation is guarded by a lock so concurrent allocations cannot
    produce duplicate ids.

    Typical usage::

        from src.resume_parsing.candidate_registry import CandidateRegistry

        registry = CandidateRegistry.load()
        candidate_id = registry.allocate_or_lookup(
            source_path="data/original/BusinessAnalyst/jane_doe.pdf",
            role="BusinessAnalyst",
        )
        # -> "BusinessAnalyst_CAND_0001"
        registry.save()  # explicit; also auto-saved on mutation

    Args:
        next_counter:
            Per-role counter map. The next number to allocate for each
            role is ``next_counter[role] + 1``. A role not in the map
            has counter 0 (i.e. the next allocation gets 1).
        candidates:
            Per-id metadata. Keys are candidate ids (``<Role>_CAND_<NNNN>``),
            values are dicts with ``source_path``, ``source_filename``,
            ``legacy_hash_id`` (optional), ``allocated_at``, ``last_seen_at``.
        path:
            Path to the on-disk JSON file. ``None`` for an in-memory
            registry (useful for tests).
        auto_save:
            If True (default), mutations are persisted to disk immediately.
    """

    def __init__(
        self,
        next_counter: Optional[Dict[str, int]] = None,
        candidates: Optional[Dict[str, Dict[str, Any]]] = None,
        path: Optional[str] = None,
        auto_save: bool = True,
    ) -> None:
        self._next_counter: Dict[str, int] = dict(next_counter or {})
        self._candidates: Dict[str, Dict[str, Any]] = dict(candidates or {})
        self._path: Optional[Path] = Path(path) if path else None
        self._auto_save = auto_save
        self._lock = threading.RLock()
        # Index from source path to candidate id for O(1) lookup. Built
        # lazily and invalidated on every mutation.
        self._path_index: Optional[Dict[str, str]] = None

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: str = DEFAULT_REGISTRY_PATH) -> "CandidateRegistry":
        """Load the registry from ``path``. Returns an empty registry if absent.

        Missing file is not an error — it means this is the first run.
        An existing file with an unsupported schema_version is a hard
        error (the caller should migrate explicitly).
        """
        p = Path(path)
        if not p.exists():
            return cls(next_counter={}, candidates={}, path=path)
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise CandidateRegistryError(
                f"registry schema_version mismatch: expected "
                f"{SCHEMA_VERSION!r}, got {version!r}. Migrate the registry first."
            )
        return cls(
            next_counter=data.get("next_counter", {}),
            candidates=data.get("candidates", {}),
            path=path,
        )

    def save(self) -> None:
        """Persist the registry to its ``path``.

        Atomic write via a temp file + rename, so a partial write
        cannot corrupt the registry. No-op if ``self.path`` is None.
        """
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "next_counter": dict(self._next_counter),
            "candidates": {k: dict(v) for k, v in self._candidates.items()},
        }
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
        tmp.replace(self._path)
        self._auto_save = True  # subsequent mutations auto-save

    # ------------------------------------------------------------------
    # Internal index
    # ------------------------------------------------------------------

    def _invalidate_index(self) -> None:
        self._path_index = None

    def _build_index(self) -> Dict[str, str]:
        idx: Dict[str, str] = {}
        for cid, meta in self._candidates.items():
            sp = meta.get("source_path")
            if sp:
                idx[sp] = cid
        return idx

    def _get_index(self) -> Dict[str, str]:
        if self._path_index is None:
            self._path_index = self._build_index()
        return self._path_index

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def allocate_or_lookup(
        self,
        source_path: str | Path,
        role: str,
        legacy_hash_id: Optional[str] = None,
    ) -> str:
        """Return the candidate id for ``source_path`` under ``role``.

        If the source path is already registered, the existing id is
        returned (``last_seen_at`` is updated). Otherwise a new id is
        allocated by incrementing the role's counter.

        Args:
            source_path:
                Absolute or relative path to the resume file. Will be
                normalized via :func:`_normalize_path` before lookup.
            role:
                Role folder name. Must match ``^[A-Za-z][A-Za-z0-9]*$``.
            legacy_hash_id:
                Optional. The pre-DEC-025 hash id (``cand_<12hex>``) for
                this source path. Stored in the registry entry as
                ``legacy_hash_id`` for backwards compatibility with the
                6,377 existing Document-Aware chunks.

        Returns:
            The candidate id, e.g. ``"BusinessAnalyst_CAND_0001"``.

        Raises:
            InvalidCandidateIdError: If ``role`` is not a valid identifier.
        """
        if not re.match(r"^[A-Za-z][A-Za-z0-9]*$", role):
            raise InvalidCandidateIdError(
                f"role must be a Python identifier: got {role!r}"
            )
        sp = _normalize_path(source_path)
        now = _now_iso()

        with self._lock:
            # Fast path: existing entry.
            idx = self._get_index()
            existing = idx.get(sp)
            if existing is not None:
                meta = self._candidates[existing]
                meta["last_seen_at"] = now
                if self._auto_save:
                    self.save()
                return existing

            # Slow path: allocate a new id.
            current = self._next_counter.get(role, _STARTING_COUNTER)
            new_counter = current + 1
            new_id = _format_id(role, new_counter)
            self._next_counter[role] = new_counter
            self._candidates[new_id] = {
                "source_path": sp,
                "source_filename": Path(sp).name,
                "allocated_at": now,
                "last_seen_at": now,
            }
            if legacy_hash_id is not None:
                self._candidates[new_id]["legacy_hash_id"] = legacy_hash_id
            self._invalidate_index()

            if self._auto_save:
                self.save()
            return new_id

    def lookup(self, source_path: Optional[str | Path] = None, candidate_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Return the registry entry for ``source_path`` or ``candidate_id``.

        At least one of ``source_path`` / ``candidate_id`` must be provided.
        Returns ``None`` if the entry is not found.

        Args:
            source_path:
                Path to look up. Normalized via :func:`_normalize_path`.
            candidate_id:
                Candidate id to look up. Must match the expected format.

        Returns:
            The metadata dict (a copy) or ``None``.
        """
        if source_path is None and candidate_id is None:
            raise ValueError("lookup requires source_path or candidate_id")
        with self._lock:
            if candidate_id is not None:
                meta = self._candidates.get(candidate_id)
                return dict(meta) if meta is not None else None
            # source_path lookup
            sp = _normalize_path(source_path)
            idx = self._get_index()
            cid = idx.get(sp)
            if cid is None:
                return None
            return dict(self._candidates[cid])

    def role_counter(self, role: str) -> int:
        """Return the next counter value for ``role`` (the number that will be allocated next)."""
        with self._lock:
            return self._next_counter.get(role, _STARTING_COUNTER)

    def all_candidates(self) -> Dict[str, Dict[str, Any]]:
        """Return a shallow copy of all registry entries (id -> metadata)."""
        with self._lock:
            return {k: dict(v) for k, v in self._candidates.items()}

    def candidates_for_role(self, role: str) -> Dict[str, Dict[str, Any]]:
        """Return all candidates whose role is ``role``."""
        with self._lock:
            return {
                cid: dict(meta)
                for cid, meta in self._candidates.items()
                if cid.startswith(f"{role}_CAND_")
            }

    def __len__(self) -> int:
        return len(self._candidates)

    def __contains__(self, candidate_id: object) -> bool:
        return isinstance(candidate_id, str) and candidate_id in self._candidates


# ---------------------------------------------------------------------------
# Convenience for tests + scripts
# ---------------------------------------------------------------------------


def fresh_registry() -> CandidateRegistry:
    """Return a new in-memory registry (no path, no auto-save)."""
    return CandidateRegistry(next_counter={}, candidates={}, path=None, auto_save=False)


__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_REGISTRY_PATH",
    "COUNTER_DIGITS",
    "ID_PATTERN",
    "CandidateRegistry",
    "CandidateRegistryError",
    "InvalidCandidateIdError",
    "RoleNotFoundError",
    "fresh_registry",
]
