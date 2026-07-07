from pathlib import Path

import pytest

from src.resume_parsing.parser import _HAS_OCR, parse_resume


# When the optional PDF extraction back-ends (pdfplumber / pypdfium2 via
# src.resume_parsing.ocr) are unavailable, ``parse_resume`` raises a
# RuntimeError on a .pdf path. Skip the test in those environments so
# the suite remains green regardless of which PDF libraries are
# installed — Track 6 reconciliation.
@pytest.mark.skipif(
    not _HAS_OCR,
    reason="src.resume_parsing.ocr is unavailable (pdfplumber/pypdfium2 missing).",
)
def test_parse_resume_extracts_contact_and_name():
    sample_file = Path("data/original/BusinessAnalyst/01888170110d1ccf.pdf")
    profile = parse_resume(sample_file)

    assert profile["name"]["value"] == "John Wood"
    assert "+1-925-885-5155" in profile["contact"]["phones"]
    assert "help@enhancv.com" in profile["contact"]["emails"]
    assert profile["experience"]["entries"]
