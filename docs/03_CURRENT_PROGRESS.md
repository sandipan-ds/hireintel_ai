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
| 3 | **Resume Parsing (PDF → JSON)** — routed pipeline for any format | 🟡 Pipeline built; batch extraction in progress |
| 4 | **Chunking & Embedding Index** — RecursiveChunker + ThresholdRetriever | ⬜ **NEXT** — rebuild after Stage 3 batch completes |
| 5 | **Scoring Engine** — additive formula, deterministic, LLM evidence only | ✅ built; pending Stage 3 data |
| 6 | **Candidate Ranking** — deterministic sort, per-candidate JSON output | ✅ built; pending Stage 3 data |

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

**Status: ⬜ Planned — current next step**

The system must extract structured JSON from resume PDFs of any design,
template, or writing style. This is a MUST-HAVE capability per the project spec.

The target JSON schema is defined in `06_RESUME_EXTRACTION_JSON_SCHEMA.md`.
The implementation how-to is in `07_SPECIAL_GUIDE_PDF_RESUME_TO_JSON.md`.

| Sub-step | Status |
|---|---|
| File classifier (native-text / scanned / mixed / DOCX) | ⬜ |
| Route 1: Docling primary parser | ⬜ |
| Route 2: Unstructured fallback parser | ⬜ |
| Route 3: PaddleOCR + Surya for scanned / image-heavy resumes | ⬜ |
| Section builder — canonical section grouping | ⬜ |
| LLM normalization — schema-compliant JSON output | ⬜ |
| Confidence scoring on extracted fields | ⬜ |
| Batch re-parse all resumes under the new pipeline | ⬜ |

**Why the existing parser is insufficient:**
`src/resume_parsing/parser.py` uses `pdfplumber` raw text extraction.
It does not handle two-column layouts, graphical headers, sidebar sections,
or scanned PDFs. Reading order is not preserved. Output does not follow the
JSON schema in `06_RESUME_EXTRACTION_JSON_SCHEMA.md`.

---

## Stage 4 — Chunking & Embedding Index

**Status: 🟡 Foundation built; must be rebuilt after Stage 3**

| Component | Status |
|---|---|
| `RecursiveChunker` — `chunk_size=1000`, `chunk_overlap=500` | ✅ `src/rag/recursive_chunker.py` |
| `ThresholdRetriever` — cosine >= theta, default theta=0.25 | ✅ `src/rag/retriever.py` |
| Per-REQ retrieval — embeds SubQueries, unions + dedupes chunks | ✅ `src/rag/per_req_retrieval.py` |
| Subquery embedding cache | ✅ `src/rag/subquery_cache.py` |
| Embedding model: `all-MiniLM-L6-v2`, 384-dim | ✅ `src/rag/build_index.py` |
| Zero-evidence audit log | ✅ `src/audit/no_evidence_flags.py` |

> The embedding index was built on the old parser output.
> It must be rebuilt once the new PDF -> JSON pipeline (Stage 3) is complete.

---

## Stage 5 — Scoring Engine

**Status: ✅ Built; pending clean data from Stage 3**

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
| `src/scoring/unified_scorer.py` — routes code-only vs rubric-LLM | ✅ |
| `src/scoring/graded_scorer.py` — code-only synonym + years scoring | ✅ |
| `src/scoring/tier_lookup.py` — institute + cert tier lookup | ✅ |
| `src/services/subquery_parser.py` — parse SubQuery tables | ✅ |
| `src/scoring/unified_scorer.evaluate_candidate_composed` | ✅ |
| `scripts/score_batch_composed.py` — batch CLI | ✅ |
| `src/services/llm_caller.py` — Ollama backend (qwen2.5:3b) | ✅ |
| `data/Institutes/institute_tiers.json` — 115 Tier-1 institutions | ✅ |
| `data/Certificates/certificate_tiers.json` — 115 certs | ✅ |

**Architecture compliance:**
- LLM never sees weights, never ranks ✅
- Final scores are deterministic and auditable ✅
- Cached scoring trace frozen at scoring time ✅

---

## Stage 6 — Candidate Ranking

**Status: ✅ Engine built; awaiting clean data from Stage 3**

| Component | Status |
|---|---|
| Deterministic sort by total score | ✅ |
| Output: `data/scores/composed/<role>_ranked.json` | ✅ |
| Per-candidate evaluation JSON with per-item evidence | ✅ |
| LLM never ranks (enforced by design) | ✅ |

---

## Not Yet Built

| Feature | Notes |
|---|---|
| **PDF -> JSON extraction pipeline** (Stage 3) | Critical next step |
| Run reports (`run_reports/`) | `scripts/generate_run_report.py` not built |
| JD clarification loop (Green / Yellow / Red) | Block ambiguous requirements |
| Per-item `expected_years` in the recruiter UI | DB field exists; UI not exposed |
| Resume Chat (RAG-grounded Q&A) | Prompt spec exists; not wired |
| Candidate Comparison UI | Score deltas computed; no UI |
| Hiring Recommendations | Planned for later |
| Optuna sweep (theta, chunk_size, chunk_overlap) | Not run yet |

---

## How this doc relates to others

- `02_WORKING_LOGIC.md` — canonical spec (what the system must do)
- `03_CURRENT_PROGRESS.md` (this file) — status snapshot (what it does today)
- `15_IMPLEMENTATION_ROADMAP.md` — execution plan (what to build next)
- `18_DECISIONS.md` — decision log; DEC-001 to DEC-033 are pre-restart archived context; active decisions start from DEC-034
- `19_ARCHITECTURE_CHANGELOG.md` — what changed and when
