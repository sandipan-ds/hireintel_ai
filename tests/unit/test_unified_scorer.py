"""Tests for the unified scoring engine — code-only + rubric-bound LLM."""

import json
import pytest
from src.rag.document_aware_chunker import ChunkRecord
from src.resume_parsing.structured_profile import (
    StructuredCandidateProfile,
    DegreeEntry,
    CertificationEntry,
    EmploymentEntry,
)
from src.scoring.unified_scorer import (
    UnifiedCandidateEvaluation,
    UnifiedItemEvaluation,
    evaluate_candidate_unified,
    _score_education_code_only,
    _score_certification_code_only,
    _score_location_code_only,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chunks():
    """Create candidate chunks for testing."""
    return [
        ChunkRecord(
            chunk_id="c1", candidate_id="cand_test", role_bucket="Test",
            source_file="test.pdf", section="Experience", chunk_index=0,
            text="Data Scientist @ Netflix | 2020-Present\n- Built recommendation engine in Python",
            char_span=(0, 80), section_type="experience",
            skills_asserted=["Python", "Spark"],
        ),
        ChunkRecord(
            chunk_id="c2", candidate_id="cand_test", role_bucket="Test",
            source_file="test.pdf", section="Skills", chunk_index=0,
            text="Python, SQL, Spark, Tableau, Power BI",
            char_span=(0, 40), section_type="skills",
            skills_asserted=["Python", "SQL", "Spark", "Tableau", "Power BI"],
        ),
        ChunkRecord(
            chunk_id="c3", candidate_id="cand_test", role_bucket="Test",
            source_file="test.pdf", section="Education", chunk_index=0,
            text="BTech in Computer Science, IIT Bombay, 2014-2018",
            char_span=(0, 50), section_type="education",
        ),
        ChunkRecord(
            chunk_id="c4", candidate_id="cand_test", role_bucket="Test",
            source_file="test.pdf", section="Certifications", chunk_index=0,
            text="AWS Solutions Architect Associate",
            char_span=(0, 35), section_type="certifications",
        ),
        ChunkRecord(
            chunk_id="c5", candidate_id="cand_test", role_bucket="Test",
            source_file="test.pdf", section="Languages", chunk_index=0,
            text="English (Native), Hindi (Proficient)",
            char_span=(0, 35), section_type="languages",
        ),
        ChunkRecord(
            chunk_id="c6", candidate_id="cand_test", role_bucket="Test",
            source_file="test.pdf", section="Personal_Info", chunk_index=0,
            text="John Doe | Mumbai, India",
            char_span=(0, 25), section_type="personal_info",
        ),
    ]


def _make_structured_profile():
    return StructuredCandidateProfile(
        candidate_id="cand_test",
        degrees=[DegreeEntry(degree="BTech", field="Computer Science",
                             institution="IIT Bombay", year="2014-2018")],
        certifications=[CertificationEntry(name="AWS Solutions Architect Associate",
                                           provider="Amazon Web Services")],
        total_experience_years=4.0,
        companies=["Netflix"],
        roles=["Data Scientist"],
        employment_history=[EmploymentEntry(company="Netflix", role="Data Scientist",
                                            dates="2020-Present",
                                            calculated_duration_months=48,
                                            is_current=True)],
    )


def _make_weights():
    return {
        "role": "DataScience",
        "max_score": 40,
        "scale_factor": 100.0 / 40,
        "categories": [
            {
                "name": "Core Skills",
                "items": [
                    {"name": "Python", "importance": 10, "expected_years": 5},
                ],
            },
            {
                "name": "Education",
                "items": [
                    {"name": "BTech", "importance": 6},
                ],
            },
            {
                "name": "Certifications",
                "items": [
                    {"name": "AWS Certified", "importance": 8},
                ],
            },
            {
                "name": "Location",
                "items": [
                    {"name": "Mumbai", "importance": 5},
                ],
            },
        ],
    }


def _mock_llm_skill(response_json=None):
    """Mock LLM that returns skill scoring results."""
    if response_json is None:
        response_json = {
            "sub_scores": [
                {"key": "skill_presence", "extracted_evidence": "Python in skills",
                 "cited_text": "Python, SQL, Spark", "sub_score": 1.0},
                {"key": "years_experience", "extracted_evidence": "4 years at Netflix",
                 "cited_text": "Data Scientist @ Netflix 2020-Present",
                 "sub_score": 0.8, "extracted_years": 4},
                {"key": "project_relevance", "extracted_evidence": "Recommendation engine",
                 "cited_text": "Built recommendation engine in Python",
                 "sub_score": 0.75, "anchor_description": "Multiple projects clearly relevant"},
            ]
        }
    def caller(prompt: str) -> str:
        return json.dumps(response_json)
    return caller


# ---------------------------------------------------------------------------
# Code-only scoring — education
# ---------------------------------------------------------------------------

class TestEducationCodeOnly:
    """Education should be scored with degree match + institute tier lookup."""

    def test_btech_iit_tier_1(self):
        sp = _make_structured_profile()
        result = _score_education_code_only("BTech", 6, sp)
        assert result.matched is True
        assert result.scoring_mode == "code_only"
        # IIT Bombay is Tier 1 (1.0) → raw = 1.0 * 1.0 * 6 = 6.0
        assert result.raw_score == pytest.approx(6.0)
        assert result.scoring_trace is not None
        assert result.scoring_trace["sub_scores"][0]["sub_score"] == 1.0
        assert result.scoring_trace["sub_scores"][1]["sub_score"] == 1.0

    def test_no_degree_match(self):
        sp = StructuredCandidateProfile(candidate_id="c", degrees=[])
        result = _score_education_code_only("BTech", 6, sp)
        assert result.matched is False
        assert result.raw_score == 0.0


# ---------------------------------------------------------------------------
# Code-only scoring — certification
# ---------------------------------------------------------------------------

class TestCertificationCodeOnly:
    """Certification should be scored with cert match + provider tier lookup."""

    def test_aws_tier_1(self):
        sp = _make_structured_profile()
        result = _score_certification_code_only("AWS Certified", 8, sp)
        assert result.matched is True
        assert result.scoring_mode == "code_only"
        # AWS is Tier 1 (1.0) → raw = 1.0 * 1.0 * 8 = 8.0
        assert result.raw_score == pytest.approx(8.0)

    def test_no_cert_match(self):
        sp = StructuredCandidateProfile(candidate_id="c", certifications=[])
        result = _score_certification_code_only("AWS Certified", 8, sp)
        assert result.matched is False
        assert result.raw_score == 0.0

    # Regression: Short abbreviations must NOT match longer tokens that
    # merely contain them as substrings. Previously "_score_*_code_only"
    # used a bare ``in`` substring check, so "BA" matched "MBA", "BS"
    # matched "BSE", and "PMP" matched "PMPI". The fix uses
    # ``_token_boundary_match`` (word-boundary regex).
    def test_education_no_ba_in_mba_false_positive(self):
        sp = StructuredCandidateProfile(
            candidate_id="c",
            degrees=[DegreeEntry(degree="MBA", field="Business",
                                 institution="Wharton", year="2018-2020")],
        )
        # Requirement "BA" must NOT match degree "MBA" — word boundaries
        # correctly reject "ba" inside "mba" (no left boundary because
        # the preceding "m" is a letter).
        result = _score_education_code_only("BA", 6, sp)
        assert result.matched is False
        assert result.raw_score == 0.0

    def test_education_no_bs_in_bse_false_positive(self):
        sp = StructuredCandidateProfile(
            candidate_id="c",
            degrees=[DegreeEntry(degree="BSE", field="Engineering",
                                 institution="Stanford", year="2014-2018")],
        )
        # Requirement "BS" must NOT match degree "BSE" — they are distinct
        # degrees and the bare substring "bs" in "bse" used to false-match.
        result = _score_education_code_only("BS", 6, sp)
        assert result.matched is False
        assert result.raw_score == 0.0

    def test_education_ba_matches_real_ba_degree(self):
        # Sanity: real "BA" degree still matches BA requirement.
        sp = StructuredCandidateProfile(
            candidate_id="c",
            degrees=[DegreeEntry(degree="BA", field="English",
                                 institution="Yale", year="2014-2018")],
        )
        result = _score_education_code_only("BA", 6, sp)
        assert result.matched is True

    def test_education_btech_in_btech_computer_science(self):
        # Sanity: "BTech" requirement still matches degree string
        # "BTech in Computer Science" — substring is whole word.
        sp = StructuredCandidateProfile(
            candidate_id="c",
            degrees=[DegreeEntry(degree="BTech in Computer Science",
                                 institution="IIT Bombay", field="CS",
                                 year="2014-2018")],
        )
        result = _score_education_code_only("BTech", 6, sp)
        assert result.matched is True

    def test_cert_no_pmp_in_pmpi_false_positive(self):
        sp = StructuredCandidateProfile(
            candidate_id="c",
            certifications=[CertificationEntry(
                name="PMPI by Project Management Prep Institute",
                provider="Project Management Prep Institute")],
        )
        # Requirement "PMP" must NOT match cert "PMPI" — they are distinct
        # programs and the bare substring "pmp" in "pmpi" used to false-match.
        result = _score_certification_code_only("PMP", 8, sp)
        assert result.matched is False
        assert result.raw_score == 0.0

    def test_cert_pmp_match_in_pmp_certified(self):
        sp = StructuredCandidateProfile(
            candidate_id="c",
            certifications=[CertificationEntry(
                name="PMP Certified by PMI",
                provider="Project Management Institute")],
        )
        # Sanity: PMP still matches "PMP Certified" (word boundary works
        # because there's a space after "PMP").
        result = _score_certification_code_only("PMP", 8, sp)
        assert result.matched is True


# ---------------------------------------------------------------------------
# Code-only scoring — location
# ---------------------------------------------------------------------------

class TestLocationCodeOnly:
    """Location should be scored as a binary match from the profile."""

    def test_location_match(self):
        profile = {"raw_text": "John Doe | Mumbai, India"}
        result = _score_location_code_only("Mumbai", 5, profile)
        assert result.matched is True
        assert result.raw_score == pytest.approx(5.0)

    def test_location_no_match(self):
        profile = {"raw_text": "John Doe | Delhi, India"}
        result = _score_location_code_only("Mumbai", 5, profile)
        assert result.matched is False
        assert result.raw_score == 0.0


# ---------------------------------------------------------------------------
# Unified scoring — end-to-end
# ---------------------------------------------------------------------------

class TestEvaluateCandidateUnified:
    """The unified scorer should route items to the correct mode."""

    def test_skill_routed_to_rubric_llm(self):
        chunks = _make_chunks()
        sp = _make_structured_profile()
        weights = _make_weights()
        result = evaluate_candidate_unified(
            {"candidate_id": "cand_test", "raw_text": "Mumbai"},
            weights, chunks, sp, llm_caller=_mock_llm_skill(),
        )
        # Find the Python item.
        skill_item = None
        for cat in result.categories:
            for item in cat.items:
                if item.item_name == "Python":
                    skill_item = item
        assert skill_item is not None
        assert skill_item.scoring_mode == "rubric_llm"
        assert skill_item.scoring_trace is not None
        # Banded years-ratio (4 yrs vs target 5): 4 ≥ 0.5*5 → 0.5
        # Formula: 1.0 * 0.5 * 0.75 = 0.375; 10 * 0.375 = 3.75
        assert skill_item.raw_score == pytest.approx(3.75)

    def test_education_routed_to_code_only(self):
        chunks = _make_chunks()
        sp = _make_structured_profile()
        weights = _make_weights()
        result = evaluate_candidate_unified(
            {"candidate_id": "cand_test", "raw_text": "Mumbai"},
            weights, chunks, sp, llm_caller=_mock_llm_skill(),
        )
        edu_item = None
        for cat in result.categories:
            for item in cat.items:
                if item.item_name == "BTech":
                    edu_item = item
        assert edu_item is not None
        assert edu_item.scoring_mode == "code_only"
        assert edu_item.scoring_trace is not None

    def test_certification_routed_to_code_only(self):
        chunks = _make_chunks()
        sp = _make_structured_profile()
        weights = _make_weights()
        result = evaluate_candidate_unified(
            {"candidate_id": "cand_test", "raw_text": "Mumbai"},
            weights, chunks, sp, llm_caller=_mock_llm_skill(),
        )
        cert_item = None
        for cat in result.categories:
            for item in cat.items:
                if item.item_name == "AWS Certified":
                    cert_item = item
        assert cert_item is not None
        assert cert_item.scoring_mode == "code_only"

    def test_location_routed_to_code_only(self):
        chunks = _make_chunks()
        sp = _make_structured_profile()
        weights = _make_weights()
        result = evaluate_candidate_unified(
            {"candidate_id": "cand_test", "raw_text": "Mumbai, India"},
            weights, chunks, sp, llm_caller=_mock_llm_skill(),
        )
        loc_item = None
        for cat in result.categories:
            for item in cat.items:
                if item.item_name == "Mumbai":
                    loc_item = item
        assert loc_item is not None
        assert loc_item.scoring_mode == "code_only"
        assert loc_item.matched is True

    def test_total_score_is_deterministic(self):
        chunks = _make_chunks()
        sp = _make_structured_profile()
        weights = _make_weights()
        result1 = evaluate_candidate_unified(
            {"candidate_id": "cand_test", "raw_text": "Mumbai"},
            weights, chunks, sp, llm_caller=_mock_llm_skill(),
        )
        result2 = evaluate_candidate_unified(
            {"candidate_id": "cand_test", "raw_text": "Mumbai"},
            weights, chunks, sp, llm_caller=_mock_llm_skill(),
        )
        assert result1.total == result2.total

    def test_no_llm_caller_gives_zero_for_rubric_items(self):
        chunks = _make_chunks()
        sp = _make_structured_profile()
        weights = _make_weights()
        result = evaluate_candidate_unified(
            {"candidate_id": "cand_test", "raw_text": "Mumbai"},
            weights, chunks, sp, llm_caller=None,
        )
        skill_item = None
        for cat in result.categories:
            for item in cat.items:
                if item.item_name == "Python":
                    skill_item = item
        assert skill_item is not None
        assert skill_item.scoring_mode == "rubric_llm"
        assert skill_item.raw_score == 0.0

    def test_to_dict_includes_scoring_mode_and_trace(self):
        chunks = _make_chunks()
        sp = _make_structured_profile()
        weights = _make_weights()
        result = evaluate_candidate_unified(
            {"candidate_id": "cand_test", "raw_text": "Mumbai"},
            weights, chunks, sp, llm_caller=_mock_llm_skill(),
        )
        d = result.to_dict()
        assert "categories" in d
        first_item = d["categories"][0]["items"][0]
        assert "scoring_mode" in first_item
        assert "scoring_trace" in first_item

    def test_all_items_have_scoring_mode(self):
        chunks = _make_chunks()
        sp = _make_structured_profile()
        weights = _make_weights()
        result = evaluate_candidate_unified(
            {"candidate_id": "cand_test", "raw_text": "Mumbai"},
            weights, chunks, sp, llm_caller=_mock_llm_skill(),
        )
        for cat in result.categories:
            for item in cat.items:
                assert item.scoring_mode in ("code_only", "rubric_llm")
                assert item.scoring_trace is not None
