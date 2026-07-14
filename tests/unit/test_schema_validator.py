"""Unit tests for the schema validator (DEC-035)."""

import pytest

from src.resume_parsing.extraction.schema_validator import (
    validate_resume_json,
    ValidationResult,
)


def test_validate_missing_candidate_profile():
    """Verify failure when candidate_profile is missing entirely."""
    res = validate_resume_json({})
    assert not res.is_valid
    assert "candidate_profile" in res.missing_fields
    assert res.confidence_score == 0.0


def test_validate_missing_required_full_name():
    """Verify failure when full_name is missing."""
    data = {
        "candidate_profile": {
            "emails": ["test@example.com"],
        }
    }
    res = validate_resume_json(data)
    assert not res.is_valid
    assert "candidate_profile.full_name" in res.missing_fields


def test_validate_missing_required_emails():
    """Verify failure when emails list is missing or empty."""
    data = {
        "candidate_profile": {
            "full_name": "John Doe",
        }
    }
    res = validate_resume_json(data)
    assert not res.is_valid
    assert "candidate_profile.emails" in res.missing_fields


def test_validate_warnings_triggered():
    """Verify warnings for missing recommended fields."""
    data = {
        "candidate_profile": {
            "full_name": "John Doe",
            "emails": ["test@example.com"],
        }
    }
    res = validate_resume_json(data)
    assert res.is_valid  # still valid as phone/skills are only warnings
    assert len(res.warnings) == 4
    assert any("phone" in w for w in res.warnings)
    assert any("skills" in w for w in res.warnings)
    assert any("education" in w for w in res.warnings)
    assert any("experience" in w for w in res.warnings)


def test_validate_confidence_score_calculation():
    """Verify confidence score is correctly averaged."""
    data = {
        "candidate_profile": {
            "full_name": "John Doe",
            "emails": ["test@example.com"],
            "skills": [
                {"name_raw": "Python", "confidence": 0.8},
                {"name_raw": "SQL", "confidence": 0.6},
            ],
            "education": [
                {"degree": "BS", "confidence": 0.9},
            ],
            "experience": [
                {"role": "Developer", "confidence": 0.7},
            ],
            "certifications": [
                {"name": "AWS", "confidence": 1.0},
            ]
        }
    }
    res = validate_resume_json(data)
    assert res.is_valid
    # Average of [0.8, 0.6, 0.9, 0.7, 1.0] = 4.0 / 5 = 0.80
    assert pytest.approx(res.confidence_score) == 0.80


def test_validate_confidence_score_default_high():
    """Verify high default confidence score when details are present without scores."""
    data = {
        "candidate_profile": {
            "full_name": "John Doe",
            "emails": ["test@example.com"],
            "skills": [{"name_raw": "Python"}],
        }
    }
    res = validate_resume_json(data)
    assert res.is_valid
    assert res.confidence_score == 0.90


def test_validate_confidence_score_default_low():
    """Verify low default confidence score when profile is blank/anonymous."""
    data = {
        "candidate_profile": {
            "emails": ["test@example.com"],
        }
    }
    res = validate_resume_json(data)
    assert not res.is_valid
    assert res.confidence_score == 0.50
