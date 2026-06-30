"""Tests for rubric templates — the fixed, recruiter-visible scoring rules."""

from src.scoring.rubrics import (
    Anchor,
    SubQuestion,
    RubricTemplate,
    RUBRIC_REGISTRY,
    SKILL_RUBRIC,
    EXPERIENCE_RUBRIC,
    LEADERSHIP_RUBRIC,
    EDUCATION_RUBRIC,
    CERTIFICATION_RUBRIC,
    PROJECT_RUBRIC,
    LANGUAGE_RUBRIC,
    LOCATION_RUBRIC,
    COMMUNICATION_RUBRIC,
    RESUME_ORGANIZATION_RUBRIC,
    DOMAIN_RUBRIC,
    SAME_ROLE_RUBRIC,
    get_rubric,
    is_code_only,
    is_rubric_bound_llm,
    all_rubric_types,
    BINARY_ANCHORS,
    RELEVANCE_ANCHORS,
    COMPLEXITY_ANCHORS,
    PROFICIENCY_ANCHORS,
)


# ---------------------------------------------------------------------------
# Registry — all dimension types have rubrics
# ---------------------------------------------------------------------------

class TestRubricRegistry:
    """Every dimension type must have a registered rubric."""

    def test_all_expected_types_registered(self):
        expected = {
            "skill", "experience", "leadership", "same_role", "domain",
            "education", "certification", "project", "language", "location",
            "communication", "resume_organization",
        }
        assert set(RUBRIC_REGISTRY.keys()) == expected

    def test_get_rubric_returns_correct_template(self):
        assert get_rubric("skill") is SKILL_RUBRIC
        assert get_rubric("education") is EDUCATION_RUBRIC

    def test_get_rubric_raises_for_unknown_type(self):
        try:
            get_rubric("nonexistent")
            assert False, "Should have raised KeyError"
        except KeyError:
            pass

    def test_all_rubric_types_returns_list(self):
        types = all_rubric_types()
        assert isinstance(types, list)
        assert "skill" in types
        assert "education" in types


# ---------------------------------------------------------------------------
# Code-only vs rubric-bound LLM classification
# ---------------------------------------------------------------------------

class TestCodeOnlyVsLLM:
    """Code-only dimensions use no LLM; rubric-bound use the LLM judge."""

    def test_education_is_code_only(self):
        assert is_code_only("education") is True
        assert is_rubric_bound_llm("education") is False

    def test_certification_is_code_only(self):
        assert is_code_only("certification") is True
        assert is_rubric_bound_llm("certification") is False

    def test_location_is_code_only(self):
        assert is_code_only("location") is True
        assert is_rubric_bound_llm("location") is False

    def test_skill_requires_llm(self):
        assert is_code_only("skill") is False
        assert is_rubric_bound_llm("skill") is True

    def test_experience_requires_llm(self):
        assert is_code_only("experience") is False
        assert is_rubric_bound_llm("experience") is True

    def test_leadership_requires_llm(self):
        assert is_code_only("leadership") is False
        assert is_rubric_bound_llm("leadership") is True

    def test_project_requires_llm(self):
        assert is_code_only("project") is False
        assert is_rubric_bound_llm("project") is True

    def test_language_requires_llm(self):
        assert is_code_only("language") is False
        assert is_rubric_bound_llm("language") is True


# ---------------------------------------------------------------------------
# Skill rubric
# ---------------------------------------------------------------------------

class TestSkillRubric:
    """The skill rubric must have 3 sub-questions: presence, years, relevance."""

    def test_has_three_sub_questions(self):
        assert len(SKILL_RUBRIC.sub_questions) == 3

    def test_sub_question_keys(self):
        keys = [sq.key for sq in SKILL_RUBRIC.sub_questions]
        assert "skill_presence" in keys
        assert "years_experience" in keys
        assert "project_relevance" in keys

    def test_presence_is_binary(self):
        sq = next(sq for sq in SKILL_RUBRIC.sub_questions if sq.key == "skill_presence")
        assert sq.type == "binary"

    def test_years_is_linear(self):
        sq = next(sq for sq in SKILL_RUBRIC.sub_questions if sq.key == "years_experience")
        assert sq.type == "linear"
        assert sq.target_field == "expected_years"

    def test_relevance_is_anchored_with_five_points(self):
        sq = next(sq for sq in SKILL_RUBRIC.sub_questions if sq.key == "project_relevance")
        assert sq.type == "anchored"
        assert len(sq.anchors) == 5
        values = [a.value for a in sq.anchors]
        assert 0.0 in values
        assert 1.0 in values

    def test_formula_is_gate_times_ratio_times_relevance(self):
        assert "gate" in SKILL_RUBRIC.formula
        assert "years_ratio" in SKILL_RUBRIC.formula
        assert "relevance" in SKILL_RUBRIC.formula

    def test_sections_include_experience_projects_skills(self):
        assert "Experience" in SKILL_RUBRIC.sections
        assert "Projects" in SKILL_RUBRIC.sections
        assert "Skills" in SKILL_RUBRIC.sections

    def test_all_sub_questions_extract_first(self):
        assert all(sq.extract_first for sq in SKILL_RUBRIC.sub_questions)


# ---------------------------------------------------------------------------
# Experience rubric
# ---------------------------------------------------------------------------

class TestExperienceRubric:
    def test_has_three_sub_questions(self):
        assert len(EXPERIENCE_RUBRIC.sub_questions) == 3

    def test_formula_includes_gate_and_ratio(self):
        assert "gate" in EXPERIENCE_RUBRIC.formula
        assert "years_ratio" in EXPERIENCE_RUBRIC.formula


# ---------------------------------------------------------------------------
# Leadership rubric — has extra leadership_gate
# ---------------------------------------------------------------------------

class TestLeadershipRubric:
    def test_has_four_sub_questions(self):
        assert len(LEADERSHIP_RUBRIC.sub_questions) == 4

    def test_has_leadership_gate(self):
        keys = [sq.key for sq in LEADERSHIP_RUBRIC.sub_questions]
        assert "leadership_gate" in keys

    def test_formula_includes_leadership_gate(self):
        assert "leadership_gate" in LEADERSHIP_RUBRIC.formula


# ---------------------------------------------------------------------------
# Education rubric — code-only
# ---------------------------------------------------------------------------

class TestEducationRubric:
    def test_has_two_sub_questions(self):
        assert len(EDUCATION_RUBRIC.sub_questions) == 2

    def test_has_degree_match(self):
        keys = [sq.key for sq in EDUCATION_RUBRIC.sub_questions]
        assert "degree_match" in keys

    def test_has_institute_tier(self):
        keys = [sq.key for sq in EDUCATION_RUBRIC.sub_questions]
        assert "institute_tier" in keys

    def test_institute_tier_has_three_anchors(self):
        sq = next(sq for sq in EDUCATION_RUBRIC.sub_questions if sq.key == "institute_tier")
        assert len(sq.anchors) == 3
        values = [a.value for a in sq.anchors]
        assert 1.0 in values
        assert 0.75 in values
        assert 0.50 in values

    def test_formula_is_degree_match_times_tier(self):
        assert "degree_match" in EDUCATION_RUBRIC.formula
        assert "institute_tier_points" in EDUCATION_RUBRIC.formula

    def test_not_extract_first(self):
        """Code-only rubrics don't need LLM extraction."""
        assert all(not sq.extract_first for sq in EDUCATION_RUBRIC.sub_questions)


# ---------------------------------------------------------------------------
# Certification rubric — code-only
# ---------------------------------------------------------------------------

class TestCertificationRubric:
    def test_has_two_sub_questions(self):
        assert len(CERTIFICATION_RUBRIC.sub_questions) == 2

    def test_formula_is_cert_match_times_provider_tier(self):
        assert "cert_match" in CERTIFICATION_RUBRIC.formula
        assert "provider_tier_points" in CERTIFICATION_RUBRIC.formula

    def test_provider_tier_has_three_anchors(self):
        sq = next(sq for sq in CERTIFICATION_RUBRIC.sub_questions if sq.key == "provider_tier")
        assert len(sq.anchors) == 3


# ---------------------------------------------------------------------------
# Project rubric
# ---------------------------------------------------------------------------

class TestProjectRubric:
    def test_has_three_sub_questions(self):
        assert len(PROJECT_RUBRIC.sub_questions) == 3

    def test_has_complexity_anchored_scale(self):
        sq = next(sq for sq in PROJECT_RUBRIC.sub_questions if sq.key == "project_complexity")
        assert sq.type == "anchored"
        assert len(sq.anchors) == 5

    def test_formula_is_presence_times_relevance_times_complexity(self):
        assert "presence" in PROJECT_RUBRIC.formula
        assert "relevance" in PROJECT_RUBRIC.formula
        assert "complexity" in PROJECT_RUBRIC.formula


# ---------------------------------------------------------------------------
# Language rubric
# ---------------------------------------------------------------------------

class TestLanguageRubric:
    def test_has_two_sub_questions(self):
        assert len(LANGUAGE_RUBRIC.sub_questions) == 2

    def test_has_proficiency_anchored_scale(self):
        sq = next(sq for sq in LANGUAGE_RUBRIC.sub_questions if sq.key == "language_proficiency")
        assert sq.type == "anchored"
        assert len(sq.anchors) == 5
        values = [a.value for a in sq.anchors]
        assert 0.0 in values
        assert 1.0 in values


# ---------------------------------------------------------------------------
# Location rubric — code-only, single binary
# ---------------------------------------------------------------------------

class TestLocationRubric:
    def test_has_one_sub_question(self):
        assert len(LOCATION_RUBRIC.sub_questions) == 1

    def test_formula_is_just_match(self):
        assert LOCATION_RUBRIC.formula == "match"


# ---------------------------------------------------------------------------
# Anchor definitions — verify explicit definitions exist
# ---------------------------------------------------------------------------

class TestAnchorDefinitions:
    """Every anchor must have an explicit, non-empty description."""

    def test_binary_anchors(self):
        assert len(BINARY_ANCHORS) == 2
        assert BINARY_ANCHORS[0].value == 0.0
        assert BINARY_ANCHORS[1].value == 1.0
        assert all(a.description for a in BINARY_ANCHORS)

    def test_relevance_anchors_five_points(self):
        assert len(RELEVANCE_ANCHORS) == 5
        values = [a.value for a in RELEVANCE_ANCHORS]
        assert values == [0.0, 0.25, 0.5, 0.75, 1.0]
        assert all(a.description for a in RELEVANCE_ANCHORS)

    def test_complexity_anchors_five_points(self):
        assert len(COMPLEXITY_ANCHORS) == 5
        assert all(a.description for a in COMPLEXITY_ANCHORS)

    def test_proficiency_anchors_five_points(self):
        assert len(PROFICIENCY_ANCHORS) == 5
        assert all(a.description for a in PROFICIENCY_ANCHORS)


# ---------------------------------------------------------------------------
# to_dict serialization
# ---------------------------------------------------------------------------

class TestSerialization:
    """All rubric templates should serialize to dict cleanly."""

    def test_skill_rubric_to_dict(self):
        d = SKILL_RUBRIC.to_dict()
        assert d["dimension_type"] == "skill"
        assert len(d["sub_questions"]) == 3
        assert "formula" in d
        assert "sections" in d

    def test_all_rubrics_serialize(self):
        for rubric in RUBRIC_REGISTRY.values():
            d = rubric.to_dict()
            assert "dimension_type" in d
            assert "sub_questions" in d
            assert "formula" in d
            assert len(d["sub_questions"]) > 0
