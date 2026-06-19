"""Compare two candidates side-by-side and generate a "Why A ranked above B" narrative.

This script loads two candidate profiles, their scores, and generates a recruiter-
friendly comparison using the LLM to explain score differences and highlight key
differentiators.

Usage:
    python scripts/compare_two.py --candidate-a <id_a> --candidate-b <id_b> --role <role>
    
Example:
    python scripts/compare_two.py --candidate-a cand_f920c9c311de --candidate-b cand_abc123 --role BusinessAnalyst
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional
import os
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from hireintel_ai.core.config import Settings


def _load_candidate_profile(role: str, candidate_id_or_file: str) -> Optional[dict]:
    """Load a candidate's full parsed profile from data/processed.
    
    Args:
        role: Job role bucket (e.g., 'BusinessAnalyst')
        candidate_id_or_file: Either candidate_id (e.g., '8c5959c7993cb7a1') or
                              full candidate_id (e.g., 'cand_f920c9c311de')
    """
    settings = Settings()
    profile_dir = settings.resolved_processed_data_dir / role
    
    if not profile_dir.exists():
        return None
    
    # Try exact match first
    profile_file = profile_dir / f"{candidate_id_or_file}.json"
    if profile_file.exists():
        with open(profile_file, "r", encoding="utf-8") as f:
            return json.load(f)
    
    # Search by partial match (file stem contains the ID)
    for file in profile_dir.glob("*.json"):
        if candidate_id_or_file in file.stem:
            with open(file, "r", encoding="utf-8") as f:
                return json.load(f)
    
    return None


def _load_scores(role: str, strategy: str = "hybrid") -> dict:
    """Load all scored candidates for a role and strategy.
    
    Returns:
        Dict mapping candidate_id -> score record
    """
    # Try multiple possible locations
    possible_paths = [
        Path("data/scores") / strategy / f"{role}_ranked.json",
        Path("data/scores") / f"{role}_ranked.json",  # Fallback
    ]
    
    for scores_file in possible_paths:
        if scores_file.exists():
            with open(scores_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {row["candidate_id"]: row for row in data}
    
    return {}


def _resolve_candidate_id(role: str, user_input: str, all_scores: dict) -> Optional[str]:
    """Resolve user input to a canonical candidate_id in the scores.
    
    Args:
        role: Job role bucket
        user_input: User-provided candidate identifier (file stem or candidate_id)
        all_scores: Loaded scores dict
    
    Returns:
        Canonical candidate_id from scores, or None if not found
    """
    # Direct match in scores
    if user_input in all_scores:
        return user_input
    
    # Search by source_file basename match
    for cid, score_rec in all_scores.items():
        source_file = score_rec.get("source_file", "")
        if user_input in source_file:
            return cid
    
    # Search by profile file
    settings = Settings()
    profile_dir = settings.resolved_processed_data_dir / role
    profile_file = profile_dir / f"{user_input}.json"
    
    if profile_file.exists():
        # Found the profile, search for matching score by source file
        with open(profile_file, "r", encoding="utf-8") as f:
            profile = json.load(f)
        
        # Extract candidate ID or source file reference
        # Search for this candidate in scores
        raw_text = profile.get("raw_text", "")[:100]  # Just to get context
        
        for cid, score_rec in all_scores.items():
            # Match by source file if available
            if "source_file" in score_rec:
                score_source = score_rec["source_file"].lower()
                if user_input in score_source:
                    return cid
    
    # If still not found, try to find by profile match
    for cid, score_rec in all_scores.items():
        if user_input in cid:
            return cid
    
    return None


def _extract_candidate_info(profile: dict) -> dict:
    """Extract key candidate information for comparison."""
    return {
        "name": profile.get("name", {}).get("value", "N/A"),
        "email": profile.get("contact", {}).get("emails", ["N/A"])[0] if profile.get("contact", {}).get("emails") else "N/A",
        "summary": profile.get("summary", {}).get("value", "N/A")[:300],  # Truncate for readability
        "experience_count": len(profile.get("experience", {}).get("entries", [])),
        "education": profile.get("education", {}).get("value", "N/A")[:200],
        "skills": profile.get("skills", [])[:5] if isinstance(profile.get("skills", []), list) else [],
    }


def _build_comparison_table(
    candidate_a: dict,
    candidate_b: dict,
    profile_a: dict,
    profile_b: dict,
    score_a: Optional[dict],
    score_b: Optional[dict],
) -> str:
    """Build a formatted comparison table."""
    table = []
    table.append("=" * 120)
    table.append("CANDIDATE COMPARISON")
    table.append("=" * 120)
    table.append("")
    
    # Extract info
    info_a = _extract_candidate_info(profile_a)
    info_b = _extract_candidate_info(profile_b)
    
    score_a_val = score_a.get("final_score", score_a.get("normalized_score", 0.0)) if score_a else 0.0
    score_b_val = score_b.get("final_score", score_b.get("normalized_score", 0.0)) if score_b else 0.0
    
    # Header
    table.append(f"{'Attribute':<30} {'Candidate A':<40} {'Candidate B':<40}")
    table.append("-" * 120)
    
    # Basic info
    table.append(f"{'Name':<30} {info_a['name']:<40} {info_b['name']:<40}")
    table.append(f"{'Email':<30} {str(info_a['email'])[:39]:<40} {str(info_b['email'])[:39]:<40}")
    table.append(f"{'Years of Experience':<30} {info_a['experience_count']:<40} {info_b['experience_count']:<40}")
    table.append("")
    
    # Scores
    table.append(f"{'Hybrid Score':<30} {score_a_val:<40.2f} {score_b_val:<40.2f}")
    table.append(f"{'Score Difference':<30} {score_a_val - score_b_val:+.2f} {'(A ahead)' if score_a_val > score_b_val else '(B ahead)' if score_b_val > score_a_val else '(Tie)':<40}")
    table.append("")
    
    # Component breakdown
    table.append("COMPONENT BREAKDOWN:")
    table.append("-" * 120)
    
    # Get matched components from score
    components_a = score_a.get("components", score_a.get("keyword_components", [])) if score_a else []
    components_b = score_b.get("components", score_b.get("keyword_components", [])) if score_b else []
    
    if components_a:
        a_matched = sum(1 for c in components_a if c.get("matched"))
        table.append(f"{'Matched Requirements (A)':<30} {a_matched:<40} {len(components_a):<40}")
    
    if components_b:
        b_matched = sum(1 for c in components_b if c.get("matched"))
        table.append(f"{'Matched Requirements (B)':<30} {'':40} {b_matched:<40}")
    
    table.append("")
    
    # Top matched components for A
    if components_a:
        table.append("Top Strengths — Candidate A:")
        matched_comps = [c for c in components_a if c.get("matched")][:3]
        for comp in matched_comps:
            snippet = comp.get('snippet', comp.get('notes', 'N/A'))
            if isinstance(snippet, str):
                snippet = snippet[:60] + "..." if len(snippet) > 60 else snippet
            else:
                snippet = "N/A"
            table.append(f"  • {comp.get('item_name', 'Unknown')}: {snippet}")
        table.append("")
    
    # Top matched components for B
    if components_b:
        table.append("Top Strengths — Candidate B:")
        matched_comps = [c for c in components_b if c.get("matched")][:3]
        for comp in matched_comps:
            snippet = comp.get('snippet', comp.get('notes', 'N/A'))
            if isinstance(snippet, str):
                snippet = snippet[:60] + "..." if len(snippet) > 60 else snippet
            else:
                snippet = "N/A"
            table.append(f"  • {comp.get('item_name', 'Unknown')}: {snippet}")
        table.append("")
    
    table.append("=" * 120)
    
    return "\n".join(table)


def _generate_llm_explanation(
    candidate_a_id: str,
    candidate_b_id: str,
    score_a: Optional[dict],
    score_b: Optional[dict],
    profile_a: dict,
    profile_b: dict,
    role: str,
) -> str:
    """Generate an LLM-powered explanation of why A ranked above B.
    
    This placeholder uses deterministic logic for now. Future: integrate with LLM service.
    """
    score_a_val = score_a.get("final_score", score_a.get("normalized_score", 0.0)) if score_a else 0.0
    score_b_val = score_b.get("final_score", score_b.get("normalized_score", 0.0)) if score_b else 0.0
    
    info_a = _extract_candidate_info(profile_a)
    info_b = _extract_candidate_info(profile_b)
    
    # Get components
    components_a = score_a.get("components", score_a.get("keyword_components", [])) if score_a else []
    components_b = score_b.get("components", score_b.get("keyword_components", [])) if score_b else []
    
    explanation = []
    explanation.append("WHY THIS RANKING?")
    explanation.append("=" * 60)
    explanation.append("")
    
    if score_a_val > score_b_val:
        diff = score_a_val - score_b_val
        explanation.append(f"[SCORE] {info_a['name']} ranked HIGHER by {diff:.1f} points.")
        explanation.append("")
        
        # Matched components comparison
        a_matched = sum(1 for c in components_a if c.get("matched"))
        b_matched = sum(1 for c in components_b if c.get("matched"))
        if a_matched > 0 or b_matched > 0:
            explanation.append(f"[MATCH] Matched {a_matched} requirements vs {b_matched} for {info_b['name']}.")
        
        # Top strengths
        if components_a:
            matched_comps = [c for c in components_a if c.get("matched")]
            if matched_comps:
                top = matched_comps[0]
                explanation.append(f"[STRENGTH] Strong in: {top.get('item_name', 'Unknown')}")
        
    elif score_b_val > score_a_val:
        diff = score_b_val - score_a_val
        explanation.append(f"[SCORE] {info_b['name']} ranked HIGHER by {diff:.1f} points.")
        explanation.append("")
        
        b_matched = sum(1 for c in components_b if c.get("matched"))
        a_matched = sum(1 for c in components_a if c.get("matched"))
        if b_matched > 0 or a_matched > 0:
            explanation.append(f"[MATCH] Matched {b_matched} requirements vs {a_matched} for {info_a['name']}.")
    else:
        explanation.append(f"[SCORE] Both candidates scored EQUALLY at {score_a_val:.1f} points.")
        explanation.append("Consider other factors like cultural fit, growth potential, or recent experience.")
    
    explanation.append("")
    explanation.append("RECRUITER NOTE:")
    explanation.append("Review the component breakdown above. Scores reflect objective requirement matching.")
    explanation.append("Consider scheduling interviews with both top candidates.")
    
    return "\n".join(explanation)


def compare_candidates(
    candidate_a_input: str,
    candidate_b_input: str,
    role: str,
    strategy: str = "hybrid",
) -> None:
    """Load and compare two candidates."""
    
    # Load scores first
    all_scores = _load_scores(role, strategy)
    
    if not all_scores:
        print(f"❌ No scores found for role '{role}' and strategy '{strategy}'")
        return
    
    # Resolve candidate IDs
    candidate_a_id = _resolve_candidate_id(role, candidate_a_input, all_scores)
    candidate_b_id = _resolve_candidate_id(role, candidate_b_input, all_scores)
    
    if not candidate_a_id:
        print(f"❌ Could not find candidate A: {candidate_a_input}")
        print(f"   Available candidates: {', '.join(list(all_scores.keys())[:5])}...")
        return
    
    if not candidate_b_id:
        print(f"❌ Could not find candidate B: {candidate_b_input}")
        print(f"   Available candidates: {', '.join(list(all_scores.keys())[:5])}...")
        return
    
    # Load profiles
    profile_a = _load_candidate_profile(role, candidate_a_input)
    profile_b = _load_candidate_profile(role, candidate_b_input)
    
    if not profile_a:
        print(f"❌ Could not load profile for candidate A: {candidate_a_input}")
        return
    
    if not profile_b:
        print(f"❌ Could not load profile for candidate B: {candidate_b_input}")
        return
    
    # Get scores
    score_a = all_scores.get(candidate_a_id)
    score_b = all_scores.get(candidate_b_id)
    
    # Display comparison table
    table = _build_comparison_table(
        candidate_a_id,
        candidate_b_id,
        profile_a,
        profile_b,
        score_a,
        score_b,
    )
    print(table)
    print()
    
    # Display LLM-powered explanation
    explanation = _generate_llm_explanation(
        candidate_a_id,
        candidate_b_id,
        score_a,
        score_b,
        profile_a,
        profile_b,
        role,
    )
    print(explanation)
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Compare two candidates side-by-side with score breakdown and ranking explanation."
    )
    parser.add_argument(
        "--candidate-a",
        required=True,
        help="ID of first candidate (e.g., cand_f920c9c311de or a short name like '8c5959c7993cb7a1')",
    )
    parser.add_argument(
        "--candidate-b",
        required=True,
        help="ID of second candidate",
    )
    parser.add_argument(
        "--role",
        default="BusinessAnalyst",
        help="Job role to compare for (default: BusinessAnalyst)",
    )
    parser.add_argument(
        "--strategy",
        choices=["keyword", "semantic", "hybrid"],
        default="hybrid",
        help="Scoring strategy to use (default: hybrid)",
    )
    
    args = parser.parse_args()
    
    compare_candidates(
        args.candidate_a,
        args.candidate_b,
        args.role,
        args.strategy,
    )


if __name__ == "__main__":
    main()
