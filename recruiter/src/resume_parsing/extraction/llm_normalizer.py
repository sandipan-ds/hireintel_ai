# This module normalizes raw resume section text into the structured JSON schema.
#
# It uses robust regexes for contact fields (name, email, phone, links)
# and calls an LLM with multi-provider key rotation for structural mapping of:
# education, experience, skills, certifications, and languages.
#
# Provider rotation order (tried in sequence until one succeeds):
#   1. Google AI Studio 1→2  (models/gemma-4-31b-it — Gemma 4 31B multimodal)
#   2. NVIDIA NIM key 1,2,3   (meta/llama-3.2-90b-vision-instruct / 49b-nemotron)
#   3. Google AI Studio 1→2  (models/gemini-2.0-flash — fallback)
#   4. OpenCode keys 1→2→3  (minimax-m3 via /go/v1 — when credits restored)
#   5. OpenRouter keys        (google/gemma-4-31b-it — fallback)
#   6. Ollama (local)         — LAST RESORT only
# If all fail, an empty scaffold is returned so the batch never crashes.
# Timeout: 120s per provider.
# LLM_WORKER_ID env var rotates the list so parallel workers use different keys.

import os
import re
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

from src.resume_parsing.parser import EMAIL_REGEX, PHONE_REGEX, _looks_like_name

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# .env loader — reads all keys, handles duplicate key names
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent.parent.parent
_ENV_PATH = ROOT / ".env"


def _load_env_raw() -> Dict[str, List[str]]:
    """Load .env into key → [values] mapping (handles duplicate keys like NVIDIA_NIM_API_KEY_1)."""
    result: Dict[str, List[str]] = {}
    if not _ENV_PATH.exists():
        return result
    for raw_line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        key = k.strip()
        val = v.strip().strip('"').strip("'")
        if val:
            result.setdefault(key, []).append(val)
    return result


_RAW_ENV = _load_env_raw()


def _get_all(key: str) -> List[str]:
    """Return all non-empty values for a .env key."""
    return _RAW_ENV.get(key, [])


def _get_first(key: str, default: str = "") -> str:
    vals = _get_all(key)
    return vals[0] if vals else default


# ---------------------------------------------------------------------------
# Ollama health check (used only as last-resort fallback)
# ---------------------------------------------------------------------------

def _ollama_is_alive(base_url: str) -> bool:
    """Ping local Ollama root URL with a 1-second timeout."""
    try:
        import requests
        root = base_url.replace("/v1", "").rstrip("/")
        r = requests.get(root, timeout=1.0)
        return r.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Build ordered provider list: (api_key, base_url, model_name)
# ---------------------------------------------------------------------------

# Hard-coded base URLs per provider to avoid ambiguity caused by duplicate
# `base_url` key names in .env (each provider section reuses the same key).
_OPENCODE_BASE    = "https://opencode.ai/zen/go/v1"                          # /go/ = low-cost routing
_GOOGLE_BASE      = "https://generativelanguage.googleapis.com/v1beta/openai/"  # Google AI Studio (OpenAI-compat)
_OPENROUTER_BASE  = "https://openrouter.ai/api/v1"
_NVIDIA_BASE      = "https://integrate.api.nvidia.com/v1"

# Preferred multimodal models per provider.
# NVIDIA: llama-3.2-11b-vision-instruct is confirmed working (vision-capable).
# 90b-vision exists but has higher latency — kept as fallback.
_NVIDIA_MULTIMODAL_MODELS = [
    "meta/llama-3.2-11b-vision-instruct",   # Vision — confirmed 200 OK
    "meta/llama-3.2-90b-vision-instruct",   # Vision 90B — slower, fallback
]


def _build_providers() -> List[Tuple[str, str, str]]:
    """
    Build the ordered list of (api_key, base_url, model) tuples to try.

    Priority (multimodal models, large parameter count preferred):
      1. OpenCode keys 1,2,3    (/go/v1 endpoint, minimax-m3 — low-cost multimodal)
      2. Google AI Studio 1,2   (gemini-2.0-flash — large multimodal, free tier)
      3. OpenRouter keys 1,2,3  (google/gemma-4-31b-it — 31B multimodal)
      4. NVIDIA NIM keys        (llama-3.2-vision — vision-capable)
      5. Ollama local           (last resort — only if running)

    If LLM_WORKER_ID env var is set (by parallel launcher), the list is
    rotated by that many positions so each parallel worker leads with a
    different API key, spreading load across providers.

    Returns:
        List of provider tuples ready to iterate.
    """
    providers: List[Tuple[str, str, str]] = []

    # --- 0. Recruiter BYOK from environment variables (Highest Priority) ----
    recruiter_key = os.environ.get("RECRUITER_API_KEY")
    recruiter_base = os.environ.get("RECRUITER_BASE_URL")
    recruiter_model = os.environ.get("RECRUITER_MODEL")
    if recruiter_key:
        providers.append((
            recruiter_key,
            recruiter_base or "https://openrouter.ai/api/v1",
            recruiter_model or "google/gemma-4-31b-it"
        ))

    # --- 1. Google AI Studio (PRIMARY — gemma-4-31b-it multimodal) -------
    # Models on Google OpenAI endpoint need the 'models/' prefix.
    # Gemma 4 31B is multimodal and fits the >=30B parameter preference perfectly.
    g_model = "models/gemma-4-31b-it"
    for key in (_get_all("GOOGLE_API_KEY_1") + _get_all("GOOGLE_API_KEY_2")):
        providers.append((key, _GOOGLE_BASE, g_model))

    # --- 2. NVIDIA NIM (SECONDARY — 90B and 49B working models) -----------
    # Priority 1: meta/llama-3.2-90b-vision-instruct (90B multimodal vision)
    # Priority 2: nvidia/llama-3.3-nemotron-super-49b-v1 (49B multimodal instruct)
    # Interleave them so worker_id rotation gives Worker 0 -> Key 1, Worker 1 -> Key 2, etc.
    nim_keys = _get_all("NVIDIA_NIM_API_KEY_1")
    for key in nim_keys:
        providers.append((key, _NVIDIA_BASE, "meta/llama-3.2-90b-vision-instruct"))
    for key in nim_keys:
        providers.append((key, _NVIDIA_BASE, "nvidia/llama-3.3-nemotron-super-49b-v1"))

    # --- 3. Google AI Studio Fallback (gemini-2.0-flash) -----------------
    g_fallback = "models/gemini-2.0-flash"
    for key in (_get_all("GOOGLE_API_KEY_1") + _get_all("GOOGLE_API_KEY_2")):
        providers.append((key, _GOOGLE_BASE, g_fallback))

    # --- 4. OpenCode /go/v1 (when credits restored) -----------------------
    oc_model = "minimax-m3"
    for key in (_get_all("OPENCODE_API_KEY_1")
                + _get_all("OPENCODE_API_KEY_2")
                + _get_all("OPENCODE_API_KEY_3")):
        providers.append((key, _OPENCODE_BASE, oc_model))

    # --- 5. OpenRouter (when credits restored) ----------------------------
    or_model = "google/gemma-4-31b-it"
    for key in _get_all("OPENROUTER_API_KEY_1"):
        providers.append((key, _OPENROUTER_BASE, or_model))

    # --- 6. Ollama (last resort) ------------------------------------------
    ollama_base = _get_first("ollama_base_url", "http://localhost:11434/v1")
    ollama_model = _get_first("ollama_model", "gemma3:27b")
    if _ollama_is_alive(ollama_base):
        providers.append(("ollama", ollama_base, ollama_model))
        logger.info("Ollama is running — added as last-resort provider (%s)", ollama_model)
    else:
        logger.debug("Ollama not reachable — skipped")

    if not providers:
        logger.error("No LLM providers found in .env — normalization will produce empty scaffolds.")
        return providers

    # --- Worker-ID rotation (for parallel batch extraction) ---------------
    # LLM_WORKER_ID rotates the list so worker N leads with a different key.
    # Worker 0 = no rotation, Worker 1 = rotate by 1, etc.
    worker_id = int(os.environ.get("LLM_WORKER_ID", "0"))
    if worker_id > 0 and len(providers) > 1:
        shift = worker_id % len(providers)
        providers = providers[shift:] + providers[:shift]
        logger.debug("LLM_WORKER_ID=%d — provider list rotated by %d", worker_id, shift)

    logger.info(
        "Provider list built: %d entries (worker_id=%d) — leading with %s:%s",
        len(providers), worker_id,
        providers[0][1].split('/')[2], providers[0][2]
    )
    return providers


# Build once at module import; re-built lazily if empty
_PROVIDERS: List[Tuple[str, str, str]] = _build_providers()

# ---------------------------------------------------------------------------
# Contact helpers
# ---------------------------------------------------------------------------

LINK_REGEX = re.compile(r"https?://[^\s,\"']+")

def extract_contact_info(text: str) -> Dict[str, Any]:
    """Extract contact information (email, phone, links) from text using deterministic regexes."""
    emails = []
    for m in EMAIL_REGEX.finditer(text):
        emails.append({
            "value": m.group(),
            "primary": len(emails) == 0,
            "confidence": 0.99
        })

    phones = []
    for m in PHONE_REGEX.finditer(text):
        phones.append({
            "value": m.group(),
            "primary": len(phones) == 0,
            "confidence": 0.95
        })

    links = {
        "linkedin": None,
        "github": None,
        "portfolio": None,
        "other": []
    }
    
    for url in LINK_REGEX.findall(text):
        url_lower = url.lower()
        if "linkedin.com" in url_lower:
            links["linkedin"] = url
        elif "github.com" in url_lower:
            links["github"] = url
        elif "portfolio" in url_lower or "personal" in url_lower or "website" in url_lower:
            links["portfolio"] = url
        else:
            links["other"].append(url)

    return {
        "emails": emails,
        "phones": phones,
        "links": links
    }

def extract_name_from_raw_text(raw_text: str) -> Optional[str]:
    """Attempt to extract candidate name from first 10 non-empty lines using looks_like_name filters."""
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    for line in lines[:10]:
        if _looks_like_name(line):
            return line
    return None

_SYSTEM_PROMPT = (
    "You are an expert resume parser. Extract raw resume text into valid JSON matching the schema exactly. "
    "STRICT RULES: "
    "(1) Return ONLY valid raw JSON — no markdown fences (no ```json), no explanation, no comments. "
    "(2) Dates MUST be in YYYY-MM format (e.g. 2021-03, not 03-2021 or March 2021). Use null if unknown. "
    "(3) responsibilities[] must be individual short bullet points (1 sentence each), NOT a single paragraph dump. "
    "Split multi-sentence paragraphs into separate array items. "
    "(4) Each skill in skills[] must be a single discrete technology or skill name, NOT a full sentence. "
    "Bad: 'Experience with relational databases'. Good: 'SQL', 'PostgreSQL'. "
    "(5) full_name must be the candidate's actual name (First Last), not a placeholder or section header. "
    "(6) If a field has no data, set it to null or []. Never invent data."
)


def call_llm_normalizer(prompt: str) -> str:
    """
    Try each LLM provider in order until one succeeds.

    Strategy:
      - timeout=30s per provider (fast-fail on flaky APIs)
      - max_retries=0 (we rotate manually — no exponential backoff hangs)
      - On exception or empty response → immediately try next provider
      - Returns the first non-empty response, or "" if all providers fail

    Args:
        prompt: Full user-side prompt with resume sections and JSON schema.

    Returns:
        Raw LLM response string (may still need markdown fence cleanup).
    """
    from openai import OpenAI

    providers = _PROVIDERS or _build_providers()
    total = len(providers)

    for idx, (api_key, base_url, model) in enumerate(providers):
        host = base_url.split("/")[2] if "/" in base_url else base_url
        label = f"[{idx+1}/{total}] {host} ({model})"
        try:
            client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                max_retries=0,   # rotate manually — no exponential backoff hangs
            )
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
            )
            if not response.choices:
                logger.warning("%s returned empty choices — trying next", label)
                continue
            text = (response.choices[0].message.content or "").strip()
            if not text:
                logger.warning("%s returned empty content — trying next", label)
                continue
            logger.info("%s succeeded", label)
            return text
        except Exception as exc:
            logger.warning("%s failed: %s — trying next", label, exc)
            continue

    logger.error("All %d LLM providers failed — returning empty string", total)
    return ""

def normalize_to_schema(sections: Dict[str, List[str]], raw_text: str, candidate_id: str) -> Dict[str, Any]:
    """
    Call LLM to normalize the raw sections into structured profile fields.

    Args:
        sections: Dictionary mapping canonical section names to list of text blocks.
        raw_text: Full raw text of the resume.
        candidate_id: Registry-allocated candidate ID.

    Returns:
        Dict conforming to candidate_profile section of the schema.
    """
    # 1. Regex-based deterministic contact parsing
    contact = extract_contact_info(raw_text)
    name = extract_name_from_raw_text(raw_text)

    # 2. Build LLM prompt containing section content
    sections_prompt_input = ""
    for sec_name, blocks in sections.items():
        if blocks:
            sections_prompt_input += f"=== SECTION: {sec_name.upper()} ===\n"
            sections_prompt_input += "\n".join(blocks) + "\n\n"

    prompt = f"""Extract the resume below into the JSON schema specified. Follow ALL rules strictly.

RULES:
- Dates: ALWAYS use YYYY-MM format (e.g. 2021-03). If only year known, use YYYY-01. Use null if completely unknown.
- responsibilities[]: Split into INDIVIDUAL bullet points (one action per item). Never dump a full paragraph as one item.
  BAD:  ["Worked on databases and APIs and also handled deployments"]
  GOOD: ["Designed and maintained PostgreSQL databases", "Built REST APIs", "Managed CI/CD deployments"]
- skills[]: Each entry must be ONE discrete skill/technology (e.g. "Python", "React", "Docker").
  Do NOT include full sentences. Extract atomic skill names only.
- name_canonical in skills: standardize names (e.g. "Node Js" -> "Node.js", "postgres" -> "PostgreSQL").
- full_name: Extract the candidate's actual name. If a template placeholder (e.g. "YOUR NAME"), set null.
- summary: The professional summary paragraph from the resume. Set null if not present.
- headline: The job title or professional title line. Set null if not present.
- If no data exists for a section, return an empty array [].

RESUME TEXT:
---
{sections_prompt_input}
---

Return this JSON structure (filled with real data from the resume above):
{{
  "full_name": {json.dumps(name)},
  "headline": "Professional title line or null",
  "summary": "Professional summary paragraph or null",
  "skills": [
    {{
      "name_raw": "exact skill text from resume",
      "name_canonical": "standardized name (Python, Node.js, PostgreSQL, AWS, etc.)",
      "category": "one of: frontend / backend / database / mobile / devops / cloud / methodology / data_science / security / other",
      "source_type": "explicit",
      "last_used": "YYYY-MM or null",
      "months_of_evidence": 0
    }}
  ],
  "education": [
    {{
      "degree": "e.g. B.Tech / M.Tech / MBA / BS / MS / PhD / Bachelor's / Master's",
      "specialization": "e.g. Computer Science / Business Administration",
      "institution_raw": "exact institution name from resume",
      "institution_normalized": "cleaned full institution name",
      "start_date": "YYYY-MM or null",
      "end_date": "YYYY-MM or null",
      "grade": "GPA, CGPA or percentage or null",
      "completed": true
    }}
  ],
  "experience": [
    {{
      "job_title": "Exact job title",
      "company": "Company name or null",
      "employment_type": "full_time / contract / part_time / internship or null",
      "start_date": "YYYY-MM or null",
      "end_date": "YYYY-MM or null (null if current)",
      "is_current": false,
      "location": "City, State/Country or null",
      "responsibilities": ["Individual bullet point 1", "Individual bullet point 2", "..."],
      "tools_and_skills": ["Python", "Django", "PostgreSQL"]
    }}
  ],
  "projects": [
    {{
      "name": "Project name",
      "organization": "Company or university or null",
      "role": "Your role in the project or null",
      "start_date": "YYYY-MM or null",
      "end_date": "YYYY-MM or null",
      "description": ["What the project did", "Your contribution"],
      "skills_used": ["Python", "React"]
    }}
  ],
  "certifications": [
    {{
      "name": "Certification name",
      "issuer": "Issuer organization or null",
      "issue_date": "YYYY-MM or null",
      "expiry_date": "YYYY-MM or null",
      "credential_id": "ID string or null"
    }}
  ],
  "languages": [
    {{
      "name": "Language name (e.g. English, Spanish)",
      "proficiency": "native / fluent / professional / conversational / basic or null"
    }}
  ]
}}
"""

    response = call_llm_normalizer(prompt)
    
    # Clean response (strip thought blocks and markdown wrappers)
    response_clean = response.strip()
    
    # Strip <think>...</think> and <thought>...</thought> reasoning blocks if present.
    response_clean = re.sub(r"<(think|thought)>.*?</(think|thought)>", "", response_clean, flags=re.DOTALL).strip()

    # Strip markdown code blocks
    if response_clean.startswith("```json"):
        response_clean = response_clean[7:]
    elif response_clean.startswith("```"):
        response_clean = response_clean[3:]
    if response_clean.endswith("```"):
        response_clean = response_clean[:-3]
    response_clean = response_clean.strip()
    
    # Strip trailing conversational fluff after the final JSON bracket if present
    if response_clean and not response_clean.endswith("}"):
        idx = response_clean.rfind("}")
        if idx != -1:
            response_clean = response_clean[:idx+1].strip()

    try:
        data = json.loads(response_clean)
    except Exception as exc:
        logger.error("Failed to parse LLM response as JSON: %s\nResponse: %s", exc, response_clean)
        return _scaffold_empty_profile(name, contact)

    # Overwrite regex-extracted contact fields for absolute safety and accuracy
    data["emails"] = contact["emails"]
    data["phones"] = contact["phones"]
    data["links"] = contact["links"]

    # BUG 3 fix: guard against null-like name strings the LLM may echo back.
    # When name is None the prompt injects JSON null, but if the LLM hallucinates
    # "None", "null", "N/A", or an empty string, fall back to the regex-extracted name.
    _NULL_NAME_STRINGS = {"null", "none", "n/a", "na", ""}
    llm_name = data.get("full_name")
    if not llm_name or str(llm_name).strip().lower() in _NULL_NAME_STRINGS:
        data["full_name"] = name


    # Add default field confidence estimates
    for skill in data.get("skills", []):
        skill["confidence"] = 0.90
    for edu in data.get("education", []):
        edu["confidence"] = 0.90
    for exp in data.get("experience", []):
        exp["confidence"] = 0.92
    for proj in data.get("projects", []):
        proj["confidence"] = 0.85
    for cert in data.get("certifications", []):
        cert["confidence"] = 0.93
    for lang in data.get("languages", []):
        lang["confidence"] = 0.80

    return data

def _scaffold_empty_profile(name: Optional[str], contact: Dict[str, Any]) -> Dict[str, Any]:
    """Helper to return a minimum valid profile structure when LLM fails or is unavailable."""
    return {
        "full_name": name,
        "headline": None,
        "summary": None,
        "emails": contact["emails"],
        "phones": contact["phones"],
        "locations": [],
        "links": contact["links"],
        "skills": [],
        "education": [],
        "experience": [],
        "projects": [],
        "certifications": [],
        "languages": [],
        "awards": [],
        "publications": []
    }
