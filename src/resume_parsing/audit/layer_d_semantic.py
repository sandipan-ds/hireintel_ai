# This module implements Layer D: Semantic Missing-Information Audit.
#
# It uses an LLM to compare the raw resume text against a summary of the
# extracted JSON. This allows catching semantic omissions (e.g. projects,
# certifications, or experience entries present in the resume text but completely
# omitted in the JSON structure) that deterministic heuristics might miss.
#
# Cost control: To avoid unnecessary API costs, the LLM is only called if prior
# deterministic checks (Layers A-C) have flagged warnings or errors.

"""Layer D: Semantic Missing-Information Audit (DEC-036)."""

import json
import logging
from typing import Dict, Any, List, Tuple, Optional
from openai import OpenAI

from src.resume_parsing.audit.models import AuditCheck, MissingCandidate
from src.resume_parsing.extraction.llm_normalizer import _build_providers

logger = logging.getLogger(__name__)

# The system prompt tells the LLM to behave like a strict QA auditor
# and output raw JSON ONLY.
AUDITOR_SYSTEM_PROMPT = (
    "You are a strict QA auditor for a candidate resume parsing pipeline. "
    "Your job is to compare the raw resume text with the summary of extracted data, "
    "and identify any explicit sections, roles, certifications, projects, or contact details "
    "that are present in the raw text but completely missing or underrepresented in the extracted JSON. "
    "STRICT RULES: "
    "(1) Do NOT invent or infer data. Only report items that are explicitly stated in the raw text. "
    "(2) Output ONLY a raw JSON array — no markdown fences (no ```json), no explanations, no conversational text. "
    "(3) If everything is correctly extracted, return an empty array []."
)

def run(
    resume_json: Dict[str, Any],
    skip_if_clean: bool = True,
    prior_checks: Optional[List[AuditCheck]] = None,
) -> Tuple[List[AuditCheck], List[MissingCandidate], float]:
    """
    Compare raw resume text vs JSON summary to detect semantic omissions using an LLM.

    Args:
        resume_json: Extracted candidate JSON.
        skip_if_clean: If True, skip LLM call when no prior warnings/errors exist.
        prior_checks: The list of checks from prior layers (A, B, C).

    Returns:
        A tuple of (audit_checks, missing_candidates, semantic_score).
    """
    checks: List[AuditCheck] = []
    missing_candidates: List[MissingCandidate] = []

    # 1. Cost Control Check
    if skip_if_clean and prior_checks is not None:
        has_warnings = any(c.severity in ("warning", "error", "critical") for c in prior_checks)
        if not has_warnings:
            logger.info("Semantic audit: prior layers are clean. Skipping LLM call.")
            return checks, missing_candidates, 1.0

    raw = resume_json.get("raw", {})
    raw_text = raw.get("raw_text", "") or ""
    if not raw_text.strip():
        return checks, missing_candidates, 1.0

    profile = resume_json.get("candidate_profile", {})
    
    # Safely get counts of extracted fields
    exp = profile.get("experience") or {}
    exp_count = len(exp.get("entries") or []) if isinstance(exp, dict) else len(exp or [])
    
    edu = profile.get("education") or {}
    edu_count = len(edu.get("entries") or []) if isinstance(edu, dict) else len(edu or [])

    skills = profile.get("skills") or []
    certs = profile.get("certifications") or []
    projects = profile.get("projects") or []
    emails = profile.get("emails") or []

    # 2. Construct LLM Prompt
    json_summary = {
        "full_name": profile.get("full_name"),
        "emails": [e.get("value") if isinstance(e, dict) else e for e in emails],
        "skills_count": len(skills),
        "experience_count": exp_count,
        "education_count": edu_count,
        "certifications_count": len(certs),
        "projects_count": len(projects)
    }

    prompt = f"""Compare the raw resume text with the extracted JSON summary. List any missing items.

RAW RESUME TEXT:
---
{raw_text}
---

EXTRACTED JSON SUMMARY:
{json.dumps(json_summary, indent=2)}

Return a JSON array of missing candidates. If none, return [].
Format:
[
  {{
    "field_family": "experience|certifications|skills|education|contact|project",
    "resume_evidence": "exact text snippet from the raw resume that was missed",
    "reason": "description of why it is considered missed or underrepresented",
    "confidence": 0.0-1.0
  }}
]
"""

    # 3. LLM Call via multi-provider key rotation
    providers = _build_providers()
    total_providers = len(providers)
    response_text = ""

    for idx, (api_key, base_url, model) in enumerate(providers):
        host = base_url.split("/")[2] if "/" in base_url else base_url
        label = f"[{idx+1}/{total_providers}] {host} ({model})"
        try:
            client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0, timeout=60.0)
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": AUDITOR_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
            )
            if response.choices:
                val = (response.choices[0].message.content or "").strip()
                if val:
                    response_text = val
                    logger.info("Semantic audit: %s succeeded", label)
                    break
        except Exception as exc:
            logger.warning("Semantic audit: %s failed: %s — trying next", label, exc)
            continue

    if not response_text:
        logger.error("Semantic audit: all LLM providers failed — skipping semantic checks")
        return checks, missing_candidates, 1.0

    # 4. Clean up LLM response
    clean_resp = response_text.strip()
    if "</thought>" in clean_resp:
        idx = clean_resp.find("</thought>")
        clean_resp = clean_resp[idx + len("</thought>"):].strip()
    elif "<thought>" in clean_resp:
        idx = clean_resp.find("[")
        if idx != -1:
            clean_resp = clean_resp[idx:].strip()

    if clean_resp.startswith("```json"):
        clean_resp = clean_resp[7:]
    elif clean_resp.startswith("```"):
        clean_resp = clean_resp[3:]
    if clean_resp.endswith("```"):
        clean_resp = clean_resp[:-3]
    clean_resp = clean_resp.strip()

    # Parse LLM response
    try:
        results = json.loads(clean_resp)
        if not isinstance(results, list):
            logger.warning("Semantic audit response is not a JSON list: %r", clean_resp)
            results = []
    except Exception as e:
        logger.warning("Failed to parse semantic audit JSON response: %s. Response was: %r", e, clean_resp)
        results = []

    # Process findings
    for idx, item in enumerate(results):
        if not isinstance(item, dict):
            continue
        field_family = item.get("field_family", "other")
        evidence = item.get("resume_evidence", "")
        reason = item.get("reason", "")
        conf = item.get("confidence", 0.8)

        missing_candidates.append(MissingCandidate(
            field_family=field_family,
            resume_evidence=evidence,
            source_chunk_id="",
            reason=reason,
            confidence=float(conf)
        ))

        checks.append(AuditCheck(
            check_id=f"semantic_missing_{field_family}_{idx}",
            severity="warning" if conf < 0.9 else "error",
            layer="semantic",
            field=f"candidate_profile.{field_family}",
            issue=f"Semantic auditor detected missing {field_family} info: {reason}",
            expected="Extracted",
            actual="Missed"
        ))

    # Calculate score
    # Deduced by number of missing items, capped at 1.0 minimum score
    semantic_score = max(0.0, 1.0 - min(len(missing_candidates) * 0.1, 1.0))
    return checks, missing_candidates, semantic_score
