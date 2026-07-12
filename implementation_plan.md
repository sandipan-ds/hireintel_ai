# Implementation Plan — Gap-Fill Re-Extraction for Audit-Flagged Candidates

## Background

The quality audit identified **12 candidates** (1 CRITICAL + 11 WARNING) in `run_reports/review_queue.md`
whose extracted JSONs are missing key fields (`experience`, `education`, `skills`, `certifications`).

A re-extraction pass using multimodal LLMs can fill these gaps by:
1. Sending the **original PDF** as a base64 image (for scanned/OCR-failed resumes) **plus** the existing
   raw text to a multimodal model.
2. Using the **same JSON schema and extraction prompt** that `llm_normalizer.py` already uses.
3. Only patching the **specific empty fields** — never overwriting fields that were successfully extracted.
4. Writing the patched JSON back to `data/processed/<Role>/<candidate_id>.json`.

---

## Pre-Flight Audit Results

| Candidate | Raw Text | PDF on Disk | Gaps |
|---|---|---|---|
| WebDesigning_CAND_0016 | 1,877 ch | ✅ | skills, experience, education, certifications |
| WebDesigning_CAND_0014 | **188 ch** | ✅ | skills, experience, education ← scanned |
| SalesManager_CAND_0158 | 578 ch | ✅ | skills, experience, certifications |
| BusinessAnalyst_CAND_0128 | 1,633 ch | ✅ | experience, education, certifications |
| BusinessAnalyst_CAND_0132 | 2,177 ch | ✅ | skills |
| WebDesigning_CAND_0009 | **94 ch** | ✅ | skills, education, certifications ← scanned |
| SQLDeveloper_CAND_0038 | 2,493 ch | ✅ | education, certifications |
| SrPythonDeveloper_CAND_0038 | 1,667 ch | ✅ | certifications |
| SrPythonDeveloper_CAND_0045 | 1,817 ch | ✅ | certifications |
| SrPythonDeveloper_CAND_0062 | 1,667 ch | ✅ | certifications |
| WebDesigning_CAND_0003 | 1,418 ch | ✅ | certifications |
| SalesManager_CAND_0046 | 2,079 ch | ✅ | certifications |

> [!IMPORTANT]
> `CAND_0014` (188 ch) and `CAND_0009` (94 ch) have nearly no raw text — original OCR failed.
> These **must** use PDF-as-image (base64) so the vision model can see the actual resume.
> All others should also send the PDF image as primary input, with raw_text as supplementary context.

---

## Provider Configuration (`.env.audit`)

The script reads exclusively from `.env.audit` (not `.env`) using the same multi-key loader
pattern already established in `llm_normalizer.py`.

| Priority | Provider | Keys | Model | Modality |
|---|---|---|---|---|
| 1 | Google AI Studio | GOOGLE_API_KEY_1, _2 | `gemini-2.5-flash` | ✅ Vision |
| 2 | NVIDIA NIM | NVIDIA_NIM_API_KEY_1 (×3) | `minimaxai/minimax-m3` | ✅ Vision |
| 3 | OpenRouter | OPENROUTER_API_KEY_1, _2, _3 | `google/gemma-4-31b-it` | ✅ Vision |

All three providers support the OpenAI-compatible chat completions API with image content.

> [!NOTE]
> `.env.audit` has a typo: `base_url-"..."` (dash instead of equals) on line 17 for OpenRouter.
> The script will hardcode the correct base URLs (same pattern as `llm_normalizer.py`) to avoid
> depending on a broken key. The OpenRouter base URL is `https://openrouter.ai/api/v1`.

---

## Open Questions

> [!NOTE]
> **Q1 — Scope:** Should the script run only on the 12 review-queue candidates, or any candidate
> with empty fields?
> **Default in plan:** Flagged candidates from `review_queue.md` first; `--all-gaps` flag for full corpus.

> [!NOTE]
> **Q2 — Overwrite policy after gap-fill:** After patching the JSON, should the script re-trigger
> chunking + index rebuild automatically?
> **Default in plan:** Script writes patched JSON and prints instructions to re-run `build_index.py`
> and `score_batch_composed.py --resume` — does NOT auto-trigger (avoids silent cascading).

---

## Proposed Changes

---

### Component 1 — `scripts/gap_fill_extraction.py` [NEW FILE]

A self-contained script. No changes to existing extraction pipeline files.

#### Architecture

```
gap_fill_extraction.py
│
├── load_env_audit()          — parse .env.audit, same duplicate-key logic as llm_normalizer.py
├── build_audit_providers()   — ordered list (Google → NVIDIA → OpenRouter) from .env.audit keys
├── pdf_to_base64_images()    — convert each page of PDF to JPEG base64 for vision API
├── build_gap_fill_prompt()   — construct the targeted re-extraction prompt (schema-identical)
├── call_multimodal_llm()     — try providers in order with PDF image + raw_text in message
├── patch_candidate_json()    — merge only missing fields; preserve existing populated fields
├── load_progress()           — read gap_fill_progress.json ledger
├── save_progress()           — atomic write (tmp → rename)
├── main()                    — CLI: --resume, --candidate, --all-gaps, --dry-run
│
└── gap_fill_progress.json    → run_reports/gap_fill_progress.json
```

#### Progress Ledger Schema

```json
{
  "completed": ["WebDesigning_CAND_0016", "SrPythonDeveloper_CAND_0038"],
  "failed": ["WebDesigning_CAND_0014"],
  "skipped_no_gaps": []
}
```

#### CLI Flags

```
python scripts/gap_fill_extraction.py                  # all 12 review_queue candidates
python scripts/gap_fill_extraction.py --resume         # skip already completed
python scripts/gap_fill_extraction.py --candidate WebDesigning_CAND_0016
python scripts/gap_fill_extraction.py --all-gaps       # scan all 721 processed JSONs
python scripts/gap_fill_extraction.py --dry-run        # print what would be patched; no writes
```

#### Prompt Strategy

The gap-fill prompt differs from the original extraction prompt in one key way:
**it tells the LLM which fields are already filled and which are missing**, so it
focuses only on the gaps without touching working fields.

```
EXISTING DATA (already extracted — do NOT change these):
  full_name: "..."
  emails: [...]
  phones: [...]   ← or "EMPTY — please try to find"
  skills: [...]   ← or "EMPTY — please try to find"

GAPS TO FILL (these fields are currently empty [] or null — fill them if present in the resume):
  experience: []  → fill with job history if found
  education:  []  → fill with degree/institution if found
  certifications: [] → fill with any certifications found

IMPORTANT: Return ONLY the gap fields in your JSON response.
Do NOT return fields that are already filled above.
```

The response is merged via `patch_candidate_json()` which only copies keys from the
LLM response that are currently empty in the stored JSON.

#### Multimodal Message Format

For vision-capable providers, each message will include:

```python
messages = [
    {"role": "system", "content": SYSTEM_PROMPT},
    {"role": "user", "content": [
        {"type": "text", "text": prompt_text},
        # Up to 3 pages as base64 images (most resumes are 1-2 pages)
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{page1_b64}"}},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{page2_b64}"}},
    ]}
]
```

PDF → JPEG conversion uses `pdf2image` (already available via the OCR pipeline).
Fallback: if `pdf2image` fails, send text-only prompt with raw_text.

---

### Component 2 — Post-Run: Re-score flagged candidates

After gap-fill completes, run targeted re-score:

```bash
# Re-score only the patched candidates (cheap — just 12 of 721)
python scripts/score_batch_composed.py --candidate WebDesigning_CAND_0016 --flush-cache
# Or re-score each role that had a patch:
python scripts/score_batch_composed.py --role WebDesigning --resume
```

> [!NOTE]
> This step is manual — the gap-fill script prints the exact commands to run after completion.

---

### Component 3 — Update `03_CURRENT_PROGRESS.md`

| Change | Detail |
|---|---|
| Add row | `scripts/gap_fill_extraction.py` — gap-fill re-extraction for audit-flagged candidates → ✅ |
| Stage 4A status | Add note: `gap_fill_extraction.py patches 12 flagged candidates` |

---

### Component 4 — Add `RESUME-GAPFILL-001` to `15_PROMPT_LIBRARY.md`

New prompt spec entry documenting the gap-fill prompt ID, purpose, inputs, outputs,
constraints, and version history.

---

## Full Execution Order

```
Step 0  Verify all 12 PDFs are accessible and review_queue.md exists.
        python scripts/gap_fill_extraction.py --dry-run
        → Prints: candidate list, gaps, PDF path, provider to be used. No writes.

Step 1  Run gap-fill (first pass):
        python scripts/gap_fill_extraction.py
        → Writes patched JSONs to data/processed/<Role>/<cand_id>.json
        → Writes run_reports/gap_fill_progress.json

Step 2  If interrupted, resume:
        python scripts/gap_fill_extraction.py --resume

Step 3  Verify patches:
        python scripts/gap_fill_extraction.py --dry-run
        → Should show no remaining gaps for completed candidates.

Step 4  Rebuild embedding index (picks up new chunks from patched data):
        python -m src.rag.build_index

Step 5  Re-score patched candidates:
        python scripts/score_batch_composed.py --role WebDesigning --resume
        python scripts/score_batch_composed.py --role SalesManager --resume
        python scripts/score_batch_composed.py --role BusinessAnalyst --resume
        python scripts/score_batch_composed.py --role SrPythonDeveloper --resume
        python scripts/score_batch_composed.py --role SQLDeveloper --resume

Step 6  Regenerate run report:
        python scripts/generate_run_report.py
```

---

## Verification Plan

### After Step 0 — Dry Run
- All 12 candidates listed with correct gap fields
- PDF paths resolve for all 12
- Provider list shows ≥1 provider from `.env.audit`

### After Step 1 — Gap Fill
```bash
python -c "
import json
from pathlib import Path
cands = ['WebDesigning_CAND_0016','WebDesigning_CAND_0014','SalesManager_CAND_0158',
         'BusinessAnalyst_CAND_0128','BusinessAnalyst_CAND_0132','WebDesigning_CAND_0009',
         'SQLDeveloper_CAND_0038','SrPythonDeveloper_CAND_0038','SrPythonDeveloper_CAND_0045',
         'SrPythonDeveloper_CAND_0062','WebDesigning_CAND_0003','SalesManager_CAND_0046']
roles = {'WebDesigning':'WebDesigning','SalesManager':'SalesManager',
         'BusinessAnalyst':'BusinessAnalyst','SQLDeveloper':'SQLDeveloper',
         'SrPythonDeveloper':'SrPythonDeveloper'}
for cid in cands:
    role = cid.rsplit('_CAND_',1)[0]
    p = Path(f'data/processed/{role}/{cid}.json')
    d = json.loads(p.read_text(encoding='utf-8'))
    cp = d['candidate_profile']
    gaps = [k for k in ['skills','experience','education','certifications'] if not cp.get(k)]
    status = 'STILL EMPTY' if gaps else 'FILLED'
    print(f'{cid}: {status} {gaps if gaps else \"\"}')
"
```

---

## What This Does NOT Include

| Feature | Notes |
|---|---|
| Auto-rebuild index after gap-fill | Intentionally manual — avoids silent cascading |
| Re-scoring all 721 candidates | Only re-score the patched roles |
| Gap-fill for non-flagged candidates | `--all-gaps` flag available but not default |
| Writing gap-fill output to a separate JSON | Patches the canonical processed JSON directly |
