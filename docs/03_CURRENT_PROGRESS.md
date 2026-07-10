# Current Progress vs `WORKING_LOGIC.md`

This document maps every step of the canonical spec
[`WORKING_LOGIC.md`](WORKING_LOGIC.md) to its implementation status. As of
**2026-07-09**, the project has been restarted from scratch due to sub-score zero bugs in candidate evaluation. All scoring, embedding, and execution caches have been cleared to ensure a clean rebuild.

**Legend:** ✅ Shipped · 🟡 Partially shipped / scaffolded · ⬜ Planned

---

> ## Project Restart from Scratch (2026-07-09)
>
> To address bugs in the LLM scoring engine (where sub-scores were repeatedly evaluated as 0.0), the project database, caches, intermediate scores, and temporary scripts have been deleted. 
> We are rebuilding the pipeline from a clean slate using recursive chunking and robust years extraction helpers.
>
> | Action | Status |
> |---|---|
> | Clear old cache, databases, and scores | ✅ Completed |
> | Remove redundant ad-hoc scripts | ✅ Completed |
> | Reset project vital documents | ✅ Completed |
> | Re-initialize database & rebuild pipeline | 🟡 In Progress |

---

## Pipeline Stages (high-level view)

The platform moves through four stages; we are currently resetting the implementation of these stages.

| # | Stage | Status | Where |
|---|---|---|---|
| 1 | **JD Formation** — extract requirements from JDs; produce per-role structured JD objects | ✅ | `data/job_descriptions/<role>/<Role>_JD.md`; 8 roles fully populated |
| 2 | **Sub-Query Formation** — decompose each JD requirement into 2–4 anchored sub-questions | ✅ | `data/job_descriptions/<role>/<Role>_SubQuery.md`; 8 roles audited |
| 3 | **Recursive Chunking & Embeddings** — uniform chunks, threshold-based cosine retrieval | ⬜ Planned | To be rebuilt under clean index |
| 4 | **Recursive Chunking** — uniform 1000-char chunks with 500-char overlap (50%), threshold-based cosine retrieval (θ ≥ 0.25), employment-history-augmented rubric prompt, per-experiment folder convention | 🟡 in progress | `data/recursive_chunking_<params>/` (M0.5a-d-f); `data/active_experiment` symlink (M0.5e-b); chunking bounds widened 2026-07-07 (DEC-032) |

**What's preserved across the pivot:** the deterministic scoring engine (`src/scoring/graded_scorer.py` + `src/scoring/unified_scorer.py`) is unchanged. The four stages produce evidence; the engine produces the score. The pivot changes how evidence is gathered, not who decides the score.

**What's added in stage 4:** experiment management (MLflow + Optuna) and per-experiment storage (per-experiment folders, per-resume reasoning tree, chunk reports). Stage 4 is the first stage where the production hyperparameters are **data-driven** (Optuna-recommended) rather than hand-picked.

---

## Foundational Rules

| Spec rule | Status | Where |
|---|---|---|
| System is not a generic ATS / keyword matcher / RAG chatbot | ✅ | Architecture, scoring |
| Recruiter-controlled weights (0–100%, slider UI) | ✅ | FastAPI + HTMX UI → `data/job_descriptions/<role>/<role>_WeightConfig_*.json` (normalized internally to 0–100 via `scale_factor`) |
| Recruiter-controlled `expected_years` per item | 🟡 | Default 10 in `graded_scorer.DEFAULT_EXPECTED_YEARS`; per-item field not yet exposed in UI |
| Weight normalization to 0–100 | ✅ | `scale_factor = 100 / max_score` in `src/scoring/graded_scorer.py` |
| Reproducible, auditable, explainable rankings | ✅ | `graded_scorer.evaluate_candidate` |
| LLM explains, never scores | ✅ | `src/scoring/rubric_scorer.explain_score_from_cache`; recruiter UI narrates cached traces |
| Ask for clarification, don't assume | ⬜ | No clarification loop yet |
| **Recursive Chunking is the default** (2026-07-05, refined 2026-07-07) | ✅ | `RecursiveChunker` is the active chunker per DEC-019 / DEC-032. Defaults: `chunk_size=1000`, `chunk_overlap=500` (50% of `chunk_size`); bounds `[500, 1000]` / `[50%, 60%]` of `chunk_size`. `DocumentAwareChunker` retained for one release as a migration aid. |

---

## Role-Specific Documentation & Operational Readiness

| Role | Status | Files | SubQuery Audit |
|---|---|---|---|
| BusinessAnalyst (template) | ✅ | 8/8 | ✅ Pass |
| DataScience | ✅ | 8/8 | ✅ Pass |
| JavaDeveloper | ✅ | 8/8 | ✅ Pass |
| ReactDeveloper | ✅ | 8/8 | ✅ Pass |
| SalesManager | ✅ | 8/8 | ✅ Pass |
| SQLDeveloper | ✅ | 8/8 | ✅ Pass |
| SrPythonDeveloper | ✅ | 8/8 | ✅ Pass |
| WebDesigning | ✅ | 8/8 | ✅ Pass |

**7-file template per role** (was 8; the per-role Streamlit CLI `recruiter_weight_input.py` was retired in favour of the unified FastAPI UI on 2026-07-03):
1. `<Role>_JD.md` — Job Description
2. `<Role>_SubQuery.md` — Sub-query decomposition with scoring formulas
3. `<Role>_ScoringGuide.md` — Percentage-based weighting guide
4. `<Role>_WeightConfiguration_Guide.md` — Weight configuration instructions
5. `<Role>_RecruiterWeights_EXAMPLE.json` — Example weight configuration
6. `QUICK_START.md` — Quick start guide
7. `README_SETUP.md` — Detailed setup instructions

> Recruiter weight configuration is now done via the unified **FastAPI + HTMX** UI at `src/api/app.py` → `http://127.0.0.1:8000/configure` (added 2026-07-03). It serves all 8 roles, persists to SQLite (`data/hireintel.db`) + JSON (`data/job_descriptions/<role>/<role>_WeightConfig_*.json`), and supports strict 100% validation with +/- 0.5 step sliders.

**SubQuery audit criteria (all passed):**
- Every JD requirement has corresponding REQ in SubQuery
- Core Skills, Preferred Skills, Experience, Education sections map correctly
- Binary gates × Float evidence scoring pattern consistent
- Scoring formula documented for each requirement
- recruiter_weight_input.py REQUIREMENTS lists match SubQuery REQ-IDs

---

## JD Pipeline (Steps 0–5 of `WORKING_LOGIC.md`)

| Step | Spec | Status | Where |
|---|---|---|---|
| JD validation & clarification | Reject ambiguous JDs | ⬜ | — |
| Green / Yellow / Red requirement classification | Tag each requirement | ⬜ | — |
| Recruiter follow-up questions for Yellow items | Ask, don't assume | ⬜ | — |
| Red items block scoring until clarified | Hard gate | ⬜ | — |
| Degree equivalence table per role | Confirm acceptable alternatives | ⬜ | — |
| Per-skill expected years (ask when missing) | "Expected Tableau experience?" | ⬜ | — |
| Recruiter weight assignment 0–10 | Done via FastAPI + HTMX UI | ✅ | `src/api/app.py` → `/configure`; stores to `data/hireintel.db` + `data/job_descriptions/<role>/<role>_WeightConfig_*.json`; **now consumed by scoring engine** via `src/services/scoring_pipeline.py` + `src/api/scoring.py` (`GET /api/score/<role>/<candidate_id>?config_name=...`, `GET /api/score/<role>/rank?config_name=...&top_k=...`) |
| Weight normalization to 100 | `scale_factor = 100 / max_score` | ✅ | `src/scoring/graded_scorer.py` |

---

## Resume Pipeline

| Step | Spec | Status | Where |
|---|---|---|---|
| Resume Upload (PDF, DOCX, text) | Multiple formats | ✅ | `src/resume_parsing/parser.py`, OCR fallback via `pypdfium2` |
| Resume Cleaning (headers, footers, templates, noise, duplicates) | Strip noise | 🟡 | Implicit via section parsing; no dedicated cleaning step |
| **Recursive Chunking** (active 2026-07-05, refined 2026-07-07) | Uniform 1000-char chunks with 500-char overlap (50%), Optuna bounds `[500, 1000]` / `[50%, 60%]` of `chunk_size` (DEC-032) | ✅ | `src/rag/recursive_chunker.py::RecursiveChunker` shipped (Track 1, M0.5a); refined 2026-07-07 (DEC-032). `DocumentAwareChunker` retained as migration aid. `chunk_size` and `chunk_overlap` are Optuna hyperparameters. Embedding index rebuilt: 4,763 chunks (was 6,670). |
| Header Normalization | Synonym lookup + fallback classification → 7 canonical sections | ✅ | Implemented directly in `src/resume_parsing/parser.py` (the `SECTION_HEADERS` dict + `sectionize()` + `identify_section_heading()` functions). There is no `header_normalization.py` file — that was a docs-only phantom, reconciled in Track 6. |
| Chunk Metadata Schema (simplified 2026-07-05) | `chunk_id`, `candidate_id`, `text`, `char_span`, `embedding_index` (required); `section_type` is a soft tag | 🟡 | Schema updated; implementation pending. |
| Structured Candidate Profile Extraction | Deterministic extraction of degrees, certs, total exp, companies, dates | ✅ | `src/resume_parsing/structured_profile.py` — separate record, no double-counting of overlapping experience |
| Evidence Extraction | Linked to source text | ✅ | `char_span` in chunk records |
| Candidate Intelligence Report | Aggregated Skills + Experience + Education + Certs + Projects + Objective Scores + Evidence | ✅ | 721 reports pre-generated 2026-07-01 → `data/processed/<role>/<id>_intelligence_report.json`. Production pipeline script retired during 2026-07-03 dead-code cleanup; report format remains valid input to `unified_scorer` |

---

## Candidate Evaluation (Steps 6–11 of `WORKING_LOGIC.md`)

| Step | Spec | Status | Where |
|---|---|---|---|
| Skill Presence (code-only) | Boolean match | ✅ | `graded_scorer._search_profile` |
| Skill Years of Experience (code-only) | Years near alias | ✅ | `graded_scorer._detect_years_in_text` |
| Skill Depth (rubric-bound LLM) | LLM judge against recruiter rubric | ✅ | `src/scoring/rubric_scorer.py` + `src/scoring/rubrics.py` SKILL_RUBRIC |
| Relevant Experience (rubric-bound LLM) | Same-role / industry / leadership via LLM judge | ✅ | `src/scoring/rubric_scorer.py` + EXPERIENCE/LEADERSHIP/DOMAIN rubrics |
| Same Role Experience | Similar-role via rubric LLM | ✅ | `src/scoring/rubrics.py` SAME_ROLE_RUBRIC — "Has served in a similar role?" |
| Education (Degree Match + Institute Tier) | Code-only: degree match + tier lookup | ✅ | `src/scoring/unified_scorer._score_education_code_only` + `src/scoring/tier_lookup.py` |
| Education (Institution Quality) | IIT / NIT / Tier-1 / Tier-2 / Tier-3 / not-listed | ✅ | `data/Institutes/institute_tiers.json` + `tier_lookup.py` |
| Certifications (Match + Provider Tier) | Code-only: cert match + tier lookup | ✅ | `src/scoring/unified_scorer._score_certification_code_only` + `tier_lookup.py` |
| Certifications (Provider Reputation) | AWS / Microsoft / Google / Coursera / local | ✅ | `data/Certificates/certificate_tiers.json` + `tier_lookup.py` |
| Projects (rubric-bound LLM) | Relevance + depth via LLM judge | ✅ | `src/scoring/rubrics.py` PROJECT_RUBRIC |
| Location | Code-only binary match | ✅ | `src/scoring/unified_scorer._score_location_code_only` |
| Languages (rubric-bound LLM) | Presence + proficiency via LLM judge | ✅ | `src/scoring/rubrics.py` LANGUAGE_RUBRIC |
| Communication Quality | LLM judge against anchored scale | ✅ | `src/scoring/rubrics.py` COMMUNICATION_RUBRIC |
| Resume Organization | LLM judge against anchored scale | ✅ | `src/scoring/rubrics.py` RESUME_ORGANIZATION_RUBRIC |
| Section-Routed Evidence Retrieval | Exact label match on canonical sections | ⬜ | **Superseded 2026-07-05 by DEC-017.** Module retained under `src/rag/section_routed.py` for one release as a migration aid only. New code should not call it. |
| Sub-Query Similarity Retrieval | Per-REQ sub-query decomposition → cosine → LLM | ⬜ | **Superseded 2026-07-05 by DEC-017.** Module retained under `src/services/subquery_retrieval.py` for one release as a migration aid only. |
| **Threshold-Based Retrieval (Regular RAG)** (active 2026-07-05) | Cosine ≥ θ over Recursive chunks; all hits, capped at `max_chunks_per_query` | 🟡 | New active strategy per DEC-017 + DEC-018. Default `θ = 0.70`, `max_chunks_per_query = 20`, both Optuna hyperparameters. Implementation pending in `src/rag/retriever.py`. |
| Chunk Embedding Index | MiniLM-L6-v2, 384-dim, L2-normalized | ✅ | `data/embeddings/index.npz` + `chunks.jsonl`. 6,377 chunks across 721 resumes (under the old Document-Aware chunker; will be rebuilt under RecursiveChunker per M0.5a). |
| LLM Sub-Score Cache | (candidate_id, req_id, hash(query, top-chunk-ids), model_name, θ) → full LLM output (reasoning + basis + retrieved chunks + sub-scores) | 🟡 | **Migrating to per-resume tree 2026-07-05 per DEC-022.** Active path: `data/per_candidate/<role>/<candidate_id>/reasoning/<req_id>__<query_hash>.json`. Legacy single-file cache at `data/embeddings/llm_cache.jsonl` moves to `data/embeddings/llm_cache_legacy.jsonl` in M0.5e. |
| Rubric Templates | Fixed sub-questions + anchored scales per dimension | ✅ | `src/scoring/rubrics.py` — 12 templates registered |
| Per-item raw score = `min(importance, years / expected × importance)` | Years-proportional (code-only mode) | ✅ | `graded_scorer.evaluate_candidate` |
| Partial credit (mentioned, no years) | `importance × 0.3` | ✅ | `graded_scorer.evaluate_candidate` |
| Total normalized to 100 | `total_raw × scale_factor` | ✅ | `graded_scorer.evaluate_candidate` + `unified_scorer.evaluate_candidate_unified` |
| Per-item evidence (section, snippet, years, reason) | Mandatory | ✅ | `ItemEvaluation` + `UnifiedItemEvaluation` dataclass |
| Cached rubric reasoning for score explanation | Store sub-scores + cited evidence at scoring time | ✅ | `src/scoring/rubric_scorer.py` CachedScoringTrace — frozen at scoring time |
| Score explanation from cache | Narrate cached trace without re-scoring | ✅ | `src/scoring/rubric_scorer.explain_score_from_cache` |
| Unified scoring (code-only + rubric LLM) | Both modes in one engine | ✅ | `src/scoring/unified_scorer.py` — routes per dimension type |
| Score Explanation Using RAG | Retrieve → ground → narrate | 🟡 | LLM service scaffolded; per-item explanation from cache implemented in `rubric_scorer.py`; full RAG follow-up not yet wired |

---

## Candidate Ranking

| Rule | Status | Where |
|---|---|---|
| Sort by deterministic total | ✅ | `_ranked_rows` (in `graded_scorer`); 8 ranked files in `data/scores/graded/<role>_ranked.json` from pre-2026-07-03 batch run |
| LLM never ranks | ✅ | Enforced by design |
| Cosine similarity is a supporting signal only | 🟡 | Vector index exists (`data/embeddings/index.npz`); recruiter-facing cosine match UI not built |

---

## Resume Chat

| Step | Status |
|---|---|
| **Recursive Chunking for retrieval (2026-07-05)** | 🟡 | `RecursiveChunker` is the active strategy per DEC-019; implementation pending. `DocumentAwareChunker` retained for one release. |
| **Threshold-based retrieval (2026-07-05)** | 🟡 | New active retrieval per DEC-018; implementation pending. Default `θ = 0.70`, `max_chunks_per_query = 20`. |
| RAG-grounded answers | ⬜ (no resume-chat method implemented; prompt spec in `PROMPT_LIBRARY.md` RESUME-CHAT-001 not wired to code) |
| Strict grounding prompt (no hallucination) | ⬜ (prompt spec exists in `PROMPT_LIBRARY.md` RESUME-CHAT-001; not implemented in code) |
| "Information not found in candidate documents." fallback | ⬜ (string appears only in docs; not in any `.py` file) |

---

## Candidate Comparison

| Step | Status | Where |
|---|---|---|
| Side-by-side comparison | 🟡 | Standalone CLI script retired 2026-07-03; `unified_scorer` produces per-item evidence + score deltas ready for a comparison view; not yet exposed in any UI |
| Evidence-backed "Why A above B" | 🟡 | Deterministic score deltas + component breakdown are produced by `unified_scorer`; LLM narrative generation deferred until LLM caller is wired |

---

## Hiring Recommendations

| Step | Status |
|---|---|
| Generate evidence-backed recommendation text | ⬜ (planned for Phase 8) |

---

## Quality-Based Evaluation (Spec §"Quality-Based Evaluation")

| Tier | Status | Where |
|---|---|---|
| Institution quality tiers | ✅ | `data/Institutes/institute_tiers.json` — 115 Tier 1, 54 Tier 2, 155 Tier 3, not-listed=0.50 |
| Certification provider reputation | ✅ | `data/Certificates/certificate_tiers.json` — 115 Tier 1, 45 Tier 2, 10 Tier 3, not-listed=0.50 |
| Recruiter-controlled tier definitions | ✅ | JSON files are recruiter-editable; `reload_tier_databases()` clears cache |
| Tier lookup code | ✅ | `src/scoring/tier_lookup.py` — word-boundary matching, `lru_cache` |
| Tier integration in scorer | ✅ | `src/scoring/unified_scorer.py` — education + certification code-only scoring |

---

## Ranking Evaluation Without Labeled Data (DEC-024)

**The problem:** the platform ranks candidates against recruiter-defined weight configs, but there is no single labeled "ground truth" ranking. Recruiters disagree among themselves; the "right" candidate is a judgment call; labeled sets are expensive and decay over time. A traditional ML evaluation (precision@K, NDCG against labels) does not apply.

**The approach:** five independent signals for "is our ranking correct?", none of which require a single labeled ground truth. The platform's claim "rankings are correct" is backed by **all five signals**, not one. If all five agree, the ranking is good. If any one disagrees, we investigate.

| Prong | Source of "ground truth" | Cost | Gate? | Target |
|---|---|---|---|---|
| **1. Counterfactual tests** | Constructed test cases with unambiguous expected behavior (weight monotonicity, must-have gate, years-proportionality, synonym equivalence) | Cheap; automated | **Yes** | Pass rate ≥ 0.95 |
| **2. Synthetic labeled set** | 30–50 (candidate, role) pairs hand-ranked by 2–3 recruiters; inter-rater agreement ≥ 0.60 | Moderate; quarterly | **Yes** | NDCG@10 ≥ 0.80 |
| **3. Stability tests** | Re-running the same config | Free | **Yes** | Rate = 1.0 (byte-identical) |
| **4. Recruiter agreement** | Cohen's kappa / Krippendorff's alpha against human raters | High; periodic study | Informational | Kappa ≥ 0.60 |
| **5. Behavioral signals** (production only) | `top_1_interview_rate`, `top_3_interview_rate`, `bottom_rejection_rate`, `revisit_rate` | Production data; noisy | Informational | Tracked, not enforced |

**Promotion gate (DEC-024):** a new "Active" config is promoted only if **all four** hold:
1. Counterfactual pass rate ≥ 0.95
2. Stability rate = 1.0
3. NDCG@10 ≥ 0.80 (if the labeled set exists; skipped otherwise)
4. No regression in the prior "Active" config's counterfactual pass rate

See `EVALUATION.md` §"Ranking Evaluation Without Labeled Data" for the full spec. Counterfactual suite lives at `data/eval/counterfactual_v1.jsonl` (M0.5f-c); synthetic labeled set at `data/eval/ranking_v1.jsonl` (M0.5f-d).

---

## M0.5: Experiment Tracking + Threshold-Based Retrieval (NEW 2026-07-05)

Per DEC-017/018/019/020/021. See `IMPLEMENTATION_ROADMAP.md` M0.5 for the full sub-milestone list.

| Sub-milestone | Status | Where |
|---|---|---|
| **M0.5a** — RecursiveChunker added; DocumentAwareChunker renamed | ✅ | `src/rag/recursive_chunker.py` shipped 2026-07-06 (DEC-019 active); `DocumentAwareChunker` retained at `src/rag/document_aware_chunker.py` as migration aid. Owner-specified Optuna bounds enforced: `chunk_size ∈ [200, 500]`, `chunk_overlap ∈ [100, floor(0.60 * chunk_size)]`. |
| **M0.5a** — Retriever switched to threshold-based cosine | ✅ | `src/rag/retriever.py` shipped 2026-07-06 (DEC-018 active). Defaults: `θ = 0.30`, `max_chunks_per_query = 20`. Owner-specified Optuna bounds enforced: `θ ∈ [0.10, 0.50]`. Cap-hit WARN log fires when unioned per-REQ set exceeds cap. |
| **M0.5a** — Per-REQ retrieval wired | ✅ | `src/rag/per_req_retrieval.py` shipped 2026-07-06 — `retrieve_evidence_for_req()` embeds each SubQuery, retrieves via `ThresholdRetriever`, unions + dedupes by `chunk_id` (highest cosine kept), caps the union, returns `[]` on zero retrieval so the caller raises the no-evidence flag. 11 unit tests at `tests/unit/test_per_req_retrieval.py`. |
| **M0.5a** — SubQuery parser extended | ✅ | `src/services/subquery_parser.py` extended 2026-07-06 to parse SubQuery table rows (`SQ### | text | type | scale | assessment_method`) into a `sub_queries` list per REQ. Verified on all 8 roles (138 REQs, 356 sub-queries, 0 count mismatches). |
| **M0.5a** — Embedding index rebuilt with Recursive chunks | ✅ | `data/embeddings/index.npz` + `chunks.jsonl` rebuilt 2026-07-06 by `src/rag/build_index.py`: 721 resumes → **6,670 chunks**, 384-dim MiniLM-L6-v2, L2-normalized, 8.4 MB. Prior Document-Aware index (6,377 chunks) backed up to `data/embeddings/document_aware_backup/`. |
| **M0.5a** — Cache key includes θ | ✅ | `src/services/subquery_retrieval.py::make_cache_key` extended 2026-07-06 with a `theta` kwarg folded into the SHA-256 hash (quantized to 6 decimals). All 3 callers updated to thread the retrieval `threshold` into the key. 11 unit tests at `tests/unit/test_cache_key.py` lock in the theta-in-key invariant for Optuna sweeps. |
| **M0.5b** — Eval set `data/eval/v1.jsonl` (≥50 triples, ≥3 roles, ≥4 dims) | ⬜ | Not started; **gate on M0.5d** |
| **M0.5c** — Local MLflow server running | ✅ | `scripts/start_mlflow_server.py` shipped 2026-07-08 (DEC-020); launcher produces the exact `mlflow server --host 127.0.0.1 --port 5000 --backend-store-uri sqlite:///data/mlflow/mlflow.db --default-artifact-root data/mlflow/artifacts/` command and pre-creates the SQLite + artifact dirs. |
| **M0.5c** — `mlflow`, `optuna`, `optuna-dashboard` in `requirements.txt` | 🟡 | `mlflow>=2.10,<5.0` (3.14.0 installed) + `optuna>=3.6,<5.0` pinned 2026-07-08. `optuna-dashboard` not installed in the dev env (pip fails on `pyarrow` wheel build); revisit for M0.5d. |
| **M0.5c** — Pipeline logs params + metrics + artifacts per `EVALUATION.md` contract | ✅ | `src/services/mlflow_wiring.py` ships the typed `PipelineParams` (9 DEC-020 params) + `RetrievalMetrics` (11 DEC-020 metrics) + `MLflowRun` context manager with graceful no-op degradation. `scripts/score_batch_composed.py` wires one `MLflowRun` per role, logs tags (`experiment_set`, `role`), all params, rollup + placeholder metrics, and the `<role>_ranked.json` artifact. New flags: `--no-mlflow`, `--experiment-set`, `--tracking-uri`, `--no-llm-track`. 12 hermetic unit tests at `tests/unit/test_mlflow_wiring.py` (in-memory SQLite tracking store, 524/524 total). |
| **M0.5d** — First Optuna study `chunking_v1_20260705` complete | ⬜ | `data/optuna/studies.db`; 200 trials; multi-objective |
| **M0.5d** — Pareto-front point promoted to "Active" in `MODEL_REGISTRY.md` | ⬜ | Promotion pending; current `θ = 0.70` is a placeholder |
| **M0.5e-a** — Legacy Document-Aware chunks moved to `data/document_aware_chunking/` | ⬜ | 721 files + `MIGRATION_NOTES.md` (DEC-022, refined by DEC-023) |
| **M0.5e-b** — Per-resume reasoning tree at `data/per_candidate/.../reasoning/` | ⬜ | New active cache; supersedes `llm_cache.jsonl` (DEC-022) |
| **M0.5e-b** — Per-experiment folder convention `data/recursive_chunking_<chunk_size>_<overlap>_<top_k>_<threshold×100>/` | ⬜ | Folder name encodes hyperparameters; one folder per (chunk_size, overlap, top_k, θ) combo (DEC-023) |
| **M0.5e-b** — `metadata.json` per experiment folder | ⬜ | Canonical record of the experiment's config (DEC-023) |
| **M0.5e-b** — `data/active_experiment` symlink to the "Active" config folder | ⬜ | Runtime entry point; one-line symlink operation when Active changes (DEC-023) |
| **M0.5e-c** — Backfill from legacy cache (one-time) | ⬜ | Mark backfilled entries; re-runs refresh them |
| **M0.5e-d** — Cache hit rate + determinism metrics | ⬜ | `cache_hit_rate`, `sub_score_match_rate` in MLflow (DEC-022) |
| **M0.5f-a** — Document-Aware chunking report (`reports/chunk_reports/document_aware_chunking_report.{json,md}`) | ⬜ | Captures the 49% missing-`section_type` finding (DEC-015) — the empirical justification for DEC-019 (DEC-024) |
| **M0.5f-b** — `generate_chunk_report` wired into the pipeline | ⬜ | Every Recursive experiment produces a committed `recursive_chunking_<params>_report.{json,md}` pair (DEC-024) |
| **M0.5f-c** — Counterfactual test suite (`data/eval/counterfactual_v1.jsonl`, ≥50 tests, ≥4 categories) | ⬜ | Fast feedback loop for the Optuna sweep; `pass_rate ≥ 0.95` is the promotion gate (DEC-024) |
| **M0.5f-d** — Synthetic labeled ranking set (`data/eval/ranking_v1.jsonl`, 30–50 pairs, 2–3 recruiters) | ⬜ | Slow feedback loop; `ndcg_at_10 ≥ 0.80` is the promotion gate; quarterly refresh (DEC-024) |
| **M0.5f-e** — Behavioral signal tracking (production) | ⬜ | `top_1_interview_rate`, `top_3_interview_rate`, `bottom_rejection_rate`, `revisit_rate` — tracked, not enforced (DEC-024) |

---

## M0.5g: Candidate ID Nomenclature (NEW 2026-07-05, DEC-025)

Replaces the SHA1-hash-based candidate id (`cand_<12hex>`) with the role-encoded sequential id (`<Role>_CAND_<NNNN>`, e.g. `BusinessAnalyst_CAND_0001`). See `IMPLEMENTATION_ROADMAP.md` M0.5g for the full sub-milestone list.

| Sub-milestone | Status | Where |
|---|---|---|
| **M0.5g-a** — DEC-025 in `DECISIONS.md` | ✅ | Decision record appended; id format `<Role>_CAND_<NNNN>`, registry at `data/candidate_registry.json` |
| **M0.5g-b** — `src/resume_parsing/candidate_registry.py` | ✅ | `CandidateRegistry` class with `allocate_or_lookup`, `lookup`, `save`, `load`; thread-safe; atomic write |
| **M0.5g-c** — `parser.py` integration | ✅ | `parse_resume(path, registry=None)` allocates the new id via the registry; legacy `candidate_id_from_path` preserved for the 6,377 existing Document-Aware chunks |
| **M0.5g-d** — `scripts/backfill_candidate_registry.py` | ✅ | Walks `data/processed/<role>/<id>.json` and registers all 721 existing candidates; idempotent |
| **M0.5g-e** — Backfill executed | ✅ | `data/candidate_registry.json` populated with 721 candidates (BA=133, DS=42, JD=72, RD=18, SQL=82, SM=164, SrPy=98, WD=112) |
| **M0.5g-f** — Tests | ✅ | `tests/unit/test_candidate_registry.py` (34 tests) + `tests/unit/test_parser_candidate_id.py` (10 tests); 49 new tests, all passing |

---

## Evaluation & Validation (Phase 7)

| Metric family | Status | Where |
|---|---|---|
| **Resume Parsing: Precision / Recall / F1** | ⬜ | Per `EVALUATION.md` "Resume Parsing Evaluation" — not yet instrumented |
| **Retrieval: Recall@K / Precision@K / MRR / nDCG** | 🟡 | `EVALUATION.md` "Retrieval Evaluation" — metrics defined; logs land in MLflow once M0.5c ships |
| **Retrieval (threshold-based): `recall_at_theta`, `precision_at_theta`, `cap_hit_rate`** | 🟡 | New per-θ metrics for DEC-018; defined in `EVALUATION.md` |
| **Generation: Faithfulness / Groundedness / Answer Relevancy** | 🟡 | Defined in `EVALUATION.md`; per-run log pending M0.5c |
| **Ranking: Top-K Accuracy / Recruiter Agreement / Ranking Accuracy** | 🟡 | **Replaced by the 5-pronged methodology (DEC-024)** — see "Ranking Evaluation Without Labeled Data" section above. Counterfactual suite (M0.5f-c) is the fast feedback loop; synthetic labeled set (M0.5f-d) is the slow feedback loop. |
| **Ranking (counterfactual): `pass_rate`, `by_category`** | ⬜ | M0.5f-c — target ≥ 0.95 for promotion |
| **Ranking (stability): `ranking_stability_rate`** | 🟡 | Covered by DEC-022 determinism; target = 1.0 |
| **Ranking (synthetic): `ndcg_at_10`, `top_3_accuracy`, `spearman`** | ⬜ | M0.5f-d — target NDCG@10 ≥ 0.80 for promotion |
| **Ranking (recruiter agreement): Cohen's kappa, Krippendorff's alpha** | ⬜ | Quarterly study, M0.5f-d |
| **Ranking (behavioral, production): `top_1_interview_rate`, `top_3_interview_rate`, `bottom_rejection_rate`, `revisit_rate`** | ⬜ | M0.5f-e — tracked, not enforced |
| **Hallucination Rate** | ⬜ | Per `EVALUATION.md` "Hallucination Evaluation" |
| **Per-Resume Reasoning Cache: `cache_hit_rate`, `sub_score_match_rate`, `disk_usage_total`** | 🟡 | DEC-022; logs land in MLflow once M0.5e-d ships |
| **Business: Screening Efficiency / Recruiter Time Saved** | ⬜ | Phase 7 — deferred until production data exists |
| **Chunk Reports (per-experiment diagnostics)** | ⬜ | `reports/chunk_reports/` per DEC-024; M0.5f-a/b |

---

## Next Recommended Unit of Work

**Status as of 2026-07-06:** the architecture pivot (DEC-017 → DEC-024) is fully specified. **Track 1 (M0.5a) is shipped** — RecursiveChunker + ThresholdRetriever + per-REQ retrieval + rebuilt embedding index (6,670 chunks) + theta-aware cache key are all live. **Track 2-S (scorer refactor, DEC-028) is shipped** — the composed Mode1 × Mode2 scorer (`evaluate_candidate_composed` + `evaluate_candidate_code_only_v2`) is unit-tested (38 new tests) and lands scores under the canonical WORKING_LOGIC formula (`Sub-Score = Code_only_part × Rubric_LLM_part`, `Total = Σ weight% × Sub-Score`). The legacy `evaluate_candidate` / `evaluate_candidate_unified` paths are kept untouched as backward-compat shims; production wiring (batch CLI) is the next step. 441/442 unit tests passing (1 pre-existing `ocr.py` failure, deferred). Below is a single ordered list of the next unit of work, in unblocking-power order. Several tracks (M0.5e, M0.5f) can run in parallel with M0.5b–d; see the notes.

### Track 1 — Stage 4 code (M0.5a) — ✅ SHIPPED 2026-07-06

M0.5a is the minimum viable code change to align the implementation with the new spec. All five sub-steps are shipped; the platform's "Active" config is now data-ready for the Optuna sweep (M0.5d) under the owner-specified bounds `θ ∈ [0.10, 0.50]`, `chunk_size ∈ [200, 500]`, `chunk_overlap ∈ [100, floor(0.60 * chunk_size)]`.

| Step | Action | Where | Status |
|---|---|---|---|
| 1.1 | Add `RecursiveChunker` class (LangChain-free `recursive_split_text`, separator hierarchy `["\n\n","\n",". "," "]`, `chunk_size=500`, `chunk_overlap=100`, bounds enforced) | `src/rag/recursive_chunker.py` | ✅ |
| 1.2 | Document-Aware retained as migration aid (not renamed — kept at original path per AGENTS.md "small commits") | `src/rag/document_aware_chunker.py` | ✅ |
| 1.3 | Switch `src/rag/retriever.py` from top-K to threshold-based cosine (default `θ = 0.30`, `max_chunks_per_query = 20`, bounds enforced, WARN on cap-hit) | `src/rag/retriever.py` | ✅ |
| 1.4 | Re-build the embedding index over the 721-resume corpus (721 → 6,670 chunks, 384-dim, prior index backed up) | `data/embeddings/index.npz` + `chunks.jsonl`; `src/rag/build_index.py` | ✅ |
| 1.5 | Update the LLM cache key to include `θ` (threaded through all 3 callers; quantized to 6 decimals; 11 unit tests) | `src/services/subquery_retrieval.py::make_cache_key` + `tests/unit/test_cache_key.py` | ✅ |

### Track 2-S — Composed scorer refactor (DEC-028) — ✅ SHIPPED 2026-07-06

Track 2-S is the production consumer for the Track 1 RAG pipeline. It introduces the canonical `Mode1 × Mode2` composed scorer per WORKING_LOGIC §1262-1289, drops the legacy `scale_factor` and `DEFAULT_EXPECTED_YEARS = 10` defaults, and gives the new pipeline its first end-to-end score path. All five sub-steps are shipped as additive code (legacy paths untouched, deprecated).

| Step | Action | Where | Status |
|---|---|---|---|
| 2-S.1 | Code-only v2 scorer: `Sub-Score = Code_only_part` (no `scale_factor`); `Total = Σ weight% × Sub-Score` lands in [0, 100]; missing `expected_years` = block + flag | `src/scoring/graded_scorer.py::evaluate_candidate_code_only_v2`, `extract_expected_years`, `CodeOnlyCandidateEvaluation` | ✅ |
| 2-S.2 | Sub-query parser extended: each REQ row carries `sub_queries` list (verified on 8 roles, 138 REQs / 356 sub-queries) | `src/services/subquery_parser.py::_extract_requirements` | ✅ |
| 2-S.3 | Composed evaluator: per REQ retrieve evidence via `per_req_retrieval`, score Code-only part from Binary + Years SQs, score Rubric LLM part via `rubric_scorer.score_requirement_with_rubric`, return `ComposedCandidateEvaluation`. New `sq_embedder` kwarg allows tests to inject stub vectors | `src/scoring/unified_scorer.py::evaluate_candidate_composed`, `ComposedREQResult`, `ComposedCandidateEvaluation`, helpers `_is_binary_subquery`/`_is_years_subquery`/`_is_rubric_subquery`/`_score_presence_sq`/`_score_years_sq`/`_build_section_evidence` | ✅ |
| 2-S.4 | Zero-evidence audit log: append-only JSONL `data/audit/no_evidence_flags.jsonl` per `(candidate, REQ)` pair with theta + chunker context | `src/audit/no_evidence_flags.py::write_flag` / `read_flags` / `clear_flags` | ✅ |
| 2-S.5 | 38 unit tests covering extract_expected_years (8), no_evidence_flags (6), code_only_v2 (6), sub-query classification (3), per-SQ scoring (5), evaluate_candidate_composed end-to-end (10). All tests use a 4-dim synthetic toy index + stub embedder (no MiniLM download) | `tests/unit/test_composed_scorer.py` | ✅ |

**Next step under Track 2-S:** wire the composed scorer into the batch CLI (`scripts/score_batch_composed.py`) so production runs swap from `graded_scorer.evaluate_role` to `evaluate_candidate_composed`. Until then, the legacy `evaluate_role` / `evaluate_candidate_unified` paths remain the live production path.

### Track 2 — Eval set + MLflow (M0.5b + M0.5c) — **gate on M0.5d**

Without these, Optuna (M0.5d) has no signal and no way to log results.

| Step | Action | Where |
|---|---|---|
| 2.1 | Hand-curate ≥ 50 (query, expected_chunks, expected_answer) triples in `data/eval/v1.jsonl` spanning ≥ 3 roles and ≥ 4 dimensions (M0.5b) | New file |
| 2.2 | Add `mlflow`, `optuna`, `optuna-dashboard` to `requirements.txt` (pinned) | `requirements.txt` |
| 2.3 | Launch `mlflow server --host 127.0.0.1 --port 5000 --backend-store-uri sqlite:///data/mlflow/mlflow.db` | Local server |
| 2.4 | Wire `with mlflow.start_run():` + the per-run `log_params` / `log_metrics` / `log_artifact` contract into the pipeline (DEC-020) | Pipeline entry point |

### Track 3 — First Optuna study (M0.5d) — **first data-driven defaults**

| Step | Action | Where |
|---|---|---|
| 3.1 | Create `data/optuna/studies.db` (SQLite, in `.gitignore`) | New file |
| 3.2 | First study: `chunking_v1_20260705` — multi-objective `[maximize faithfulness, minimize avg_chunks_returned]`, TPE, 200 trials, `MLflowCallback` (DEC-021) | `data/optuna/studies.db` |
| 3.3 | Pick the Pareto-front operating point that meets the faithfulness bar (e.g. `faithfulness ≥ 0.85`) | Optuna dashboard |
| 3.4 | Export params to `MODEL_REGISTRY.md` as the new "Active" config; recreate `data/active_experiment` symlink | `MODEL_REGISTRY.md` |

### Track 4 — Storage + reporting (M0.5e + M0.5f) — **parallel, independent of Track 1**

These tracks don't depend on the chunker/retriever code. Run them alongside Track 1.

**M0.5e (DEC-022 + DEC-023):**

| Step | Action | Where |
|---|---|---|
| 4.1 | Move 721 Document-Aware chunk files from `data/chunks/` → `data/document_aware_chunking/`; write `MIGRATION_NOTES.md` (M0.5e-a) | `data/document_aware_chunking/` |
| 4.2 | Replace `llm_cache.jsonl` with the per-experiment per-resume tree at `data/recursive_chunking_<params>/per_candidate/<role>/<candidate_id>/reasoning/<req_id>__<query_hash>.json` (M0.5e-b); create `data/active_experiment` symlink | `src/rag/retriever.py`, `src/scoring/rubric_scorer.py` |
| 4.3 | Backfill per-resume files from the legacy cache into the per-experiment tree (one-time; M0.5e-c) | `data/recursive_chunking_*/per_candidate/` |
| 4.4 | Add `cache_hit_rate`, `sub_score_match_rate`, storage-cost metrics to MLflow; raise disk-usage alert from 5 GB to **20 GB** (M0.5e-d) | `requirements.txt`, MLflow |

**M0.5f (DEC-024):**

| Step | Action | Where |
|---|---|---|
| 4.5 | Generate the historical Document-Aware report → `reports/chunk_reports/document_aware_chunking_report.{json,md}` (captures the 49% missing-`section_type` finding) | `reports/chunk_reports/` |
| 4.6 | Wire `generate_chunk_report` into the pipeline so every Recursive experiment produces a `recursive_chunking_<params>_report.{json,md}` pair | `src/reporting/chunk_report.py` |
| 4.7 | Build the counterfactual test suite → `data/eval/counterfactual_v1.jsonl` (≥ 50 tests spanning ≥ 4 categories) — **hard promotion gate: pass rate ≥ 0.95** | `data/eval/counterfactual_v1.jsonl` |
| 4.8 | Build the synthetic labeled ranking set → `data/eval/ranking_v1.jsonl` (30–50 pairs, 2–3 recruiters, inter-rater agreement ≥ 0.60) — **hard promotion gate: NDCG@10 ≥ 0.80** | `data/eval/ranking_v1.jsonl` |
| 4.9 | Add behavioral signal tracking for production (top-K interview rate, revisit rate, etc.) — tracked, not enforced | Production telemetry |

### Promotion gate (DEC-024, applies after M0.5d)

A new "Active" config is promoted only if **all four** hold:
1. Counterfactual pass rate ≥ 0.95
2. Stability rate = 1.0
3. NDCG@10 ≥ 0.80 (if the labeled set exists)
4. No regression in the prior "Active" config's counterfactual pass rate

### Deferred (not blocked by M0.5)

- **Robust prompt engineering for `linear` sub-questions.** The free LLM (nemotron-3-ultra-free) sometimes returns "Not specified" for `years_experience`. A better prompt or a fallback to the structured profile's `total_experience_years` would help. A larger model (gpt-5-mini, claude-haiku-4-5) would solve it but requires credits.
- **Per-item `expected_years` field in the FastAPI weight UI.** Today the form captures `weight_percentage` only.
- **JD clarification loop (Green / Yellow / Red).** Build `clarifications.json` per role; UI page that blocks Red items and requires Yellow answers.
- **Production rollout.** Behavioral signals (M0.5f-e) only become meaningful once recruiters are actually using the system.

### Track 5 — Substring-matching false-positive fix (DEC-029) — ✅ SHIPPED 2026-07-06

Pre-existing bug in `unified_scorer._score_education_code_only` and `_score_certification_code_only`: the legacy matchers used a bare `in` substring check (`item_name.lower() in degree.lower()`), so short abbreviations matched longer tokens that merely contained them (`"BA" in "MBA"`, `"BS" in "BSE"`, `"PMP" in "PMPI"`). The fix adds `_token_boundary_match` — a word-boundary regex matcher that preserves the legacy any-token semantic for cert matching (so `"AWS Certified"` still matches `"AWS Solutions Architect Associate"` via the `aws` token) while rejecting substring collisions.

| Step | Action | Where | Status |
|---|---|---|---|
| 5.1 | Add `_token_boundary_match` helper (whole-phrase OR any-token, all with `\b` word boundaries; stop-word filter skips tokens ≤ 2 chars) | `src/scoring/unified_scorer.py` | ✅ |
| 5.2 | Replace bare substring `in` checks in `_score_education_code_only` and `_score_certification_code_only` with the word-boundary helper | `src/scoring/unified_scorer.py` lines 170-171, 261-262 | ✅ |
| 5.3 | Add 6 regression tests: `BA` vs `MBA` (no match), `BS` vs `BSE` (no match), `BA` vs `BA` (matches), `BTech` vs `BTech in Computer Science` (matches), `PMP` vs `PMPI` (no match), `PMP` vs `PMP Certified` (matches) | `tests/unit/test_unified_scorer.py` | ✅ |

**Test status:** 447/448 passing (one pre-existing `ocr.py` failure, Track 6 deferred). +6 tests in this track vs the prior 441/442 baseline.

### Track 6 — Missing module reconciliation: `src/resume_parsing/ocr.py` + `header_normalization.py` (DEC-030) — ✅ SHIPPED 2026-07-06

Two pre-existing doc/impl inconsistencies from earlier architecture drafts:

1. **`src/resume_parsing/ocr.py` was a phantom.** `parser.py` already lazy-imported it via `try/except ImportError` and wrote `_HAS_OCR = False` when missing, but no module actually wired the PDF back-ends together. The parser raised `RuntimeError` whenever a `.pdf` path reached `extract_text_from_path`, even on machines where `pdfplumber` was already installed. The single failing test (`test_parse_resume_extracts_contact_and_name`) was a fixture PDF this path could never extract.
2. **Several docs claimed a `src/resume_parsing/header_normalization.py` file existed.** No such file was ever checked in — the section-header classification logic (the `SECTION_HEADERS` dict + `sectionize()` + `identify_section_heading()` functions) was implemented directly inside `src/resume_parsing/parser.py`. The phantom references lived across `CURRENT_PROGRESS.md`, `MODEL_REGISTRY.md`, `IMPLEMENTATION_ROADMAP.md`, `ARCHITECTURE_CHANGELOG.md`, and `RELEASE_NOTES.md`.

| Step | Action | Where | Status |
|---|---|---|---|
| 6.1 | Create `src/resume_parsing/ocr.py` as a real optional dependency bridge. Declares `_HAS_PDFPLUMBER`, `_HAS_PYPDFIUM`, `_HAS_PDF2IMAGE` availability flags at import time. Exposes `extract_text_hybrid(path) -> str` running pdfplumber first, pypdfium2 as Poppler-free fallback, pdf2image + OCR as last resort, raising informative `RuntimeError` if every strategy returns empty text. | `src/resume_parsing/ocr.py` (NEW) | ✅ |
| 6.2 | Add `pytest.mark.skipif(not _HAS_OCR, ...)` to `test_parse_resume_extracts_contact_and_name` so the suite is green in environments with and without PDF back-ends installed. | `tests/unit/test_resume_parser.py` | ✅ |
| 6.3 | Add 7 unit tests covering the availability flags, the happy-path extraction on the real `01888170110d1ccf.pdf` (John Wood's resume), both `RuntimeError` paths (no backends / empty backends), and the individual private backend wrappers. | `tests/unit/test_ocr.py` (NEW) | ✅ |
| 6.4 | Reconcile the `header_normalization.py` phantom in docs: `CURRENT_PROGRESS.md` (Header Normalization row), `MODEL_REGISTRY.md` (Header Normalization row), `IMPLEMENTATION_ROADMAP.md` (line 237), `ARCHITECTURE_CHANGELOG.md` (line 277 with reconciliation note). All four references now point to `parser.py` as the real implementation location. | docs (no code change) | ✅ |
| 6.5 | Document the optional-dependency pattern + the PDF back-end availability matrix in `ENVIRONMENT_NOTES.md`. Document the full debugging trail (symptoms → root cause → investigation → solution → prevention) in `TROUBLESHOOTING.md`. | `docs/ENVIRONMENT_NOTES.md`, `docs/TROUBLESHOOTING.md` | ✅ |

**Test status:** **455/455 passing** — perfect green. +7 new tests in this track vs the prior 447/448 baseline (the previously failing PDF test is now passing because `pdfplumber` is installed and `ocr.py` is restored).

### Track 7 — Production wiring: sub-query cache + batch CLI + Optuna rank stability (DEC-031, in progress 2026-07-06)

Track 7 is the production-wiring track that turns the composed scorer (Track 2-S) and the Track 1 RAG pipeline into a runnable end-to-end batch scorer. It also introduces the Optuna ranking-stability metric (Prong 6 of the ranking eval methodology per `EVALUATION.md`) so the team can see how brittle the shortlist is to hyperparameter perturbations during the M0.5d sweep.

| Step | Action | Where | Status |
|---|---|---|---|
| 7.0 | Add Project File Map to `docs/SYSTEM_ARCHITECTURE.md` so anyone (including PR inspectors) can navigate the source-tree / data-artifact / docs layout in one place. Add the new `data/embeddings/subqueries_cache.npz` and `data/audit/no_evidence_flags.jsonl` rows to `MODEL_REGISTRY.md`. Add Prong 6 (Optuna rank stability) to `docs/EVALUATION.md`. | `docs/SYSTEM_ARCHITECTURE.md`, `docs/MODEL_REGISTRY.md`, `docs/EVALUATION.md` | ✅ |
| 7.1 | Build `src/rag/subquery_cache.py`: in-memory dict + optional on-disk `data/embeddings/subqueries_cache.npz` (+ manifest JSONL). File-hash-aware invalidation (hash `<Role>_SubQuery.md` → store in manifest; rebuild when file changes). Wraps `embed_sub_queries`; the batch CLI passes a `cached_embedder` closure into `evaluate_candidate_composed`. | `src/rag/subquery_cache.py` (NEW) | ✅ |
| 7.2 | Fix single-year date heuristic in `parse_temporal_context`: when `dates` is a 4-digit year alone AND the entry has a real `company` + (`title` OR `details`) present → emit `calculated_duration_months = 12` with `inferred_full_year: True` flag. Guard against cert/education mis-bucketing by skipping entries whose `title` is a section name ("Certifications", "Education", "Projects"). Document the gaming-cost tradeoff (max ≈ 1 year false credit; recruiter-visible). | `src/resume_parsing/structured_profile.py` | ✅ |
| 7.3 | Wire the audit flag for inferred-full-year entries in `src/audit/no_evidence_flags.py` (new `flag_type: "inferred_full_year"` field) so the recruiter can see "this candidate got 12 months credit from a single-year date" in `data/audit/no_evidence_flags.jsonl`. | `src/audit/no_evidence_flags.py` | ✅ |
| 7.4 | Write `scripts/score_batch_composed.py` CLI: load subquery cache → for each role, walk `data/processed/<role>/*.json`, run `evaluate_candidate_composed` per candidate, dump per-role rankings to `data/scores/composed/<role>_ranked.json` + per-candidate evaluation JSONs. Pre-encode all 8 SubQuery files upfront via the cache. Track 8 roles × 721 candidates = 5,768 evaluations target; expected speedup vs naive = ~12 min/role saved by sub-query cache. | `scripts/score_batch_composed.py` (NEW); output to `data/scores/composed/` | ✅ |
| 7.4.1 | **Bug fix (2026-07-07):** All candidates scored 100.00 under `--no-llm` because the CLI was passing the entire 8-role dict to `evaluate_candidate_composed` as `role_subqueries`, while the function expected a single-role dict — so `sq_by_id` was empty and every REQ defaulted to `code_only_part=1.0 × rubric_llm_part=1.0 = 1.0`. Fix: made `evaluate_candidate_composed` robust to BOTH input shapes (slice out the single-role dict when the all-roles shape is detected via absence of a `requirements` key). Added a `rubric_skipped` boolean field to `ComposedREQResult` to distinguish the `--no-llm` rubric-bypass branch from a real "zero-evidence" branch so `n_zero_evidence_reqs` is correctly 0 under `--no-llm` (was miscounted as 19 per candidate). See `docs/TROUBLESHOOTING.md` for the full post-mortem. | `src/scoring/unified_scorer.py:1039`, `tests/unit/test_composed_scorer.py`, `tests/unit/test_unified_scorer.py` | ✅ |
| 7.4.2 | **Bug fix + scoring improvements (2026-07-07):** Three combined fixes that turn the LLM rubric path from always-zero into a working scoring pipeline. (a) **Widened chunking:** `chunk_size=500 → 1000`, `chunk_overlap=100 → 500` (50% of chunk_size). New Optuna bounds: `chunk_size ∈ [500, 1000]`, `chunk_overlap ∈ [floor(0.50 * chunk_size), floor(0.60 * chunk_size)]`. Reduces the failure mode where the date line lands in a different chunk from the skill mention. (b) **Lowered default θ:** `0.30 → 0.25` (bounds stay `[0.10, 0.50]`). Surfaces more date-bearing chunks per REQ. (c) **Employment-history context for rubric LLM:** `score_requirement_with_rubric` now accepts an optional `employment_history` kwarg; when non-empty, `_build_rubric_prompt` appends an `EMPLOYMENT HISTORY (computed deterministically from date ranges)` block so the LLM can correlate skill mentions in retrieved chunks with the parser-computed role durations — instead of being forced to re-parse sparse dates out of 500-char chunks. (d) **Banded years-ratio rule:** replaced continuous `min(years/target, 1.0)` with a discrete 4-band rule (`>= target → 1.0; >= 50% → 0.5; >= 25% → 0.25; else 0.0`) — easier to audit and explain to a recruiter. (e) **Lenient JSON parser + null-safety:** added `_extract_json_lenient` to recover truncated LLM responses mid-JSON; added defensive `null` handling for `sub_score` so a "no evidence" LLM answer doesn't crash the parser. (f) **Local Ollama backend:** added `OllamaRubricCaller` and `get_rubric_caller` factory in `src/services/llm_caller.py`; `.env` now selects `LLM_BACKEND=ollama` with `qwen2.5:3b` as the production rubric LLM (free-tier cloud was unreliable). End-to-end smoke test on DataScience `--limit 1`: 1 candidate scored 2.25 (was 0.00), with real LLM sub-scores (`skill_presence=1.0, years_experience=1.0, project_relevance=0.75`) and `extracted_years=3.0` (parsed from the employment_history block, not sparse chunks). | `src/rag/recursive_chunker.py`, `src/rag/retriever.py`, `src/scoring/rubric_scorer.py`, `src/scoring/unified_scorer.py:1264`, `src/services/llm_caller.py`, `scripts/score_batch_composed.py`, `tests/unit/test_recursive_chunker.py`, `tests/unit/test_retriever.py`, `tests/unit/test_rubric_scorer.py`, `data/embeddings/recursive_chunking/index.npz` (rebuilt) | ✅ |
| 7.5 | Build `src/reporting/rank_stability.py` — the Prong 6 reporter. Reads `reports/diff_rankings/optuna_study_*__rankings.json` files produced by the M0.5d sweep, computes `top_10_jaccard`, `top_50_jaccard`, `max_rank_shift`, `mean_abs_rank_shift`, `kendall_tau`, `spearman_rho`, `newcomer_rate_top_10`, `drop_rate_top_10`, `HP_axis_explained_variance`. Writes `rank_stability.json` + `.md` per `reports/diff_rankings/`. Includes 8 unit tests. 2026-07-08: shipped `src/reporting/rank_stability.py` (RankStabilityReport dataclass + pure-function per-pair primitives `top_k_jaccard`, `rank_shift_stats`, `distribution_correlations`, `newcomer_drop_rates` + study-level `compute_rank_stability` + `load_study_file` / `write_stability_report` I/O layer). All unsigned magnitudes per spec's +/- cancellation guard. HP-axis R^2 via closed-form single-slope regression (no scikit-learn). 9 unit tests (spec called for 8; one extra for malformed-JSON FileNotFoundError vs ValueError distinction). Tests hermetic — synthetic fixtures, no real Optuna study. Suite 512/512 (was 503 + 9). Ruff clean. | `src/reporting/rank_stability.py` (NEW: 766 lines), `tests/unit/test_rank_stability.py` (NEW: 9 tests) | ✅ |
| 7.6 | Full test suite run + docs update (DEC-031 in DECISIONS + ARCHITECTURE_CHANGELOG + RELEASE_NOTES). Headless-CLI smoke test on one role (DataScience) via `scripts/score_batch_composed.py`. 2026-07-07 docs sync landed: Track 7.4.1 bug-fix + Track 7.4.2 scoring improvements reflected across `WORKING_LOGIC.md`, `MODEL_REGISTRY.md`, `AI_DESIGN_RATIONALE.md`, `RELEASE_NOTES.md`, `ARCHITECTURE_CHANGELOG.md` (DEC-032 + DEC-033 entries). DEC-031 dedicated entry added to `DECISIONS.md` 2026-07-08 (Track 7 umbrella: subquery cache + batch CLI + rank-stability reporter). | `docs/DECISIONS.md`, `docs/ARCHITECTURE_CHANGELOG.md`, `docs/RELEASE_NOTES.md` | ✅ |

**Gating:** Track 7 gates M0.5b (eval set). Without the batch CLI, we cannot run on the eval set; without rank-stability, Optuna cannot diagnose shortlist churn.

---

## Recruiter Weight Configuration UI (2026-07-03)

**FastAPI + HTMX** service, no JS framework required. Replaces the per-role Streamlit CLI scripts (`recruiter_weight_input.py`) and the old `src/ui/recruiter_weight_config.py`.

| Capability | Status | Where |
|---|---|---|
| Role dropdown (8 roles synced from SubQuery docs) | ✅ | `src/api/roles.py` `POST /api/roles/sync-from-subquery` |
| Per-requirement slider (0–100, 0.5 step) | ✅ | `src/templates/partials/requirements_form.html` |
| `+` / `−` buttons for 0.5 fine-tuning | ✅ | `onclick="adjustWeight(...)"` in `configure.html` |
| Live category breakdown (rated/total/remaining %) | ✅ | `updateTotals()` JS in `configure.html` |
| Live "Current Weights" panel (REQ-ID, name, current %) | ✅ | `renderCurrentWeights()` JS in `configure.html` |
| Auto-balance to 100% | ✅ | `autoBalance()` JS in `configure.html` |
| Strict 100% validation (server-side + client-side) | ✅ | `pages.py:htmx_save_weights` + `updateTotals` |
| Persist to SQLite (`weight_configurations` + `weight_items`) | ✅ | `src/models/database.py` |
| Persist to JSON (`<role>_WeightConfig_<name>.json`) | ✅ | `src/services/json_export.py` |
| Delete removes from both DB and JSON | ✅ | `weights.py:delete_configuration` + `json_export.delete_json_config` |
| OpenAPI / Swagger docs | ✅ | `GET /docs` (FastAPI auto) |
| Per-item `expected_years` UI input | ⬜ | Field exists in DB + JSON; not yet exposed in slider form |
| Multiple recruiters per role (auth + isolation) | ⬜ | Single-recruiter model only |
| Edit existing config (load weights into form) | ⬜ | Configs are listed and deletable, not re-editable |

**Endpoints:**
- `GET /` — home
- `GET /configure` — weight config UI
- `GET /api/htmx/requirements/{role_id}` — slider form partial
- `GET /api/htmx/validate/{role_id}` — live validation summary
- `POST /api/htmx/save/{role_id}` — save to DB + JSON
- `GET /api/htmx/configurations/{role_id}` — saved configs list
- `GET /api/roles/`, `GET /api/weights/configurations`, etc. — REST API

**Launch:** `python -m uvicorn src.api.app:app --host 127.0.0.1 --port 8000` → http://127.0.0.1:8000/configure

---

## How this doc relates to others

- `WORKING_LOGIC.md` is the **canonical spec** (the "what should it do").
- This doc is the **status snapshot** (the "what does it do today").
- `IMPLEMENTATION_ROADMAP.md` is the **execution plan** (the "what do we build next").
- `ARCHITECTURE_CHANGELOG.md` is the **history** (the "what changed and when").
- `EVALUATION.md` is the **metric contract** (the "how do we know it's working?").

---

## Recent Decisions (2026-07-05, full day of pivots)

| DEC | Decision | Status |
|---|---|---|
| **DEC-017** | Regular RAG pivot for retrieval — single strategy for per-candidate + pool + chat | Accepted |
| **DEC-018** | Threshold-based cosine retrieval (`θ = 0.70`, `max_chunks_per_query = 20`); θ is an Optuna hyperparameter | Accepted |
| **DEC-019** | Recursive Chunking replaces Document-Aware Chunking as the active strategy | Accepted |
| **DEC-020** | MLflow for experiment tracking (local server, SQLite backend, filesystem artifact root) | Accepted |
| **DEC-021** | Optuna for hyperparameter search (multi-objective, TPE sampler, SQLite study store) | Accepted |
| **DEC-022** | Per-resume reasoning storage (`data/per_candidate/.../reasoning/<req_id>__<query_hash>.json`) + legacy chunk migration to `data/document_aware_chunking/` | Accepted |
| **DEC-023** | Per-experiment folder naming (`data/recursive_chunking_<chunk_size>_<overlap>_<top_k>_<threshold×100>/`) + `data/active_experiment` symlink + folder rename `chunks_legacy_document_aware/` → `document_aware_chunking/` | Accepted (refines DEC-022) |
| **DEC-024** | `reports/chunk_reports/` folder for per-experiment diagnostics + multi-pronged ranking evaluation (counterfactual + synthetic + stability + recruiter agreement + behavioral) | Accepted |

All eight decisions shipped in a single session. The deterministic scoring engine (`src/scoring/graded_scorer.py` + `src/scoring/unified_scorer.py`) is unchanged across all of them.

---

## Snapshot (one-paragraph)

As of 2026-07-05, the platform is at the end of stage 3 (Document-Aware Chunking, retired) and the spec for stage 4 (Recursive Chunking + threshold-based retrieval + MLflow + Optuna + per-experiment storage + per-resume reasoning + chunk reports + multi-pronged ranking evaluation) is fully laid out across `DEC-017` through `DEC-024`. The deterministic scoring engine, the tier databases, the structured candidate profile, the FastAPI weight UI, the per-role SubQuery audits, and the 721 parsed resumes are all shipped. The next session's job is to turn the M0.5 spec into working code (M0.5a–f) so the "Active" config in `MODEL_REGISTRY.md` becomes the first data-driven config rather than a placeholder.