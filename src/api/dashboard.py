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
        try:
            from src.services.gdrive_syncer import restore_role_files_from_gdrive
            restore_role_files_from_gdrive(role)
        except Exception as e:
            logger.warning("GDrive Sync: Error during on-demand restore of ranked file: %s", e)
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
        try:
            from src.services.gdrive_syncer import restore_role_files_from_gdrive
            restore_role_files_from_gdrive(role)
        except Exception as e:
            logger.warning("GDrive Sync: Error during on-demand restore of processed file: %s", e)
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

    eval_data = None
    eval_file = SCORES_DIR / f"{role}_rag_evaluation.json"
    if eval_file.exists():
        try:
            with eval_file.open("r", encoding="utf-8") as ef:
                eval_data = json.load(ef)
        except Exception:
            pass

    return {
        "role": role,
        "n_candidates": data.get("n_candidates", len(rankings)),
        "mean_score": data.get("mean_score"),
        "rankings": slim_rankings,
        "rag_evaluation": eval_data,
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

    # Build context from rubric traces in the ranked JSON (always available).
    # Each requirement's sub-queries carry closest_evidence + cited_text
    # which together form a reliable summary of the candidate's resume.
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
            pass

    # Last resort: return helpful message
    if not context_parts:
        return {
            "candidate_id": req.candidate_id,
            "answer": "No resume evidence is available for this candidate yet. Run the pipeline to generate scores first.",
            "source_chunks": [],
        }

    # Sort context chunks by keyword relevance to user query, then take top 50 (to cover all requirements)
    question_lower = req.question.lower()
    question_words = set(re.findall(r"\w+", question_lower)) - {
        "the", "a", "an", "is", "are", "was", "were", "has", "have",
        "what", "how", "when", "where", "who", "why", "does", "do",
        "their", "this", "that", "with", "for", "and", "or", "in",
        "of", "to", "on", "at", "can", "did", "they", "about", "candidate", "resume", "experience", "skills"
    }

    def _evidence_relevance(part: str) -> int:
        part_lower = part.lower()
        return sum(2 for w in question_words if w in part_lower)

    context_parts = sorted(context_parts, key=_evidence_relevance, reverse=True)
    
    # Increase to a larger limit of 50 chunks (total size is small, but covers all requirements)
    max_to_use = max(req.max_chunks, 50)
    context_text = "\n\n---\n\n".join(context_parts[:max_to_use])

    # Build global ranking & comparison context
    global_context = ""
    try:
        ranked_data = _load_ranked(role)
        rankings = ranked_data.get("rankings", [])
        total_candidates = len(rankings)
        
        # Find current candidate's index/rank and entry
        candidate_entry = None
        candidate_rank = None
        for i, c in enumerate(rankings):
            if c.get("candidate_id") == req.candidate_id:
                candidate_entry = c
                candidate_rank = i + 1
                break
        
        if rankings and candidate_entry:
            scores = [float(c.get("total") or 0.0) for c in rankings]
            top_score = max(scores)
            min_score = min(scores)
            avg_score = sum(scores) / len(scores)
            
            # Median score
            sorted_scores = sorted(scores)
            n_scores = len(sorted_scores)
            if n_scores % 2 == 1:
                median_score = sorted_scores[n_scores // 2]
            else:
                median_score = (sorted_scores[n_scores // 2 - 1] + sorted_scores[n_scores // 2]) / 2.0
            
            cand_score = float(candidate_entry.get("total") or 0.0)
            
            # Aggregate requirement scores
            req_names = []
            if candidate_entry.get("reqs"):
                req_names = [r.get("requirement_name") for r in candidate_entry.get("reqs")]
            
            req_comparisons = []
            for rname in req_names:
                # Get candidate's contribution for this req
                cand_req = next((r for r in candidate_entry.get("reqs", []) if r.get("requirement_name") == rname), None)
                cand_val = float(cand_req.get("contribution") or 0.0) if cand_req else 0.0
                
                # Top 10 average
                top_10 = rankings[:10]
                top_10_vals = []
                for c in top_10:
                    r_item = next((r for r in c.get("reqs", []) if r.get("requirement_name") == rname), None)
                    if r_item is not None:
                        top_10_vals.append(float(r_item.get("contribution") or 0.0))
                top_10_avg = sum(top_10_vals) / len(top_10_vals) if top_10_vals else 0.0
                
                # Others average
                others = rankings[10:]
                others_vals = []
                for c in others:
                    r_item = next((r for r in c.get("reqs", []) if r.get("requirement_name") == rname), None)
                    if r_item is not None:
                        others_vals.append(float(r_item.get("contribution") or 0.0))
                others_avg = sum(others_vals) / len(others_vals) if others_vals else 0.0
                
                req_comparisons.append(
                    f"- {rname}: Candidate={cand_val:.2f}, Top 10 Avg={top_10_avg:.2f}, Rest of Pool Avg={others_avg:.2f}"
                )
            
            req_comp_text = "\n".join(req_comparisons)
            
            # Compute pool statistics for top 10, 20, 50 candidates
            pool_stats_parts = []
            for limit in [10, 20, 50]:
                sub_pool = rankings[:limit]
                if sub_pool:
                    req_sums: Dict[str, float] = {}
                    for c in sub_pool:
                        for r in c.get("reqs", []):
                            rname = r.get("requirement_name", "")
                            contrib = float(r.get("contribution") or 0.0)
                            req_sums[rname] = req_sums.get(rname, 0.0) + contrib
                    
                    req_avgs = []
                    for rname, total_sum in req_sums.items():
                        avg = total_sum / len(sub_pool)
                        req_avgs.append(f"    * {rname}: Avg Score={avg:.2f}")
                    
                    pool_stats_parts.append(
                        f"  - Top {len(sub_pool)} Candidates (Average scores per requirement):\n"
                        + "\n".join(req_avgs)
                    )
            pool_stats_text = "\n\n".join(pool_stats_parts)

            # Build sub-query evidence details for top candidates
            comp_candidates_text = []
            for idx, c_entry in enumerate(rankings[:5]):
                c_id = c_entry.get("candidate_id", "Unknown")
                c_rank = idx + 1
                c_tot = float(c_entry.get("total") or 0.0)
                
                c_req_details = []
                for r_item in c_entry.get("reqs", []):
                    r_name = r_item.get("requirement_name", "")
                    r_contrib = float(r_item.get("contribution") or 0.0)
                    r_trace = r_item.get("rubric_trace", {})
                    r_sub_scores = r_trace.get("sub_scores", [])
                    
                    evidences = []
                    for sq in r_sub_scores:
                        ev = sq.get("closest_evidence") or sq.get("cited_text") or ""
                        if ev:
                            ev_clean = ev.strip().replace("\n", " ")
                            if len(ev_clean) > 150:
                                ev_clean = ev_clean[:150] + "..."
                            evidences.append(f"    * Q: {sq.get('question', '')} -> Evidence: {ev_clean}")
                    
                    ev_text = "\n".join(evidences[:2])
                    c_req_details.append(
                        f"  - Requirement: {r_name} (Score: {r_contrib:.2f})\n{ev_text}"
                    )
                
                comp_candidates_text.append(
                    f"CANDIDATE {c_rank}: {c_id} (Total Score: {c_tot:.2f})\n"
                    + "\n".join(c_req_details)
                )
            comparison_pool_text = "\n\n".join(comp_candidates_text)

            global_context = (
                f"GLOBAL RANKING & POOL STATISTICS:\n"
                f"- Candidate Rank: {candidate_rank} out of {total_candidates} candidates in pool\n"
                f"- Candidate Score: {cand_score:.2f} / 100.0\n"
                f"- Pool High Score: {top_score:.2f}\n"
                f"- Pool Average Score: {avg_score:.2f}\n"
                f"- Pool Median Score: {median_score:.2f}\n"
                f"- Pool Low Score: {min_score:.2f}\n"
                f"- Requirement Score Comparison:\n{req_comp_text}\n\n"
                f"POOL LEVEL REQ averages (Top 10/20/50):\n{pool_stats_text}\n\n"
                f"DETAILS OF TOP 5 CANDIDATES IN POOL (for comparative questions):\n"
                f"{comparison_pool_text}\n"
            )
    except Exception as exc:
        logger.warning("Could not build comparative context for chat: %s", exc)

    # Build LLM prompt
    system_prompt = (
        "You are an expert HR analyst. You have access to a candidate's resume "
        "evidence (extracted during AI scoring or retrieved from raw resume chunks) and global pool statistics.\n"
        "STRICT COMPARISON & TRUTHFULNESS DIRECTIVES:\n"
        "1. Never speculate, assume, or hallucinate candidate qualifications. If a candidate has a requirement "
        "score of 0.0 or 0.01, or if a sub-question's evidence is 'none' or empty, that candidate has ZERO experience or evidence "
        "for that requirement. Do not imply they might have it.\n"
        "2. Double check all score comparisons: a higher score means superior experience and evidence. Do not invert the comparison "
        "(e.g., if Candidate A has 4.5/9 and Candidate B has 0/9, Candidate A has superior OOD skills, and Candidate B has none. "
        "Never say Candidate A ranks lower than Candidate B for OOD skills in this case).\n"
        "3. Answer the recruiter's comparison questions using only these exact, verified score numbers and direct evidence snippets. "
        "Refuse to speculate about potential future evidence that is not in the text.\n"
        "Answer the recruiter's question concisely, accurately, and professionally based on the provided context."
    )
    user_prompt = (
        f"CANDIDATE: {req.candidate_id}\n\n"
        f"{global_context}\n"
        f"RESUME EVIDENCE:\n```\n{context_text}\n```\n\n"
        f"RECRUITER QUESTION: {req.question}\n\n"
        "Answer based on the evidence and global statistics above."
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
        "source_chunks": source_chunks[:8],
    }
