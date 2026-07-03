# Current Progress vs `WORKING_LOGIC.md`

This document maps every step of the canonical spec
[`WORKING_LOGIC.md`](WORKING_LOGIC.md) to its implementation status as of
2026-07-03. Use it as the single source of truth for "what's done vs what's
left" when planning the next session.

**Legend:** ✅ Shipped · 🟡 Partially shipped / scaffolded · ⬜ Planned

---

## Foundational Rules

| Spec rule | Status | Where |
|---|---|---|
| System is not a generic ATS / keyword matcher / RAG chatbot | ✅ | Architecture, scoring |
| Recruiter-controlled weights (0–100%, slider UI) | ✅ | FastAPI + HTMX UI → `data/job_descriptions/<role>/<role>_WeightConfig_*.json` (normalized internally to 0–100 via `scale_factor`) |
| Recruiter-controlled `expected_years` per item | 🟡 | Default 10 in `graded_scorer.DEFAULT_EXPECTED_YEARS`; per-item field not yet exposed in UI |
| Weight normalization to 0–100 | ✅ | `scale_factor = 100 / max_score` in `src/scoring/graded_scorer.py` |
| Reproducible, auditable, explainable rankings | ✅ | `graded_scorer.evaluate_candidate` |
| LLM explains, never scores | ✅ | `src/scoring/rubric_scorer.explain_score_from_cache`; recruiter UI narrates cached traces |
| Ask for clarification, don't assume | ⬜ | No clarification loop yet |
| Document-Aware Chunking is the default | ✅ | `src/rag/chunker.py` |

---

## Role-Specific Documentation & Operational Readiness

| Role | Status | Files | SubQuery Audit |
|---|---|---|---|
| BusinessAnalyst (template) | ✅ | 8/8 | ✅ Pass |
| DataScience | ✅ | 8/8 | ✅ Pass |
| JavaDeveloper | ✅ | 8/8 | ✅ Pass |
| ReactDeveloper | ✅ | 8/8 | ✅ Pass |
| SalesManager | ✅ | 8/8 | ✅ Pass |
| SQLDeveloper | ✅ | 8/8 | ✅ Pass |
| SrPythonDeveloper | ✅ | 8/8 | ✅ Pass |
| WebDesigning | ✅ | 8/8 | ✅ Pass |

**7-file template per role** (was 8; the per-role Streamlit CLI `recruiter_weight_input.py` was retired in favour of the unified FastAPI UI on 2026-07-03):
1. `<Role>_JD.md` — Job Description
2. `<Role>_SubQuery.md` — Sub-query decomposition with scoring formulas
3. `<Role>_ScoringGuide.md` — Percentage-based weighting guide
4. `<Role>_WeightConfiguration_Guide.md` — Weight configuration instructions
5. `<Role>_RecruiterWeights_EXAMPLE.json` — Example weight configuration
6. `QUICK_START.md` — Quick start guide
7. `README_SETUP.md` — Detailed setup instructions

> Recruiter weight configuration is now done via the unified **FastAPI + HTMX** UI at `src/api/app.py` → `http://127.0.0.1:8000/configure` (added 2026-07-03). It serves all 8 roles, persists to SQLite (`data/hireintel.db`) + JSON (`data/job_descriptions/<role>/<role>_WeightConfig_*.json`), and supports strict 100% validation with +/- 0.5 step sliders.

**SubQuery audit criteria (all passed):**
- Every JD requirement has corresponding REQ in SubQuery
- Core Skills, Preferred Skills, Experience, Education sections map correctly
- Binary gates × Float evidence scoring pattern consistent
- Scoring formula documented for each requirement
- recruiter_weight_input.py REQUIREMENTS lists match SubQuery REQ-IDs

---

## JD Pipeline (Steps 0–5 of `WORKING_LOGIC.md`)

| Step | Spec | Status | Where |
|---|---|---|---|
| JD validation & clarification | Reject ambiguous JDs | ⬜ | — |
| Green / Yellow / Red requirement classification | Tag each requirement | ⬜ | — |
| Recruiter follow-up questions for Yellow items | Ask, don't assume | ⬜ | — |
| Red items block scoring until clarified | Hard gate | ⬜ | — |
| Degree equivalence table per role | Confirm acceptable alternatives | ⬜ | — |
| Per-skill expected years (ask when missing) | "Expected Tableau experience?" | ⬜ | — |
| Recruiter weight assignment 0–10 | Done via FastAPI + HTMX UI | ✅ | `src/api/app.py` → `/configure`; stores to `data/hireintel.db` + `data/job_descriptions/<role>/<role>_WeightConfig_*.json` |
| Weight normalization to 100 | `scale_factor = 100 / max_score` | ✅ | `src/scoring/graded_scorer.py` |

---

## Resume Pipeline

| Step | Spec | Status | Where |
|---|---|---|---|
| Resume Upload (PDF, DOCX, text) | Multiple formats | ✅ | `src/resume_parsing/parser.py`, OCR fallback via `pypdfium2` |
| Resume Cleaning (headers, footers, templates, noise, duplicates) | Strip noise | 🟡 | Implicit via section parsing; no dedicated cleaning step |
| Document-Aware Chunking | One chunk per experience/education/project entry | ✅ | `src/rag/chunker.py` |
| Header Normalization | Synonym lookup + fallback classification → 7 canonical sections | 🟡 | Module code existed pre-2026-07-03 but was retired during dead-code cleanup; canonical section routing now handled inline in `src/rag/section_routed.py` |
| Chunk Metadata Schema | `calculated_duration_months`, `experience_type`, `skills_asserted`, `parent_structure` | ✅ | `src/rag/chunker.py` — full schema implemented, dates parsed deterministically |
| Structured Candidate Profile Extraction | Deterministic extraction of degrees, certs, total exp, companies, dates | ✅ | `src/resume_parsing/structured_profile.py` — separate record, no double-counting of overlapping experience |
| Evidence Extraction | Linked to source text | ✅ | `char_span` in chunk records |
| Candidate Intelligence Report | Aggregated Skills + Experience + Education + Certs + Projects + Objective Scores + Evidence | ✅ | 721 reports pre-generated 2026-07-01 → `data/processed/<role>/<id>_intelligence_report.json`. Production pipeline script retired during 2026-07-03 dead-code cleanup; report format remains valid input to `unified_scorer` |

---

## Candidate Evaluation (Steps 6–11 of `WORKING_LOGIC.md`)

| Step | Spec | Status | Where |
|---|---|---|---|
| Skill Presence (code-only) | Boolean match | ✅ | `graded_scorer._search_profile` |
| Skill Years of Experience (code-only) | Years near alias | ✅ | `graded_scorer._detect_years_in_text` |
| Skill Depth (rubric-bound LLM) | LLM judge against recruiter rubric | ✅ | `src/scoring/rubric_scorer.py` + `src/scoring/rubrics.py` SKILL_RUBRIC |
| Relevant Experience (rubric-bound LLM) | Same-role / industry / leadership via LLM judge | ✅ | `src/scoring/rubric_scorer.py` + EXPERIENCE/LEADERSHIP/DOMAIN rubrics |
| Same Role Experience | Similar-role via rubric LLM | ✅ | `src/scoring/rubrics.py` SAME_ROLE_RUBRIC — "Has served in a similar role?" |
| Education (Degree Match + Institute Tier) | Code-only: degree match + tier lookup | ✅ | `src/scoring/unified_scorer._score_education_code_only` + `src/scoring/tier_lookup.py` |
| Education (Institution Quality) | IIT / NIT / Tier-1 / Tier-2 / Tier-3 / not-listed | ✅ | `data/Institutes/institute_tiers.json` + `tier_lookup.py` |
| Certifications (Match + Provider Tier) | Code-only: cert match + tier lookup | ✅ | `src/scoring/unified_scorer._score_certification_code_only` + `tier_lookup.py` |
| Certifications (Provider Reputation) | AWS / Microsoft / Google / Coursera / local | ✅ | `data/Certificates/certificate_tiers.json` + `tier_lookup.py` |
| Projects (rubric-bound LLM) | Relevance + depth via LLM judge | ✅ | `src/scoring/rubrics.py` PROJECT_RUBRIC |
| Location | Code-only binary match | ✅ | `src/scoring/unified_scorer._score_location_code_only` |
| Languages (rubric-bound LLM) | Presence + proficiency via LLM judge | ✅ | `src/scoring/rubrics.py` LANGUAGE_RUBRIC |
| Communication Quality | LLM judge against anchored scale | ✅ | `src/scoring/rubrics.py` COMMUNICATION_RUBRIC |
| Resume Organization | LLM judge against anchored scale | ✅ | `src/scoring/rubrics.py` RESUME_ORGANIZATION_RUBRIC |
| Section-Routed Evidence Retrieval | Exact label match on canonical sections | ✅ | `src/rag/section_routed.py` — fixed mapping table, no embeddings |
| Rubric Templates | Fixed sub-questions + anchored scales per dimension | ✅ | `src/scoring/rubrics.py` — 12 templates registered |
| Per-item raw score = `min(importance, years / expected × importance)` | Years-proportional (code-only mode) | ✅ | `graded_scorer.evaluate_candidate` |
| Partial credit (mentioned, no years) | `importance × 0.3` | ✅ | `graded_scorer.evaluate_candidate` |
| Total normalized to 100 | `total_raw × scale_factor` | ✅ | `graded_scorer.evaluate_candidate` + `unified_scorer.evaluate_candidate_unified` |
| Per-item evidence (section, snippet, years, reason) | Mandatory | ✅ | `ItemEvaluation` + `UnifiedItemEvaluation` dataclass |
| Cached rubric reasoning for score explanation | Store sub-scores + cited evidence at scoring time | ✅ | `src/scoring/rubric_scorer.py` CachedScoringTrace — frozen at scoring time |
| Score explanation from cache | Narrate cached trace without re-scoring | ✅ | `src/scoring/rubric_scorer.explain_score_from_cache` |
| Unified scoring (code-only + rubric LLM) | Both modes in one engine | ✅ | `src/scoring/unified_scorer.py` — routes per dimension type |
| Score Explanation Using RAG | Retrieve → ground → narrate | 🟡 | LLM service scaffolded; per-item explanation from cache implemented in `rubric_scorer.py`; full RAG follow-up not yet wired |

---

## Candidate Ranking

| Rule | Status | Where |
|---|---|---|
| Sort by deterministic total | ✅ | `_ranked_rows` (in `graded_scorer`); 8 ranked files in `data/scores/graded/<role>_ranked.json` from pre-2026-07-03 batch run |
| LLM never ranks | ✅ | Enforced by design |
| Cosine similarity is a supporting signal only | 🟡 | Vector index exists (`data/embeddings/index.npz`); recruiter-facing cosine match UI not built |

---

## Resume Chat

| Step | Status |
|---|---|
| Document-Aware Chunking for retrieval | ✅ |
| RAG-grounded answers | ⬜ (no resume-chat method implemented; prompt spec in `PROMPT_LIBRARY.md` RESUME-CHAT-001 not wired to code) |
| Strict grounding prompt (no hallucination) | ⬜ (prompt spec exists in `PROMPT_LIBRARY.md` RESUME-CHAT-001; not implemented in code) |
| "Information not found in candidate documents." fallback | ⬜ (string appears only in docs; not in any `.py` file) |

---

## Candidate Comparison

| Step | Status | Where |
|---|---|---|
| Side-by-side comparison | 🟡 | Standalone CLI script retired 2026-07-03; `unified_scorer` produces per-item evidence + score deltas ready for a comparison view; not yet exposed in any UI |
| Evidence-backed "Why A above B" | 🟡 | Deterministic score deltas + component breakdown are produced by `unified_scorer`; LLM narrative generation deferred until LLM caller is wired |

---

## Hiring Recommendations

| Step | Status |
|---|---|
| Generate evidence-backed recommendation text | ⬜ (planned for Phase 8) |

---

## Quality-Based Evaluation (Spec §"Quality-Based Evaluation")

| Tier | Status | Where |
|---|---|---|
| Institution quality tiers | ✅ | `data/Institutes/institute_tiers.json` — 115 Tier 1, 54 Tier 2, 155 Tier 3, not-listed=0.50 |
| Certification provider reputation | ✅ | `data/Certificates/certificate_tiers.json` — 115 Tier 1, 45 Tier 2, 10 Tier 3, not-listed=0.50 |
| Recruiter-controlled tier definitions | ✅ | JSON files are recruiter-editable; `reload_tier_databases()` clears cache |
| Tier lookup code | ✅ | `src/scoring/tier_lookup.py` — word-boundary matching, `lru_cache` |
| Tier integration in scorer | ✅ | `src/scoring/unified_scorer.py` — education + certification code-only scoring |

---

## Evaluation & Validation (Phase 7)

| Metric family | Status |
|---|---|
| Resume Parsing: Precision / Recall / F1 | ⬜ |
| Retrieval: Recall@K / Precision@K / MRR / nDCG | ⬜ |
| Generation: Faithfulness / Groundedness / Answer Relevancy | ⬜ |
| Ranking: Top-K Accuracy / Recruiter Agreement / Ranking Accuracy | ⬜ |
| Hallucination Rate | ⬜ |
| Business: Screening Efficiency / Recruiter Time Saved | ⬜ |

---

## Next Recommended Unit of Work

**Status as of 2026-07-03:**

The recruiter weight-configuration UI is now live (FastAPI + HTMX, `/configure`). Dead-code cleanup complete: 14 orphan `.py` files removed, retired `recruiter_weight_input.py` per-role scripts, retired the `phase45_pipeline.py` driver (data outputs retained). Production scorer (`unified_scorer`) and FastAPI app verified loading and serving.

**Immediate next unit of work** (in order of unblocking power):

1. **Wire the FastAPI weight UI to the scoring engine.** The UI produces `data/job_descriptions/<role>/<role>_WeightConfig_*.json` in the canonical format, but `unified_scorer` does not yet read these. Add a `load_weight_config(role_name, config_name) -> dict` helper in `src/scoring/` and have the scorer consume it. This unblocks end-to-end "configure → score" in one click.
2. **Per-item `expected_years` field in the FastAPI weight UI.** Today the form captures `weight_percentage` only. Add an "expected years" input next to each slider and persist it to the `weight_items.expected_years` column + JSON.
3. **JD clarification loop (Green / Yellow / Red).** Build `clarifications.json` per role listing each REQ as G/Y/R plus an auto-generated recruiter question. Add a UI page that shows Red items as hard blocks and Yellow items as required questions before scoring policy locks.
4. **Recruiter evaluation (Phase 7).** With the scorer consuming recruiter JSON, ground-truth the ranking on the 8 ranked files in `data/scores/graded/` against recruiter-confirmed expectations. See `EVALUATION.md` for metrics.

**Why this order:**
- Step 1 closes the "configure weights → see scores" loop the recruiter is waiting for.
- Step 2 makes per-skill expected years recruiter-editable (a spec rule in `WORKING_LOGIC.md`).
- Step 3 unblocks ambiguous JD handling (a foundational rule still ⬜).
- Step 4 is the meta-validation that confirms the platform actually works.

---

## Recruiter Weight Configuration UI (2026-07-03)

**FastAPI + HTMX** service, no JS framework required. Replaces the per-role Streamlit CLI scripts (`recruiter_weight_input.py`) and the old `src/ui/recruiter_weight_config.py`.

| Capability | Status | Where |
|---|---|---|
| Role dropdown (8 roles synced from SubQuery docs) | ✅ | `src/api/roles.py` `POST /api/roles/sync-from-subquery` |
| Per-requirement slider (0–100, 0.5 step) | ✅ | `src/templates/partials/requirements_form.html` |
| `+` / `−` buttons for 0.5 fine-tuning | ✅ | `onclick="adjustWeight(...)"` in `configure.html` |
| Live category breakdown (rated/total/remaining %) | ✅ | `updateTotals()` JS in `configure.html` |
| Live "Current Weights" panel (REQ-ID, name, current %) | ✅ | `renderCurrentWeights()` JS in `configure.html` |
| Auto-balance to 100% | ✅ | `autoBalance()` JS in `configure.html` |
| Strict 100% validation (server-side + client-side) | ✅ | `pages.py:htmx_save_weights` + `updateTotals` |
| Persist to SQLite (`weight_configurations` + `weight_items`) | ✅ | `src/models/database.py` |
| Persist to JSON (`<role>_WeightConfig_<name>.json`) | ✅ | `src/services/json_export.py` |
| Delete removes from both DB and JSON | ✅ | `weights.py:delete_configuration` + `json_export.delete_json_config` |
| OpenAPI / Swagger docs | ✅ | `GET /docs` (FastAPI auto) |
| Per-item `expected_years` UI input | ⬜ | Field exists in DB + JSON; not yet exposed in slider form |
| Multiple recruiters per role (auth + isolation) | ⬜ | Single-recruiter model only |
| Edit existing config (load weights into form) | ⬜ | Configs are listed and deletable, not re-editable |

**Endpoints:**
- `GET /` — home
- `GET /configure` — weight config UI
- `GET /api/htmx/requirements/{role_id}` — slider form partial
- `GET /api/htmx/validate/{role_id}` — live validation summary
- `POST /api/htmx/save/{role_id}` — save to DB + JSON
- `GET /api/htmx/configurations/{role_id}` — saved configs list
- `GET /api/roles/`, `GET /api/weights/configurations`, etc. — REST API

**Launch:** `python -m uvicorn src.api.app:app --host 127.0.0.1 --port 8000` → http://127.0.0.1:8000/configure

---

## How this doc relates to others

- `WORKING_LOGIC.md` is the **canonical spec** (the "what should it do").
- This doc is the **status snapshot** (the "what does it do today").
- `IMPLEMENTATION_ROADMAP.md` is the **execution plan** (the "what do we build next").
- `ARCHITECTURE_CHANGELOG.md` is the **history** (the "what changed and when").