#!/usr/bin/env python3
"""Gap-fill re-extraction script for quality audit flagged candidates.

This script identifies candidates flagged in `run_reports/review_queue.md`
(or scans all candidates with --all-gaps), renders their original PDFs to base64 JPEGs
via pypdfium2, calls multimodal LLM models from `.env.audit` (Google, NVIDIA NIM, OpenRouter),
extracts the missing fields, and merges them into the candidate's processed JSON.

Usage:
    python scripts/gap_fill_extraction.py                  # Process flagged candidates
    python scripts/gap_fill_extraction.py --resume         # Resume interrupted run
    python scripts/gap_fill_extraction.py --candidate WebDesigning_CAND_0016
    python scripts/gap_fill_extraction.py --all-gaps       # Scan all 721 candidates for gaps
    python scripts/gap_fill_extraction.py --dry-run        # Preview candidates and gaps
"""

import argparse
import base64
import collections
import io
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add project root to sys.path so src imports resolve correctly
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Import pipeline calculation helpers to recalculate features after patching
try:
    from src.resume_parsing.extraction.pipeline import calculate_experience_metrics, determine_highest_degree
    from src.resume_parsing.extraction.schema_validator import validate_resume_json
    from src.resume_parsing.extraction.llm_normalizer import extract_contact_info, extract_name_from_raw_text
    _PIPELINE_MODULES_AVAILABLE = True
except ImportError as err:
    logger = logging.getLogger("gap_fill_extraction")
    logger.error("Import failed for pipeline modules: %s", err)
    _PIPELINE_MODULES_AVAILABLE = False
    # Fallbacks to avoid NameErrors
    extract_contact_info = lambda text: {"emails": [], "phones": [], "links": {"linkedin": None, "github": None, "portfolio": None, "other": []}}
    extract_name_from_raw_text = lambda text: None

try:
    import pypdfium2 as pdfium
    _PYPDFIUM_AVAILABLE = True
except ImportError:
    _PYPDFIUM_AVAILABLE = False

# Setup logging
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("gap_fill_extraction")

ROOT = Path(__file__).resolve().parent.parent
ENV_AUDIT_PATH = ROOT / ".env.audit"
REGISTRY_PATH = ROOT / "data/candidate_registry.json"
PROCESSED_DIR = ROOT / "data/processed"
RUN_REPORTS_DIR = ROOT / "run_reports"
REVIEW_QUEUE_FILE = RUN_REPORTS_DIR / "review_queue.md"
PROGRESS_FILE = RUN_REPORTS_DIR / "gap_fill_progress.json"

# ---------------------------------------------------------------------------
# Load and Parse .env.audit
# ---------------------------------------------------------------------------

def load_env_audit() -> Dict[str, List[str]]:
    """Load .env.audit key-value pairs, handling duplicate keys and hyphen-assigns."""
    result: Dict[str, List[str]] = {}
    if not ENV_AUDIT_PATH.exists():
        logger.warning(".env.audit file not found at %s", ENV_AUDIT_PATH)
        return result
        
    for raw_line in ENV_AUDIT_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # OpenRouter uses base_url-"https..." typo, handle it along with standard =
        if "=" in line:
            k, _, v = line.partition("=")
        elif "-" in line:
            k, _, v = line.partition("-")
        else:
            continue
            
        key = k.strip()
        val = v.strip().strip('"').strip("'")
        if val:
            result.setdefault(key, []).append(val)
    return result

def build_providers(env_data: Dict[str, List[str]]) -> List[Tuple[str, str, str]]:
    """Build the ordered list of (api_key, base_url, model) tuples.
    
    Order:
      1. Google AI Studio (gemini-2.5-flash)
      2. NVIDIA NIM (minimaxai/minimax-m3)
      3. OpenRouter (google/gemma-4-31b-it)
    """
    providers = []
    
    # 1. Google
    g_model = "gemini-2.5-flash"
    g_base = "https://generativelanguage.googleapis.com/v1beta/openai/"
    g_keys = env_data.get("GOOGLE_API_KEY_1", []) + env_data.get("GOOGLE_API_KEY_2", [])
    for key in g_keys:
        providers.append((key, g_base, g_model))
        
    # 2. NVIDIA NIM
    nv_model = "minimaxai/minimax-m3"
    nv_base = "https://integrate.api.nvidia.com/v1"
    nv_keys = env_data.get("NVIDIA_NIM_API_KEY_1", [])
    for key in nv_keys:
        providers.append((key, nv_base, nv_model))
        
    # 3. OpenRouter
    or_model = "openrouter/free"
    or_base = "https://openrouter.ai/api/v1"
    or_keys = env_data.get("OPENROUTER_API_KEY_1", []) + env_data.get("OPENROUTER_API_KEY_2", []) + env_data.get("OPENROUTER_API_KEY_3", [])
    for key in or_keys:
        providers.append((key, or_base, or_model))
        
    return providers

# ---------------------------------------------------------------------------
# PDF rendering using pypdfium2
# ---------------------------------------------------------------------------

def pdf_to_base64_images(pdf_path: Path) -> List[str]:
    """Convert each page of PDF to base64 JPEG format for vision API."""
    if not _PYPDFIUM_AVAILABLE:
        logger.warning("pypdfium2 not installed; cannot render pages to base64 image")
        return []
    
    images_b64 = []
    try:
        pdf = pdfium.PdfDocument(str(pdf_path))
        # Limit to first 3 pages to avoid payload blowing up API limits
        num_pages = min(len(pdf), 3)
        for i in range(num_pages):
            page = pdf[i]
            # scale=1.5 renders at ~1000px height, high enough for text readability but compact
            bitmap = page.render(scale=1.5)
            pil_img = bitmap.to_pil()
            
            buf = io.BytesIO()
            pil_img.save(buf, format="JPEG")
            b64_str = base64.b64encode(buf.getvalue()).decode("utf-8")
            images_b64.append(b64_str)
        pdf.close()
    except Exception as exc:
        logger.error("Failed to render PDF %s: %s", pdf_path, exc)
    return images_b64

# ---------------------------------------------------------------------------
# Registry and Processed File Location
# ---------------------------------------------------------------------------

def get_pdf_path(candidate_id: str) -> Optional[Path]:
    """Lookup original PDF path from candidate_registry.json."""
    if not REGISTRY_PATH.exists():
        return None
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        cands = data.get("candidates", {})
        if candidate_id in cands:
            path_str = cands[candidate_id].get("source_path")
            if path_str:
                return Path(path_str)
    except Exception as exc:
        logger.error("Failed to read registry: %s", exc)
    return None

def find_processed_json_path(candidate_id: str) -> Optional[Path]:
    """Locate the data/processed/<role>/<candidate_id>.json file."""
    role = candidate_id.rsplit("_CAND_", 1)[0]
    expected_path = PROCESSED_DIR / role / f"{candidate_id}.json"
    if expected_path.exists():
        return expected_path
    
    # Fallback: scan subdirectories
    for d in PROCESSED_DIR.iterdir():
        if d.is_dir():
            path = d / f"{candidate_id}.json"
            if path.exists():
                return path
    return None

# ---------------------------------------------------------------------------
# Progress Ledger Management
# ---------------------------------------------------------------------------

def load_progress() -> Dict[str, List[str]]:
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"completed": [], "failed": [], "skipped_no_gaps": []}

def save_progress(progress: Dict[str, List[str]]) -> None:
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PROGRESS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(progress, indent=2), encoding="utf-8")
    tmp.replace(PROGRESS_FILE)

# ---------------------------------------------------------------------------
# Candidate lists discovery
# ---------------------------------------------------------------------------

def get_flagged_candidates(threshold: Optional[float] = None) -> List[str]:
    """Parse review_queue.md or scan audit files under a threshold to identify candidate IDs."""
    cands = []
    
    if threshold is not None:
        audit_dir = ROOT / "data/audit"
        if not audit_dir.exists():
            logger.warning("Audit directory %s does not exist. Cannot filter by threshold.", audit_dir)
            return cands
            
        logger.info("Scanning data/audit/ for overall quality score < %.2f", threshold)
        for audit_file in sorted(audit_dir.rglob("*_audit.json")):
            try:
                data = json.loads(audit_file.read_text(encoding="utf-8"))
                score = data.get("quality_scores", {}).get("overall_extraction_quality")
                if score is not None and score < threshold:
                    cid = data.get("candidate_id")
                    if cid and cid not in cands:
                        cands.append(cid)
            except Exception as exc:
                logger.error("Failed to parse audit file %s: %s", audit_file, exc)
        return cands

    if not REVIEW_QUEUE_FILE.exists():
        return cands
        
    content = REVIEW_QUEUE_FILE.read_text(encoding="utf-8")
    # Matches: WebDesigning_CAND_0016
    for m in re.finditer(r"([A-Za-z0-9]+_CAND_\d+)", content):
        cand_id = m.group(1)
        if cand_id not in cands:
            cands.append(cand_id)
    return cands

def get_candidates_with_gaps(target_ids: Optional[List[str]] = None) -> List[Tuple[str, List[str]]]:
    """Find candidates that have actual missing fields in their processed JSON.
    
    Returns:
        List of tuples: (candidate_id, list_of_gap_fields)
    """
    candidates_to_process = []
    
    # If candidate IDs are specified, only check those
    if target_ids is not None:
        ids_to_check = target_ids
    else:
        # Scan all processed files
        ids_to_check = []
        if PROCESSED_DIR.exists():
            for d in PROCESSED_DIR.iterdir():
                if d.is_dir():
                    for f in d.glob("*.json"):
                        if not f.name.endswith(("_intelligence_report.json", "_structured_profile.json")):
                            ids_to_check.append(f.stem)
                            
    for cid in sorted(ids_to_check):
        p = find_processed_json_path(cid)
        if not p:
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            cp = d.get("candidate_profile", {})
            if not cp:
                candidates_to_process.append((cid, ["skills", "experience", "education", "certifications"]))
                continue
                
            gaps = []
            for field in ["skills", "experience", "education", "certifications"]:
                val = cp.get(field)
                if not val:  # None or empty list
                    gaps.append(field)
            if gaps:
                candidates_to_process.append((cid, gaps))
        except Exception as exc:
            logger.error("Failed to read processed JSON for %s: %s", cid, exc)
            
    return candidates_to_process

# ---------------------------------------------------------------------------
# Multimodal LLM Extraction logic
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are an expert resume parser. Extract raw resume text and images into valid JSON matching the schema exactly. "
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

SCHEMA_BLOCKS = {
    "skills": """  "skills": [
    {
      "name_raw": "exact skill text from resume",
      "name_canonical": "standardized name (Python, Node.js, PostgreSQL, AWS, etc.)",
      "category": "one of: frontend / backend / database / mobile / devops / cloud / methodology / data_science / security / other",
      "source_type": "explicit",
      "last_used": "YYYY-MM or null",
      "months_of_evidence": 0
    }
  ]""",
    "education": """  "education": [
    {
      "degree": "e.g. B.Tech / M.Tech / MBA / BS / MS / PhD / Bachelor's / Master's",
      "specialization": "e.g. Computer Science / Business Administration",
      "institution_raw": "exact institution name from resume",
      "institution_normalized": "cleaned full institution name",
      "start_date": "YYYY-MM or null",
      "end_date": "YYYY-MM or null",
      "grade": "GPA, CGPA or percentage or null",
      "completed": true
    }
  ]""",
    "experience": """  "experience": [
    {
      "job_title": "Exact job title",
      "company": "Company name or null",
      "employment_type": "full_time / contract / part_time / internship or null",
      "start_date": "YYYY-MM or null",
      "end_date": "YYYY-MM or null (null if current)",
      "is_current": false,
      "location": "City, State/Country or null",
      "responsibilities": ["Individual bullet point 1", "Individual bullet point 2", "..."],
      "tools_and_skills": ["Python", "Django", "PostgreSQL"]
    }
  ]""",
    "certifications": """  "certifications": [
    {
      "name": "Certification name",
      "issuer": "Issuer organization or null",
      "issue_date": "YYYY-MM or null",
      "expiry_date": "YYYY-MM or null",
      "credential_id": "ID string or null"
    }
  ]"""
}

def build_prompt(raw_text: str, name: Optional[str], gaps: List[str]) -> str:
    schema_parts = []
    for g in gaps:
        if g in SCHEMA_BLOCKS:
            schema_parts.append(SCHEMA_BLOCKS[g])
            
    # Fallback to skills if gaps is empty or unknown
    if not schema_parts:
        schema_parts.append(SCHEMA_BLOCKS["skills"])
        
    schema_str = "{\n" + ",\n".join(schema_parts) + "\n}"

    return f"""You are a targeted resume parser. Your job is to extract ONLY the specific missing sections of the candidate's profile.

MISSING SECTIONS TO EXTRACT:
{', '.join(gaps)}

STRICT RULES:
1. Return ONLY a valid raw JSON object. Your response MUST start directly with '{{' and end with '}}'. Do NOT write any introduction, explanation, preambles, or markdown fences (no ```json).
2. Follow all standard formatting rules (Dates in YYYY-MM, skills/responsibilities split into list items).
3. Do NOT include thoughts, comments, or extra conversational text.
4. If no information is present in the resume for a missing section, return an empty list `[]` for that key.

RESUME TEXT:
---
{raw_text}
---

Return ONLY this JSON structure filled with data from the resume (start directly with '{{'):
{schema_str}
"""

def call_multimodal_llm(providers: List[Tuple[str, str, str]], prompt_text: str, images_b64: List[str]) -> str:
    """Try each provider in order using OpenAI-compatible client, sending vision payload if images exist."""
    from openai import OpenAI
    
    total = len(providers)
    if total == 0:
        logger.error("No active provider credentials found in provider list.")
        return ""
        
    for idx, (api_key, base_url, model) in enumerate(providers):
        host = base_url.split("/")[2] if "/" in base_url else base_url
        label = f"[{idx+1}/{total}] {host} ({model})"
        
        # We try with images first if available, then fall back to text-only if API fails with 402 (payment) or token limits
        current_images = images_b64.copy()
        
        while True:
            logger.info("Attempting LLM call via %s (multimodal=%s)...", label, bool(current_images))
            
            # Build user message content block (handles multimodal input)
            content_list: List[Dict[str, Any]] = [
                {"type": "text", "text": prompt_text}
            ]
            
            # Attach rendered PDF pages as image inputs
            for img in current_images:
                content_list.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img}"}
                })
                
            try:
                client = OpenAI(
                    api_key=api_key,
                    base_url=base_url,
                    max_retries=0
                )
                
                text = ""
                # Attempt to use JSON mode to force clean JSON output
                try:
                    logger.info("Calling completions with response_format={'type': 'json_object'}...")
                    response = client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": _SYSTEM_PROMPT},
                            {"role": "user", "content": content_list}
                        ],
                        temperature=0.0,
                        max_tokens=2048,
                        timeout=120.0,
                        response_format={"type": "json_object"}
                    )
                    if response.choices and response.choices[0].message.content:
                        text = response.choices[0].message.content.strip()
                except Exception as json_err:
                    logger.warning("JSON mode not supported by provider: %s", json_err)
                
                # If JSON mode failed or returned empty content, fall back to standard call
                if not text:
                    logger.info("JSON mode returned empty or failed. Falling back to standard call...")
                    response = client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": _SYSTEM_PROMPT},
                            {"role": "user", "content": content_list}
                        ],
                        temperature=0.0,
                        max_tokens=2048,
                        timeout=120.0
                    )
                    if response.choices and response.choices[0].message.content:
                        text = response.choices[0].message.content.strip()
                        
                if text:
                    logger.info("%s succeeded!", label)
                    return text
                logger.warning("%s returned empty choice or content.", label)
                break
            except Exception as exc:
                exc_str = str(exc)
                # Check for 402/credits/payment errors
                is_credit_issue = "402" in exc_str or "credits" in exc_str.lower() or "payment" in exc_str.lower()
                
                if current_images and (is_credit_issue or "token" in exc_str.lower()):
                    logger.warning(
                        "%s failed with credit/token limit: %s. Retrying in text-only mode to conserve credits...",
                        label, exc_str
                    )
                    current_images = []
                    continue
                else:
                    logger.warning("%s failed: %s", label, exc)
                    break
            
    logger.error("All %d LLM providers failed to generate normalizations.", total)
    return ""

def clean_llm_json(response: str) -> str:
    """Helper to strip thought blocks and markdown wrappers from LLM output."""
    response_clean = response.strip()
    
    # Strip <thought>...</thought> blocks if present (common in reasoning models)
    if "</thought>" in response_clean:
        idx = response_clean.find("</thought>")
        response_clean = response_clean[idx + len("</thought>"):].strip()
        
    # Extract JSON object between first '{' and last '}'
    start_idx = response_clean.find("{")
    end_idx = response_clean.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        response_clean = response_clean[start_idx:end_idx + 1].strip()
            
    return response_clean

# ---------------------------------------------------------------------------
# Merging / Patching logic
# ---------------------------------------------------------------------------

def patch_candidate_json(existing_json_path: Path, extracted_profile: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Merge only missing fields into existing processed JSON and write to disk."""
    if not existing_json_path.exists():
        logger.error("Target JSON file not found for patch: %s", existing_json_path)
        return False, []
        
    try:
        existing = json.loads(existing_json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Failed to read existing JSON: %s", exc)
        return False, []
        
    cp_exist = existing.setdefault("candidate_profile", {})
    cp_gap = extracted_profile.get("candidate_profile", {}) or extracted_profile
    
    patched_fields = []
    
    # 1. Patch scalar fields if they are missing
    for field in ["full_name", "headline", "summary"]:
        val_exist = cp_exist.get(field)
        val_gap = cp_gap.get(field)
        if val_exist is None or str(val_exist).strip().lower() in ("", "none", "null", "n/a"):
            if val_gap and str(val_gap).strip().lower() not in ("", "none", "null", "n/a"):
                cp_exist[field] = val_gap
                patched_fields.append(field)
                
    # 2. Patch list fields if they are empty
    for list_field in ["skills", "education", "experience", "projects", "certifications", "languages"]:
        if not cp_exist.get(list_field) and cp_gap.get(list_field):
            cp_exist[list_field] = cp_gap[list_field]
            patched_fields.append(list_field)
            
    # 3. Patch link fields inside links dict
    existing_links = cp_exist.setdefault("links", {})
    gap_links = cp_gap.get("links", {}) or {}
    if isinstance(existing_links, dict) and isinstance(gap_links, dict):
        for k in ["linkedin", "github", "portfolio"]:
            if not existing_links.get(k) and gap_links.get(k):
                existing_links[k] = gap_links[k]
                patched_fields.append(f"links.{k}")
        if not existing_links.get("other") and gap_links.get("other"):
            existing_links["other"] = gap_links["other"]
            patched_fields.append("links.other")
            
    # 4. Patch contact phones if empty but found in regex
    if not cp_exist.get("phones") and cp_exist.get("summary"):
        # Run standard regex helper on the summary or raw text to double check phone presence
        raw_text = existing.get("raw", {}).get("raw_text", "")
        contact_info = extract_contact_info(raw_text)
        if contact_info.get("phones"):
            cp_exist["phones"] = contact_info["phones"]
            patched_fields.append("phones")
            
    if not patched_fields:
        return False, []
        
    # 5. Overwrite/add default field confidences for the patched items
    for skill in cp_exist.get("skills", []):
        skill.setdefault("confidence", 0.90)
    for edu in cp_exist.get("education", []):
        edu.setdefault("confidence", 0.90)
    for exp in cp_exist.get("experience", []):
        exp.setdefault("confidence", 0.92)
    for cert in cp_exist.get("certifications", []):
        cert.setdefault("confidence", 0.93)
        
    # 6. Recalculate experience metrics and highest degree
    if _PIPELINE_MODULES_AVAILABLE:
        total_months, latest_title, latest_company = calculate_experience_metrics(cp_exist.get("experience", []))
        highest_degree = determine_highest_degree(cp_exist.get("education", []))
        
        existing["normalized_features"] = {
            "total_experience_months": total_months,
            "latest_job_title": latest_title,
            "latest_company": latest_company,
            "highest_degree": highest_degree,
            "skill_canonical_map": {
                skill.get("name_raw", "").lower(): skill.get("name_canonical")
                for skill in cp_exist.get("skills", [])
                if skill.get("name_raw")
            },
            "location_normalized": (cp_exist.get("locations") or [{}])[0].get("normalized") if cp_exist.get("locations") else None,
            "work_authorization": existing.get("normalized_features", {}).get("work_authorization")
        }
        
        # Validate schemas and populate audit stats
        val_res = validate_resume_json(existing)
        existing["validation"] = {
            "status": "passed" if val_res.is_valid else "review_required",
            "warnings": val_res.warnings,
            "errors": val_res.missing_fields
        }
        existing["confidence"] = {
            "document_confidence": val_res.confidence_score,
            "field_confidence": {
                "candidate_profile.full_name": 0.98 if cp_exist.get("full_name") else 0.0,
                "candidate_profile.skills": 0.90 if cp_exist.get("skills") else 0.0,
                "candidate_profile.education": 0.90 if cp_exist.get("education") else 0.0,
                "candidate_profile.experience": 0.92 if cp_exist.get("experience") else 0.0
            }
        }
        
    try:
        existing_json_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        return True, patched_fields
    except Exception as exc:
        logger.error("Failed to write patched JSON back to disk: %s", exc)
        return False, []

# ---------------------------------------------------------------------------
# Main CLI Orchestration
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Multimodal Gap-Fill Re-Extraction Script")
    parser.add_argument("--resume", action="store_true", help="Resume interrupted execution.")
    parser.add_argument("--candidate", default=None, help="Process a single candidate by ID.")
    parser.add_argument("--all-gaps", action="store_true", help="Scan all parsed files for gaps instead of review queue.")
    parser.add_argument("--threshold", type=float, default=None, help="Process candidates with quality scores below this threshold.")
    parser.add_argument("--dry-run", action="store_true", help="Preview gaps and paths. No LLM calls or writes.")
    args = parser.parse_args()
    
    # 1. Determine targets
    if args.candidate:
        logger.info("Target: candidate '%s'", args.candidate)
        candidates_with_gaps = get_candidates_with_gaps([args.candidate])
    elif args.all_gaps:
        logger.info("Target: all candidates in data/processed/ with empty fields")
        candidates_with_gaps = get_candidates_with_gaps()
    else:
        if args.threshold is not None:
            logger.info("Target: candidates with audit quality score < %.2f", args.threshold)
        else:
            logger.info("Target: flagged candidates from review_queue.md")
        flagged_ids = get_flagged_candidates(args.threshold)
        logger.info("Found %d matching flagged candidates", len(flagged_ids))
        candidates_with_gaps = get_candidates_with_gaps(flagged_ids)
        
    if not candidates_with_gaps:
        logger.info("No candidates with gaps found. Done!")
        sys.exit(0)
        
    logger.info("Found %d candidates with gaps requiring re-extraction", len(candidates_with_gaps))
    
    # 2. Dry run preview
    if args.dry_run:
        print("\n--- Dry Run Preview ---")
        for cid, gaps in candidates_with_gaps:
            pdf_path = get_pdf_path(cid)
            json_path = find_processed_json_path(cid)
            print(f"- {cid:35s} | Gaps: {str(gaps):50s} | PDF: {str(pdf_path.name if pdf_path else 'missing')}")
        print("\nDry run completed. No files modified.")
        sys.exit(0)
        
    # 3. Load provider configuration
    env_data = load_env_audit()
    providers = build_providers(env_data)
    # Filter list to only keep working keys (NVIDIA NIM and active OpenRouter key)
    working_providers = []
    for key, base, model in providers:
        if "nvidia" in base:
            working_providers.append((key, base, model))
        elif "openrouter" in base and key == env_data.get("OPENROUTER_API_KEY_1", [""])[0]:
            working_providers.append((key, base, model))
            
    # Fallback: if we didn't match the known working key filter, keep all for normal rotation
    if not working_providers:
        working_providers = providers
        
    logger.info("Configured %d active LLM provider endpoints", len(working_providers))
    if not working_providers:
        logger.error("No LLM provider endpoints available. Check .env.audit.")
        sys.exit(1)
        
    # 4. Load progress ledger
    progress = load_progress() if args.resume else {"completed": [], "failed": [], "skipped_no_gaps": []}
    
    # 5. Execution loop
    for idx, (cid, gaps) in enumerate(candidates_with_gaps):
        logger.info("[%d/%d] Processing %s (Gaps: %s)...", idx + 1, len(candidates_with_gaps), cid, gaps)
        
        # Skip if resume and already finished/no gaps
        if args.resume and (cid in progress["completed"] or cid in progress.get("skipped_no_gaps", [])):
            logger.info("Skipping %s (already completed/no gaps)", cid)
            continue
            
        json_path = find_processed_json_path(cid)
        pdf_path = get_pdf_path(cid)
        
        if not json_path:
            logger.error("Processed JSON file not found for %s — skipping", cid)
            progress["failed"].append(cid)
            save_progress(progress)
            continue
            
        if not pdf_path or not pdf_path.exists():
            logger.error("Original PDF path not found or missing on disk for %s — skipping", cid)
            progress["failed"].append(cid)
            save_progress(progress)
            continue
            
        # Get raw text from the processed JSON
        try:
            stored_data = json.loads(json_path.read_text(encoding="utf-8"))
            raw_text = stored_data.get("raw", {}).get("raw_text", "")
            name = stored_data.get("candidate_profile", {}).get("full_name") or extract_name_from_raw_text(raw_text)
        except Exception as exc:
            logger.error("Failed to load processed JSON raw text: %s", exc)
            progress["failed"].append(cid)
            save_progress(progress)
            continue
            
        # Render PDF pages to base64 images for scanned/OCR-failed resumes (raw_text < 3000 chars or name starts with 'Image_')
        is_scanned = len(raw_text) < 3000 or (pdf_path and pdf_path.name.startswith("Image_"))
        if is_scanned:
            logger.info("Scanned/OCR resume detected (raw_text size=%d, name=%s). Rendering PDF pages to base64 JPEGs...", len(raw_text), pdf_path.name if pdf_path else "")
            images_b64 = pdf_to_base64_images(pdf_path)
            if not images_b64:
                logger.warning("No pages rendered for PDF. Attempting text-only re-extraction.")
        else:
            logger.info("Native text resume detected (raw_text size=%d). Using text-only re-extraction.", len(raw_text))
            images_b64 = []
            
        # Process gaps one-by-one to avoid exceeding token limits and improve JSON compliance
        any_success = False
        all_failed = True
        patched_fields_accumulated = []
        
        for gap in gaps:
            logger.info("Processing gap '%s'...", gap)
            prompt_text = build_prompt(raw_text, name, [gap])
            llm_response = call_multimodal_llm(working_providers, prompt_text, images_b64)
            
            if not llm_response:
                logger.warning("Failed to retrieve LLM response for gap '%s'", gap)
                continue
                
            cleaned_json = clean_llm_json(llm_response)
            try:
                extracted_profile = json.loads(cleaned_json)
            except Exception as exc:
                logger.warning("Failed to parse JSON response for gap '%s': %s", gap, exc)
                continue
                
            all_failed = False
            success, patched = patch_candidate_json(json_path, extracted_profile)
            if success:
                logger.info("Successfully patched gap '%s'! Fields filled: %s", gap, patched)
                any_success = True
                patched_fields_accumulated.extend(patched)
            else:
                logger.info("No data extracted for gap '%s'", gap)
                
        if any_success:
            logger.info("Candidate %s patch completed! Fields filled: %s", cid, patched_fields_accumulated)
            if cid in progress["failed"]:
                progress["failed"].remove(cid)
            progress["completed"].append(cid)
        elif all_failed:
            logger.error("All gap extractions failed for candidate %s", cid)
            if cid not in progress["failed"]:
                progress["failed"].append(cid)
        else:
            logger.info("No new data extracted for candidate %s (all gaps returned empty)", cid)
            if cid in progress["failed"]:
                progress["failed"].remove(cid)
            if cid not in progress.get("skipped_no_gaps", []):
                progress.setdefault("skipped_no_gaps", []).append(cid)
                
        save_progress(progress)
        
    logger.info("Gap-fill re-extraction run completed!")
    print("\n--- Summary ---")
    print(f"Completed patches: {len(progress['completed'])}")
    print(f"Failed candidates: {len(progress['failed'])}")
    print(f"Skipped (no gaps filled): {len(progress['skipped_no_gaps'])}")
    
    if progress["completed"]:
        print("\nPatched candidates modified on disk. To complete indexing and scoring, run:")
        print("  1. python -m src.rag.build_index")
        print("  2. python scripts/score_batch_composed.py --resume")
        print("  3. python scripts/generate_run_report.py")

if __name__ == "__main__":
    main()
