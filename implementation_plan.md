# Stage 3 — PDF Resume → JSON Extraction Pipeline (DEC-035)

## What this solves

The existing `src/resume_parsing/parser.py` extracts raw text using `pdfplumber`.
It breaks on two-column layouts, graphical headers, sidebar sections, scanned PDFs,
and DOCX files. The output is unstructured text — it does not follow
`06_RESUME_EXTRACTION_JSON_SCHEMA.md`, which is the data contract all downstream
scoring depends on.

This plan implements a **routed extraction pipeline** that produces schema-compliant
JSON from any resume format, per `07_SPECIAL_GUIDE_PDF_RESUME_TO_JSON.md`.

---

## Why this is the critical path

Without correct JSON extraction:
- Chunking produces noise chunks from broken reading order
- Retrieval surfaces irrelevant text
- The scoring LLM gets wrong evidence
- Scores are wrong regardless of the scoring formula

All downstream stages (4 → 5 → 6) depend on Stage 3 output.

---

## Architecture

```
Input (PDF / DOCX / image)
        │
        ▼
┌─────────────────────┐
│   File Classifier   │  → native_pdf / scanned_pdf / mixed_pdf / docx
└─────────────────────┘
        │
   ┌────┴────────────────────────────────┐
   │                                              │
   ▼                                              ▼
Route A: Native PDF / DOCX                  Route B: Scanned / Image PDF
  Step 1: Docling (primary parser)            Step 1: PaddleOCR (text detection)
  Step 2: Unstructured (fallback)             Step 2: Surya (layout + reading order)
        │                                          │
        └──────────┬────────────────────┘
                   ▼
         ┌────────────────────┐
         │   Section Builder   │  → group into 7 canonical sections
         └────────────────────┘
                   │
                   ▼
         ┌────────────────────┐
         │   LLM Normalization │  → dates, degrees, skill names → structured fields
         └────────────────────┘
                   │
                   ▼
         ┌────────────────────┐
         │  Schema Validation  │  → required fields check + confidence score
         └────────────────────┘
                   │
                   ▼
         Output JSON (per 06_RESUME_EXTRACTION_JSON_SCHEMA.md)
```

---

## Proposed Changes

### New Package: `src/resume_parsing/extraction/`

#### [NEW] `src/resume_parsing/extraction/__init__.py`
Empty init file.

#### [NEW] `src/resume_parsing/extraction/file_classifier.py`
- `classify_file(path: str) -> FileType`
- `FileType` enum: `NATIVE_PDF`, `SCANNED_PDF`, `MIXED_PDF`, `DOCX`, `TEXT`
- Detection: try `pdfplumber` text extraction; if < 50 chars/page → classify `SCANNED_PDF`
- DOCX: check extension + `python-docx` content sniff

#### [NEW] `src/resume_parsing/extraction/docling_parser.py`
- `extract_with_docling(path: str) -> ExtractionResult`
- Primary parser for native PDFs using **Docling**
- Produces reading-order-correct elements: paragraphs, headings, tables, lists
- Returns `None` gracefully if Docling not installed or fails

#### [NEW] `src/resume_parsing/extraction/unstructured_parser.py`
- `extract_with_unstructured(path: str) -> ExtractionResult`
- Fallback parser using **Unstructured**
- Element-level output: `Title`, `NarrativeText`, `ListItem`, `Table`
- Supports PDF and DOCX

#### [NEW] `src/resume_parsing/extraction/ocr_parser.py`
- `extract_with_ocr(path: str) -> ExtractionResult`
- **PaddleOCR** for text detection and recognition
- **Surya** for layout analysis and reading-order recovery
- Handles multi-column layouts
- Only loaded/instantiated when the file classifier routes to this path

#### [NEW] `src/resume_parsing/extraction/section_builder.py`
- `build_sections(elements: list[Element]) -> dict[str, list[str]]`
- Groups elements into 7 canonical sections:
  `summary`, `skills`, `experience`, `education`, `certifications`, `projects`, `other`
- Uses the existing `SECTION_HEADERS` synonym table from `parser.py`
- Handles heading→body grouping

#### [NEW] `src/resume_parsing/extraction/llm_normalizer.py`
- `normalize_to_schema(sections: dict, candidate_id: str) -> ResumeJSON`
- Deterministic regex for: name, email, phone, URLs (fast, no LLM)
- LLM (Ollama `qwen2.5:3b`) for: dates, durations, degree names, skill list normalization
- Strict JSON-only output prompt; cites text literally, no hallucination

#### [NEW] `src/resume_parsing/extraction/schema_validator.py`
- `validate(resume_json: dict) -> ValidationResult`
- `ValidationResult`: `is_valid: bool`, `missing_fields: list[str]`, `confidence_score: float`
- Checks all required fields per `06_RESUME_EXTRACTION_JSON_SCHEMA.md`
- Flags low-confidence fields (< 0.70) for review

#### [NEW] `src/resume_parsing/extraction/pipeline.py`
- `extract_resume(path: str, candidate_id: str) -> ResumeJSON`
- Orchestrates the full pipeline: classify → route → build sections → normalize → validate
- The single entry point for all downstream code

---

### Batch Script

#### [NEW] `scripts/batch_extract_resumes.py`
- Walk `data/original/<role>/` for all 8 roles
- Run `extract_resume()` per file
- Write output to `data/processed/<role>/<candidate_id>.json`
- Log failures and low-confidence extractions to `run_reports/`
- Progress bar (tqdm)

---

### Tests

#### [NEW] `tests/unit/test_file_classifier.py` — 5 test cases
#### [NEW] `tests/unit/test_section_builder.py` — 10 test cases
#### [NEW] `tests/unit/test_schema_validator.py` — 8 test cases
#### [NEW] `tests/integration/test_extraction_pipeline.py` — 3 real resume fixtures

---

## Dependencies to Add (`requirements.txt`)

```
docling>=2.0          # primary document parser
unstructured>=0.16    # fallback element-level parser
paddleocr>=2.9        # OCR for scanned resumes
surya-ocr>=0.6        # layout analysis + reading order
python-docx>=1.1      # DOCX support
```

> [!IMPORTANT]
> `PaddleOCR` and `Surya` are large packages with model downloads on first use.
> They should only be instantiated when the file classifier routes to OCR.
> Add a `--no-ocr` flag to the batch script to skip scanned PDFs during testing.

---

## Open Questions

> [!IMPORTANT]
> **LLM normalization scope:** Should the LLM normalize all fields, or only
> ambiguous ones (dates, degree names, skill normalization)?
> **Recommendation:** deterministic regex for contact info + simple fields;
> LLM only for dates, experience bullet normalization, education parsing.

> [!IMPORTANT]
> **Keep old `parser.py` as a fallback or retire it?**
> It works for simple single-column native PDFs.
> **Recommendation:** keep it as Route D (last resort), clearly labeled.

> [!NOTE]
> **Re-parse all 721 existing resumes immediately?**
> **Recommendation:** yes — re-parse all to get a consistent data layer,
> then rebuild the embedding index. The old `data/processed/` JSONs do not
> follow `06_RESUME_EXTRACTION_JSON_SCHEMA.md`.

---

## Verification Plan

1. Install dependencies: `pip install docling unstructured paddleocr surya-ocr python-docx`
2. Run on 5 DataScience resumes: `python scripts/batch_extract_resumes.py --role DataScience --limit 5`
3. Inspect output JSON — confirm all schema fields are populated
4. Manually verify 2 complex resumes (two-column layout, scanned)
5. Check confidence scores — flag any < 0.70
6. Rebuild embedding index: `python src/rag/build_index.py`
7. Run scoring: `python scripts/score_batch_composed.py --role DataScience --limit 5`
8. Confirm scores are meaningfully higher than the current broken-parser output

---

## Decision Record

**DEC-035: PDF → JSON Extraction Pipeline** — to be formally recorded in `18_DECISIONS.md` after approval.

Documents to update after implementation:
`03_CURRENT_PROGRESS.md`, `18_DECISIONS.md`, `19_ARCHITECTURE_CHANGELOG.md`, `20_RELEASE_NOTES.md`


---

## Failure Mode 1 — Wrong Evidence Retrieved (RAG mismatch)

**Examples:**
- `cand_3b6b638c310c` REQ-011 (Visualization): Evidence shown is *"analyzing large datasets, developing dashboards..."* — no mention of Tableau/Power BI/matplotlib. Yet the candidate clearly built dashboards!
- `cand_49c7271f22cf` REQ-016 (Bachelor's Degree): Evidence shown is *"Madison University... Computer Science... GPA 3.7"* — that IS a CS degree. Score should be 1, but LLM gave 0.
- `cand_49c7271f22cf` REQ-011 (Visualization): Evidence = *"Developed insights into performance of Network/Studio programs..."* — clearly the wrong chunk retrieved.

**Root cause:** Section routing is fetching text from the wrong section, or the skill keyword (e.g., "Tableau", "matplotlib") is not present in the retrieved chunk, so the LLM correctly concludes "no evidence" — but the evidence retrieved was already the wrong one.

---

## Failure Mode 2 — LLM Sees Evidence but Still Scores 0 (Inference Failure)

**Examples (your specific ones):**
- `cand_3b6b638c310c` REQ-011: Evidence *contains* "developing visualizations... 3 new dashboards" — this IS data visualization. LLM should say `skill_presence = 1`. It said 0.
- `cand_49c7271f22cf` REQ-016: Evidence is literally *"Madison University Department of Computer Science"* — this IS a CS degree, yet `degree_match = 0`.
- `cand_2998bbbd6f03` REQ-018: Evidence contains "Designed, developed and deployed statistical data models" — directly maps to "Design & Develop ML Models". LLM gave `skill_presence = 0`.
- `cand_98344c47897a` REQ-002: Evidence = *"Masters... Advanced Statistics for Health"* — clearly relevant. LLM gave `experience_presence = 0`.

**Root cause:** The `qwen2.5:3b` model is performing **surface-level keyword matching** instead of semantic reasoning. "developing visualizations" ≠ "Tableau/matplotlib" to a small 3B model. It is not inferring that "dashboards = data visualization tools" without explicit tool names in the text.

---

## Failure Mode 3 — The "Contradictory Evidence" Problem

The LLM returns `extracted_evidence` that contains content from completely irrelevant sections (e.g., `"SAS Enterprise and SAS Miner (60 hours)"` as evidence for REQ-014 "Proven Track Record"). This happens when:
- The retrieved chunk for that requirement is from certifications/courses section
- The LLM faithfully quotes from what it was given, but it makes no sense

This means the `extracted_evidence` field in the report **is currently lying** — it says "Evidence:" but it's actually the closest thing retrieved, which may be irrelevant. The user correctly identifies this: we need to distinguish:
- **`evidence_found`**: `yes` / `no` — did the LLM actually find matching content?
- **`closest_evidence`**: the text it retrieved (regardless of whether it matched)

---

## Failure Mode 4 — Employment History Swapped Columns Bug

As documented earlier: the `_format_employment_history` renders rows as:
```
- {company} | {role} | {dates} | {months}
```
But the parsed employment history has `company` holding layout artifacts (`Oct`, `68`, `Ç2`) and `role` holding actual company names. The LLM cannot correlate skill mentions with correct job durations.

---

## Proposed Fixes

### Fix 1 — Add `evidence_found` + `closest_evidence` fields to the prompt & SubScoreResult

**What changes:**
- In the JSON skeleton sent to the LLM (`_build_rubric_prompt`), replace:
  ```json
  "extracted_evidence": "FILL: paste relevant resume text here"
  ```
  with two fields:
  ```json
  "evidence_found": "yes" or "no",
  "closest_evidence": "FILL: paste the most relevant text you found, even if it doesn't directly prove the skill"
  ```
- Add explicit instruction: *"Set `evidence_found` to `yes` only if the text directly proves the skill. Set to `no` if you are citing the closest available text but it does not prove the requirement."*
- Update `SubScoreResult` dataclass to store both `evidence_found: bool` and `closest_evidence: str`.
- The report generator and `explain_score_from_cache()` use these to emit either `"Evidence of..."` or `"No direct evidence (closest: ...)"`.

**Why this matters:**
- Makes it immediately visible WHY the LLM gave a 0 — was it truly absent, or was wrong text retrieved?
- Removes the misleading "Evidence:" label when the text shown has nothing to do with the requirement.

---

### Fix 2 — Semantic Inference Hint in Prompt

**What changes:**
- In the system prompt instruction block, add a brief inference table for common equivalences:

```
SEMANTIC INFERENCE RULES (apply these before deciding evidence_found = no):
- "dashboard", "report", "visualization", "chart", "plot" → counts as Data Visualization
- "clean", "preprocess", "transform", "wrangle", "ETL" → counts as Data Wrangling
- "deploy", "serve", "containerize", "API", "endpoint" → counts as Model Deployment
- "Bachelor" / "B.Sc" / "B.Tech" / "B.E." in CS, Stats, Maths, Engineering → counts as Degree Match
- "Master" / "M.Sc" / "M.Tech" / "MBA (quantitative)" → counts as Advanced Degree
```

This addresses the qwen2.5:3b surface-level keyword matching failure directly.

---

### Fix 3 — Employment History Column Order Fix

**What changes:**
- In `_format_employment_history()`, swap `company` and `role` in the template:
  ```python
  # Current (broken): f"- {company} | {role} | ..."
  # Fixed: f"- {role} | {company} | ..."  
  ```
  And add a header row so the LLM knows the column meaning:
  ```
  EMPLOYMENT HISTORY: Role | Company | Dates | Duration
  - Data Scientist | General Motor - NewYork | Oct 2018 - Present | 103 months (~8.6 yrs)
  ```

---

### Fix 4 — Log Enrichment: Zero-Evidence Flagging

**What changes:**
- When generating run reports, any sub-score where `evidence_found = "no"` and `sub_score = 0` is flagged as `ZERO_NO_EVIDENCE`.
- Any sub-score where `evidence_found = "yes"` and `sub_score = 0` is flagged as `ZERO_WRONG_INFERENCE` — a LLM reasoning failure we can target with better prompts.
- The log file written to `run_reports/` now includes a structured section:
  ```
  [ZERO_NO_EVIDENCE]    cand_X REQ-001 skill_presence — no matching text found
  [ZERO_WRONG_INFERENCE] cand_Y REQ-011 skill_presence — text found but LLM did not infer
  ```

---

## Files to Change

### `src/scoring/rubric_scorer.py`
- `SubScoreResult`: add `evidence_found: bool = False`, rename `extracted_evidence` → `closest_evidence`
- `_build_rubric_prompt()`: update skeleton JSON to use new field names + add semantic inference rules
- `_parse_llm_response()`: parse new `evidence_found` field, propagate to `SubScoreResult`
- `explain_score_from_cache()`: use `evidence_found` to choose label ("Evidence of..." vs "No direct evidence (closest:...)")

### `scripts/score_batch_composed.py` (or wherever the run report is generated)
- Enrich the zero-score logging with `[ZERO_NO_EVIDENCE]` / `[ZERO_WRONG_INFERENCE]` tags

### `run_reports/` generation (report writer script)
- Update the Markdown report template to emit `evidence_found: yes/no` and `closest_evidence`

---

## Open Questions

> [!IMPORTANT]
> **Should `evidence_found` be a hard gate?**  
> Option A: `evidence_found = "no"` forces `sub_score = 0` (strict — no inference allowed).  
> Option B: `evidence_found = "no"` only affects reporting, not the score (LLM can still infer and give partial credit).  
> My recommendation: **Option B** — keep scoring lenient, use `evidence_found` only for diagnostics.

> [!IMPORTANT]
> **Semantic inference rules: hardcoded vs. LLM-generated?**  
> The rules above are static. If a new role type is added, they need updating. Alternatively, the JD extraction step could generate these hints per-role. For now, a static table per dimension type is pragmatic.

> [!NOTE]
> **Does fixing the employment history column order require re-parsing all resumes?**  
> No — the fix is in the prompt formatting function only. No re-parsing needed.  
> The cached sub-query results will need to be flushed (`--flush-cache`) on the next run.

---

## Verification Plan

1. Run `score_batch_composed.py --role DataScience --limit 5 --flush-cache` after changes.
2. Check that `cand_3b6b638c310c` REQ-011 now shows `evidence_found: yes` with score > 0.
3. Check that `cand_49c7271f22cf` REQ-016 now shows `degree_match = 1`.
4. Check the run report `run_reports/run_DataScience_2.md` for reduced `[ZERO_NO_EVIDENCE]` counts.
5. Confirm total scores increase meaningfully (candidate 1 should exceed 31.5/100).
