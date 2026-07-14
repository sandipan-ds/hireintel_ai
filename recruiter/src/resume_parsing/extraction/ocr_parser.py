# This module handles layout-aware OCR for scanned and image-heavy PDF resumes.
#
# It can utilize PaddleOCR + Surya, falling back to ONNX-based RapidOCR
# when CUDA compilation dependencies prevent installing PaddleOCR/Surya.
#
# It uses pypdfium2 to render PDF pages directly to PIL images, avoiding
# Poppler installation dependencies required by pdf2image.

import logging
from pathlib import Path
from typing import Optional, List

from src.resume_parsing.extraction.element import ExtractedElement

logger = logging.getLogger(__name__)

# Lazy import flags
_PADDLEOCR_AVAILABLE: Optional[bool] = None
_SURYA_AVAILABLE: Optional[bool] = None
_RAPIDOCR_AVAILABLE: Optional[bool] = None
_PYPDFIUM_AVAILABLE: Optional[bool] = None

def _init_libraries():
    """Lazily verify which libraries are available."""
    global _PADDLEOCR_AVAILABLE, _SURYA_AVAILABLE, _RAPIDOCR_AVAILABLE, _PYPDFIUM_AVAILABLE
    
    if _PADDLEOCR_AVAILABLE is None:
        try:
            from paddleocr import PaddleOCR
            _PADDLEOCR_AVAILABLE = True
        except ImportError:
            _PADDLEOCR_AVAILABLE = False
            
    if _SURYA_AVAILABLE is None:
        try:
            from surya.inference import SuryaInferenceManager
            from surya.layout import LayoutPredictor
            _SURYA_AVAILABLE = True
        except ImportError:
            _SURYA_AVAILABLE = False

    if _RAPIDOCR_AVAILABLE is None:
        try:
            from rapidocr import RapidOCR
            _RAPIDOCR_AVAILABLE = True
        except ImportError:
            _RAPIDOCR_AVAILABLE = False

    if _PYPDFIUM_AVAILABLE is None:
        try:
            import pypdfium2 as pdfium
            _PYPDFIUM_AVAILABLE = True
        except ImportError:
            _PYPDFIUM_AVAILABLE = False

def extract_with_ocr(path: str | Path) -> Optional[List[ExtractedElement]]:
    """
    Extract structured elements using OCR. Matches layout-aware reading order.

    Args:
        path: Path to the scanned PDF or image resume.

    Returns:
        List of ExtractedElement objects, or None if OCR is unavailable/fails.
    """
    # Lazy imports: numpy and PIL are only needed here (OCR path).
    # Importing them at module level would crash the whole pipeline on startup
    # for environments where Pillow/numpy is not installed, even for native PDFs
    # that never reach this function.
    import numpy as np  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    _init_libraries()

    path_obj = Path(path)
    if not path_obj.exists():
        logger.error("OCR parser target not found: %s", path)
        return None

    # Step 1: Render PDF pages to PIL Images
    images: List[Image.Image] = []
    if path_obj.suffix.lower() == ".pdf":
        if not _PYPDFIUM_AVAILABLE:
            logger.error("pypdfium2 is required to render scanned PDF pages.")
            return None
        try:
            import pypdfium2 as pdfium
            pdf = pdfium.PdfDocument(str(path_obj))
            for i in range(len(pdf)):
                page = pdf[i]
                # Render at 150 DPI (scale=2.0) for good OCR accuracy
                bitmap = page.render(scale=2.0)
                images.append(bitmap.to_pil())
            pdf.close()
        except Exception as exc:
            logger.error("Failed to render PDF pages with pypdfium2: %s", exc)
            return None
    else:
        # Assume it is a direct image file
        try:
            images.append(Image.open(path_obj).convert("RGB"))
        except Exception as exc:
            logger.error("Failed to open image file: %s", exc)
            return None

    if not images:
        return []

    # Step 2: Attempt PaddleOCR + Surya (if available)
    if _PADDLEOCR_AVAILABLE and _SURYA_AVAILABLE:
        try:
            return _extract_paddle_surya(images)
        except Exception as exc:
            logger.warning("PaddleOCR + Surya route failed, trying RapidOCR fallback: %s", exc)

    # Step 3: Attempt RapidOCR (if available)
    if _RAPIDOCR_AVAILABLE:
        try:
            return _extract_rapidocr(images)
        except Exception as exc:
            logger.error("RapidOCR failed: %s", exc)
            
    logger.error("No working OCR engine available to parse scanned resume.")
    return None

def _extract_paddle_surya(images: List["Image.Image"]) -> List[ExtractedElement]:
    """Extract elements using PaddleOCR + Surya."""
    import numpy as np  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415
    from paddleocr import PaddleOCR
    from surya.inference import SuryaInferenceManager
    from surya.layout import LayoutPredictor

    # Initialize engines
    ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
    inference_manager = SuryaInferenceManager()
    layout_predictor = LayoutPredictor(inference_manager)

    elements: List[ExtractedElement] = []

    for page_idx, img in enumerate(images):
        page_no = page_idx + 1
        
        # Get page layout + reading order from Surya
        layout_preds = layout_predictor([img])
        if not layout_preds:
            continue
            
        page_pred = layout_preds[0]
        
        # Convert PIL image to numpy for PaddleOCR
        img_np = np.array(img)
        
        # For each layout block detected by Surya, run PaddleOCR to extract text
        for block in page_pred.bboxes:
            bbox = block.bbox  # [x1, y1, x2, y2]
            
            # Crop image to layout block
            crop_img = img.crop((bbox[0], bbox[1], bbox[2], bbox[3]))
            crop_np = np.array(crop_img)
            
            # Run OCR on block
            ocr_res = ocr.ocr(crop_np, cls=True)
            if not ocr_res or not ocr_res[0]:
                continue
                
            block_texts = []
            block_scores = []
            for line in ocr_res[0]:
                line_text = line[1][0]
                line_score = line[1][1]
                block_texts.append(line_text)
                block_scores.append(line_score)
                
            text = "\n".join(block_texts).strip()
            if not text:
                continue

            # Map Surya labels to standard element types
            label = block.label.lower()
            if "heading" in label or "title" in label:
                elem_type = "heading"
            elif "list" in label:
                elem_type = "list_item"
            elif "table" in label:
                elem_type = "table"
            else:
                elem_type = "paragraph"
                
            avg_score = float(np.mean(block_scores)) if block_scores else 1.0

            elements.append(
                ExtractedElement(
                    text=text,
                    element_type=elem_type,
                    page_number=page_no,
                    confidence=avg_score
                )
            )

    return elements

def _extract_rapidocr(images: List["Image.Image"]) -> List[ExtractedElement]:
    """Extract elements using RapidOCR (highly robust ONNX model)."""
    import numpy as np  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415
    from rapidocr import RapidOCR
    engine = RapidOCR()
    
    elements: List[ExtractedElement] = []

    for page_idx, img in enumerate(images):
        page_no = page_idx + 1
        
        # Convert PIL image to numpy
        img_np = np.array(img)
        
        # RapidOCR returns a RapidOCROutput dataclass
        out = engine(img_np)
        if not out or not out.txts:
            continue

        # Group lines that are visually close or treat them as paragraphs/list items
        # RapidOCR doesn't do complex layout taxonomy out of the box,
        # so we map lines directly to standard elements.
        for txt, bbox, score in zip(out.txts, out.boxes, out.scores):
            txt = txt.strip()
            if not txt:
                continue

            # Heuristic element mapping based on text structure
            if len(txt) < 80 and (txt.isupper() or txt.istitle()):
                elem_type = "heading"
            elif txt.startswith(("- ", "* ", "• ", "1. ", "2. ")):
                elem_type = "list_item"
            else:
                elem_type = "paragraph"

            elements.append(
                ExtractedElement(
                    text=txt,
                    element_type=elem_type,
                    page_number=page_no,
                    confidence=float(score)
                )
            )

    return elements
