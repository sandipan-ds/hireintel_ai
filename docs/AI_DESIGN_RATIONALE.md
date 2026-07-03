# AI Design Rationale

## Overview

This document records the AI design decisions made in the HireIntel AI platform. Each decision includes alternatives considered, tradeoffs evaluated, final rationale, and future upgrade paths.

---

## 1. Chunking Strategy

### Decision
**Primary:** Document-Aware Chunking  
**Long-section handling:** Deterministic metadata filtering (`skills_asserted contains "Python"`) — not semantic chunking

### Alternatives Considered
- **Recursive Chunking:** Fixed-size overlapping chunks regardless of document structure
- **Document-Aware Chunking:** Chunking based on resume sections (Education, Experience, Projects, etc.)
- **Semantic Chunking:** Splitting based on semantic boundaries using embeddings
- **Agentic Chunking:** Using an LLM agent to dynamically decide chunk boundaries

### Tradeoffs Evaluated

| Strategy | Structure Preservation | Retrieval Quality | Cost | Complexity |
|----------|------------------------|-------------------|------|------------|
| Recursive | Low | Medium | Low | Low |
| Document-Aware | High | High | Medium | Medium |
| Semantic | Medium | High | High | High |
| Agentic | Medium | Medium | Very High | Very High |

### Final Rationale
- Resumes have a well-defined, predictable structure (Education, Experience, Skills, etc.)
- Document-aware chunking preserves semantic coherence within each section
- Improves retrieval relevance since recruiters often query specific sections (e.g., "React experience")
- Avoids the high cost and latency of agentic or fully semantic approaches

### Future Upgrade Path
- Header Normalization (synonym lookup + fallback classification) maps heterogeneous resume headers to canonical section labels at parse time — see `AI_ARCHITECTURE.md` §9a.
- Evaluate hybrid approaches as embedding models improve (for cross-candidate pool search only, not per-candidate evidence retrieval).

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

### Decision
**Per-candidate evidence retrieval (for scoring):** Section-Routed Evidence Retrieval — exact label match on canonical sections, no embeddings, no cosine. Full section content is sent to the rubric-bound LLM judge.

**Cross-candidate pool search + resume chat:** Dense Cosine over in-memory vector index. Hybrid search (Sparse BM25 + Dense + Reranker) is a **future upgrade path for pool-level search only** — never for per-candidate scoring.

### Alternatives Considered
- **Sparse-Only (Keyword):** Fast, exact match, poor with synonyms
- **Dense-Only (Vector):** Good semantic understanding, misses exact terms
- **Hybrid (Sparse + Dense):** Balances exact matching and semantic understanding
- **Hybrid + Reranker:** Adds a reranking step to boost top-k precision

### Tradeoffs Evaluated

| Strategy | Exact Match | Semantic Match | Speed | Complexity |
|----------|-------------|----------------|-------|------------|
| Sparse-Only | Excellent | Poor | Fast | Low |
| Dense-Only | Poor | Excellent | Medium | Low |
| Hybrid | Good | Good | Medium | Medium |
| Hybrid + Reranker | Excellent | Excellent | Medium | High |

### Final Rationale
- **Section-Routed Evidence Retrieval** is the correct tool for per-candidate scoring: a single resume is a short document (1,000–3,000 tokens) that should be read, not searched. Exact label match on canonical sections guarantees no relevant chunk is silently missed and the same requirement always returns the same content.
- **Dense cosine** is the correct tool for cross-candidate pool search and resume chat, where the corpus is large and open-ended.
- Hybrid search (BM25 + Dense + Reranker) is a future upgrade for pool-level search only — it adds synonym awareness and semantic understanding for triage without sacrificing speed.
- Reranking would significantly improve precision for RAG-based answers and pool triage.
- Per-candidate scoring must never use similarity ranking — this is a hard rule in `WORKING_LOGIC.md`.

### Future Upgrade Path
- Evaluate ColBERT-style late interaction models for reranking
- Add query expansion or synonym injection to improve sparse retrieval

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
