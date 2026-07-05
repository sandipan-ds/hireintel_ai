# Model Registry

## Overview

This document tracks production AI models, model-adjacent components, and deterministic evaluation strategies for HireIntel AI.

All model changes must be documented here before implementation, and significant AI architecture changes must also update `AI_DESIGN_RATIONALE.md`, `AI_ARCHITECTURE.md`, and `DECISIONS.md`.

---

## Current Registry

| Component | Current Selection | Status | Purpose |
| --- | --- | --- | --- |
| Active LLM | OpenRouter `minimax/minimax-m3` | **Active** | Candidate comparison narrative (`scripts/compare_two.py`); score explanation scaffold (`src/hireintel_ai/llm/service.py`). Resume chat and rubric-bound evidence scoring are **planned** but not yet implemented. |
| Primary LLM (production upgrade) | GPT-4 | Proposed | Resume parsing support, JD extraction support, summaries, comparisons, explanations |
| Fallback LLM (production upgrade) | Claude 3 | Proposed | Long-context fallback for large resumes and document-heavy comparison tasks |
| Private / Local LLM | Llama 3 | Proposed | Privacy-first deployment option where candidate data cannot leave controlled infrastructure |
| **Embedding Model** | **`sentence-transformers/all-MiniLM-L6-v2`** | **Active** | **Chunk and JD-bullet embeddings; 384-dim, CPU-runnable, ~80 MB, no API key** |
| Alternative Embedding Model | BGE-M3 | Future | Multilingual upgrade path; CPU-runnable but larger |
| Cloud Embedding Option | OpenAI `text-embedding-3-small` | Future | Highest quality but per-token API cost; data egress concern |
| Reranker | None yet | Future | Optional cross-encoder reranker for top-K precision boost (pool-level search only) |
| **Chunking Strategy** | **Recursive (`chunk_size=500`, `chunk_overlap=50`)** | **Active (2026-07-05)** | **Replaces Document-Aware chunking under DEC-019. Both `chunk_size` and `chunk_overlap` are Optuna hyperparameters (DEC-021).** |
| **Header Normalization** | **Synonym lookup table + fallback classification (7 canonical sections)** | **Active** | **Maps heterogeneous resume headers to canonical section labels at parse time; still required by the structured profile (degrees/certs/total experience). No longer the retrieval routing mechanism (DEC-019).** |
| **Vector Storage** | **In-memory numpy (`data/embeddings/index.npz`)** | **Active** | **Trivial to load; switchable to FAISS / Chroma / Qdrant without API changes** |
| Planned Vector Database | FAISS / Chroma / Qdrant | Future | When scale exceeds single-machine memory or we need hosted multi-user |
| **Retrieval Mode** | **Threshold-based cosine (default `θ = 0.70`, `max_chunks_per_query = 20`)** | **Active (2026-07-05)** | **Returns all chunks with cosine ≥ θ; replaces both Section-Routed (DEC-012) and Sub-Query Similarity (DEC-015) per DEC-017/018. θ is an Optuna hyperparameter.** |
| **Per-Candidate Evidence Retrieval** | **Threshold-based cosine over Recursive chunks** | **Active (2026-07-05)** | **Replaces Section-Routed as the per-candidate retrieval path; scoring engine still consumes the retrieved chunks for the rubric-bound LLM judge.** |
| **Cross-Candidate Pool Retrieval** | **Threshold-based cosine over Recursive chunks** | **Active (2026-07-05)** | **Single retrieval strategy now covers per-candidate + pool + chat (DEC-017).** |
| **Keyword Scoring Strategy** | **Deprecated — see `graded_scorer`** | **Legacy** | **Superseded by the single deterministic scorer below** |
| **Semantic Scoring Strategy** | **Deprecated — see `graded_scorer`** | **Legacy** | **Superseded by the single deterministic scorer below** |
| **Hybrid Scoring Strategy** | **Deprecated — see `graded_scorer`** | **Legacy** | **Superseded by the single deterministic scorer below** |
| **Code-Only Scoring** | **`src/scoring/graded_scorer.py` + `src/scoring/unified_scorer.py`**: per-item `min(weight_percentage, candidate_years / expected_years × weight_percentage)`, education/cert tier lookup, normalized to 0-100 | **Active** | **Scores total experience, skill presence/years, degree match + institute tier, cert match + provider tier, location — no LLM** |
| **Rubric-Bound LLM Evidence Scoring** | **`src/scoring/rubric_scorer.py` + `src/scoring/rubrics.py`: LLM judge scores against recruiter-defined rubric; weight application in code** | **Active** | **Scores skill depth, relevant/same-role/leadership experience, project complexity, language proficiency, communication quality; LLM never sees weight or computes aggregation** |
| **Rubric Templates** | **`src/scoring/rubrics.py`: 12 templates with anchored scales (0.0/0.25/0.5/0.75/1.0)** | **Active** | **Fixed sub-questions + formulas per dimension type; recruiter-visible, LLM cannot invent rubrics** |
| **Section-Routed Evidence Retrieval** | **`src/rag/section_routed.py`: exact label match on canonical sections** | **Superseded (2026-07-05) by DEC-017** | **Retained for one release as a migration aid only; new code should not call it** |
| **Header Normalization** | **`src/resume_parsing/header_normalization.py`: Layer 1 synonym table + Layer 2 LLM fallback** | **Active (parse-time only)** | **7 canonical sections (Personal_Info, Education, Experience, Projects, Skills, Certifications, Languages); used by structured profile, not by retrieval** |
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
| `threshold θ` | 0.70 (Optuna hyperparameter) | `src/rag/retriever.DEFAULT_THRESHOLD` |
| `max_chunks_per_query` | 20 (safety cap) | `src/rag/retriever.MAX_CHUNKS_PER_QUERY` |
| Similarity metric | cosine | `src/rag/retriever` |
| Cap-hit warning | logged at WARN when > 20 chunks meet θ | `src/rag/retriever` |
| Fallback response (no chunks ≥ θ) | `"Information not found in candidate documents."` | prompt construction in `src/rag/retriever` |

## Storage Layout (added 2026-07-05, DEC-022, refined by DEC-023)

| Path | Purpose | Status | Notes |
| --- | --- | --- | --- |
| `data/document_aware_chunking/<role>/<candidate_id>.jsonl` | Legacy Document-Aware chunks | Legacy (read-only after M0.5e-a) | Renamed from `data/chunks_legacy_document_aware/` per DEC-023. `MIGRATION_NOTES.md` in the directory records the move. |
| `data/recursive_chunking_<chunk_size>_<overlap>_<top_k>_<threshold×100>/` | Per-experiment Recursive chunks + index + per-resume reasoning | Active (2026-07-05, DEC-023) | Folder name encodes the hyperparameters; see "Per-Experiment Folder Naming" below. One folder per (chunk_size, overlap, top_k, θ) combination. |
| `data/recursive_chunking_<chunk_size>_<overlap>_<top_k>_<threshold×100>/chunks.jsonl` | Recursive chunks for this experiment | Active | Written by `RecursiveChunker` only (DEC-019) |
| `data/recursive_chunking_<chunk_size>_<overlap>_<top_k>_<threshold×100>/index.npz` | Embedding index for this experiment | Active | 384-dim, L2-normalized, MiniLM-L6-v2 |
| `data/recursive_chunking_<chunk_size>_<overlap>_<top_k>_<threshold×100>/metadata.json` | Canonical record of the experiment's config | Active | Schema in `WORKING_LOGIC.md` §"Per-Experiment Folder Naming" |
| `data/recursive_chunking_<chunk_size>_<overlap>_<top_k>_<threshold×100>/per_candidate/<role>/<candidate_id>/reasoning/<req_id>__<query_hash>.json` | Per-resume reasoning artifacts for this experiment | Active (2026-07-05, DEC-022) | Stores narrative reasoning, basis, retrieved chunks, sub-scores per (candidate, req, query) |
| `data/active_experiment` | Symlink to the "Active" config folder | Active (2026-07-05, DEC-023) | Runtime entry point; promoted via one-line symlink operation when `MODEL_REGISTRY.md` "Active" row changes |
| `data/embeddings/llm_cache_legacy.jsonl` | Legacy single-file LLM cache | Legacy (read-only after M0.5e-b) | Superseded by the per-experiment per-resume reasoning tree |
| `data/per_candidate_archive/` | Archived reasoning entries (90+ days idle) | Planned | GC target; not yet created |
| `data/mlflow/mlflow.db` | MLflow backend store | Active (2026-07-05, DEC-020) | SQLite |
| `data/mlflow/artifacts/` | MLflow artifact root | Active (2026-07-05, DEC-020) | Retrieved-chunks JSON, eval-set inputs, study summaries |
| `data/optuna/studies.db` | Optuna study store | Active (2026-07-05, DEC-021) | SQLite; in `.gitignore` |
| `data/candidate_registry.json` | Candidate registry (DEC-025) | Active (2026-07-05) | Maps `<Role>_CAND_<NNNN>` to source path + legacy hash id; 721 entries backfilled from the existing corpus; **committed to git** (the source of truth for downstream joins) |
| `reports/chunk_reports/document_aware_chunking_report.{json,md}` | Historical Document-Aware diagnostic | Active (2026-07-05, DEC-024) | Captures the 49% missing-`section_type` finding (DEC-015) |
| `reports/chunk_reports/recursive_chunking_<params>_report.{json,md}` | Per-experiment Recursive diagnostic | Active (2026-07-05, DEC-024) | One pair (JSON + MD) per Recursive experiment; file name mirrors the experiment folder |
| `reports/diff_rankings/<baseline>__vs__<current>__<role>.{json,md}` | Ranking diff (DEC-026) | Active (2026-07-05) | One pair (JSON + MD) per diff run; JSON includes the full per-case investigation records (reasoning + basis + retrieved chunks + sub-scores for both sides) |

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
data/embeddings/index.npz
data/embeddings/chunks.jsonl
data/embeddings/llm_cache_legacy.jsonl
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

