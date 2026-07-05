# Current Progress vs `WORKING_LOGIC.md`

This document maps every step of the canonical spec
[`WORKING_LOGIC.md`](WORKING_LOGIC.md) to its implementation status as of
**2026-07-05**. Use it as the single source of truth for "what's done vs what's
left" when planning the next session.

**Legend:** ✅ Shipped · 🟡 Partially shipped / scaffolded · ⬜ Planned

---

> ## Architecture pivot (2026-07-05)
>
> The platform pivoted end-to-end in a single day. Eight new decisions
> (`DEC-017` through `DEC-024`) reshape retrieval, chunking, storage,
> experiment management, and ranking evaluation. The **deterministic scoring
> engine is unchanged** and remains the only ranking signal.
>
> | DEC | What changed |
> |---|---|
> | DEC-017 | **Regular RAG pivot.** Single retrieval strategy for everything: per-candidate scoring, pool search, resume chat. Section-Routed (DEC-012) and Sub-Query Similarity (DEC-015) superseded. |
> | DEC-018 | **Threshold-based cosine retrieval** (`θ = 0.70`, `max_chunks_per_query = 20`). θ is an Optuna hyperparameter. |
> | DEC-019 | **Recursive Chunking replaces Document-Aware.** `chunk_size = 500`, `chunk_overlap = 50`. Both are Optuna hyperparameters. Header Normalization retained for parse-time only. |
> | DEC-020 | **MLflow for experiment tracking.** Local server, SQLite backend, filesystem artifact root. Every retrieval / scoring run logged. |
> | DEC-021 | **Optuna for hyperparameter search.** Multi-objective (faithfulness ↑, avg_chunks_returned ↓). TPE sampler, SQLite study store. |
> | DEC-022 | **Per-resume reasoning storage + legacy chunk migration.** Replaces `llm_cache.jsonl` with `data/per_candidate/<role>/<id>/reasoning/<req_id>__<query_hash>.json` storing reasoning + basis + retrieved chunks + sub-scores. |
> | DEC-023 | **Per-experiment folder naming.** `data/recursive_chunking_<chunk_size>_<overlap>_<top_k>_<threshold×100>/` with `data/active_experiment` symlink. `data/chunks_legacy_document_aware/` renamed to `data/document_aware_chunking/`. |
> | DEC-024 | **Chunk reports folder + multi-pronged ranking evaluation.** `reports/chunk_reports/` per-experiment diagnostics. Five independent signals for "is our ranking correct?" — none require a single labeled ground truth. |
>
> See `ARCHITECTURE_CHANGELOG.md` 2026-07-05 (a/b/c/d) for the full change set.

---

## Pipeline Stages (high-level view)

The platform moves through four stages; the first three are shipped, the fourth is the next unit of work.

| # | Stage | Status | Where |
|---|---|---|---|
| 1 | **JD Formation** — extract requirements from JDs (required/preferred skills, experience, education, certifications); produce per-role structured JD objects | ✅ | `data/job_descriptions/<role>/<Role>_JD.md` + `<Role>_RecruiterWeights_EXAMPLE.json`; 8 roles fully populated |
| 2 | **Sub-Query Formation** — decompose each JD requirement into 2–4 anchored sub-questions (binary / linear / anchored) so the LLM can judge each aspect separately | ✅ | `data/job_descriptions/<role>/<Role>_SubQuery.md`; 8 roles audited (DEC-014) |
| 3 | **Document-Aware Chunking** — preserve resume section structure (one chunk per experience/education/project entry) with Header Normalization for parse-time section labeling | ✅ shipped, now legacy | `data/document_aware_chunking/` (moved 2026-07-05 per DEC-022/023); the **49% missing-`section_type` finding (DEC-015)** is captured in `reports/chunk_reports/document_aware_chunking_report.{json,md}` (M0.5f-a) |
| 4 | **Recursive Chunking** — uniform 500-char chunks with 50-char overlap, threshold-based cosine retrieval (cosine ≥ θ), per-experiment folder convention | 🟡 in progress | `data/recursive_chunking_<params>/` (M0.5a-d-f); `data/active_experiment` symlink (M0.5e-b) |

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
| **Recursive Chunking is the default** (2026-07-05) | 🟡 | `RecursiveChunker` is the active chunker per DEC-019; implementation pending. `DocumentAwareChunker` retained for one release as a migration aid. |

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
| **Recursive Chunking** (active 2026-07-05) | Uniform 500-char chunks with 50-char overlap | 🟡 | `RecursiveChunker` is the active chunker per DEC-019; implementation pending. `DocumentAwareChunker` retained for one release as a migration aid. `chunk_size` and `chunk_overlap` are Optuna hyperparameters. |
| Header Normalization | Synonym lookup + fallback classification → 7 canonical sections | ✅ | `src/resume_parsing/header_normalization.py` — still required by the structured profile (degrees, certs, total experience). No longer the retrieval routing mechanism (DEC-019). |
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
| **M0.5a** — RecursiveChunker added; DocumentAwareChunker renamed | ⬜ | `src/rag/chunker.py` — new class pending |
| **M0.5a** — Retriever switched to threshold-based cosine | ⬜ | `src/rag/retriever.py` — `θ` and `max_chunks_per_query` pending |
| **M0.5a** — Embedding index rebuilt with Recursive chunks | ⬜ | `data/embeddings/index.npz` + `chunks.jsonl` — current build is from Document-Aware |
| **M0.5a** — Cache key includes θ | ⬜ | `data/embeddings/llm_cache.jsonl` — needs invalidation + new key |
| **M0.5b** — Eval set `data/eval/v1.jsonl` (≥50 triples, ≥3 roles, ≥4 dims) | ⬜ | Not started; **gate on M0.5d** |
| **M0.5c** — Local MLflow server running | ⬜ | `http://127.0.0.1:5000`; backend `data/mlflow/mlflow.db` |
| **M0.5c** — `mlflow`, `optuna`, `optuna-dashboard` in `requirements.txt` | ⬜ | Not pinned yet |
| **M0.5c** — Pipeline logs params + metrics + artifacts per `EVALUATION.md` contract | ⬜ | Wiring pending |
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

**Status as of 2026-07-05:** the architecture pivot is fully specified (DEC-017 through DEC-024). The next session turns the spec into working code. Below is a single ordered list of the next unit of work, in unblocking-power order. Several tracks (M0.5e, M0.5f) can run in parallel with M0.5a–d; see the notes.

### Track 1 — Stage 4 code (M0.5a) — **highest unblocking power**

This is the minimum viable code change to align the implementation with the new spec. Until M0.5a ships, the platform's "Active" config is the placeholder `θ = 0.70` / `chunk_size = 500` / `chunk_overlap = 50` — none of which are data-driven yet.

| Step | Action | Where |
|---|---|---|
| 1.1 | Add `RecursiveChunker` class to `src/rag/chunker.py` (`RecursiveCharacterTextSplitter(separators=["\n\n","\n",". "," "], chunk_size=500, chunk_overlap=50)`) | New class |
| 1.2 | Rename existing chunker to `DocumentAwareChunker` (DEC-023) | `src/rag/chunker.py` |
| 1.3 | Switch `src/rag/retriever.py` from top-K to threshold-based cosine (default `θ = 0.70`, `max_chunks_per_query = 20`); WARN on cap-hit | `src/rag/retriever.py` |
| 1.4 | Re-build the embedding index over the 721-resume corpus | `data/embeddings/index.npz` + `chunks.jsonl` |
| 1.5 | Update the LLM cache key to include `θ` (DEC-022) | `data/embeddings/llm_cache.jsonl` |

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