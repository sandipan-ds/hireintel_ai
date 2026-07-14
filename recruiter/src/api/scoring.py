"""Scoring API endpoints.

Bridges the recruiter weight-config UI to the deterministic scoring engine.
Exposes endpoints to score a single candidate and to rank all candidates
in a role against a chosen weight config.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.models.database import Role, get_db
try:
    from src.services.scoring_pipeline import (
        list_candidate_ids,
        list_configs_for_role,
        load_weight_config,
        score_candidate,
        score_candidate_batched_end_to_end,
    )
    _SCORING_AVAILABLE = True
except ImportError as _scoring_import_err:
    import logging as _li
    _li.getLogger(__name__).warning(
        "Scoring pipeline unavailable: %s — scoring API routes will return 503.", _scoring_import_err
    )
    _SCORING_AVAILABLE = False


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/score", tags=["scoring"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class ItemScoreResponse(BaseModel):
    """One scored item (one REQ)."""
    req_id: Optional[str] = None
    item_name: str
    category: str
    importance: float
    raw_score: float
    matched: bool
    years_detected: float = 0
    section: str = ""
    snippet: str = ""
    reason: str = ""
    scoring_mode: str
    scoring_trace: Optional[Dict[str, Any]] = None


class CategoryScoreResponse(BaseModel):
    """One category's aggregate score."""
    name: str
    raw_score: float
    max_score: float
    score: float
    items: List[ItemScoreResponse]


class ScoreCandidateResponse(BaseModel):
    """Full evaluation for one candidate against one weight config."""
    candidate_id: str
    role: str
    config_name: str
    total: float
    total_raw: float
    total_max: float
    has_flagged_institute: bool
    flagged_institutes: List[str]
    categories: List[CategoryScoreResponse]


class RankResponse(BaseModel):
    """Ranking of all candidates in a role."""
    role: str
    config_name: str
    total_candidates: int
    scored_candidates: int
    rankings: List[ScoreCandidateResponse]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/configs/{role}", response_model=List[str])
def list_available_configs(role: str) -> List[str]:
    """List all weight config names available for a role."""
    paths = list_configs_for_role(role)
    # Extract the config name from each filename: <role>_WeightConfig_<name>.json
    prefix = f"{role}_WeightConfig_"
    suffix = ".json"
    names = []
    for p in paths:
        n = p.name
        if n.startswith(prefix) and n.endswith(suffix):
            names.append(n[len(prefix):-len(suffix)])
    return names


@router.get("/{role}/rank", response_model=RankResponse)
def rank_candidates(
    role: str,
    config_name: str = Query(..., description="Weight config name"),
    top_k: int = Query(20, ge=1, le=200, description="Number of top candidates to return"),
    db: Session = Depends(get_db),
) -> RankResponse:
    """Rank all candidates in a role against a saved weight config.

    Iterates every candidate in ``data/processed/<role>/``, scores them, and
    returns the top-K by total score.
    """
    role_obj = db.query(Role).filter(Role.name == role).first()
    if not role_obj:
        raise HTTPException(status_code=404, detail=f"Role not found: {role}")

    # Get all candidate IDs (handles both hash and Image_* naming)
    candidate_ids = list_candidate_ids(role)
    if not candidate_ids:
        raise HTTPException(
            status_code=404,
            detail=f"No structured profiles found for role: {role}",
        )

    # Score each candidate (batched: 1 LLM call per candidate for all REQs)
    scored: List[ScoreCandidateResponse] = []
    failed: List[str] = []

    # Initialize a shared LLM caller once (lazy-loaded) so the model
    # is only loaded on the first scoring call
    llm_caller = LLMRubricCaller()

    for cand_id in candidate_ids:
        try:
            result = score_candidate_batched_end_to_end(
                role=role,
                candidate_id=cand_id,
                config_name=config_name,
                llm_caller=llm_caller,
            )
            scored.append(_to_response(result, config_name))
        except Exception as e:
            failed.append(f"{cand_id}: {e}")
            logger.warning("Failed to score %s: %s", cand_id, e)
            continue

    # Sort by total desc
    scored.sort(key=lambda x: x.total, reverse=True)
    top = scored[:top_k]

    return RankResponse(
        role=role,
        config_name=config_name,
        total_candidates=len(candidate_ids),
        scored_candidates=len(scored),
        rankings=top,
    )


@router.get("/{role}/{candidate_id}", response_model=ScoreCandidateResponse)
def score_one_candidate(
    role: str,
    candidate_id: str,
    config_name: str = Query(..., description="Weight config name (e.g., Senior_Level)"),
    db: Session = Depends(get_db),
) -> ScoreCandidateResponse:
    """Score a single candidate against a saved weight config.

    Returns the full evaluation with per-item evidence, scoring traces,
    and a 0-100 total.
    """
    # Verify role exists
    role_obj = db.query(Role).filter(Role.name == role).first()
    if not role_obj:
        raise HTTPException(status_code=404, detail=f"Role not found: {role}")

    try:
        result = score_candidate(
            role=role,
            candidate_id=candidate_id,
            config_name=config_name,
            llm_caller=None,  # No LLM wired yet
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Scoring failed")
        raise HTTPException(status_code=500, detail=f"Scoring failed: {e}")

    return _to_response(result, config_name)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_response(result, config_name: str) -> ScoreCandidateResponse:
    """Convert ``UnifiedCandidateEvaluation`` to API response model."""
    categories = []
    for cat in result.categories:
        items = []
        for it in cat.items:
            items.append(ItemScoreResponse(
                req_id=getattr(it, "req_id", None),
                item_name=it.item_name,
                category=it.category,
                importance=it.importance,
                raw_score=it.raw_score,
                matched=it.matched,
                years_detected=it.years_detected,
                section=it.section or "",
                snippet=it.snippet or "",
                reason=it.reason or "",
                scoring_mode=it.scoring_mode,
                scoring_trace=it.scoring_trace,
            ))
        categories.append(CategoryScoreResponse(
            name=cat.name,
            raw_score=cat.raw_score,
            max_score=cat.max_score,
            score=cat.score,
            items=items,
        ))

    return ScoreCandidateResponse(
        candidate_id=result.candidate_id,
        role=result.role,
        config_name=config_name,
        total=result.total,
        total_raw=result.total_raw,
        total_max=result.total_max,
        has_flagged_institute=result.has_flagged_institute,
        flagged_institutes=result.flagged_institutes,
        categories=categories,
    )
