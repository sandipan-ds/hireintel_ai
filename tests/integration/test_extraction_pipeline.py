"""Integration tests for the routed extraction pipeline (DEC-035)."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.resume_parsing.extraction.pipeline import extract_resume
from src.resume_parsing.candidate_registry import fresh_registry


@pytest.fixture
def mock_llm_normalizer():
    """Mock normalize_to_schema to prevent API/network calls during tests."""
    with patch("src.resume_parsing.extraction.pipeline.normalize_to_schema") as mock_norm:
        mock_norm.return_value = {
            "full_name": "Integration Test Candidate",
            "headline": "Software Engineer",
            "summary": "Experienced engineer.",
            "skills": [
                {"name_raw": "Python", "name_canonical": "Python", "confidence": 0.9},
                {"name_raw": "SQL", "name_canonical": "SQL", "confidence": 0.8},
            ],
            "education": [
                {
                    "degree": "Bachelor of Science in Computer Science",
                    "institution": "University of Technology",
                    "start_date": "2015-09",
                    "end_date": "2019-05",
                    "confidence": 0.95
                }
            ],
            "experience": [
                {
                    "job_title": "Data Analyst",
                    "role": "Data Analyst",
                    "company": "Analytics Corp",
                    "start_date": "2019-06",
                    "end_date": "2022-12",
                    "is_current": False,
                    "confidence": 0.9
                }
            ],
            "projects": [],
            "certifications": [
                {"name": "AWS Certified Cloud Practitioner", "confidence": 0.98}
            ],
            "languages": ["English"],
            "emails": ["test@example.com"],
            "phones": ["+1-555-0199"],
            "links": {
                "linkedin": "https://linkedin.com/in/test",
                "github": "https://github.com/test",
                "portfolio": None,
                "other": []
            }
        }
        yield mock_norm


def test_extract_resume_integration_fixture_1(mock_llm_normalizer):
    """Verify end-to-end extraction on a real BusinessAnalyst PDF fixture."""
    file_path = Path("data/original/BusinessAnalyst/01888170110d1ccf.pdf")
    if not file_path.exists():
        pytest.skip(f"Test fixture not found: {file_path}")

    registry = fresh_registry()
    result = extract_resume(file_path, registry=registry)

    # 1. Top level check
    assert result["schema_version"] == "1.0.0"
    assert result["candidate_id"] == "BusinessAnalyst_CAND_0001"

    # 2. Document details
    doc = result["document"]
    assert doc["file_name"] == "01888170110d1ccf.pdf"
    assert doc["file_type"] == "pdf"

    # 3. Profile details (from mocked LLM output)
    profile = result["candidate_profile"]
    assert profile["full_name"] == "Integration Test Candidate"
    assert profile["emails"] == ["test@example.com"]

    # 4. Computed normalized features
    features = result["normalized_features"]
    assert features["total_experience_months"] > 0
    assert features["latest_job_title"] == "Data Analyst"
    assert features["latest_company"] == "Analytics Corp"
    assert "bachelor" in features["highest_degree"].lower()

    # 5. Grounding evidence chunks and mapping
    assert len(result["evidence_chunks"]) > 0
    assert len(result["field_evidence_map"]) > 0


def test_extract_resume_integration_fixture_2(mock_llm_normalizer):
    """Verify end-to-end extraction on a second BusinessAnalyst PDF fixture."""
    file_path = Path("data/original/BusinessAnalyst/01946c56a6f1a9d5.pdf")
    if not file_path.exists():
        pytest.skip(f"Test fixture not found: {file_path}")

    registry = fresh_registry()
    result = extract_resume(file_path, registry=registry)

    assert result["schema_version"] == "1.0.0"
    assert result["candidate_id"] == "BusinessAnalyst_CAND_0001"
    assert result["document"]["file_name"] == "01946c56a6f1a9d5.pdf"
    assert len(result["evidence_chunks"]) > 0


def test_extract_resume_integration_fixture_3(mock_llm_normalizer):
    """Verify end-to-end extraction on a third BusinessAnalyst PDF fixture."""
    file_path = Path("data/original/BusinessAnalyst/02a87605b8841c0f.pdf")
    if not file_path.exists():
        pytest.skip(f"Test fixture not found: {file_path}")

    registry = fresh_registry()
    result = extract_resume(file_path, registry=registry)

    assert result["schema_version"] == "1.0.0"
    assert result["candidate_id"] == "BusinessAnalyst_CAND_0001"
    assert result["document"]["file_name"] == "02a87605b8841c0f.pdf"
    assert len(result["evidence_chunks"]) > 0
