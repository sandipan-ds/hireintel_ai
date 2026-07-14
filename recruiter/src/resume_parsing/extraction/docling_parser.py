# This module is responsible for parsing native text PDFs using Docling.
#
# Docling is used as the primary parser because of its layout-aware
# document-structure recovery.

import logging
from pathlib import Path
from typing import Optional, List

from src.resume_parsing.extraction.element import ExtractedElement

logger = logging.getLogger(__name__)

# Lazy imports flag
_DOCLING_AVAILABLE: Optional[bool] = None

def _init_docling():
    """Check if Docling is installed and try to initialize."""
    global _DOCLING_AVAILABLE
    if _DOCLING_AVAILABLE is not None:
        return _DOCLING_AVAILABLE

    try:
        from docling.document_converter import DocumentConverter
        _DOCLING_AVAILABLE = True
    except ImportError as exc:
        logger.warning("Docling is not installed or failed to import: %s", exc)
        _DOCLING_AVAILABLE = False
    return _DOCLING_AVAILABLE

def extract_with_docling(path: str | Path) -> Optional[List[ExtractedElement]]:
    """
    Extract structured elements from a native PDF using Docling.

    Args:
        path: Path to the PDF file.

    Returns:
        List of ExtractedElement objects, or None if Docling is unavailable/fails.
    """
    if not _init_docling():
        return None

    path_obj = Path(path)
    if not path_obj.exists():
        logger.error("Docling parser target not found: %s", path)
        return None

    try:
        from docling.document_converter import DocumentConverter
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import PdfFormatOption
        
        # Configure Docling pipeline options to focus on layout elements
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = False  # OCR is handled by our dedicated OCR path
        pipeline_options.do_table_structure = True  # Preserve structured tables
        
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
        
        result = converter.convert(str(path_obj))
        doc = result.document

        elements: List[ExtractedElement] = []
        
        # Iterate document elements in reading order
        for element, _level in doc.iterate_items():
            text = getattr(element, "text", "").strip()
            if not text:
                # Handle tables specifically, which may have structure but not a flat text field
                if hasattr(element, "export_to_dataframe"):
                    try:
                        df = element.export_to_dataframe()
                        text = df.to_markdown()
                    except Exception:
                        text = ""
                else:
                    continue

            # Determine element type
            cls_name = element.__class__.__name__.lower()
            if "heading" in cls_name or "header" in cls_name:
                elem_type = "heading"
            elif "list" in cls_name:
                elem_type = "list_item"
            elif "table" in cls_name:
                elem_type = "table"
            elif "title" in cls_name:
                elem_type = "title"
            else:
                elem_type = "paragraph"

            # Extract page number from provenance if available
            page_no = 1
            prov = getattr(element, "prov", None)
            if prov and len(prov) > 0:
                page_no = getattr(prov[0], "page_no", 1)

            elements.append(
                ExtractedElement(
                    text=text,
                    element_type=elem_type,
                    page_number=page_no
                )
            )

        return elements

    except Exception as exc:
        logger.warning("Docling extraction failed on %s: %s", path_obj, exc)
        return None
