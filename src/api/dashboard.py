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
ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
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


@router.post("/chat")
def chat_with_candidate(req: ChatRequest) -> Dict[str, Any]:
    """
    Answer a question about a candidate using their resume evidence chunks.

    Uses a RAG-lite approach: relevant evidence_chunks from the processed JSON
    are selected as context, then passed to the LLM with the question.

    Args:
        req: ChatRequest with candidate_id, question, max_chunks.

    Returns:
        Dict with answer, source_chunks used, and candidate_id.
    """
    role = _role_from_candidate_id(req.candidate_id)
    try:
        proc = _load_processed(role, req.candidate_id)
    except HTTPException as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Build context from evidence chunks (simple keyword relevance filter)
    all_chunks = proc.get("evidence_chunks", [])
    question_lower = req.question.lower()
    question_words = set(re.findall(r"\w+", question_lower)) - {
        "the", "a", "an", "is", "are", "was", "were", "has", "have",
        "what", "how", "when", "where", "who", "why", "does", "do",
        "their", "this", "that", "with", "for", "and", "or", "in",
        "of", "to", "on", "at", "can", "did", "they",
    }

    def _relevance(chunk: Dict[str, Any]) -> int:
        text = (chunk.get("text") or "").lower()
        return sum(1 for w in question_words if w in text)

    scored = sorted(all_chunks, key=_relevance, reverse=True)
    context_chunks = scored[: req.max_chunks]

    # Also include raw_text summary if chunks are sparse
    raw_text = proc.get("raw", {}).get("raw_text", "")
    if not context_chunks and raw_text:
        context_chunks = [{"text": raw_text[:4000], "section_type": "full_resume"}]

    context_text = "\n\n---\n\n".join(
        f"[{c.get('section_type', 'section')}]\n{c.get('text', '')}"
        for c in context_chunks
    )

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
        f"RESUME EVIDENCE:\n```\n{context_text}\n```\n\n"
        f"RECRUITER QUESTION: {req.question}\n\n"
        "Answer based only on the evidence above."
    )

    # Waterfall order (exact):
    #  1. OpenCode  — deepseek/deepseek-v4-flash:free
    #  2. OpenCode  — minimax-m3
    #  3. NVIDIA NIM key-1 — google/gemma-4-31b-it
    #  4. NVIDIA NIM key-2 — google/gemma-4-31b-it
    #  5. NVIDIA NIM key-3 — google/gemma-4-31b-it
    #  6. OpenRouter       — google/gemma-4-31b-it:free
    oc_key    = _env_value("OPENCODE_KEY_1")
    oc_url    = _env_value("OPENCODE_BASE_URL", "https://opencode.ai/zen/go/v1")
    nv_url    = _env_value("NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
    or_url    = _env_value("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    or_key    = _env_value("OPENROUTER_API_KEY_1") or _env_value("OPENROUTER_API_KEY")

    providers = []
    if oc_key:
        providers.append({"name": "OpenCode/deepseek-v4-flash", "api_key": oc_key,
                          "base_url": oc_url, "model": "deepseek/deepseek-v4-flash:free"})
        providers.append({"name": "OpenCode/minimax-m3",        "api_key": oc_key,
                          "base_url": oc_url, "model": "minimax-m3"})
    for idx, nv_env in enumerate(["NVIDIA_NIM_API_KEY_1", "NVIDIA_NIM_API_KEY_2", "NVIDIA_NIM_API_KEY_3"], 1):
        nv_key = _env_value(nv_env)
        if nv_key:
            providers.append({"name": f"NVIDIA-key{idx}/gemma-4-31b", "api_key": nv_key,
                              "base_url": nv_url, "model": "google/gemma-4-31b-it"})
    if or_key:
        providers.append({"name": "OpenRouter/gemma-4-31b:free", "api_key": or_key,
                          "base_url": or_url, "model": "google/gemma-4-31b-it:free"})


    if not providers:
        return {
            "candidate_id": req.candidate_id,
            "answer": "Chat is unavailable: no API keys configured.",
            "source_chunks": [],
        }

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
            break  # success — stop waterfall
        except Exception as exc:
            last_error = exc
            logger.warning("Chat provider %s failed: %s — trying next.", provider["name"], exc)
            continue

    if answer is None:
        logger.error("All chat providers failed. Last error: %s", last_error)
        answer = f"Chat unavailable — all providers failed. Last error: {last_error}"

    return {
        "candidate_id": req.candidate_id,
        "answer": answer,
        "source_chunks": [
            {"section": c.get("section_type"), "text": c.get("text", "")[:300]}
            for c in context_chunks
        ],
    }
