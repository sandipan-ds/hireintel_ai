# Release Notes

## Overview

This document tracks notable changes to HireIntel AI, including features, fixes, breaking changes, documentation updates, and version history.

---

## Unreleased

### Added
- **Phase 5: Candidate Ranking & Comparison** — `scripts/compare_two.py` generates recruiter-friendly side-by-side candidate comparisons.
  - Loads two candidate profiles and hybrid scores.
  - Displays component breakdown (matched requirements count, top strengths).
  - Generates deterministic "Why A ranked above B" narrative.
  - Evidence-backed explanations with no LLM black-box ranking.
  - 6 integration tests passing; handles invalid candidates gracefully.

### Changed
- Documentation requirements now align with the current source-of-truth documents in `docs/`.
- Implementation roadmap now includes a foundation code structure phase before feature work.
- Standardized product-facing naming on `HireIntel AI`.

### Fixed
- Removed `docs/` from `.gitignore` so documentation can be tracked as required by `AGENTS.md`.

### Breaking Changes
- None.

---

## Phase 3 — Resume Parsing (shipped 2026-06-19)

### Added
- `src/resume_parsing/parser.py` — Document-Aware structured profile parser. Produces JSON profile with `candidate_id`, `raw_text`, `sections` (with char spans), `name`, `contact`, `summary`, `experience` (raw + entries + count), `education` (raw + entries + count), `skills`, `certifications`, `projects`, `languages`, `source_file`.
- `src/resume_parsing/ocr.py` — Hybrid text extraction: `pdfplumber` first, OCR fallback via `pypdfium2` (no Poppler required) → `pdf2image` (with Poppler) → informative error.
- `src/resume_parsing/batch_parse.py` — CLI: parses every PDF in `data/original/<role>/` and writes `data/processed/<role>/<name>.json`.
- `tests/unit/test_resume_parser.py` — unit test suite; passing.
- 721 resume profiles successfully parsed across 8 role folders.

### Changed
- Parser applies strict `_looks_like_name` filter rejecting locations, form labels, dates, and punctuation — significantly improves name quality on OCR-garbled PDFs.
- Section detection is heading-anchored and prevents overlapping section spans (verified: 0 overlapping section pairs across 721 profiles).
- Experience entry parsing attaches dates to the same entry as the preceding title line.

### Fixed
- Regex bug in phone extraction.
- Optional `pdf2image` dependency failure replaced with informative error message.
- pytest import path resolved via `conftest.py`.

---

## Phase 4 + 5 — Candidate Evaluation Engine (shipped 2026-06-19)

### Added
- `src/rag/chunker.py` — Document-Aware chunker. One chunk per experience/education/project entry, list-joined chunks for skills/certifications/languages, sub-split at 1200 chars with 120-char overlap.
- `src/rag/batch_chunk.py` — CLI: writes `data/chunks/<role>/<candidate_id>.jsonl`.
- `src/rag/embeddings.py` — `sentence-transformers/all-MiniLM-L6-v2` wrapper with cosine similarity helper.
- `src/rag/index.py` — In-memory vector index over chunks (`data/embeddings/index.npz`).
- `src/rag/retriever.py` — High-level `retrieve(query, top_k, role_bucket)` + `retrieve_for_candidate`.
- `src/rag/build_index.py` — CLI to (re)build the index.
- `src/rag/jd_match.py` — JD-bullet → chunk cosine matching. Ranks candidates against a JD.
- `src/scoring/keyword_scorer.py` (renamed from `evaluate.py`) — Deterministic keyword + heuristic scorer. Per-item binary match, normalize to 100. Per-component evidence links to `chunk_id` + `source_file`.
- `src/scoring/semantic_scorer.py` — **New strategy.** JD-bullet → candidate's chunks cosine. `score = mean(max_cosine) × 100`.
- `src/scoring/hybrid_scorer.py` — **New strategy.** `final = α × keyword + (1-α) × semantic`, default `α = 0.5`.
- `src/scoring/evaluate.py` — Re-export shim so existing imports keep working.
- `src/scoring/evidence.py` — Evidence aggregation helpers + plain-text explanation.
- `src/scoring/batch_score.py` — CLI: `--strategy {keyword, semantic, hybrid}` + `--alpha`.
- `tests/unit/test_chunker.py`, `test_scoring.py`, `test_semantic_scorer.py`, `test_hybrid_scorer.py`, `tests/integration/test_jd_match.py`.
- `scripts/demo_jd_match.py`, `scripts/demo_scoring.py`, `scripts/compare_scores.py`.
- **4,083 chunks** generated from 721 resumes.
- **Vector index** persisted (4,083 × 384 dims ≈ 6 MB).

### Changed
- Three independent scoring strategies now available; each writes to its own `data/scores/<strategy>/<role>_ranked.json` folder.
- `Model Registry` and `AI Design Rationale` updated to document MiniLM-L6-v2 as the active embedding model and the three-strategy scoring design.

### Breaking Changes
- `src/scoring/evaluate.py` is now a re-export shim. Direct imports of internals (`score_item`, etc.) still work via the shim but should migrate to `src.scoring.keyword_scorer` over time.
- Batch scoring output moved from `data/scores/<role>_ranked.json` to `data/scores/<strategy>/<role>_ranked.json`.

---
