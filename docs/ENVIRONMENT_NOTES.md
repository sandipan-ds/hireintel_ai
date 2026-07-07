# Environment Notes

## Overview

This document records environment and setup findings for HireIntel AI.

Use this document for Python installation issues, dependency conflicts, IDE issues, build failures, runtime configuration issues, local service setup, and OCR/runtime dependencies.

---

## Current Environment Observations

**Date:** 2026-06-19

**Environment:**
- Windows development workspace
- Python project with Streamlit, FastAPI, OCR, PDF parsing, and AI dependencies

**Notes:**
- OCR utilities depend on `pytesseract`, which requires the Tesseract OCR executable to be installed separately on the machine.
- Resume data may contain PII and should remain outside commits.
- `.venv/`, `data/`, `.history/`, `.checkpoints/`, and local cache directories should remain ignored.
- `docs/` must remain tracked because documentation is part of implementation governance.
- `pytest` currently passes, but local `.pytest_cache/` may emit a Windows cache warning if stale cache artifacts conflict with pytest writes.
- **2026-06-19-PM:** `.venv` was missing `pydantic`, `pydantic-settings`, and `httpx` packages even though they are listed in `requirements.txt`. Fix: run `python -m pip install -r requirements.txt` inside the activated venv, or `python -m pip install pydantic pydantic-settings httpx` for the minimum required set. The graded per-item scorer (`scripts/evaluate_one.py`) and the LLM-powered explanations (`scripts/compare_two.py`) both require these packages.
- **2026-06-19-PM (Phase 4 cleanup):** The legacy `keyword_scorer.py`, `semantic_scorer.py`, `hybrid_scorer.py` modules were removed. The canonical scorer is `src/scoring/graded_scorer.py` (no extra dependencies beyond the standard library). The batch CLI (`python -m src.scoring.batch_score`) and the comparison CLI (`scripts/compare_two.py`) read from `data/scores/graded/`. If you previously had `data/scores/{keyword,semantic,hybrid}/` from an older run, those folders are no longer produced; rerun the batch CLI to regenerate the canonical output.
- **2026-06-19-PM (doc alignment):** `docs/WORKING_LOGIC.md` is now the canonical scoring/evaluation spec. `docs/CURRENT_PROGRESS.md` is the single status doc mapping every step of `WORKING_LOGIC.md` to ✅ / 🟡 / ⬜. All other docs defer to these two for scoring details.

**Prevention Strategy:**
- Add `.env.example` before introducing runtime configuration.
- Document external binaries such as Tesseract in setup instructions.
- Avoid committing raw candidate resumes or generated processing artifacts.
- Clear local pytest cache if cache warnings become noisy.
- Always sync `.venv` with `requirements.txt` after pulling new dependency declarations:
  ```powershell
  .\.venv\Scripts\python.exe -m pip install -r requirements.txt
  ```

---

## PDF extraction back-ends availability

**Date:** 2026-07-06 (Track 6 reconciliation)

**Environment:**
- Windows development workspace
- Python 3.14.4
- venv: `.venv\`

**Available back-ends (probed at runtime via `src/resume_parsing/ocr.py`):**
- `pdfplumber` — installed. High-fidelity text-layer extraction; preserves layout. Default first try.
- `pypdfium2` — installed. Poppler-free fallback; fast. Used when `pdfplumber` produces empty text.
- `pdf2image` — not installed. Optional scanned-PDF OCR bridge. Requires Poppler on the system PATH and an OCR engine (e.g. `pytesseract`).
- `pymupdf` / `fitz` — not installed. Alternative to `pypdfium2`. Not currently wired into `ocr.py`.

**Cause:**
- The optional `src/resume_parsing/ocr.py` module was missing; `parser.py` already gated its import via `try/except ImportError` but no module imported the (installed) back-ends. The parser therefore raised a hard `RuntimeError` whenever a `.pdf` path reached `extract_text_from_path`, even on a machine where `pdfplumber` was already installed.

**Resolution:**
- Created `src/resume_parsing/ocr.py` with availability flags `_HAS_PDFPLUMBER`, `_HAS_PYPDFIUM`, `_HAS_PDF2IMAGE` declared at import time. The hybrid extractor runs `pdfplumber` first, then `pypdfium2`, then `pdf2image` (when installed); raises an informative `RuntimeError` when every strategy returns empty text.
- Installed back-ends are picked up automatically — no environment variables, no extra setup beyond `pip install`.
- The parser's lazy import detects the new module and writes `_HAS_OCR = True` automatically.

**Prevention:**
- Future optional-dependency modules should follow the same pattern: declare availability flags at import time, fail-open at import, fail-closed at call time. This matches `src/resume_parsing/ocr.py` and the existing `pdfplumber` / `pypdfium2` lazy-import branches.
- To enable scanned-PDF OCR support, install `pdf2image` + Poppler + `pytesseract` together. The placeholder OCR invocation in `ocr.py::_extract_with_pdf2image_ocr` is the only code path that needs extension when OCR back-ends are added.

**Required packages (unchanged):**
```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```
`pdfplumber` and `pypdfium2` are already declared in `requirements.txt`, so this command brings back any missing PDF back-end on a fresh clone.

**Test gating:**
- `tests/unit/test_resume_parser.py` carries `pytest.mark.skipif(not _HAS_OCR, reason="...")` so the suite is green in environments that have no PDF back-end installed.
- `tests/unit/test_ocr.py` carries the same guard for the real-PDF extraction paths (kept as 4 skip-marked tests when back-ends are missing).
