# Candidate Evaluation and Scoring System

## Core Principle

This is the most important component of the platform.

The system must not behave like a generic ATS, keyword matcher, resume parser, or simple RAG chatbot.

The primary purpose of the platform is to provide:

* Objective candidate evaluation
* Recruiter-controlled scoring
* Explainable rankings
* Evidence-based recommendations
* Transparent hiring decisions

All rankings must be reproducible, auditable, and explainable.

The platform must never rely on black-box AI scoring.

If any requirement is unclear, the system must ask for clarification instead of making assumptions.

Where an LLM is used to read evidence (for example, judging skill depth or project complexity), it must score strictly against a recruiter-defined rubric — never against its own internal notion of what "Advanced" or "Strong" means. The LLM must not see a requirement's weight while scoring evidence against that rubric, and it must never perform the final weighted aggregation across requirements. Weight application and final score aggregation are always computed in code. See **Scoring Rubrics** below.

---

# High-Level Workflow

```text
JD Upload
        ↓
JD Validation & Clarification
        ↓
Requirement Extraction
        ↓
Green / Yellow / Red Classification
        ↓
Recruiter Clarification
        ↓
Requirement Finalization
        ↓
Recruiter Weight Assignment
        ↓
Scoring Policy Generation
        ↓
Requirement → Section Mapping
(fixed table: which canonical section(s) each requirement depends on)

Resume Upload
        ↓
Resume Parsing
        ↓
Resume Cleaning
        ↓
        ├─────────────────────┐
         ↓                     ↓
Structured Profile     Recursive Chunking
Extraction              (uniform 500-char chunks)
(degrees, certs,                ↓
 total experience,      Embedding (MiniLM-L6-v2)
 companies, dates)              ↓
         |               Vector Index
         |                        ↓
          |              Threshold-based Retrieval
          |              (cosine ≥ θ over Recursive chunks,
         |               all hits returned, capped at 20)
         |                        ↓
          |              Evidence per Requirement
         └────────────┬───────────┘
                      ↓
            Evidence Extraction
                      ↓
        Candidate Intelligence Report
                      ↓
   Deterministic Scoring Engine
   (code formulas + rubric-bound LLM evidence scoring)
                      ↓
            Candidate Ranking

Candidate Intelligence Report
+
Cached Rubric Reasoning
+
Resume Sections (full content, on demand)
        ↓
Score Explanations
        ↓
Candidate Comparison
        ↓
Recruiter Chat
        ↓
Hiring Recommendations
```

---

# Fundamental Rule

The platform separates:

## Candidate Scoring

Performed using:

* Recruiter-defined weights
* Structured candidate information
* Deterministic formulas
* Objective evidence

No LLM should directly determine candidate scores.

This separates into two modes:

**Code-only scoring** — used wherever a requirement is fully measurable: years of experience (linear formula), institute tier (lookup table), certification tier (lookup table). No LLM is involved at all.

**Rubric-bound LLM evidence scoring** — used wherever genuine judgment is required: skill depth, project complexity, domain expertise. The LLM reads the evidence retrieved by the threshold-based retrieval pipeline (cosine ≥ θ, all hits, capped at `max_chunks_per_query`) and maps it onto a recruiter-defined point scale (years used, project complexity, frameworks/tools, ownership level) — never onto a free-form label. The LLM does not see the requirement's weight, and never computes the final weighted contribution.

In both modes, weight application and the final aggregated score are computed by code, never by the LLM. Full formulas are defined in **Scoring Rubrics**.

## Candidate Explanations

Performed using:

* Cached rubric reasoning from scoring time (default)
* Threshold-based retrieval over the candidate's chunks (for follow-up questions)
* Candidate Intelligence Report

LLMs explain scores.

LLMs do not generate scores.

---

## Scoring architecture overview

The system should process each candidate in the following order:

1. **Normalize the JD** into canonical requirement blocks.
2. **Decompose each requirement block** into meaningful sub-questions.
3. **Collect resume evidence** relevant to each requirement block.
4. **Send the evidence to the LLM judge** with a fixed rubric.
5. **Receive structured sub-scores** from the LLM.
6. **Compute final requirement scores in code**.
7. **Aggregate total candidate score in code**.
8. **Store the full scoring trace** for auditability.

---

## Requirement blocks

A JD should be transformed into a small number of non-overlapping requirement blocks. Each requirement is assigned a unique REQ-ID and categorized into one of five groups.

**Categories:**
1. **Core Skills** — Essential technical skills required for the role
2. **Preferred Skills** — Nice-to-have skills that add value
3. **Experience** — Years of experience and role-level requirements
4. **Education & Certifications** — Degree and certification requirements
5. **Key Responsibilities** — Evidence of capability through demonstrated responsibilities

**Example (Business Analyst Lead):**

| REQ-ID | Requirement Name | Category | Type |
|--------|------------------|----------|------|
| REQ-001 | Business Analysis & Requirement Gathering | Core Skill | Required |
| REQ-002 | SQL for Data Validation & Analysis | Technology Skill | Required |
| REQ-003 | Process Mapping & Business Process Improvement | Core Skill | Required |
| REQ-004 | Stakeholder Management & Communication | Core Skill | Required |
| REQ-005 | Documentation, User Stories & Acceptance Criteria | Core Skill | Required |
| REQ-006 | Business Intelligence Tools (Power BI, Tableau, Looker) | Preferred Skill | Preferred |
| REQ-007 | CRM, ERP, or Data Warehouse Systems | Preferred Skill | Preferred |
| REQ-008 | Agile & Scrum Methodologies | Preferred Skill | Preferred |
| REQ-009 | Product-Led or Digital Transformation Environment | Preferred Skill | Preferred |
| REQ-010 | 6+ Years Business Analysis or Related Domain | Experience | Required |
| REQ-011 | Leadership or Senior Analyst Role | Experience | Required |
| REQ-012 | Cross-Functional Team Collaboration | Experience | Required |
| REQ-013 | Bachelor's Degree (BA/IS/CS/Related) | Education | Required |
| REQ-014 | Advanced Degree or Certification (CBAP/PMI-PBA) | Certification | Preferred |
| REQ-015 | Demonstrated Responsibility Execution | Responsibilities | Required |

**Total: 15 requirements (12 Required, 3 Preferred)**

This prevents double counting and keeps the scoring logic interpretable.

---

# Step 0: Job Description Validation and Clarification

Before weight collection begins, the system must analyze the uploaded JD.

The system must identify:

1. Explicit requirements
2. Ambiguous requirements
3. Missing requirements

The system must not silently assume critical information.

---

## Requirement Classification

Every requirement must be classified.

### Green Requirements

Clear and measurable.

Examples:

* Python with 5+ years experience
* SQL
* Power BI
* MBA
* AWS Certification

These can immediately enter the scoring framework.

---

### Yellow Requirements

Partially defined or ambiguous.

Examples:

* Strong Python Skills
* Good Communication
* Relevant Degree
* Preferred Certification
* Experience with Modern Tools

The system must ask follow-up questions.

Example:

Strong Python Skills

Questions:

* What minimum experience qualifies as strong?
* What proficiency level qualifies as strong?

---

### Red Requirements

Missing critical information.

Examples:

* Experience requirement not specified
* Education requirement not specified
* Location requirement not specified
* Certification requirement not specified

These require clarification before scoring.

---

# Requirement Clarification Logic

The platform must identify all unresolved requirements before continuing.

Example:

JD:

```text
Strong Python Skills
Relevant Degree
Cloud Certification Preferred
```

System Output:

✅ Clear Requirements

* Python
* Cloud Technologies

🟡 Clarification Required

* Strong Python Skills
* Relevant Degree
* Cloud Certification

Questions:

* What minimum Python experience is expected?
* Which degrees are acceptable?
* Which certifications qualify?

---

# Degree Clarification Logic

Educational equivalence is role dependent.

The system must never assume:

```text
All Bachelor Degrees are equivalent.
```

Example:

Business Analyst

Possible equivalents:

* BBA
* BCom
* Economics
* Statistics

Mechanical Engineer

Possible equivalents:

* Mechanical Engineering
* Production Engineering
* Industrial Engineering

The recruiter must confirm acceptable alternatives.

---

# Experience Clarification Logic

When a skill is listed but experience requirements are missing:

Example:

Skills:

* Tableau
* Handling Projects
* Team Management

Questions:

* Expected Tableau experience?
* Any specific projects? Will only related project experience count? If yes then how many years of minimum experience?
* Expected experience in a leadership role?

The system must not assume.

---

# Clarification Completion Requirement

After clarification:

Generate:

## Clear Requirements

Ready for scoring.

## Remaining Unresolved Requirements

Still ambiguous.

Example:

```text
Resolved:
8

Unresolved:
2
```

Display unresolved items.

Allow the recruiter to:

* Answer remaining questions
* Proceed anyway

If proceeding, record assumptions explicitly.

---

# Requirement Finalization

After clarification, create a normalized requirement specification.

Example:

Before:

```text
Strong Python Skills
Relevant Degree
Cloud Certification Preferred
```

After:

```text
Python:
5+ Years

Degree:
BTech / BE / MCA

Certification:
AWS Solutions Architect Associate
```

This becomes the final scoring policy input.

---

# Recruiter Weight Assignment

The recruiter assigns importance weights to each requirement.

**Scale:** Percentage (0-100%)

**Constraint:** All percentages must sum to exactly **100%**

**Categories:**
- Core Skills (Required)
- Preferred Skills (Optional but valued)
- Experience (Required)
- Education & Certifications (Required/Preferred)
- Key Responsibilities (Required)

**Example:**

```
Core Skills (Required):
├─ Business Analysis & Req Gathering    → 12%
├─ SQL                                  → 8%
├─ Process Mapping                      → 7%
├─ Stakeholder Management               → 10%
└─ Documentation & User Stories         → 8%
   Subtotal: 45%

Preferred Skills:
├─ BI Tools (Power BI, Tableau)         → 6%
├─ CRM/ERP/Data Warehouse               → 5%
├─ Agile & Scrum                        → 4%
└─ Product-Led / Digital Transformation → 3%
   Subtotal: 18%

Experience (Required):
├─ 6+ Years BA Experience               → 12%
├─ Leadership or Senior Analyst Role    → 8%
└─ Cross-Functional & Fast-Paced        → 5%
   Subtotal: 25%

Education & Certifications:
├─ Bachelor's Degree                    → 8%
└─ Advanced Degree / Certification      → 4%
   Subtotal: 12%

TOTAL: 100% ✅
```

The platform must not assume recruiter priorities.

Recruiters define what matters.

---

# Transforming the JD based requirements into sub-questions:

We will not do a direct vector embedding based similarity search based on the JD requirements.
Rather we will break each requirement into small set of sub-queries, and those sub-queries be used to see what output do we get from the retrieved similar chunks.

For example- If one of the requirement in JD for the Data Scientist position asks for-

  - The candidate must have an experience of 5+ years in the recommendation system and clustering.

How to break this into sub-questions;

  - Does the candidate know Python? If yes, then how many years of experience does he or she have? Does the candidate has experience in the relevant projects?

How to evaluate the replies based on this query objectively.

Here, the LLM act as only a brain to objectively check and give a subscore for this requirement/ skill.

The scoring proceeds as follows- 

1 if the candidate knows Python (It's a binary gate 0 or 1), 
3 years of experience scored against a 5-year target using the banded rule (3 ≥ 2.5 = 50% → 0.5 band)
Relevance of the projects to the JD requirement (in a scale of 0 to 1, 0 lowest, and 1 exact match)

So for a candidate whose resume says-

- Python with experience of 4+ years
- Worked in Netflix for Recommendation system for 3 years 
                                   
The normalized score should be:

Normalized Score for Python Skill and exp: 1 × 0.5 × 0.8 = 0.4 (using the banded ratio)

Explanation- 1 because he knows python, 0.8 because he has exp of 4 years in python (this requires LLM judgment, as in the resume
the experience may not always be mentioned clearly, so we need to calculate relevant exp from each retrieved chunk
but do not double count for the experience on the same skill. So all evidence minus the common or repeated experience mentions of the same skill), 0.8 because of the relevance of his working experience as demanded by the JD requirement (This requires some LLM Judgment too)

# Final Sub-score Normalization

Weights must be converted into a consistent scoring framework.

Example:

```text
Power BI = 9
Python = 10
Excel = 10
Project Management = 10
Certification = 8
Graduation = 6
Age = 5
Location = 8
Management Experience = 8
```
So we can see for Python the max score is 10-

But the candidate has 0.64 sub-score for Python relevant skills
So the final sub-score should be - 10 * 0.64= 6.4

Like this you have to calculate for each sub_score and experience.

---

# Resume Processing

Resume Upload

↓

Resume Cleaning

Remove:

* Headers
* Footers
* Templates
* Decorative elements
* Noise
* Duplicate content

Retain:

* Candidate information
* Education
* Experience
* Projects
* Skills
* Certifications
* Languages

---

# Structured Candidate Profile Extraction

Alongside chunking, the system extracts a structured profile directly from the cleaned resume:

* Degrees and institutions
* Certifications
* Total experience (years)
* Companies and roles
* Employment dates

This extraction is deterministic (parsing, not retrieval) and is stored as its own structured record, separate from the chunked sections.

Reason: facts that are exact and unambiguous — a degree name, a certification title, total years of experience — should be read directly from the structured profile rather than re-derived through search. Similarity search can miss or under-rank a chunk containing an exact fact like this; a structured lookup cannot.

Requirements that are purely factual (e.g. "Does the candidate hold a Bachelor's degree?") may be answered entirely from the structured profile, bypassing everything else.

Requirements that require interpretation (e.g. "How deep is the candidate's Power BI expertise?") still rely on the threshold-based retrieval pipeline and rubric-bound LLM evidence scoring (below).

---

# Recursive Chunking (active 2026-07-05, DEC-019)

The active chunking strategy is:

Recursive Chunking

```text
RecursiveCharacterTextSplitter(
    separators=["\n\n", "\n", ". ", " "],
    chunk_size=1000,       # Optuna hyperparameter (bounds [500, 1000])
    chunk_overlap=500,      # Optuna hyperparameter (bounds [50%, 60%] of chunk_size)
)
```

The default chunk size is 1000 characters with 500 characters of overlap (50% of `chunk_size`). Both are tuned by Optuna against a fixed eval set. The bounds were widened on 2026-07-07 from `[200, 500]` / `[100, 60%]` to `[500, 1000]` / `[50%, 60%]` to reduce the failure mode where a resume role's date line and its skill bullets land in different chunks — larger chunks with 50% overlap keep the date line and the bullet points in the same (or overlapping) chunk, so the rubric LLM can correlate skills with durations without needing to re-parse dates.

This chunking supports:

* Threshold-based retrieval (regular RAG)
* Resume Chat
* Score Explanation
* Candidate Comparison
* Hiring Recommendations

The previous Document-Aware chunking strategy (which preserved resume section boundaries) is retained as `DocumentAwareChunker` in `src/rag/chunker.py` for one release as a migration aid. Its only consumer is the structured-profile extractor, which needs labeled sections for `degrees`, `certifications`, and `total_experience_years`.

---

# Header Normalization

Resumes do not use consistent section names: "Skills" vs "Technical Skills" vs "Core Competencies"; "Experience" vs "Employment History" vs "Job Experience" vs "Career History"; "Education" vs "Academic Qualifications". Routing a JD requirement to "the Education section" only works if every resume's education-like header reliably maps to the same canonical label.

This is handled once per resume, at parse time — not once per requirement, and not by similarity ranking.

## Canonical Sections

```text
Personal_Info | Education | Experience | Projects
| Skills | Certifications | Languages
```

## Layer 1 — Synonym Lookup (free, deterministic)

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

## Layer 2 — Fallback Classification (one model call, only for unmatched headers)

If a header doesn't match the table — or a resume has no headers at all and uses free-flowing paragraphs — one classification call per resume assigns it to a canonical section. This is a discrete classification into a fixed set of 7 buckets, not a similarity score, so it is deterministic-enough and auditable: the system logs which header (or absence of one) produced which label and with what confidence.

## Multi-Tag Chunks

Content does not always respect section boundaries even after labeling — a bullet under "Projects" can describe genuine professional work; a line under "Experience" can describe a certification earned on the job. A chunk must be allowed to carry more than one section tag when its content genuinely spans categories, rather than being forced into a single bucket.

---

# Chunk Metadata Schema

A chunk on its own is not enough — a bullet point that mentions a skill is useless for scoring if it loses the dates and context of the role it came from. Every chunk is enriched with metadata at parse time, not inferred later by an LLM.

```text
chunk:
  section_type: experience | education | skills_summary | projects | certifications | header
  parent_structure:
    organization
    role_title
    location
    temporal_context:
      start_date
      end_date
      is_current
      calculated_duration_months   ← computed deterministically, never by the LLM
  skills_asserted: [ ... ]
  experience_type: professional | personal_project | academic | unknown
```

`calculated_duration_months` is computed in code from the parsed dates at parse time. LLMs are unreliable at date arithmetic, so this number is handed to the LLM ready-made rather than asked for.

`experience_type` lets scoring distinguish a skill used professionally from one mentioned only in a personal project or coursework — this distinction matters for rubric scoring below.

---

# Threshold-Based Retrieval (Regular RAG, updated 2026-07-05 per DEC-017 + DEC-018)

For each JD requirement (and for each recruiter chat question), the system must retrieve the evidence needed to score that requirement against the candidate. The canonical retrieval strategy is **threshold-based cosine over a per-candidate (or pool-wide) Recursive-chunk index** — the same regular RAG pattern used in standard LLM applications.

## What retrieval has to do

A JD requirement such as "5+ years of Python experience" is not directly comparable to a chunk of resume text. A candidate's Python experience might be in any section (Experience, Projects, Skills summary, or even a free-text "Career Highlights" block), and might be written in any phrasing ("built ML pipelines in Python", "developed backends in Python/Django", "automated data workflows with Python"). The retrieval step has to find **all** the evidence the LLM will need to score the requirement, and miss **none** of it.

## The retrieval strategy: threshold-based cosine

```
For each query (a sub-question, a chat question, or a JD bullet):

1. Embed the query (sentence-transformers/all-MiniLM-L6-v2, 384-dim).

2. Compute cosine similarity between the query vector and every chunk
   vector in the relevant index (per-candidate for scoring, pool-wide
   for triage and chat).

3. Return all chunks whose cosine ≥ θ (default θ = 0.25, Optuna-tuned;
   bounds [0.10, 0.50] per owner spec 2026-07-06; default lowered
   from 0.30 to 0.25 on 2026-07-07 to surface more date-bearing
   chunks per REQ).

4. Sort by similarity descending. If the result is larger than
   max_chunks_per_query (default 20), truncate and log a warning.

5. Send the joined chunks + the rubric (for scoring) to the LLM.
   The prompt also includes an EMPLOYMENT HISTORY block (computed
   deterministically from parsed date ranges by the structured profile
   extractor) so the LLM can correlate skill mentions in retrieved
   chunks with the parser-computed role durations — without needing
   to re-parse sparse date strings from 1000-char chunks.

6. For scoring: the LLM outputs anchored floats for each sub-question:
     skill_presence: 1.0     (binary, from {0.0, 1.0})
     years_experience: 0.5   (banded: >= target → 1.0; >= 50% → 0.5; >= 25% → 0.25; else 0.0)
     project_relevance: 0.75 (anchored)

7. The code computes the sub-score: SQ1 × SQ2 × SQ3 = 1.0 × 0.5 × 0.75 = 0.375.
   The LLM never sees the requirement's weight and never performs the
   final aggregation.

8. Cache the (candidate_id, req_id, hash(query, top-chunk-ids), model_name, θ) -> sub-scores
   for determinism on re-runs.
```

## Why a single θ, not top-K

A fixed `top_k` (e.g. `top_k = 5`) doesn't adapt to query difficulty: a 3-chunk result for a hard query is as bad as a 20-chunk result for an easy one. Threshold-based retrieval returns **more chunks when there are more matches** and **fewer when there are few**, with a single, intuitive knob (`θ`). The cap at `max_chunks_per_query = 20` is a safety net, not a primary control.

## Why the LLM does the final filtering, not a higher threshold

A cosine threshold of 0.10, 0.25, 0.50, or 0.90 all have failure modes:

- **θ = 0.10** — recall is maximized; precision is very low; almost all chunks reach the LLM (noisy, expensive).
- **θ = 0.25** (current default, 2026-07-07) — surfaces more date-bearing chunks per REQ; combined with the larger `chunk_size=1000` and 50% overlap, reduces date/skill split incidents. Optuna will tune this.
- **θ = 0.50** — recall is high; precision is low; many irrelevant chunks reach the LLM.
- **θ = 0.90** — precision is high; recall collapses; relevant chunks get dropped.

The chosen default `0.70` is a starting point. Optuna (DEC-021) calibrates `θ` against a fixed eval set to find a value that balances faithfulness and `avg_chunks_returned` (the multi-objective target).

## Why this is reliable (not "non-deterministic")

The rubric's sub-questions are **anchored**:

- Binary gates: 0.0 or 1.0
- Linear years: a single float derived from a deterministic formula (`min(years / expected, 1.0)`)
- Anchored scales: 0.0, 0.25, 0.5, 0.75, 1.0 — with explicit descriptions of what each value means

The LLM is reading chunks and outputting **one of a small set of fixed values**, not generating free-form text. The rubric is the determinism mechanism, not the LLM temperature. Across runs, the LLM's anchored outputs are stable for a well-designed prompt. The cache makes the second run bit-deterministic.

## Header Normalization (parse-time only)

The Recursive chunker emits chunks with a soft `section_type` field ("experience", "education", "skills", etc.) inherited from the legacy Document-Aware chunker. This is **retained as a soft tag** because the structured profile (`degrees`, `certifications`, `total_experience_years`) still needs labeled sections. It is **not** used for retrieval routing — the cosine similarity decides relevance.

## Caching for cost and reproducibility

The cache key is:

```
hash(candidate_id, req_id, hash(query, sorted(top_chunk_ids)), model_name, θ)
```

- Same candidate + same REQ + same query + same top chunks + same model + same θ = cache hit
- Chunking changes → cache invalidates (different chunk IDs)
- Model upgrade → cache invalidates (different model name)
- θ change → cache invalidates (different top chunks may be returned)

The cache is stored as a **per-resume reasoning tree** (DEC-022):

```
data/per_candidate/<role>/<candidate_id>/reasoning/<req_id>__<query_hash>.json
```

Each file contains the LLM's full output: narrative reasoning, basis (cited chunks + quotes), retrieved-chunks list, and sub-scores. The legacy single-file cache at `data/embeddings/llm_cache.jsonl` is moved to `data/embeddings/llm_cache_legacy.jsonl` during the M0.5e migration and is read-only after that.

See **Per-Resume Reasoning Storage** below for the file schema, cache key, invalidation rules, and GC policy.

## Worked example: Python experience

Candidate has 4 Experience entries (Torphy 9yrs, Dufour 3yrs, Lessard 4yrs, personal project 1yr), 1 Project entry, and 1 Skills line → after Recursive chunking with `chunk_size=1000`, ~4 chunks.

```
JD requirement: REQ-002 = "5+ years Python experience (required, weight 8%)"
Sub-question (or requirement text): "Python experience"

Step 1: Embed the query
  v(query) = [0.42, 0.31, 0.18, 0.55, 0.22, 0.41]

Step 2-3: Cosine vs the candidate's chunks
  chunk_0 (Torphy 9yrs, Python):       0.91   ← ≥ 0.70
  chunk_1 (Dufour 3yrs, Python):      0.84   ← ≥ 0.70
  chunk_2 (Lessard 4yrs, Python):     0.79   ← ≥ 0.70
  chunk_3 (personal project, 1yr):    0.72   ← ≥ 0.25
  chunk_4 (Project entry, Python):    0.74   ← ≥ 0.25
  chunk_5 (Skills line, "Python"):    0.65   ← ≥ 0.25, included (θ = 0.25)
  → 5 chunks returned (under cap of 20)

Step 4: Sort by similarity desc: chunk_0, chunk_1, chunk_4, chunk_2, chunk_3.

Step 5: LLM receives the 5 chunks + the rubric + the EMPLOYMENT HISTORY block
  (which shows Torphy 9yrs 108mo, Dufour 3yrs 36mo, Lessard 4yrs 48mo, personal project 1yr 12mo).

Step 6: LLM outputs (correlating the skill mentions with the employment durations):
  skill_presence: 1.0     (Python is mentioned in 4 of 5 chunks)
  years_experience: 1.0   (Torphy 9yrs + Dufour 3yrs + Lessard 4yrs where Python appears; 16 yrs ≥ 5 target → banded 1.0)
  project_relevance: 0.75 (project descriptions show direct Python use)

Step 7: sub-score = 1.0 × 1.0 × 0.75 = 0.75
         contribution = 8% × 0.6 = 0.048 (4.8 points out of 8 possible)

Step 8: cache.put(hash, {sub_scores, normalized_score: 0.6})
         On re-run with same θ: cache.get(hash) returns the same sub-scores.
```

## What changed from the previous design

The earlier design (DEC-012 → DEC-015) used two layered strategies:

1. **Section-Routed Evidence Retrieval** — exact label match on canonical sections.
2. **Sub-Query Similarity Retrieval** — decompose each requirement into 2–4 sub-questions, embed each, cosine-match, union, LLM filter.

Both were retired in favor of regular RAG. Why:

- **Section-Routed had a 49% chunk-invisibility bug** (chunks with `section_type=""` were dropped).
- **Sub-Query Similarity's two-step decomposition added latency and prompt complexity** for a small candidate pool (avg 17 chunks per resume) where it produced no observed quality gain over a single-query threshold retrieval.
- **Regular RAG is the industry standard** for this use case. The simplification makes the codebase easier to reason about and easier to tune (one knob, `θ`, instead of two).

The deterministic scoring engine is **unchanged** — the `graded_scorer` and `unified_scorer` are still the only ranking signal. The RAG pivot changes how evidence is gathered, not who decides the score.

---

# Per-Resume Reasoning Storage (added 2026-07-05, DEC-022)

The LLM's output for every (candidate, requirement, query) is persisted as a first-class per-resume artifact. This is the **audit trail** and the **cache** for re-runs, and it is what makes the system deterministic on re-runs even though the underlying LLM is not bit-deterministic.

## Storage Layout

```text
data/
├── document_aware_chunking/                      # LEGACY — Document-Aware chunks (DEC-022a, DEC-023)
│   ├── MIGRATION_NOTES.md
│   └── <role>/<candidate_id>.jsonl
├── recursive_chunking_<chunk_size>_<overlap>_<top_k>_<threshold×100>/  # PER-EXPERIMENT (DEC-023)
│   ├── metadata.json                             # the full config that produced this folder
│   ├── chunks.jsonl                              # Recursive chunks for this (chunk_size, overlap)
│   ├── index.npz                                 # embedding index (MiniLM-L6-v2, 384-dim)
│   ├── llm_cache_legacy.jsonl                    # (only in the M0.5e-b migration window)
│   └── per_candidate/                            # per-resume reasoning tree (DEC-022)
│       └── <role>/
│           └── <candidate_id>/
│               └── reasoning/
│                   └── <req_id>__<query_hash>.json
├── active_experiment -> recursive_chunking_1000_500_x_25/  # SYMLINK — points to the Active config
├── embeddings/                                   # ACTIVE — shared index/cache (legacy; migrate to per-experiment)
│   ├── index.npz
│   ├── chunks.jsonl
│   └── llm_cache_legacy.jsonl                    # LEGACY — read-only after M0.5e
├── mlflow/                                       # ACTIVE — experiment tracking (DEC-020)
│   ├── mlflow.db
│   └── artifacts/
├── optuna/                                       # ACTIVE — hyperparameter search (DEC-021)
│   └── studies.db
└── ../reports/                                   # ACTIVE — per-experiment chunk reports (DEC-024)
    └── chunk_reports/
        ├── document_aware_chunking_report.json
        ├── document_aware_chunking_report.md
        ├── recursive_chunking_1000_500_x_25_report.json
        └── recursive_chunking_1000_500_x_25_report.md
```

(`reports/` is a sibling of `data/`, not a child, so the path is `reports/chunk_reports/...`. The `data/` tree is for binary artifacts; the `reports/` tree is for human-readable diagnostics. Both are committed to git — `data/` mostly ignored, `reports/` fully tracked.)

The legacy chunk files (`data/document_aware_chunking/`) and the legacy `llm_cache.jsonl` are **moved**, not deleted, so the migration is reversible. The per-experiment folders are the active strategy; `data/active_experiment` is the runtime symlink to the "Active" config.

## Per-Experiment Folder Naming (added 2026-07-05, DEC-023)

Every MLflow run for the Recursive chunking pipeline writes its artifacts to a per-experiment folder whose name encodes the hyperparameters that produced it:

```
data/recursive_chunking_<chunk_size>_<overlap>_<top_k>_<threshold×100>/
```

**Field order is fixed (4 numeric fields, in this order):**

| Position | Field | Example | Notes |
|---|---|---|---|
| 1 | `chunk_size` (chars) | `1000` | from `RecursiveChunker.RECURSIVE_CHUNK_SIZE` |
| 2 | `overlap` (chars) | `200` | from `RecursiveChunker.RECURSIVE_CHUNK_OVERLAP` |
| 3 | `top_k` | `5` | from `Retriever.top_k`; `x` if not used |
| 4 | `threshold × 100` | `50` (i.e. θ=0.50) | from `Retriever.threshold`; `x` if not used |

**Examples:**

| Config | Folder |
|---|---|
| `chunk_size=1000, overlap=500, θ=0.25` (threshold mode, no top_k cap — current Active) | `data/recursive_chunking_1000_500_x_25/` |
| `chunk_size=1000, overlap=500, top_k=20, θ=0.25` (threshold + cap mode) | `data/recursive_chunking_1000_500_20_25/` |
| `chunk_size=500, overlap=250, θ=0.10` (low recision sweep point) | `data/recursive_chunking_500_250_x_10/` |
| `chunk_size=1000, overlap=600, θ=0.50` (high precision sweep point) | `data/recursive_chunking_1000_600_x_50/` |

**`metadata.json` is the canonical record** of the experiment and is the source of truth for the folder's contents:

```json
{
  "schema_version": "1.0",
  "experiment_folder": "recursive_chunking_1000_500_x_25",
  "created_at": "2026-07-05T11:14:22Z",
  "chunking": {
    "chunker": "RecursiveChunker",
    "chunk_size": 1000,
    "chunk_overlap": 500,
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

**Folder name is the self-documenting identifier.** Two MLflow runs with the same `(chunk_size, overlap, top_k, threshold)` share the same folder — the artifacts (chunks, index, cache) are byte-identical for the same config, so sharing is correct, not redundant. The "Active" config in `MODEL_REGISTRY.md` points to one specific folder; promoting a new Active config means pointing `data/active_experiment` to a different folder (or recreating the symlink).

**Runtime entry point:** code does not hardcode `data/recursive_chunking_1000_500_x_25/`. It follows the `data/active_experiment` symlink. Promoting a new Active config is a one-line symlink operation.

## File Schema

Each `<req_id>__<query_hash>.json` stores:

```json
{
  "schema_version": "1.0",
  "candidate_id": "cand_042",
  "req_id": "REQ-002",
  "query": "5+ years of Python experience with recommendation systems",
  "created_at": "2026-07-05T10:32:14Z",
  "model_name": "qwen2.5:3b",
  "model_params": { "temperature": 0, "max_tokens": 4000 },
  "retrieval_params": {
    "theta": 0.25,
    "max_chunks_per_query": 20,
    "chunk_size": 1000,
    "chunk_overlap": 500,
    "embedding_model": "all-MiniLM-L6-v2",
    "llm_backend": "ollama"
  },
  "retrieved_chunks": [
    { "chunk_id": "cand_042__14", "cosine": 0.91, "text": "..." },
    { "chunk_id": "cand_042__2",  "cosine": 0.84, "text": "..." }
  ],
  "reasoning": "The candidate mentions Python in 4 of 5 retrieved chunks...",
  "basis": [
    { "chunk_id": "cand_042__14", "quote": "Delivered 9 ML projects in Python",                    "relevance": "primary" },
    { "chunk_id": "cand_042__2",  "quote": "Recommendation system at Netflix for 3 years",          "relevance": "supporting" }
  ],
  "sub_scores": {
    "skill_presence":   { "value": 1.0,  "type": "binary",   "source_basis_idx": [0, 1] },
    "years_experience": { "value": 1.0,  "type": "banded",   "source_basis_idx": [0], "extracted_years": 16, "target_years": 5 },
    "project_relevance":{ "value": 0.75, "type": "anchored", "source_basis_idx": [1] }
  },
  "employment_history_used": true,
  "rubric_version": "v1.0",
  "scoring_mode": "rubric_bound_llm"
}
```

## Cache Key

```
hash(candidate_id, req_id, hash(query, sorted(top_chunk_ids)), model_name, θ)
```

A re-run is a **cache hit** when this key matches exactly. On hit:
- The LLM is **not called** (no round-trip cost).
- The embedding is **not recomputed** (no vector DB call).
- The retrieval is **not re-run** (no cosine call).
- The scoring engine reads `sub_scores` directly from the file and applies the weight.

A re-run is a **cache miss** when any component of the key differs:
- Chunking parameters change → new `chunk_id` set → different `top_chunk_ids`.
- Embedding model changes → new vectors → new `cosine` values.
- LLM model upgrade → `model_name` differs.
- `θ` change → different `top_chunk_ids` returned.
- JD requirement or weight config change → `req_id` or `query` differs.

## Why Storage is Worth It

| Concern | Cost without per-resume storage | Cost with per-resume storage |
|---|---|---|
| LLM round-trips on re-runs | One per (candidate, req, θ) — repeat if θ changes during Optuna | Zero (filesystem read) |
| Re-run determinism | Approximate (LLM temperature variance) | Structural (same key → same bytes) |
| Score-explanation UI | Re-run the LLM, or read from a stripped cache | Read the file directly |
| Auditability per (candidate, req) | Re-derive from `llm_cache.jsonl` + retrieval logs | Open one file |

Storage estimate: 721 candidates × ~15 REQs × ~4 sub-queries = ~43,000 JSON files per (model, θ) combo. At 5–20 KB each, that's ~200–800 MB per combo. Peak during an Optuna sweep (~2–3 combos in flight) is ~1–2 GB. See `EVALUATION.md` for the storage-cost metric.

## GC Policy

- Entries with no read in the last 90 days are candidates for archival: moved to `data/per_candidate_archive/`. Not deleted by default.
- A disk-usage monitor alerts if `data/per_candidate/` exceeds 5 GB.
- The `MIGRATION_NOTES.md` in `data/chunks_legacy_document_aware/` records the legacy chunk files; they are GC'd after one release.

## Migration Notes

The M0.5e migration script (`scripts/migrate_to_per_resume_reasoning.py`):

1. **Move legacy chunks** (DEC-022a, refined by DEC-023): `mv data/chunks/<role>/<candidate_id>.jsonl data/document_aware_chunking/<role>/<candidate_id>.jsonl` for all 721 files. Write `MIGRATION_NOTES.md` with the move date, source/target chunkers, and per-file chunk-count delta. The destination directory is `document_aware_chunking/` (per DEC-023), not the longer `chunks_legacy_document_aware/` (DEC-022's original placeholder).
2. **Move legacy cache** (DEC-022b): `mv data/embeddings/llm_cache.jsonl data/embeddings/llm_cache_legacy.jsonl`.
3. **Backfill per-resume reasoning** (one-time, optional): walk `llm_cache_legacy.jsonl`, group entries by `(candidate_id, req_id, query, model_name, θ)`, and write one file per group into the per-experiment folder. Note: the legacy cache may not have the full `reasoning` and `basis`; backfilled entries are marked `"backfilled": true` and re-runs of those (candidate, req) pairs are forced to refresh.

After M0.5e completes, every new pipeline run creates a per-experiment folder per the DEC-023 convention. The Active config is symlinked from `data/active_experiment`.

The script is **idempotent** — running it twice is a no-op.

---

# Why Chunks, Why Not Embeddings (Per-Candidate Scoring)

> **Updated 2026-07-05 (DEC-017):** The platform now uses regular RAG for
> retrieval (embed → cosine ≥ θ → LLM), the same pattern as the "Usual
> RAG" column. The scoring engine remains the only ranking signal; the
> RAG pivot changes how evidence is gathered, not who decides the score.
> This section is retained as historical rationale for the design
> decisions that survived (deterministic scoring, no LLM in the final
> aggregation, RAG grounding rule, "Information not found…" fallback).

It is reasonable to ask: *if we are not running top-K similarity search, why chunk the resume at all, and why not embed the chunks?* The answer is that **chunks serve a different purpose in this system than in a typical RAG pipeline**, and the deterministic scoring engine is the only ranking signal. Usual RAG (embed corpus → cosine → top-K → LLM) is designed for searching a large document collection; this system uses the same retrieval pattern but routes the result through a deterministic scorer rather than trusting the LLM with the final score.

## Usual RAG vs. this system's approach

The "usual RAG" pipeline most engineers know is: **embed corpus → query → cosine → top-K chunks → LLM answer**. That works when the corpus is large (thousands of docs) and the query is open-ended ("how do I deploy X?"). It does not work when the corpus is one short document and the task is to score every fact in it against a fixed rubric. The two designs are:

| Layer | Usual RAG (large corpus) | This system (per-candidate scoring) |
|---|---|---|
| **Chunking** | Recursive or semantic — split text into 500-1000 token pieces, optimize for retrieval recall | **Recursive** — `chunk_size=1000`, `chunk_overlap=500` (50% overlap); both Optuna hyperparameters (DEC-019, refined 2026-07-07) |
| **Embedding** | All chunks embedded; vectors stored in a vector DB | **All chunks embedded** (MiniLM-L6-v2, 384-dim). Used for cosine ≥ θ retrieval, not for ranking. |
| **Retrieval** | Cosine similarity, top-K (e.g. 3-5 chunks) | **Cosine ≥ θ** (default θ=0.70, Optuna-tuned) — return all hits, cap at 20 |
| **Ranking** | LLM picks winner from top-K | **Deterministic scoring engine** in code — LLM never decides ranking |
| **LLM input** | Top-K chunks ranked by similarity | **All chunks meeting θ** — same content, ranked by similarity |
| **Determinism (ranking)** | Approximate — same query can return different chunks if the index changes | **Exact** — `graded_scorer` produces the same number for the same inputs |
| **Auditability (ranking)** | Hard — "why was this chunk dropped?" affects the score | **Trivial** — the ranking formula is public; the retrieved chunks are reproducible via cache |

The shift from "LLM picks the winner" to "LLM gathers evidence, code ranks" drives every other design choice below.

## How usual RAG fails on this use case (concrete example)

Consider a candidate with three Python roles, two side projects mentioning Python, and a CS degree. Scoring JD requirement *"5+ years of Python experience (required, 10% weight)"*.

**With usual RAG (embed corpus → cosine → top-3):**

```
1. JD requirement "5+ years of Python experience" → embedded as a query vector
2. Cosine vs every chunk in the resume
3. top-K = 3, by descending similarity
4. LLM receives those 3 chunks + the rubric
5. LLM scores

What can go wrong:
- The 3 most-similar chunks might be 3 different roles, but the 4th role
  (ranked 4th by cosine) is the longest Python tenure. It gets dropped.
- "Python" in the degree section might be the most-similar chunk because
  of the word "Python" + "computer science" co-occurring. LLM scores
  the candidate on degree + 1 role, missing 2 of 3 roles.
- Top-K=3 was a guess — the LLM's score depends on whether you set
  K=2, K=3, or K=5. Different K = different score for the same
  candidate + same JD.
- A re-run with a newer embedding model produces a different top-3 →
  different score. The recruiter cannot reproduce "why 78?".
```

**With this system's approach (label match → full section):**

```
1. JD requirement "5+ years of Python experience"
   + dimension_type = "skill"  (or "experience")
2. section_routed_retrieval():
     classify_requirement_type(category, name)  →  "skill"
     skill_filter = "Python"  (from requirement name)
     fetch all chunks where:
       section_type == "experience"
       AND ("python" in skills_asserted OR "python" in text)
3. Returns: chunk_0 (Torphy 2017-2026, 9 yrs, Python), chunk_1
   (Dufour 2014-2017, 3 yrs, Python), chunk_2 (Lessard 2010-2014,
   4 yrs, Python), chunk_3 (personal project, 1 yr, Python)
4. LLM receives all 4 chunks + the rubric, joined as one section
5. LLM scores based on: 9+3+4 = 16 years Python (deduplicated overlapping
   time ranges); 1-yr project doesn't count toward professional
   experience.
6. Score: 16 / 5 = capped at 1.0 (i.e. exceeded the 5-yr expectation)
7. Re-run with different model: same chunks, same content, same score.
   Auditable.
```

The same candidate, the same JD, the same rubric — same score. That is the property we need and that usual RAG cannot give us at scoring time.

## What chunks are for here

Chunks are not the unit of retrieval. They are the **unit of section delivery** to the rubric-bound LLM judge. A JD requirement mapped to "Experience" needs the candidate's full Experience content, with company, role, dates, and bullets intact, so the LLM can read it and score against the rubric.

Concretely, each chunk carries:

- `section_type` (experience, education, projects, skills, certifications, languages)
- `parent_structure` (organization, role_title, location, temporal_context with `calculated_duration_months`)
- `skills_asserted`, `experience_type`

When the scorer asks "what is this candidate's experience with Python?", the route is:

```
JD requirement "Python experience"
        ↓
section_routed_retrieval()
        ↓
fetch every chunk tagged section_type="experience"
        ↓
join their text into one section string
        ↓
send to rubric-bound LLM with the rubric
```

No similarity ranking happens. Every experience chunk is delivered, in original order, with its metadata.

## Why embeddings are the wrong tool for this

A single resume is a **short document** (1,000–3,000 tokens) — not a corpus. Embeddings + top-K cosine are the right tool for searching across thousands of documents; they are the wrong tool for reading one document. Concretely:

| Failure mode | What goes wrong with embeddings + top-K |
|---|---|
| **False negatives from cutoff** | A second Python role ranks at cosine 0.72, below the top-3 cutoff. It gets silently dropped. The candidate looks like they have 3 years of Python when they have 5. |
| **Context loss** | Embedding a chunk strips the metadata that the scorer needs: dates, duration, company, role title. The LLM cannot tell if "Python" was used for 6 months or 6 years. |
| **Non-determinism** | Same resume + same JD produces different results if the embedding model changes, the chunk boundaries shift, or the top-K parameter changes. The score becomes unauditable — a recruiter cannot reproduce "why 78?" |
| **Cost** | For 721 resumes × 17 chunks each = 12,000+ embedding calls just to start. For 1,000s of roles this explodes, and every scoring run has to repeat the embedding step or carry a stale index. |

The deterministic engine (see "Deterministic Scoring Engine" below) requires **reproducible, auditable, explainable rankings**. A score that depends on a similarity ranking is none of those.

## What needs to be modified for this use case

Five concrete changes from the usual RAG pattern:

1. **Chunk by section, not by token count.** Document-Aware Chunking splits the resume on canonical section boundaries (Experience, Education, Projects, ...) and keeps each entry (one job, one degree, one project) as a single intact chunk with its metadata. The usual recursive-or-semantic chunker, which optimizes for retrieval recall, would split a job across two chunks and lose the company + dates context.
2. **Attach metadata at chunk time, not at retrieval time.** `calculated_duration_months`, `company`, `role_title`, `start_date`, `end_date`, `skills_asserted`, `experience_type` are all computed deterministically at parse time and stored on the chunk. The LLM receives them ready-made; it never has to do date arithmetic or guess at a role's duration. Usual RAG stores text and metadata separately and asks the LLM to re-derive facts at query time — which is exactly what the spec says not to do.
3. **Use exact label match, not similarity rank.** A fixed table maps each requirement to its canonical section(s) (`src/rag/section_routed.py`). Retrieval is a `WHERE section_type = X` query, not a top-K cosine. This guarantees no relevant chunk is missed because of a similarity cutoff.
4. **Send the full section, not top-K.** All chunks in the mapped section are joined into one string and sent to the LLM. The LLM reads the full Experience history in order. There is no "rank" applied between the LLM and the evidence.
5. **Score against a recruiter-defined rubric, not a free-form query.** Each requirement has a rubric (`src/scoring/rubrics.py`) with anchored scales (0.0 / 0.25 / 0.5 / 0.75 / 1.0) and sub-questions. The LLM is constrained to that rubric; it cannot invent its own definition of "Strong" or "Advanced". The LLM also does not see the requirement's weight — it returns sub-scores, and the code applies the weight.

These five modifications together make the system deterministic, auditable, and explainable, at the cost of giving up the flexibility of "ask anything about the resume." For per-candidate scoring, that trade is correct.

## Where embeddings DO belong

Embeddings are the correct tool for **all retrieval** in this system, including per-candidate scoring (post-2026-07-05). The distinction is that the **scoring engine** is the only ranking signal; embeddings are the only retrieval signal. Use cases:

- **Per-candidate evidence retrieval for scoring** — `candidate_id` filter applied; chunks for that one candidate are ranked; the rubric-bound LLM judge reads the evidence and outputs anchored floats that the code aggregates.
- **Shortlisting / triage** — narrowing a large applicant pool before running the full per-candidate scoring pass.
- **Open-ended pool search** — "find candidates with healthcare domain experience" across every resume on file.
- **Resume chat** — RAG-grounded answers to recruiter questions about one candidate's full resume content.

These are all served by the same threshold-based retrieval pipeline; only the filter (`candidate_id` set vs. not set) changes.

## Quick reference

| What | When | Why |
|---|---|---|
| Chunk the resume (Recursive) | Every pipeline run | Uniform chunks for fair cosine comparison |
| Embed + cosine ≥ θ (per-candidate) | Every scoring run | Gathers evidence; threshold tuned by Optuna |
| Embed + cosine ≥ θ (pool) | Pool search / chat | Same pipeline, no `candidate_id` filter |
| Deterministic scoring engine | Every scoring run | Only ranking signal; same inputs → same score |
| LLM (rubric-bound) | Every scoring run | Reads retrieved evidence, outputs anchored floats; never sees weight, never aggregates |
| LLM (chat) | Recruiter question | Reads retrieved chunks, grounded answer; "Information not found…" if no chunks meet θ |
| Cross-encoder reranker | Future | Optional post-threshold rerank if Optuna shows a faithfulness gain |

The chunks we build are for **retrieval**, and the scoring engine is the only thing that decides the score. Embeddings + cosine are the right tool for retrieval; the deterministic engine is the right tool for ranking.

---

# Candidate Intelligence Report

Before ranking candidates, the platform shall generate a Candidate Intelligence Report.

This report becomes the primary knowledge source for evaluation.

Contents:

## Candidate Information

* Name
* Location
* Languages

## Skills

* Skill Name
* Years of Experience
* Evidence

## Experience

* Total Experience
* Relevant Experience
* Same Role Experience
* Leadership Experience

## Education

* Degree
* Institution
* Institution Category

## Certifications

* Certification Name
* Provider
* Relevance

## Projects

* Relevant Projects
* Project Relevance

## Objective Scores

Populated after the Deterministic Scoring Engine runs (see below):

* Skill Scores
* Experience Scores
* Education Scores
* Certification Scores

## Evidence Sources

Resume references used for scoring.

---

# Deterministic Scoring Engine

This is the only scoring engine.

The platform must not implement multiple competing ranking systems.

The scoring engine shall:

* Apply recruiter-defined weights
* Apply documented formulas
* Use extracted evidence
* Produce reproducible scores

The scoring engine is the source of truth.

---

# Scoring Rubrics

Every scoring dimension must resolve to an explicit, recruiter-visible rule before it is used. The system must never let the LLM invent a rubric at evaluation time.

## Sub-Query Decomposition Pattern

Each requirement is broken down into atomic sub-queries (2-6 per requirement depending on complexity). Sub-queries follow a consistent pattern:

**Pattern:** Binary gates × Float evidence scores

```
REQ-001: Requirement Name
├─ SQ001: Binary gate (0 or 1) — Does evidence exist?
├─ SQ002: Binary gate (0 or 1) — Is it used for the right purpose?
├─ SQ003: Float evidence (0.0 - 1.0) — How strong is the evidence?
└─ SQ004: Float years-proportional (0.0 - 1.0) — min(years / expected, 1.0)
```

**Formula for each requirement:**
```
Sub-Score = SQ001 × SQ002 × SQ003 × SQ004
```

**Final contribution:**
```
Contribution = Recruiter_Weight% × Sub-Score
```

**Total candidate score:**
```
Total = SUM of all contributions
```

**Example:**

For a Business Analyst role requiring SQL skills:

```
REQ-002: SQL for Data Validation & Analysis (Weight: 8%)
├─ SQ004: Does candidate know SQL? → Binary (0 or 1)
├─ SQ005: Has candidate used SQL for data validation? → Binary (0 or 1)
├─ SQ006: Years of SQL experience (relative to 4 years expected) → Float (0.0 - 1.0)
└─ SQ007: Complexity level of SQL work → Float (0.0 - 1.0)

Sub-Score = SQ004 × SQ005 × SQ006 × SQ007
Contribution = 8% × Sub-Score
```

## Experience Scoring (Banded Years-Ratio Formula)

For any "years of experience" requirement, the recruiter sets a target/ideal value. The score is computed using a **banded ratio** — one of four discrete values rather than a continuous fraction — so it is easy to audit and explain to a recruiter (updated 2026-07-07 per the banded-rule refinement):

```text
if candidate_years >= ideal_years:
    score = 1.0
elif candidate_years >= 0.5 * ideal_years:
    score = 0.5
elif candidate_years >= 0.25 * ideal_years:
    score = 0.25
else:
    score = 0.0
```

Replaces the prior continuous formula `min(candidate_years / ideal_years, 1.0)`. The banded thresholds (50%, 25%) align with the four anchor values used on the relevance scale (1.0, 0.75, 0.5, 0.25); this rubric uses 1.0 / 0.5 / 0.25 / 0.0 (no 0.75 band) to keep "no evidence" firmly at zero.

Note: `candidate_years` for **total experience** is read directly from the structured candidate profile (code-only, no LLM). `candidate_years` for **relevant / same-role / leadership / skill-specific experience** is extracted by the rubric-bound LLM from:
  1. The chunks retrieved by the threshold-based retrieval pipeline (skill mentions, project descriptions).
  2. The **Employment History block** — a pre-computed list of (company, role, dates, computed duration_months) appended to the rubric prompt right after the SECTION CONTENT. The LLM correlates the skill mention in a retrieved chunk with the role duration from the employment history — without needing to re-parse sparse date strings from the chunks themselves. This mitigates the failure mode where the Recursive chunker splits a role's date line away from its bullet points.
The banded formula is then applied in code. The LLM never sees the weight or performs the final aggregation.

Example-

The candidate must have experience of 6 years in a leadership role managing projects on Customer Services:

Sub-questions-

Is the candidate experienced? (Binary 1 or 0)
Has she got 6 years of experience? (Linearly varies in scale of years of experience / total experience required)
Has he or she been engaged in a leadership role? (Binary 1 or 0)
How relevant his or her projects are on scale of 0 to 1? (Not relevant at all- 0, Absolutely relevant-1)

So for a candidate whose resume says-

- Been engaged in managing a jewellery shop for 10 years

It should be-

1 * (10/6) * 1 * 1

Experience sub-score = min(calculated sub-score, 1.0) = min(1.67, 1) = 1


## Institute and Certification Tier Lookup (Code-Only)

The platform maintains a recruiter-editable tier database for institutions and certification providers.

```text
Tier 1            → 100% of allotted points (1.0)
Tier 2            → 75%  of allotted points (0.75)
Tier 3            → 50%  of allotted points (0.50)
Not Listed        → 50%  of allotted points (0.50)
```

Institute and certification weight remain fully recruiter-controlled — a recruiter may set Education Weight = 2 for one role and Education Weight = 20 for another. The platform must never assume institute prestige is universally important; see **Quality-Based Evaluation** below.

The tier databases are stored as recruiter-editable JSON files at `data/Institutes/institute_tiers.json` and `data/Certificates/certificate_tiers.json`. An institute or certification not found in any tier gets 0.50 (same as Tier 3) unless evidence places it in Tier 1 or Tier 2. The degree/cert match itself is scored separately.

# Objective Candidate Evaluation

Evaluate:

## Skills

* Skill Presence
* Skill Experience
* Skill Project Relevance (If it is mentioned, otherwise consider generic experience)

## Experience

* Experienced or Fresher
* Years of Experience
* Relevance of Experience

For example, for a Data Science candidate, if someone's resume says-

- Has worked in a Python environment for 6+ years for building cluster-based systems
- Has got 6+ years of experience in managing recommendation system based projects

One experience is related to skill and particular system design based project like cluster-based system and Python.
Next is related to management of projects, so both shouldn't be added to get 12 years of experience.

So consider: if the JD is explicitly asking for management based experience, if not, that management skill doesn't even count here.

## Education

* Degree Match
* Institute Tier based on a Database (web search may be used only to enrich the tier database offline, never at scoring time).

## Certifications

* Certification Match
* Provider Reputation

## Projects

* Relevance (This shouldn't be counted twice unless the recruiter explicitly provides separate weightage for this)

## Location

* Location Match

## Languages

* Language Match

---

# Quality-Based Evaluation

Not all qualifications are equal.

Examples:

Education:

IIT

NIT

Tier-1 Private University

Regional College

may receive different scores if the recruiter includes institution quality as a scoring factor.

Similarly:

AWS

Microsoft

Google

certifications may receive different scores if certification quality is included.

The recruiter controls these priorities.

---

# Resume Matching (Cross-Candidate Search)

This is the one place embeddings and similarity search belong in this system — searching across the whole candidate pool, not inside a single resume.

Use cases:

* Shortlisting / triage: narrowing a large applicant pool before running the full per-candidate rubric scoring pass.
* Open-ended pool search: "find candidates with healthcare domain experience" across every resume on file.

Workflow:

```text
All Resumes
        ↓
Embedding Generation
        ↓
Vector Index (Pool-Level)
        ↓
Cosine Similarity Search
        ↓
Similarity Score
```

This is unrelated to evidence retrieval for scoring a single candidate, which uses the same threshold-based retrieval pipeline (cosine ≥ θ over Recursive chunks) — only the `candidate_id` filter changes.

The similarity score is not the final ranking score.

It is only one supporting/triage signal.

Candidate ranking must always be driven by the deterministic scoring engine.

---

# Candidate Ranking Rule

Candidate rankings must always be based on:

* Recruiter-defined scoring policy
* Objective evidence
* Deterministic calculations

RAG, cosine similarity, and LLMs may provide supporting information but must never override the deterministic score.

---

# Explainable Candidate Scoring

Recruiters must be able to ask:

* Why did this candidate receive 78/100?
* Why did this candidate receive 6/10 for Power BI?
* Why did this candidate receive 5/10 for Education?

Every score must be traceable.

Every score must be explainable.

No black-box scoring is allowed.

---

# Score Explanation

When a recruiter requests an explanation:

The system shall:

1. Identify the scoring dimension.
2. Return the rubric sub-scores and cited evidence stored at scoring time — this is the default path (see note below).
3. If the recruiter asks a follow-up that goes beyond what was stored, re-fetch the candidate's evidence via threshold-based retrieval and generate a fresh answer grounded in the retrieved chunks.

Example:

Power BI Score:

8/10

Reason:

The candidate demonstrated 5 years of Power BI experience across two organizations and used Power BI in three projects. The recruiter-defined target was 6 years.

Note: the rubric sub-scores and the specific lines cited as evidence (see **Scoring Rubrics**) are stored at evaluation time. When a recruiter later asks "why", the system returns this stored reasoning first rather than re-evaluating from scratch — this keeps explanations fast, cheap, and guaranteed consistent with the original score. Because every requirement's evidence already comes from a fixed, fully-included section rather than a similarity-ranked subset, a follow-up re-fetch always returns the same content as the original scoring pass.

---

# Candidate Comparison

Recruiters must be able to compare candidates.

Examples:

* Why is Candidate A ranked above Candidate B?
* Which candidate has stronger Power BI experience?
* Which candidate has stronger leadership experience?
* Which candidate has more relevant projects?

Comparisons must use:

* Candidate Intelligence Reports
* Full Resume / Section Evidence

---

# Resume Chat

Recruiters must be able to chat with candidate resumes.

Questions may include:

* Which college did this candidate attend?
* What certifications does this candidate have?
* What was the candidate's last role?
* What projects has the candidate completed?
* What is the expected salary?
* What hobbies are mentioned?

All answers must be grounded in the candidate's full resume content.

---

# Final Principle

The platform must always follow:

```text
Recursive Chunking + Embedding
        ↓
Threshold-Based Retrieval (cosine ≥ θ)
        ↓
Code-Only Scoring  +  Rubric-Bound LLM Evidence Scoring
        ↓
Weighted Aggregation (Code)
        ↓
Candidate Ranking
        ↓
Cached-Reasoning Explanation
        ↓
Recruiter Decision Support
```

Never:

```text
LLM Opinion
        ↓
Candidate Score
```

The LLM explains decisions.

The scoring engine makes decisions.