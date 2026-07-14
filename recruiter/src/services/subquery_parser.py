"""SubQuery document parser for extracting requirements.

Parses SubQuery markdown documents to extract requirements with their
categories, types, and scoring formulas. Used to populate the database
and serve requirements via API.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Root directory
ROOT = Path(__file__).resolve().parent.parent.parent


def parse_subquery_document(file_path: Path) -> Dict[str, Any]:
    """Parse a SubQuery markdown document to extract requirements.

    Args:
        file_path: Path to the SubQuery markdown file.

    Returns:
        Dictionary with role name and list of requirements.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"SubQuery file not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Extract role name from filename or content
    role_name = _extract_role_name(file_path, content)

    # Extract all requirements
    requirements = _extract_requirements(content)

    return {
        "role_name": role_name,
        "file_path": str(file_path),
        "requirements": requirements,
        "total_requirements": len(requirements),
    }


def _extract_role_name(file_path: Path, content: str) -> str:
    """Extract role name from filename or content."""
    # Try to extract from first heading
    heading_match = re.search(r"^#\s+(.+?)(?:\s*:\s*Sub-Query.*)?$", content, re.MULTILINE)
    if heading_match:
        return heading_match.group(1).strip()

    # Fallback to filename
    return file_path.stem.replace("_SubQuery", "").replace("SubQuery", "")


def _extract_requirements(content: str) -> List[Dict[str, Any]]:
    """Extract all requirements from SubQuery content.

    Each requirement carries:
        - ``req_id``, ``name``, ``category``, ``requirement_type``,
          ``description``, ``subquery_count``, ``scoring_formula`` (as before)
        - ``sub_queries``: a list of dicts of shape
          ``{key, text, type, scale, assessment_method}`` parsed from the
          SubQuery table rows following each REQ header. Empty list if the
          table is missing or malformed.
    """
    requirements = []

    # Find all REQ sections
    req_pattern = r"###\s+(REQ-\d+):\s+(.+?)(?:\n|$)"
    req_matches = list(re.finditer(req_pattern, content, re.MULTILINE))

    for i, match in enumerate(req_matches):
        req_id = match.group(1)
        req_name = match.group(2).strip()

        # Extract section content (from this REQ to the next REQ or end)
        start_pos = match.end()
        end_pos = req_matches[i + 1].start() if i + 1 < len(req_matches) else len(content)
        section_content = content[start_pos:end_pos]

        # Extract category and type
        category, requirement_type = _extract_category_and_type(section_content)

        # Extract description
        description = _extract_description(section_content)

        # Extract subquery count and formula
        subquery_count, scoring_formula = _extract_subquery_info(section_content)

        # Extract the actual sub-query rows from the table.
        sub_queries = _extract_sub_queries(section_content)

        requirements.append({
            "req_id": req_id,
            "name": req_name,
            "category": category,
            "requirement_type": requirement_type,
            "description": description,
            "subquery_count": subquery_count,
            "scoring_formula": scoring_formula,
            "sub_queries": sub_queries,
        })

    return requirements


# ---------------------------------------------------------------------------
# Sub-query row parser.
#
# SubQuery tables follow this shape (one row per sub-query):
#
#     | # | Sub-Query | Type | Scale | Assessment Method |
#     |---|-----------|------|-------|-------------------|
#     | SQ001 | Is there evidence that...? | Binary | 0 or 1 | Look for: ... |
#     | SQ002 | How relevant is...?        | Float  | 0.0-1.0 | Rubric: ...    |
#
# The parser:
#   1. Finds the table (lines starting with ``| SQ``).
#   2. Per row, splits on ``|``, strips whitespace, and pulls the 5 columns.
#      Extra ``|`` characters inside the assessment cell (rare but legal) are
#      rejoined so the cell stays whole.
#   3. Returns a list of dicts in the order they appear. An empty list means
#      the table was missing or unparseable — the caller can still score the
#      REQ using its name as a single query.
# ---------------------------------------------------------------------------

# Matches a table row whose first cell is a sub-query id (SQ### or SQ###-X).
_SQ_ROW_RE = re.compile(r"^\|\s*(SQ[a-zA-Z0-9_\-]+)\s*\|", re.MULTILINE)


def _extract_sub_queries(section_content: str) -> List[Dict[str, Any]]:
    """Parse the sub-query table rows under one REQ section.

    Args:
        section_content: The markdown body between this REQ's ``### REQ-XXX:``
            header and the next REQ header (or end of document).

    Returns:
        A list of dicts, one per sub-query row, in document order. Each dict
        has keys: ``key`` (e.g. ``"SQ001"``), ``text`` (the sub-query text),
        ``type`` (``"Binary"`` / ``"Float"``), ``scale`` (e.g. ``"0 or 1"``,
        ``"0.0 - 1.0"``), ``assessment_method`` (the rubric/formula text).
        Returns ``[]`` if no ``| SQ### |`` rows are found.
    """
    out: List[Dict[str, Any]] = []
    for m in _SQ_ROW_RE.finditer(section_content):
        # Grab the full line containing this row.
        line_start = section_content.rfind("\n", 0, m.start()) + 1
        line_end = section_content.find("\n", m.end())
        if line_end < 0:
            line_end = len(section_content)
        row = section_content[line_start:line_end].strip()

        # Strip the leading and trailing ``|`` and split.
        # Rejoin any overflow columns so the assessment cell stays whole.
        cells = [c.strip() for c in row.strip("|").split("|")]
        if len(cells) < 5:
            continue
        key = cells[0]
        text = cells[1]
        sq_type = cells[2]
        scale = cells[3]
        # The assessment-method cell may have been split by ``|`` inside a
        # regex like ``r"\bword\b"`` — rejoin with ``|`` so the cell ends up
        # exactly as in the source file.
        assessment_method = "|".join(cells[4:])

        out.append({
            "key": key,
            "text": text,
            "type": sq_type,
            "scale": scale,
            "assessment_method": assessment_method,
        })
    return out


def _extract_category_and_type(content: str) -> Tuple[str, str]:
    """Extract category and type from requirement section."""
    # Look for category line
    category_match = re.search(r"\*\*Category:\*\*\s*(.+?)(?:\n|$)", content)
    category = category_match.group(1).strip() if category_match else "Unknown"

    # Determine type based on category
    category_lower = category.lower()
    if "core" in category_lower or "required" in category_lower:
        requirement_type = "required"
    elif "preferred" in category_lower or "optional" in category_lower:
        requirement_type = "preferred"
    elif "experience" in category_lower:
        requirement_type = "required"
    elif "education" in category_lower:
        requirement_type = "required"
    elif "certification" in category_lower:
        requirement_type = "preferred"
    else:
        requirement_type = "required"

    return category, requirement_type


def _extract_description(content: str) -> str:
    """Extract description from requirement section."""
    # Look for description or purpose
    desc_match = re.search(r"\*\*(?:Description|Purpose):\*\*\s*(.+?)(?:\n\n|\n\*\*|\Z)", content, re.DOTALL)
    if desc_match:
        return desc_match.group(1).strip()

    # Fallback: extract first paragraph
    lines = content.strip().split("\n")
    description_lines = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith("**") and not line.startswith("|"):
            description_lines.append(line)
        elif line.startswith("**"):
            break

    return " ".join(description_lines[:3]) if description_lines else ""


def _extract_subquery_info(content: str) -> Tuple[int, str]:
    """Extract subquery count and scoring formula."""
    # Extract subquery count
    count_match = re.search(r"\*\*Sub-Query Count:\*\*\s*(\d+)", content)
    subquery_count = int(count_match.group(1)) if count_match else 1

    # Extract scoring formula
    formula_match = re.search(r"\*\*Scoring Formula:\*\*\s*(.+?)(?:\n|$)", content)
    scoring_formula = formula_match.group(1).strip() if formula_match else ""

    return subquery_count, scoring_formula


def get_all_role_subqueries() -> Dict[str, Dict[str, Any]]:
    """Get SubQuery data for all available roles.

    Returns:
        Dictionary mapping role names to their SubQuery data.
    """
    roles_dir = ROOT / "data" / "job_descriptions"
    result = {}

    if not roles_dir.exists():
        return result

    for role_dir in roles_dir.iterdir():
        if not role_dir.is_dir():
            continue

        subquery_file = role_dir / f"{role_dir.name}_SubQuery.md"
        if subquery_file.exists():
            try:
                result[role_dir.name] = parse_subquery_document(subquery_file)
            except Exception as e:
                print(f"Error parsing {subquery_file}: {e}")

    return result


def get_role_subquery(role_name: str) -> Optional[Dict[str, Any]]:
    """Get SubQuery data for a specific role.

    Args:
        role_name: Name of the role.

    Returns:
        SubQuery data dictionary or None if not found.
    """
    roles_dir = ROOT / "data" / "job_descriptions"
    subquery_file = roles_dir / role_name / f"{role_name}_SubQuery.md"

    if subquery_file.exists():
        return parse_subquery_document(subquery_file)

    return None


def categorize_requirements(requirements: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Categorize requirements by their category.

    Args:
        requirements: List of requirement dictionaries.

    Returns:
        Dictionary mapping categories to lists of requirements.
    """
    categorized: Dict[str, List[Dict[str, Any]]] = {}

    for req in requirements:
        category = req.get("category", "Unknown")
        if category not in categorized:
            categorized[category] = []
        categorized[category].append(req)

    return categorized


def calculate_category_totals(
    requirements: List[Dict[str, Any]],
    weight_items: Dict[int, float],
) -> Dict[str, Dict[str, Any]]:
    """Calculate category totals based on weight items.

    Args:
        requirements: List of requirement dictionaries.
        weight_items: Dictionary mapping requirement IDs to weight percentages.

    Returns:
        Dictionary with category totals and counts.
    """
    categorized = categorize_requirements(requirements)
    result = {}

    for category, reqs in categorized.items():
        total = sum(weight_items.get(req["id"], 0) for req in reqs)
        rated_count = sum(1 for req in reqs if req["id"] in weight_items)
        unrated_count = len(reqs) - rated_count

        result[category] = {
            "total": total,
            "count": len(reqs),
            "rated_count": rated_count,
            "unrated_count": unrated_count,
            "remaining": 100.0 - total,  # This will be adjusted at global level
        }

    return result
