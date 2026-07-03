"""JSON export service for weight configurations.

Saves weight configurations as JSON files alongside SubQuery docs,
in the same format expected by the scoring engine (unified_scorer.py).
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent.parent


def export_config_to_json(
    role_name: str,
    config_name: str,
    weight_items: List[Dict[str, Any]],
    total_allocated: float,
    scale_factor: float,
    recruiter_name: str = "Recruiter",
) -> Path:
    """Export a weight configuration to JSON file.

    Saves to: data/job_descriptions/{role_name}/{role_name}_WeightConfig_{config_name}.json

    Args:
        role_name: Name of the role (e.g., "BusinessAnalyst").
        config_name: Name of the configuration (e.g., "Senior Level").
        weight_items: List of weight item dicts with keys:
            req_id, name, category, type, weight_percentage, expected_years (optional).
        total_allocated: Total weight percentage allocated.
        scale_factor: Scale factor for normalization.
        recruiter_name: Name of the recruiter.

    Returns:
        Path to the saved JSON file.
    """
    # Build the JSON structure matching the existing example format
    requirements_weights = []
    by_category: Dict[str, Dict[str, Any]] = {}

    for item in weight_items:
        req_entry = {
            "requirement_id": item["req_id"],
            "requirement_name": item["name"],
            "category": item["category"],
            "type": item.get("requirement_type", "required"),
            "weight_percentage": item["weight_percentage"],
        }
        if item.get("expected_years") is not None:
            req_entry["expected_years"] = item["expected_years"]
        if item.get("notes"):
            req_entry["notes"] = item["notes"]

        requirements_weights.append(req_entry)

        # Build category summary
        cat = item["category"]
        if cat not in by_category:
            by_category[cat] = {"total": 0.0, "count": 0, "items": []}
        by_category[cat]["total"] += item["weight_percentage"]
        by_category[cat]["count"] += 1
        by_category[cat]["items"].append(
            f"{item['name']} ({item['weight_percentage']}%)"
        )

    # Build interpretation
    interpretation = _build_interpretation(role_name, by_category)

    # Build the full JSON
    config_json = {
        "role": role_name,
        "config_name": config_name,
        "created_by": recruiter_name,
        "created_date": datetime.date.today().isoformat(),
        "scale_factor": round(scale_factor, 4),
        "requirements_weights": requirements_weights,
        "summary": {
            "total_allocated": total_allocated,
            "by_category": by_category,
        },
        "interpretation": interpretation,
    }

    # Save to file
    role_dir = ROOT / "data" / "job_descriptions" / role_name
    role_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize config_name for filename
    safe_name = config_name.replace(" ", "_").replace("/", "_")
    file_path = role_dir / f"{role_name}_WeightConfig_{safe_name}.json"

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(config_json, f, indent=2, ensure_ascii=False)

    return file_path


def load_config_from_json(file_path: Path) -> Dict[str, Any]:
    """Load a weight configuration from a JSON file.

    Args:
        file_path: Path to the JSON file.

    Returns:
        Configuration dictionary.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_json_configs(role_name: str) -> List[Path]:
    """List all JSON weight configs for a role.

    Args:
        role_name: Name of the role.

    Returns:
        List of paths to JSON config files.
    """
    role_dir = ROOT / "data" / "job_descriptions" / role_name
    if not role_dir.exists():
        return []

    pattern = f"{role_name}_WeightConfig_*.json"
    return sorted(role_dir.glob(pattern))


def delete_json_config(role_name: str, config_name: str) -> bool:
    """Delete a JSON weight config file.

    Args:
        role_name: Name of the role.
        config_name: Name of the configuration.

    Returns:
        True if deleted, False if not found.
    """
    role_dir = ROOT / "data" / "job_descriptions" / role_name
    safe_name = config_name.replace(" ", "_").replace("/", "_")
    file_path = role_dir / f"{role_name}_WeightConfig_{safe_name}.json"

    if file_path.exists():
        file_path.unlink()
        return True
    return False


def _build_interpretation(role_name: str, by_category: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """Build an interpretation summary for the configuration."""
    total_weights = {cat: data["total"] for cat, data in by_category.items()}
    sorted_cats = sorted(total_weights.items(), key=lambda x: x[1], reverse=True)

    if not sorted_cats:
        return {"emphasis": "No weights configured.", "hiring_profile": "", "candidate_fit_example": ""}

    top_category = sorted_cats[0][0]
    top_pct = sorted_cats[0][1]

    emphasis_parts = []
    for cat, pct in sorted_cats:
        if pct > 0:
            emphasis_parts.append(f"{cat} ({pct}%)")

    emphasis = f"This configuration emphasizes {', '.join(emphasis_parts)}."

    # Determine hiring profile
    core_total = total_weights.get("Core Skill", 0) + total_weights.get("Technology Skill", 0)
    experience_total = total_weights.get("Experience", 0)
    edu_total = total_weights.get("Education", 0) + total_weights.get("Certification", 0)

    if core_total > experience_total:
        profile = f"Looking for: Strong {role_name} with solid technical and core skills."
    elif experience_total > core_total:
        profile = f"Looking for: Experienced {role_name} with proven track record."
    else:
        profile = f"Looking for: Balanced {role_name} with both skills and experience."

    return {
        "emphasis": emphasis,
        "hiring_profile": profile,
        "candidate_fit_example": "",
    }
