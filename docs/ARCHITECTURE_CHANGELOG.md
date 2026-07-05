# Architecture Changelog

## Overview

This document records architecture changes that affect system structure, runtime behavior, AI workflows, storage, APIs, or deployment.

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
- `src/resume_parsing/header_normalization.py` — Layer 1 synonym table + Layer 2 LLM fallback for 7 canonical sections (Personal_Info, Education, Experience, Projects, Skills, Certifications, Languages).
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
