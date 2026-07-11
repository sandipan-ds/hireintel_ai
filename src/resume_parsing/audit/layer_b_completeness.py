# This module implements Layer B: Field and Section Completeness Audit.
#
# It uses deterministic heuristics (like regular expressions and keyword checks)
# on the raw text of the resume to determine if information is likely missing
# from the extracted JSON.
#
# If the resume contains phone numbers, emails, LinkedIn URLs, or clear
# education/experience patterns, but the extracted JSON lacks them, the audit
# flags a warning or error. This helps detect silently dropped sections.

"""Layer B: Field and Section Completeness Heuristics (DEC-036)."""

import re
from typing import Dict, Any, List, Tuple
from src.resume_parsing.audit.models import AuditCheck

# Heuristic Regex Patterns
EMAIL_REGEX = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")
# Phone regex matching international or standard US numbers
PHONE_REGEX = re.compile(r"(?:\+?\d{1,4}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}")
LINKEDIN_REGEX = re.compile(r"linkedin\.com/[a-zA-Z0-9_\-\/]+")
GITHUB_REGEX = re.compile(r"github\.com/[a-zA-Z0-9_\-\/]+")

# Date ranges commonly found in experience sections:
# e.g., "2018 - 2021", "2015-Present", "Jan 2018 - Dec 2020", "October 2019 - current"
DATE_RANGE_REGEX = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}\b"
    r"|\b\d{4}\b\s*-\s*(?:\b\d{4}\b|Present|present|Current|current|Present|Present)"
)

# Education indicators
EDU_KEYWORDS = ["bachelor", "master", "phd", "b.sc", "m.sc", "b.tech", "m.tech", "degree", "university", "college", "institute"]

# Certification indicators
CERT_KEYWORDS = ["certified", "certification", "aws", "azure", "gcp", "pmp", "scrum", "oracle", "cisco", "ccna"]

# Section heading patterns in raw text
SECTION_EDU_HEADING = re.compile(r"\b(?:education|academic|background|studies)\b", re.IGNORECASE)
SECTION_EXP_HEADING = re.compile(r"\b(?:experience|employment|work history|career|history)\b", re.IGNORECASE)
SECTION_SKILL_HEADING = re.compile(r"\b(?:skills|technical skills|expertise|technologies|proficiencies)\b", re.IGNORECASE)

def run(resume_json: Dict[str, Any]) -> Tuple[List[AuditCheck], float]:
    """
    Run completeness validation against raw text vs JSON fields.

    Args:
        resume_json: Extracted candidate JSON dict.

    Returns:
        A tuple of (audit_checks, completeness_score).
    """
    checks: List[AuditCheck] = []
    errors = 0
    checks_conducted = 0

    raw = resume_json.get("raw", {})
    raw_text = raw.get("raw_text", "") or ""
    # Strip some spacing to avoid regex failure on multi-line layout text
    collapsed_text = " ".join(raw_text.split())

    profile = resume_json.get("candidate_profile", {})

    # 1. Email Completeness Check
    checks_conducted += 1
    emails_in_raw = EMAIL_REGEX.findall(collapsed_text)
    emails_in_json = profile.get("emails") or []
    if emails_in_raw and not emails_in_json:
        errors += 1
        checks.append(AuditCheck(
            check_id="completeness_email_missing",
            severity="warning",
            layer="field",
            field="candidate_profile.emails",
            issue="Email pattern found in raw text but emails array is empty",
            expected="non-empty list",
            actual=str(emails_in_json)
        ))

    # 2. Phone Completeness Check
    checks_conducted += 1
    phones_in_raw = PHONE_REGEX.findall(collapsed_text)
    phones_in_json = profile.get("phones") or []
    if phones_in_raw and not phones_in_json:
        errors += 1
        checks.append(AuditCheck(
            check_id="completeness_phone_missing",
            severity="warning",
            layer="field",
            field="candidate_profile.phones",
            issue="Phone number pattern found in raw text but phones array is empty",
            expected="non-empty list",
            actual=str(phones_in_json)
        ))

    # 3. LinkedIn / GitHub Links Check
    checks_conducted += 1
    has_linkedin = bool(LINKEDIN_REGEX.search(collapsed_text))
    has_github = bool(GITHUB_REGEX.search(collapsed_text))
    links_in_json = profile.get("links") or []

    if (has_linkedin or has_github) and not links_in_json:
        errors += 1
        checks.append(AuditCheck(
            check_id="completeness_links_missing",
            severity="warning",
            layer="field",
            field="candidate_profile.links",
            issue="LinkedIn or GitHub link found in raw text but links array is empty",
            expected="non-empty list",
            actual=str(links_in_json)
        ))

    # 4. Experience Completeness Check
    checks_conducted += 1
    exp = profile.get("experience")
    exp_entries = []
    if isinstance(exp, dict):
        exp_entries = exp.get("entries") or []
    elif isinstance(exp, list):
        exp_entries = exp

    # Find date range references to estimate experience entries count
    detected_date_ranges = DATE_RANGE_REGEX.findall(collapsed_text)
    # Filter duplicate matches or near overlaps
    unique_date_ranges = list(set(detected_date_ranges))
    
    # Check if heading exists
    has_exp_heading = bool(SECTION_EXP_HEADING.search(collapsed_text))

    if has_exp_heading and not exp_entries:
        errors += 1
        checks.append(AuditCheck(
            check_id="completeness_exp_section_empty",
            severity="error",
            layer="section",
            field="candidate_profile.experience",
            issue="Experience-related heading detected in raw text, but experience array is empty",
            expected="list of entries",
            actual="[]"
        ))
    elif len(unique_date_ranges) > 2 and len(exp_entries) <= int(len(unique_date_ranges) / 2):
        errors += 1
        checks.append(AuditCheck(
            check_id="completeness_exp_count_low",
            severity="warning",
            layer="section",
            field="candidate_profile.experience",
            issue=f"Detected {len(unique_date_ranges)} date ranges in raw text, but only {len(exp_entries)} experience entries extracted",
            expected=f">= {int(len(unique_date_ranges) / 2)} entries",
            actual=str(len(exp_entries))
        ))

    # 5. Education Completeness Check
    checks_conducted += 1
    edu = profile.get("education")
    edu_entries = []
    if isinstance(edu, dict):
        edu_entries = edu.get("entries") or []
    elif isinstance(edu, list):
        edu_entries = edu

    has_edu_heading = bool(SECTION_EDU_HEADING.search(collapsed_text))
    # Count occurrence of educational keywords
    edu_kw_matches = [kw for kw in EDU_KEYWORDS if kw in collapsed_text.lower()]

    if has_edu_heading and not edu_entries:
        errors += 1
        checks.append(AuditCheck(
            check_id="completeness_edu_section_empty",
            severity="error",
            layer="section",
            field="candidate_profile.education",
            issue="Education-related heading detected in raw text, but education array is empty",
            expected="list of entries",
            actual="[]"
        ))
    elif edu_kw_matches and not edu_entries:
        errors += 1
        checks.append(AuditCheck(
            check_id="completeness_edu_missing_heuristic",
            severity="warning",
            layer="field",
            field="candidate_profile.education",
            issue=f"Education keywords like {edu_kw_matches[:3]} found in raw text, but education list is empty",
            expected="non-empty list",
            actual="[]"
        ))

    # 6. Certifications Completeness Check
    checks_conducted += 1
    certs = profile.get("certifications") or []
    cert_kw_matches = [kw for kw in CERT_KEYWORDS if kw in collapsed_text.lower()]
    
    if cert_kw_matches and not certs:
        errors += 1
        checks.append(AuditCheck(
            check_id="completeness_certs_missing_heuristic",
            severity="warning",
            layer="field",
            field="candidate_profile.certifications",
            issue=f"Certification keywords like {cert_kw_matches[:3]} found in raw text, but certifications array is empty",
            expected="non-empty list",
            actual="[]"
        ))

    # 7. Skills Section Heading and Count Check
    checks_conducted += 1
    skills = profile.get("skills") or []
    has_skills_heading = bool(SECTION_SKILL_HEADING.search(collapsed_text))

    if has_skills_heading and not skills:
        errors += 1
        checks.append(AuditCheck(
            check_id="completeness_skills_section_empty",
            severity="warning",
            layer="section",
            field="candidate_profile.skills",
            issue="Skills-related heading detected in raw text, but skills array is empty",
            expected="non-empty list",
            actual="[]"
        ))

    score = 1.0 - (errors / checks_conducted) if checks_conducted > 0 else 1.0
    return checks, score
