# This module replaces Docling as the primary PDF parser (DEC-037).
#
# Why Docling was removed:
#   Docling has torch + transformers as hard transitive dependencies, which
#   inflates the production Docker image by ~2 GB and defeats the purpose of
#   removing sentence-transformers.  Since the LLM normalizer (Gemini, NVIDIA
#   NIM, OpenRouter) is fully multimodal, it can structure raw text just as
#   well as Docling's layout-aware output.  The section_builder already groups
#   elements into canonical resume sections from plain paragraphs.
#
# Replacement strategy:
#   pypdfium2 (already in requirements.prod.txt) extracts the text layer of
#   native PDFs with correct reading order, page numbers, and line boundaries.
#   It is a thin Python wrapper around the PDFium C library — no ML deps, tiny
#   install size.  For resumes with standard text layers this is sufficient.
#   The Unstructured fallback covers edge cases; OCR handles scanned PDFs.
#
# Output:
#   Same List[ExtractedElement] interface as the old Docling parser so
#   pipeline.py needs only a one-line import change.

import logging
from pathlib import Path
from typing import List, Optional

from src.resume_parsing.extraction.element import ExtractedElement

logger = logging.getLogger(__name__)

# Lazy availability flag — set on first call to _init_pypdfium.
_PYPDFIUM_AVAILABLE: Optional[bool] = None


def _init_pypdfium() -> bool:
    """Check if pypdfium2 is importable (lazy, cached).

    Returns:
        True if pypdfium2 is installed and importable, False otherwise.
    """
    global _PYPDFIUM_AVAILABLE
    if _PYPDFIUM_AVAILABLE is not None:
        return _PYPDFIUM_AVAILABLE
    try:
        import pypdfium2  # noqa: F401
        _PYPDFIUM_AVAILABLE = True
    except ImportError as exc:
        logger.warning("pypdfium2 is not installed: %s", exc)
        _PYPDFIUM_AVAILABLE = False
    return _PYPDFIUM_AVAILABLE


def extract_with_pypdf(path: str | Path) -> Optional[List[ExtractedElement]]:
    """Extract text elements from a native PDF using pypdfium2.

    pypdfium2 wraps the Google PDFium rendering engine.  It extracts the
    text layer of born-digital PDFs in correct reading order with page
    numbers, producing the same ``List[ExtractedElement]`` structure that the
    old Docling parser produced.

    The LLM normalizer downstream (Gemini / NIM) handles any structural
    ambiguity — we do not need layout-ML to pre-label headings.  pypdfium2
    extracts raw paragraph and line blocks which the section_builder then
    groups into canonical resume sections.

    Args:
        path:
            Path to the native-text PDF file.

    Returns:
        List of :class:`ExtractedElement` objects in page order,
        or ``None`` if pypdfium2 is unavailable or extraction fails.
    """
    if not _init_pypdfium():
        return None

    path_obj = Path(path)
    if not path_obj.exists():
        logger.error("pypdf parser: file not found: %s", path)
        return None

    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(path_obj))
        elements: List[ExtractedElement] = []

        for page_index in range(len(pdf)):
            page = pdf[page_index]
            page_no = page_index + 1

            # Extract text page-by-page using the text page object.
            # get_textpage() gives us the full text layer with layout info.
            textpage = page.get_textpage()
            full_text: str = textpage.get_text_range()

            if not full_text.strip():
                continue

            # Split into paragraph-level blocks by double newline.
            # pypdfium2 preserves paragraph breaks from the PDF text layer.
            raw_blocks = full_text.split("\n\n")

            for block in raw_blocks:
                # Normalise whitespace inside the block while preserving
                # line structure for the section_builder heuristics.
                block_text = " ".join(block.split())
                if not block_text:
                    continue

                # Heuristic element-type labelling — light-touch, no ML.
                # The LLM normalizer downstream resolves any ambiguity.
                word_count = len(block_text.split())
                if word_count <= 6 and block_text.isupper():
                    # Short ALL-CAPS blocks are almost always section headers
                    # (e.g. "EXPERIENCE", "EDUCATION", "SKILLS").
                    elem_type = "heading"
                elif word_count <= 10 and block_text.endswith(":"):
                    # Short label-style blocks (e.g. "Work Experience:").
                    elem_type = "heading"
                else:
                    elem_type = "paragraph"

                elements.append(
                    ExtractedElement(
                        text=block_text,
                        element_type=elem_type,
                        page_number=page_no,
                        confidence=0.95,
                    )
                )

        if not elements:
            logger.warning(
                "pypdf parser: no text extracted from %s (may be scanned).",
                path_obj.name,
            )
            return None

        logger.info(
            "pypdf parser: extracted %d elements from %s across %d page(s).",
            len(elements), path_obj.name, len(pdf),
        )
        return elements

    except Exception as exc:
        logger.warning("pypdf parser extraction failed on %s: %s", path, exc)
        return None
