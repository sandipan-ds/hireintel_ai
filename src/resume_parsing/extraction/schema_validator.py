# This module validates the output resume JSON against required schema criteria
# and computes confidence scores for extraction quality audits.

from dataclasses import dataclass, field
from typing import List, Dict, Any

@dataclass
class ValidationResult:
    is_valid: bool
    missing_fields: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    confidence_score: float = 1.0

def validate_resume_json(data: Dict[str, Any]) -> ValidationResult:
    """
    Validate the structured resume JSON according to schema requirements.

    Args:
        data: Top-level extracted resume dictionary.

    Returns:
        ValidationResult detailing status and confidence.
    """
    missing_fields = []
    warnings = []
    
    profile = data.get("candidate_profile", {})
    if not profile:
        return ValidationResult(is_valid=False, missing_fields=["candidate_profile"], confidence_score=0.0)

    # 1. Required Fields Checks
    if not profile.get("full_name"):
        missing_fields.append("candidate_profile.full_name")

    if not profile.get("emails"):
        missing_fields.append("candidate_profile.emails")

    if not profile.get("phones"):
        warnings.append("No phone numbers found in candidate profile")

    if not profile.get("skills"):
        warnings.append("No skills extracted in candidate profile")

    if not profile.get("education"):
        warnings.append("No education entries extracted in candidate profile")

    if not profile.get("experience"):
        warnings.append("No experience entries extracted in candidate profile")

    # 2. Compute average confidence score
    confidence_scores = []
    
    # Collect confidence scores from profile lists
    for skill in profile.get("skills", []):
        if "confidence" in skill:
            confidence_scores.append(skill["confidence"])
            
    for edu in profile.get("education", []):
        if "confidence" in edu:
            confidence_scores.append(edu["confidence"])
            
    for exp in profile.get("experience", []):
        if "confidence" in exp:
            confidence_scores.append(exp["confidence"])
            
    for cert in profile.get("certifications", []):
        if "confidence" in cert:
            confidence_scores.append(cert["confidence"])

    # Average score (default to 0.90 if no fields are present, or average of all available)
    if confidence_scores:
        avg_confidence = sum(confidence_scores) / len(confidence_scores)
    else:
        avg_confidence = 0.90 if profile.get("full_name") else 0.50

    is_valid = len(missing_fields) == 0

    return ValidationResult(
        is_valid=is_valid,
        missing_fields=missing_fields,
        warnings=warnings,
        confidence_score=avg_confidence
    )
