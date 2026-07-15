# Implementation Plan — Hash-Based Job Description Caching Check

This plan designs and implements a cryptographic hashing mechanism (SHA-256) for job description texts to prevent duplicate LLM calls, avoid folder namespace pollution, and enable instant fast-forwarding of previously configured roles.

---

## Proposed Changes

### Recruiter API

#### [MODIFY] [recruiter.py](file:///c:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/recruiter/src/api/recruiter.py)
* **Define Hashing Utility:**
  Create a helper function `_get_jd_hash(text: str) -> str` to normalize the JD text (casing, trailing whitespace, line ends) and compute its SHA-256 hash.
* **Integrate Cache Check in `/extract-reqs`:**
  * Compute `jd_hash` of incoming `jd_text`.
  * Scan all subfolders under `recruiter/data/jobs/*/metadata.json`.
  * If a folder contains a matching `jd_hash` (or matching raw text):
    * Load and return the pre-saved requirements directly from `requirements.json`.
    * Skip the LLM call entirely, improving execution speed to **<1ms** and eliminating token cost.
* **Integrate Cache Check in `/gen-subqueries`:**
  * Check if the matching job directory contains a pre-saved `subqueries.json`.
  * If found, return the subqueries immediately, bypassing the LLM decomposition.
* **Derive Stable Slugs in `/save-role`:**
  * Replace the random `uuid.uuid4().hex[:8]` suffix with the stable prefix of the job description hash (`jd_hash[:8]`).
  * If a recruiter processes the same JD, it will resolve to the exact same slug (e.g. `React_Developer_20260715_a7d8c2e1`), reusing directory space and SQLite records instead of creating duplicate directories.
  * Store the `"jd_hash": jd_hash` in `metadata.json` when the configuration is saved.

---

## Verification Plan

### Automated Tests
* Create a verification script `scratch/test_jd_caching.py` to programmatically assert the cache hits:
  1. Call `/api/recruiter/extract-reqs` with a new JD.
  2. Verify that requirements are successfully extracted (non-cached first run).
  3. Call `/api/recruiter/extract-reqs` again with the same JD.
  4. Verify that it returns **instantly** (asserting execution time < 100ms) and outputs identical requirements.
  5. Run the full onboarding flow and verify that the saved role slug uses the stable hash suffix.

### Manual Verification
* Paste an existing Job Description into Step 1 of the Recruiter Board onboarding wizard.
* Click "Extract Requirements" and verify that it loads the requirements instantly if it has been run before.
