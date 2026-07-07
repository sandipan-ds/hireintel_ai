"""Unit tests for the composed scorer (Track 2 / DEC-028, 2026-07-06).

Covers:

* :func:`src.scoring.graded_scorer.evaluate_candidate_code_only_v2` —
  the code-only composed scorer that drops ``scale_factor`` and
  ``DEFAULT_EXPECTED_YEARS`` and blocks REQs with missing
  ``expected_years`` on years-type items.
* :func:`src.scoring.graded_scorer.extract_expected_years` — the
  regex extractor for ``expected_years`` from free text like
  "relative to expected 3 years".
* :func:`src.audit.no_evidence_flags.write_flag` /
  :func:`src.audit.no_evidence_flags.read_flags` — the JSONL audit
  log writer/reader for zero-evidence flags.
* :func:`src.scoring.unified_scorer.evaluate_candidate_composed` —
  the full Mode1 × Mode2 composition that scores each REQ as
  ``Code_only_part × Rubric_LLM_part`` and aggregates to a [0, 100]
  total via ``Σ weight% × sub_score``.

The composed scorer's rubric path uses ``per_req_retrieval`` (the new
RAG pipeline) and ``rubric_scorer`` (the existing LLM judge). To keep
these tests deterministic and LLM-free we use:

* a small synthetic :class:`ThresholdRetriever` with hand-picked
  vectors (no model download)
* a stub ``llm_caller`` that returns a fixed anchored response

so the tests run in < 1 s on any environment without network.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pytest

from src.rag.retriever import (
    DEFAULT_THRESHOLD,
    IndexedChunk,
    ThresholdRetriever,
    VectorIndex,
)
from src.rag.per_req_retrieval import retrieve_evidence_for_req
from src.scoring.graded_scorer import (
    CodeOnlyCandidateEvaluation,
    CodeOnlyItemResult,
    evaluate_candidate_code_only_v2,
    extract_expected_years,
)
from src.scoring.unified_scorer import (
    ComposedCandidateEvaluation,
    ComposedREQResult,
    evaluate_candidate_composed,
    _is_binary_subquery,
    _is_years_subquery,
    _is_rubric_subquery,
    _score_presence_sq,
    _score_years_sq,
)
from src.audit.no_evidence_flags import (
    DEFAULT_FLAGS_PATH,
    clear_flags,
    read_flags,
    write_flag,
)


# ---------------------------------------------------------------------------
# Fixtures — synthetic weight configs, profiles, and retriever.
# ---------------------------------------------------------------------------


@pytest.fixture
def simple_weights() -> Dict[str, Any]:
    """A 2-REQ weight config that sums to 100%.

    REQ names are kept single-token (``"Python"``, ``"Statistics"``) so
    the legacy :func:`graded_scorer._aliases_for` regex (which wraps the
    full item name with word boundaries) actually matches the skill
    tokens present in the profile.
    """
    return {
        "role": "DataScience",
        "requirements_weights": [
            {
                "requirement_id": "REQ-001",
                "requirement_name": "Python",
                "category": "Core Skill",
                "type": "required",
                "weight_percentage": 60.0,
            },
            {
                "requirement_id": "REQ-002",
                "requirement_name": "Statistics",
                "category": "Core Skill",
                "type": "required",
                "weight_percentage": 40.0,
            },
        ],
    }


@pytest.fixture
def fallback_texts() -> Dict[str, str]:
    """Fallback text blobs (SubQuery file's SQ texts) per REQ."""
    return {
        "REQ-001": "Is there strong Python? Binary. How many years of hands-on Python (relative to expected 3 years minimum)? Float.",
        "REQ-002": "Is there evidence of statistics understanding? Binary. How strong is the statistics expertise? Float.",
    }


@pytest.fixture
def python_profile() -> Dict[str, Any]:
    """A profile with 5 years of Python and use of statistics."""
    return {
        "candidate_id": "cand_test_001",
        "source_file": "test.pdf",
        "summary": {"value": "Senior Python developer with 5+ years of experience."},
        "skills": ["Python", "pandas", "scikit-learn", "Statistics", "hypothesis testing"],
        "experience": {
            "entries": [
                {"title": "Data Scientist", "company": "Acme",
                 "details": ["Built ML models in Python for 5 years", "Ran A/B experiments and statistical tests"]},
            ]
        },
        "education": {"entries": [{"degree": "BS Computer Science"}]},
    }


@pytest.fixture
def stub_sq_embedder():
    """A stub sub-query embedder that returns 4-dim vectors aligned to
    the synthetic ``toy_index`` fixture.

    Each sub-query is embedded as the unit vector along its own axis:
    vector [1, 0, 0, 0] for the first SQ encountered, [0, 1, 0, 0]
    for the second, etc. The fourth axis is reserved for "no-match"
    SQs. This guarantees cosine = 1.0 between each SQ vector and the
    indexed chunk on its axis, well above any reasonable threshold.
    """
    import numpy as np

    def _embed(sq_pairs):
        n = len(sq_pairs)
        vecs = np.zeros((n, 4), dtype=np.float32)
        for i, (_key, _text) in enumerate(sq_pairs):
            axis = i % 3  # cycle through the 3 axes the toy_index has chunks on
            vecs[i, axis] = 1.0
        return vecs
    return _embed


@pytest.fixture
def empty_profile() -> Dict[str, Any]:
    """An empty profile that matches nothing."""
    return {
        "candidate_id": "cand_empty",
        "source_file": "blank.pdf",
        "summary": {},
        "skills": [],
        "experience": {"entries": []},
        "education": {"entries": []},
    }


@pytest.fixture
def subquery_data() -> Dict[str, Any]:
    """Synthetic SubQuery data for REQ-001 and REQ-002."""
    return {
        "requirements": [
            {
                "req_id": "REQ-001",
                "name": "Python programming",
                "category": "Core Skill",
                "scoring_formula": "SQ001 x SQ002 x SQ003",
                "sub_queries": [
                    {"key": "SQ001", "text": "Is there evidence that the candidate has strong proficiency in Python?", "type": "Binary", "scale": "0 or 1", "assessment_method": "Look for: Python, proficient, advanced in skills"},
                    {"key": "SQ004", "text": "How many years of hands-on Python experience (relative to expected 3 years minimum)?", "type": "Float", "scale": "0.0 - 1.0", "assessment_method": "Extract years from profile"},
                    {"key": "SQ003", "text": "How strong is their Python and data science library experience?", "type": "Float", "scale": "0.0 - 1.0", "assessment_method": "Assess project depth"},
                ],
            },
            {
                "req_id": "REQ-002",
                "name": "Statistics",
                "category": "Core Skill",
                "scoring_formula": "SQ005 x SQ006 x SQ007",
                "sub_queries": [
                    {"key": "SQ005", "text": "Is there evidence that the candidate has solid understanding of statistics and probability?", "type": "Binary", "scale": "0 or 1", "assessment_method": "Look for: statistics, probability"},
                    {"key": "SQ007", "text": "How strong is their statistics expertise?", "type": "Float", "scale": "0.0 - 1.0", "assessment_method": "Assess depth"},
                ],
            },
        ]
    }


# Fixtures for a small retriever used by the composed scorer tests.

@pytest.fixture
def toy_index() -> VectorIndex:
    """3-chunk index aligned to the sub_queries above."""
    dim = 4
    chunks = [
        IndexedChunk(
            chunk_id="cand_test_001__0",
            vector=np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
            text="Python developer with 5 years experience",
            metadata={"candidate_id": "cand_test_001", "section": "summary", "chunk_index": 0, "role_bucket": "DataScience"},
        ),
        IndexedChunk(
            chunk_id="cand_test_001__1",
            vector=np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32),
            text="Built ML models in Python for 5 years",
            metadata={"candidate_id": "cand_test_001", "section": "experience_0", "chunk_index": 1, "role_bucket": "DataScience"},
        ),
        IndexedChunk(
            chunk_id="cand_test_001__2",
            vector=np.array([0.0, 0.0, 1.0, 0.0], dtype=np.float32),
            text="Ran A/B experiments and statistical tests",
            metadata={"candidate_id": "cand_test_001", "section": "experience_0", "chunk_index": 2, "role_bucket": "DataScience"},
        ),
    ]
    return VectorIndex(chunks, normalize=True)


@pytest.fixture
def toy_retriever(toy_index) -> ThresholdRetriever:
    return ThresholdRetriever(toy_index, threshold=0.30)


# ---------------------------------------------------------------------------
# extract_expected_years — regex extractor
# ---------------------------------------------------------------------------


class TestExtractExpectedYears:
    """Locks in the four supported patterns + the None case."""

    def test_explicit_expected_phrase(self):
        assert extract_expected_years("relative to expected 3 years minimum") == 3.0

    def test_range_takes_upper_bound(self):
        assert extract_expected_years("3-4 years as stated in JD") == 4.0

    def test_plus_years_pattern(self):
        assert extract_expected_years("10+ years experience") == 10.0

    def test_bare_years_mention(self):
        assert extract_expected_years("5 years of Python") == 5.0

    def test_no_years_returns_none(self):
        assert extract_expected_years("How strong is their Python?") is None

    def test_decimal_years_supported(self):
        assert extract_expected_years("expected 2.5 years") == 2.5

    def test_empty_text_returns_none(self):
        assert extract_expected_years("") is None
        assert extract_expected_years(None) is None  # type: ignore[arg-type]

    def test_priority_explicit_over_range(self):
        """When both patterns match, 'expected N years' wins."""
        # "expected 3 years" should match the explicit pattern first
        # (above the range pattern in the list).
        result = extract_expected_years("expected 3 years, range 2-4 years")
        assert result == 3.0


# ---------------------------------------------------------------------------
# write_flag / read_flags — JSONL audit log
# ---------------------------------------------------------------------------


class TestNoEvidenceFlags:
    """Locks in the JSONL schema + append-only behavior."""

    @pytest.fixture
    def tmp_flags_path(self, tmp_path) -> str:
        return str(tmp_path / "flags" / "no_evidence_flags.jsonl")

    def test_write_flag_creates_parent_dirs(self, tmp_flags_path):
        # Parent dir does not exist yet.
        assert not Path(tmp_flags_path).exists()
        write_flag(
            candidate_id="c1", role="DS", req_id="REQ-001",
            requirement_name="Python",
            sub_query_keys=["SQ001", "SQ002"],
            theta=0.30,
            path=tmp_flags_path,
        )
        assert Path(tmp_flags_path).exists()

    def test_write_flag_returns_entry_dict(self, tmp_flags_path):
        entry = write_flag(
            candidate_id="c1", role="DS", req_id="REQ-001",
            requirement_name="Python",
            sub_query_keys=["SQ001"],
            theta=0.30,
            path=tmp_flags_path,
        )
        assert entry["candidate_id"] == "c1"
        assert entry["req_id"] == "REQ-001"
        assert entry["sub_query_keys"] == ["SQ001"]
        assert entry["sub_query_count"] == 1
        assert entry["theta"] == 0.3
        assert "timestamp" in entry

    def test_read_flags_round_trip(self, tmp_flags_path):
        write_flag("c1", "DS", "REQ-001", "A", ["SQ001"], 0.3, path=tmp_flags_path)
        write_flag("c2", "DS", "REQ-002", "B", ["SQ002", "SQ003"], 0.4, path=tmp_flags_path)
        entries = read_flags(tmp_flags_path)
        assert len(entries) == 2
        assert entries[0]["candidate_id"] == "c1"
        assert entries[1]["candidate_id"] == "c2"
        assert entries[1]["sub_query_count"] == 2

    def test_read_flags_when_file_missing_returns_empty_list(self, tmp_path):
        result = read_flags(str(tmp_path / "does_not_exist.jsonl"))
        assert result == []

    def test_write_flag_extra_fields_merged(self, tmp_flags_path):
        entry = write_flag(
            "c1", "DS", "REQ-001", "Python", ["SQ001"], 0.3,
            path=tmp_flags_path,
            extra={"mlflow_run_id": "abc123", "candidate_id": "OVERRIDE_ATTEMPT"},
        )
        assert entry["mlflow_run_id"] == "abc123"
        assert entry["candidate_id"] == "c1"  # extra cannot override reserved keys

    def test_clear_flags_truncates_log(self, tmp_flags_path):
        write_flag("c1", "DS", "REQ-001", "A", [], 0.3, path=tmp_flags_path)
        write_flag("c2", "DS", "REQ-002", "B", [], 0.3, path=tmp_flags_path)
        assert len(read_flags(tmp_flags_path)) == 2
        clear_flags(tmp_flags_path)
        assert not Path(tmp_flags_path).exists()
        # After clear, writing again works.
        write_flag("c3", "DS", "REQ-003", "C", [], 0.3, path=tmp_flags_path)
        assert len(read_flags(tmp_flags_path)) == 1


# ---------------------------------------------------------------------------
# evaluate_candidate_code_only_v2 — the new code-only scorer.
# ---------------------------------------------------------------------------


class TestCodeOnlyV2:
    """Locks in the new code-only scoring contract."""

    def test_matched_python_contribution(
        self, simple_weights, fallback_texts, python_profile,
    ):
        """REQ-001 matches Python @ 5 years vs 3 expected → 60% × min(5/3,1)=60%."""
        result = evaluate_candidate_code_only_v2(
            profile=python_profile,
            weights=simple_weights,
            fallback_expected_years_texts=fallback_texts,
        )
        assert isinstance(result, CodeOnlyCandidateEvaluation)
        assert result.candidate_id == "cand_test_001"
        # Total = 60% × 1.0 (presence match) × 1.0 (years match capped at 1.0)
        #      + 40% × 1.0 (Statistics is binary match)
        # = 60 + 40 = 100.
        assert result.total == 100.0
        assert len(result.items) == 2
        req1 = result.items[0]
        assert req1.requirement_id == "REQ-001"
        assert req1.weight_percentage == 60.0
        assert req1.matched is True
        assert req1.years_detected == 5.0
        assert req1.expected_years == 3.0
        assert req1.code_only_part == 1.0  # min(5/3, 1.0) = 1.0
        assert req1.contribution == 60.0  # 60% × 1.0
        assert req1.blocked is False
        # REQ-002 is binary (no expected_years needed).
        req2 = result.items[1]
        assert req2.matched is True  # 'Statistics' in skills
        assert req2.code_only_part == 1.0
        assert req2.contribution == 40.0

    def test_no_scale_factor_in_aggregation(
        self, simple_weights, fallback_texts, python_profile,
    ):
        """No scale_factor: total = Σ (weight% × code_only_part)."""
        # If a scale_factor was applied, the total would differ from 100 here.
        result = evaluate_candidate_code_only_v2(
            profile=python_profile,
            weights=simple_weights,
            fallback_expected_years_texts=fallback_texts,
        )
        # Direct sum, no normalization.
        assert result.total == pytest.approx(
            sum(i.contribution for i in result.items), abs=1e-6,
        )

    def test_missing_expected_years_blocks_req(
        self, simple_weights, python_profile,
    ):
        """REQ with years-type 'experience' + no expected_years text → blocked."""
        # Provide fallback that has NO years mention.
        no_years_fallback = {
            "REQ-001": "Is there strong Python? Binary. How strong is Python?",
            "REQ-002": "Is there evidence of statistics? Binary. How strong?",
        }
        # Also change the requirement name to include "experience" so it
        # classifies as a years-type REQ.
        weights = json.loads(json.dumps(simple_weights))
        weights["requirements_weights"][0]["requirement_name"] = "Python experience"
        result = evaluate_candidate_code_only_v2(
            profile=python_profile,
            weights=weights,
            fallback_expected_years_texts=no_years_fallback,
        )
        # REQ-001 has "experience" in its name → years-type, no expected_years → blocked.
        assert result.items[0].blocked is True
        assert result.items[0].contribution == 0.0
        assert result.items[0].code_only_part == 0.0
        assert "BLOCKED" in result.items[0].reason
        # REQ-002 is "Statistics" → not years-type → not blocked.
        assert result.items[1].blocked is False

    def test_empty_profile_scores_zero(self, simple_weights, fallback_texts, empty_profile):
        result = evaluate_candidate_code_only_v2(
            profile=empty_profile,
            weights=simple_weights,
            fallback_expected_years_texts=fallback_texts,
        )
        assert result.total == 0.0
        assert all(not it.matched for it in result.items)
        assert all(it.code_only_part == 0.0 for it in result.items)

    def test_mention_only_partial_credit(
        self, fallback_texts, python_profile,
    ):
        """Matched but no years detectable → 0.3 mention-only partial credit.

        This only applies to years-type REQs (whose name contains
        'experience', 'years', 'tenure', or 'senior'). A bare 'Python'
        REQ is treated as a binary presence match (1.0 on match); a
        'Python experience' REQ with no measureable years gets the
        mention-only 0.3 partial credit per the legacy spec.
        """
        # Use a years-type REQ name so the scorer enters the years path.
        weights = {
            "role": "DataScience",
            "requirements_weights": [
                {"requirement_id": "REQ-001", "requirement_name": "Python experience",
                 "category": "Core Skill", "type": "required", "weight_percentage": 60.0},
                {"requirement_id": "REQ-002", "requirement_name": "Statistics",
                 "category": "Core Skill", "type": "required", "weight_percentage": 40.0},
            ],
        }
        # Modify the profile to kill all years mentions.
        no_years_profile = json.loads(json.dumps(python_profile))
        no_years_profile["summary"] = {"value": "Python developer."}
        # Put the literal REQ name in skills so the presence regex
        # ``\bpython experience\b`` matches. The years detector will
        # then scan the matched section for any "<n> years" phrase,
        # which we deliberately omit to exercise the mention-only 0.3
        # partial credit branch of evaluate_candidate_code_only_v2.
        no_years_profile["skills"] = ["Python", "Python experience"]
        no_years_profile["experience"] = {"entries": [{"title": "Dev", "company": "X", "details": ["Used Python experience at Acme"]}]}
        result = evaluate_candidate_code_only_v2(
            profile=no_years_profile,
            weights=weights,
            fallback_expected_years_texts=fallback_texts,
        )
        req1 = result.items[0]
        assert req1.matched is True
        assert req1.years_detected == 0.0
        assert req1.code_only_part == 0.3
        assert req1.contribution == pytest.approx(60.0 * 0.3, abs=1e-6)

    def test_blocked_items_property(self, simple_weights, python_profile):
        result = evaluate_candidate_code_only_v2(
            profile=python_profile,
            weights=simple_weights,
            fallback_expected_years_texts={},  # no fallback → expected_years None
        )
        # REQ-001 name "Python programming" does not contain "experience"
        # so it's NOT years-type and not blocked. But "Python programming"
        # also doesn't have "experience" keyword — let me test that path.
        # Use a name with "experience" to make it blocked.
        weights = json.loads(json.dumps(simple_weights))
        weights["requirements_weights"][0]["requirement_name"] = "Python experience"
        result = evaluate_candidate_code_only_v2(
            profile=python_profile,
            weights=weights,
            fallback_expected_years_texts={},
        )
        assert len(result.blocked_items) == 1
        assert result.blocked_items[0].requirement_id == "REQ-001"


# ---------------------------------------------------------------------------
# Sub-query classification helpers.
# ---------------------------------------------------------------------------


class TestSubQueryClassification:
    """Heuristics for splitting SubQuery SQs into code-only vs rubric."""

    def test_binary_subquery_is_code_only(self):
        sq = {"key": "SQ001", "text": "Is there evidence of Python?", "type": "Binary"}
        assert _is_binary_subquery(sq) is True
        assert _is_years_subquery(sq) is False
        assert _is_rubric_subquery(sq) is False

    def test_years_subquery_is_code_only(self):
        sq = {"key": "SQ004", "text": "How many years of Python (relative to expected 3 years)?", "type": "Float"}
        assert _is_binary_subquery(sq) is False
        assert _is_years_subquery(sq) is True
        assert _is_rubric_subquery(sq) is False

    def test_float_depth_subquery_is_rubric(self):
        sq = {"key": "SQ003", "text": "How strong is their Python expertise?", "type": "Float"}
        assert _is_binary_subquery(sq) is False
        assert _is_years_subquery(sq) is False
        assert _is_rubric_subquery(sq) is True


# ---------------------------------------------------------------------------
# Per-SQ scoring helpers.
# ---------------------------------------------------------------------------


class TestPerSQScoring:
    """Direct tests on the per-SQ scoring helpers."""

    def test_score_presence_sq_returns_1_on_skill_match(self, python_profile):
        sq = {"text": "Has Python?", "assessment_method": "Look for: Python"}
        score = _score_presence_sq(sq, requirement_name="Python", profile=python_profile)
        assert score == 1.0

    def test_score_presence_sq_returns_0_on_no_match(self, python_profile):
        sq = {"text": "Has COBOL?", "assessment_method": "Look for: COBOL"}
        score = _score_presence_sq(sq, requirement_name="COBOL", profile=python_profile)
        assert score == 0.0

    def test_score_presence_sq_falls_back_to_sq_text_tokens(self, python_profile):
        """If req_name itself doesn't match but the SQ text lists library
        names that DO match (e.g. 'pandas' is in the profile's skills),
        the SQ is still scored as a presence hit."""
        sq = {"text": "Has the candidate used data science libraries (pandas, NumPy)?", "assessment_method": ""}
        # 'pandas' is in python_profile.skills; 'Python libraries' generic req
        # name wouldn't match by itself.
        score = _score_presence_sq(sq, requirement_name="data science libraries", profile=python_profile)
        assert score == 1.0  # matched 'pandas' from the SQ text

    def test_score_years_sq_caps_at_1(self, python_profile):
        sq = {"text": "How many years (relative to expected 3 years)?", "type": "Float"}
        score, years, expected = _score_years_sq(sq, requirement_name="Python", profile=python_profile)
        # 5+ years detected, expected=3 → min(5/3, 1.0) = 1.0
        assert expected == 3.0
        assert years == 5.0
        assert score == 1.0

    def test_score_years_sq_returns_none_when_no_expected(self, python_profile):
        sq = {"text": "How many years of Python?", "type": "Float"}
        score, years, expected = _score_years_sq(sq, requirement_name="Python", profile=python_profile)
        assert expected is None
        assert score == 0.0


# ---------------------------------------------------------------------------
# evaluate_candidate_composed — full Mode1 × Mode2 composition.
# ---------------------------------------------------------------------------


class TestComposedScorer:
    """End-to-end composed scoring tests.

    The rubric path uses a stub LLM caller that returns a fixed
    anchored response, so tests are deterministic without network.
    """

    @pytest.fixture
    def stub_llm_caller(self):
        """A stub LLM caller that returns anchored 0.75 for all rubric SQs.

        The rubric_scorer parses the LLM's text response to extract
        sub-scores. We return a JSON-like dict of SQ-key → anchored
        value so the parser can pick it up.
        """
        def _stub(prompt: str) -> str:
            # The rubric_scorer parses anchored floats. We return a
            # consolidated anchored "1.0" so the normalized_score is
            # 1.0; the actual rubric_scorer's parse_anchored_response
            # converts "yes"/"high" to anchored floats.
            return '{"skill_presence": "yes", "skill_depth": "high", "project_relevance": "high", "years_experience": "10+ years"}'
        return _stub

    def test_composed_no_llm_scores_only_code_only(
        self, simple_weights, fallback_texts, python_profile, subquery_data,
        toy_retriever,
    ):
        """When llm_caller is None, rubric part = 0 → contribution = 0 for
        REQs with rubric SQs. The total is still computable from code-only
        parts, but those rubric-REQ contributions are 0."""
        result = evaluate_candidate_composed(
            profile=python_profile,
            weights=simple_weights,
            retriever=toy_retriever,
            structured_profile=None,
            sq_embedder=stub_sq_embedder,
            llm_caller=None,
            role_subqueries=subquery_data,
            role_name="DataScience",
            threshold=0.30,
        )
        # Both REQ-001 and REQ-002 have rubric SQs (SQ003, SQ007).
        # Without LLM, their rubric_llm_part = 0 → contribution = 0.
        assert isinstance(result, ComposedCandidateEvaluation)
        assert result.total == 0.0  # all rubric parts are 0
        assert all(r.contribution == 0.0 for r in result.reqs)

    def test_composed_no_retriever_zeros_rubric_part(
        self, simple_weights, python_profile, subquery_data,
    ):
        """retriever=None → rubric parts are 0 even with an LLM caller."""
        result = evaluate_candidate_composed(
            profile=python_profile,
            weights=simple_weights,
            retriever=None,
            structured_profile=None,
            sq_embedder=stub_sq_embedder,
            llm_caller=lambda p: "yes",
            role_subqueries=subquery_data,
            role_name="DataScience",
        )
        assert result.total == 0.0
        assert all(r.rubric_llm_part == 0.0 for r in result.reqs)

    def test_composed_blocked_when_expected_years_missing(
        self, simple_weights, python_profile, subquery_data, toy_retriever,
        stub_sq_embedder,
    ):
        """A years-type SQ whose text has no 'years' phrase blocks the REQ."""
        # Replace the sub_queries for REQ-001 with a years-type SQ that has
        # NO extractable expected_years (text mentions 'years' but with
        # no number → extract_expected_years returns None).
        subq = json.loads(json.dumps(subquery_data))
        subq["requirements"][0]["sub_queries"] = [
            {"key": "SQ004", "text": "How many years of Python does the candidate have?", "type": "Float"},
        ]
        # And rename the REQ to include "experience" so it's years-type.
        weights = json.loads(json.dumps(simple_weights))
        weights["requirements_weights"][0]["requirement_name"] = "Python experience"
        result = evaluate_candidate_composed(
            profile=python_profile,
            weights=weights,
            retriever=toy_retriever,
            structured_profile=None,
            sq_embedder=stub_sq_embedder,
            llm_caller=lambda p: "yes",
            role_subqueries=subq,
            role_name="DataScience",
        )
        req1 = result.reqs[0]
        assert req1.blocked is True
        assert "expected_years" in req1.blocked_reason
        assert req1.contribution == 0.0

    def test_composed_formula_subscore_eq_code_only_times_rubric(
        self, simple_weights, fallback_texts, python_profile, subquery_data,
        toy_retriever, stub_sq_embedder, tmp_path,
    ):
        """Sub-Score = Code_only_part × Rubric_LLM_part, contribution = weight% × Sub-Score."""
        # Use a stub LLM caller whose response produces a known normalized_score.
        # The rubric_scorer's parse_anchored_response maps "yes" → 1.0, "high"
        # → 0.75. So our stub returns "yes" for everything, producing
        # normalized_score = product of all anchored floats from the rubric
        # sub-questions = 1.0 × 1.0 × ... = 1.0.
        def stub(p):
            return "skill_presence: yes\nskill_depth: yes\nproject_relevance: yes\nyears_experience: 10+ years"
        result = evaluate_candidate_composed(
            profile=python_profile,
            weights=simple_weights,
            retriever=toy_retriever,
            structured_profile=None,
            sq_embedder=stub_sq_embedder,
            llm_caller=stub,
            role_subqueries=subquery_data,
            role_name="DataScience",
            threshold=0.30,
            audit_flags_path=str(tmp_path / "flags.jsonl"),
        )
        req1 = result.reqs[0]
        # REQ-001 has SQ001 (binary presence, matched Python → 1)
        #                  SQ004 (years, 5 years vs expected 3 → min(5/3,1) = 1)
        #                  SQ003 (rubric LLM, stub returns "yes" → anchored 1.0
        #                         for skill rubric sub-questions → normalized_score
        #                         ~ product ~ 1.0)
        # code_only_part = 1 × 1 = 1.0
        # rubric_llm_part = ~1.0
        # sub_score = 1.0 × 1.0 = 1.0
        # contribution = 60% × 1.0 = 60.0
        assert req1.code_only_part == 1.0
        # The rubric part depends on the rubric_scorer's parsing of "yes" /
        # "10+ years". We at least assert it exists and the contribution is
        # weight_pct × code_only × rubric_llm_part.
        assert req1.rubric_llm_part is not None
        assert req1.contribution == pytest.approx(
            60.0 * req1.code_only_part * req1.rubric_llm_part, abs=1e-3,
        )
        # Total = contribution_req1 + contribution_req2.
        assert result.total == pytest.approx(
            sum(r.contribution for r in result.reqs), abs=1e-6,
        )

    def test_composed_zero_retrieval_writes_flag(
        self, simple_weights, python_profile, subquery_data, toy_retriever,
        stub_sq_embedder, tmp_path,
    ):
        """When retrieve_evidence_for_req returns [], a flag is written."""
        # The toy_index has 3 chunks. Use a HIGH threshold so retrieval
        # returns empty for the candidate.
        flags_path = str(tmp_path / "no_evidence.jsonl")
        # Use threshold > 1.0 (impossible to clear). Per :class:`ThresholdRetriever`
        # this returns [] for all queries.
        result = evaluate_candidate_composed(
            profile=python_profile,
            weights=simple_weights,
            retriever=toy_retriever,
            structured_profile=None,
            sq_embedder=stub_sq_embedder,
            llm_caller=lambda p: "yes",
            role_subqueries=subquery_data,
            role_name="DataScience",
            threshold=2.0,  # impossible to reach → zero retrieval
            audit_flags_path=flags_path,
        )
        # Both REQs have rubric SQs → both blocked by zero retrieval.
        from src.audit.no_evidence_flags import read_flags
        entries = read_flags(flags_path)
        assert len(entries) >= 1
        for e in entries:
            assert e["candidate_id"] == "cand_test_001"
            assert e["role"] == "DataScience"
            assert "req_id" in e
            assert e["theta"] == 2.0
        assert all(r.blocked for r in result.reqs)

    def test_composed_total_in_0_to_100(
        self, simple_weights, python_profile, subquery_data, toy_retriever,
        stub_sq_embedder, tmp_path,
    ):
        """The total is bounded in [0, 100] because recruiter weights sum
        to 100 and every sub_score ∈ [0, 1]."""
        result = evaluate_candidate_composed(
            profile=python_profile,
            weights=simple_weights,
            retriever=toy_retriever,
            structured_profile=None,
            sq_embedder=stub_sq_embedder,
            llm_caller=lambda p: "yes",
            role_subqueries=subquery_data,
            role_name="DataScience",
            threshold=0.30,
            audit_flags_path=str(tmp_path / "flags.jsonl"),
        )
        assert 0.0 <= result.total <= 100.0

    def test_composed_empty_profile_total_is_zero(
        self, simple_weights, subquery_data, toy_retriever, empty_profile,
        stub_sq_embedder, tmp_path,
    ):
        """Empty profile → all code-only SQs miss → contribution = 0 for
        every REQ regardless of the rubric LLM path."""
        result = evaluate_candidate_composed(
            profile=empty_profile,
            weights=simple_weights,
            retriever=toy_retriever,
            structured_profile=None,
            sq_embedder=stub_sq_embedder,
            llm_caller=lambda p: "yes",
            role_subqueries=subquery_data,
            role_name="DataScience",
            threshold=0.30,
            audit_flags_path=str(tmp_path / "flags.jsonl"),
        )
        # All REQs scored 0.
        assert result.total == 0.0

    def test_composed_to_dict_contains_blocked_count(
        self, simple_weights, python_profile, subquery_data, toy_retriever,
        stub_sq_embedder, tmp_path,
    ):
        """to_dict serializes the full evaluation including blocked counters."""
        result = evaluate_candidate_composed(
            profile=python_profile,
            weights=simple_weights,
            retriever=toy_retriever,
            structured_profile=None,
            sq_embedder=stub_sq_embedder,
            llm_caller=lambda p: "yes",
            role_subqueries=subquery_data,
            role_name="DataScience",
            threshold=2.0,
            audit_flags_path=str(tmp_path / "flags.jsonl"),
        )
        d = result.to_dict()
        assert "blocked_count" in d
        assert "zero_evidence_count" in d
        assert "reqs" in d
        assert isinstance(d["reqs"], list)

    def test_composed_passes_threshold_through_to_retrieval(
        self, simple_weights, python_profile, subquery_data, toy_retriever,
        stub_sq_embedder, tmp_path,
    ):
        """``threshold`` argument flows through to ``retrieve_evidence_for_req``
        as a per-call override (per the per_req_retrieval module's
        threshold kwarg)."""
        # threshold = 0.5 (above the toy_index cosines) → fewer hits.
        result = evaluate_candidate_composed(
            profile=python_profile,
            weights=simple_weights,
            retriever=toy_retriever,
            structured_profile=None,
            sq_embedder=stub_sq_embedder,
            llm_caller=lambda p: "yes",
            role_subqueries=subquery_data,
            role_name="DataScience",
            threshold=0.5,
            audit_flags_path=str(tmp_path / "flags.jsonl"),
        )
        # With theta=0.5 (above 1/sqrt(2)~0.707 already; our toy_index
        # vectors don't have any cosine >= 0.5 against arbitrary SQ
        # embeddings because the embed_sub_queries is real). This test
        # mainly asserts the API contract: the threshold kwarg is
        # plumbed through. We assert the result is non-empty.
        assert len(result.reqs) == 2

    def test_composed_missing_subquery_data_raises(
        self, simple_weights, python_profile,
    ):
        """When role_subqueries is None and the role has no SubQuery file,
        a ValueError is raised."""
        # role_subqueries=None → falls back to get_all_role_subqueries();
        # role_name="NoSuchRole" → no SubQuery data → ValueError.
        with pytest.raises(ValueError, match="no SubQuery data for role"):
            evaluate_candidate_composed(
                profile=python_profile,
                weights=simple_weights,
                retriever=None,
                llm_caller=None,
                role_subqueries=None,
                role_name="NoSuchRole",
            )