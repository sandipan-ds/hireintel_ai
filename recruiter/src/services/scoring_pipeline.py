"""Wire recruiter weight configs (UI JSON output) to the scoring engine.

This module bridges the gap between the FastAPI weight-config UI and the
unified scoring engine:

  1. Loads a weight config JSON from ``data/job_descriptions/<role>/``.
  2. Converts it from UI format (flat list keyed by req_id) to the format
     ``unified_scorer.evaluate_candidate_unified`` expects (categories with items).
  3. Loads a candidate's structured profile + chunked sections.
  4. Calls the scorer.
  5. Returns a unified evaluation ready for ranking + explanation.

This is the end-to-end "configure weights -> see scores" pipeline recommended
as the next unit of work in ``docs/CURRENT_PROGRESS.md`` (2026-07-03).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.rag.document_aware_chunker import ChunkRecord
from src.resume_parsing.structured_profile import (
    CertificationEntry,
    DegreeEntry,
    EmploymentEntry,
    StructuredCandidateProfile,
)
from src.scoring.tier_lookup import get_institute_tier_points, get_certificate_tier_points
from src.scoring.unified_scorer import (
    UnifiedCandidateEvaluation,
    UnifiedCategoryEvaluation,
    UnifiedItemEvaluation,
    _score_certification_code_only,
    _score_education_code_only,
    _score_location_code_only,
    evaluate_candidate_unified,
)
from src.services.scoring_subquery import score_candidate_all_reqs

logger = logging.getLogger(__name__)

# Root directory for candidate data.
ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"
JOB_DESCRIPTIONS_DIR = DATA_DIR / "job_descriptions"
PROCESSED_DIR = DATA_DIR / "processed"
CHUNKS_DIR = DATA_DIR / "chunks"


# ---------------------------------------------------------------------------
# Weight config loader
# ---------------------------------------------------------------------------

@dataclass
class WeightItem:
    """Normalized weight item (UI format)."""

    req_id: str
    name: str
    category: str
    type: str  # "required" | "preferred"
    weight_percentage: float
    expected_years: Optional[float] = None
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "req_id": self.req_id,
            "name": self.name,
            "category": self.category,
            "type": self.type,
            "weight_percentage": self.weight_percentage,
            "expected_years": self.expected_years,
            "notes": self.notes,
        }


@dataclass
class WeightConfig:
    """Normalized weight config (UI format)."""

    role: str
    config_name: str
    scale_factor: float
    total_allocated: float
    items: List[WeightItem] = field(default_factory=list)
    source_path: Optional[Path] = None

    def to_unified_scorer_format(self) -> Dict[str, Any]:
        """Convert UI format to ``unified_scorer`` input format.

        The unified scorer expects ``weights`` in this shape::

            {
                "role": "BusinessAnalyst",
                "max_score": 100,            # sum of all importance values
                "scale_factor": 1.0,         # 100 / max_score for normalization
                "categories": [
                    {
                        "name": "Core Skill",
                        "items": [
                            {
                                "name": "Business Analysis & Requirement Gathering",
                                "importance": 12.0,
                                "expected_years": 0,
                                "description": "...",
                            },
                            ...
                        ],
                    },
                    ...
                ],
            }

        Our UI produces a flat list with percentages summing to 100.
        We map each percentage to ``importance`` and group by category.
        """
        # Group items by category
        by_category: Dict[str, List[WeightItem]] = {}
        for item in self.items:
            by_category.setdefault(item.category, []).append(item)

        categories = []
        total_importance = 0.0
        for cat_name, cat_items in by_category.items():
            cat_block = {"name": cat_name, "items": []}
            for wi in cat_items:
                # importance = the percentage directly (UI gives 0-100 summing to 100)
                importance = float(wi.weight_percentage)
                total_importance += importance
                cat_block["items"].append({
                    "name": wi.name,
                    "req_id": wi.req_id,
                    "type": wi.type,
                    "importance": importance,
                    "expected_years": float(wi.expected_years) if wi.expected_years else 0,
                    "description": wi.notes or "",
                })
            categories.append(cat_block)

        max_score = total_importance if total_importance > 0 else 100.0
        return {
            "role": self.role,
            "max_score": max_score,
            "scale_factor": self.scale_factor if self.scale_factor > 0 else (100.0 / max_score),
            "categories": categories,
        }


def list_configs_for_role(role: str) -> List[Path]:
    """List all weight config JSON files for a role."""
    role_dir = JOB_DESCRIPTIONS_DIR / role
    if not role_dir.exists():
        return []
    return sorted(role_dir.glob(f"{role}_WeightConfig_*.json"))


def load_weight_config(role: str, config_name: str) -> WeightConfig:
    """Load a weight config by role + config name.

    Args:
        role: Role folder name (e.g., "BusinessAnalyst").
        config_name: Config name (e.g., "Senior_Level" - the safe form with
            spaces converted to underscores, as saved by the UI).

    Returns:
        ``WeightConfig`` populated from the JSON.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValueError: If the JSON is malformed or missing required keys.
    """
    safe_name = config_name.replace(" ", "_").replace("/", "_")
    file_path = JOB_DESCRIPTIONS_DIR / role / f"{role}_WeightConfig_{safe_name}.json"

    if not file_path.exists():
        raise FileNotFoundError(
            f"Weight config not found: {file_path}\n"
            f"Available: {[p.name for p in list_configs_for_role(role)]}"
        )

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = []
    for entry in data.get("requirements_weights", []):
        items.append(WeightItem(
            req_id=entry.get("requirement_id", ""),
            name=entry.get("requirement_name", ""),
            category=entry.get("category", "Unknown"),
            type=entry.get("type", "required"),
            weight_percentage=float(entry.get("weight_percentage", 0)),
            expected_years=entry.get("expected_years"),
            notes=entry.get("notes"),
        ))

    return WeightConfig(
        role=data.get("role", role),
        config_name=config_name,
        scale_factor=float(data.get("scale_factor", 1.0)),
        total_allocated=float(data.get("summary", {}).get("total_allocated", 0)),
        items=items,
        source_path=file_path,
    )


# ---------------------------------------------------------------------------
# Candidate data loaders
# ---------------------------------------------------------------------------

def _load_structured_profile_from_json(
    file_path: Path,
) -> StructuredCandidateProfile:
    """Load a structured profile from a pre-generated JSON file.

    Maps the on-disk JSON shape back to the ``StructuredCandidateProfile``
    dataclass so the scorer can consume it.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    degrees = []
    for d in data.get("degrees", []):
        degrees.append(DegreeEntry(
            degree=d.get("degree", ""),
            field=d.get("field", ""),
            institution=d.get("institution", ""),
            year=d.get("year", ""),
        ))

    certs = []
    for c in data.get("certifications", []):
        if isinstance(c, str):
            certs.append(CertificationEntry(name=c, provider="", year=""))
        elif isinstance(c, dict):
            certs.append(CertificationEntry(
                name=c.get("name", ""),
                provider=c.get("provider", ""),
                year=c.get("year", ""),
            ))

    history = []
    for e in data.get("employment_history", []):
        history.append(EmploymentEntry(
            company=e.get("company", ""),
            role=e.get("role", ""),
            dates=e.get("dates", ""),
            calculated_duration_months=int(e.get("calculated_duration_months", 0)),
            is_current=bool(e.get("is_current", False)),
        ))

    return StructuredCandidateProfile(
        candidate_id=data.get("candidate_id", ""),
        degrees=degrees,
        certifications=certs,
        total_experience_years=float(data.get("total_experience_years", 0)),
        companies=data.get("companies", []),
        roles=data.get("roles", []),
        employment_history=history,
        flagged_institutes=data.get("flagged_institutes", []),
        has_flagged_institute=bool(data.get("has_flagged_institute", False)),
    )


def _load_chunks_from_jsonl(file_path: Path) -> List[ChunkRecord]:
    """Load chunks from a .jsonl file."""
    chunks: List[ChunkRecord] = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            chunks.append(ChunkRecord(
                chunk_id=d.get("chunk_id", ""),
                candidate_id=d.get("candidate_id", ""),
                role_bucket=d.get("role_bucket", ""),
                source_file=d.get("source_file", ""),
                section=d.get("section", ""),
                chunk_index=int(d.get("chunk_index", 0)),
                text=d.get("text", ""),
                char_span=tuple(d.get("char_span", (0, 0))),
                metadata=d.get("metadata", {}),
                section_type=d.get("section_type", ""),
                parent_structure=d.get("parent_structure", {}),
                skills_asserted=d.get("skills_asserted", []),
                experience_type=d.get("experience_type", "unknown"),
            ))
    return chunks


def find_candidate_files(role: str, candidate_id: str) -> Dict[str, Optional[Path]]:
    """Locate the on-disk files for a candidate.

    The pre-generated files use either a hash (e.g. ``01888170110d1ccf``) or
    an image name (e.g. ``Image_1``) as the file stem, not the internal
    ``candidate_id`` (e.g. ``cand_433d020a3cd7``). This helper scans the role
    directory to map ``candidate_id`` -> file stem.
    """
    role_dir_processed = PROCESSED_DIR / role
    role_dir_chunks = CHUNKS_DIR / role

    # The structured profile contains the internal candidate_id; we need to
    # find the file that matches. This is O(n) but only happens once per score.
    stem = None
    if not role_dir_processed.exists():
        return {
            "structured_profile": None,
            "intelligence_report": None,
            "chunks": None,
        }

    for profile_path in role_dir_processed.glob("*_structured_profile.json"):
        try:
            with open(profile_path) as f:
                d = json.load(f)
            if d.get("candidate_id") == candidate_id:
                stem = profile_path.name.replace("_structured_profile.json", "")
                break
        except Exception:
            continue

    if not stem:
        return {
            "structured_profile": None,
            "intelligence_report": None,
            "chunks": None,
        }

    return {
        "structured_profile": role_dir_processed / f"{stem}_structured_profile.json",
        "intelligence_report": role_dir_processed / f"{stem}_intelligence_report.json",
        "chunks": role_dir_chunks / f"{stem}.jsonl",
    }


def list_candidate_ids(role: str) -> List[str]:
    """List all candidate IDs available for a role.

    Scans ``data/processed/<role>/*_structured_profile.json`` and returns
    the ``candidate_id`` field of each.
    """
    role_dir = PROCESSED_DIR / role
    if not role_dir.exists():
        return []

    ids = []
    for profile_path in role_dir.glob("*_structured_profile.json"):
        try:
            with open(profile_path) as f:
                d = json.load(f)
            cid = d.get("candidate_id", "")
            if cid:
                ids.append(cid)
        except Exception:
            continue
    return ids


# ---------------------------------------------------------------------------
# End-to-end scorer
# ---------------------------------------------------------------------------

def score_candidate(
    role: str,
    candidate_id: str,
    config_name: str,
    llm_caller: Optional[Callable[[str], str]] = None,
    default_expected_years: int = 10,
) -> UnifiedCandidateEvaluation:
    """End-to-end: load weight config + candidate data, run scorer.

    This is the single function that closes the loop from
    "recruiter clicks Save in UI" to "candidate gets a score."

    Args:
        role: Role name (e.g., "BusinessAnalyst").
        candidate_id: Internal candidate ID (e.g., "cand_433d020a3cd7").
        config_name: Weight config name (e.g., "Senior_Level").
        llm_caller: Optional callable for rubric-bound LLM scoring. If None,
            items routed to "rubric_llm" mode will get zero scores.
        default_expected_years: Default expected years when not in config.

    Returns:
        ``UnifiedCandidateEvaluation`` with per-item evidence, cached
        scoring traces, and a deterministic 0-100 total.

    Raises:
        FileNotFoundError: If the weight config or candidate files are missing.
        ValueError: If the data is malformed.
    """
    # 1. Load weight config and convert to scorer format.
    config = load_weight_config(role, config_name)
    weights_for_scorer = config.to_unified_scorer_format()
    logger.info(
        "Loaded weight config '%s' for role '%s': %d items, %.1f%% allocated",
        config_name, role, len(config.items), config.total_allocated,
    )

    # 2. Find candidate files.
    files = find_candidate_files(role, candidate_id)
    if not files["structured_profile"] or not files["chunks"]:
        raise FileNotFoundError(
            f"Candidate files not found for role={role}, candidate_id={candidate_id}. "
            f"Expected structured profile and chunks in data/processed/{role}/ and "
            f"data/chunks/{role}/."
        )

    # 3. Load structured profile.
    structured_profile = _load_structured_profile_from_json(files["structured_profile"])

    # 4. Load chunks for section-routed evidence retrieval.
    candidate_chunks = _load_chunks_from_jsonl(files["chunks"])
    logger.info(
        "Loaded candidate %s: %d chunks, %d degrees, %d certs, %.1f yrs exp",
        candidate_id, len(candidate_chunks), len(structured_profile.degrees),
        len(structured_profile.certifications), structured_profile.total_experience_years,
    )

    # 5. Build the profile dict the unified_scorer expects.
    profile = {
        "candidate_id": candidate_id,
        "id": candidate_id,
        "raw_text": "",  # Not used in code-only mode
        "contact": {},
    }

    # 6. Run the scorer.
    result = evaluate_candidate_unified(
        profile=profile,
        weights=weights_for_scorer,
        candidate_chunks=candidate_chunks,
        structured_profile=structured_profile,
        llm_caller=llm_caller,
        default_expected_years=default_expected_years,
    )

    return result


# ---------------------------------------------------------------------------
# Batched scoring: code-only + 1 LLM call for all rubric-bound REQs
# ---------------------------------------------------------------------------

def _code_only_education_score(item_name: str, importance: float, profile: StructuredCandidateProfile):
    return _score_education_code_only(item_name, importance, profile)


def _code_only_certification_score(item_name: str, importance: float, profile: StructuredCandidateProfile):
    return _score_certification_code_only(item_name, importance, profile)


def _code_only_location_score(item_name: str, importance: float, profile_dict: dict):
    return _score_location_code_only(item_name, importance, profile_dict)


def score_candidate_batched_end_to_end(
    role: str,
    candidate_id: str,
    config_name: str,
    llm_caller: Optional[Callable[[str], str]] = None,
) -> UnifiedCandidateEvaluation:
    """End-to-end batched scoring: 1 LLM call per candidate for all REQs.

    Steps:
    1. Load weight config from data/job_descriptions/<role>/.
    2. Load candidate's structured profile + chunks.
    3. Compute code-only scores for Education/Certification/Location REQs
       (no LLM, deterministic).
    4. Make 1 batched LLM call for all Skill/Experience/Project/etc REQs.
    5. Aggregate: sub-score × importance → 0-100 total.

    ~15x faster than per-REQ scoring for 15-REQ configs.
    """
    # 1. Load weight config
    config = load_weight_config(role, config_name)
    logger.info(
        "Batched scoring: '%s' for role '%s', %d items, %.1f%% allocated",
        config_name, role, len(config.items), config.total_allocated,
    )

    # 2. Find candidate files
    files = find_candidate_files(role, candidate_id)
    if not files["structured_profile"] or not files["chunks"]:
        raise FileNotFoundError(
            f"Candidate files not found for role={role}, candidate_id={candidate_id}."
        )

    structured_profile = _load_structured_profile_from_json(files["structured_profile"])

    # 3. Split REQs: code-only vs LLM-bound
    code_only_requirements = []
    llm_requirements = []

    from src.services.scoring_subquery import CATEGORY_TO_RUBRIC_TYPE
    for item in config.items:
        rubric_type = CATEGORY_TO_RUBRIC_TYPE.get(item.category.lower(), "skill")
        if rubric_type in ("education",):
            code_only_requirements.append(("education", item))
        elif rubric_type in ("certification",):
            code_only_requirements.append(("certification", item))
        elif rubric_type in ("location",):
            code_only_requirements.append(("location", item))
        else:
            # Convert item to dict for batched scorer
            llm_requirements.append({
                "req_id": item.req_id,
                "req_name": item.name,
                "category": item.category,
                "weight_percentage": item.weight_percentage,
            })

    # 4. Compute code-only scores
    code_only_results: Dict[str, UnifiedItemEvaluation] = {}
    for kind, item in code_only_requirements:
        if kind == "education":
            ev = _code_only_education_score(item.name, item.weight_percentage, structured_profile)
        elif kind == "certification":
            ev = _code_only_certification_score(item.name, item.weight_percentage, structured_profile)
        else:  # location
            profile_dict = {"candidate_id": candidate_id, "raw_text": "", "contact": {}}
            ev = _code_only_location_score(item.name, item.weight_percentage, profile_dict)
        code_only_results[item.req_id] = ev

    # 5. Run batched LLM scoring (1 call per candidate, or 0 if no LLM REQs)
    llm_results: Dict[str, Dict[str, Any]] = {}
    if llm_requirements and llm_caller is not None:
        llm_results = score_candidate_all_reqs(
            candidate_id=candidate_id,
            requirements=llm_requirements,
            llm_caller=llm_caller,
        )
    elif llm_requirements:
        # No LLM caller — all LLM items get 0
        for req in llm_requirements:
            llm_results[req["req_id"]] = {
                "req_id": req["req_id"],
                "req_name": req["req_name"],
                "hits": [],
                "sub_scores": {},
                "normalized_score": 0.0,
                "from_cache": False,
            }

    # 6. Aggregate: build UnifiedCandidateEvaluation
    # Group by category
    by_category: Dict[str, List[UnifiedItemEvaluation]] = {}
    total_raw = 0.0
    total_max = 0.0

    for kind, item in code_only_requirements:
        ev = code_only_results[item.req_id]
        by_category.setdefault(item.category, []).append(ev)
        total_raw += ev.raw_score
        total_max += ev.importance

    for req in llm_requirements:
        req_id = req["req_id"]
        result = llm_results.get(req_id, {})
        norm = result.get("normalized_score", 0.0)
        weight = req["weight_percentage"]
        # Build a UnifiedItemEvaluation-equivalent for the LLM result
        # We use ev (from the code-only helpers) and override raw_score
        ev = UnifiedItemEvaluation(
            category=req["category"],
            item_name=req["req_name"],
            description="",
            importance=weight,
            expected_years=0,
            matched=norm > 0,
            years_detected=0,
            raw_score=round(norm * weight, 2),
            score=round(norm * weight, 2),
            section="LLM-scored",
            snippet="",
            reason=f"LLM batched score: {norm:.3f}",
            scoring_mode="rubric_llm",
        )
        by_category.setdefault(req["category"], []).append(ev)
        total_raw += ev.raw_score
        total_max += ev.importance

    # Build category evaluations
    categories = []
    for cat_name, items in by_category.items():
        categories.append(UnifiedCategoryEvaluation(name=cat_name, items=items))

    # Normalize to 0-100
    scale = 100.0 / total_max if total_max > 0 else 1.0
    total = round(total_raw * scale, 2)

    return UnifiedCandidateEvaluation(
        candidate_id=candidate_id,
        role=role,
        total_raw=round(total_raw, 2),
        total_max=round(total_max, 2),
        total=total,
        categories=categories,
        has_flagged_institute=structured_profile.has_flagged_institute,
        flagged_institutes=structured_profile.flagged_institutes,
    )
