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
JOBS_DIR = ROOT / "data" / "jobs"
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
            raw = _call_byok(req.api_key, req.model, system, user, base_url=req.base_url)
        else:
            raw = _call_llm(system, user)
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
# Endpoint 2 — Generate + validate sub-queries per REQ
# ---------------------------------------------------------------------------
@router.post("/gen-subqueries")
def gen_subqueries(req: GenSubqueriesRequest) -> JSONResponse:
    """
    AI generates 2–6 atomic sub-queries per requirement and classifies each GREEN / YELLOW / RED.

    Returns:
        { subqueries: { "REQ-001": [...], "REQ-002": [...] } }
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

        Return ONLY a valid JSON object keyed by req_id — no markdown, no explanation:
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
    reqs_summary = json.dumps(
        [
            {
                "req_id": r.get("req_id"),
                "name": r.get("name"),
                "category": r.get("category"),
                "description": r.get("description", ""),
            }
            for r in req.reqs
        ],
        indent=2,
    )
    user = f"Requirements to decompose:\n{reqs_summary}"

    try:
        if req.api_key and req.model:
            raw = _call_byok(req.api_key, req.model, system, user, base_url=req.base_url)
        else:
            raw = _call_llm(system, user)
        subqueries = _parse_json(raw)
        if not isinstance(subqueries, dict):
            raise ValueError("LLM returned a non-dict response")
    except Exception as exc:
        logger.error("Sub-query generation failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Sub-query generation failed: {exc}")

    return JSONResponse({"subqueries": subqueries})


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

    return JSONResponse({
        "valid": True,
        "provider": provider,
        "reason": f"Link verified — trusted {provider} link.",
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

    # Guard: do not create a duplicate role
    existing = db.query(Role).filter(Role.name == slug).first()
    if existing:
        return JSONResponse(
            {
                "role_id": existing.id,
                "role_slug": slug,
                "already_exists": True,
                "message": (
                    f"Role '{req.role_name}' already exists (id={existing.id}). "
                    "Use Configure Weights to update its weights."
                ),
            }
        )

    # Create Role
    role = Role(
        name=slug,
        display_name=req.role_name,
        description=f"Recruiter wizard upload — {len(req.reqs)} requirements",
    )
    db.add(role)
    db.flush()  # obtain role.id before creating child rows

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

    logger.info("Saved new role '%s' (id=%d) with %d REQs to %s", slug, role.id, len(req.reqs), job_dir)
    return JSONResponse({
        "role_id": role.id,
        "role_slug": slug,
        "already_exists": False,
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
