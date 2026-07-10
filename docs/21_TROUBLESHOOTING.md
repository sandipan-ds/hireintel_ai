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
