#!/usr/bin/env python
"""Backfill the candidate registry from the existing 721-resume corpus (DEC-025).

Walks ``data/processed/<role>/<id>.json`` and registers each candidate
under the new ``<Role>_CAND_<NNNN>`` scheme. The legacy hash id is
preserved in the ``legacy_hash_id`` field of each entry so the existing
6,377 Document-Aware chunks can be cross-referenced.

The script is idempotent: running it twice is a no-op (existing
allocations are preserved). It is also safe to re-run after manual
edits to ``data/candidate_registry.json``; new candidates get the
next free number, existing allocations stay.

Usage::

    python -m scripts.backfill_candidate_registry [--dry-run]

Options:
    --dry-run    Print what would be done without writing anything.
    --verbose    Log every registration, not just summary stats.

Exit codes:
    0   success (or no-op if no candidates found)
    1   unexpected error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


# Make the ``src`` package importable when running this script directly
# (e.g. ``python scripts/backfill_candidate_registry.py`` from the
# project root).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.resume_parsing.candidate_registry import (  # noqa: E402
    CandidateRegistry,
    DEFAULT_REGISTRY_PATH,
    ID_PATTERN,
    InvalidCandidateIdError,
)


#: Root of the parsed profiles.
_PROCESSED_ROOT = _PROJECT_ROOT / "data" / "processed"

#: Roles we expect to find (DEC-014: 8 roles).
EXPECTED_ROLES: List[str] = [
    "BusinessAnalyst",
    "DataScience",
    "JavaDeveloper",
    "ReactDeveloper",
    "SalesManager",
    "SQLDeveloper",
    "SrPythonDeveloper",
    "WebDesigning",
]


def _iter_existing_candidates() -> List[Tuple[str, str, str]]:
    """Walk ``data/processed/<role>/<id>.json`` and yield ``(role, legacy_id, abs_path)``.

    The ``data/processed/<role>/`` directory contains three files per
    candidate: the parsed profile (``<id>.json``), the intelligence
    report (``<id>_intelligence_report.json``), and the structured
    profile (``<id>_structured_profile.json``). We only count the
    ``<id>.json`` files; the others are derived artifacts.

    Sort by ``(role, legacy_id)`` for deterministic allocation order:
    candidates in the same role get sequential numbers based on the
    legacy hash id (alphabetical), which is a stable proxy for
    "first-seen" without requiring git history.
    """
    out: List[Tuple[str, str, str]] = []
    if not _PROCESSED_ROOT.is_dir():
        return out
    for role_dir in sorted(_PROCESSED_ROOT.iterdir()):
        if not role_dir.is_dir():
            continue
        for profile_path in sorted(role_dir.glob("*.json")):
            # Skip auxiliary files (intelligence report, structured
            # profile); only the bare profile ``<id>.json`` represents
            # a candidate. Auxiliary files have suffixes
            # ``_intelligence_report.json`` and ``_structured_profile.json``.
            if not _is_candidate_profile_path(profile_path):
                continue
            try:
                with profile_path.open("r", encoding="utf-8") as f:
                    profile = json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                print(
                    f"  warn: skipping unreadable profile {profile_path}: {exc}",
                    file=sys.stderr,
                )
                continue
            legacy = profile.get("candidate_id", "")
            if not legacy:
                print(
                    f"  warn: profile {profile_path} has no candidate_id, "
                    f"using filename {profile_path.stem}",
                    file=sys.stderr,
                )
                legacy = profile_path.stem
            out.append((role_dir.name, legacy, str(profile_path.resolve())))
    # Deterministic order: by (role, legacy_id).
    out.sort(key=lambda t: (t[0], t[1]))
    return out


def _is_candidate_profile_path(path: Path) -> bool:
    """Return True iff ``path`` is a bare ``<id>.json`` candidate profile.

    Excludes:
    * ``<id>_intelligence_report.json``
    * ``<id>_structured_profile.json``
    and any other auxiliary file with a non-candidate filename.
    """
    if path.suffix.lower() != ".json":
        return False
    stem = path.stem
    return not (stem.endswith("_intelligence_report") or stem.endswith("_structured_profile"))


def backfill(
    registry_path: str = DEFAULT_REGISTRY_PATH,
    dry_run: bool = False,
    verbose: bool = False,
) -> Dict[str, int]:
    """Backfill the registry from the existing corpus.

    Returns a small dict of summary statistics:
        ``{"registered": int, "skipped": int, "newly_allocated": int}``.
    """
    candidates = _iter_existing_candidates()
    if not candidates:
        print("No existing candidates found; nothing to backfill.")
        return {"registered": 0, "skipped": 0, "newly_allocated": 0}

    if dry_run:
        # In dry-run mode we still want to report what would happen, so
        # we build a virtual counter and walk the candidates. We do not
        # write to disk.
        next_counter: Dict[str, int] = {}
        registered = 0
        skipped = 0
        for role, legacy, abs_path in candidates:
            new_id = (
                f"{role}_CAND_"
                f"{next_counter.get(role, 0) + 1:04d}"
            )
            next_counter[role] = next_counter.get(role, 0) + 1
            registered += 1
            if verbose:
                print(f"  would register: {legacy!r} -> {new_id!r}")
        return {
            "registered": registered,
            "skipped": skipped,
            "newly_allocated": registered,
        }

    registry = CandidateRegistry.load(registry_path)
    pre_count = len(registry)
    newly_allocated = 0
    skipped = 0

    # Disable auto-save during the loop and save once at the end. This
    # avoids 721 file writes (one per candidate) and the Windows file-
    # locking issue where a process can't replace a file it just wrote.
    registry._auto_save = False  # noqa: SLF001 — internal but documented

    for role, legacy, abs_path in candidates:
        # The legacy id is a hash of the absolute path. The new id is
        # allocated from the registry. We pass the source path so the
        # registry's index is keyed correctly.
        try:
            existing = registry.lookup(source_path=abs_path)
        except Exception as exc:  # pragma: no cover - defensive
            print(f"  warn: lookup failed for {abs_path}: {exc}", file=sys.stderr)
            skipped += 1
            continue
        if existing is not None:
            # Already registered; skip but verify legacy_hash_id is recorded.
            if existing.get("legacy_hash_id") != legacy:
                existing["legacy_hash_id"] = legacy
                # Caller saves once at the end.
            skipped += 1
            if verbose:
                print(f"  skip: {existing['candidate_id']!r} (already registered)")
            continue
        new_id = registry.allocate_or_lookup(
            source_path=abs_path,
            role=role,
            legacy_hash_id=legacy,
        )
        newly_allocated += 1
        if verbose:
            print(f"  + {new_id!r}  <-  {legacy!r}  ({Path(abs_path).name})")

    registry.save()

    return {
        "registered": len(registry),
        "skipped": skipped,
        "newly_allocated": newly_allocated,
        "pre_count": pre_count,
    }


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill the candidate registry from the existing corpus."
    )
    parser.add_argument(
        "--registry",
        default=DEFAULT_REGISTRY_PATH,
        help=f"Path to the registry JSON (default: {DEFAULT_REGISTRY_PATH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without writing anything.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Log every registration, not just summary stats.",
    )
    args = parser.parse_args(argv)

    stats = backfill(
        registry_path=args.registry,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )
    mode = "DRY-RUN " if args.dry_run else ""
    print(
        f"{mode}Backfill summary: "
        f"registered={stats.get('registered', 0)} "
        f"newly_allocated={stats.get('newly_allocated', 0)} "
        f"skipped={stats.get('skipped', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
