"""Tests for Structured Candidate Profile extraction."""

from src.resume_parsing.structured_profile import (
    DegreeEntry,
    CertificationEntry,
    EmploymentEntry,
    StructuredCandidateProfile,
    extract_structured_profile,
)


class TestExtractDegrees:
    """Degree extraction should parse degree name, field, institution, year."""

    def test_btech_extraction(self):
        profile = {
            "candidate_id": "cand_test",
            "education": {
                "entries": [
                    {"description": "BTech in Computer Science, IIT Bombay, 2016-2020"}
                ]
            },
        }
        result = extract_structured_profile(profile)
        assert len(result.degrees) == 1
        assert "BTech" in result.degrees[0].degree or "B" in result.degrees[0].degree
        assert result.degrees[0].year == "2016-2020"

    def test_mba_extraction(self):
        profile = {
            "candidate_id": "cand_test",
            "education": {
                "entries": [
                    {"description": "MBA, Harvard University, 2020-2022"}
                ]
            },
        }
        result = extract_structured_profile(profile)
        assert len(result.degrees) == 1
        assert "MBA" in result.degrees[0].degree

    def test_multiple_degrees(self):
        profile = {
            "candidate_id": "cand_test",
            "education": {
                "entries": [
                    {"description": "BTech in Computer Science, IIT Delhi, 2014-2018"},
                    {"description": "MS in Data Science, Stanford University, 2019-2021"},
                ]
            },
        }
        result = extract_structured_profile(profile)
        assert len(result.degrees) == 2

    def test_no_education_entries(self):
        profile = {"candidate_id": "cand_test", "education": {"entries": []}}
        result = extract_structured_profile(profile)
        assert result.degrees == []


class TestExtractCertifications:
    """Certification extraction should parse name and provider."""

    def test_aws_cert(self):
        profile = {
            "candidate_id": "cand_test",
            "certifications": ["AWS Solutions Architect Associate"],
        }
        result = extract_structured_profile(profile)
        assert len(result.certifications) == 1
        assert result.certifications[0].name == "AWS Solutions Architect Associate"
        assert result.certifications[0].provider == "Amazon Web Services"

    def test_multiple_certs(self):
        profile = {
            "candidate_id": "cand_test",
            "certifications": ["AWS Certified", "PMP Certification", "Azure Fundamentals"],
        }
        result = extract_structured_profile(profile)
        assert len(result.certifications) == 3
        assert result.certifications[0].provider == "Amazon Web Services"
        assert result.certifications[1].provider == "Project Management Institute"
        assert result.certifications[2].provider == "Microsoft"

    def test_unknown_cert_no_provider(self):
        profile = {
            "candidate_id": "cand_test",
            "certifications": ["Some Random Certificate"],
        }
        result = extract_structured_profile(profile)
        assert len(result.certifications) == 1
        assert result.certifications[0].provider == ""


class TestEmploymentHistory:
    """Employment history should extract company, role, dates, and compute duration."""

    def test_single_employment(self):
        profile = {
            "candidate_id": "cand_test",
            "experience": {
                "entries": [
                    {
                        "title": "Data Scientist",
                        "company": "Netflix",
                        "dates": "2020 - 2023",
                        "location": "California",
                        "details": [],
                    }
                ]
            },
        }
        result = extract_structured_profile(profile)
        assert len(result.employment_history) == 1
        assert result.employment_history[0].company == "Netflix"
        assert result.employment_history[0].role == "Data Scientist"
        # 2020-2023 inclusive = 48 months = 4 years.
        assert result.employment_history[0].calculated_duration_months == 48

    def test_companies_and_roles_lists(self):
        profile = {
            "candidate_id": "cand_test",
            "experience": {
                "entries": [
                    {"title": "Engineer", "company": "Google", "dates": "2018-2020", "details": []},
                    {"title": "Senior Engineer", "company": "Meta", "dates": "2020-Present", "details": []},
                ]
            },
        }
        result = extract_structured_profile(profile)
        assert result.companies == ["Google", "Meta"]
        assert result.roles == ["Engineer", "Senior Engineer"]


class TestTotalExperienceYears:
    """Total experience should be computed deterministically without double-counting."""

    def test_non_overlapping_roles(self):
        profile = {
            "candidate_id": "cand_test",
            "experience": {
                "entries": [
                    {"title": "Engineer", "company": "A", "dates": "2018-2020", "details": []},
                    {"title": "Senior Engineer", "company": "B", "dates": "2020-2023", "details": []},
                ]
            },
        }
        result = extract_structured_profile(profile)
        # 2018-2020 = 36 months, 2020-2023 = 48 months.
        # They overlap in 2020 (12 months). Merged: 2018-2023 = 72 months = 6 years.
        assert result.total_experience_years == 6.0

    def test_overlapping_roles_no_double_count(self):
        profile = {
            "candidate_id": "cand_test",
            "experience": {
                "entries": [
                    {"title": "Engineer", "company": "A", "dates": "2018-2022", "details": []},
                    {"title": "Consultant", "company": "B", "dates": "2020-2023", "details": []},
                ]
            },
        }
        result = extract_structured_profile(profile)
        # 2018-2022 = 60 months, 2020-2023 = 48 months, overlap 2020-2022 = 36 months.
        # Merged: 2018-2023 = 72 months = 6 years.
        assert result.total_experience_years == 6.0

    def test_no_experience(self):
        profile = {"candidate_id": "cand_test", "experience": {"entries": []}}
        result = extract_structured_profile(profile)
        assert result.total_experience_years == 0.0

    def test_present_role(self):
        profile = {
            "candidate_id": "cand_test",
            "experience": {
                "entries": [
                    {"title": "Engineer", "company": "A", "dates": "2020 - Present", "details": []},
                ]
            },
        }
        result = extract_structured_profile(profile)
        assert result.total_experience_years > 0
        assert result.employment_history[0].is_current is True


class TestToDict:
    """The to_dict method should produce a serializable record."""

    def test_full_profile_to_dict(self):
        profile = {
            "candidate_id": "cand_test",
            "education": {"entries": [{"description": "BTech, IIT, 2016-2020"}]},
            "certifications": ["AWS Certified"],
            "experience": {
                "entries": [
                    {"title": "Engineer", "company": "Google", "dates": "2020-2023", "details": []}
                ]
            },
        }
        result = extract_structured_profile(profile)
        d = result.to_dict()
        assert d["candidate_id"] == "cand_test"
        assert len(d["degrees"]) == 1
        assert len(d["certifications"]) == 1
        assert len(d["employment_history"]) == 1
        # 2020-2023 inclusive = 48 months = 4 years.
        assert d["total_experience_years"] == 4.0
        assert d["companies"] == ["Google"]
        assert d["roles"] == ["Engineer"]
