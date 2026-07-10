"""Unit tests for the Optuna ranking-stability reporter (DEC-024 Prong 6).

Tests cover the per-pair primitives (identity, total disjoint, single
large jump, partial overlap) and the study-level aggregation, including
HP-axis explained-variance decomposition and end-to-end I/O. Synthetic
fixtures are used throughout so the suite is hermetic — no real Optuna
study or labeled ground truth is required.
"""

import json

import pytest

from src.reporting.rank_stability import (
    SCHEMA_VERSION,
    RankStabilityReport,
    compute_rank_stability,
    distribution_correlations,
    load_study_file,
    newcomer_drop_rates,
    rank_shift_stats,
    top_k_jaccard,
    write_stability_report,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _ranking(candidate_ids):
    """Build a trial ``ranking`` list shaped like the Optuna export.

    The export writes ``[{"candidate_id", "total_score", "rank"}, ...]``
    per ``EVALUATION.md`` §"Where the rankings come from". We pin ``rank``
    to the iteration index so the reporter's internal sort is stable
    regardless of the input order.
    """
    return [
        {"candidate_id": cid, "total_score": 100.0 - i, "rank": i + 1}
        for i, cid in enumerate(candidate_ids)
    ]


def _trial(number, ranking_ids, params):
    """Build a minimal trial record."""
    return {
        "trial_number": number,
        "params": params,
        "ranking": _ranking(ranking_ids),
    }


@pytest.fixture
def hundred_candidates():
    """A 100-candidate pool shared across the tiered-perturbation tests."""
    return [f"CAND_{i:03d}" for i in range(100)]


@pytest.fixture
def two_identical_trials(hundred_candidates):
    """Two trials with identical rankings → every stability metric at its
    "perfectly stable" extreme."""
    return [
        _trial(0, hundred_candidates, {"chunk_size": 1000, "theta": 0.25}),
        _trial(1, hundred_candidates, {"chunk_size": 1000, "theta": 0.25}),
    ]


@pytest.fixture
def two_disjoint_top10_trials(hundred_candidates):
    """Two trials with no overlap in their top-10 → jaccard 0, churn 1."""
    # Trial A ranks the first 100 candidates; trial B rotates the first
    # 20 to the back so B's top-10 is fully disjoint from A's top-10.
    rotated = hundred_candidates[20:] + hundred_candidates[:20]
    return [
        _trial(0, hundred_candidates, {"chunk_size": 1000, "theta": 0.25}),
        _trial(1, rotated, {"chunk_size": 1000, "theta": 0.30}),
    ]


@pytest.fixture
def single_jump_trials(hundred_candidates):
    """One candidate jumps from rank 50 to rank 5 → max shift 45."""
    moved = hundred_candidates[49]  # candidate at rank 50 (1-indexed)
    rest = [c for c in hundred_candidates if c != moved]
    # Insert at index 4 → rank 5 (1-indexed).
    after_jump = rest[:4] + [moved] + rest[4:]
    return [
        _trial(0, hundred_candidates, {"chunk_size": 1000, "theta": 0.25}),
        _trial(1, after_jump, {"chunk_size": 1000, "theta": 0.25}),
    ]


# ---------------------------------------------------------------------------
# Per-pair primitives
# ---------------------------------------------------------------------------


def test_identical_rankings_are_perfectly_stable():
    """Identical rankings report no churn and perfect agreement."""
    rank = [f"c{i}" for i in range(20)]
    assert top_k_jaccard(rank, rank, 10) == 1.0
    assert top_k_jaccard(rank, rank, 50) == 1.0
    assert rank_shift_stats(rank, rank) == (0.0, 0.0)
    assert distribution_correlations(rank, rank) == (1.0, 1.0)
    assert newcomer_drop_rates(rank, rank, 10) == (0.0, 0.0)


def test_disjoint_top10_produces_zero_jaccard_and_full_churn():
    """Top-10 disjoint ⇒ jaccard 0, newcomer+drop = 1.0."""
    a = [f"a{i}" for i in range(10)]
    b = [f"b{i}" for i in range(10)]
    assert top_k_jaccard(a, b, 10) == 0.0
    new, drop = newcomer_drop_rates(a, b, 10)
    assert new == 1.0
    assert drop == 1.0
    # Shared candidates is empty ⇒ shift stats and correlations are the
    # documented "no overlap" sentinels, not NaN.
    assert rank_shift_stats(a, b) == (0.0, 0.0)
    assert distribution_correlations(a, b) == (0.0, 0.0)


def test_single_jump_max_shift_is_45(hundred_candidates, single_jump_trials):
    """Moving rank-50 → rank-5 surfaces max_rank_shift = 45.

    This pins the spec's "max positional movement" example: a candidate
    at rank 50 jumping to rank 5 produces |50 - 5| = 45 positions of
    swing. The mean is diluted across the 99 shared candidates because
    only one of them moves; the max is the loudest signal and must not
    be averaged away.
    """
    trial_a, trial_b = single_jump_trials
    rank_a, rank_b = trial_a["ranking"], trial_b["ranking"]
    ids_a = [row["candidate_id"] for row in rank_a]
    ids_b = [row["candidate_id"] for row in rank_b]
    max_shift, mean_shift = rank_shift_stats(ids_a, ids_b)
    assert max_shift == 45.0
    # Exactly one candidate moves by 45, 99 are unchanged at indices
    # above 5 and indices 5..49 shift by exactly 1 position.
    assert mean_shift == pytest.approx(45.0 / 100 + 45.0 / 100, abs=0.05)
    # The moved candidate is c49 (0-indexed) → CAND_049.
    assert "CAND_049" in ids_b[:5]


# ---------------------------------------------------------------------------
# Study-level aggregation
# ---------------------------------------------------------------------------


def test_compute_identical_study_is_perfectly_stable(two_identical_trials):
    """Two trials with identical rankings produce a report at the stable
    extremes: jaccard 1, max shift 0, kendall/spearman 1, newcomer 0."""
    study = {
        "study_name": "smoke",
        "role": "DataScience",
        "trials": two_identical_trials,
    }
    report = compute_rank_stability(study, iso_now="2026-07-08T00:00:00Z")
    assert isinstance(report, RankStabilityReport)
    assert report.schema_version == SCHEMA_VERSION
    assert report.study_name == "smoke"
    assert report.role == "DataScience"
    assert report.created_at == "2026-07-08T00:00:00Z"
    assert report.trial_count == 2
    assert report.pair_count == 1
    assert report.top_10_jaccard == 1.0
    assert report.top_50_jaccard == 1.0
    assert report.max_rank_shift == 0.0
    assert report.mean_abs_rank_shift == 0.0
    assert report.kendall_tau == 1.0
    assert report.spearman_rho == 1.0
    assert report.newcomer_rate_top_10 == 0.0
    assert report.drop_rate_top_10 == 0.0
    # Identical params ⇒ every HP axis has zero variation ⇒ R^2 = 0.
    assert report.hp_axis_explained_variance == {"chunk_size": 0.0, "theta": 0.0}
    # Perfect stability ⇒ no soft-target violations.
    assert report.flags == []


def test_compute_disjoint_top10_surfaces_churn_flags(two_disjoint_top10_trials):
    """Disjoint top-10 ⇒ low jaccard, full churn, and the flags section
    lists every soft-target violation surfaced by _derive_flags."""
    study = {
        "study_name": "fragile_sweep",
        "role": "BusinessAnalyst",
        "trials": two_disjoint_top10_trials,
    }
    report = compute_rank_stability(study, iso_now="2026-07-08T00:00:00Z")
    assert report.top_10_jaccard == 0.0
    assert report.newcomer_rate_top_10 == 1.0
    assert report.drop_rate_top_10 == 1.0
    # The top-10 jaccard collapse + newcomer churn must appear in flags.
    flag_text = " ".join(report.flags)
    assert "top_10_jaccard" in flag_text
    assert "newcomer_rate" in flag_text


def test_hp_axis_explained_variance_isolates_theta_driver(hundred_candidates):
    """Vary only ``theta`` between trials ⇒ theta dominates the R^2,
    chunk_size explains nothing.

    Three trials, identical chunking, theta swept across a narrow band.
    A_realisitic rank shuffle is induced by rotating the bottom of the
    pool by a theta-proportional offset. The reporter should return
    ``theta``'s R^2 strictly greater than ``chunk_size``'s (which has
    no variation across the study).
    """
    base = hundred_candidates
    trials = []
    for i, theta in enumerate((0.20, 0.25, 0.30)):
        # Rotate by ``i * 5`` positions so larger theta deltas ⇒ larger
        # rank churn. chunk_size stays constant.
        rotated = base[i * 5:] + base[: i * 5]
        trials.append(_trial(i, rotated, {"chunk_size": 1000, "theta": theta}))
    study = {"study_name": "theta_driver", "role": "WebDesigning", "trials": trials}
    report = compute_rank_stability(study, iso_now="2026-07-08T00:00:00Z")
    explained = report.hp_axis_explained_variance
    assert "theta" in explained
    assert "chunk_size" in explained
    # chunk_size is constant ⇒ R^2 = 0; theta varies ⇒ R^2 ≥ 0.
    assert explained["chunk_size"] == 0.0
    assert explained["theta"] > 0.0


def test_compute_rank_stability_requires_two_trials():
    """A study with one trial has nothing to compare against ⇒ ValueError.
    A study with zero trials must also raise rather than silently emit
    an all-zero report (which would be indistinguishable from "perfectly
    stable" and silently mask a missing-study bug).
    """
    with pytest.raises(ValueError, match="at least two trials"):
        compute_rank_stability({"study_name": "lonely", "role": "X", "trials": []})
    with pytest.raises(ValueError, match="at least two trials"):
        compute_rank_stability(
            {
                "study_name": "lonely",
                "role": "X",
                "trials": [_trial(0, ["a", "b", "c"], {"theta": 0.25})],
            }
        )


# ---------------------------------------------------------------------------
# End-to-end I/O
# ---------------------------------------------------------------------------


def test_end_to_end_writes_json_and_md_alongside_input(tmp_path):
    """A synthetic study JSON on disk, the reporter produces a sibling
    ``...__rank_stability.json`` + ``.md`` pair whose contents round-trip
    back into a :class:`RankStabilityReport`."""
    # 1. Write a synthetic study file using the Optuna exporter's naming.
    ids = [f"CAND_{i:03d}" for i in range(40)]
    study = {
        "study_name": "m05d_first_sweep",
        "role": "DataScience",
        "trials": [
            _trial(0, ids, {"chunk_size": 1000, "theta": 0.25}),
            _trial(1, ids[5:] + ids[:5], {"chunk_size": 1000, "theta": 0.30}),
        ],
    }
    study_path = tmp_path / "optuna_study_m05d_first_sweep__DataScience__rankings.json"
    study_path.write_text(json.dumps(study), encoding="utf-8")

    # 2. Compute + persist.
    payload = load_study_file(str(study_path))
    report = compute_rank_stability(payload, iso_now="2026-07-08T00:00:00Z")
    json_out, md_out = write_stability_report(report, str(study_path))

    # 3. Paths follow the spec's ``optuna_study_*__<role>__rank_stability.{ext}``
    # convention and are siblings of the input.
    expected_json = "optuna_study_m05d_first_sweep__DataScience__rank_stability.json"
    expected_md = "optuna_study_m05d_first_sweep__DataScience__rank_stability.md"
    assert json_out.name == expected_json
    assert md_out.name == expected_md
    assert json_out.parent == study_path.parent
    assert md_out.parent == study_path.parent

    # 4. JSON shape round-trips into a report with the same primitive fields.
    reloaded = json.loads(json_out.read_text(encoding="utf-8"))
    assert reloaded["schema_version"] == SCHEMA_VERSION
    assert reloaded["role"] == "DataScience"
    assert reloaded["trial_count"] == 2
    assert reloaded["pair_count"] == 1
    assert reloaded["top_10_jaccard"] == report.top_10_jaccard
    assert reloaded["kendall_tau"] == report.kendall_tau
    assert reloaded["spearman_rho"] == report.spearman_rho
    assert reloaded["hp_axis_explained_variance"] == report.hp_axis_explained_variance

    # 5. Markdown contains the soft-target headers a reviewer scans first.
    md_text = md_out.read_text(encoding="utf-8")
    assert "Rank Stability Report" in md_text
    assert "top_10_jaccard" in md_text
    assert "newcomer_rate" in md_text.lower()
    assert "HP axis explained variance" in md_text


def test_load_study_file_raises_on_missing_and_malformed(tmp_path):
    """Missing path ⇒ FileNotFoundError; malformed JSON ⇒ ValueError.
    Both errors are surfaced distinctly so a CI pipeline can tell
    "sweep never ran" from "sweep wrote garbage" without parsing the
    message."""
    missing = tmp_path / "does_not_exist.json"
    with pytest.raises(FileNotFoundError):
        load_study_file(str(missing))

    bad = tmp_path / "bad.json"
    bad.write_text("{not: json}", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        load_study_file(str(bad))