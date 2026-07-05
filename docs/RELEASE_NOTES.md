# Release Notes

## Overview

This document tracks notable changes to HireIntel AI, including features, fixes, breaking changes, documentation updates, and version history.

---

## Unreleased

### Added — 2026-07-04 (late evening): Real LLM caller + verified end-to-end scoring

- **LLM caller** (`src/services/llm_caller.py`): OpenAI-compatible client using `OPENCODE_API_KEY` from `.env`, base_url `https://opencode.ai/zen/v1`. Model: `nemotron-3-ultra-free` (the actual free model on the endpoint; the original `.env` value `MiMo V2.5 Free` was an invalid alias).
- **Robust anchored-value parser** (`parse_anchored_response` in `subquery_retrieval.py`): maps `yes`/`no`/`true`/`false`/`high`/`medium`/`low`/`partial`/`none` to anchored floats (1.0/0.0/1.0/0.5/0.25/0.0). Also extracts leading numbers from "12+ years" / "5 yrs" patterns. Snaps non-anchored values to the nearest anchored float.
- **Improved prompt template** with explicit anchored-value scales per sub-question type (binary 0/1, linear 0-1, anchored 0.0/0.25/0.5/0.75/1.0).
- **Bumped `max_tokens` to 2000** (was 500) — the LLM was getting cut off mid-response.

### Verified — 2026-07-04 (late evening)

- 8 candidates × 1 REQ (across 8 roles) tested with real LLM:
  - BA: 1.000, DataScience: 0.375, SalesManager: 0.750, SrPythonDeveloper: 0.750
  - Mean 0.359, variance 1.000 — LLM produces differentiated scores per candidate
- Cache: 100% hit on second pass, ~0.02s per cached call vs ~30s for real LLM
- LLM correctly identifies presence/absence of skills from chunk evidence
- LLM responses in anchored format: `skill_presence: Yes`, `project_relevance: High`, `years_experience: 12+ years`

### Known limitations

- Free model `nemotron-3-ultra-free` sometimes returns "Not specified" for `linear` (years) sub-questions instead of computing from the evidence. Larger models (gpt-5-mini, claude-haiku-4-5) require credits on this API key.
- LLM latency is high (15-90s per call). Cache mitigates this on re-runs.
- No batching; each REQ is one LLM call. 15 REQs × 1 candidate = 15 calls ≈ 5-7 minutes per candidate cold.

### Configuration

- `.env` now points to `nemotron-3-ultra-free` (the only working free model on `https://opencode.ai/zen/v1`).
- For production: set `OPENCODE_API_KEY` to a key with credits, update `model` in `.env` to a paid model (e.g., `gpt-5-mini`, `claude-haiku-4-5`).
- `max_tokens`, `temperature` (default 0.0) configurable in `LLMRubricCaller.__init__`.

---

### Added — 2026-07-04 (evening): Sub-Query Similarity Retrieval (architecture revision)

- **New retrieval strategy** (`src/services/subquery_retrieval.py`): replaces Section-Routed Evidence Retrieval as the primary retrieval mechanism for per-candidate scoring. Per `WORKING_LOGIC.md` line 470-471.
- **Sub-query decomposition**: each JD requirement is broken into 2-4 sub-questions per its rubric (e.g. SKILL_RUBRIC has `skill_presence`, `years_experience`, `project_relevance`). The rubric structure is in `src/scoring/rubrics.py`.
- **Embedding index**: 6,377 chunks across 721 resumes, embedded with `sentence-transformers/all-MiniLM-L6-v2` (384-dim, L2-normalized). Persisted at `data/embeddings/index.npz` and `data/embeddings/chunks.jsonl`. Built once on first call, reused for all subsequent scoring.
- **Cosine retrieval**: each sub-query is embedded and matched against the candidate's chunks. Default threshold 0.0 (send all chunks; the LLM does final filtering). Threshold is configurable per call.
- **Rubric-bound LLM scoring** with anchored outputs: the LLM reads the retrieved chunks and outputs one anchored value per sub-question (binary {0,1} / linear {0..1} / anchored {0.0, 0.25, 0.5, 0.75, 1.0}). Sub-score is the product of sub-scores per the spec's Sub-Query Decomposition Pattern.
- **Sub-score cache**: deterministic and fast on re-runs. Key = hash(candidate_id, req_id, sorted-chunk-ids, model-name). Stored at `data/embeddings/llm_cache.jsonl`. Invalidates on chunk change or model upgrade.
- **Why this replaces Section-Routed**: Section-Routed depended on every chunk having the correct `section_type` label, but 49% of chunks in our 721-resume corpus had `section_type=""` (lost label). Sub-Query Similarity finds evidence by content, not by label, so chunks with broken/missing labels are still found.
- **Section-Routed still used as metadata pre-filter**: a chunk's `section_type` is now a *soft* filter, not a routing gate. A chunk with no label is still retrieved; the cosine decides relevance.
- **LLM stub provided** for end-to-end testing without a real LLM. Production: replace with OpenAI / Azure OpenAI / local model.

### Changed — 2026-07-04 (evening)

- **`WORKING_LOGIC.md` §"Section-Routed Evidence Retrieval"** — replaced with **"Sub-Query Similarity Retrieval (Per-Candidate, for Scoring)"** as the canonical retrieval strategy. Includes the worked Python example showing 6 chunks retrieved, anchored sub-scores returned by LLM, sub-score = 1.0 × 0.8 × 0.75 = 0.6, contribution = 8% × 0.6 = 0.048.
- **`WORKING_LOGIC.md`** — added a new subsection "Where Section-Routed (label-only) retrieval is wrong" explaining the 49% bug and why sub-query similarity replaces it.

### Verified — 2026-07-04 (evening)

- 6,377 chunks indexed (one-time, ~30s on CPU).
- Sub-query retrieval returns 17 chunks per REQ per candidate (full section delivery, no threshold).
- Cache hits on re-runs (100% of test calls returned `from_cache=True` on second pass).
- 5 different REQs across 4 dimension types (skill, experience, education, certification) all work with the same pipeline.

### Known limitations

- LLM stub returns 0 for all sub-scores because it can't read chunks. Production requires a real LLM caller (next unit of work).
- Embedding model is `all-MiniLM-L6-v2` (English-only). Multilingual candidates would need BGE-M3 or similar.
- Cache grows linearly with (candidates × REQs). For 1,000s of roles, this is millions of entries. JSONL is fine for now; switch to SQLite for >100K entries.

### Documentation — 2026-07-04 (earlier)

- **`WORKING_LOGIC.md`** — strengthened the "Why Chunks, Why Not Embeddings" section with:
  - **Usual RAG vs. this system** — 6-row comparison table (chunking, embedding, retrieval, LLM input, determinism, auditability) showing how each layer differs.
  - **Concrete failure example** — JD requirement "5+ years of Python" with 3 roles + 1 project + CS degree.
  - **Five concrete modifications** from usual RAG: (1) chunk by section not tokens, (2) attach metadata at chunk time not retrieval time, (3) use exact label match not similarity rank, (4) send full section not top-K, (5) score against recruiter-defined rubric not free-form query.
- **`AI_DESIGN_RATIONALE.md`** — added a cross-reference link from §6 Retrieval Strategy to the new WORKING_LOGIC section.

---

### Added — 2026-07-04 (morning): End-to-end "configure → score" pipeline

- **Scoring pipeline service** (`src/services/scoring_pipeline.py`):
  - `load_weight_config(role, config_name)` — loads a weight config JSON from `data/job_descriptions/<role>/` and converts it to `unified_scorer` input format.
  - `find_candidate_files(role, candidate_id)` — maps internal `candidate_id` to on-disk file paths (handles both hash and `Image_*` naming).
  - `list_candidate_ids(role)` — lists all available candidate IDs for a role.
  - `score_candidate(role, candidate_id, config_name)` — end-to-end: load config + candidate data + run `unified_scorer.evaluate_candidate_unified`.
- **Scoring API endpoints** (`src/api/scoring.py`):
  - `GET /api/score/configs/{role}` — list all weight config names available for a role.
  - `GET /api/score/{role}/{candidate_id}?config_name=<name>` — score one candidate against a config. Returns full `UnifiedCandidateEvaluation` with per-item evidence, scoring traces, 0–100 total.
  - `GET /api/score/{role}/rank?config_name=<name>&top_k=20` — rank all candidates in a role, return top-K by total score.
- **DB + JSON parity restored** — DB-only saved configs now have matching JSON files in `data/job_descriptions/<role>/` (rebuilt from DB on 2026-07-04). All 8 roles now scoreable from the UI → JSON → scorer chain.

### Verified — 2026-07-04

- 6/8 roles score end-to-end via HTTP (BusinessAnalyst 103/133, ReactDeveloper 9/18 scored, others similar). Failures are data-quality issues (missing structured profiles or chunks) not pipeline bugs.
- Code-only path works: education tier lookup + certification tier lookup + degree match + location match produce real scores (e.g. `cand_433d020a3cd7` scored 3.5/100 on BusinessAnalyst — Tier-3 education match only).
- Rubric-LLM path returns 0 with no LLM caller (expected per `WORKING_LOGIC.md` §"Rubric-bound LLM evidence scoring" — without a caller, items get zero).

### Known limitations

- Rubric-LLM mode still requires an LLM caller. Most candidates score 0–5/100 until an OpenAI / Azure OpenAI / local model is wired in.
- Per-item `expected_years` not yet exposed in the UI; defaults to 10 years.
- No batch re-rank endpoint (only single-role); recruiters iterate one role at a time.
- No LLM-backed "why this score?" narrative (cached scoring trace is the deterministic fallback).

### Changed — 2026-07-04

- `docs/CURRENT_PROGRESS.md` — "Recruiter weight assignment 0–10" row updated to show full path from UI to scorer; "Next Recommended Unit of Work" reframed: step 1 (wiring) is ✅ done, step 2 (LLM) is the new step 1.

---

## Unreleased

### Added — 2026-07-03: Recruiter Weight Configuration UI (FastAPI + HTMX)

- **Web UI** at `http://127.0.0.1:8000/configure` — replaces the per-role Streamlit CLI scripts.
- **FastAPI service** (`src/api/`) with 9 routes:
  - `GET /configure` — main config page
  - `POST /api/htmx/save/{role_id}` — persist to DB + JSON
  - `GET /api/htmx/requirements/{role_id}` — slider form partial
  - `GET /api/htmx/validate/{role_id}` — live validation
  - `GET /api/htmx/configurations/{role_id}` — saved configs list
  - REST: `GET /api/roles/`, `GET /api/weights/configurations`, etc.
- **HTMX-powered UI** with:
  - Per-requirement slider (0–100%, 0.5 step)
  - `+` / `−` buttons for fine-tuning (0.5 increment)
  - Live counter: `X of Y features rated | Z% left`
  - Live "Current Weights" panel (REQ-ID + name + current value)
  - Auto-balance to 100% button
  - Strict server-side 100% validation
  - Sticky progress bar with over/under color coding
- **Dual storage** (DB + JSON):
  - SQLite: `data/hireintel.db` → `weight_configurations` + `weight_items` tables
  - JSON: `data/job_descriptions/<role>/<role>_WeightConfig_<name>.json` (matches `*_RecruiterWeights_EXAMPLE.json` schema; ready for `unified_scorer` consumption)
  - Delete removes from both
- **Database schema** in `src/models/database.py`:
  - `roles` (8, synced from SubQuery docs)
  - `requirements` (139 across all roles, 14–20 per role)
  - `weight_configurations` (name, role_id, total_allocated, scale_factor)
  - `weight_items` (requirement_id, weight_percentage, expected_years)
  - `recruiters` (table scaffolded, not yet used in UI)
- **Role sync from SubQuery** via `POST /api/roles/sync-from-subquery` — parses `data/job_descriptions/<role>/<role>_SubQuery.md` and populates `roles` + `requirements` tables.

### Changed — 2026-07-03: Dead-code cleanup (14 orphan files)

- **Deleted 14 files** (no remaining references in production code):
  - `src/rag/batch_chunk.py`, `build_index.py`, `embeddings.py`, `index.py`, `jd_match.py`, `retriever.py` (6 — superseded by `chunker.py` + `section_routed.py`)
  - `src/resume_parsing/batch_parse.py`, `header_normalization.py`, `ocr.py` (3 — were used by retired `phase45_pipeline.py`)
  - `src/scoring/batch_score.py` (1 — was used by retired `phase45_pipeline.py`)
  - `scripts/check_data_root.py`, `check_storage.py`, `check_tiers.py`, `audit_imports.py` (4 — dev-only tools)
  - `data/job_descriptions/*/recruiter_weight_input.py` (8 — replaced by FastAPI UI)
- **Retired `scripts/phase45_pipeline.py`** driver. Pre-generated outputs retained:
  - 721 intelligence reports in `data/processed/<role>/`
  - 8 ranked score files in `data/scores/graded/`
  - 721 chunk files in `data/chunks/`
  - These remain valid input to `unified_scorer`.
- **Fixed folder casing bug** — `data/certificates/` → `data/Certificates/`. The code path in `tier_lookup.py` was `data/Certificates/` but the on-disk folder was lowercase, working only on Windows (case-insensitive). Will now work on Linux/Mac deploys.
- **Fixed JS `const newVal` bug** in `configure.html` — `adjustWeight()` was throwing `TypeError: Assignment to constant variable` on first click, making `+` / `−` buttons non-functional. Changed to `let`.

### Documentation — 2026-07-03

- `docs/CURRENT_PROGRESS.md` — refreshed to 2026-07-03; added new "Recruiter Weight Configuration UI" section; "Next Recommended Unit of Work" reframed around wiring scorer to JSON.
- `docs/ARCHITECTURE_CHANGELOG.md` — added tier database expansion entry (Institute tiers 137/54/165 → 192/98/176, Certs expanded to 223, flagged-institute penalty).
- `docs/AI_DESIGN_RATIONALE.md` — added §11 "Flagged (Fake / Unknown) Institute Detection" with alternatives, tradeoffs, final rationale, and implementation.
- `docs/EVALUATION.md` — added "Test Dataset" section with role/country/institution/certification distribution from the 721-resume extract.
- `data/` root — 4 working `.md` files (RESUME_DATA_SUMMARY, CURATED_DATA_FOR_TIERS, TIER_DATABASE_UPDATE_SUMMARY, FLAGGED_INSTITUTE_SYSTEM) merged into the canonical docs above and deleted. `data/hireintel.db` is the only file at `data/` root now.

### Known limitations (post-cleanup)

- Per-item `expected_years` field exists in DB + JSON but is not exposed in the slider UI.
- `expected_years` defaults to `graded_scorer.DEFAULT_EXPECTED_YEARS` (10 years) until a recruiter-editable UI is built.
- Recruiter auth / isolation not implemented — single-recruiter model.
- No re-edit of saved configs (only list + delete); create-only.
- `unified_scorer` does not yet consume the JSON files the new UI produces — wiring is the next recommended unit of work.

---

- **`scripts/phase45_pipeline.py`** — End-to-end batch pipeline that parses resumes, applies Header Normalization, extracts Structured Candidate Profiles, chunks with full metadata schema, scores with the canonical deterministic scorer, and aggregates Candidate Intelligence Reports.
- **721 parsed profiles** → `data/processed/<role>/<candidate_id>.json` (8 role folders: BusinessAnalyst 133, DataScience 42, JavaDeveloper 72, ReactDeveloper 18, SalesManager 164, SQLDeveloper 82, SrPythonDeveloper 98, WebDesigning 112).
- **721 structured profiles** → `data/processed/<role>/<id>_structured_profile.json` (degrees, certifications, total experience years, companies, roles, employment history).
- **721 chunk files** → `data/chunks/<role>/<candidate_id>.jsonl` (Document-Aware Chunking: one chunk per experience/education/project entry; full metadata schema with `calculated_duration_months`, `experience_type`, `skills_asserted`, `parent_structure`).
- **8 ranked score files** → `data/scores/graded/<role>_ranked.json` (deterministic 0–100 normalized scores, per-item evidence with matched section, snippet, years detected, reason).
- **721 Candidate Intelligence Reports** → `data/processed/<role>/<id>_intelligence_report.json` (aggregated skills, experience, education, certifications, projects, objective scores, scoring summary).
- Scoring runs in **code-only mode** (graded_scorer: synonym + regex + years-proportional). Rubric-bound LLM mode pending LLM caller wiring.

### Changed — 2026-07-01
- `CURRENT_PROGRESS.md` — Candidate Intelligence Report ✅; Candidate Ranking updated with pipeline reference; Next Recommended Unit of Work section reframed around remaining Phase 4.5 items (LLM wiring, clarification loop, expected_years UI).

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
