# Implementation Roadmap

## Overview
This roadmap defines the step-by-step execution plan for HireIntel AI, aligned
with `AGENTS.md`, `docs/PROJECT_OVERVIEW.md`, and the canonical scoring spec
[`docs/WORKING_LOGIC.md`](WORKING_LOGIC.md). For "what is implemented today vs
what's planned", see [`docs/CURRENT_PROGRESS.md`](CURRENT_PROGRESS.md).

---

## Phase 0: Foundation & alignment
1. Confirm repository structure
   - Ensure `/docs` exists and contains required docs.
   - Treat `/docs` as source of truth.
2. Establish documentation process
   - Keep `PROJECT_OVERVIEW.md`, `SYSTEM_ARCHITECTURE.md`, `AI_ARCHITECTURE.md`, `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md`, `PROMPT_LIBRARY.md`, `EVALUATION.md`, `RECRUITER_WORKFLOWS.md`, and `RELEASE_NOTES.md` synchronized with implementation.
3. Establish production code foundation
   - Use `src/hireintel_ai/` as the production package.
   - Keep application entry points under `src/hireintel_ai/app/`.
   - Keep shared configuration under `src/hireintel_ai/core/`.
   - Keep shared typed contracts under `src/hireintel_ai/schemas/`.
   - Keep tests under `tests/unit/`, `tests/integration/`, and `tests/fixtures/`.

---

## Phase 1: Job Description Intelligence
1. Build JD ingestion
   - Support PDF, DOCX, Text input.
2. Extract requirements
   - Required/Preferred skills
   - Experience
   - Education
   - Certifications
   - Industry experience
   - Leadership requirements
   - Technology stack
3. Store structured JD output
   - Use as hiring policy input for scoring and matching.

---

## Phase 2: Recruiter Weight Configuration
1. Create recruiter-configurable scoring policy
   - Support weights for skills and categories.
2. Ensure explicit policy
   - Recruiters assign points.
   - Policy becomes deterministic evaluation rules.

---

## Phase 3: Resume Parsing ✅ Shipped 2026-06-19
1. Build resume ingestion and normalization
   - Support formats in `data/original`. ✅ (PDF + TXT)
   - Use parsing + OCR if needed. ✅ (`pdfplumber` → `pypdfium2` OCR → `pdf2image` fallback)
2. Extract structured candidate profiles
   - Name, contact, education, skills, certifications, languages, experience, projects, technologies, leadership indicators. ✅
3. Capture evidence
   - Link each extracted field to source resume text for explainability. ✅ (`raw_text` + `sections[].start/end` char spans; `candidate_id` SHA1 of source path)

**Artifacts:**
- 721 profile JSONs in `data/processed/<role>/`.
- `src/resume_parsing/{parser, ocr, batch_parse}.py`.
- `tests/unit/test_resume_parser.py` — passing.

---

## Phase 4: Candidate Evaluation Engine ✅ Shipped 2026-06-19 (Mode 1) + 2026-06-30 (Mode 2)

Per `WORKING_LOGIC.md` "Fundamental Rule": the platform ships **one**
deterministic scorer operating in **two modes**:

* **Code-only** — for fully measurable requirements (total experience, degree
  match, institute tier, cert match, provider tier, location). No LLM.
* **Rubric-bound LLM** — for requirements requiring judgment (skill depth,
  relevant experience, leadership, project complexity, language proficiency,
  communication quality). LLM scores against anchored rubric scales; weight
  application and aggregation in code.

1. Implement deterministic scoring (Mode 1)
   - Use recruiter weights + `expected_years` + structured profiles. ✅ (`graded_scorer.py`)
   - Per-item `min(importance, candidate_years / expected_years × importance)`. ✅
2. Implement rubric-bound LLM evidence scoring (Mode 2)
   - 12 rubric templates with anchored scales (0.0/0.25/0.5/0.75/1.0). ✅ (`rubrics.py`)
   - RUBRIC-SCORE-001 prompt: LLM extracts evidence, scores against rubric. ✅ (`rubric_scorer.py`)
   - LLM never sees weight, never computes aggregation. ✅
   - Cached scoring trace frozen at scoring time. ✅ (`CachedScoringTrace`)
3. Implement unified scoring engine
   - Routes each requirement to code-only or rubric-bound LLM. ✅ (`unified_scorer.py`)
   - Both modes feed same weight × sub-score aggregation. ✅
   - Produces `UnifiedCandidateEvaluation` with per-item scoring traces. ✅
4. Produce evidence-backed scoring
   - Score value ✅
   - Supporting evidence ✅ (matched section, snippet, cited text, anchor description)
   - Resume source snippets ✅
   - Cached sub-scores + cited evidence ✅
5. Avoid black-box ranking
   - LLMs support scoring against fixed rubrics only — never final ranking. ✅
   - Final scores must be auditable and reproducible. ✅
   - Score explanation reads from cached trace — no re-scoring. ✅ (`explain_score_from_cache`)

**Scoring modules:**

| File | Purpose |
|---|---|
| `src/scoring/graded_scorer.py` | Mode 1: code-only synonym + regex + years-proportional scoring |
| `src/scoring/rubrics.py` | 12 rubric templates with anchored scales, sub-questions, formulas |
| `src/scoring/rubric_scorer.py` | Mode 2: RUBRIC-SCORE-001 prompt, LLM judge, cached scoring trace |
| `src/scoring/unified_scorer.py` | Routes per dimension type; produces unified evaluation with traces |
| `src/scoring/tier_lookup.py` | Code-only institute + certificate tier lookup from JSON databases |

**Legacy triad (`keyword` / `semantic` / `hybrid`) retired 2026-06-19.** Passing
the legacy strategy names to `batch_score` / `compare_two` prints a
deprecation warning and forwards to `graded`.

**Batch CLI:** `python -m src.scoring.batch_score --role <Role>` → `data/scores/graded/<Role>_ranked.json` (ranked, 0-100 normalized, per-item evidence included).
**Per-candidate report:** `python scripts/evaluate_one.py --candidate <id> --role <Role>`.
**Comparison view:** `python scripts/compare_scores.py --role <Role> --top 10` shows the canonical graded ranking + per-candidate strengths and gaps.

---

## Phase 4.5: Clarification Loop + Pipeline Rewiring ⬜ Planned

The foundation modules (Header Normalization, Chunk Metadata, Structured
Profile, Section-Routed Retrieval, Rubric Templates, Tier Databases) are
shipped as standalone modules (Phase 4.6). This phase wires them into the
batch pipeline and builds the remaining recruiter-facing features.

1. **Re-parse all resumes with Header Normalization**
   - Produce new `data/processed/` with canonical section labels.
   - Produce `data/processed/<role>/<id>_structured_profile.json`.
2. **Re-chunk with updated chunker**
   - Produce new `data/chunks/` with full metadata schema.
3. **Wire `unified_scorer` into batch pipeline**
   - Replace `graded_scorer` call in `batch_score.py` with `unified_scorer.evaluate_candidate_unified`.
   - Pass chunks + structured profile + LLM caller.
   - Output includes scoring traces per item.
4. **JD clarification loop** (Green / Yellow / Red)
   - Auto-classify each extracted requirement.
   - Auto-generate follow-up questions for Yellow items.
   - Hard-block the scoring policy until all items are Green.
   - Persist `clarifications.json` next to the role's weight config.
5. **Per-item `expected_years` in the recruiter UI**
   - Surface as a per-item field next to `importance`.
6. **Resume cleaning pipeline**
   - Dedicated step between "raw text" and "structured profile" that strips headers, footers, template noise, decorative elements, and duplicate content.
7. **Candidate Intelligence Report artifact**
   - Aggregate unified scorer per-item evidence + scoring traces into a single `data/processed/<role>/<id>_intelligence_report.json`.
8. **Score explanation UI**
   - Wire `explain_score_from_cache` into the recruiter UI for per-item score explanations.

---

## Phase 5: Candidate Ranking & Comparison ✅ Shipped 2026-06-19

*Note: Phase 4.6 below documents the foundation modules shipped 2026-06-30
that the scoring engine depends on. It is placed after Phase 4.5 because the
modules are built but not yet wired into the batch pipeline.*

---

## Phase 4.6: Scoring Foundation Modules ✅ Shipped 2026-06-30

Standalone modules implementing the two-mode scoring architecture from
`WORKING_LOGIC.md`. These are built and unit-tested (279 tests) but not yet
wired into the batch pipeline (that is Phase 4.5).

1. **Header Normalization** ✅
   - `src/resume_parsing/header_normalization.py`
   - Layer 1: synonym lookup table → 7 canonical sections
   - Layer 2: LLM fallback classification for unmatched headers
2. **Chunk Metadata Schema** ✅
   - `src/rag/chunker.py` (updated)
   - `section_type`, `parent_structure`, `temporal_context` with `calculated_duration_months`
   - `skills_asserted`, `experience_type` (professional/personal_project/academic)
   - Deterministic date parsing in code, never by LLM
3. **Structured Candidate Profile** ✅
   - `src/resume_parsing/structured_profile.py`
   - Degrees + institutions, certifications, total experience (no double-count), companies, roles
   - Separate deterministic record, no LLM, no retrieval
4. **Section-Routed Evidence Retrieval** ✅
   - `src/rag/section_routed.py`
   - Fixed requirement→section mapping table (not a model decision)
   - Exact label match — no embeddings, no cosine, no top-K
   - Metadata filtering for long sections
5. **Rubric Templates** ✅
   - `src/scoring/rubrics.py`
   - 12 templates: skill, experience, leadership, same_role, domain, education, certification, project, language, location, communication, resume_organization
   - Anchored scales (0.0/0.25/0.5/0.75/1.0) with explicit descriptions
   - Code-only vs rubric-bound LLM classification
6. **Rubric-Bound LLM Scorer** ✅
   - `src/scoring/rubric_scorer.py`
   - RUBRIC-SCORE-001 prompt (weight excluded, extract-before-score, anchored scales)
   - `CachedScoringTrace` frozen at scoring time
   - `explain_score_from_cache` narrates trace without re-scoring
7. **Unified Scorer** ✅
   - `src/scoring/unified_scorer.py`
   - Routes each requirement to code-only or rubric-bound LLM
   - `UnifiedCandidateEvaluation` with per-item `scoring_mode` + `scoring_trace`
8. **Tier Databases** ✅
   - `src/scoring/tier_lookup.py` + `data/Institutes/institute_tiers.json` + `data/Certificates/certificate_tiers.json`
   - 3 tiers (1.0/0.75/0.50) + not-listed (0.50)
   - Recruiter-editable JSON, word-boundary matching

---

## Phase 5: Candidate Ranking & Comparison ✅ Shipped 2026-06-19
1. Build candidate comparison engine
   - Load two candidates' profiles and scores ✅
   - Diff the two side by side ✅ (matched components, top strengths)
   - Generate recruiter-friendly "Why A ranked above B" narrative ✅
2. Produce deterministic side-by-side comparison tables
   - Score values ✅
   - Matched requirement counts ✅
   - Component breakdowns ✅
3. Avoid LLM-driven final rankings (LLM supports explanation only)
   - Scores computed by deterministic engine ✅

**Artifacts:**
- `scripts/compare_two.py` — CLI: `python scripts/compare_two.py --candidate-a <id_a> --candidate-b <id_b> --role <R>`
- `tests/integration/test_candidate_comparison.py` — 6 integration tests passing.

**Example output:**
```
Score:                   58.39        vs 37.07
Matched Requirements:   10           vs 4
Top Strengths:          Requirements Gathering, Stakeholder Management, Process Mapping
Why A ranked above B:   [SCORE] BUSINESS ANALYST RESUME ranked HIGHER by 21.3 points.
                        [MATCH] Matched 10 requirements vs 4 for John Wood.
```

---

## Phase 6: Resume Chat / RAG 🟡 Mostly built, CLI pending
1. Implement chunking strategy
   - **Recursive Chunking** (active 2026-07-05 per DEC-019): `chunk_size=500`, `chunk_overlap=50`, both Optuna hyperparameters. ✅ (`src/rag/chunker.py` `RecursiveChunker`)
   - Document-Aware chunker retained as `DocumentAwareChunker` for one release. ✅
   - Header Normalization with 7 canonical sections. ✅ (`src/resume_parsing/header_normalization.py`) — used for the structured profile, no longer for retrieval routing.
   - Chunk metadata simplified: `chunk_id`, `candidate_id`, `text`, `char_span`, `embedding_index` (required); `section_type` is a soft tag.
2. Build embedding and retrieval pipeline
   - Embedding model: `sentence-transformers/all-MiniLM-L6-v2` ✅
   - Vector store: in-memory numpy (`data/embeddings/index.npz`) ✅
   - **Threshold-based cosine retrieval** (active 2026-07-05 per DEC-018): cosine ≥ θ (default `θ=0.70`, Optuna-tuned), capped at `max_chunks_per_query=20`. ✅
   - Documented in `AI_DESIGN_RATIONALE.md` and `MODEL_REGISTRY.md`. ✅
   - Section-Routed (DEC-012) and Sub-Query Similarity (DEC-015) are **superseded** but the modules are retained under their original names for one release as migration aids.
3. Build recruiter-facing chat CLI
   - `scripts/resume_chat.py --candidate <id> --question "..." --role <Role>` — CLI. ⬜
   - Streamlit chat UI. ⬜
4. Ensure grounded conversational answers
   - LLM service via OpenRouter (`src/hireintel_ai/llm/service.py`) ✅
   - Strict-grounding prompt (see `docs/PROMPT_LIBRARY.md` RESUME-CHAT-001). ⬜ (prompt spec exists; not implemented in code)
   - "Information not found in candidate documents." fallback. ⬜ (string appears only in docs; not in any `.py` file)
   - Cite retrieved resume content. ⬜ (citation pattern planned; recruiter UI not yet built)
5. Score explanation from cached trace
   - `explain_score_from_cache` reads frozen trace. ✅ (`src/scoring/rubric_scorer.py`)
   - RAG follow-up for questions beyond cached trace. ⬜
6. **Experiment tracking (NEW 2026-07-05, M0.5c)** ⬜
   - Stand up local MLflow server. ⬜
   - Wire `log_params` / `log_metrics` into the pipeline. ⬜
   - Verify UI at `http://127.0.0.1:5000` shows the per-run dashboard. ⬜
7. **Optuna search (NEW 2026-07-05, M0.5d)** ⬜
   - Create `data/optuna/studies.db` (SQLite, in `.gitignore`). ⬜
   - First study `chunking_v1_20260705`: multi-objective, TPE, 200 trials. ⬜
   - Promote the Pareto-front point to `MODEL_REGISTRY.md` as the new "Active" config. ⬜

---

## Phase 7: Evaluation & validation
1. Define metrics
   - Resume parsing: precision, recall, F1
   - Retrieval: Recall@K, Precision@K, MRR, nDCG
   - Generation: faithfulness, groundedness, relevancy
   - RAG: context recall, context precision
   - Ranking: Top-K accuracy, recruiter agreement
   - Hallucination: unsupported statements, hallucination rate
   - Business: screening efficiency, time saved, satisfaction
2. Validate and iterate
   - Measure performance
   - Refine parsing, retrieval, scoring

---

## Phase 8: Technology & deployment
1. Assemble stack
   - Backend: Python, FastAPI
   - Frontend: Streamlit
   - NLP: spaCy, NLTK, regex
   - LLM/embeddings: chosen models
   - Vector DB: chosen engine
2. Document implementation
   - Keep architecture and decision docs updated.
   - Add release notes for feature completion and bug fixes.

---

## Recommended execution order
1. Define documentation and architecture ✅
2. Establish production package structure, configuration, schemas, and test layout ✅
3. Build JD extraction + clarification loop (Phase 1) — clarification loop ⬜
4. Build weight configuration (weights + expected_years) (Phase 2) — expected_years UI ⬜
5. Build resume parsing + cleaning (Phase 3) — cleaning ⬜
6. Build scoring engine — Mode 1 code-only ✅ + Mode 2 rubric-bound LLM ✅ + unified scorer ✅ (Phases 4 + 4.6)
7. Build ranking/comparison (Phase 5) ✅
8. **Phase 4.5: re-parse with Header Normalization, re-chunk, wire unified scorer into batch pipeline, clarification loop, expected_years UI, resume cleaning, Candidate Intelligence Report, score explanation UI**
9. **M0.5: experiment tracking + threshold-based retrieval (NEW 2026-07-05)** ⬜
   - M0.5a: switch chunker to RecursiveChunker; switch retriever to threshold-based cosine
   - M0.5b: build the eval set (≥50 (query, expected_chunks, expected_answer) triples spanning ≥3 roles)
   - M0.5c: stand up local MLflow; wire `log_params` / `log_metrics` into the pipeline
   - M0.5d: run the first Optuna study; promote the Pareto-front point to `MODEL_REGISTRY.md`
    - **M0.5e: per-resume reasoning storage + legacy chunk migration + per-experiment folder naming (NEW 2026-07-05, DEC-022 + DEC-023)**
     - M0.5e-a: move 721 Document-Aware chunk files to `data/document_aware_chunking/` (refined by DEC-023)
     - M0.5e-b: replace `llm_cache.jsonl` with per-experiment per-resume `data/recursive_chunking_<params>/per_candidate/.../reasoning/` tree; create `data/active_experiment` symlink
     - M0.5e-c: backfill from legacy cache into the per-experiment tree (one-time, optional)
     - M0.5e-d: add cache hit rate + determinism metrics to MLflow; raise disk-usage alert from 5 GB to 20 GB
    - **M0.5f: chunk reports + ranking evaluation setup (NEW 2026-07-05, DEC-024)**
     - M0.5f-a: generate the historical Document-Aware chunking report (49% missing-section_type finding) into `reports/chunk_reports/`
     - M0.5f-b: wire `generate_chunk_report` into the pipeline; every Recursive experiment produces a committed report
     - M0.5f-c: build the counterfactual test suite (`data/eval/counterfactual_v1.jsonl`, ≥50 tests, ≥4 categories) — fast feedback loop
     - M0.5f-d: build the synthetic labeled ranking set (`data/eval/ranking_v1.jsonl`, 30–50 pairs, 2–3 recruiters) — slow feedback loop
     - M0.5f-e: add behavioral signal tracking (production only, tracked not enforced)
10. Add retrieval, then grounded RAG/chat (Phase 6) — chunking ✅, threshold retrieval ✅, chat CLI ⬜
11. Evaluate, harden, deploy, and document (Phases 7 + 8)

---

## M0.5: Experiment Tracking + Threshold-Based Retrieval (NEW 2026-07-05)

Pivots the active retrieval to regular RAG (DEC-017) and adds MLflow + Optuna (DEC-020/021) as the experiment-management pair. The deterministic scoring engine is **unchanged** — this milestone changes how evidence is gathered and how configs are tuned, not how the score is computed.

### M0.5a — Chunking + Retrieval Switch

1. **Switch chunker to RecursiveChunker** (`src/rag/chunker.py`)
   - Add `RecursiveChunker` class implementing `RecursiveCharacterTextSplitter(separators=["\n\n","\n",". "," "], chunk_size=500, chunk_overlap=50)`.
   - Rename existing chunker to `DocumentAwareChunker`; keep it for one release as a migration aid.
   - Chunk metadata schema simplified: required fields are `chunk_id`, `candidate_id`, `text`, `char_span`, `embedding_index`. `section_type` becomes a soft tag.
2. **Switch retriever to threshold-based cosine** (`src/rag/retriever.py`)
   - Replace `top_k` retrieval with `retrieve(query, θ=0.70, max_chunks_per_query=20)`.
   - Log a WARN when the cap is hit.
   - Same pipeline serves per-candidate scoring, pool search, and chat — only the `candidate_id` filter changes.
3. **Re-build the embedding index** with the new chunker
   - One-time `python -m src.rag.build_index` over the 721-resume corpus.
   - Verify chunk count distribution (avg ~17, max ~50 per resume).
4. **Update cache key** to `(candidate_id, req_id, hash(query, top-chunk-ids), model_name, θ)`.

### M0.5b — Eval Set

1. Hand-curate ≥50 (query, expected_chunks, expected_answer) triples spanning ≥3 roles and ≥4 dimensions.
2. Store as `data/eval/v1.jsonl` (line-delimited JSON per the schema in `EVALUATION.md`).
3. Commit a CI check that fails if `data/eval/v1.jsonl` falls below 50 triples.

### M0.5c — MLflow Wiring

1. Add `mlflow`, `optuna`, `optuna-dashboard` to `requirements.txt` (pinned).
2. Stand up `mlflow server --host 127.0.0.1 --port 5000 --backend-store-uri sqlite:///data/mlflow/mlflow.db --default-artifact-root ./data/mlflow/artifacts/`.
3. Add a `with mlflow.start_run():` wrapper to the pipeline entry point.
4. Log all required params + metrics + artifacts per the contract in `EVALUATION.md`.

### M0.5d — Optuna Search

1. Create `data/optuna/studies.db` (SQLite, in `.gitignore`).
2. First study: `chunking_v1_20260705` — multi-objective `[maximize faithfulness, minimize avg_chunks_returned]`, TPE sampler, 200 trials.
3. Each trial's params + metrics are auto-logged to MLflow via `optuna.integration.MLflowCallback`.
4. After the study: pick the operating point on the Pareto front (e.g. faithfulness ≥ 0.85) and export its params to `MODEL_REGISTRY.md` as the new "Active" config.
5. Update `RECURSIVE_CHUNK_SIZE`, `RECURSIVE_CHUNK_OVERLAP`, and `DEFAULT_THRESHOLD` constants in `src/rag/{chunker,retriever}.py` to the Optuna-recommended values.

**Risks:**
- A small or biased eval set → confidently-wrong `θ`. The eval set is the bottleneck.
- `θ` is dataset-sensitive; the first study may need to be re-run as the corpus grows.
- The cap (`max_chunks_per_query = 20`) is a safety net, not a primary control; if it's hit on >10% of queries, `θ` is too low.

**Success criteria:**
- A new "Active" config in `MODEL_REGISTRY.md` that came from an Optuna trial, not from a hand-picked value.
- `MLflow` UI at `http://127.0.0.1:5000` showing ≥100 trials, all with full params + metrics + retrieved-chunks artifacts.
- `data/optuna/studies.db` with a populated Pareto front for `chunking_v1_20260705`.

---

## M0.5e — Per-Resume Reasoning Storage + Legacy Chunk Migration + Per-Experiment Folder Naming (NEW 2026-07-05, DEC-022 + DEC-023)

Pivots the LLM cache from a single line-delimited file to a per-resume artifact tree, migrates the legacy Document-Aware chunks to a clearly-named directory (`data/document_aware_chunking/`), and adopts the per-experiment folder convention for the Recursive chunking pipeline. Storage cost is accepted; LLM-call cost and re-run determinism are the win.

### M0.5e-a — Legacy Chunk Migration (one-time, DEC-022a + DEC-023)

1. Create `data/document_aware_chunking/<role>/` directories for all 8 roles.
2. Move all 721 files from `data/chunks/<role>/<candidate_id>.jsonl` to `data/document_aware_chunking/<role>/<candidate_id>.jsonl`. Use `git mv` so history is preserved in version control. The destination directory is `document_aware_chunking/` (per DEC-023), not the longer `chunks_legacy_document_aware/` (DEC-022's original placeholder).
3. Write `data/document_aware_chunking/MIGRATION_NOTES.md` with:
   - Date of the move (`2026-07-05`).
   - Source chunker (`DocumentAwareChunker`, pre-DEC-019).
   - Target chunker (`RecursiveChunker`, post-DEC-019).
   - Per-file chunk-count delta (so it's obvious the new files are not renamed copies).
   - A `git mv`-friendly undo script.
4. Add `data/document_aware_chunking/<role>/` and `data/recursive_chunking_*/` to `.gitignore` (chunks are large binaries; only `MIGRATION_NOTES.md` is committed).
5. Verify: `data/document_aware_chunking/` has 721 files, `MIGRATION_NOTES.md` is committed, `data/active_experiment` symlink points to the first experiment folder once M0.5e-b completes.

### M0.5e-b — Per-Resume Reasoning Storage + Per-Experiment Folder Convention (DEC-022b + DEC-023)

1. Create the per-experiment folder convention. The pipeline entry point consults the active hyperparameters (`chunk_size`, `overlap`, `top_k`, `θ`) and resolves the target folder to `data/recursive_chunking_<chunk_size>_<overlap>_<top_k>_<threshold×100>/`. Field order is fixed; `x` is used for inactive dimensions. `metadata.json` is written to the folder with the full config.
2. Create `data/recursive_chunking_<params>/per_candidate/<role>/<candidate_id>/reasoning/` per candidate.
3. Replace the single `data/embeddings/llm_cache.jsonl` writer/reader with a per-resume writer/reader:
   - **Writer:** when the rubric-bound LLM returns its output, write `<req_id>__<query_hash>.json` per the schema in `WORKING_LOGIC.md` §"Per-Resume Reasoning Storage". Target folder is the per-experiment folder resolved in step 1.
   - **Reader:** before calling the LLM, compute the cache key. If a file matches, read `sub_scores` directly. Otherwise, call the LLM, persist the result.
4. Update the cache key to `(candidate_id, req_id, hash(query, sorted(top-chunk-ids)), model_name, θ)`.
5. Move `data/embeddings/llm_cache.jsonl` to `data/embeddings/llm_cache_legacy.jsonl`. Legacy reader code stays for one release to handle backfilled entries.
6. Update `src/rag/retriever.py` and `src/scoring/rubric_scorer.py` to use the per-experiment cache path.
7. Add `data/recursive_chunking_*/` and `data/per_candidate/` to `.gitignore` (large binaries; not committed).
8. Create the `data/active_experiment` symlink pointing to the first per-experiment folder. Re-point the symlink whenever the "Active" config in `MODEL_REGISTRY.md` changes. Runtime code follows the symlink; it never hardcodes hyperparameter values.

### M0.5e-c — Backfill from Legacy Cache (one-time, optional)

1. Walk `data/embeddings/llm_cache_legacy.jsonl` line by line.
2. Group entries by `(candidate_id, req_id, query, model_name, θ)`. Each group is a backfill target.
3. For each group, resolve the target per-experiment folder (DEC-023 convention) and write one file to that folder's `per_candidate/.../reasoning/` tree. Mark the entry `"backfilled": true` (the legacy cache doesn't have the full `reasoning` / `basis`, only the `sub_scores`).
4. After backfill, re-runs of backfilled (candidate, req) pairs are forced to refresh — the scoring engine detects `"backfilled": true` and re-calls the LLM.
5. Verify: count of files in each per-experiment folder's `per_candidate/.../reasoning/` tree equals the count of distinct (candidate, req, query, model_name, θ) groups in the legacy cache that map to that experiment.

### M0.5e-d — Cache Metrics

1. Add `cache_hit_rate`, `llm_calls_avoided`, `disk_usage_total`, `backfilled_entries_count` to the MLflow run.
2. Add a determinism check: re-run the same config twice, log `sub_score_match_rate`. Target: 1.0.
3. Raise the disk-usage alert from 5 GB (DEC-022d) to **20 GB** (DEC-023) to accommodate the per-experiment storage footprint (~10–15 GB peak across an Optuna sweep). Update `ENVIRONMENT_NOTES.md`.
4. Add a per-folder metric `experiments_count` to the MLflow run; alert if more than 600 experiment folders exist (suggests GC is overdue).

**Risks:**
- Migration move is a one-time `mv` of 721 files. If it fails partway, the script is idempotent — re-run resumes from the last completed file. `MIGRATION_NOTES.md` records which files have been moved.
- Per-resume reasoning files contain PII. They inherit the same PII policy as `data/processed/` — local-only, never logged, never uploaded.
- Storage growth: estimate 10–15 GB peak across an Optuna sweep. The 20 GB alert is the trip-wire; auto-archive experiments older than 30 days to `data/archive/<study_name>/`.
- Folder proliferation: 200 Optuna trials × 3 studies = ~600 folders. GC after each study.
- The `sub_score_match_rate` determinism check will fail if the cache key is wrong. Investigate immediately; this is a hard regression of DEC-022's promise.

**Success criteria:**
- `data/document_aware_chunking/` contains 721 files + `MIGRATION_NOTES.md`.
- `data/recursive_chunking_<params>/` folders are created on demand, one per (chunk_size, overlap, top_k, θ) combination.
- `data/active_experiment` is a valid symlink pointing to the "Active" config's folder.
- Each per-experiment folder has a `metadata.json` whose `experiment_folder` matches the folder name.
- Each per-experiment folder's `per_candidate/.../reasoning/` has one file per (candidate, req, query) triple.
- Re-running the same config twice returns byte-identical sub-scores (`sub_score_match_rate == 1.0`).
- MLflow shows `cache_hit_rate ≥ 0.95` after the first scoring pass.

---

## M0.5f — Chunk Reports + Ranking Evaluation Setup (NEW 2026-07-05, DEC-024)

Adopts the `reports/chunk_reports/` convention and the multi-pronged ranking evaluation methodology. Reports are committed to git for historical record; ranking evaluation is backed by five independent signals, none of which require a single labeled ground truth.

### M0.5f-a — Generate the Document-Aware Chunking Report (one-time)

1. Walk `data/document_aware_chunking/` (the legacy chunks, M0.5e-a must complete first).
2. Compute chunk statistics per the report schema in `EVALUATION.md` §"Chunk Reports":
   - Total chunks, chunks per role, chunks per resume (mean, median, min, max, p95).
   - **Chunks with `section_type=""`** (the DEC-015 finding).
   - Section-type distribution.
3. Write `reports/chunk_reports/document_aware_chunking_report.json` and `document_aware_chunking_report.md`.
4. The MD report's "Key findings" section prominently calls out the 49% missing-`section_type` rate and the empirical justification for DEC-019 (retiring Document-Aware chunking).
5. Commit both files to git.

### M0.5f-b — Wire Report Generation into the Pipeline

1. Add a `generate_chunk_report(experiment_folder, metadata) -> Report` function in `src/reporting/chunk_report.py`.
2. After every Recursive experiment finishes scoring, call `generate_chunk_report` and write:
   - `reports/chunk_reports/recursive_chunking_<params>_report.json`
   - `reports/chunk_reports/recursive_chunking_<params>_report.md`
3. The MD report is a human-readable summary; the JSON is the structured artifact that downstream tools can consume.
4. Both files are committed to git by the developer after review (no auto-commit; reports may contain evaluation findings the team wants to discuss first).

### M0.5f-c — Build the Counterfactual Test Suite

1. Hand-construct ≥ 50 counterfactual test cases in `data/eval/counterfactual_v1.jsonl`.
2. Span at least 4 categories: weight monotonicity, must-have gate, years-proportionality, synonym equivalence.
3. Each test case has two configs (`config_a`, `config_b`) and an expected ranking delta.
4. Add a `run_counterfactual_tests(suite) -> pass_rate` function in `src/eval/counterfactual.py` that runs every test case and asserts the expected behavior.
5. **Gate:** `pass_rate >= 0.95` is required for promotion to "Active" in `MODEL_REGISTRY.md`.

### M0.5f-d — Build the Synthetic Labeled Ranking Set

1. Hand-rank 30–50 (candidate, role) pairs across 2–3 recruiters.
2. Compute inter-rater agreement (Cohen's kappa or Krippendorff's alpha). If agreement < 0.60, the "ground truth" itself is suspect; investigate before using the set.
3. Store the median ranking as `data/eval/ranking_v1.jsonl`.
4. Add a `run_ranking_eval(set) -> {ndcg_at_10, top_3_accuracy, spearman}` function in `src/eval/ranking.py`.
5. **Gate:** `ndcg_at_10 >= 0.80` is required for promotion (skipped if the set does not exist yet; this is the slow feedback loop, not the fast one).
6. Quarterly refresh cadence. The decay of recruiting ground truth is documented in `EVALUATION.md`.

### M0.5f-e — Add Behavioral Signal Tracking (production only)

1. In production (post-M0.5d), track: `top_1_interview_rate`, `top_3_interview_rate`, `bottom_rejection_rate`, `revisit_rate`.
2. Log to MLflow as informational metrics. Tracked, not enforced.
3. A change in trend is a signal; an absence of signal is not a regression.

**Risks:**

- The Document-Aware report is generated from already-moved files; if M0.5e-a is not yet complete, the report waits.
- The counterfactual test suite is hand-constructed. Coverage gaps are possible. Audit quarterly.
- The synthetic labeled set decays over time. Document the refresh cadence in `EVALUATION.md`.
- Behavioral signals are noisy. Tracked, not enforced. An empty signal is not a regression.

**Success criteria:**

- `reports/chunk_reports/document_aware_chunking_report.{json,md}` exists and is committed; the MD report's "Key findings" mentions the 49% missing-`section_type` rate.
- Every Recursive experiment produces a `recursive_chunking_<params>_report.{json,md}` pair, committed to git.
- `data/eval/counterfactual_v1.jsonl` has ≥ 50 tests spanning ≥ 4 categories.
- `data/eval/ranking_v1.jsonl` has 30–50 (candidate, role) pairs with inter-rater agreement ≥ 0.60.
- The promotion gate in `EVALUATION.md` (counterfactual pass rate ≥ 0.95, stability = 1.0, NDCG ≥ 0.80, no regression in prior Active) is enforced before any new config is promoted to "Active" in `MODEL_REGISTRY.md`.
