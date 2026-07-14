# Implementation Plan - Scoring Stability and Wizard Robustness

This plan addresses the scoring nondeterminism and missing candidate ranking issues under the recruiter onboarding wizard.

## Goal Description
Resolve the following issues in the recruiter wizard sandbox:
1. **Scoring Nondeterminism:** LLM scoring (e.g. via `minimax-m3`) varies wildly across runs because it fails to output parseable JSON under certain scenarios (especially when a candidate lacks any evidence), causing the scorer to fall back to a low floor score (0.01).
2. **Missing Candidates:** In subsequent scoring runs, the number of ranked candidates drops because:
   - Concurrency conflict: A cleanup timer from an earlier run fires and deletes the processed JSONs and index files of the current run.
   - Uvicorn auto-reloading: Uvicorn detects file writes under `recruiter/data/` or `recruiter/logs/` and reloads, terminating the background scoring thread mid-run.

---

## Proposed Changes

### Recruiter Scorer

#### [MODIFY] [rubric_scorer.py](file:///c:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/recruiter/src/scoring/rubric_scorer.py)
- Update `_build_rubric_prompt` to generate a syntactically valid JSON skeleton by replacing raw text placeholders (like `FILL_yes_OR_no`) with default JSON-compliant values (like `"no"`, `0`, `null`, `"none"`).
- Improve the prompt task instructions to guide the model to output valid JSON by replacing defaults rather than writing placeholders.
- Implement regex fallback parsing in `_extract_json_lenient` / `_parse_llm_response` to extract sub-scores, evidence presence, levels, and years from free-form text or invalid JSON outputs when standard parsing fails.

---

### Recruiter API

#### [MODIFY] [recruiter.py](file:///c:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/recruiter/src/api/recruiter.py)
- Introduce a thread-safe `_CLEANUP_TIMERS` dictionary to track active cleanup timers by role slug.
- In `/start-scoring`, search for any active cleanup timer for the given `role_slug` and cancel it before starting a new one.
- In `_silent_cleanup_role`, stop deleting `recruiter/data/job_descriptions/{slug}` to keep weight configs and JDs intact for the recruiter.
- Increase the cleanup timer duration from 10 minutes (600s) to 2 hours (7200s) to give the recruiter adequate time to explore candidate details and compare dashboards.

---

### Documentation

#### [MODIFY] [23_TROUBLESHOOTING.md](file:///c:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/docs/23_TROUBLESHOOTING.md)
- Document the uvicorn auto-reload termination bug on Windows when writing data/logs to the workspace.
- Recommend using `--reload-dir recruiter/src` to restrict uvicorn's watch path to source code files.

---

## Verification Plan

### Automated Tests
- Create a scratch script `c:/Users/sandi/Desktop/ML Working Folder/hireintel_ai/recruiter/scratch/test_fallback_parser.py` that runs the updated lenient JSON and regex fallback parser on historical/failing LLM responses.
- Run `pytest recruiter/tests/` to verify that rubric scoring logic still passes its unit tests.

### Manual Verification
- Deploy the updated app, start scoring via the recruiter dashboard, and monitor logs to ensure uvicorn does not reload during data writes.
- Verify that subsequent scoring runs correctly cancel previous timers and rank all candidates.
