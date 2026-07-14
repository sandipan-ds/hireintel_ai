"""Recruiter onboarding workflow API.

Provides endpoints for the 6-step recruiter wizard:
  1. POST /api/recruiter/extract-reqs    — AI extracts + validates REQs from JD
  2. POST /api/recruiter/gen-subqueries  — AI generates + validates sub-queries per REQ
  3. POST /api/recruiter/validate-link   — Security check for cloud resume link
  4. POST /api/recruiter/save-role       — Persist JD / REQ artifacts + register in DB
  5. POST /api/recruiter/parse-jd-file   — Extract text from uploaded JD file (.txt/.md/.pdf/.docx)

⚠ No session state is persisted between wizard steps — all context is
carried by the client (sessionStorage) and posted with each request.
This is a stateless, demo-grade implementation by design.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
import uuid
from datetime import datetime
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.models.database import Requirement, Role, get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recruiter", tags=["recruiter"])

# ---------------------------------------------------------------------------
# Storage root for recruiter-uploaded job artifacts
# (kept separate from data/job_descriptions/ which holds pre-built reference JDs)
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent.parent
JOBS_DIR = ROOT / "recruiter" / "data" / "jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Security — trusted cloud resume provider domains (allowlist)
# Only HTTPS links from these domains are accepted.  All others are rejected.
# ---------------------------------------------------------------------------
TRUSTED_DOMAINS = {
    "drive.google.com",
    "docs.google.com",
    "dropbox.com",
    "www.dropbox.com",
    "dl.dropboxusercontent.com",
    "onedrive.live.com",
    "1drv.ms",
    "sharepoint.com",
    "box.com",
    "app.box.com",
}

# Block patterns applied before domain check (XSS / traversal / SSRF guards)
_BLOCK_PATTERNS = [
    r"javascript:",
    r"data:",
    r"vbscript:",
    r"\.\./",
    r"localhost",
    r"127\.0\.",
    r"0\.0\.0\.0",
    r"169\.254\.",   # AWS metadata endpoint
    r"::1",          # IPv6 loopback
]

# ---------------------------------------------------------------------------
# Helper — read .env values
# ---------------------------------------------------------------------------
def _env(key: str, default: str = "") -> str:
    """Read a value from os.environ (populated from .env at startup)."""
    return os.environ.get(key, default).strip()


# ---------------------------------------------------------------------------
# Helper — LLM provider waterfall (mirrors dashboard.py)
# Priority: OpenCode (deepseek → minimax) → NVIDIA NIM (key1/2/3) → OpenRouter
# ---------------------------------------------------------------------------
def _call_llm(system: str, user: str, temperature: float = 0.1) -> str:
    """
    Call an LLM using the configured provider waterfall.

    Provider order is determined by the LLM_BACKEND env var:
      - 'openrouter' (default) → OpenRouter first, then OpenCode, then NVIDIA
      - 'opencode'             → OpenCode first, then OpenRouter, then NVIDIA
      - 'nvidia'               → NVIDIA first, then OpenRouter, then OpenCode

    Args:
        system:      System prompt.
        user:        User message.
        temperature: LLM temperature (low for structured JSON output).

    Returns:
        Raw text content of the first successful provider response.

    Raises:
        RuntimeError: If every configured provider fails.
    """
    backend  = _env("LLM_BACKEND", "openrouter").lower()
    oc_key   = _env("OPENCODE_KEY_1")
    oc_url   = _env("OPENCODE_BASE_URL", "https://opencode.ai/zen/go/v1")
    nv_url   = _env("NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
    or_url   = _env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    or_key   = _env("OPENROUTER_API_KEY_1") or _env("OPENROUTER_API_KEY")
    or_model = _env("OPENROUTER_RUBRIC_MODEL", "google/gemini-3.1-flash-lite")

    # Build per-provider lists
    openrouter_providers: List[Dict[str, str]] = []
    opencode_providers:   List[Dict[str, str]] = []
    nvidia_providers:     List[Dict[str, str]] = []

    if or_key:
        openrouter_providers.append({
            "name": f"OpenRouter/{or_model}",
            "key": or_key, "url": or_url, "model": or_model,
        })
    if oc_key:
        opencode_providers.extend([
            {"name": "OpenCode/deepseek-v4-flash", "key": oc_key,
             "url": oc_url, "model": "deepseek/deepseek-v4-flash:free"},
            {"name": "OpenCode/minimax-m3", "key": oc_key,
             "url": oc_url, "model": "minimax-m3"},
        ])
    for idx, env_var in enumerate(
        ["NVIDIA_NIM_API_KEY_1", "NVIDIA_NIM_API_KEY_2", "NVIDIA_NIM_API_KEY_3"], 1
    ):
        nv_key = _env(env_var)
        if nv_key:
            nvidia_providers.append({
                "name": f"NVIDIA-key{idx}/gemma-4-31b",
                "key": nv_key, "url": nv_url, "model": "google/gemma-4-31b-it",
            })

    # Order according to LLM_BACKEND preference
    if backend == "opencode":
        providers = opencode_providers + openrouter_providers + nvidia_providers
    elif backend == "nvidia":
        providers = nvidia_providers + openrouter_providers + opencode_providers
    else:  # default: openrouter
        providers = openrouter_providers + opencode_providers + nvidia_providers

    if not providers:
        raise RuntimeError("No LLM provider keys configured in .env")

    last_err: Optional[Exception] = None
    for p in providers:
        try:
            resp = httpx.post(
                f"{p['url']}/chat/completions",
                headers={
                    "Authorization": f"Bearer {p['key']}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://hireintel.ai",
                    "X-Title": "HireIntel Recruiter Wizard",
                },
                json={
                    "model": p["model"],
                    "temperature": temperature,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
                timeout=90.0,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            logger.info("Recruiter LLM answered via %s", p["name"])
            return content
        except Exception as exc:
            last_err = exc
            logger.warning("Recruiter provider %s failed: %s — trying next.", p["name"], exc)

    raise RuntimeError(f"All LLM providers failed. Last error: {last_err}")


# ---------------------------------------------------------------------------
# Helper — BYOK call (recruiter-provided OpenRouter key + model)
# When a recruiter supplies their own API key through the sidebar, all LLM
# calls route here instead of the server-side waterfall.  OpenRouter's
# unified API supports all models listed in the wizard (Gemini, Gemma,
# DeepSeek, Minimax, GPT-4o-mini) through a single endpoint.
# ---------------------------------------------------------------------------
def _call_byok(
    api_key: str,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.1,
    base_url: Optional[str] = None,
) -> str:
    """
    Call an LLM using a recruiter-provided API key and base URL.

    Provider-agnostic: works with any OpenAI-compatible endpoint
    (OpenRouter, OpenCode, NVIDIA NIM, Google AI, etc.).

    Args:
        api_key:     Recruiter's API key.
        model:       Provider model slug.
        system:      System prompt.
        user:        User message.
        temperature: Low temperature for structured JSON output.
        base_url:    Provider base URL (e.g. https://opencode.ai/zen/go/v1).
                     Defaults to OpenRouter if not supplied.

    Returns:
        Raw text content of the model response.

    Raises:
        RuntimeError: On HTTP or parsing failure.
    """
    # Use caller-supplied base URL; fall back to OpenRouter default
    endpoint_base = (base_url or _env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")).rstrip("/")
    try:
        resp = httpx.post(
            f"{endpoint_base}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://hireintel.ai",
                "X-Title": "HireIntel Recruiter Wizard",
            },
            json={
                "model": model,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json()

        # Extract content — some models (e.g. reasoning models) put output in
        # reasoning_content rather than content when content is null/empty.
        msg = data.get("choices", [{}])[0].get("message", {})
        content = msg.get("content") or msg.get("reasoning_content") or ""

        if not content:
            # Log the full response so we can debug unexpected formats
            logger.error(
                "BYOK returned empty content. Full response: %s",
                json.dumps(data)[:800],
            )
            finish = data.get("choices", [{}])[0].get("finish_reason", "unknown")
            raise RuntimeError(
                f"Model returned empty content (finish_reason={finish!r}). "
                f"Response snippet: {json.dumps(data)[:300]}"
            )

        logger.info("BYOK answered via %s model=%s", endpoint_base, model)
        return content
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Provider returned HTTP {exc.response.status_code}: {exc.response.text[:400]}"
        ) from exc
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"BYOK call failed: {exc}") from exc

# ---------------------------------------------------------------------------
def _parse_json(text: str) -> Any:
    """Strip reasoning blocks and markdown fences, then parse JSON from an LLM response.

    Some models (e.g. MiniMax-M3, DeepSeek-R1) wrap their chain-of-thought in
    <think>...</think> tags before emitting the actual JSON output.  We must
    remove those blocks first or json.loads will fail immediately.
    """
    text = text.strip()
    # Remove <think>...</think> reasoning blocks (MiniMax-M3, DeepSeek-R1, etc.)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    # Strip ```json ... ``` or ``` ... ``` markdown fences
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return json.loads(text.strip())



# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------
class ExtractReqsRequest(BaseModel):
    """Input for REQ extraction.

    api_key, model, and base_url are optional BYOK fields.  When all three are
    present, the LLM call routes directly to the recruiter's own provider
    instead of the server-side waterfall.  base_url must be the
    OpenAI-compatible endpoint root (e.g. https://opencode.ai/zen/go/v1).
    """
    jd_text: str
    role_name: str
    api_key:  Optional[str] = None   # BYOK: API key
    model:    Optional[str] = None   # BYOK: model slug
    base_url: Optional[str] = None   # BYOK: provider base URL


class GenSubqueriesRequest(BaseModel):
    """Input for sub-query generation (same BYOK semantics as ExtractReqsRequest)."""
    reqs: List[Dict[str, Any]]
    api_key:  Optional[str] = None
    model:    Optional[str] = None
    base_url: Optional[str] = None


class ValidateLinkRequest(BaseModel):
    """Input for cloud link security validation."""
    url: str


class SaveRoleRequest(BaseModel):
    """Input for persisting a completed recruiter session to DB + disk."""
    role_name: str
    jd_text: str
    reqs: List[Dict[str, Any]]
    subqueries: Dict[str, List[Dict[str, Any]]]


# ---------------------------------------------------------------------------
# Endpoint 1 — Extract + validate REQs from JD text
# ---------------------------------------------------------------------------
@router.post("/extract-reqs")
def extract_reqs(req: ExtractReqsRequest) -> JSONResponse:
    """
    AI extracts all requirements from the JD and classifies each as GREEN / YELLOW / RED.

    - GREEN  🟢: Specific and objectively measurable
    - YELLOW 🟡: Somewhat vague but workable with context
    - RED    🔴: Too vague to score — missing years, level, tool name, or domain

    Returns:
        { reqs: [...], count: int }
    """
    system = textwrap.dedent("""\
        You are an expert job requirements analyst for an AI candidate ranking system.

        CRITICAL RULE: Extract ONLY requirements that are EXPLICITLY stated in the Job Description text
        provided by the user. Do NOT guess, infer, or add generic requirements that are not written in
        the JD. Every requirement you list must be traceable to a specific sentence or phrase in the JD.

        For each explicit requirement, classify it as GREEN, YELLOW, or RED:
        - GREEN:  Specific, objectively measurable (e.g. "5+ years Python", "AWS Certified Solutions Architect")
        - YELLOW: Somewhat vague but contextually workable (e.g. "strong communication skills", "team player")
        - RED:    Too vague to score objectively — missing critical detail like years, tool name, or level

        Categories (use EXACTLY these values):
        - Core Skill: primary technical or functional skills
        - Preferred Skill: nice-to-have technical or domain skills
        - Experience: years or type of work experience
        - Education: degree, field of study, or academic level
        - Certification: named certifications (required or preferred)

        requirement_type values:
        - "required" for must-have items stated as mandatory in the JD
        - "preferred" for nice-to-have items stated as optional/preferred in the JD

        Return ONLY a valid JSON array — no markdown fences, no explanation, no <think> tags:
        [
          {
            "req_id": "REQ-001",
            "name": "Short requirement name (max 60 chars)",
            "category": "Core Skill",
            "requirement_type": "required",
            "description": "1-2 sentence description quoting the exact JD phrasing",
            "status": "GREEN",
            "reason": "One sentence explaining the GREEN/YELLOW/RED classification"
          }
        ]
    """)
    user = f"Job Role: {req.role_name}\n\nJob Description (extract requirements ONLY from this text):\n{req.jd_text[:12000]}"

    try:
        if req.api_key and req.model:
            raw = _call_byok(req.api_key, req.model, system, user, temperature=0.0, base_url=req.base_url)
        else:
            raw = _call_llm(system, user, temperature=0.0)
        reqs = _parse_json(raw)
        if not isinstance(reqs, list):
            raise ValueError("LLM returned a non-list response")
    except Exception as exc:
        logger.error("REQ extraction failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"REQ extraction failed: {exc}")

    # Normalize + sanitize fields
    valid_categories = {"Core Skill", "Preferred Skill", "Experience", "Education", "Certification"}
    valid_statuses   = {"GREEN", "YELLOW", "RED"}
    for i, r in enumerate(reqs):
        r["req_id"]            = r.get("req_id") or f"REQ-{i + 1:03d}"
        r["category"]          = r.get("category") if r.get("category") in valid_categories else "Core Skill"
        r["requirement_type"]  = r.get("requirement_type") if r.get("requirement_type") in {"required", "preferred"} else "required"
        r["status"]            = r.get("status") if r.get("status") in valid_statuses else "YELLOW"
        r.setdefault("name", f"Requirement {i + 1}")
        r.setdefault("description", "")
        r.setdefault("reason", "Classified by AI")

    return JSONResponse({"reqs": reqs, "count": len(reqs)})


# ---------------------------------------------------------------------------
# Endpoint 2 — Generate + validate sub-queries per REQ (Parallelized)
# ---------------------------------------------------------------------------
import asyncio

@router.post("/gen-subqueries")
async def gen_subqueries(req: GenSubqueriesRequest) -> JSONResponse:
    """
    AI generates 2–6 atomic sub-queries per requirement and classifies each GREEN / YELLOW / RED.
    Runs concurrently in chunks of 3 requirements to speed up generation by ~4x.
    """
    system = textwrap.dedent("""\
        You are an expert technical recruiter designing candidate evaluation rubrics for an AI scoring system.

        For each requirement, generate 2–6 atomic sub-queries evaluable from resume text alone.

        Sub-query types:
        - binary: yes/no question → scored 0 (absent) or 1 (present)
        - float:  graded assessment → 4-band scale: 0.01 (none), 0.25 (few), 0.50 (some), 1.00 (substantial)

        Classify each sub-query:
        - GREEN:  Specific, directly verifiable from resume text
        - YELLOW: Requires reasonable inference from context
        - RED:    Subjective, not verifiable from resume, or overlaps another sub-query

        Return ONLY a valid JSON object keyed by req_id — no markdown, no explanation, no <think> tags:
        {
          "REQ-001": [
            {
              "sq_id": "SQ001",
              "text": "Does the candidate explicitly list Python as a skill?",
              "type": "binary",
              "scoring_hint": "0 = not mentioned, 1 = explicitly listed in skills or experience",
              "status": "GREEN",
              "reason": "Binary and directly verifiable from the skills section"
            }
          ]
        }
    """)

    # Chunk requirements in batches of 3
    chunks = [req.reqs[i:i + 3] for i in range(0, len(req.reqs), 3)]
    
    def process_chunk(chunk: List[Dict[str, Any]]) -> Dict[str, Any]:
        reqs_summary = json.dumps(
            [
                {
                    "req_id": r.get("req_id"),
                    "name": r.get("name"),
                    "category": r.get("category"),
                    "description": r.get("description", ""),
                }
                for r in chunk
            ],
            indent=2,
        )
        user = f"Requirements to decompose:\n{reqs_summary}"
        
        try:
            if req.api_key and req.model:
                raw = _call_byok(req.api_key, req.model, system, user, temperature=0.0, base_url=req.base_url)
            else:
                raw = _call_llm(system, user, temperature=0.0)
            res = _parse_json(raw)
            if isinstance(res, dict):
                return res
            logger.warning("Chunk returned non-dict response: %s", raw)
            return {}
        except Exception as exc:
            logger.error("Failed to generate subqueries for chunk: %s", exc)
            return {}

    # Run chunks in parallel thread pool tasks
    tasks = [asyncio.to_thread(process_chunk, chunk) for chunk in chunks]
    results = await asyncio.gather(*tasks)

    # Merge results
    merged_subqueries: Dict[str, Any] = {}
    for res in results:
        merged_subqueries.update(res)

    return JSONResponse({"subqueries": merged_subqueries})


# ---------------------------------------------------------------------------
# Endpoint 3 — Validate a cloud resume storage link
# ---------------------------------------------------------------------------
@router.post("/validate-link")
def validate_link(req: ValidateLinkRequest) -> JSONResponse:
    """
    Security-validate a cloud resume storage link.

    Checks (in order):
      1. Block-pattern guard (XSS / traversal / SSRF)
      2. URL parseable and uses HTTPS
      3. Hostname in trusted provider allowlist (or subdomain of one)

    Returns:
        { valid: bool, provider: str | null, reason: str }
    """
    url = req.url.strip()

    # 1. Block pattern guard
    for pattern in _BLOCK_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return JSONResponse({
                "valid": False,
                "provider": None,
                "reason": f"URL contains a blocked pattern and cannot be accepted.",
            })

    # 2. Parse and scheme check
    try:
        parsed = urlparse(url)
    except Exception:
        return JSONResponse({"valid": False, "provider": None, "reason": "Invalid URL format."})

    if parsed.scheme != "https":
        return JSONResponse({
            "valid": False, "provider": None,
            "reason": "Only HTTPS links are accepted. Please use a secure (https://) link.",
        })

    # 3. Domain allowlist
    hostname = (parsed.hostname or "").lower()
    is_trusted = hostname in TRUSTED_DOMAINS or any(
        hostname.endswith(f".{d}") for d in TRUSTED_DOMAINS
    )
    if not is_trusted:
        return JSONResponse({
            "valid": False, "provider": None,
            "reason": (
                f"Domain '{hostname}' is not in the trusted list. "
                "Supported providers: Google Drive, Dropbox, OneDrive, SharePoint, Box."
            ),
        })

    # Identify provider label
    provider_map = {
        "drive.google.com": "Google Drive", "docs.google.com": "Google Drive",
        "dropbox.com": "Dropbox", "www.dropbox.com": "Dropbox",
        "dl.dropboxusercontent.com": "Dropbox",
        "onedrive.live.com": "OneDrive", "1drv.ms": "OneDrive",
        "box.com": "Box", "app.box.com": "Box",
    }
    provider = next(
        (v for k, v in provider_map.items() if hostname == k or hostname.endswith(f".{k}")),
        "SharePoint",
    )

    # 4. Connection & Secure Sign-in Verification (Safe Scan)
    try:
        # Use a short timeout to prevent UI hang
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = httpx.get(url, headers=headers, follow_redirects=True, timeout=5.0)
        
        # Check if it returned a standard error code
        if resp.status_code == 404:
            return JSONResponse({
                "valid": False, "provider": provider,
                "reason": f"Link returned 404 (Not Found). Check the link or make sure sharing is enabled.",
            })
        elif resp.status_code in (401, 403):
            return JSONResponse({
                "valid": False, "provider": provider,
                "reason": f"Link returned {resp.status_code} (Access Denied). Please set folder sharing to 'Anyone with the link'.",
            })
            
        # Check for Google Sign-in redirect
        final_url = str(resp.url).lower()
        if "accounts.google.com" in final_url or "signin" in final_url or "login" in final_url:
            return JSONResponse({
                "valid": False, "provider": provider,
                "reason": "This folder link requires sign-in. Change permissions to 'Anyone with the link'.",
            })
            
    except Exception as exc:
        # Don't block completely on connection failure (e.g. offline dev), but warn
        logger.warning("Validation connection check failed for %s: %s", url, exc)
        return JSONResponse({
            "valid": True, "provider": provider,
            "reason": f"Link matched {provider} template, but accessibility verification was skipped.",
        })

    return JSONResponse({
        "valid": True,
        "provider": provider,
        "reason": f"Link verified — trusted {provider} link and publicly accessible.",
    })


# ---------------------------------------------------------------------------
# Endpoint 4 — Save role + artifacts to DB and disk
# ---------------------------------------------------------------------------
@router.post("/save-role")
def save_role(req: SaveRoleRequest, db: Session = Depends(get_db)) -> JSONResponse:
    """
    Persist a completed recruiter session: role → SQLite, artifacts → data/jobs/{slug}/.

    - Creates a new Role row (returns existing if name already taken).
    - Creates Requirement rows for all extracted REQs.
    - Writes jd.md, requirements.json, subqueries.json, metadata.json to disk.

    Returns:
        { role_id: int, role_slug: str, message: str }
    """
    # Derive a safe slug from the role name + today's date so external recruiter
    # sessions never collide with the internal project's pre-scored roles
    # (e.g. internal "ReactDeveloper" vs wizard "React_Developer_20260714").
    date_suffix = datetime.utcnow().strftime("%Y%m%d")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", req.role_name.strip()).strip("_") + f"_{date_suffix}"

    # Delete old rankings, scores, and index files immediately when saving the role configuration
    old_ranked_file = Path("recruiter/data/scores/composed") / f"{slug}_ranked.json"
    old_cand_dir = Path("recruiter/data/scores/composed") / slug
    idx_path_old = Path("recruiter/data/embeddings") / f"{slug}_index.npz"
    chk_path_old = Path("recruiter/data/embeddings") / f"{slug}_chunks.jsonl"
    try:
        import shutil
        if old_ranked_file.exists():
            old_ranked_file.unlink()
        if old_cand_dir.exists():
            shutil.rmtree(old_cand_dir)
        if idx_path_old.exists():
            idx_path_old.unlink()
        if chk_path_old.exists():
            chk_path_old.unlink()
        logger.info("Cleared old rankings and index files for %s on save_role", slug)
    except Exception as exc:
        logger.warning("Failed to clear old score files for %s: %s", slug, exc)

    # Guard: support updating existing roles or create new ones
    existing = db.query(Role).filter(Role.name == slug).first()
    if existing:
        role = existing
        # Delete old Requirement rows so we can re-insert updated ones
        db.query(Requirement).filter(Requirement.role_id == role.id).delete()
        already_exists = True
    else:
        # Create Role
        role = Role(
            name=slug,
            display_name=req.role_name,
            description=f"Recruiter wizard upload — {len(req.reqs)} requirements",
        )
        db.add(role)
        db.flush()  # obtain role.id before creating child rows
        already_exists = False

    # Create Requirement rows
    for r in req.reqs:
        db.add(Requirement(
            role_id=role.id,
            req_id=r.get("req_id", "REQ-???"),
            name=r.get("name", "Unknown"),
            category=r.get("category", "Core Skill"),
            requirement_type=r.get("requirement_type", "required"),
            description=r.get("description", ""),
            subquery_count=len(req.subqueries.get(r.get("req_id", ""), [])),
        ))

    db.commit()

    # Write artifacts to disk under data/jobs/{slug}/
    job_dir = JOBS_DIR / slug
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "jd.md").write_text(req.jd_text, encoding="utf-8")
    (job_dir / "requirements.json").write_text(
        json.dumps(req.reqs, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (job_dir / "subqueries.json").write_text(
        json.dumps(req.subqueries, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (job_dir / "metadata.json").write_text(
        json.dumps(
            {"role_name": req.role_name, "role_slug": slug,
             "role_id": role.id, "req_count": len(req.reqs)},
            indent=2,
        ),
        encoding="utf-8",
    )

    # Automatically generate the SubQuery markdown file for scoring pipeline lookup
    # under recruiter/data/job_descriptions/{slug}/{slug}_SubQuery.md
    jd_desc_dir = ROOT / "recruiter" / "data" / "job_descriptions" / slug
    jd_desc_dir.mkdir(parents=True, exist_ok=True)
    
    md_lines = [
        f"# {req.role_name}: Sub-Query Decomposition",
        "",
        "**Purpose:** Break down each requirement from the JD into atomic, measurable sub-queries.",
        "",
        "---",
        "",
        "## SECTION 1: REQUIREMENTS",
        ""
    ]
    for r in req.reqs:
        r_id = r.get("req_id", "REQ-???")
        r_name = r.get("name", "Unknown")
        r_cat = r.get("category", "Core Skill")
        sq_list = req.subqueries.get(r_id, [])
        
        md_lines.append(f"### {r_id}: {r_name}")
        md_lines.append("")
        md_lines.append(f"**Category:** {r_cat}  ")
        md_lines.append(f"**Sub-Query Count:** {len(sq_list)}  ")
        
        # Build scoring formula, e.g. SQ001 * SQ002
        formula_parts = [sq.get("sq_id") or f"SQ{idx+1:03d}" for idx, sq in enumerate(sq_list)]
        formula = " * ".join(formula_parts)
        md_lines.append(f"**Scoring Formula:** {formula}  ")
        md_lines.append("")
        
        md_lines.append("| # | Sub-Query | Type | Scale | Assessment Method |")
        md_lines.append("|---|-----------|------|-------|-------------------|")
        for sq in sq_list:
            sq_id = sq.get("sq_id") or "SQ???"
            text = sq.get("text") or ""
            sq_type = sq.get("type") or "Binary"
            scale = sq.get("scale") or "0 or 1"
            method = sq.get("reason") or sq.get("scoring_hint") or "Look for evidence in resume"
            md_lines.append(f"| {sq_id} | {text} | {sq_type} | {scale} | {method} |")
        
        md_lines.append("")
        md_lines.append("---")
        md_lines.append("")

    sq_md_content = "\n".join(md_lines)
    (jd_desc_dir / f"{slug}_SubQuery.md").write_text(sq_md_content, encoding="utf-8")
    (job_dir / f"{slug}_SubQuery.md").write_text(sq_md_content, encoding="utf-8")

    logger.info("Saved new role '%s' (id=%d) with %d REQs to %s and %s", slug, role.id, len(req.reqs), job_dir, jd_desc_dir)
    return JSONResponse({
        "role_id": role.id,
        "role_slug": slug,
        "already_exists": already_exists,
        "message": f"Role '{req.role_name}' saved — {len(req.reqs)} requirements registered.",
    })


# ---------------------------------------------------------------------------
# Endpoint 5 — Parse JD text from an uploaded file
# ---------------------------------------------------------------------------
@router.post("/parse-jd-file")
async def parse_jd_file(file: UploadFile = File(...)) -> JSONResponse:
    """
    Extract plain text from an uploaded JD file for the textarea in Step 1.

    Supported: .txt, .md (browser-side), .pdf, .docx (server-side extraction).

    Returns:
        { text: str, source: str }
    """
    ext = Path(file.filename or "").suffix.lower()
    content = await file.read()

    if ext in (".txt", ".md"):
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1")
        return JSONResponse({"text": text, "source": file.filename})

    if ext == ".pdf":
        try:
            import io
            import pdfplumber  # already a project dependency
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                text = "\n\n".join(p.extract_text() or "" for p in pdf.pages).strip()
            return JSONResponse({"text": text, "source": file.filename})
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"PDF extraction failed: {exc}")

    if ext == ".docx":
        try:
            import io
            import docx  # python-docx
            doc = docx.Document(io.BytesIO(content))
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            return JSONResponse({"text": text, "source": file.filename})
        except ImportError:
            raise HTTPException(
                status_code=422,
                detail="python-docx is not installed. Please paste the JD text manually.",
            )
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"DOCX extraction failed: {exc}")

    raise HTTPException(
        status_code=415,
        detail=f"Unsupported file type '{ext}'. Use .txt, .md, .pdf, or .docx.",
    )


# ---------------------------------------------------------------------------
# In-memory job store — persists for the lifetime of the server process.
# Each entry: { status, phase, done, total, eta_seconds, started, log }
# ---------------------------------------------------------------------------
_SCORING_JOBS: Dict[str, Dict[str, Any]] = {}

_PYTHON = (
    str(Path(".venv/Scripts/python.exe"))
    if Path(".venv/Scripts/python.exe").exists()
    else "python"
)


class StartScoringRequest(BaseModel):
    """Input for kicking off the extraction + scoring pipeline via the web UI."""
    role_slug: str
    n_reqs: int = 10
    parallel: bool = True
    resume_link: Optional[str] = None
    weights: Optional[Dict[str, float]] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None


def _download_resumes_from_link(link: str, dest_dir: Path) -> int:
    """
    Parse a shared Google Drive or Dropbox link and download all resumes
    to the destination directory. Returns the number of files downloaded.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    link = link.strip()
    downloaded_count = 0

    # ── CASE 1: Dropbox Shared Folder ──────────────────────────────────────
    if "dropbox.com" in link:
        # Dropbox folders can be downloaded as a ZIP archive by appending/changing dl=1
        zip_url = link
        if "dl=0" in zip_url:
            zip_url = zip_url.replace("dl=0", "dl=1")
        elif "dl=" not in zip_url:
            zip_url += ("&" if "?" in zip_url else "?") + "dl=1"

        zip_path = dest_dir / "temp_resumes.zip"
        try:
            logger.info("Downloading Dropbox folder ZIP from %s", zip_url)
            with httpx.stream("GET", zip_url, follow_redirects=True, timeout=60.0) as r:
                r.raise_for_status()
                with open(zip_path, "wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)

            # Extract ZIP
            import zipfile
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                # Extract only files ending with allowed extensions
                allowed_exts = {".pdf", ".docx", ".doc"}
                for member in zip_ref.infolist():
                    filename = Path(member.filename).name
                    ext = Path(member.filename).suffix.lower()
                    if ext in allowed_exts and not filename.startswith("._"):
                        # Extract directly into dest_dir, flattening folder structures
                        with zip_ref.open(member) as source, open(dest_dir / filename, "wb") as target:
                            target.write(source.read())
                            downloaded_count += 1
            os.remove(zip_path)
            logger.info("Extracted %d resumes from Dropbox ZIP", downloaded_count)
            return downloaded_count
        except Exception as e:
            logger.error("Dropbox download failed: %s", e)
            if zip_path.exists():
                os.remove(zip_path)

    # ── CASE 2: Google Drive Shared Folder ─────────────────────────────────
    if "drive.google.com" in link or "docs.google.com" in link:
        # Try gdown first as it is the most robust and handles complex nested pages and redirects
        folder_match = re.search(r"/folders/([a-zA-Z0-9-_]+)", link)
        if folder_match:
            folder_id = folder_match.group(1)
            try:
                import gdown
                logger.info("Downloading folder ID %s using gdown...", folder_id)
                
                # gdown will download and return the list of downloaded files.
                # It automatically filters files or downloads the folder structure.
                downloaded_files = gdown.download_folder(
                    id=folder_id,
                    output=str(dest_dir),
                    quiet=True,
                    use_cookies=False
                )
                
                if downloaded_files:
                    # Clean up any nested directories or files that don't match allowed types
                    allowed_exts = {".pdf", ".docx", ".doc"}
                    for p in dest_dir.rglob("*"):
                        if p.is_file():
                            if p.suffix.lower() not in allowed_exts or p.name.startswith("._"):
                                os.remove(p)
                            else:
                                # Flatten: move to parent dest_dir if nested
                                if p.parent != dest_dir:
                                    shutil.move(str(p), str(dest_dir / p.name))
                                downloaded_count += 1
                    
                    # Remove empty subfolders
                    for p in sorted(dest_dir.glob("**/"), key=lambda x: len(str(x)), reverse=True):
                        if p.is_dir() and p != dest_dir:
                            try:
                                os.rmdir(p)
                            except OSError:
                                pass
                                
                    logger.info("Successfully fetched %d resumes via gdown.", downloaded_count)
                    return downloaded_count
            except Exception as ge:
                err_msg = str(ge)
                if "status code 500" in err_msg or "status code 403" in err_msg or "status code 404" in err_msg:
                    raise ValueError(
                        "Google Drive returned Access Denied (404/500). Please verify that "
                        "the folder link sharing setting is set to 'Anyone with the link' (Viewer/Editor)."
                    )
                logger.warning("gdown download failed: %s — trying fallback HTTP scraper...", ge)

            # Fallback HTTP scraper if gdown failed or is not available
            folder_url = f"https://drive.google.com/drive/folders/{folder_id}"
            try:
                logger.info("Fetching Google Drive folder page: %s", folder_url)
                resp = httpx.get(
                    folder_url,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                    follow_redirects=True,
                    timeout=30.0,
                )
                if resp.status_code in (404, 403, 500):
                    raise ValueError(
                        "Google Drive returned Access Denied (404/500). Please verify that "
                        "the folder link sharing setting is set to 'Anyone with the link' (Viewer/Editor)."
                    )
                resp.raise_for_status()
                html = resp.text

                # Matches: ["ID", "filename.ext"]
                matches = re.findall(
                    r'\["([a-zA-Z0-9-_]{28,})","([^"]+\.[a-zA-Z0-9]{3,4})"', html
                )
                if not matches:
                    # Fallback regex to capture /file/d/ID links
                    file_ids = list(set(re.findall(r"/file/d/([a-zA-Z0-9-_]+)", html)))
                    matches = [(fid, f"resume_{idx+1}.pdf") for idx, fid in enumerate(file_ids)]

                seen_ids = set()
                allowed_exts = {".pdf", ".docx", ".doc"}
                for file_id, file_name in matches:
                    if file_id in seen_ids:
                        continue
                    seen_ids.add(file_id)

                    ext = Path(file_name).suffix.lower()
                    if ext not in allowed_exts:
                        continue

                    dl_url = f"https://drive.google.com/uc?export=download&id={file_id}"
                    file_dest = dest_dir / file_name
                    logger.info("Downloading file %s (ID: %s)", file_name, file_id)

                    try:
                        with httpx.stream("GET", dl_url, follow_redirects=True, timeout=60.0) as r:
                            content_disp = r.headers.get("content-disposition", "")
                            if "attachment" not in content_disp:
                                text = ""
                                for chunk in r.iter_text():
                                    text += chunk
                                    if len(text) > 2000:
                                        break
                                confirm_match = re.search(r"confirm=([a-zA-Z0-9-_]+)", text)
                                if confirm_match:
                                    confirm_token = confirm_match.group(1)
                                    confirm_url = f"{dl_url}&confirm={confirm_token}"
                                    with httpx.stream("GET", confirm_url, follow_redirects=True, timeout=60.0) as r2:
                                        with open(file_dest, "wb") as f:
                                            for chunk in r2.iter_bytes():
                                                f.write(chunk)
                                else:
                                    with open(file_dest, "wb") as f:
                                        f.write(text.encode("utf-8"))
                            else:
                                with open(file_dest, "wb") as f:
                                    for chunk in r.iter_bytes():
                                        f.write(chunk)
                        
                        if file_dest.exists() and file_dest.stat().st_size > 0:
                            downloaded_count += 1
                    except Exception as fe:
                        logger.error("Failed to download file ID %s: %s", file_id, fe)

                return downloaded_count
            except Exception as e:
                if "Access Denied" in str(e):
                    raise e
                logger.error("Google Drive listing failed: %s", e)

    return downloaded_count

    return downloaded_count


def _silent_cleanup_role(slug: str) -> None:
    """Silently delete original resumes, extracted, processed JSONs, and temporary index files after 10 minutes."""
    import shutil
    orig = Path(f"recruiter/data/original/{slug}")
    extr = Path(f"recruiter/data/extracted/{slug}")
    proc = Path(f"recruiter/data/processed/{slug}")
    jd_dir = Path(f"recruiter/data/job_descriptions/{slug}")
    idx_file = Path(f"recruiter/data/embeddings/{slug}_index.npz")
    chk_file = Path(f"recruiter/data/embeddings/{slug}_chunks.jsonl")
    try:
        if orig.exists():
            shutil.rmtree(orig)
            logger.info("Auto-cleanup: Deleted original resumes directory: %s", orig)
        if extr.exists():
            shutil.rmtree(extr)
            logger.info("Auto-cleanup: Deleted extracted json directory: %s", extr)
        if proc.exists():
            shutil.rmtree(proc)
            logger.info("Auto-cleanup: Deleted processed JSONs directory: %s", proc)
        if jd_dir.exists():
            shutil.rmtree(jd_dir)
            logger.info("Auto-cleanup: Deleted weight config directory: %s", jd_dir)
        if idx_file.exists():
            idx_file.unlink()
            logger.info("Auto-cleanup: Deleted temporary index file: %s", idx_file)
        if chk_file.exists():
            chk_file.unlink()
            logger.info("Auto-cleanup: Deleted temporary chunks file: %s", chk_file)
    except Exception as exc:
        logger.error("Auto-cleanup failed for %s: %s", slug, exc)


# ---------------------------------------------------------------------------
# Endpoint 6 — Start scoring pipeline in background
# ---------------------------------------------------------------------------
@router.post("/start-scoring")
def start_scoring(req: StartScoringRequest) -> JSONResponse:
    """
    Launch auto-download and run extraction + scoring pipeline in the background.
    Schedules silent deletion of data files after 10 minutes.
    """
    job_id = uuid.uuid4().hex[:10]
    
    # We don't know the count or ETA until we download. Start with estimate.
    _SCORING_JOBS[job_id] = {
        "status": "running",
        "phase": "downloading",
        "done": 0,
        "total": 0,
        "eta_seconds": 60,  # placeholder until downloads finish
        "started": time.time(),
        "log": ["Awaiting connection to shared folder...", "Starting download..."],
    }

    # Start pipeline thread (download → extract → score)
    import threading
    t = threading.Thread(
        target=_run_pipeline_bg,
        args=(job_id, req.role_slug, req.resume_link, req.n_reqs, req.parallel, req.weights, req.api_key, req.model, req.base_url),
        daemon=True,
    )
    t.start()

    # Schedule silent auto-cleanup in 10 minutes (600 seconds)
    cleanup_timer = threading.Timer(600.0, _silent_cleanup_role, args=(req.role_slug,))
    cleanup_timer.daemon = True
    cleanup_timer.start()

    return JSONResponse({
        "job_id": job_id,
        "resume_count": 0,
        "eta_seconds": 60,
    })


def _run_pipeline_bg(job_id: str, slug: str, link: Optional[str], n_reqs: int, parallel: bool, weights: Optional[Dict[str, float]], api_key: Optional[str], model: Optional[str], base_url: Optional[str]) -> None:
    """Run download → extract → score pipeline in a background thread, updating _SCORING_JOBS."""
    job = _SCORING_JOBS.get(job_id)
    if not job:
        return
        return

    # 0. Delete old rankings, embeddings, and score data to avoid stale UI state
    old_ranked_file = Path("recruiter/data/scores/composed") / f"{slug}_ranked.json"
    old_cand_dir = Path("recruiter/data/scores/composed") / slug
    idx_path_old = Path("recruiter/data/embeddings") / f"{slug}_index.npz"
    chk_path_old = Path("recruiter/data/embeddings") / f"{slug}_chunks.jsonl"
    try:
        import shutil
        if old_ranked_file.exists():
            old_ranked_file.unlink()
        if old_cand_dir.exists():
            shutil.rmtree(old_cand_dir)
        if idx_path_old.exists():
            idx_path_old.unlink()
        if chk_path_old.exists():
            chk_path_old.unlink()
        job["log"].append("✓ Cleared old scores and index files.")
    except Exception as exc:
        logger.warning("Failed to clear old score files for %s: %s", slug, exc)

    resume_dir = Path(f"recruiter/data/original/{slug}")
    resume_dir.mkdir(parents=True, exist_ok=True)

    # 1. Download resumes in background
    if link:
        job["phase"] = "downloading"
        job["log"].append(f"Downloading files from: {link}")
        try:
            n_dl = _download_resumes_from_link(link, resume_dir)
            job["log"].append(f"✓ Downloaded {n_dl} resume files successfully.")
        except Exception as e:
            job["status"] = "error"
            job["log"].append(f"✗ Download failed: {e}")
            return
    else:
        job["log"].append("No shared link provided. Checking local folder...")

    # Count files
    exts = {".pdf", ".docx", ".doc"}
    resumes = [f for f in resume_dir.iterdir() if f.suffix.lower() in exts]
    if not resumes:
        job["status"] = "error"
        job["log"].append("✗ No PDF/DOCX resumes found in the folder. Please verify the folder link has public read access.")
        return

    n = len(resumes)
    job["total"] = n
    
    # Calculate true ETA
    eta_seconds = n * (15 + (6 if parallel else n_reqs * 5))
    job["eta_seconds"] = eta_seconds

    # Helper function to run scripts with custom recruiter environment variables
    sub_env = os.environ.copy()
    if api_key:
        sub_env["RECRUITER_API_KEY"] = api_key
    if base_url:
        sub_env["RECRUITER_BASE_URL"] = base_url
    if model:
        sub_env["RECRUITER_MODEL"] = model

    def _run(cmd: list[str], phase: str) -> bool:
        job["phase"] = phase
        job["log"].append(f"▶ {' '.join(cmd)}")
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=sub_env,
            )
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    job["log"] = job["log"][-40:] + [line]
            proc.wait()
            if proc.returncode != 0:
                job["status"] = "error"
                job["log"].append(f"✗ Exited with code {proc.returncode}")
                return False
        except Exception as exc:
            job["status"] = "error"
            job["log"].append(f"✗ {exc}")
            return False
        return True

    # 1.5 Generate recruiter WeightConfig JSON dynamically from SQLite DB and user input
    try:
        from src.models.database import get_db_session
        db = get_db_session()
        role_row = db.query(Role).filter(Role.name == slug).first()
        if role_row:
            req_rows = db.query(Requirement).filter(Requirement.role_id == role_row.id).all()
            weight_list = []
            for r in req_rows:
                pct = 100.0 / len(req_rows)
                if weights and r.req_id in weights:
                    pct = weights[r.req_id]
                
                weight_list.append({
                    "requirement_id": r.req_id,
                    "requirement_name": r.name,
                    "category": r.category,
                    "type": r.requirement_type,
                    "weight_percentage": float(pct)
                })
            
            wc_dir = Path("recruiter/data/job_descriptions") / slug
            wc_dir.mkdir(parents=True, exist_ok=True)
            wc_file = wc_dir / f"{slug}_WeightConfig_recruiter.json"
            
            wc_data = {
                "role": slug,
                "config_name": "recruiter",
                "created_by": "recruiter_wizard",
                "created_date": datetime.utcnow().strftime("%Y-%m-%d"),
                "scale_factor": 1.0,
                "requirements_weights": weight_list
            }
            wc_file.write_text(json.dumps(wc_data, indent=2, ensure_ascii=False), encoding="utf-8")
            job["log"].append("✓ Weight configuration JSON generated successfully.")
        db.close()
    except Exception as we:
        logger.error("Failed to generate recruiter WeightConfig: %s", we)
        job["log"].append(f"⚠ Warning: WeightConfig generation failed: {we}")

    # 1.6 Generate recruiter SubQuery Markdown file dynamically if missing or needs update (self-healing)
    try:
        job_dir = JOBS_DIR / slug
        reqs_file = job_dir / "requirements.json"
        subqueries_file = job_dir / "subqueries.json"
        
        if reqs_file.exists() and subqueries_file.exists():
            reqs_data = json.loads(reqs_file.read_text(encoding="utf-8"))
            subqueries_data = json.loads(subqueries_file.read_text(encoding="utf-8"))
            
            jd_desc_dir = ROOT / "recruiter" / "data" / "job_descriptions" / slug
            jd_desc_dir.mkdir(parents=True, exist_ok=True)
            
            md_lines = [
                f"# {slug}: Sub-Query Decomposition",
                "",
                "**Purpose:** Break down each requirement from the JD into atomic, measurable sub-queries.",
                "",
                "---",
                "",
                "## SECTION 1: REQUIREMENTS",
                ""
            ]
            for r in reqs_data:
                r_id = r.get("req_id", "REQ-???")
                r_name = r.get("name", "Unknown")
                r_cat = r.get("category", "Core Skill")
                sq_list = subqueries_data.get(r_id, [])
                
                md_lines.append(f"### {r_id}: {r_name}")
                md_lines.append("")
                md_lines.append(f"**Category:** {r_cat}  ")
                md_lines.append(f"**Sub-Query Count:** {len(sq_list)}  ")
                
                formula_parts = [sq.get("sq_id") or f"SQ{idx+1:03d}" for idx, sq in enumerate(sq_list)]
                formula = " * ".join(formula_parts)
                md_lines.append(f"**Scoring Formula:** {formula}  ")
                md_lines.append("")
                
                md_lines.append("| # | Sub-Query | Type | Scale | Assessment Method |")
                md_lines.append("|---|-----------|------|-------|-------------------|")
                for sq in sq_list:
                    sq_id = sq.get("sq_id") or "SQ???"
                    text = sq.get("text") or ""
                    sq_type = sq.get("type") or "Binary"
                    scale = sq.get("scale") or "0 or 1"
                    method = sq.get("reason") or sq.get("scoring_hint") or "Look for evidence in resume"
                    md_lines.append(f"| {sq_id} | {text} | {sq_type} | {scale} | {method} |")
                
                md_lines.append("")
                md_lines.append("---")
                md_lines.append("")

            sq_md_content = "\n".join(md_lines)
            (jd_desc_dir / f"{slug}_SubQuery.md").write_text(sq_md_content, encoding="utf-8")
            (job_dir / f"{slug}_SubQuery.md").write_text(sq_md_content, encoding="utf-8")
            job["log"].append("✓ SubQuery markdown generated successfully (self-healing).")
    except Exception as sqe:
        logger.error("Failed to generate recruiter SubQuery markdown in pipeline: %s", sqe)
        job["log"].append(f"⚠ Warning: SubQuery markdown generation failed: {sqe}")

    # 2. Extract resumes using the recruiter extraction script
    ok = _run([_PYTHON, "recruiter/batch_extract_resumes.py", "--role", slug], "extracting")
    if not ok:
        return

    # 2.5 Build dynamic embedding index containing only the recruiter's resumes
    idx_path = f"recruiter/data/embeddings/{slug}_index.npz"
    chk_path = f"recruiter/data/embeddings/{slug}_chunks.jsonl"
    ok = _run(
        [_PYTHON, "recruiter/build_index.py", "--index-path", idx_path, "--chunks-path", chk_path, "--role", slug],
        "indexing"
    )
    if not ok:
        return

    # 3. Score resumes using the recruiter scoring script and dynamic index file
    ok = _run(
        [_PYTHON, "recruiter/score_batch_composed.py", "--role", slug, "--index-path", idx_path],
        "scoring"
    )
    if not ok:
        return

    job["status"] = "done"
    job["phase"] = "done"
    job["log"].append("✓ Scoring complete — click ↻ Check for Rankings")


# ---------------------------------------------------------------------------
# Endpoint 7 — Poll scoring job status
# ---------------------------------------------------------------------------
@router.get("/scoring-status/{job_id}")
def scoring_status(job_id: str) -> JSONResponse:
    """
    Return progress for a scoring job started by /start-scoring.

    Returns { status, phase, done, total, eta_seconds, elapsed, log }.
    """
    job = _SCORING_JOBS.get(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found. The server may have restarted.")

    elapsed = int(time.time() - job["started"])
    remaining = max(0, job["eta_seconds"] - elapsed)

    return JSONResponse({
        "status":      job["status"],      # "running" | "done" | "error"
        "phase":       job["phase"],       # "extracting" | "scoring" | "done"
        "done":        job["done"],
        "total":       job["total"],
        "eta_seconds": remaining,
        "elapsed":     elapsed,
        "log":         job["log"][-10:],   # last 10 lines for UI display
    })
