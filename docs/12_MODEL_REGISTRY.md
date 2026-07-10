# Model Registry

## Overview

This document tracks production AI models, model-adjacent components, and deterministic evaluation strategies for HireIntel AI.

All model changes must be documented here before implementation, and significant AI architecture changes must also update `AI_DESIGN_RATIONALE.md`, `AI_ARCHITECTURE.md`, and `DECISIONS.md`.

---

## Current Registry

| Component | Current Selection | Status | Purpose |
| --- | --- | --- | --- |
| Active LLM | OpenRouter `minimax/minimax-m3` | **Active** | Candidate comparison narrative (`scripts/compare_two.py`); score explanation scaffold (`src/hireintel_ai/llm/service.py`). Resume chat and rubric-bound evidence scoring are **planned** but not yet implemented. |
| **Rubric LLM (rubric-bound scoring)** | **`qwen2.5:3b` via Ollama local endpoint** | **Active (2026-07-07)** | **Used by `src/scoring/rubric_scorer.py::score_requirement_with_rubric` for the rubric-bound LLM judge. Local inference via Ollama's OpenAI-compatible endpoint at `http://localhost:11434/v1` avoids free-tier cloud truncation issues (the nemotron-3-ultra-free endpoint was returning `choices=None` and `deepseek-v4-flash-free` truncated JSON mid-stream). `LLM_BACKEND=ollama` env var in `.env` selects this backend; the `OllamaRubricCaller` in `src/services/llm_caller.py` is a drop-in for `LLMRubricCaller`. ~6s per call, ~4000 max_tokens, returns complete JSON.** |
| Fallback Rubric LLM | `deepseek-v4-flash-free` via `https://opencode.ai/zen/v1` | Available (cloud fallback) | When `LLM_BACKEND=opencode` in `.env`, uses `LLMRubricCaller`. Free-tier `deepseek-v4-flash-free` works but truncates JSON mid-stream at the server-side `completion_tokens` cap — the rubric parser now has a `_extract_json_lenient` recovery helper to handle this case. |
| Primary LLM (production upgrade) | GPT-4 | Proposed | Resume parsing support, JD extraction support, summaries, comparisons, explanations |
| Fallback LLM (production upgrade) | Claude 3 | Proposed | Long-context fallback for large resumes and document-heavy comparison tasks |
| Private / Local LLM | Llama 3 | Proposed | Privacy-first deployment option where candidate data cannot leave controlled infrastructure |
| **Embedding Model** | **`sentence-transformers/all-MiniLM-L6-v2`** | **Active** | **Chunk and JD-bullet embeddings; 384-dim, CPU-runnable, ~80 MB, no API key** |
| Alternative Embedding Model | BGE-M3 | Future | Multilingual upgrade path; CPU-runnable but larger |
| Cloud Embedding Option | OpenAI `text-embedding-3-small` | Future | Highest quality but per-token API cost; data egress concern |
| Reranker | None yet | Future | Optional cross-encoder reranker for top-K precision boost (pool-level search only) |
| **Chunking Strategy** | **Recursive (`chunk_size=1000`, `chunk_overlap=500`)** | **Active (default-config, refined 2026-07-07)** | **Replaces Document-Aware chunking under DEC-019. LangChain-free `recursive_split_text` with separator hierarchy `["\n\n", "\n", ". ", " "]`. Both `chunk_size` and `chunk_overlap` are Optuna hyperparameters (DEC-021). Owner-refined Optuna bounds (2026-07-07): `chunk_size ∈ [500, 1000]`, `chunk_overlap ∈ [floor(0.50 * chunk_size), floor(0.60 * chunk_size)]` (overlap is 50-60% of chunk_size). Widened from prior `chunk_size=500`, `chunk_overlap=100` to reduce date/skill split incidents across chunks and improve rubric-LLM correlation of skill mentions with role durations. Bounds enforced at construction; exported as `CHUNK_SIZE_LOWER`/`CHUNK_SIZE_UPPER`/`CHUNK_OVERLAP_MIN_FRACTION`/`CHUNK_OVERLAP_MAX_FRACTION`/`min_overlap_for`/`max_overlap_for` in `src.rag.recursive_chunker`. Implementation in `src/rag/recursive_chunker.py`.** |
| **Header Normalization** | **Synonym lookup table + fallback classification (7 canonical sections)** | **Active** | **Maps heterogeneous resume headers to canonical section labels at parse time; still required by the structured profile (degrees/certs/total experience). No longer the retrieval routing mechanism (DEC-019).** |
| **Vector Storage** | **In-memory numpy (`data/embeddings/index.npz`)** | **Active** | **Trivial to load; switchable to FAISS / Chroma / Qdrant without API changes** |
| Planned Vector Database | FAISS / Chroma / Qdrant | Future | When scale exceeds single-machine memory or we need hosted multi-user |
| **Retrieval Mode** | **Threshold-based cosine (default `θ = 0.25`, `max_chunks_per_query = 20`)** | **Active (default-config, refined 2026-07-07)** | **Returns all chunks with cosine ≥ θ, sorted desc, capped at `max_chunks_per_query`; WARN log on cap-hit. Replaces Section-Routed (DEC-012) and Sub-Query Similarity (DEC-015) per DEC-017/018. θ is an Optuna hyperparameter. Owner-specified Optuna bounds (2026-07-06, retained 2026-07-07): `θ ∈ [0.10, 0.50]`. Bounds enforced at construction; exported as `THRESHOLD_LOWER`/`THRESHOLD_UPPER` in `src.rag.retriever`. The shipped default was lowered from `θ = 0.30` to `θ = 0.25` on 2026-07-07 to surface more date-bearing chunks per REQ during smoke testing (mitigates the failure mode where the date line landed in a chunk that did not pass a higher θ). Combined with the larger `chunk_size=1000` and 50% overlap, this drastically reduces incidents where the rubric LLM sees a skill mention without its corresponding date context. The Optuna-promoted "Active" config is still pending M0.5d — the shipped default is data-ready, not the recommended value. Implementation in `src/rag/retriever.py::ThresholdRetriever`.** |
| **Per-Candidate Evidence Retrieval** | **Threshold-based cosine over Recursive chunks** | **Active (2026-07-05)** | **Replaces Section-Routed as the per-candidate retrieval path; scoring engine still consumes the retrieved chunks for the rubric-bound LLM judge.** |
| **Cross-Candidate Pool Retrieval** | **Threshold-based cosine over Recursive chunks** | **Active (2026-07-05)** | **Single retrieval strategy now covers per-candidate + pool + chat (DEC-017).** |
| **Keyword Scoring Strategy** | **Deprecated — see `graded_scorer`** | **Legacy** | **Superseded by the single deterministic scorer below** |
| **Semantic Scoring Strategy** | **Deprecated — see `graded_scorer`** | **Legacy** | **Superseded by the single deterministic scorer below** |
| **Hybrid Scoring Strategy** | **Deprecated — see `graded_scorer`** | **Legacy** | **Superseded by the single deterministic scorer below** |
| **Code-Only Scoring** | **`src/scoring/graded_scorer.py` + `src/scoring/unified_scorer.py`**: per-item `min(weight_percentage, candidate_years / expected_years × weight_percentage)`, education/cert tier lookup, normalized to 0-100 | **Active** | **Scores total experience, skill presence/years, degree match + institute tier, cert match + provider tier, location — no LLM** |
| **Rubric-Bound LLM Evidence Scoring** | **`src/scoring/rubric_scorer.py` + `src/scoring/rubrics.py`: LLM judge scores against recruiter-defined rubric; weight application in code** | **Active** | **Scores skill depth, relevant/same-role/leadership experience, project complexity, language proficiency, communication quality; LLM never sees weight or computes aggregation** |
| **Rubric Templates** | **`src/scoring/rubrics.py`: 12 templates with anchored scales (0.0/0.25/0.5/0.75/1.0)** | **Active** | **Fixed sub-questions + formulas per dimension type; recruiter-visible, LLM cannot invent rubrics** |
| **Section-Routed Evidence Retrieval** | **`src/rag/section_routed.py`: exact label match on canonical sections** | **Superseded (2026-07-05) by DEC-017** | **Retained for one release as a migration aid only; new code should not call it** |
| **Header Normalization** | **`src/resume_parsing/parser.py` (the `SECTION_HEADERS` dict + `sectionize()` + `identify_section_heading()` functions): synonym lookup + fallback classification** | **Active (parse-time only)** | **7 canonical sections (Personal_Info, Education, Experience, Projects, Skills, Certifications, Languages); used by structured profile, not by retrieval. The dedicated `src/resume_parsing/header_normalization.py` file referenced in older docs was a phantom — see Track 6 reconciliation.** |
| **Chunk Metadata Schema** | **`src/rag/chunker.py`: simplified to `chunk_id`, `candidate_id`, `text`, `char_span`, `embedding_index`** | **Active (2026-07-05)** | **Section metadata is now a soft tag retained for the structured profile; not required for retrieval** |
| **Structured Candidate Profile** | **`src/resume_parsing/structured_profile.py`: deterministic extraction** | **Active** | **Degrees, institutions, certifications, total experience (no double-count), companies, roles, employment dates** |
| **Institute Tier Database** | **`data/Institutes/institute_tiers.json` + `src/scoring/tier_lookup.py`** | **Active** | **115 Tier 1 (1.0), 54 Tier 2 (0.75), 155 Tier 3 (0.50), not-listed (0.50); recruiter-editable** |
| **Certificate Tier Database** | **`data/Certificates/certificate_tiers.json` + `src/scoring/tier_lookup.py`** | **Active** | **115 Tier 1 (1.0), 45 Tier 2 (0.75), 10 Tier 3 (0.50), not-listed (0.50); recruiter-editable** |
| **Experiment Tracking** | **MLflow (local server, SQLite backend)** | **Active (2026-07-05, DEC-020)** | **Tracking URI `http://127.0.0.1:5000`; backend `data/mlflow/mlflow.db`; artifacts `data/mlflow/artifacts/`; every retrieval/scoring run logs params + metrics + retrieved-chunks JSON** |
| **Hyperparameter Search** | **Optuna (TPE sampler, multi-objective, SQLite study store)** | **Active (2026-07-05, DEC-021)** | **Studies at `data/optuna/studies.db`; default study: maximize faithfulness + minimize avg_chunks_returned; trials auto-logged to MLflow via `optuna.integration.MLflowCallback`** |
| **Candidate Ranking Strategy** | **Sort by the deterministic scorer's normalized total; ties broken by per-item matched count** | **Active** | **LLM never determines final ranking; unchanged by the RAG pivot** |

---

## Chunking Configuration

| Parameter | Value | Source |
| --- | --- | --- |
| Active chunker | `RecursiveChunker` | `src/rag/chunker.py` (DEC-019) |
| `chunk_size` | 500 chars (Optuna hyperparameter) | `src/rag/chunker.RECURSIVE_CHUNK_SIZE` |
| `chunk_overlap` | 50 chars (Optuna hyperparameter) | `src/rag/chunker.RECURSIVE_CHUNK_OVERLAP` |
| Separator hierarchy | `\n\n` → `\n` → `. ` → ` ` | `RecursiveCharacterTextSplitter` default |
| Legacy chunker | `DocumentAwareChunker` (renamed; retained for one release) | `src/rag/chunker.py` |
| Chunk ID format | `{candidate_id}__{chunk_index}` | e.g. `cand_xxx__14` |
| Required metadata | `chunk_id`, `candidate_id`, `text`, `char_span`, `embedding_index` | `src/rag/chunker.py` |
| Optional metadata | `section_type` (soft tag for the structured profile) | `src/rag/chunker.py` |

## Retrieval Configuration

| Parameter | Value | Source |
| --- | --- | --- |
| Retrieval mode | `threshold` | `src/rag/retriever.py` (DEC-018) |
| `threshold θ` | 0.25 (Optuna hyperparameter; bounds `[0.10, 0.50]` per owner spec 2026-07-06; default lowered from 0.30 → 0.25 on 2026-07-07) | `src/rag/retriever.DEFAULT_THRESHOLD` |
| `max_chunks_per_query` | 20 (safety cap) | `src/rag/retriever.MAX_CHUNKS_PER_QUERY` |
| Similarity metric | cosine | `src/rag/retriever` |
| Cap-hit warning | logged at WARN when > 20 chunks meet θ | `src/rag/retriever` |
| Fallback response (no chunks ≥ θ) | `"Information not found in candidate documents."` | prompt construction in `src/rag/retriever` |

## Storage Layout (added 2026-07-05, DEC-022, refined by DEC-023)

> **Pre-DEC-023 layout (active today):** the Recursive chunks + index live at `data/embeddings/recursive_chunking/{chunks.jsonl,index.npz}` (moved to a sub-folder 2026-07-06 Track 7.4 to separate the active Recursive artifacts from the legacy Document-Aware index). The per-experiment folder naming scheme below is the target post-M0.5e. The legacy Document-Aware index is backed up at `data/embeddings/document_aware_backup/`.

| Path | Purpose | Status | Notes |
| --- | --- | --- | --- |
| `data/embeddings/recursive_chunking/chunks.jsonl` | Recursive chunks (6,670) — pre-DEC-023 active location | Active (2026-07-06, M0.5a; moved into sub-folder 2026-07-06 Track 7.4) | Will be relocated to `data/recursive_chunking_<params>/chunks.jsonl` per DEC-023 once M0.5e ships. Schema: `chunk_id`, `candidate_id`, `role_bucket`, `source_file`, `section`, `chunk_index`, `text`, `metadata`. |
| `data/embeddings/recursive_chunking/index.npz` | Recursive embedding index (6,670 × 384-dim, L2-normalized, MiniLM-L6-v2) — pre-DEC-023 active location | Active (2026-07-06, M0.5a; moved into sub-folder 2026-07-06 Track 7.4) | Will be relocated to `data/recursive_chunking_<params>/index.npz` per DEC-023 once M0.5e ships. |
| `data/embeddings/subqueries_cache.npz` *(planned, Track 7)* | Encoded sub-queries cache — (N, 384) matrix + manifest mapping `cache_key → (role, req_id, sq_key, sq_text, subquery_file_hash)`. | Planned | File-hash-aware invalidation: rebuild when `<role>_SubQuery.md` changes. Wraps `embed_sub_queries`; consumed via `sq_embedder` callable in `evaluate_candidate_composed`. |
| `data/embeddings/document_aware_backup/` | Prior Document-Aware index (6,377 chunks) backed up pre-rebuild. | Legacy / read-only | M0.5a Step 1.4 migration record. |
| `data/embeddings/llm_cache_legacy.jsonl` | Legacy single-file LLM cache (35-line JSONL). | Legacy / read-only after M0.5e-b | Superseded by the per-experiment per-resume reasoning tree. |
| `data/document_aware_chunking/<role>/<candidate_id>.jsonl` | Legacy Document-Aware chunks | Legacy (read-only after M0.5e-a) | Renamed from `data/chunks_legacy_document_aware/` per DEC-023. `MIGRATION_NOTES.md` in the directory records the move. |
| `data/recursive_chunking_<chunk_size>_<overlap>_<top_k>_<threshold×100>/` | Per-experiment Recursive chunks + index + per-resume reasoning | Active (2026-07-05, DEC-023) | Folder name encodes the hyperparameters; see "Per-Experiment Folder Naming" below. One folder per (chunk_size, overlap, top_k, θ) combination. |
| `data/recursive_chunking_<chunk_size>_<overlap>_<top_k>_<threshold×100>/chunks.jsonl` | Recursive chunks for this experiment | Active | Written by `RecursiveChunker` only (DEC-019) |
| `data/recursive_chunking_<chunk_size>_<overlap>_<top_k>_<threshold×100>/index.npz` | Embedding index for this experiment | Active | 384-dim, L2-normalized, MiniLM-L6-v2 |
| `data/recursive_chunking_<chunk_size>_<overlap>_<top_k>_<threshold×100>/metadata.json` | Canonical record of the experiment's config | Active | Schema in `WORKING_LOGIC.md` §"Per-Experiment Folder Naming" |
| `data/recursive_chunking_<chunk_size>_<overlap>_<top_k>_<threshold×100>/per_candidate/<role>/<candidate_id>/reasoning/<req_id>__<query_hash>.json` | Per-resume reasoning artifacts for this experiment | Active (2026-07-05, DEC-022) | Stores narrative reasoning, basis, retrieved chunks, sub-scores per (candidate, req, query) |
| `data/active_experiment` | Symlink to the "Active" config folder | Active (2026-07-05, DEC-023) | Runtime entry point; promoted via one-line symlink operation when `MODEL_REGISTRY.md` "Active" row changes |
| `data/candidate_registry.json` | Candidate registry (DEC-025) | Active (2026-07-05) | Maps `<Role>_CAND_<NNNN>` to source path + legacy hash id; 721 entries backfilled from the existing corpus; **committed to git** (the source of truth for downstream joins) |
| `data/job_descriptions/<role>/<role>_SubQuery.md` | Canonical SubQuery source for each role | Authoritative | Parsed by `src/services/subquery_parser.py` into REQ list with `sub_queries` field. Verified on 8 roles: 138 REQs, 356 sub-queries. **Must not be editorialized** (AGENTS.md rule). |
| `data/job_descriptions/<role>/<role>_WeightConfig_<name>.json` | Recruiter weight configuration | Active | `requirements_weights` flat list, `weight_percentage` sums to 100, `expected_years` extracted from SubQuery SQ text via `extract_expected_years` (not stored per-item). |
| `data/Institutes/institute_tiers.json` | Recruiter-editable institute tier database | Active | Committed to git. |
| `data/Certificates/certificate_tiers.json` | Recruiter-editable certification tier database | Active | Committed to git. |
| `reports/audit/no_evidence_flags.jsonl` | Zero-evidence audit log | Active (2026-07-06, Track 2-S) | One line per `(candidate, REQ)` pair with no retrieved chunks. Schema: `flag_type: "no_evidence"`, `timestamp` ISO 8601 UTC, `candidate_id`, `role`, `req_id`, `requirement_name`, `sub_query_keys`, `sub_query_count`, `theta`, `chunker`. Written by `src/audit/no_evidence_flags.py::write_flag`. |
| `reports/audit/inferred_full_year_flags.jsonl` | Inferred-full-year audit log | Active (2026-07-06, Track 7.3 / DEC-031) | One line per accepted single-year-date inference. Schema: `flag_type: "inferred_full_year"`, `timestamp`, `candidate_id`, `year`, `dates_string`, `employer`, `role`, `inferred_months`, `guard_checks: {has_real_company, has_title_or_details, title_is_section_name}`. Written by `src/audit/no_evidence_flags.py::write_inferred_full_year_flag`. Kept in a separate file from `no_evidence_flags.jsonl` because the two flag types serve different audiences (scorer-debugging vs recruiter-trust) with orthogonal schemas. |
| `reports/chunk_reports/document_aware_chunking_report.{json,md}` | Historical Document-Aware diagnostic | Active (2026-07-05, DEC-024) | Captures the 49% missing-`section_type` finding (DEC-015) |
| `reports/chunk_reports/recursive_chunking_<params>_report.{json,md}` | Per-experiment Recursive diagnostic | Active (2026-07-05, DEC-024) | One pair (JSON + MD) per Recursive experiment; file name mirrors the experiment folder |
| `reports/diff_rankings/<baseline>__vs__<current>__<role>.{json,md}` | Ranking diff (DEC-026) + Optuna rank-stability metrics | Active (2026-07-05; rank-stability metrics added Track 7) | One pair (JSON + MD) per diff run; JSON includes the full per-case investigation records (reasoning + basis + retrieved chunks + sub-scores for both sides) |
| `data/eval/v1.jsonl` | Retrieval/RAG eval set (≥50 triples, ≥3 roles) | Planned (M0.5b) | Gates M0.5d Optuna. |
| `data/eval/counterfactual_v1.jsonl` | Counterfactual ranking suite (≥50 tests, ≥4 categories) | Planned (M0.5f) | Hard promotion gate: pass rate ≥ 0.95. |
| `data/eval/ranking_v1.jsonl` | Synthetic labeled ranking set (30–50 pairs, 2–3 recruiters, inter-rater agreement ≥ 0.60) | Planned (M0.5f) | Hard promotion gate: NDCG@10 ≥ 0.80. |
| `data/mlflow/mlflow.db` | MLflow backend store | Active (2026-07-05, DEC-020) | SQLite |
| `data/mlflow/artifacts/` | MLflow artifact root | Active (2026-07-05, DEC-020) | Retrieved-chunks JSON, eval-set inputs, study summaries |
| `data/optuna/studies.db` | Optuna study store | Active (2026-07-05, DEC-021) | SQLite; in `.gitignore` |

### Per-Experiment Folder Naming (DEC-023)

The active Recursive chunking pipeline writes its artifacts to per-experiment folders named after the hyperparameters that produced them:

```
data/recursive_chunking_<chunk_size>_<overlap>_<top_k>_<threshold×100>/
```

**Field order is fixed (4 numeric fields, in this order):**

| Position | Field | Example | Notes |
|---|---|---|---|
| 1 | `chunk_size` (chars) | `500` | from `RecursiveChunker.RECURSIVE_CHUNK_SIZE` |
| 2 | `overlap` (chars) | `200` | from `RecursiveChunker.RECURSIVE_CHUNK_OVERLAP` |
| 3 | `top_k` | `5` | from `Retriever.top_k`; `x` if not used |
| 4 | `threshold × 100` | `50` (i.e. θ=0.50) | from `Retriever.threshold`; `x` if not used |

**Examples:**

| Config | Folder |
|---|---|
| `chunk_size=500, overlap=200, top_k=5, θ=0.50` | `data/recursive_chunking_500_200_5_50/` |
| `chunk_size=500, overlap=50, top_k=10, θ=0.70` | `data/recursive_chunking_500_50_10_70/` |
| `chunk_size=500, overlap=50, θ=0.70` (threshold-only) | `data/recursive_chunking_500_50_x_70/` |
| `chunk_size=500, overlap=50, top_k=5` (top_k-only) | `data/recursive_chunking_500_50_5_x/` |

The "Active" config in this table points to one specific folder; promoting a new Active config means recreating the `data/active_experiment` symlink.

### `.gitignore` additions (per DEC-022, refined by DEC-023)

```gitignore
# Large binary artifacts
data/document_aware_chunking/
data/recursive_chunking_*/
# Recursive chunks + index moved into sub-folder 2026-07-06 (Track 7.4) to
# separate them from the legacy Document-Aware backup.
data/embeddings/recursive_chunking/
data/embeddings/document_aware_backup/
data/embeddings/llm_cache_legacy.jsonl
data/embeddings/llm_cache.jsonl
data/embeddings/subqueries_cache.npz
data/embeddings/subqueries_cache_manifest.jsonl
data/per_candidate/
data/per_candidate_archive/
data/mlflow/
data/optuna/

# Migration record is the only committed artifact in the legacy directory
!data/document_aware_chunking/MIGRATION_NOTES.md
```

**The `reports/` tree is fully tracked by git** — reports are small text files (a few KB each) and the historical record of every experiment matters. Binaries stay in `.gitignore`; reports do not.

The only committed artifacts in the data tree are:
- `data/document_aware_chunking/MIGRATION_NOTES.md` (DEC-022 migration record)
- `data/Institutes/institute_tiers.json` (recruiter-editable tier database)
- `data/Certificates/certificate_tiers.json` (recruiter-editable tier database)
- `data/eval/v1.jsonl` (the retrieval/RAG eval set, M0.5b)
- `data/eval/counterfactual_v1.jsonl` (the counterfactual ranking test suite, M0.5f)
- `data/eval/ranking_v1.jsonl` (the synthetic labeled ranking set, M0.5f)

## Scoring Configuration

| Parameter | Value | Source |
| --- | --- | --- |
| Default expected years (when config omits) | 10 | `src/scoring/graded_scorer.DEFAULT_EXPECTED_YEARS` |
| Per-item score rule | `min(weight_percentage, candidate_years / expected_years × weight_percentage)` | `src/scoring/graded_scorer.evaluate_candidate` |
| Partial credit (mentioned, no years) | `weight_percentage × 0.3` | `src/scoring/graded_scorer.evaluate_candidate` |
| Total normalization | Sum of all weight percentages (must equal 100%) | `src/scoring/graded_scorer.evaluate_candidate` |
| Section priority | experience.entries → skills → education.entries → certifications → projects → summary | `src/scoring/graded_scorer._search_profile` |
| Summary-years fallback | only for items in non-Education / non-Certification categories | `src/scoring/graded_scorer._is_experience_item` |
| Synonym dictionary | `src/scoring/graded_scorer._SYNONYMS` (curated, with regex word boundaries) | `src/scoring/graded_scorer._aliases_for` |

---

## Change Control

Before changing any model, retrieval strategy, reranker, chunking approach, scoring methodology, hyperparameter, or experiment-tracking config:

1. Add or update an entry in `DECISIONS.md`.
2. Update `AI_DESIGN_RATIONALE.md`.
3. Update this registry.
4. Update `AI_ARCHITECTURE.md` when workflow impact exists.
5. Update `EVALUATION.md` with required validation metrics.
6. Log the change as an MLflow run (DEC-020) and, if it is a hyperparameter, add a trial to the active Optuna study (DEC-021).

The shipped `θ`, `chunk_size`, and `chunk_overlap` are always the **Optuna-recommended point on the Pareto front**, not hand-picked. Promotion to "Active" status requires the Optuna trial to exist in `data/optuna/studies.db` and the corresponding MLflow run to be in the registry.

