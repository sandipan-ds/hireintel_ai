# This module normalizes raw resume section text into the structured JSON schema.
#
# It uses robust regexes for contact fields (name, email, phone, links)
# and calls an LLM with multi-provider key rotation for structural mapping of:
# education, experience, skills, certifications, and languages.
#
# Provider rotation order (tried in sequence until one succeeds):
#   1. Ollama (local) — fastest if running, zero cost
#   2. OpenCode keys 1→2→3 (mimo-v2.5-free)
#   3. OpenRouter key (google/gemma-4-31b-it)
#   4. NVIDIA NIM keys (google/gemma-4-31b-it:free)
# If all fail, an empty scaffold is returned so the batch never crashes.

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
# Ollama health check
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

def _build_providers() -> List[Tuple[str, str, str]]:
    """
    Build the ordered list of (api_key, base_url, model) tuples to try.

    Priority:
      1. OpenRouter keys         (google/gemma-4-31b-it) — Primary
      2. OpenCode keys 1, 2, 3   (minimax-m3 / cloud fallback)
      3. NVIDIA NIM keys         (google/gemma-4-31b-it:free)

    Returns:
        List of provider tuples ready to iterate.
    """
    providers: List[Tuple[str, str, str]] = []

    # 1. OpenRouter
    or_base = "https://openrouter.ai/api/v1"
    or_model = _get_first("MODEL", "google/gemma-4-31b-it")
    for key in _get_all("OPENROUTER_API_KEY_1"):
        providers.append((key, or_base, or_model))

    # 2. OpenCode (3 numbered keys, same base/model)
    oc_base = _get_first("base_url", "https://opencode.ai/zen/v1")
    oc_model = _get_first("model", "minimax-m3")
    for key in (_get_all("OPENCODE_API_KEY_1")
                + _get_all("OPENCODE_API_KEY_2")
                + _get_all("OPENCODE_API_KEY_3")):
        providers.append((key, oc_base, oc_model))

    # 3. NVIDIA NIM (3 keys all stored under same .env name)
    nim_base = "https://integrate.api.nvidia.com/v1"
    nim_model = _get_first("mode", "google/gemma-4-31b-it:free")
    for key in _get_all("NVIDIA_NIM_API_KEY_1"):
        providers.append((key, nim_base, nim_model))

    if not providers:
        logger.error("No LLM providers found in .env — normalization will produce empty scaffolds.")
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
    "You are an expert resume parser. Extract raw resume sections into valid JSON "
    "matching the schema exactly. Return ONLY valid raw JSON — no markdown fences "
    "(no ```json or ```), no explanation, no comments, no extra text."
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
                max_retries=0,   # rotate manually, no exponential backoff
                timeout=30.0,    # fast-fail per provider
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

    prompt = f"""
Analyze the following resume sections and extract structured information into the requested JSON schema.
Ensure dates are in "YYYY-MM" format (or "YYYY" or null if not specified).
Set is_current = true/false for experience entries.
Ensure no text or markdown wrapper is returned; return ONLY valid raw JSON matching the schema.

---
{sections_prompt_input}
---

JSON SCHEMA TO RETURN:
{{
  "full_name": "{name or 'null'}",
  "headline": "headline/job title summary or null",
  "summary": "professional summary or null",
  "skills": [
    {{
      "name_raw": "raw skill name as listed",
      "name_canonical": "canonical standardized skill name (e.g. Node Js -> Node.js, postgres -> PostgreSQL)",
      "category": "e.g. frontend, backend, database, mobile, devops, cloud, methodology, or other",
      "source_type": "explicit",
      "last_used": "YYYY-MM or null",
      "months_of_evidence": 0
    }}
  ],
  "education": [
    {{
      "degree": "Degree name, e.g. B.Tech, M.Tech, MBA, BS, MS, PhD",
      "specialization": "Specialization, e.g. Computer Science",
      "institution_raw": "Raw institution name from resume",
      "institution_normalized": "Cleaned institution name",
      "start_date": "YYYY-MM or null",
      "end_date": "YYYY-MM or null",
      "grade": "GPA, CGPA or percentage or null",
      "completed": true
    }}
  ],
  "experience": [
    {{
      "job_title": "Job title",
      "company": "Company name",
      "employment_type": "full_time, contract, part_time, internship or null",
      "start_date": "YYYY-MM or null",
      "end_date": "YYYY-MM or null",
      "is_current": false,
      "location": "Location or null",
      "responsibilities": ["bullet 1", "bullet 2"],
      "tools_and_skills": ["skill1", "skill2"]
    }}
  ],
  "projects": [
    {{
      "name": "Project name",
      "organization": "Organization name or null",
      "role": "Role in project or null",
      "start_date": "YYYY-MM or null",
      "end_date": "YYYY-MM or null",
      "description": ["bullet 1"],
      "skills_used": ["skill1"]
    }}
  ],
  "certifications": [
    {{
      "name": "Certification name",
      "issuer": "Issuer or null",
      "issue_date": "YYYY-MM or null",
      "expiry_date": "YYYY-MM or null",
      "credential_id": "Credential ID or null"
    }}
  ],
  "languages": [
    {{
      "name": "Language name",
      "proficiency": "native, fluent, professional, conversational, basic or null"
    }}
  ]
}}
"""

    response = call_llm_normalizer(prompt)
    
    # Clean response (sometimes LLM adds markdown code block backticks despite system instructions)
    response_clean = response.strip()
    if response_clean.startswith("```json"):
        response_clean = response_clean[7:]
    elif response_clean.startswith("```"):
        response_clean = response_clean[3:]
    if response_clean.endswith("```"):
        response_clean = response_clean[:-3]
    response_clean = response_clean.strip()

    try:
        data = json.loads(response_clean)
    except Exception as exc:
        logger.error("Failed to parse LLM response as JSON: %s\nResponse: %s", exc, response_clean)
        return _scaffold_empty_profile(name, contact)

    # Overwrite regex-extracted contact fields for absolute safety and accuracy
    data["emails"] = contact["emails"]
    data["phones"] = contact["phones"]
    data["links"] = contact["links"]
    if not data.get("full_name") or data["full_name"] == "null":
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
