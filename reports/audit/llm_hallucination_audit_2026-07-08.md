# LLM Hallucination Audit Report — 2026-07-08

**Subject:** Is the rubric-bound LLM extracting correct sub-scores, or hallucinating evidence?

**Scope:** One REQ (REQ-001 "Python & Data Science Libraries") against one candidate (`06f12df20c0ed54e.json`, name RACHELLE) scored live across three LLM backends (Ollama qwen2.5:3b, OpenRouter nvidia/nemotron-3-super-120b-a12b:free, opencode.ai deepseek-v4-flash-free).

**Prompt construction:** The rubric scorer built the canonical RUBRIC-SCORE-001 prompt with `target_years=3.0` (the current production behavior that the user flagged as a hallucination risk). Same prompt was sent verbatim to every backend. Same retrieved chunks (% chunks, 1510 chars total).

**Verdict methodology:** For each sub-score the LLM returned, check whether `cited_text` actually appears as a substring of the retrieved chunk text, and whether `extracted_evidence` is consistent with what the chunks actually contain.

---

## 1. What the chunks actually contain

The retrieval pipeline surfaced 3 chunks (1510 chars) for REQ-001 against this candidate. Their content, abridged:

```
DATA SCIENTIST @ Googie +
2017-2019
- Developed insights into the performance
- of Network/Studio programs and their
- competitors across all platforms
- (including linear, multiplatform and
- svoD)
- DATA SCIENTIST
Microsoft Office (Word, Excel, PowerPoint), Six Sigma (Black Belts), Information,
Technology Delivery, methods, PHP, Python, HTML, css, Minitab, SPSS, DATA SCIENTIST,
Work Experience, DATA SCIENTIST, Googie + 2017-2019, Developed insights into the
performance, of Network/Studio programs and their, competitors across all platforms,
(including linear, multiplatform and, svoD), DATA S
```

**Ground truth for this candidate on REQ-001:**
- **Skill presence:** The candidate lists **only `Python`** from the required stack. The other 5 libraries (pandas, NumPy, scikit-learn, TensorFlow, PyTorch) are **nowhere in the resume**.
- **Years:** Resume stores experience as date ranges (`2017-2019`), not "N years" phrases. No explicit "3 years of Python" claim anywhere — neither in the chunks nor in the structured profile.
- **Project relevance:** The candidate has one DS-ish stint at Googie+ (2017-2019) doing media-analytics insights.

**Ground-truth rubric answer for this candidate against REQ-001** (per the spec's `gate × years_ratio × relevance` formula):
- `skill_presence`: 1.0 if the rubric counts "Python alone" as passes-presence-for-the-Python-stack, else 0.0 if the rubric requires the full library list. Either reading is defensible; an honest LLM should make the call and explain it.
- `years_experience`: 0.0 if "no explicit years for Python"; 2.0 if date-range `2017-2019 = 2 yrs`. **Either is honest**, as long as the LLM says what it computed and **does not** claim 3.0.
- `project_relevance`: 0.25 if the Googie+ project is tangentially related, 0.5 if substantially related. Either band is defensible.

---

## 2. Per-backend results

### Backend A — Ollama qwen2.5:3b (local, free, 17.3s)

| Sub-question | sub_score | extracted_years | extracted_evidence | cited_text verdict |
|---|---|---|---|---|
| skill_presence | **1.0** | — | `['Python', 'pandas', 'NumPy', 'scikit-learn', 'TensorFlow', 'PyTorch']` | CITED_PRESENT |
| years_experience | **0.0** | None (defaulted) | `None` | NO_CITE |
| project_relevance | **0.5** | — | `['pandas', 'NumPy', 'scikit-learn', 'TensorFlow', 'PyTorch']` | CITED_PRESENT |

`normalized_score = gate*yrs*relevance` → `1 * 0 * 0.5 = 0.0`.

**Hallucination.** Even though `cited_text` is technically a substring of the retrieved chunks, the `extracted_evidence` list is fabricated — pandas, NumPy, scikit-learn, TensorFlow, and PyTorch appear **nowhere** in the candidate's resume. The 2B model just dumped the requirement's library list back as "evidence" without checking each one. The same failure pattern was visible in the earlier cached trace from candidate `cand_49c7271f22cf`.

The 2B model also left `extracted_years=None` (the banded-ratio fallback defaulted to 0). So in this particular candidate's case, the hallucinated `skill_presence=1.0` didn't propagate to a non-zero contribution because `years_experience=0` zeroed the multiplicative chain. But that's luck, not correctness — a different candidate with explicit years text (e.g., "3 years of Python") would have let the hallucinated skill_presence=1.0 ride all the way into a permanent positive contribution.

**Critical caveat:** the existing `data/scores/composed/DataScience_ranked.json` from the old `cand_49c7271f22cf` ranking was also this 2B model's work, and its `extracted_evidence` lists show the exact same hallucination pattern. So the legacy 15-zero-evidence-REQs analysis I gave you earlier was being selectively deflated by Model A's hallucination: on some REQs the inflated skill_presence would have turned into inflated contributions had the multiplicative `code_only_part` not zeroed it.

### Backend B — OpenRouter nvidia/nemotron-3-super-120b-a12b:free (cloud, free, 48.8s)

| Sub-question | sub_score | extracted_years | extracted_evidence | cited_text verdict |
|---|---|---|---|---|
| skill_presence | **0.0** | — | `"Python mentioned in skills list: 'PHP, Python, HTML, css, Minitab, SPSS'"` | CITED_PRESENT |
| years_experience | **0.0** | **0.0** | `"No explicit mention of years of experience with pandas, NumPy, scikit-learn, TensorFlow, PyTorch."` | NO_CITE |
| project_relevance | **0.25** | — | `"Duties: 'Developed insights into the performance of Network/Studio programs and their competitors across all platforms' and 'Built and defined strategies for R&D ...'"` | CITED_PRESENT |

`normalized_score = gate*yrs*relevance` → `0 * 0 * 0.25 = 0.0`.

**No hallucination.** The 120B model correctly distinguishes "Python only" vs "the full library stack required". It says `skill_presence=0.0` with grounded `extracted_evidence` naming exactly what's there ("Python mentioned in skills list: 'PHP, Python, HTML, css, Minitab, SPSS'"), rather than dropping the requirement's library list back as fake evidence. It also honestly returns `extracted_years=0.0` rather than computing 2 years from a date range without being directed to.

This is the behavior the spec describes ("If evidence is insufficient, return 0 … do not speculate."). The model obeyed the rule.

### Backend C — opencode.ai deepseek-v4-flash-free (cloud, free, 29.7s)

| Sub-question | sub_score | extracted_years | extracted_evidence | cited_text verdict |
|---|---|---|---|---|
| skill_presence | **0.0** | — | `"Python is listed as a skill, but no data science libraries are mentioned."` | CITED_PRESENT |
| years_experience | **0.0** | **0.0** | `"No explicit mention of years of experience with Python or data science libraries."` | NO_CITE |
| project_relevance | **0.0** | — | `"No projects or experience with the specified data science libraries are mentioned."` | NO_CITE |

`normalized_score = gate*yrs*relevance` → `0 * 0 * 0 = 0.0`.

**No hallucination.** Either honest or stricter than nemotron: it returns `project_relevance=0.0` instead of `0.25`, explaining in `extracted_evidence` that no projects matching the specified data science libraries were found. Defensible — perhaps stricter than nemotron but well within the rubric's anchored float framework.

---

## 3. Side-by-side verdict table

| Backend | Hallucinated evidence? | Honest about missing skills? | Returned fake years? | Honest about missing years? | Cited text actually in chunks? |
|---|---|---|---|---|---|
| Ollama qwen2.5:3b | **YES** — listed all 6 required libraries as evidence even though only Python is present | No (claimed presence of pandas/NumPy/etc.) | No (defaulted to 0) | Yes — left `extracted_years=None` which the banded-ratio coerced to 0.0 | Yes (cited chunk IS in chunks) |
| OpenRouter nvidia/nemotron-3-super-120b:free | **NO** — grounded; named exactly what's there | Yes — explicitly noted Python alone, no full stack | No (returned `0.0` explicitly) | Yes — said "No explicit mention of years" | Yes |
| opencode.ai deepseek-v4-flash-free | **NO** — grounded; explicitly stated "Python is listed as a skill, but no data science libraries are mentioned" | Yes | No (returned `0.0` explicitly) | Yes — said "No explicit mention of years of experience" | Yes |

---

## 4. Implications

### (i) The 2B local model is unsafe for skill/experience evidence scoring
Every audit-visible red flag (fabricated evidence lists while citing chunks that don't contain them) is what the 2B model produced. This is the same model the cached trace from `cand_49c7271f22cf` was running under, and its `extracted_evidence` there showed the same hallucination pattern. The 2B model obeys the system-prompt rule "If evidence is insufficient, return 0" far less reliably than the 120B-class models on the cloud backends. **For skill/experience rubrics specifically, the 2B local model should not be trusted as the primary scorer.**

### (ii) The `target_years` leak in the prompt wasn't the hallucination driver for THIS candidate
Even though `target_years=3.0` was visible in the prompt to all three models, hallucination here is about *skill presence*, not years. Stripping `target_years` from the prompt (per your proposal) removes the LLM's incentive to rationalize its extracted number toward the recruiter's target — that's a real defensive win for years-type SQs, but it doesn't fix the skill-hallucination pattern. Different problems. Both fixes are warranted.

### (iii) The code-only multiplicative AND-gate was actually protecting against Model A hallucination
For THIS candidate, Model A's hallucinated `skill_presence=1.0` didn't propagate because `years_experience` defaulted to 0 in the multiplicative chain. But for a different candidate whose resume happens to say "5 years of Python" (which Model A would extract as 5.0), Model A would have hallucinated `skill_presence=1.0` for pandas/NumPy/Theano... AND gotten `years`=5/3=1.0, AND gotten `project_relevance=0.5` — a fully-strided `sub_score=0.5` for skill libraries that candidate never touched. The legacy code-only gate accidentally deflated that failure because its monolithic regex never matched and therefore zeroed `code_only_part`.

**This means the naive `max(code_only, rubric_llm)` I proposed is unsafe in the presence of Model A.** Taking the max would let Model A's hallucinated 1.0 win over the code-only path's correct 0. **Do not ship max() as the fix.** Your "drop the code-only path entirely" + "use a stronger LLM" framing is the correct path.

### (iv) Retrieval is healthy for REQ-001 against this candidate
3 chunks retrieved at cosine 0.4911 / 0.4406 / 0.2531. The current `theta=0.25` default admits them. So the earlier smoke-test trace showing REQ-013 with 0 retrieved chunks is a separate issue — likely theta or SubQuery phrasing.

---

## 5. Recommendations the audit supports

1. **Strip `target_years` from the rubric prompt template.** The `_banded_years_ratio` banding already runs in code at `rubric_scorer.py:519-522`. Removing the leak from the prompt is a one-line code change with no spec risk; it removes the LLM's incentive to round toward the recruiter's target.

2. **Stop running the 2B local model as the rubric scorer.** Switch the default backend to OpenRouter `nvidia/nemotron-3-super-120b-a12b:free` or opencode.ai `deepseek-v4-flash-free` (both audited here as honest). Plumb the `LLM_BACKEND` env flag through `LLMRubricCaller` so `.env` controls backend selection and operators can A/B test.

3. **Drop the code-only path for skill+experience REQs.** Route those REQs solely to the rubric LLM. Keep code-only reserved for what it was spec'd for (total experience metric, institute tier, certification tier, degree match, location match). This is a `WORKING_LOGIC.md` spec clarification + `DECISIONS.md` architectural-change log entry, not a behavior break: the spec never intended the code-only path to override the rubric LLM on judgment questions.

4. **Add a regression test** that asserts (a) `target_years` is not a substring of the built prompt, and (b) `_banded_years_ratio` is still invoked in code after the LLM's response is parsed. Locks the fix in.

5. **Do NOT ship the `max(code_only, rubric_llm)` formula change** I floated earlier. The audit shows Model A hallucinates positive scores; `max()` would encode those as permanent. The bug is "code-only path is mistakenly applied to skill/experience REQs", not "the combination formula is wrong".

6. **Future investigation** (separate task): the 2B model's failure here is bad enough that re-running the full corpus with a 12B+ model is warranted before any final rankings. The opencode-deepseek-v4-flash-free result is essentially zero for this candidate — adopting it would produce a very different ranking distribution than the old qwen hallucinated run. Worth a controlled A/B before publicly committing any "Active" config.

---

## 6. Artifacts

- `scripts/audit_llm_hallucination.py` — the runnable harness (deterministic: same candidate, same REQ, same prompt, three backends). Re-run any time.
- `scripts/_audit_results.json` — raw structured results from this run.
- `scripts/_audit_prompt.txt` — the exact prompt sent to every backend (for the record).
