"""Unit tests for the file classifier (DEC-035)."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.resume_parsing.extraction.file_classifier import classify_file, FileType


def test_classify_file_not_found():
    """Verify that a FileNotFoundError is raised when the file does not exist."""
    with pytest.raises(FileNotFoundError):
        classify_file("nonexistent_file.pdf")


def test_classify_docx(tmp_path):
    """Verify classification of docx files."""
    file_path = tmp_path / "resume.docx"
    file_path.write_text("dummy docx content")
    assert classify_file(file_path) == FileType.DOCX


def test_classify_txt(tmp_path):
    """Verify classification of text files."""
    file_path = tmp_path / "resume.txt"
    file_path.write_text("dummy text content")
    assert classify_file(file_path) == FileType.TEXT


@patch("src.resume_parsing.extraction.file_classifier._classify_pdf")
def test_classify_pdf_routing(mock_classify, tmp_path):
    """Verify that pdf extension routes to PDF classification."""
    file_path = tmp_path / "resume.pdf"
    file_path.write_text("dummy pdf content")
    mock_classify.return_value = FileType.NATIVE_PDF
    assert classify_file(file_path) == FileType.NATIVE_PDF
    mock_classify.assert_called_once()


def test_classify_pdf_native(tmp_path):
    """Verify native PDF classification when significant text is extracted."""
    file_path = tmp_path / "native.pdf"
    file_path.write_text("dummy pdf text")

    # Mock pdfplumber to return high amount of text (e.g. 200 chars)
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "This is a native PDF document with plenty of extracted text content " * 10
    mock_pdf = MagicMock()
    mock_pdf.pages = [mock_page]

    with patch("pdfplumber.open") as mock_open:
        mock_open.return_value.__enter__.return_value = mock_pdf
        assert classify_file(file_path) == FileType.NATIVE_PDF


def test_classify_pdf_scanned(tmp_path):
    """Verify scanned PDF classification when minimal or no text is extracted."""
    file_path = tmp_path / "scanned.pdf"
    file_path.write_text("dummy scanned pdf")

    # Mock pdfplumber to return very little text
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "Hi"
    mock_pdf = MagicMock()
    mock_pdf.pages = [mock_page]

    with patch("pdfplumber.open") as mock_open:
        mock_open.return_value.__enter__.return_value = mock_pdf
        assert classify_file(file_path) == FileType.SCANNED_PDF


def test_classify_pdf_mixed(tmp_path):
    """Verify mixed PDF classification when some pages have text and others do not."""
    file_path = tmp_path / "mixed.pdf"
    file_path.write_text("dummy mixed pdf")

    # Mock pdfplumber to return text for page 1 and none for page 2
    mock_page1 = MagicMock()
    # Provide a long text for page 1 so total_len exceeds 50 * num_pages = 100
    mock_page1.extract_text.return_value = "Page 1 contains some standard text blocks that are long enough to pass scanned PDF threshold." * 2
    mock_page2 = MagicMock()
    mock_page2.extract_text.return_value = ""
    mock_pdf = MagicMock()
    mock_pdf.pages = [mock_page1, mock_page2]

    with patch("pdfplumber.open") as mock_open:
        mock_open.return_value.__enter__.return_value = mock_pdf
        assert classify_file(file_path) == FileType.MIXED_PDF
