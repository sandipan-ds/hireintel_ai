# This module implements Layer A: Schema Validation for the quality audit.
#
# It verifies that the JSON structure conforms strictly to the expected target
# resume schema. It performs data type checks, key presence checks, and date format
# validation (e.g. YYYY-MM or YYYY format checking).
#
# Doing this deterministically ensures that downstream components (RAG, scoring,
# DB insertion) do not crash due to malformed values or missing properties.

"""Layer A: Schema Validation for resume JSON (DEC-036)."""

import re
from typing import Dict, Any, List, Tuple
from src.resume_parsing.audit.models import AuditCheck

# Date pattern matching YYYY-MM or YYYY
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}$|^\d{4}$")

def validate_date(date_str: Any) -> bool:
    """Check if date_str is in YYYY-MM or YYYY format."""
    if not isinstance(date_str, str):
        return False
    return bool(DATE_PATTERN.match(date_str.strip()))

def run(resume_json: Dict[str, Any]) -> Tuple[List[AuditCheck], float]:
    """
    Run schema validation on extracted resume JSON.

    Args:
        resume_json: The candidate JSON dictionary loaded from processed data.

    Returns:
        A tuple of (audit_checks, schema_validity_score).
        schema_validity_score is in [0.0, 1.0], where 1.0 represents perfect conformance.
    """
    checks: List[AuditCheck] = []
    errors = 0
    total_checks = 0

    # 1. Top-Level Key Checks
    required_top_keys = [
        "schema_version", "candidate_id", "candidate_profile",
        "evidence_chunks", "field_evidence_map", "validation", "confidence", "raw"
    ]
    for key in required_top_keys:
        total_checks += 1
        if key not in resume_json:
            errors += 1
            checks.append(AuditCheck(
                check_id="schema_top_key_missing",
                severity="critical",
                layer="schema",
                field=key,
                issue=f"Required top-level key '{key}' is missing from JSON",
                expected="Present",
                actual="Absent"
            ))

    # If top-level keys or candidate_profile is missing, return early
    if "candidate_profile" not in resume_json:
        return checks, 0.0

    profile = resume_json["candidate_profile"]
    if not isinstance(profile, dict):
        checks.append(AuditCheck(
            check_id="schema_profile_not_dict",
            severity="critical",
            layer="schema",
            field="candidate_profile",
            issue="candidate_profile is not an object/dictionary",
            expected="dict",
            actual=str(type(profile))
        ))
        return checks, 0.0

    # 2. Profile Field Presence and Type Checks
    profile_fields = {
        "full_name": str,
        "headline": str,
        "summary": (str, dict),
        "skills": list,
        "education": (list, dict),
        "experience": (list, dict),
        "projects": list,
        "certifications": list,
        "languages": list,
        "emails": list,
        "phones": list,
        "links": dict
    }

    for field_name, expected_types in profile_fields.items():
        total_checks += 1
        if field_name not in profile:
            errors += 1
            checks.append(AuditCheck(
                check_id=f"schema_field_missing_{field_name}",
                severity="error",
                layer="schema",
                field=f"candidate_profile.{field_name}",
                issue=f"Field '{field_name}' missing from candidate_profile",
                expected="Present",
                actual="Absent"
            ))
        else:
            val = profile[field_name]
            # None/null values are checked depending on field family
            if val is not None:
                is_type_ok = isinstance(val, expected_types)
                if not is_type_ok:
                    errors += 1
                    checks.append(AuditCheck(
                        check_id=f"schema_field_type_invalid_{field_name}",
                        severity="error",
                        layer="schema",
                        field=f"candidate_profile.{field_name}",
                        issue=f"Field '{field_name}' has invalid type",
                        expected=str(expected_types),
                        actual=str(type(val))
                    ))

    # 3. Experience Entry Checks
    exp = profile.get("experience")
    exp_entries = []
    if isinstance(exp, dict):
        exp_entries = exp.get("entries") or []
    elif isinstance(exp, list):
        exp_entries = exp

    for idx, entry in enumerate(exp_entries):
        if not isinstance(entry, dict):
            errors += 1
            checks.append(AuditCheck(
                check_id=f"schema_exp_not_dict_{idx}",
                severity="error",
                layer="schema",
                field=f"candidate_profile.experience[{idx}]",
                issue=f"Experience entry at index {idx} is not a dictionary",
                expected="dict",
                actual=str(type(entry))
            ))
            continue

        # Check dates and current markers
        start_date = entry.get("start_date")
        end_date = entry.get("end_date")
        is_current = entry.get("is_current")

        total_checks += 1
        if start_date:
            if not validate_date(start_date):
                errors += 1
                checks.append(AuditCheck(
                    check_id=f"schema_exp_start_date_format_{idx}",
                    severity="error",
                    layer="schema",
                    field=f"candidate_profile.experience[{idx}].start_date",
                    issue=f"Experience start_date '{start_date}' is not in YYYY-MM or YYYY format",
                    expected="YYYY-MM or YYYY",
                    actual=str(start_date)
                ))

        total_checks += 1
        if end_date:
            if not validate_date(end_date):
                errors += 1
                checks.append(AuditCheck(
                    check_id=f"schema_exp_end_date_format_{idx}",
                    severity="error",
                    layer="schema",
                    field=f"candidate_profile.experience[{idx}].end_date",
                    issue=f"Experience end_date '{end_date}' is not in YYYY-MM or YYYY format",
                    expected="YYYY-MM or YYYY or null",
                    actual=str(end_date)
                ))

        # Checks experience[].end_date is null only when is_current is true
        total_checks += 1
        if end_date is None or str(end_date).strip().lower() in ("null", "none", ""):
            # It's null/empty, so is_current must be True (or equivalent)
            if not is_current:
                errors += 1
                checks.append(AuditCheck(
                    check_id=f"schema_exp_current_mismatch_{idx}",
                    severity="warning",
                    layer="schema",
                    field=f"candidate_profile.experience[{idx}].is_current",
                    issue=f"Experience entry {idx} has null end_date but is_current is not set to true",
                    expected="True",
                    actual=str(is_current)
                ))

    # 4. Education Entry Checks
    edu = profile.get("education")
    edu_entries = []
    if isinstance(edu, dict):
        edu_entries = edu.get("entries") or []
    elif isinstance(edu, list):
        edu_entries = edu

    for idx, entry in enumerate(edu_entries):
        if not isinstance(entry, dict):
            errors += 1
            checks.append(AuditCheck(
                check_id=f"schema_edu_not_dict_{idx}",
                severity="error",
                layer="schema",
                field=f"candidate_profile.education[{idx}]",
                issue=f"Education entry at index {idx} is not a dictionary",
                expected="dict",
                actual=str(type(entry))
            ))
            continue

        start_date = entry.get("start_date")
        end_date = entry.get("end_date")

        total_checks += 1
        if start_date and not validate_date(start_date):
            errors += 1
            checks.append(AuditCheck(
                check_id=f"schema_edu_start_date_format_{idx}",
                severity="error",
                layer="schema",
                field=f"candidate_profile.education[{idx}].start_date",
                issue=f"Education start_date '{start_date}' is not in YYYY-MM or YYYY format",
                expected="YYYY-MM or YYYY",
                actual=str(start_date)
            ))

        total_checks += 1
        if end_date and not validate_date(end_date):
            errors += 1
            checks.append(AuditCheck(
                check_id=f"schema_edu_end_date_format_{idx}",
                severity="error",
                layer="schema",
                field=f"candidate_profile.education[{idx}].end_date",
                issue=f"Education end_date '{end_date}' is not in YYYY-MM or YYYY format",
                expected="YYYY-MM or YYYY or null",
                actual=str(end_date)
            ))

    # 5. Skills Array Checks
    skills = profile.get("skills") or []
    if isinstance(skills, list):
        for idx, skill in enumerate(skills):
            total_checks += 1
            skill_name = ""
            if isinstance(skill, dict):
                skill_name = skill.get("name_raw") or skill.get("name_canonical") or ""
            elif isinstance(skill, str):
                skill_name = skill

            if not isinstance(skill_name, str) or not skill_name.strip():
                errors += 1
                checks.append(AuditCheck(
                    check_id=f"schema_skill_name_invalid_{idx}",
                    severity="error",
                    layer="schema",
                    field=f"candidate_profile.skills[{idx}]",
                    issue=f"Skill entry at index {idx} does not contain a non-empty name string",
                    expected="Non-empty string",
                    actual=str(skill)
                ))

    # 6. Confidence Level Check
    conf = resume_json.get("confidence")
    if isinstance(conf, dict):
        total_checks += 1
        doc_conf = conf.get("document_confidence")
        if doc_conf is not None:
            try:
                doc_conf_float = float(doc_conf)
                if not (0.0 <= doc_conf_float <= 1.0):
                    errors += 1
                    checks.append(AuditCheck(
                        check_id="schema_doc_confidence_out_of_bounds",
                        severity="error",
                        layer="schema",
                        field="confidence.document_confidence",
                        issue=f"document_confidence '{doc_conf}' is out of [0.0, 1.0] bounds",
                        expected="[0.0, 1.0]",
                        actual=str(doc_conf)
                    ))
            except ValueError:
                errors += 1
                checks.append(AuditCheck(
                    check_id="schema_doc_confidence_not_float",
                    severity="error",
                    layer="schema",
                    field="confidence.document_confidence",
                    issue=f"document_confidence '{doc_conf}' is not numeric",
                    expected="float",
                    actual=str(type(doc_conf))
                ))

    # Calculate score
    if total_checks == 0:
        score = 1.0
    else:
        score = max(0.0, 1.0 - (errors / total_checks))

    return checks, score
