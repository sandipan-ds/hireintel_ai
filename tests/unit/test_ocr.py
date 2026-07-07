"""Unit tests for the hybrid PDF text extractor (Track 6).

Covers:
- Lazy-import availability flags (``_HAS_PDFPLUMBER``, etc.)
- ``extract_text_hybrid`` behavior on a real PDF in the corpus.
- The two empty-text / no-backends RuntimeError paths.
- Each private backend wrapper (``_extract_with_pdfplumber``,
  ``_extract_with_pypdfium``) is exercised on the same real PDF.

The fixture PDF is ``data/original/BusinessAnalyst/01888170110d1ccf.pdf``
(John Wood's resume — same one used by ``test_resume_parser.py``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.resume_parsing import ocr
from src.resume_parsing.ocr import (
    _extract_with_pdfplumber,
    _extract_with_pypdfium,
    _HAS_PDF2IMAGE,
    _HAS_PDFPLUMBER,
    _HAS_PYPDFIUM,
    _HAS_TEXT_LAYER,
    extract_text_hybrid,
)

SAMPLE_PDF = Path("data/original/BusinessAnalyst/01888170110d1ccf.pdf")


# ---------------------------------------------------------------------------
# Availability flags
# ---------------------------------------------------------------------------


def test_text_layer_flag_matches_installed_backends():
    """``_HAS_TEXT_LAYER`` is True iff at least one text-layer backend is installed."""
    assert _HAS_TEXT_LAYER == (_HAS_PDFPLUMBER or _HAS_PYPDFIUM)


def test_pdf2image_flag_has_bool_value():
    """``_HAS_PDF2IMAGE`` is always a bool (never None) for downstream gating."""
    assert isinstance(_HAS_PDF2IMAGE, bool)


# ---------------------------------------------------------------------------
# extract_text_hybrid — happy path
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _HAS_TEXT_LAYER or not SAMPLE_PDF.exists(),
    reason="No text-layer PDF backend or sample PDF missing.",
)
def test_extract_text_hybrid_returns_text_from_real_pdf():
    text = extract_text_hybrid(SAMPLE_PDF)
    # We don't assert specific content (the PDF's text content can shift
    # if the corpus is regenerated); we only assert it isn't empty.
    assert isinstance(text, str)
    assert text.strip(), "Expected non-empty text from a real PDF"


# ---------------------------------------------------------------------------
# extract_text_hybrid — error paths
# ---------------------------------------------------------------------------


def test_extract_text_hybrid_raises_runtime_when_no_backends_installed(monkeypatch):
    """If neither pdfplumber nor pypdfium2 is installed, the call raises.

    We monkeypatch the module-level flags so the RuntimeError path
    executes deterministically regardless of which libraries are
    installed in the test environment.
    """
    monkeypatch.setattr(ocr, "_HAS_PDFPLUMBER", False)
    monkeypatch.setattr(ocr, "_HAS_PYPDFIUM", False)
    with pytest.raises(RuntimeError, match="pdfplumber or pypdfium2"):
        extract_text_hybrid(SAMPLE_PDF)


def test_extract_text_hybrid_raises_runtime_when_all_backends_empty(monkeypatch):
    """If every backend returns empty text, the file is treated as unparsable.

    Monkeypatch the private backends to return empty strings; the
    pdf2image OCR fallback is short-circuited via
    ``_HAS_PDF2IMAGE = False`` so the test runs Poppler-free.
    """
    monkeypatch.setattr(ocr, "_HAS_PDFPLUMBER", True)
    monkeypatch.setattr(ocr, "_HAS_PYPDFIUM", True)
    monkeypatch.setattr(ocr, "_HAS_PDF2IMAGE", False)
    monkeypatch.setattr(ocr, "_extract_with_pdfplumber", lambda _p: "")
    monkeypatch.setattr(ocr, "_extract_with_pypdfium", lambda _p: "")
    with pytest.raises(RuntimeError, match="no extractable text"):
        extract_text_hybrid(SAMPLE_PDF)


# ---------------------------------------------------------------------------
# Private backend wrappers — sanity on the real PDF
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _HAS_PDFPLUMBER or not SAMPLE_PDF.exists(),
    reason="pdfplumber not installed or sample PDF missing.",
)
def test_extract_with_pdfplumber_returns_text_on_real_pdf():
    text = _extract_with_pdfplumber(SAMPLE_PDF)
    assert text.strip(), "pdfplumber produced empty text from a real PDF"


@pytest.mark.skipif(
    not _HAS_PYPDFIUM or not SAMPLE_PDF.exists(),
    reason="pypdfium2 not installed or sample PDF missing.",
)
def test_extract_with_pypdfium_returns_text_on_real_pdf():
    text = _extract_with_pypdfium(SAMPLE_PDF)
    # pypdfium2 sometimes returns empty when pdfplumber succeeds, so we
    # only assert non-empty (the fallback path picks whichever gives
    # text; a pass on each backend in isolation confirms both paths
    # genuinely extract text).
    assert text.strip(), "pypdfium2 produced empty text from a real PDF"
