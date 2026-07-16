# This module orchestrates the Stage 3 PDF -> JSON routed extraction pipeline.
#
# It classifies the input file, routes it to the most accurate extraction backend
# (pypdfium2, Unstructured, or PaddleOCR+Surya), groups elements into canonical
# sections, normalizes fields via LLM, and validates the schema.
#
# DEC-037: Docling was removed and replaced with pypdfium2 (pypdf_parser).
# Docling pulled in torch + transformers as transitive dependencies, inflating
# the production image by ~2 GB. Since the LLM normalizer (Gemini) is
# multimodal it does not need layout-ML pre-processing; pypdfium2 extracts
# the text layer in correct reading order with zero ML dependencies.

import os
import re
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

from src.resume_parsing.extraction.file_classifier import classify_file, FileType
from src.resume_parsing.extraction.pypdf_parser import extract_with_pypdf
from src.resume_parsing.extraction.unstructured_parser import extract_with_unstructured
from src.resume_parsing.extraction.ocr_parser import extract_with_ocr
from src.resume_parsing.extraction.section_builder import build_sections
from src.resume_parsing.extraction.llm_normalizer import normalize_to_schema
from src.resume_parsing.extraction.schema_validator import validate_resume_json
from src.resume_parsing.extraction.element import ExtractedElement
from src.resume_parsing.parser import extract_text_from_path, _role_from_path, candidate_id_from_path
from src.resume_parsing.candidate_registry import CandidateRegistry, fresh_registry

logger = logging.getLogger(__name__)

def extract_resume(path: str | Path, registry: Optional[CandidateRegistry] = None) -> Dict[str, Any]:
    """
    Orchestrate the full routed PDF -> JSON extraction pipeline for a resume.

    Args:
        path: Path to the resume file (PDF, DOCX, text).
        registry: Candidate registry to allocate sequential, role-encoded ID.

    Returns:
        JSON structure matching 06_RESUME_EXTRACTION_JSON_SCHEMA.md.
    """
    path_obj = Path(path)
    if not path_obj.exists():
        raise FileNotFoundError(f"Resume file not found: {path}")

    # 1. Allocate candidate ID via registry
    role = _role_from_path(path_obj) or "Unknown"
    legacy_id = candidate_id_from_path(path_obj)
    if registry is None:
        registry = fresh_registry()
    candidate_id = registry.allocate_or_lookup(
        source_path=path_obj,
        role=role,
        legacy_hash_id=legacy_id,
    )

    # 2. Classify file type
    file_type = classify_file(path_obj)
    logger.info("Classified %s as %s", path_obj.name, file_type.value)

    # 3. Route and Extract Elements
    elements: Optional[List[ExtractedElement]] = None
    ocr_used = False

    bypass_layout = os.environ.get("BYPASS_LAYOUT_PARSERS", "false").lower() == "true"

    if file_type == FileType.NATIVE_PDF:
        if bypass_layout:
            logger.info(
                "Bypassing layout-aware parsing for %s due to BYPASS_LAYOUT_PARSERS=true",
                path_obj.name,
            )
            elements = None
        else:
            # Route A: pypdfium2 (primary, zero ML deps — DEC-037)
            logger.info("Routing %s to Route A: pypdfium2", path_obj.name)
            elements = extract_with_pypdf(path_obj)
            if not elements:
                logger.warning(
                    "pypdf parser failed or returned empty. Falling back to Unstructured."
                )
                elements = extract_with_unstructured(path_obj)
        
        if not elements and not bypass_layout:
            logger.warning("Unstructured fallback failed. Trying OCR.")
            elements = extract_with_ocr(path_obj)
            ocr_used = True

    elif file_type in (FileType.SCANNED_PDF, FileType.MIXED_PDF):
        # Route B: OCR
        logger.info("Routing %s to Route B: OCR", path_obj.name)
        elements = extract_with_ocr(path_obj)
        ocr_used = True

    elif file_type == FileType.DOCX:
        # Route C: Unstructured for Word Docs
        logger.info("Routing %s to Route C: Unstructured (DOCX)", path_obj.name)
        elements = extract_with_unstructured(path_obj)

    # Default Route D fallback: raw text parser extraction
    if not elements:
        logger.warning("All layout-aware parsers failed or returned empty. Falling back to raw text parser.")
        try:
            raw_text = extract_text_from_path(path_obj)
            elements = [
                ExtractedElement(
                    text=raw_text,
                    element_type="paragraph",
                    page_number=1
                )
            ]
        except Exception as exc:
            logger.error("Default raw text extraction failed: %s", exc)
            elements = []

    # 4. Section builder (group into canonical sections)
    sections = build_sections(elements)

    # Reconstruct raw text and detect character spans for evidence chunks
    raw_text_parts = []
    evidence_chunks = []
    field_evidence_map: Dict[str, List[str]] = {}
    
    char_cursor = 0
    for idx, elem in enumerate(elements):
        chunk_id = f"{candidate_id}__{idx:03d}"
        elem_text = elem.text.strip()
        raw_text_parts.append(elem_text)
        
        char_start = char_cursor
        char_end = char_start + len(elem_text)
        char_cursor = char_end + 2  # account for double newline spacing
        
        # Build Section label mapping
        matched_section = "other"
        for sec_name, blocks in sections.items():
            if elem_text in blocks:
                matched_section = sec_name
                break

        evidence_chunks.append({
            "chunk_id": chunk_id,
            "candidate_id": candidate_id,
            "document_id": f"doc_{candidate_id}",
            "page_number": elem.page_number,
            "section": matched_section,
            "chunk_type": "text",
            "text": elem_text,
            "char_start": char_start,
            "char_end": char_end,
            "embedding_ready": True,
            "ocr_confidence": elem.confidence if ocr_used else None,
            "source_bbox": None
        })

        # Populating field_evidence_map groups by section
        section_key = f"candidate_profile.{matched_section}"
        if section_key not in field_evidence_map:
            field_evidence_map[section_key] = []
        field_evidence_map[section_key].append(chunk_id)

    full_raw_text = "\n\n".join(raw_text_parts)

    # 5. Normalization via LLM
    profile_data = normalize_to_schema(sections, full_raw_text, candidate_id)

    # 6. Calculate deterministic features (months of exp, latest job, highest degree)
    total_months, latest_title, latest_company = calculate_experience_metrics(profile_data.get("experience", []))
    highest_degree = determine_highest_degree(profile_data.get("education", []))

    normalized_features = {
        "total_experience_months": total_months,
        "latest_job_title": latest_title,
        "latest_company": latest_company,
        "highest_degree": highest_degree,
        "skill_canonical_map": {
            skill.get("name_raw", "").lower(): skill.get("name_canonical")
            for skill in profile_data.get("skills", [])
            if skill.get("name_raw")
        },
        # BUG 1 fix: locations is not included in the LLM output prompt so it is
        # almost always absent. Using safe chained access prevents a crash when the
        # LLM hallucinates `"locations": null` (JSON null → Python None).
        "location_normalized": (
            (profile_data.get("locations") or [{}])[0].get("normalized")
        ),
        "work_authorization": None
    }

    # 7. Validate output against schema requirements
    validation_res = validate_resume_json({"candidate_profile": profile_data})

    # Assemble full JSON output structure
    output_json = {
        "schema_version": "1.0.0",
        "candidate_id": candidate_id,
        "document": {
            "document_id": f"doc_{candidate_id}",
            "file_name": path_obj.name,
            "file_type": path_obj.suffix.lstrip(".").lower(),
            "ingestion_type": file_type.value,
            "source_language": "en",
            "page_count": len(set(chunk["page_number"] for chunk in evidence_chunks)) or 1,
            "parsed_at": datetime.now(timezone.utc).isoformat(),
            "ocr_used": ocr_used,
            "parser_name": "pypdfium2+llm-normalizer",
            "parser_version": "2.0.0"
        },
        "candidate_profile": profile_data,
        "normalized_features": normalized_features,
        "evidence_chunks": evidence_chunks,
        "field_evidence_map": field_evidence_map,
        "validation": {
            "status": "success" if validation_res.is_valid else "review_required",
            "warnings": validation_res.warnings,
            "errors": validation_res.missing_fields
        },
        "confidence": {
            "document_confidence": validation_res.confidence_score,
            "field_confidence": {
                f"candidate_profile.{field}": profile_data.get(field, {}).get("confidence", 0.9)
                if isinstance(profile_data.get(field), dict) else 0.90
                for field in profile_data
            }
        },
        "raw": {
            "raw_text": full_raw_text,
            "sections_detected": list(sections.keys()),
            "ocr_text": full_raw_text if ocr_used else None
        }
    }

    return output_json


# ---------------------------------------------------------------------------
# Core Date & Feature Parsing Primitives
# ---------------------------------------------------------------------------

def parse_date_months(date_str: str) -> Optional[int]:
    """Parse YYYY-MM or YYYY format to total months since AD 0."""
    if not date_str or not isinstance(date_str, str):
        return None
    date_clean = date_str.strip().lower()
    
    if any(p in date_clean for p in ("present", "current", "ongoing")):
        return datetime.utcnow().year * 12 + datetime.utcnow().month
        
    # YYYY-MM
    m = re.match(r"^(\d{4})-(\d{2})$", date_clean)
    if m:
        return int(m.group(1)) * 12 + int(m.group(2))
        
    # YYYY
    m = re.match(r"^(\d{4})$", date_clean)
    if m:
        return int(m.group(1)) * 12 + 6  # assume midpoint of year
        
    # Try generic year matching in dates
    years = re.findall(r"\b(19\d{2}|20\d{2})\b", date_clean)
    if years:
        return int(years[0]) * 12 + 6
        
    return None

def calculate_experience_metrics(experience_entries: List[Dict[str, Any]]) -> tuple[int, Optional[str], Optional[str]]:
    """Compute total months of experience from employment entries without double counting overlaps."""
    if not experience_entries:
        return 0, None, None
        
    intervals = []
    latest_end_month = -1
    latest_job_title = None
    latest_company = None
    
    for entry in experience_entries:
        start_str = entry.get("start_date") or ""
        end_str = entry.get("end_date") or ""
        is_current = entry.get("is_current", False)
        
        start_val = parse_date_months(start_str)
        if not start_val:
            continue
            
        end_val = parse_date_months(end_str)
        if not end_val:
            if is_current:
                end_val = datetime.utcnow().year * 12 + datetime.utcnow().month
            else:
                end_val = start_val  # default 1 month
                
        intervals.append((start_val, end_val))
        
        # Track the latest experience details
        if end_val > latest_end_month:
            latest_end_month = end_val
            latest_job_title = entry.get("job_title")
            latest_company = entry.get("company")
            
    if not intervals:
        return 0, None, None
        
    # Sort and merge overlapping intervals
    intervals.sort()
    merged = [intervals[0]]
    for start, end in intervals[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
            
    total_months = sum(end - start + 1 for start, end in merged)
    return total_months, latest_job_title, latest_company

def determine_highest_degree(education_entries: List[Dict[str, Any]]) -> Optional[str]:
    """Identify highest degree held from education entries using standard hierarchy."""
    if not education_entries:
        return None
        
    degree_hierarchy = [
        "phd", "ph.d", "doctor",
        "mtech", "m.tech", "ms", "m.s", "msc", "m.sc", "mba", "master", "post graduate", "pg",
        "btech", "b.tech", "be", "b.e", "bs", "b.s", "bsc", "b.sc", "bca", "bba", "bachelor",
        "diploma"
    ]
    
    highest_deg = None
    highest_rank = len(degree_hierarchy)
    
    for edu in education_entries:
        deg = str(edu.get("degree") or "").lower().strip()
        for i, h_deg in enumerate(degree_hierarchy):
            if h_deg in deg and i < highest_rank:
                highest_rank = i
                highest_deg = edu.get("degree")
                
    return highest_deg or education_entries[0].get("degree")
