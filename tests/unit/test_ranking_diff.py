"""Unit tests for the ranking diff module (DEC-026)."""

import json
import tempfile
from pathlib import Path

import pytest

from src.eval.ranking_diff import (
    RankingDiff,
    diff_from_pairs,
    investigate_case,
    load_reasoning,
    write_diff_report,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def toy_diff() -> RankingDiff:
    """A 20-candidate ranking with one new entrant, one departure, and a 6-position jump.

    Baseline (top 10): C1-C10 in order. Current (top 10): C7 jumps to #1,
    C1-C6 drop 1 slot each, C10 disappears, a new C21 enters at #10.
    """
    baseline = [(f"C{i:02d}", 100.0 - i) for i in range(1, 21)]
    current = list(baseline)
    # C7 jumps from rank 6 (0-indexed) to rank 0.
    c7 = ("C07", baseline[6][1] + 50)  # bigger score to push to top
    current = [c7] + [b for b in current if b[0] != "C07"]
    # New C21 enters at rank 9 (slot 10).
    current.insert(9, ("C21", 91.0))
    # C10 disappears.
    current = [c for c in current if c[0] != "C10"]
    return diff_from_pairs(
        baseline=baseline,
        current=current,
        role="BusinessAnalyst",
        baseline_label="exp_baseline",
        current_label="exp_current",
        big_swap_fraction=0.10,
    )


# ---------------------------------------------------------------------------
# Pure diff computation
# ---------------------------------------------------------------------------


def test_total_candidates_counts_unique_across_both(toy_diff):
    # Baseline has 20 (C01..C20). Current has 19 from baseline (C10 dropped)
    # + 1 new (C21). Union: 20 + 1 = 21.
    assert toy_diff.total_candidates == 21


def test_baseline_and_current_rank_maps(toy_diff):
    assert toy_diff.baseline_rank["C01"] == 0
    assert toy_diff.current_rank["C01"] == 1
    assert toy_diff.baseline_rank["C07"] == 6
    assert toy_diff.current_rank["C07"] == 0


def test_rank_delta_signed_moved_up_is_positive(toy_diff):
    # C07 moved from 6 to 0 -> delta = 6 (positive = moved up)
    assert toy_diff.rank_delta("C07") == 6


def test_rank_delta_signed_moved_down_is_negative(toy_diff):
    """Sign convention: positive = moved UP (better position = lower rank number).
    Rank delta is computed as ``baseline_rank - current_rank``.

    C01 moved from rank 0 to rank 1 (got worse). delta = 0 - 1 = -1.
    """
    assert toy_diff.rank_delta("C01") == -1


def test_rank_delta_is_none_for_only_in_one(toy_diff):
    # C10 only in baseline, C21 only in current
    assert toy_diff.rank_delta("C10") is None
    assert toy_diff.rank_delta("C21") is None


def test_score_delta_returns_none_for_only_in_one(toy_diff):
    assert toy_diff.score_delta("C10") is None
    assert toy_diff.score_delta("C21") is None


# ---------------------------------------------------------------------------
# Top-K queries
# ---------------------------------------------------------------------------


def test_new_in_top_k(toy_diff):
    # C21 enters top-10
    assert "C21" in toy_diff.new_in_top_k(10)
    # C07 is in both top-10, not a new entrant
    assert "C07" not in toy_diff.new_in_top_k(10)


def test_dropped_from_top_k(toy_diff):
    # C10 dropped from top-10
    assert "C10" in toy_diff.dropped_from_top_k(10)


def test_top_k_returns_correct_count(toy_diff):
    top5 = toy_diff.top_k("current", 5)
    assert len(top5) == 5
    assert top5[0] == "C07"  # C07 is now #1


# ---------------------------------------------------------------------------
# Categorization
# ---------------------------------------------------------------------------


def test_categorize_separates_stable_and_big_swaps(toy_diff):
    cats = toy_diff.categorize()
    assert "C07" in [c for c, _ in cats["big_swap_up"]]
    # C01..C06, C08, C09, C11..C20 are mostly stable (delta = +-1)
    # C01..C06 have delta -1 (stable, threshold 2)
    # C08..C20 have delta 0 or +-1
    for cid in ["C02", "C03", "C04", "C05", "C06"]:
        assert cid in [c for c, _ in cats["stable"]]


def test_categorize_separates_only_in_baseline_and_current(toy_diff):
    cats = toy_diff.categorize()
    assert "C10" in [c for c, _ in cats["only_in_baseline"]]
    assert "C21" in [c for c, _ in cats["only_in_current"]]


def test_categorize_threshold_is_fraction_of_pool(toy_diff):
    # 20 candidates, fraction 0.10 -> threshold = max(1, int(2.0)) = 2
    assert toy_diff.big_swap_threshold == 2
    # A delta of 1 is stable; a delta of 3 is big.


def test_categorize_with_custom_fraction():
    d = diff_from_pairs(
        baseline=[("A", 10.0), ("B", 5.0), ("C", 0.0)],
        current=[("B", 10.0), ("A", 5.0), ("C", 0.0)],
        role="TestRole",
        baseline_label="x",
        current_label="y",
        big_swap_fraction=0.50,
    )
    # 3 candidates, fraction 0.50 -> threshold = max(1, int(1.5)) = 1
    assert d.big_swap_threshold == 1
    cats = d.categorize()
    # Sign convention: rank_delta = baseline_rank - current_rank.
    # A: baseline=0, current=1 -> delta = -1 (moved down, got worse).
    # B: baseline=1, current=0 -> delta = +1 (moved up, got better).
    assert ("A", -1) in cats["big_swap_down"]
    assert ("B", 1) in cats["big_swap_up"]


# ---------------------------------------------------------------------------
# Aggregate stats
# ---------------------------------------------------------------------------


def test_average_rank_change(toy_diff):
    # Most candidates moved by 0 or 1, but C07 moved 6
    # average across 19 shared (20 minus 1 dropped) -- 1 jump of 6 and the rest 0..1
    # Approximate: most share is 0, so average should be small but > 0
    avg = toy_diff.average_rank_change()
    assert 0.0 < avg < 2.0


def test_max_rank_change(toy_diff):
    cid, delta = toy_diff.max_rank_change()
    assert cid == "C07"
    assert delta == 6


def test_max_rank_change_with_no_shared_candidates():
    d = diff_from_pairs(
        baseline=[("A", 1.0)],
        current=[("B", 1.0)],
        role="TestRole",
        baseline_label="x",
        current_label="y",
    )
    assert d.max_rank_change() == (None, 0)


def test_only_in_baseline_and_current(toy_diff):
    assert toy_diff.only_in_baseline() == ["C10"]
    assert toy_diff.only_in_current() == ["C21"]


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def test_summary_dict_contains_expected_keys(toy_diff):
    s = toy_diff.summary_dict()
    expected_keys = {
        "role", "baseline_label", "current_label", "total_candidates",
        "big_swap_threshold", "big_swap_fraction",
        "new_in_top_10", "new_in_top_50",
        "dropped_from_top_10", "dropped_from_top_50",
        "shared_candidates", "only_in_baseline", "only_in_current",
        "average_abs_rank_change", "max_rank_change",
    }
    assert expected_keys <= set(s.keys())


def test_to_dict_is_json_serializable(toy_diff):
    payload = toy_diff.to_dict()
    s = json.dumps(payload)  # should not raise
    roundtrip = json.loads(s)
    assert roundtrip["summary"]["role"] == "BusinessAnalyst"
    assert roundtrip["summary"]["total_candidates"] == toy_diff.total_candidates


# ---------------------------------------------------------------------------
# Per-resume tree loader
# ---------------------------------------------------------------------------


def test_load_reasoning_returns_empty_for_missing_experiment_root(tmp_path):
    result = load_reasoning(tmp_path / "does_not_exist", "BusinessAnalyst", "C01")
    assert result == []


def test_load_reasoning_loads_matching_files(tmp_path):
    base = tmp_path / "per_candidate" / "BusinessAnalyst" / "C01" / "reasoning"
    base.mkdir(parents=True)
    (base / "REQ-001__abc.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "candidate_id": "C01",
                "req_id": "REQ-001",
                "model_name": "test-model",
                "reasoning": "x" * 500,
                "basis": [{"chunk_id": "c1", "quote": "q", "relevance": "primary"}],
                "retrieved_chunks": [{"chunk_id": "c1", "cosine": 0.9, "text": "t"}],
                "sub_scores": {"presence": {"value": 1.0}},
            }
        )
    )
    (base / "REQ-002__def.json").write_text(
        json.dumps({"schema_version": "1.0", "candidate_id": "C01", "req_id": "REQ-002"})
    )
    out = load_reasoning(tmp_path, "BusinessAnalyst", "C01")
    assert len(out) == 2
    assert {r["req_id"] for r in out} == {"REQ-001", "REQ-002"}


def test_load_reasoning_filters_by_req_id(tmp_path):
    base = tmp_path / "per_candidate" / "BusinessAnalyst" / "C01" / "reasoning"
    base.mkdir(parents=True)
    (base / "REQ-001__abc.json").write_text(json.dumps({"req_id": "REQ-001"}))
    (base / "REQ-002__def.json").write_text(json.dumps({"req_id": "REQ-002"}))
    out = load_reasoning(tmp_path, "BusinessAnalyst", "C01", req_id="REQ-001")
    assert len(out) == 1
    assert out[0]["req_id"] == "REQ-001"


def test_load_reasoning_skips_malformed_files(tmp_path):
    base = tmp_path / "per_candidate" / "BusinessAnalyst" / "C01" / "reasoning"
    base.mkdir(parents=True)
    (base / "REQ-001__abc.json").write_text("not valid json")
    (base / "REQ-002__def.json").write_text(json.dumps({"req_id": "REQ-002"}))
    out = load_reasoning(tmp_path, "BusinessAnalyst", "C01")
    # Malformed file is skipped (with a warning), good file is kept.
    assert len(out) == 1
    assert out[0]["req_id"] == "REQ-002"


# ---------------------------------------------------------------------------
# investigate_case
# ---------------------------------------------------------------------------


def test_investigate_case_returns_expected_shape(toy_diff, tmp_path):
    base = tmp_path / "exp_a" / "per_candidate" / "BusinessAnalyst" / "C07" / "reasoning"
    base.mkdir(parents=True)
    (base / "REQ-001__h.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "candidate_id": "C07",
                "req_id": "REQ-001",
                "model_name": "model-a",
                "retrieval_params": {"theta": 0.7, "chunk_size": 500},
                "sub_scores": {"presence": {"value": 1.0}},
                "reasoning": "candidate has Python experience",
            }
        )
    )
    cur = tmp_path / "exp_b" / "per_candidate" / "BusinessAnalyst" / "C07" / "reasoning"
    cur.mkdir(parents=True)
    (cur / "REQ-001__h2.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "candidate_id": "C07",
                "req_id": "REQ-001",
                "model_name": "model-b",
                "retrieval_params": {"theta": 0.5, "chunk_size": 300},
                "sub_scores": {"presence": {"value": 0.5}},
                "reasoning": "no clear Python",
            }
        )
    )
    inv = investigate_case(
        toy_diff, "C07",
        baseline_root=tmp_path / "exp_a",
        current_root=tmp_path / "exp_b",
        role="BusinessAnalyst",
        req_id="REQ-001",
    )
    assert inv["candidate_id"] == "C07"
    assert inv["rank_delta"] == 6
    assert len(inv["baseline"]["reasoning_files"]) == 1
    assert len(inv["current"]["reasoning_files"]) == 1
    assert inv["baseline"]["reasoning_files"][0]["model_name"] == "model-a"
    assert inv["current"]["reasoning_files"][0]["model_name"] == "model-b"


# ---------------------------------------------------------------------------
# write_diff_report
# ---------------------------------------------------------------------------


def test_write_diff_report_creates_both_files(toy_diff, tmp_path):
    json_path = tmp_path / "diff.json"
    md_path = tmp_path / "diff.md"
    write_diff_report(toy_diff, json_path, md_path)
    assert json_path.exists()
    assert md_path.exists()
    assert json_path.stat().st_size > 0
    assert md_path.stat().st_size > 0


def test_write_diff_report_creates_parent_dirs(toy_diff, tmp_path):
    json_path = tmp_path / "deep" / "nested" / "diff.json"
    md_path = tmp_path / "deep" / "nested" / "diff.md"
    write_diff_report(toy_diff, json_path, md_path)
    assert json_path.exists()
    assert md_path.exists()


def test_write_diff_report_includes_investigations(toy_diff, tmp_path):
    json_path = tmp_path / "diff.json"
    md_path = tmp_path / "diff.md"
    investigations = [
        {
            "candidate_id": "C07",
            "req_id": "REQ-001",
            "rank_delta": 6,
            "score_delta": None,
            "baseline": {
                "label": "exp_a",
                "summary_files": [
                    {
                        "schema_version": "1.0",
                        "model_name": "model-a",
                        "model_params": {"temperature": 0},
                        "retrieval_params": {"theta": 0.7, "chunk_size": 500},
                        "rubric_version": "v1.0",
                        "sub_scores": {"presence": {"value": 1.0}},
                        "retrieved_chunk_count": 5,
                        "basis_count": 2,
                        "reasoning_excerpt": "x" * 250,
                        "created_at": "2026-07-05T00:00:00Z",
                    }
                ],
                "reasoning_files": [
                    {"schema_version": "1.0", "model_name": "model-a", "reasoning": "x" * 250}
                ],
            },
            "current": {
                "label": "exp_b",
                "summary_files": [
                    {
                        "schema_version": "1.0",
                        "model_name": "model-b",
                        "model_params": {"temperature": 0},
                        "retrieval_params": {"theta": 0.5, "chunk_size": 300},
                        "rubric_version": "v1.0",
                        "sub_scores": {"presence": {"value": 0.5}},
                        "retrieved_chunk_count": 3,
                        "basis_count": 1,
                        "reasoning_excerpt": "y" * 100,
                        "created_at": "2026-07-05T01:00:00Z",
                    }
                ],
                "reasoning_files": [
                    {"schema_version": "1.0", "model_name": "model-b", "reasoning": "y" * 100}
                ],
            },
        }
    ]
    write_diff_report(toy_diff, json_path, md_path, investigations=investigations)
    payload = json.loads(json_path.read_text())
    assert len(payload["investigations"]) == 1
    assert payload["investigations"][0]["candidate_id"] == "C07"
    md_text = md_path.read_text()
    # Both sides' reasoning excerpts should appear in the MD.
    assert "x" in md_text
    assert "y" in md_text
    assert "model-a" in md_text
    assert "model-b" in md_text


# ---------------------------------------------------------------------------
# diff_from_pairs convenience
# ---------------------------------------------------------------------------


def test_diff_from_pairs_basic():
    d = diff_from_pairs(
        baseline=[("A", 1.0), ("B", 0.5)],
        current=[("B", 1.0), ("A", 0.5)],
        role="Test",
        baseline_label="x",
        current_label="y",
    )
    assert isinstance(d, RankingDiff)
    assert d.role == "Test"
    # Sign convention: rank_delta = baseline_rank - current_rank.
    # A: 0 -> 1 -> delta = -1 (moved down)
    # B: 1 -> 0 -> delta = +1 (moved up)
    assert d.rank_delta("A") == -1
    assert d.rank_delta("B") == 1
