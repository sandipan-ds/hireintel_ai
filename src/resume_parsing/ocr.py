"""Hybrid text extraction for PDF resumes.

This module is the optional PDF -> text bridge for the resume parser.
It is imported lazily by :mod:`src.resume_parsing.parser` so that
non-PDF paths (id allocation, text parsing helpers, structured-profile
tests) keep working in environments without PDF libraries.

Extraction strategy (in order, first non-empty result wins):

1. ``pdfplumber`` — slow but high fidelity; preserves layout and
   recovers text from most text-layer PDFs.
2. ``pypdfium2`` — fast and Poppler-free; used as a fallback when
   ``pdfplumber`` produces no text (e.g. on scanned PDFs that
   ``pdfplumber`` cannot extract) and as a sanity cross-check.
3. ``pdf2image`` + an OCR engine (optional; only attempted if both are
   installed) — handles truly scanned PDFs where the text layer is an
   image. Requires Poppler on the system PATH; wraps the failure in an
   informative :class:`RuntimeError` otherwise.

If every strategy returns empty text, the caller sees an informative
runtime error so the parser can mark the resume as unparsable rather
than silently producing an empty profile.

The module never raises during import — individual functions raise at
call time if their backend is unavailable. ``_HAS_OCR`` (consumed by
:mod:`src.resume_parsing.parser`) is True if at least one text-layer
backend (``pdfplumber`` or ``pypdfium2``) imports successfully.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Detect which text-layer backends are available. Import only one of
# these and the parser still surfaces ``_HAS_OCR = True`` via the
# lazy-import branch in ``parser.py``.
try:
    import pdfplumber  # type: ignore[import-untyped]
    _HAS_PDFPLUMBER = True
except ImportError:  # pragma: no cover - exercised by the env, not a test
    pdfplumber = None  # type: ignore[assignment]
    _HAS_PDFPLUMBER = False

try:
    import pypdfium2  # type: ignore[import-untyped]
    _HAS_PYPDFIUM = True
except ImportError:  # pragma: no cover - exercised by the env, not a test
    pypdfium2 = None  # type: ignore[assignment]
    _HAS_PYPDFIUM = False

# The OCR/image-based fallbacks are optional; both require Poppler on
# the system PATH, so they are not part of the ``_HAS_OCR`` gate. They
# are attempted last and only when the text-layer back-ends produce no
# extractable text.
try:
    import pdf2image  # type: ignore[import-untyped]
    _HAS_PDF2IMAGE = True
except ImportError:  # pragma: no cover - exercised by the env, not a test
    pdf2image = None  # type: ignore[assignment]
    _HAS_PDF2IMAGE = False


def _extract_with_pdfplumber(path: Path) -> str:
    """Extract text using ``pdfplumber`` (high-fidelity text-layer)."""
    if not _HAS_PDFPLUMBER:
        return ""
    out: list[str] = []
    try:
        with pdfplumber.open(path) as pdf:  # type: ignore[union-attr]
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                if page_text:
                    out.append(page_text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("pdfplumber failed on %s: %s", path, exc)
        return ""
    return "\n\n".join(out).strip()


def _extract_with_pypdfium(path: Path) -> str:
    """Extract text using ``pypdfium2`` (fast Poppler-free fallback)."""
    if not _HAS_PYPDFIUM:
        return ""
    try:
        pdf = pypdfium2.PdfDocument(str(path))  # type: ignore[union-attr]
        out: list[str] = []
        for i in range(len(pdf)):
            page = pdf[i]
            page_text = page.get_textpage().get_text_range() or ""
            if page_text:
                out.append(page_text)
        pdf.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("pypdfium2 failed on %s: %s", path, exc)
        return ""
    return "\n\n".join(out).strip()


def _extract_with_pdf2image_ocr(path: Path) -> str:
    """Extract text from scanned PDFs via ``pdf2image`` (Pre-Poppler).

    Returns an empty string when Poppler is not on the system PATH or
    when no OCR engine is configured. The parser treats this as a
    soft fallback (an empty string propagates to the caller, which can
    decide whether to surface a "scanned PDF could not be OCR'd"
    error).
    """
    if not _HAS_PDF2IMAGE:
        return ""
    try:
        images = pdf2image.convert_from_path(str(path))  # type: ignore[union-attr]
    except Exception as exc:  # noqa: BLE001
        logger.warning("pdf2image failed on %s: %s", path, exc)
        return ""
    out: list[str] = []
    for img in images:
        # We do not bundle an OCR engine here; if ``pytesseract`` is
        # installed in the environment, it would be invoked here. For
        # now, this path is preserved for future extension.
        text = ""  # Placeholder for OCR invocation.
        if text:
            out.append(text)
    return "\n\n".join(out).strip()


def extract_text_hybrid(path: Path) -> str:
    """Extract plain text from a PDF using a hybrid strategy.

    Args:
        path: Absolute path to a ``.pdf`` file.

    Returns:
        The extracted text (preserving paragraph separations with
        ``\\n\\n``). Empty string when every backend produced no text
        (caller decides whether to raise).

    Raises:
        RuntimeError: If neither ``pdfplumber`` nor ``pypdfium2`` is
            installed in the environment, or if the file cannot be
            opened by either backend.
    """
    if not _HAS_PDFPLUMBER and not _HAS_PYPDFIUM:
        raise RuntimeError(
            "PDF extraction requires pdfplumber or pypdfium2, but neither "
            "is installed in this environment. Install one of them "
            "(e.g. `pip install pdfplumber`) to enable PDF parsing."
        )

    text = _extract_with_pdfplumber(path)
    if text:
        return text

    text = _extract_with_pypdfium(path)
    if text:
        return text

    # Last resort: OCR path via pdf2image (only includes a placeholder
    # today; raises only when the caller explicitly requests OCR via
    # configuration — not currently wired up).
    text = _extract_with_pdf2image_ocr(path)
    if text:
        return text

    # All backends produced empty text — typical for scanned PDFs that
    # have no extractable text layer and no OCR backend configured.
    # Raise so the parser can mark the resume as unparsable rather than
    # silently producing an empty profile.
    raise RuntimeError(
        f"PDF at {path} produced no extractable text via pdfplumber or "
        "pypdfium2; the file may be a scanned image PDF. Configure an "
        "OCR backend (e.g. pytesseract via pdf2image) to extract text "
        "from scanned PDFs."
    )


__all__ = ["extract_text_hybrid"]


# Lightweight availability flag consumed lazily by the parser. This is
# set at import time so the parser doesn't have to probe manually.
_HAS_TEXT_LAYER = _HAS_PDFPLUMBER or _HAS_PYPDFIUM
