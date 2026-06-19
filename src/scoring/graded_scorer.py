"""Graded per-item scorer: produces per-component scores (0-10) with evidence.

Unlike the binary keyword scorer, this produces graduated scores per requirement
based on the strength of evidence. For example:
  - HTML: 10/10 (Reason: 6 years of HTML experience identified)
  - CSS: 5/10 (Reason: 3 years of CSS experience identified)
  - React: 9/10 (Reason: 5 years of React experience identified)

This is the format specified in docs/PROJECT_OVERVIEW.md Phase 4.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


# Common English stopwords used in skill/technology detection.
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have",
    "in", "is", "it", "its", "of", "on", "or", "that", "the", "to", "was", "were",
    "will", "with", "this", "these", "those", "we", "you", "your", "i",
}

# Keywords that suggest a numeric duration ("6 years", "5+ years").
_YEARS_PATTERN = re.compile(r"(\d+)\s*\+?\s*(?:year|yr)s?", re.IGNORECASE)

# Skill tokens that almost always appear in the same form (case-insensitive).
_SKILL_SYNONYMS = {
    "power bi": ["powerbi", "power-bi", "pbi"],
    "react": ["reactjs", "react.js"],
    "node.js": ["nodejs", "node"],
    "javascript": ["js", "java-script"],
    "typescript": ["ts"],
    "python": [],
    "java": [],
    "c++": ["cpp"],
    "c#": ["csharp"],
    "sql": ["structured query language"],
    "machine learning": ["ml"],
    "natural language processing": ["nlp"],
}


def _normalize_skill(skill: str) -> str:
    """Lowercase and strip punctuation for matching purposes."""
    return re.sub(r"[^a-z0-9.+#\- ]+", "", skill.lower()).strip()


def _skill_keywords(item_name: str, item_description: str = "") -> list[str]:
    """Return a list of keyword tokens used to detect evidence for a scoring item.

    Args:
        item_name: The requirement name (e.g., 'HTML').
        item_description: Optional longer description.

    Returns:
        List of normalized keyword tokens (deduped).
    """
    tokens: list[str] = []
    base = _normalize_skill(item_name)
    if base:
        tokens.append(base)
        tokens.extend(_SKILL_SYNONYMS.get(base, []))

    if item_description:
        desc_tokens = [
            t for t in re.findall(r"[A-Za-z0-9.+#\-]+", item_description.lower())
            if t not in _STOPWORDS and len(t) >= 2
        ]
        tokens.extend(desc_tokens[:5])

    # Deduplicate preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def _count_keyword_mentions(raw_text: str, keywords: list[str]) -> tuple[int, list[str]]:
    """Count how many times each keyword appears in the resume text.

    Args:
        raw_text: Full resume text (lowercased).
        keywords: Normalized skill tokens to look for.

    Returns:
        Tuple of (total mentions, list of snippets where keywords were found).
    """
    mentions = 0
    snippets: list[str] = []
    for kw in keywords:
        if not kw:
            continue
        for m in re.finditer(re.escape(kw), raw_text, flags=re.IGNORECASE):
            mentions += 1
            start = max(0, m.start() - 40)
            end = min(len(raw_text), m.end() + 60)
            snippet = raw_text[start:end].replace("\n", " ").strip()
            if snippet and snippet not in snippets:
                snippets.append(snippet)
            if len(snippets) >= 3:
                break
        if len(snippets) >= 3:
            break
    return mentions, snippets


def _detect_years_experience(raw_text: str, keywords: list[str]) -> int:
    """Return the highest years-of-experience number found near any keyword.

    Args:
        raw_text: Full resume text.
        keywords: Keyword tokens for the requirement.

    Returns:
        Highest years value detected (0 if none found).
    """
    if not keywords:
        return 0
    text = raw_text.lower()
    best = 0
    for kw in keywords:
        for m in re.finditer(re.escape(kw), text, flags=re.IGNORECASE):
            window_start = max(0, m.start() - 60)
            window_end = min(len(text), m.end() + 60)
            window = text[window_start:window_end]
            for ym in _YEARS_PATTERN.finditer(window):
                try:
                    years = int(ym.group(1))
                    if years > best:
                        best = years
                except (ValueError, IndexError):
                    continue
    return best


def _grade_score(
    matched: bool,
    mentions: int,
    years: int,
    importance: int,
) -> float:
    """Convert raw evidence into a 0-10 graded score.

    Scoring heuristic:
        - No evidence: 0
        - Mentions but weak: 2-4
        - Multiple mentions: 5-7
        - Mentions + years evidence: 8-10
        - Years >= importance: cap at 10

    Args:
        matched: Whether keyword evidence was found.
        mentions: Total keyword mentions in resume.
        years: Highest years-of-experience value detected near keyword.
        importance: Max importance for this item (1-10).

    Returns:
        Float score between 0 and importance.
    """
    if not matched:
        return 0.0

    # Base score from mention count.
    if mentions >= 4:
        base = 8.0
    elif mentions == 3:
        base = 7.0
    elif mentions == 2:
        base = 6.0
    else:
        base = 5.0

    # Boost from years-of-experience.
    if years >= 5:
        base = min(10.0, base + 2.0)
    elif years >= 3:
        base = min(10.0, base + 1.0)
    elif years >= 1:
        base = min(10.0, base + 0.5)

    # Cap at the item's importance.
    return round(min(float(importance), base), 1)


def _evaluate_item(
    raw_text: str,
    item: dict,
) -> dict:
    """Evaluate a single requirement item against the resume text.

    Args:
        raw_text: Candidate resume text (lowercased ideally).
        item: Item dict with 'name', 'description', 'importance'.

    Returns:
        Dict with score, matched, evidence.
    """
    item_name = item.get("name", "Unknown")
    item_desc = item.get("description", "")
    importance = float(item.get("importance", 10))

    keywords = _skill_keywords(item_name, item_desc)
    text_lower = raw_text.lower()

    mentions, snippets = _count_keyword_mentions(text_lower, keywords)
    years = _detect_years_experience(text_lower, keywords)
    matched = mentions > 0
    score = _grade_score(matched, mentions, years, importance)

    if matched:
        if years > 0:
            reason = f"{years} year{'s' if years != 1 else ''} of {item_name} experience identified."
        else:
            reason = f"{mentions} mention{'s' if mentions != 1 else ''} of {item_name} found in resume."
    else:
        reason = f"No evidence of {item_name} found in resume."

    return {
        "item_name": item_name,
        "description": item_desc,
        "importance": importance,
        "score": score,
        "max_score": importance,
        "matched": matched,
        "mentions": mentions,
        "years_detected": years,
        "evidence_snippets": snippets[:3],
        "reason": reason,
    }


def evaluate_candidate(
    profile: dict,
    weights: dict,
) -> dict:
    """Produce a per-item graded evaluation for a single candidate.

    Args:
        profile: Candidate profile dict from data/processed/<role>/<id>.json.
        weights: Recruiter weights config (with 'categories' -> 'items').

    Returns:
        Evaluation dict with per-item scores, evidence, total, and normalized total.
    """
    raw_text = profile.get("raw_text", "")

    category_results = []
    total_score = 0.0
    total_max = 0.0

    for category in weights.get("categories", []):
        category_items = []
        category_score = 0.0
        category_max = 0.0

        for item in category.get("items", []):
            item_result = _evaluate_item(raw_text, item)
            category_items.append(item_result)
            category_score += item_result["score"]
            category_max += item_result["max_score"]

        category_results.append({
            "name": category.get("name", "Unknown"),
            "items": category_items,
            "category_score": round(category_score, 1),
            "category_max": round(category_max, 1),
        })

        total_score += category_score
        total_max += category_max

    normalized_total = round((total_score / total_max) * 100, 1) if total_max > 0 else 0.0

    return {
        "total_score": round(total_score, 1),
        "max_score": round(total_max, 1),
        "normalized_total": normalized_total,
        "categories": category_results,
        "candidate_id": profile.get("candidate_id"),
        "role": weights.get("role", ""),
    }


def render_evaluation_report(evaluation: dict) -> str:
    """Render an evaluation dict as the recruiter-friendly report format.

    Matches the example in docs/PROJECT_OVERVIEW.md Phase 4.

    Args:
        evaluation: Output of `evaluate_candidate`.

    Returns:
        Formatted multi-line string.
    """
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("CANDIDATE EVALUATION REPORT")
    lines.append("=" * 70)
    lines.append(f"Candidate: {evaluation.get('candidate_id', 'N/A')}")
    lines.append(f"Role: {evaluation.get('role', 'N/A')}")
    lines.append("")
    lines.append(f"### Total Score: {evaluation.get('normalized_total', 0)} / 100")
    lines.append("")

    for category in evaluation.get("categories", []):
        lines.append(f"### {category.get('name', 'Unknown')}")
        lines.append("")
        for item in category.get("items", []):
            score = item.get("score", 0)
            max_score = item.get("max_score", 10)
            lines.append(f"{item.get('item_name', 'Unknown')}")
            lines.append("")
            lines.append(f"Score: {score:.1f} / {max_score:.1f}")
            lines.append("")
            lines.append("Reason:")
            lines.append(item.get("reason", "No reason provided."))
            lines.append("")
            # Show snippets as supporting evidence
            snippets = item.get("evidence_snippets", [])
            if snippets:
                lines.append("Evidence:")
                for snip in snippets[:1]:
                    lines.append(f'  "{snip[:120]}..."')
                lines.append("")

    lines.append("=" * 70)
    return "\n".join(lines)


def load_weights(role: str) -> dict:
    """Load the filled weights config for a role.

    Args:
        role: Role bucket name (e.g., 'BusinessAnalyst').

    Returns:
        Parsed weights config dict.
    """
    weights_path = Path("data/Job descriptions") / role / f"{role}_WeightConfig_filled.json"
    if not weights_path.exists():
        raise FileNotFoundError(f"Weights config not found: {weights_path}")
    with open(weights_path, "r", encoding="utf-8") as f:
        return json.load(f)
