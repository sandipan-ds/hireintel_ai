# Decisions

## Overview

This document records significant product, architecture, AI, data, and implementation decisions.

Every major architecture or AI change must be documented here before implementation, then reflected in the affected source-of-truth documents.

---

## Decision Log

| ID | Date | Decision | Status | Related Docs |
| --- | --- | --- | --- | --- |
| DEC-001 | 2026-06-19 | Use documentation-first development with `docs/` as source of truth. | Accepted | `AGENTS.md`, `PROJECT_OVERVIEW.md` |
| DEC-002 | 2026-06-19 | Use deterministic scoring for final candidate scores and rankings. | Accepted | `AI_ARCHITECTURE.md`, `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md` |
| DEC-003 | 2026-06-19 | Use document-aware chunking as the primary resume chunking strategy. | Accepted | `AI_ARCHITECTURE.md`, `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md` |
| DEC-004 | 2026-06-19 | Use Qdrant as the proposed vector database. | Superseded | `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md` |
| DEC-005 | 2026-06-19 | Use BGE-M3 as the proposed primary embedding model. | Superseded | `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md` |
| DEC-006 | 2026-06-19 | Use an in-memory numpy vector index until scale demands a hosted vector DB. | Accepted | `MODEL_REGISTRY.md`, `AI_ARCHITECTURE.md` |
| DEC-007 | 2026-06-19 | Use `sentence-transformers/all-MiniLM-L6-v2` as the active embedding model (CPU-runnable, no API key, PII-safe). | Accepted | `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md` |
| DEC-008 | 2026-06-19 | Ship three independent scoring strategies (keyword, semantic, hybrid) runnable side by side; default production strategy is hybrid with `α = 0.5`. | Superseded | `AI_ARCHITECTURE.md`, `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md` |
| DEC-009 | 2026-06-19 | Use `pypdfium2` (no Poppler required) as the primary OCR fallback renderer for image-only PDFs. | Accepted | `AI_ARCHITECTURE.md`, `MODEL_REGISTRY.md` |
| DEC-010 | 2026-06-19 | Ship a **single canonical deterministic scorer** (`src/scoring/graded_scorer.py`) in two modes (code-only + rubric-bound LLM evidence scoring); retire the keyword / semantic / hybrid triad. Code-only: per-item `min(importance, candidate_years / expected_years × importance)` with partial credit. Rubric-bound LLM: scores against recruiter-defined rubric, weight application in code. | Accepted | `WORKING_LOGIC.md`, `AI_DESIGN_RATIONALE.md`, `AI_ARCHITECTURE.md`, `MODEL_REGISTRY.md` |
| DEC-011 | 2026-06-19 | Make `WORKING_LOGIC.md` the canonical scoring/evaluation spec; all other docs defer to it for scoring details. | Accepted | `WORKING_LOGIC.md`, `CURRENT_PROGRESS.md`, all docs |
| DEC-012 | 2026-06-30 | Use Section-Routed Evidence Retrieval (exact label match on canonical sections) for per-candidate scoring, replacing cosine similarity. Dense cosine remains only for cross-candidate pool search and resume chat. | Superseded by DEC-015, then DEC-017 | `AI_ARCHITECTURE.md`, `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md`, `WORKING_LOGIC.md` |
| DEC-013 | 2026-06-30 | Ship recruiter-editable tier databases for institutes and certifications. 3 tiers (1.0/0.75/0.50) + not-listed default 0.50. Code-only lookup, no LLM, no web search at scoring time. | Accepted | `WORKING_LOGIC.md`, `MODEL_REGISTRY.md`, `AI_ARCHITECTURE.md` |
| DEC-014 | 2026-07-01 | Role-specific documentation template and SubQuery audit. Each role folder contains 8 files (JD, SubQuery, ScoringGuide, WeightConfig, JSON example, QUICK_START, README_SETUP, recruiter_weight_input.py). SubQuery files audited for complete JD requirement coverage. | Accepted | `AGENTS.md`, `CURRENT_PROGRESS.md`, all role folders |
| DEC-015 | 2026-07-04 | Use Sub-Query Similarity Retrieval as the primary retrieval strategy for per-candidate scoring. Each JD requirement is decomposed into 2-4 sub-questions per its rubric; each sub-query is embedded and matched against the candidate's chunks via cosine (default threshold 0.0, LLM does final filtering). The LLM outputs anchored floats for each sub-question; sub-score is the product. Section-Routed is now a metadata pre-filter, not the routing mechanism. Supersedes DEC-012 because empirical data showed 49% of chunks in our 721-resume corpus had `section_type=""` and were invisible to the label-based routing. | Superseded by DEC-017 | `WORKING_LOGIC.md`, `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md` |
| DEC-016 | 2026-07-04 | Cache LLM sub-scores at `(candidate_id, req_id, sorted-chunk-ids, model-name)` for deterministic and fast re-runs. Cache invalidates on chunk change or model upgrade. Rubric determinism (anchored floats, fixed sub-questions) plus the cache means the system is reliable on re-runs even though the underlying LLM is not bit-deterministic. | Accepted (retained under DEC-017 with revised cache key) | `WORKING_LOGIC.md`, `AI_DESIGN_RATIONALE.md` |
| DEC-017 | 2026-07-05 | **Regular RAG pivot for retrieval.** Replace the per-candidate sub-query similarity + section-routed hybrid with a single regular RAG pipeline: Recursive Chunking + dense cosine retrieval against a per-candidate chunk index + threshold-based retrieval (return all chunks with cosine ≥ θ, capped at `max_chunks_per_query` for safety). The deterministic scoring engine (`src/scoring/graded_scorer.py` + `src/scoring/unified_scorer.py`) is **unchanged** and remains the only ranking signal. The LLM is restricted to evidence extraction / rubric-bound scoring and answer generation, never to the final score or ranking. The threshold replaces the previous "threshold 0.0, LLM filters" design and is itself an Optuna-tuned hyperparameter. Supersedes DEC-015 (and transitively DEC-012). | Accepted | `WORKING_LOGIC.md`, `AI_ARCHITECTURE.md`, `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md`, `EVALUATION.md`, `PROJECT_OVERVIEW.md`, `IMPLEMENTATION_ROADMAP.md`, `CURRENT_PROGRESS.md` |
| DEC-018 | 2026-07-05 | **Threshold-based retrieval (regular RAG variant).** For every recruiter query (sub-question, chat question, or JD bullet), retrieve **all** chunks whose cosine similarity is ≥ `θ` (default `θ = 0.70`, configurable per call), with a hard `max_chunks_per_query` cap (default `20`) to bound context size. The set of returned chunks is dynamic — it is not a fixed top-K. A safety warning is logged when the cap is hit. `θ` is exposed as an Optuna hyperparameter (DEC-021) so the threshold itself is calibrated, not hand-picked. | Accepted | `WORKING_LOGIC.md`, `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md` |
| DEC-019 | 2026-07-05 | **Recursive Chunking replaces Document-Aware Chunking as the active chunking strategy.** Use `RecursiveCharacterTextSplitter` (or equivalent) with `chunk_size = 500` and `chunk_overlap = 50` as defaults, both exposed as Optuna hyperparameters. Reasoning: regular RAG needs uniform-sized chunks for fair cosine comparison; Document-Aware chunking is over-specialized for the retired section-routed path. Header Normalization (DEC-013's synonym table) is **retained** for parse-time section labeling and is still useful for the structured profile and the tier lookup, even though it is no longer the retrieval routing mechanism. | Accepted (supersedes prior Document-Aware as the active strategy; old chunker retained as `DocumentAwareChunker` for one release for data migration) | `AI_ARCHITECTURE.md`, `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md` |
| DEC-020 | 2026-07-05 | **MLflow for experiment tracking.** Every retrieval / chunking / embedding / scoring run is logged to a local MLflow server (`mlflow server --host 127.0.0.1 --port 5000`). Per run: `log_params` for `chunk_size`, `chunk_overlap`, `embedding_model`, `vector_store`, `similarity`, `retrieval_mode` (threshold/top_k), `threshold`, `top_k`, `llm`; `log_metrics` for retrieval metrics (Recall@θ, Precision@θ, MRR, nDCG, avg_chunks_returned, p95_chunks_returned), generation metrics (faithfulness, groundedness, answer_relevancy, hallucination_rate), ranking metrics (top-k accuracy, recruiter_agreement); `log_artifact` for the retrieved-chunks JSON; `set_tag` for `experiment_set` (e.g. `chunking_v1`). Tracking URI: `http://127.0.0.1:5000`. Backend store: local SQLite (`data/mlflow/mlflow.db`). Artifact root: `data/mlflow/artifacts/`. | Accepted | `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md`, `EVALUATION.md` |
| DEC-021 | 2026-07-05 | **Optuna for hyperparameter search.** Drive the search for `chunk_size`, `chunk_overlap`, `threshold θ`, and `top_k` using Optuna with a TPE sampler and SQLite-backed studies at `data/optuna/studies.db`. Default to **multi-objective** optimization: `maximize faithfulness` and `minimize avg_chunks_returned` simultaneously, producing a Pareto front so the operator can pick a `θ` that meets the faithfulness bar without paying a large context-size tax. Optuna logs every trial to MLflow via `optuna.integration.MLflowCallback` (DEC-020). Naming convention: `<experiment_set>_<yyyymmdd>` (e.g. `chunking_v1_20260705`). The final shipped config is the Optuna-recommended point, not a hand-picked value, and is recorded in `MODEL_REGISTRY.md`. | Accepted | `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md`, `EVALUATION.md`, `IMPLEMENTATION_ROADMAP.md` |
| DEC-022 | 2026-07-05 | **Per-resume reasoning storage + legacy chunk migration.** (a) Move the existing Document-Aware chunk files from `data/chunks/<role>/<candidate_id>.jsonl` to `data/chunks_legacy_document_aware/<role>/<candidate_id>.jsonl` so it is unambiguous which chunker produced them. Do not delete — preserve as historical reference. (b) Replace the single `data/embeddings/llm_cache.jsonl` with a per-resume artifact tree at `data/per_candidate/<role>/<candidate_id>/reasoning/<req_id>__<query_hash>.json` that stores, for every (candidate, req, query) triple, the full LLM output: the LLM's narrative **reasoning**, the **basis** (which chunks it cited and which excerpts it pulled), the **retrieved chunks** (the full list of chunks the LLM considered), and the **sub-scores** (the anchored floats that drive the deterministic engine). Cache key: `(candidate_id, req_id, hash(query, sorted(top-chunk-ids)), model_name, θ)`. Invalidates on chunk-set change, model upgrade, or θ change. Storage cost is accepted; LLM-call cost and re-run determinism are the win. | Accepted (refined by DEC-023) | `WORKING_LOGIC.md`, `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md`, `EVALUATION.md`, `IMPLEMENTATION_ROADMAP.md`, `CURRENT_PROGRESS.md` |
| DEC-023 | 2026-07-05 | **Per-experiment folder naming for the Recursive chunking pipeline + folder renames.** (a) Rename the legacy Document-Aware folder from `data/chunks_legacy_document_aware/` to `data/document_aware_chunking/` (DEC-022a refinement — the user requested the explicit `document_aware_chunking` name for clarity). (b) Adopt the convention that every MLflow experiment's artifacts (chunks, embedding index, per-resume reasoning tree, `metadata.json`) live in a per-experiment folder named after the hyperparameters that produced it. Format: `data/recursive_chunking_<chunk_size>_<overlap>_<top_k>_<threshold×100>/`. Example: an experiment with `chunk_size=500`, `overlap=200`, `top_k=5`, `threshold=0.50` lives in `data/recursive_chunking_500_200_5_50/`. When a hyperparameter is not active in a given retrieval mode (e.g., pure threshold mode has no `top_k` cap), use `x` as the placeholder: `recursive_chunking_500_200_x_70` for threshold-only. The folder name is the self-documenting identifier of the experiment; two MLflow runs with the same config share the same folder. The "Active" config in `MODEL_REGISTRY.md` points to one specific folder. | Accepted (refines DEC-022) | `WORKING_LOGIC.md`, `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md`, `IMPLEMENTATION_ROADMAP.md`, `CURRENT_PROGRESS.md` |
| DEC-024 | 2026-07-05 | **Chunk reports folder + ranking evaluation methodology without labeled data.** (a) Adopt `reports/chunk_reports/` as the canonical location for per-experiment chunk diagnostics. Report file names mirror the experiment folder names: `document_aware_chunking_report.{json,md}` and `recursive_chunking_<chunk_size>_<overlap>_<top_k>_<threshold×100>_report.{json,md}`. Each report captures chunk counts, chunk-size distribution, the `section_type=""` rate (the DEC-015 bug), retrieval hit rates, LLM call counts, and the eval metrics. Reports are committed to git (small text files) so the historical record of every experiment is preserved. (b) Adopt a multi-pronged ranking evaluation methodology: (i) **counterfactual tests** (synthetic, deterministic, 100% ground truth) — construct test cases where the expected ranking change is unambiguous and verify the system obeys; (ii) **synthetic labeled set** — hand-rank 30–50 (candidate, role) pairs across multiple recruiters, measure inter-rater agreement, use the majority/median ranking as ground truth; (iii) **stability tests** — re-run the same config twice, verify byte-identical ranking (already covered by DEC-022 determinism but worth measuring explicitly); (iv) **recruiter agreement** (when applicable) — Cohen's kappa or Krippendorff's alpha against human raters; (v) **behavioral signals** (production only) — did the recruiter interview the top-K? tracked, not enforced. | Accepted | `WORKING_LOGIC.md`, `MODEL_REGISTRY.md`, `EVALUATION.md`, `IMPLEMENTATION_ROADMAP.md`, `CURRENT_PROGRESS.md` |
| DEC-025 | 2026-07-05 | **Candidate ID nomenclature: `<Role>_CAND_<NNNN>`.** Replace the SHA1-hash-based candidate id (`cand_<12hex>`, e.g. `cand_74cbbc14c744141a`) with a human-readable, role-encoded, sequential id (`BusinessAnalyst_CAND_0001`). The id is allocated and persisted by a new ``data/candidate_registry.json`` so numbers are monotonic per role and never renumber on re-parse. The registry also stores the legacy hash id and the absolute source path for traceability and backwards compatibility with the 6,377 existing Document-Aware chunks. New candidates get the next free number for their role; existing candidates are backfilled once from the corpus. The chunk_id format (`{candidate_id}__{chunk_index}`) is unchanged in shape but switches to the new id space. | Accepted | `WORKING_LOGIC.md`, `MODEL_REGISTRY.md`, `EVALUATION.md`, `IMPLEMENTATION_ROADMAP.md`, `CURRENT_PROGRESS.md` |
| DEC-026 | 2026-07-05 | **Ranking diff methodology (before NDCG@k / MAP@k).** Adopt a per-experiment ranking-diff workflow as the first line of regression detection, before any aggregate metric. The diff tool (``src.eval.ranking_diff`` + ``scripts/diff_rankings.py``) compares two rankings of the same role and reports: (1) new entrants to top-K for K=10 and K=50; (2) departures from top-K; (3) per-candidate rank deltas (signed, normalized by the total number of candidates in the role) with average and max; (4) a categorization into ``stable``, ``big_swap_up``, ``big_swap_down``, ``only_in_baseline``, ``only_in_current`` (where "big" is > 10% of the role's total candidates); (5) for each notable case, a side-by-side dump of the rubric-bound LLM's reasoning, the cited basis chunks, the retrieved-chunk list with cosine scores, and the model + retrieval parameters — all read from each experiment's per-resume reasoning tree (DEC-022) so the comparison is fully versioned. Outputs ``reports/diff_rankings/<baseline>__vs__<current>__<role>.{json,md}`` committed to git. This precedes aggregate metrics (NDCG@k, MAP@k) so regressions are diagnosed at the candidate level, not just measured. | Accepted | `EVALUATION.md`, `MODEL_REGISTRY.md`, `IMPLEMENTATION_ROADMAP.md`, `CURRENT_PROGRESS.md` |

---

## Decision Template

```text
## DEC-XXX: Title

Date:
Status:

Context:

Decision:

Alternatives Considered:

Consequences:

Related Documents:
```

---

## DEC-006: In-memory numpy vector index (defer Qdrant)

**Date:** 2026-06-19
**Status:** Accepted

**Context:** We needed a vector store for ~4k chunks to enable retrieval for both JD matching and semantic scoring. `Qdrant` was previously proposed but introduces a separate service to deploy, monitor, and secure.

**Decision:** Persist chunk vectors to `data/embeddings/index.npz` (compressed numpy). Load on first retrieval. Keep Qdrant as the planned upgrade when scale exceeds single-machine memory or we need hosted multi-user concurrency.

**Alternatives Considered:**
- **Qdrant:** Best long-term option, but operational overhead before we have users.
- **ChromaDB:** Lighter than Qdrant but still a service.
- **FAISS:** Fast but poor metadata filtering.

**Consequences:**
- Zero infra dependencies to run locally / on a single machine.
- 6 MB on disk for 4k chunks × 384 dims; trivial to load.
- Trivial to swap to Qdrant later — `src/rag/index.py.VectorIndex` is the only abstraction to replace.

**Related Documents:** `MODEL_REGISTRY.md`, `AI_ARCHITECTURE.md`

---

## DEC-007: MiniLM-L6-v2 as primary embedding model (defer BGE-M3)

**Date:** 2026-06-19
**Status:** Accepted

**Context:** BGE-M3 was previously proposed. After scoping the v1 system to English-only JDs and resumes with ~4k chunks, we evaluated latency, cost, and PII constraints.

**Decision:** Use `sentence-transformers/all-MiniLM-L6-v2` (384-dim, ~80 MB, CPU-runnable, no API key) as the active embedding model. Keep BGE-M3 as the planned upgrade path for multilingual candidates.

**Alternatives Considered:**
- **BGE-M3:** Multilingual, larger model.
- **OpenAI `text-embedding-3-small`:** Highest quality, but per-token API cost and PII egress.
- **E5 / Nomic:** Comparable to MiniLM but with weaker English retrieval.

**Consequences:**
- Fully offline, no API key, no candidate data egress — strong PII story.
- One embedding call per (JD bullet × candidate) at scoring time → fast enough for our scale.
- Model swap is isolated to `src/rag/embeddings.DEFAULT_MODEL_NAME`.

**Related Documents:** `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md`

---

## DEC-008: Three scoring strategies (keyword, semantic, hybrid) with `α = 0.5` default

**Date:** 2026-06-19
**Status:** Superseded by DEC-010

**Context:** Keyword-only scoring is fast and auditable but misses synonyms. LLM-direct ranking is prohibited by `AGENTS.md`. We needed a way to add synonym awareness without giving up explainability or reproducibility.

**Decision (original):** Ship three independent scorers, each writing to its own output folder:
- `keyword_scorer.py` — deterministic binary match against recruiter weights.
- `semantic_scorer.py` — JD-bullet cosine vs candidate's chunks (mean × 100).
- `hybrid_scorer.py` — `α × keyword + (1-α) × semantic`, default `α = 0.5`.

**Superseded by DEC-010:** the canonical scorer (`graded_scorer.py`) replaces
the triad. The legacy modules were removed 2026-06-19; the CLI accepts the
legacy strategy names only as deprecated aliases.

**Related Documents:** `AI_ARCHITECTURE.md`, `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md`

---

## DEC-009: pypdfium2 as primary OCR fallback renderer

**Date:** 2026-06-19
**Status:** Accepted

**Context:** Image-only PDFs in `data/original/WebDesigning/` failed to extract text via `pdfplumber`. OCR fallback via `pdf2image` requires Poppler to be installed on the host — fragile for local dev.

**Decision:** Use `pypdfium2` (which bundles PDFium) as the primary PDF→image renderer for the OCR fallback. Keep `pdf2image` as a secondary fallback when `pypdfium2` is unavailable.

**Alternatives Considered:**
- `pdf2image` only (requires Poppler install).
- `PyMuPDF` (mupdf-based; similar trade-offs to pdfium but heavier dependency).

**Consequences:**
- Zero host-system dependencies for OCR fallback in most cases.
- Same `pytesseract` text extraction layer regardless of renderer.
- Documented in `src/resume_parsing/ocr.py`.

**Related Documents:** `AI_ARCHITECTURE.md`, `MODEL_REGISTRY.md`

---

## DEC-010: Single canonical deterministic scorer (`graded_scorer.py`)

**Date:** 2026-06-19
**Status:** Accepted

**Context:** `WORKING_LOGIC.md` is explicit: *"you don't need so many different scoring or ranking systems, just one is enough."* The legacy keyword / semantic / hybrid triad produced three non-comparable numbers and made recruiter interpretation harder, not easier. We also needed years-proportional scoring (a candidate with 1 year of Power BI should not score the same as one with 6 years), which the binary keyword scorer couldn't express.

**Decision:** Ship one deterministic scorer (`src/scoring/graded_scorer.py`) that operates in **two modes** per `WORKING_LOGIC.md` ("Fundamental Rule"):

1. **Code-only scoring** — for fully measurable requirements (total experience, skill presence + years, degree match, certification match, institute/cert tier lookups). Uses synonym dictionary + structured profile search + regex years detection. Per-item raw score = `min(importance, candidate_years / expected_years × importance)`, with `importance × 0.3` partial credit for mention-only matches. No LLM involved.

2. **Rubric-bound LLM evidence scoring** — for requirements requiring judgment (skill depth, relevant/same-role/leadership experience, project complexity, domain expertise). The LLM receives the full content of the mapped section(s) via Section-Routed Evidence Retrieval (exact label match, not similarity-ranked) and scores against a recruiter-defined rubric. The LLM does not see the weight and never computes the final weighted contribution.

In both modes:
- Weight application and final aggregation are computed in code, never by the LLM.
- Total normalized to 0–100 via `scale_factor = 100 / max_score` from the recruiter config.
- Per-item evidence is recorded: matched section, exact snippet, years detected, recruiter-readable reason.
- Rubric sub-scores and cited evidence are cached at scoring time for fast, consistent score explanations.

The legacy `keyword_scorer.py`, `semantic_scorer.py`, `hybrid_scorer.py` modules were removed. The CLI accepts `--strategy keyword|semantic|hybrid` only as a deprecated alias that prints a `DeprecationWarning` and forwards to `graded`.

**Alternatives Considered:**
- Keep the triad (rejected — spec says one scorer is enough).
- LLM-direct ranking (rejected by `AGENTS.md`).
- ML-trained ranker (deferred — see `AI_DESIGN_RATIONALE.md` §5 future upgrade path).
- Code-only scoring for everything (rejected — skill depth, relevant experience, and project complexity require genuine judgment that synonym+regex cannot provide).

**Consequences:**
- One canonical ranking signal per role; cross-role comparisons are direct.
- Per-item evidence is auditable from the candidate's own words.
- Years-proportional scoring rewards demonstrated depth, not just keyword presence.
- Summary-years fallback only applies to experience-style items, so credentials (BE/BTech, CBAP) aren't contaminated by total tenure.
- Rubric-bound LLM mode ensures judgment-based scoring is anchored to recruiter-defined rubrics, not LLM opinions.

**Related Documents:** `WORKING_LOGIC.md`, `AI_DESIGN_RATIONALE.md`, `AI_ARCHITECTURE.md`, `MODEL_REGISTRY.md`, `ARCHITECTURE_CHANGELOG.md`

---

## DEC-011: `WORKING_LOGIC.md` is the canonical scoring/evaluation spec

**Date:** 2026-06-19
**Status:** Accepted

**Context:** `PROJECT_OVERVIEW.md` and `WORKING_LOGIC.md` both describe scoring, but they drifted apart — `PROJECT_OVERVIEW.md` still referenced the legacy triad while `WORKING_LOGIC.md` was the source of truth for the single-scorer design. Recruiters and contributors reading the docs got conflicting answers.

**Decision:** `WORKING_LOGIC.md` is the canonical spec for scoring, evaluation, and ranking. All other docs (`PROJECT_OVERVIEW.md`, `SYSTEM_ARCHITECTURE.md`, `AI_ARCHITECTURE.md`, `RECRUITER_WORKFLOWS.md`, `EVALUATION.md`, etc.) defer to it for scoring details and link to it at the top. `CURRENT_PROGRESS.md` is the status snapshot ("what's done vs planned") mapped to every step of `WORKING_LOGIC.md`.

**Alternatives Considered:**
- Promote `PROJECT_OVERVIEW.md` to canonical (rejected — `WORKING_LOGIC.md` is more detailed and more recent).
- Merge both into a single doc (rejected — `WORKING_LOGIC.md` is the spec; `PROJECT_OVERVIEW.md` is the high-level product overview).

**Consequences:**
- One source of truth for scoring rules; no more drift.
- `CURRENT_PROGRESS.md` becomes the single status doc, replacing ad-hoc status notes scattered across the other docs.

**Related Documents:** `WORKING_LOGIC.md`, `CURRENT_PROGRESS.md`, all docs

---

## DEC-012: Section-Routed Evidence Retrieval for per-candidate scoring

**Date:** 2026-06-30
**Status:** Accepted

**Context:** The original design used dense cosine similarity to retrieve resume chunks for per-candidate scoring. This was the wrong tool: a single resume is a short document (1,000–3,000 tokens) that should be read, not searched. Cosine retrieval risks silently dropping relevant chunks (e.g. a second Python role falling below the top-K cutoff), and produces non-deterministic evidence depending on the embedding model's ranking.

`WORKING_LOGIC.md` ("Section-Routed Evidence Retrieval") specifies that each requirement should be mapped to canonical section(s) by a fixed table, and retrieval should be an exact label match — fetch every chunk tagged with the mapped section(s), never a ranked top-K subset.

**Decision:** Implement Section-Routed Evidence Retrieval (`src/rag/section_routed.py`) as the sole retrieval strategy for per-candidate scoring. Dense cosine retrieval remains only for:
- Cross-candidate pool search (JD ↔ resume triage via `jd_match.py`)
- Resume chat (RAG via `retriever.py`)

The fixed routing table maps requirement types to canonical sections:
- Skill → Experience + Projects + Skills
- Education → Education
- Certification → Certifications
- Experience → Experience
- etc.

For unusually long sections, deterministic metadata filtering (`skills_asserted contains "Python"`) narrows the content — still an exact filter, not a similarity rank.

**Alternatives Considered:**
- Keep cosine for per-candidate scoring (rejected — non-deterministic, risks silent chunk drops, wrong tool for a single short document).
- Hybrid: cosine + section routing (rejected — adds complexity without benefit; section routing is strictly better for per-candidate evidence).
- LLM decides which sections to read (rejected — the routing must be fixed and auditable, not a model decision).

**Consequences:**
- Same requirement against same resume always returns the same content — fully deterministic.
- No relevant chunk can be silently missed (no top-K cutoff).
- No embeddings or cosine needed for scoring — only for pool search and chat.
- Fields that belong together (institute, branch, CGPA) can never be split across retrieval calls.

**Related Documents:** `AI_ARCHITECTURE.md`, `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md`, `WORKING_LOGIC.md`

---

## DEC-013: Recruiter-editable tier databases for institutes and certifications

**Date:** 2026-06-30
**Status:** Accepted

**Context:** `WORKING_LOGIC.md` ("Institute and Certification Tier Lookup") requires the platform to maintain a recruiter-editable tier database for institutions and certification providers. The original spec defined 4 tiers (A/B/C/D) with 100%/80%/60%/40% point multipliers. The user requested a simpler 3-tier system with a 0.50 default for unlisted institutes/certs (same as Tier 3), since verifying whether an unknown institute is legitimate would require either a database or a web search — and web search at scoring time introduces non-determinism.

**Decision:** Ship two recruiter-editable JSON tier databases:

1. `data/Institutes/institute_tiers.json` — 115 Tier 1 (1.0), 54 Tier 2 (0.75), 155 Tier 3 (0.50), not-listed (0.50). Sources: Wikipedia "List of state universities in India" (459 state universities), Wikipedia "List of deemed universities" (124 deemed universities), world top 100 universities.

2. `data/Certificates/certificate_tiers.json` — 115 Tier 1 (1.0), 45 Tier 2 (0.75), 10 Tier 3 (0.50), not-listed (0.50). Sources: Wikipedia "Professional certification", industry knowledge.

Scoring rules:
- Tier 1 → 1.0 × allotted points (premier/renowned)
- Tier 2 → 0.75 × allotted points (recognized/second-grade)
- Tier 3 → 0.50 × allotted points (regional/local)
- Not listed → 0.50 × allotted points (same as Tier 3 — innocent until proven guilty)

Lookup is code-only (`src/scoring/tier_lookup.py`) with word-boundary regex matching. No LLM, no web search at scoring time. Web search may be used only to enrich the tier databases offline.

**Alternatives Considered:**
- 4 tiers (A/B/C/D) per original WORKING_LOGIC.md (rejected — user requested 3 tiers for simplicity).
- Not-listed = 0.0 (rejected — penalizes legitimate but unlisted institutes; user requested 0.50 default).
- Not-listed = 0.25 (rejected — user changed to 0.50 after further consideration).
- LLM classifies institute tier at scoring time (rejected — non-deterministic, violates code-only principle).
- Web search at scoring time (rejected — non-deterministic, adds latency, PII concern).

**Consequences:**
- Fully deterministic tier lookup — same institute always gets the same tier.
- Recruiter can edit JSON files to move institutes/certs between tiers or add new ones.
- Unlisted institutes get 0.50 (same as Tier 3) — no penalty for being unrecognized.
- `reload_tier_databases()` clears the `lru_cache` after edits.

**Related Documents:** `WORKING_LOGIC.md`, `MODEL_REGISTRY.md`, `AI_ARCHITECTURE.md`

---

## DEC-014: Role-specific documentation template and SubQuery audit

**Date:** 2026-07-01
**Status:** Accepted

**Context:** Each role folder needed a consistent set of documents for recruiter onboarding and operational use. The BusinessAnalyst role served as the template with 8 complete files. The remaining 7 roles (DataScience, JavaDeveloper, ReactDeveloper, SalesManager, SQLDeveloper, SrPythonDeveloper, WebDesigning) needed matching documentation. SubQuery files required auditing against their corresponding JDs to ensure complete requirement coverage before the scoring system could be trusted for production use.

**Decision:** Each role folder shall contain 8 files:

1. `<Role>_JD.md` — Job Description (source of requirements)
2. `<Role>_SubQuery.md` — Sub-query decomposition with scoring formulas
3. `<Role>_ScoringGuide.md` — Percentage-based weighting guide for recruiters
4. `<Role>_WeightConfiguration_Guide.md` — Weight configuration instructions
5. `<Role>_RecruiterWeights_EXAMPLE.json` — Example weight configuration
6. `QUICK_START.md` — Quick start guide for recruiters
7. `README_SETUP.md` — Detailed setup instructions
8. `recruiter_weight_input.py` — Interactive CLI for weight configuration

**SubQuery audit criteria:**
- Every JD requirement must have at least one REQ in SubQuery
- Core Skills, Preferred Skills, Experience, Education sections must map correctly
- Binary gates × Float evidence scoring pattern must be consistent
- Scoring formula documented for each requirement
- recruiter_weight_input.py REQUIREMENTS lists must match SubQuery REQ-IDs

**Alternatives Considered:**
- Fewer files per role (rejected — reduces recruiter self-sufficiency)
- More files per role (rejected — increases maintenance burden)
- Skip SubQuery audit (rejected — misaligned requirements would produce incorrect scores)

**Consequences:**
- All 8 roles now have complete, audited documentation
- SubQuery alignment verified for all roles — scoring system can be trusted
- New roles can be created by copying the 8-file template from BusinessAnalyst
- Recruiters have self-service documentation for each role

**Related Documents:** `AGENTS.md`, `CURRENT_PROGRESS.md`, all role folders in `data/job_descriptions/`

---

## DEC-017: Regular RAG pivot for retrieval

**Date:** 2026-07-05
**Status:** Accepted (supersedes DEC-015, transitively DEC-012)

**Context:** The current retrieval stack runs two strategies side by side: Section-Routed (DEC-012) and Sub-Query Similarity (DEC-015) for per-candidate scoring, plus Dense Cosine (DEC-006) for pool search and chat. The Section-Routed path was retired because 49% of chunks had `section_type=""`; Sub-Query Similarity was added as a content-based fallback. In practice, the per-candidate "two strategies" design is more complex than the task needs: a single resume is a small document, and the recruiter-facing query volume is low. The team decided to simplify to a **regular RAG pipeline** (chunk → embed → cosine retrieve → generate) and rely on (a) the deterministic scoring engine for final ranking, and (b) hyperparameter tuning (Optuna + MLflow) to calibrate the retrieval.

**Decision:** Adopt a single regular RAG pipeline for all retrieval — per-candidate scoring, cross-candidate pool search, and resume chat.

- **Chunking:** Recursive (DEC-019). Default `chunk_size = 500`, `chunk_overlap = 50`. Both are Optuna hyperparameters.
- **Embedding:** Unchanged — `sentence-transformers/all-MiniLM-L6-v2` (DEC-007).
- **Retrieval:** Threshold-based cosine (DEC-018). Default `θ = 0.70`, `max_chunks_per_query = 20`.
- **Generation:** LLM receives retrieved chunks + (for scoring) the rubric. LLM never sees the requirement's weight. LLM never computes the final weighted contribution.
- **Scoring:** Unchanged. The deterministic engine in `src/scoring/graded_scorer.py` and `src/scoring/unified_scorer.py` is the **only** ranking signal. RAG feeds evidence; code computes the score.
- **RAG grounding rule:** Unchanged. If no chunk meets `θ`, LLM responds with `"Information not found in candidate documents."`

**Alternatives Considered:**

- **Keep Sub-Query Similarity (DEC-015)** — rejected. The two-step sub-query decomposition adds latency and prompt complexity; for ~17 chunks per candidate, top-K-or-threshold over a regular index is sufficient and the score is identical in practice.
- **Re-activate pure Section-Routed (DEC-012)** — rejected. 49% chunk invisibility remains; regular RAG is content-based and avoids the bug class entirely.
- **Hybrid (Section-Routed pre-filter + cosine)** — rejected. Adds complexity for no observed gain; the Optuna-tuned `θ` already handles the long-tail chunk distribution.
- **ML-trained ranker (cross-encoder) on top** — deferred. Can be added later as a `rerank_top_n` step after threshold retrieval; not in v1.

**Consequences:**

- One retrieval strategy, one config, one set of hyperparameters to tune.
- `θ` becomes the single most important knob — it determines recall vs. context size. Optuna (DEC-021) calibrates it against a fixed eval set.
- Chunking loses the resume-section structure that DEC-012/015 preserved. Mitigation: Header Normalization (DEC-013's synonym table) is retained for parse-time labeling, used by the structured profile and the tier lookup.
- The cache key from DEC-016 changes from `(candidate_id, req_id, sorted-chunk-ids, model-name)` to `(candidate_id, req_id, hash(query, top-chunk-ids), model-name, θ)` so cache hits are still safe across runs that use the same threshold.

**Related Documents:** `WORKING_LOGIC.md`, `AI_ARCHITECTURE.md`, `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md`, `EVALUATION.md`, `PROJECT_OVERVIEW.md`, `IMPLEMENTATION_ROADMAP.md`, `CURRENT_PROGRESS.md`

---

## DEC-018: Threshold-based retrieval (regular RAG variant)

**Date:** 2026-07-05
**Status:** Accepted

**Context:** Standard RAG uses top-K retrieval (e.g. `top_k = 5`). The team wanted a retrieval strategy that:
- Returns **more chunks** when there are more relevant matches in the corpus (don't artificially cap at 5 if 12 chunks are good).
- Returns **fewer chunks** when the corpus is noisy (don't send 20 mediocre chunks to the LLM when only 3 are good).
- Has a single, intuitive knob (`θ`) instead of two (`top_k` and a similarity filter).

**Decision:** For every query (sub-question, chat question, JD bullet), retrieve **all** chunks whose cosine similarity is ≥ `θ`. Apply a hard cap `max_chunks_per_query` (default 20) to bound context size. Log a warning when the cap is hit. Default `θ = 0.70`; expose as an Optuna hyperparameter.

```python
def retrieve(query: str, index, top_level_cap: int = 20) -> list[Chunk]:
    q_vec = embed(query)
    sims  = index.cosine(q_vec)               # dense vector
    hits  = [(s, c) for s, c in zip(sims, index.chunks) if s >= THRESHOLD]
    hits.sort(reverse=True)
    if len(hits) > top_level_cap:
        log.warning("threshold cap hit: %d > %d", len(hits), top_level_cap)
        return hits[:top_level_cap]
    return hits
```

**Alternatives Considered:**

- **Top-K (e.g. `top_k = 5`)** — rejected. Doesn't adapt to query difficulty; a 3-chunk result for a hard query is as bad as a 20-chunk result for an easy one.
- **Top-K + min-similarity filter** — rejected. Two knobs to tune; thresholds and top-K interact in non-obvious ways.
- **MMR (maximal marginal relevance) for diversity** — deferred. Useful when chunks are redundant; can be layered on top later.

**Consequences:**

- Returned chunk count is dynamic per query. Prompt size is variable but bounded.
- A naive `θ = 0.70` will return 0 chunks on some resumes and 30 on others — the Optuna search (DEC-021) calibrates against a fixed eval set to find a `θ` that balances recall and context size.
- The cap is a safety net, not a primary control. If the cap is being hit on > 10% of queries, `θ` is too low.

**Related Documents:** `WORKING_LOGIC.md`, `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md`, `EVALUATION.md`

---

## DEC-019: Recursive Chunking replaces Document-Aware Chunking

**Date:** 2026-07-05
**Status:** Accepted (supersedes prior Document-Aware as the active strategy)

**Context:** Document-Aware chunking was originally chosen (DEC-003) to preserve resume section structure for the Section-Routed retrieval path. With Section-Routed retired (DEC-012 → DEC-015 → DEC-017) and regular RAG in place, the section structure is no longer required for retrieval — chunks are embedded as opaque text, and cosine similarity is content-based. Recursive chunking is simpler, faster, and produces uniform-sized chunks that are more comparable under cosine similarity.

**Decision:** Use **Recursive Chunking** (`RecursiveCharacterTextSplitter` or equivalent) as the active chunking strategy. Defaults: `chunk_size = 500` chars, `chunk_overlap = 50` chars. Both are exposed as Optuna hyperparameters.

Separator hierarchy (LangChain default, fits resumes well):
1. `\n\n` (paragraph)
2. `\n` (line)
3. `. ` (sentence)
4. ` ` (word)

**Alternatives Considered:**

- **Keep Document-Aware** — rejected. Designed for label-based routing, no longer needed.
- **Semantic chunking (split on embedding-distance breakpoints)** — rejected. Adds an embedding call per chunk boundary; expensive and not better for short resumes.
- **Agentic chunking (LLM decides boundaries)** — rejected. Non-deterministic, expensive, and the LLM is not reliable at boundary detection for short structured documents.
- **Fixed-size (e.g. 500-char with no separator awareness)** — rejected. Cuts words mid-token; Recursive avoids that with the separator hierarchy.

**Consequences:**

- One uniform chunking strategy across the codebase. Chunks are now opaque blobs of text + their embedding.
- Header Normalization (DEC-013's synonym table) is **retained** for parse-time section labeling because the structured profile (`degrees`, `certifications`, `total_experience_years`) still needs the labeled sections. It is no longer used for retrieval routing.
- The Document-Aware chunker in `src/rag/chunker.py` is renamed `DocumentAwareChunker` and kept for one release as a migration aid; removed in the release after that.
- Chunk metadata schema (DEC-016) is simplified: `section_type` becomes a soft tag (still populated for the structured profile) but is no longer required for retrieval. Required fields are now `chunk_id`, `candidate_id`, `text`, `char_span`, `embedding_index`.

**Related Documents:** `AI_ARCHITECTURE.md`, `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md`

---

## DEC-020: MLflow for experiment tracking

**Date:** 2026-07-05
**Status:** Accepted

**Context:** The team plans to experiment with `chunk_size`, `chunk_overlap`, `θ`, `top_k`, embedding model, and LLM in combination. Without a tracking system, results are lost, configs are not reproducible, and the team cannot answer "which config produced this score?" Two candidates were considered: MLflow and Weights & Biases.

**Decision:** Use **MLflow** for experiment tracking.

- **Tracking URI:** `http://127.0.0.1:5000` (local server)
- **Backend store:** `data/mlflow/mlflow.db` (SQLite)
- **Artifact root:** `data/mlflow/artifacts/`
- **Launch:** `mlflow server --host 127.0.0.1 --port 5000 --backend-store-uri sqlite:///data/mlflow/mlflow.db --default-artifact-root ./data/mlflow/artifacts/`

Per-run logging contract:

```python
with mlflow.start_run():
    mlflow.log_params({
        "chunk_size": 500, "chunk_overlap": 50,
        "embedding_model": "all-MiniLM-L6-v2",
        "vector_store": "faiss",
        "similarity": "cosine",
        "retrieval_mode": "threshold",
        "threshold": 0.70, "top_k": None,
        "llm": "gpt-4o-mini",
    })
    mlflow.log_metrics({
        "recall_at_theta": ..., "precision_at_theta": ...,
        "mrr": ..., "ndcg": ...,
        "avg_chunks_returned": ..., "p95_chunks_returned": ...,
        "faithfulness": ..., "groundedness": ...,
        "answer_relevancy": ..., "hallucination_rate": ...,
        "top_k_accuracy": ..., "recruiter_agreement": ...,
    })
    mlflow.log_artifact("runs/<run_id>/retrieved_chunks.json")
    mlflow.set_tag("experiment_set", "chunking_v1")
```

**Alternatives Considered:**

- **Weights & Biases (W&B)** — rejected. Best-in-class UI and built-in Sweeps, but cloud-based. Resume PII (candidates' names, contact info, employer history) would leave the local machine. The privacy boundary is a hard constraint for this project.
- **CSV / JSON manifests** — rejected. No UI, no comparison view, no way to diff runs.
- **TensorBoard** — rejected. Designed for training curves, not for retrieval/hyperparameter sweeps.

**Consequences:**

- Resume PII stays on the local machine. MLflow's backend and artifact store are both local SQLite + filesystem.
- Every retrieval run is reproducible: the params block is the full config; the artifacts include the retrieved chunks and the eval-set inputs.
- The Optuna study (DEC-021) writes its trials to MLflow via `optuna.integration.MLflowCallback`; the final recommended config is exported to `MODEL_REGISTRY.md` as the new "Active" config.

**Related Documents:** `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md`, `EVALUATION.md`

---

## DEC-021: Optuna for hyperparameter search

**Date:** 2026-07-05
**Status:** Accepted

**Context:** Four hyperparameters drive retrieval quality (`chunk_size`, `chunk_overlap`, `threshold θ`, and an optional `top_k` fallback). Hand-picking them is guesswork; the team wants data-driven defaults. Optuna is the standard Python hyperparameter-optimization library and integrates natively with MLflow (DEC-020).

**Decision:** Use **Optuna** with a TPE sampler and a SQLite-backed study store to drive the hyperparameter search. Run **multi-objective** optimization by default: `maximize faithfulness` and `minimize avg_chunks_returned` simultaneously. The result is a **Pareto front**; the operator picks the operating point on the front (e.g. faithfulness ≥ 0.85 with ≤ 8 chunks per query).

```python
import optuna
from optuna.integration import MLflowCallback

study = optuna.create_study(
    directions=["maximize", "minimize"],
    sampler=optuna.samplers.TPESampler(),
    storage="sqlite:///data/optuna/studies.db",
    study_name="rag_retrieval_v1_20260705",
)

@study.optimize(n_trials=200, callbacks=[MLflowCallback(tracking_uri="http://127.0.0.1:5000")])
def objective(trial):
    params = {
        "chunk_size":    trial.suggest_int   ("chunk_size",    200, 1000, step=100),
        "chunk_overlap": trial.suggest_int   ("chunk_overlap",   0,  150, step=25),
        "threshold":     trial.suggest_float ("threshold",     0.50, 0.90, step=0.05),
        "top_k":         trial.suggest_int   ("top_k",           3,   20),
    }
    return run_pipeline_with_params(params, eval_set)  # (faithfulness, avg_chunks_returned)
```

Eval set requirement: a fixed `data/eval/<set_name>.jsonl` of `(query, expected_chunks, expected_answer)` triples — see DEC-020 for the schema.

Naming convention: `<experiment_set>_<yyyymmdd>` (e.g. `chunking_v1_20260705`, `threshold_v1_20260712`).

**Alternatives Considered:**

- **Grid search** — rejected. Combinatorial explosion; no learning between trials.
- **Random search** — rejected. Better than grid but still no learning; Optuna's TPE is strictly stronger.
- **Hyperopt** — rejected. Comparable capability, weaker MLflow integration.
- **W&B Sweeps** — rejected. Couples hyperparameter search to a cloud SaaS (DEC-020); the project stays local.

**Consequences:**

- Hyperparameters are data-driven, not hand-picked. The shipped config is the Optuna-recommended point on the Pareto front.
- The eval set becomes the **single source of truth** for "what does good look like". A bad eval set → bad Optuna recommendation → bad shipped config. Building the eval set is the first prerequisite (see `IMPLEMENTATION_ROADMAP.md` M0.5b).
- Study history is persisted in SQLite at `data/optuna/studies.db` (in `.gitignore`). Resumable; multiple team members can append trials.
- The Optuna dashboard (`optuna-dashboard sqlite:///data/optuna/studies.db`) gives a free Pareto-front UI without MLflow's cloud.

**Related Documents:** `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md`, `EVALUATION.md`, `IMPLEMENTATION_ROADMAP.md`

---

## DEC-022: Per-resume reasoning storage + legacy chunk migration

**Date:** 2026-07-05
**Status:** Accepted

**Context:** Two storage concerns need to be settled before M0.5a ships.

1. **Legacy chunks.** The 721-resume corpus has Document-Aware chunk files at `data/chunks/<role>/<candidate_id>.jsonl`. Once `RecursiveChunker` becomes the active chunker (M0.5a, DEC-019), the new files will also be written to `data/chunks/`. We must not let the two chunkers' outputs collide in the same directory — the chunk counts, the metadata schema, and the `chunk_id` format are different, and a downstream consumer that picks the wrong one will silently corrupt scores. The user requested that legacy chunks be either deleted or renamed so it is unambiguous which chunker produced them.

2. **Reasoning storage.** The current `data/embeddings/llm_cache.jsonl` only stores the rubric-bound LLM's anchored sub-scores — a memoization layer to make re-runs cheap. It does not store the LLM's narrative reasoning, the specific chunks the LLM cited, or the retrieved-chunks list. Two problems follow:
   - **Cost:** every re-run of the same (candidate, req, query) with the same θ still pays the LLM round-trip if the cache key doesn't match (e.g. after a `θ` change in Optuna, even if the result would be identical). The user wants to eliminate the re-call in those cases.
   - **Determinism:** even with anchored sub-scores, the LLM can produce slightly different outputs across runs (especially with non-zero temperature). The user wants the reasoning itself frozen so re-runs return the same sub-scores byte-for-byte, not just "almost the same".

**Decision:**

**(a) Legacy chunk migration (one-time, M0.5a).** Move the existing Document-Aware chunk files from `data/chunks/<role>/<candidate_id>.jsonl` to `data/chunks_legacy_document_aware/<role>/<candidate_id>.jsonl`. Do not delete — the file contents are valid Document-Aware output and may be needed for backward-compatibility checks during the migration window. A new file `data/chunks_legacy_document_aware/MIGRATION_NOTES.md` records:
- the date of the move
- the source chunker (`DocumentAwareChunker`, the pre-DEC-019 implementation)
- the target chunker (`RecursiveChunker`, post-DEC-019)
- the chunk-count delta per file (so it is obvious the new files are not just renamed copies)
- a `git mv`-friendly script the user can run to undo the move if needed

After the move, `data/chunks/<role>/<candidate_id>.jsonl` is reserved exclusively for `RecursiveChunker` output. Any code path that writes to `data/chunks/` MUST be the `RecursiveChunker`.

**(b) Per-resume reasoning storage (active from M0.5e onward).** Replace the single `data/embeddings/llm_cache.jsonl` with a per-resume artifact tree:

```
data/per_candidate/
└── <role>/
    └── <candidate_id>/
        └── reasoning/
            └── <req_id>__<query_hash>.json
```

Each `<req_id>__<query_hash>.json` file stores, for one (candidate, req, query) triple:

```json
{
  "schema_version": "1.0",
  "candidate_id": "cand_042",
  "req_id": "REQ-002",
  "query": "5+ years of Python experience with recommendation systems",
  "created_at": "2026-07-05T10:32:14Z",
  "model_name": "nemotron-3-ultra-free",
  "model_params": { "temperature": 0, "max_tokens": 1024 },
  "retrieval_params": {
    "theta": 0.70,
    "max_chunks_per_query": 20,
    "chunk_size": 500,
    "chunk_overlap": 50,
    "embedding_model": "all-MiniLM-L6-v2"
  },
  "retrieved_chunks": [
    { "chunk_id": "cand_042__14", "cosine": 0.91, "text": "..." },
    { "chunk_id": "cand_042__2",  "cosine": 0.84, "text": "..." }
  ],
  "reasoning": "The candidate mentions Python in 4 of 5 retrieved chunks...",
  "basis": [
    { "chunk_id": "cand_042__14", "quote": "Delivered 9 ML projects in Python", "relevance": "primary" },
    { "chunk_id": "cand_042__2",  "quote": "Recommendation system at Netflix for 3 years", "relevance": "supporting" }
  ],
  "sub_scores": {
    "skill_presence":   { "value": 1.0,  "type": "binary",   "source_basis_idx": [0, 1] },
    "years_experience": { "value": 0.8,  "type": "linear",   "source_basis_idx": [0] },
    "project_relevance":{ "value": 0.75, "type": "anchored", "source_basis_idx": [1] }
  },
  "rubric_version": "v1.0",
  "scoring_mode": "rubric_bound_llm"
}
```

**Cache key** (must match for a re-run to be a cache hit, not a re-call):

```
hash(candidate_id, req_id, hash(query, sorted(top_chunk_ids)), model_name, θ)
```

A re-run is a **cache hit** when the key matches exactly. On hit, the scoring engine reads the stored `sub_scores` directly — no LLM call, no embedding call, no retrieval. The `reasoning` and `basis` are read for the score-explanation UI.

**Cache invalidation** (key mismatch → re-call):
- Chunking parameters change (`chunk_size`, `chunk_overlap`) → new `chunk_id` set → different `top_chunk_ids` → cache miss.
- Embedding model changes → new vectors → new `cosine` values → different `top_chunk_ids` → cache miss.
- LLM model upgrade → `model_name` differs → cache miss.
- `θ` change → different `top_chunk_ids` returned → cache miss.
- JD requirement or weight config change → `req_id` or `query` differs → cache miss.

**GC policy:** entries with no read in the last 90 days are candidates for archival (move to `data/per_candidate_archive/`); not deleted by default.

**Alternatives Considered:**

- **Delete legacy chunks outright** — rejected. Preserves history at near-zero cost; renaming (vs. deleting) is strictly safer during a migration window.
- **Rename legacy files with a `legacy_document_aware_` prefix in the same directory** — rejected. The `data/chunks/` directory should mean one thing: Recursive chunks. Putting legacy files there with a name prefix is ambiguous and breaks naive directory listings.
- **Keep `llm_cache.jsonl` as the single cache file** — rejected. The single-file design makes the "re-run reads from cache" claim implicit and un-inspectable. Per-resume storage makes the cache a first-class artifact that recruiters can browse per candidate.
- **Store only sub-scores, not reasoning/basis** — rejected. The whole point of DEC-022 is to make the LLM's behavior auditable per-candidate and per-req. Storing only sub-scores is just a fancier cache; storing the reasoning and basis makes the cache an audit trail.
- **External KV store (Redis, Memcached) for the cache** — rejected. Re-runs need to be reproducible from local artifacts for audit. The per-resume JSON tree is on the local filesystem; no extra service to deploy.

**Consequences:**

- Storage cost grows. Estimate: 721 candidates × ~15 REQs × ~4 sub-queries = ~43,000 JSON files per (model, θ) combo. At ~5–20 KB each, that's ~200–800 MB per combo. With 2–3 combos in flight during an Optuna sweep, peak usage is ~1–2 GB. Acceptable on a single-machine deployment; flag in `ENVIRONMENT_NOTES.md` for ops review.
- LLM-call cost drops dramatically. After the first scoring pass, every re-run of the same (candidate, req, θ) is a filesystem read.
- Re-run determinism is now structural, not statistical. Same cache key → same `sub_scores` byte-for-byte. The LLM temperature debate is moot for any (candidate, req) that has been scored.
- Score-explanation UI gets richer for free. The `reasoning` and `basis` are already on disk; rendering them as "Why did this candidate receive this score?" is a JSON read.
- Auditability is per-(candidate, req), not per-batch. A recruiter can open `data/per_candidate/BusinessAnalyst/cand_042/reasoning/REQ-002__<hash>.json` and see exactly what the LLM saw, what it cited, and what it returned.
- The legacy chunk directory `data/chunks_legacy_document_aware/` is added to `.gitignore` (chunks are large binaries; only the `MIGRATION_NOTES.md` is committed).

**Related Documents:** `WORKING_LOGIC.md`, `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md`, `EVALUATION.md`, `IMPLEMENTATION_ROADMAP.md`, `CURRENT_PROGRESS.md`, `ENVIRONMENT_NOTES.md`

---

## DEC-023: Per-experiment folder naming for Recursive chunking + folder renames

**Date:** 2026-07-05
**Status:** Accepted (refines DEC-022)

**Context:** DEC-022 settled the per-resume reasoning storage layout, but two naming issues remain.

1. The legacy Document-Aware folder name `data/chunks_legacy_document_aware/` is verbose and awkward. The user requested the more direct `data/document_aware_chunking/`.
2. The active Recursive chunking folder name `data/chunks/` is generic — it does not encode the active chunker. With multiple MLflow experiments in flight (different `chunk_size`, `overlap`, `top_k`, `θ` combinations per Optuna trial), a single `data/chunks/` directory would conflate the artifacts of distinct experiments. The user requested per-experiment folders whose names encode the hyperparameters that produced them.

**Decision:**

**(a) Rename `data/chunks_legacy_document_aware/` → `data/document_aware_chunking/`.** The directory is still the legacy home of the 721 Document-Aware chunk files; only the name changes. `MIGRATION_NOTES.md` moves with the directory. The `.gitignore` rule moves with it. Old code paths and docs that referenced `data/chunks_legacy_document_aware/` are updated to `data/document_aware_chunking/`.

**(b) Adopt the per-experiment folder naming convention for the Recursive chunking pipeline.** Every MLflow run's artifacts live in a folder named after the hyperparameters that produced it:

```
data/recursive_chunking_<chunk_size>_<overlap>_<top_k>_<threshold×100>/
```

**Field order** (4 numeric fields, in this order):

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
| `chunk_size=500, overlap=50, θ=0.70` (threshold mode, no top_k cap) | `data/recursive_chunking_500_50_x_70/` |
| `chunk_size=500, overlap=50, top_k=5` (top_k mode, no threshold filter) | `data/recursive_chunking_500_50_5_x/` |

**Folder contents (per experiment):**

```
data/recursive_chunking_500_200_5_50/
├── metadata.json                    # the full config that produced this folder
├── chunks.jsonl                     # Recursive chunks for this (chunk_size, overlap)
├── index.npz                        # embedding index (MiniLM-L6-v2, 384-dim)
├── llm_cache_legacy.jsonl           # (only in the M0.5e-b migration window)
└── per_candidate/
    └── <role>/
        └── <candidate_id>/
            └── reasoning/
                └── <req_id>__<query_hash>.json
```

**`metadata.json` schema** (the canonical record of the experiment):

```json
{
  "schema_version": "1.0",
  "experiment_folder": "recursive_chunking_500_200_5_50",
  "created_at": "2026-07-05T11:14:22Z",
  "chunking": {
    "chunker": "RecursiveChunker",
    "chunk_size": 500,
    "chunk_overlap": 200,
    "separators": ["\n\n", "\n", ". ", " "]
  },
  "retrieval": {
    "mode": "threshold_and_top_k",
    "threshold": 0.50,
    "top_k": 5,
    "max_chunks_per_query": 20,
    "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
    "similarity": "cosine"
  },
  "mlflow_run_id": "abc123def456",
  "optuna_trial_id": 42
}
```

**Folder name is the self-documenting identifier.** Two MLflow runs with the same `(chunk_size, overlap, top_k, threshold)` share the same folder — the artifacts (chunks, index, cache) are byte-identical for the same config, so sharing is correct, not redundant. The "Active" config in `MODEL_REGISTRY.md` points to one specific folder; promoting a new Active config means pointing to a different folder (or renaming an existing one to "active").

**Promotion ceremony:** when a config is promoted to "Active", its folder is symlinked (or copied) to `data/active_experiment/` so the runtime can find it without hardcoding the hyperparameter values. The symlink is a one-line, one-direction operation; reverting is `rm data/active_experiment`.

**Alternatives Considered:**

- **Keep `data/chunks_legacy_document_aware/` (verbose name)** — rejected. The user requested the explicit `document_aware_chunking` name; the verbose form was a placeholder.
- **Single `data/chunks/` folder for all Recursive experiments** — rejected. Conflates artifacts of distinct experiments; cache invalidation becomes ambiguous; the folder name carries no information about which experiment it serves.
- **Hash-based folder names (e.g., `data/recursive_chunking_<sha256[:8]>/`)** — rejected. Self-documenting beats self-identifying. The folder name is the recruiter's first hint at what the experiment tested; "500_200_5_50" is more useful than "a3f2b1c8".
- **Sub-folders per MLflow run (e.g., `data/recursive_chunking/<run_id>/`)** — rejected. Same-hash experiments should share artifacts, not duplicate them. The hyperparameter tuple is the natural grouping key.
- **Prefix letters in the folder name (e.g., `c500_o200_k5_t50`)** — rejected by user preference. Numeric form is shorter and the field order is documented.
- **`x` placeholder for unused modes** — accepted. Cleaner than a sentinel value (e.g., `0` or `-1`) and reads as "this dimension is not used in this experiment".

**Consequences:**

- The number of sub-folders under `data/recursive_chunking_*` grows with the Optuna sweep. Estimate: 200 trials × 1 study = ~200 folders; across 3 studies = ~600 folders. Manageable on a single machine.
- Storage cost grows proportionally. Each experiment folder is ~10–20 MB (chunks + index) plus per-resume reasoning. With 600 folders, peak is ~10–15 GB. The 5 GB alert threshold in `EVALUATION.md` (DEC-022d) is too low; raised to **20 GB** in DEC-023.
- Folder names are sortable on the filesystem: `ls data/ | sort` lists experiments by chunk_size first, then overlap, then top_k, then threshold. Useful for ad-hoc inspection.
- The `data/active_experiment` symlink is the runtime entry point; the `Active` config in `MODEL_REGISTRY.md` is its source of truth.
- Code that writes chunks, indexes, or caches must consult `metadata.json` to find its target folder. Hardcoded paths like `data/chunks/` are no longer valid after M0.5e.

**Related Documents:** `WORKING_LOGIC.md`, `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md`, `IMPLEMENTATION_ROADMAP.md`, `CURRENT_PROGRESS.md`, `ENVIRONMENT_NOTES.md`

---

## DEC-024: Chunk reports folder + ranking evaluation methodology without labeled data

**Date:** 2026-07-05
**Status:** Accepted

**Context:** Two related concerns need to be settled before the Recursive chunking pipeline replaces Document-Aware chunking as the active strategy.

1. **Historical record of Document-Aware chunking.** The Document-Aware chunker was the active strategy from 2026-06-19 to 2026-07-04 and produced 721 chunk files. Empirical testing on the 721-resume corpus surfaced a critical bug: **49% of chunks had `section_type=""` and were invisible to Section-Routed retrieval** (DEC-015). This finding justified retiring the Document-Aware chunker (DEC-019) and is documented in `DECISIONS.md` and `ARCHITECTURE_CHANGELOG.md`, but there is no per-experiment chunk diagnostic report on disk. If the question "how bad was the bug, really?" is asked in six months, the answer is "read the report".

2. **Ranking evaluation without labeled data.** The platform ranks candidates against recruiter-defined weight configs, but there is no labeled "ground truth" ranking to compare against. A traditional ML evaluation (precision@K, NDCG against labels) doesn't apply. Recruiters disagree among themselves; the "right" candidate is a judgment call; labeled sets are expensive and decay over time. The team needs a methodology for answering "is our ranking correct?" without a single ground truth.

**Decision:**

**(a) Adopt `reports/chunk_reports/` as the canonical home for per-experiment chunk diagnostics.** Report file names mirror the experiment folder names so the two are unambiguous pairs:

```
reports/
└── chunk_reports/
    ├── document_aware_chunking_report.json         # the 721-resume Document-Aware diagnostic
    ├── document_aware_chunking_report.md           # human-readable summary
    ├── recursive_chunking_500_200_5_50_report.json # per-experiment Recursive diagnostic
    ├── recursive_chunking_500_200_5_50_report.md
    └── ...
```

**Report schema (`<experiment>_report.json`):**

```json
{
  "schema_version": "1.0",
  "experiment_name": "document_aware_chunking",
  "experiment_folder": "document_aware_chunking/",
  "created_at": "2026-07-05T13:45:00Z",
  "source": "pre-DEC-019 production chunks",
  "chunker": "DocumentAwareChunker",
  "config": {
    "max_chunk_chars": 1200,
    "split_overlap_chars": 120
  },
  "chunk_statistics": {
    "total_chunks": 6377,
    "chunks_per_role": {
      "BusinessAnalyst": 1180,
      "SalesManager": 1450,
      "WebDesigning": 990,
      "SrPythonDeveloper": 870,
      "SQLDeveloper": 720,
      "JavaDeveloper": 640,
      "DataScience": 360,
      "ReactDeveloper": 167
    },
    "chunks_per_resume": {
      "mean": 8.84,
      "median": 8,
      "min": 3,
      "max": 27,
      "p95": 18
    },
    "chunks_with_section_type_empty": 3125,
    "section_type_empty_rate": 0.490,
    "section_type_distribution": {
      "experience": 2100,
      "education": 720,
      "skills_summary": 240,
      "projects": 120,
      "certifications": 60,
      "header": 12,
      "(empty)": 3125
    }
  },
  "retrieval_statistics": {
    "section_routed_hits": 1620,
    "section_routed_misses_due_to_empty_label": 3125,
    "counterfactual_estimate": "of 5000 relevant chunks in the 721-resume corpus, ~2450 (49%) were dropped at routing time because section_type was empty"
  },
  "key_findings": [
    "49.0% of chunks have section_type='' and are invisible to Section-Routed retrieval (DEC-015 finding).",
    "Section labels are wrong assumptions; resumes use 30+ different header strings for 'Experience' alone."
  ],
  "recommendation": "Retire Document-Aware + Section-Routed. Adopt Recursive Chunking + threshold-based cosine retrieval (DEC-017, DEC-019)."
}
```

**For Recursive experiments, the same schema is used** with the `config` block populated from the per-experiment `metadata.json` and additional retrieval/eval metrics from MLflow.

**Reports are committed to git** — they are small text files (a few KB each) and the historical record of every experiment matters. Binaries (chunks, index, caches) stay in `.gitignore`; reports do not.

**(b) Adopt a multi-pronged ranking evaluation methodology** that does not require a single labeled ground truth. See `EVALUATION.md` §"Ranking Evaluation Without Labeled Data" for the full spec. The five prongs:

| Prong | Source of "ground truth" | Cost | Coverage |
|---|---|---|---|
| **Counterfactual tests** | Constructed test cases where the expected ranking change is unambiguous | Cheap; automated; scales | Always |
| **Synthetic labeled set** | 30–50 (candidate, role) pairs hand-ranked by 2–3 recruiters; majority/median ranking is the truth | Moderate; one-time + periodic refresh | Once per quarter |
| **Stability tests** | Re-running the same config | Free; already covered by DEC-022 determinism | Always |
| **Recruiter agreement** | Multiple recruiters rank the same pool; Cohen's kappa or Krippendorff's alpha | High; needs ≥2 humans per case | Periodic study |
| **Behavioral signals** (production) | Did the recruiter interview the top-K? Did they reject the bottom-K? | Requires production data; noisy | Production only |

**Counterfactual test suite (built first, runs on every config):** a JSON file `data/eval/counterfactual_v1.jsonl` where each row is a test case with expected ranking delta. Examples:

```json
{
  "test_id": "cf_001",
  "description": "Increasing Python weight should rank the Python-heavy candidate above the Java-heavy candidate",
  "config_a": { "weights": { "python": 5, "java": 5 } },
  "config_b": { "weights": { "python": 15, "java": 5 } },
  "candidates": ["cand_python_heavy", "cand_java_heavy"],
  "expected": "config_b ranks cand_python_heavy above cand_java_heavy"
}
```

The system runs both configs on the test candidates and asserts the expected ranking change. Pass rate ≥ 0.95 is the target.

**Synthetic labeled set:** `data/eval/ranking_v1.jsonl`. Each row is:

```json
{
  "set_id": "ranking_v1",
  "role": "BusinessAnalyst",
  "candidates": ["cand_001", "cand_002", ..., "cand_010"],
  "expected_ranking": ["cand_005", "cand_002", "cand_008", ...],
  "recruiters": ["recruiter_A", "recruiter_B"],
  "inter_rater_agreement": 0.73,
  "created_at": "2026-07-15"
}
```

Computed metrics: `ndcg_at_10`, `top_3_accuracy`, `spearman_correlation` against the expected ranking.

**Alternatives Considered:**

- **Build a large labeled ranking set (e.g., 1000+ candidates)** — rejected. Recruiting ground truth decays fast (a "great" candidate last year may not be a "great" candidate this year). A 30–50-case high-quality set, refreshed quarterly, is more durable.
- **Use resume-to-resume similarity as a proxy for ranking quality** — rejected. The whole point of the deterministic scoring engine is that ranking is not driven by similarity. Using similarity to evaluate ranking would be circular.
- **Use a public benchmark (e.g., ResumeMatch, LinkedIn)** — rejected. Public benchmarks use different definitions of "good match" than our recruiter-defined weights. They would measure similarity to a different ground truth, not ours.
- **Behavioral signals only (no offline eval)** — rejected. Behavioral signals are noisy, slow (need production), and don't help during the Optuna sweep (which needs fast automated feedback). They supplement offline eval, not replace it.
- **Recruiter agreement only** — rejected. Inter-rater agreement is a useful signal, but it tells us "the system agrees with recruiters" — not "the system is correct". Two raters can agree and both be wrong.
- **Inline reports (markdown sections in chunk files)** — rejected. Reports need to be findable on the filesystem, version-controlled, and not coupled to the chunker output. A separate `reports/` tree is the right separation.

**Consequences:**

- The Document-Aware chunking report is generated **once** from the existing 721 chunk files. It captures the DEC-015 finding (49% missing `section_type`) and the empirical justification for DEC-019.
- Every Recursive experiment generates a report at scoring time. The report is committed to git so the historical record is preserved.
- The counterfactual test suite is built first because it's cheap and runs on every config. It is the **fast feedback loop** for the Optuna sweep (M0.5d).
- The synthetic labeled set is built once per quarter. It is the **slow feedback loop** for the recruiter-facing score.
- The platform's claim "rankings are correct" is now backed by five independent signals, not one. The user-facing promise is "we have five ways to catch ranking regressions; if all five agree the ranking is good; if any one disagrees we investigate."
- `EVALUATION.md` is the canonical spec for the methodology. The `reports/chunk_reports/` folder is the artifact; the methodology is the spec.

**Related Documents:** `WORKING_LOGIC.md`, `MODEL_REGISTRY.md`, `EVALUATION.md`, `IMPLEMENTATION_ROADMAP.md`, `CURRENT_PROGRESS.md`

---

## DEC-025: Candidate ID nomenclature (`<Role>_CAND_<NNNN>`)

**Date:** 2026-07-05
**Status:** Accepted

**Context:** The platform's candidate identifier was a 12-character SHA1 hash of the absolute source file path (`cand_<12hex>`, e.g. `cand_74cbbc14c744141a`). This was stable across runs and PII-friendly, but had three practical problems:

1. **Not human-readable.** A recruiter looking at `cand_74cbbc14c744141a` cannot tell which role or which candidate it is without looking up the registry.
2. **Not role-encoded.** Listing "all candidates for BusinessAnalyst" required a database join on the source path; a role-prefixed id makes this a string prefix match.
3. **Hidden renumbering risk.** Without a stable counter, any future code that sorted by path or position would silently change the mapping between the hash and the "first" candidate for a role.

The team has no external candidate registration number (no ATS, no HRIS import), so we are free to design a sensible internal scheme. The user proposed `<Role>_CAND_<NNNN>` (e.g. `BusinessAnalyst_CAND_0001`); this decision adopts that proposal with two refinements.

**Decision:**

**(a) ID format.** Every candidate id is `<Role>_CAND_<NNNN>` where:
- `<Role>` is the role folder name (one of the 8 roles: `BusinessAnalyst`, `DataScience`, `JavaDeveloper`, `ReactDeveloper`, `SalesManager`, `SQLDeveloper`, `SrPythonDeveloper`, `WebDesigning`).
- `<NNNN>` is a 4-digit zero-padded decimal counter, allocated per role from a registry.
- The format is regex-enforced: `^[A-Za-z][A-Za-z0-9]*_CAND_\d{4,}$`.

**(b) Stable registry.** A new file `data/candidate_registry.json` is the source of truth for the mapping. Schema:

```json
{
  "schema_version": "1.0",
  "next_counter": {
    "BusinessAnalyst": 134,
    "DataScience": 43,
    "JavaDeveloper": 73,
    ...
  },
  "candidates": {
    "BusinessAnalyst_CAND_0001": {
      "source_path": "C:/.../data/original/BusinessAnalyst/jane_doe.pdf",
      "source_filename": "jane_doe.pdf",
      "legacy_hash_id": "cand_74cbbc14c744141a",
      "allocated_at": "2026-07-05T10:00:00Z",
      "last_seen_at": "2026-07-05T10:00:00Z"
    },
    ...
  }
}
```

`next_counter` is the next number to allocate for each role (atomic increment under a file lock). The counter is **monotonic** — a deleted candidate's number is never reused.

**(c) Allocation.** The parser consults the registry when it first sees a source path. If the path is already registered, the existing id is returned. Otherwise, a new id is allocated by incrementing the role's `next_counter` and the registry is persisted. Two distinct source paths can never share an id; one source path always maps to the same id.

**(d) Backward compatibility with the 721 existing candidates.** A one-time backfill script (`scripts/backfill_candidate_registry.py`) walks `data/processed/<role>/<id>.json`, computes the legacy hash id via the old `candidate_id_from_path`, and registers each candidate with a new sequential id (allocated in filesystem order for determinism). The legacy hash id is stored in `legacy_hash_id`. The 6,377 existing Document-Aware chunks are **not** migrated — they keep their hash-based chunk_ids. The new Recursive chunks (M0.5a) use the new id space.

**(e) Chunk ID impact.** The chunk_id format (`{candidate_id}__{chunk_index}`) is unchanged in shape. New Recursive chunks get `BusinessAnalyst_CAND_0001__0`; legacy chunks keep `cand_74cbbc14c744141a__experience__0`. Two coexisting id spaces is the cleanest migration — no churn in the existing 6,377 chunks.

**Alternatives Considered:**

- **Global counter (`CAND_000042` with a separate role field).** Rejected — loses the role-encoded grep ("all candidates for BusinessAnalyst" becomes a JOIN instead of a string prefix).
- **UUID.** Rejected — not human-readable, defeats the whole point of the rename.
- **Hash-based with a friendly alias table.** Rejected — the alias is human-readable but the canonical id is still a hash. The hash never appears in the chunk_id, the structured profile, the score, the per-resume reasoning tree, or any other artifact.
- **Per-role counter without a registry file (in-memory only).** Rejected — a fresh process would restart at 1, breaking stability.
- **Renumber on every parse (delete-then-allocate).** Rejected — the counter would drift every run; "first candidate" would change with the file system.

**Consequences:**

- The 721 existing candidates are backfilled once. After the backfill, the registry has 721 entries and the per-role counters are at the post-allocation values.
- The chunk_id format change is **not retroactive**. The 6,377 existing Document-Aware chunks keep their `cand_<hash>__<section>__<i>` ids. New chunks use `<Role>_CAND_<NNNN>__<i>` per the DEC-023 simplified schema.
- The `candidate_id_from_path` function in `src/resume_parsing/parser.py` is **deprecated** in favor of `CandidateRegistry.allocate_or_lookup(source_path, role)`. The deprecated function is kept for one release as a fallback for any caller that hasn't migrated.
- The registry file is committed to git. It contains source paths (which may leak the test environment) but no PII beyond the file system layout. Treat the file as semi-sensitive.
- Per-resume reasoning tree paths (`data/per_candidate/<role>/<candidate_id>/reasoning/...`) use the new id space for new candidates. The tree for an old candidate would use the hash id; the registry's `legacy_hash_id` field is the bridge.

**Related Documents:** `WORKING_LOGIC.md`, `MODEL_REGISTRY.md`, `EVALUATION.md`, `IMPLEMENTATION_ROADMAP.md`, `CURRENT_PROGRESS.md`

---

## DEC-026: Ranking diff methodology (before NDCG@k / MAP@k)

**Date:** 2026-07-05
**Status:** Accepted

**Context:** The platform's "is our ranking correct?" methodology (DEC-024) lists five prongs: counterfactual tests, synthetic labeled set, stability tests, recruiter agreement, behavioral signals. Two of those — synthetic labeled set and recruiter agreement — eventually call for aggregate metrics like NDCG@k and MAP@k. Those metrics are useful summary numbers, but they don't tell us **which** candidates changed rank or **why**. A regression in the Optuna-recommended config could move 5 candidates by 20 positions each, and the aggregate NDCG might still look "OK" while the recruiter-facing ranking is silently wrong.

The user explicitly requested a per-candidate diff before any aggregate metric: "before we go for NDCG@k or MAP we will evaluate how similar or different each of such experiments are". The intuition is sound: regressions in this product are best diagnosed at the candidate level ("candidate X dropped 18 places because the new threshold excluded the chunks that cited his 6 years of Python"). Aggregate metrics are a follow-up, not a substitute.

**Decision:**

**(a) The diff tool.** A new module ``src.eval.ranking_diff`` (with CLI ``scripts/diff_rankings.py``) compares two rankings of the same role. Inputs are the two ``List[Tuple[candidate_id, score]]`` lists and a label for each. The output is a structured report with five sections:

1. **New entrants / departures for top-K.** For K=10 and K=50 (the recruiter-facing shortlists), the report lists every candidate that appears in one top-K but not the other. The user reads this first because a new candidate in the top-10 is the loudest possible signal.
2. **Rank deltas (signed).** For every candidate that appears in *both* rankings, a signed integer delta where positive = moved up (smaller rank number = better position) and negative = moved down. Sorted by absolute value to surface the largest changes first.
3. **Aggregate stats.** Average absolute rank change across shared candidates; max absolute change (with the candidate id). Both are *normalized by the total number of candidates in the role* — a 5-position change in a 50-candidate pool is much louder than in a 1000-candidate pool.
4. **Categorization.** A ``categorize`` method partitions every shared candidate into one of:
   - ``stable`` — |delta| ≤ threshold
   - ``big_swap_up`` — moved up by more than the threshold
   - ``big_swap_down`` — moved down by more than the threshold
   - ``only_in_baseline`` — present in baseline, absent in current
   - ``only_in_current`` — present in current, absent in baseline
   The default threshold is **10% of the total candidates in the role** (e.g. 10 positions in a 100-candidate pool). The threshold is configurable; for small role pools the absolute minimum is 1.
5. **Per-case investigation with versioned reasoning + chunks.** For each candidate in ``new_in_top_k``, ``only_in_current``, ``big_swap_up``, or ``big_swap_down``, the CLI dumps a side-by-side record pulled from each experiment's per-resume reasoning tree (``data/recursive_chunking_<params>/per_candidate/<role>/<candidate_id>/reasoning/<req_id>__<query_hash>.json`` per DEC-022). The dump includes:
   - the rubric-bound LLM's narrative ``reasoning``
   - the cited ``basis`` (chunks + quotes)
   - the ``retrieved_chunks`` list with cosine scores
   - the ``model_name`` and ``retrieval_params`` (so the diff report is reproducible from MLflow)
   - the ``sub_scores`` (the anchored floats that the deterministic engine aggregated)
   This is what the user means by "everything has to be versioned" — and the per-resume tree from DEC-022 already provides it. The diff tool just reads from both trees and presents the comparison.

**(b) Output format.** The CLI writes a JSON + Markdown pair to ``reports/diff_rankings/<baseline>__vs__<current>__<role>.{json,md}``. The folder is committed to git (small text files). File names mirror the diff inputs: ``exp1__vs__exp2__BusinessAnalyst.{json,md}``.

**(c) When to run.** The diff tool is the first check after every Optuna-promoted config change. The promotion gate (DEC-024) is "counterfactual pass rate ≥ 0.95, stability = 1.0, NDCG@10 ≥ 0.80"; the diff is what you run *after* the new config is promoted, to inspect which candidates actually moved. It does not gate promotion; it diagnoses it.

**(d) The "versioned" part is already in place.** The user asked "I think it is set like that?" — yes. The per-resume reasoning tree from DEC-022 is keyed by ``(candidate_id, req_id, hash(query, sorted(top-chunk-ids)), model_name, θ)`` and lives in a per-experiment folder. Two experiments with different θ values store *different* files; a third experiment with the same θ reuses the same file. The diff tool reads from both trees; no new versioning infrastructure is needed.

**Alternatives Considered:**

- **Skip the per-candidate diff and just compute NDCG@k / MAP@k.** Rejected. Aggregate metrics tell you "the ranking changed" but not "which candidates moved and why". A 0.02 NDCG drop could be a benign 1-position shuffle across the whole pool, or it could be a 5-candidate massacre in the top-10. The diff is what disambiguates.
- **Compute NDCG@k first, then per-candidate diff if NDCG drops.** Rejected. The user explicitly asked for per-candidate diff *first*. Their argument: if a new config has a 0.01 NDCG improvement but introduces 3 nonsense candidates into the top-10, the aggregate metric hides the regression. Per-candidate diff catches it.
- **Use a database join across two score files.** Rejected. The score files are per-experiment and may have different schemas (different fields, different chunk-id sets). A purpose-built diff tool with a clean dataclass API is more maintainable.
- **Manually compare two score files in a spreadsheet.** Rejected. Doesn't scale, doesn't produce a committed artifact, doesn't preserve the versioned reasoning + chunks.
- **Run the diff as a Jupyter notebook.** Rejected. Not reproducible, not version-controlled, not committable.

**Consequences:**

- A new ``src/eval/`` package with a focused responsibility: compare two rankings. No dependencies on the scoring engine — the tool accepts ``List[Tuple[candidate_id, score]]`` and produces a report.
- A new ``scripts/diff_rankings.py`` CLI that the team runs after every config promotion. The CLI's job is to find the candidates worth investigating; the team's job is to look at them.
- A new ``reports/diff_rankings/`` folder committed to git. Each diff is a small text file (a few KB) that captures a snapshot of the platform's ranking behavior at a point in time. The historical record grows linearly with the number of config changes.
- The diff tool is **complementary** to NDCG@k / MAP@k, not a replacement. Once the diff is healthy, NDCG/k is the right aggregate to add next (next session's work).
- No NDCG / MAP work in this session. Per the user's instruction, that comes after the per-candidate diff lands.

**Related Documents:** `EVALUATION.md`, `MODEL_REGISTRY.md`, `IMPLEMENTATION_ROADMAP.md`, `CURRENT_PROGRESS.md`

---

## DEC-027: M0.5a stage-4 code shipped — RecursiveChunker + ThresholdRetriever + per-REQ retrieval + rebuilt index + theta-aware cache key

**Date:** 2026-07-06
**Status:** Accepted

**Context:** Per the architecture pivot of 2026-07-05 (DEC-017 → DEC-024), the platform switched from Document-Aware chunking + Section-Routed retrieval + top-K cosine to Recursive chunking + threshold-based cosine + per-REQ SubQuery retrieval, all under Optuna hyperparameter search (DEC-021). The owner specified tighter Optuna search-space bounds than the original DEC-019/018 doc defaults: `threshold ∈ [0.10, 0.50]`, `chunk_size ∈ [200, 500]`, `chunk_overlap ∈ [100, floor(0.60 * chunk_size)]`. M0.5a was the single-session minimum-viable code change to align the implementation with the new spec, gated on getting the full unit-test suite passing on the active stack.

**Decision:**

**(a) RecursiveChunker is the active chunker.** `src/rag/recursive_chunker.py` (LangChain-free `recursive_split_text` with separator hierarchy `["\n\n", "\n", ". ", " "]`) replaces `DocumentAwareChunker` as the live strategy. `DocumentAwareChunker` is retained at its original path as a one-release migration aid per DEC-022. Default values `chunk_size = 500`, `chunk_overlap = 100` sit inside the Optuna search range so the default-config run is a valid point in the sweep. Bounds are enforced at construction time and in `recursive_split_text` — out-of-range inputs raise `ValueError` instead of silently shipping a wrong config.

**(b) ThresholdRetriever is the active retriever.** `src/rag/retriever.py` (`ThresholdRetriever` + `VectorIndex`) replaces top-K cosine with threshold-based cosine: return every chunk with `cosine >= theta`, sorted desc, capped at `max_chunks_per_query` as a safety net. Default `theta = 0.30` (midpoint of [0.10, 0.50]), `max_chunks_per_query = 20`. A WARN log fires on cap-hit so a misconfigured `theta` is loud rather than silent.

**(c) Per-REQ retrieval via union + dedup.** `src/rag/per_req_retrieval.py` is the new entry point for SubQuery-style evidence gathering. For each REQ, it embeds every sub-query (or accepts caller-supplied vectors), calls `ThresholdRetriever.retrieve_scored` once per sub-query with the `candidate_id` filter, unions the results with dedup by `chunk_id` (keeping the highest cosine and remembering which sub-query produced it for audit), sorts the union desc, and applies the final cap. Returns `[]` on zero retrieval so the caller (the deterministic scorer) raises the no-evidence flag — a candidate with zero retrieved evidence for a REQ scores 0 and is flagged for human review at `reports/audit/no_evidence_flags.jsonl`. One sub-query alone does not evaluate a sub-score; the whole SubQuery set is the evidence-gathering query for the REQ.

**(d) SubQuery parser extended.** `src/services/subquery_parser.py::_extract_requirements` was extended to parse SubQuery table rows (`SQ### | text | type | scale | assessment_method`) into a `sub_queries` list per REQ. Verified across all 8 role SubQuery files: 138 REQs, 356 sub-queries, 0 declared-vs-parsed count mismatches.

**(e) Embedding index rebuilt.** `src/rag/build_index.py` (new module + CLI) walks `data/processed/<role>/*.json`, filters out the `_intelligence_report.json` and `_structured_profile.json` downstream artifacts so only the 721 canonical parsed resumes are indexed, chunks each with `RecursiveChunker`, batch-embeds with MiniLM-L6-v2 (DEC-007, 384-dim, L2-normalized), and persists to `data/embeddings/index.npz` + `data/embeddings/chunks.jsonl` via `VectorIndex.save_npz`. Build result: **721 resumes → 6,670 chunks, 384-dim, 8.4 MB**, built in 135 s on CPU. The prior Document-Aware index (6,377 chunks) was moved to `data/embeddings/document_aware_backup/` per DEC-022.

**(f) Defensive chunker coercion.** During the first dry-run of `build_index.py` a real-world shape variance surfaced: in the parsed-resume tree some profiles store `experience` and `education` as a list (canonical is `{"entries": [...]}`) and others as `None`. `RecursiveChunker.chunk_profile` previously called `.get("entries")` on the value blindly and crashed with `AttributeError`. The fix coerces non-dict `experience`/`education` to the canonical `{"entries": []}` shape in `chunk_profile` so the chunker is robust to parser-output variance without changing the parse contract.

**(g) Cache key includes theta.** `src/services/subquery_retrieval.py::make_cache_key` was extended with a `theta` kwarg folded into the SHA-256 hash (quantized to 6 decimals to avoid float noise invalidating the cache). All 3 callers (per-REQ scoring + 2 in batched scoring) were updated to thread the retrieval `threshold` into the key. The rationale (M0.5a Step 5): `theta` is the one Optuna hyperparameter whose change can leave the chunk-id set *identical* (every retrieved chunk clears both candidate thresholds), so without `theta` in the key the cache would silently return sub-scores computed under a different trial. Folding `theta` into the key trades a lower hit rate during the sweep for a strict per-trial isolation: every cached value is tagged with the theta that produced it, and the sweep is auditable.

**(h) Optuna bounds are owner-specified, not doc-specified.** The shipped defaults and enforced bounds match the owner's 2026-07-06 spec, which differ from the 2026-07-05 doc defaults (DEC-018/019). The doc defaults were `theta = 0.70`, `chunk_size = 500`, `chunk_overlap = 50`; the shipped defaults are `theta = 0.30`, `chunk_size = 500`, `chunk_overlap = 100`. The bounds are exported as module-level constants (`THRESHOLD_LOWER`, `THRESHOLD_UPPER`, `CHUNK_SIZE_LOWER`, `CHUNK_SIZE_UPPER`, `CHUNK_OVERLAP_LOWER`, `CHUNK_OVERLAP_MAX_FRACTION`, `max_overlap_for`) so Optuna can import them directly. The Optuna-promoted "Active" config in `MODEL_REGISTRY.md` is still pending M0.5d — the shipped defaults are a valid point in the search space, not the recommended one.

**Alternatives Considered:**

- **Leave Optuna bounds at doc defaults (chunk_size up to 2000, overlap 0-200).** Rejected — the owner explicitly tightened the ranges on 2026-07-06. The wider chunk_size range would have wasted Optuna trials on chunks > 500 (which are too large for our candidate-side evidence gathering) and on chunks < 200 (which are too small to carry a complete skill claim).

- **Skip the SubQuery parser extension and hand-write sub-queries in the test harness.** Rejected — the SubQuery files at `data/job_descriptions/<role>/<role>_SubQuery.md` are the canonical source of truth (per AGENTS.md: "do NOT editorialize, rewrite, or audit SubQueries — the JD is ground truth"). Hand-writing would force a second source of truth and drift from the JD.

- **Build the index by streaming through `ChunkIndex` instead of using the new `VectorIndex` class.** Rejected — `ChunkIndex` is the legacy class tied to Document-Aware chunking; `VectorIndex` was already designed (DEC-018) as the canonical on-disk format. Building via `VectorIndex.save_npz` keeps the on-disk format consistent regardless of which script wrote the file.

- **Do not fold `theta` into the LLM cache key.** Rejected — see (g). The tradeoff (lower hit rate) was deemed acceptable because the sweep is the only place where different `theta` values are exercised, and per-trial isolation makes the Optuna objective function easier to reason about (no silent cross-trial reuse).

- **Default theta to 0.70 (doc default).** Rejected — 0.70 is outside the owner-specified [0.10, 0.50] range, so the default-config run would not be a valid point in the sweep. We need the default run to be inside the search space so a vanilla `python -m src.rag.build_index` followed by a default-config score run produces something the Optuna tracker can ingest as the first trial.

**Consequences:**

- **The "Active" config is data-ready for M0.5d.** The shipped defaults (`theta = 0.30`, `chunk_size = 500`, `chunk_overlap = 100`) sit inside the owner-specified Optuna search range. The first Optuna trial can therefore reuse the existing index (built with the default `chunk_size` and `chunk_overlap`) and only has to vary `theta` to score candidates at different thresholds.

- **The embedding index needs to be rebuilt only when `chunk_size` or `chunk_overlap` changes.** `theta` is a retrieval-time parameter and does not affect the index. The Optuna sweep can therefore reuse the same `index.npz` across all theta trials and only rebuild when it varies `chunk_size` or `chunk_overlap` — a significant cost saving for the sweep.

- **The previous Document-Aware index is preserved at `data/embeddings/document_aware_backup/`.** A rollback to Document-Aware chunking for debugging is possible by moving the backup back into place.

- **403 / 404 unit tests pass.** The single pre-existing failure (`test_parse_resume_extracts_contact_and_name`) is the `src/resume_parsing/ocr.py` missing-module issue (deferred to Track 6). New tests added this session: `test_per_req_retrieval.py` (11), `test_cache_key.py` (11).

- **No production score path is wired through `per_req_retrieval` yet.** The new module is the canonical entry point for SubQuery scoring, but the legacy `src/services/subquery_retrieval.py::retrieve_chunks_for_requirement` is still live and unchanged except for the cache-key signature update. Track 2 (scorer refactor: Mode1 × Mode2 composition, drop `scale_factor`, drop `DEFAULT_EXPECTED_YEARS`) will replace the legacy path with the per-REQ path as its scoring consumer.

- **The 113 missing candidates** (721 resumes → 608 unique candidate_ids in the index) were silently dropped because their parsed profile produced zero non-empty sections. This is a parser-quality issue and is tracked for Track 6; the index correctly excludes them since they would produce zero-chunk noise in retrieval.

**Related Documents:** `WORKING_LOGIC.md`, `MODEL_REGISTRY.md`, `EVALUATION.md`, `IMPLEMENTATION_ROADMAP.md`, `CURRENT_PROGRESS.md`, `AI_DESIGN_RATIONALE.md`, `AI_ARCHITECTURE.md`

---

## DEC-028: Composed Mode1 × Mode2 scorer shipped (DEC-024 execution, scorer refactor)

**Date:** 2026-07-06
**Status:** Accepted / shipped
**Supersedes / refines:** DEC-024 (gives the architecture pivot its first production score consumer); makes legacy `scale_factor` and `DEFAULT_EXPECTED_YEARS = 10` deprecated in the production path.

### Context

DEC-024 pivoted Stage-4 retrieval to RecursiveChunker + ThresholdRetriever + per-REQ retrieval (DEC-027 / Track 1 / M0.5a) but did not specify the scorer that would consume it. The legacy `graded_scorer.evaluate_candidate` (and the later `unified_scorer.evaluate_candidate_unified`) used a `scale_factor = 100 / max_score` normalization and a `DEFAULT_EXPECTED_YEARS = 10` fallback for years-type REQs whose JD did not carry an `expected_years` field. Per WORKING_LOGIC §1262-1289, the canonical formula is `Sub-Score_REQ = Code_only_part × Rubric_LLM_part` (both ∈ [0,1]), `Contribution = weight% × Sub-Score`, `Total = Σ Contribution` — recruiter weights sum to 100, so no `scale_factor` is required. Missing `expected_years` should block the REQ (and flag for human review), not silently default to 10.

### Decision

Adopt the canonical WORKING_LOGIC scoring formula as the production scoring path, implemented as additive new code alongside the legacy shims:

1. **`evaluate_candidate_code_only_v2`** (in `src/scoring/graded_scorer.py`) — code-only scorer under the new spec. Drops `scale_factor` and `DEFAULT_EXPECTED_YEARS`. Total = `Σ (weight% × code_only_part)`. Years-type REQs with no recoverable `expected_years` are blocked (contribution 0 + "BLOCKED:" reason).
2. **`extract_expected_years`** (in `src/scoring/graded_scorer.py`) — regex extractor for `expected_years` from free text. Handles 4 patterns: `expected N years`, `N-M years → M (upper bound)`, `N+ years`, `N years`; returns `None` when nothing recoverable.
3. **`evaluate_candidate_composed`** (in `src/scoring/unified_scorer.py`) — per REQ: `Sub-Score = Code_only_part × Rubric_LLM_part` (both ∈ [0, 1]); `Contribution = weight% × Sub-Score`; `Total = Σ Contribution`. Code-only part comes from `Binary` + `Float years-proportional` SubQuery SQs scored against the parsed profile. Rubric LLM part comes from one `rubric_scorer.score_requirement_with_rubric` call per REQ after `per_req_retrieval.retrieve_evidence_for_req` retrieves evidence. New `sq_embedder` kwarg lets tests inject synthetic vectors.
4. **`src/audit/no_evidence_flags.py`** — append-only JSONL audit log (`data/audit/no_evidence_flags.jsonl`) for zero-evidence flags. One line per `(candidate, REQ)` pair with theta + chunker context. Reserved field names protected against overwrite from `extra` dict.

### Rationale

- **Additive over rewrite.** Adding new functions alongside the legacy ones keeps the existing batch CLI and roadmap work unbroken while the new path is wired into production. Legacy paths are deprecated in the new spec but kept as backward-compat shims (importable, callable).
- **`sq_embedder` injection** keeps unit tests fast (4-dim synthetic toy index) and lets the production path swap embedders without code edits (MiniLM-L6-v2 in production, stub in tests).
- **Rubric LLM part is one call per REQ (not per SubQuery-SQ)** for the first iteration, because `rubric_scorer.score_requirement_with_rubric` already produces a per-REQ `trace.normalized_score`. Per-SQ rubric granularity is deferred.
- **Missing `expected_years` = block, not default** aligns with AGENTS.md ("AI assumptions must not replace recruiter priorities") and WORKING_LOGIC (JD/SubQuery file is the source of truth). Silent defaulting would mask a JD-quality issue.
- **Zero-evidence flags are auditable, not silent** — recruiters and reviewers must be able to see which `(candidate, REQ)` pairs had no retrieved evidence so they can act (lower θ, rewrite SubQuery, or accept the score-0 as correct).

### Consequences

- The composed scorer is the first production consumer of the Track 1 RAG pipeline; the per-REQ retrieval path now has a measurable downstream effect.
- Production callers must migrate from `evaluate_candidate` / `evaluate_candidate_unified` to `evaluate_candidate_composed` to get the canonical formula. Until `scripts/score_batch_composed.py` is written, the legacy batch CLI remains the live production path.
- The legacy `DEFAULT_EXPECTED_YEARS = 10` constant is kept in `graded_scorer.py` as a deprecation marker (importable, unused in the new path).
- `Sub-Score_REQ` is bounded ∈ [0, 1] by construction; recruiter weights sum to 100 by spec; therefore `Total` is bounded ∈ [0, 100] without any `scale_factor`. The old "total × scale_factor" math is no longer needed.
- The deterministic scoring engine remains the only ranking signal; the LLM only scores the rubric sub-questions within a single REQ. Final candidate order is reproducible and auditable.

### Risks

- **Sub-query classifier heuristics** (`_is_binary_subquery`, `_is_years_subquery`, `_is_rubric_subquery`) reduce the SQ table to a Code-only vs Rubric partition. `_is_years_requirement` uses a keyword heuristic ("experience", "years", "tenure", "senior") which misses years-type REQs whose names lack those keywords (e.g., a REQ named "Python" that actually probes Python years). Mitigation: `_score_years_sq` returns `(score, years, expected)`; when `expected=None` the REQ is blocked regardless of classifier label, so a misclassified years-REQ surfaces as a block + flag rather than a silent wrong score.
- **Per-SQ rubric granularity deferred.** The first iteration calls the rubric scorer once per REQ, not once per SubQuery-SQ. A REQ with mixed Binary + Rubric SQs may have its rubric LLM part dominated by the loudest rubric SQ. Mitigation: per-REQ rubric scoring was already the existing `rubric_scorer` API; per-SQ rubric scoring is a future iteration and is tracked in CURRENT_PROGRESS as deferred.
- **`sq_embedder` stub interface.** Unit tests inject hand-crafted 4-dim vectors aligned to a 3-chunk `toy_index`. This sidesteps the real MiniLM model in tests but means the unit tests do not exercise the real embedding geometry. Mitigation: the production `per_req_retrieval` path is separately exercised by the M0.5a smoke test on a real DS candidate, and the composed scorer's behavior on real embeddings will be validated in M0.5b/c eval.
- **Legacy paths still live.** Until the batch CLI is migrated, the platform can still produce scores from `evaluate_candidate_unified` which carry the legacy `scale_factor` and `DEFAULT_EXPECTED_YEARS = 10`. Production consumers must be migrated deliberately; no automatic cutover.

### Verification

- **441 / 442 unit tests pass** (one pre-existing `ocr.py` failure, deferred to Track 6).
- **38 new tests** in `tests/unit/test_composed_scorer.py` cover: `extract_expected_years` (8), `no_evidence_flags` writer (6), `evaluate_candidate_code_only_v2` (6), sub-query classification (3), per-SQ scoring helpers (5), and `evaluate_candidate_composed` end-to-end (10).
- **No-recounting rule preserved.** Two REQs may cite the same evidence via the retrieved-chunks union, but each REQ measures a different dimension (`Code_only_part` derives from the SQ's own type, `Rubric_LLM_part` derives from the rubric call scoped to that REQ).
- **No LLM-determined ranking.** The LLM only contributes a per-REQ sub-question score inside the rubric. Final candidate order is deterministic and reproducible.

### Related Documents

`WORKING_LOGIC.md` (§1262-1289 scoring spec, § recruiter weight config schema), `MODEL_REGISTRY.md` (Candidate Scoring Strategy entry), `CURRENT_PROGRESS.md` (Track 2-S status table), `RELEASE_NOTES.md` (2026-07-06 Track 2-S entry), `AI_ARCHITECTURE.md` (Candidate scoring workflow), `AI_DESIGN_RATIONALE.md` (Mode1 × Mode2 composition rationale), `RECRUITER_WORKFLOWS.md` (Candidate Evaluation workflow).

---

## DEC-029: Word-boundary matcher for education/cert code-only scoring (Track 5, substring fix)

**Date:** 2026-07-06
**Status:** Accepted / shipped
**Supersedes / refines:** Pre-existing implementation bug in `_score_education_code_only` and `_score_certification_code_only` (legacy bare-`in` substring check). No architectural change — this is a bugfix.

### Context

`src/scoring/unified_scorer.py::_score_education_code_only` and `_score_certification_code_only` matched requirement strings against candidate degree/cert strings with a bare `in` substring check:

```python
# Education (legacy):
if item_name.lower() in degree_entry.degree.lower() or \
   degree_entry.degree.lower() in item_name.lower():
# Certification (legacy):
if item_name.lower() in cert_entry.name.lower() or \
   any(kw in cert_entry.name.lower() for kw in item_name.lower().split()):
```

Substring matching causes false positives when the requirement is a short abbreviation that happens to appear inside a longer token:

- `"BA" in "MBA"` → True. A `BA` requirement wrongly matched an `MBA` degree.
- `"BS" in "BSE"` → True. A `BS` requirement wrongly matched a `BSE` (Bachelor of Science in Engineering) degree.
- `"PMP" in "PMPI"` → True. A `PMP` requirement wrongly matched a `PMPI` (Project Management Prep Institute) cert.

Real data inspection confirmed the bug is active: real candidate degrees include `"BA"` (15 candidates) and `"MBA"` (6 candidates), so the false-positive path was being exercised.

### Decision

Add a `_token_boundary_match(needle, haystack)` helper to `unified_scorer.py` and replace both legacy substring matchers with calls to it.

Matcher semantics (in order of evaluation):

1. **Whole-phrase match** — `re.search(r"\b" + re.escape(needle) + r"\b", haystack, re.IGNORECASE)`. Highest signal. Short-circuits to True when the requirement appears verbatim in the candidate text as a whole phrase.
2. **ANY-token match** — split `needle` on whitespace, ignore tokens ≤ 2 chars (stop-words), and return True if any remaining token matches `haystack` with `\b<tok>\b` word boundaries. Preserves the legacy certification "any token of the requirement matches" behavior so `"AWS Certified"` still matches `"AWS Solutions Architect Associate"` via the `aws` token.

### Rationale

- **Word-boundary regex is the correct primitive for whole-token matching.** Python's `re` `\b` anchor matches at a position where the immediately preceding character is a non-word character (or the start of string) and the following character is a word character. Therefore `re.search(r"\bba\b", "mba", re.I)` is `None` because the `b` immediately to the left of `ba` is itself a letter (no boundary). This correctly rejects `"BA"` matching `"MBA"`.
- **ANY-token (not ALL-token) semantic preserved.** The legacy cert matcher did `any(kw in cert for kw in item_name.split())`, which is ANY-token. Switching to ALL-token would have broken the existing `"AWS Certified"` → `"AWS Solutions Architect Associate"` match (the `certified` token does not appear in the candidate cert string, but `aws` does). ANY-token with word boundaries preserves the match while rejecting substring collisions.
- **Stop-word filter (≤ 2 chars) skips near-zero-signal matches.** A 1- or 2-character token from the requirement (e.g., `in`, `of`, `is`) should not carry any matching signal — the `aws` / `ba` / `pmp` / `btech` tokens do. The filter prevents a 2-char stop-word from spuriously matching longer candidate tokens.
- **No architectural change.** This is a bugfix to two code-only scoring helpers. The deterministic scoring engine, rubric path, and composed scorer path are all unchanged. No new data files, no new external dependencies.

### Consequences

- Pre-existing real-data false positives are corrected: candidates with `"MBA"` degrees no longer spuriously match `"BA"` requirements; candidates with `"BSE"` no longer spuriously match `"BS"`; certs named `"PMPI"` no longer spuriously match `"PMP"`.
- Real `"BA"` degrees (15 candidates) still correctly match `"BA"` requirements (whole-word match works when there is a boundary on both sides).
- Any-token cert matching is preserved: `"AWS Certified"` requirement still matches `"AWS Solutions Architect Associate"` candidate cert via the `aws` token.
- No false negatives introduced for substantive degree strings (`"BTech"` requirement matches `"BTech"`, `"BTech in Computer Science"`, etc., via whole-phrase or single-token `btech` word boundary).
- The fix is scoped to `unified_scorer.py`. The legacy `graded_scorer._text_matches` (in `graded_scorer.py`) already uses word boundaries via `_aliases_for`'s `\b<alias>\b` regex, so it was never affected.

### Risks

- **Edge case: tokens with punctuation suffixes.** Tokens like `"Bachelor's"` are escaped by `re.escape`, so the apostrophe is treated literally. The match `re.search(r"\bbachelor's\b", "bachelor of science", re.I)` is False (no apostrophe in candidate), so requirements phrased with apostrophes may not match via the whole-phrase path — they fall through to the ANY-token path which only sees `["bachelor's"]` (after the stop-word filter removes tokens ≤ 2 chars; "bachelor's" is 10 chars and survives). The token `"bachelor's"` does not appear in `"bachelor of science"`, so this requirement-to-degree pair still does not match — the same outcome as legacy substring (which also did not match). No regression.
- **Edge case: requirements containing only stop-words.** If `needle` is a 2-char abbreviation like `"BA"`, the stop-word filter removes it (≤ 2 chars), and the fallback path uses the raw token list (which contains `"BA"`). `\bba\b` is then evaluated against the haystack. This correctly matches real `"BA"` degrees and rejects `"MBA"`. The fallback path is invoked only when *all* tokens are ≤ 2 chars.
- **No regression to all 14 existing `test_unified_scorer.py` tests.** All 14 pre-existing tests in `TestEducationCodeOnly`, `TestCertificationCodeOnly`, `TestLocationCodeOnly`, and `TestEvaluateCandidateUnified` continue to pass without modification. 6 new regression tests cover the bugfix.

### Verification

- **447 / 448 unit tests pass** (+6 vs the prior 441/442 baseline). The single pre-existing failure (`test_parse_resume_extracts_contact_and_name`) is the unrelated `src/resume_parsing/ocr.py` missing-module issue (Track 6, deferred).
- **6 new regression tests** in `tests/unit/test_unified_scorer.py`:
  - `test_education_no_ba_in_mba_false_positive` — `"BA"` requirement no longer matches `"MBA"` degree.
  - `test_education_no_bs_in_bse_false_positive` — `"BS"` requirement no longer matches `"BSE"` degree.
  - `test_education_ba_matches_real_ba_degree` — sanity: real `"BA"` degree still matches `"BA"` requirement.
  - `test_education_btech_in_btech_computer_science` — sanity: `"BTech"` requirement still matches `"BTech in Computer Science"` degree string.
  - `test_cert_no_pmp_in_pmpi_false_positive` — `"PMP"` requirement no longer matches `"PMPI"` cert.
  - `test_cert_pmp_match_in_pmp_certified` — sanity: `"PMP"` still matches `"PMP Certified"` (word boundary works because there is whitespace after `PMP`).

### Related Documents

`CURRENT_PROGRESS.md` (Track 5 status table, shipped), `RELEASE_NOTES.md` (2026-07-06 Track 5 Added/Fixed/Unchanged entries), `AI_ARCHITECTURE.md` (Candidate scoring workflow, code-only branch), `WORKING_LOGIC.md` (code-only scoring rules).

---

## DEC-030: Reconcile missing modules — `src/resume_parsing/ocr.py` restored + `header_normalization.py` phantom documented (Track 6)

**Date:** 2026-07-06
**Status:** Accepted / shipped
**Supersedes / refines:** Pre-existing doc/impl inconsistencies. No architectural change.

### Context

Two pre-existing inconsistencies between the docs and the implementation had been kicked forward for several sessions:

1. **`src/resume_parsing/ocr.py` was a phantom module.** The parser (`src/resume_parsing/parser.py:28-37, 138-150`) already imported it lazily via `try/except ImportError` and wrote `_HAS_OCR = False` when missing, raising `RuntimeError` at call time. No actual `.py` file existed, even though two PDF back-ends (`pdfplumber` and `pypdfium2`) were already declared in `requirements.txt` and installed in the venv. The fixture PDF test `test_parse_resume_extracts_contact_and_name` therefore failed every run with `RuntimeError: PDF extraction requires src.resume_parsing.ocr which is not installed in this environment.`

2. **Several docs claimed `src/resume_parsing/header_normalization.py` existed.** It never did. The section-header classification logic (the `SECTION_HEADERS` dict + `sectionize()` + `identify_section_heading()` functions) was implemented directly inside `src/resume_parsing/parser.py`. Phantom references were present in `CURRENT_PROGRESS.md`, `MODEL_REGISTRY.md`, `IMPLEMENTATION_ROADMAP.md`, `ARCHITECTURE_CHANGELOG.md`, and older `RELEASE_NOTES.md` entries.

### Decision

1. **Create `src/resume_parsing/ocr.py` as a real optional-dependency bridge.** It declares three availability flags at import time — `_HAS_PDFPLUMBER`, `_HAS_PYPDFIUM`, `_HAS_PDF2IMAGE` — and exposes a single public function `extract_text_hybrid(path: Path) -> str` that runs the strategies in order (pdfplumber → pypdfium2 → pdf2image + OCR), short-circuiting on the first non-empty result. Raises an informative `RuntimeError` if every strategy returns empty text so the parser can mark the resume as unparsable rather than silently producing an empty profile.
2. **Add `pytest.mark.skipif(not _HAS_OCR, ...)` to the existing PDF fixture test** so the suite remains green in environments with and without PDF back-ends installed.
3. **Add 7 new unit tests in `tests/unit/test_ocr.py`** covering the availability flags, the happy-path extraction on a real PDF from the corpus, both `RuntimeError` paths (no backends / empty backends), and the individual private backend wrappers. Use `skipif` guards for tests that exercise unavailable backends.
4. **Reconcile the `header_normalization.py` doc phantom.** Update `CURRENT_PROGRESS.md`, `MODEL_REGISTRY.md`, `IMPLEMENTATION_ROADMAP.md`, and `ARCHITECTURE_CHANGELOG.md` to point at `src/resume_parsing/parser.py` as the real location of the section-header classification logic. Each reconciled reference links back to this decision record (Track 6 / DEC-030).
5. **Document the optional-dependency pattern + the PDF back-end availability matrix in `docs/ENVIRONMENT_NOTES.md`.**
6. **Document the full debugging trail in `docs/TROUBLESHOOTING.md`** (problem → symptoms → root cause → investigation → solution → verification → prevention), as a reusable pattern for future optional-dependency missing-module investigations.

### Rationale

- **Restoring `ocr.py` is the substantive fix; skippifying tests is the safety net.** Both `pdfplumber` and `pypdfium2` were already installed; the failure was purely a missing wiring module. Creating `ocr.py` lets the parser use what the environment already provides. The `skipif` guard preserves green-test semantics in minimal CI environments where `pdfplumber`/`pypdfium2` are deliberately absent.
- **The `_HAS_X` flags declared at import time are the canonical optional-dependency pattern.** They make the availability state inspectable by tests and by other modules, they fail-open at import time (so the rest of the parser stays importable), and they fail-closed at call time (so callers get an informative `RuntimeError` instead of a silent empty result). New optional backends should follow the same pattern.
- **Doc reconciliation is part of implementation governance per AGENTS.md.** The `header_normalization.py` phantom existed because a docs-only architecture draft was never reconciled with the actual code. Updating the four doc references in the same track prevents future contributors from chasing a file that doesn't exist.
- **No architectural change.** This is a missing-module bugfix + doc reconciliation. The deterministic parser path, structured profile, scoring engine, and RAG pipeline are all unchanged.

### Consequences

- **The pre-existing single failing test now passes.** `test_parse_resume_extracts_contact_and_name` runs `parse_resume(<pdf>)` and extracts "John Wood" + phone + email from the `01888170110d1ccf.pdf` fixture via `pdfplumber`. The suite is now **455/455 passing** (perfect green).
- **New optional-dependency tests are env-resilient.** The 7 new tests in `tests/unit/test_ocr.py` skip cleanly in environments without PDF backends — the suite is green in both backends-present and backends-absent configurations.
- **The docs no longer point at a phantom `header_normalization.py`.** Future contributors reading the architecture roadmap, model registry, current-progress table, or architecture changelog will see that the section-header classification logic lives in `src/resume_parsing/parser.py` (the `SECTION_HEADERS` dict + `sectionize()` + `identify_section_heading()` functions).
- **No new runtime dependencies.** `pdfplumber` and `pypdfium2` were already in `requirements.txt`; `ocr.py` simply wires them up. `pdf2image` is documented as optional (Poppler required) but not added to `requirements.txt` as a hard dependency.
- **The lazy-import branch in `parser.py` (`try: from .ocr import extract_text_hybrid; _HAS_OCR = True except ImportError: _HAS_OCR = False`) is unchanged.** The new `ocr.py` simply makes the `True` branch reachable in environments where the PDF backends are already installed.

### Risks

- **OCR fallback is a placeholder.** `_extract_with_pdf2image_ocr` is wired but does not yet invoke an OCR engine; it returns empty text today. Scanned-PDF resumes therefore still hit the empty-text `RuntimeError`. This is a documented limitation, not a regression — the previous state was "raise RuntimeError unconditionally for all PDFs", so the change strictly improves reach.
- **`pdf2image` requires Poppler on the system PATH.** The placeholder does not error if Poppler is missing because it is only invoked when both `pdfplumber` and `pypdfium2` produce empty text. When OCR is later wired up, the Poppler installation must be documented in `ENVIRONMENT_NOTES.md` alongside the `pdf2image` flag.
- **`pypdfium2` text extraction is sometimes layout-lossy** compared to `pdfplumber`. The order in `extract_text_hybrid` (pdfplumber first, pypdfium2 second) is on purpose: prefer high fidelity, use the fast fallback only when the high-fidelity strategy yields nothing.
- **Doc reconciliation only touched the four most misleading references.** Older `RELEASE_NOTES.md` entries that mention `header_normalization.py` are left as historical record — they describe the state of the codebase at their date of authorship and rewriting them would erase the history. A pointer in `TROUBLESHOOTING.md` flags the phantom for future readers.

### Verification

- **455 / 455 unit tests pass** (+7 new tests in `tests/unit/test_ocr.py` vs the prior 448/448 baseline after Track 5; +1 fix for the previously failing PDF test).
- The previously failing `test_parse_resume_extracts_contact_and_name` now extracts `"John Wood"`, `"+1-925-885-5155"`, and `"help@enhancv.com"` from the real `01888170110d1ccf.pdf` fixture via `pdfplumber`.
- The 7 new `test_ocr.py` tests run the availability-flag invariants, a happy-path real-PDF extraction, both `RuntimeError` paths (no backends / empty backends via monkeypatch), and the individual private backend wrappers (`_extract_with_pdfplumber`, `_extract_with_pypdfium`). Tests that exercise unavailable backends skip cleanly via `skipif`.
- 4 doc references reconciled: `CURRENT_PROGRESS.md` Header Normalization row, `MODEL_REGISTRY.md` Header Normalization row, `IMPLEMENTATION_ROADMAP.md` line 237, `ARCHITECTURE_CHANGELOG.md` line 277. Each now points at `src/resume_parsing/parser.py` as the real implementation and links back to this decision record.

### Related Documents

`CURRENT_PROGRESS.md` (Track 6 status table, shipped), `RELEASE_NOTES.md` (2026-07-06 Track 6 Added/Fixed/Unchanged entries), `TROUBLESHOOTING.md` (full debugging trail for the missing `ocr.py` issue), `ENVIRONMENT_NOTES.md` (PDF back-end availability matrix + the optional-dependency pattern), `MODEL_REGISTRY.md` (Header Normalization row reconciled), `IMPLEMENTATION_ROADMAP.md` (Header Normalization line reconciled), `ARCHITECTURE_CHANGELOG.md` (initial-creation entry annotated with the Track 6 reconciliation note), `AI_ARCHITECTURE.md` (Resume parsing workflow — header classification step now correctly attributed to `parser.py`).
