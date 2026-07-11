# This module implements Layer E: Cross-Parser Consistency Audit.
#
# It compares the primary extraction (typically produced via layout-aware Docling + LLM)
# against the old regex/rule-based baseline parser (src/resume_parsing/parser.py).
#
# Comparing these two parser runs acts as a second opinion. Large discrepancies
# in names, emails, or section item counts flag conflicts that lower the overall
# quality confidence.

"""Layer E: Cross-Parser Consistency Audit (DEC-036)."""

import logging
from pathlib import Path
from typing import Dict, Any, List, Tuple
from src.resume_parsing.audit.models import ParserConflict
from src.resume_parsing.parser import parse_resume

logger = logging.getLogger(__name__)

def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate the Levenshtein distance between two strings."""
    s1 = s1.strip().lower()
    s2 = s2.strip().lower()
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    
    previous_row = list(range(len(s2) + 1))
    for c1 in s1:
        current_row = [previous_row[0] + 1]
        for idx, c2 in enumerate(s2):
            insertions = previous_row[idx + 1] + 1
            deletions = current_row[idx] + 1
            substitutions = previous_row[idx] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]

def run(resume_json: Dict[str, Any], source_path: str) -> Tuple[List[ParserConflict], float]:
    """
    Run cross-parser consistency audit against the legacy parser.

    Args:
        resume_json: Extracted candidate JSON dictionary.
        source_path: Path to the original PDF/DOCX file.

    Returns:
        A tuple of (conflicts, parser_agreement_score).
    """
    conflicts: List[ParserConflict] = []
    agreements = 0
    total_checks = 0

    p_path = Path(source_path)
    if not p_path.exists():
        logger.warning("Cross-parser: Source file '%s' does not exist; skipping Layer E.", source_path)
        return conflicts, 1.0

    # 1. Run legacy parser
    try:
        old_profile = parse_resume(p_path)
    except Exception as e:
        logger.warning("Cross-parser: Legacy parser failed to parse '%s': %s", source_path, e)
        # Return 1.0 agreement as the fallback is unavailable (not an extraction conflict)
        return conflicts, 1.0

    profile = resume_json.get("candidate_profile", {})

    # 2. Compare Names
    total_checks += 1
    new_name = profile.get("full_name") or ""
    old_name = old_profile.get("name", {}).get("value") or ""
    
    if new_name and old_name:
        dist = levenshtein_distance(new_name, old_name)
        if dist > 2:
            conflicts.append(ParserConflict(
                field="candidate_profile.full_name",
                parser_a=new_name,
                parser_b=old_name,
                severity="warning"
            ))
        else:
            agreements += 1
    else:
        # If one parser missed name completely, record a conflict
        if (new_name and not old_name) or (old_name and not new_name):
            conflicts.append(ParserConflict(
                field="candidate_profile.full_name",
                parser_a=str(new_name),
                parser_b=str(old_name),
                severity="warning"
            ))
        else:
            agreements += 1

    # 3. Compare Emails
    total_checks += 1
    new_emails = set(profile.get("emails") or [])
    old_emails_raw = old_profile.get("contact", {}).get("emails") or []
    # Coerce format if old parser emails is dict list or str list
    old_emails = set()
    for e in old_emails_raw:
        if isinstance(e, dict):
            old_emails.add(e.get("value") or "")
        else:
            old_emails.add(str(e))
    old_emails.discard("")

    # Standardize comparison set
    new_emails_clean = {str(e).strip().lower() for e in new_emails if str(e).strip()}
    old_emails_clean = {str(e).strip().lower() for e in old_emails if str(e).strip()}

    if new_emails_clean != old_emails_clean:
        conflicts.append(ParserConflict(
            field="candidate_profile.emails",
            parser_a=str(list(new_emails_clean)),
            parser_b=str(list(old_emails_clean)),
            severity="warning"
        ))
    else:
        agreements += 1

    # 4. Compare Experience entry count
    total_checks += 1
    exp = profile.get("experience")
    new_exp_count = len(exp.get("entries") or []) if isinstance(exp, dict) else len(exp or [])
    
    old_exp = old_profile.get("experience") or {}
    old_exp_count = len(old_exp.get("entries") or []) if isinstance(old_exp, dict) else len(old_exp or [])

    if abs(new_exp_count - old_exp_count) > 1:
        conflicts.append(ParserConflict(
            field="candidate_profile.experience.count",
            parser_a=str(new_exp_count),
            parser_b=str(old_exp_count),
            severity="info"  # experience count differences are common, marked as informational
        ))
    else:
        agreements += 1

    # 5. Compare Education entry count
    total_checks += 1
    edu = profile.get("education")
    new_edu_count = len(edu.get("entries") or []) if isinstance(edu, dict) else len(edu or [])
    
    old_edu = old_profile.get("education") or {}
    old_edu_count = len(old_edu.get("entries") or []) if isinstance(old_edu, dict) else len(old_edu or [])

    if abs(new_edu_count - old_edu_count) > 1:
        conflicts.append(ParserConflict(
            field="candidate_profile.education.count",
            parser_a=str(new_edu_count),
            parser_b=str(old_edu_count),
            severity="info"
        ))
    else:
        agreements += 1

    # Calculate agreement score
    agreement_score = agreements / total_checks if total_checks > 0 else 1.0
    return conflicts, agreement_score
