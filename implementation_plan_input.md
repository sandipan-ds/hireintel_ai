# HireIntel.AI — Recruiter Onboarding Workflow

## Overview

A multi-step wizard integrated as a new **"New Job"** tab in the existing dark-mode UI.
All existing pages (Rankings, Candidate Chat) remain unchanged.

---

## UI Structure — New Tab Layout

```
Nav: HireIntel.AI  |  [ New Job ★ ]  |  Rankings  |  Configure  |  API
```

The **New Job** tab is a single-page multi-step wizard:

```
Step 1 → Step 2 → Step 3 → Step 4 → Step 5 → Step 6
JD Input   REQs    Sub-Q   Weights  Resumes   Run & View
```

Progress bar at top. Steps are linear but allow back-navigation.

---

## Step-by-Step Design

### Step 1 — Job Description Input
- **Paste JD** into a textarea, OR upload a `.txt` / `.md` / `.pdf` / `.docx` file
- **Role Name** field (free text — e.g., "Senior ML Engineer 2026 Q3")
- A note: *"The more detailed your JD, the more precisely candidates will be ranked."*
- Submit → triggers AI REQ extraction

### Step 2 — REQ Review (GREEN / YELLOW / RED)

AI extracts REQs and classifies each:

| Badge | Meaning |
|-------|---------|
| 🟢 GREEN | Clear, specific, scorable requirement |
| 🟡 YELLOW | Ambiguous but workable — recruiter should clarify |
| 🔴 RED | Too vague or missing critical detail (years? level? tool name?) |

- Each REQ shows: ID, name, category, reason for flag, and an inline **Edit** field
- If recruiter edits the JD text → **Re-extract REQs** button re-runs AI
- If recruiter edits individual REQs inline → those changes are accepted directly
- Confirm button moves to Step 3

### Step 3 — Sub-Query Review (GREEN / YELLOW / RED)

AI generates 2–6 sub-queries per REQ and classifies them similarly:
- Binary (yes/no) vs. Float (0.01–1.00) scoring type shown
- Recruiter can edit sub-query text inline
- Confirm → moves to Step 4

### Step 4 — Weight Configuration

> Reuses the **existing weight config logic** — same sliders, same validation, same 100% constraint.

- Role is pre-populated with the REQs from Step 2/3
- REQs are saved to SQLite for the weight config UI to load
- Weight config saves to DB + JSON file (same as today)

### Step 5 — Resume Sources + BYOK

**Cloud Resume Sources** (external links only — no file upload):

| Provider | Accepted Domain | Notes |
|----------|----------------|-------|
| Google Drive | `drive.google.com` | Shared folder link |
| Dropbox | `dropbox.com` | Shared folder link |
| OneDrive | `onedrive.live.com`, `1drv.ms` | Shared folder link |
| SharePoint | `sharepoint.com` | Org share link |
| Box | `box.com` | Shared folder link |

**Security validation:**
- Allowlist: only the domains above are accepted
- URL pattern check: must start with `https://`
- No URL shorteners, redirect chains, or raw IPs
- No actual download in this step — link is stored as reference only
- Warning: *"HireIntel only stores the link. Resume download happens at scoring time. Do not share links with sensitive access."*

> [!NOTE]
> The resume download/processing pipeline for new cloud-sourced resumes is a future step (Stage 8). In this release, the link is stored and a manual trigger instruction is shown.

**BYOK — Bring Your Own Key:**

```
┌─────────────────────────────────────────────┐
│  API Key (OpenRouter / Google AI / NVIDIA)  │
│  [sk-or-v1-...                           ]  │
│                                             │
│  Model (for free keys, must be multimodal): │
│  [ gemini-3.1-flash-lite ▾ ] (recommended) │
│                                             │
│  ⚠ For large batches (>100 resumes):       │
│     Paid API key is strongly recommended.   │
│     Default: gemini-3.1-flash-lite (fast)   │
│     Free keys: choose a multimodal model.   │
└─────────────────────────────────────────────┘
```

Key is **never stored** — held only in session memory and passed as a header to the backend.

### Step 6 — Run & View

- Summary panel: role name, # REQs, # sub-queries, weight config name, resume source link
- **"Run Ranking"** button triggers the existing `score_batch_composed.py` pipeline
- Progress bar / live log stream via SSE (Server-Sent Events)
- On complete → **"View Rankings"** link navigates to `/dashboard`

---

## Files to Create / Modify

### New API Router

#### [NEW] `src/api/recruiter.py`
- `POST /api/recruiter/extract-reqs` — AI extracts REQs from JD text
- `POST /api/recruiter/validate-reqs` — GREEN/YELLOW/RED classification per REQ
- `POST /api/recruiter/generate-subqueries` — AI generates + classifies sub-queries
- `POST /api/recruiter/validate-link` — Security check for cloud resume link
- `POST /api/recruiter/save-session` — Persist JD/REQ/SubQuery to `data/jobs/{session_id}/`
- `GET  /api/recruiter/session/{session_id}` — Reload a saved session

### New Database Model

#### [MODIFY] `src/models/database.py`
Add `RecruitingSession` table:
```
id, role_name, jd_text, jd_file_path, extracted_reqs_json,
subqueries_json, validation_json, resume_link, byok_model,
weight_config_id (FK), status (draft/active), created_at
```

### New Template

#### [NEW] `src/templates/recruiter.html`
- Same dark glassmorphism design as `dashboard.html`
- Multi-step wizard with progress bar
- Step components rendered server-side (Jinja2) + enhanced by JS

### Updated Navigation

#### [MODIFY] `src/templates/dashboard.html`
#### [MODIFY] `src/templates/candidate.html`
- Add **"New Job"** to the nav bar (highlighted with ★ badge)

### Job Artefact Storage

New JDs saved to `data/jobs/{session_id}/`:
```
data/jobs/{session_id}/
├── jd.md               ← original or edited JD text
├── requirements.json   ← extracted REQs with validation
├── subqueries.json     ← generated sub-queries with validation
└── metadata.json       ← role name, date, weight config ref
```
> This is **entirely separate** from `data/job_descriptions/` which holds the pre-built reference JDs.

### `src/api/app.py`

#### [MODIFY] Register new `recruiter` router + add `/recruiter` page route

---

## AI Prompts Required

| Prompt | Purpose | Input | Output |
|--------|---------|-------|--------|
| `JD-REQ-EXTRACT-001` | Extract REQs from raw JD text | JD text | JSON list of REQs with category/type |
| `REQ-VALIDATE-001` | Classify each REQ as GREEN/YELLOW/RED | REQ list | JSON with `status`, `reason` per REQ |
| `SUBQUERY-GEN-001` | Generate sub-queries per REQ | REQ + category | JSON sub-queries with scoring type |
| `SUBQUERY-VALIDATE-001` | Classify sub-queries GREEN/YELLOW/RED | Sub-query list | JSON with `status`, `reason` |

---

## Open Questions

> [!IMPORTANT]
> Please confirm before building:

1. **Step 6 (Run Ranking)**: Should "Run Ranking" actually trigger the pipeline in the browser session, or should it just save the configuration and show instructions to run it manually? *(The full pipeline can take 20–60 minutes for 100+ resumes.)*

2. **REQ editing in Step 2**: Can the recruiter add entirely new REQs not in the AI output, or only edit AI-generated ones?

3. **Session persistence**: Should a recruiter be able to save a draft session and come back to it later, or is each session a one-time flow?

4. **Multiple JDs for the same role**: Can a recruiter submit a new JD for a role that already has one (e.g., a refreshed version), or should it always create a new role?

5. **Cloud link download (Step 5)**: Is it acceptable for this release to just **store the link** and show a message like "Download resumes to `data/original/{role}/` and run the pipeline"? Or do you want actual cloud download wired up?

---

## Verification Plan

- Import new router → server starts cleanly ✅
- Step 1 extract REQs → returns valid JSON ✅
- Step 2 validation → returns GREEN/YELLOW/RED with reasons ✅
- Step 3 sub-queries → generated per REQ ✅
- Step 4 weights → existing configure page pre-populated with new REQs ✅
- Step 5 link security → only allowlisted domains accepted ✅
- Step 6 save → `data/jobs/{session_id}/` files written ✅
