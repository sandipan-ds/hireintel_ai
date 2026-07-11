# Stage 4 — Embedding Index Rebuild + JSON Quality Audit Layer (DEC-036)

## What this solves

Stage 3 produced 721 extracted JSON files in `data/processed/<role>/`.
Before any of these can enter scoring with confidence, two things must happen:

1. **Rebuild the embedding index** — the RAG layer still indexes old pre-extraction
   chunks. Until rebuilt over the new structured JSON, retrieval surfaces stale text
   and scoring is wrong regardless of schema fixes.

2. **Run the JSON Quality Audit Layer** — per `08_JSON_QUALITY_AUDIT_SPEC.md`,
   extracted JSON must never be treated as unquestionable truth. The audit layer
   determines whether each extraction is trustworthy enough to score automatically,
   needs human review, or should be re-extracted.

Without this stage, Stage 5 (Candidate Scoring) scores on unverified data.

---

## Why this order matters

```
Stage 3: PDF → JSON extraction          ← DONE (721/721)
         ↓
Stage 4A: Rebuild embedding index       ← DO FIRST — RAG depends on it
         ↓
Stage 4B: JSON Quality Audit Layer      ← Audit all 721 JSONs before scoring
         ↓
Stage 5: Candidate Scoring              ← Only score audit-passed candidates
```

Stage 4A must run before 4B because the evidence coverage audit (Layer C) reads
`evidence_chunks` and `field_evidence_map` that the indexer enriches.

---

## Architecture

```
data/processed/<role>/<candidate_id>.json   (721 files)
        │
        ▼
┌────────────────────┐
│  4A: Index Rebuild │  → src/rag/build_index.py (existing, verify + re-run)
└────────────────────┘
        │
        ▼
┌────────────────────────────────────────────────────────┐
│                 4B: JSON Audit Engine                  │
│                                                        │
│  Layer A: Schema Validation                            │
│  Layer B: Field & Section Completeness                 │
│  Layer C: Evidence Coverage                            │
│  Layer D: Semantic Missing-Info  (LLM-assisted)        │
│  Layer E: Cross-Parser Consistency                     │
│                                                        │
│  → Quality Score  (0.0–1.0)                            │
│  → Status: passed / review_required / failed           │
│  → Review Triggers (info/warning/error/critical)       │
└────────────────────────────────────────────────────────┘
        │
        ├─ passed          → ready for Stage 5 scoring
        ├─ review_required → review queue Markdown report
        └─ failed          → logged, skipped from scoring
```

---

## Proposed Changes

---

### Stage 4A — Rebuild Embedding Index

#### [MODIFY] `src/rag/build_index.py`

- Already exists. Verify it reads the new JSON schema keys correctly:
  `candidate_profile`, `evidence_chunks`, `field_evidence_map`, `confidence`.
- If it still reads old schema keys (pre-Stage-3), update the reader.
- Re-run to replace stale index.
- Output written to `data/index/` (create if missing).

No new files needed for 4A — it is a re-run task, not a code task.

---

### Stage 4B — JSON Quality Audit Layer

New package: `src/resume_parsing/audit/`

---

#### [NEW] `src/resume_parsing/audit/__init__.py`
Empty init.

---

#### [NEW] `src/resume_parsing/audit/models.py`

Defines all shared data types for the audit system.

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class AuditCheck:
    """A single audit finding from any layer."""
    check_id: str
    severity: str          # "info" | "warning" | "error" | "critical"
    layer: str             # "schema" | "field" | "section" | "evidence" | "semantic" | "cross_parser"
    field: str             # dotted path e.g. "candidate_profile.experience[1].start_date"
    issue: str
    expected: str = ""
    actual: str = ""

@dataclass
class MissingCandidate:
    """Information present in the resume but absent in the extracted JSON."""
    field_family: str      # "experience" | "certifications" | "skills" | ...
    resume_evidence: str   # exact text found in raw resume
    source_chunk_id: str   # chunk ID if mappable, else ""
    reason: str
    confidence: float

@dataclass
class ParserConflict:
    """Disagreement between two extraction routes on the same field."""
    field: str
    parser_a: str
    parser_b: str
    severity: str

@dataclass
class QualityScores:
    """Extraction-quality scores. NOT candidate quality scores."""
    schema_validity: float
    field_completeness: float
    section_completeness: float
    evidence_coverage: float
    parser_agreement: float
    ocr_quality: float
    overall_extraction_quality: float

@dataclass
class AuditResult:
    """Complete audit output for one candidate."""
    audit_version: str
    document_id: str
    candidate_id: str
    audit_status: str      # "passed" | "review_required" | "failed"
    schema_checks: list[AuditCheck] = field(default_factory=list)
    field_checks: list[AuditCheck] = field(default_factory=list)
    section_checks: list[AuditCheck] = field(default_factory=list)
    evidence_coverage_checks: list[AuditCheck] = field(default_factory=list)
    semantic_checks: list[AuditCheck] = field(default_factory=list)
    missing_candidates: list[MissingCandidate] = field(default_factory=list)
    conflicts: list[ParserConflict] = field(default_factory=list)
    quality_scores: Optional[QualityScores] = None
    review_triggers: list[AuditCheck] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
```

---

#### [NEW] `src/resume_parsing/audit/layer_a_schema.py`

**Layer A — Schema Validation**

Checks structural correctness. No LLM needed — pure deterministic rules.

Rules:
- Required top-level keys: `schema_version`, `candidate_id`, `candidate_profile`,
  `evidence_chunks`, `field_evidence_map`, `validation`, `confidence`, `raw`
- `candidate_profile` keys: `full_name`, `skills`, `experience`, `education`,
  `certifications`, `projects`, `emails`, `phones`, `links`, `languages`
- Array fields are actually arrays: `skills`, `experience`, `education`, `certifications`
- Date strings match `YYYY-MM` or `YYYY` on every experience/education entry
- `confidence.document_confidence` is float in `[0.0, 1.0]`
- `experience[].end_date` is null only when `is_current == True`
- `skills[].name` is non-empty string

```python
def run(resume_json: dict) -> tuple[list[AuditCheck], float]:
    """
    Run schema validation layer.

    Returns:
        (checks, schema_validity_score) where schema_validity_score
        is 1.0 - weighted_error_fraction.
    """
```

---

#### [NEW] `src/resume_parsing/audit/layer_b_completeness.py`

**Layer B — Field & Section Completeness**

Heuristic pattern matching on `raw.raw_text` to detect likely missing fields.

| Detector | Pattern | JSON field checked |
|---|---|---|
| Email | RFC-like regex | `candidate_profile.emails` non-empty |
| Phone | `\+?[\d\s\-\(\)]{7,}` | `candidate_profile.phones` non-empty |
| LinkedIn/GitHub URL | `linkedin.com`, `github.com` | `candidate_profile.links` non-empty |
| Experience block | company + date-range heuristic | `experience` count vs detected blocks |
| Education block | degree keyword + institution pattern | `education` count vs detected blocks |
| Certification keyword | `Certified|Certification|AWS|Azure|GCP|PMP|Scrum` | `certifications` non-empty |
| Skills heading | `Skills:|Technical Skills:` | `skills` count > 0 |

Logic:
- Pattern fires in raw text + JSON field empty/null → `warning`
- Detected count > 2× extracted count → `warning` (likely missed entries)
- Education section heading found but `education` array empty → `error`

```python
def run(resume_json: dict) -> tuple[list[AuditCheck], float]:
    """
    Run field and section completeness layer.

    Returns:
        (checks, field_completeness_score) where score =
        1 - (missing_field_fraction).
    """
```

---

#### [NEW] `src/resume_parsing/audit/layer_c_evidence.py`

**Layer C — Evidence Coverage**

Reads `field_evidence_map` and `evidence_chunks` to check forward and reverse coverage.

**Forward coverage** — for each JSON field referenced in `field_evidence_map`:
- Do the chunk IDs exist in `evidence_chunks`?
- Is the chunk text non-empty?
- Flag broken references as `error`.

**Reverse coverage** — for each chunk in `evidence_chunks`:
- Is it referenced in `field_evidence_map`?
- If not: it is unmapped. Check if its text contains certification/experience/skill
  keywords → emit `warning` (silent extraction miss).

```python
def run(resume_json: dict) -> tuple[list[AuditCheck], float]:
    """
    Run evidence coverage layer.

    Returns:
        (checks, evidence_coverage_score) where score =
        mapped_chunks / total_meaningful_chunks.
    """
```

---

#### [NEW] `src/resume_parsing/audit/layer_d_semantic.py`

**Layer D — Semantic Missing-Info Audit (LLM-assisted)**

Sends a focused prompt to the LLM asking it to identify information present in the
raw resume text but absent or underrepresented in the extracted JSON.

**Cost control:** Layer D runs **only** if Layer B or C emit at least one `warning`
or higher. For clean extractions (all green), the LLM call is skipped entirely.
This reduces API calls by ~60% in practice.

Uses the same provider rotation as `llm_normalizer.py`:
Google AI Studio → NVIDIA NIM → fallback.

**Prompt template:**

```
You are an extraction auditor. Your task is to identify information that is
explicitly present in a resume but was missed during structured extraction.
Do NOT invent new data. Only report items with clear textual evidence.

RAW RESUME TEXT:
{raw_text}

EXTRACTED JSON SUMMARY:
- Name: {full_name}
- Emails: {emails}
- Skills count: {skills_count}
- Experience entries: {experience_count}
- Education entries: {education_count}
- Certifications: {certifications_count}
- Projects: {projects_count}

Return ONLY a JSON array. Each item:
{{"field_family": "experience|certifications|skills|education|contact|project",
  "resume_evidence": "the exact text from the resume",
  "reason": "why it appears to be missing or underrepresented",
  "confidence": 0.0-1.0}}

If nothing is missing, return [].
```

```python
def run(
    resume_json: dict,
    skip_if_clean: bool = True,
    prior_checks: list[AuditCheck] | None = None,
) -> tuple[list[AuditCheck], list[MissingCandidate], float]:
    """
    Run semantic missing-info audit.

    Args:
        resume_json: Extracted candidate JSON.
        skip_if_clean: If True, skip LLM call when no prior warnings exist.
        prior_checks: Checks from Layers A/B/C to determine if LLM is needed.

    Returns:
        (checks, missing_candidates, semantic_score) where semantic_score
        = 1 - min(len(missing_candidates) / 5, 1.0).
    """
```

---

#### [NEW] `src/resume_parsing/audit/layer_e_cross_parser.py`

**Layer E — Cross-Parser Consistency**

Compares primary extraction against a lightweight re-run of the old `parser.py`
(Route D, kept as last-resort fallback) on the same source file.

Fields compared:
- `full_name` — Levenshtein distance ≤ 2 counts as agreement
- `emails` — set intersection check
- `experience` count — flag if delta > 1
- `education` count — flag if delta > 1

This is intentionally lightweight. Only run it when Layers A–D already flag issues.
Controlled by `--cross-parser` flag in the batch script (off by default).

```python
def run(resume_json: dict, source_path: str) -> tuple[list[ParserConflict], float]:
    """
    Run cross-parser consistency check.

    Returns:
        (conflicts, parser_agreement_score) where score =
        agreements / (agreements + conflicts).
    """
```

---

#### [NEW] `src/resume_parsing/audit/scorer.py`

**Quality Score Computation + Review Status**

Applies the weighted formula from `08_JSON_QUALITY_AUDIT_SPEC.md §14.2`:

```python
WEIGHTS = {
    "schema_validity":      0.20,
    "field_completeness":   0.25,
    "section_completeness": 0.20,   # derived from Layer B section checks
    "evidence_coverage":    0.20,
    "parser_agreement":     0.10,
    "ocr_quality":          0.05,
}
```

OCR quality is the average `field_confidence` when `raw.ocr_text` is non-null.
Defaults to `1.0` if OCR was not used.

**Review status thresholds:**

| Score | Status |
|---|---|
| ≥ 0.85 | `passed` |
| 0.65 – 0.84 | `review_required` |
| < 0.65 | `failed` |

Any `critical` severity trigger → always `review_required` regardless of score.

```python
def compute_scores(...) -> QualityScores: ...
def assign_status(scores: QualityScores, checks: list[AuditCheck]) -> str: ...
def extract_review_triggers(checks: list[AuditCheck]) -> list[AuditCheck]: ...
```

---

#### [NEW] `src/resume_parsing/audit/engine.py`

**Audit Orchestrator — single public entry point.**

Runs all layers in the order specified by `08_JSON_QUALITY_AUDIT_SPEC.md §18`.

```python
def audit_resume(
    resume_json: dict,
    source_path: str,
    run_semantic: bool = True,
    run_cross_parser: bool = False,
) -> AuditResult:
    """
    Run the full JSON Quality Audit for one candidate.

    Args:
        resume_json:      Extracted candidate JSON (loaded from data/processed/).
        source_path:      Original PDF/DOCX path (for Layer E).
        run_semantic:     Call the LLM for Layer D (slower but catches more misses).
        run_cross_parser: Compare against old parser output (Layer E).

    Returns:
        AuditResult with status, all checks, quality scores, review triggers.

    Raises:
        ValueError: If resume_json is missing required top-level keys.
    """
```

Execution order inside `audit_resume`:
1. Layer A: schema
2. Layer B: field + section completeness
3. Layer C: evidence coverage
4. Layer D: semantic (conditional on prior warnings + `run_semantic` flag)
5. Layer E: cross-parser (conditional on `run_cross_parser` flag)
6. `scorer.py`: compute `QualityScores` + `audit_status`
7. Build and return `AuditResult`

---

### Batch Audit Script

#### [NEW] `scripts/run_audit.py`

Walks all JSONs in `data/processed/` and runs the audit engine on each.

```
python scripts/run_audit.py [--role ROLE] [--no-semantic] [--cross-parser] [--limit N]
```

- Writes per-candidate audit JSON → `data/audit/<role>/<candidate_id>_audit.json`
- Writes role-level Markdown summary → `run_reports/audit_<role>_<timestamp>.md`
- Prints final summary:

```
Audit Complete — DataScience (42 candidates)
  passed:           36  (85.7%)
  review_required:   5  (11.9%)
  failed:            1   (2.4%)
  Avg quality score: 0.83
  Review queue:      run_reports/audit_DataScience_review_queue.md
```

---

#### [NEW] `scripts/generate_review_queue.py`

Reads all `data/audit/` files and generates a prioritized cross-role review queue:

```markdown
# Review Queue — 2026-07-12

## Critical (block from scoring)
- cand_XXXX [WebDesigning] score=0.52
  Experience section likely incomplete (3 role blocks detected, 1 extracted)

## Warning (review recommended, may score provisionally)
- cand_YYYY [DataScience] score=0.71
  "AWS Certified Developer" in raw text, absent from certifications JSON
```

---

## Files Summary

| File | Type | Purpose |
|---|---|---|
| `src/rag/build_index.py` | MODIFY | Verify new JSON schema keys; re-run |
| `src/resume_parsing/audit/__init__.py` | NEW | Package init |
| `src/resume_parsing/audit/models.py` | NEW | All shared dataclasses |
| `src/resume_parsing/audit/layer_a_schema.py` | NEW | Schema validation (deterministic) |
| `src/resume_parsing/audit/layer_b_completeness.py` | NEW | Field & section completeness (regex) |
| `src/resume_parsing/audit/layer_c_evidence.py` | NEW | Evidence coverage (forward + reverse) |
| `src/resume_parsing/audit/layer_d_semantic.py` | NEW | LLM semantic missing-info audit |
| `src/resume_parsing/audit/layer_e_cross_parser.py` | NEW | Cross-parser consistency |
| `src/resume_parsing/audit/scorer.py` | NEW | Quality scoring + review status |
| `src/resume_parsing/audit/engine.py` | NEW | Audit orchestrator (public API) |
| `scripts/run_audit.py` | NEW | Batch audit runner (all 721 candidates) |
| `scripts/generate_review_queue.py` | NEW | Cross-role review queue generator |

---

## Dependencies

No new packages required.

- Layer D reuses the LLM provider rotation from `llm_normalizer.py`
- Layer E reuses `src/resume_parsing/parser.py` (old parser, kept as Route D)
- Schema validation uses standard `re` and Python `dataclasses`

---

## Open Questions

> [!IMPORTANT]
> **Layer D API cost:** With `skip_if_clean=True`, Layer D calls the LLM only for
> candidates where Layers B/C already fired warnings (estimated ~100–200 of 721).
> Recommend running `--no-semantic` first for a fast baseline, then re-running
> semantic-only on `review_required` cases.

> [!IMPORTANT]
> **Scoring policy for `review_required` candidates:** Two options:
> - **Option A (strict):** Skip from scoring until manually approved.
> - **Option B (lenient):** Score anyway but flag report with `[AUDIT: review_required]`.
> Confirm before Stage 5. Recommendation: **Option B** — avoids blocking the entire
> scoring run on a small set of edge-case candidates.

> [!NOTE]
> **Layer E (cross-parser):** Disabled by default (`--cross-parser` flag required).
> The old `parser.py` is a weak baseline and will generate noise. Enable only for
> candidates where Layers A–D already flag `error` or `critical`.

---

## Verification Plan

1. `python src/rag/build_index.py` — confirm index rebuilds cleanly, `data/index/` populated
2. `python scripts/run_audit.py --role DataScience --no-semantic --limit 5` — fast spot-check
3. Inspect 3 `data/audit/DataScience/*.json` files — confirm `AuditResult` structure
4. Check role summary report for sensible pass/review/fail distribution
5. `python scripts/run_audit.py --role DataScience` — with semantic layer enabled
6. Compare Layer D findings vs Layer B — confirm LLM catches real misses, not hallucinating
7. `python scripts/run_audit.py` — full run, all 8 roles
8. `python scripts/generate_review_queue.py` — confirm review queue is generated
9. Confirm `data/audit/` contains 721 audit JSON files

---

## Decision Record

**DEC-036: JSON Quality Audit Layer** — to be recorded in `docs/20_DECISIONS.md`.

Documents to update after implementation:
`docs/03_CURRENT_PROGRESS.md`, `docs/20_DECISIONS.md`,
`docs/21_ARCHITECTURE_CHANGELOG.md`, `docs/22_RELEASE_NOTES.md`
