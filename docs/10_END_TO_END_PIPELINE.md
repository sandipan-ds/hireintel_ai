# End-to-End Pipeline: From PDF Upload to Deterministic Candidate Ranking

This document describes an end-to-end production pipeline for a resume shortlisting project in which candidates are matched to a job description using evidence-backed extraction, requirement-wise retrieval, rubric-based evaluation, and deterministic ranking.

The core philosophy is simple. Language models can help extract evidence and generate explanations, but the final candidate score must be computed in code using recruiter-defined weights and documented formulas.

## 1. System objective

The goal of the system is not to keyword-match resumes or produce opaque AI rankings. The goal is to evaluate each candidate against clearly defined job requirements in a reproducible and explainable way.

The pipeline should therefore answer three questions separately:

1. What information does the resume contain?
2. Which parts of that information support a particular job requirement?
3. How should those supported findings translate into a deterministic score?

## 2. High-level stages

The pipeline has nine stages:

1. job description intake and validation
2. recruiter requirement definition and weighting
3. resume ingestion and file classification
4. resume extraction and normalization
5. chunking and indexing
6. requirement-wise evidence retrieval
7. rubric-based requirement evaluation
8. deterministic score aggregation and ranking
9. explainable reporting and recruiter chat

## 3. Stage 1: Job description intake and validation

Start with the job description, not the resumes. A poor job description creates poor matching.

The system should clean and normalize the JD, then identify:

- explicit requirements
- ambiguous requirements
- missing but important requirements

If ambiguity exists, the recruiter should clarify it before candidate ranking begins. This keeps the evaluation standard stable across all candidates.

### Output of stage 1

```json
{
  "job_id": "job_001",
  "title": "Backend Engineer",
  "jd_cleaned": "...",
  "validation_findings": [
    {
      "type": "ambiguity",
      "text": "Strong experience in backend systems"
    }
  ]
}
```

## 4. Stage 2: Recruiter requirement definition and weighting

The validated JD is transformed into requirement blocks. These should be explicit, categorized, uniquely identified, and weighted by the recruiter.

Typical categories are:

- core skills
- preferred skills
- experience
- education and certifications
- key responsibilities

Each requirement gets a weight, and the total must sum to 100 percent.

### Example requirement block

```json
{
  "requirement_id": "req_001",
  "category": "core_skills",
  "label": "Python",
  "description": "Hands-on backend development experience using Python",
  "must_have": true,
  "weight_percent": 20,
  "rubric": {
    "type": "binary_or_banded",
    "anchors": [
      {"condition": "strong direct evidence", "score": 1.0},
      {"condition": "partial evidence", "score": 0.5},
      {"condition": "weak or indirect evidence", "score": 0.25},
      {"condition": "no evidence", "score": 0.01}
    ]
  }
}
```

## 5. Stage 3: Resume ingestion and file classification

When a resume is uploaded, the first task is to classify the file. The system should decide whether it is:

- a native-text PDF
- a scanned or image PDF
- a mixed PDF
- a DOCX or other supported format

This decision determines the extraction route.

### Example classifier outputs

```json
{
  "document_id": "doc_001",
  "ingestion_type": "native_pdf",
  "ocr_required": false
}
```

```json
{
  "document_id": "doc_002",
  "ingestion_type": "scanned_pdf",
  "ocr_required": true
}
```

## 6. Stage 4: Resume extraction and normalization

This stage converts the file into two parallel outputs.

The first output is a structured candidate profile containing fields such as contact details, skills, education, experience, certifications, projects, and languages.

The second output is a raw evidence representation that preserves extractable text, sections, page metadata, and local context needed for retrieval.

### Key rules for extraction

- do not invent missing data
- preserve raw evidence wherever possible
- normalize dates, canonical skill names, and institutions only after capturing source values
- mark uncertainty explicitly
- keep extraction independent from final scoring

### Example extraction output

```json
{
  "candidate_id": "cand_001",
  "candidate_profile": {
    "full_name": "John Doe",
    "skills": ["Python", "SQL", "Docker"],
    "education": [],
    "experience": []
  },
  "validation": {
    "status": "pending",
    "warnings": []
  }
}
```

## 7. Stage 5: Chunking and indexing

After extraction, the resume content should be chunked into retrievable units. Each chunk should have metadata such as candidate identifier, section, and page number.

This stage matters because a later requirement such as "experience with distributed systems" may only be supported by one project or one bullet point in the resume. Without chunking, targeted evidence retrieval becomes unreliable.

### Example chunk object

```json
{
  "chunk_id": "chunk_007",
  "candidate_id": "cand_001",
  "section": "projects",
  "page_number": 2,
  "text": "Built a distributed task queue using Python and Redis",
  "embedding_ready": true
}
```

These chunks are then embedded and stored in a vector index.

## 8. Stage 6: Requirement-wise evidence retrieval

For each requirement block, the system retrieves only the most relevant chunks for a given candidate. This should be threshold-based retrieval, not unrestricted semantic search.

The reason is simple. If the threshold is too loose, irrelevant chunks pollute evaluation. If the threshold is too strict, genuine evidence may be missed. The threshold should therefore be tuned using test data.

### Example retrieval event

```json
{
  "requirement_id": "req_004",
  "candidate_id": "cand_001",
  "retrieved_chunks": [
    {"chunk_id": "chunk_007", "similarity": 0.88},
    {"chunk_id": "chunk_010", "similarity": 0.81}
  ]
}
```

## 9. Stage 7: Rubric-based requirement evaluation

Each requirement is evaluated using the recruiter-defined rubric. A language model may help interpret retrieved evidence against a rubric, but it must operate only within that rubric and not invent new scoring logic.

The stored output for each requirement should include:

- the retrieved evidence
- rubric sub-scores
- a short evidence summary
- the final raw requirement score

### Example requirement evaluation

```json
{
  "requirement_id": "req_004",
  "candidate_id": "cand_001",
  "rubric_subscores": {
    "direct_skill_match": 1.0,
    "recency": 0.5,
    "depth_of_usage": 0.75
  },
  "raw_requirement_score": 0.8,
  "evidence_summary": "Candidate shows direct project evidence for distributed systems using Python and Redis. Evidence is explicit but limited in duration."
}
```

## 10. Stage 8: Deterministic score aggregation and ranking

Once all requirement evaluations are available, the final score is computed in code. This stage must be deterministic.

A simple weighted formula is:

```text
final_score = Σ(requirement_raw_score × requirement_weight)
```

If there are mandatory screening rules, apply them before final ranking. For example, candidates lacking a must-have certification may be flagged or excluded based on recruiter policy.

### Example scorecard

```json
{
  "job_id": "job_001",
  "candidate_id": "cand_001",
  "score_breakdown": [
    {"requirement_id": "req_001", "weight": 20, "raw_score": 1.0, "weighted_score": 20.0},
    {"requirement_id": "req_002", "weight": 15, "raw_score": 0.5, "weighted_score": 7.5}
  ],
  "total_score": 78.5,
  "rank_position": 3
}
```

## 11. Stage 9: Explainable reporting and recruiter chat

After ranking, the system should generate an explanation layer for the recruiter. This should not be a free-form opinion. It should be grounded in stored sub-scores and evidence.

A good report answers:

- why the candidate scored this way
- which requirements were strongest
- where evidence was weak or missing
- what text from the resume supports the score

A follow-up chat interface can answer recruiter questions by retrieving from the candidate’s stored chunks and evaluations.

## 12. Recommended service decomposition

A clean implementation can be split into the following services:

- JD processing service
- resume extraction service
- chunking and embedding service
- retrieval service
- rubric evaluation service
- deterministic scoring service
- explanation service
- recruiter review UI

This makes it easier to iterate on one layer without destabilizing the whole system.

## 13. Failure handling and review queues

Real resumes are messy, so production systems need review paths.

Send a resume to manual review if:

- OCR confidence is too low
- name or contact details are missing
- experience dates are inconsistent
- too few chunks are retrievable for key requirements
- field confidence is below threshold for critical sections

The review queue should not change the scoring philosophy. It only protects data quality.

## 14. Suggested development roadmap

A good build order is:

1. implement JD requirement blocks and recruiter weights
2. build canonical resume extraction JSON
3. build chunking plus metadata storage
4. add embeddings and threshold retrieval
5. implement requirement-wise rubric evaluation
6. implement deterministic weighted score aggregation
7. build explanation and recruiter review screens

This order reduces risk because it locks down the scoring contract early.

## 15. Final recommendation

For your project, success depends on preserving a strict separation of responsibilities. Resume extraction finds evidence. Retrieval links evidence to requirements. Rubrics translate evidence into raw requirement scores. Deterministic scoring produces rank. Explanations simply expose the stored reasoning trail.

If you preserve that separation, the system remains explainable, reproducible, and recruiter-controlled even when resume formats are messy.

## 16. Multi-role refinement based on the attached scoring documents

The attached documents make it clear that the pipeline should be generalized into a role-pack-driven platform. The Data Science example is not the architecture itself. It is one instance of a repeatable pattern that should also work for Business Analyst Lead, Sales Manager, Web Designer, and other roles.

### 16.1 Treat each role as a configurable scoring pack

A reusable role pack should contain at least these assets:

1. a source job description or role brief
2. normalized requirement blocks with REQ IDs
3. atomic sub-query definitions for each requirement
4. recruiter-facing weight configuration guidance
5. example or actual weight JSON summing to 100
6. rubric definitions for binary, float, banded-years, and two-band education checks

This means your pipeline should have a role-template stage before live scoring begins.

### 16.2 Revised high-level multi-role flow

A more reusable end-to-end flow is:

1. choose or create a role template
2. validate the uploaded JD against the role template
3. finalize requirement blocks and unresolved clarifications
4. collect recruiter weights summing to 100
5. parse and normalize resumes into one canonical extraction schema
6. chunk and index resume evidence
7. evaluate each candidate requirement by requirement using atomic sub-queries
8. compute normalized contributions using deterministic formulas
9. aggregate final scores to 100 and rank candidates
10. expose explanations from stored evidence and sub-scores

This is the same core logic as the Data Science example, but generalized for any role.

### 16.3 Keep categories fixed, change labels by role

The attached guides strongly suggest that the engine should keep stable category families across roles. The recommended categories are:

- Core Skills
- Preferred Skills
- Experience
- Education and Certifications
- Key Responsibilities

What changes across roles is the content inside these categories. For example:

- Data Scientist: Python, SQL, model evaluation, MLOps
- Business Analyst Lead: requirement gathering, stakeholder management, BI tools, documentation
- Sales Manager: revenue ownership, pipeline management, lead conversion, client relationship management
- Web Designer: typography, visual hierarchy, Figma or Adobe tools, portfolio quality, responsive design responsibilities

The pipeline should therefore not branch into entirely different engines for each role. It should use the same scoring engine fed by different requirement packs.

### 16.4 Standard sub-query pattern for all roles

The attached documents show a repeatable decomposition strategy that should become a platform standard.

For each requirement, build 2 to 6 atomic sub-queries using combinations of:

- binary evidence existence
- binary correct-context usage
- float evidence-strength using anchored bands
- float years or duration relative to a target
- deterministic lookup values such as degree match or tier lookup

This is important because it gives you a universal scoring grammar that can be reused across roles without relying on opaque whole-resume judgment.

### 16.5 Standard contribution formula

The attached documents converge on a reusable formula for requirement contribution:

```text
Sub-Score = SUM(sub-query scores)
Contribution = Recruiter_Weight × (Sub-Score / Number_of_Sub_Queries)
Final Candidate Score = SUM(all requirement contributions)
```

The pipeline should treat this formula as a platform-level invariant. Role packs may change requirements, sub-query counts, rubrics, and weights, but not the explainable aggregation logic.

### 16.6 Role-specific examples of reuse

The Data Science documents make the reuse principle very clear even though they only define one role in detail. Based on the role examples mentioned across the documents, the pipeline should support at least these kinds of translations:

- for a Data Scientist role, the retrieval engine may look for model-building, SQL, deployment, and experimentation evidence
- for a Business Analyst Lead role, the same engine may look for stakeholder workshops, BRDs, user stories, SQL analysis, and leadership evidence
- for a Sales Manager role, the same engine may look for target ownership, account growth, pipeline coverage, team leadership, and CRM usage
- for a Web Designer role, the same engine may look for portfolio links, design tools, responsive design work, client-facing revisions, and visual systems

The pipeline mechanics remain unchanged. Only the requirement blocks, sub-queries, rubrics, and recruiter weight distributions change.

### 16.7 Recommended new stage: role template authoring

To make this operational, add a role-template authoring stage before recruiter configuration. That stage should produce:

- canonical role name
- list of requirement blocks
- default categories
- draft sub-query sets
- suggested weights or example allocation
- clarifying questions for ambiguous requirements

This will help you scale from one example role to many without redesigning your system every time.

## 17. Final multi-role recommendation

Your platform should have one universal resume-processing and scoring engine, plus many role-specific configuration packs. The extraction contract, chunking strategy, retrieval approach, normalized scoring formula, and explanation model should stay constant. The role packs should supply the requirement definitions, sub-query structure, recruiter weighting, and rubrics. That is the most faithful generalization of the attached documents into a scalable hiring platform.
