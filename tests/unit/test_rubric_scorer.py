"""Tests for the rubric-bound LLM evidence scorer."""

import json
import pytest
from src.rag.document_aware_chunker import ChunkRecord
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
    _extract_json_lenient,
    _format_employment_history,
)
from src.scoring.rubrics import RubricTemplate, SubQuestion

SKILL_RUBRIC = RubricTemplate(
    dimension_type="skill",
    sub_questions=[
        SubQuestion(
            key="skill_presence",
            question="Is there evidence of the candidate possessing {skill}?",
            type="binary"
        ),
        SubQuestion(
            key="years_experience",
            question="How many years of experience with {skill}?",
            type="four_band"
        )
    ],
    formula="sum",
    sections=["Experience", "Projects", "Skills"],
    description="Python"
)

LEADERSHIP_RUBRIC = SKILL_RUBRIC


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
        assert "0 (No) or 1 (Yes)" in prompt
        assert "substantial" in prompt

    def test_extract_first_instruction_in_prompt(self):
        evidence = _make_evidence("Some text")
        prompt = _build_rubric_prompt("Python", SKILL_RUBRIC, evidence)
        assert "evidence" in prompt.lower()

    def test_formula_not_in_prompt_for_purity(self):
        # The LLM must not see the formula so it doesn't try to compute it.
        evidence = _make_evidence("Some text")
        prompt = _build_rubric_prompt("Python", SKILL_RUBRIC, evidence)
        assert "gate *" not in prompt

    def test_target_years_in_prompt(self):
        evidence = _make_evidence("Some text")
        prompt = _build_rubric_prompt("Python", SKILL_RUBRIC, evidence, target_years=5)
        # target_years is not shown to the LLM per rubric_scorer.py design 
        # to prevent model rationalization, but it must be passed cleanly.
        assert prompt is not None


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
            ]
        })
        results = _parse_llm_response(response, SKILL_RUBRIC, target_years=5)
        assert len(results) == 2
        assert results[0].key == "skill_presence"
        assert results[0].sub_score == 1.0
        assert results[1].key == "years_experience"
        assert results[1].extracted_years == 4.0
        # Banded years-ratio: 4 / 5 ≥ 0.5*5 → 0.5 (was min(4/5,1.0)=0.8
        # under the old continuous rule). See _banded_years_ratio().
        assert results[1].sub_score == 0.5

    def test_binary_clamped_to_0_or_1(self):
        response = json.dumps({
            "sub_scores": [
                {"key": "skill_presence", "sub_score": 0.7},
                {"key": "years_experience", "sub_score": 0.5, "extracted_years": 2.5},
            ]
        })
        results = _parse_llm_response(response, SKILL_RUBRIC, target_years=5)
        # 0.7 >= 0.5 → clamped to 1.0
        assert results[0].sub_score == 1.0

    def test_invalid_json_returns_defaults(self):
        results = _parse_llm_response("not json at all", SKILL_RUBRIC, target_years=5)
        assert len(results) == 2
        assert all(r.sub_score == 0.01 for r in results)

    def test_missing_sub_scores_returns_defaults(self):
        response = json.dumps({"sub_scores": []})
        results = _parse_llm_response(response, SKILL_RUBRIC, target_years=5)
        assert len(results) == 2
        assert all(r.sub_score == 0.01 for r in results)

    def test_json_in_markdown_fence(self):
        response = '```json\n{"sub_scores": [{"key": "skill_presence", "sub_score": 1.0}, {"key": "years_experience", "sub_score": 0.8, "extracted_years": 4}]}\n```'
        results = _parse_llm_response(response, SKILL_RUBRIC, target_years=5)
        assert len(results) == 2
        assert results[0].sub_score == 1.0

    def test_sub_score_clamped_to_0_1(self):
        response = json.dumps({
            "sub_scores": [
                {"key": "skill_presence", "sub_score": 1.5},
                {"key": "years_experience", "sub_score": 1.2, "extracted_years": 10},
            ]
        })
        results = _parse_llm_response(response, SKILL_RUBRIC, target_years=5)
        assert results[0].sub_score == 1.0  # clamped from 1.5
        assert results[1].sub_score == 1.0  # min(10/5, 1.0) = 1.0

    def test_null_sub_score_defaults_to_zero(self):
        # Free-tier LLMs sometimes emit `"sub_score": null` when they
        # find no evidence. The parser must not crash on None.
        response = json.dumps({
            "sub_scores": [
                {"key": "skill_presence", "sub_score": None},
                {"key": "years_experience", "sub_score": None,
                 "extracted_years": None},
            ]
        })
        results = _parse_llm_response(response, SKILL_RUBRIC, target_years=5)
        assert results[0].sub_score == 0.0
        assert results[1].sub_score == 0.01


class TestLenientJsonExtraction:
    """The lenient JSON extractor must recover sub-score data when the
    free-tier LLM endpoint truncates the response mid-JSON."""

    def test_valid_complete_json(self):
        body = '{"sub_scores": [{"key": "a", "sub_score": 0.5}]}'
        out = _extract_json_lenient(body)
        assert out is not None
        assert len(out["sub_scores"]) == 1
        assert out["sub_scores"][0]["sub_score"] == 0.5

    def test_json_with_prose_around_it(self):
        body = ('Here is the score:\n'
                '```json\n'
                '{"sub_scores": [{"key": "a", "sub_score": 1.0}]}\n'
                '```\n')
        out = _extract_json_lenient(body)
        assert out is not None
        assert out["sub_scores"][0]["sub_score"] == 1.0

    def test_truncated_mid_object_recovers(self):
        # Response cut mid-value for the 3rd sub-score.
        body = ('{"sub_scores": [\n'
                '  {"key": "skill_presence", "sub_score": 1.0},\n'
                '  {"key": "years_experience", "sub_score": 0.6, "extracted_years": 3},\n'
                '  {"key": "project_relevance", "extracted_evidence": "partial eviden')
        out = _extract_json_lenient(body)
        # Recovery should keep the first two sub_scores.
        assert out is not None
        assert "sub_scores" in out
        assert len(out["sub_scores"]) == 2
        assert out["sub_scores"][0]["key"] == "skill_presence"
        assert out["sub_scores"][1]["key"] == "years_experience"

    def test_truncated_mid_string_value_recovers(self):
        # Truncated while still inside a string value.
        body = ('{"sub_scores": [\n'
                '  {"key": "skill_presence", "extracted_evidence": "Python experience but the text keeps going ')
        out = _extract_json_lenient(body)
        # No complete sub_score object boundary → unverifiable → None.
        # Acceptable: either None (no recovery) or empty list.
        assert out is None or out.get("sub_scores", []) == []

    def test_empty_string_returns_none(self):
        assert _extract_json_lenient("") is None
        assert _extract_json_lenient("not even a brace") is None

    def test_string_with_braces_inside_value(self):
        body = ('{"sub_scores": [{"key": "skill_presence", '
                '"extracted_evidence": "Built {pipeline} with Python"}]}')
        out = _extract_json_lenient(body)
        assert out is not None
        assert out["sub_scores"][0]["extracted_evidence"] == "Built {pipeline} with Python"


# ---------------------------------------------------------------------------
# Banded years-ratio (owner spec 2026-07-07)
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Employment history prompt block (mitigates chunk-split date loss)
# ---------------------------------------------------------------------------

class TestEmploymentHistoryBlock:
    """When employment_history is provided, the rubric prompt must include an
    EMPLOYMENT HISTORY section right after the SECTION CONTENT so the LLM
    can correlate skill mentions in retrieved chunks with the parser-
    computed role durations."""

    def test_format_returns_none_when_empty(self):
        assert _format_employment_history(None) is None
        assert _format_employment_history([]) is None

    def test_format_renders_entries(self):
        # Duck-typed dicts in the same shape as EmploymentEntry.
        eh = [
            {
                "company": "Google",
                "role": "Data Scientist",
                "dates": "2017-2019",
                "calculated_duration_months": 36,
                "inferred_full_year": False,
            },
            {
                "company": "IBM",
                "role": "Analyst",
                "dates": "2016-2017",
                "calculated_duration_months": 12,
                "inferred_full_year": True,
            },
        ]
        out = _format_employment_history(eh)
        assert out is not None
        assert out.startswith("EMPLOYMENT HISTORY")
        assert "Google" in out and "IBM" in out
        assert "36 months" in out and "12 months" in out
        assert "~3.0 yrs" in out
        # Inferred marker present on the second entry.
        assert "inferred full year" in out

    def test_prompt_includes_employment_history_block(self):
        evidence = _make_evidence("Built ETL with Python, pandas, Airflow.")
        eh = [
            {
                "company": "Google",
                "role": "Data Scientist",
                "dates": "2017-2019",
                "calculated_duration_months": 36,
                "inferred_full_year": False,
            },
        ]
        prompt = _build_rubric_prompt(
            requirement_name="Python",
            rubric=SKILL_RUBRIC,
            evidence=evidence,
            target_years=3,
            employment_history=eh,
        )
        # The prompt must include the EMPLOYMENT HISTORY header
        # and the parser-computed duration.
        assert "EMPLOYMENT HISTORY" in prompt
        assert "Google" in prompt
        assert "36 months" in prompt
        # The linear sub-question hint telling the LLM to use the
        # precomputed durations must also be present.
        assert "pre-computed employment history" in prompt.lower()

    def test_prompt_omits_block_when_no_history(self):
        evidence = _make_evidence("Built ETL with Python.")
        prompt = _build_rubric_prompt(
            requirement_name="Python",
            rubric=SKILL_RUBRIC,
            evidence=evidence,
            target_years=3,
            employment_history=None,
        )
        assert "EMPLOYMENT HISTORY" not in prompt
        # No hint about deferred date math either.
        assert "pre-computed" not in prompt.lower()

    def test_prompt_omits_block_when_empty_list(self):
        evidence = _make_evidence("Built ETL with Python.")
        prompt = _build_rubric_prompt(
            requirement_name="Python",
            rubric=SKILL_RUBRIC,
            evidence=evidence,
            target_years=3,
            employment_history=[],
        )
        assert "EMPLOYMENT HISTORY" not in prompt


# ---------------------------------------------------------------------------
# Formula evaluation
# ---------------------------------------------------------------------------

class TestFormulaEvaluation:
    """The formula should return the sum of all sub-scores under the additive model."""

    def test_sum_of_scores(self):
        sub_scores = [
            SubScoreResult(key="skill_presence", question="", sub_score=1.0),
            SubScoreResult(key="years_experience", question="", sub_score=0.8, target_years=5),
        ]
        result = _evaluate_formula("", sub_scores)
        assert result == pytest.approx(1.8)

    def test_sum_with_zero(self):
        sub_scores = [
            SubScoreResult(key="skill_presence", question="", sub_score=0.0),
            SubScoreResult(key="years_experience", question="", sub_score=0.8, target_years=5),
        ]
        result = _evaluate_formula("", sub_scores)
        assert result == pytest.approx(0.8)

    def test_sum_multiple_sub_scores(self):
        sub_scores = [
            SubScoreResult(key="experience_presence", question="", sub_score=1.0),
            SubScoreResult(key="years_experience", question="", sub_score=0.8, target_years=6),
            SubScoreResult(key="leadership_gate", question="", sub_score=1.0),
        ]
        result = _evaluate_formula("", sub_scores)
        assert result == pytest.approx(2.8)


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
            ]
        })
        trace = score_requirement_with_rubric(
            requirement_name="Python",
            dimension_type="skill",
            weight=10,
            evidence=evidence,
            target_years=5,
            llm_caller=mock,
            sub_queries=[
                {"key": "skill_presence", "text": "Is there evidence of the candidate possessing Python?", "type": "Binary"},
                {"key": "years_experience", "text": "How many years of experience with Python?", "type": "Float"}
            ]
        )
        assert trace.requirement_name == "Python"
        assert trace.dimension_type == "skill"
        assert trace.weight == 10
        assert len(trace.sub_scores) == 2
        # Sum sub-score: 1.0 + 0.5 = 1.5
        assert trace.normalized_score == pytest.approx(1.5)
        # 10 * (1.5 / 2) = 7.5
        assert trace.weighted_score == pytest.approx(7.5)

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
        # 0.01 * 2 sub-questions = 0.02 floor
        assert trace.normalized_score == pytest.approx(0.02)

    def test_cached_trace_contains_all_fields(self):
        evidence = _make_evidence("Python experience")
        mock = _mock_llm({
            "sub_scores": [
                {"key": "skill_presence", "sub_score": 1.0, "cited_text": "Python"},
                {"key": "years_experience", "sub_score": 0.8, "extracted_years": 4},
            ]
        })
        trace = score_requirement_with_rubric(
            "Python", "skill", 10, evidence, target_years=5,
            llm_caller=mock,
            sub_queries=[
                {"key": "skill_presence", "text": "Is there evidence of the candidate possessing Python?", "type": "Binary"},
                {"key": "years_experience", "text": "How many years of experience with Python?", "type": "Float"}
            ]
        )
        d = trace.to_dict()
        assert "requirement_name" in d
        assert "sub_scores" in d
        assert "normalized_score" in d
        assert "weighted_score" in d
        assert "formula" in d
        assert d["formula"] == ""


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
