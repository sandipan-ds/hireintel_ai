# Recruiter Workflows

> **Source of truth for scoring, evaluation, and ranking:**
> [`WORKING_LOGIC.md`](WORKING_LOGIC.md). This document is the recruiter-facing
> flow map. For "what is implemented today vs what's planned", see
> [`CURRENT_PROGRESS.md`](CURRENT_PROGRESS.md).

## Overview

This document describes how recruiters interact with HireIntel AI across job setup, resume processing, candidate evaluation, ranking, comparison, chat, and hiring recommendations.

The cardinal rule: **the platform must not assume what isn't stated**. When a JD is ambiguous, the platform asks the recruiter instead of silently defaulting.

---

## Workflow 1: Job Description Upload

1. Recruiter creates or selects a job.
2. Recruiter uploads a job description as PDF, DOCX, or text.
3. The platform validates the file and stores the original document.
4. The job description is sent for requirement extraction.

---

## Workflow 2: Requirement Extraction

1. The parser extracts structured hiring requirements.
2. Extracted requirements include required skills, preferred skills, experience, education, certifications, industry background, and technology stack.
3. Each requirement retains supporting evidence from the job description.
4. **Clarification classification:** every requirement is tagged Green / Yellow / Red.
   - **Green** — Clear and measurable (e.g. "Python with 5+ years"). Enters the scoring policy directly.
   - **Yellow** — Partially defined (e.g. "Strong Python Skills"). Auto-generates a follow-up question.
   - **Red** — Missing critical info (e.g. no experience duration). Hard-blocks the scoring policy.
5. The platform writes a `clarifications.json` next to the role's weight config listing open questions.
6. Recruiter reviews and corrects extracted requirements before scoring policy creation.

---

## Workflow 3: Recruiter Weight Configuration

1. The platform presents Green requirements to the recruiter. **Yellow and Red items block this workflow until clarified.**
2. Recruiter assigns two values per item:
   - **Weight percentage** 0–100% (how much this criterion matters). All percentages must sum to exactly **100%**.
   - **Expected years** (target years of experience for this criterion; defaults to 10 if recruiter omits).
3. The platform validates that weights are non-negative and that all Green items have either an explicit or default `expected_years`.
4. The platform validates that all percentages sum to exactly 100%.
5. The finalized scoring policy is locked and applied consistently to all candidates for the job.

---

## Workflow 4: Resume Upload

1. Recruiter uploads one or more candidate resumes.
2. The platform validates supported file types.
3. Original files are stored in object storage.
4. Parsing jobs are queued for asynchronous processing.

---

## Workflow 5: Resume Parsing

1. Resume text is extracted from PDF, DOCX, text, or OCR when needed.
2. **Resume cleaning** removes headers, footers, template noise, decorative elements, and duplicate content.
3. The parser extracts structured candidate profile fields.
4. Evidence references are attached to extracted fields where possible.
5. Structured profiles are stored for scoring, ranking, comparison, and RAG.

---

## Workflow 6: Candidate Evaluation

1. The **unified scoring engine** (`src/scoring/unified_scorer.py`) loads the scoring policy, candidate profile, chunks, and structured profile. It routes each requirement to code-only mode (`graded_scorer.py` + `tier_lookup.py`) or rubric-bound LLM mode (`rubric_scorer.py` + `rubrics.py`) based on the dimension type.
2. The engine operates in **two modes** (per `WORKING_LOGIC.md` "Fundamental Rule"):
   - **Code-only scoring** — for fully measurable requirements (total experience, skill presence + years, degree match, certification match, institute/cert tier lookups). Uses synonym dictionary + structured profile search + regex years detection. Computes `min(importance, candidate_years / expected_years × importance)` with partial credit for mention-only matches. No LLM involved.
   - **Rubric-bound LLM evidence scoring** — for requirements requiring judgment (skill depth, relevant/same-role/leadership experience, project complexity, domain expertise). The LLM receives the chunks retrieved by the threshold-based retrieval pipeline (cosine ≥ θ, DEC-018) and scores against a recruiter-defined rubric. The LLM **does not see the weight** and **never computes the final weighted contribution**.
3. In both modes, weight application and final score aggregation are computed in code.
4. The platform produces score values, explanations, evidence snippets, **matched profile sections**, and score breakdowns.
5. Rubric sub-scores and cited evidence are **cached at scoring time** for fast, consistent score explanations later.
6. **RAG may explain results but never produces them.** When the recruiter asks "Why did this candidate receive 78/100?", the system returns the cached reasoning first; if the follow-up goes beyond what was stored, it re-fetches the candidate's evidence via threshold-based retrieval and generates a fresh grounded answer — it cannot change the score.

---

## Workflow 7: Candidate Ranking

1. The platform aggregates candidate evaluation scores from the single scorer.
2. Candidates are sorted by deterministic total score (0–100).
3. Tie breakers: matched-item count first, then raw score, then candidate_id (deterministic).
4. Recruiters view ranked candidates with per-item score explanations.

---

## Workflow 8: Candidate Comparison

1. Recruiter selects two candidates or asks a comparison question.
2. The system retrieves structured profile evidence for both candidates.
3. The deterministic engine produces a side-by-side table: per-item scores, top strengths, biggest gaps.
4. If configured, the LLM narrates a "Why A above B" using the deterministic evidence — never the other way around.
5. Claims cite candidate profile fields or resume sections.

---

## Workflow 9: Resume Chat

1. Recruiter asks a question about a candidate or group of candidates.
2. The RAG pipeline retrieves relevant resume chunks via dense cosine over `data/embeddings/index.npz`.
3. The LLM (OpenRouter `minimax/minimax-m3`) answers only from retrieved evidence.
4. If evidence is missing, the response is exactly: **"Information not found in candidate documents."**
5. No speculation, no fabrication.

---

## Workflow 10: Hiring Recommendation

1. The platform combines ranked candidates, evaluation reports, and recruiter policy.
2. The recommendation engine generates an evidence-backed recommendation.
3. The recommendation must not contradict deterministic rankings.
4. Recruiters receive strengths, gaps, and source-backed justification.

