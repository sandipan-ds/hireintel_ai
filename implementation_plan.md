# Implementation Plan — Stage 5+6: Production Scoring Run with Resume-on-Interrupt

## Background

All prerequisite stages are complete and verified:

| Stage | Status |
|---|---|
| PDF → JSON Extraction (Stage 3) | ✅ 721 resumes |
| JSON Quality Audit (Stage 4B) | ✅ 709 pass, 11 review, 1 fail |
| Chunking + Embedding Index (Stage 4A) | ⚠️ **Stale — needs rebuild** (see below) |
| Scoring engine (rubric_scorer, unified_scorer, score_batch_composed) | ✅ Built + tested |
| Scoring Fixes 1–4 (evidence, semantic inference, column order, diagnostics) | ✅ Applied |
| Tests (27/27) | ✅ Passing |

---

## Known Issues Found During Audit

> [!WARNING]
> **Index is stale — 19 of 721 candidates are missing from the embedding index.**
>
> - Index built: `2026-07-12 00:13` (current session)
> - Candidates in index: **702** — missing **19**
> - All 19 are *older* than the index timestamp → they were extracted before the index was built
>   but were not captured (likely parallel extractor was still writing when `build_index.py` ran)
> - **Impact:** scoring will silently retrieve zero chunks for 19 candidates → rubric scores = 0 for all REQs
> - **Fix:** `python -m src.rag.build_index` (takes ~2–3 min, must run before scoring)

> [!NOTE]
> **Chunk metadata is minimal — does not match `09_CHUNKING_AND_METADATA_SPEC.md`**
>
> Current chunk schema: `{ "section": "summary" }` (only section name)
> Spec requires: `section_type`, `char_span`, `confidence`, `embedding_index`, `source_resume`
>
> This is a known gap — chunks were built from the old parsed-profile format.
> A **full re-chunk from the new extraction JSONs** (Stage 4A upgrade) is a separate future task.
> For now, the index rebuild using the current `build_index.py` is sufficient for the scoring run.
> This is logged as technical debt below.

> [!IMPORTANT]
> **LLM scores are in-memory only — no disk cache exists for rubric scoring results.**
>
> The `SubQueryCache` only caches subquery *embeddings* (cheap, fast).
> The LLM rubric judge calls (expensive: 10–30s per candidate per rubric REQ) produce a
> `CachedScoringTrace` that lives only in RAM. A crash mid-run = all LLM work is lost.
> This is why the progress ledger + `--resume` flag and per-candidate JSON are **required**,
> not optional.

---

## What `score_batch_composed.py` Has vs. What It Needs

| Capability | Current | After This Plan |
|---|---|---|
| Per-role batching (writes `<role>_ranked.json` per role) | ✅ | ✅ Unchanged |
| `--role X` single role | ✅ | ✅ Unchanged |
| Diagnostic reports (`score_diagnostic_<role>.txt`) | ✅ | ✅ Unchanged |
| Per-candidate JSON written immediately after scoring | ❌ | ✅ Added |
| Progress ledger (`scoring_progress.json`) | ❌ | ✅ Added |
| `--resume` flag (skip completed roles + candidates) | ❌ | ✅ Added |
| Run report Markdown | ❌ | ✅ `generate_run_report.py` |

**Why per-candidate JSON + ledger are required:**
- LLM scores are in-memory only → crash = hours of re-work
- Per-candidate JSON written immediately = each completed score is safe on disk
- Ledger tracks which candidates are done → `--resume` loads from disk, skips re-scoring

---

## Open Questions

> [!IMPORTANT]
> **Q1 — LLM Judge:** Which provider/model is the primary rubric scorer?
> `get_rubric_caller()` reads from `.env`. Confirm the right API key is set for your ≥30B model.

> [!IMPORTANT]
> **Q2 — Cache flush:** Run with `--flush-cache` (fresh embedding cache, slower first run) or without?
> Recommendation: **`--flush-cache`** for the first clean production pass.

> [!NOTE]
> **Q3 — `review_required` candidates (11 of 721):** Score provisionally — not blocked.
> Already the default behaviour. No code change needed — just confirming intent.

---

## Proposed Changes

---

### Component 0 — Rebuild Embedding Index [EXECUTION ONLY — no code change]

```bash
python -m src.rag.build_index
```

Expected output: **~4,400–4,500 chunks** (vs current 4,247 — the missing 19 will add ~50–100 chunks).

Verify after:
```bash
python -c "
import json
from pathlib import Path
lines = open('data/embeddings/recursive_chunking/chunks.jsonl').readlines()
cands = set(json.loads(l)['candidate_id'] for l in lines)
print(f'Chunks: {len(lines)}, Unique candidates: {len(cands)}')
"
```
Expected: **721 unique candidates**.

---

### Component 1 — Progress Ledger + `--resume` in `score_batch_composed.py`

> [!NOTE]
> Constraint: **do NOT touch `scripts/parallel_batch_extract.py`**. All changes in `score_batch_composed.py` only.

#### [MODIFY] score_batch_composed.py

**a) Progress ledger file constant + helper functions** (~60 lines, new code only):

```python
PROGRESS_FILE = Path("run_reports/scoring_progress.json")

def load_progress() -> dict:
    """Load the progress ledger from disk, or return a fresh empty ledger."""

def save_progress(progress: dict) -> None:
    """Atomically write the ledger: write to .tmp then rename to avoid corruption."""

def is_role_complete(progress: dict, role: str) -> bool:
    """Return True if the role is in completed_roles (fully scored in a prior run)."""

def is_candidate_scored(progress: dict, role: str, candidate_id: str) -> bool:
    """Return True if candidate_id is in scored_candidates[role]."""

def mark_candidate_done(progress: dict, role: str, candidate_id: str) -> None:
    """Add candidate to ledger and flush to disk immediately."""

def mark_role_done(progress: dict, role: str, n_candidates: int) -> None:
    """Mark role as fully complete and flush to disk."""
```

**b) Per-candidate JSON** — written immediately after `evaluate_candidate_composed` returns:
```python
# Write immediately — before moving to next candidate. This is what --resume loads.
per_cand_dir = output_dir / role
per_cand_dir.mkdir(parents=True, exist_ok=True)
(per_cand_dir / f"{candidate_id}.json").write_text(
    json.dumps(eval_result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
)
mark_candidate_done(progress, role, candidate_id)
```

**c) `--resume` CLI flag:**
```
--resume    Resume an interrupted run from run_reports/scoring_progress.json.
            Completed roles are skipped entirely.
            Already-scored candidates load their result from disk; LLM not called again.
            Without this flag, any existing ledger is deleted and the run starts fresh.
```

**d) On fresh run** (no `--resume`): delete existing `scoring_progress.json` before starting.

**e) On resume**: for candidates already in the ledger, load `data/scores/composed/<role>/<candidate_id>.json` from disk and reconstruct into `evaluations` list — then continue with unscored candidates.

**f) Rebuild ranked list at end of each role** from the `evaluations` list (which on resume is the union of disk-loaded + newly scored). This ensures `<role>_ranked.json` is always complete.

**Modified `score_role` signature:**
```python
def score_role(
    role: str,
    retriever: ThresholdRetriever,
    cache: SubQueryCache,
    llm_caller: Any | None,
    role_subqueries: dict[str, Any] | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    max_chunks_per_query: int | None = None,
    limit: int | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    progress: dict | None = None,   # NEW
    resume: bool = False,           # NEW
) -> dict:
```

---

### Component 2 — `scripts/generate_run_report.py` [NEW FILE]

**Priority: 🟡 Nice to have** — `<role>_ranked.json` already has the raw data; this script formats it into readable Markdown. Build after the scoring run if time allows.

**CLI:**
```bash
python scripts/generate_run_report.py              # all 8 roles
python scripts/generate_run_report.py --role BusinessAnalyst
```

**Output:** `run_reports/run_report_<YYYYMMDD_HHMMSS>.md`

**Sections:**
1. **Score Distribution per Role** — min / max / mean / median / std
2. **Top-10 Candidates per Role** — ranked table (candidate ID, score)
3. **Zero-Score Diagnostic Roll-up** — `[ZERO_NO_EVIDENCE]` vs `[ZERO_WRONG_INFERENCE]` counts per role + per REQ-ID
4. **Audit-Flagged Candidates** — 11 `review_required` + 1 `failed` from `run_reports/review_queue.md` with their actual scores
5. **Pipeline Health** — index size, candidates scored vs extracted, zero-evidence rate
6. **Overall Summary** — global mean score, top-1 per role

**Dependencies:** stdlib only — `json`, `pathlib`, `statistics`, `datetime`, `collections.Counter`.

---

### Component 3 — Update `03_CURRENT_PROGRESS.md`

After scoring run completes:

| Change | Detail |
|---|---|
| Stage 4A status | `✅ Complete` → `✅ Complete (index rebuilt 2026-07-12, 721 candidates)` |
| Stage 5 status | `✅ Built; pending clean data from Stage 3` → `✅ Complete — 721 candidates scored` |
| Stage 6 status | `✅ Engine built; awaiting clean data from Stage 3` → `✅ Complete` |
| Add row | `scoring_progress.json ledger + --resume flag` → ✅ |
| Add row | `generate_run_report.py` → ✅ |
| Move from "Not Yet Built" | `run_reports/ via generate_run_report.py` → ✅ |

---

## Technical Debt Logged

> [!NOTE]
> **Chunk metadata does not match `09_CHUNKING_AND_METADATA_SPEC.md`**
>
> Current chunks store only `{ "section": "summary" }`. The spec requires `section_type`,
> `char_span`, `confidence`, `embedding_index`, `source_resume`.
>
> This is a **future Stage 4A upgrade task** — re-chunk from the new schema-compliant
> extraction JSONs using a metadata-complete chunker. The current minimal chunks are
> sufficient for threshold cosine retrieval (which only needs `text` + `candidate_id`).
> The gap matters for section-aware retrieval (Phase 4.5) and chunk reports (M0.5f).
>
> **Do not block the scoring run on this.** Log it in `03_CURRENT_PROGRESS.md` as ⬜.

---

## Full Execution Order

```
Step 0  REBUILD EMBEDDING INDEX (fixes 19 missing candidates)
        python -m src.rag.build_index
        → Verify: 721 unique candidates in chunks.jsonl

Step 1  Implement progress ledger + --resume in score_batch_composed.py
        Implement generate_run_report.py (can do after scoring if short on time)

Step 2  Smoke test (fast, no LLM — verifies ledger + per-candidate JSON work):
        python scripts/score_batch_composed.py --role DataScience --no-llm --limit 5
        → Check: data/scores/composed/DataScience/*.json (5 files created)
        → Check: run_reports/scoring_progress.json (5 candidates recorded)

Step 3  Test resume:
        python scripts/score_batch_composed.py --role DataScience --no-llm --limit 3
        python scripts/score_batch_composed.py --role DataScience --no-llm --resume
        → Confirm: 3 loaded from disk, remaining 2 scored fresh (or vice versa)
        → Confirm: final DataScience ranked JSON has correct count

Step 4  Full production run:
        python scripts/score_batch_composed.py --flush-cache
        If interrupted at any point:
        python scripts/score_batch_composed.py --resume

Step 5  Generate run report:
        python scripts/generate_run_report.py
        → Open run_reports/run_report_<timestamp>.md

Step 6  Review results:
        - Top candidates per role look plausible (not all 0 or all 100)
        - ZERO_WRONG_INFERENCE rate < 20% (calibration target)
        - Audit-flagged candidates appear in ranked list with [PROVISIONAL] note

Step 7  Update 03_CURRENT_PROGRESS.md
```

---

## Verification Commands

### After Step 0 — Index rebuild
```bash
python -c "
import json
lines = open('data/embeddings/recursive_chunking/chunks.jsonl').readlines()
cands = set(json.loads(l)['candidate_id'] for l in lines)
print(f'Chunks: {len(lines)}, Unique candidates: {len(cands)}')
assert len(cands) == 721, f'Expected 721 candidates, got {len(cands)}'
print('Index OK')
"
```

### After Step 2 — Smoke test
```bash
python -c "
import json; from pathlib import Path
p = json.loads(Path('run_reports/scoring_progress.json').read_text())
print('Completed roles:', p.get('completed_roles'))
print('DataScience scored:', len(p.get('scored_candidates', {}).get('DataScience', [])))
files = list(Path('data/scores/composed/DataScience').glob('*.json'))
print('Per-candidate files on disk:', len(files))
"
```

### After Step 4 — Full run completeness check
```bash
python -c "
from pathlib import Path
roles = ['BusinessAnalyst','DataScience','JavaDeveloper','ReactDeveloper',
         'SalesManager','SQLDeveloper','SrPythonDeveloper','WebDesigning']
total_proc = total_scored = 0
for role in roles:
    proc = len([f for f in Path(f'data/processed/{role}').glob('*.json')
                if not f.name.endswith(('_intelligence_report.json','_structured_profile.json'))])
    scored = len(list(Path(f'data/scores/composed/{role}').glob('*.json')))
    total_proc += proc; total_scored += scored
    status = '✅' if proc == scored else f'❌ ({proc} processed, {scored} scored)'
    print(f'{role:30s} {status}')
print(f'Total: {total_scored}/{total_proc}')
"
```

---

## What This Does NOT Include

| Feature | Future Milestone | Notes |
|---|---|---|
| Chunk metadata upgrade (full spec) | Stage 4A upgrade | Technical debt logged above |
| JD clarification loop (Green/Yellow/Red) | Phase 4.5 | |
| `expected_years` in recruiter UI | Phase 4.5 | DB field exists; UI not exposed |
| Resume Chat CLI | Phase 6 | Prompt spec exists; not wired |
| MLflow + Optuna experiment tracking | M0.5c / M0.5d | |
| Candidate Comparison UI | Later | Score deltas computed; no UI |
| Hiring Recommendations | Later | |
