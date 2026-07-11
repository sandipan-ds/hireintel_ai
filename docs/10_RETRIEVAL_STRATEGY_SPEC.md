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


---

## Extended Specification (Supplement)

# RETRIEVAL_STRATEGY_SPEC.md

## 1. Purpose

This document defines the retrieval strategy for the hiring system.

Its purpose is to specify how the platform should retrieve evidence for:

- requirement-level candidate scoring
- recruiter resume chat
- score explanation
- candidate comparison
- follow-up evidence inspection

The retrieval layer must support the broader system principle described in `WORKING_LOGIC.md`:

- LLMs may help interpret evidence
- retrieval may help gather evidence
- but final candidate ranking must remain deterministic and recruiter-controlled

This document focuses specifically on **how evidence should be found** before evaluation or explanation.

---

## 2. Core Principle

Retrieval is not one thing.

The system should not rely on a single retrieval method for every question.

Instead, retrieval should be **mode-based**.

Depending on the task, the platform should choose among:

- structured retrieval
- semantic retrieval
- lexical retrieval
- hybrid retrieval

This matters because resume evidence exists in more than one form.

Some facts are best retrieved from structured fields.

Examples:

- total years of experience
- degree name
- current location
- certification names
- list of known skills extracted into JSON

Other evidence is best retrieved from chunked text.

Examples:

- how a candidate used a skill
- whether a responsibility was ownership or support
- whether leadership was direct or indirect
- whether project evidence is relevant to a requirement
- what exact wording supports an explanation

Therefore, the correct rule is:

**use the simplest retrieval method that can answer the question reliably; use hybrid retrieval when a single method is insufficient.**

---

## 3. Retrieval objectives

The retrieval layer must support five major objectives:

### 3.1 Requirement-level evidence retrieval

Find the best evidence for one requirement block or sub-query during scoring.

### 3.2 Recruiter-facing Q&A

Answer questions about a candidate resume using grounded evidence.

### 3.3 Score explanation

Return the evidence that justified a sub-score or requirement evaluation.

### 3.4 Candidate comparison

Retrieve comparable evidence for the same requirement across candidates.

### 3.5 Candidate pool search and triage

Support open-ended search such as finding resumes relevant to a target skill or role.

This last use case is related but should be treated separately from per-candidate scoring retrieval.

---

## 4. Types of retrieval in the system

### 4.1 Structured retrieval

Structured retrieval means fetching information from canonical extracted fields.

Examples:

- `candidate_profile.skills`
- `candidate_profile.education`
- `candidate_profile.experience`
- `candidate_profile.certifications`
- normalized dates, durations, and titles

This is the most reliable retrieval mode for explicit facts.

### 4.2 Semantic retrieval

Semantic retrieval means retrieving the most relevant resume chunks using embeddings and vector similarity.

Use this when the system needs meaning-based matching rather than exact string matching.

Examples:

- requirement asks for experimentation but resume says A/B testing
- requirement asks for stakeholder management but resume says cross-functional coordination
- requirement asks for building pipelines but resume describes ETL orchestration

### 4.3 Lexical retrieval

Lexical retrieval means keyword or term-based matching.

This is especially useful when exact phrases matter.

Examples:

- certification names
- tool names
- framework names
- proper nouns
- version-sensitive terms
- abbreviations such as BRD, SQL, NLP, MLOps

### 4.4 Hybrid retrieval

Hybrid retrieval combines structured, semantic, and lexical evidence to answer one question or score one requirement.

This should be the default mode for complex requirement evaluation.

---

## 5. The retrieval rule hierarchy

The system should follow a simple decision hierarchy.

### Rule 1: Use structured retrieval first for explicit facts

If a requirement can be answered directly from normalized fields, use structured lookup first.

Examples:

- whether the candidate has a Bachelor’s degree
- how many years of experience are recorded
- whether the candidate lists Python
- whether a certification exists

### Rule 2: Use lexical retrieval when exact named entities matter

If the requirement is sensitive to exact keywords, named tools, or certification titles, add lexical matching.

Examples:

- AWS Certified Solutions Architect
- Power BI
- Snowflake
- TensorFlow
- Databricks

### Rule 3: Use semantic retrieval when meaning matters more than wording

Use semantic retrieval when the system must identify relevant evidence even if the resume uses different wording.

### Rule 4: Use hybrid retrieval when the requirement needs both factual grounding and contextual evidence

This is common for real hiring requirements.

Example:

A recruiter may want to know whether the candidate has Python, how recently they used it, how deeply they used it, and whether the usage was production-level.

A single retrieval mode is usually insufficient.

---

## 6. Retrieval units

The retrieval system should operate over different units depending on the task.

### 6.1 Structured objects

Examples:

- skill objects
- experience objects
- education objects
- certification objects
- project objects

### 6.2 Evidence chunks

These are the chunked text units defined in `CHUNKING_AND_METADATA_SPEC.md`.

Primary retrieval units should generally be:

- `experience_entry`
- `project_entry`
- `education_entry`
- `certification_entry`
- `skills_block`

### 6.3 Child chunks

Examples:

- `experience_bullet`
- `project_bullet`

These are useful when finer retrieval precision is needed.

---

## 7. Retrieval strategies by use case

## 7.1 Retrieval for requirement-level scoring

This is the most important retrieval path in the platform.

For each requirement block or sub-query:

1. inspect the requirement type
2. choose initial retrieval mode
3. gather candidate evidence
4. filter weak evidence
5. send only grounded evidence into the evaluator
6. store retrieved evidence references for auditability

### Requirement categories and recommended retrieval modes

#### A. Core technical skills

Use **hybrid retrieval**.

Why:

- structured skills list may confirm presence
- lexical search may find exact tool names
- semantic search may find contextual usage in projects or roles

Examples:

- Python
- SQL
- Machine Learning
- Power BI
- Spark

#### B. Preferred skills

Use **hybrid retrieval**, but allow weaker evidence bands than core skills.

#### C. Experience years

Use **structured retrieval first**.

Primary evidence should come from normalized date ranges and role history.

Semantic chunks may be used only to clarify ambiguity, such as whether work was professional or academic.

#### D. Education

Use **structured retrieval first**, then lexical verification if needed.

#### E. Certifications

Use **structured + lexical retrieval**.

Certification titles are often exact and name-sensitive.

#### F. Responsibilities and ownership

Use **semantic + lexical retrieval**, often with parent-child chunk support.

Examples:

- led stakeholder workshops
- designed ML models
- deployed models to production
- collaborated with engineering

#### G. Domain relevance

Use **semantic retrieval** first, optionally anchored by lexical terms.

Examples:

- fintech experience
- healthcare analytics
- e-commerce optimization

---

## 7.2 Retrieval for recruiter resume chat

Resume chat must always be grounded in the candidate’s own stored evidence.

Recommended retrieval sequence:

1. classify whether the question is factual, interpretive, comparative, or exploratory
2. use structured retrieval if the question asks for an explicit fact
3. use chunk retrieval if the question asks for supporting context or narrative evidence
4. use hybrid retrieval if both are needed
5. answer only from retrieved evidence

Examples:

- “Does this candidate have SQL?” → structured first, then lexical validation if needed
- “Where did this candidate use forecasting?” → semantic chunk retrieval
- “Did this candidate lead or just assist?” → semantic retrieval over responsibility chunks

---

## 7.3 Retrieval for score explanations

This is different from fresh evidence discovery.

If the system already stored requirement-level retrieved evidence and reasoning, the explanation layer should prefer:

1. cached evidence references
2. cached sub-scores
3. cached rationale objects

Fresh retrieval should be a fallback, not the first step.

This is important for reproducibility.

A user asking why a candidate got a score should see the evidence that actually informed the score, not newly discovered evidence that was not part of the original evaluation.

---

## 7.4 Retrieval for candidate comparison

Comparison requires aligned retrieval.

The system should retrieve evidence against the **same requirement or comparison lens** for each candidate.

Examples:

- compare SQL evidence across Candidate A and Candidate B
- compare leadership evidence across shortlisted candidates
- compare project deployment experience across finalists

Recommended rule:

- same query intent
- same retrieval mode family
- same threshold policy
- same explanation structure

This prevents unfair comparison caused by inconsistent retrieval.

---

## 7.5 Retrieval for candidate pool search

This use case is different from requirement scoring.

Pool search is broader and often open-ended.

Examples:

- find resumes similar to this job description
- find candidates with NLP and MLOps
- shortlist candidates for experimentation-heavy data science roles

Recommended approach:

- use embeddings over candidate-level representations or aggregated chunk representations
- optionally combine with filters such as location, years, degree, or required certifications
- treat this as discovery or triage, not final scoring

Pool search may help select which resumes to score, but it must not replace the scoring engine.

---

## 8. Query construction for retrieval

Retrieval quality depends heavily on query construction.

The system should not always pass raw requirement text directly into retrieval.

Instead, it should generate retrieval queries from normalized requirement blocks.

A requirement block may contain:

- requirement ID
- category
- normalized statement
- synonyms or expansions
- must-have vs preferred flag
- expected evidence types

Example:

Requirement:

```text
Experience deploying machine learning models into production
```

Possible retrieval query forms:

- production ML deployment
- model deployment production pipeline
- deployed machine learning model API batch inference monitoring

These queries may be generated deterministically or with controlled LLM assistance, but the retrieval target remains evidence, not score.

---

## 9. Metadata-aware retrieval

Retrieval should not rely on embeddings alone.

Chunk metadata should be used to improve precision.

Recommended filters include:

- section = experience
- chunk_type = experience_entry or project_entry
- experience_type = professional
- candidate_id = specific candidate
- date recency filters
- current role only
- certifications only
- education only

Examples:

- for years-of-experience scoring, prioritize professional experience chunks
- for certification lookup, restrict to certification chunks and certification JSON objects
- for degree validation, prioritize education entries

---

## 10. Threshold-based retrieval

The platform should use threshold-based relevance filtering instead of blindly taking top-k results.

### Why thresholds matter

Top-k alone can force irrelevant evidence into the evaluator, especially when a candidate simply lacks a requirement.

That creates noisy scoring and weak explanations.

### Recommended principle

Retrieve evidence only if it crosses a minimum relevance threshold.

If no chunk crosses threshold, the system should allow a **no reliable evidence found** outcome.

This is better than hallucinating support.

### Operational behavior

For semantic retrieval:

- score each candidate chunk against the requirement query
- keep only chunks above threshold `θ`
- optionally cap final evidence count after thresholding

For lexical retrieval:

- require exact or high-confidence term match when exact entities matter

For hybrid retrieval:

- use a fusion rule, then threshold fused evidence quality

---

## 11. No-evidence handling

The retrieval system must explicitly support no-evidence outcomes.

Possible cases:

- candidate truly does not have the requirement
- resume wording is too weak to support the requirement
- evidence exists but extraction failed
- evidence exists but retrieval query needs refinement

The evaluator should distinguish between:

- explicit negative evidence
- absence of evidence
- ambiguous evidence

This distinction is very important for fair scoring and explanation.

---

## 12. Evidence packaging for evaluation

Retrieval should not dump raw results into the evaluator without structure.

Evidence should be packaged in a normalized format such as:

```json
{
  "requirement_id": "R12",
  "candidate_id": "cand_001",
  "retrieval_mode": "hybrid",
  "evidence": [
    {
      "chunk_id": "chunk_exp_014",
      "chunk_type": "experience_entry",
      "relevance_score": 0.86,
      "matched_terms": ["Python", "SQL"],
      "text": "Built Python ETL pipelines and SQL-based reporting workflows...",
      "metadata": {
        "company_name": "ABC Analytics",
        "job_title": "Data Analyst"
      }
    }
  ]
}
```

This package can then be passed into rubric-level evaluation and stored for audit.

---

## 13. Evidence storage for reproducibility

For every requirement evaluated, the system should store:

- retrieval query or normalized query form
- retrieval mode used
- retrieved chunk IDs
- structured fields consulted
- threshold used
- final evidence package sent to evaluator
- timestamp and version identifiers

This is necessary because later explanations should refer back to the evidence actually used during scoring.

---

## 14. Retrieval and deterministic scoring

Retrieval may involve embeddings or LLM-assisted query formation, but retrieval must not determine the final score by itself.

The correct separation is:

- retrieval finds candidate evidence
- evaluators interpret evidence against sub-query rubrics
- deterministic code aggregates sub-scores using recruiter weights

This protects the system from black-box ranking.

---

## 15. Parent-child retrieval behavior

If child chunks are used, the system should preserve context.

Recommended rule:

- retrieve child chunks for precision
- attach parent chunk for context during evaluation or explanation

Example:

A bullet saying “deployed models to production” is useful, but the parent chunk may also reveal:

- the company
- the role title
- the time period
- whether deployment was part of a larger ML ownership scope

Without parent context, evidence can be misinterpreted.

---

## 16. Re-ranking strategy

When the initial retrieval set is broad, the system may re-rank results before evaluation.

Recommended re-ranking signals:

- semantic relevance
- exact term match
- section priority
- chunk type priority
- recency
- professional experience preference over academic evidence where required
- parent chunk relevance

This can remain deterministic even if embeddings are used upstream.

---

## 17. Retrieval by requirement category

This section gives a compact mapping between requirement types and recommended default retrieval modes.

| Requirement type | Default retrieval mode | Notes |
|---|---|---|
| Explicit skill presence | Structured + lexical | Add semantic if context needed |
| Skill depth / applied usage | Hybrid | Usually needs project/experience context |
| Years of experience | Structured | Semantic only for clarification |
| Degree qualification | Structured + lexical | Education chunks as backup |
| Certification validation | Structured + lexical | Exact names matter |
| Responsibility / ownership | Semantic + lexical | Often use experience/project chunks |
| Domain relevance | Semantic | Optionally add lexical anchors |
| Tool / platform familiarity | Hybrid | Skill list alone may be insufficient |
| Communication / collaboration evidence | Semantic | Usually inferred from role/project text |
| Production deployment | Hybrid | Needs contextual evidence |

---

## 18. Failure modes to avoid

The retrieval layer should avoid the following anti-patterns:

### 18.1 Over-reliance on embeddings alone

This can miss exact certifications, versions, and tool names.

### 18.2 Over-reliance on exact keywords alone

This can miss semantically equivalent evidence.

### 18.3 Retrieving top-k without thresholding

This can inject irrelevant evidence into scoring.

### 18.4 Mixing scoring retrieval with pool-search retrieval

These are different tasks and should not share the same assumptions.

### 18.5 Fresh retrieval during explanation when cached evidence exists

This harms reproducibility.

### 18.6 Ignoring metadata filters

This increases noise and can surface irrelevant sections.

---

## 19. Recommended operational retrieval pipeline

For requirement-level scoring, the recommended pipeline is:

1. load normalized requirement block
2. identify requirement category
3. choose retrieval mode using policy rules
4. construct retrieval query or query set
5. retrieve from structured fields and/or chunk indexes
6. apply metadata filters
7. threshold weak evidence out
8. optionally re-rank
9. package final evidence
10. pass evidence to rubric evaluator
11. store retrieval artifacts for audit and explanation

---

## 20. Example workflows

### Example A: Requirement = “Python proficiency”

Recommended retrieval:

- structured lookup in skills JSON
- lexical search for Python in skills/project/experience chunks
- semantic retrieval for evidence of actual usage if the rubric asks for depth

### Example B: Requirement = “3+ years in Data Science role”

Recommended retrieval:

- structured experience date calculations first
- use title normalization and experience type filters
- use chunks only if ambiguity exists around role relevance

### Example C: Requirement = “Deployed ML models to production”

Recommended retrieval:

- semantic retrieval over experience/project chunks
- lexical anchors such as deployment, production, API, inference, monitoring, pipeline
- prefer professional experience chunks over academic projects if the rubric requires industry evidence

### Example D: Recruiter asks “Did this candidate lead stakeholders or just support analysis?”

Recommended retrieval:

- semantic retrieval over experience and project chunks
- lexical anchors such as led, owned, partnered, supported, assisted, coordinated
- return evidence snippets, not only a yes/no

---

## 21. Relation to other specs

### Relation to `CHUNKING_AND_METADATA_SPEC.md`

That document defines the evidence objects and metadata used by semantic and hybrid retrieval.

### Relation to `RESUME_EXTRACTION_SPEC.md`

That document defines the structured data layer used by structured retrieval.

### Relation to `SCORING_FORMULA_SPEC.md`

That document defines what happens after evidence is retrieved and interpreted.

### Relation to `JSON_QUALITY_AUDIT_SPEC.md`

That document can audit whether the retrieval inputs were complete, traceable, and internally consistent.

### Relation to `WORKING_LOGIC.md`

This document operationalizes the retrieval portion of the broader system philosophy described there.

---

## 22. Final recommendation

The hiring system should adopt a **retrieval-policy architecture**, not a one-size-fits-all retriever.

The default mindset should be:

- use structured retrieval for explicit facts
- use lexical retrieval for exact entities
- use semantic retrieval for meaning-based evidence
- use hybrid retrieval for most real scoring requirements
- always apply thresholds, metadata filters, and audit storage

This retrieval strategy best supports recruiter-controlled, explainable, reproducible candidate evaluation.

