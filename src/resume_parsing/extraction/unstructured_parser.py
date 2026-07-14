# This module is responsible for parsing files using Unstructured.
#
# Unstructured is used as a fallback parser or for element-level processing.

import logging
from pathlib import Path
from typing import Optional, List

from src.resume_parsing.extraction.element import ExtractedElement

logger = logging.getLogger(__name__)

# Lazy imports flag
_UNSTRUCTURED_AVAILABLE: Optional[bool] = None

def _init_unstructured():
    """Check if Unstructured is installed and try to initialize."""
    global _UNSTRUCTURED_AVAILABLE
    if _UNSTRUCTURED_AVAILABLE is not None:
        return _UNSTRUCTURED_AVAILABLE

    try:
        from unstructured.partition.auto import partition
        _UNSTRUCTURED_AVAILABLE = True
    except ImportError as exc:
        logger.warning("Unstructured is not installed or failed to import: %s", exc)
        _UNSTRUCTURED_AVAILABLE = False
    return _UNSTRUCTURED_AVAILABLE

def extract_with_unstructured(path: str | Path) -> Optional[List[ExtractedElement]]:
    """
    Extract structured elements using Unstructured.

    Args:
        path: Path to the resume file.

    Returns:
        List of ExtractedElement objects, or None if Unstructured is unavailable/fails.
    """
    if not _init_unstructured():
        return None

    path_obj = Path(path)
    if not path_obj.exists():
        logger.error("Unstructured parser target not found: %s", path)
        return None

    try:
        from unstructured.partition.auto import partition

        # Convert document
        raw_elements = partition(filename=str(path_obj))
        
        elements: List[ExtractedElement] = []
        for raw_el in raw_elements:
            text = str(raw_el).strip()
            if not text:
                continue

            # Map categories
            category = getattr(raw_el, "category", "paragraph").lower()
            
            if "title" in category or "header" in category:
                elem_type = "heading"
            elif "listitem" in category or "list_item" in category:
                elem_type = "list_item"
            elif "table" in category:
                elem_type = "table"
            else:
                elem_type = "paragraph"

            # Page number
            page_no = 1
            metadata = getattr(raw_el, "metadata", None)
            if metadata:
                page_no = getattr(metadata, "page_number", 1) or 1

            elements.append(
                ExtractedElement(
                    text=text,
                    element_type=elem_type,
                    page_number=page_no
                )
            )

        return elements

    except Exception as exc:
        logger.warning("Unstructured extraction failed on %s: %s", path_obj, exc)
        return None
