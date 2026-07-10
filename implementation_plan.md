# Implementation Plan — New Rubric Scoring Functions

## Background & What Changed

The current scoring engine in `src/scoring/rubrics.py` defines broad **per-dimension rubric templates** (e.g. `SKILL_RUBRIC`, `EXPERIENCE_RUBRIC`, `LEADERSHIP_RUBRIC`) each containing sub-questions of type `"binary"`, `"linear"`, or `"anchored"`. The LLM reads evidence and scores each sub-question using generic anchor objects like `RELEVANCE_ANCHORS`, `COMPLEXITY_ANCHORS`, `PROFICIENCY_ANCHORS`, etc.

**The new model replaces all of this** with explicit, named **scoring functions** that the LLM calls per sub-question. Each sub-question in a SubQuery document maps to exactly one of these functions, and the function determines both the scale and the logic:

| Function | When to Use | Scale |
|---|---|---|
| `BINARY` | Is a skill present? Has the candidate served a role? Does a degree match? | `0` or `1` |
| `FOUR_BAND_QUALITATIVE` | Depth/strength of evidence when **no dates, months, or years** are mentioned | `1.00 / 0.50 / 0.25 / 0.01` |
| `FOUR_BAND_QUANTITATIVE` | Depth/strength of evidence when **dates, months, or years are mentioned** and can be extracted | `1.00 / 0.50 / 0.25 / 0.01` |
| `CGPA` | Academic grade / percentage against a recruiter-defined target | `1.00` (≥ target) or `0.50` (< target) |
| `INSTITUTION_RANK` | Tier lookup for university/institute | `1.00 / 0.75 / 0.50 / 0.01` |
| `CERTIFICATE_RANK` | Tier lookup for certification provider | `1.00 / 0.75 / 0.50 / 0.01` |

**Either-or rule for qualitative vs quantitative:** For any given sub-question evaluating depth or quantity of experience, the LLM first checks if the resume provides explicit temporal evidence (dates, duration, number of years/months). If yes → `FOUR_BAND_QUANTITATIVE`. If no → `FOUR_BAND_QUALITATIVE`. **Never both.**

**Aggregation (additive, not multiplicative):**
```
Sub-Score = SQ1 + SQ2 + SQ3 + ... + SQ_N   (simple sum)
Contribution = Weight × (Sub-Score / N)      (scaled to weight, out of weight)
Total Score = Σ all contributions             (out of 100)
```

---

## User Review Required

> [!IMPORTANT]
> **The old per-dimension rubric templates (`SKILL_RUBRIC`, `EXPERIENCE_RUBRIC`, `LEADERSHIP_RUBRIC`, `SAME_ROLE_RUBRIC`, `DOMAIN_RUBRIC`, `PROJECT_RUBRIC`, `LANGUAGE_RUBRIC`, `COMMUNICATION_RUBRIC`, `RESUME_ORGANIZATION_RUBRIC`) will be deleted.** Their sub-question logic is replaced by the new functions.

> [!WARNING]
> **The anchor objects (`RELEVANCE_ANCHORS`, `COMPLEXITY_ANCHORS`, `PROFICIENCY_ANCHORS`, `COMMUNICATION_ANCHORS`, `ORGANIZATION_ANCHORS`) will be deleted.** The new functions encode the scale directly — no separate anchor tables needed.

> [!NOTE]
> **Kept unchanged:** `BINARY_ANCHORS` (still used by `BINARY` function), `EDUCATION_RUBRIC`, `CERTIFICATION_RUBRIC`, `LOCATION_RUBRIC` templates are replaced by the new `CGPA`, `INSTITUTION_RANK`, `CERTIFICATE_RANK` functions. The code-only path in `unified_scorer` is replaced by function calls. The RAG pipeline, chunking, embeddings, API, and DB remain untouched.

---

## Proposed Changes

### 1. DELETE — Legacy Scoring Files

#### [DELETE] [subquery_retrieval.py](file:///c:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/src/services/subquery_retrieval.py)
Legacy sub-query similarity vector search. Superseded by regular RAG (DEC-017). No active callers after `scoring_subquery.py` is also removed.

#### [DELETE] [scoring_subquery.py](file:///c:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/src/services/scoring_subquery.py)
Legacy batched sub-query LLM call pipeline. Superseded by `evaluate_candidate_composed`. No active callers after `scoring_pipeline.py` cleanup.

---

### 2. MODIFY — `src/scoring/rubrics.py`

This is the **central change**. The file will be substantially rewritten.

**What is removed:**
- `RELEVANCE_ANCHORS`, `COMPLEXITY_ANCHORS`, `PROFICIENCY_ANCHORS`, `COMMUNICATION_ANCHORS`, `ORGANIZATION_ANCHORS` — all deleted.
- Per-dimension `RubricTemplate` objects: `SKILL_RUBRIC`, `EXPERIENCE_RUBRIC`, `LEADERSHIP_RUBRIC`, `SAME_ROLE_RUBRIC`, `DOMAIN_RUBRIC`, `PROJECT_RUBRIC`, `LANGUAGE_RUBRIC`, `COMMUNICATION_RUBRIC`, `RESUME_ORGANIZATION_RUBRIC` — all deleted.
- `RUBRIC_REGISTRY` dict — deleted (no longer needed; sub-question type dispatch replaces it).

**What is added — the new scoring functions:**

```python
def score_binary(condition_met: bool) -> float:
    """Binary gate: 1.0 if condition met, 0.0 otherwise."""

def score_four_band_qualitative(level: str) -> float:
    """4-band scale for qualitative evidence (no dates/years in resume).
    level values: "substantial" | "some" | "few" | "none"
    Returns: 1.00 / 0.50 / 0.25 / 0.01
    """

def score_four_band_quantitative(
    extracted_years: Optional[float],
    target_years: float,
) -> float:
    """4-band scale for quantitative evidence (dates/years present in resume).
    extracted_years >= target_years        → 1.00
    extracted_years >= 0.5 * target_years  → 0.50
    extracted_years >= 0.25 * target_years → 0.25
    else / None                            → 0.01
    """

def score_cgpa(score: Optional[float], target: float) -> float:
    """2-band CGPA/percentage check.
    score >= target  → 1.00
    score < target   → 0.50  (partial credit — candidate has degree, just below target)
    score is None    → 0.01  (no grade info found)
    """

def score_institution_rank(institute_name: str) -> float:
    """Tier lookup for university/institute via data/Institutes/institute_tiers.json.
    Tier 1 → 1.00 | Tier 2 → 0.75 | Tier 3 → 0.50 | Unlisted → 0.01
    """

def score_certificate_rank(provider_name: str) -> float:
    """Tier lookup for certification provider via data/Certificates/certificate_tiers.json.
    Tier 1 → 1.00 | Tier 2 → 0.75 | Tier 3 → 0.50 | Unlisted → 0.01
    """
```

**What is kept:**
- `Anchor`, `SubQuestion`, `RubricTemplate` dataclasses — **kept** (still needed for `SubQuestion` type declarations in the sub-query parser and prompt builder).
- `BINARY_ANCHORS` — **kept** (used by `BINARY` sub-questions).
- `EDUCATION_RUBRIC` and `CERTIFICATION_RUBRIC` template definitions — **replaced** by direct calls to `score_cgpa`, `score_institution_rank`, `score_certificate_rank` in the scorer (the template objects themselves are removed).
- `is_code_only()`, `is_rubric_bound_llm()` — **removed** (the code-only/LLM-bound split is no longer the routing mechanism; function type on each sub-question handles dispatch).

---

### 3. MODIFY — `src/scoring/tier_lookup.py`

Change `_NOT_LISTED_POINTS = 0.50` → `_NOT_LISTED_POINTS = 0.01` to align with the new unlisted fallback standard across all tier lookups.

---

### 4. MODIFY — `src/scoring/rubric_scorer.py`

Refactor the LLM response parser and sub-score aggregator:

- **Remove** all references to `RELEVANCE_ANCHORS`, `COMPLEXITY_ANCHORS`, `PROFICIENCY_ANCHORS`.
- **Add** a dispatcher that reads each sub-question's `type` field from the SubQuery document and calls the correct scoring function:
  - `"binary"` → `score_binary()`
  - `"four_band_qualitative"` → `score_four_band_qualitative()`
  - `"four_band_quantitative"` → `score_four_band_quantitative()` with `extracted_years` parsed from the LLM response.
  - `"cgpa"` → `score_cgpa()`
  - `"institution_rank"` → `score_institution_rank()`
  - `"certificate_rank"` → `score_certificate_rank()`
- **Either-or routing:** For sub-questions tagged as `"four_band"` (before the LLM call), detect if the retrieved chunks contain explicit temporal evidence. If yes → invoke `score_four_band_quantitative`. If no → invoke `score_four_band_qualitative`.
- **Aggregation:** Replace `gate × years_ratio × ...` multiplication with simple addition: `sum(sq_scores)`.

---

### 5. MODIFY — `src/scoring/unified_scorer.py`

Update `evaluate_candidate_composed` aggregation logic:

- **Replace** the legacy `Code_only_part × Rubric_LLM_part` multiplication formula with the new additive sum: `Sub-Score = SQ1 + SQ2 + ... + SQ_N`.
- **Replace** the contribution formula: `Contribution = Weight × (Sub-Score / N)`.
- **Remove** direct calls to `_score_education_code_only`, `_score_certification_code_only`, `_score_location_code_only` (these are replaced by the new function calls above routed through `rubric_scorer`).
- **Keep** the `CGPA` / `INSTITUTION_RANK` / `CERTIFICATE_RANK` code paths but refactor them to call the new `score_cgpa()`, `score_institution_rank()`, `score_certificate_rank()` functions from `rubrics.py` instead of the old structured-profile lookup helpers.

---

### 6. MODIFY — `src/services/scoring_pipeline.py`

- **Remove** all `from src.services.scoring_subquery import ...` imports.
- **Remove** all `from src.services.subquery_retrieval import ...` imports.
- **Refactor** `score_candidate_batched_end_to_end` to route all REQs (including education/certification) through the updated composed evaluator, removing the old "code_only vs llm-bound split" approach.
- **Keep** `score_candidate`, `list_candidate_ids`, `load_weight_config`, `list_configs_for_role` unchanged.

---

### 7. MODIFY — `src/api/scoring.py`

Minor alignment: ensure `ItemScoreResponse` fields reflect the new sub-score aggregation output (rename any references to old anchor-type fields).

---

## What Does NOT Change

| Component | Why Untouched |
|---|---|
| `src/rag/` (retriever, per_req_retrieval, subquery_cache, recursive_chunker) | RAG pipeline is correct and active |
| `src/resume_parsing/` | Parsing, OCR, structured profile, candidate registry are all correct |
| `src/services/subquery_parser.py` | Sub-query parser is correct; just adds `type` field per sub-question |
| `src/services/mlflow_wiring.py` | Experiment tracking is correct |
| `src/api/` (app, pages, roles, weights) | FastAPI recruiter UI is correct |
| `src/models/database.py` | SQLite schema is correct |
| `src/schemas/weight_config.py` | Pydantic config models are correct |
| `data/Institutes/institute_tiers.json` | Used by `score_institution_rank()` |
| `data/Certificates/certificate_tiers.json` | Used by `score_certificate_rank()` |
| All `*_SubQuery.md` files | Already updated to additive scoring and 0.01 floors |
| All `*_ScoringGuide.md` files | Already updated |
| `docs/WORKING_LOGIC.md` | Already updated |

---

## Verification Plan

### Automated Tests
- Verify new functions individually:
  `pytest tests/unit/test_rubrics.py`
- Verify tier lookup `_NOT_LISTED_POINTS = 0.01`:
  `pytest tests/unit/test_tier_lookup.py`
- Run the composed scorer smoke test on 1 candidate:
  `python scripts/score_batch_composed.py --role BusinessAnalyst --no-llm`
- Initialize database from scratch:
  `python scripts/init_database.py`

### Manual Verification
- Start the API: `python scripts/start_server.py`
- Verify `/api/score/BusinessAnalyst/<candidate_id>?config_name=...` returns per-item sub-scores using additive sums and that unlisted tiers return `0.01` in the scoring trace.
