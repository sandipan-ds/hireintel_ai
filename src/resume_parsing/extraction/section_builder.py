# This module is responsible for grouping extracted document elements into canonical sections.
#
# It uses the SECTION_HEADERS synonym table from parser.py to match headings,
# and groups elements under their respective sections using heading-to-body rules.

import re
from typing import List, Dict, Optional

from src.resume_parsing.extraction.element import ExtractedElement
from src.resume_parsing.parser import SECTION_HEADERS

def clean_header(text: str) -> str:
    """Normalize header text for robust synonym matching."""
    # Lowercase, strip punctuation and extra spaces
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", "", text)
    return " ".join(text.split())

def match_section_header(text: str) -> Optional[str]:
    """Match a header string to one of the canonical section names."""
    cleaned = clean_header(text)
    
    for section, synonyms in SECTION_HEADERS.items():
        for syn in synonyms:
            cleaned_syn = clean_header(syn)
            # Match exact, prefix, suffix, or word boundary containment
            if cleaned == cleaned_syn or cleaned.startswith(cleaned_syn + " ") or cleaned.endswith(" " + cleaned_syn):
                # Map 'languages' to 'other' to fit the 7 canonical sections contract
                if section == "languages":
                    return "other"
                return section
    return None

def build_sections(elements: List[ExtractedElement]) -> Dict[str, List[str]]:
    """
    Group extracted elements into 7 canonical sections:
    summary, skills, experience, education, certifications, projects, other.

    Args:
        elements: List of ExtractedElement objects.

    Returns:
        Dict mapping canonical section names to list of text blocks.
    """
    sections: Dict[str, List[str]] = {
        "summary": [],
        "skills": [],
        "experience": [],
        "education": [],
        "certifications": [],
        "projects": [],
        "other": []
    }

    # Start by defaulting to 'summary' for any top-of-resume text before headers
    current_section = "summary"

    for elem in elements:
        text = elem.text.strip()
        if not text:
            continue

        # If it's a heading, try to match it to a section
        if elem.element_type == "heading":
            matched = match_section_header(text)
            if matched:
                current_section = matched
                # Skip adding the header itself to keep sections clean of raw headers
                continue
            else:
                # Unrecognized headers go to 'other'
                current_section = "other"
                # Keep the header text for context in 'other'
                sections[current_section].append(text)
                continue

        # Non-heading elements get grouped into the current section
        sections[current_section].append(text)

    return sections
