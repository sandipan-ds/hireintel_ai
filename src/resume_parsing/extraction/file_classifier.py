# This file is responsible for classifying input resume files.
#
# It determines if a file is a Native PDF, Scanned PDF, Mixed PDF, DOCX, or Text.
#
# The pipeline later uses this classification to route the file to the
# most accurate extraction engine (e.g. Docling, Unstructured, or PaddleOCR+Surya).

import logging
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

class FileType(str, Enum):
    NATIVE_PDF = "NATIVE_PDF"
    SCANNED_PDF = "SCANNED_PDF"
    MIXED_PDF = "MIXED_PDF"
    DOCX = "DOCX"
    TEXT = "TEXT"

def classify_file(path: str | Path) -> FileType:
    """
    Detect the type of input resume file to determine the best extraction route.

    Args:
        path: Path to the resume file.

    Returns:
        FileType enum indicating native PDF, scanned PDF, mixed, DOCX, or Text.
    """
    path_obj = Path(path)
    if not path_obj.exists():
        raise FileNotFoundError(f"File not found: {path}")

    suffix = path_obj.suffix.lower()

    if suffix in (".docx", ".doc"):
        return FileType.DOCX
    elif suffix in (".txt", ".rtf"):
        return FileType.TEXT
    elif suffix == ".pdf":
        return _classify_pdf(path_obj)
    
    # Default fallback based on suffix
    return FileType.TEXT

def _classify_pdf(path: Path) -> FileType:
    """Classify a PDF file into native, scanned, or mixed."""
    try:
        import pdfplumber
        has_pdfplumber = True
    except ImportError:
        pdfplumber = None
        has_pdfplumber = False

    try:
        import pypdfium2
        has_pypdfium = True
    except ImportError:
        pypdfium = None
        has_pypdfium = False

    if not has_pdfplumber and not has_pypdfium:
        logger.warning("No PDF libraries installed. Defaulting classification to NATIVE_PDF.")
        return FileType.NATIVE_PDF

    page_texts: list[str] = []
    
    # Try pdfplumber first
    if has_pdfplumber:
        try:
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text() or ""
                    page_texts.append(text)
        except Exception as exc:
            logger.warning("pdfplumber failed during classification of %s: %s", path, exc)
            page_texts = []

    # Try pypdfium2 as fallback for text count
    if not page_texts and has_pypdfium:
        try:
            pdf = pypdfium2.PdfDocument(str(path))
            for i in range(len(pdf)):
                page = pdf[i]
                text = page.get_textpage().get_text_range() or ""
                page_texts.append(text)
            pdf.close()
        except Exception as exc:
            logger.warning("pypdfium2 failed during classification of %s: %s", path, exc)

    if not page_texts:
        logger.warning("Could not read any pages from PDF. Classifying as SCANNED_PDF.")
        return FileType.SCANNED_PDF

    total_len = sum(len(t.strip()) for t in page_texts)
    num_pages = len(page_texts)

    # Threshold for scanned vs native: if average chars per page is less than 50
    if total_len < 50 * num_pages:
        return FileType.SCANNED_PDF

    # Check for mixed PDF (some pages have significant text, others have none)
    empty_pages = 0
    text_pages = 0
    for t in page_texts:
        if len(t.strip()) < 50:
            empty_pages += 1
        else:
            text_pages += 1

    if empty_pages > 0 and text_pages > 0:
        return FileType.MIXED_PDF

    return FileType.NATIVE_PDF
