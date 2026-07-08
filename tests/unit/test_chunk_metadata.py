"""Tests for the chunk metadata schema and date parsing utilities."""

from src.rag.document_aware_chunker import (
    ChunkRecord,
    _classify_experience_type,
    _extract_skills_asserted,
    parse_temporal_context,
    chunk_profile,
)


# ---------------------------------------------------------------------------
# parse_temporal_context — deterministic date parsing
# ---------------------------------------------------------------------------

class TestParseTemporalContext:
    """Date parsing must be deterministic and produce calculated_duration_months in code."""

    def test_year_range(self):
        ctx = parse_temporal_context("2017 - 2023")
        assert ctx["start_date"]["year"] == 2017
        assert ctx["end_date"]["year"] == 2023
        assert ctx["is_current"] is False
        assert ctx["calculated_duration_months"] == 84  # 7 years inclusive

    def test_month_year_range(self):
        ctx = parse_temporal_context("Jun 2019 — Dec 2022")
        assert ctx["start_date"]["year"] == 2019
        assert ctx["start_date"]["month"] == 6
        assert ctx["end_date"]["year"] == 2022
        assert ctx["end_date"]["month"] == 12
        assert ctx["calculated_duration_months"] == 43  # Jun 2019 to Dec 2022 inclusive

    def test_present_ongoing(self):
        ctx = parse_temporal_context("2020 - Present")
        assert ctx["start_date"]["year"] == 2020
        assert ctx["is_current"] is True
        # Duration should be > 0 (computed against today).
        assert ctx["calculated_duration_months"] is not None
        assert ctx["calculated_duration_months"] > 0

    def test_current_keyword(self):
        ctx = parse_temporal_context("Jan 2018 – Current")
        assert ctx["start_date"]["year"] == 2018
        assert ctx["start_date"]["month"] == 1
        assert ctx["is_current"] is True

    def test_ongoing_keyword(self):
        ctx = parse_temporal_context("2019 — Ongoing")
        assert ctx["is_current"] is True

    def test_empty_string(self):
        ctx = parse_temporal_context("")
        assert ctx["start_date"] is None
        assert ctx["end_date"] is None
        assert ctx["is_current"] is False
        assert ctx["calculated_duration_months"] is None

    def test_unparseable(self):
        ctx = parse_temporal_context("some random text")
        assert ctx["start_date"] is None
        assert ctx["calculated_duration_months"] is None

    def test_single_year(self):
        # Track 7.2 (DEC-031): a single year alone is treated as a full
        # year of employment (start=Jan, end=Dec → 12 months inclusive
        # both ends), with an ``inferred_full_year`` flag set so callers
        # can audit / override. The guard against cert/education
        # mis-bucketing is applied at the structured-profile call site.
        ctx = parse_temporal_context("2020")
        assert ctx["start_date"]["year"] == 2020
        assert ctx["start_date"]["month"] == 1
        assert ctx["end_date"]["month"] == 12
        assert ctx["calculated_duration_months"] == 12
        assert ctx["inferred_full_year"] is True

    def test_unparseable_text_has_no_inferred_full_year_flag(self):
        # When the date string can't be parsed at all, ``inferred_full_year``
        # must be False (not missing). Callers use this flag to decide
        # whether to emit an audit record.
        ctx = parse_temporal_context("some random text")
        assert ctx.get("inferred_full_year") is False

    def test_year_range_not_inferred(self):
        # A real "2018 - 2020" range is NOT an inferred-full-year entry —
        # the start and end are both explicit, so the ``inferred_full_year``
        # flag should be False (or missing — both treated as False).
        ctx = parse_temporal_context("2018 - 2020")
        assert ctx["calculated_duration_months"] == 36  # Jan 2018..Dec 2020
        assert not ctx.get("inferred_full_year", False)

    def test_slash_format(self):
        ctx = parse_temporal_context("01/2020 - 06/2023")
        assert ctx["start_date"]["year"] == 2020
        assert ctx["start_date"]["month"] == 1
        assert ctx["end_date"]["year"] == 2023
        assert ctx["end_date"]["month"] == 6
        assert ctx["calculated_duration_months"] == 42  # Jan 2020 to Jun 2023 inclusive


# ---------------------------------------------------------------------------
# _extract_skills_asserted
# ---------------------------------------------------------------------------

class TestExtractSkillsAsserted:
    """Skills assertion should find known skills in chunk text."""

    def test_finds_known_skills(self):
        text = "Built recommendation engine in Python using Spark and SQL"
        known = ["Python", "Spark", "SQL", "Java"]
        result = _extract_skills_asserted(text, known)
        assert "Python" in result
        assert "Spark" in result
        assert "SQL" in result
        assert "Java" not in result

    def test_empty_text(self):
        assert _extract_skills_asserted("", ["Python"]) == []

    def test_no_known_skills(self):
        assert _extract_skills_asserted("Some text here", None) == []


# ---------------------------------------------------------------------------
# _classify_experience_type
# ---------------------------------------------------------------------------

class TestClassifyExperienceType:
    """Experience type classification should be deterministic."""

    def test_experience_section_is_professional(self):
        assert _classify_experience_type("Senior Engineer @ Google", "experience") == "professional"

    def test_education_section_is_academic(self):
        assert _classify_experience_type("BS in Computer Science", "education") == "academic"

    def test_projects_academic(self):
        text = "University thesis project on machine learning"
        assert _classify_experience_type(text, "projects") == "academic"

    def test_projects_personal(self):
        text = "Personal side project: built a web app"
        assert _classify_experience_type(text, "projects") == "personal_project"

    def test_projects_professional(self):
        text = "Built recommendation system for Netflix"
        assert _classify_experience_type(text, "projects") == "professional"


# ---------------------------------------------------------------------------
# ChunkRecord — full metadata schema in chunk_profile output
# ---------------------------------------------------------------------------

class TestChunkMetadataSchema:
    """Chunks from chunk_profile should carry the full metadata schema."""

    def _make_profile(self):
        """Create a minimal profile for testing."""
        return {
            "candidate_id": "cand_test123",
            "source_file": "/fake/path.pdf",
            "skills": ["Python", "SQL", "Power BI"],
            "experience": {
                "entries": [
                    {
                        "title": "Data Scientist",
                        "company": "Netflix",
                        "dates": "2020 - Present",
                        "location": "California",
                        "details": [
                            "Built recommendation engine in Python",
                            "Used SQL for data analysis",
                        ],
                    }
                ]
            },
            "education": {
                "entries": [
                    {"description": "BS in Computer Science, MIT, 2016-2020"}
                ]
            },
            "projects": [
                "Built a clustering system using Python for academic research at University"
            ],
            "summary": {"value": "Data Scientist with 4+ years of experience"},
        }

    def test_experience_chunk_has_section_type(self):
        chunks = chunk_profile(self._make_profile(), "DataScience")
        exp_chunks = [c for c in chunks if c.section == "experience"]
        assert len(exp_chunks) == 1
        assert exp_chunks[0].section_type == "experience"

    def test_experience_chunk_has_parent_structure(self):
        chunks = chunk_profile(self._make_profile(), "DataScience")
        exp = [c for c in chunks if c.section == "experience"][0]
        assert exp.parent_structure["organization"] == "Netflix"
        assert exp.parent_structure["role_title"] == "Data Scientist"
        assert exp.parent_structure["location"] == "California"

    def test_experience_chunk_has_temporal_context(self):
        chunks = chunk_profile(self._make_profile(), "DataScience")
        exp = [c for c in chunks if c.section == "experience"][0]
        tc = exp.parent_structure["temporal_context"]
        assert tc["start_date"]["year"] == 2020
        assert tc["is_current"] is True
        assert tc["calculated_duration_months"] is not None
        assert tc["calculated_duration_months"] > 0

    def test_experience_chunk_has_skills_asserted(self):
        chunks = chunk_profile(self._make_profile(), "DataScience")
        exp = [c for c in chunks if c.section == "experience"][0]
        assert "Python" in exp.skills_asserted
        assert "SQL" in exp.skills_asserted

    def test_experience_chunk_has_experience_type(self):
        chunks = chunk_profile(self._make_profile(), "DataScience")
        exp = [c for c in chunks if c.section == "experience"][0]
        assert exp.experience_type == "professional"

    def test_education_chunk_has_experience_type_academic(self):
        chunks = chunk_profile(self._make_profile(), "DataScience")
        edu = [c for c in chunks if c.section == "education"][0]
        assert edu.experience_type == "academic"
        assert edu.section_type == "education"

    def test_projects_chunk_has_experience_type(self):
        chunks = chunk_profile(self._make_profile(), "DataScience")
        proj = [c for c in chunks if c.section == "projects"][0]
        assert proj.experience_type == "academic"  # mentions "academic" and "University"
        assert proj.section_type == "projects"

    def test_to_dict_includes_schema_fields(self):
        chunks = chunk_profile(self._make_profile(), "DataScience")
        exp = [c for c in chunks if c.section == "experience"][0]
        d = exp.to_dict()
        assert "section_type" in d
        assert "parent_structure" in d
        assert "skills_asserted" in d
        assert "experience_type" in d
        assert d["section_type"] == "experience"
        assert d["experience_type"] == "professional"
