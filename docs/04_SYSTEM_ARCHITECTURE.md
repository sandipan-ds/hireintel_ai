# System Architecture

> **Source of truth for scoring, evaluation, and ranking:**
> [`WORKING_LOGIC.md`](WORKING_LOGIC.md). This document covers the high-level
> system architecture; AI-specific architecture is in
> [`AI_ARCHITECTURE.md`](AI_ARCHITECTURE.md). For "what is implemented today
> vs what's planned", see [`CURRENT_PROGRESS.md`](CURRENT_PROGRESS.md).

## Overview

This document describes the high-level architecture, system components, service interactions, and deployment model for the HireIntel AI platform.

---

## Project File Map (navigational index)

This section is the single-entry index for "which file does what" in the repository. New contributors (and PR inspectors) start here, then dive into the specific doc / file for their question. For per-experiment data artifacts see `MODEL_REGISTRY.md` "Storage Layout". For AI-specific architecture see `AI_ARCHITECTURE.md`. For what's implemented today vs planned see `CURRENT_PROGRESS.md`.

### Source code (`src/`)

| File | What it does | Replaced / superseded by |
|---|---|---|
| `src/resume_parsing/parser.py` | Deterministic resume parser. Produces the structured profile (`raw_text`, `sections`, `name`, `contact`, `summary`, `experience`, `education`, `skills`, `certifications`, `projects`, `languages`). Owns section-header classification (`SECTION_HEADERS`, `sectionize()`, `identify_section_heading()`). | — |
| `src/resume_parsing/ocr.py` | Optional PDF → text bridge. Hybrid: `pdfplumber` → `pypdfium2` (Poppler-free) → `pdf2image` (OCR last resort, placeholder). Lazy-imported by `parser.py`; absent => `_HAS_OCR=False` and `.pdf` paths raise an informative `RuntimeError`. | — |
| `src/resume_parsing/structured_profile.py` | Deterministic structured-profile extractor. Parses dates, computes `calculated_duration_months` per employment entry, merges overlapping intervals for `total_experience_years` (no double-counting). | — |
| `src/resume_parsing/candidate_registry.py` | `CandidateRegistry` class — canonical `<Role>_CAND_<NNNN>` id allocator (DEC-025). Atomic, persistent, role-encoded. Backed by `data/candidate_registry.json`. | — |
| `src/api/roles.py` + `src/api/pages.py` + `src/templates/` | FastAPI + HTMX recruiter UI. Role drop-down, weight slider per REQ (0–100, strict 100% sum), persist to SQLite + JSON. See "Recruiter Weight Configuration UI" in `CURRENT_PROGRESS.md`. | Streamlit `recruiter_weight_input.py` (retired). |
| `src/services/json_export.py` | Persists recruiter weight config to `data/job_descriptions/<role>/<role>_WeightConfig_<name>.json`. | — |
| `src/services/subquery_parser.py` | Parses `<role>_SubQuery.md` → REQ list with `sub_queries` field (Track 2-S Step 2-S.2). Verified on 8 roles: 138 REQs, 356 sub-queries, 0 mismatches. | — |
| `src/services/subquery_retrieval.py` | **Legacy** retrieval path (DEC-017). `retrieve_chunks_for_requirement` + `make_cache_key` (theta-aware, SHA-256, 6-decimal quantization). Kept as backward-compat shim; new code uses `src/rag/per_req_retrieval.py`. | `src/rag/per_req_retrieval.py` |
| `src/rag/recursive_chunker.py` | `RecursiveChunker` — active chunker (DEC-019). LangChain-free `recursive_split_text`, separators `["\n\n","\n",". "," "]`. Optuna bounds enforced at construction: `chunk_size ∈ [200, 500]`, `chunk_overlap ∈ [100, floor(0.60 * chunk_size)]`. | `src/rag/document_aware_chunker.py` (legacy, retained one release as migration aid). |
| `src/rag/document_aware_chunker.py` | Legacy Document-Aware chunker (DEC-019 superseded). Read-only after M0.5e-a. | `src/rag/recursive_chunker.py` |
| `src/rag/section_routed.py` | **Legacy** section-routed retrieval (DEC-017 superseded). `classify_requirement_type` + `retrieve_evidence_for_requirement`. `SectionEvidence` dataclass is still reused by the composed scorer via `_build_section_evidence`. | `src/rag/per_req_retrieval.py` |
| `src/rag/build_index.py` | CLI — walks `data/processed/<role>/*.json`, filters `_intelligence_report.json` / `_structured_profile.json` downstream artifacts (721 resumes → canonical chunk source), chunks each profile with `RecursiveChunker`, embeds with MiniLM-L6-v2, writes `data/embeddings/recursive_chunking/chunks.jsonl` + `index.npz`. Run: `python -m src.rag.build_index`. | — |
| `src/rag/retriever.py` | `ThresholdRetriever` + `VectorIndex`. Cosine threshold retrieval with `candidate_id` filter (per-candidate scoring). Bounds: `theta ∈ [0.10, 0.50]` (default 0.30), `max_chunks_per_query` default 20. | Top-K retrieval (retired). |
| `src/rag/per_req_retrieval.py` | **Production** per-REQ retrieval (DEC-017/018/019). `retrieve_evidence_for_req` takes a REQ's sub-query SET, embeds each, retrieves chunks per sub-query, unions + dedups by `chunk_id` keeping highest cosine, hard-caps at `max_chunks_per_query`. `embed_sub_queries` is the lazy model loader (`_EMBED_MODEL` cached). Supports `sub_query_vectors` for caller-supplied pre-encoded embeddings (cache hook). | `src/services/subquery_retrieval.py::retrieve_chunks_for_requirement` |
| `src/rag/subquery_cache.py` *(planned, Track 7)* | Sub-query embedding cache. In-memory dict + optional on-disk `data/embeddings/subqueries_cache.npz` (+ manifest JSONL). File-hash-aware invalidation. Wraps `embed_sub_queries`; the batch CLI passes a `cached_embedder` closure into `evaluate_candidate_composed`. | — |
| `src/scoring/graded_scorer.py` | **Code-only scorer.** Legacy `evaluate_candidate` (with `scale_factor` + `DEFAULT_EXPECTED_YEARS=10`) kept as backward-compat shim. Production path uses `evaluate_candidate_code_only_v2` (Track 2-S, no scale_factor, missing years = block). `extract_expected_years` — regex for 4 patterns of `expected_years` from free text. `_aliases_for` with `\b...\b` word boundaries. | `evaluate_candidate` (legacy). |
| `src/scoring/unified_scorer.py` | **Composition scorer** + legacy unification. Production: `evaluate_candidate_composed` (Track 2-S) computes per-REQ `Sub-Score = Code_only_part × Rubric_LLM_part`, `Contribution = weight% × Sub-Score`, `Total = Σ Contribution`. Helpers: `_is_binary_subquery`, `_is_years_subquery`, `_is_rubric_subquery`, `_score_presence_sq`, `_score_years_sq`, `_build_section_evidence`, `_token_boundary_match` (Track 5 false-positive fix). `evaluate_candidate_unified` is the legacy path. | `evaluate_candidate_unified` (legacy). |
| `src/scoring/rubric_scorer.py` | Rubric-bound LLM evidence scorer. `score_requirement_with_rubric` returns `CachedScoringTrace`; the composed scorer uses `trace.normalized_score` as the `Rubric_LLM_part`. | — |
| `src/scoring/rubrics.py` | Anchored rubric definitions per dimension (skill, experience, education, certification, project, etc.). `is_code_only`, `get_rubric`. | — |
| `src/scoring/tier_lookup.py` | Institute + certification tier lookup tables from `data/Institutes/` + `data/Certificates/`. `get_institute_tier_points`, `get_certificate_tier_points`, `is_institute_flagged`. Unlisted entries get 0.50 (Tier 3 equivalent). | — |
| `src/audit/no_evidence_flags.py` | Append-only JSONL writer for zero-evidence flags per `(candidate, REQ)` pair. Schema: timestamp ISO 8601 UTC, candidate_id, role, req_id, requirement_name, sub_query_keys, sub_query_count, theta, chunker. | — |
| `src/reporting/chunk_report.py` | Chunk-corpus diagnostic reporter. Each Recursive experiment writes `reports/chunk_reports/recursive_chunking_<params>_report.{json,md}`. | — |
| `src/models/database.py` | SQLite persistence for weight configs (`weight_configurations` + `weight_items` tables). | — |

### Data artifacts (`data/`)

| Path | What it is | Producer | Status |
|---|---|---|---|
| `data/original/<role>/<hash>.pdf` (.txt) | Raw uploaded resumes (PDF or text) | Recruiter upload | Active; gitignored |
| `data/processed/<role>/<hash>.json` | Parsed profile (`raw_text`, `sections`, `experience`, `education`, etc.) — feeds the chunker | `src/resume_parsing/parser.py` | Active; gitignored |
| `data/processed/<role>/<hash>_structured_profile.json` | Reduced deterministic record (`degrees`, `certifications`, `total_experience_years`, `employment_history`) — feeds the code-only scorer | `src/resume_parsing/structured_profile.py` | Active; gitignored |
| `data/processed/<role>/<hash>_intelligence_report.json` | Legacy Stage-3 evaluation (candidate intelligence report; objective_scores, scoring_summary, evidence_sources) — feeds recruiter UI | Legacy `evaluate_role` pipeline | Legacy; superseded by composed scorer output (Track 2-S); gitignored |
| `data/candidate_registry.json` | DEC-025 candidate id registry — maps `<Role>_CAND_<NNNN>` ⟷ `legacy_hash_id` ⟷ `source_path`. 721 entries. | `src/resume_parsing/candidate_registry.py` | Active; **committed to git** (source of truth for downstream joins) |
| `data/job_descriptions/<role>/<role>_SubQuery.md` | Canonical SubQuery source — REQs + sub-query table per role, parsed by `subquery_parser.py`. **Do not editorialize** (AGENTS.md rule). | Authoritative input | Active; committed to git |
| `data/job_descriptions/<role>/<role>_WeightConfig_<name>.json` | Recruiter weight config schema (`requirements_weights` flat list, `weight_percentage` sums to 100, no `expected_years`). | FastAPI + HTMX UI | Active; committed to git |
| `data/embeddings/recursive_chunking/chunks.jsonl` | 6,670 RecursiveChunks (6,670 × 384-dim MiniLM-L6-v2 chunks) over 721 resumes — written by `build_index.py`. Schema: `chunk_id`, `candidate_id`, `role_bucket`, `source_file`, `section`, `chunk_index`, `text`, `metadata`. | `src/rag/build_index.py` | Active; gitignored. Per-DEC-023 futurelabs when M0.5e ships, this moves to per-experiment folder `data/recursive_chunking_<params>/chunks.jsonl`. |
| `data/embeddings/recursive_chunking/index.npz` | 6,670 × 384-dim MiniLM-L6-v2 embedding matrix (L2-normalized). Loaded at runtime by `VectorIndex`. | `src/rag/build_index.py` | Active; gitignored. |
| `data/embeddings/subqueries_cache.npz` *(planned, Track 7)* | Encoded sub-queries cache — keyed by `(model_name, sha256(sq_text))`. Manifest maps cache_key → `(role, req_id, sq_key, sq_text, subquery_file_hash)`. | `src/rag/subquery_cache.py` | Planned |
| `data/embeddings/document_aware_backup/` | Prior Document-Aware index (6,377 chunks) — backed up pre-rebuild (M0.5a Step 1.4). | M0.5a migration | Read-only; gitignored |
| `data/document_aware_chunking/<role>/<candidate_id>.jsonl` | Legacy Document-Aware chunks. 730 files. Read-only post-M0.5e-a. | `src/rag/document_aware_chunker.py` | Legacy; gitignored (except `MIGRATION_NOTES.md`) |
| `data/Institutes/institute_tiers.json` | Recruiter-editable institute tier database. | Recruiter | Active; **committed to git** |
| `data/Certificates/certificate_tiers.json` | Recruiter-editable certification tier database. | Recruiter | Active; **committed to git** |
| `data/audit/no_evidence_flags.jsonl` | Zero-evidence audit log — one line per `(candidate, REQ)` pair with no retrieved chunks. | `src/audit/no_evidence_flags.py::write_flag` | Active; gitignored |
| `data/eval/v1.jsonl` | Retrieval/RAG eval set (≥50 triples, ≥3 roles) — M0.5b. Gates M0.5d Optuna. | Manual | Pending |
| `data/eval/counterfactual_v1.jsonl` | Counterfactual ranking suite (≥50 tests, ≥4 categories) — hard promotion gate ≥ 0.95. | Manual | Pending |
| `data/eval/ranking_v1.jsonl` | Synthetic labeled ranking set (30–50 pairs, 2–3 recruiters, inter-rater agreement ≥ 0.60) — NDCG@10 ≥ 0.80 gate. | Manual | Pending |
| `data/mlflow/mlflow.db` + `data/mlflow/artifacts/` | MLflow tracking (SQLite backend + artifact root). Per DEC-020. | MLflow | Active; gitignored |
| `data/optuna/studies.db` | Optuna study store. SQLite. | Optuna | Active; gitignored |

### Outputs (`reports/`)

| Path | What it is | Producer |
|---|---|---|
| `reports/chunk_reports/document_aware_chunking_report.{json,md}` | Historical Document-Aware diagnostic (49% missing-`section_type` finding, DEC-015). | `src/reporting/chunk_report.py` |
| `reports/chunk_reports/recursive_chunking_<params>_report.{json,md}` | Per-experiment Recursive diagnostic. One pair per experiment. | `src/reporting/chunk_report.py` |
| `reports/diff_rankings/<baseline>__vs__<current>__<role>.{json,md}` | Ranking diff between two configs (DEC-026). Includes Optuna rank-stability metrics (Track 7 addition). | Planned: `src/reporting/rank_stability.py` |
| `reports/audit/no_evidence_flags.jsonl` | Same as `data/audit/no_evidence_flags.jsonl` (mirror; canonical lives in `data/`). | `src/audit/no_evidence_flags.py` |

### Documentation (`docs/`)

| Document | What it is | Source of truth for |
|---|---|---|
| `WORKING_LOGIC.md` | Canonical scoring / evaluation / ranking contract (DEC-011). | "What the system should do" w.r.t. scoring and evaluation. All other docs defer to this. |
| `CURRENT_PROGRESS.md` | Status snapshot mapping every `WORKING_LOGIC.md` step to ✅ / 🟡 / ⬜ + the next unit of work. | "What the system does today vs planned." |
| `PROJECT_OVERVIEW.md` | Product vision, problem statement, business objectives, end-to-end workflow, differentiators, features. | "Why the system exists and what it does at a high level." |
| `SYSTEM_ARCHITECTURE.md` | High-level architecture, system components, service interactions, storage, deployment. **This file.** | "How the system is constructed" (non-AI). |
| `AI_ARCHITECTURE.md` | All AI workflows: resume ingestion, parsing, JD processing, weight config, evaluation, ranking, comparison, summarization, chunking, embedding, retrieval, RAG, hiring recommendation. | "How the AI is architected." |
| `AI_DESIGN_RATIONALE.md` | Every AI design decision (chunking, embedding, vector DB, LLM, scoring strategy) with alternatives considered, tradeoffs, rationale, upgrade path. | "Why these AI choices." |
| `MODEL_REGISTRY.md` | Production AI models + the per-experiment storage layout. | "Which model + which data artifacts live where." |
| `PROMPT_LIBRARY.md` | All production prompts with ID, purpose, inputs, outputs, constraints, version history. | "What prompts are live and how they've changed." |
| `EVALUATION.md` | Evaluation methodology + datasets + metrics. Includes the Optuna rank-stability spec (Track 7). | "How we measure correctness." |
| `RECRUITER_WORKFLOWS.md` | The 10 recruiter-facing workflows. | "How recruiters interact." |
| `IMPLEMENTATION_ROADMAP.md` | Phases, milestones, delivery sequence, prioritization. | "What's being built and when." |
| `RELEASE_NOTES.md` | Feature additions / bug fixes / breaking changes / version history (newest at top within "Unreleased"). | "What changed in each release." |
| `DECISIONS.md` | All architecture / design / AI / ops decisions (DEC-001 through DEC-030+). | "Why each non-obvious choice was made." |
| `ARCHITECTURE_CHANGELOG.md` | Reverse-chronological architecture change log. Each entry cross-references a DEC. | "How the architecture has evolved." |
| `TROUBLESHOOTING.md` | Debugging findings (problem → symptoms → root cause → investigation → solution → prevention). | Reusable debugging patterns. |
| `ENVIRONMENT_NOTES.md` | Environment + setup findings (Python packages, PDF back-ends, IDE issues, build failures, runtime config). | How to set up + common env issues. |
| `STYLE_GUIDE.md` | Code structure / performance / Python + Pandas / refactoring / senior engineering standards. | Code conventions. |

### Project entry-point CLIs

| Command | What it does |
|---|---|
| `python -m src.rag.build_index` | Rebuild the embedding index from `data/processed/<role>/*.json` corpus. |
| `python -m src.scoring.batch_score` *(legacy)* | Batch scoring CLI (uses `graded_scorer.evaluate_role`). Will be replaced by `scripts/score_batch_composed.py` (Track 7). |
| `scripts/score_batch_composed.py` *(planned, Track 7)* | Production batch scoring CLI using `evaluate_candidate_composed` with `subquery_cache.py` injected as `sq_embedder`. |
| `scripts/evaluate_one.py` | Score a single candidate against a role's weight config — interactive / debugging. |
| `scripts/compare_two.py` | Side-by-side candidate comparison via LLM narration (RAG-grounded). |

---

## High-Level Architecture

HireIntel AI follows a modular, service-oriented architecture designed to support scalability, maintainability, and clear separation of concerns. The system is composed of several independent services that communicate via well-defined APIs.

```text
┌─────────────────────────────────────────────────────────────────┐
│                        HireIntel AI Platform                     │
├─────────────────────────────┬─────────────────────────────────────┤
│       User Interface        │         API Gateway / BFF           │
│        (Streamlit)          │            (FastAPI)                │
├─────────────────────────────┴─────────────────────────────────────┤
│                         Core Services                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────┐ │
│  │   Job       │  │  Resume     │  │  Candidate  │  │  Report  │ │
│  │   Service   │  │  Service    │  │  Service    │  │  Service │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └──────────┘ │
├─────────────────────────────────────────────────────────────────┤
│                       AI/ML Layer                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────┐ │
│  │   Parser    │  │  Embedding  │  │  Scoring    │  │   RAG    │ │
│  │   Engine    │  │  Service    │  │  Engine     │  │  Engine  │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └──────────┘ │
├─────────────────────────────────────────────────────────────────┤
│                    Infrastructure Layer                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────┐ │
│  │   Vector    │  │  Object     │  │  Document   │  │  Message │ │
│  │   Database  │  │  Storage    │  │  Database   │  │  Queue   │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └──────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

---

## Major System Components

### 1. User Interface (UI)
- **Technology:** Streamlit
- **Purpose:** Provides an intuitive web interface for recruiters to upload job descriptions, clarify ambiguous requirements, configure weights (with `expected_years` per item), upload resumes, view rankings, and interact with candidates.

### 2. API Gateway / Backend for Frontend (BFF)
- **Technology:** FastAPI
- **Purpose:** Acts as the central entry point for all client requests. Handles authentication, request routing, rate limiting, and response aggregation.

### 3. Core Services

#### Job Service
- Manages job description lifecycle (upload, storage, requirement extraction).
- Runs the **JD clarification loop** (Green / Yellow / Red classification) per `WORKING_LOGIC.md` Step 0 — refuses to lock the scoring policy until all items are Green.
- Interfaces with the Parser Engine for JD processing.
- Persists structured job requirements and the `clarifications.json` artifact.

#### Resume Service
- Manages resume upload, storage, parsing, and cleaning (headers / footers / template noise).
- Coordinates with the Parser Engine for structured profile extraction.
- Handles document chunking and embedding pipeline.

#### Candidate Service
- Orchestrates candidate evaluation and ranking using the **single canonical deterministic scorer** (`src/scoring/graded_scorer.py`).
- Manages scoring policy application (weights + expected_years).
- Provides candidate comparison and summary generation.
- Produces the **Candidate Intelligence Report** aggregating per-item evidence.

#### Report Service
- Generates evaluation reports, comparison matrices, and hiring recommendations.
- Formats data for recruiter-friendly presentation.

### 4. AI/ML Layer

#### Parser Engine
- Extracts structured information from unstructured documents (resumes, job descriptions).
- Uses a combination of NLP techniques and LLM-based information extraction.
- Output: structured profile JSON in `data/processed/<role>/<id>.json`.

#### Embedding Service
- Generates vector embeddings for resume sections and chunks.
- Active model: `sentence-transformers/all-MiniLM-L6-v2` (384-dim, CPU-runnable).

#### Scoring Engine
- Two-mode scoring engine per `WORKING_LOGIC.md` "Fundamental Rule":
  - **Code-only mode** (`src/scoring/graded_scorer.py` + `src/scoring/unified_scorer.py`): synonym match, regex years detection, institute/cert tier lookup. No LLM. `min(importance, candidate_years / expected_years × importance)` with partial credit.
  - **Rubric-bound LLM mode** (`src/scoring/rubric_scorer.py` + `src/scoring/rubrics.py`): LLM scores against anchored rubric scales (0.0/0.25/0.5/0.75/1.0). LLM never sees weight, never computes aggregation. `CachedScoringTrace` frozen at scoring time.
- Total normalized to 0–100 via `scale_factor = 100 / max_score`.
- Produces explainable, reproducible scores with per-item evidence (section, snippet, cited text, anchor description, scoring trace).
- Institute and certificate tier databases (`data/Institutes/`, `data/Certificates/`) are recruiter-editable JSON files consumed by `src/scoring/tier_lookup.py`.

#### RAG Engine
- Retrieves relevant resume chunks based on recruiter queries (dense cosine over in-memory index).
- Generates grounded, context-aware responses via OpenRouter LLM with strict-grounding prompt.
- **RAG never participates in scoring** — it only explains scores that the deterministic engine produced.

### 5. Infrastructure Layer

#### Vector Database
- Stores and indexes resume embeddings for semantic search
- Enables efficient similarity search and retrieval

#### Object Storage
- Stores original resume files (PDF, DOCX, etc.)
- Provides durable, scalable file storage

#### Document Database
- Stores structured candidate profiles, job descriptions, scoring policies, and evaluation results

#### Message Queue
- Handles asynchronous task processing (parsing, embedding, scoring)
- Decouples services for improved resilience and scalability

---

## Service Interactions

### Synchronous Interactions
- **UI <-> API Gateway:** HTTP/REST for real-time user actions (upload, query, display)
- **API Gateway <-> Core Services:** Internal REST/gRPC for service orchestration
- **Core Services <-> AI/ML Layer:** Synchronous calls for immediate results (parsing, scoring)

### Asynchronous Interactions
- **Resume Upload:** Triggers async parsing and embedding pipeline via message queue
- **Evaluation:** Async scoring and report generation to handle large candidate lists
- **Notifications:** Async email or system notifications upon job completion

---

## API Architecture

### API Style
- **RESTful HTTP APIs** for client-facing and internal service communication
- **OpenAPI (Swagger)** for API documentation and client generation
- **Versioned endpoints** (e.g., `/api/v1/jobs`, `/api/v1/resumes`)

### Key API Groups
1. **Job Management:** `POST /api/v1/jobs`, `GET /api/v1/jobs/{id}`, `DELETE /api/v1/jobs/{id}`
2. **Resume Management:** `POST /api/v1/resumes`, `GET /api/v1/resumes/{id}`, `GET /api/v1/resumes/{id}/parsed`
3. **Candidate Evaluation:** `POST /api/v1/evaluations`, `GET /api/v1/evaluations/{job_id}`, `GET /api/v1/evaluations/{job_id}/rankings`
4. **Comparison & Chat:** `POST /api/v1/compare`, `POST /api/v1/chat`

---

## Runtime Architecture

### Deployment Model
- **Containerized services** using Docker
- **Orchestrated** via Docker Compose (local) or Kubernetes (production)
- **Scalable** — individual services can be scaled horizontally based on demand

### Request Flow
1. Recruiter uploads a job description via the UI.
2. API Gateway forwards the request to the Job Service.
3. Job Service persists the JD, runs the **clarification loop** (Green / Yellow / Red), and surfaces unresolved items to the recruiter.
4. Parser Engine extracts structured requirements and stores them.
5. Recruiter configures **weights + expected_years per item**, which are persisted as a scoring policy. The policy is locked only when all items are Green.
6. Resumes are uploaded, triggering async parsing, cleaning, and embedding.
7. **Single deterministic Scoring Engine** evaluates every candidate against the policy; output is `data/scores/graded/<role>_ranked.json`.
8. Results are stored and made available via the Candidate Service.
9. RAG Engine handles free-form recruiter questions (resume chat, comparison narratives) using retrieved chunks + LLM with strict-grounding prompt. **RAG never overrides the deterministic ranking.**

---

## Data Flow Architecture

### Ingestion Flow
```text
[Job Description / Resume] -> [API Gateway] -> [Core Service] -> [Object Storage]
                                                     |
                                                     v
                                              [Parser Engine]
                                                     |
                                                     v
                                              [Document Database]
```

### Evaluation Flow
```text
[Scoring Policy] + [Structured Profiles] -> [Scoring Engine] -> [Evaluation Results]
                                                                   |
                                                                   v
                                                           [Document Database]
```

### RAG Flow
```text
[Recruiter Query] -> [RAG Engine] -> [Vector Database] -> [Retrieved Chunks] -> [LLM] -> [Grounded Response]
```

---

## Storage Architecture

### Object Storage
- **Purpose:** Stores raw uploaded files (PDFs, DOCXs)
- **Structure:** Hierarchical by tenant/job/candidate identifiers
- **Retention:** Configurable based on business and compliance requirements

### Document Database
- **Purpose:** Stores structured data — candidate profiles, job descriptions, scoring policies, evaluation results
- **Schema:** Flexible to accommodate evolving AI-extracted fields
- **Access Patterns:** Indexed by job_id, candidate_id, and evaluation_id

### Vector Database
- **Purpose:** Stores embeddings for semantic search and retrieval
- **Indexing:** Optimized for cosine similarity and nearest-neighbor search
- **Updates:** Incremental — new resumes trigger embedding and index updates

---

## Deployment Architecture

### Local Development
- Docker Compose for all services
- Local instances of object storage (MinIO), document database, and vector database

### Production
- **Container Orchestration:** Kubernetes (EKS/AKS/GKE or on-premise)
- **Load Balancer:** External and internal load balancers for traffic distribution
- **Auto-scaling:** Horizontal Pod Autoscaler (HPA) for core and AI services
- **Monitoring:** Prometheus + Grafana for metrics; ELK stack for logs
- **Security:** TLS termination, network policies, secret management (e.g., Kubernetes Secrets, Vault)
