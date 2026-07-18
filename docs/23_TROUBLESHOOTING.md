# Troubleshooting

## Overview

This document records debugging findings that should be reusable in future sessions.

Each entry should include problem description, symptoms, root cause, investigation process, solution, and prevention strategy.

---

## Known Issues

### Pytest cache warning on Windows

**Date:** 2026-06-19

**Problem:** Running `pytest` produced a cache warning while trying to write node IDs.

**Symptoms:**
- Tests passed.
- Pytest emitted `PytestCacheWarning` for `.pytest_cache\v\cache\nodeids`.

**Root Cause:**
- The local `.pytest_cache` path appears to have a stale file or directory conflict.

**Investigation Process:**
- Ran the full test suite after adding the production package foundation.
- Confirmed all tests passed despite the cache warning.

**Solution:**
- No code change required.
- The cache can be cleared locally if the warning becomes noisy.

**Prevention Strategy:**
- Keep `.pytest_cache/` ignored.
- Treat pytest cache artifacts as disposable local runtime state.

---

### Documentation ignored by Git

**Date:** 2026-06-19

**Problem:** The repository requires documentation to be maintained as part of implementation, but `.gitignore` contained `docs/`.

**Symptoms:**
- New required documentation files would not appear as untracked files.
- Documentation changes could be missed during commits.

**Root Cause:**
- `.gitignore` incorrectly ignored the `docs/` directory.

**Investigation Process:**
- Reviewed `AGENTS.md` documentation requirements.
- Reviewed `.gitignore`.
- Compared required docs with files present under `docs/`.

**Solution:**
- Removed `docs/` from `.gitignore`.
- Added missing required documentation files.

**Prevention Strategy:**
- Keep `docs/` tracked.
- Do not add source-of-truth documentation folders to `.gitignore`.

---

### Legacy scorer imports after Phase 4 cleanup

**Date:** 2026-06-19 (PM)

**Problem:** After retiring the legacy `keyword / semantic / hybrid` triad, any code that still imported from `src.scoring.keyword_scorer`, `src.scoring.semantic_scorer`, `src.scoring.hybrid_scorer`, `src.scoring.evidence`, or `src.scoring.evaluate` would fail with `ModuleNotFoundError`.

**Symptoms:**
- `ModuleNotFoundError: No module named 'src.scoring.keyword_scorer'` (or similar).
- `ImportError: cannot import name 'CandidateScore' from 'src.scoring.evaluate'`.

**Root Cause:**
- The legacy modules were removed as part of the Phase 4 cleanup (DEC-010). The canonical scorer is `src/scoring/graded_scorer.py`.

**Investigation Process:**
- Ran `grep_search` for `from src.scoring.(keyword|semantic|hybrid|evidence|evaluate)` across the source tree.
- Found 0 matches — all consumers had been migrated.

**Solution:**
- Replace any legacy import with the canonical scorer:
  ```python
  from src.scoring.graded_scorer import (
      evaluate_candidate, evaluate_role, render_report, load_weights,
  )
  ```
- The CLI accepts `--strategy keyword|semantic|hybrid` only as a deprecated alias that prints a `DeprecationWarning` and forwards to `graded`.

**Prevention Strategy:**
- The single canonical scorer is the only ranking signal. New code must use `graded_scorer`.
- If you need to add a new scoring strategy, extend `graded_scorer` (e.g. add a new synonym, a new section priority, or a new tier dictionary) rather than introducing a parallel scorer.

---

## Missing optional modules: src/resume_parsing/ocr.py + header_normalization.py cross-reference

**Date:** 2026-07-06 (Track 6 reconciliation)

**Problem:**
- The test ``test_parse_resume_extracts_contact_and_name`` failed in environments without PDF extraction libraries, raising ``RuntimeError: PDF extraction requires src.resume_parsing.ocr which is not installed in this environment.`` The pre-existing parser already gated the import lazily via ``try/except ImportError`` and wrote ``_HAS_OCR = False`` when missing, but the test file did not skip on the unavailable path.
- Separately, several architectural docs (`IMPLEMENTATION_ROADMAP.md`, `MODEL_REGISTRY.md`, `RELEASE_NOTES.md`, `ARCHITECTURE_CHANGELOG.md`) claimed the canonical section-header normalization logic lived in a dedicated ``src/resume_parsing/header_normalization.py`` file. No such file existed; the same logic was implemented directly inside ``src/resume_parsing/parser.py`` (``SECTION_HEADERS`` dict, ``sectionize()``, ``identify_section_heading()``).

**Symptoms:**
- The unit test suite reported ``1 failed, 441 passed`` (then ``... 447 passed`` after Track 5) for many sessions because the PDF path could not be exercised without an installed ``ocr.py``.
- The docs created a phantom module reference that misled anyone trying to navigate to ``src/resume_parsing/header_normalization.py`` for the section-classification logic.

**Root Cause:**
- The optional ``src/resume_parsing/ocr.py`` module (the PDF -> text bridge) had been removed or never written but its lazy-import branch lived on in ``parser.py``. Backends (``pdfplumber`` for the text layer, ``pypdfium2`` as a Poppler-free fallback, ``pdf2image`` + Poppler for true OCR) were present in the environment but no Python module wired them up; the parser raised a hard RuntimeError whenever a ``.pdf`` path reached ``extract_text_from_path``.
- The docs captured a future-state file layout from an earlier draft of the architecture roadmap that was never finalized. The structured-profile section-classification code was folded into ``parser.py`` but the doc references were never reconciled.

**Investigation Process:**
1. Ran the suite and the failing test was localized to a single ``parse_resume(<pdf>)`` call.
2. Read ``src/resume_parsing/parser.py:28-37, 138-150`` — confirmed the lazy-import + RuntimeError pattern.
3. Ran ``python -c "import pdfplumber; import pypdfium2; import pymupdf"`` and confirmed that ``pdfplumber`` and ``pypdfium2`` were already installed in the environment (only ``pymupdf`` / ``pdf2image`` were absent).
4. Searched the repo for files referencing ``resume_parsing.ocr`` and ``resume_parsing.header_normalization`` — found zero ``src/`` references to ``header_normalization`` (zero) and one test for ``ocr`` (already accounted for).
5. Searched the docs for the same patterns and found 17 references scattered across ``CURRENT_PROGRESS``, ``IMPLEMENTATION_ROADMAP``, ``MODEL_REGISTRY``, ``ARCHITECTURE_CHANGELOG``, ``RELEASE_NOTES``, ``DECISIONS``.

**Solution:**
- **Created ``src/resume_parsing/ocr.py``** as a real optional module. It declares ``_HAS_PDFPLUMBER``, ``_HAS_PYPDFIUM``, ``_HAS_PDF2IMAGE`` availability flags at import time. It exposes ``extract_text_hybrid(path) -> str`` which runs the strategies in order: ``pdfplumber`` (high-fidelity text layer), ``pypdfium2`` (Poppler-free fallback), ``pdf2image`` (scanned-PDF OCR — placeholder for future wiring; needs Poppler + an OCR engine). If every strategy returns empty text, the call raises an informative ``RuntimeError`` so the parser can mark the resume as unparsable rather than silently producing an empty profile.
- **Added ``pytest.mark.skipif(not _HAS_OCR, ...)`` to ``tests/unit/test_resume_parser.py``** so the test now passes when PDF libraries are installed and skips cleanly when they are not.
- **Added 7 unit tests in ``tests/unit/test_ocr.py``** covering the availability flags, the happy-path extraction on the real ``01888170110d1ccf.pdf`` (John Wood's resume), both ``RuntimeError`` paths (no backends / empty backends), and the individual private backend wrappers.
- **Reconciled the docs** to reflect that the section-header classification logic actually lives inside ``src/resume_parsing/parser.py`` (the ``SECTION_HEADERS`` dict, ``sectionize()``, and ``identify_section_heading()`` functions). The ``header_normalization.py`` file is not present and is not needed. Phantom references in the roadmap, model registry, architecture changelog, release notes are annotated with a cross-reference indicating the real location.

**Verification:**
- ``pytest tests/unit/test_ocr.py`` -> 7 passed in 0.73s.
- ``pytest tests/unit/test_resume_parser.py`` -> 1 passed in 0.57s.
- Full suite: ``448 passed in 4.04s`` (perfect green, no prior failures).

**Prevention Strategy:**
- The pattern of optional dependencies in a new module (declare ``_HAS_X = bool`` at import time, fail-open at import, fail-closed at call time) is now exemplified by ``src/resume_parsing/ocr.py``. New optional backends should follow the same pattern.
- When future-state file layouts end up folded into a different module or never realized, the docs reconciliation step belongs to the same PR (per AGENTS.md "Documentation Maintenance Rules"). The header-normalization phantom lived because a docs-only draft was never reconciled to the actual implementation.
- All new unit tests for optional-dependency code should include explicit ``skipif(not _HAS_X, ...)`` so the suite is green in both backends-present and backends-absent environments.

---

## All candidates scored 100.00 under `--no-llm` smoke tests

**Date:** 2026-07-07 (Track 7 / DEC-031 bug)

**Problem:**
- Running ``python scripts/score_batch_composed.py --role DataScience --no-llm`` produced ``mean=100.00`` and ``top-1=100.00`` for every role. The per-REQ JSON showed``code_only_part=1.00``, ``rubric_llm_part=1.00``, ``sub_score=1.00`` for every REQ on every candidate, with ``rubric_sq_scores={}`` and ``code_only_sq_scores={}`` (both empty).

**Symptoms:**
- ``data/scores/composed/<role>_ranked.json`` reported identical perfect totals for every candidate regardless of profile content.
- ``n_zero_evidence_reqs`` was 0 (no flags written), even though the rubric path was supposed to zero-out under ``--no-llm``.
- The ComposedREQResult ``code_only_sq_scores`` and ``rubric_sq_scores`` were empty dicts, indicating the per-SQ loop never ran.

**Root Cause:**
- The composed scorer's contract for the ``role_subqueries`` parameter said "Pre-loaded SubQuery data for the candidate's role" — i.e. the SINGLE-role dict (``{requirements: [...], role_name: ...}``) produced by ``get_all_role_subqueries().get(role)``.
- The CLI ``scripts/score_batch_composed.py`` pre-loads ``role_subqueries = get_all_role_subqueries()`` (line 401) and passes the WHOLE 8-role dict (``{BusinessAnalyst: {...}, DataScience: {...}, ...}``) directly to ``evaluate_candidate_composed`` (line 227).
- Inside ``evaluate_candidate_composed`` (line 1051), the code did ``subquery_reqs = role_subqueries.get("requirements", [])``. Since the 8-role dict had no top-level ``requirements`` key, this returned ``[]``. ``sq_by_id`` was thus empty, so for every REQ ``sq_data = sq_by_id.get(req_id)`` returned ``None``, and ``sub_queries = sq_data.get("sub_queries", []) if sq_data else []`` returned ``[]``.
- With no sub_queries, both the binary/years loop and the rubric loop were skipped, leaving both parts at the dataclass default of ``1.0`` (multiplicative identity). ``sub_score = 1.0 × 1.0 = 1.0`` for every REQ, and ``total = Σ weight × 1.0 = 100.0``.

**Investigation Process:**
1. Ran ``python scripts/score_batch_composed.py --role DataScience --no-llm --limit 2`` and confirmed ``mean=100.00``.
2. Loaded ``data/scores/composed/DataScience_ranked.json`` and observed ``code_only_sq_scores={}`` and ``rubric_sq_scores={}`` on every REQ — the smoking gun that no SQs were being scored.
3. Verified ``src/services/subquery_parser.py::get_role_subquery("DataScience")`` returned 20 REQs each with populated ``sub_queries`` (e.g. REQ-001 had 4 SQs).
4. Verified ``get_all_role_subqueries()`` returned the same shape, keyed by role name, with each role's dict containing a ``requirements`` list.
5. Wrote a debug script that monkey-patched ``evaluate_candidate_composed`` and printed ``sq_by_id`` keys before invoking the real function — saw ``sq_by_id keys: []`` and ``subquery_reqs = role_subqueries.get("requirements", []) = []``. This proved that the ``role_subqueries`` ARGUMENT received by the function did NOT have a ``requirements`` key, i.e. it was the 8-role dict, not a single-role dict.
6. Read ``scripts/score_batch_composed.py:401, 227`` and confirmed the CLI passes the all-roles dict directly, contradicting the function's documented contract.

**Solution:**
- Made ``evaluate_candidate_composed`` (``src/scoring/unified_scorer.py:1039``) robust to BOTH input shapes. After resolving ``role_subqueries`` (either lazy-loaded from ``role_name`` or supplied by the caller), it now checks for the all-roles shape by the absence of a ``requirements`` key, then slices out the single-role dict via ``role_subqueries.get(role)``. The function then uniformly sees the single-role shape (a) regardless of how the caller invoked it.
- Added a new ``rubric_skipped`` boolean field to ``ComposedREQResult`` so the ``--no-llm`` rubric-bypass branch can be distinguished from a "zero-evidence" branch. The ``zero_evidence_reqs`` property was updated to exclude ``rubric_skipped=True`` REQs, so ``n_zero_evidence_reqs`` is now correctly 0 under ``--no-llm`` (was previously miscounted as 19 per candidate — every rubric REQ was incorrectly flagged).
- Updated the ``ComposedREQResult.to_dict()`` to serialize ``rubric_skipped`` so the audit JSON exposes the distinction.

**Verification:**
- All new unit tests for optional-dependency code should include explicit ``skipif(not _HAS_X, ...)`` so the suite is green in both backends-present and backends-absent environments.

---

## All candidates scored 100.00 under `--no-llm` smoke tests

**Date:** 2026-07-07 (Track 7 / DEC-031 bug)

**Problem:**
- Running ``python scripts/score_batch_composed.py --role DataScience --no-llm`` produced ``mean=100.00`` and ``top-1=100.00`` for every role. The per-REQ JSON showed``code_only_part=1.00``, ``rubric_llm_part=1.00``, ``sub_score=1.00`` for every REQ on every candidate, with ``rubric_sq_scores={}`` and ``code_only_sq_scores={}`` (both empty).

**Symptoms:**
- ``data/scores/composed/<role>_ranked.json`` reported identical perfect totals for every candidate regardless of profile content.
- ``n_zero_evidence_reqs`` was 0 (no flags written), even though the rubric path was supposed to zero-out under ``--no-llm``.
- The ComposedREQResult ``code_only_sq_scores`` and ``rubric_sq_scores`` were empty dicts, indicating the per-SQ loop never ran.

**Root Cause:**
- The composed scorer's contract for the ``role_subqueries`` parameter said "Pre-loaded SubQuery data for the candidate's role" — i.e. the SINGLE-role dict (``{requirements: [...], role_name: ...}``) produced by ``get_all_role_subqueries().get(role)``.
- The CLI ``scripts/score_batch_composed.py`` pre-loads ``role_subqueries = get_all_role_subqueries()`` (line 401) and passes the WHOLE 8-role dict (``{BusinessAnalyst: {...}, DataScience: {...}, ...}``) directly to ``evaluate_candidate_composed`` (line 227).
- Inside ``evaluate_candidate_composed`` (line 1051), the code did ``subquery_reqs = role_subqueries.get("requirements", [])``. Since the 8-role dict had no top-level ``requirements`` key, this returned ``[]``. ``sq_by_id`` was thus empty, so for every REQ ``sq_data = sq_by_id.get(req_id)`` returned ``None``, and ``sub_queries = sq_data.get("sub_queries", []) if sq_data else []`` returned ``[]``.
- With no sub_queries, both the binary/years loop and the rubric loop were skipped, leaving both parts at the dataclass default of ``1.0`` (multiplicative identity). ``sub_score = 1.0 × 1.0 = 1.0`` for every REQ, and ``total = Σ weight × 1.0 = 100.0``.

**Investigation Process:**
1. Ran ``python scripts/score_batch_composed.py --role DataScience --no-llm --limit 2`` and confirmed ``mean=100.00``.
2. Loaded ``data/scores/composed/DataScience_ranked.json`` and observed ``code_only_sq_scores={}`` and ``rubric_sq_scores={}`` on every REQ — the smoking gun that no SQs were being scored.
3. Verified ``src/services/subquery_parser.py::get_role_subquery("DataScience")`` returned 20 REQs each with populated ``sub_queries`` (e.g. REQ-001 had 4 SQs).
4. Verified ``get_all_role_subqueries()`` returned the same shape, keyed by role name, with each role's dict containing a ``requirements`` list.
5. Wrote a debug script that monkey-patched ``evaluate_candidate_composed`` and printed ``sq_by_id`` keys before invoking the real function — saw ``sq_by_id keys: []`` and ``subquery_reqs = role_subqueries.get("requirements", []) = []``. This proved that the ``role_subqueries`` ARGUMENT received by the function did NOT have a ``requirements`` key, i.e. it was the 8-role dict, not a single-role dict.
6. Read ``scripts/score_batch_composed.py:401, 227`` and confirmed the CLI passes the all-roles dict directly, contradicting the function's documented contract.

**Solution:**
- Made ``evaluate_candidate_composed`` (``src/scoring/unified_scorer.py:1039``) robust to BOTH input shapes. After resolving ``role_subqueries`` (either lazy-loaded from ``role_name`` or supplied by the caller), it now checks for the all-roles shape by the absence of a ``requirements`` key, then slices out the single-role dict via ``role_subqueries.get(role)``. The function then uniformly sees the single-role shape (a) regardless of how the caller invoked it.
- Added a new ``rubric_skipped`` boolean field to ``ComposedREQResult`` so the ``--no-llm`` rubric-bypass branch can be distinguished from a "zero-evidence" branch. The ``zero_evidence_reqs`` property was updated to exclude ``rubric_skipped=True`` REQs, so ``n_zero_evidence_reqs`` is now correctly 0 under ``--no-llm`` (was previously miscounted as 19 per candidate — every rubric REQ was incorrectly flagged).
- Updated the ``ComposedREQResult.to_dict()`` to serialize ``rubric_skipped`` so the audit JSON exposes the distinction.

**Verification:**
- ``pytest tests/unit/test_composed_scorer.py tests/unit/test_unified_scorer.py`` -> 58 passed in 0.86s.
- ``python scripts/score_batch_composed.py --role DataScience --no-llm --limit 2`` -> ``mean=0.00, top-1=0.00, 0-Evid=0`` (was ``mean=100.00, top-1=100.00, 0-Evid=38``).
- Per-REQ JSON now shows populated ``code_only_sq_scores`` (binary + years SQs) and ``rubric_sq_scores`` (rubric SQs zero'd under ``--no-llm`` with ``rubric_skipped=True``).

**Prevention Strategy:**
- API contracts that accept a "data for one role" vs "data for all roles" should be validated at function entry — the run-time shape check (``"requirements" not in role_subqueries``) is now a lasting guard, not just a one-time fix.
- The CLI's pre-load + pass-through pattern (load once in ``main``, pass to per-role helpers, pass to per-candidate function) is fine — but the helper boundaries need explicit shape normalization. The fix moves that normalization into the canonical entry point (``evaluate_candidate_composed``) so future callers cannot reintroduce the bug.
- Smoke-test golden values must be sanity-checked against the scoring semantics: a "all-zero under --no-llm" result is correct per the documented contract (rubric-bypass zeros the rubric part for any REQ with rubric SQs; nearly every REQ has at least one rubric SQ, so nearly every contribution is 0).

---

### Rubric scorer returns 0.0 for all skill/experience REQs with qwen2.5:3b

**Date:** 2026-07-08

**Problem:** The batch scorer (`score_batch_composed.py`) returns `0.0` contribution for every skill and experience requirement even when the candidate clearly has the skill (e.g. Python is listed in skills and experience).

**Symptoms:**
- `skill_presence` sub-score correctly set to `1.0` (LLM says "yes, knows Python").
- `years_experience` sub-score is `0.0` with `extracted_years = None`.
- Final `normalized_score = gate * years_ratio = 1.0 * 0.0 = 0.0`.

**Root Cause — Three compounding bugs:**

1. **qwen2.5:3b only generates one JSON array item** when the old prompt template showed a generic `{ "key": "<placeholder>" }` example. The model filled in the first slot and stopped, leaving `years_experience` missing from the response (which then defaults to 0).

2. **qwen2.5:3b returns `extracted_years = null`** when dates appear in text format (`"2016 - Ongoing"`) because the 3B model cannot compute `2026 - 2016 = 10 years` on its own. The old code did a bare `float()` call which would also crash on string values like `"3 years"`.

3. **No partial credit path**: when `extracted_years = null` and `sub_score = 0`, the formula `gate * years_ratio` returns `0` even when `gate = 1`. A candidate with confirmed skill presence received zero contribution — identical to a candidate who doesn't have the skill at all.

**Investigation Process:**
- Added `python scripts/debug_llm_response.py` to fire one live rubric scoring call and print the raw LLM response.
- Confirmed the raw JSON only contained one sub-score entry (not two).
- Confirmed `extracted_years` was always `null` even when date ranges were visible in the evidence.
- Traced through `_parse_llm_response` and `_evaluate_formula` to confirm the formula evaluated correctly but was fed `0.0` for `years_ratio`.

**Solution — Four changes to `src/scoring/rubric_scorer.py`:**

1. **Pre-populated JSON skeleton prompt** (`_build_rubric_prompt`): The JSON template now contains one pre-keyed entry per sub-question with `FILL_...` placeholders. The model only needs to fill values, not decide how many items to produce. This fixes the "model stops after first item" failure.

2. **Robust `_coerce_years()` helper**: Added a dedicated function that handles `"3 years"`, `"~4"`, `"approximately 3"`, `"3+"` etc. by stripping noise and extracting the numeric digit. Replaces the bare `float()` call that silently produced `None`.

3. **Partial-credit rescue `_apply_partial_credit_for_unknown_years()`**: After LLM response parsing, if the binary gate sub-question passed (`skill_presence = 1`) but the linear sub-question returned `extracted_years = None`, the linear sub-score is set to `0.25` (minimum banded credit). This prevents the misleading "skill confirmed but score = 0" outcome.

4. **Full DEBUG logging** of raw LLM response at every step so future failures are immediately diagnosable.

**Prevention Strategy:**
- When integrating a new small LLM (≤7B params), always run `scripts/debug_llm_response.py` first to verify JSON output quality before running the full batch.
- Use pre-keyed JSON skeletons (not generic placeholders) in prompts for all multi-item rubric responses.
- Never let a confirmed binary-gate=1 result in zero final score — the partial-credit rescue is a safety net.
- For accurate years, the `employment_history` block (pre-computed role durations in months) should always be passed to `score_requirement_with_rubric`; `unified_scorer.py` already does this. Verify it is wired correctly when adding new scoring paths.

---

### Low/Near-Zero Candidate Scores (Top Score 40.73/100) Due to Nested Data & Match Failures

**Date:** 2026-07-13

**Problem:** 
Scored resumes returned artificially low scores (e.g., top candidate scoring only `40.73/100`), with factual checks like degrees, certifications, CGPA, and institution tiers scoring near-zero floors (`0.0`, `0.01`, or `0.02`) even when candidates had high qualifications (e.g., PhD in Data Science from IIT).

**Symptoms:**
- `SQ045` (qualifying bachelor's degree check) and `SQ048` (MS/PhD check) returned `0.0` despite candidates holding relevant degrees.
- `SQ046` (CGPA check) returned `0.01` floor score for all candidates.
- `SQ047` and `SQ049` (institution rank check) returned `0.01` floor score for all candidates.
- Cloud platforms check (`REQ-008`) and locations returned `0.0` or `0.01` because they rely on structured profile certifications/raw_text.

**Root Causes:**

1. **JSON Nesting Mismatch (BUG-1 & BUG-2):**
   `extract_structured_profile` was trying to read `"education"`, `"certifications"`, and `"experience"` directly from the root of the candidate's JSON profile (`profile.get("education")`). However, in production, these fields are nested inside `profile["candidate_profile"]`. Also, normalized education entries were flat lists rather than dictionaries wrapping entries under `education["entries"]`, and keys like `"degree"` and `"institution_normalized"` were used rather than `"description"`.
   
2. **Missing Degree Abbreviations and Synonym Mapping (BUG-3):**
   The token matcher used raw JD strings like `"Bachelor's Degree in CS..."` and checked if those exact tokens (like `"bachelor"`) appeared in the resume's degree abbreviation (like `"BTech"`, `"B.E."`, `"BS"`). Since they didn't overlap, matching failed.

3. **CGPA Missing Data Nesting (BUG-4 & BUG-5):**
   `extract_cgpa_from_profile` was reading education from the wrong root level. Consequently, CGPA was always extracted as `None`. The rubric scoring engine then penalized `None` to `0.01` (treating missing data as a red flag/failure instead of neutral).

4. **Unlisted Institution / Cert Rank Penalties (BUG-6):**
   When institutions or certification providers were not matched or unlisted, the scoring system returned `0.01` as a default. This heavily penalized candidates for unknown/smaller universities or missing entries.

5. **Inefficient `top_k` Retrieval configuration:**
   The hard retrieval cap `top_k` was set to `20`. But a typical resume only contains 3–8 chunks total, making `20` meaningless and wasting retrieval resources.

**Investigation Process:**
- Created a diagnosis script (`deep_sq_audit.py`) to extract requirement-level and sub-query-level score breakdowns.
- Identified that the entire `structured_profile.degrees` list was empty (`[]`) for candidates, revealing the parsing level bug.
- Logged the input parameter layouts to `extract_structured_profile` to locate the correct production dictionary paths.
- Wrote a verification suite to test edge cases for degree canonicalization, scale normalization, and neutral penalties.

**Solution:**

1. **Unpacked candidate_profile:** Modified `extract_structured_profile` in `src/resume_parsing/structured_profile.py` to read nested variables under `profile["candidate_profile"]` and fallback to root for backward compatibility with unit tests.
2. **Added flat list parsing:** Handled flat list formatting for education/certifications/experience, mapping direct keys like `"degree"`, `"specialization"`, and `"institution_normalized"`.
3. **Degree Alias Mapping:** Added a `DEGREE_ALIASES` map and `degree_canonical_tier` classification helper to canonicalize degree titles (e.g. `BTech`, `B.E.`, `BS` to `bachelor`; `PhD` to `phd`). Integrated this check into `_token_boundary_match` in `src/scoring/unified_scorer.py`.
4. **Fixed CGPA Extraction & Penalty:** Read education list and raw text from the correct nesting level. Changed `score_cgpa(None)` in `src/scoring/rubrics.py` to return `0.50` (neutral, no penalty) instead of `0.01`.
5. **Fixed Institution/Cert Rank Default:** Changed default values for empty/unlisted universities and providers to `0.50` in `src/scoring/rubrics.py`, preserving `0.01` only for explicitly blacklisted institutions.
6. **Optimized `top_k` cap:** Lowered `DEFAULT_MAX_CHUNKS_PER_QUERY` from `20` to `8` in `src/rag/retriever.py` to match the 95th-percentile chunk count.

**Prevention Strategy:**
- Use `scripts/scorer_variance_evaluator.py` on initial batches to check count, min, max, mean, standard deviation, and Sub-Score Floor Rate (SFR).
- If SFR < 0.25 exceeds 30%, inspect the suspect requirement list to trace parsing failures or retrieval mismatches.
- Ensure all factual lookup code functions support both normalized production and raw legacy formats using dictionary checks.

---

### BUG-RC-001: RecursiveChunker Causes High Binary Sub-Query Zero Rates (Retrieval Failure)

**Date:** 2026-07-13

**Severity:** High — caused 50-90% floor rates on core REQs (Agile, Documentation, Cross-Functional, SQL)

**Problem:**
The active chunker (`RecursiveChunker`, DEC-019) produces chunks with 50% text overlap by splitting the resume as flat text every 1000 chars. With typical resume sizes of 3,000–8,000 chars, this generates 5–15 heavily overlapping chunks with no section structure. Binary sub-queries (e.g. "Has the candidate used Agile/Scrum?") returned 0 for the majority of candidates despite the evidence being present in the resume text.

**Symptoms:**
- `SQ027` (Agile binary): 78% zero rate across BA candidates
- `SQ015` (Documentation float): 78% returning 0.0 (not even 0.01 floor)
- `SQ036` (Cross-functional binary): 56% zero rate
- `SQ044` (UAT binary): 89% zero rate
- `REQ-008` (Agile): 68.7% SFR — unacceptably high for a universal BA skill
- `REQ-005` (Documentation): 61.6% SFR — a core BA deliverable
- `REQ-012` (Cross-functional): 54.5% SFR

**Root Cause:**
Recursive chunking disperses resume content uniformly across all chunks because of 50% overlap. When the embedding model (`all-MiniLM-L6-v2`, 384-dim, trained on general sentence similarity) computes cosine similarity between a formal sub-query ("Has the candidate worked in an Agile or Scrum environment?") and these overlapping blobs of mixed resume text, the scores are uniformly low (~0.2–0.28) for all chunks. At θ=0.25 threshold, many queries fall right at the boundary. The BUG-9 fallback (θ−0.05) partially mitigated block rates but did not fix binary SQ zero rates because the LLM was receiving chunks that did not contain clear, focused evidence for the question — the relevant sentence was spread thinly across all overlapping chunks rather than concentrated in one targeted chunk.

The secondary cause is the embedding model mismatch: `all-MiniLM-L6-v2` is trained on general semantic textual similarity (STS tasks), not question-to-passage retrieval (BEIR/MS-MARCO). Sub-queries are structured questions; resume chunks are informal narrative text. This domain mismatch reduces retrieval precision further.

**Investigation Process:**
1. Ran `scorer_variance_evaluator.py` → identified SFR >50% on REQ-005, REQ-008, REQ-012.
2. Wrote `diagnose_sfr.py` → per-SQ zero rates revealed binary SQs at 56–89% zero across all REQs.
3. Confirmed REQ was not blocked (BUG-9 fallback working) but binary SQs still returning 0.
4. Inspected `recursive_chunker.py` → confirmed chunk_size=1000, overlap=500, no section tags.
5. Compared DocumentAware chunker design → found it reads structured JSON fields directly (not raw text), creates one chunk per job entry with section_type tag.
6. Confirmed that section header normalization ("Work History" → "experience") is already done at parse time by `parser.py` — DocumentAware chunker reads the structured profile, not raw resume text, so header variation is irrelevant.

**Solution (DEC-035):**
1. **Revert active chunker** from `RecursiveChunker` to `DocumentAwareChunker`. The DocumentAware chunker reads the structured profile JSON (which has already normalized headers) and creates one chunk per experience entry, one for skills, one for education, one for certifications. Each chunk carries `section_type` metadata.
2. **Switch embedding model** from `all-MiniLM-L6-v2` (384-dim, STS-trained) to `BAAI/bge-base-en-v1.5` (768-dim, MS-MARCO/BEIR retrieval-trained). This dramatically improves sub-query → resume-chunk cosine alignment.
3. **Remove cosine threshold** — switch from threshold-based retrieval to top-K retrieval (top-K per section). Since DocumentAware chunks are pre-filtered by section type, every sub-query retrieves the most relevant section chunks, not an arbitrary threshold cutoff.
4. **Delete all stale data**: old embeddings index (MiniLM 384-dim incompatible with BGE 768-dim), old score outputs (from wrong chunker), optuna studies (threshold-tuned, now invalid), mlflow artifacts, hireintel.db.
5. **Rebuild index** with DocumentAware chunker + BGE model.

**Files Changed:**
- `src/rag/build_index.py` — embedding model, active chunker class
- `src/rag/retriever.py` — model name, remove DEFAULT_THRESHOLD, add DEFAULT_TOP_K
- `src/rag/per_req_retrieval.py` — model name, remove fallback retry, top-K retrieval
- `src/rag/subquery_cache.py` — model name
- `src/scoring/unified_scorer.py` — retrieval call updates
- `scripts/score_batch_composed.py` — chunker switch

**Scripts Deleted (obsolete with threshold removal):**
- `scripts/run_hpo_sweep.py`, `run_all_roles_hpo.py`, `run_grid_sweep.py`
- `scripts/plot_parameter_sensitivity.py`, `generate_grid_stability_report.py`
- `scripts/run_determinism_check.py`, `run_judge_eval.py`, `generate_judge_eval_report.py`
- `src/evaluation/judge_prompt_builder.py`, `src/evaluation/score_comparator.py`
- `src/eval/ranking_diff.py`

**Data Deleted:**
- `data/embeddings/` (entire dir — MiniLM 384-dim index incompatible with BGE 768-dim)
- `data/scores/composed/` (produced by wrong chunker/model)
- `data/optuna/` (threshold-tuned, invalid post-removal)
- `data/mlflow/` (old run artifacts)
- `data/eval/`, `data/audit/`, `run_reports/`
- `data/hireintel.db` (will be recreated by `scripts/init_database.py`)

**Prevention Strategy:**
- When switching chunking strategy, always verify that section_type metadata is preserved in chunks — without it, section-aware retrieval cannot function.
- Run `diagnose_sfr.py` (per-SQ zero-rate diagnostic) after any chunker or embedding model change to catch retrieval failures before a full batch run.
- Always match embedding model training objective to retrieval task: use retrieval-trained models (BGE, E5, Nomic-embed) for Q→passage tasks, not STS-trained models (MiniLM, MPNet).

---

### Project Adapter TypeErrors, Education False Positives, and retriever.py top-K / VectorIndex Integration Errors

**Date:** 2026-07-13

**Problem:**
- Rebuilding the RAG index with the BGE-768 model failed with a list description TypeError when processing certain candidate profiles.
- Code-only degree checks suffered from false positive matches (e.g. `BA` matched `MBA`, `BS` matched `BSE`).
- Deprecating `ThresholdRetriever` in favor of direct `VectorIndex` top-K retrieval (DEC-035) broke `score_batch_composed.py`, `unified_scorer.py`, and the unit test suite due to invalid retriever interfaces and arguments.
- The unit test suite failed in environments without `mlflow` installed.

**Symptoms:**
- `TypeError: sequence item 1: expected str instance, list found` in `build_index.py`.
- `AssertionError: assert True is False` in `test_education_no_ba_in_mba_false_positive` and `test_education_no_bs_in_bse_false_positive`.
- `AttributeError: 'ThresholdRetriever' object has no attribute 'retrieve_top_k'` or `got an unexpected keyword argument 'threshold'` errors during batch scoring and composed scorer testing.
- `ModuleNotFoundError: No module named 'mlflow'` failing 7 unit tests in `test_mlflow_wiring.py`.

**Root Cause:**
- `_adapt_profile_for_chunker` in `build_index.py` expected the candidate's `projects` description field to always be a string, but some profiles parsed description as a list of strings.
- Rule 3 (alias-tier matching) in `_token_boundary_match` (defined in `unified_scorer.py`) matched "BA" to "MBA" because both mapped to the `"bachelor"` tier, bypassing exact token word boundary boundaries.
- Callers and tests passed `ThresholdRetriever` instead of `VectorIndex`, and supplied `threshold` argument parameters where `retrieve_evidence_for_req` now expects `top_k`/`max_chunks_per_req`.
- The years-blocking unit test SQ text `"How many years of Python does the candidate have?"` did not contain expected keywords like `"relative to expected"`, failing to register as years-proportional.
- `test_mlflow_wiring.py` did not skip when mlflow was missing in the environment.

**Solution:**
1. **List adapter**: Modified `_adapt_profile_for_chunker` in `build_index.py` to check for and join list-based descriptions.
2. **Short abbreviation guard**: Added a guard in `_token_boundary_match` restricting Rule 3 alias-tier matching to strings/phrases longer than 5 characters (so BA, BS, BE are evaluated strictly on exact token word boundaries).
3. **API update**: Cleaned up the composed scoring logic and batch script (`score_batch_composed.py`) to pass the bare `VectorIndex` retriever, added a `--top-k` CLI argument, and replaced threshold parameters with top-K equivalents.
4. **Test rewrites**: Rewrote `test_per_req_retrieval.py` and `test_composed_scorer.py` to use `VectorIndex` and test top-K retrieval behaviors (dedup, union cap, empty index).
5. **SQ keyword fix**: Adjusted the test subquery string in `test_composed_scorer.py` to `"How many years of Python relative to expected minimum?"` so the years-proportional classifier triggers correctly.
6. **MLflow skip guard**: Added `pytest.importorskip("mlflow")` to the header of `test_mlflow_wiring.py`.

**Verification:**
- Full unit test suite passes cleanly: `441 passed, 1 skipped` (mlflow test module skipped cleanly).
- Batch scoring runs to completion via `python scripts/score_batch_composed.py --workers 10 --flush-cache`.

**Prevention Strategy:**
- Ensure data adapters check variable types (`isinstance(..., list)`) before string functions.
- Short degree or certification abbreviations must match exactly; alias-tier matching should be gated by name length.
- Standardize all RAG pipelines on `VectorIndex` directly; wrap retrieval modifications at the class layer.

---

### Onboarding Wizard: FileNotFoundError for SubQuery.md during scoring retry

**Date:** 2026-07-14

**Problem:**
- When retrying or initiating a background scoring run via the interactive recruiter onboarding wizard, the script failed with a `FileNotFoundError` because the `React_Developer_20260714_SubQuery.md` file was missing from `recruiter/data/job_descriptions/{slug}/`.

**Symptoms:**
- The background thread logs output `FileNotFoundError: SubQuery file not found: recruiter/data/job_descriptions/..._SubQuery.md`.
- Background execution exits immediately with code 1, and no candidate scores are calculated.

**Root Cause:**
- The wizard only saved files to `recruiter/data/jobs/{slug}/` during the save configuration step. The scoring scripts, however, were hardcoded to look for the SubQuery markdown document inside `recruiter/data/job_descriptions/{slug}/`.

**Solution:**
- Added a self-healing SubQuery document compiler block at the start of `_run_pipeline_bg` in [src/api/recruiter.py](file:///c:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/src/api/recruiter.py). If the `requirements.json` and `subqueries.json` configurations are found in the job folder, the script automatically parses them and compiles the corresponding `_SubQuery.md` file dynamically under both folders before scoring begins.

**Prevention Strategy:**
- Background tasks executing separate CLI scripts must self-heal their own file dependencies where possible rather than assuming they were pre-created by earlier manual steps.

---

### Onboarding Wizard: JSON Extraction Fails with empty results on Reasoning Models (MiniMax/DeepSeek)

**Date:** 2026-07-14

**Problem:**
- Scored candidates returned empty responses and the console logged warnings: `No JSON found in LLM response. Raw response (first 400 chars): (empty)`.

**Symptoms:**
- Candidate scores were completely flat (all defaulting to `0.01` floor value) and candidates were marked as `Blocked`.
- No LLM responses were parsed.

**Root Cause:**
- Reasoning models (such as `minimax-m3` on OpenCode) enclose their thinking process within `<think>\n...\n</think>` (or `<thought>...</thought>`) tags. Because the first `{` character of the JSON string structure often lands inside this `<think>` block, naive parser functions matching the first `{` extracted the thoughts instead of the real JSON, failing to parse and returning empty values.

**Solution:**
- Added a robust thought-stripping regular expression `re.sub(r"<(think|thought)>.*?</(think|thought)>", "", text, flags=re.DOTALL)` to both `_extract_json_lenient` in `rubric_scorer.py` and `llm_normalizer` in `llm_normalizer.py` to cleanly strip thought blocks before searching for the first `{`.

**Prevention Strategy:**
- Standardize all structured JSON extraction utilities on a central parser that handles reasoning thought-blocks natively, as reasoning LLMs are increasingly common.

---

### Onboarding Wizard: Stale rankings and cached dashboard files persist on new sessions

**Date:** 2026-07-14

**Problem:**
- When initiating a new onboarding wizard session or going to Step 6, the rankings table displayed ranked candidates from the *previous* session.

**Symptoms:**
- The "Refresh Rankings" button did not fetch the new results.
- Stale candidates with old scores were visible.

**Root Cause:**
- Two caching vectors existed:
  1. The browser cached GET `/api/v1/rankings/...` responses.
  2. The server-side scoring script output files (`_ranked.json`) were never cleaned on new run starts. If a new run was in progress or failed, the server kept serving the old file.

**Solution:**
- **Client-Side:** Added a cache-busting timestamp `?t=${Date.now()}` query parameter to the rankings fetch in the HTML template.
- **Server-Side:** Added an immediate deletion block inside the `save_role` endpoint and `_run_pipeline_bg` starting thread. Old rankings, scores folders, and embeddings files are immediately unlinked from disk when the wizard configuration is saved or scoring is triggered.

**Prevention Strategy:**
- Clear local outputs and use cache-busting tokens for any dynamic dashboard tables displaying background task results.

---

### Onboarding Wizard: JavaScript ReferenceError "getByokKey is not defined" on Start Scoring click

**Date:** 2026-07-14

**Problem:**
- Clicking the "Start Scoring" button in Step 6 did absolutely nothing.

**Symptoms:**
- The button text stayed as "► Start Scoring" and no network requests were sent.

**Root Cause:**
- The click handler called undefined getter functions (`getByokKey()`, `getByokModel()`, `getByokBaseUrl()`). The actual helper defined in the script was `getByok()` returning a settings object.

**Solution:**
- Corrected the references inside `startScoring()` to invoke `getByok()` and extract keys.
- Added a global `window.onerror` handler to alert any client-side exceptions directly as popup alerts so caching or runtime bugs do not fail silently.

**Prevention Strategy:**
- Always execute client-side scripts under a global error boundary during testing.

---

### Onboarding Wizard: StartScoringRequest payload omits BYOK settings

**Date:** 2026-07-14

**Problem:**
- Candidates scored 0.01 floor values and were flagged as Blocked even when API calls were succeeding.

**Symptoms:**
- Scorer logs showed `SKIP: caller not available or api_key missing`.

**Root Cause:**
- The frontend fetch to `/api/recruiter/start-scoring` failed to pass the sidebar input fields (`api_key`, `model`, `base_url`), resulting in the background thread running with `None` values and skipping API calls.

**Solution:**
- Updated the fetch body stringifier to read and include `api_key`, `model`, and `base_url` in the `/start-scoring` POST request.

---

### Onboarding Wizard: False-positive Blocked Candidate Statuses due to hyphenated sub-query key regex mismatch

**Date:** 2026-07-14

**Problem:**
- All scored candidates were marked as "Blocked" under the Status column on Step 6.

**Symptoms:**
- The logs reported: `No sub-queries found/parsed for REQ-XXX`.
- Scored JSON files reported `blocked: true` for the final 5 requirements.

**Root Cause:**
- The sub-query parser strictly matched keys with format `SQ\d+` (e.g. `SQ001`). The wizard generator generated sub-query keys with hyphens (e.g. `SQ013-5`, `SQ014-1`). Because of this, the parser matched `[]` sub-queries, blocking the evaluations.

**Solution:**
- Modified `_SQ_ROW_RE` in `subquery_parser.py` to match `SQ[a-zA-Z0-9_\-]+` to support hyphenated keys.

**Prevention Strategy:**
- Ensure regex patterns matching ID fields support common separator formats (hyphens, underscores) to prevent parser failures.

---

### Onboarding Wizard: Uvicorn Auto-Reload Interrupting Scoring Jobs

**Date:** 2026-07-14

**Problem:**
- Running a scoring run for a large list of candidates would complete with many candidates missing (e.g. only 2 out of 10 ranked).

**Symptoms:**
- The uvicorn reload process logged `WARNING: WatchFiles detected changes... Reloading...` mid-run.
- The background thread terminated abruptly, leaving candidate score outputs incomplete.

**Root Cause:**
- Uvicorn was started with `--reload`, which recursively watches the entire project workspace. When the background scoring script wrote processed JSON results to `recruiter/data/processed/` or logged requests to `recruiter/logs/llm_calls.log`, Uvicorn detected the file modifications and triggered a full server reload, killing all active background threads.

**Solution:**
- Documented that the server should be run with `--reload-dir recruiter/src` to restrict watching to source code files only:
  ```powershell
  .venv\Scripts\python -m uvicorn recruiter.src.api.app:app --host 0.0.0.0 --port 8000 --reload --reload-dir recruiter/src
  ```
- Alternatively, run without the `--reload` flag during production/bulk runs.

---

### Onboarding Wizard: Cleanup Timer Collisions and Missing Files

**Date:** 2026-07-14

**Problem:**
- Doing multiple scoring runs in quick succession or opening candidate details/chat tabs resulted in missing files or empty dashboards.

**Symptoms:**
- Processed JSON files and indexes disappeared from directories.
- Recruiter weights config JSON was lost, causing `FileNotFoundError`.

**Root Cause:**
- A `threading.Timer` was scheduled at start-scoring to delete the candidate directory after 10 minutes. However:
  1. Starting a new scoring run did not cancel the previous run's cleanup timer, causing the first timer to fire and delete the new run's files.
  2. The timer deleted the job description weight config folder (`recruiter/data/job_descriptions/{slug}`), which ruined saved weights.

**Solution:**
- Maintained a global `_CLEANUP_TIMERS` registry to track active timers.
- Modified `/start-scoring` and background worker `finally` block to cancel any active timer for the slug before scheduling a new one.
- Changed cleanup timing to trigger exactly 30 seconds after the background scoring job finishes (succeeds or fails), rather than starting at kickoff.
- Stopped deleting the job description weights configuration directory.

---

### Onboarding Wizard: Scoring Nondeterminism on JSON Parsing Failures

**Date:** 2026-07-14

**Problem:**
- A candidate's total score fluctuated wildly across runs (e.g. 60+ vs 49 vs 7) for identical inputs.

**Symptoms:**
- Logs showed `No JSON found in LLM response` warnings.
- Sub-scores defaulted to 0.01 (essentially 0), dropping total scores.

**Root Cause:**
- Smaller/reasoning models (like `minimax-m3` or `qwen2.5:3b`) occasionally output free-form text or non-JSON formats when they find no matching evidence. Additionally, the skeleton prompt template had unquoted text placeholders (like `FILL_yes_OR_no`), causing the model to produce invalid JSON syntax.

**Solution:**
- Corrected the prompt skeleton template to use valid JSON-compliant default values (e.g. `"no"`, `null`, `0`) so the template itself is valid JSON.
- Implemented a robust `_parse_fallback_regex` parser in `rubric_scorer.py` that extracts scores, evidence status, and levels using regular expressions when standard JSON parsing fails, ensuring the candidate gets scored correctly.

---

### Onboarding Wizard: OperationalError No Such Table 'roles'

**Date:** 2026-07-14

**Problem:**
- Saving a role configuration or accessing dashboards in the sandboxed wizard resulted in a 500 error on `/api/recruiter/save-role` or `/api/recruiter/start-scoring`.

**Symptoms:**
- Server output and tracebacks logged `sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such table: roles` during query execution.

**Root Cause:**
- The database schema initialization function (`init_db`) in `app.py` was mistakenly imported from the root project module (`from src.models.database import init_db`) rather than the recruiter sandbox database module (`from recruiter.src.models.database import init_db`). As a result, the sandboxed SQLite DB was never initialized with the required recruiter tables.

**Solution:**
- Corrected the database initialization import in `recruiter/src/api/app.py` to point to the recruiter sandbox module: `from recruiter.src.models.database import init_db`.
- Fixed the session import in `recruiter/src/api/recruiter.py` inside the `_run_pipeline_bg` thread to cleanly access `recruiter.src.models.database`.

**Prevention Strategy:**
- Keep sandboxed execution contexts completely isolated. Never mix root-level database imports inside sandboxed controllers.

---

### Onboarding Wizard: Double 'recruiter/' Folder Path Resolution Bug

**Date:** 2026-07-14

**Problem:**
- Dynamic WeightConfig JSON files, SubQuery Markdown files, and job metadata were generated in duplicated folders, making them inaccessible to the scoring scripts.

**Symptoms:**
- The background thread logged `FileNotFoundError: No weight config found` or `FileNotFoundError: SubQuery file not found: recruiter\data\job_descriptions\...`.
- Files were written to unexpected paths like `recruiter/recruiter/data/job_descriptions/...` instead of `recruiter/data/job_descriptions/...`.

**Root Cause:**
- The `ROOT` folder path variable in `recruiter/src/api/recruiter.py` was defined as `ROOT = Path(__file__).resolve().parent.parent.parent` (resolving to the `recruiter/` directory). Consequently, code doing `ROOT / "recruiter" / "data"` created duplicate `recruiter/recruiter/data` paths.

**Solution:**
- Updated the `ROOT` path in `recruiter.py` to point to the correct workspace root directory (four parent directories up instead of three): `ROOT = Path(__file__).resolve().parent.parent.parent.parent`.

**Prevention Strategy:**
- Always trace Path parent count relative to the source code file's actual position in the directory tree.

---

### Onboarding Wizard: Background Timer NameError Crash

**Date:** 2026-07-14

**Problem:**
- Scoring execution crashed immediately after completion, failing to log final success flags.

**Symptoms:**
- The uvicorn log output raised `NameError: name 'threading' is not defined. Did you forget to import 'threading'?` inside `_run_pipeline_bg`.

**Root Cause:**
- The code scheduled a 30-second cleanup timer using `threading.Timer` but the `threading` library was never imported at the top of the API script.

**Solution:**
- Added `import threading` at the top of `recruiter/src/api/recruiter.py`.

---

### Dashboard: Path Mismatch Showing Recruiter Uploaded Roles Instead of Project Roles

**Date:** 2026-07-15

**Problem:**
- The candidate rankings dashboard (`/dashboard`) listed the recruiter-uploaded roles instead of the 8 original roles of the project.

**Symptoms:**
- The "My Project Ranking" dropdown select listed roles like `React_Developer_20260714` instead of `BusinessAnalyst`, `DataScience`, etc.

**Root Cause:**
- The path variable `ROOT` in `recruiter/src/api/dashboard.py` was defined as `ROOT = pathlib.Path(__file__).resolve().parent.parent.parent` (resolving to the `recruiter/` directory). Consequently, `SCORES_DIR` pointed to `recruiter/data/scores/composed` instead of the main project's `data/scores/composed`.

**Solution:**
- Changed `ROOT` to four parent directories up instead of three: `ROOT = pathlib.Path(__file__).resolve().parent.parent.parent.parent`. This correctly resolves to the workspace root, enabling the dashboard to display the 8 original roles from `data/scores/composed` and load the recruiter's custom scores from `recruiter/data/scores/composed` if present.

**Prevention Strategy:**
- Keep module directories and their path resolutions relative to the actual workspace root and check dashboard role output lists during manual verification.

---

### Onboarding Wizard: LLM Non-Determinism during Requirements & Sub-Query Extraction

**Date:** 2026-07-15

**Problem:**
- Requirements and sub-query generation returned inconsistent structures, mismatched IDs, and formatting variances across runs on the same Job Description.

**Symptoms:**
- Extracted requirement list structures differed in schema and detail.
- Sub-query IDs did not align sequentially with requirement IDs (e.g. using `SQ031` for `REQ-002` instead of mapping it as part of a clean sequence).
- Subsequent scoring steps failed because the evaluation loops could not match the generated sub-queries to requirements.

**Root Cause:**
- The LLM prompts used mixed, inconsistent few-shot examples across different roles (e.g. mixing SQL developer tasks with general BA experience requirements) in the same run. This prevented the model from understanding the sequential relationship of how JDs map to REQs and how REQs are decomposed into SQs.
- The model temperature was set to `0.1`, allowing minor probabilistic token variations.

**Solution:**
- Rewrote the few-shot exemplars in `/extract-reqs` and `/gen-subqueries` in `recruiter/src/api/recruiter.py` to use a **single, unified Business Analyst Lead workflow**:
  - The requirements extraction prompt shows a snippet from the BA Lead JD and its exact requirements list output (`REQ-001`, `REQ-002`, `REQ-003`).
  - The sub-query generation prompt accepts those exact same requirements as input and shows their exact sub-queries output (`SQ001` through `SQ006`).
- Set temperature to exactly `0.0` for both endpoints to ensure maximum formatting and token selection determinism.

**Prevention Strategy:**
- When design patterns require a multi-stage LLM generation pipeline (e.g., Stage 1: Extraction, Stage 2: Decomposition), use a single, consistent reference case in the few-shot examples to illustrate the entire cognitive flow.

---

### Recruiter Board: Hanging during Embedding Phase on Cloud Run (Rust Tokenizer Parallelism Deadlock)

**Date:** 2026-07-16

**Problem:**
- When running the pipeline on GCP Cloud Run, the scoring wizard hung during the embedding phase (`15:09:29 INFO src.rag.build_index | embedding 51 chunks with BAAI/bge-base-en-v1.5 (batch_size=32) ...`) and remained stuck indefinitely.

**Symptoms:**
- The weights loaded successfully (`Loading weights: 100%|██████████| 199/199 [01:01<00:00, 3.25it/s]`) but the process froze immediately upon starting the embedding encode step.
- The Cloud Run instance remained in a RUNNING state with CPU pinned or idle, but never wrote the embedding index or proceeded to the candidate scoring phase.
- Output logs were buffered, making it hard to see the exact point of failure without verbose logging.

**Root Cause:**
- Hugging Face Tokenizers (written in Rust) use parallel threads by default to tokenize text batches. Under serverless/docker container runtimes (such as GCP Cloud Run which runs containers in a sandboxed gVisor guest kernel), thread spawning and synchronization locks within child processes can cause deadlocks or indefinite freezes.

**Investigation Process:**
- Inspected the container uvicorn and runner logs, noting the hang occurred immediately inside `embedder.encode()`.
- Verified that model weights loading was successful, ruling out PyTorch startup hangs.
- Recognized the classic Hugging Face tokenizers deadlock pattern common in serverless guest kernel environments.

**Solution:**
- **Set `TOKENIZERS_PARALLELISM=false`** in the Dockerfile environment and in the runner `sub_env` configuration inside `recruiter/src/api/recruiter.py` and `src/api/recruiter.py`. This disables multithreaded tokenization, running it safely and sequentially in the main thread.
- **Set `PYTHONUNBUFFERED=1`** in the Dockerfile and subprocess runner environments to force immediate stdout flushes, enabling real-time logging.
- **Build Optimization (GCP Cache-Baking):** Configured `.dockerignore` and `.gcloudignore` to exclude local `recruiter/models/` files (reducing upload size from 466.5 MiB to 48.1 MiB). Configured the Dockerfile to pre-download the model weights during the Cloud Build phase directly on Google's high-speed network. This baked the model cache directly into the container image, allowing the container to run completely offline at runtime with zero startup latency.

**Prevention Strategy:**
- Always set `TOKENIZERS_PARALLELISM=false` in serverless and containerized Python application runtimes.
- Disable python buffering with `PYTHONUNBUFFERED=1` in container deployments to ensure real-time logging in UI consoles.
- Prevent local model uploads by using ignore files and pre-downloading models in the Dockerfile cache layers.


---

### Pipeline: Only 1 of N Candidates Ranked — Parallel Candidate ID Collision

**Date:** 2026-07-17

**Problem:**
- After uploading 10 resumes and running the full pipeline, only 1 candidate appeared in the rankings table. The remaining 9 candidates were silently lost.

**Symptoms:**
- Pipeline performance log showed "Extraction Phase: 232.53 seconds (10 resumes)" — all 10 resumes were downloaded and extraction was reported complete.
- Scoring phase completed successfully with no errors.
- Rankings dashboard showed exactly 1 candidate regardless of how many resumes were in the Google Drive folder.
- `recruiter/data/processed/{slug}/` contained only a single `{slug}_CAND_0001.json` file despite 10 resumes being processed.

**Root Cause:**
- `recruiter/batch_extract_resumes.py` used `ThreadPoolExecutor(max_workers=10)` to extract resumes in parallel. Each thread called `extract_resume(path, registry=None)`.
- When `registry=None`, `extract_resume()` (via `pipeline.py`) calls `fresh_registry()` to create an isolated in-memory `CandidateRegistry` with an empty counter (`next_counter={}`).
- A fresh registry starts its counter at 0 for every role. On the first allocation, all 10 threads independently computed `current = 0 → new_counter = 1 → new_id = {slug}_CAND_0001`.
- All 10 threads wrote their extraction result to `processed/{slug}/{slug}_CAND_0001.json`. Each write overwrote the previous — the last thread to finish "won" and the other 9 candidates disappeared.
- The code comment claimed "The candidate_id is derived deterministically from the file path so it is stable across threads" — this was incorrect. The ID is sequential (counter-based), not path-derived.

**Investigation Process:**
1. Observed "10 resumes" in extraction log but "1 candidate" in rankings.
2. Checked `recruiter/data/processed/{slug}/` — confirmed only `{slug}_CAND_0001.json` existed.
3. Traced `batch_extract_resumes.py` → `extract_resume(path, registry=None)` → `fresh_registry()` in `pipeline.py`.
4. Read `CandidateRegistry.allocate_or_lookup()` in `candidate_registry.py` → counter starts at `_STARTING_COUNTER = 0` in a fresh registry → all 10 threads independently assign counter 1 → same ID.
5. Confirmed all threads write to the same output path, overwriting each other.

**Solution:**
- **File:** `recruiter/batch_extract_resumes.py`
- Changed `result = extract_resume(path, registry=None)` to `result = extract_resume(path, registry=registry)`, passing the shared registry instance to all threads.
- `CandidateRegistry.allocate_or_lookup()` is guarded internally by a `threading.RLock`. ID allocation (the fast step) is serialized correctly. The expensive PDF-parsing and LLM-normalization work still runs fully in parallel because the lock is released immediately after ID allocation.
- Removed the now-redundant post-extraction merge-back call (`registry.allocate_or_lookup()` after extraction) since `extract_resume` now registers directly with the shared registry.
- Removed the now-unused `_registry_lock = threading.Lock()` and `import threading` from `batch_extract_resumes.py`.

**Fix (git commit):** `382200e` — `fix(extraction): fix parallel candidate ID collision — all 10/10 candidates now ranked`

**Prevention Strategy:**
- Never pass `registry=None` to `extract_resume()` in a multi-threaded context. `fresh_registry()` is appropriate only for single-file, one-off scripts.
- `CandidateRegistry` is thread-safe by design (internal `RLock`). Pass the same instance to all threads.
- When testing multi-threaded extraction, verify `recruiter/data/processed/{slug}/` contains exactly N files (one per resume) before proceeding to ranking. A mismatch between "N resumes extracted" in the log and file count on disk is a strong indicator of the overwrite bug.

---

### Pipeline: Scorer 404 / Deprecated Model Error (OpenRouter)

**Date:** 2026-07-17

**Problem:**
- The scoring phase completed with 0 candidates scored (or all defaulted to 0.01 floor), despite the extraction and indexing phases succeeding.

**Symptoms:**
- Pipeline log showed "Scoring Phase: 0.00 seconds" — scoring completed almost instantly, which indicates no actual API calls were made.
- Scorer logs contained HTTP 404 or a message similar to `Model not found` / `model has been deprecated`.
- All candidate scores defaulted to floor values (0.01).

**Root Cause:**
- The model name configured in the BYOK settings (e.g., via `OPENROUTER_MODEL` env var or the Step 5 model input field) referred to a deprecated OpenRouter model endpoint. OpenRouter returns a 404 response for deprecated model IDs, which the rubric scorer treats as a failed LLM call and falls back to floor scores.

**Solution:**
- Update the model name in the BYOK settings or `.env` / Cloud Run environment variables to a currently-active OpenRouter model.
- Verify the model ID is active by checking [https://openrouter.ai/models](https://openrouter.ai/models) before configuring.
- Common working models (as of 2026-07): `meta-llama/llama-3.1-8b-instruct:free`, `google/gemma-3-27b-it:free`, `mistralai/mistral-7b-instruct:free`.

**Prevention Strategy:**
- Pin model IDs in `.env` / Cloud Run vars to models with stable, long-term support. Avoid `:free` tier models that may be deprecated without notice.
- Add a startup health-check that fires a single test prompt to the configured model and logs a warning if the response is a 4xx error, before any batch scoring begins.
- The scorer logs should surface the raw HTTP status code prominently (not just a generic "LLM call failed") so the root cause is immediately visible.

---

### UI: 'No sub-query evidence available' Displayed for Factual Checks with Full Scores

**Date:** 2026-07-17

**Problem:**
- Factual/code-only requirements (e.g. `REQ-016 Bachelor's Degree` and `REQ-017 Advanced Degree or BA Certification`) displayed a warning message saying "No sub-query evidence available" inside the score accordion card details, even though the candidate was successfully scored with full points (e.g. `5.00 / 5%`).

**Symptoms:**
- The candidate accordion cards showed a contribution of `5.00 / 5%` (or other non-zero score).
- Clicking to expand the detail card showed only the string "No sub-query evidence available." with no listed sub-queries or score details.

**Root Cause:**
- Requirements classified as code-only (e.g., location, degree, and certification checks) are evaluated deterministically in Python rather than calling the RAG search + LLM rubric pipeline.
- Because no LLM rubric is invoked, no `rubric_trace` object is generated for the requirement (`trace.sub_scores` is empty).
- The template rendering script `candidate.html` strictly checked `if (subScores.length === 0)` to display the "No sub-query evidence" message. It had no branch to display the questions and scores from the code-only results (`code_only_sq_scores`).

**Solution:**
- **Files Modified:**
  - `src/scoring/unified_scorer.py` and `recruiter/src/scoring/unified_scorer.py`: Serialized `sub_queries` list in `ComposedREQResult.to_dict()`.
  - `src/templates/candidate.html` and `recruiter/src/templates/candidate.html`: Updated the `subScores` array definition. If `trace.sub_scores` is empty, it now maps `r.sub_queries` and checks `r.code_only_sq_scores` to create virtual sub-score records dynamically on the fly.
- Displays a status label `✓ Full` / `◑ Partial` / `✗ None` and notes the evidence origin as `"Factual verification from structured profile details (e.g. education/degree/certifications)."`.

**Fix (git commit):** `bee3e23` — `fix(ui): resolve 'No sub-query evidence available' for code-only requirements`

**Prevention Strategy:**
- When adding new factual check pipelines or custom scoring strategies that bypass LLM rubrics, make sure the underlying sub-queries and score structures are still fully serialized in the JSON endpoint payload.
- Test frontend accordion cards for all requirement categories (Green, Yellow, Red) to verify detail rows render correctly for both RAG and factual checks.

---

### UI/API: API Documentation Link returns 404 in Production

**Date:** 2026-07-17

**Problem:**
- Clicking on the "API" documentation link in the navigation header of the Recruiter Board or My Project Ranking page resulted in a 404 Not Found error.

**Symptoms:**
- Clicking the "API" button in `recruiter.html` or `dashboard.html` navigated to `/api/docs` and showed `{"detail":"Not Found"}`.
- Clicking the "API Documentation" link on the home page did the same.

**Root Cause:**
- The FastAPI application hosts its interactive Swagger API documentation on the default `/docs` URL (or `/redoc` for ReDoc), but the HTML template files had href links pointing to a deprecated `/api/docs` path.

**Solution:**
- **Files Modified:**
  - [home.html](file:///C:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/recruiter/src/templates/home.html)
  - [recruiter.html](file:///C:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/recruiter/src/templates/recruiter.html)
  - [dashboard.html](file:///C:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/recruiter/src/templates/dashboard.html)
- Updated the hyperlinks from `/api/docs` to the correct `/docs` endpoint.
- Re-built and successfully re-deployed the container image to Google Cloud Run, verifying the link works and loads the Swagger UI correctly.

**Prevention Strategy:**
- When configuring path routing or mounting sub-routers in FastAPI (`app.include_router`), make sure any path changes are verified against the static UI pages.
- Add an automated navigation test in verification runs to verify all header links (e.g. Recruiter Board, My Project Ranking, API) return HTTP 200.

