# RETRIEVAL_STRATEGY_SPEC.md

## 1. Purpose

This document defines the retrieval strategy for the hiring platform after resumes have been converted into structured JSON and evidence chunks.

Its purpose is to specify:

- what retrieval modes the system should support
- when to use structured lookup versus chunk-based retrieval
- whether this architecture should be considered a Hybrid RAG system
- how retrieval should support deterministic requirement scoring and explainability

This document is intentionally separate from:

- `ROLE_TEMPLATE_SCHEMA.md`
- `SCORING_FORMULA_SPEC.md`
- `RESUME_EXTRACTION_SPEC.md`
- `WORKING_LOGIC.md`

---

## 2. Short answer

Yes, this is a **Hybrid RAG system**, but with an important clarification.

In the broad architectural sense, a Hybrid RAG system means the platform uses more than one retrieval method and routes requests to the best retrieval source depending on the task.

In this project, the hybrid design is:

- **structured retrieval / vectorless lookup** for exact factual fields
- **chunk-based semantic retrieval** for contextual evidence

So yes, this is Hybrid RAG.

But in a narrower industry sense, some people use the phrase “hybrid RAG” only for:

- keyword search such as BM25
- plus vector search

That narrower meaning is too limited for this platform.

For this hiring system, the correct definition is:

**a retrieval architecture that combines structured exact retrieval with semantic evidence retrieval under one routing layer**.

---

## 3. Why one retrieval method is not enough

After resume extraction, the platform has two fundamentally different kinds of information.

### 3.1 Exact structured facts

Examples:

- candidate name
- email
- phone number
- degree name
- institution name
- certification name
- total experience months
- latest job title
- portfolio link

These are best retrieved directly from structured JSON.

### 3.2 Contextual evidence

Examples:

- how strongly Python was used
- whether SQL was used in a relevant business context
- whether a candidate actually led stakeholder workshops
- whether sales ownership was real or only supporting participation
- whether design-system work was substantial or incidental

These are not best retrieved from flat structured fields alone. They need evidence chunks and semantic/contextual retrieval.

Because the platform contains both information types, retrieval must also be hybrid.

---

## 4. Retrieval layers in this system

The platform should use three logical retrieval layers.

### Layer 1: Structured lookup layer

This layer reads directly from canonical extracted JSON.

Use it when the question or requirement is factual, discrete, and explicit.

Examples:

- Does the candidate have an MBA?
- What certifications are listed?
- What is the latest company?
- What is the total normalized experience?

This layer should be deterministic and vectorless.

### Layer 2: Evidence chunk retrieval layer

This layer retrieves recursively chunked evidence from resume content using semantic similarity and metadata filtering.

Use it when the system must inspect contextual evidence.

Examples:

- Show evidence of stakeholder management
- Retrieve relevant chunks for responsive design work
- Find evidence that the candidate deployed models in production
- Find evidence that the candidate owned pipeline targets

This layer is semantic and evidence-oriented.

### Layer 3: Optional lexical / keyword retrieval layer

This layer is optional but highly useful.

Use it when:

- exact skill terms matter
- embeddings may miss acronym-heavy matches
- recruiter terminology is strict
- rare certifications or tool names are important

Examples:

- BRD
- FRD
- KPI
- Tableau
- HubSpot
- Figma
- Databricks

A practical system can use lexical filtering before or alongside semantic retrieval.

---

## 5. Core recommendation

The best design for this project is:

- structured JSON lookup for exact facts
- metadata-aware recursive chunk retrieval for evidence
- optional lexical filtering for term-sensitive requirements
- a router that decides which retrieval path to use

This is the recommended Hybrid RAG architecture for the hiring platform.

---

## 6. Why vectorless retrieval alone is not enough

If you only use vectorless retrieval on extracted JSON, the system becomes too shallow for scoring.

It may answer:

- degree present or not
- certification present or not
- company names
- date ranges

But it will struggle with:

- quality of project evidence
- depth of skill usage
- leadership ownership versus participation
- business context of a tool or responsibility
- requirement-specific explanation

That means vectorless retrieval alone is not enough for requirement-wise scoring.

---

## 7. Why recursive chunk RAG alone is also not enough

If you only use chunk-based RAG, then exact facts become less reliable than they should be.

For example, direct structured lookups are better for:

- contact fields
- exact education fields
- exact certifications
- normalized duration totals
- canonical skills already extracted and validated

Using chunk RAG for these simple facts creates unnecessary ambiguity and higher error rates.

So chunk RAG alone is also not enough.

---

## 8. Routing principle

The system should decide retrieval strategy based on **requirement type** or **query type**.

### 8.1 Use structured lookup when:

- the field is explicit
- the field is deterministic
- the field is already normalized
- no contextual interpretation is needed

### 8.2 Use chunk retrieval when:

- context matters
- evidence strength matters
- there are multiple mentions across resume sections
- professional versus academic context matters
- explanation must show supporting text

### 8.3 Use both when:

- a factual field must be confirmed by contextual evidence
- a requirement has both exact and contextual parts
- a recruiter asks a “what + why” question

Example:

- `Does the candidate have Power BI?` -> structured lookup may say yes
- `How strong is the candidate’s Power BI experience?` -> chunk retrieval is needed

---

## 9. Best retrieval strategy by requirement category

### 9.1 Core Skills

Recommended retrieval:

- first structured skill lookup
- then semantic evidence retrieval from experience/projects chunks

Why:

A skill may be listed explicitly, but the scoring engine should still inspect evidence of real usage.

### 9.2 Preferred Skills

Recommended retrieval:

- structured lookup if available
- semantic chunk retrieval if needed for strength validation

### 9.3 Experience

Recommended retrieval:

- structured normalized duration lookup for exact totals
- chunk retrieval for relevance, recency, and context

### 9.4 Education and Certifications

Recommended retrieval:

- primarily structured lookup
- chunk retrieval only for ambiguity resolution or evidence explanation

### 9.5 Responsibilities

Recommended retrieval:

- primarily chunk retrieval with section and metadata filters

Why:

Responsibilities usually require interpreting action, ownership, depth, and context.

---

## 10. Recursive text splitting: should you use it?

Yes, but not as your only retrieval basis.

Recursive chunking is useful because resumes are irregular documents. It helps preserve local context while producing chunks small enough for targeted retrieval.

A good chunking strategy should:

- preserve section boundaries where possible
- keep role/company/date blocks together
- keep project bullets together when possible
- keep contact/header information separate
- attach metadata such as section, page, experience type, candidate ID

So the answer is:

- **yes** to recursive text splitting for evidence retrieval
- **no** to using it as the only retrieval system

---

## 11. Metadata is the real multiplier

The performance of chunk retrieval improves a lot when you add metadata.

Recommended metadata on each chunk:

- `candidate_id`
- `document_id`
- `page_number`
- `section`
- `chunk_type`
- `experience_type` such as professional, academic, internship, project
- `date_range` if applicable
- `calculated_duration_months` if applicable
- `skills_asserted`
- `company_name` if applicable
- `job_title` if applicable

This makes retrieval much more accurate than plain chunk embeddings alone.

---

## 12. Threshold-based retrieval rule

The platform should use threshold-based retrieval rather than blindly taking the top-k chunks every time.

Recommended pattern:

1. retrieve candidate chunks for one requirement
2. apply metadata filters if relevant
3. score similarity
4. reject chunks below threshold
5. keep the highest-quality evidence set
6. store retrieved chunk IDs and similarity scores

This avoids polluting evaluation with irrelevant text.

---

## 13. Recommended retrieval router

A good router can be rule-based at first.

### 13.1 Router inputs

The router should consider:

- requirement category
- requirement label
- sub-query type
- whether the needed field already exists in structured JSON
- whether evidence explanation is required

### 13.2 Router outputs

The router should choose one of:

- `STRUCTURED_ONLY`
- `CHUNK_ONLY`
- `HYBRID_BOTH`
- `LEXICAL_PLUS_SEMANTIC`

### 13.3 Example router behavior

`Bachelor's degree present?`

- route: `STRUCTURED_ONLY`

`How strong is Python experience?`

- route: `HYBRID_BOTH`

`Show evidence of stakeholder leadership`

- route: `CHUNK_ONLY`

`Does the candidate mention HubSpot?`

- route: `LEXICAL_PLUS_SEMANTIC`

---

## 14. Recommended operational flow

For each requirement:

1. inspect requirement category and sub-query type
2. determine routing mode
3. fetch exact structured facts if needed
4. fetch evidence chunks if needed
5. combine results into an evaluation packet
6. pass the evaluation packet to rubric scoring
7. store all retrieval artifacts for audit

This keeps retrieval grounded and explainable.

---

## 15. Best strategy for your project

For your hiring system, use the following default strategy.

### 15.1 Structured layer should answer:

- who the candidate is
- exact education facts
- exact certification facts
- normalized experience totals
- exact links and contact details
- already-normalized skill lists

### 15.2 Chunk RAG layer should answer:

- how skills were used
- where leadership evidence exists
- how responsibilities map to the JD
- whether project work is relevant
- how strong or weak evidence is for a requirement

### 15.3 Hybrid layer should answer:

- requirement scoring inputs that need both exact facts and supporting evidence
- recruiter why-questions
- must-have validation with explanation

This matches your deterministic scoring design much better than a single retrieval mode.

---

## 16. Example

Take the requirement:

`REQ-RESP-004: Experience leading client-facing business workshops`

A good hybrid retrieval flow is:

- structured layer checks whether experience entries exist in relevant BA/consulting roles
- chunk layer retrieves resume bullets mentioning workshops, stakeholder sessions, elicitation, BRDs, or client meetings
- metadata filters prefer professional experience chunks over academic or project-only chunks
- retrieved evidence is passed to rubric scoring
- final score contribution is computed deterministically

Now take another requirement:

`REQ-EDU-001: Bachelor's degree in a quantitative discipline`

A good retrieval flow is:

- structured lookup checks education objects directly
- chunk retrieval is optional and mainly used for explanation or ambiguity resolution

These two requirements clearly do not need the same retrieval method.

---

## 17. What this is called

Yes, this is a **Hybrid RAG system**.

More precisely, it is a:

**structured + semantic + optional lexical hybrid retrieval architecture**

for resume evaluation.

If you want even more precise naming, you can describe it as:

**requirement-routed hybrid retrieval for deterministic hiring intelligence**

That would be a very accurate name for your project.

---

## 18. What not to do

Avoid these mistakes:

- using only structured JSON for all requirement evaluation
- using only chunk embeddings for exact facts
- using top-k retrieval without thresholds
- chunking without section metadata
- allowing retrieval results to directly determine final score without rubric logic
- mixing retrieval and scoring into one black-box step

---

## 19. Final recommendation

Use a router-driven Hybrid RAG system.

The practical default should be:

- **structured retrieval first** for exact facts
- **recursive chunk retrieval** for contextual evidence
- **optional lexical retrieval** for acronym-heavy or exact-term-sensitive requirements
- **deterministic scoring** after retrieval, never retrieval as ranking itself

This is the best retrieval architecture for your resume shortlisting platform because it is:

- more accurate
- more explainable
- more auditable
- more scalable across roles
- better aligned with requirement-wise scoring
