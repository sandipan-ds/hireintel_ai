# Current Progress

This document is the **status snapshot** of the platform.
It maps what is built today against the canonical spec in `02_WORKING_LOGIC.md`.

For the execution plan of what to build next, see `15_IMPLEMENTATION_ROADMAP.md`.
For the full decision history, see `18_DECISIONS.md`.

**Legend:** ✅ Done · 🟡 Partial / in progress · ⬜ Planned

---

> ## Project Restart Notice
>
> As of **2026-07-09**, the project was restarted from scratch.
> All prior scoring caches, databases, intermediate scores, and experimental
> scripts were cleared. The pipeline is being rebuilt cleanly.
>
> **Key scoring changes introduced at restart (DEC-034):**
> - Scoring formula changed from **multiplication to addition**:
>   `Sub-Score = SQ1 + SQ2 + SQ3 + ...`
> - Recruiter weights are normalized so the total always sums to **100 points**
> - The 4-band evaluation minimum floor is now **0.01** (not 0.0) — prevents
>   any requirement from contributing absolute zero when there is any evidence
> - CGPA uses a 2-band rule: `>= target → 1.00`, else `0.50`
>
> All content below reflects the **post-restart state only**.
> Earlier milestones (DEC-001 through DEC-033) are archived in `18_DECISIONS.md`
> and marked as deprecated pre-restart context.

---

## Pipeline Overview

| # | Stage | Status |
|---|---|---|
| 1 | **JD Formation** — 8 roles with full SubQuery decomposition | ✅ |
| 2 | **Recruiter Weight Configuration** — FastAPI + HTMX UI | ✅ |
| 3 | **Resume Parsing (PDF → JSON)** — routed pipeline for any format | ✅ |
| 4A| **Chunking & Embedding Index** — RecursiveChunker + ThresholdRetriever | ✅ |
| 4B| **JSON Quality Audit** — five-layer extraction audit (DEC-036) | ✅ |
| 4C| **Gap-Fill Re-Extraction** — multimodal vision pass on audit-flagged candidates | ✅ |
| 4D| **RAG Hyperparameter Optimization** — Optuna multi-objective sweep + rank stability | ✅ |
| 5 | **Scoring Engine** — additive formula, deterministic, LLM evidence only | ✅ |
| 6 | **Candidate Ranking** — deterministic sort, per-candidate JSON output | ✅ |
| 7 | **Rankings Dashboard & Candidate Chat** — dropdown, leaderboard, inline PDF, waterfall RAG chat | ✅ |

---

## Stage 1 — JD Formation


**Status: ✅ Complete for all 8 roles**

Each role under `data/job_descriptions/<role>/` has 7 files:

| File | Purpose |
|---|---|
| `<Role>_JD.md` | Job Description |
| `<Role>_SubQuery.md` | Sub-query decomposition with scoring formulas |
| `<Role>_ScoringGuide.md` | Percentage-based weighting guide |
| `<Role>_WeightConfiguration_Guide.md` | Weight configuration instructions |
| `<Role>_WeightConfig_<name>.json` | Recruiter-saved weight configuration |
| `QUICK_START.md` | Quick start guide |
| `README_SETUP.md` | Detailed setup instructions |

| Role | SubQuery Audit |
|---|---|
| BusinessAnalyst | ✅ Pass |
| DataScience | ✅ Pass |
| JavaDeveloper | ✅ Pass |
| ReactDeveloper | ✅ Pass |
| SalesManager | ✅ Pass |
| SQLDeveloper | ✅ Pass |
| SrPythonDeveloper | ✅ Pass |
| WebDesigning | ✅ Pass |

**SubQuery structure (consistent across all roles):**
- Every JD requirement has a corresponding REQ-ID
- Each REQ decomposes into 2–6 atomic sub-queries
- Sub-queries are Binary (0 or 1) or Float (0.01–1.00 on the 4-band scale)
- Scoring formula per REQ: `SQ001 + SQ002 + SQ003` (additive, DEC-034)
- Max score per REQ = sum of all sub-query maxima
- Sections: Core Skills, Preferred Skills, Experience, Education, Certifications

---

## Stage 2 — Recruiter Weight Configuration

**Status: ✅ Complete**

Recruiters assign weights to each REQ via a FastAPI + HTMX web UI.

| Capability | Status |
|---|---|
| Role dropdown (8 roles synced from SubQuery docs) | ✅ |
| Per-requirement slider (0–100, 0.5 step) | ✅ |
| Live category breakdown (rated/total/remaining %) | ✅ |
| Auto-balance to 100% | ✅ |
| Strict 100% validation (server-side + client-side) | ✅ |
| Persist to SQLite and JSON | ✅ |
| Per-item `expected_years` UI input | ⬜ (DB field exists; not in UI yet) |
| Multiple recruiters per role | ⬜ (single-recruiter only) |
| Edit existing config | ⬜ (configs are listed and deletable, not re-editable) |

**Launch:** `python -m uvicorn src.api.app:app --host 127.0.0.1 --port 8000`

---

## Stage 3 — Resume Parsing (PDF → JSON)

**Status: ✅ Complete**

The system extracts structured JSON from resume PDFs of any design, template,
or writing style. This is a MUST-HAVE capability per the project spec.

The target JSON schema is defined in `06_RESUME_EXTRACTION_JSON_SCHEMA.md`.
The implementation how-to is in `07_SPECIAL_GUIDE_PDF_RESUME_TO_JSON.md`.

| Sub-step | Status |
|---|---|
| File classifier (native-text / scanned / mixed / DOCX) | ✅ `src/resume_parsing/extraction/file_classifier.py` |
| Route 1: Docling primary parser | ✅ `src/resume_parsing/extraction/docling_parser.py` |
| Route 2: Unstructured fallback parser | ✅ `src/resume_parsing/extraction/unstructured_parser.py` |
| Route 3: PaddleOCR + Surya for scanned / image-heavy resumes | ✅ `src/resume_parsing/extraction/ocr_parser.py` |
| Section builder — canonical section grouping | ✅ `src/resume_parsing/extraction/section_builder.py` |
| LLM normalization — schema-compliant JSON output | ✅ `src/resume_parsing/extraction/llm_normalizer.py` |
| Confidence scoring on extracted fields | ✅ `src/resume_parsing/extraction/schema_validator.py` |
| Orchestrator pipeline (`extract_resume`) | ✅ `src/resume_parsing/extraction/pipeline.py` |
| Batch extraction script | ✅ `scripts/batch_extract_resumes.py` |
| Batch re-parse DataScience role (5 candidates — smoke test) | ✅ `data/processed/DataScience/` |
| Batch re-parse all 8 roles (721 total resumes) | ✅ Complete — 721 resumes processed and stored |

**Fallback chain (per file):**
`Docling` → `Unstructured` → `PaddleOCR+Surya` → `pdfplumber raw text`

**LLM Normalizer:**
- Deterministic regex for contact fields (email, phone, URLs).
- Dedicated system prompt for structured JSON extraction (not the rubric scorer prompt).
- Checks local Ollama server with 1s health ping; falls back to cloud API on failure.
- Strips markdown code fences from LLM response before JSON parse.

---

## Stage 4A — Chunking & Embedding Index

**Status: ✅ Complete**

| Component | Status |
|---|---|
| `DocumentAwareChunker` — section-based (skills, experience, etc.) chunking | ✅ `src/rag/document_aware_chunker.py` |
| `VectorIndex` top-K retrieval — default top_k=10, no threshold | ✅ `src/rag/retriever.py` |
| Per-REQ retrieval — embeds SubQueries, retrieves top-K per SQ, unions | ✅ `src/rag/per_req_retrieval.py` |
| Subquery embedding cache | ✅ `src/rag/subquery_cache.py` |
| Embedding model: `BAAI/bge-base-en-v1.5`, 768-dim | ✅ `src/rag/build_index.py` |
| Zero-evidence audit log | ✅ `src/audit/no_evidence_flags.py` |

> The embedding index was rebuilt using the `DocumentAwareChunker` and `BAAI/bge-base-en-v1.5` (768-dim) retrieval model on **2026-07-13** (3,844 chunks generated and indexed in `data/embeddings/document_aware/`).

---

## Stage 4B — JSON Quality Audit (DEC-036)

**Status: ✅ Complete**

Implements a formal five-layer quality audit for all extracted candidate JSONs prior to candidate matching/scoring.

| Audit Layer | Scope | Status |
|---|---|---|
| **Layer A: Schema** | Fields, types, dates (YYYY-MM/YYYY format), structures | ✅ `layer_a_schema.py` |
| **Layer B: Completeness** | Regex-validated emails, phones, education keywords | ✅ `layer_b_completeness.py` |
| **Layer C: Evidence** | Bidirectional mapping between JSON fields and evidence chunks | ✅ `layer_c_evidence.py` |
| **Layer D: Semantic** | LLM-assisted verification comparing raw text against summary | ✅ `layer_d_semantic.py` |
| **Layer E: Cross-Parser** | Levenshtein edit distance agreement with legacy parser | ✅ `layer_e_cross_parser.py` |
| **Scorer & Reports** | Overall extraction quality score formula & queue reports | ✅ `scorer.py` / `generate_review_queue.py` |

---

## Stage 4C — Gap-Fill Re-Extraction (DEC-036 follow-up)

**Status: ✅ Complete**

After the JSON Quality Audit (Stage 4B) identified 12 candidates with missing fields, a targeted multimodal re-extraction pass was run to fill the gaps using the original PDF pages as vision input.

| Component | Status |
|---|---|
| `scripts/gap_fill_extraction.py` — multimodal gap-fill CLI with `--resume`, `--dry-run`, `--candidate`, `--all-gaps` | ✅ |
| `.env.audit` multi-key provider loader (Google / NVIDIA NIM / OpenRouter) | ✅ |
| PDF → base64 JPEG page converter for vision APIs | ✅ |
| Gap-fill prompt `RESUME-GAPFILL-001` (fills only empty fields, never overwrites) | ✅ `docs/15_PROMPT_LIBRARY.md` |
| Progress ledger `run_reports/gap_fill_progress.json` (interrupt/resume safe) | ✅ |
| Scanned resume detection: `len(raw_text) < 3000` or `Image_*.pdf` prefix | ✅ |

**Results (2026-07-12):**
- 12 candidates targeted from `run_reports/review_queue.md`
- **2 successfully patched:**
  - `BusinessAnalyst_CAND_0132` — `skills` filled (score improved 0.522 → 0.682)
  - `WebDesigning_CAND_0016` — `skills`, `experience`, `education`, `certifications` filled
- **9 confirmed empty:** Multimodal vision pass confirmed these fields are genuinely absent from the source PDFs (no data to extract)
- **1 not targeted:** `WebDesigning_CAND_0014` (scanned, nearly empty text) — vision pass returned no extractable data
- RAG index rebuilt post-patch (4,890 chunks)
- All 5 affected roles re-scored (`BusinessAnalyst`, `WebDesigning`, `SalesManager`, `SrPythonDeveloper`, `SQLDeveloper`)



---

## Stage 4D — RAG Parameter Sweep & Stability Evaluation

**Status: ⬜ Retired (DEC-035)**

Optuna hyperparameter tuning and threshold-based sweeps are retired due to the pivot from cosine thresholding to top-K retrieval (`top_k=10`). 

Grid sweep, rank stability metrics, and parameter sweeps conducted pre-pivot (with `RecursiveChunker` + `ThresholdRetriever` + `all-MiniLM-L6-v2`) are archived, and related files have been deleted.

---

## Stage 5 — Scoring Engine

**Status: ✅ Complete — 721 candidates scored**


### Scoring Formula (DEC-034 — Additive)

```
REQ Sub-Score  = SQ1 + SQ2 + SQ3 + ...   (sum of sub-query scores)
Candidate Total = sum of (weight_pct x REQ_Sub-Score) across all REQs
                = final score out of 100
```

4-band float: `0.01` (none) / `0.25` (few) / `0.50` (some) / `1.00` (substantial)
Binary sub-query: `0` or `1`
CGPA: `1.00` if >= target, `0.50` otherwise

| Module | Status |
|---|---|
| `src/scoring/rubrics.py` — 12 rubric templates | ✅ |
| `src/scoring/rubric_scorer.py` — RUBRIC-SCORE-001 prompt, LLM judge | ✅ |
| `src/scoring/unified_scorer.py` — routes code-only vs rubric-LLM (top-K retrieval) | ✅ |
| `src/scoring/graded_scorer.py` — code-only synonym + years scoring | ✅ |
| `src/scoring/tier_lookup.py` — institute + cert tier lookup | ✅ |
| `src/services/subquery_parser.py` — parse SubQuery tables | ✅ |
| `src/scoring/unified_scorer.evaluate_candidate_composed` | ✅ |
| `scripts/score_batch_composed.py` — batch CLI using top-K retrieval | ✅ |
| `src/services/llm_caller.py` — Ollama backend (qwen2.5:3b) | ✅ |
| `data/Institutes/institute_tiers.json` — 115 Tier-1 institutions | ✅ |
| `data/Certificates/certificate_tiers.json` — 115 certs | ✅ |

**Architecture compliance:**
- LLM never sees weights, never ranks ✅
- Final scores are deterministic and auditable ✅
- Cached scoring trace frozen at scoring time ✅
- Standardized on top-K retrieval (`VectorIndex.retrieve_top_k`), guaranteeing evidence presence for LLM evaluation ✅

---

## Stage 6 — Candidate Ranking

**Status: ✅ Complete**

| Component | Status |
|---|---|
| Deterministic sort by total score | ✅ |
| Output: `data/scores/composed/<role>_ranked.json` | ✅ |
| Per-candidate evaluation JSON with per-item evidence | ✅ |
| LLM never ranks (enforced by design) | ✅ |
| Progress ledger (`run_reports/scoring_progress.json`) for resume-on-interrupt | ✅ |
| Post-scoring Markdown report generator (`scripts/generate_run_report.py`) | ✅ |

---

## Stage 7 — Rankings Dashboard & Candidate Chat

**Status: ✅ Complete**

FastAPI + Jinja2 + Tailwind-alternative dark-mode layout providing a recruiter-facing dashboard for ranked candidates and live context-aware chat.

| Component | Status | Description |
|---|---|---|
| Role Rankings View | ✅ Complete | Dynamic dropdown for all 8 roles, live stats panel, search, column sorting, pagination |
| Leaderboard & Visual Indicators | ✅ Complete | Score bar visualizations, zero-evidence & blocked status flags, per-REQ mini score-pips |
| Candidate Profile Detail | ✅ Complete | Circular score-arc, metadata chips, scrollable list of requirements |
| Collapsible Trace Accordions | ✅ Complete | Visual trace details for each requirement showing sub-queries, scores, extracted evidence, and original cited text |
| Inline PDF Viewer | ✅ Complete | Interactive iframe rendering candidate's source PDF inline |
| Multi-Key Waterfall Chat | ✅ Complete | Live interactive candidate RAG chat falling back across OpenCode (DeepSeek/MiniMax) -> NVIDIA NIM (3 keys) -> OpenRouter |

---

## Not Yet Built

| Feature | Notes |
|---|---|
| JD clarification loop (Green / Yellow / Red) | Block ambiguous requirements |
| Per-item `expected_years` in the recruiter UI | DB field exists; UI not exposed |
| Hiring Recommendations | Planned for later |


---

## How this doc relates to others

- `02_WORKING_LOGIC.md` — canonical spec (what the system must do)
- `03_CURRENT_PROGRESS.md` (this file) — status snapshot (what it does today)
- `15_IMPLEMENTATION_ROADMAP.md` — execution plan (what to build next)
- `18_DECISIONS.md` — decision log; DEC-001 to DEC-033 are pre-restart archived context; active decisions start from DEC-034
- `19_ARCHITECTURE_CHANGELOG.md` — what changed and when
