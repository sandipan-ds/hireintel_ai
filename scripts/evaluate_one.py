"""Evaluate a single candidate and produce the per-item report format from PROJECT_OVERVIEW.md.

Usage:
    python scripts/evaluate_one.py --candidate <id_or_file_stem> --role <role>

Example:
    python scripts/evaluate_one.py --candidate 8c5959c7993cb7a1 --role BusinessAnalyst
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from hireintel_ai.core.config import Settings
from scoring.graded_scorer import (
    evaluate_candidate,
    render_evaluation_report,
    load_weights,
)


def load_profile(role: str, candidate_id_or_file: str) -> dict:
    """Load candidate profile by ID or file stem.

    Args:
        role: Role bucket.
        candidate_id_or_file: Either a file stem (e.g. '8c5959c7993cb7a1') or
            an internal candidate_id.

    Returns:
        Parsed profile dict.

    Raises:
        FileNotFoundError: If profile not found.
    """
    settings = Settings()
    profile_dir = settings.resolved_processed_data_dir / role

    if not profile_dir.exists():
        raise FileNotFoundError(f"Role directory not found: {profile_dir}")

    # Try exact match
    candidate_file = profile_dir / f"{candidate_id_or_file}.json"
    if candidate_file.exists():
        with open(candidate_file, "r", encoding="utf-8") as f:
            return json.load(f)

    # Try search by partial match
    for f in profile_dir.glob("*.json"):
        if candidate_id_or_file in f.stem:
            with open(f, "r", encoding="utf-8") as fp:
                return json.load(fp)

    raise FileNotFoundError(
        f"Profile not found for '{candidate_id_or_file}' in {profile_dir}"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate a single candidate using the per-item graded scorer."
    )
    parser.add_argument(
        "--candidate",
        required=True,
        help="Candidate ID or file stem (e.g. '8c5959c7993cb7a1').",
    )
    parser.add_argument(
        "--role",
        default="BusinessAnalyst",
        help="Role bucket (default: BusinessAnalyst).",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Optional output JSON path.",
    )

    args = parser.parse_args()

    profile = load_profile(args.role, args.candidate)
    weights = load_weights(args.role)
    evaluation = evaluate_candidate(profile, weights)

    report = render_evaluation_report(evaluation)
    print(report)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(evaluation, f, indent=2, ensure_ascii=False)
        print(f"\nDetailed evaluation saved to: {out_path}")


if __name__ == "__main__":
    main()
