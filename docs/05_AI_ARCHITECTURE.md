# AI Architecture

> **Source of truth for the candidate evaluation contract, scoring rules, and
> ranking discipline:** [`WORKING_LOGIC.md`](WORKING_LOGIC.md). This document
> is the source of truth for AI workflows (chunking, embedding, retrieval,
> RAG). For "what is implemented today vs what's planned", see
> [`CURRENT_PROGRESS.md`](CURRENT_PROGRESS.md).

## Overview

This document is the source of truth for all AI-related architecture in the HireIntel AI platform. It defines the end-to-end workflows, chunking strategies, embedding pipelines, retrieval mechanisms, and RAG-based interactions.

---

## 1. Resume Ingestion Workflow

**Purpose:** Accept and store resume files, triggering downstream parsing and embedding.

```text
[Recruiter Upload] -> [API Gateway] -> [Resume Service] -> [Object Storage]
                                         |
                                         v
                                   [Message Queue] -> [Parsing Worker]
```

**Steps:**
1. Recruiter uploads resume (PDF, DOCX, or plain text)
2. File is validated and stored in Object Storage
3. A parsing job is enqueued asynchronously
4. Parsing Worker picks up the job and triggers the Resume Parsing Workflow

---

## 2. Resume Parsing Workflow

**Purpose:** Extract structured candidate profiles from unstructured resumes.

```text
[Raw Resume] -> [Parser Engine] -> [Structured Profile] -> [Document Database]
                                      |
                                      v
                               [Embedding Service]
                                      |
                                      v
                               [Vector Database]
```

**Techniques Used:**
- Document parsing (PyPDF2, python-docx)
- NLP-based section segmentation
- LLM-based information extraction (GPT, Claude, Gemini)

**Extracted Fields:**
- Candidate Name
- Contact Information
- Education (degree, institution, year)
- Skills (technical and soft)
- Certifications
- Languages Known
- Work Experience (company, role, duration, responsibilities)
- Projects (title, description, technologies)
- Technology Stack
- Leadership Experience

**Output:** Structured JSON profile persisted in the Document Database.

---

## 2a. Structured Candidate Profile Extraction

**Purpose:** Extract exact, unambiguous facts directly from the cleaned resume as a deterministic structured record — separate from chunking and separate from retrieval.

Per `WORKING_LOGIC.md` ("Structured Candidate Profile Extraction"), facts that are exact and unambiguous — a degree name, a certification title, total years of experience — are read directly from the structured profile rather than re-derived through search. Similarity search can miss or under-rank a chunk containing an exact fact; a structured lookup cannot.

```text
[Cleaned Resume] -> [Structured Profile Extractor] -> [Structured Profile Record]
                                                         (degrees, certs, total
                                                          experience, companies,
                                                          dates)
```

**Extracted Fields:**
- Degrees and institutions
- Certifications
- Total experience (years)
- Companies and roles
- Employment dates

**Key Rule:** Requirements that are purely factual (e.g. "Does the candidate hold a Bachelor's degree?") may be answered entirely from this structured profile, bypassing Section-Routed Evidence Retrieval. Requirements that require interpretation (e.g. "How deep is the candidate's Power BI expertise?") still rely on Section-Routed Evidence Retrieval and rubric-bound LLM evidence scoring (see §5).

**Output:** Structured profile record stored alongside the chunked sections. This record is the input for code-only scoring of total experience, institute tier, and certification tier.

---

## 3. Job Description (JD) Processing Workflow

**Purpose:** Analyze and extract structured hiring requirements from job descriptions, and refuse to score until ambiguous items are clarified.

```text
[JD Upload] -> [Parser Engine] -> [Structured Requirements]
                                            │
                                            ▼
                                  [Clarification Classifier]
                                  Green | Yellow | Red
                                            │
                                            ▼
                                  [clarifications.json]
                                            │
                                            ▼
                                  [Recruiter UI: answer Yellow + Red]
                                            │
                                            ▼
                                  [Scoring Policy (all Green)]
```

**Extracted Information:**
- Required Skills
- Preferred Skills
- Required Experience (years, role type) — **per-skill expected_years** is surfaced as a recruiter question when missing
- Education Requirements — **degree equivalencies** are surfaced when ambiguous
- Certifications — **provider reputation tier** is surfaced when ambiguous
- Industry Experience
- Leadership Requirements
- Technology Stack
- Location / Remote preferences

**Clarification Rules (per `WORKING_LOGIC.md` Step 0):**

* **Green** — Clear and measurable. Enters the scoring policy directly.
* **Yellow** — Partially defined. Platform must auto-generate a follow-up question (e.g. "What minimum Tableau experience qualifies as 'strong'?") and block the scoring policy until answered.
* **Red** — Missing critical info. Hard block until clarified.

**Output:** Structured JD object stored and linked to the employer's account, plus `clarifications.json` listing open questions. Scoring policy is locked only when every item is Green.

---

## 4. Recruiter Weight Configuration Workflow

**Purpose:** Allow recruiters to define scoring priorities for a specific role.

```text
[Extracted JD Requirements] -> [Present to Recruiter] -> [Recruiter Assigns Weights]
                                                               |
                                                               v
                                                    [Scoring Policy Generated]
                                                               |
                                                               v
                                                    [Persist in Document Database]
```

**Components of a Scoring Policy:**
- Percentage-based weights for each requirement (0–100%, must sum to exactly 100%)
- Objective vs. subjective metric weighting
- Custom scoring rules (e.g., bonus for product company experience)

**Validation:**
- Total weights must sum to 100%
- Weights must be non-negative
- Minimum one objective metric is required

---

## 5. Candidate Evaluation Workflow

**Purpose:** Evaluate each candidate against the recruiter's scoring policy using evidence from their resume.

Per `WORKING_LOGIC.md` ("Fundamental Rule") and the deprecation note in
`AI_DESIGN_RATIONALE.md` §5, the platform ships **one** deterministic scorer.
Multiple competing ranking systems are explicitly disallowed.

The scoring engine operates in **two modes**, both of which compute weight
application and final aggregation in code — never in the LLM:

```text
[Structured Profile] + [Chunked Sections] + [Scoring Policy (weights + expected_years)]
                              │
                   ┌──────────┴──────────┐
                   ▼                     ▼
         Code-Only Scoring       Rubric-Bound LLM Evidence Scoring
         (total experience,      (skill depth, relevant experience,
          institute tier,         project complexity, domain expertise)
          certification tier)              │
                   │                     ▼
                   │           Section-Routed Evidence Retrieval
                   │           (full mapped section content → LLM judge
                   │            with recruiter-defined rubric)
                   │                     │
                   └──────────┬──────────┘
                              ▼
                   Weighted Aggregation (Code)
                              │
                              ▼
               data/scores/graded/<role>_ranked.json
```

**Evaluation Dimensions by Scoring Mode:**

| Dimension | Mode | Status |
|---|---|---|
| Skill Presence | Code-only (synonym match) | ✅ Active |
| Skill Years (total) | Code-only (regex years detection) | ✅ Active |
| Skill Depth / Project Relevance | Rubric-bound LLM | ⬜ Planned |
| Relevant Experience (same-role, industry, leadership) | Rubric-bound LLM | ⬜ Planned |
| Total Experience (years) | Code-only (structured profile) | ✅ Active |
| Education (Degree Match) | Code-only (structured profile) | ✅ Active |
| Education (Institute Tier) | Code-only (tier lookup) | ⬜ Planned |
| Certification (Match) | Code-only (synonym match) | ✅ Active |
| Certification (Provider Tier) | Code-only (tier lookup) | ⬜ Planned |
| Language Capabilities | Code-only (alias match) | 🟡 Partial |
| Communication Quality | Rubric-bound LLM | ⬜ Planned |
| Resume Organization | Rubric-bound LLM | ⬜ Planned |

### 5.1 Code-Only Scoring (`src/scoring/graded_scorer.py`)

Used wherever a requirement is fully measurable without judgment: total
years of experience (linear formula), institute tier (lookup table),
certification tier (lookup table). No LLM is involved at all.

For every recruiter-defined item handled by this mode:

1. **Expand the item name** into a synonym dictionary (e.g. `Power BI → powerbi, pbi, dax, power query`), compiled as word-boundary regex patterns.
2. **Search the structured profile** in priority order: `experience.entries[*].details` → `skills` → `education.entries` → `certifications` → `projects` → `summary`. Raw-text regex is never used.
3. **Detect years of experience** near the matched alias (`X year(s)` / `X+ yr(s)` within 80 chars). For experience-style items, fall back to the summary's "X+ years of experience as …" line.
4. **Compute the per-item raw score** on the recruiter's percentage scale:

    * **No evidence** → `0`
    * **Mentioned, no years measured** → `weight_percentage × 0.3` (partial credit)
    * **Years measured** → `min(weight_percentage, candidate_years / expected_years × weight_percentage)` (proportional)
5. **Normalize to 0–100** using the sum of all weight percentages (which must equal 100%).

### 5.2 Rubric-Bound LLM Evidence Scoring

Used wherever genuine judgment is required: skill depth, project complexity,
relevant/same-role/leadership experience, domain expertise. The LLM reads the
full content of the section(s) that the requirement maps to (see
**Section-Routed Evidence Retrieval**, §11a) and maps it onto a
recruiter-defined point scale — never onto a free-form label.

**Key constraints (per `WORKING_LOGIC.md`):**
- The LLM must **not** see the requirement's weight while scoring evidence.
- The LLM must **never** compute the final weighted contribution.
- The LLM scores strictly against a recruiter-defined rubric — never against its own internal notion of "Advanced" or "Strong."
- Weight application and final score aggregation are always computed in code.

**Workflow per requirement:**

```text
[Requirement] -> [Section Mapping (fixed table)]
                          │
                          ▼
           [Fetch all chunks tagged with mapped section(s)]
           (exact label match — no embeddings, no cosine)
                          │
                          ▼
           [LLM Judge: extract relevant evidence, then score
            against recruiter-defined rubric]
                          │
                          ▼
           [Structured sub-scores (0.0–1.0 per sub-question)]
                          │
                          ▼
           [Code: weight × sub-score → weighted contribution]
```

**Extraction before scoring:** The LLM is asked to first extract what's
relevant from the mapped section(s) (e.g. "list every role where Python
appears, with dates"), then score against the rubric. This keeps the read
systematic rather than holistic, and prevents the model from being influenced
by content outside the mapped section.

**Deterministic metadata filtering:** If a section is unusually long (a senior
candidate's multi-page Experience history), deterministic metadata filtering
(`skills_asserted contains "Python"`) narrows it further — still an exact
filter, not a similarity rank.

**See `PROMPT_LIBRARY.md` RUBRIC-SCORE-001 for the production prompt spec.**

### 5.3 Why Years-Proportional Scoring

A candidate with 1 year of Power BI does not receive the same score as a candidate with 6 years. The score is proportional to `candidate_years / expected_years × weight_percentage`, capped at the item's `weight_percentage`. The default `expected_years = 10` (configurable per item) means recruiters can tune the depth required for any criterion.

### 5.4 Output Contract

```json
{
  "candidate_id": "cand_xxx",
  "role": "Business Analyst Lead",
  "total_raw": 56.8,
  "total_max": 100.0,
  "total": 56.8,
  "rank": 1,
  "categories": [
    {
      "name": "Core Skills",
      "score": 21.5,
      "max_score": 45.0,
      "items": [
        {
          "category": "Core Skills",
          "item_name": "Requirements Gathering",
          "description": "...",
          "weight_percentage": 12,
          "expected_years": 6,
          "matched": true,
          "years_detected": 5.0,
          "raw_score": 10.0,
          "score": 10.0,
          "section": "experience",
          "snippet": "Gather business requirements and translate them into user stories.",
          "reason": "5 year(s) of Requirements Gathering experience identified in the experience section — below the recruiter target of 6 year(s)."
        }
      ]
    }
  ]
}
```

Every score carries: matched boolean, years detected, **matched profile section**, **exact snippet that earned the score**, and a recruiter-readable reason. Recruiters can click the snippet and see the original resume text.

### 5.5 Legacy Triad (Retired)

The legacy `keyword_scorer / semantic_scorer / hybrid_scorer` modules were
removed 2026-06-19. The CLI accepts `--strategy keyword|semantic|hybrid` only
as a deprecated alias that prints a `DeprecationWarning` and forwards to
`graded`. See `ARCHITECTURE_CHANGELOG.md` for the file-by-file change list.

---

## 6. Candidate Ranking Workflow

**Purpose:** Rank candidates deterministically based on evaluation scores.

```text
[All Evaluation Reports] -> [Single Scorer Normalization] -> [Ranked List]
data/scores/graded/<role>_ranked.json
```

**Key Rules (per `WORKING_LOGIC.md`):**
- LLM does **not** directly determine rankings — ever.
- Rankings are derived from the single deterministic Scoring Engine.
- Tie-breaks: by matched-item count, then by raw score, then by candidate_id (deterministic).
- Rankings are reproducible given the same inputs.

**Output:** `data/scores/graded/<role>_ranked.json` — sorted candidate list with per-item scores, sections, snippets, and reasons.

---

## 7. Candidate Comparison Workflow

**Purpose:** Enable side-by-side or question-driven comparison of shortlisted candidates.

```text
[Recruiter Query] -> [Query Analysis] -> [Retrieve Candidate Profiles] -> [LLM Comparison]
```

**Examples:**
- Who has more React experience?
- Compare leadership experience across candidates.
- Why is Candidate A ranked higher than Candidate B?

**Grounding Constraint:** All comparisons must cite evidence from structured resume fields.

---

## 8. Summarization Workflow

**Purpose:** Generate recruiter-friendly summaries of candidates.

```text
[Structured Profile] -> [Summarization Engine] -> [Natural Language Summary]
```

**Components:**
- Highlight key strengths aligned with job requirements
- Flag potential gaps or concerns
- Cite specific evidence for claims

---

## 9. Chunking Architecture

**Purpose:** Divide resumes into uniform chunks for regular RAG retrieval.

**Primary Strategy (updated 2026-07-05, DEC-019): Recursive Chunking**

```text
[Cleaned Resume Text]
        ↓
[RecursiveCharacterTextSplitter]
   separators = ["\n\n", "\n", ". ", " "]
   chunk_size    = 500 chars       (Optuna hyperparameter)
   chunk_overlap = 50 chars        (Optuna hyperparameter)
        ↓
[Chunks] → [Embedding Model] → [Vector Index]
```

**Why Recursive (not Document-Aware):** With Section-Routed retrieval retired (DEC-012 → DEC-017), uniform-sized chunks are more comparable under cosine similarity. Recursive chunking is fast, deterministic, and produces chunks whose only metadata is `text + embedding + char_span`.

**Chunks are emitted as JSONL files at `data/chunks/<role_bucket>/<candidate_id>.jsonl`.** Each record contains:

```json
{
  "chunk_id": "cand_xxx__14",
  "candidate_id": "cand_xxx",
  "role_bucket": "BusinessAnalyst",
  "source_file": "...",
  "chunk_index": 14,
  "text": "Senior Data Scientist @ Acme | 2020 - Present. Built ML pipelines in Python...",
  "char_span": [800, 1300],
  "section_type": "experience"        // soft tag, retained from Header Normalization
}
```

The `char_span` references offsets into the profile's `raw_text`, so RAG answers can cite the exact substring.

**Header Normalization is retained for parse-time section labeling** because the structured profile (`degrees`, `certifications`, `total_experience_years`) still needs labeled sections. It is no longer the retrieval routing mechanism.

**Legacy chunker** (`DocumentAwareChunker`, the old behavior) is retained under that name in `src/rag/chunker.py` for one release as a migration aid. New code should call `RecursiveChunker`.

### 9a. Header Normalization

**Purpose:** Resumes do not use consistent section names: "Skills" vs "Technical Skills" vs "Core Competencies"; "Experience" vs "Employment History" vs "Career History". Routing a JD requirement to "the Education section" only works if every resume's education-like header maps to the same canonical label.

Per `WORKING_LOGIC.md` ("Header Normalization"), this is handled **once per resume, at parse time** — not once per requirement, and not by similarity ranking.

**Canonical Sections:**

```text
Personal_Info | Education | Experience | Projects
| Skills | Certifications | Languages
```

**Layer 1 — Synonym Lookup (free, deterministic):**

A maintained table catches the large majority of headers with no model call:

```text
"work experience" | "employment history" | "professional experience"
  | "job experience" | "career history"          → Experience
"skills" | "technical skills" | "core competencies"
  | "technical proficiencies"                    → Skills
"education" | "academic background"
  | "academic qualifications"                    → Education
"certifications" | "licenses" | "credentials"
  | "licenses & certifications"                  → Certifications
```

**Layer 2 — Fallback Classification (one model call, only for unmatched headers):**

If a header doesn't match the table — or a resume has no headers at all and uses free-flowing paragraphs — one classification call per resume assigns it to a canonical section. This is a discrete classification into a fixed set of 7 buckets, not a similarity score, so it is deterministic-enough and auditable: the system logs which header (or absence of one) produced which label and with what confidence.

**Multi-Tag Chunks:**

Content does not always respect section boundaries even after labeling — a bullet under "Projects" can describe genuine professional work; a line under "Experience" can describe a certification earned on the job. A chunk is allowed to carry more than one section tag when its content genuinely spans categories, rather than being forced into a single bucket.

---

## 10. Embedding Architecture

**Purpose:** Generate vector representations for resume chunks to enable threshold-based retrieval.

**Pipeline:**
```text
[Resume Chunk] -> [Embedding Model] -> [Vector] -> [Vector Index]
```

**Embedding Models Used:**
- Primary: `sentence-transformers/all-MiniLM-L6-v2` (384-dim, ~80 MB, CPU-runnable, no API key)
- Alternative / future: BGE-M3 (multilingual) — see `MODEL_REGISTRY.md` for upgrade path
- Experiment candidates for Optuna: MiniLM-L6-v2, `bge-small-en`, `bge-m3`

**Processing:**
- Chunks are batched (batch size 64) for efficient inference
- Embeddings are L2-normalized so dot product == cosine similarity
- Vectors are persisted to `data/embeddings/index.npz` (compressed numpy)
- Chunk metadata is persisted to `data/embeddings/chunks.jsonl`
- Re-built on demand via `python -m src.rag.build_index` (re-runs as part of every Optuna trial that changes `chunk_size` or `chunk_overlap`)

---

## 11. Retrieval Architecture

**Purpose:** Retrieve resume content for all retrieval purposes — per-candidate scoring, cross-candidate pool search, and resume chat — using a single threshold-based pipeline.

**Strategy (updated 2026-07-05, DEC-017 + DEC-018):**

```text
[Query] -> [Embed] -> [Cosine ≥ θ over data/embeddings/index.npz] -> [All hits, capped at max_chunks_per_query]
```

**Configuration:**
- Threshold θ: default `0.70` (Optuna hyperparameter)
- `max_chunks_per_query`: `20` (safety cap; warn on hit)
- Similarity metric: cosine
- Optional `role_bucket` and `candidate_id` filters on retrieval

**Per-query flow:**

```python
def retrieve(query: str, *, candidate_id: str | None = None,
             role_bucket: str | None = None) -> list[Chunk]:
    q_vec = embed(query)
    sims  = index.cosine(q_vec, candidate_id=candidate_id, role_bucket=role_bucket)
    hits  = [(s, c) for s, c in zip(sims, index.chunks) if s >= THRESHOLD]
    hits.sort(reverse=True)
    if len(hits) > MAX_CHUNKS_PER_QUERY:
        log.warning("threshold cap hit: %d > %d", len(hits), MAX_CHUNKS_PER_QUERY)
        return hits[:MAX_CHUNKS_PER_QUERY]
    return hits
```

**Used in three contexts:**

1. **Per-candidate evidence retrieval for scoring** — `candidate_id` filter applied; chunks for that one candidate are ranked; the rubric-bound LLM judge (§5.2) scores against anchored scales.
2. **Cross-candidate pool search** — no `candidate_id` filter; used by JD matching (triage) to narrow a large applicant pool before the full per-candidate scoring pass.
3. **Resume Chat** — `candidate_id` filter applied; recruiter questions about a candidate answered via RAG (§12).

**Critical constraint:** The retrieval quality is not the final ranking quality. The deterministic scoring engine in §5 is the **only** ranking signal. The LLM is restricted to extraction, rubric-bound scoring, and answer generation; it never sees the weight and never computes the final contribution.

---

## 12. RAG Workflow

**Purpose:** Answer recruiter questions with grounded, resume-based information, and explain scores using cached rubric reasoning.

### 12a. Score Explanation (Cached Reasoning First)

Per `WORKING_LOGIC.md` ("Score Explanation"), when a recruiter asks "why did
this candidate receive this score?", the system returns the **rubric
sub-scores and cited evidence stored at scoring time** — this is the default
path. It keeps explanations fast, cheap, and guaranteed consistent with the
original score.

```text
[Recruiter asks "why"] -> [Return cached rubric sub-scores + cited evidence]
```

If the recruiter asks a follow-up that goes beyond what was stored, the system
re-fetches the mapped section(s) for that requirement (Section-Routed Evidence
Retrieval, §11a) and generates a fresh answer grounded in them. Because every
requirement's evidence already comes from a fixed, fully-included section
rather than a similarity-ranked subset, a follow-up re-fetch always returns
the same content as the original scoring pass.

See `PROMPT_LIBRARY.md` SCORE-EXPLAIN-001.

### 12b. Resume Chat (RAG)

```text
[Recruiter Question] -> [Dense Cosine Retrieval (§11b)] -> [Context Assembly] -> [Prompt Construction] -> [LLM]
                                                                                                    |
                                                                                                    v
                                                                                            [Grounded Answer]
```

**Prompt Construction:**
- System prompt: "You are a helpful recruiting assistant. Answer based ONLY on the provided context."
- User prompt includes: question + top-k retrieved chunks

**Constraints:**
- If no relevant chunk is found, respond: "Information not found in candidate documents."
- Never hallucinate or infer beyond the provided context
- Cite specific resume sections when applicable

---

## 13. Hiring Recommendation Workflow

**Purpose:** Generate transparent, evidence-based hiring recommendations.

```text
[Ranked Candidates] + [Evaluation Reports] -> [LLM Recommendation Engine] -> [Hiring Recommendation]
```

**Output Includes:**
- Recommended candidate(s) with ranking justification
- Key qualifications and potential concerns
- Comparison with other top candidates
- Explicit statement of evidence sources (e.g., "Based on 5 years of relevant experience...")

**Constraints:**
- Recommendations must not contradict the deterministic ranking
- All claims must be supported by extraction results
- Uncertainty must be clearly communicated

---

## 14. AI Component Interaction Summary

```text
                                ┌──────────────────────┐
                                │   Recruiter (UI)     │
                                └──────────┬───────────┘
                                           │
              ┌────────────┬───────────────┼───────────────┬────────────┐
              │            │               │               │            │
              ▼            ▼               ▼               ▼            ▼
        [JD Upload] [Weight Config]  [Resume Upload]  [Evaluations]  [Chat/Compare]
              │            │               │               │            │
              ▼            ▼               ▼               ▼            ▼
        [JD Parser]  [Policy Store]  [Resume Parser]  [Scoring Engine]  [RAG Engine]
              │            │               │               │            │
              ▼            ▼               ▼               ▼            ▼
        [Vector DB]  [Doc DB]       [Vector DB]    [Doc DB]       [Vector DB]
```

All AI workflows are modular, logged, and designed to be explainable and auditable.
