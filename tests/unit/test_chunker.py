"""Unit tests for the Document-Aware chunker."""

import json
from pathlib import Path

import pytest

from src.rag.document_aware_chunker import (
    MAX_CHUNK_CHARS,
    SPLIT_OVERLAP_CHARS,
    ChunkRecord,
    chunk_profile,
)


@pytest.fixture
def sample_profile() -> dict:
    """A representative parsed profile for testing."""
    return {
        "candidate_id": "cand_unit_test0001",
        "source_file": "data/original/BusinessAnalyst/sample.pdf",
        "raw_text": "Placeholder raw text.",
        "sections": {
            "summary": {"text": "Experienced analyst.", "start": 0, "end": 20},
            "experience": {"text": "Lots of detail.", "start": 21, "end": 100},
        },
        "name": {"value": "Test Person", "source": "first non-contact line"},
        "contact": {"emails": ["t@example.com"], "phones": ["555-1212"]},
        "summary": {"value": "Experienced analyst.", "source": "summary section"},
        "experience": {
            "raw": "Analyst @ Acme | 2020 - Present | Remote\n- Did stuff\n- Did more",
            "entries": [
                {
                    "title": "Senior Analyst",
                    "company": "Acme",
                    "dates": "2020 - Present",
                    "location": "Remote",
                    "details": ["Did stuff", "Did more"],
                },
                {
                    "title": "Junior Analyst",
                    "company": "Beta",
                    "dates": "2018 - 2020",
                    "location": "NY",
                    "details": ["Made charts"],
                },
            ],
            "count": 2,
        },
        "education": {
            "raw": "BS CS, MIT, 2018",
            "entries": [
                {"description": "BS Computer Science, MIT, 2018"},
                {"description": "MS Data Science, Stanford, 2020"},
            ],
            "count": 2,
        },
        "skills": ["Python", "SQL", "Tableau"],
        "certifications": ["PMP"],
        "projects": ["Forecast Engine (Python, 2022)"],
        "languages": ["English", "Spanish"],
    }


def test_chunk_profile_emits_one_chunk_per_experience_entry(sample_profile):
    chunks = chunk_profile(sample_profile, role_bucket="BusinessAnalyst")
    experience_chunks = [c for c in chunks if c.section == "experience"]
    assert len(experience_chunks) == 2
    assert experience_chunks[0].metadata["title"] == "Senior Analyst"
    assert experience_chunks[0].metadata["company"] == "Acme"
    assert "Did stuff" in experience_chunks[0].text


def test_chunk_profile_emits_one_chunk_per_education_entry(sample_profile):
    chunks = chunk_profile(sample_profile, role_bucket="BusinessAnalyst")
    education_chunks = [c for c in chunks if c.section == "education"]
    assert len(education_chunks) == 2
    assert "BS Computer Science" in education_chunks[0].text


def test_chunk_profile_summary_chunk_is_present(sample_profile):
    chunks = chunk_profile(sample_profile, role_bucket="BusinessAnalyst")
    summary = [c for c in chunks if c.section == "summary"]
    assert len(summary) == 1
    assert "Experienced analyst." in summary[0].text


def test_chunk_profile_skips_empty_fields(sample_profile):
    sample_profile["skills"] = []
    sample_profile["certifications"] = []
    sample_profile["languages"] = []
    sample_profile["projects"] = []
    chunks = chunk_profile(sample_profile, role_bucket="BusinessAnalyst")
    assert not any(c.section == "skills" for c in chunks)
    assert not any(c.section == "certifications" for c in chunks)


def test_chunk_ids_are_unique(sample_profile):
    chunks = chunk_profile(sample_profile, role_bucket="BusinessAnalyst")
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))


def test_large_section_is_split_into_smaller_chunks(sample_profile):
    # Build a giant summary to force sub-splitting.
    big_para_a = "Paragraph A. " * 50
    big_para_b = "Paragraph B. " * 50
    sample_profile["summary"]["value"] = f"{big_para_a}\n\n{big_para_b}"
    chunks = chunk_profile(sample_profile, role_bucket="BusinessAnalyst")
    summary_chunks = [c for c in chunks if c.section == "summary"]
    assert len(summary_chunks) >= 2
    for chunk in summary_chunks:
        assert len(chunk.text) <= MAX_CHUNK_CHARS + SPLIT_OVERLAP_CHARS + 1


def test_to_dict_round_trip(sample_profile):
    chunks = chunk_profile(sample_profile, role_bucket="BusinessAnalyst")
    for chunk in chunks:
        d = chunk.to_dict()
        # Should serialize cleanly to JSON.
        json.dumps(d)
        assert d["candidate_id"] == "cand_unit_test0001"
        assert d["role_bucket"] == "BusinessAnalyst"


def test_role_bucket_propagates_to_chunks(sample_profile):
    chunks = chunk_profile(sample_profile, role_bucket="DataScience")
    assert all(c.role_bucket == "DataScience" for c in chunks)
