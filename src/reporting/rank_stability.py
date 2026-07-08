"""Optuna ranking-stability reporter (DEC-024 Prong 6, Track 7.5).

This module measures how brittle the recruiter shortlist is across
hyperparameter perturbations during an Optuna sweep (M0.5d). The Optuna
study optimizes RAG quality (faithfulness up, ``avg_chunks_returned``
down) and has no labeled ground truth — Prong 6 is a *robustness* probe,
not a correctness gate. Its outputs are informational diagnostics that
ship with every sweep so the team can spot shortlist churn (e.g.
``theta`` nudged by 0.05 producing a wildly different top-10) before
trusting the promoted "Active" config.

Pipeline role:

    Optuna trial n ─┐
    Optuna trial n+1 ─┼─► reports/diff_rankings/optuna_study_*__rankings.json
    ...            ─┘                              │
                                                    ▼
                                       compute_rank_stability()
                                                    │
                                ┌───────────────────┴────────────────────┐
                                ▼                                        ▼
            optuna_study_*__rank_stability.json      optuna_study_*__rank_stability.md
            (structured — logged to MLflow)          (human-readable — committed to git)

Per ``EVALUATION.md`` §"Prong 6" the nine metrics below are computed
pairwise across every ``(trial_A, trial_B)`` of the same role/study,
then averaged. Unsigned magnitudes are used throughout — see the note
on the +/- cancellation problem in the spec.

The reporter is intentionally decoupled from Optuna itself: it reads a
self-describing per-study rankings JSON of the shape documented in
``EVALUATION.md`` §"Where the rankings come from". That lets the unit
tests verify every metric against synthetic fixtures without spinning
up a real study.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import kendalltau, spearmanr  # type: ignore[import-not-found]

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

#: Current schema version. Bump on any breaking change to the report shape.
SCHEMA_VERSION: str = "1.0"

#: Default top-K band used for the shortlist-churn metrics. Matches the
#: recruiter-facing shortlist the spec calls out (Prong 6 targets table).
DEFAULT_TOP_K: int = 10

#: Default wider-net top-K band (Prong 6 spec).
DEFAULT_TOP_K_WIDE: int = 50


@dataclass
class RankStabilityReport:
    """The Prong 6 metric bundle for one ``(study, role)`` pair.

    Every field is an average across all distinct trial pairs in the
    study (or a per-axis breakdown in the case of
    ``hp_axis_explained_variance``). All rank-shift magnitudes are
    unsigned — see the +/- cancellation note in the module docstring.
    """

    schema_version: str = SCHEMA_VERSION
    study_name: str = ""
    role: str = ""
    created_at: str = ""
    trial_count: int = 0
    pair_count: int = 0
    top_10_jaccard: float = 0.0
    top_50_jaccard: float = 0.0
    max_rank_shift: float = 0.0
    mean_abs_rank_shift: float = 0.0
    kendall_tau: float = 0.0
    spearman_rho: float = 0.0
    newcomer_rate_top_10: float = 0.0
    drop_rate_top_10: float = 0.0
    hp_axis_explained_variance: dict[str, float] = field(default_factory=dict)
    soft_targets: dict[str, float] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Per-pair metric primitives (pure functions — no I/O, easy to unit test)
# ---------------------------------------------------------------------------


def top_k_jaccard(
    rank_a: Sequence[str],
    rank_b: Sequence[str],
    k: int,
) -> float:
    """Jaccard similarity of the top-k candidate sets from two rankings.

    Args:
        rank_a:
            Candidate ids ordered best-to-worst by trial A.
        rank_b:
            Candidate ids ordered best-to-worst by trial B.
        k:
            Top band size (e.g. 10 or 50). Capped at the shorter
            ranking's length so an empty trial does not produce NaN.

    Returns:
        ``|A_k ∩ B_k| / |A_k ∪ B_k|`` in ``[0.0, 1.0]``. ``0.0`` when
        either side has no candidates in the band.
    """
    if k <= 0:
        return 0.0
    set_a = set(rank_a[:k])
    set_b = set(rank_b[:k])
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


def rank_shift_stats(
    rank_a: Sequence[str],
    rank_b: Sequence[str],
) -> tuple[float, float]:
    """Maximum and mean unsigned positional shift across shared candidates.

    Candidates absent from one ranking are skipped — a missing-vs-present
    case is reported by ``newcomer_rate`` / ``drop_rate``, not by the
    shift stats. This keeps the +/- cancellation problem addressed in
    the spec out of the aggregation: every value is ``|delta|``.

    Args:
        rank_a:
            Candidate ids ordered best-to-worst by trial A.
        rank_b:
            Candidate ids ordered best-to-worst by trial B.

    Returns:
        ``(max_abs_shift, mean_abs_shift)``. ``(0.0, 0.0)`` when the two
        rankings share no candidates.
    """
    pos_a = {cand: i for i, cand in enumerate(rank_a)}
    pos_b = {cand: i for i, cand in enumerate(rank_b)}
    shared = pos_a.keys() & pos_b.keys()
    if not shared:
        return 0.0, 0.0
    shifts = [abs(pos_a[c] - pos_b[c]) for c in shared]
    return float(max(shifts)), float(sum(shifts) / len(shifts))


def distribution_correlations(
    rank_a: Sequence[str],
    rank_b: Sequence[str],
) -> tuple[float, float]:
    """Kendall's tau-b and Spearman's rho between two rankings.

    Computed on the candidates present in *both* rankings (positional
    agreement is only meaningful on the shared sub-ranking). Falls back
    to ``(0.0, 0.0)`` when fewer than two shared candidates exist —
    ``scipy`` returns NaN for tiny inputs and we surface a defined zero
    instead so downstream averaging cannot go NaN.

    Args:
        rank_a:
            Candidate ids ordered best-to-worst by trial A.
        rank_b:
            Candidate ids ordered best-to-worst by trial B.

    Returns:
        ``(kendall_tau, spearman_rho)`` in ``[-1.0, 1.0]``.
    """
    pos_a = {cand: i for i, cand in enumerate(rank_a)}
    pos_b = {cand: i for i, cand in enumerate(rank_b)}
    shared = list(pos_a.keys() & pos_b.keys())
    if len(shared) < 2:
        return 0.0, 0.0
    ranks_a = np.array([pos_a[c] for c in shared], dtype=float)
    ranks_b = np.array([pos_b[c] for c in shared], dtype=float)
    tau = float(kendalltau(ranks_a, ranks_b).correlation or 0.0)
    rho = float(spearmanr(ranks_b, ranks_a).correlation or 0.0)
    if math.isnan(tau):
        tau = 0.0
    if math.isnan(rho):
        rho = 0.0
    return tau, rho


def newcomer_drop_rates(
    rank_a: Sequence[str],
    rank_b: Sequence[str],
    k: int,
) -> tuple[float, float]:
    """Symmetric top-k newcomer and drop rates for one trial pair.

    The "newcomer rate" reads trial B's top-k and asks: how many of
    those candidates were *not* in trial A's top-k? The "drop rate"
    is the symmetric counterpart — how many of A's top-k are missing
    from B's top-k? Subdividing the diagnostic (rather than reporting
    one combined number) surfaces the *direction* of shortlist churn
    and matches the spec's split-column table.

    Args:
        rank_a:
            Candidate ids ordered best-to-worst by trial A.
        rank_b:
            Candidate ids ordered best-to-worst by trial B.
        k:
            Top band size.

    Returns:
        ``(newcomer_rate, drop_rate)`` in ``[0.0, 1.0]``. ``0.0`` when
        the relevant top-k is empty. Note each side is asymmetric:
        ``newcomer_rate`` divides by ``len(B_k)``; ``drop_rate`` by
        ``len(A_k)``.
    """
    if k <= 0:
        return 0.0, 0.0
    set_a = set(rank_a[:k])
    set_b = set(rank_b[:k])
    newcomer = set_b - set_a
    dropped = set_a - set_b
    new_rate = len(newcomer) / len(set_b) if set_b else 0.0
    drop_rate = len(dropped) / len(set_a) if set_a else 0.0
    return float(new_rate), float(drop_rate)


# ---------------------------------------------------------------------------
# Study-level aggregation
# ---------------------------------------------------------------------------


def _extract_rank_pair(
    trial_a: Mapping[str, Any],
    trial_b: Mapping[str, Any],
) -> tuple[list[str], list[str]]:
    """Pull the candidate_id sequences from two trial records.

    Each trial is expected to carry a ``ranking`` list of dicts with
    ``candidate_id`` and ``rank`` keys (per ``EVALUATION.md``). We
    *sort* on ``rank`` rather than trust the input order — the Optuna
    exporter and a future hand-curated test fixture should both survive
    reordering, and sorting makes the metric deterministic.
    """
    rank_a = [
        row["candidate_id"]
        for row in sorted(trial_a.get("ranking", []), key=lambda r: r.get("rank"))
    ]
    rank_b = [
        row["candidate_id"]
        for row in sorted(trial_b.get("ranking", []), key=lambda r: r.get("rank"))
    ]
    return rank_a, rank_b


def _accumulate_pair(
    trial_a: Mapping[str, Any],
    trial_b: Mapping[str, Any],
    *,
    top_k: int,
    top_k_wide: int,
    accumulator: dict[str, float],
) -> None:
    """Accumulate per-pair metrics into a running sum/maximum dict.

    Sums the averages (jaccard, correlations, rates, mean_abs_shift) and
    takes the running max for ``max_rank_shift`` so a single violent
    pair dominates the reported maximum rather than being hidden by the
    mean — matching the spec's interpretation. The accumulator is
    mutated in place; the caller divides by ``pair_count`` at the end.
    """
    rank_a, rank_b = _extract_rank_pair(trial_a, trial_b)

    acc_j10 = top_k_jaccard(rank_a, rank_b, top_k)
    acc_j50 = top_k_jaccard(rank_a, rank_b, top_k_wide)
    acc_max, acc_mean = rank_shift_stats(rank_a, rank_b)
    acc_tau, acc_rho = distribution_correlations(rank_a, rank_b)
    acc_new, acc_drop = newcomer_drop_rates(rank_a, rank_b, top_k)

    accumulator["top_10_jaccard"] += acc_j10
    accumulator["top_50_jaccard"] += acc_j50
    accumulator["mean_abs_rank_shift"] += acc_mean
    accumulator["kendall_tau"] += acc_tau
    accumulator["spearman_rho"] += acc_rho
    accumulator["newcomer_rate_top_10"] += acc_new
    accumulator["drop_rate_top_10"] += acc_drop
    if acc_max > accumulator["max_rank_shift"]:
        accumulator["max_rank_shift"] = acc_max


def _hp_axis_explained_variance(
    trials: Sequence[Mapping[str, Any]],
    pair_metrics: Sequence[tuple[Mapping[str, Any], Mapping[str, Any], float]],
) -> dict[str, float]:
    """R^2 of ``mean_abs_rank_shift`` per hyperparameter axis.

    For each HP key present in the trial ``params`` dicts we treat the
    *absolute HP delta* between paired trials as the predictor and the
    *per-pair mean_abs_rank_shift* as the response, then compute the
    coefficient of determination (R^2). The HP with the largest R^2 is
    the dimension driving the most rank churn — that is the answer the
    spec calls "Which HP dimension drives the most rank churn?".

    The one-dimensional linear regression is computed in closed form so
    we avoid pulling in ``scikit-learn`` for what is a single-slope
    fit. The catch-all "no variation in HP axis" branch returns ``0.0``
    rather than NaN: if an HP is constant across the study, it explains
    zero of the *across-trial* variance by definition.

    Args:
        trials:
            Ordered trial records. Only used to harvest the union of
            HP keys present in the study.
        pair_metrics:
            One ``(trial_a, trial_b, mean_abs_shift)`` per trial pair.

    Returns:
        ``{"chunk_size": r2, "theta": r2, ...}`` — one entry per HP
        key, values in ``[0.0, 1.0]``.
    """
    hp_keys: set[str] = set()
    for trial in trials:
        hp_keys.update((trial.get("params") or {}).keys())

    if not pair_metrics or not hp_keys:
        return {key: 0.0 for key in sorted(hp_keys)}

    y = np.array([m for _, _, m in pair_metrics], dtype=float)
    y_mean = y.mean()
    ss_tot = float(((y - y_mean) ** 2).sum())
    if ss_tot == 0.0:
        return {key: 0.0 for key in sorted(hp_keys)}

    return {
        key: _r_squared_for_axis(key, pair_metrics, y, y_mean, ss_tot)
        for key in sorted(hp_keys)
    }


def _r_squared_for_axis(
    key: str,
    pair_metrics: Sequence[tuple[Mapping[str, Any], Mapping[str, Any], float]],
    y: np.ndarray,
    y_mean: float,
    ss_tot: float,
) -> float:
    """Closed-form R^2 of ``mean_abs_rank_shift`` against one HP axis.

    The predictor is the absolute HP delta between paired trials. When
    the HP is constant across the study (``ss_xx == 0``) the axis
    explains zero variance by definition — we return ``0.0`` rather
    than NaN so the downstream average stays finite.
    """
    x = np.array(
        [
            abs(
                float(ta.get("params", {}).get(key, 0.0))
                - float(tb.get("params", {}).get(key, 0.0))
            )
            for ta, tb, _ in pair_metrics
        ],
        dtype=float,
    )
    x_mean = x.mean()
    ss_xx = float(((x - x_mean) ** 2).sum())
    if ss_xx == 0.0:
        return 0.0
    ss_xy = float(((x - x_mean) * (y - y_mean)).sum())
    slope = ss_xy / ss_xx
    intercept = y_mean - slope * x_mean
    y_hat = slope * x + intercept
    ss_res = float(((y - y_hat) ** 2).sum())
    return max(0.0, 1.0 - ss_res / ss_tot)


# The soft targets the spec publishes for Track 7 calibration are surfaced
# verbatim in the report so a reader can compare actual vs. target without
# having to open EVALUATION.md. See EVALUATION.md §"Prong 6 Targets".
_SOFT_TARGETS: dict[str, float] = {
    "top_10_jaccard_min": 0.60,
    "max_rank_shift_max": 50.0,
    "mean_abs_rank_shift_max": 15.0,
    "kendall_tau_min": 0.60,
    "spearman_rho_min": 0.65,
    "newcomer_rate_top_10_max": 0.30,
}


def _derive_flags(report: RankStabilityReport) -> list[str]:
    """Flag violations of the published soft targets for human review.

    A flag is informational — per the spec, Prong 6 cannot block an
    Optuna promotion by itself, but a flag prompts the reviewer to
    justify the new "Active" config before merging it into
    ``MODEL_REGISTRY.md``.
    """
    flags: list[str] = []
    if report.top_10_jaccard < _SOFT_TARGETS["top_10_jaccard_min"]:
        flags.append(
            f"top_10_jaccard={report.top_10_jaccard:.3f} < "
            f"{_SOFT_TARGETS['top_10_jaccard_min']:.2f} "
            "shortlist overlap is below the soft target"
        )
    if report.max_rank_shift > _SOFT_TARGETS["max_rank_shift_max"]:
        flags.append(
            f"max_rank_shift={report.max_rank_shift:.1f} > "
            f"{_SOFT_TARGETS['max_rank_shift_max']:.0f} "
            "a candidate swings more than the soft cap across HP perturbations"
        )
    if report.mean_abs_rank_shift > _SOFT_TARGETS["mean_abs_rank_shift_max"]:
        flags.append(
            f"mean_abs_rank_shift={report.mean_abs_rank_shift:.1f} > "
            f"{_SOFT_TARGETS['mean_abs_rank_shift_max']:.0f} "
            "average positional movement exceeds the soft target"
        )
    if report.kendall_tau < _SOFT_TARGETS["kendall_tau_min"]:
        flags.append(
            f"kendall_tau={report.kendall_tau:.3f} < "
            f"{_SOFT_TARGETS['kendall_tau_min']:.2f} "
            "pairwise ordering agreement is below the soft target"
        )
    if report.spearman_rho < _SOFT_TARGETS["spearman_rho_min"]:
        flags.append(
            f"spearman_rho={report.spearman_rho:.3f} < "
            f"{_SOFT_TARGETS['spearman_rho_min']:.2f} "
            "monotonic ordering agreement is below the soft target"
        )
    if report.newcomer_rate_top_10 > _SOFT_TARGETS["newcomer_rate_top_10_max"]:
        flags.append(
            f"newcomer_rate_top_10={report.newcomer_rate_top_10:.3f} > "
            f"{_SOFT_TARGETS['newcomer_rate_top_10_max']:.2f} "
            "shortlist turnover exceeds the soft target"
        )
    return flags


def compute_rank_stability(
    study_payload: Mapping[str, Any],
    role: str | None = None,
    *,
    iso_now: str | None = None,
    top_k: int = DEFAULT_TOP_K,
    top_k_wide: int = DEFAULT_TOP_K_WIDE,
) -> RankStabilityReport:
    """Compute the full Prong 6 metric bundle for one ``(study, role)``.

    This is the pure-math entry point: it takes the parsed study JSON
    (see ``EVALUATION.md`` §"Where the rankings come from") and returns
    a populated :class:`RankStabilityReport`. No files are read or
    written. Use :func:`load_study_file` to read the JSON and
    :func:`write_stability_report` to persist.

    Args:
        study_payload:
            The parsed study JSON. Must carry ``study_name`` and a
            ``trials`` list whose entries each carry ``params`` and
            ``ranking`` (a list of ``{candidate_id, rank, ...}`` dicts).
        role:
            Optional override for ``role`` recorded in the report. If
            ``None``, ``study_payload["role"]`` is used (the field the
            Optuna exporter writes per ``EVALUATION.md``).
        iso_now:
            ISO 8601 timestamp recorded in ``created_at``. If
            ``None``, the caller is expected to inject the value
            (e.g. ``datetime.utcnow().isoformat() + "Z"``) so test
            code can pin it.
        top_k:
            Narrow top-band size for the shortlist-churn metrics.
            Default 10 per the spec.
        top_k_wide:
            Wide top-band size. Default 50 per the spec.

    Returns:
        A populated :class:`RankStabilityReport`.

    Raises:
        ValueError:
            If ``study_payload`` has no ``trials`` field or fewer
            than two trials (a single trial has nothing to be
            *stable against*).
    """
    trials = study_payload.get("trials")
    if not trials or len(trials) < 2:
        raise ValueError(
            "rank stability requires at least two trials; got "
            f"{len(trials) if trials is not None else 'None'}"
        )

    acc, pair_metrics = _accumulate_all_pairs(
        trials, top_k=top_k, top_k_wide=top_k_wide
    )

    pair_count = max(1, len(pair_metrics))
    averaged = {key: acc[key] / pair_count for key in acc}
    averaged["max_rank_shift"] = acc["max_rank_shift"]

    hp_variance = _hp_axis_explained_variance(trials, pair_metrics)

    report = RankStabilityReport(
        study_name=str(study_payload.get("study_name", "")),
        role=str(role if role is not None else study_payload.get("role", "")),
        created_at=iso_now or _now_iso(),
        trial_count=len(trials),
        pair_count=len(pair_metrics),
        top_10_jaccard=round(averaged["top_10_jaccard"], 4),
        top_50_jaccard=round(averaged["top_50_jaccard"], 4),
        max_rank_shift=round(averaged["max_rank_shift"], 2),
        mean_abs_rank_shift=round(averaged["mean_abs_rank_shift"], 4),
        kendall_tau=round(averaged["kendall_tau"], 4),
        spearman_rho=round(averaged["spearman_rho"], 4),
        newcomer_rate_top_10=round(averaged["newcomer_rate_top_10"], 4),
        drop_rate_top_10=round(averaged["drop_rate_top_10"], 4),
        hp_axis_explained_variance={
            k: round(v, 4) for k, v in hp_variance.items()
        },
        soft_targets=dict(_SOFT_TARGETS),
    )
    report.flags = _derive_flags(report)
    return report


def _accumulate_all_pairs(
    trials: Sequence[Mapping[str, Any]],
    *,
    top_k: int,
    top_k_wide: int,
) -> tuple[dict[str, float], list[tuple[Mapping[str, Any], Mapping[str, Any], float]]]:
    """Sweep every unordered trial pair, accumulate sums and the running max.

    Returns the accumulator dict (sums for averaging + running max for
    ``max_rank_shift``) and the per-pair ``(trial_a, trial_b,
    mean_abs_shift)`` list consumed by the HP-axis explained-variance
    decomposition.
    """
    acc: dict[str, float] = {
        "top_10_jaccard": 0.0,
        "top_50_jaccard": 0.0,
        "max_rank_shift": 0.0,
        "mean_abs_rank_shift": 0.0,
        "kendall_tau": 0.0,
        "spearman_rho": 0.0,
        "newcomer_rate_top_10": 0.0,
        "drop_rate_top_10": 0.0,
    }
    pair_metrics: list[tuple[Mapping[str, Any], Mapping[str, Any], float]] = []
    for trial_a, trial_b in combinations(trials, 2):
        rank_a, rank_b = _extract_rank_pair(trial_a, trial_b)
        _, pair_mean = rank_shift_stats(rank_a, rank_b)
        pair_metrics.append((trial_a, trial_b, pair_mean))
        _accumulate_pair(
            trial_a,
            trial_b,
            top_k=top_k,
            top_k_wide=top_k_wide,
            accumulator=acc,
        )
    return acc, pair_metrics


# ---------------------------------------------------------------------------
# I/O layer
# ---------------------------------------------------------------------------


# The Optuna exporter emits per-study files of the form
# "optuna_study_<study_name>__<role>__rankings.json". This regex
# captures the three segments so we can derive output paths without
# the caller having to pass them in.
_STUDY_FILE_RE = re.compile(
    r"optuna_study_(?P<study>[^_]+(?:_[^_]+)*?)__(?P<role>[A-Za-z0-9]+)__rankings\.json$"
)


def _now_iso() -> str:
    """Return the current UTC timestamp as an ISO 8601 string."""
    from datetime import datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_study_file(path: str) -> dict[str, Any]:
    """Read one per-study rankings JSON file from disk.

    Args:
        path:
            Path to a file written by the Optuna exporter (see
            ``EVALUATION.md`` §"Where the rankings come from").

    Returns:
        The parsed study JSON.

    Raises:
        FileNotFoundError:
            If ``path`` does not exist.
        ValueError:
            If the file content is not valid JSON.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"study file not found: {path}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc


def _derive_output_path(
    input_path: str,
    suffix: str,
) -> Path:
    """Return the sibling output path for a given input + suffix.

    ``optuna_study_X__BusinessAnalyst__rankings.json`` produces
    ``optuna_study_X__BusinessAnalyst__rank_stability.json`` (or
    ``.md``) alongside it. This keeps every report next to the sweep
    it diagnoses, matching the layout in MODEL_REGISTRY's diff_rankings
    row.
    """
    base = Path(input_path)
    # Strip the trailing ``__rankings.json`` (or ``.json``) so the new
    # file shares the study/role prefix.
    name = base.name
    match = _STUDY_FILE_RE.search(name)
    if match:
        stem = f"optuna_study_{match.group('study')}__{match.group('role')}"
    else:
        stem = base.stem
    return base.parent / f"{stem}__rank_stability.{suffix}"


def write_stability_report(
    report: RankStabilityReport,
    input_path: str,
) -> tuple[Path, Path]:
    """Persist ``report`` as a JSON + Markdown pair next to ``input_path``.

    Both files are written to the same directory as the input study
    file (the layout MODEL_REGISTRY.md's diff_rankings row documents)
    and are byte-identical on re-runs of the same inputs — Prong 6 is
    a deterministic aggregation over the per-trial rankings the Optuna
    exporter already committed.

    Args:
        report:
            A populated :class:`RankStabilityReport`.
        input_path:
            Path of the source ``...__rankings.json`` file. Used only
            to derive the output path; the file is not read again.

    Returns:
        ``(json_path, md_path)`` — the absolute paths written.
    """
    json_path = _derive_output_path(input_path, "json")
    md_path = _derive_output_path(input_path, "md")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(
        _render_markdown(report),
        encoding="utf-8",
    )
    return json_path, md_path


def _render_markdown(report: RankStabilityReport) -> str:
    """Render the human-readable summary a recruiter-facing reviewer reads.

    Kept intentionally dense — one short paragraph per metric group,
    with the soft-target violation surfaced as a "Flags" section so
    the reviewer can decide whether the new "Active" config needs a
    comment in MODEL_REGISTRY.md before merging.

    The body is assembled by three focused section renderers; this
    function stitches them into one document and owns only the header.
    """
    lines: list[str] = [
        f"# Rank Stability Report — {report.study_name} / {report.role}",
        "",
        f"- **Schema version:** {report.schema_version}",
        f"- **Created at:** {report.created_at}",
        f"- **Trials:** {report.trial_count}",
        f"- **Pairs compared:** {report.pair_count}",
    ]
    lines.extend(_render_metric_sections(report))
    lines.extend(_render_hp_axis_table(report))
    lines.extend(_render_flags_section(report))
    lines.append("")
    return "\n".join(lines)


def _render_metric_sections(report: RankStabilityReport) -> list[str]:
    """The four metric-group blocks: overlap, movement, shape, churn.

    Each block opens with an H2 header and lists its metric(s) with the
    soft target inline, so the reviewer can compare actual vs. published
    target without opening EVALUATION.md.
    """
    return [
        "",
        "## Shortlist overlap",
        "",
        f"- **top_10_jaccard:** `{report.top_10_jaccard:.4f}` "
        f"(soft target ≥ {_SOFT_TARGETS['top_10_jaccard_min']:.2f})",
        f"- **top_50_jaccard:** `{report.top_50_jaccard:.4f}`",
        "",
        "## Positional movement",
        "",
        f"- **max_rank_shift:** `{report.max_rank_shift:.2f}` "
        f"(soft target ≤ {_SOFT_TARGETS['max_rank_shift_max']:.0f})",
        f"- **mean_abs_rank_shift:** `{report.mean_abs_rank_shift:.4f}` "
        f"(soft target ≤ {_SOFT_TARGETS['mean_abs_rank_shift_max']:.0f})",
        "",
        "## Distribution shape agreement",
        "",
        f"- **kendall_tau:** `{report.kendall_tau:.4f}` "
        f"(soft target ≥ {_SOFT_TARGETS['kendall_tau_min']:.2f})",
        f"- **spearman_rho:** `{report.spearman_rho:.4f}` "
        f"(soft target ≥ {_SOFT_TARGETS['spearman_rho_min']:.2f})",
        "",
        "## Shortlist churn",
        "",
        f"- **newcomer_rate_top_10:** `{report.newcomer_rate_top_10:.4f}` "
        f"(soft target ≤ {_SOFT_TARGETS['newcomer_rate_top_10_max']:.2f})",
        f"- **drop_rate_top_10:** `{report.drop_rate_top_10:.4f}`",
    ]


def _render_hp_axis_table(report: RankStabilityReport) -> list[str]:
    """The HP-axis explained-variance table — sorted by descending R^2."""
    if not report.hp_axis_explained_variance:
        return []
    lines: list[str] = [
        "",
        "## HP axis explained variance (R^2 of mean_abs_rank_shift)",
        "",
        "| HP axis | R^2 |",
        "| --- | ---: |",
    ]
    for axis, value in sorted(
        report.hp_axis_explained_variance.items(),
        key=lambda kv: -kv[1],
    ):
        lines.append(f"| `{axis}` | `{value:.4f}` |")
    return lines


def _render_flags_section(report: RankStabilityReport) -> list[str]:
    """The Flags section surfaced only when soft targets are violated."""
    if not report.flags:
        return []
    return [
        "",
        "## Flags (informational — review before promotion)",
        "",
        *[f"- {flag}" for flag in report.flags],
    ]


__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_TOP_K",
    "DEFAULT_TOP_K_WIDE",
    "RankStabilityReport",
    "top_k_jaccard",
    "rank_shift_stats",
    "distribution_correlations",
    "newcomer_drop_rates",
    "compute_rank_stability",
    "load_study_file",
    "write_stability_report",
]