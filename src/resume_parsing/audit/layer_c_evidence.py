# This module implements Layer C: Evidence Coverage for the quality audit.
#
# It verifies the bidirectional mapping between the structured JSON fields
# and the unstructured text chunks (evidence chunks).
#
# Forward coverage: Checks if all chunk IDs referenced in the field_evidence_map
# actually exist and contain valid text.
#
# Reverse coverage: Checks if any important text chunks (e.g. experience descriptions,
# degrees, certifications) exist in the source document but are not linked/mapped
# to any field in the JSON profile, indicating a missed extraction.

"""Layer C: Evidence Coverage Audit (DEC-036)."""

from typing import Dict, Any, List, Tuple, Set
from src.resume_parsing.audit.models import AuditCheck

# High-value section tags that should not remain unmapped
MEANINGFUL_SECTIONS = {"experience", "education", "certifications", "projects", "skills"}

# High-value keyword triggers indicating important evidence
IMPORTANT_KEYWORDS = [
    "certified", "certification", "aws", "azure", "gcp", "pmp", "scrum",
    "bachelor", "master", "phd", "degree", "university", "college",
    "developed", "managed", "designed", "engineered", "implemented"
]

def run(resume_json: Dict[str, Any]) -> Tuple[List[AuditCheck], float]:
    """
    Run forward and reverse evidence coverage checks.

    Args:
        resume_json: Extracted candidate JSON dict.

    Returns:
        A tuple of (audit_checks, evidence_coverage_score).
    """
    checks: List[AuditCheck] = []
    errors = 0
    checks_conducted = 0

    evidence_chunks = resume_json.get("evidence_chunks") or []
    field_evidence_map = resume_json.get("field_evidence_map") or {}

    # Build a lookup set of existing chunk IDs and map to their texts
    chunk_lookup: Dict[str, Dict[str, Any]] = {}
    for chunk in evidence_chunks:
        if isinstance(chunk, dict) and "chunk_id" in chunk:
            chunk_lookup[chunk["chunk_id"]] = chunk

    # Set of chunk IDs mapped to any JSON field
    mapped_chunk_ids: Set[str] = set()

    # 1. Forward Coverage Check
    for field_path, chunk_ids in field_evidence_map.items():
        if not isinstance(chunk_ids, list):
            checks_conducted += 1
            errors += 1
            checks.append(AuditCheck(
                check_id="evidence_map_invalid_type",
                severity="error",
                layer="evidence",
                field=f"field_evidence_map.{field_path}",
                issue=f"Chunk IDs mapped to '{field_path}' must be a list, found {type(chunk_ids)}",
                expected="list of strings",
                actual=str(chunk_ids)
            ))
            continue

        for chunk_id in chunk_ids:
            checks_conducted += 1
            mapped_chunk_ids.add(chunk_id)
            
            if chunk_id not in chunk_lookup:
                errors += 1
                checks.append(AuditCheck(
                    check_id="evidence_missing_chunk_id",
                    severity="error",
                    layer="evidence",
                    field=f"field_evidence_map.{field_path}",
                    issue=f"Field references missing evidence chunk ID '{chunk_id}'",
                    expected="existing chunk_id",
                    actual="missing"
                ))
            else:
                chunk_data = chunk_lookup[chunk_id]
                chunk_text = chunk_data.get("text") or ""
                if not isinstance(chunk_text, str) or not chunk_text.strip():
                    errors += 1
                    checks.append(AuditCheck(
                        check_id="evidence_empty_chunk_text",
                        severity="error",
                        layer="evidence",
                        field=f"field_evidence_map.{field_path}",
                        issue=f"Referenced chunk '{chunk_id}' contains empty text",
                        expected="non-empty string",
                        actual=repr(chunk_text)
                    ))

    # 2. Reverse Coverage Check
    # Check for unmapped chunks that contain meaningful content
    for chunk_id, chunk_data in chunk_lookup.items():
        if chunk_id in mapped_chunk_ids:
            continue

        # Chunk is unmapped. Check if it seems to contain meaningful information
        chunk_text = chunk_data.get("text") or ""
        section_name = chunk_data.get("section") or ""
        
        # Heuristics for "meaningful" chunk
        is_meaningful_section = any(s in section_name.lower() for s in MEANINGFUL_SECTIONS)
        has_important_kw = any(kw in chunk_text.lower() for kw in IMPORTANT_KEYWORDS)
        
        if is_meaningful_section or (has_important_kw and len(chunk_text.strip()) > 30):
            checks_conducted += 1
            # We treat this as a warning (silent extraction omission)
            errors += 0.5  # half penalty since it is heuristic
            checks.append(AuditCheck(
                check_id="evidence_unmapped_chunk",
                severity="warning",
                layer="evidence",
                field="evidence_chunks",
                issue=f"Chunk '{chunk_id}' in section '{section_name}' is unmapped but contains potentially important text",
                expected="mapped chunk",
                actual=f"unmapped text: {chunk_text[:60]}..."
            ))

    # Calculate score
    if checks_conducted == 0:
        score = 1.0
    else:
        score = max(0.0, 1.0 - (errors / checks_conducted))

    return checks, score
