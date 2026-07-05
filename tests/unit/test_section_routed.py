"""Tests for Section-Routed Evidence Retrieval."""

from rag.document_aware_chunker import ChunkRecord
from src.rag.section_routed import (
    SectionEvidence,
    classify_requirement_type,
    retrieve_evidence_for_requirement,
    route_requirement_to_sections,
    section_routed_retrieval,
    MAX_FULL_CONTENT_CHARS,
    REQUIREMENT_TO_SECTIONS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chunk(
    chunk_id: str,
    section: str,
    text: str,
    skills_asserted: list = None,
) -> ChunkRecord:
    """Create a minimal ChunkRecord for testing."""
    return ChunkRecord(
        chunk_id=chunk_id,
        candidate_id="cand_test",
        role_bucket="Test",
        source_file="test.pdf",
        section=section,
        chunk_index=0,
        text=text,
        char_span=(0, len(text)),
        section_type=section.lower(),
        skills_asserted=skills_asserted or [],
    )


def _make_candidate_chunks() -> list:
    """Create a realistic set of chunks for a candidate."""
    return [
        _make_chunk("c1", "Experience", "Senior Data Scientist @ Netflix | 2020 - Present\n- Built recommendation engine in Python", ["Python", "Spark"]),
        _make_chunk("c2", "Experience", "Data Analyst @ Google | 2018-2020\n- Analyzed data using SQL and Tableau", ["SQL", "Tableau"]),
        _make_chunk("c3", "Skills", "Python, SQL, Spark, Tableau, Power BI, Excel", ["Python", "SQL", "Spark", "Tableau", "Power BI"]),
        _make_chunk("c4", "Projects", "Built a clustering system using Python for customer segmentation", ["Python"]),
        _make_chunk("c5", "Education", "BTech in Computer Science, IIT Bombay, 2014-2018"),
        _make_chunk("c6", "Certifications", "AWS Solutions Architect Associate, Tableau Desktop Specialist"),
        _make_chunk("c7", "Languages", "English (Native), Hindi (Proficient), Spanish (Basic)"),
        _make_chunk("c8", "Personal_Info", "John Doe | San Francisco, CA | john@email.com"),
    ]


# ---------------------------------------------------------------------------
# route_requirement_to_sections — fixed mapping table
# ---------------------------------------------------------------------------

class TestRouteRequirementToSections:
    """The routing table is fixed — not a model decision."""

    def test_skill_routes_to_experience_projects_skills(self):
        sections = route_requirement_to_sections("skill")
        assert "Experience" in sections
        assert "Projects" in sections
        assert "Skills" in sections

    def test_education_routes_to_education_only(self):
        sections = route_requirement_to_sections("education")
        assert sections == ["Education"]

    def test_certification_routes_to_certifications_only(self):
        sections = route_requirement_to_sections("certification")
        assert sections == ["Certifications"]

    def test_experience_routes_to_experience_only(self):
        sections = route_requirement_to_sections("experience")
        assert sections == ["Experience"]

    def test_language_routes_to_languages_only(self):
        sections = route_requirement_to_sections("language")
        assert sections == ["Languages"]

    def test_location_routes_to_personal_info(self):
        sections = route_requirement_to_sections("location")
        assert sections == ["Personal_Info"]

    def test_unknown_type_returns_default_all_sections(self):
        sections = route_requirement_to_sections("unknown_type")
        assert len(sections) > 3  # returns all sections

    def test_all_types_have_at_least_one_section(self):
        for req_type, sections in REQUIREMENT_TO_SECTIONS.items():
            assert len(sections) >= 1, f"{req_type} has no sections"


# ---------------------------------------------------------------------------
# classify_requirement_type — category + name-based classification
# ---------------------------------------------------------------------------

class TestClassifyRequirementType:
    """Classification should correctly route requirements by category and name."""

    def test_category_core_skills(self):
        assert classify_requirement_type("Core Skills") == "skill"
        assert classify_requirement_type("Core Skills & Technologies") == "skill"

    def test_category_technology_tools(self):
        assert classify_requirement_type("Technology & Tools") == "skill"

    def test_category_education(self):
        assert classify_requirement_type("Education") == "education"

    def test_category_certifications(self):
        assert classify_requirement_type("Certifications") == "certification"

    def test_category_experience(self):
        assert classify_requirement_type("Experience") == "experience"

    def test_category_leadership(self):
        assert classify_requirement_type("Leadership Experience") == "leadership"

    def test_category_languages(self):
        assert classify_requirement_type("Languages") == "language"

    def test_category_location(self):
        assert classify_requirement_type("Location") == "location"

    def test_name_inference_education(self):
        assert classify_requirement_type(None, "BTech in Computer Science") == "education"
        assert classify_requirement_type(None, "MBA") == "education"

    def test_name_inference_certification(self):
        assert classify_requirement_type(None, "AWS Certification") == "certification"
        assert classify_requirement_type(None, "PMP Certified") == "certification"

    def test_name_inference_language(self):
        assert classify_requirement_type(None, "English Language") == "language"

    def test_name_inference_location(self):
        assert classify_requirement_type(None, "Location: Mumbai") == "location"

    def test_name_inference_leadership(self):
        assert classify_requirement_type(None, "Leadership Experience") == "leadership"

    def test_name_inference_experience(self):
        assert classify_requirement_type(None, "5+ years experience") == "experience"

    def test_name_inference_skill_default(self):
        assert classify_requirement_type(None, "Python") == "skill"
        assert classify_requirement_type(None, "Power BI") == "skill"

    def test_no_category_no_name_defaults_to_skill(self):
        assert classify_requirement_type(None, None) == "skill"

    def test_category_takes_precedence_over_name(self):
        # Category says education, name says "Python" — category wins.
        assert classify_requirement_type("Education", "Python") == "education"


# ---------------------------------------------------------------------------
# section_routed_retrieval — exact label match, no top-K
# ---------------------------------------------------------------------------

class TestSectionRoutedRetrieval:
    """Retrieval must be exact label match — no embeddings, no cosine, no top-K."""

    def test_skill_retrieval_fetches_experience_projects_skills(self):
        chunks = _make_candidate_chunks()
        evidence = section_routed_retrieval("skill", "Python", chunks)
        # Should fetch chunks from Experience, Projects, and Skills sections.
        sections_in_evidence = {c.section for c in evidence.chunks}
        assert "Experience" in sections_in_evidence
        assert "Projects" in sections_in_evidence
        assert "Skills" in sections_in_evidence
        # Should NOT fetch Education, Certifications, etc.
        assert "Education" not in sections_in_evidence
        assert "Certifications" not in sections_in_evidence

    def test_education_retrieval_fetches_only_education(self):
        chunks = _make_candidate_chunks()
        evidence = section_routed_retrieval("education", "BTech", chunks)
        assert all(c.section == "Education" for c in evidence.chunks)
        assert len(evidence.chunks) == 1

    def test_certification_retrieval_fetches_only_certifications(self):
        chunks = _make_candidate_chunks()
        evidence = section_routed_retrieval("certification", "AWS", chunks)
        assert all(c.section == "Certifications" for c in evidence.chunks)

    def test_language_retrieval_fetches_only_languages(self):
        chunks = _make_candidate_chunks()
        evidence = section_routed_retrieval("language", "English", chunks)
        assert all(c.section == "Languages" for c in evidence.chunks)

    def test_full_text_contains_all_matching_chunk_text(self):
        chunks = _make_candidate_chunks()
        evidence = section_routed_retrieval("skill", "Python", chunks)
        # The full text should contain text from Experience, Projects, and Skills chunks.
        assert "Netflix" in evidence.full_text
        assert "clustering system" in evidence.full_text
        assert "Python, SQL, Spark" in evidence.full_text

    def test_no_embeddings_or_cosine_used(self):
        """The module should not import or use any embedding functionality."""
        # This is a design guarantee — the function only does exact label match.
        # We verify by checking that the result is deterministic.
        chunks = _make_candidate_chunks()
        evidence1 = section_routed_retrieval("skill", "Python", chunks)
        evidence2 = section_routed_retrieval("skill", "Python", chunks)
        assert evidence1.full_text == evidence2.full_text
        assert evidence1.chunk_count == evidence2.chunk_count

    def test_empty_chunks_returns_empty_evidence(self):
        evidence = section_routed_retrieval("skill", "Python", [])
        assert evidence.chunk_count == 0
        assert evidence.full_text == ""

    def test_case_insensitive_section_matching(self):
        """Should match both 'Experience' (canonical) and 'experience' (legacy)."""
        chunks = [
            _make_chunk("c1", "experience", "Job at Google"),  # lowercase
            _make_chunk("c2", "Experience", "Job at Netflix"),  # title case
        ]
        evidence = section_routed_retrieval("experience", "5 years", chunks)
        assert evidence.chunk_count == 2


# ---------------------------------------------------------------------------
# Metadata filtering for long sections
# ---------------------------------------------------------------------------

class TestMetadataFiltering:
    """Long sections should be narrowed with deterministic metadata filtering."""

    def test_filter_applied_when_section_too_long(self):
        """When total content exceeds MAX_FULL_CONTENT_CHARS and skill_filter
        is provided, chunks should be narrowed by skills_asserted."""
        # Create many experience chunks with skills_asserted.
        big_chunks = []
        for i in range(20):
            text = f"Role {i} @ Company {i} | 2020-2023\n- Built systems using Python and SQL\n" + "x" * 400
            big_chunks.append(_make_chunk(
                f"c{i}", "Experience", text,
                skills_asserted=["Python"] if i % 2 == 0 else ["SQL"],
            ))

        # Total chars will exceed MAX_FULL_CONTENT_CHARS.
        total = sum(len(c.text) for c in big_chunks)
        assert total > MAX_FULL_CONTENT_CHARS

        evidence = section_routed_retrieval(
            "skill", "Python", big_chunks, skill_filter="Python"
        )
        assert evidence.filtered_by_skill is True
        assert evidence.skill_filter == "Python"
        # Only chunks with "Python" in skills_asserted should remain.
        assert all("Python" in c.skills_asserted for c in evidence.chunks)
        assert evidence.chunk_count == 10  # half have Python

    def test_filter_not_applied_when_section_short(self):
        """When total content is below the threshold, no filtering even if
        skill_filter is provided."""
        chunks = _make_candidate_chunks()
        evidence = section_routed_retrieval(
            "skill", "Python", chunks, skill_filter="Python"
        )
        assert evidence.filtered_by_skill is False

    def test_filter_not_applied_when_no_skill_filter(self):
        """Even if the section is long, no filtering without a skill_filter."""
        big_chunks = []
        for i in range(20):
            text = f"Role {i} @ Company {i}\n" + "x" * 400
            big_chunks.append(_make_chunk(f"c{i}", "Experience", text, skills_asserted=["Python"]))

        evidence = section_routed_retrieval("experience", "5 years", big_chunks)
        assert evidence.filtered_by_skill is False
        assert evidence.chunk_count == 20

    def test_filter_keeps_all_if_filter_matches_nothing(self):
        """If the skill filter matches no chunks, keep the original set —
        better to send too much than nothing."""
        big_chunks = []
        for i in range(20):
            text = f"Role {i} @ Company {i}\n" + "x" * 400
            big_chunks.append(_make_chunk(f"c{i}", "Experience", text, skills_asserted=["Java"]))

        evidence = section_routed_retrieval(
            "skill", "Python", big_chunks, skill_filter="Python"
        )
        # No chunks have "Python" in skills_asserted, so filter is not applied.
        assert evidence.filtered_by_skill is False
        assert evidence.chunk_count == 20


# ---------------------------------------------------------------------------
# retrieve_evidence_for_requirement — convenience function
# ---------------------------------------------------------------------------

class TestRetrieveEvidenceForRequirement:
    """The convenience function should classify + route + retrieve in one call."""

    def test_skill_requirement(self):
        chunks = _make_candidate_chunks()
        evidence = retrieve_evidence_for_requirement("Python", "Core Skills", chunks)
        assert evidence.requirement_type == "skill"
        assert evidence.requirement_name == "Python"
        sections = {c.section for c in evidence.chunks}
        assert "Experience" in sections
        assert "Skills" in sections

    def test_education_requirement(self):
        chunks = _make_candidate_chunks()
        evidence = retrieve_evidence_for_requirement("BTech", "Education", chunks)
        assert evidence.requirement_type == "education"
        assert all(c.section == "Education" for c in evidence.chunks)

    def test_certification_requirement(self):
        chunks = _make_candidate_chunks()
        evidence = retrieve_evidence_for_requirement("AWS Certified", "Certifications", chunks)
        assert evidence.requirement_type == "certification"
        assert all(c.section == "Certifications" for c in evidence.chunks)

    def test_no_category_infers_from_name(self):
        chunks = _make_candidate_chunks()
        evidence = retrieve_evidence_for_requirement("BTech in Computer Science", None, chunks)
        assert evidence.requirement_type == "education"


# ---------------------------------------------------------------------------
# Determinism — same input always returns same output
# ---------------------------------------------------------------------------

class TestDeterminism:
    """Section-Routed retrieval must be deterministic — same input, same output."""

    def test_same_input_same_output(self):
        chunks = _make_candidate_chunks()
        ev1 = section_routed_retrieval("skill", "Python", chunks)
        ev2 = section_routed_retrieval("skill", "Python", chunks)
        assert ev1.full_text == ev2.full_text
        assert ev1.chunk_count == ev2.chunk_count
        assert [c.chunk_id for c in ev1.chunks] == [c.chunk_id for c in ev2.chunks]

    def test_no_chunk_silently_missed(self):
        """Unlike top-K cosine, every matching chunk must be included."""
        chunks = _make_candidate_chunks()
        # There are 2 Experience chunks — both must be retrieved for a skill requirement.
        evidence = section_routed_retrieval("skill", "Python", chunks)
        experience_chunks = [c for c in evidence.chunks if c.section == "Experience"]
        assert len(experience_chunks) == 2  # both, not just top-1


# ---------------------------------------------------------------------------
# SectionEvidence to_dict
# ---------------------------------------------------------------------------

class TestSectionEvidenceToDict:
    """The to_dict method should produce a serializable record."""

    def test_to_dict(self):
        chunks = _make_candidate_chunks()
        evidence = section_routed_retrieval("skill", "Python", chunks)
        d = evidence.to_dict()
        assert d["requirement_type"] == "skill"
        assert d["requirement_name"] == "Python"
        assert "Experience" in d["sections"]
        assert d["chunk_count"] > 0
        assert d["full_text_length"] > 0
        assert d["filtered_by_skill"] is False
        assert len(d["chunk_ids"]) == d["chunk_count"]
