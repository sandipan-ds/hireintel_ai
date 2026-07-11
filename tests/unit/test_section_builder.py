"""Unit tests for the section builder (DEC-035)."""

import pytest

from src.resume_parsing.extraction.element import ExtractedElement
from src.resume_parsing.extraction.section_builder import (
    clean_header,
    match_section_header,
    build_sections,
)


def test_clean_header():
    """Verify that headers are normalized properly."""
    assert clean_header("  Work  History:  ") == "work history"
    assert clean_header("SKILLS & KEY COMPETENCIES") == "skills key competencies"


def test_match_section_header_exact():
    """Verify exact synonym match."""
    assert match_section_header("Experience") == "experience"
    assert match_section_header("Work Experience") == "experience"
    assert match_section_header("Employment History") == "experience"
    assert match_section_header("Education") == "education"


def test_match_section_header_prefix_suffix():
    """Verify header matching with prefix/suffix words."""
    assert match_section_header("My Skills") == "skills"
    assert match_section_header("Professional Experience") == "experience"
    assert match_section_header("Languages Spoken") == "languages"


def test_match_section_header_none():
    """Verify unmatched headers return None."""
    assert match_section_header("Random Unmatched Header") is None
    assert match_section_header("") is None


def test_build_sections_empty():
    """Verify handling of empty element lists."""
    res = build_sections([])
    for sec in ["summary", "skills", "experience", "education", "certifications", "projects", "languages", "other"]:
        assert res[sec] == []


def test_build_sections_pre_header_default():
    """Verify text before any header defaults to summary."""
    elements = [
        ExtractedElement(text="John Doe", element_type="paragraph", page_number=1),
        ExtractedElement(text="Software Engineer", element_type="paragraph", page_number=1),
    ]
    res = build_sections(elements)
    assert res["summary"] == ["John Doe", "Software Engineer"]


def test_build_sections_grouping():
    """Verify correct grouping under headings."""
    elements = [
        ExtractedElement(text="John Doe", element_type="paragraph", page_number=1),
        ExtractedElement(text="Experience", element_type="heading", page_number=1),
        ExtractedElement(text="Software Engineer at Acme", element_type="paragraph", page_number=1),
        ExtractedElement(text="Worked on APIs", element_type="paragraph", page_number=1),
        ExtractedElement(text="Education", element_type="heading", page_number=1),
        ExtractedElement(text="BS CS", element_type="paragraph", page_number=1),
    ]
    res = build_sections(elements)
    assert res["summary"] == ["John Doe"]
    assert res["experience"] == ["Software Engineer at Acme", "Worked on APIs"]
    assert res["education"] == ["BS CS"]


def test_build_sections_unrecognized_header():
    """Verify unrecognized headings are mapped to other along with their header text."""
    elements = [
        ExtractedElement(text="Interests", element_type="heading", page_number=1),
        ExtractedElement(text="Hiking and reading", element_type="paragraph", page_number=1),
    ]
    res = build_sections(elements)
    assert res["other"] == ["Interests", "Hiking and reading"]


def test_build_sections_languages_section():
    """Verify languages section is kept separate."""
    elements = [
        ExtractedElement(text="Languages", element_type="heading", page_number=1),
        ExtractedElement(text="English (Native), French (Fluent)", element_type="paragraph", page_number=1),
    ]
    res = build_sections(elements)
    assert res["languages"] == ["English (Native), French (Fluent)"]
    assert "Languages" not in res["other"]


def test_build_sections_ignores_empty_elements():
    """Verify elements with only whitespace are skipped."""
    elements = [
        ExtractedElement(text="   ", element_type="paragraph", page_number=1),
        ExtractedElement(text="Experience", element_type="heading", page_number=1),
        ExtractedElement(text="\n", element_type="paragraph", page_number=1),
        ExtractedElement(text="Software Engineer", element_type="paragraph", page_number=1),
    ]
    res = build_sections(elements)
    assert res["experience"] == ["Software Engineer"]
