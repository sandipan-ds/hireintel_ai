# This module is responsible for normalizing raw section texts into the structured JSON schema.
#
# It uses robust regexes for contact fields (name, email, phone, links)
# and calls the configured LLM (Ollama or Opencode) for structural mapping of:
# education, experience, skills, certifications, and languages.

import re
import json
import logging
from typing import Dict, List, Any, Optional

from src.services.llm_caller import _ENV
from src.resume_parsing.parser import EMAIL_REGEX, PHONE_REGEX, _looks_like_name

logger = logging.getLogger(__name__)

# Link regexes
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

def call_llm_normalizer(prompt: str) -> str:
    """Make LLM request using custom system prompt designed for structured JSON extraction."""
    api_key = _ENV.get("OPENCODE_API_KEY")
    base_url = _ENV.get("base_url", "https://opencode.ai/zen/v1")
    model = _ENV.get("model", "deepseek-v4-flash-free")
    
    if not api_key:
        logger.warning("No OPENCODE_API_KEY found, cannot call LLM normalizer.")
        return ""
        
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert resume parser. Extract raw resume sections "
                        "into valid JSON matching the schema. Return ONLY valid raw JSON. "
                        "Do not wrap in markdown block (do NOT use ```json or ```). "
                        "No explanation, no comment lines, no conversational text."
                    )
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            timeout=45.0
        )
        if not response.choices:
            return ""
        return (response.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.error("LLM normalizer call failed: %s", exc)
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
