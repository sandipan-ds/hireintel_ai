#!/usr/bin/env python3
"""Evaluate score variance, standard deviation, and sub-score floor rate (SFR) across roles.

Scans data/scores/composed/ for:
1. Individual candidate JSON files: data/scores/composed/<Role>/<Role>_CAND_<ID>.json
2. Final aggregated ranked files: data/scores/composed/<Role>_ranked.json

Aggregates scores, computes stats (Min, Max, Avg, Std Dev, Variance), and calculates
the percentage of requirements scoring strictly less than 0.25 (Sub-Score Floor Rate).
Also identifies specific requirements that are frequently failing (SFR >= 30%).

Roles with 0 scored candidates are omitted from the main table and shown separately
under "Not yet scored" so the report only reflects actual results.
"""

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_SCORES_DIR = ROOT / "data/scores/composed"

# Downstream artefact files that live in role subdirs but are not candidate scores.
DOWNSTREAM_SUFFIXES: Tuple[str, ...] = (
    "_intelligence_report.json",
    "_structured_profile.json",
    "_ranked.json",
)


def _is_downstream(name: str) -> bool:
    return any(name.endswith(s) for s in DOWNSTREAM_SUFFIXES)


def calculate_stats(scores: List[float], req_scores: List[float]) -> Dict[str, Any]:
    """Compute descriptive statistics and Sub-Score Floor Rate (< 0.25)."""
    n = len(scores)
    if n == 0:
        return {"count": 0, "min": 0.0, "max": 0.0, "avg": 0.0,
                "std": 0.0, "var": 0.0, "sfr": 0.0}

    min_val = min(scores)
    max_val = max(scores)
    avg_val = sum(scores) / n
    variance = sum((x - avg_val) ** 2 for x in scores) / (n - 1) if n > 1 else 0.0
    std_val = math.sqrt(variance)

    sfr = 0.0
    if req_scores:
        sfr = sum(1 for s in req_scores if s < 0.25) / len(req_scores) * 100

    hi2 = sum(1 for x in scores if x > avg_val + 2 * std_val)
    lo2 = sum(1 for x in scores if x < avg_val - 2 * std_val)

    return {"count": n, "min": min_val, "max": max_val, "avg": avg_val,
            "std": std_val, "var": variance, "sfr": sfr,
            "hi2": hi2, "lo2": lo2}


def collect_scores(
    base_dir: Path,
) -> Tuple[
    Dict[str, Dict[str, Any]],          # role -> cand_id -> {total, reqs}
    Dict[str, Dict[str, List[float]]],  # role -> req_id  -> [sub_scores]
    Dict[str, int],                     # role -> total candidate files on disk
]:
    role_candidates: Dict[str, Dict[str, Any]] = {}
    role_req_details: Dict[str, Dict[str, List[float]]] = {}
    total_per_role: Dict[str, int] = defaultdict(int)
    seen: Dict[str, Set[str]] = defaultdict(set)

    if not base_dir.exists():
        print(f"Warning: {base_dir} does not exist.", file=sys.stderr)
        return role_candidates, role_req_details, total_per_role

    def _add(role: str, cand_id: str, total_score: float,
             reqs_list: List[Dict[str, Any]]) -> None:
        if role not in role_candidates:
            role_candidates[role] = {}
            role_req_details[role] = defaultdict(list)
        if cand_id in seen[role]:
            return
        seen[role].add(cand_id)
        reqs_dict: Dict[str, float] = {}
        for r in reqs_list:
            req_id = r.get("requirement_id")
            sub_score = r.get("sub_score")
            if req_id is not None and sub_score is not None:
                v = float(sub_score)
                reqs_dict[req_id] = v
                role_req_details[role][req_id].append(v)
        role_candidates[role][cand_id] = {"total": float(total_score), "reqs": reqs_dict}

    # 1. Per-candidate files (authoritative).
    for subdir in sorted(base_dir.iterdir()):
        if not subdir.is_dir():
            continue
        role = subdir.name
        for f in sorted(subdir.glob("*.json")):
            if _is_downstream(f.name):
                continue
            total_per_role[role] += 1
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                cand_id = data.get("candidate_id")
                total = data.get("total")
                if cand_id and total is not None:
                    _add(role, cand_id, total, data.get("reqs") or [])
            except Exception as e:
                print(f"  Warning: {f.name}: {e}", file=sys.stderr)

    # 2. Ranked files — fallback only (no double-counting toward total).
    for rf in sorted(base_dir.glob("*_ranked.json")):
        role = rf.name.replace("_ranked.json", "")
        try:
            data = json.loads(rf.read_text(encoding="utf-8"))
            for entry in (data.get("rankings") or []):
                cand_id = entry.get("candidate_id")
                total = entry.get("total")
                if cand_id and total is not None:
                    _add(role, cand_id, total, entry.get("reqs") or [])
        except Exception as e:
            print(f"  Warning: {rf.name}: {e}", file=sys.stderr)

    return role_candidates, role_req_details, total_per_role


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate scorer variance and Sub-Score Floor Rate."
    )
    parser.add_argument(
        "--dir", default=str(DEFAULT_SCORES_DIR),
        help=f"Scores directory (default: {DEFAULT_SCORES_DIR})",
    )
    args = parser.parse_args()

    scores_dir = Path(args.dir)
    print(f"Scanning score files in: {scores_dir}\n")

    role_candidates, role_req_details, total_per_role = collect_scores(scores_dir)

    all_roles = sorted(set(list(role_candidates.keys()) + list(total_per_role.keys())))
    scored_roles = [r for r in all_roles if role_candidates.get(r)]
    pending_roles = [r for r in all_roles if not role_candidates.get(r)]

    if not scored_roles and not pending_roles:
        print("No scores found.")
        return

    # ------------------------------------------------------------------
    # Main table — only roles with at least 1 scored candidate.
    # ------------------------------------------------------------------
    header = (
        f"{'Role':<22} | {'Scored':<8} | {'Min':<7} | {'Max':<7} | "
        f"{'Mean':<7} | {'Std Dev':<7} | {'Variance':<8} | {'SFR <0.25':<10} | "
        f"{'> +2s':<7} | {'< -2s':<7}"
    )
    print(header)
    print("-" * len(header))

    all_totals: List[float] = []
    all_reqs: List[float] = []

    for role in scored_roles:
        candidates = role_candidates[role]
        totals = [c["total"] for c in candidates.values()]
        reqs: List[float] = []
        for c in candidates.values():
            reqs.extend(c["reqs"].values())

        all_totals.extend(totals)
        all_reqs.extend(reqs)

        s = calculate_stats(totals, reqs)
        print(
            f"{role:<22} | {s['count']:<8d} | {s['min']:<7.2f} | {s['max']:<7.2f} | "
            f"{s['avg']:<7.2f} | {s['std']:<7.2f} | {s['var']:<8.2f} | {s['sfr']:<9.1f}% | "
            f"{s['hi2']:<7d} | {s['lo2']:<7d}"
        )

    print("-" * len(header))
    all_valid = sum(len(v) for v in role_candidates.values())
    ov = calculate_stats(all_totals, all_reqs)
    if ov["count"] > 0:
        print(
            f"{'OVERALL (scored)':<22} | {all_valid:<8d} | {ov['min']:<7.2f} | {ov['max']:<7.2f} | "
            f"{ov['avg']:<7.2f} | {ov['std']:<7.2f} | {ov['var']:<8.2f} | {ov['sfr']:<9.1f}% | "
            f"{ov['hi2']:<7d} | {ov['lo2']:<7d}"
        )

    # ------------------------------------------------------------------
    # Not-yet-started roles.
    # ------------------------------------------------------------------
    if pending_roles:
        print("\nNot yet scored:")
        for role in pending_roles:
            print(f"  {role:<22}  ({total_per_role.get(role, 0)} files on disk)")

    # ------------------------------------------------------------------
    # Suspect requirements breakdown.
    # ------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("SUSPECT REQUIREMENTS BREAKDOWN (SFR < 0.25 >= 30%)")
    print("=" * 80)

    any_suspect = False
    for role in sorted(role_req_details.keys()):
        suspects = []
        for req_id, scores in role_req_details[role].items():
            n = len(scores)
            if n > 0:
                fails = sum(1 for s in scores if s < 0.25)
                pct = fails / n * 100
                if pct >= 30.0:
                    suspects.append((req_id, pct, fails, n))
        if suspects:
            any_suspect = True
            print(f"\nRole: {role}")
            print(f"  {'Requirement ID':<15} | {'Floor Rate (< 0.25)':<22} | {'Counts (Floored/Scored)':<22}")
            print(f"  {'-'*15}-+-{'-'*22}-+-{'-'*22}")
            for req_id, pct, fails, total in sorted(suspects, key=lambda x: -x[1]):
                print(f"  {req_id:<15} | {pct:<20.1f}% | {f'{fails}/{total}':<22}")
            print()

    if not any_suspect:
        print("\nNo requirements with >= 30% floor rate. Scoring coverage looks healthy.")
        print()


if __name__ == "__main__":
    main()
