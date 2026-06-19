"""Tests for the graded per-item scorer (Phase 4 per-candidate evaluation)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from scoring.graded_scorer import (
    _grade_score,
    _skill_keywords,
    _detect_years_experience,
    _count_keyword_mentions,
    evaluate_candidate,
    render_evaluation_report,
)


class TestGradedScorer:
    """Test the per-item graded scoring engine."""

    def test_skill_keywords_basic(self):
        """Test that skill keywords are extracted and normalized."""
        keywords = _skill_keywords("HTML", "Build web pages")
        assert "html" in keywords

    def test_skill_keywords_with_synonyms(self):
        """Test that skill synonyms are expanded (e.g., React -> reactjs)."""
        keywords = _skill_keywords("React", "Build user interfaces")
        assert "react" in keywords
        # Synonyms include reactjs
        assert any("react" in kw for kw in keywords)

    def test_skill_keywords_with_powerbi(self):
        """Test Power BI normalization."""
        keywords = _skill_keywords("Power BI", "Build dashboards")
        assert "power bi" in keywords
        # Synonyms should be present
        assert any("pbi" in kw or "power" in kw for kw in keywords)

    def test_count_keyword_mentions(self):
        """Test keyword mention counting."""
        text = "I have HTML, CSS, and more HTML experience. HTML is great."
        keywords = ["html"]
        mentions, snippets = _count_keyword_mentions(text.lower(), keywords)
        assert mentions >= 2  # At least 2 mentions

    def test_detect_years_experience(self):
        """Test years-of-experience detection near keywords."""
        text = "I have 7+ years of HTML experience and 3 years of CSS."
        years_html = _detect_years_experience(text.lower(), ["html"])
        assert years_html >= 7
        years_css = _detect_years_experience(text.lower(), ["css"])
        assert years_css >= 3

    def test_grade_score_no_match(self):
        """Test grading when no match found."""
        score = _grade_score(matched=False, mentions=0, years=0, importance=10)
        assert score == 0.0

    def test_grade_score_with_match(self):
        """Test grading with matches."""
        score = _grade_score(matched=True, mentions=2, years=3, importance=10)
        # Should be >= 6 (2 mentions + 3 years boost)
        assert score >= 6.0
        assert score <= 10.0

    def test_grade_score_with_strong_evidence(self):
        """Test grading with strong evidence (many mentions + years)."""
        score = _grade_score(matched=True, mentions=5, years=7, importance=10)
        assert score == 10.0

    def test_grade_score_capped_by_importance(self):
        """Test that score is capped by item importance."""
        # Importance is 5, but score would normally be higher
        score = _grade_score(matched=True, mentions=10, years=10, importance=5)
        assert score <= 5.0

    def test_evaluate_candidate_structure(self):
        """Test that evaluate_candidate returns proper structure."""
        profile = {
            "raw_text": "I have 5 years of HTML experience and worked with React.",
            "candidate_id": "test_123",
        }
        weights = {
            "role": "Test Role",
            "categories": [
                {
                    "name": "Core Skills",
                    "items": [
                        {"name": "HTML", "description": "Web markup", "importance": 8},
                        {"name": "React", "description": "UI library", "importance": 9},
                    ],
                }
            ],
        }

        result = evaluate_candidate(profile, weights)

        # Check structure
        assert "total_score" in result
        assert "max_score" in result
        assert "normalized_total" in result
        assert "categories" in result
        assert "candidate_id" in result

        # Check values
        assert result["candidate_id"] == "test_123"
        assert len(result["categories"]) == 1
        assert len(result["categories"][0]["items"]) == 2

        # Check that HTML and React scored > 0 (matched)
        html_item = result["categories"][0]["items"][0]
        react_item = result["categories"][0]["items"][1]
        assert html_item["matched"] is True
        assert react_item["matched"] is True

    def test_render_evaluation_report_format(self):
        """Test that the rendered report matches PROJECT_OVERVIEW.md format."""
        profile = {
            "raw_text": "I have 6 years of HTML experience.",
            "candidate_id": "cand_test",
        }
        weights = {
            "role": "Test Role",
            "categories": [
                {
                    "name": "Skills",
                    "items": [
                        {"name": "HTML", "description": "Markup", "importance": 10},
                    ],
                }
            ],
        }

        result = evaluate_candidate(profile, weights)
        report = render_evaluation_report(result)

        # Check that report contains expected sections
        assert "CANDIDATE EVALUATION REPORT" in report
        assert "Total Score:" in report
        assert "HTML" in report
        assert "Score:" in report
        assert "Reason:" in report


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
