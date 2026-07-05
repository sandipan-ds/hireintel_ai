"""Tests for header normalization — Layer 1 synonym lookup and Layer 2 fallback."""

from src.resume_parsing.header_normalization import (
    CANONICAL_SECTIONS,
    HeaderClassification,
    get_synonym_table,
    normalize_headers,
    normalize_single_header,
    synonym_lookup,
)


# ---------------------------------------------------------------------------
# Layer 1 — Synonym lookup (deterministic, no model call)
# ---------------------------------------------------------------------------

class TestSynonymLookup:
    """Layer 1 should catch common synonyms without any LLM call."""

    def test_exact_match_skills(self):
        assert synonym_lookup("Skills") == "Skills"
        assert synonym_lookup("Technical Skills") == "Skills"
        assert synonym_lookup("Core Competencies") == "Skills"
        assert synonym_lookup("Technical Proficiencies") == "Skills"

    def test_exact_match_experience(self):
        assert synonym_lookup("Work Experience") == "Experience"
        assert synonym_lookup("Employment History") == "Experience"
        assert synonym_lookup("Professional Experience") == "Experience"
        assert synonym_lookup("Job Experience") == "Experience"
        assert synonym_lookup("Career History") == "Experience"

    def test_exact_match_education(self):
        assert synonym_lookup("Education") == "Education"
        assert synonym_lookup("Academic Background") == "Education"
        assert synonym_lookup("Academic Qualifications") == "Education"

    def test_exact_match_certifications(self):
        assert synonym_lookup("Certifications") == "Certifications"
        assert synonym_lookup("Licenses") == "Certifications"
        assert synonym_lookup("Credentials") == "Certifications"
        assert synonym_lookup("Licenses & Certifications") == "Certifications"

    def test_exact_match_personal_info(self):
        assert synonym_lookup("Personal Information") == "Personal_Info"
        assert synonym_lookup("Contact") == "Personal_Info"
        assert synonym_lookup("Summary") == "Personal_Info"
        assert synonym_lookup("About Me") == "Personal_Info"

    def test_exact_match_projects(self):
        assert synonym_lookup("Projects") == "Projects"
        assert synonym_lookup("Selected Projects") == "Projects"

    def test_exact_match_languages(self):
        assert synonym_lookup("Languages") == "Languages"
        assert synonym_lookup("Language Skills") == "Languages"

    def test_case_insensitive(self):
        assert synonym_lookup("SKILLS") == "Skills"
        assert synonym_lookup("EDUCATION") == "Education"
        assert synonym_lookup("Work EXPERIENCE") == "Experience"

    def test_strips_decorations(self):
        assert synonym_lookup("Skills:") == "Skills"
        assert synonym_lookup("**Skills**") == "Skills"
        assert synonym_lookup("# Experience") == "Experience"
        assert synonym_lookup("• Education") == "Education"

    def test_prefix_match(self):
        assert synonym_lookup("Skills & Tools") == "Skills"
        assert synonym_lookup("Skills&Tools") == "Skills"
        assert synonym_lookup("Experience and Training") == "Experience"

    def test_no_match_returns_none(self):
        assert synonym_lookup("Random Header XYZ") is None
        assert synonym_lookup("") is None
        assert synonym_lookup("   ") is None


# ---------------------------------------------------------------------------
# normalize_headers — batch API
# ---------------------------------------------------------------------------

class TestNormalizeHeaders:
    """Batch normalization should produce one HeaderClassification per input."""

    def test_all_matched_by_synonym(self):
        headers = ["Skills", "Work Experience", "Education", "Certifications"]
        results = normalize_headers(headers)
        assert len(results) == 4
        assert results[0].canonical_section == "Skills"
        assert results[1].canonical_section == "Experience"
        assert results[2].canonical_section == "Education"
        assert results[3].canonical_section == "Certifications"
        assert all(r.method == "synonym_lookup" for r in results)
        assert all(r.confidence == 1.0 for r in results)

    def test_mixed_match_and_unmatch_without_llm(self):
        headers = ["Skills", "Random Unknown Header"]
        results = normalize_headers(headers, llm_caller=None)
        assert results[0].canonical_section == "Skills"
        assert results[0].method == "synonym_lookup"
        assert results[1].method == "fallback_classification"
        assert results[1].confidence == 0.0
        # Without LLM, defaults to Personal_Info.
        assert results[1].canonical_section == "Personal_Info"

    def test_preserves_original_header(self):
        headers = ["**Technical Skills**", "Random Header"]
        results = normalize_headers(headers, llm_caller=None)
        assert results[0].original_header == "**Technical Skills**"
        assert results[1].original_header == "Random Header"

    def test_empty_list(self):
        assert normalize_headers([]) == []


# ---------------------------------------------------------------------------
# normalize_single_header — single API
# ---------------------------------------------------------------------------

class TestNormalizeSingleHeader:
    def test_synonym_match(self):
        result = normalize_single_header("Core Competencies")
        assert result.canonical_section == "Skills"
        assert result.method == "synonym_lookup"

    def test_unmatch_without_llm(self):
        result = normalize_single_header("XYZ Random", llm_caller=None)
        assert result.method == "fallback_classification"
        assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# Layer 2 — Fallback LLM classification
# ---------------------------------------------------------------------------

class TestFallbackClassification:
    """Layer 2 should use the LLM caller when provided."""

    def test_llm_fallback_valid_response(self):
        def mock_llm(prompt: str) -> str:
            return '{"section": "Skills", "confidence": 0.85}'

        result = normalize_single_header("Random Unknown Header", llm_caller=mock_llm)
        assert result.canonical_section == "Skills"
        assert result.method == "fallback_classification"
        assert result.confidence == 0.85

    def test_llm_fallback_invalid_section_defaults(self):
        def mock_llm(prompt: str) -> str:
            return '{"section": "InvalidSection", "confidence": 0.5}'

        result = normalize_single_header("Random Header", llm_caller=mock_llm)
        assert result.canonical_section == "Personal_Info"
        assert result.confidence == 0.5

    def test_llm_fallback_malformed_json_defaults(self):
        def mock_llm(prompt: str) -> str:
            return "This is not JSON at all."

        result = normalize_single_header("Random Header", llm_caller=mock_llm)
        assert result.canonical_section == "Personal_Info"
        assert result.confidence == 0.0

    def test_llm_fallback_json_in_markdown_fence(self):
        def mock_llm(prompt: str) -> str:
            return '```json\n{"section": "Education", "confidence": 0.9}\n```'

        result = normalize_single_header("Random Header", llm_caller=mock_llm)
        assert result.canonical_section == "Education"
        assert result.confidence == 0.9


# ---------------------------------------------------------------------------
# Canonical sections validation
# ---------------------------------------------------------------------------

class TestCanonicalSections:
    def test_seven_sections(self):
        assert len(CANONICAL_SECTIONS) == 7

    def test_personal_info_present(self):
        assert "Personal_Info" in CANONICAL_SECTIONS

    def test_all_synonyms_map_to_canonical(self):
        table = get_synonym_table()
        for _, canonical in table.items():
            assert canonical in CANONICAL_SECTIONS
