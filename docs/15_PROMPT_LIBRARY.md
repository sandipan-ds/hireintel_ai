# Prompt Library

> **Source of truth for scoring, evaluation, and ranking:**
> [`WORKING_LOGIC.md`](WORKING_LOGIC.md). For "what is implemented today vs
> what's planned", see [`CURRENT_PROGRESS.md`](CURRENT_PROGRESS.md).

## Overview

This document stores production prompt specifications for HireIntel AI.

Each production prompt must include a prompt ID, purpose, inputs, outputs, constraints, known limitations, and version history. Prompt changes must be versioned because prompt behavior affects parsing quality, evidence grounding, and recruiter-facing explanations.

---

## Prompt Index

| Prompt ID | Purpose | Status |
| --- | --- | --- |
| JD-EXTRACT-001 | Extract structured hiring requirements from a job description | Active (`recruiter/src/api/recruiter.py`) |
| JD-SUBQUERY-GEN-001 | Decompose requirements into structured binary and float sub-queries | Active (`recruiter/src/api/recruiter.py`) |
| RESUME-PARSE-001 | Extract a structured candidate profile from resume content | Planned (current parser is rule-based; LLM extraction is the upgrade path) |
| RUBRIC-SCORE-001 | Score candidate evidence against a recruiter-defined rubric | Active (`src/scoring/rubric_scorer.py`) |
| CANDIDATE-SUMMARY-001 | Generate an evidence-based recruiter summary | Planned |
| CANDIDATE-COMPARE-001 | Compare candidates using structured evidence | Active (used by `scripts/compare_two.py` when LLM is configured) |
| RESUME-CHAT-001 | Answer recruiter questions using retrieved resume chunks | Planned (LLM service scaffolded; no chat method or strict-grounding fallback implemented yet) |
| SCORE-EXPLAIN-001 | Narrate a per-item score using retrieved evidence + scorer output | Active (used by score-explanation flow) |
| HIRING-RECOMMENDATION-001 | Generate evidence-backed hiring recommendation text | Planned |
| RESUME-GAPFILL-001 | Re-extract missing profile fields from audit-flagged candidates using multimodal vision + text | Active (`scripts/gap_fill_extraction.py`) |

---

## JD-EXTRACT-001

**Purpose:** Extract structured requirements from a job description text to initialize the recruiter onboarding session.

**Inputs:**
- Raw job description text
- Role name

**Outputs:**
A JSON array of requirement objects conforming to:
```json
[
  {
    "req_id": "REQ-001",
    "name": "Short requirement name",
    "category": "Core Skill",
    "requirement_type": "required",
    "description": "Requirement description",
    "status": "GREEN",
    "reason": "GREEN/YELLOW/RED rationale"
  }
]
```

**Constraints:**
- Extract ONLY requirements explicitly stated in the Job Description text. Do not infer or add generic skills.
- Classify categories exactly into `Core Skill`, `Preferred Skill`, `Experience`, `Education`, or `Certification`.
- Restrict `requirement_type` exactly to `"required"` or `"preferred"`.
- Assign `status` exactly to `"GREEN"` (measurable/verifiable), `"YELLOW"` (somewhat vague but workable), or `"RED"` (too vague to score).

**Few-Shot Exemplars:**
* **Input Job Description Snippet:**
  ```text
  Required Skills:
  - Strong business analysis and requirement gathering experience.
  - Proficiency in SQL for data validation and analysis.
  Experience:
  - 6+ years in business analysis, product analysis, or related domain.
  ```
* **Output Extracted JSON:**
  ```json
  [
    {
      "req_id": "REQ-001",
      "name": "Business Analysis & Requirement Gathering",
      "category": "Core Skill",
      "requirement_type": "required",
      "description": "Strong business analysis and requirement gathering experience.",
      "status": "GREEN",
      "reason": "Specific core BA capability required."
    },
    {
      "req_id": "REQ-002",
      "name": "SQL for Data Validation & Analysis",
      "category": "Core Skill",
      "requirement_type": "required",
      "description": "Proficiency in SQL for data validation and analysis.",
      "status": "GREEN",
      "reason": "Explicit database query capability."
    },
    {
      "req_id": "REQ-003",
      "name": "6+ Years Business Analysis or Related Domain",
      "category": "Experience",
      "requirement_type": "required",
      "description": "6+ years in business analysis, product analysis, or related domain.",
      "status": "GREEN",
      "reason": "Specific tenure duration and domain defined."
    }
  ]
  ```

**Version History:**
- v0.1: Initial planned prompt specification.
- v1.0 (2026-07-15): Standardized exemplars around a unified Business Analyst Lead JD workflow at temperature 0.0.

---

## JD-SUBQUERY-GEN-001

**Purpose:** Decompose job requirements into 2–6 atomic sub-queries that can be evaluated objectively against candidate resumes.

**Inputs:**
- A JSON list of requirements (extracted from the JD)

**Outputs:**
A JSON object mapping each `req_id` to a list of sub-query objects conforming to:
```json
{
  "REQ-001": [
    {
      "sq_id": "SQ001",
      "text": "Sub-query text",
      "type": "binary",
      "scoring_hint": "Guidelines for grading",
      "status": "GREEN",
      "reason": "Rational for sub-query"
    }
  ]
}
```

**Constraints:**
- Restrict sub-query `type` exactly to `"binary"` (yes/no scored 0 or 1) or `"float"` (graded 0.01 / 0.25 / 0.50 / 1.00).
- Assign `status` exactly to `"GREEN"`, `"YELLOW"`, or `"RED"`.

**Few-Shot Exemplars:**
* **Input Extracted Requirements:**
  (Uses the exact same `REQ-001`, `REQ-002`, `REQ-003` from `JD-EXTRACT-001` output)
* **Output Decomposed JSON:**
  ```json
  {
    "REQ-001": [
      {
        "sq_id": "SQ001",
        "text": "Is there evidence that the candidate has served in a Business Analyst (or similar) role?",
        "type": "binary",
        "scoring_hint": "0 = no role evidence, 1 = role title/experience as BA/Analyst present",
        "status": "GREEN",
        "reason": "Directly verifiable BA role check."
      },
      {
        "sq_id": "SQ002",
        "text": "Has the candidate performed requirement gathering or elicitation activities?",
        "type": "binary",
        "scoring_hint": "0 = not mentioned, 1 = requirement gathering/elicitation explicitly mentioned",
        "status": "GREEN",
        "reason": "Verifiable activity check."
      },
      {
        "sq_id": "SQ003",
        "text": "How strong is their requirement gathering experience?",
        "type": "float",
        "scoring_hint": "0.01=No mention; 0.25=Few mentions (1-2 simple projects); 0.50=Some mentions (multiple projects, medium complexity); 1.00=Substantial (strategic role, complex enterprise projects)",
        "status": "GREEN",
        "reason": "Qualitative evaluation of experience depth."
      }
    ],
    "REQ-002": [
      {
        "sq_id": "SQ004",
        "text": "Is there evidence that the candidate knows SQL?",
        "type": "binary",
        "scoring_hint": "0 = not mentioned, 1 = SQL explicitly listed",
        "status": "GREEN",
        "reason": "Binary gate for database skill."
      },
      {
        "sq_id": "SQ005",
        "text": "Has the candidate used SQL specifically for data validation or analysis?",
        "type": "binary",
        "scoring_hint": "0 = no validation/analysis work, 1 = validation/analysis explicitly mentioned",
        "status": "GREEN",
        "reason": "Specific use case check."
      }
    ],
    "REQ-003": [
      {
        "sq_id": "SQ006",
        "text": "How many years of relevant experience does the candidate have (relative to expected 6 years minimum)?",
        "type": "float",
        "scoring_hint": "0.01=No mention; 0.25=Less than 2 years; 0.50=3 to 5 years; 1.00=6+ years",
        "status": "GREEN",
        "reason": "Duration gate checked using a 4-band scale."
      }
    ]
  }
  ```

**Version History:**
- v1.0 (2026-07-15): Implemented in `recruiter/src/api/recruiter.py` for sandbox onboarding. Runs concurrently in requirement chunks at temperature 0.0 using consistent Business Analyst exemplars.

---

## RUBRIC-SCORE-001

**Purpose:** Score candidate evidence against a recruiter-defined rubric for requirements
that require judgment (skill depth, relevant/same-role/leadership experience, project
complexity, domain expertise).

**Inputs:**
- A single JD requirement name (e.g. "Data Visualization Tools")
- The full content of retrieved evidence (threshold-based cosine ≥ θ, recursive chunks)
- Pre-computed employment history block: `Role | Company | Dates | Duration`
  (columns emitted in Role-first order so LLM correlates job titles with skill bullets)
- A recruiter-defined rubric with atomic sub-questions
- A pre-populated JSON skeleton (one entry per sub-question) — LLM fills in placeholders

**Outputs:**  
A JSON object with `sub_scores` array; each entry contains:
```json
{
  "key": "skill_presence",
  "evidence_found": "yes",
  "closest_evidence": "paste the most relevant resume text, even if indirect",
  "cited_text": "short exact quote",
  "sub_score": 1,
  "extracted_years": null,
  "anchor_description": ""
}
```

**evidence_found / closest_evidence semantics:**
- `evidence_found: "yes"` — LLM confirmed the resume directly proves the requirement
  (using Semantic Inference Rules)
- `evidence_found: "no"` — LLM found the closest text but no direct match
- `closest_evidence` — always populated with the most relevant text found, even if indirect
- This pair lets the report tag zero-scores as `[ZERO_NO_EVIDENCE]` vs
  `[ZERO_WRONG_INFERENCE]` for targeted debugging

**Semantic Inference Rules block (v2.0 addition):**

The prompt includes a `SEMANTIC INFERENCE RULES` section instructing the LLM to map
implicit resume language to formal requirement keywords before deciding `evidence_found`:

| Resume language | Counts as |
|---|---|
| "dashboard", "chart", "plot", "BI", "Tableau", "matplotlib" | Data Visualization |
| "clean", "preprocess", "ETL", "pipeline", "feature engineering" | Data Wrangling |
| "deploy", "API", "Docker", "MLflow", "production", "endpoint" | Model Deployment / MLOps |
| "Bachelor"/"B.Tech"/"B.S." in CS/Stats/Maths/Eng | Bachelor Degree Match |
| "classification", "regression", "clustering", "XGBoost", "random forest" | ML Models |
| "SQL", "PostgreSQL", "BigQuery", "Snowflake", "schema" | SQL / Databases |
| "Spark", "Hadoop", "Databricks", "distributed" | Big Data |
| "NLP", "sentiment", "ARIMA", "LSTM", "time series" | NLP / Time-Series |
| "AWS", "Azure", "GCP", "SageMaker", "cloud" | Cloud Platforms |

**Constraints:**
- **The LLM must not see the requirement's weight** while scoring evidence.
- **The LLM must never compute the final weighted contribution** — code does that.
- Score strictly against the recruiter-defined rubric — never against the LLM's own
  notion of "Advanced" or "Strong."
- Apply Semantic Inference Rules BEFORE deciding `evidence_found`.
- For binary keys: `sub_score` must be 0 or 1 (integer, no quotes).
- For linear keys: `extracted_years` must be a plain number (e.g. `3` or `2.5`), not
  a string. Use `null` if no evidence.
- Do NOT add extra keys. Do NOT change the `"key"` values.
- Output ONLY the JSON object, nothing else.

**Known Limitations:**
- qwen2.5:3b (the current rubric model) performs surface matching; the Semantic Inference
  Rules block in v2.0 partially compensates, but rare synonyms may still be missed.
- `calculated_duration_months` is computed in code and passed in the employment history
  block — LLM should use these durations, not re-compute from raw dates.
- Column-order in the employment history is now `Role | Company | Dates | Duration`
  (fixed in v2.0; prior versions emitted `Company | Role` which confused the LLM).

**Version History:**
- v0.1: Initial planned prompt specification per WORKING_LOGIC.md
- v1.0: Adopted as production prompt in `src/scoring/rubric_scorer.py`. Weight excluded
  from prompt; anchored scales enforced; extraction-before-scoring; cached scoring trace
  (`CachedScoringTrace`) frozen at scoring time.
- v2.0 (2026-07-09): Added `evidence_found` + `closest_evidence` JSON fields replacing
  `extracted_evidence`. Added SEMANTIC INFERENCE RULES block. Fixed employment history
  to emit `Role | Company | Dates | Duration` with explicit column header. Updated
  `SubScoreResult` dataclass and all parsing / explanation code accordingly.

---


## RESUME-PARSE-001

**Purpose:** Extract structured candidate profile information from resume text.

**Inputs:**
- Resume text
- Document metadata
- Optional section boundaries

**Outputs:**
- candidate identity fields
- contact fields
- education
- skills
- work experience
- projects
- certifications
- languages
- evidence references

**Constraints:**
- Do not invent missing fields.
- Preserve evidence for every extracted field where possible.
- Treat resume content as sensitive PII.

**Known Limitations:**
- OCR quality may affect extraction accuracy.

**Version History:**
- v0.1: Initial planned prompt specification.

---

## RESUME-CHAT-001

**Purpose:** Answer recruiter questions using retrieved resume content.

**Inputs:**
- Recruiter question
- Retrieved resume chunks (Recursive Chunking, threshold-based cosine ≥ θ, DEC-018/019)
- Candidate metadata allowed for display

**Outputs:**
- Grounded answer
- Source section references
- Missing-information response when evidence is unavailable

**Constraints:**
- Answer only from retrieved content.
- If evidence is missing, respond: "Information not found in candidate documents."
- Do not speculate.

**Known Limitations:**
- Retrieval failures may cause valid resume information to be unavailable to the prompt.
- The LLM may paraphrase evidence; the underlying chunks remain the source of truth.

**Version History:**
- v0.1: Initial planned prompt specification.
- v0.2: Reverted to Planned — `src/hireintel_ai/llm/service.py` does not yet implement a chat method or the strict-grounding fallback string.

---

## SCORE-EXPLAIN-001

**Purpose:** Narrate a per-item score from the deterministic scorer using the candidate's retrieved evidence.

**Inputs:**
- The candidate's `ItemEvaluation` (item_name, weight_percentage, expected_years, raw_score, score, matched, section, snippet, reason).
- The recruiter's question (e.g. "Why did this candidate receive 10% for Power BI?").

**Outputs:**
- A short paragraph that combines the scorer's reason with the cited snippet.
- Citation of the matched profile section.

**Constraints:**
- The LLM must not change the score.
- If the snippet does not actually support the score, return: "Evidence does not clearly support this score; please review manually."
- Cite the section name (e.g. "experience", "skills").

**Version History:**
- v0.1: Adopted as the production prompt for per-item score explanations.

---

## CANDIDATE-COMPARE-001

**Purpose:** Generate a recruiter-facing "Why A ranked above B" narrative from the deterministic comparison evidence.

**Inputs:**
- Candidate A's evaluation (per-item scores, sections, snippets).
- Candidate B's evaluation (same).
- Score delta and matched-item count delta.

**Outputs:**
- A 3-5 sentence narrative explaining the deterministic score difference.
- Citations to the items that drove the delta.

**Constraints:**
- Never claim a candidate is "better" without pointing at the specific item that drove the score.
- Never invent items that aren't in the evaluation payload.
- If the score delta is < 1.0, say so and recommend reviewing the candidates' full profiles.

**Version History:**
- v0.1: Adopted as the production prompt in `scripts/compare_two.py`.

---

## RESUME-GAPFILL-001

**Purpose:** Re-extract structured profile information from a resume using multimodal inputs (images + text) to fill missing fields (gaps) identified in the quality audit.

**Inputs:**
- Raw resume text
- Registry candidate name (for name verification/safety)
- Renders of PDF pages as base64 JPEG images (multimodal vision inputs)

**Outputs:**
A JSON object matching the standard `candidate_profile` schema containing:
- `full_name`
- `headline`
- `summary`
- `skills`
- `education`
- `experience`
- `projects`
- `certifications`
- `languages`

**Constraints:**
- Dates must conform to YYYY-MM format.
- responsibilities[] must be single short bullet points (never a single paragraph).
- skills[] must contain discrete technologies or concepts (never full sentences).
- If no data exists for a field, return an empty array `[]` or `null`.
- The output JSON must not contain markdown fences or formatting code tags.

**Version History:**
- v1.0 (2026-07-12): Implemented in `scripts/gap_fill_extraction.py` using OpenRouter/Google/NVIDIA NIM multimodal engines to rescue OCR-failed and scanned profiles.


