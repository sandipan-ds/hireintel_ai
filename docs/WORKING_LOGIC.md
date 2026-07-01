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
Structured Profile     Document-Aware Chunking
Extraction              (entry-level, intact)
(degrees, certs,                ↓
 total experience,      Header Normalization
 companies, dates)       (canonical section labels)
        |                        ↓
         |              Section-Routed Evidence Retrieval
         |              (JD requirement → mapped
        |               section, full content sent)
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

**Rubric-bound LLM evidence scoring** — used wherever genuine judgment is required: skill depth, project complexity, domain expertise. The LLM reads the full content of the section(s) that requirement maps to (see Section-Routed Evidence Retrieval) and maps it onto a recruiter-defined point scale (years used, project complexity, frameworks/tools, ownership level) — never onto a free-form label. The LLM does not see the requirement's weight, and never computes the final weighted contribution.

In both modes, weight application and the final aggregated score are computed by code, never by the LLM. Full formulas are defined in **Scoring Rubrics**.

## Candidate Explanations

Performed using:

* Cached rubric reasoning from scoring time (default)
* Section-routed resume evidence (for follow-up questions)
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
3 years of experience must be calculated linearly capped at 5. (So it should be- 3/5=0.6)
Relevance of the projects to the JD requirement (in a scale of 0 to 1, 0 lowest, and 1 exact match)

So for a candidate whose resume says-

- Python with experience of 4+ years
- Worked in Netflix for Recommendation system for 3 years 
                                  
The normalized score should be:

Normalized Score for Python Skill and exp: 1* (4/5)* (0.8)= 1* 0.8* 0.8= 0.64

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

Requirements that require interpretation (e.g. "How deep is the candidate's Power BI expertise?") still rely on Section-Routed Evidence Retrieval and rubric-bound LLM evidence scoring (below).

---

# Document-Aware Chunking

The default chunking strategy is:

Document-Aware Chunking

Sections:

* Personal Information
* Education
* Experience
* Projects
* Skills
* Certifications
* Languages

The structure must be preserved.

Each entry within a section is kept as a single intact chunk — for example, a degree's institute, branch, and CGPA are never split apart, and a job's company, dates, and bullet points stay together as one unit. Splitting an entry across chunks is what causes facts to lose the context (dates, employer, degree) they belong to.

Real resumes do not use uniform section headers. Chunking is paired with Header Normalization, below, before any chunk is labeled, so that a resume titled "Core Competencies" and one titled "Skills" both resolve to the same canonical section.

This chunking supports:

* Section-Routed Evidence Retrieval
* Resume Chat
* Score Explanation
* Candidate Comparison
* Hiring Recommendations

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

# Section-Routed Evidence Retrieval

A JD requirement does not need to be searched for inside a resume — a resume is one short document (typically 1,000–3,000 tokens), and once it is chunked and header-normalized, the system already knows exactly where each requirement's evidence lives. Similarity ranking is the wrong tool here: a single resume isn't a corpus to search, it's something to read.

Each requirement is mapped to the canonical section(s) it depends on, by a fixed table, not a model decision:

```text
Education requirement      → Education chunk(s)
Skill / experience depth   → Experience + Projects + Skills chunks
Certification requirement  → Certifications chunk(s)
```

Retrieval here is an exact label match — fetch every chunk tagged with the mapped section(s) — never a ranked top-K subset. Nothing is filtered out, and the same requirement against the same resume always returns the same content, every time: no embeddings, no cosine similarity, and no risk of a relevant chunk silently falling below a similarity cutoff (e.g. a second Python role, or a second education entry, getting missed because it ranked just outside the top K).

This also avoids a subtler failure: fields that belong together (an institute, its branch, its CGPA) can never get split across separate retrieval calls and recombined incorrectly, because the entry was never split apart in the first place (see Document-Aware Chunking).

For each requirement, the LLM is asked to first extract what's relevant from the mapped section(s) (e.g. "list every role where Python appears, with dates"), then score against the rubric — extraction before scoring keeps the read systematic rather than holistic, and keeps the model from being influenced by content outside the mapped section (e.g. scoring CGPA more generously because the Experience section looked impressive).

If a section turns out to be unusually long (a senior candidate's multi-page Experience history), deterministic metadata filtering (`skills_asserted contains "Python"`) narrows it further — still an exact filter, not a similarity rank.

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

## Experience Scoring (Code-Only Formula)

For any "years of experience" requirement, the recruiter sets a target/ideal value. The score scales linearly and caps at the maximum:

```text
score = min(candidate_years / ideal_years, 1.0) × max_points
```

Note: `candidate_years` for **total experience** is read directly from the structured candidate profile (code-only, no LLM). `candidate_years` for **relevant / same-role / leadership experience** is extracted by the rubric-bound LLM from the mapped section(s) (see Section-Routed Evidence Retrieval), then the formula above is applied in code. The LLM never sees the weight or performs the final aggregation.

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

This is unrelated to evidence retrieval for scoring a single candidate, which uses Section-Routed Evidence Retrieval instead — full, intact sections, not similarity-ranked fragments.

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
3. If the recruiter asks a follow-up that goes beyond what was stored, re-fetch the mapped section(s) for that requirement (Section-Routed Evidence Retrieval) and generate a fresh answer grounded in them.

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
Header Normalization + Section-Routed Evidence
        ↓
Full Section Content per Requirement
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