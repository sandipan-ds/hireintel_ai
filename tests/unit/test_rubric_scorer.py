"""Tests for the rubric-bound LLM evidence scorer."""

import json
import pytest
from src.rag.chunker import ChunkRecord
from src.rag.section_routed import SectionEvidence, section_routed_retrieval
from src.scoring.rubric_scorer import (
    CachedScoringTrace,
    SubScoreResult,
    score_requirement_with_rubric,
    explain_score_from_cache,
    _build_rubric_prompt,
    _parse_llm_response,
    _evaluate_formula,
    _default_sub_scores,
)
from src.scoring.rubrics import SKILL_RUBRIC, LEADERSHIP_RUBRIC


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_evidence(text: str, sections=None) -> SectionEvidence:
    """Create a minimal SectionEvidence for testing."""
    return SectionEvidence(
        requirement_type="skill",
        requirement_name="Python",
        sections=sections or ["Experience", "Projects", "Skills"],
        chunks=[],
        full_text=text,
        chunk_count=0,
    )


def _mock_llm(response_json: dict):
    """Create a mock LLM caller that returns the given JSON."""
    def caller(prompt: str) -> str:
        return json.dumps(response_json)
    return caller


# ---------------------------------------------------------------------------
# Prompt construction — weight must NOT appear in the prompt
# ---------------------------------------------------------------------------

class TestPromptConstruction:
    """The prompt must never include the weight."""

    def test_weight_not_in_prompt(self):
        evidence = _make_evidence("Python experience at Netflix")
        prompt = _build_rubric_prompt("Python", SKILL_RUBRIC, evidence, target_years=5)
        # The word "weight" must not appear in the prompt.
        assert "weight" not in prompt.lower()

    def test_requirement_name_in_prompt(self):
        evidence = _make_evidence("Python experience")
        prompt = _build_rubric_prompt("Python", SKILL_RUBRIC, evidence)
        assert "Python" in prompt

    def test_anchors_in_prompt(self):
        evidence = _make_evidence("Some experience")
        prompt = _build_rubric_prompt("Python", SKILL_RUBRIC, evidence)
        assert "0.0" in prompt
        assert "0.25" in prompt
        assert "0.5" in prompt
        assert "0.75" in prompt
        assert "1.0" in prompt

    def test_section_content_in_prompt(self):
        evidence = _make_evidence("Built recommendation engine in Python")
        prompt = _build_rubric_prompt("Python", SKILL_RUBRIC, evidence)
        assert "recommendation engine" in prompt

    def test_extract_first_instruction_in_prompt(self):
        evidence = _make_evidence("Some text")
        prompt = _build_rubric_prompt("Python", SKILL_RUBRIC, evidence)
        assert "extract" in prompt.lower()

    def test_formula_in_prompt_for_transparency(self):
        evidence = _make_evidence("Some text")
        prompt = _build_rubric_prompt("Python", SKILL_RUBRIC, evidence)
        assert "gate * years_ratio * relevance" in prompt

    def test_target_years_in_prompt(self):
        evidence = _make_evidence("Some text")
        prompt = _build_rubric_prompt("Python", SKILL_RUBRIC, evidence, target_years=5)
        assert "5" in prompt


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

class TestResponseParsing:
    """The parser should extract structured sub-scores from LLM JSON."""

    def test_valid_response(self):
        response = json.dumps({
            "sub_scores": [
                {"key": "skill_presence", "extracted_evidence": "Skills: Python, SQL", "cited_text": "Python, SQL", "sub_score": 1.0},
                {"key": "years_experience", "extracted_evidence": "4 years at Netflix", "cited_text": "Data Scientist @ Netflix 2020-2024", "sub_score": 0.8, "extracted_years": 4},
                {"key": "project_relevance", "extracted_evidence": "Recommendation system matches JD", "cited_text": "Built recommendation engine", "sub_score": 0.75, "anchor_description": "Multiple projects clearly relevant"},
            ]
        })
        results = _parse_llm_response(response, SKILL_RUBRIC, target_years=5)
        assert len(results) == 3
        assert results[0].key == "skill_presence"
        assert results[0].sub_score == 1.0
        assert results[1].key == "years_experience"
        assert results[1].extracted_years == 4.0
        # Linear score should be computed: min(4/5, 1.0) = 0.8
        assert results[1].sub_score == 0.8
        assert results[2].key == "project_relevance"
        assert results[2].anchor_description == "Multiple projects clearly relevant"

    def test_binary_clamped_to_0_or_1(self):
        response = json.dumps({
            "sub_scores": [
                {"key": "skill_presence", "sub_score": 0.7},
                {"key": "years_experience", "sub_score": 0.5, "extracted_years": 2.5},
                {"key": "project_relevance", "sub_score": 0.5},
            ]
        })
        results = _parse_llm_response(response, SKILL_RUBRIC, target_years=5)
        # 0.7 >= 0.5 → clamped to 1.0
        assert results[0].sub_score == 1.0

    def test_invalid_json_returns_defaults(self):
        results = _parse_llm_response("not json at all", SKILL_RUBRIC, target_years=5)
        assert len(results) == 3
        assert all(r.sub_score == 0.0 for r in results)

    def test_missing_sub_scores_returns_defaults(self):
        response = json.dumps({"sub_scores": []})
        results = _parse_llm_response(response, SKILL_RUBRIC, target_years=5)
        assert len(results) == 3
        assert all(r.sub_score == 0.0 for r in results)

    def test_json_in_markdown_fence(self):
        response = '```json\n{"sub_scores": [{"key": "skill_presence", "sub_score": 1.0}, {"key": "years_experience", "sub_score": 0.8, "extracted_years": 4}, {"key": "project_relevance", "sub_score": 0.75}]}\n```'
        results = _parse_llm_response(response, SKILL_RUBRIC, target_years=5)
        assert len(results) == 3
        assert results[0].sub_score == 1.0

    def test_sub_score_clamped_to_0_1(self):
        response = json.dumps({
            "sub_scores": [
                {"key": "skill_presence", "sub_score": 1.5},
                {"key": "years_experience", "sub_score": 1.2, "extracted_years": 10},
                {"key": "project_relevance", "sub_score": -0.5},
            ]
        })
        results = _parse_llm_response(response, SKILL_RUBRIC, target_years=5)
        assert results[0].sub_score == 1.0  # clamped from 1.5
        assert results[1].sub_score == 1.0  # min(10/5, 1.0) = 1.0
        assert results[2].sub_score == 0.0  # clamped from -0.5


# ---------------------------------------------------------------------------
# Formula evaluation
# ---------------------------------------------------------------------------

class TestFormulaEvaluation:
    """The formula should be evaluated in code, never by the LLM."""

    def test_skill_formula_gate_times_ratio_times_relevance(self):
        sub_scores = [
            SubScoreResult(key="skill_presence", question="", sub_score=1.0),
            SubScoreResult(key="years_experience", question="", sub_score=0.8, target_years=5),
            SubScoreResult(key="project_relevance", question="", sub_score=0.75),
        ]
        result = _evaluate_formula(SKILL_RUBRIC.formula, sub_scores)
        assert result == pytest.approx(0.6)  # 1.0 * 0.8 * 0.75

    def test_zero_gate_produces_zero(self):
        sub_scores = [
            SubScoreResult(key="skill_presence", question="", sub_score=0.0),
            SubScoreResult(key="years_experience", question="", sub_score=0.8, target_years=5),
            SubScoreResult(key="project_relevance", question="", sub_score=0.75),
        ]
        result = _evaluate_formula(SKILL_RUBRIC.formula, sub_scores)
        assert result == 0.0

    def test_leadership_formula_with_leadership_gate(self):
        sub_scores = [
            SubScoreResult(key="experience_presence", question="", sub_score=1.0),
            SubScoreResult(key="years_experience", question="", sub_score=0.8, target_years=6),
            SubScoreResult(key="leadership_gate", question="", sub_score=1.0),
            SubScoreResult(key="project_relevance", question="", sub_score=0.5),
        ]
        result = _evaluate_formula(LEADERSHIP_RUBRIC.formula, sub_scores)
        assert result == 0.4  # 1.0 * 0.8 * 1.0 * 0.5

    def test_leadership_zero_gate(self):
        sub_scores = [
            SubScoreResult(key="experience_presence", question="", sub_score=1.0),
            SubScoreResult(key="years_experience", question="", sub_score=1.0, target_years=6),
            SubScoreResult(key="leadership_gate", question="", sub_score=0.0),
            SubScoreResult(key="project_relevance", question="", sub_score=1.0),
        ]
        result = _evaluate_formula(LEADERSHIP_RUBRIC.formula, sub_scores)
        assert result == 0.0

    def test_result_clamped_to_0_1(self):
        sub_scores = [
            SubScoreResult(key="skill_presence", question="", sub_score=1.0),
            SubScoreResult(key="years_experience", question="", sub_score=1.0, target_years=5),
            SubScoreResult(key="project_relevance", question="", sub_score=1.0),
        ]
        result = _evaluate_formula(SKILL_RUBRIC.formula, sub_scores)
        assert result == 1.0


# ---------------------------------------------------------------------------
# score_requirement_with_rubric — end-to-end with mock LLM
# ---------------------------------------------------------------------------

class TestScoreRequirementWithRubric:
    """End-to-end scoring with a mock LLM caller."""

    def test_full_scoring_flow(self):
        evidence = _make_evidence(
            "Data Scientist @ Netflix | 2020-Present\n- Built recommendation engine in Python\n"
            "Skills: Python, SQL, Spark"
        )
        mock = _mock_llm({
            "sub_scores": [
                {"key": "skill_presence", "extracted_evidence": "Skills section: Python listed", "cited_text": "Python, SQL, Spark", "sub_score": 1.0},
                {"key": "years_experience", "extracted_evidence": "4 years at Netflix (2020-Present)", "cited_text": "Data Scientist @ Netflix 2020-Present", "sub_score": 0.8, "extracted_years": 4},
                {"key": "project_relevance", "extracted_evidence": "Recommendation engine directly matches JD", "cited_text": "Built recommendation engine in Python", "sub_score": 0.75, "anchor_description": "Multiple projects clearly relevant"},
            ]
        })
        trace = score_requirement_with_rubric(
            requirement_name="Python",
            dimension_type="skill",
            weight=10,
            evidence=evidence,
            target_years=5,
            llm_caller=mock,
        )
        assert trace.requirement_name == "Python"
        assert trace.dimension_type == "skill"
        assert trace.weight == 10
        assert len(trace.sub_scores) == 3
        # 1.0 * 0.8 * 0.75 = 0.6
        assert trace.normalized_score == pytest.approx(0.6)
        # 10 * 0.6 = 6.0
        assert trace.weighted_score == pytest.approx(6.0)

    def test_no_evidence_returns_zero(self):
        evidence = _make_evidence("")
        trace = score_requirement_with_rubric(
            "Python", "skill", 10, evidence, target_years=5,
            llm_caller=_mock_llm({"sub_scores": []}),
        )
        assert trace.normalized_score == 0.0
        assert trace.weighted_score == 0.0

    def test_no_llm_caller_returns_zero(self):
        evidence = _make_evidence("Some text")
        trace = score_requirement_with_rubric(
            "Python", "skill", 10, evidence, target_years=5,
            llm_caller=None,
        )
        assert trace.normalized_score == 0.0

    def test_llm_exception_returns_zero(self):
        def failing_llm(prompt):
            raise RuntimeError("API error")

        evidence = _make_evidence("Some text")
        trace = score_requirement_with_rubric(
            "Python", "skill", 10, evidence, target_years=5,
            llm_caller=failing_llm,
        )
        assert trace.normalized_score == 0.0

    def test_cached_trace_contains_all_fields(self):
        evidence = _make_evidence("Python experience")
        mock = _mock_llm({
            "sub_scores": [
                {"key": "skill_presence", "sub_score": 1.0, "cited_text": "Python"},
                {"key": "years_experience", "sub_score": 0.8, "extracted_years": 4},
                {"key": "project_relevance", "sub_score": 0.75, "anchor_description": "Clearly relevant"},
            ]
        })
        trace = score_requirement_with_rubric(
            "Python", "skill", 10, evidence, target_years=5,
            llm_caller=mock,
        )
        d = trace.to_dict()
        assert "requirement_name" in d
        assert "sub_scores" in d
        assert "normalized_score" in d
        assert "weighted_score" in d
        assert "formula" in d
        assert d["formula"] == "gate * years_ratio * relevance"


# ---------------------------------------------------------------------------
# Score explanation — narrate from cache
# ---------------------------------------------------------------------------

class TestExplainScoreFromCache:
    """The explanation should read from the cache, not re-score."""

    def test_explanation_contains_requirement_name(self):
        trace = CachedScoringTrace(
            requirement_name="Python",
            dimension_type="skill",
            weight=10,
            sub_scores=[SubScoreResult(key="skill_presence", question="Knows Python?", sub_score=1.0)],
            normalized_score=0.8,
            weighted_score=8.0,
            formula="gate * years_ratio * relevance",
            sections_read=["Experience", "Skills"],
            chunk_ids=["c1"],
        )
        explanation = explain_score_from_cache(trace)
        assert "Python" in explanation
        assert "0.80" in explanation or "0.8" in explanation
        assert "8.0" in explanation

    def test_explanation_contains_sub_scores(self):
        trace = CachedScoringTrace(
            requirement_name="Power BI",
            dimension_type="skill",
            weight=8,
            sub_scores=[
                SubScoreResult(key="skill_presence", question="Knows Power BI?", sub_score=1.0, cited_text="Power BI in skills"),
                SubScoreResult(key="years_experience", question="Years?", sub_score=0.5, extracted_years=3, target_years=6),
                SubScoreResult(key="project_relevance", question="Relevance?", sub_score=0.5, anchor_description="One project partially relevant"),
            ],
            normalized_score=0.25,
            weighted_score=2.0,
            formula="gate * years_ratio * relevance",
            sections_read=["Experience", "Projects", "Skills"],
            chunk_ids=["c1", "c2"],
        )
        explanation = explain_score_from_cache(trace)
        assert "skill_presence" in explanation
        assert "years_experience" in explanation
        assert "project_relevance" in explanation
        assert "Power BI in skills" in explanation
        assert "One project partially relevant" in explanation
        assert "3" in explanation  # extracted_years
        assert "6" in explanation  # target_years

    def test_explanation_contains_formula_and_sections(self):
        trace = CachedScoringTrace(
            requirement_name="Python",
            dimension_type="skill",
            weight=10,
            sub_scores=[],
            normalized_score=0.0,
            weighted_score=0.0,
            formula="gate * years_ratio * relevance",
            sections_read=["Experience", "Skills"],
            chunk_ids=[],
        )
        explanation = explain_score_from_cache(trace)
        assert "gate * years_ratio * relevance" in explanation
        assert "Experience" in explanation


# ---------------------------------------------------------------------------
# Determinism — same input, same output
# ---------------------------------------------------------------------------

class TestDeterminism:
    """Scoring must be reproducible given the same inputs."""

    def test_same_mock_llm_same_result(self):
        evidence = _make_evidence("Python experience at Netflix")
        mock = _mock_llm({
            "sub_scores": [
                {"key": "skill_presence", "sub_score": 1.0},
                {"key": "years_experience", "sub_score": 0.8, "extracted_years": 4},
                {"key": "project_relevance", "sub_score": 0.75},
            ]
        })
        trace1 = score_requirement_with_rubric("Python", "skill", 10, evidence, 5, mock)
        trace2 = score_requirement_with_rubric("Python", "skill", 10, evidence, 5, mock)
        assert trace1.normalized_score == trace2.normalized_score
        assert trace1.weighted_score == trace2.weighted_score
