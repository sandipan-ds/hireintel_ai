"""Dashboard API router — src/api/dashboard.py

Provides data endpoints for the HireIntel.AI ranking dashboard and candidate
chat feature. All data is read from the existing scored JSON files on disk;
no database dependency is required for these endpoints.

Routes:
    GET  /api/v1/roles                          List scored roles
    GET  /api/v1/rankings/{role}                Full ranked list for a role
    GET  /api/v1/candidate/{candidate_id}       Candidate detail + score breakdown
    GET  /api/v1/pdf/{role}/{candidate_id}      Stream original PDF
    POST /api/v1/chat                           RAG-lite chat with a candidate
"""

from __future__ import annotations

import json
import logging
import pathlib
import re
import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["dashboard"])

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = pathlib.Path(__file__).resolve().parent.parent.parent.parent
SCORES_DIR = ROOT / "data" / "scores" / "composed"
PROCESSED_DIR = ROOT / "data" / "processed"
ORIGINAL_DIR = ROOT / "data" / "original"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _role_from_candidate_id(candidate_id: str) -> str:
    """Extract role name from a candidate_id like 'BusinessAnalyst_CAND_0075'."""
    return "_".join(candidate_id.split("_")[:-2])


def _load_ranked(role: str) -> Dict[str, Any]:
    """Load and return the ranked JSON for a role."""
    path = SCORES_DIR / f"{role}_ranked.json"
    recruiter_path = ROOT / "recruiter" / "data" / "scores" / "composed" / f"{role}_ranked.json"
    if recruiter_path.exists():
        path = recruiter_path
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No rankings for role: {role}")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_processed(role: str, candidate_id: str) -> Dict[str, Any]:
    """Load processed candidate JSON."""
    path = PROCESSED_DIR / role / f"{candidate_id}.json"
    recruiter_path = ROOT / "recruiter" / "data" / "processed" / role / f"{candidate_id}.json"
    if recruiter_path.exists():
        path = recruiter_path
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No processed data for {candidate_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def _env_value(key: str, default: str = "") -> str:
    """Read a single key from .env (not python-dotenv dependency)."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return default
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == key:
            return v.strip().strip('"').strip("'")
    return default


# ---------------------------------------------------------------------------
# API: roles
# ---------------------------------------------------------------------------

@router.get("/roles")
def list_roles() -> List[str]:
    """
    Return all roles that have a scored rankings file.

    Returns:
        Sorted list of role name strings.
    """
    if not SCORES_DIR.exists():
        return []
    return sorted(
        f.stem.replace("_ranked", "")
        for f in SCORES_DIR.glob("*_ranked.json")
    )


# ---------------------------------------------------------------------------
# API: rankings
# ---------------------------------------------------------------------------

@router.get("/rankings/{role}")
def get_rankings(role: str, top: int = 0) -> Dict[str, Any]:
    """
    Return the ranked candidate list for a role.

    Args:
        role: Role name (e.g. 'BusinessAnalyst').
        top:  If > 0, return only the top N candidates. Default: all.

    Returns:
        Dict with meta fields and 'rankings' list. Each candidate entry
        contains: rank, candidate_id, total, blocked_count,
        zero_evidence_count, and a summarised req list (no full traces).
    """
    data = _load_ranked(role)
    rankings = data.get("rankings", [])
    if top > 0:
        rankings = rankings[:top]

    # Strip heavy rubric_trace fields from the list view to keep payload lean
    slim_rankings = []
    for cand in rankings:
        slim_reqs = [
            {
                "requirement_id": r.get("requirement_id"),
                "requirement_name": r.get("requirement_name"),
                "category": r.get("category"),
                "weight_percentage": r.get("weight_percentage"),
                "contribution": r.get("contribution"),
                "sub_score": r.get("sub_score"),
                "blocked": r.get("blocked", False),
            }
            for r in cand.get("reqs", [])
        ]
        slim_rankings.append({
            "rank": cand.get("rank"),
            "candidate_id": cand.get("candidate_id"),
            "total": cand.get("total"),
            "blocked_count": cand.get("blocked_count", 0),
            "zero_evidence_count": cand.get("zero_evidence_count", 0),
            "reqs": slim_reqs,
        })

    return {
        "role": role,
        "n_candidates": data.get("n_candidates", len(rankings)),
        "mean_score": data.get("mean_score"),
        "rankings": slim_rankings,
    }


# ---------------------------------------------------------------------------
# API: candidate detail
# ---------------------------------------------------------------------------

@router.get("/candidate/{candidate_id}")
def get_candidate(candidate_id: str) -> Dict[str, Any]:
    """
    Return full candidate detail: profile, scores with evidence, and PDF info.

    Args:
        candidate_id: Full candidate identifier (e.g. 'BusinessAnalyst_CAND_0075').

    Returns:
        Dict with candidate_id, role, profile, total, reqs (with full traces),
        evidence_chunks (first 10), pdf_available flag.
    """
    role = _role_from_candidate_id(candidate_id)

    # Load from ranked JSON for full trace detail
    ranked_data = _load_ranked(role)
    cand_entry = next(
        (c for c in ranked_data.get("rankings", [])
         if c.get("candidate_id") == candidate_id),
        None,
    )
    if not cand_entry:
        raise HTTPException(status_code=404, detail=f"Candidate {candidate_id} not found")

    # Load processed data for profile and chunks
    try:
        proc = _load_processed(role, candidate_id)
    except HTTPException:
        proc = {}

    profile = proc.get("candidate_profile", {})
    chunks = proc.get("evidence_chunks", [])[:10]
    doc = proc.get("document", {})
    pdf_filename = doc.get("file_name", "")
    pdf_path = ORIGINAL_DIR / role / pdf_filename
    pdf_available = bool(pdf_filename) and pdf_path.exists()

    return {
        "candidate_id": candidate_id,
        "role": role,
        "rank": cand_entry.get("rank"),
        "total": cand_entry.get("total"),
        "blocked_count": cand_entry.get("blocked_count", 0),
        "zero_evidence_count": cand_entry.get("zero_evidence_count", 0),
        "profile": profile,
        "reqs": cand_entry.get("reqs", []),
        "evidence_chunks": chunks,
        "pdf_available": pdf_available,
        "pdf_filename": pdf_filename,
    }


# ---------------------------------------------------------------------------
# API: PDF streaming
# ---------------------------------------------------------------------------

@router.get("/pdf/{candidate_id}")
def serve_pdf(candidate_id: str) -> FileResponse:
    """
    Stream the original PDF resume for a candidate.

    Args:
        candidate_id: Full candidate identifier.

    Returns:
        PDF file response suitable for inline browser viewing.
    """
    role = _role_from_candidate_id(candidate_id)
    try:
        proc = _load_processed(role, candidate_id)
    except HTTPException as exc:
        raise HTTPException(status_code=404, detail="Processed file not found") from exc

    doc = proc.get("document", {})
    pdf_filename = doc.get("file_name", "")
    if not pdf_filename:
        raise HTTPException(status_code=404, detail="No PDF filename in processed data")

    pdf_path = ORIGINAL_DIR / role / pdf_filename
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail=f"PDF not found: {pdf_filename}")

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={candidate_id}.pdf"},
    )


# ---------------------------------------------------------------------------
# API: Chat
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    """Request body for the chat endpoint."""
    candidate_id: str
    question: str
    max_chunks: int = 8
    api_key: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None



@router.post("/chat")
def chat_with_candidate(req: ChatRequest) -> Dict[str, Any]:
    """
    Answer a question about a candidate using their scored rubric evidence.

    Reads evidence from the already-deployed *_ranked.json rubric traces
    (closest_evidence + cited_text per sub-query) so that no processed JSON
    files are needed in the container. Falls back to trying _load_processed
    if evidence_chunks are available there.

    Args:
        req: ChatRequest with candidate_id, question, api_key, model, base_url.

    Returns:
        Dict with answer, source_chunks used, and candidate_id.
    """
    if not req.api_key:
        return {
            "candidate_id": req.candidate_id,
            "answer": "Please configure your OpenRouter API Key in the API Key panel (🔑 API Key in the top-right navbar) to chat with this candidate.",
            "source_chunks": [],
        }

    role = _role_from_candidate_id(req.candidate_id)

    # -----------------------------------------------------------------------
    # Build context from rubric traces in the ranked JSON (always available).
    # Each requirement's sub-queries carry closest_evidence + cited_text
    # which together form a reliable summary of the candidate's resume.
    # -----------------------------------------------------------------------
    context_parts: list[str] = []
    source_chunks: list[Dict[str, Any]] = []

    try:
        ranked_data = _load_ranked(role)
        cand_entry = next(
            (c for c in ranked_data.get("rankings", [])
             if c.get("candidate_id") == req.candidate_id),
            None,
        )
        if cand_entry:
            for req_item in cand_entry.get("reqs", []):
                req_name = req_item.get("requirement_name", "")
                trace = req_item.get("rubric_trace", {})
                sub_scores = trace.get("sub_scores", [])
                for sq in sub_scores:
                    evidence = sq.get("closest_evidence") or sq.get("cited_text") or ""
                    if evidence:
                        chunk_text = (
                            f"[{req_name} — {sq.get('key', '')}]\n"
                            f"Q: {sq.get('question', '')}\n"
                            f"Evidence: {evidence}"
                        )
                        context_parts.append(chunk_text)
                        source_chunks.append({
                            "section": req_name,
                            "text": evidence[:300],
                        })
    except Exception as exc:
        logger.warning("Could not load ranked evidence for chat: %s", exc)

    # Fallback: try processed JSON evidence_chunks if ranked evidence is sparse
    if len(context_parts) < 3:
        try:
            proc = _load_processed(role, req.candidate_id)
            all_chunks = proc.get("evidence_chunks", [])
            question_lower = req.question.lower()
            question_words = set(re.findall(r"\w+", question_lower)) - {
                "the", "a", "an", "is", "are", "was", "were", "has", "have",
                "what", "how", "when", "where", "who", "why", "does", "do",
                "their", "this", "that", "with", "for", "and", "or", "in",
                "of", "to", "on", "at", "can", "did", "they",
            }
            scored = sorted(
                all_chunks,
                key=lambda c: sum(1 for w in question_words if w in (c.get("text") or "").lower()),
                reverse=True,
            )
            for c in scored[: req.max_chunks]:
                context_parts.append(
                    f"[{c.get('section_type', 'section')}]\n{c.get('text', '')}"
                )
                source_chunks.append({
                    "section": c.get("section_type"),
                    "text": c.get("text", "")[:300],
                })
        except Exception:
            pass  # processed files not available in production — that's fine

    # Last resort: return a helpful message if truly no evidence exists
    if not context_parts:
        return {
            "candidate_id": req.candidate_id,
            "answer": "No resume evidence is available for this candidate yet. Run the pipeline to generate scores first.",
            "source_chunks": [],
        }

    context_text = "\n\n---\n\n".join(context_parts[: req.max_chunks])

    # Build LLM prompt
    system_prompt = (
        "You are an expert HR analyst. You have access to a candidate's resume "
        "evidence (extracted during AI scoring or retrieved from raw resume chunks). "
        "Note that some evidence items are associated with a specific Requirement and a "
        "Sub-Question that was already validated and matched by the scoring engine. "
        "Use this mapping to understand the context (e.g., if a snippet is listed under "
        "'Leadership & Mentoring' for a question about mentoring, you should treat it as "
        "valid mentoring evidence even if it uses synonyms like 'led a team' or 'helped a group'). "
        "Answer the recruiter's question concisely and accurately based on the provided context. "
        "If the evidence does not contain enough information, say so clearly."
    )
    user_prompt = (
        f"CANDIDATE: {req.candidate_id}\n\n"
        f"RESUME EVIDENCE (from AI scoring):\n```\n{context_text}\n```\n\n"
        f"RECRUITER QUESTION: {req.question}\n\n"
        "Answer based only on the evidence above."
    )

    providers = [{
        "name": "BYOK",
        "api_key": req.api_key,
        "base_url": req.base_url or "https://openrouter.ai/api/v1",
        "model": req.model or "google/gemini-3.1-flash-lite"
    }]

    answer = None
    last_error = None
    for provider in providers:
        try:
            resp = httpx.post(
                f"{provider['base_url']}/chat/completions",
                headers={
                    "Authorization": f"Bearer {provider['api_key']}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://hireintel.ai",
                    "X-Title": "HireIntel Candidate Chat",
                },
                json={
                    "model": provider["model"],
                    "temperature": 0.2,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
                timeout=60.0,
            )
            resp.raise_for_status()
            answer = resp.json()["choices"][0]["message"]["content"]
            logger.info("Chat answered via %s (model=%s)", provider["name"], provider["model"])
            break
        except Exception as exc:
            last_error = exc
            logger.warning("Chat provider %s failed: %s", provider["name"], exc)
            continue

    if answer is None:
        logger.error("All chat providers failed. Last error: %s", last_error)
        answer = f"Chat unavailable — provider failed. Last error: {last_error}"

    return {
        "candidate_id": req.candidate_id,
        "answer": answer,
        "source_chunks": source_chunks[:8],
    }
