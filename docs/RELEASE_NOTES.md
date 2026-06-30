# Release Notes

## Overview

This document tracks notable changes to HireIntel AI, including features, fixes, breaking changes, documentation updates, and version history.

---

## Unreleased

### Added — 2026-06-30: Two-mode scoring engine + foundation modules

- **Header Normalization** (`src/resume_parsing/header_normalization.py`) — Layer 1 synonym table + Layer 2 LLM fallback for 7 canonical sections (Personal_Info, Education, Experience, Projects, Skills, Certifications, Languages). 24 tests.
- **Chunk Metadata Schema** (`src/rag/chunker.py` updated) — `section_type`, `parent_structure` (organization, role_title, location, temporal_context with `calculated_duration_months`), `skills_asserted`, `experience_type`. Deterministic date parsing. 33 tests.
- **Structured Candidate Profile** (`src/resume_parsing/structured_profile.py`) — Degrees, institutions, certifications, total experience (no double-counting of overlapping roles), companies, roles, employment dates. Separate deterministic record. 14 tests.
- **Section-Routed Evidence Retrieval** (`src/rag/section_routed.py`) — Fixed requirement→section mapping table, exact label match, no embeddings/cosine, metadata filtering for long sections. 44 tests.
- **Rubric Templates** (`src/scoring/rubrics.py`) — 12 templates with anchored scales (0.0/0.25/0.5/0.75/1.0), sub-questions, formulas per dimension type. 47 tests.
- **Rubric-Bound LLM Scorer** (`src/scoring/rubric_scorer.py`) — RUBRIC-SCORE-001 prompt (weight excluded, extract-before-score, anchored scales), `CachedScoringTrace`, `explain_score_from_cache`. 27 tests.
- **Unified Scorer** (`src/scoring/unified_scorer.py`) — Routes each requirement to code-only or rubric-bound LLM, produces `UnifiedCandidateEvaluation` with per-item `scoring_mode` + `scoring_trace`. 14 tests.
- **Tier Databases** — `data/Institutes/institute_tiers.json` (115 Tier 1, 54 Tier 2, 155 Tier 3), `data/Certificates/certificate_tiers.json` (115 Tier 1, 45 Tier 2, 10 Tier 3), `src/scoring/tier_lookup.py`. 49 tests.
- **279 unit tests total** across all new modules.
- `pyproject.toml` dependencies populated (numpy, sentence-transformers, pdfplumber, pypdfium2, pytesseract, Pillow, reportlab, pydantic, pydantic-settings, httpx, streamlit, fastapi).

### Changed — 2026-06-30
- `WORKING_LOGIC.md` — tier system updated from 4 tiers (A/B/C/D) to 3 tiers (1/2/3) + not-listed=0.50.
- `CURRENT_PROGRESS.md` — all foundation modules and scoring modes marked ✅.
- `MODEL_REGISTRY.md` — registered all new modules.
- `PROMPT_LIBRARY.md` — RUBRIC-SCORE-001 marked Active (v1.0).
- `IMPLEMENTATION_ROADMAP.md` — Phase 4 updated with two-mode design, Phase 4.6 added for foundation modules, Phase 4.5 refocused on pipeline rewiring.
- `ARCHITECTURE_CHANGELOG.md` — 2026-06-30 entry added.
- `SYSTEM_ARCHITECTURE.md` — Scoring Engine section updated.
- 21 stub/duplicate files deleted (see ARCHITECTURE_CHANGELOG.md).
- `data/processed`, `data/chunks`, `data/embeddings`, `data/scores` deleted for fresh regeneration.
- `data/original/` role folders renamed (Sales→SalesManager, PythonDeveloper→SrPythonDeveloper).

### Added — 2026-06-19 (earlier unreleased)

### Added — 2026-06-30: Doc-code alignment fixes
- **PROMPT_LIBRARY.md** — RESUME-CHAT-001 status corrected from "Active" to "Planned" (no chat method implemented in code).
- **CURRENT_PROGRESS.md** — Resume Chat section corrected: fallback ✅→⬜, RAG grounding 🟡→⬜. Score Explanation 🟡→⬜. Candidate Comparison LLM ✅→🟡.
- **MODEL_REGISTRY.md** — Active LLM purpose corrected: removed "rubric-bound evidence scoring" attribution from `service.py` (not implemented there; implemented in `rubric_scorer.py`).
- **PROJECT_OVERVIEW.md** — Trimmed duplicated sections (How Scorer Works, Eval Framework, RAG Architecture). Added two-mode scoring summary. Fixed RAG/cosine distinction.
- **AI_ARCHITECTURE.md** — Added §2a Structured Profile, §5 two-mode design with dimension table, §5.2 rubric-bound LLM scoring, §9a Header Normalization, §11 split into §11a Section-Routed + §11b Dense Cosine, §12a cached reasoning. Removed stale `semantic_scorer.py` reference.
- **AI_DESIGN_RATIONALE.md** — Fixed §1 (semantic chunking→deterministic metadata filtering), §2 (stale semantic scorer ref), §4 (LLM identity: minimax-m3 active, GPT-4 proposed), §6 (hybrid search is pool-level only).
- **EVALUATION.md** — Added rubric-bound LLM evidence scoring metrics (rubric adherence, LLM judge consistency, weight blindness, no-aggregation compliance, double-count detection, sub-score calibration).
- **DECISIONS.md** — DEC-010 updated with two-mode scoring design.
- **ARCHITECTURE_CHANGELOG.md** — Fixed stale `data/scores/hybrid/` reference.

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
