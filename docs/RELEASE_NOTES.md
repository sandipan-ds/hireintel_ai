# Release Notes

## Overview

This document tracks notable changes to HireIntel AI, including features, fixes, breaking changes, documentation updates, and version history.

---

## Unreleased

### Added — 2026-07-07 (Track 7.4.1, bug fix): `role_subqueries` shape-mismatch bug — composed scorer defaulted every REQ to 100.00 under `--no-llm`

- **Bug:** Running `python scripts/score_batch_composed.py --role DataScience --no-llm` produced `mean=100.00` and `top-1=100.00` for every role. Every REQ on every candidate showed `code_only_part=1.00`, `rubric_llm_part=1.00`, `sub_score=1.00`, with `code_only_sq_scores={}` and `rubric_sq_scores={}` (both empty).
- **Root cause:** The CLI (`scripts/score_batch_composed.py:401,227`) was passing the 8-role dict to `evaluate_candidate_composed` as `role_subqueries`, while the function expected a single-role dict. Since the 8-role dict had no top-level `requirements` key, `subquery_reqs = role_subqueries.get("requirements", [])` returned `[]`. `sq_by_id` was thus empty, so every REQ's `sq_data` was `None`, and `sub_queries = sq_data.get("sub_queries", []) if sq_data else []` returned `[]`. With no sub-queries, both the binary/years loop and the rubric loop were skipped, leaving both parts at the dataclass default multiplicative identity of `1.0`. `sub_score = 1.0 × 1.0 = 1.0` for every REQ, and `total = Σ weight × 1.0 = 100.0`.
- **Fix:** `src/scoring/unified_scorer.py::evaluate_candidate_composed` now detects both input shapes (single-role dict vs all-roles dict) by checking for the presence of a `requirements` key. When the all-roles shape is detected, it slices out the single-role dict via `role_subqueries.get(role)`. The function then uniformly sees the single-role shape regardless of how the caller invoked it.
- **Added `rubric_skipped` boolean field to `ComposedREQResult`:** distinguishes the `--no-llm` rubric-bypass branch (`rubric_skipped=True`, no retrieval attempted) from a real "zero-evidence" branch (`rubric_skipped=False`, retrieval attempted but returned zero chunks). The `zero_evidence_reqs` property now excludes `rubric_skipped=True` REQs, so `n_zero_evidence_reqs` is correctly 0 under `--no-llm` (was miscounted as 19 per candidate).
- **Verification:** `pytest tests/unit` → 485 passing (no new tests in this fix — existing composed-scorer tests cover the happy path; the fix is at the input-shape boundary). `score_batch_composed.py --role DataScience --no-llm --limit 2` → `mean=0.00, top-1=0.00, 0-Evid=0` (was `mean=100.00, top-1=100.00, 0-Evid=38`).
- **See `docs/TROUBLESHOOTING.md`** for the full post-mortem (problem → symptoms → root cause → investigation → solution → prevention).

### Changed — 2026-07-07 (Track 7.4.2, scoring improvements + bug fix): Wider chunks + lower θ + employment-history context for rubric LLM + banded years-ratio + Ollama local backend (DEC-032 + DEC-033)

- **`src/rag/recursive_chunker.py`** — chunk_size widened from `500 → 1000`, chunk_overlap widened from `100 → 500` (50% of `chunk_size`). New Optuna bounds: `chunk_size ∈ [500, 1000]`, `chunk_overlap ∈ [floor(0.50 × chunk_size), floor(0.60 × chunk_size)]`. The new bounds reduce the failure mode where a resume role's date line and its skill bullets land in different chunks. The shipped default sits at the high end of the new range — the configuration that minimizes date/skill split incidents. The old `CHUNK_OVERLAP_LOWER = 100` constant was removed (it was a fixed floor that didn't scale with `chunk_size`); replaced with `min_overlap_for(chunk_size) = floor(0.50 × chunk_size)` so the overlap minimum is now 50% of `chunk_size`, not a flat 100. `max_overlap_for(chunk_size)` returns `max(min_overlap_for(chunk_size), floor(0.60 × chunk_size))` — the existing cap, kept.
- **`src/rag/retriever.py`** — `DEFAULT_THRESHOLD` lowered from `0.30 → 0.25` (bounds `[0.10, 0.50]` retained). Surfaces more date-bearing chunks per REQ during smoke testing, which mitigates the failure mode where the date line landed in a chunk that did not pass the higher `θ`. The bounds are exported as module-level constants for Optuna import.
- **`src/scoring/rubric_scorer.py`** — three combined improvements:
  - (a) **Employment-history context block for rubric LLM.** `score_requirement_with_rubric` accepts a new optional kwarg `employment_history: List[EmploymentEntry] = None`. `_build_rubric_prompt` now accepts the same kwarg and, when non-empty, appends an `EMPLOYMENT HISTORY (computed deterministically from date ranges)` block right after the SECTION CONTENT in the prompt. The LLM sees both the retrieved chunks (skill mentions, project descriptions) AND the parser-computed date math per role — it correlates them to answer the `years_experience` sub-question. Mitigates the failure mode where Recursive chunking splits a role's date line away from its bullet points.
  - (b) **Banded years-ratio replaces continuous `min(years/target, 1.0)`.** New helper `_banded_years_ratio(extracted_years, target_years)` returns one of four discrete values: `≥ target → 1.0; ≥ 50% → 0.5; ≥ 25% → 0.25; else 0.0`. Easier to audit and explain to a recruiter than a continuous 0.667-style ratio.
  - (c) **Lenient JSON parser + null-safety.** New `_extract_json_lenient(text)` uses a brace-counting scanner to locate the first valid JSON object; if the response is truncated mid-JSON (free-tier cloud endpoints cap `completion_tokens` mid-stream), attempts to recover at the last complete sub-score object boundary and synthetically close with `]}`. Added defensive `null` handling for `sub_score` so a `"sub_score": null` LLM answer doesn't crash the parser with `float(None)`.
- **`src/scoring/unified_scorer.py:1264`** — the rubric-LLM call now passes `structured_profile.employment_history` so the LLM gets the parser-computed date math as prompt context.
- **`src/services/llm_caller.py`** — three additions: (i) The system message in `LLMRubricCaller.__call__` was rewritten to defer to the user-prompt's format instructions instead of overriding with a contradicting `key: value` directive (the old message told the LLM to output `key: value` lines while the rubric prompt asked for JSON — the LLM followed the system message and produced non-JSON, triggering `"No JSON found"` on every call). (ii) `max_tokens` raised from `2000 → 4000`. (iii) **NEW `OllamaRubricCaller` + `get_rubric_caller` factory.** Local inference via Ollama's OpenAI-compatible endpoint at `http://localhost:11434/v1`. Drop-in for `LLMRubricCaller` — same `__call__(prompt) -> str` contract, same `model_name` / `_available` attributes. Selection via `LLM_BACKEND=ollama` env var in `.env`. Falls back to `LLMRubricCaller` when Ollama is not available.
- **`scripts/score_batch_composed.py`** — now uses `get_rubric_caller()` instead of hardcoding `LLMRubricCaller` so the CLI picks up the backend configured in `.env`.
- **`.env`** — renamed `model` from `nemotron-3-ultra-free` (broken — openai SDK returns `choices=None`) to `deepseek-v4-flash-free` (works but truncates JSON mid-stream — see (c) above for the recovery path). Added `LLM_BACKEND=ollama`, `ollama_model=qwen2.5:3b`, `ollama_base_url=http://localhost:11434/v1` so the local Ollama backend is the production rubric LLM.
- **`data/embeddings/recursive_chunking/index.npz` (rebuilt)** — re-embedded 721 profiles at the new `chunk_size=1000`, `chunk_overlap=500`. Total chunks: 4,763 (was 6,670). Dim unchanged at 384. Build time: 140.5s.
- **Tests:** `tests/unit/test_rubric_scorer.py` — +7 new tests: 4 for the banded rule (meets target, substantial partial, marginal partial, insufficient) and 3 for the employment-history prompt block (renders entries, prompt includes block when supplied, prompt omits block when empty). `tests/unit/test_recursive_chunker.py` — rewrote the bounds tests for the new `[500, 1000]` / `[50%, 60%]` ranges; added `test_min_max_overlap_bounds` checking the new 50-60% bounds. `tests/unit/test_retriever.py` — updated `test_default_threshold_matches_owner_spec_*` to expect `0.25`. Three existing rubric tests updated for the new banded sub-scores (4/5 target → 0.5 band, was 0.8 continuous).
- **Test status — 2026-07-07 (Track 7.4.2):** **503 / 503 unit tests pass** (+10 vs the prior 493/493 baseline). Composed-scorer test count climbed from 19 → 25 entries (rubric + employment-history paths).
- **Smoke test:** `python scripts/score_batch_composed.py --role DataScience --limit 1` (no `--no-llm`) → 1 candidate scored **2.25** (was **0.00**), with real LLM sub-scores (`skill_presence=1.0, years_experience=1.0, project_relevance=0.75`) and `extracted_years=3.0` parsed from the employment_history block, NOT from sparse chunks. ~8s per LLM call, ~150s total for 1 candidate.
- **Known limitations:** The local Ollama backend requires `qwen2.5:3b` installed via `ollama pull qwen2.5:3b` (1.9 GB). If Ollama is not running, the caller returns empty strings → rubric contributions zero out — same behavior as `--no-llm`.

### Added — 2026-07-06 (Track 6, missing-module reconciliation): Hybrid PDF extractor + phantom-module doc fixes (DEC-030)

- **`src/resume_parsing/ocr.py` (NEW)** — restores the optional PDF → text bridge the parser was already gated on. Declares `_HAS_PDFPLUMBER`, `_HAS_PYPDFIUM`, `_HAS_PDF2IMAGE` availability flags at import time. `extract_text_hybrid(path) -> str` runs the strategies in order: `pdfplumber` (high-fidelity text layer) → `pypdfium2` (Poppler-free fallback) → `pdf2image` + OCR (scanned-PDF last resort; placeholder for future wiring). Raises an informative `RuntimeError` if every strategy returns empty text so the parser can mark the resume as unparsable rather than silently producing an empty profile.
- **`tests/unit/test_ocr.py` (NEW)** — 7 unit tests covering the availability flags, the happy-path extraction on the real `01888170110d1ccf.pdf` (John Wood's resume — same fixture as `test_parse_resume_parser.py`), both `RuntimeError` paths (no backends / empty backends via monkeypatch), and the individual private backend wrappers (`_extract_with_pdfplumber`, `_extract_with_pypdfium`). Each PDF-exercising test carries `pytest.mark.skipif(not _HAS_*)` so the suite remains green in environments where backends are missing.
- **`tests/unit/test_resume_parser.py`** — added `pytest.mark.skipif(not _HAS_OCR, ...)` to `test_parse_resume_extracts_contact_and_name` so the existing PDF fixture test is exercised when PDF backends are installed and cleanly skipped when they are not. The test now passes (it had been the single failing test for many sessions).
- **Docs reconciliation** — `header_normalization.py` was a docs-only phantom. The section-header classification logic actually lives in `src/resume_parsing/parser.py` (the `SECTION_HEADERS` dict + `sectionize()` + `identify_section_heading()` functions). Four doc references reconciled: `CURRENT_PROGRESS.md` Header Normalization row, `MODEL_REGISTRY.md` Header Normalization row, `IMPLEMENTATION_ROADMAP.md` line 237, `ARCHITECTURE_CHANGELOG.md` line 277. Each now points to `parser.py` as the real location and links back to Track 6 / DEC-030.
- **`docs/TROUBLESHOOTING.md`** — appended the full debugging trail for the missing `ocr.py` issue (problem → symptoms → root cause → investigation process → solution → verification → prevention). Reusable pattern for future optional-dependency missing-module investigations.
- **`docs/ENVIRONMENT_NOTES.md`** — appended the PDF back-end availability matrix (pdfplumber installed, pypdfium2 installed, pdf2image not installed, pymupdf not installed), the optional-dependency pattern (`_HAS_X` flags declared at import time, fail-open at import, fail-closed at call time), and the minimum `pip install -r requirements.txt` command for fresh environments.

### Fixed — 2026-07-06 (Track 6, missing-module reconciliation)

- **The pre-existing single failing unit test (`test_parse_resume_extracts_contact_and_name`) is now passing.** The test calls `parse_resume(<pdf>)` and previously raised `RuntimeError: PDF extraction requires src.resume_parsing.ocr which is not installed in this environment.` Once `src/resume_parsing/ocr.py` was added, `pdfplumber` (already in the venv) was wired up and the John Wood fixture PDF extracts cleanly: name = "John Wood", phone contains "+1-925-885-5155", email contains "help@enhancv.com".
- **Doc phantom for `src/resume_parsing/header_normalization.py`** — four doc files claimed this file existed and held the canonical section-header normalization logic. Reconciled in this track; the functionality lives in `src/resume_parsing/parser.py`.

### Unchanged — 2026-07-06 (Track 6, missing-module reconciliation)

- The parser's lazy-import branch (`try: from .ocr import ...; _HAS_OCR = True except ImportError: _HAS_OCR = False`) is unchanged. The new `ocr.py` simply makes the `True` path trie-able; environments without PDF back-ends still write `_HAS_OCR = False` and the new `skipif` marker skipped the relevant tests.
- The `pdfplumber` and `pypdfium2` packages were already declared in `requirements.txt` — no new dependencies. `pdf2image` is documented as optional (Poppler required).

### Test status — 2026-07-06 (Track 6)

- **455 / 455 unit tests pass** (+7 vs the prior 447/448 baseline, and +1 fix for the previously-failing PDF test). Perfect green.

### Added — 2026-07-06 (Track 5, substring fix): Word-boundary matcher for education/cert code-only scoring (DEC-029)

- **`src/scoring/unified_scorer.py::_token_boundary_match`** — new helper that replaces the legacy bare-`in` substring check used by `_score_education_code_only` and `_score_certification_code_only`. The matcher is whole-phrase-first (`\b<needle>\b`) and any-token-fallback (each whitespace-separated token of the requirement checked with `\b<tok>\b` against the candidate text). Stop-word filter skips tokens ≤ 2 chars to avoid near-zero-signal matches.
- **`tests/unit/test_unified_scorer.py`** — 6 regression tests added: `"BA"` vs `"MBA"` (no match), `"BS"` vs `"BSE"` (no match), `"BA"` vs `"BA"` (match sanity), `"BTech"` vs `"BTech in Computer Science"` (legacy education match preserved), `"PMP"` vs `"PMPI"` (no match), `"PMP"` vs `"PMP Certified"` (legacy cert match preserved).
- **Test status:** 447/448 passing (+6 vs the prior 441/442 baseline). The single pre-existing failure is the unresolved `src/resume_parsing/ocr.py` issue (Track 6, deferred).

### Fixed — 2026-07-06 (Track 5, substring fix)

- **False-positive education/cert matching for short abbreviations.** Previously, `_score_education_code_only` and `_score_certification_code_only` used `item_name.lower() in degree_entry.degree.lower()` (or the reverse direction, or the `any(kw in cert for kw in item_name.split())` split form for certs). Bare `in` substring matching meant `"BA"` matched `"MBA"` because the substring `ba` appears inside `mba`, `"BS"` matched `"BSE"`, and `"PMP"` matched `"PMPI"`. The new `_token_boundary_match` uses Python's `re` `\b` anchors, so a token must appear as a *whole word* — `"BA"` no longer matches `"MBA"` because the `m` to the left of `ba` is a letter (no boundary). The ANY-token semantic for cert matching is preserved, so `"AWS Certified"` still matches `"AWS Solutions Architect Associate"` via the `aws` token.

### Unchanged — 2026-07-06 (Track 5, substring fix)

- Existing education behavior for substantive degree strings is unchanged: `"BTech"` still matches `"BTech"`, `"BTech in Computer Science"`, and the existing `_make_structured_profile` fixture (`DegreeEntry(degree="BTech", ...)`). The existing `test_btech_iit_tier_1` test confirms this.
- Existing certification behavior for `"AWS Certified"` against `"AWS Solutions Architect Associate"` is unchanged (the `aws` token carries the match). The existing `test_aws_tier_1` test confirms this.

### Added — 2026-07-06: M0.5a stage-4 code shipped (DEC-027)

- **`src/rag/recursive_chunker.py`** — active chunker (DEC-019). LangChain-free `recursive_split_text`, separator hierarchy `["\n\n", "\n", ". ", " "]`, defaults `chunk_size = 500` / `chunk_overlap = 100`. Owner-specified Optuna bounds enforced at construction: `chunk_size ∈ [200, 500]`, `chunk_overlap ∈ [100, floor(0.60 * chunk_size)]`. Bounds exported as module-level constants for Optuna import.
- **`src/rag/per_req_retrieval.py`** — canonical SubQuery evidence-gathering entry point. `retrieve_evidence_for_req()` embeds each sub-query (or accepts caller-supplied vectors), retrieves per sub-query via `ThresholdRetriever` with `candidate_id` filter, unions + dedupes by `chunk_id` keeping the highest cosine, sorts desc, caps at `max_chunks_per_query`. Returns `[]` on zero retrieval so the caller raises the no-evidence flag at `reports/audit/no_evidence_flags.jsonl`. 11 unit tests at `tests/unit/test_per_req_retrieval.py`.
- **`src/rag/build_index.py`** — production index builder + CLI. Walks `data/processed/<role>/*.json`, filters out `_intelligence_report.json` / `_structured_profile.json` downstream artifacts, chunks with `RecursiveChunker`, batch-embeds with MiniLM-L6-v2 (DEC-007, 384-dim, L2-normalized), persists to `data/embeddings/index.npz` + `chunks.jsonl`. Flags `--dry-run`, `--batch-size`, `--chunk-size`, `--chunk-overlap`, `--no-backup`.
- **`tests/unit/test_cache_key.py`** — 11 tests locking in the theta-in-key invariant for Optuna sweeps.

### Changed — 2026-07-06: M0.5a stage-4 code shipped (DEC-027)

- **Retriever switched from top-K to threshold-based cosine (DEC-018).** `src/rag/retriever.py::ThresholdRetriever` returns every chunk with `cosine >= theta`, sorted desc, capped at `max_chunks_per_query = 20`. Default `theta = 0.30` (was top-K only). WARN log on cap-hit. Bounds `THRESHOLD_LOWER` / `THRESHOLD_UPPER` exported.
- **SubQuery parser extended.** `src/services/subquery_parser.py::_extract_requirements` now parses SubQuery table rows into a `sub_queries` list per REQ. Verified across all 8 roles: 138 REQs, 356 sub-queries, 0 mismatches.
- **LLM cache key now includes `theta` (M0.5a Step 5).** `make_cache_key` folds `theta` into the SHA-256 hash, quantized to 6 decimals. All 3 callers updated to thread the retrieval `threshold` into the key. The sweep is now strictly per-trial isolated — a sub-score from `theta = 0.30` is never reused as a `theta = 0.40` hit. Tradeoff: lower hit rate during the sweep; full hit rate restores after a single "Active" config is promoted (M0.5d).
- **Embedding index rebuilt.** `data/embeddings/index.npz` + `chunks.jsonl` now contain **6,670 chunks** (was Document-Aware's 6,377) from 721 resumes, 384-dim, 8.4 MB. Build time ~135 s on CPU. The prior Document-Aware index is preserved at `data/embeddings/document_aware_backup/`.
- **Defensive chunker coercion.** `RecursiveChunker.chunk_profile` now treats non-dict `experience` / `education` (list, None) as `{"entries": []}` so real-world parser-output variance does not crash the build.

### Unchanged — 2026-07-06

- The deterministic scoring engine is still the only ranking signal.
- `DocumentAwareChunker` is retained at `src/rag/document_aware_chunker.py` as a one-release migration aid per DEC-022; production paths do not call it.
- `ChunkRecord` schema is unchanged — Recursive chunks share the exact dataclass the Document-Aware chunker emits, so downstream embedding / retrieval / scoring code is untouched.

### Known Risks — 2026-07-06

- **Production wiring pending.** The new composed scorer (`evaluate_candidate_composed`) is unit-tested but no batch scoring CLI yet invokes it. The legacy `evaluate_candidate` / `evaluate_candidate_unified` paths are live but are deprecated supersets.
- **113 candidates were silently dropped** during the index build (721 resumes → 608 unique candidate_ids in the index) because their parsed profile produced zero non-empty sections. Tracked for Track 6.
- **441 / 442 unit tests pass** (single pre-existing failure is the unresolved `src/resume_parsing/ocr.py` missing-module issue).

### Added — 2026-07-06 (Track 2-S, scorer refactor): Composed Mode1 × Mode2 scorer (DEC-028)

> Track naming: this is "Track 2-S" (scorer refactor), distinct from the docs' "Track 2" (Eval set + MLflow, M0.5b/c). The two tracks are unrelated and run on separate timelines. Track 2-S follows Track 1 (M0.5a RAG pipeline) and gives the new pipeline its first production score consumer.

- **`src/scoring/graded_scorer.py::evaluate_candidate_code_only_v2`** — the canonical code-only scorer under the new spec. Drops `scale_factor` and `DEFAULT_EXPECTED_YEARS`. Total = `Σ (weight% × code_only_part)`, lands in [0, 100] because the recruiter weights sum to 100. Years-type REQs with no recoverable `expected_years` are blocked (contribution 0 + "BLOCKED:" reason). Synonym dictionary + regex years detection from `graded_scorer` legacy helpers are reused.
- **`src/scoring/graded_scorer.py::extract_expected_years`** — regex extractor for `expected_years` from free text. Handles 4 patterns: `expected N years`, `N-M years → M (upper bound)`, `N+ years`, `N years`; returns `None` when nothing recoverable.
- **`src/scoring/unified_scorer.py::evaluate_candidate_composed`** — the canonical composition scorer: per REQ, `Sub-Score = Code_only_part × Rubric_LLM_part` (both ∈ [0, 1]); `Contribution = weight% × Sub-Score`; `Total = Σ Contribution`. Code-only part comes from `Binary` + `Float years-proportional` SubQuery SQs scored against the parsed profile. Rubric LLM part comes from one `rubric_scorer.score_requirement_with_rubric` call per REQ after `per_req_retrieval.retrieve_evidence_for_req` retrieves evidence. New `sq_embedder` kwarg lets tests inject hand-crafted vectors (sidesteps MiniLM download).
- **`src/scoring/unified_scorer.py`** — new dataclasses: `ComposedREQResult`, `ComposedCandidateEvaluation`. Helpers: `_is_binary_subquery`, `_is_years_subquery`, `_is_rubric_subquery` (sub-query classifier), `_score_presence_sq` (token-fallback presence check), `_score_years_sq` (returns `(score, years, expected)`; `expected=None` signals block), `_build_section_evidence` (adapter from per-REQ retrieval `ScoredChunk` list → rubric_scorer's `SectionEvidence`).
- **`src/audit/no_evidence_flags.py`** — append-only JSONL audit log for zero-evidence flags. `write_flag` / `read_flags` / `clear_flags`. One line per `(candidate, REQ)` pair with: timestamp (ISO 8601 UTC), candidate_id, role, req_id, requirement_name, sub_query_keys, sub_query_count, theta, chunker. Reserved field names protected against overwrite from `extra` dict.
- **`tests/unit/test_composed_scorer.py`** — 38 unit tests covering extract_expected_years (8), no_evidence_flags writer (6), evaluate_candidate_code_only_v2 (6), sub-query classification (3), per-SQ scoring helpers (5), and evaluate_candidate_composed end-to-end (10). All tests use a 4-dim synthetic toy index + stub embedder, no model download.

### Changed — 2026-07-06 (Track 2-S, scorer refactor)

- **Production scoring formula switched to the canonical WORKING_LOGIC spec.** Legacy `evaluate_candidate` / `evaluate_candidate_unified` paths are kept untouched as backward-compat shims. Production callers should migrate to `evaluate_candidate_composed` (per-REQ) and `evaluate_candidate_code_only_v2` (code-only fallback).
- **Missing `expected_years` is now a block, not a default-10.** The legacy `DEFAULT_EXPECTED_YEARS = 10` silently defaulted years-type REQs; the new path blocks the REQ (contribution 0) and flags for human review. The JD or SubQuery file is the source of truth for expected_years per the WORKING_LOGIC spec.

### Unchanged — 2026-07-06 (Track 2-S, scorer refactor)

- The legacy `graded_scorer.DEFAULT_EXPECTED_YEARS` constant is kept as a deprecation marker (importable, unused in the new path).
- The existing `rubric_scorer.score_requirement_with_rubric` API is unchanged; the composed scorer adapts per-REQ retrieved chunks to it via `_build_section_evidence`.
- The deterministic scoring engine remains the only ranking signal; the LLM only scores the rubric sub-questions within a single REQ.

---

## Earlier unreleased changes (2026-07-04 onward)

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

- **Header Normalization** (~`src/resume_parsing/header_normalization.py`~ — file never existed; the logic lives in `src/resume_parsing/parser.py` per Track 6 / DEC-030) — Layer 1 synonym table + Layer 2 LLM fallback for 7 canonical sections (Personal_Info, Education, Experience, Projects, Skills, Certifications, Languages). 24 tests.
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
