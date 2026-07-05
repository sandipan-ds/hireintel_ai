"""Ranking diff: compare two rankings of the same role (DEC-026).

Given two ``List[Tuple[candidate_id, score]]`` rankings of the same role,
this module surfaces the changes between them: new entrants, departures,
per-candidate rank deltas, average and max change, and a categorical
breakdown (stable / big_swap_up / big_swap_down / only_in_baseline /
only_in_current). A separate helper pulls the versioned reasoning +
chunks from each experiment's per-resume reasoning tree for any case
worth investigating.

This is the first line of regression detection in the platform's
multi-pronged evaluation methodology (DEC-024). Aggregate metrics
(NDCG@k, MAP@k) follow in a later milestone; the per-candidate diff
runs first because it answers "which candidates moved and why" rather
than just "the ranking changed by X".
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RankingDiff:
    """Diff between two rankings of the same role.

    Attributes:
        baseline_ranking:
            ``[(candidate_id, score)]`` in baseline order (best first).
        current_ranking:
            ``[(candidate_id, score)]`` in current order (best first).
        role:
            Role name (e.g. ``"BusinessAnalyst"``). Recorded in the
            report so the diff is self-describing.
        baseline_label:
            Human-readable label for the baseline (e.g. an experiment
            folder name, ``"experiment_500_50_x_70"``).
        current_label:
            Same for the current side.
        big_swap_fraction:
            Fraction of the total candidate pool above which a rank
            change is "big". Default ``0.10`` (10% of the pool). A
            change in a 100-candidate pool is "big" if it exceeds
            10 positions; in a 50-candidate pool, 5 positions.

    The dataclass is frozen so the comparison results are deterministic
    and the CLI can hash the diff for output filenames. Methods that
    "categorize" return new containers and do not mutate ``self``.
    """

    baseline_ranking: List[Tuple[str, float]]
    current_ranking: List[Tuple[str, float]]
    role: str
    baseline_label: str
    current_label: str
    big_swap_fraction: float = 0.10

    # ------------------------------------------------------------------
    # Indexes (built on demand)
    # ------------------------------------------------------------------

    @property
    def baseline_rank(self) -> Dict[str, int]:
        """Map ``candidate_id`` → 0-indexed rank in the baseline."""
        return {c: i for i, (c, _) in enumerate(self.baseline_ranking)}

    @property
    def current_rank(self) -> Dict[str, int]:
        """Map ``candidate_id`` → 0-indexed rank in the current."""
        return {c: i for i, (c, _) in enumerate(self.current_ranking)}

    @property
    def baseline_score(self) -> Dict[str, float]:
        return {c: s for c, s in self.baseline_ranking}

    @property
    def current_score(self) -> Dict[str, float]:
        return {c: s for c, s in self.current_ranking}

    @property
    def total_candidates(self) -> int:
        """Total number of *unique* candidates across both rankings."""
        return len(
            set(c for c, _ in self.baseline_ranking)
            | set(c for c, _ in self.current_ranking)
        )

    @property
    def big_swap_threshold(self) -> int:
        """Absolute rank change above which a change is "big".

        Uses ``max(1, int(fraction * total_candidates))`` so the
        threshold is at least 1 even for tiny pools. The check in
        :meth:`categorize` is inclusive (``abs(d) >= threshold``), so a
        delta exactly equal to the threshold is "big".
        """
        return max(1, int(self.big_swap_fraction * self.total_candidates))

    # ------------------------------------------------------------------
    # Per-candidate queries
    # ------------------------------------------------------------------

    def rank_delta(self, candidate_id: str) -> Optional[int]:
        """Signed rank change: positive = moved up, negative = moved down.

        ``None`` if the candidate is in only one of the two rankings.
        Positive means the candidate is now in a *better* (lower
        numbered) position; negative means worse.
        """
        b = self.baseline_rank.get(candidate_id)
        c = self.current_rank.get(candidate_id)
        if b is None or c is None:
            return None
        return b - c

    def score_delta(self, candidate_id: str) -> Optional[float]:
        """Signed score change: positive = higher score in current."""
        b = self.baseline_score.get(candidate_id)
        c = self.current_score.get(candidate_id)
        if b is None or c is None:
            return None
        return c - b

    def shared_candidates(self) -> List[str]:
        """Candidates present in both rankings, in current order."""
        seen = set(self.baseline_rank.keys())
        return [c for c, _ in self.current_ranking if c in seen]

    def only_in_baseline(self) -> List[str]:
        return list(set(self.baseline_rank.keys()) - set(self.current_rank.keys()))

    def only_in_current(self) -> List[str]:
        return list(set(self.current_rank.keys()) - set(self.baseline_rank.keys()))

    # ------------------------------------------------------------------
    # Top-K queries
    # ------------------------------------------------------------------

    def top_k(self, ranking: str, k: int) -> List[str]:
        """Return the top-K ``candidate_id``s of the given ranking."""
        if ranking not in ("baseline", "current"):
            raise ValueError(f"ranking must be 'baseline' or 'current', got {ranking!r}")
        src = self.baseline_ranking if ranking == "baseline" else self.current_ranking
        return [c for c, _ in src[:k]]

    def new_in_top_k(self, k: int) -> List[str]:
        """Candidates in current top-K but not in baseline top-K."""
        baseline_top = set(self.top_k("baseline", k))
        return [c for c, _ in self.current_ranking[:k] if c not in baseline_top]

    def dropped_from_top_k(self, k: int) -> List[str]:
        """Candidates in baseline top-K but not in current top-K."""
        current_top = set(self.top_k("current", k))
        return [c for c, _ in self.baseline_ranking[:k] if c not in current_top]

    def rank_changes_sorted(self) -> List[Tuple[str, int]]:
        """All shared candidates, sorted by |delta| descending.

        Each entry is ``(candidate_id, signed_delta)``.
        """
        deltas = [
            (c, self.rank_delta(c))
            for c in self.shared_candidates()
        ]
        deltas.sort(key=lambda t: abs(t[1]), reverse=True)
        return deltas

    # ------------------------------------------------------------------
    # Aggregate stats
    # ------------------------------------------------------------------

    def average_rank_change(self) -> float:
        """Mean |delta| across shared candidates. ``0.0`` if no overlap."""
        deltas = [abs(self.rank_delta(c)) for c in self.shared_candidates()]
        return sum(deltas) / len(deltas) if deltas else 0.0

    def max_rank_change(self) -> Tuple[Optional[str], int]:
        """``(candidate_id, |delta|)`` for the biggest mover, or ``(None, 0)``."""
        deltas = self.rank_changes_sorted()
        if not deltas:
            return (None, 0)
        cid, delta = deltas[0]
        return (cid, abs(delta))

    # ------------------------------------------------------------------
    # Categorization
    # ------------------------------------------------------------------

    def categorize(self) -> Dict[str, List[Tuple[str, int]]]:
        """Bucket every candidate by the kind of change.

        Returns a dict with these keys:

        * ``stable`` — shared candidates with ``|delta| <= threshold``
        * ``big_swap_up`` — shared candidates that moved up by > threshold
        * ``big_swap_down`` — shared candidates that moved down by > threshold
        * ``only_in_baseline`` — present in baseline, absent in current
        * ``only_in_current`` — present in current, absent in baseline

        For ``stable``/``big_swap_up``/``big_swap_down`` each value is a
        list of ``(candidate_id, signed_delta)``. For the "only" buckets
        the delta is ``0`` (the candidate has no rank on the other side).
        """
        threshold = self.big_swap_threshold
        out: Dict[str, List[Tuple[str, int]]] = {
            "stable": [],
            "big_swap_up": [],
            "big_swap_down": [],
            "only_in_baseline": [(c, 0) for c in self.only_in_baseline()],
            "only_in_current": [(c, 0) for c in self.only_in_current()],
        }
        for cid in self.shared_candidates():
            d = self.rank_delta(cid)
            assert d is not None
            if abs(d) >= threshold:
                if d > 0:
                    out["big_swap_up"].append((cid, d))
                else:
                    out["big_swap_down"].append((cid, d))
            else:
                out["stable"].append((cid, d))
        return out

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def summary_dict(self) -> Dict[str, Any]:
        """Compact summary suitable for a top-of-report summary block."""
        threshold = self.big_swap_threshold
        return {
            "role": self.role,
            "baseline_label": self.baseline_label,
            "current_label": self.current_label,
            "total_candidates": self.total_candidates,
            "big_swap_threshold": threshold,
            "big_swap_fraction": self.big_swap_fraction,
            "new_in_top_10": self.new_in_top_k(10),
            "new_in_top_50": self.new_in_top_k(50),
            "dropped_from_top_10": self.dropped_from_top_k(10),
            "dropped_from_top_50": self.dropped_from_top_k(50),
            "shared_candidates": len(self.shared_candidates()),
            "only_in_baseline": self.only_in_baseline(),
            "only_in_current": self.only_in_current(),
            "average_abs_rank_change": round(self.average_rank_change(), 3),
            "max_rank_change": {
                "candidate": self.max_rank_change()[0],
                "delta": self.max_rank_change()[1],
            },
        }

    def case_dict(self) -> Dict[str, Any]:
        """Full per-categorization case listing."""
        cats = self.categorize()
        return {
            k: [(cid, delta) for cid, delta in sorted(v, key=lambda t: -abs(t[1]))]
            for k, v in cats.items()
        }

    def to_dict(self) -> Dict[str, Any]:
        """Full JSON-serializable representation."""
        return {
            "summary": self.summary_dict(),
            "categorization": self.case_dict(),
            "rank_changes_sorted": [
                {"candidate_id": cid, "delta": delta}
                for cid, delta in self.rank_changes_sorted()
            ],
        }


# ---------------------------------------------------------------------------
# Versioned reasoning + chunk loader (per-resume tree)
# ---------------------------------------------------------------------------


def load_reasoning(
    experiment_root: str | Path,
    role: str,
    candidate_id: str,
    req_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Load reasoning artifacts from one experiment's per-resume tree.

    The tree lives at
    ``<experiment_root>/per_candidate/<role>/<candidate_id>/reasoning/*.json``
    (DEC-022). The optional ``req_id`` filters to entries that match
    that requirement id; when ``None``, all reasoning files for the
    candidate are returned.

    Each returned dict is the parsed JSON of one
    ``<req_id>__<query_hash>.json`` file. Includes ``reasoning``,
    ``basis``, ``retrieved_chunks``, ``sub_scores``, ``model_name``,
    ``model_params``, ``retrieval_params``, ``rubric_version``,
    ``created_at``, ``schema_version``.

    Args:
        experiment_root:
            Path to the per-experiment folder, e.g.
            ``data/recursive_chunking_500_50_x_70``.
        role:
            Role name, e.g. ``"BusinessAnalyst"``.
        candidate_id:
            Candidate id (e.g. ``BusinessAnalyst_CAND_0001`` or
            legacy ``cand_<12hex>``).
        req_id:
            Optional. If given, only files whose name starts with
            ``<req_id>__`` are returned.

    Returns:
        A list of reasoning-file contents. Empty list if the directory
        does not exist (the experiment may not have run on this
        candidate yet).
    """
    base = Path(experiment_root) / "per_candidate" / role / candidate_id / "reasoning"
    if not base.is_dir():
        return []
    pattern_prefix = f"{req_id}__" if req_id else ""
    out: List[Dict[str, Any]] = []
    for path in sorted(base.glob(f"{pattern_prefix}*.json")):
        try:
            with path.open("r", encoding="utf-8") as f:
                out.append(json.load(f))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("skipping malformed reasoning file %s: %s", path, exc)
    return out


def _summarize_reasoning(reasoning: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce one reasoning file to a compact comparison-friendly form.

    Drops the full chunk text and the basis quotes (the diff report
    links to the source file for those), keeping the structural
    metadata, the model + retrieval parameters, the sub-scores, and a
    short reasoning excerpt.
    """
    text = reasoning.get("reasoning") or ""
    excerpt = text[:200] + ("..." if len(text) > 200 else "")
    return {
        "schema_version": reasoning.get("schema_version"),
        "created_at": reasoning.get("created_at"),
        "model_name": reasoning.get("model_name"),
        "model_params": reasoning.get("model_params"),
        "retrieval_params": reasoning.get("retrieval_params"),
        "rubric_version": reasoning.get("rubric_version"),
        "sub_scores": reasoning.get("sub_scores"),
        "retrieved_chunk_count": len(reasoning.get("retrieved_chunks") or []),
        "basis_count": len(reasoning.get("basis") or []),
        "reasoning_excerpt": excerpt,
    }


def _format_sub_score_value(value: Any) -> str:
    """Format a single sub-score value (which may be a dict or scalar) as a short string."""
    if isinstance(value, dict):
        v = value.get("value", "?")
        return f"{v}"
    return f"{value}"


def investigate_case(
    diff: RankingDiff,
    candidate_id: str,
    baseline_root: str | Path,
    current_root: str | Path,
    role: str,
    req_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Pull reasoning + chunks for one candidate/req from both experiments.

    Produces a side-by-side comparison record. The ``baseline`` and
    ``current`` keys are each ``{"summary": ..., "reasoning_files": [...]}``.
    The summary is a compact structural view; the full files are
    available as the ``reasoning_files`` list (for the diff CLI to
    link out to).
    """
    baseline_full = load_reasoning(baseline_root, role, candidate_id, req_id)
    current_full = load_reasoning(current_root, role, candidate_id, req_id)
    return {
        "candidate_id": candidate_id,
        "role": role,
        "req_id": req_id,
        "rank_delta": diff.rank_delta(candidate_id),
        "score_delta": diff.score_delta(candidate_id),
        "baseline": {
            "label": diff.baseline_label,
            "summary_files": [_summarize_reasoning(r) for r in baseline_full],
            "reasoning_files": baseline_full,
        },
        "current": {
            "label": diff.current_label,
            "summary_files": [_summarize_reasoning(r) for r in current_full],
            "reasoning_files": current_full,
        },
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def write_diff_report(
    diff: RankingDiff,
    json_path: str | Path,
    md_path: str | Path,
    *,
    investigations: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Write the diff report to JSON + Markdown.

    The JSON file is the canonical artifact (machine-readable, with
    the full investigation records). The Markdown file is a
    human-readable summary for code review and quick inspection.

    Args:
        diff:
            The ``RankingDiff`` to serialize.
        json_path:
            Output path for the JSON report. Parent dirs are created.
        md_path:
            Output path for the Markdown report. Parent dirs are created.
        investigations:
            Optional list of ``investigate_case`` results, one per
            candidate worth looking at. Each is included verbatim in
            the JSON and summarized in the Markdown.
    """
    payload = diff.to_dict()
    if investigations is not None:
        # Strip the verbose reasoning_files from the Markdown; keep them in JSON.
        payload["investigations"] = [
            {
                "candidate_id": inv["candidate_id"],
                "req_id": inv["req_id"],
                "rank_delta": inv["rank_delta"],
                "score_delta": inv["score_delta"],
                "baseline": {
                    "label": inv["baseline"]["label"],
                    "summary_files": inv["baseline"]["summary_files"],
                    "reasoning_files": inv["baseline"]["reasoning_files"],
                },
                "current": {
                    "label": inv["current"]["label"],
                    "summary_files": inv["current"]["summary_files"],
                    "reasoning_files": inv["current"]["reasoning_files"],
                },
            }
            for inv in investigations
        ]

    json_path = Path(json_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")

    md_path = Path(md_path)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(_render_markdown(diff, investigations or []), encoding="utf-8")


def _render_markdown(diff: RankingDiff, investigations: Sequence[Dict[str, Any]]) -> str:
    """Render the diff report as Markdown."""
    s = diff.summary_dict()
    cats = diff.case_dict()
    lines: List[str] = []
    lines.append(f"# Ranking Diff — {diff.role}")
    lines.append("")
    lines.append(f"- **Baseline:** `{diff.baseline_label}`")
    lines.append(f"- **Current:** `{diff.current_label}`")
    lines.append(f"- **Total candidates (unique):** {s['total_candidates']}")
    lines.append(
        f"- **Big-swap threshold:** > {s['big_swap_threshold']} positions "
        f"({s['big_swap_fraction']:.0%} of the pool)"
    )
    lines.append(
        f"- **Average |delta| across shared candidates:** "
        f"{s['average_abs_rank_change']:.2f}"
    )
    if s["max_rank_change"]["candidate"]:
        lines.append(
            f"- **Max |delta|:** {s['max_rank_change']['delta']} "
            f"(`{s['max_rank_change']['candidate']}`)"
        )
    lines.append("")

    # New entrants / departures
    lines.append("## Top-K entrants and departures")
    lines.append("")
    lines.append("| K | New in top-K | Dropped from top-K |")
    lines.append("| --- | --- | --- |")
    for k in (10, 50):
        new = s[f"new_in_top_{k}"]
        dropped = s[f"dropped_from_top_{k}"]
        lines.append(
            f"| {k} | {len(new)} ({', '.join(new) if new else '-'}) | "
            f"{len(dropped)} ({', '.join(dropped) if dropped else '-'}) |"
        )
    lines.append("")

    # Categorization
    lines.append("## Categorization")
    lines.append("")
    lines.append(
        f"Threshold: > {s['big_swap_threshold']} positions "
        f"= {s['big_swap_fraction']:.0%} of {s['total_candidates']} total."
    )
    lines.append("")
    lines.append("| Bucket | Count | Candidates (with signed delta) |")
    lines.append("| --- | ---: | --- |")
    for bucket in ("stable", "big_swap_up", "big_swap_down", "only_in_baseline", "only_in_current"):
        items = cats.get(bucket, [])
        label = bucket.replace("_", " ")
        if not items:
            lines.append(f"| {label} | 0 | - |")
            continue
        if bucket in ("only_in_baseline", "only_in_current"):
            rendered = ", ".join(cid for cid, _ in items)
        else:
            rendered = ", ".join(
                f"`{cid}` ({delta:+d})" for cid, delta in items
            )
        lines.append(f"| {label} | {len(items)} | {rendered} |")
    lines.append("")

    # Top movers
    lines.append("## Top 20 rank movers")
    lines.append("")
    lines.append("| Candidate | delta (positive = moved up) |")
    lines.append("| --- | ---: |")
    for cid, delta in diff.rank_changes_sorted()[:20]:
        lines.append(f"| `{cid}` | {delta:+d} |")
    lines.append("")

    # Investigations
    if investigations:
        lines.append("## Investigations")
        lines.append("")
        for inv in investigations:
            cid = inv["candidate_id"]
            rd = inv["rank_delta"]
            sd = inv["score_delta"]
            lines.append(f"### `{cid}`")
            lines.append("")
            if rd is not None:
                lines.append(f"- **Rank delta:** {rd:+d} positions")
            if sd is not None:
                lines.append(f"- **Score delta:** {sd:+.3f}")
            for side, key in (("Baseline", "baseline"), ("Current", "current")):
                side_data = inv[key]
                lines.append(f"- **{side} ({side_data['label']}):** "
                             f"{len(side_data['reasoning_files'])} reasoning file(s)")
                for sf in side_data["summary_files"]:
                    model = sf.get("model_name", "?")
                    rp = sf.get("retrieval_params", {}) or {}
                    theta = rp.get("theta", "?")
                    chunk_size = rp.get("chunk_size", "?")
                    sub_scores = sf.get("sub_scores") or {}
                    sub_score_str = ", ".join(
                        f"{k}={_format_sub_score_value(v)}"
                        for k, v in sub_scores.items()
                    )
                    lines.append(
                        f"  - `{model}` θ={theta} chunk_size={chunk_size}, "
                        f"{sf['retrieved_chunk_count']} retrieved chunks, "
                        f"{sf['basis_count']} basis quotes, sub-scores={sub_score_str}"
                    )
                    excerpt = sf.get("reasoning_excerpt", "")
                    if excerpt:
                        lines.append(f'    > {excerpt}')
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("Generated by ``src.eval.ranking_diff`` (DEC-026).")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Convenience constructors
# ---------------------------------------------------------------------------


def diff_from_pairs(
    baseline: Sequence[Tuple[str, float]],
    current: Sequence[Tuple[str, float]],
    role: str,
    baseline_label: str,
    current_label: str,
    big_swap_fraction: float = 0.10,
) -> RankingDiff:
    """Build a ``RankingDiff`` from raw ``(id, score)`` pairs.

    Convenience wrapper that does no validation; the caller is
    responsible for ordering (best-first) and uniqueness.
    """
    return RankingDiff(
        baseline_ranking=list(baseline),
        current_ranking=list(current),
        role=role,
        baseline_label=baseline_label,
        current_label=current_label,
        big_swap_fraction=big_swap_fraction,
    )


__all__ = [
    "RankingDiff",
    "load_reasoning",
    "investigate_case",
    "write_diff_report",
    "diff_from_pairs",
]
