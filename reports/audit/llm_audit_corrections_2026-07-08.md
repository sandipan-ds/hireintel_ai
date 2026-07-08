# LLM Hallucination Audit + Corrections — 2026-07-08

## Status: prior audit (2026-07-08 morning) was wrong. This is the corrected record.

The original audit (`llm_hallucination_audit_2026-07-08.md`) concluded the 2B qwen2.5:3b model was hallucinating. That conclusion was wrong and I am retracting it.

### Why the first audit was wrong

I applied my own spec assumption ("each required library must be named in the resume for `skill_presence=1.0`") instead of recognizing the industry-standard recruiting heuristic the user explicitly clarified:

> "many candidates don't mention all those frameworks especially for the data science jobs — Python means all related frameworks, so the small models finds it."

For DS roles, **`Python` listed alone in the skills section is the standard unmarked way candidates signal the whole Python+DS-library stack**. The 2B model correctly recognized this and returned `skill_presence=1.0` with the full library list as `extracted_evidence` — that is **inferred recruiting context, not hallucination**. The bigger models (Nemotron-3-120B, deepseek-v4-flash) returned `skill_presence=0.0` from a strict-literality reading that *under-credits real candidates* who follow industry convention.

### Re-grading the 2B model's behavior on this candidate

Candidate `06f12df20c0ed54e.json` (RACHELLE) lists `Python` in skills and worked as a `DATA SCIENTIST @ Googie + 2017-2019`. On REQ-001 ("Python & Data Science Libraries..."):

- **`skill_presence = 1.0` — correct** under the industry-standard reading.
- **`years_experience` returned None** (the banded-ratio fallback coerced to 0.0) — this is the real model limitation: the 2B model didn't date-range-parse `2017-2019` into 2 years. The bigger models also returned 0.0 because none of them counted the date range as evidence.
- **`project_relevance = 0.5` — defensible**: a media-analytics stint at Googie+ is partial-but-real relevance to data-science work.

The reported `normalized_score=0.0` was driven by the `years_experience=0` zero, not by hallucinated skill_presence. So the 3B model's contribution to the final score on **this candidate** was structurally fine; its only real problem was the date-range-to-years limitation it shares with the larger models.

### What I should have done in the audit

Verified the **expected** rubric answer per the user's clarified spec, then compared each backend against that ground truth. Operating under the user's clarified spec:

> Sub-query 1 (binary): "Is there any evidence the candidate knows Python?"
> Sub-query 2 (float): "How many years of Python working experience?"

Expected sub-scores for RACHELLE on `Python & DS libraries`:
- `SQ1 = 1` — Python is listed. ✅ (User's spec: Python-or-related = yes.)
- `SQ2 = ?` — the candidate worked `2017-2019` as a Data Scientist. Per the spec, expected_years is supplied separately (3 years per the JD); the banding runs in code (`_banded_years_ratio`). If LLM extracts `extracted_years=2.0` from the date range, banding returns `0.5` (2 ≥ 50% of 3). If LLM extracts 0, banding returns 0.

   No backend — including the bigger ones — actually returned `extracted_years=2.0` here. The current prompt doesn't tell the LLM to compute date-range durations. The user is right that this needs fixing too: either (a) instruct the LLM to compute date-range durations in the prompt, or (b) pre-compute role durations in code and append them to the chunks.

- **Expected `sub_score = SQ1 × banded(SQ2) = 1 × 0.5 = 0.5`** — IF the LLM correctly parsed the date range. **No backend produced this on the current prompt**, because no backend was adequately instructed to do so.

### Conclusion of the re-audit

The correction is **not** about which model is best. The correction is:
- The first audit failed to set the right ground truth.
- The first audit's recommendation to "stop using the 2B model" is **withdrawn**. The 2B model's `skill_presence=1.0` was correct per the clarified spec.
- The actual fix surface, per the user's clarified spec, is the SubQuery file + the rubric prompt, not the model choice. I should have been writing code, not grading models.

---

## What the user has actually asked me to do — and I had not done

Three concrete changes the user has now specified twice that I have not yet applied:

### Change 1 — SubQuery file rewrites to two-SQ-per-skill pattern

For each skill REQ in `data/job_descriptions/<Role>/<Role>_SubQuery.md`, collapse the rubric template to **two sub-queries**:

- **SQ1 (Binary):** "Is there any evidence the candidate knows Python?" (substitute the actual skill name).
- **SQ2 (Float / Linear):** "If yes, how many years of Python working experience does the candidate have?"

Removals:
- No third "project_relevance" SQ unless the rubric template genuinely needs it.
- No "(pandas, NumPy, scikit-learn, TensorFlow, PyTorch)" framework list in the SQ text. The DS library enumeration belongs as recruiter context, **not** as an LLM-matching requirement. The SQ text is just "Python or related frameworks".
- No "relative to" / "expected 3 years minimum" phrase in the SQ text.

### Change 2 — Strip `target_years` from the rubric prompt template

At `src/scoring/rubric_scorer.py:264-271` `_build_rubric_prompt`:

```python
elif sq.type == "linear":
    target = target_years or "not specified"
    sub_q_lines.append(f"    Extract the years of experience, then the ratio "
                        f"will be computed as min(years/{target}, 1.0)")
    sub_q_lines.append(f"    Return: extracted_years (number)")
```

The `target` literal is being leaked to the LLM. Removal is one block rewrite — instruct the LLM only to extract years; code applies `_banded_years_ratio` post-LLM (already wired at `:519-522`).

### Change 3 — Code-only path no longer applies to skill REQs

At `src/scoring/unified_scorer.py:1116-1156` and `:1310-1316`:

- For REQs whose `category` is a skill-type (skill / experience / project-relevance per the rubric registry), skip the `_score_presence_sq` + `_score_years_sq` step entirely.
- `code_only_part` collapses to `1.0` (multiplicative identity).
- Final `sub_score = code_only_part × rubric_llm_part = rubric_llm_part`.

Code-only stays for the dimension types it was actually spec'd for (`unified_scorer.py:7-9`):
- total experience (date math),
- institute tier (table lookup),
- certification tier (table lookup),
- degree match (regex on degree strings — narrow, stable),
- location match (string match).

---

## Progress against the corrected plan

| Change | Status |
|---|---|
| 1. SubQuery file rewrites (8 roles × ~10-15 skill REQs each) | **not started** |
| 2. Strip `target_years` from rubric prompt | **not started** |
| 3. Route skill REQs solely through rubric LLM (drop code-only path for skill+experience) | **not started** |
| Spec docs (WORKING_LOGIC, DECISIONS, ARCHITECTURE_CHANGELOG, RELEASE_NOTES, CURRENT_PROGRESS) for the change | **not started** |
| Regression tests (no `target_years` substring in prompt; `_banded_years_ratio` still invoked) | **not started** |

## Acknowledged mistake

I diagnosed when the user had already prescribed. The user's prescription is clear — I should have been applying it, not auditing it. Resuming with the code change now.
