# Implementation Plan — True Score Evaluation Using Judge LLMs

Implement the sample-based score validation protocol defined in [19_EVALUATION.md](file:///c:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/docs/19_EVALUATION.md). The production scorer (qwen2.5:3b via Ollama) is evaluated by sending original **PDF resumes** to stronger multimodal judges that score from the source document directly, then comparing subscores and totals.

---

## User Review Required

> [!IMPORTANT]
> **Judge Models & Key Rotation — Mandatory Constraint**
>
> Two judges, 5 keys total, unified rotation pool:
>
> | # | Key name in `.env.audit` | Provider | Model | Endpoint |
> |---|---|---|---|---|
> | 1 | `GOOGLE_API_KEY_1` | Google AI Studio | `gemini-2.5-flash` | `https://generativelanguage.googleapis.com/v1beta/openai/` |
> | 2 | `GOOGLE_API_KEY_2` | Google AI Studio | `gemini-2.5-flash` | same |
> | 3 | `NVIDIA_NIM_API_KEY_1` | NVIDIA NIM | `minimaxai/minimax-m3` | `https://integrate.api.nvidia.com/v1` |
> | 4 | `NVIDIA_NIM_API_KEY_2` | NVIDIA NIM | `minimaxai/minimax-m3` | same |
> | 5 | `NVIDIA_NIM_API_KEY_3` | NVIDIA NIM | `minimaxai/minimax-m3` | same |
>
> **Key rotation strategy:** Each provider maintains its own circular key queue. On a `429 / rate-limit` response, the script immediately advances to the next key in that provider's queue (round-robin). Exhausted keys are re-enabled after a configurable cooldown (default: 60 s). Between candidates, a short inter-call delay (default: 2 s) reduces sustained rate pressure.
>
> **Note:** `.env.audit` currently stores all three NVIDIA keys under the same label `NVIDIA_NIM_API_KEY_1`. Rename them to `NVIDIA_NIM_API_KEY_1`, `NVIDIA_NIM_API_KEY_2`, `NVIDIA_NIM_API_KEY_3` before running.
>
> **Reference score = median of both judge scores.** If one judge fails for a candidate, the other is the sole reference. If both fail, candidate is marked `judge_status: failed` and excluded from metrics.

> [!WARNING]
> **Isolation from Production Scoring**
>
> All outputs written to `data/eval/judge_eval/` only. `data/scores/composed/` is never modified.

---

## Open Questions

> [!IMPORTANT]
> **Sampling scope — per-role or cross-role?**
>
> Sample size is **10% of candidates per role** (rounded up, minimum 2). At current counts:
>
> | Role | Candidates | 10% Sample |
> |---|---|---|
> | BusinessAnalyst | 133 | 14 |
> | DataScience | 42 | 5 |
> | JavaDeveloper | 72 | 8 |
> | ReactDeveloper | 18 | 2 |
> | SQLDeveloper | 82 | 9 |
> | SalesManager | 164 | 17 |
> | SrPythonDeveloper | 98 | 10 |
> | WebDesigning | 112 | 12 |
> | **Total** | **721** | **~77** |
>
> Default run evaluates all 8 roles (~77 total samples, ~154 judge calls). Use `--role` to restrict to one role.

---

## Proposed Changes

---

### Component 1 — Isolated Evaluation Directory Structure

#### [NEW] `data/eval/judge_eval/`

```
data/eval/judge_eval/
  batch_<YYYYMMDD_HHMMSS>/
    config.json                    ← seed, roles, sample_ids, judge models, sample_pct
    progress.json                  ← per-candidate status ledger (supports --resume)
    samples/
      <candidate_id>/
        scorer_output.json         ← frozen copy from data/scores/composed/<role>/<id>.json
        judge_gemini.json          ← Gemini 2.5 Flash output
        judge_minimax.json         ← Minimax-M3 output
    comparison_report.json         ← all 8 metric categories, per-candidate + batch-aggregate
    comparison_report.md           ← human-readable summary
    flagged_for_review.json        ← candidates with >10% deviation or errors
```

---

### Component 2 — Judge LLM Scoring Script

#### [NEW] `scripts/run_judge_eval.py`

CLI:

```bash
python scripts/run_judge_eval.py                         # all roles, 10% sample each
python scripts/run_judge_eval.py --role BusinessAnalyst  # single role, 10% sample
python scripts/run_judge_eval.py --seed 42               # reproducible sampling
python scripts/run_judge_eval.py --dry-run               # sample plan only, no API calls
python scripts/run_judge_eval.py --resume                # continue an interrupted batch
```

**Sampling logic:**

```python
n_sample = max(2, math.ceil(len(candidates) * 0.10))
sample = random.sample(candidates, n_sample)
```

Applied independently per role. Seed is logged to `config.json` for reproducibility.

**Per-candidate execution:**

1. Load `data/scores/composed/<role>/<candidate_id>.json` → scorer output (read-only).
2. Locate PDF via `data/candidate_registry.json` → `source_path`.
3. Render PDF to base64 JPEG pages via `pypdfium2` (first 5 pages, scale=2.0) — same pattern as [gap_fill_extraction.py](file:///c:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/scripts/gap_fill_extraction.py).
4. Load `<Role>_SubQuery.md` + `<Role>_WeightConfig_*.json` for the role.
5. Build multimodal judge prompt (PDF images + full rubric + weight config). Instruction: *score from the PDF images directly, not from pre-extracted text*.
6. **Call both judges via the unified key rotation pool:**

   ```python
   class KeyQueue:
       """Circular key queue per provider with cooldown on exhaustion."""
       def __init__(self, keys, cooldown_s=60): ...
       def next_key(self) -> str: ...      # advances index; blocks or raises if all cooling
       def mark_rate_limited(self, key): ... # starts cooldown timer for that key
   
   google_pool  = KeyQueue([GOOGLE_API_KEY_1, GOOGLE_API_KEY_2])
   minimax_pool = KeyQueue([NVIDIA_NIM_API_KEY_1, NVIDIA_NIM_API_KEY_2, NVIDIA_NIM_API_KEY_3])
   ```

   For each judge call: attempt with current key → on `429`, call `mark_rate_limited` → retry with `next_key()`. Up to `max_retries=len(pool)` attempts before marking the candidate as failed for that judge.

7. Parse responses with `_extract_json_lenient` (reused from [rubric_scorer.py](file:///c:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/src/scoring/rubric_scorer.py)).
8. Compute reference = median of judge totals (per-SQ and overall).
9. Recompute totals from subscores for arithmetic consistency check.
10. Write to `samples/<candidate_id>/`, update `progress.json`.

**Resume from interruption (`--resume` flag):**

`progress.json` tracks status per candidate:
```json
{
  "batch_id": "batch_20260712_221500",
  "candidates": {
    "BusinessAnalyst_CAND_0001": {"status": "done"},
    "BusinessAnalyst_CAND_0007": {"status": "in_progress"},
    "SalesManager_CAND_0043":   {"status": "pending"}
  }
}
```
On `--resume`, the script:
1. Reads the most recent `batch_<timestamp>/` directory (or the path passed via `--batch`).
2. Skips all candidates with `status: done`.
3. Re-attempts `in_progress` (treat as interrupted mid-call) and all `pending` candidates.
4. Key rotation state resets at resume start (all keys re-enabled).

**Error handling:**
- One judge fails all its key retries → other is sole reference for that candidate.
- Both judges fail → `judge_status: failed`, excluded from metrics.
- Missing PDF → `status: skipped`, log warning.

**Required judge output schema:**

```json
{
  "candidate_id": "...",
  "role": "...",
  "total": <float>,
  "reqs": [
    {
      "requirement_id": "REQ-001",
      "requirement_name": "...",
      "weight_percentage": 8.5,
      "rubric_sq_scores": {"SQ001": 1, "SQ002": 0, "SQ003": 0.5},
      "sub_score": <float>,
      "contribution": <float>,
      "justification": "short rationale"
    }
  ]
}
```

**Error handling:**
- One judge fails → other is sole reference for that candidate.
- Both judges fail → `judge_status: failed`, excluded from metrics.
- Missing PDF → skip, log warning.

---

### Component 3 — Score Comparison Engine

#### [NEW] `src/evaluation/score_comparator.py`

Pure computation module. Metrics (scorer vs judge reference — no inter-judge comparison):

| # | Metric | Formula |
|---|---|---|
| 1 | **Schema Agreement** | All expected REQ-IDs and SQ keys present in scorer + judge outputs. Boolean per candidate. |
| 2 | **Arithmetic Consistency** | `\|declared_total − recomputed_total\| < 0.001` — checked for scorer and each judge. |
| 3 | **Per-Criterion Absolute Error** | `\|scorer_sq[key] − ref_sq[key]\|` for every SQ across all REQs. |
| 4 | **Total Score Absolute Error** | `\|scorer_total − ref_total\|`. |
| 5 | **Relative Percentage Error** | `\|scorer_total − ref_total\| / ref_total × 100`. |
| 6 | **Deviation Direction** | `scorer_total − ref_total`. Positive = overscoring; negative = underscoring. Per-candidate. |
| 7 | **Bias Direction** | `mean(scorer_total − ref_total)` across all candidates in the batch. |
| 8 | **Aggregate Error Stats** | MAE, RMSE, StdDev of error, Max deviation — across the full batch. |

Escalation flag if: `relative_error > 10%`, schema invalid, or parse failure.

---

### Component 4 — Report Generator

#### [NEW] `scripts/generate_judge_eval_report.py`

Reads a completed batch and writes:

1. **`comparison_report.json`** — all 8 metrics, per-candidate and batch-aggregate.
2. **`comparison_report.md`** — per-candidate table (scorer | Gemini | Minimax | reference | error | flag), aggregate stats, per-REQ divergence table, flagged list.
3. **`flagged_for_review.json`** — candidates with `relative_error > 10%`, schema errors, or parse failures.

---

### Component 5 — Module Structure

#### [NEW] `src/evaluation/__init__.py`
#### [NEW] `src/evaluation/score_comparator.py`
#### [NEW] `src/evaluation/judge_prompt_builder.py`

---

## Pre-requisite: Update `.env.audit`

Before running, rename the three NVIDIA keys in `.env.audit` from:
```
NVIDIA_NIM_API_KEY_1=<val1>
NVIDIA_NIM_API_KEY_1=<val2>
NVIDIA_NIM_API_KEY_1=<val3>
```
to:
```
NVIDIA_NIM_API_KEY_1=<val1>
NVIDIA_NIM_API_KEY_2=<val2>
NVIDIA_NIM_API_KEY_3=<val3>
```

---

## Execution Order

```
Step 1  Update .env.audit (rename NVIDIA keys to KEY_1/2/3)
Step 2  Create data/eval/judge_eval/ skeleton
Step 3  Create src/evaluation/ package
Step 4  Write scripts/run_judge_eval.py
Step 5  Write scripts/generate_judge_eval_report.py
Step 6  Dry-run:  python scripts/run_judge_eval.py --dry-run --seed 42
Step 7  Live run: python scripts/run_judge_eval.py --seed 42
Step 8  Report:   python scripts/generate_judge_eval_report.py
Step 9  Review comparison_report.md + flagged_for_review.json
```

---

## Verification Plan

### Automated
- `--dry-run` emits `config.json` with correct 10% sample counts per role, both judge model names, all NVIDIA keys listed.
- Judge output JSON validates (all REQ-IDs, all SQ keys, numeric scores in range).
- Arithmetic consistency: `|recomputed − declared| < 0.001`.
- `comparison_report.json` has all 8 metric categories populated.

### Manual
- Review `comparison_report.md` after the first batch.
- Confirm `data/scores/composed/` is unmodified.
