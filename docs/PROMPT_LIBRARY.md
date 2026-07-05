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
| JD-EXTRACT-001 | Extract structured hiring requirements from a job description | Planned |
| RESUME-PARSE-001 | Extract a structured candidate profile from resume content | Planned (current parser is rule-based; LLM extraction is the upgrade path) |
| RUBRIC-SCORE-001 | Score candidate evidence against a recruiter-defined rubric | Active (`src/scoring/rubric_scorer.py`) |
| CANDIDATE-SUMMARY-001 | Generate an evidence-based recruiter summary | Planned |
| CANDIDATE-COMPARE-001 | Compare candidates using structured evidence | Active (used by `scripts/compare_two.py` when LLM is configured) |
| RESUME-CHAT-001 | Answer recruiter questions using retrieved resume chunks | Planned (LLM service scaffolded; no chat method or strict-grounding fallback implemented yet) |
| SCORE-EXPLAIN-001 | Narrate a per-item score using retrieved evidence + scorer output | Active (used by score-explanation flow) |
| HIRING-RECOMMENDATION-001 | Generate evidence-backed hiring recommendation text | Planned |

---

## JD-EXTRACT-001

**Purpose:** Extract role requirements from a job description.

**Inputs:**
- Raw job description text
- Optional role title
- Optional employer-provided constraints

**Outputs:**
- Required skills
- Preferred skills
- experience requirements
- education requirements
- certifications
- industry requirements
- leadership requirements
- technology stack

**Constraints:**
- Do not infer requirements that are not present in the JD.
- Separate required and preferred requirements.
- Preserve evidence snippets for each extracted requirement.

**Known Limitations:**
- Ambiguous job descriptions may require recruiter confirmation.

**Version History:**
- v0.1: Initial planned prompt specification.

---

## RUBRIC-SCORE-001

**Purpose:** Score candidate evidence against a recruiter-defined rubric for requirements that require judgment (skill depth, relevant/same-role/leadership experience, project complexity, domain expertise).

**Inputs:**
- A single JD requirement (e.g. "5+ years in recommendation systems and clustering")
- The full content of the mapped section(s) for this requirement (Section-Routed Evidence Retrieval — exact label match, not similarity-ranked)
- A recruiter-defined rubric with explicit point scales (e.g. years used, project complexity, frameworks/tools, ownership level)
- Decomposed sub-questions for the requirement

**Outputs:**
- Extracted evidence: a structured list of what's relevant from the mapped section(s) (e.g. "list every role where Python appears, with dates")
- Sub-scores per sub-question on a 0.0–1.0 scale:
  - Binary gates (e.g. "Does the candidate know Python?") → 0 or 1
  - Linear measures (e.g. "years of experience / target years") → `min(candidate_years / ideal_years, 1.0)`
  - Relevance measures (e.g. "project relevance to JD") → 0.0 to 1.0
- Cited evidence for each sub-score (exact resume text)

**Constraints:**
- **The LLM must not see the requirement's weight** while scoring evidence against the rubric.
- **The LLM must never compute the final weighted contribution** — weight application and aggregation are performed in code.
- Score strictly against the recruiter-defined rubric — never against the LLM's own internal notion of "Advanced" or "Strong."
- Extract evidence **before** scoring — this keeps the read systematic rather than holistic, and prevents the model from being influenced by content outside the mapped section.
- Do not double-count overlapping experience (e.g. 6 years Python on cluster systems + 6 years managing recommendation projects ≠ 12 years).
- If evidence is insufficient for a sub-question, return 0 for that sub-question — do not speculate.

**Known Limitations:**
- The LLM may struggle with ambiguous date ranges in resumes; `calculated_duration_months` is computed in code and provided to mitigate this.
- Relevance scoring is inherently subjective; the rubric must define explicit anchors (0 = not relevant, 0.5 = partially relevant, 1.0 = exact match).

**Version History:**
- v0.1: Initial planned prompt specification per `WORKING_LOGIC.md` "Scoring Rubrics" and "Transforming the JD based requirements into sub-questions".
- v1.0: Adopted as production prompt in `src/scoring/rubric_scorer.py`. Weight excluded from prompt; anchored scales enforced; extraction-before-scoring; cached scoring trace (`CachedScoringTrace`) frozen at scoring time.

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

