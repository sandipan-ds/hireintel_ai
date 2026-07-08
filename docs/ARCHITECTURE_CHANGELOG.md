# Architecture Changelog

## Overview

This document records architecture changes that affect system structure, runtime behavior, AI workflows, storage, APIs, or deployment.

---

## 2026-07-08 (b) — MLflow experiment-tracking wiring shipped (DEC-020, M0.5c)

### What changed

- **New module: `src/services/mlflow_wiring.py`** — the single integration point between the HireIntel scoring pipeline and the local MLflow tracking server (DEC-020). Sits under `src/services/` alongside the other external-integration helpers (`llm_caller.py`, `subquery_parser.py`, `json_export.py`). Pipeline code now imports from this module instead of `mlflow` directly, so the DEC-020 contract (9 params, 11 metrics, 2 canonical tags, ≥1 artifact) is enforced in one auditable place.
- **`PipelineParams` / `RetrievalMetrics` dataclasses** centralize the contract. Adding a contract field is a single dataclass change; every caller picks it up automatically. Defaults reflect the shipped RecursiveChunker + ThresholdRetriever config so a forgotten field logs a real value, not `None`.
- **`MLflowRun` context manager** — wraps `mlflow.start_run` with typed log helpers (`log_pipeline_params`, `log_retrieval_metrics`, `log_metric`, `log_artifact`, `set_tag`). A `with` block that raises is finalized with `status='FAILED'`. The context holds the active-run flag so every helper no-ops cleanly when the dependency is missing (graceful degradation: a missing `mlflow` breaks only tracking, never the scoring run).
- **New script: `scripts/start_mlflow_server.py`** — the convenience launcher that produces the exact DEC-020 command line. Pre-creates the SQLite parent directory and the artifact root so the first run does not fail. Supports `--dry-run`, `--port`, `--host`.
- **`scripts/score_batch_composed.py` updated** — the per-role scoring loop now opens an `MLflowRun` per role with `experiment_set` + `role` tags, logs all 9 `PipelineParams`, the 4 rollup metrics (`n_candidates`, `mean_score`, `n_zero_evidence_reqs`, `time_seconds`), the 11 `RetrievalMetrics` placeholders (0.0 until the M0.5d eval harness fills them), and the `<role>_ranked.json` artifact. New CLI flags: `--no-mlflow`, `--experiment-set`, `--tracking-uri`, `--no-llm-track`. When `mlflow` is not installed, one warning is logged and the run proceeds untracked.
- **`requirements.txt` pinned** — `mlflow>=2.10,<5.0` (resolved to 3.14.0 in dev) and `optuna>=3.6,<5.0` (for the upcoming M0.5d Optuna sweep). `optuna-dashboard` deliberately not pinned (pip wheel-build failed on this box; revisit for M0.5d).

### Why

- **DEC-020 was specified but not implemented.** The MLflow contract (tracking URI, backend store, artifact root, tags, params, metrics, artifacts) was published in `EVALUATION.md` on 2026-07-05 and the rationale recorded in `AI_DESIGN_RATIONALE.md` §12, but the implementer row in `CURRENT_PROGRESS.md` M0.5c sat at ⬜. With Track 7.5 (Prong 6 reporter) shipped earlier today, M0.5c was the only remaining unblocked prerequisite for the Optuna sweep (M0.5d). This entry closes M0.5c.
- **No outside-calls, no PII exfiltration.** MLflow runs on `127.0.0.1:5000` with a local SQLite backend and a local filesystem artifact root. Candidate resumes, names, and contact info never leave the host — the hard privacy constraint documented in `AI_DESIGN_RATIONALE.md` §12 is preserved.
- **Graceful degradation is non-negotiable for ops.** A missing optional dependency must not prevent a scoring run. The wiring module probes `mlflow` at import time and routes every helper through `_available` so the absence of the library shows up as a single warning plus an untracked run, not an ImportError that aborts the batch.

### Affected files

- **New:** `src/services/mlflow_wiring.py` (~270 lines, 1 dataclass pair, 1 context manager class).
- **New:** `scripts/start_mlflow_server.py` (~95 lines, launcher).
- **New:** `tests/unit/test_mlflow_wiring.py` (12 hermetic tests).
- **Updated:** `scripts/score_batch_composed.py` — import block + per-role scoring loop wrapped in `with run or _NullCtx():`; new flags.
- **Updated:** `requirements.txt` — `mlflow>=2.10,<5.0`, `optuna>=3.6,<5.0` pins.
- **Updated:** `docs/CURRENT_PROGRESS.md` M0.5c three rows ⬜ → ✅.
- **Updated:** `docs/RELEASE_NOTES.md` Unreleased block — Added entry for 2026-07-08 (M0.5c).
- **Updated:** `docs/DECISIONS.md` DEC-020 status advanced; rationale appended.

### Storage impact

- New persisted paths (created by the launcher or by the first tracked run):
  - `data/mlflow/mlflow.db` — MLflow SQLite backend store (experiments + runs + params + metrics + tags).
  - `data/mlflow/artifacts/` — MLflow artifact root (per-run artifact files; here, `<role>_ranked.json`).
- Both are git-ignored by convention (the `data/` directory is already in `.gitignore`).
- A transient `mlruns/` folder may appear if `mlflow` defaults are exercised without the launcher; that path is **not** part of the shipped configuration and should be removed if it appears.

### Test impact

- 12 new unit tests at `tests/unit/test_mlflow_wiring.py`. Total unit count: 512 → 524. Full suite passes (524/524). Ruff clean on the three new/modified files.

### Risks introduced

- **`mlruns/` directory accidentally created in CWD.** If the launcher is not used and the caller calls `mlflow.set_experiment(...)` before `configure_tracking`, MLflow will drop a local `./mlruns` directory rather than the SQLite backend. Mitigation: wiring always calls `mlflow.set_tracking_uri(self.tracking_uri)` *before* `mlflow.set_experiment(...)`. Tests confirm the order.
- **`optuna-dashboard` not installed.** M0.5d will need it; current pip fails on `pyarrow` wheel build in this env. Workaround for M0.5d: install via `pip install optuna-dashboard` in a fresh venv, or skip the dashboard and rely on MLflow's own comparison view.

### Future considerations

- **M0.5d (Optuna sweep)** is now unblocked: the wiring module exposes every DEC-020 contract surface the Optuna driver will need. The driver just wraps each trial in `with start_run(experiment_name="chunking_v1", ...) as run:` and calls `run.log_pipeline_params(trial.params)`.
- **Evaluator runs** (M0.5b/c/d) will overwrite the 11 `RetrievalMetrics` placeholders with measured values; the contract keys are already in place so no schema migration of older runs is required.
- **MLflow Model Registry** is the documented future upgrade path (`AI_DESIGN_RATIONALE.md` §12): if the team wants to version the scoring engine itself, not just experiment configs, promote MLflow to its remote tracking server only when multi-machine collaboration becomes necessary.

---

## 2026-07-08 (a) — Optuna ranking-stability reporter shipped (DEC-024 Prong 6, Track 7.5; DEC-031 umbrella)

### What changed

- **New module: `src/reporting/rank_stability.py`** — the Prong 6 reporter that measures ranking stability across hyperparameter perturbations during an Optuna sweep (M0.5d). The Prong 6 spec was published in `EVALUATION.md` on 2026-07-06 (DEC-024) but its implementer was a Track 7 ⬜ row. This entry closes Track 7.5.

- **Pipeline role:** the reporter sits at the end of the Optuna sweep loop. Each Optuna trial already writes a per-study rankings JSON at `reports/diff_rankings/optuna_study_<study>__<role>__rankings.json` (per `EVALUATION.md` §"Where the rankings come from"). Once the sweep completes, `compute_rank_stability(study_payload)` reads that JSON, computes the nine Prong 6 metrics across every `(trial_A, trial_B)` pair, and `write_stability_report()` writes a sibling `...__rank_stability.json` + `...__rank_stability.md` pair. The JSON is what MLflow logs as a metric set for the study; the MD is the human-readable summary a reviewer scans before promoting an Optuna-recommended config to "Active" in `MODEL_REGISTRY.md`.

- **Pure-function primitives.** Every per-pair metric is a deterministic function of two candidate-id sequences — no I/O, no global state, easy to unit test. `top_k_jaccard`, `rank_shift_stats`, `distribution_correlations`, `newcomer_drop_rates`. All rank-shift magnitudes are unsigned (per the spec's +/- cancellation guard — a `+5` and `-5` between two candidates never sum to 0 and hide the magnitude).

- **HP-axis explained-variance decomposition.** For each HP key present in the trial `params` dicts, the reporter computes the R^2 of `mean_abs_rank_shift` against the absolute HP delta between paired trials. Uses a closed-form single-slope linear regression (`_r_squared_for_axis`) — no `scikit-learn` dependency. The catch-all "no variation in HP axis" branch returns `0.0` rather than NaN: a constant HP explains zero of the *across-trial* variance by definition.

- **Soft-target flags.** The six soft targets published in `EVALUATION.md` §"Prong 6 Targets" (`top_10_jaccard ≥ 0.60`, `max_rank_shift ≤ 50`, `mean_abs_rank_shift ≤ 15`, `kendall_tau ≥ 0.60`, `spearman_rho ≥ 0.65`, `newcomer_rate_top_10 ≤ 0.30`) are surfaced verbatim in every report. `_derive_flags` lists any violation in the `flags` field. Per spec, Prong 6 metrics are **informational** — an Optuna-recommended "Active" config candidate **cannot** be blocked solely by Prong 6. A flag is a prompt for human review, not a gate.

### Why

- **Prong 6 was specified but not implemented.** DEC-024 (2026-07-05) added the 5-prong ranking-evaluation methodology including Prong 6, but left the implementer as a Track 7 ⬜ row. With Track 7.4 (batch CLI + subquery cache + scoring improvements) shipped 2026-07-07, the only blocking gap for the Optuna sweep (M0.5d) was the absence of a stability diagnostic — the spec's exact phrasing was "without rank-stability, Optuna cannot diagnose shortlist churn". Track 7.5 closes that gap.

- **The reporter is decoupled from Optuna itself.** It takes the parsed study JSON and returns a populated report. That decoupling is what lets the unit tests (9 in `tests/unit/test_rank_stability.py`) verify every metric against synthetic fixtures without spinning up a real Optuna study — the test-suite stays hermetic and CI-runnable in seconds.

### Affected files

- **New:** `src/reporting/rank_stability.py` (766 lines, 18 functions, 1 dataclass).
- **New:** `tests/unit/test_rank_stability.py` (9 tests).
- **Updated:** `docs/CURRENT_PROGRESS.md` Track 7.5 row ⬜ → ✅; Track 7.6 row ⬜ → ✅ (doc-drift fix — Track 7.6 had been landed inline last session but the row was not flipped).
- **Updated:** `docs/RELEASE_NOTES.md` "Unreleased" block — Added entry for 2026-07-08 (Track 7.5).
- **Updated:** `docs/DECISIONS.md` — dedicated DEC-031 entry added (was previously only referenced in Track 7 prose; the entry had never landed).

### Storage impact

- New output paths (per-study, per-role):
  - `reports/diff_rankings/optuna_study_<study>__<role>__rank_stability.json` — the structured metric bundle (logged to MLflow as a metric set).
  - `reports/diff_rankings/optuna_study_<study>__<role>__rank_stability.md` — the human-readable summary (committed to git per the existing `reports/` tracking rule).
- Both files are siblings of the source `...__rankings.json` written by the Optuna exporter — they move with the study.

### Test status

- **512 / 512 unit tests pass** (was 503/503; +9 from the new test file). Ruff clean on both new files.

### Promotion gate impact

- None — Prong 6 is informational. The four hard gates (DEC-024 promotion-gate revision: counterfactual ≥ 0.95, stability = 1.0, NDCG@10 ≥ 0.80 if labeled set exists, no regression in prior Active's counterfactual) are unchanged. Prong 6 merely adds a flag for human review when `top_10_jaccard < 0.30` against the prior "Active" config — the reviewer can still override.

### Related decisions

- **DEC-024** (2026-07-05) — added Prong 6 to the ranking-evaluation methodology and specified the nine metrics + soft targets.
- **DEC-031** (added 2026-07-08) — Track 7 umbrella decision (subquery cache + batch CLI + rank-stability reporter); this entry implements its Prong 6 component.

---

## 2026-07-07 (b) — Rubric LLM context enrichment + banded years-ratio + local Ollama backend (DEC-033, Track 7.4.2)

### What changed

- **`src/scoring/rubric_scorer.py`** — three changes:
  - (a) `score_requirement_with_rubric` accepts a new optional kwarg `employment_history: List[EmploymentEntry] = None`. When non-empty, `_build_rubric_prompt` appends an `EMPLOYMENT HISTORY (computed deterministically from date ranges)` block right after the SECTION CONTENT in the rubric prompt. The LLM sees both the retrieved chunks (skill mentions, project descriptions) **and** the parser-computed per-role durations — so it can correlate skill mentions with role durations without being forced to re-parse sparse dates out of 1000-char chunks.
  - (b) New helper `_banded_years_ratio(extracted_years, target_years)` replaces the continuous `min(years/target, 1.0)` formula with a discrete 4-band rule: `≥ target → 1.0; ≥ 50% → 0.5; ≥ 25% → 0.25; else 0.0`. Banded scores are easier to audit and defend in a recruiter UI than continuous ratios like 0.667.
  - (c) New `_extract_json_lenient(text)` helper uses a brace-counting scanner to locate the first valid JSON object in a truncated LLM response, then attempts to recover at the last complete sub-score object boundary. Defensive `null` handling added for `sub_score` so a `"sub_score": null` LLM answer doesn't crash the parser.

- **`src/scoring/unified_scorer.py:1264`** — the rubric-LLM call now passes `structured_profile.employment_history` so the LLM gets the parser-computed date math as prompt context.

- **`src/services/llm_caller.py`** — three additions:
  - (i) `LLMRubricCaller.__call__` system message rewritten to defer to the user-prompt's format instructions instead of overriding with a contradicting `key: value` directive (the old message told the LLM to output `key: value` lines while the rubric prompt asked for JSON — the LLM followed the system message and produced non-JSON, triggering `"No JSON found"` on every call).
  - (ii) `max_tokens` raised from `2000 → 4000`.
  - (iii) **NEW `OllamaRubricCaller` class + `get_rubric_caller()` factory.** Local inference via Ollama's OpenAI-compatible endpoint at `http://localhost:11434/v1`. Drop-in for `LLMRubricCaller` — same `__call__(prompt) -> str` contract, same `model_name` / `_available` attributes. Selection via `LLM_BACKEND=ollama` env var in `.env`; falls back to `LLMRubricCaller` (cloud) when Ollama is not available.

- **`scripts/score_batch_composed.py`** — now uses `get_rubric_caller()` instead of hardcoding `LLMRubricCaller` so the CLI picks up the backend configured in `.env`.

- **`.env`** — renamed `model` from `nemotron-3-ultra-free` (broken — openai SDK returns `choices=None`) to `deepseek-v4-flash-free` (works but truncates JSON mid-stream). Added `LLM_BACKEND=ollama`, `ollama_model=qwen2.5:3b`, `ollama_base_url=http://localhost:11434/v1` so the local Ollama backend is the production rubric LLM.

### Why

The 2026-07-07 LLM rubric smoke test surfaced multiple bugs in the rubric scoring path:

1. **Cloud free-tier LLM endpoints were unreliable.** `nemotron-3-ultra-free` caused the openai SDK to deserialize `choices=None`. `deepseek-v4-flash-free` worked but truncated JSON responses mid-stream (`completion_tokens` server-side cap). The default model in `.env` (`MiMo V2.5 Free`) was an invalid alias and returned 401. The rubric scorer's strict `json.loads` failed on every truncated response and fell back to zero scores.
2. **`years_experience` sub-question depended on the LLM extracting years from chunks alone.** The parser already computed `StructuredCandidateProfile.employment_history` with `calculated_duration_months` per role (Track 7.2), but that result was never passed to the rubric LLM. The LLM was forced to re-derive what the system already knew.
3. **The system message in `LLMRubricCaller.__call__` contradicted the rubric prompt format.** "output ONLY `key: value` lines" (system) vs "Respond with ONLY a JSON object" (user). The LLM followed the system message and produced anchored `key: value` lines instead of JSON, triggering `"No JSON found in LLM response"` on every call.
4. **Continuous `min(years/target, 1.0)` was hard to audit.** A recruiter UI showing `0.67` for a 4/6 years-ratio would require explaining why 0.67 and not 0.71. Bands map directly to explainable labels ("meets expectation", "substantial partial", "marginal").

### Impact

- Production rubric LLM now runs locally via Ollama `qwen2.5:3b` — no API cost, no rate limits, no JSON truncation. ~6s per call.
- End-to-end smoke test: 1 DataScience candidate scored **2.25** (was **0.00**), with real LLM sub-scores (`skill_presence=1.0, years_experience=1.0, project_relevance=0.75`) and `extracted_years=3.0` parsed from the employment_history block, not sparse chunks.
- The LLM now has both the retrieved chunks AND the pre-computed date math; it does the skill-to-role correlation (still its job) but is no longer forced to re-parse dates the system already parsed.
- **503/503 unit tests pass** (+10 vs the prior 493/493 baseline).

---

## 2026-07-07 (a) — Chunking bounds widened + default θ lowered (DEC-032, Track 7.4.2)

### What changed

- **`src/rag/recursive_chunker.py`** — `RECURSIVE_CHUNK_SIZE`: `500 → 1000`. `RECURSIVE_CHUNK_OVERLAP`: `100 → 500` (50% of `chunk_size`). Optuna bounds widened: `CHUNK_SIZE_LOWER`: `200 → 500`, `CHUNK_SIZE_UPPER`: `500 → 1000`. The old flat `CHUNK_OVERLAP_LOWER = 100` constant was removed (overlap minimum didn't scale with `chunk_size`); replaced with `min_overlap_for(chunk_size) = floor(0.50 × chunk_size)` and `max_overlap_for(chunk_size) = max(min_overlap_for(chunk_size), floor(0.60 × chunk_size))`. A new `CHUNK_OVERLAP_MIN_FRACTION: float = 0.50` constant exposed for Optuna export.
- **`src/rag/retriever.py`** — `DEFAULT_THRESHOLD`: `0.30 → 0.25` (bounds `[0.10, 0.50]` retained). `CHUNK_SIZE_LOWER` / `CHUNK_SIZE_UPPER` mirrored from the chunker. Replaced `CHUNK_OVERLAP_LOWER` / `CHUNK_OVERLAP_MAX_FRACTION` with `CHUNK_OVERLAP_MIN_FRACTION` / `CHUNK_OVERLAP_MAX_FRACTION` to match the new bounds. Module docstring updated to reflect the new default.
- **`data/embeddings/recursive_chunking/index.npz` (rebuilt)** — 721 profiles re-embedded at the new `chunk_size=1000`, `chunk_overlap=500`. Total chunks: 4,763 (was 6,670 under the prior 500/100 defaults). 384-dim MiniLM-L6-v2 embeddings. Build time: 140.5s.
- **`tests/unit/test_recursive_chunker.py` + `tests/unit/test_retriever.py`** — bounds tests rewritten for the new `[500, 1000]` / `[50%, 60%]` ranges. Added `test_min_max_overlap_bounds` explicitly verifying the 50-60% bounds.

### Why

The prior defaults (`chunk_size=500`, `chunk_overlap=100`, `θ=0.30`) produced chunks small enough that a resume role's date line frequently landed in a different chunk from its bullet describing skill use. The rubric LLM received the bullet chunk but not the date chunk, and returned `extracted_years=0` (correctly — there was no evidence in the chunk). The multiplicative formula `gate × years_ratio × relevance` then zeroed the entire REQ even when gate and relevance were correctly scored.

Widening chunk_size to 1000 and chunk_overlap to 500 (50% of chunk_size) means adjacent chunks share half their text — the date line in chunk N also appears in chunk N+1, so the LLM sees the date context even when the bullet text is the retrieval hit. The default θ was lowered from 0.30 to 0.25 to surface more date-bearing chunks per REQ; bounds `[0.10, 0.50]` remain unchanged for the Optuna sweep.

### Alternatives considered

- **Keep `chunk_size=500` and only lower θ:** insufficient — even with `θ=0.10`, the date line would still land in a different chunk from the bullet.
- **Switch to whole-resume prompts (no chunking):** rejected — 721 × 20 REQs × whole-resume prompts = enormous token cost. Retrieval exists precisely to avoid this. The structured profile already has the dates, so we don't need to re-feed the whole resume.
- **Pure regex years extraction:** rejected — regex can't reliably correlate "did ETL work" (line 4) with "2017-2019" (line 12) across chunks. The LLM's skill-to-role correlation judgment is what we want; we just need to give it the date math the parser already computed (see 2026-07-07 (b) above).

### Impact

- Larger chunks reduce retrieval granularity (a 1000-char chunk is coarser than a 500-char chunk) but improve the chance the chunk contains both the date line and the skill mention — the actual bottleneck in the 2026-07-07 smoke test.
- 50% overlap means 50% of each chunk is duplicated in the next chunk. Token cost is ~2× per chunk, but chunk count is ~half, so total token cost is roughly the same. The overlap ensures the date line in chunk N also appears in chunk N+1.
- Optuna bounds widened accordingly; these remain Optuna hyperparameters. The shipped defaults sit at the high end of the new range — the configuration that minimizes date/skill split incidents.
- **503/503 unit tests pass.**

---

## 2026-07-06 (c) — Hybrid PDF extractor restored + header_normalization phantom reconciled (DEC-030, Track 6)

### What changed

- **`src/resume_parsing/ocr.py` (NEW)** — restored the optional PDF → text bridge the parser (`src/resume_parsing/parser.py`) was already gated on. Declares `_HAS_PDFPLUMBER`, `_HAS_PYPDFIUM`, `_HAS_PDF2IMAGE` availability flags at import time. Exposes `extract_text_hybrid(path: Path) -> str` running pdfplumber first, pypdfium2 as Poppler-free fallback, pdf2image + OCR as last resort, raising an informative `RuntimeError` if every strategy returns empty text so the parser can mark the resume as unparsable rather than silently producing an empty profile.
- **`tests/unit/test_ocr.py` (NEW)** — 7 unit tests covering the availability flags, the happy-path extraction on the real `01888170110d1ccf.pdf` (John Wood's resume — same fixture as `test_resume_parser.py`), both `RuntimeError` paths (no backends / empty backends via monkeypatch), and the individual private backend wrappers (`_extract_with_pdfplumber`, `_extract_with_pypdfium`). Each PDF-exercising test carries `pytest.mark.skipif(not _HAS_*)` so the suite is green in environments where backends are missing.
- **`tests/unit/test_resume_parser.py`** — added `pytest.mark.skipif(not _HAS_OCR, ...)` to `test_parse_resume_extracts_contact_and_name` so the existing PDF fixture test is exercised when PDF backends are installed and cleanly skipped when they are not. The test now passes (had been the single failing test for many sessions).
- **Doc reconciliation of the `header_normalization.py` phantom.** Four doc references reconciled: `CURRENT_PROGRESS.md` Header Normalization row, `MODEL_REGISTRY.md` Header Normalization row, `IMPLEMENTATION_ROADMAP.md` Header Normalization line, `ARCHITECTURE_CHANGELOG.md` initial-creation entry annotated with the Track 6 note. All now point at `src/resume_parsing/parser.py` as the real implementation location (the `SECTION_HEADERS` dict, `sectionize()`, and `identify_section_heading()` functions).
- **`docs/TROUBLESHOOTING.md`** — appended the full debugging trail for the missing `ocr.py` issue (problem → symptoms → root cause → investigation process → solution → verification → prevention). Reusable pattern for future optional-dependency missing-module investigations.
- **`docs/ENVIRONMENT_NOTES.md`** — appended the PDF back-end availability matrix and the optional-dependency pattern description (`_HAS_X` flags declared at import time, fail-open at import, fail-closed at call time).

### Why

- `parser.py` already lazy-imported `ocr` via `try/except ImportError` but the actual `ocr.py` file did not exist, so the parser raised `RuntimeError` whenever a `.pdf` path reached `extract_text_from_path` — even on machines where `pdfplumber` was already installed. The fixture PDF test (`test_parse_resume_extracts_contact_and_name`) had been the single failing test for many sessions.
- The `header_normalization.py` phantom existed because a docs-only architecture draft was never reconciled with the actual code. The section-header classification logic was folded into `src/resume_parsing/parser.py` early on, but the doc references continued to point at a non-existent dedicated file. Future contributors chasing the phantom wasted time navigating to a file that didn't exist.

### Where

| Layer | File | Change |
|---|---|---|
| Resume parsing (optional) | `src/resume_parsing/ocr.py` (NEW) | Hybrid PDF → text bridge with three back-ends. |
| Tests | `tests/unit/test_ocr.py` (NEW) | 7 unit tests, all passing. |
| Tests | `tests/unit/test_resume_parser.py` | Added `skipif(not _HAS_OCR)` guard. |
| Docs | `docs/CURRENT_PROGRESS.md`, `docs/MODEL_REGISTRY.md`, `docs/IMPLEMENTATION_ROADMAP.md`, `docs/ARCHITECTURE_CHANGELOG.md`, `docs/TROUBLESHOOTING.md`, `docs/ENVIRONMENT_NOTES.md` | Phantom reconciliation + debugging trail + environment notes. |

### Impact

- **The pre-existing single failing unit test now passes.** `test_parse_resume_extracts_contact_and_name` runs `parse_resume(<pdf>)` and extracts "John Wood" + phone + email from the real `01888170110d1ccf.pdf` fixture via `pdfplumber`.
- **Suite is perfect green:** 455/455 unit tests pass (+7 vs the prior 448/448 baseline after Track 5; +1 fix for the previously failing PDF test).
- **No new runtime dependencies.** `pdfplumber` and `pypdfium2` were already in `requirements.txt`; `ocr.py` simply wires them up.
- **Docs no longer point at a phantom `header_normalization.py` file.** Future contributors reading the roadmap, model registry, current-progress table, or architecture changelog will see that the section-header classification logic lives in `src/resume_parsing/parser.py`.
- **No architectural change.** The deterministic parser path, structured profile, scoring engine, RAG pipeline, and composed scorer are all unchanged.

### Migration

- **No code migration required.** Callers of `parse_resume` immediately benefit on environments where `pdfplumber` or `pypdfium2` is installed — no API change.
- **Environments without PDF back-ends** continue to write `_HAS_OCR = False` at import time and skip the new PDF-related tests via `skipif`. No action needed.
- **To enable scanned-PDF OCR support** (currently a placeholder in `_extract_with_pdf2image_ocr`), install `pdf2image` + Poppler on the system PATH + an OCR engine (e.g. `pytesseract`). The placeholder OCR invocation site is the only code path that needs extension when OCR back-ends are added.

### References

- **Decision record:** `docs/DECISIONS.md` (DEC-030)
- **Status snapshot:** `docs/CURRENT_PROGRESS.md` (Track 6 row, all 5 steps ✅)
- **Release notes:** `docs/RELEASE_NOTES.md` (2026-07-06 Track 6 Added/Fixed/Unchanged entries)
- **Debugging trail:** `docs/TROUBLESHOOTING.md` (Missing optional modules entry)
- **Environment notes:** `docs/ENVIRONMENT_NOTES.md` (PDF back-end availability matrix)

---

## 2026-07-06 (b) — Composed Mode1 × Mode2 scorer shipped (DEC-028, Track 2-S)

### What changed

- **Production scoring formula switched to the canonical WORKING_LOGIC spec.** Per REQ, `Sub-Score = Code_only_part × Rubric_LLM_part` (both ∈ [0, 1]); `Contribution = weight% × Sub-Score`; `Total = Σ Contribution`. Recruiter weights sum to 100, so `Total` lands in [0, 100] without any `scale_factor`. Missing `expected_years` is a block (contribution 0 + "BLOCKED:" reason), not a default-10.
- **New production score path:** `src/scoring/unified_scorer.py::evaluate_candidate_composed` (the full composition) backed by `src/scoring/graded_scorer.py::evaluate_candidate_code_only_v2` (code-only fallback) and `src/rag/per_req_retrieval.py::retrieve_evidence_for_req` (evidence supplier).
- **New audit log:** `src/audit/no_evidence_flags.py` writes `data/audit/no_evidence_flags.jsonl` — one line per `(candidate, REQ)` pair with zero retrieved evidence. Fields: `timestamp` (ISO 8601 UTC), `candidate_id`, `role`, `req_id`, `requirement_name`, `sub_query_keys`, `sub_query_count`, `theta`, `chunker`, plus any `extra` (with reserved-name protection).
- **New dataclasses:** `ComposedREQResult`, `ComposedCandidateEvaluation` (in `unified_scorer.py`); `CodeOnlyCandidateEvaluation` (in `graded_scorer.py`).
- **Legacy `scale_factor` math** (in `graded_scorer.evaluate_candidate`) and **legacy `DEFAULT_EXPECTED_YEARS = 10`** default are kept as backward-compat shims but are no longer in the production path.

### Why

DEC-024 pivoted Stage-4 retrieval (DEC-027 / Track 1 / M0.5a) but did not specify the scorer that consumes the new pipeline. WORKING_LOGIC §1262-1289 defines the canonical `Mode1 × Mode2` composition formula and requires recruiter weights to sum to 100 with no `scale_factor`. The legacy `DEFAULT_EXPECTED_YEARS = 10` silently masked JD-quality issues and violated the "AI assumptions must not replace recruiter priorities" principle in AGENTS.md. This change aligns the production score path with the spec and gives the Track 1 pipeline its first production consumer.

### Where

| Layer | File | Change |
|---|---|---|
| Scoring (production) | `src/scoring/unified_scorer.py` | Added `evaluate_candidate_composed` + `ComposedREQResult` + `ComposedCandidateEvaluation` + sub-query classification helpers (`_is_binary_subquery`, `_is_years_subquery`, `_is_rubric_subquery`) + per-SQ scoring helpers (`_score_presence_sq`, `_score_years_sq`) + `_build_section_evidence` adapter. Legacy `evaluate_candidate_unified` untouched. |
| Scoring (code-only) | `src/scoring/graded_scorer.py` | Added `evaluate_candidate_code_only_v2` + `extract_expected_years` + `CodeOnlyCandidateEvaluation`. Drops `scale_factor` and `DEFAULT_EXPECTED_YEARS` from the new path; legacy `evaluate_candidate` untouched (kept as shim). |
| Audit | `src/audit/no_evidence_flags.py` (NEW) | Append-only JSONL writer for zero-evidence flags. |
| Tests | `tests/unit/test_composed_scorer.py` (NEW) | 38 unit tests, all passing. Uses a 4-dim synthetic `toy_index` + `sq_embedder` stub to avoid the MiniLM download in tests. |

### Impact

- **Deterministic scoring engine remains the only ranking signal.** The LLM only scores rubric sub-questions within a single REQ (one `rubric_scorer.score_requirement_with_rubric` call per REQ). Final candidate order is reproducible and auditable.
- **Auditability.** Every zero-evidence REQ is flagged for human review in `data/audit/no_evidence_flags.jsonl`. Every REQ result carries its `code_only_part`, `rubric_llm_part`, `sub_score`, and contribution, plus the retrieved evidence chunks (`chunk_id`, `similarity`) that grounded the rubric call.
- **No recounting.** Two REQs may cite the same evidence (union across the REQ's sub-query set dedups by `chunk_id`), but each REQ measures a different dimension (`Code_only_part` derives from the SQ's own type, `Rubric_LLM_part` derives from the rubric call scoped to that REQ).
- **Production wiring pending.** The composed scorer is shipped and unit-tested but no batch scoring CLI invokes it yet. The next step is `scripts/score_batch_composed.py` to swap batch scoring from `graded_scorer.evaluate_role` to `evaluate_candidate_composed`. Until then the legacy batch CLI remains the live production path.

### Migration

- **Callers of `graded_scorer.evaluate_candidate` / `unified_scorer.evaluate_candidate_unified`** keep working — both legacy paths are untouched. To opt in to the canonical formula, call `evaluate_candidate_composed` (full mode) or `evaluate_candidate_code_only_v2` (code-only fallback).
- **`DEFAULT_EXPECTED_YEARS = 10`** is kept in `graded_scorer.py` as a deprecation marker. Code that imports it will keep working; the new path does not use it.
- **No data migration.** The Track 1 index (`data/embeddings/index.npz`, 6,670 chunks) is reused as-is. Only the new scorer consumes it.

### References

- **Decision record:** `docs/DECISIONS.md` (DEC-028)
- **Status snapshot:** `docs/CURRENT_PROGRESS.md` (Track 2-S row, all steps ✅)
- **Release notes:** `docs/RELEASE_NOTES.md` (2026-07-06 Track 2-S entries)
- **Spec:** `docs/WORKING_LOGIC.md` (§1262-1289 scoring formulas)

---

## 2026-07-06 (a) — M0.5a stage-4 code shipped (DEC-027)

### Added

- **`src/rag/recursive_chunker.py` — active chunker (DEC-019).** LangChain-free `recursive_split_text` with the separator hierarchy `["\n\n", "\n", ". ", " "]`. Defaults `chunk_size = 500`, `chunk_overlap = 100`. Owner-specified Optuna bounds enforced at construction time: `chunk_size ∈ [200, 500]`, `chunk_overlap ∈ [100, floor(0.60 * chunk_size)]`. Bounds exported as module-level constants (`CHUNK_SIZE_LOWER`, `CHUNK_SIZE_UPPER`, `CHUNK_OVERLAP_LOWER`, `CHUNK_OVERLAP_MAX_FRACTION`, `max_overlap_for`) so Optuna can import them directly.
- **`src/rag/per_req_retrieval.py` — canonical SubQuery evidence-gathering entry point.** `retrieve_evidence_for_req()` embeds every sub-query for a REQ (or accepts caller-supplied vectors), calls `ThresholdRetriever.retrieve_scored` once per sub-query with the `candidate_id` filter, unions + dedupes by `chunk_id` (keeping the highest cosine and remembering which sub-query produced each hit), sorts the union desc, applies the final cap, and returns `[]` on zero retrieval so the caller raises the no-evidence flag at `reports/audit/no_evidence_flags.jsonl`.
- **`src/rag/build_index.py` — production index builder + CLI.** Walks `data/processed/<role>/*.json`, filters out `_intelligence_report.json` / `_structured_profile.json` downstream artifacts so only the 721 canonical parsed resumes are indexed, chunks each with `RecursiveChunker`, batch-embeds with MiniLM-L6-v2 (DEC-007, 384-dim, L2-normalized), and persists to `data/embeddings/index.npz` + `data/embeddings/chunks.jsonl` via `VectorIndex.save_npz`. Supports `--dry-run`, `--batch-size`, `--chunk-size`, `--chunk-overlap`, `--no-backup`.
- **`tests/unit/test_per_req_retrieval.py`** — 11 tests covering union dedup, candidate filter, threshold filter, zero-retrieval, cap, sorting, threshold override.
- **`tests/unit/test_cache_key.py`** — 11 tests locking in the theta-in-key invariant (`theta` change always invalidates the key; quantized to 6 decimals; `None` vs explicit differ).
- **`data/embeddings/document_aware_backup/`** — the previous Document-Aware index (`index.npz` + `chunks.jsonl`, 6,377 chunks) backed up here so a Document-Aware rollback is one `mv` command.

### Changed

- **`src/rag/retriever.py` — active retriever switched from top-K to threshold-based cosine (DEC-018).** `ThresholdRetriever` returns every chunk with `cosine >= theta`, sorted desc, capped at `max_chunks_per_query`. Defaults `theta = 0.30` (midpoint of [0.10, 0.50]), `max_chunks_per_query = 20`. A WARN log fires on cap-hit so a misconfigured `theta` is loud rather than silent. Bounds exported as `THRESHOLD_LOWER` / `THRESHOLD_UPPER` constants.
- **`src/rag/recursive_chunker.py::RecursiveChunker.chunk_profile`** — defensive coercion of `experience` / `education`. The chunker now treats non-dict shapes (list, None, str) as `{"entries": []}` so real-world parser-output variance does not crash the build. Discovered while running the first dry-run against the 721-resume corpus.
- **`src/services/subquery_parser.py::_extract_requirements`** — extended to parse SubQuery table rows (`SQ### | text | type | scale | assessment_method`) into a `sub_queries` list per REQ. Verified across all 8 role SubQuery files: 138 REQs, 356 sub-queries, 0 declared-vs-parsed mismatches.
- **`src/services/subquery_retrieval.py::make_cache_key`** — added `theta` kwarg (defaults to `None` for backward compatibility). Folded into the SHA-256 hash, quantized to 6 decimals. All 3 callers (per-REQ scoring + 2 in batched scoring) updated to thread the retrieval `threshold` into the key. The rationale: `theta` is the one Optuna hyperparameter whose change can leave the chunk-id set *identical*, so without `theta` in the key the cache would silently return sub-scores computed under a different trial.
- **`data/embeddings/index.npz` + `chunks.jsonl`** — rebuilt from 721 resumes via `build_index.py`. New shape: **6,670 chunks, 384-dim, 8.4 MB** (was Document-Aware's 6,377 chunks). Build time ~135 s on CPU.

### Unchanged

- The deterministic scoring engine remains the only ranking signal. The LLM remains the information-extraction layer, not the scorer.
- `DocumentAwareChunker` is retained at `src/rag/document_aware_chunker.py` (not renamed, not deleted) as a one-release migration aid per DEC-022. Production code paths still use `RecursiveChunker` exclusively.
- The legacy `src/services/subquery_retrieval.py::retrieve_chunks_for_requirement` is still live and unchanged except for the cache-key signature update. Track 2 (scorer refactor) will replace it with the per-REQ path as its scoring consumer.
- `ChunkRecord` schema is unchanged — the new Recursive chunker emits the same dataclass as the Document-Aware chunker, so downstream embedding, retrieval, and scoring code is untouched.

### Decision

- **Optuna bounds are owner-specified, not doc-specified.** The shipped defaults (`theta = 0.30`, `chunk_size = 500`, `chunk_overlap = 100`) differ from the 2026-07-05 doc defaults (DEC-018/019 listed `theta = 0.70`, `chunk_overlap = 50`) but match the owner's 2026-07-06 spec. The default values sit inside the search range so the default-config run is a valid point in the Optuna sweep.
- **The embedding index needs to be rebuilt only when `chunk_size` or `chunk_overlap` changes.** `theta` is a retrieval-time parameter and does not affect the index. The Optuna sweep can therefore reuse the same `index.npz` across all theta trials and only rebuild when it varies `chunk_size` or `chunk_overlap`.
- **The previous Document-Aware index is preserved at `data/embeddings/document_aware_backup/`.** A rollback to Document-Aware chunking for debugging is possible by moving the backup back into place.
- **113 candidates were silently dropped** during the index build (721 resumes → 608 unique candidate_ids in the index) because their parsed profile produced zero non-empty sections. This is a parser-quality issue and is tracked for Track 6; the index correctly excludes them since they would produce zero-chunk noise in retrieval.

### Risks

- **No production score path is wired through `per_req_retrieval` yet.** The new module is the canonical entry point for SubQuery scoring, but the legacy `retrieve_chunks_for_requirement` is still live. Track 2 will replace it.
- **The cache-hit rate will drop during the Optuna sweep** because `theta` is now part of the cache key. This is a deliberate tradeoff for per-trial isolation. After the sweep promotes a single "Active" config (M0.5d), the hit rate returns to its pre-sweep level.
- **403 / 404 unit tests pass.** The single pre-existing failure (`test_parse_resume_extracts_contact_and_name`) is the `src/resume_parsing/ocr.py` missing-module issue, deferred to Track 6.

---

## 2026-07-05 (d) — Chunk reports folder + ranking evaluation methodology (DEC-024)

### Added
- **Reports folder convention.** `reports/chunk_reports/` is the canonical home for per-experiment chunk diagnostics. Report file names mirror the experiment folder names:
  - `document_aware_chunking_report.{json,md}` — historical diagnostic of the 721-resume Document-Aware corpus (the DEC-015 49%-missing-`section_type` finding).
  - `recursive_chunking_<chunk_size>_<overlap>_<top_k>_<threshold×100>_report.{json,md}` — per-experiment Recursive diagnostic.
- **Multi-pronged ranking evaluation methodology.** Five independent signals for "is our ranking correct?", none of which require a single labeled ground truth: counterfactual tests, synthetic labeled set, stability tests, recruiter agreement, behavioral signals. See `EVALUATION.md` §"Ranking Evaluation Without Labeled Data" for the full spec.

### Unchanged
- The deterministic scoring engine remains the only ranking signal.
- Per-experiment folder convention from DEC-023 is unchanged; reports are siblings of the experiment folders, not children.
- The per-resume cache key from DEC-022 is unchanged.

### Decision
- **Reports are committed to git** — they are small text files (a few KB) and the historical record of every experiment matters. Binaries (chunks, index, caches) stay in `.gitignore`; reports do not.
- **Five signals, not one** — the platform's claim "rankings are correct" is now backed by five independent signals. The user-facing promise is "we have five ways to catch ranking regressions; if all five agree the ranking is good; if any one disagrees we investigate".
- **Counterfactual tests are built first** — they are cheap, automated, and run on every config. They are the fast feedback loop for the Optuna sweep (M0.5d).

### Risks
- The Document-Aware report is generated from already-moved files; if the migration to `data/document_aware_chunking/` (M0.5e-a) is not yet complete, the report must wait. The report can be regenerated any time from the source chunks.
- The synthetic labeled set decays over time (a "great" candidate last year may not be a "great" candidate this year). Quarterly refresh is the planned cadence; documenting the decay in `EVALUATION.md` is required.
- Behavioral signals are noisy and require production data. They are tracked, not enforced; an empty behavioral signal is not a regression.

### Related decisions
- `DECISIONS.md` DEC-024 (chunk reports folder + ranking evaluation methodology).

---

## 2026-07-05 (c) — Per-experiment folder naming + folder renames (DEC-023)

### Changed
- **Legacy folder renamed.** `data/chunks_legacy_document_aware/` → `data/document_aware_chunking/`. The 721 Document-Aware chunk files + `MIGRATION_NOTES.md` move with the directory. Code paths and docs that referenced the old name are updated to the new one. The `.gitignore` rule moves with the directory.
- **Per-experiment folder convention adopted.** Every MLflow run for the Recursive chunking pipeline now writes its artifacts to `data/recursive_chunking_<chunk_size>_<overlap>_<top_k>_<threshold×100>/`. Field order is fixed: chunk_size, overlap, top_k, threshold×100. `x` is used for an inactive dimension (e.g., pure threshold mode has no `top_k` cap).
- **Active experiment symlink.** When a config is promoted to "Active" in `MODEL_REGISTRY.md`, its folder is symlinked (or copied) to `data/active_experiment/` so the runtime can find it without hardcoding hyperparameter values. The `Active` row in `MODEL_REGISTRY.md` is the source of truth.
- **Disk-usage alert threshold raised.** From 5 GB (DEC-022d) to **20 GB** to accommodate the larger per-experiment storage footprint (~10–15 GB at peak across an Optuna sweep).

### Unchanged
- Cache key from DEC-016/DEC-022: `(candidate_id, req_id, hash(query, sorted(top-chunk-ids)), model_name, θ)`. The cache key already encodes the hyperparameters via `θ`; the folder name is a human-readable mirror.
- The deterministic scoring engine still applies weights and aggregates in code; per-resume reasoning is the input it reads.
- The RAG grounding rule is preserved: if no chunk meets θ, the LLM is called once, returns `"Information not found in candidate documents."`, and that string is stored as the `reasoning` value.

### Decision
- **Folder name is the self-documenting identifier of the experiment.** Numeric form (`500_200_5_50`) is preferred over hash-based names because the recruiter and the engineer both need to read the folder name and know "this is the experiment with chunk_size=500, overlap=200, top_k=5, threshold=0.50". A short hash would force them to look up `metadata.json` first.
- **Same-config runs share a folder.** If two MLflow runs have the same hyperparameters, their artifacts are byte-identical (chunks, index, cache), so sharing the folder is correct. Trial uniqueness lives in the MLflow run ID and Optuna trial ID (logged in `metadata.json` and `mlflow_run_id`), not in the folder name.
- **`data/active_experiment` symlink is the runtime entry point.** Code does not hardcode `data/recursive_chunking_500_50_10_70/`; it follows the symlink. This makes promoting a new Active config a one-line operation.

### Risks
- Folder proliferation: 200 Optuna trials × 3 studies = ~600 folders. Manageable, but `data/recursive_chunking_*` should be GC'd after each study (move to `data/archive/<study_name>/`).
- Disk-usage growth: 10–15 GB peak. The 20 GB alert is the trip-wire; the 5 GB alert from DEC-022d was too aggressive.
- The `x` placeholder convention for inactive dimensions could be confused with the literal value 0; documented clearly in `WORKING_LOGIC.md` and `MODEL_REGISTRY.md`.

### Related decisions
- `DECISIONS.md` DEC-023 (per-experiment folder naming + folder renames).
- DEC-022 is refined; its storage layout section is superseded by DEC-023's per-experiment convention.

---

## 2026-07-05 (b) — Per-resume reasoning storage + legacy chunk migration

### Changed
- **Storage layout split.** Two new directories under `data/`:
  - `data/chunks_legacy_document_aware/<role>/<candidate_id>.jsonl` — moved from `data/chunks/` on M0.5a. Contains the 721 Document-Aware chunk files produced pre-2026-07-05. A `MIGRATION_NOTES.md` in the directory records the move date, source/target chunkers, and per-file chunk-count delta.
  - `data/per_candidate/<role>/<candidate_id>/reasoning/<req_id>__<query_hash>.json` — new per-resume artifact tree. Stores, per (candidate, req, query), the LLM's full output: reasoning narrative, basis (cited chunks + quotes), retrieved-chunks list, and sub-scores.
- **Cache layout replaced.** The single `data/embeddings/llm_cache.jsonl` is **superseded** by the per-resume reasoning tree. New code reads from `data/per_candidate/.../reasoning/`; the old file is moved to `data/embeddings/llm_cache_legacy.jsonl` for backward-compat reads during the migration window.

### Unchanged
- Cache key from DEC-016/DEC-022: `(candidate_id, req_id, hash(query, sorted(top-chunk-ids)), model_name, θ)`.
- The deterministic scoring engine still applies weights and aggregates in code; per-resume reasoning is the input it reads.
- The RAG grounding rule is preserved: if no chunk meets θ, the LLM is called once, returns `"Information not found in candidate documents."`, and that string is stored as the `reasoning` value for the (candidate, req) pair.

### Decision
- **Storage is a feature, not a cost.** The per-resume reasoning tree adds ~1–2 GB at peak during an Optuna sweep, but it eliminates the LLM round-trip on re-runs and makes the LLM's behavior auditable per-(candidate, req). Both are non-negotiable under DEC-022.
- **Legacy chunks are moved, not deleted.** Renaming is strictly safer during a migration window. `DocumentAwareChunker` is retained in code for one release; the old chunks are retained on disk for that same release.
- **`MIGRATION_NOTES.md` is the only committed artifact in the legacy directory.** The 721 JSONL files themselves are added to `.gitignore` (large binaries; reproducible from the source resumes + `DocumentAwareChunker`).

### Risks
- Storage growth can outpace the .gitignore strategy. Add a GC job (90-day archive) and a disk-usage monitor in `ENVIRONMENT_NOTES.md`.
- Per-resume reasoning files contain PII (candidate name, employer history, etc.). They inherit the same PII policy as `data/processed/` — local-only, never logged, never uploaded.
- The migration move is a one-time `mv` of 721 files. If it fails partway, `MIGRATION_NOTES.md` records which files have been moved and which haven't; the script is idempotent.

### Related decisions
- `DECISIONS.md` DEC-022 (per-resume reasoning storage + legacy chunk migration).
- DEC-016 (LLM sub-score cache) is now realized as a per-resume tree rather than a single JSONL file.

---

## 2026-07-05 — Regular RAG pivot + MLflow + Optuna

### Changed
- **Retrieval strategy simplified to regular RAG.** Section-Routed (DEC-012) and Sub-Query Similarity (DEC-015) are retired as the active retrieval path. All retrieval — per-candidate scoring, cross-candidate pool search, resume chat — now uses a single Recursive Chunking + dense cosine + threshold-based retrieval pipeline (DEC-017, DEC-018, DEC-019).
- **Chunking strategy switched from Document-Aware to Recursive.** `src/rag/chunker.py` exposes `RecursiveChunker` as the active strategy. The previous `DocumentAwareChunker` is retained for one release under that name as a migration aid. Defaults: `chunk_size = 500`, `chunk_overlap = 50`. Both are Optuna hyperparameters.
- **Retrieval mode switched from `top_k` to `threshold θ`.** All retrieval now returns chunks with cosine ≥ `θ` (default `0.70`), with a hard `max_chunks_per_query = 20` cap to bound context size. `θ` is an Optuna hyperparameter.
- **MLflow added for experiment tracking.** Every retrieval/scoring run logs params + metrics + artifacts to a local MLflow server at `http://127.0.0.1:5000` (SQLite backend, filesystem artifact root). See DEC-020.
- **Optuna added for hyperparameter search.** Multi-objective study (maximize faithfulness, minimize avg_chunks_returned) with TPE sampler and SQLite study store at `data/optuna/studies.db`. See DEC-021.

### Unchanged
- The deterministic scoring engine (`src/scoring/graded_scorer.py`, `src/scoring/unified_scorer.py`) is the **only** ranking signal. RAG feeds evidence; code computes the score.
- The LLM is restricted to extraction, rubric-bound evidence scoring, and answer generation. The LLM never sees the requirement's weight and never computes the final weighted contribution.
- The RAG grounding rule is preserved: if no chunk meets `θ`, the LLM responds with `"Information not found in candidate documents."`
- The tier databases (`data/Institutes/institute_tiers.json`, `data/Certificates/certificate_tiers.json`) and the flagged-institute detection are unchanged.
- The structured candidate profile (`src/resume_parsing/structured_profile.py`) is unchanged; it still relies on Header Normalization for parse-time section labeling.
- Cache key from DEC-016 is updated to `(candidate_id, req_id, hash(query, top-chunk-ids), model_name, θ)`.

### Decision
- **Regular RAG is sufficient when the deterministic scorer is the only ranking signal.** The two-strategy (Section-Routed + Sub-Query Similarity) design was over-engineered for the actual use case: a small candidate pool where final ranking never depends on retrieval quality. The saved complexity goes into Optuna-calibrated hyperparameters instead.
- **MLflow + Optuna are paired.** Optuna drives the search, MLflow logs every trial, and the Pareto-front recommended point is exported to `MODEL_REGISTRY.md` as the new "Active" config. The shipped config is always data-driven, never hand-picked.
- **Header Normalization survives the chunking change** because the structured profile still needs labeled sections for degree/certification/total-experience extraction. It is no longer on the retrieval hot path.

### Risks
- The chunking change is not yet implemented in code (planned for M0.5a in `IMPLEMENTATION_ROADMAP.md`). Until then, the existing `DocumentAwareChunker` and `Sub-Query Similarity` paths remain live.
- The Optuna eval set is the new bottleneck: a small or biased eval set will produce a confidently-wrong `θ`. Building the eval set is the first prerequisite for M0.5b.
- `θ` is dataset-sensitive. The default `0.70` is a placeholder until the first Optuna study completes.

### Related decisions
- `DECISIONS.md` DEC-017 (regular RAG pivot), DEC-018 (threshold retrieval), DEC-019 (recursive chunking), DEC-020 (MLflow), DEC-021 (Optuna).
- DEC-012 and DEC-015 are now superseded by DEC-017.

---

## 2026-07-01 — Tier database expansion (international institutes + certs + fake flagging)

### Changed
- **`data/Institutes/institute_tiers.json`** expanded from ~356 to **466 institutes**:
  - Tier 1: 137 → **192** (+55 international universities: USA, UK, Germany, Canada, Finland, Mexico, South Korea per QS World Rankings 2025).
  - Tier 2: 54 → **98** (+44 international universities).
  - Tier 3: 165 → **176** (+11 new + 13 fake/unknown flagged).
- **`data/Certificates/certificate_tiers.json`** expanded to **223 certificates**:
  - Tier 2 additions: Spring Professional, Oracle Academy, Cloudera, SAS, SQL Server, Adobe Expert, Python Institute.
  - Tier 3 additions: NLP Practitioner, Django, Python Developer, FreeCodeCamp, CNPR, Certified Sales Rep, Salesforce, Java SE, Tableau Desktop/Server, Microsoft Data Analyst, Google Cloud PE, Certified Data Scientist.

### Added
- **Flagged institute detection** in `src/scoring/tier_lookup.py`:
  - `is_institute_flagged(name)` — returns True for fake/unknown universities.
  - `get_flagged_institutes()` — returns full list of flagged entries.
  - 13 flagged institutes marked with `_note` field in `institute_tiers.json`.
- **Flagged penalty** in `src/scoring/unified_scorer.py`: flagged institutes receive a **50% penalty** on education score.
  - Formula: `degree_match × institute_tier_points × 0.5` (vs. `× 1.0` for non-flagged).
- **Structured profile fields** in `src/resume_parsing/structured_profile.py`:
  - `flagged_institutes: List[str]`
  - `has_flagged_institute: bool`

### Decision
- Flagged institutes are placed in **Tier 3 (0.5 points)** — same as unlisted. This ensures they don't get penalized excessively but also don't get undue credit.
- The 50% penalty is applied **multiplicatively on top of** the tier points, so a flagged Tier 3 entry contributes 0.25 effective points instead of 0.5.
- See `AI_DESIGN_RATIONALE.md` §11 for the full rationale.

### Countries covered in tier database

| Country | Tier 1 | Tier 2 | Tier 3 | Total |
|---------|--------|--------|--------|-------|
| USA | 30+ | 15+ | 5+ | 50+ |
| UK | 8 | 10 | 2 | 20 |
| Germany | 3 | 7 | 3 | 13 |
| Canada | 3 | 7 | 7 | 17 |
| Finland | 2 | 3 | 4 | 9 |
| Mexico | 1 | 4 | 3 | 8 |
| South Korea | 3 | 6 | 8 | 17 |

---

## 2026-07-01 — Phase 4.5 pipeline (parse + chunk + score 721 resumes)

### Added
- `scripts/phase45_pipeline.py` — end-to-end batch pipeline: parse → header normalization → structured profile → chunk → score → intelligence report. Accepts `--role`, `--all-roles`, `--skip-scoring`.
- 721 parsed profiles in `data/processed/<role>/` (8 role folders, one JSON per candidate).
- 721 structured profile records in `data/processed/<role>/<id>_structured_profile.json`.
- 721 chunk files in `data/chunks/<role>/<candidate_id>.jsonl` (Document-Aware chunking with full metadata schema: `section_type`, `parent_structure`, `temporal_context.calculated_duration_months`, `skills_asserted`, `experience_type`).
- 8 ranked score files in `data/scores/graded/<role>_ranked.json` with per-item evidence (matched, years_detected, snippet, reason, section).
- 721 Candidate Intelligence Reports in `data/processed/<role>/<id>_intelligence_report.json`.

### Changed
- `CURRENT_PROGRESS.md` — Candidate Intelligence Report status 🟡→✅; Next Recommended Unit of Work reframed around remaining Phase 4.5 items.
- `RELEASE_NOTES.md` — 2026-07-01 entry added.

### Decision
- The pipeline currently scores in **code-only mode** (`graded_scorer.evaluate_candidate`) because the `unified_scorer` routes skill items to rubric-bound LLM mode, which returns zero when no LLM caller is provided. The code-only graded scorer handles skill presence + years detection with synonym match and regex, producing non-zero evidence-backed scores. Wiring the rubric-bound LLM scorer (which scores skill depth, relevant experience, project complexity) requires an LLM caller and is the next step.

---

## 2026-06-30 — Two-mode scoring engine + foundation modules

### Added
- `src/resume_parsing/header_normalization.py` — Layer 1 synonym table + Layer 2 LLM fallback for 7 canonical sections (Personal_Info, Education, Experience, Projects, Skills, Certifications, Languages). — **Note (Track 6 reconciliation, 2026-07-06):** this file was never actually checked in — the same logic lived in `src/resume_parsing/parser.py` (the `SECTION_HEADERS` dict, `sectionize()`, and `identify_section_heading()` functions). The phantom was reconciled in Track 6 / DEC-030.
- `src/resume_parsing/structured_profile.py` — deterministic Structured Candidate Profile extraction (degrees, institutions, certifications, total experience with no double-counting, companies, roles, employment dates).
- `src/rag/section_routed.py` — Section-Routed Evidence Retrieval: fixed requirement→section mapping table, exact label match, metadata filtering for long sections. No embeddings, no cosine.
- `src/scoring/rubrics.py` — 12 rubric templates with anchored scales (0.0/0.25/0.5/0.75/1.0), sub-questions, and formulas per dimension type. Code-only vs rubric-bound LLM classification.
- `src/scoring/rubric_scorer.py` — RUBRIC-SCORE-001 prompt construction, LLM response parsing, formula evaluation in code, `CachedScoringTrace` frozen at scoring time, `explain_score_from_cache` for score explanation.
- `src/scoring/unified_scorer.py` — Unified scoring engine: routes each requirement to code-only or rubric-bound LLM mode, produces `UnifiedCandidateEvaluation` with per-item scoring traces.
- `src/scoring/tier_lookup.py` — code-only tier lookup for institutes and certificates with word-boundary matching.
- `data/Institutes/institute_tiers.json` — 115 Tier 1, 54 Tier 2, 155 Tier 3 institutes; not-listed=0.50.
- `data/Certificates/certificate_tiers.json` — 115 Tier 1, 45 Tier 2, 10 Tier 3 certificates; not-listed=0.50.
- `src/rag/chunker.py` updated — chunk metadata schema: `section_type`, `parent_structure` (organization, role_title, location, temporal_context with `calculated_duration_months`), `skills_asserted`, `experience_type`.
- 279 unit tests across all new modules.

### Changed
- `WORKING_LOGIC.md` — tier system updated from 4 tiers (A/B/C/D) to 3 tiers (1/2/3) + not-listed=0.50.
- `CURRENT_PROGRESS.md` — all foundation modules and scoring modes marked ✅.
- `MODEL_REGISTRY.md` — registered all new modules (header normalization, section-routed retrieval, rubric templates, rubric scorer, unified scorer, tier databases, structured profile).
- `PROMPT_LIBRARY.md` — RUBRIC-SCORE-001 marked Active (v1.0).

### Decision
- **Two-mode scoring engine implemented.** Code-only mode scores education, certification, and location using tier databases and structured profiles (no LLM). Rubric-bound LLM mode scores skill depth, experience, leadership, projects, languages, and communication quality using anchored rubric scales (LLM never sees weight or computes aggregation).
- **Section-Routed Evidence Retrieval replaces cosine for per-candidate scoring.** Dense cosine remains only for cross-candidate pool search and resume chat.
- **Tier databases are recruiter-editable JSON files.** Not-listed institutes/certs default to 0.50 (same as Tier 3) unless evidence places them in Tier 1 or Tier 2.

---

## 2026-06-19 (PM) — Doc alignment sweep (WORKING_LOGIC.md as canonical)

### Added
- `docs/CURRENT_PROGRESS.md` — single status doc mapping every step of `WORKING_LOGIC.md` to ✅ / 🟡 / ⬜.
- `docs/WORKING_LOGIC.md` is now the canonical scoring/evaluation spec (DEC-011). All other docs defer to it for scoring details.

### Changed
- `PROJECT_OVERVIEW.md` — added JD clarification loop (Green / Yellow / Red), per-item `expected_years`, single canonical scorer, RAG-as-explanation flow.
- `SYSTEM_ARCHITECTURE.md` — Job Service now runs the clarification loop; Scoring Engine is the single canonical scorer; RAG Engine is explanation-only.
- `AI_ARCHITECTURE.md` — §3 (JD processing) now includes the clarification classifier; §5 (Candidate Evaluation) rewritten around the single canonical scorer; legacy triad marked retired.
- `RECRUITER_WORKFLOWS.md` — Workflow 2 now includes Green/Yellow/Red classification; Workflow 3 includes `expected_years`; Workflow 5 includes resume cleaning; Workflow 6 includes the years-proportional scoring rule.
- `EVALUATION.md` — added per-item scoring evaluation metrics (Skill Presence Precision/Recall, Years Detection MAE, Per-item Score Accuracy, Evidence Section Precision, Snippet Faithfulness, Score Reproducibility).
- `PROMPT_LIBRARY.md` — added SCORE-EXPLAIN-001 and CANDIDATE-COMPARE-001 prompt specs; marked RESUME-CHAT-001 as Active.
- `IMPLEMENTATION_ROADMAP.md` — added Phase 4.5 (clarification loop + quality tiers + Candidate Intelligence Report); updated Phase 6 to reflect the mostly-built RAG pieces.
- `DECISIONS.md` — added DEC-010 (single canonical scorer) and DEC-011 (WORKING_LOGIC.md is canonical); superseded DEC-008.

### Decision
- **WORKING_LOGIC.md is the canonical scoring/evaluation spec.** All other docs defer to it for scoring details. `CURRENT_PROGRESS.md` is the single status doc.

---

## 2026-06-19 (PM) — Phase 4 scorer consolidation

### Added
- Single canonical scorer (`src/scoring/graded_scorer.py`) that satisfies `docs/WORKING_LOGIC.md`.
- Per-item scoring rule: `min(importance, candidate_years / expected_years × importance)` with `importance × 0.3` partial credit for mention-only matches.
- Structured-profile search priority: `experience.entries → skills → education.entries → certifications → projects → summary`.
- Summary-years fallback gated on item category (only non-Education / non-Certification items may use it).
- CLI (`scripts/evaluate_one.py`) prints the recruiter-facing report in the exact format from `docs/PROJECT_OVERVIEW.md` Phase 4.
- Batch CLI (`python -m src.scoring.batch_score`) writes ranked output to `data/scores/graded/<role>_ranked.json`.
- `scripts/compare_scores.py` shows the canonical ranked table + per-candidate top strengths and gaps.

### Removed
- `src/scoring/keyword_scorer.py`
- `src/scoring/semantic_scorer.py`
- `src/scoring/hybrid_scorer.py`
- `src/scoring/evidence.py`
- `src/scoring/evaluate.py` (re-export shim)
- `data/scores/keyword/`, `data/scores/semantic/`, `data/scores/hybrid/`
- `data/scores/BusinessAnalyst_ranked.json` (orphan)
- `tests/unit/test_hybrid_scorer.py`
- `tests/unit/test_semantic_scorer.py`
- `tests/unit/test_scoring.py`

### Changed
- Candidate scoring is no longer a triad of `keyword / semantic / hybrid` modules; those are deprecated and removed. The new `graded_scorer` is the single ranking signal.
- Total normalized to 0-100 using the config's `scale_factor = 100 / max_score`.
- `scripts/compare_two.py` reads from `data/scores/graded/`, surfaces per-item evidence, and accepts `--strategy graded` as the canonical choice (legacy strategy names print a deprecation warning and forward to graded).
- `scripts/demo_scoring.py` shows the canonical per-item breakdown for the top-ranked candidate.

### Decision
- **Single deterministic scorer** — `WORKING_LOGIC.md` is explicit: *"you don't need so many different scoring or ranking systems, just one is enough."* Per-component breakdowns still come from the structured profile, not from running multiple scorers.
- **RAG is reserved for explanations and resume chat** — never for ranking. The scorer itself is deterministic and offline.

---

## 2026-06-19 (PM) — Phase 5

### Added
- Candidate comparison engine (`scripts/compare_two.py`) for side-by-side recruiter-friendly candidate analysis.
  - Loads scored candidate profiles from `data/processed/<role>/<id>.json`.
  - Retrieves canonical graded scores from `data/scores/graded/<role>_ranked.json`.
  - Generates deterministic "Why A ranked above B" narratives using score deltas and component breakdowns.
  - Displays component-level evidence: matched requirement counts, top strengths by category.
- Integration tests for comparison workflow (`tests/integration/test_candidate_comparison.py`, 6 tests passing).
- Evidence-based ranking explanations (no LLM black-box scoring, LLM reserved for future explanation enhancement).

### Changed
- Comparison output format: side-by-side table with normalized scores, score deltas, component breakdowns.
- Phase 5 completes the candidate ranking & comparison pillar of the end-to-end workflow.

### Decision
- **No LLM in scoring chain (Phase 5)** — Explanations are deterministic and auditable. LLM integration deferred to Phase 6+ for enhanced summaries.
- **Candidate ID resolution** — Script auto-resolves user input (file stem or candidate_id) to internal identifiers by searching scores and profiles.

---

## 2026-06-19

### Added
- Established modular service-oriented architecture in `SYSTEM_ARCHITECTURE.md`.
- Established AI workflow architecture in `AI_ARCHITECTURE.md`.
- Established AI design rationale for chunking, embeddings, vector database, LLM usage, scoring, retrieval, RAG grounding, and evaluation.
- Added required governance docs for decisions, model registry, prompt library, evaluation, recruiter workflows, release notes, troubleshooting, and environment notes.
- Added production package foundation under `src/hireintel_ai/` with application entry points, shared config, schemas, ingestion, JD, resume, scoring, ranking, RAG, LLM, storage, and evaluation modules.
- Added test foundation under `tests/unit/`, `tests/integration/`, and `tests/fixtures/`.

### Changed
- Updated `AGENTS.md` architecture compliance references from missing legacy files to current source-of-truth docs.
- Updated the implementation roadmap to include production code foundation before feature implementation.
- Standardized the public product and production package naming on `HireIntel AI` / `hireintel_ai`.

### Risks
- The workspace folder is still named `talentlens_ai`, but product-facing docs and production package names now use `HireIntel AI` / `hireintel_ai`.
