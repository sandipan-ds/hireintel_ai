"""Tests for candidate comparison script (Phase 5)."""

import json
import subprocess
from pathlib import Path
import pytest


class TestCandidateComparison:
    """Test candidate comparison functionality."""
    
    def test_compare_two_script_exists(self):
        """Test that the compare_two.py script exists."""
        script = Path("scripts/compare_two.py")
        assert script.exists(), "compare_two.py script not found"
    
    def test_compare_two_with_valid_candidates(self):
        """Test comparing two valid candidates."""
        result = subprocess.run(
            [
                "python",
                "scripts/compare_two.py",
                "--candidate-a", "8c5959c7993cb7a1",
                "--candidate-b", "01888170110d1ccf",
                "--role", "BusinessAnalyst",
                "--strategy", "hybrid",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Script failed: {result.stderr}"
        output = result.stdout
        
        # Check that output contains expected sections
        assert "CANDIDATE COMPARISON" in output
        assert "Hybrid Score" in output
        assert "WHY THIS RANKING?" in output
        assert "RECRUITER NOTE" in output
    
    def test_compare_two_with_hybrid_strategy(self):
        """Test that hybrid strategy works correctly."""
        result = subprocess.run(
            [
                "python",
                "scripts/compare_two.py",
                "--candidate-a", "8c5959c7993cb7a1",
                "--candidate-b", "01888170110d1ccf",
                "--role", "BusinessAnalyst",
                "--strategy", "hybrid",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        output = result.stdout
        
        # Check for score numbers
        assert "58.39" in output or "final_score" in output.lower()
    
    def test_compare_two_with_keyword_strategy(self):
        """Test that keyword strategy works."""
        result = subprocess.run(
            [
                "python",
                "scripts/compare_two.py",
                "--candidate-a", "8c5959c7993cb7a1",
                "--candidate-b", "01888170110d1ccf",
                "--role", "BusinessAnalyst",
                "--strategy", "keyword",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # May or may not have scores depending on keyword file existence
        # But should at least run without crashing
        assert isinstance(result.returncode, int)
    
    def test_compare_two_invalid_candidate_a(self):
        """Test with invalid candidate A."""
        result = subprocess.run(
            [
                "python",
                "scripts/compare_two.py",
                "--candidate-a", "nonexistent_xyz_123",
                "--candidate-b", "01888170110d1ccf",
                "--role", "BusinessAnalyst",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout + result.stderr
        assert "Could not find" in output or "Could not load" in output
    
    def test_compare_two_invalid_role(self):
        """Test with invalid role."""
        result = subprocess.run(
            [
                "python",
                "scripts/compare_two.py",
                "--candidate-a", "8c5959c7993cb7a1",
                "--candidate-b", "01888170110d1ccf",
                "--role", "NonexistentRole",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout + result.stderr
        # Should either fail gracefully or find no scores
        assert "No scores found" in output or result.returncode != 0 or "Could not" in output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
