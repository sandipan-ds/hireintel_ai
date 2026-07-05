"""Tier lookup for institutions and certifications — code-only, deterministic.

Per ``WORKING_LOGIC.md`` ("Institute and Certification Tier Lookup"), the
platform maintains a recruiter-editable tier database for institutions and
certification providers. This module loads the JSON tier databases and
provides deterministic lookup functions.

The scoring rules are:

    Tier 1            → 100% of allotted points (1.0)
    Tier 2            → 75%  of allotted points (0.75)
    Tier 3            → 50%  of allotted points (0.50)
    Not Listed        → 50%  of allotted points (0.50)

Unlisted institutes/certifications get 0.50 — the same as Tier 3, unless
evidence places them in Tier 1 or Tier 2. The degree/cert match itself is
scored separately by the scorer.

The databases are stored as JSON files:
    data/Institutes/institute_tiers.json
    data/Certificates/certificate_tiers.json

Recruiters can edit these files to move institutes/certificates between tiers
or add new ones. The matching is case-insensitive and checks if the input
name contains any of the aliases listed for each entry.
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default paths — can be overridden for testing.
# ---------------------------------------------------------------------------

_INSTITUTES_PATH = Path("data/Institutes/institute_tiers.json")
_CERTIFICATES_PATH = Path("data/Certificates/certificate_tiers.json")

# Tier name → points multiplier.
_TIER_POINTS = {
    "tier_1": 1.0,
    "tier_2": 0.75,
    "tier_3": 0.50,
}

# Points for institutes/certs not found in any tier.
# This is NOT 0.0 — a legitimate but unlisted institute still gets partial
# credit for the quality multiplier. The degree/cert match itself is scored
# separately by the scorer.
_NOT_LISTED_POINTS = 0.50


# ---------------------------------------------------------------------------
# Database loading.
# ---------------------------------------------------------------------------

@lru_cache(maxsize=4)
def _load_tier_db(path_str: str) -> Dict[str, Any]:
    """Load a tier database JSON file.

    Args:
        path_str: Path to the JSON file (string for lru_cache compatibility).

    Returns:
        Parsed JSON dict with tier_1, tier_2, tier_3 sections.

    Raises:
        FileNotFoundError: If the file does not exist.
        json.JSONDecodeError: If the file is not valid JSON.
    """
    path = Path(path_str)
    if not path.exists():
        logger.warning("Tier database not found: %s", path)
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def reload_tier_databases() -> None:
    """Clear the cached tier databases so they are re-read on next lookup.

    Call this after editing the JSON files if the process is long-running.
    """
    _load_tier_db.cache_clear()


# ---------------------------------------------------------------------------
# Tier lookup — deterministic, case-insensitive, alias-based.
# ---------------------------------------------------------------------------

def _lookup_tier(name: str, db: Dict[str, Any]) -> Tuple[Optional[str], float]:
    """Look up a name in a tier database.

    Matching is case-insensitive. The function checks if the lower-cased
    input name contains any of the aliases listed for each entry in each
    tier (tier_1, tier_2, tier_3). The first match wins, with tier_1
    checked first.

    If no entry matches in any tier, the name returns ``(None, 0.0)`` —
    unlisted institutes/certificates get 0 points for the quality multiplier.
    The degree/cert match itself is scored separately by the scorer.

    Args:
        name: Institute or certificate name to look up.
        db: Parsed tier database dict.

    Returns:
        Tuple of (tier_name, points_multiplier). Returns (None, 0.0) if
        the name is not found in any tier.
    """
    if not name or not db:
        return None, 0.0

    name_lower = name.lower().strip()

    # Check each tier in order: tier_1, tier_2, tier_3.
    # Use word-boundary regex matching to avoid false positives like
    # "mit" matching inside "amity", or "du" matching inside "duke".
    for tier_name in ("tier_1", "tier_2", "tier_3"):
        tier_data = db.get(tier_name, {})
        entries = tier_data.get("institutes") or tier_data.get("certificates") or []
        for entry in entries:
            aliases = entry.get("aliases", [])
            for alias in aliases:
                if alias == "_default_":
                    continue
                # Word-boundary match: the alias must appear as a whole word
                # or phrase, not as a substring inside another word.
                pattern = r"\b" + re.escape(alias.lower()) + r"\b"
                if re.search(pattern, name_lower):
                    points = _TIER_POINTS.get(tier_name, 0.0)
                    return tier_name, points

    # Not found in any tier — return the not-listed default (0.25).
    # A legitimate but unlisted institute still gets partial credit for
    # the quality multiplier. The degree/cert match itself is scored
    # separately by the scorer.
    return None, _NOT_LISTED_POINTS


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------

def lookup_institute_tier(
    institute_name: str,
    db_path: Optional[Path] = None,
) -> Tuple[Optional[str], float]:
    """Look up the tier for an institute.

    Args:
        institute_name: Name of the institute to classify.
        db_path: Optional path to a custom institute tier database.

    Returns:
        Tuple of (tier_name, points_multiplier):
        - ("tier_1", 1.0) for premier institutes
        - ("tier_2", 0.75) for recognized institutes
        - ("tier_3", 0.50) for regional/other institutes
        - (None, 0.50) if not found in any tier (not-listed default, same as Tier 3)
    """
    path = db_path or _INSTITUTES_PATH
    db = _load_tier_db(str(path))
    return _lookup_tier(institute_name, db)


def lookup_certificate_tier(
    certificate_name: str,
    db_path: Optional[Path] = None,
) -> Tuple[Optional[str], float]:
    """Look up the tier for a certification.

    Args:
        certificate_name: Name of the certification to classify.
        db_path: Optional path to a custom certificate tier database.

    Returns:
        Tuple of (tier_name, points_multiplier):
        - ("tier_1", 1.0) for top-tier certifications
        - ("tier_2", 0.75) for second-grade certifications
        - ("tier_3", 0.50) for local/other certifications
        - (None, 0.50) if not found in any tier (not-listed default, same as Tier 3)
    """
    path = db_path or _CERTIFICATES_PATH
    db = _load_tier_db(str(path))
    return _lookup_tier(certificate_name, db)


def get_institute_tier_points(
    institute_name: str,
    db_path: Optional[Path] = None,
) -> float:
    """Convenience: return just the points multiplier for an institute.

    Args:
        institute_name: Name of the institute.
        db_path: Optional custom database path.

    Returns:
        Points multiplier (1.0, 0.75, 0.50, or 0.0).
    """
    _, points = lookup_institute_tier(institute_name, db_path)
    return points


def get_certificate_tier_points(
    certificate_name: str,
    db_path: Optional[Path] = None,
) -> float:
    """Convenience: return just the points multiplier for a certification.

    Args:
        certificate_name: Name of the certification.
        db_path: Optional custom database path.

    Returns:
        Points multiplier (1.0, 0.75, 0.50, or 0.0).
    """
    _, points = lookup_certificate_tier(certificate_name, db_path)
    return points


# ---------------------------------------------------------------------------
# Flagged institute detection — identifies fake/unknown universities.
# ---------------------------------------------------------------------------

def _check_flagged_institute(name: str, db: Dict[str, Any]) -> bool:
    """Check if an institute is flagged as fake/unknown.

    Args:
        name: Institute name to check.
        db: Parsed tier database dict.

    Returns:
        True if the institute is flagged as fake/unknown, False otherwise.
    """
    if not name or not db:
        return False

    name_lower = name.lower().strip()

    # Check all tiers for flagged institutes
    for tier_name in ("tier_1", "tier_2", "tier_3"):
        tier_data = db.get(tier_name, {})
        entries = tier_data.get("institutes") or []
        for entry in entries:
            # Check if this entry has a _note indicating it's flagged
            if "_note" in entry:
                aliases = entry.get("aliases", [])
                for alias in aliases:
                    if alias == "_default_":
                        continue
                    pattern = r"\b" + re.escape(alias.lower()) + r"\b"
                    if re.search(pattern, name_lower):
                        return True

    return False


def is_institute_flagged(
    institute_name: str,
    db_path: Optional[Path] = None,
) -> bool:
    """Check if an institute is flagged as fake/unknown.

    Args:
        institute_name: Name of the institute to check.
        db_path: Optional path to a custom institute tier database.

    Returns:
        True if the institute is flagged as fake/unknown, False otherwise.
    """
    path = db_path or _INSTITUTES_PATH
    db = _load_tier_db(str(path))
    return _check_flagged_institute(institute_name, db)


def get_flagged_institutes(
    db_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Get all flagged institutes from the tier database.

    Args:
        db_path: Optional path to a custom institute tier database.

    Returns:
        List of flagged institute entries with their details.
    """
    path = db_path or _INSTITUTES_PATH
    db = _load_tier_db(str(path))
    flagged = []

    for tier_name in ("tier_1", "tier_2", "tier_3"):
        tier_data = db.get(tier_name, {})
        entries = tier_data.get("institutes") or []
        for entry in entries:
            if "_note" in entry:
                flagged.append({
                    "name": entry.get("name", ""),
                    "aliases": entry.get("aliases", []),
                    "tier": tier_name,
                    "note": entry.get("_note", ""),
                })

    return flagged
