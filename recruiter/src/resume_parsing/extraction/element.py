# Standard representation of document elements extracted from resumes.
#
# This allows uniform processing of document segments across different
# extraction backends (Docling, Unstructured, OCR).

from dataclasses import dataclass

@dataclass
class ExtractedElement:
    text: str
    element_type: str  # e.g. "heading", "paragraph", "list_item", "table", "title"
    page_number: int
    confidence: float = 1.0
