"""Wire the new sub-query similarity scoring into the pipeline.

This module replaces the Section-Routed Evidence Retrieval in
``scoring_pipeline.py`` with the sub-query similarity + cache flow.

It is the production code path. Section-Routed is kept for backward
compatibility and as the metadata pre-filter.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.scoring.rubrics import get_rubric, RubricTemplate, SubQuestion
from src.rag.section_routed import classify_requirement_type
from src.services.subquery_retrieval import (
    LLMScoreCache,
    SubQueryHit,
    build_index_from_chunks_dir,
    score_requirement_with_similarity,
    score_candidate_batched,
)

logger = logging.getLogger(__name__)

# Module-level index cache (built once on first call)
_INDEX = None
_CACHE: Optional[LLMScoreCache] = None


def get_index():
    """Get or build the global chunk index."""
    global _INDEX
    if _INDEX is None:
        logger.info("Building chunk embedding index...")
        _INDEX = build_index_from_chunks_dir(Path("data/chunks"))
    return _INDEX


def get_cache() -> LLMScoreCache:
    """Get the global LLM score cache."""
    global _CACHE
    if _CACHE is None:
        _CACHE = LLMScoreCache()
    return _CACHE


def sub_queries_for_rubric(
    rubric: RubricTemplate,
    requirement_name: str,
) -> List[Tuple[str, str]]:
    """Build the (key, text) sub-queries for a requirement.

    The rubric's sub-questions are templated with the requirement name.
    """
    return [
        (sq.key, sq.question.format(**{_template_var(sq, requirement_name): requirement_name}))
        for sq in rubric.sub_questions
    ]


def _template_var(sq: SubQuestion, requirement_name: str) -> str:
    """Find the template variable name in the sub-question text."""
    import re
    matches = re.findall(r"\{(\w+)\}", sq.question)
    return matches[0] if matches else "skill"


def score_requirement(
    candidate_id: str,
    req_id: str,
    req_name: str,
    dimension_type: str,
    llm_caller: Callable[[str], str],
    cache: Optional[LLMScoreCache] = None,
    threshold: float = 0.0,
) -> Dict[str, Any]:
    """Score one REQ for one candidate using sub-query similarity.

    Returns:
        Dict with:
            - hits: List of SubQueryHit
            - sub_scores: Dict[str, float]
            - normalized_score: float
            - from_cache: bool
            - dimension_type: str
    """
    rubric = get_rubric(dimension_type)
    if rubric is None:
        logger.warning("No rubric for dimension type %s, returning zeros", dimension_type)
        return {
            "hits": [],
            "sub_scores": {},
            "normalized_score": 0.0,
            "from_cache": False,
            "dimension_type": dimension_type,
        }

    sub_queries = sub_queries_for_rubric(rubric, req_name)

    index = get_index()
    cache = cache or get_cache()

    return score_requirement_with_similarity(
        index=index,
        candidate_id=candidate_id,
        req_id=req_id,
        req_name=req_name,
        sub_queries=sub_queries,
        llm_caller=llm_caller,
        cache=cache,
        threshold=threshold,
    )


# Mapping of UI category names → rubric type (mirrors CATEGORY_TO_TYPE in section_routed)
CATEGORY_TO_RUBRIC_TYPE = {
    "core skills": "skill",
    "core skills & technologies": "skill",
    "technology & tools": "skill",
    "technology and tools": "skill",
    "technical skills": "skill",
    "skills": "skill",
    "tools": "skill",
    "programming": "skill",
    "programming languages": "skill",
    "experience": "experience",
    "relevant experience": "experience",
    "overall relevant experience": "experience",
    "same role experience": "same_role",
    "same-role experience": "same_role",
    "leadership experience": "leadership",
    "leadership": "leadership",
    "industry experience": "domain",
    "management experience": "leadership",
    "product company experience": "domain",
    "technology stack experience": "skill",
    "education": "education",
    "education fit": "education",
    "academic": "education",
    "certifications": "certification",
    "certification": "certification",
    "certification alignment": "certification",
    "projects": "project",
    "project relevance": "project",
    "project experience": "project",
    "languages": "language",
    "language": "language",
    "language capabilities": "language",
    "location": "location",
    "communication quality": "communication",
    "communication": "communication",
    "resume organization": "resume_organization",
    "responsibilities": "responsibilities",
}


def _resolve_rubric_type(category: str, req_name: str) -> str:
    """Resolve a category name + REQ name to a rubric type.

    Falls back to "skill" if no match, or for categories that don't have
    a dedicated rubric (e.g. "responsibilities" maps to "skill" since
    demonstrating responsibility is a kind of skill evidence).
    """
    cat_lower = (category or "").lower().strip()
    if cat_lower in CATEGORY_TO_RUBRIC_TYPE:
        rubric_type = CATEGORY_TO_RUBRIC_TYPE[cat_lower]
    else:
        try:
            rubric_type = classify_requirement_type(cat_lower, req_name)
        except Exception:
            rubric_type = "skill"

    # Validate against the actual rubric registry — fall back to "skill"
    # for categories that don't have a rubric (e.g. "responsibilities",
    # which uses skill rubric as a proxy).
    from src.scoring.rubrics import RUBRIC_REGISTRY
    if rubric_type not in RUBRIC_REGISTRY:
        rubric_type = "skill"

    return rubric_type


def score_candidate_all_reqs(
    candidate_id: str,
    requirements: List[Dict[str, Any]],
    llm_caller: Callable[[str], str],
    cache: Optional[LLMScoreCache] = None,
    threshold: float = 0.0,
) -> Dict[str, Dict[str, Any]]:
    """Score ALL REQs for one candidate in a single LLM call.

    15x speedup over per-REQ scoring (one LLM round-trip instead of N).

    Args:
        candidate_id: Candidate.
        requirements: List of dicts from the recruiter's weight config:
            {
                "req_id": "REQ-002",
                "req_name": "SQL for Data Validation & Analysis",
                "category": "Technology Skill",
                "weight_percentage": 8.0,
            }
        llm_caller: Callable(prompt: str) -> str.
        cache: Optional cache.
        threshold: Cosine threshold.

    Returns:
        Dict mapping req_id -> per-REQ result dict (same shape as
        ``score_requirement_with_similarity``).
    """
    # Build the requirements list with sub-queries and rubric_type
    enriched_requirements = []
    for req in requirements:
        req_id = req["req_id"]
        req_name = req["req_name"]
        category = req.get("category", "")
        rubric_type = _resolve_rubric_type(category, req_name)
        rubric = get_rubric(rubric_type)
        if rubric is None:
            continue
        sub_queries = sub_queries_for_rubric(rubric, req_name)
        enriched_requirements.append({
            "req_id": req_id,
            "req_name": req_name,
            "sub_queries": sub_queries,
            "rubric_type": rubric_type,
        })

    if not enriched_requirements:
        return {}

    index = get_index()
    cache = cache or get_cache()

    return score_candidate_batched(
        index=index,
        candidate_id=candidate_id,
        requirements=enriched_requirements,
        llm_caller=llm_caller,
        cache=cache,
        threshold=threshold,
    )
