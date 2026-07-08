#!/usr/bin/env python
"""Diff two rankings of the same role (DEC-026).

Compares the ranked output of two experiment folders (or any two
``(candidate_id, score)`` lists) for a given role. Reports:

1. New entrants to top-K (K=10, 50)
2. Departures from top-K
3. Average and max rank change
4. Categorization (stable / big_swap_up / big_swap_down / only_in_baseline / only_in_current)
5. For each notable case, a side-by-side dump of the rubric-bound
   LLM's reasoning, basis, retrieved chunks, and sub-scores from each
   experiment's per-resume reasoning tree (DEC-022).

The output is a JSON + Markdown pair at
``reports/diff_rankings/<baseline>__vs__<current>__<role>.{json,md}``,
committed to git so the diff is part of the project's historical
record.

Usage::

    # Diff two experiment folders for a single role, load rankings from
    # the canonical ranked score files.
    python -m scripts.diff_rankings \\
        --baseline data/recursive_chunking_500_50_x_70 \\
        --current  data/recursive_chunking_300_50_x_70 \\
        --role     BusinessAnalyst

    # Diff two explicit score files (older / non-experiment layouts).
    python -m scripts.diff_rankings \\
        --baseline data/scores/graded/BusinessAnalyst_ranked.json \\
        --current  data/scores/graded_v2/BusinessAnalyst_ranked.json \\
        --role     BusinessAnalyst

    # Pass rankings directly via stdin (one ``candidate_id`` per line;
    # scores are ignored if the file has no scores, only ids).
    python -m scripts.diff_rankings \\
        --baseline-id-file ids_a.txt --current-id-file ids_b.txt \\
        --role BusinessAnalyst

The diff is what the team runs after every config promotion to inspect
which candidates actually moved. It does not gate promotion; it
diagnoses it (per DEC-026).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple


# Make ``src`` importable when running this script directly.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.eval.ranking_diff import (  # noqa: E402
    RankingDiff,
    diff_from_pairs,
    investigate_case,
    write_diff_report,
)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


def _normalize_label(s: str) -> str:
    """Turn a path-like string into a safe file-name label."""
    return (
        s.replace("\\", "_")
        .replace("/", "_")
        .replace(":", "_")
        .replace(" ", "_")
        .strip("_")
    )


def _load_ranking_from_json(path: Path, role: str) -> List[Tuple[str, float]]:
    """Load ``[(candidate_id, score)]`` from a JSON score file.

    Supports two common layouts:
    - ``{"ranked": [{"candidate_id": "...", "score": ...}, ...]}``
    - ``{"candidates": [{"id": "...", "score": ...}, ...]}``
    - ``[{"candidate_id": "...", "score": ...}, ...]``  (list at top level)
    - ``{"scores": {"<candidate_id>": <score>, ...}}``  (dict of scores)
    """
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        items = data
    else:
        items = (
            data.get("ranked")
            or data.get("candidates")
            or data.get("results")
            or []
        )
    out: List[Tuple[str, float]] = []
    if items and isinstance(items[0], dict):
        for it in items:
            cid = it.get("candidate_id") or it.get("id") or it.get("candidate")
            if not cid:
                continue
            score = it.get("score")
            if score is None and "scores" in data and isinstance(data["scores"], dict):
                score = data["scores"].get(cid)
            score = float(score) if score is not None else 0.0
            out.append((cid, score))
        return out
    # ``{"scores": {cid: score, ...}}`` shape
    scores = data.get("scores") if isinstance(data, dict) else None
    if isinstance(scores, dict):
        # We don't know the order from a score-dict; we use the role's
        # ``candidates`` list if present, else the sorted-by-score order
        # of the dict (best first).
        cands = data.get("candidates") or list(scores.keys())
        scored = sorted(
            ((c, float(scores.get(c, 0.0))) for c in cands),
            key=lambda t: -t[1],
        )
        return scored
    return out


def _load_id_file(path: Path) -> List[Tuple[str, float]]:
    """Load rankings from a plain text file (one id per line).

    Lines starting with ``#`` and empty lines are ignored. When scores
    are present as ``<id>\\t<score>`` they are used; otherwise the
    score is 0.0 and the file order is the ranking order.
    """
    out: List[Tuple[str, float]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            cid, score_str = line.split("\t", 1)
            try:
                score = float(score_str)
            except ValueError:
                score = 0.0
        else:
            cid = line
            score = 0.0
        out.append((cid, score))
    return out


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _resolve_inputs(args: argparse.Namespace) -> Tuple[List[Tuple[str, float]], List[Tuple[str, float]], str, str, Path, Path]:
    """Return ``(baseline, current, baseline_label, current_label, baseline_root, current_root)``.

    ``baseline_root`` / ``current_root`` are the per-experiment roots
    for the investigation step (or ``/nonexistent`` if not applicable).
    """
    if args.baseline_id_file or args.current_id_file:
        if not (args.baseline_id_file and args.current_id_file):
            raise SystemExit("both --baseline-id-file and --current-id-file are required when using id-files")
        baseline = _load_id_file(Path(args.baseline_id_file))
        current = _load_id_file(Path(args.current_id_file))
        baseline_label = _normalize_label(args.baseline_id_file)
        current_label = _normalize_label(args.current_id_file)
        # Use the explicit experiment roots if provided; otherwise fall
        # back to /nonexistent (the CLI's investigation step will
        # report "0 reasoning files", which is the right behavior when
        # no experiment root is available).
        bl_root = Path(args.baseline_experiment_root) if args.baseline_experiment_root else Path("/nonexistent")
        cl_root = Path(args.current_experiment_root) if args.current_experiment_root else Path("/nonexistent")
        return baseline, current, baseline_label, current_label, bl_root, cl_root

    if not (args.baseline and args.current):
        raise SystemExit("provide --baseline/--current (score files or experiment folders) or --baseline-id-file/--current-id-file")

    baseline_path = Path(args.baseline)
    current_path = Path(args.current)

    # If the path looks like an experiment folder, find the canonical
    # ranked score file inside. Otherwise treat it as a direct score
    # file.
    def _resolve_ranked(exp_or_file: Path, role: str) -> Tuple[List[Tuple[str, float]], Optional[Path]]:
        if (exp_or_file / "data").is_dir() or (exp_or_file / "per_candidate").is_dir():
            # looks like an experiment root; use the experiment's ranked
            # score file at ``data/scores/graded/<role>_ranked.json``
            candidate = exp_or_file / "data" / "scores" / "graded" / f"{role}_ranked.json"
            if candidate.is_file():
                return _load_ranking_from_json(candidate, role), exp_or_file
            # Try a different layout
            for sub in exp_or_file.rglob(f"{role}_ranked.json"):
                return _load_ranking_from_json(sub, role), exp_or_file
            raise FileNotFoundError(
                f"no ranked score file found under {exp_or_file} for role {role}"
            )
        # Direct score file.
        return _load_ranking_from_json(exp_or_file, role), None

    baseline, baseline_exp = _resolve_ranked(baseline_path, args.role)
    current, current_exp = _resolve_ranked(current_path, args.role)
    # Explicit experiment roots override auto-detection.
    bl_root = Path(args.baseline_experiment_root) if args.baseline_experiment_root else (baseline_exp or Path("/nonexistent"))
    cl_root = Path(args.current_experiment_root) if args.current_experiment_root else (current_exp or Path("/nonexistent"))

    baseline_label = _normalize_label(args.baseline)
    current_label = _normalize_label(args.current)
    return baseline, current, baseline_label, current_label, bl_root, cl_root


def _cases_to_investigate(diff: RankingDiff) -> List[str]:
    """Return the list of candidate ids worth a per-case investigation."""
    cases: List[str] = []
    cases.extend(diff.new_in_top_k(10))
    cases.extend(diff.only_in_current())
    cats = diff.categorize()
    cases.extend(cid for cid, _ in cats["big_swap_up"])
    cases.extend(cid for cid, _ in cats["big_swap_down"])
    # Dedup but preserve order.
    seen: set = set()
    out: List[str] = []
    for cid in cases:
        if cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Diff two rankings of the same role (DEC-026)."
    )
    parser.add_argument(
        "--baseline",
        help="Path to the baseline ranking. Either a JSON score file or an experiment folder.",
    )
    parser.add_argument(
        "--current",
        help="Path to the current ranking. Same layout as --baseline.",
    )
    parser.add_argument(
        "--baseline-id-file",
        help="Plain-text file of candidate ids (one per line) for the baseline. Use this if you don't have a score file.",
    )
    parser.add_argument(
        "--current-id-file",
        help="Plain-text file of candidate ids for the current.",
    )
    parser.add_argument(
        "--role",
        required=True,
        help="Role name (e.g. BusinessAnalyst). Used to locate score files and the per-resume tree.",
    )
    parser.add_argument(
        "--baseline-experiment-root",
        help="Path to the baseline experiment root (with per_candidate/<role>/<id>/reasoning/). "
             "Auto-detected from --baseline when --baseline is an experiment folder; required when "
             "--baseline is a score file and you want the per-case investigation to find reasoning files.",
    )
    parser.add_argument(
        "--current-experiment-root",
        help="Path to the current experiment root. Same auto-detect rules as --baseline-experiment-root.",
    )
    parser.add_argument(
        "--out-dir",
        default="reports/diff_rankings",
        help="Output directory for the JSON + Markdown report (default: reports/diff_rankings).",
    )
    parser.add_argument(
        "--big-swap-fraction",
        type=float,
        default=0.10,
        help="Fraction of the pool above which a rank change is 'big' (default: 0.10).",
    )
    parser.add_argument(
        "--req-id",
        help="Optional. If given, investigation pulls only reasoning files for this requirement id.",
    )
    parser.add_argument(
        "--max-investigations",
        type=int,
        default=10,
        help="Cap on the number of per-case investigations (default: 10). Use 0 to skip.",
    )
    args = parser.parse_args(argv)

    baseline, current, bl_label, cl_label, bl_root, cl_root = _resolve_inputs(args)

    diff = diff_from_pairs(
        baseline=baseline,
        current=current,
        role=args.role,
        baseline_label=bl_label,
        current_label=cl_label,
        big_swap_fraction=args.big_swap_fraction,
    )

    summary = diff.summary_dict()
    print(f"=== Ranking diff: {bl_label} -> {cl_label} ({args.role}) ===")
    print(f"  total candidates (unique): {summary['total_candidates']}")
    print(f"  big_swap_threshold: > {summary['big_swap_threshold']} positions")
    print(f"  new_in_top_10: {summary['new_in_top_10']}")
    print(f"  dropped_from_top_10: {summary['dropped_from_top_10']}")
    print(f"  new_in_top_50: {summary['new_in_top_50']}")
    print(f"  dropped_from_top_50: {summary['dropped_from_top_50']}")
    print(f"  only_in_baseline: {summary['only_in_baseline']}")
    print(f"  only_in_current:  {summary['only_in_current']}")
    print(f"  average |delta|:   {summary['average_abs_rank_change']:.2f}")
    print(f"  max |delta|:       {summary['max_rank_change']['delta']} ({summary['max_rank_change']['candidate']})")
    cats = diff.categorize()
    for bucket, items in cats.items():
        if not items:
            continue
        sample = ", ".join(f"{cid}({delta:+d})" for cid, delta in items[:5])
        print(f"  {bucket} ({len(items)}): {sample}")

    # Per-case investigations
    investigations: List[dict] = []
    if args.max_investigations > 0:
        cases = _cases_to_investigate(diff)[: args.max_investigations]
        for cid in cases:
            try:
                inv = investigate_case(
                    diff,
                    cid,
                    baseline_root=bl_root,
                    current_root=cl_root,
                    role=args.role,
                    req_id=args.req_id,
                )
            except Exception as exc:  # pragma: no cover - defensive
                print(f"  warn: investigation failed for {cid}: {exc}", file=sys.stderr)
                continue
            investigations.append(inv)
            files_b = len(inv["baseline"]["reasoning_files"])
            files_c = len(inv["current"]["reasoning_files"])
            print(f"  investigated {cid}: baseline={files_b} file(s), current={files_c} file(s)")

    # Write report
    out_dir = Path(args.out_dir)
    filename_base = f"{_normalize_label(bl_label)}__vs__{_normalize_label(cl_label)}__{args.role}"
    json_path = out_dir / f"{filename_base}.json"
    md_path = out_dir / f"{filename_base}.md"
    write_diff_report(diff, json_path, md_path, investigations=investigations)
    print(f"  -> {json_path}")
    print(f"  -> {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
