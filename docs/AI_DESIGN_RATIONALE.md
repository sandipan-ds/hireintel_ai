# AI Design Rationale

## Overview

This document records the AI design decisions made in the HireIntel AI platform. Each decision includes alternatives considered, tradeoffs evaluated, final rationale, and future upgrade paths.

---

## 1. Chunking Strategy

### Decision (updated 2026-07-05, DEC-019)
**Primary:** Recursive Chunking  
**Defaults:** `chunk_size = 500` chars, `chunk_overlap = 50` chars  
**Long-section handling:** N/A (recursive splitter respects the configured size)
**Hyperparameters:** both `chunk_size` and `chunk_overlap` are tuned by Optuna (DEC-021)

### Alternatives Considered
- **Recursive Chunking (chosen):** Splits text recursively by separator hierarchy (`\n\n` → `\n` → `. ` → ` `) until chunks fit `chunk_size`. Fast, deterministic, no model calls.
- **Document-Aware Chunking (replaced as active 2026-07-05):** One chunk per resume section entry (Experience, Education, Project). Was the right choice when retrieval was Section-Routed (DEC-012); with regular RAG in place, uniform chunk sizes are more comparable under cosine similarity.
- **Semantic Chunking:** Splitting based on embedding-distance breakpoints. Adds an embedding call per boundary; expensive and not better for short resumes.
- **Agentic Chunking:** LLM decides boundaries. Non-deterministic, expensive, and the LLM is unreliable at boundary detection for short structured documents.

### Tradeoffs Evaluated

| Strategy | Structure Preservation | Retrieval Quality | Cost | Complexity | Notes |
|----------|------------------------|-------------------|------|------------|-------|
| Recursive (chosen) | Low | High (when θ is tuned) | Low | Low | Uniform chunks; cosine-friendly |
| Document-Aware | High | High (with section routing) | Medium | Medium | Loses value without section routing |
| Semantic | Medium | High | High | High | Embedding calls per boundary |
| Agentic | Medium | Medium | Very High | Very High | Non-deterministic |

### Final Rationale
- With Section-Routed retrieval retired (DEC-012 → DEC-017), the structural preservation that Document-Aware chunking offered is no longer required for retrieval.
- Regular RAG needs uniform-sized chunks so cosine similarity is comparing like with like.
- Recursive chunking is fast, deterministic, easy to reason about, and produces chunks whose only metadata is `text + embedding + char_span`.
- Header Normalization (the synonym table from DEC-013) is **retained for parse-time section labeling** because the structured profile (`degrees`, `certifications`, `total_experience_years`) still needs labeled sections. It is no longer the retrieval routing mechanism.

### Future Upgrade Path
- Semantic chunking can be added as a chunker variant if Optuna shows a quality gain on a specific role.
- The chunker interface (`ChunkerProtocol`) is the only contract code must depend on, so swapping chunkers is a one-line change in the pipeline factory.
- Header Normalization remains parse-time; if a future design needs section-aware retrieval again, the labels are already on the chunks.

---

## 2. Embedding Model

### Decision
**Primary:** `sentence-transformers/all-MiniLM-L6-v2` (384-dim, local, CPU-runnable)
**Alternative / upgrade:** BGE-M3 (multilingual)
**Fallback / future:** OpenAI `text-embedding-3-small`

### Alternatives Considered
- **all-MiniLM-L6-v2 (sentence-transformers):** Small (~80 MB), fast, strong English retrieval, runs on CPU
- **BGE-M3 (BAAI):** Multilingual, retrieval-optimized
- **E5 (Microsoft):** Sentence-level semantic similarity
- **Nomic Embed:** Open-source, recently released
- **OpenAI Embeddings:** Managed, high quality, but per-token API cost and data egress

### Tradeoffs Evaluated

| Model | Retrieval Quality | Cost | Latency | Multilingual | Open Source | Local Run |
|-------|-------------------|------|---------|--------------|-------------|-----------|
| MiniLM-L6-v2 | High | Free | Low (<200 chunks/sec on CPU) | No | Yes | Yes |
| BGE-M3 | High | Free | Medium | Yes | Yes | Yes |
| E5 | High | Free | Medium | Limited | Yes | Yes |
| Nomic | Medium | Free | Low | Yes | Yes | Yes |
| OpenAI | Very High | $$$ per 1M tokens | Low | Yes | No | No |

### Final Rationale
- The embedding model is on the hot path for cross-candidate pool search (JD ↔ resume triage) and resume chat (RAG) — latency and cost matter
- MiniLM-L6-v2 runs entirely on CPU and offline (no API key, no egress) — critical because resumes contain PII
- Quality on short English business text is well-validated (top of MTEB leaderboard for its size class)
- 384-dim vectors keep the in-memory index small (~6 MB for 4k chunks) — no external vector DB needed for the current scale
- Per-candidate evidence retrieval uses Section-Routed Evidence Retrieval (exact label match), not embeddings — so the embedding model is not on the scoring hot path

### Future Upgrade Path
- **BGE-M3** when we onboard multilingual candidates or non-English JDs
- **OpenAI text-embedding-3-small** if recruiters report recall@K issues and budget allows API egress
- Model swap is isolated to `src/rag/embeddings.DEFAULT_MODEL_NAME`; index must be rebuilt

---

## 3. Vector Database

### Decision
**Qdrant**

### Alternatives Considered
- **Qdrant:** Open-source, high-performance, supports filtering and hybrid search
- **ChromaDB:** Lightweight, easy to embed, developer-friendly
- **Pinecone:** Managed, scalable, but expensive for high-volume usage
- **FAISS:** Meta's library, very fast, but lacks native metadata filtering

### Tradeoffs Evaluated

| Database | Performance | Scalability | Metadata Filtering | Self-Hosted | Cost |
|----------|-------------|-------------|--------------------|-------------|------|
| Qdrant | High | High | Excellent | Yes | Free |
| ChromaDB | Medium | Medium | Good | Yes | Free |
| Pinecone | High | Very High | Good | No | High |
| FAISS | Very High | Medium | Poor | Yes | Free |

### Final Rationale
- Qdrant offers the best balance of performance, scalability, and metadata filtering
- Native support for hybrid search (sparse + dense) aligns with our retrieval architecture
- Self-hosted option gives full control over cost, security, and compliance
- Strong community and active development

### Future Upgrade Path
- Evaluate Pinecone for managed SaaS if in-house ops overhead increases
- Monitor ChromaDB as it matures for even lighter-weight deployments

---

## 4. Large Language Model (LLM)

### Decision
**Active:** OpenRouter `minimax/minimax-m3` — used for resume chat, score explanation, candidate comparison, and rubric-bound evidence scoring
**Proposed (production upgrade):** GPT-4 (OpenAI)  
**Proped fallback:** Claude (Anthropic)  
**Local/Private:** Llama 3 (Meta)

### Alternatives Considered
- **GPT-4 / GPT-4 Turbo (OpenAI):** Strong reasoning, extensive context window
- **Claude 3 (Anthropic):** Excellent long-context handling, strong instruction following
- **Gemini (Google):** Multimodal, competitive reasoning
- **Llama 3 (Meta):** Open-source, self-hostable, strong performance for size

### Tradeoffs Evaluated

| Model | Reasoning | Context Window | Cost | Privacy | Self-Hosted |
|-------|-----------|--------------|------|---------|-------------|
| GPT-4 | Excellent | 128K | High | Low | No |
| Claude 3 | Excellent | 200K | High | Low | No |
| Gemini | Strong | 1M | Medium | Low | No |
| Llama 3 | Strong | 128K | Low | High | Yes |

### Final Rationale
- `minimax/minimax-m3` via OpenRouter is the current active LLM — provides reasonable quality at low cost for resume chat, score explanations, and candidate comparisons without requiring direct API relationships with multiple providers
- GPT-4 is the proposed production upgrade for the most consistent and robust performance across parsing, summarization, comparison, and rubric-bound evidence scoring tasks
- Claude 3 is the proposed fallback for long-document processing (very long resumes)
- Llama 3 available for private or fully self-hosted deployments where data cannot leave the environment
- Using a deterministic scoring engine reduces direct dependency on LLM reasoning for rankings, mitigating cost concerns
- The LLM is restricted to extraction, summarization, comparison, rubric-bound evidence scoring, and chat — never final ranking

### Future Upgrade Path
- Evaluate GPT-5, Claude 4, or other next-generation models as they release
- Expand Llama-based deployment for fully offline, privacy-first use cases

---

## 5. Candidate Scoring Strategy

### Decision
Ship **one deterministic, evidence-backed scorer** (`src/scoring/graded_scorer.py`) that satisfies `docs/WORKING_LOGIC.md` end to end. The legacy `keyword_scorer`, `semantic_scorer`, and `hybrid_scorer` modules are deprecated; the spec explicitly states *"you don't need so many different scoring or ranking systems, just one is enough."*

The **LLM never determines final rankings** — it is restricted to extraction, summarization, comparison, and chat. Scoring is purely deterministic given the same profile + weight config.

### How It Works

For every recruiter-defined item in `data/Job descriptions/<role>/<role>_WeightConfig_filled.json`:

1. Resolve the item's synonyms from a curated dictionary (e.g. `Power BI → powerbi, pbi, dax`).
2. Search the **structured** profile in priority order: `experience.entries[*].details` → `skills` → `education.entries` → `certifications` → `projects` → `summary`. Raw-text regex is not used.
3. Detect years of experience near the matched alias (`X year(s)` / `X+ yr(s)`). For experience-style items (Core Skills, Technology & Tools, Experience), fall back to the summary's "X+ years of experience as …" line.
4. Compute the per-item raw score on the recruiter's 0-10 scale:
   * No evidence → `0`
   * Mentioned but no years measured → `importance * 0.3`
   * Years measured → `min(importance, candidate_years / expected_years × importance)`
5. Normalize the per-item score using the config's `normalized_importance` (so the candidate's total is on a 0-100 scale per `WORKING_LOGIC.md` Step 6) and aggregate.

Every item is **explainable**: the report lists the matched profile section, the exact snippet that earned the score, the years detected, and a recruiter-readable reason.

### Alternatives Considered

| Approach | Explainability | Reproducibility | Cost | Synonym handling | Bias risk |
|----------|---------------|-----------------|------|-------------------|-----------|
| Single deterministic scorer (chosen) | High (per-item evidence) | High | Low | Good (synonym dict) | Low |
| Keyword only | High | High | Low | Poor | Low |
| Semantic (cosine) only | Medium (numeric) | High | Low | Good | Low |
| LLM-direct ranking | Low | Low | High | Excellent | High |
| Hybrid (α-blend) | High (both lenses) | High | Low | Good | Low |
| ML-trained ranker | Medium | Medium | Medium | Good (depends on training) | Medium |

### Final Rationale
- **One scorer → one canonical ranking signal.** Recruiters no longer have to interpret three different numbers; the 0-100 total is directly comparable across roles (`scale_factor = 100 / max_score`).
- **Per-item reasoning is grounded in the structured profile**, so every score is auditable from the candidate's own words. This satisfies the "no black-box scoring" rule in `AGENTS.md`.
- **Years-proportional scoring** matches the recruiter's mental model ("7 of 10 years = 7/10") and rewards demonstrated depth, not just keyword presence.
- **Summary-years fallback** only applies to experience-style items, so credential-only items (BE/BTech, CBAP) are not contaminated by total-tenure numbers.

### Future Upgrade Path
- Recruiter-configurable per-item `expected_years` (currently uses `DEFAULT_EXPECTED_YEARS = 10`)
- Quality-based scoring for institutions and certification providers (Tier 1 / Tier 2 / Tier 3 institutions; vendor reputation)
- ML-trained reranker **on top of** the deterministic score for the shortlist (cross-encoder for top-50 → top-5 precision) — never as a replacement

---

## 6. Retrieval Strategy

### Decision (updated 2026-07-05, DEC-017 + DEC-018)
**Single retrieval strategy for all purposes (per-candidate scoring, cross-candidate pool search, resume chat):** Threshold-based cosine over Recursive chunks.

```
retrieve(query)  →  embed(query)  →  cosine ≥ θ  →  return all hits
                                                  (capped at max_chunks_per_query)
```

**Defaults:** `θ = 0.70`, `max_chunks_per_query = 20`. Both are Optuna hyperparameters.

**Scoring engine is unchanged** — the deterministic scorer in `src/scoring/graded_scorer.py` is still the only ranking signal. The LLM is restricted to extraction, rubric-bound scoring, and answer generation; it never sees the weight and never computes the final contribution.

### Alternatives Considered
- **Sparse-Only (Keyword):** Fast, exact match, poor with synonyms.
- **Dense-Only (Vector) + Top-K (DEC-012 predecessor):** Good semantic understanding; a fixed `top_k` doesn't adapt to query difficulty.
- **Dense-Only (Vector) + Threshold (chosen):** Same as top-K but the returned set is dynamic. More chunks when there are more matches, fewer when there are few.
- **Dense + Reranker (cross-encoder):** Adds a reranking step after threshold retrieval to boost precision on the top-N. Deferred; can be layered on later.
- **Section-Routed (DEC-012) and Sub-Query Similarity (DEC-015) (replaced):** Two strategies designed around label-based routing; both retired because the routing assumption was brittle and the engineering complexity was not justified for a small candidate pool.

### Tradeoffs Evaluated

| Strategy | Adapt to query difficulty | Calibration | Speed | Complexity |
|----------|---------------------------|-------------|-------|------------|
| Top-K (fixed) | No | Two knobs (K + filter) | Fast | Low |
| **Threshold θ (chosen)** | **Yes** | **One knob (θ) — tuned by Optuna** | **Fast** | **Low** |
| Top-K + Reranker | No (top-K caps the rerank pool) | Three knobs | Medium | Medium |
| Threshold + Reranker | Yes | Two knobs (θ + reranker model) | Medium | Medium |
| Section-Routed (replaced) | N/A | Routing table | Fast | High (two retrieval paths) |

### Final Rationale
- A single retrieval strategy across per-candidate scoring, pool search, and chat simplifies the codebase: one config, one index, one set of metrics.
- Threshold-based retrieval adapts to query difficulty without two-knob tuning. Optuna (DEC-021) calibrates `θ` against a fixed eval set.
- The deterministic scoring engine provides the explainability and reproducibility that the regular RAG pipeline sacrifices — there is no "embedding chose the wrong chunk and changed the score" failure mode at ranking time, only at evidence-collection time, and the LLM caches the evidence per `(candidate_id, req_id, hash(query, top-chunk-ids), model_name, θ)` so re-runs are stable.
- `WORKING_LOGIC.md` retains the "chunks for evidence, code for ranking" principle. The RAG pivot changes how evidence is gathered, not who decides the score.

### Future Upgrade Path
- Add a cross-encoder reranker as a post-threshold step (`rerank_top_n` from 20 → 5) if Optuna shows a faithfulness gain.
- Add MMR for diversity when many near-duplicate chunks return at high similarity.
- Per-candidate index persistence (FAISS per-candidate file) when candidate pool grows past in-memory comfort.

---

## 7. RAG Grounding Approach

### Decision
Strict Grounding — all answers must be derived from retrieved resume content. If no relevant chunk is found, respond: "Information not found in candidate documents."

### Alternatives Considered
- **Loose Grounding:** Allow general knowledge to augment retrieved content
- **Strict Grounding:** Only use retrieved content; no external knowledge
- **Citation Grounding:** Require specific quotes from source materials

### Final Rationale
- Prevents hallucination and protects candidate privacy
- Builds recruiter trust by ensuring every claim is evidence-based
- Aligns with legal and compliance requirements around candidate data

### Future Upgrade Path
- Add structured citation extraction (highlighting specific resume sections)
- Support cross-document synthesis when comparing candidates

---

## 8. Evaluation Framework

### Decision
Multi-level evaluation covering parsing, retrieval, generation, ranking, and business metrics.

### Metrics Choice
- **Parsing:** Precision, Recall, F1
- **Retrieval:** Recall@K, Precision@K, MRR, nDCG
- **Generation:** Faithfulness, Groundedness, Answer Relevancy, Completeness
- **Ranking:** Top-K Accuracy, Recruiter Agreement, Ranking Accuracy
- **Hallucination:** Hallucination Rate, Unsupported Statements
- **Business:** Screening Efficiency, Recruiter Time Saved, Recruiter Satisfaction

### Final Rationale
- End-to-end visibility into system performance is critical for an AI product
- Each metric ties directly to recruiter-facing outcomes
- Enables data-driven iteration and AI system improvement

### Future Upgrade Path
- Incorporate A/B testing framework for model and prompt changes
- Add automated regression pipelines triggered on code or tier database updates

---

## 11. Flagged (Fake / Unknown) Institute Detection

### Decision
The system automatically detects resumes listing universities/institutes that are **not found in any major ranking system** (QS, THE, ARWU) or appear to be placeholder names, and applies a **50% scoring penalty** on the education dimension.

### Alternatives Considered
- **Drop flagged institutes entirely** — Harsher, but punishes candidates who may have legitimately attended unranked regional schools.
- **No penalty** — Permits resume fraud / placeholder text to go undetected, undermining recruiter trust.
- **Manual recruiter review only** — Doesn't scale; recruiters can't review every resume manually.
- **Binary flag (visible warning, no scoring impact)** — Recruiters may ignore the warning; doesn't affect candidate ranking.
- **50% multiplicative penalty (chosen)** — Visible in score, recruiter can still override, doesn't drop candidate from pipeline entirely.

### Tradeoffs Evaluated

| Approach | Deterrent Effect | False-Positive Risk | Recruiter Workload | Scalability |
|----------|------------------|---------------------|--------------------|-------------|
| Drop entirely | High | High (legit unranked schools) | Low | High |
| No penalty | None | None | High (manual review) | Low |
| Manual review | High | Low | Very High | Low |
| Warning only | Low | None | Medium | High |
| **50% penalty (chosen)** | **Medium-High** | **Low** | **Low** | **High** |

### Final Rationale
- **Visible in score, not in pipeline** — Candidate ranks lower but is still viewable.
- **Recruiter-overridable** — The penalty shows up as `has_flagged_institute: bool` in the intelligence report so the recruiter can make the final call.
- **Evidenced** — The flag lists the exact institute names that triggered it, so the recruiter can verify.
- **Data-driven threshold** — The 13 currently flagged institutes were found by cross-referencing all 721 resumes against QS/THE/ARWU rankings.
- **Tunable** — Adding `_note: "flagged"` to a new institute is a single-line JSON edit, no code change.

### Implementation

**Detection (`src/scoring/tier_lookup.py`):**
- `is_institute_flagged(name)` — returns True if the name matches any entry with a `_note` field in `institute_tiers.json`.
- `get_flagged_institutes()` — returns all flagged entries for display.

**Profile integration (`src/resume_parsing/structured_profile.py`):**
```python
for degree in structured.degrees:
    if degree.institution and is_institute_flagged(degree.institution):
        structured.flagged_institutes.append(degree.institution)
        structured.has_flagged_institute = True
```

**Scoring penalty (`src/scoring/unified_scorer.py`):**
- Formula: `degree_match × institute_tier_points × flagged_penalty` (where `flagged_penalty = 0.5`).
- Example: 1.0 match × 0.5 tier points × 1.0 (no flag) = 5.0 → 1.0 × 0.5 × 0.5 (flagged) = 2.5.

**Flagged institutes (13 identified):**
Shodwe University, XYZ University, XZ University, Cowell University, Timmerman University, Borcelle University, Ace University, Montriad University, Really Great University, Your University, Happy College, Expensive School, Reasonably Priced School.

### Future Upgrade Path
- Auto-suggest: when an unranked institute appears in N+ resumes, auto-add it to the flagged DB.
- Recruiter dashboard: badge on candidate cards for `has_flagged_institute = true`.
- Soft vs hard flagging tiers (e.g., "definitely fake" vs "unranked but possibly legit").
- Cross-reference with government accreditation databases per country.

---

## 12. Experiment Tracking — MLflow (added 2026-07-05, DEC-020)

### Decision
Use **MLflow** (local server, SQLite backend, filesystem artifact root) as the single source of truth for retrieval / chunking / scoring experiment results. Resume PII stays on the local machine; no data leaves the host.

### Alternatives Considered
- **Weights & Biases (W&B)** — rejected. Best-in-class UI and built-in Sweeps, but cloud-based. Resume PII (candidates' names, contact info, employer history) would leave the local machine.
- **CSV / JSON manifests** — rejected. No UI, no comparison view, no way to diff runs.
- **TensorBoard** — rejected. Designed for training curves, not for retrieval/hyperparameter sweeps.

### Final Rationale
- Privacy boundary is a hard constraint: candidate resumes must not be uploaded to any cloud service.
- MLflow's `log_params` + `log_metrics` + `log_artifact` contract maps cleanly onto the project's per-run logging needs.
- Local SQLite + filesystem is zero-ops. No external services, no accounts, no rate limits.
- Integrates natively with Optuna (DEC-021) via `optuna.integration.MLflowCallback`.

### Future Upgrade Path
- Promote to MLflow's remote tracking server only if multi-machine collaboration becomes necessary.
- Add MLflow's Model Registry when the team wants to version the scoring engine itself, not just the experiment configs.

---

## 13. Hyperparameter Search — Optuna (added 2026-07-05, DEC-021)

### Decision
Use **Optuna** with a TPE sampler and a SQLite-backed study store to drive the hyperparameter search. Default to **multi-objective** optimization: maximize faithfulness, minimize `avg_chunks_returned`. The result is a Pareto front; the operator picks the operating point.

### Alternatives Considered
- **Grid search** — rejected. Combinatorial explosion; no learning between trials.
- **Random search** — rejected. Better than grid but no learning; TPE is strictly stronger.
- **Hyperopt** — rejected. Comparable capability, weaker MLflow integration.
- **W&B Sweeps** — rejected. Couples hyperparameter search to a cloud SaaS.

### Final Rationale
- Optuna's TPE sampler learns from prior trials; it doesn't waste compute on obviously-bad configurations.
- Multi-objective search prevents the "50 chunks for 1% faithfulness gain" failure mode that threshold retrieval is prone to.
- The Optuna study becomes the versioned history of "what configs did we try?"; the MLflow runs become "what did each config produce?". The two together give full reproducibility.
- The Optuna dashboard (`optuna-dashboard sqlite:///data/optuna/studies.db`) is a free, local Pareto-front view.

### Future Upgrade Path
- Add a pruner (Hyperband / Successive Halving) for early trial termination when intermediate metrics look hopeless.
- Add a constrained optimization mode (e.g. `faithfulness ≥ 0.85`) once the team has an SLA target.
- Add per-role Optuna studies (e.g. `BusinessAnalyst_threshold_v1`) when role-specific tuning is needed.

---

## 14. Per-Resume Reasoning Storage (added 2026-07-05, DEC-022)

### Decision
Replace the single `data/embeddings/llm_cache.jsonl` with a per-resume artifact tree at `data/per_candidate/<role>/<candidate_id>/reasoning/<req_id>__<query_hash>.json`. Each file stores, per (candidate, req, query), the LLM's full output: narrative reasoning, basis (cited chunks + quotes), retrieved-chunks list, and sub-scores.

**Accept the storage cost (~1–2 GB peak during an Optuna sweep) in exchange for:**
1. Eliminating LLM round-trips on re-runs of the same (candidate, req, θ).
2. Structural re-run determinism (same cache key → byte-identical sub-scores).
3. Per-(candidate, req) audit trail that the score-explanation UI can render directly.

### Alternatives Considered
- **Keep `llm_cache.jsonl` as a single-file cache** — rejected. The single-file design makes the "re-run reads from cache" claim implicit and un-inspectable. Per-resume storage makes the cache a first-class, browsable artifact.
- **Store only sub-scores, not reasoning/basis** — rejected. The whole point of DEC-022 is to make the LLM's behavior auditable per-candidate and per-req. Storing only sub-scores is just a fancier cache; storing the reasoning and basis makes the cache an audit trail.
- **External KV store (Redis, Memcached)** — rejected. Re-runs need to be reproducible from local artifacts for audit. The per-resume JSON tree is on the local filesystem; no extra service to deploy.
- **Compress the JSON files (gzip)** — deferred. Worth it once the directory exceeds 1 GB; premature now.

### Final Rationale
- **Storage is a feature, not a cost.** The per-resume reasoning tree makes the LLM's behavior auditable per-(candidate, req) — that is non-negotiable for a system whose deterministic engine is fed by an LLM judge.
- **Re-runs become free.** After the first scoring pass, every re-run of the same (candidate, req, θ) is a filesystem read. The Optuna sweep (DEC-021) re-runs the eval set dozens of times per trial; without per-resume storage, the LLM cost of an Optuna sweep is prohibitive.
- **Determinism is structural, not statistical.** Same cache key → same `sub_scores` byte-for-byte. The LLM temperature debate is moot for any (candidate, req) that has been scored.
- **PII stays local.** Per-resume reasoning files inherit the same PII policy as `data/processed/` — local-only, never logged, never uploaded.

### Future Upgrade Path
- Compress the JSON files (gzip) once `data/per_candidate/` exceeds 1 GB.
- Add a `score_explanation` field that pre-renders the recruiter-facing explanation string (cached at scoring time, no LLM call at explanation time).
- Per-role cache namespaces (e.g. `data/per_candidate/BusinessAnalyst/...` could be split into a separate volume if the dataset grows).
- A "warm cache" service that pre-loads frequently-accessed reasoning files into memory for sub-millisecond reads.

---

## 15. Per-Experiment Folder Naming (added 2026-07-05, DEC-023)

### Decision
Every MLflow run for the Recursive chunking pipeline writes its artifacts to a per-experiment folder whose name encodes the hyperparameters that produced it:

```
data/recursive_chunking_<chunk_size>_<overlap>_<top_k>_<threshold×100>/
```

**Field order is fixed (4 numeric fields):** `chunk_size`, `overlap`, `top_k`, `threshold × 100`. `x` is used for an inactive dimension (e.g., `recursive_chunking_500_50_x_70` for threshold-only mode with no `top_k` cap).

The "Active" config in `MODEL_REGISTRY.md` is symlinked at `data/active_experiment/`. Runtime code follows the symlink; it never hardcodes the hyperparameter values.

### Alternatives Considered
- **Single `data/chunks/` folder for all Recursive experiments** — rejected. Conflates artifacts of distinct experiments; cache invalidation becomes ambiguous; the folder name carries no information about which experiment it serves.
- **Hash-based folder names (e.g., `data/recursive_chunking_<sha256[:8]>/`)** — rejected. Self-documenting beats self-identifying. The folder name is the recruiter's first hint at what the experiment tested; `500_200_5_50` is more useful than `a3f2b1c8`.
- **Sub-folders per MLflow run (e.g., `data/recursive_chunking/<run_id>/`)** — rejected. Same-config experiments should share artifacts, not duplicate them. The hyperparameter tuple is the natural grouping key.
- **Prefix letters in the folder name (e.g., `c500_o200_k5_t50`)** — rejected by user preference. Numeric form is shorter and the field order is documented.
- **`x` placeholder for unused modes** — accepted. Cleaner than a sentinel value (e.g., `0` or `-1`) and reads as "this dimension is not used in this experiment".

### Final Rationale
- **Folder name is the self-documenting identifier of the experiment.** The recruiter and the engineer both need to read the folder name and know "this is the experiment with chunk_size=500, overlap=200, top_k=5, threshold=0.50". A short hash would force them to look up `metadata.json` first.
- **Same-config runs share a folder.** If two MLflow runs have the same hyperparameters, their artifacts are byte-identical (chunks, index, cache), so sharing is correct, not redundant. Trial uniqueness lives in the MLflow run ID and Optuna trial ID (logged in `metadata.json`), not in the folder name.
- **`data/active_experiment` symlink is the runtime entry point.** Code does not hardcode `data/recursive_chunking_500_50_10_70/`; it follows the symlink. This makes promoting a new Active config a one-line symlink operation.
- **Active architecture is Recursive Chunking.** The user explicitly stated "our new architecture should be based on recursive_chunking, so all the new codes should follow that". All new pipeline code targets the `data/recursive_chunking_*` folder convention; the legacy `data/document_aware_chunking/` folder is read-only after M0.5e.

### Future Upgrade Path
- Compress per-experiment artifacts (gzip) once `data/recursive_chunking_*` exceeds 10 GB total.
- Auto-archive experiments older than 30 days to `data/archive/<study_name>/`.
- Add a `compare_experiments.py` CLI that reads `metadata.json` from N folders and produces a side-by-side table.
