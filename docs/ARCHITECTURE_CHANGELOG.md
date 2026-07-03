# Architecture Changelog

## Overview

This document records architecture changes that affect system structure, runtime behavior, AI workflows, storage, APIs, or deployment.

---

## 2026-07-01 — Tier database expansion (international institutes + certs + fake flagging)

### Changed
- **`data/Institutes/institute_tiers.json`** expanded from ~356 to **466 institutes**:
  - Tier 1: 137 → **192** (+55 international universities: USA, UK, Germany, Canada, Finland, Mexico, South Korea per QS World Rankings 2025).
  - Tier 2: 54 → **98** (+44 international universities).
  - Tier 3: 165 → **176** (+11 new + 13 fake/unknown flagged).
- **`data/Certificates/certificate_tiers.json`** expanded to **223 certificates**:
  - Tier 2 additions: Spring Professional, Oracle Academy, Cloudera, SAS, SQL Server, Adobe Expert, Python Institute.
  - Tier 3 additions: NLP Practitioner, Django, Python Developer, FreeCodeCamp, CNPR, Certified Sales Rep, Salesforce, Java SE, Tableau Desktop/Server, Microsoft Data Analyst, Google Cloud PE, Certified Data Scientist.

### Added
- **Flagged institute detection** in `src/scoring/tier_lookup.py`:
  - `is_institute_flagged(name)` — returns True for fake/unknown universities.
  - `get_flagged_institutes()` — returns full list of flagged entries.
  - 13 flagged institutes marked with `_note` field in `institute_tiers.json`.
- **Flagged penalty** in `src/scoring/unified_scorer.py`: flagged institutes receive a **50% penalty** on education score.
  - Formula: `degree_match × institute_tier_points × 0.5` (vs. `× 1.0` for non-flagged).
- **Structured profile fields** in `src/resume_parsing/structured_profile.py`:
  - `flagged_institutes: List[str]`
  - `has_flagged_institute: bool`

### Decision
- Flagged institutes are placed in **Tier 3 (0.5 points)** — same as unlisted. This ensures they don't get penalized excessively but also don't get undue credit.
- The 50% penalty is applied **multiplicatively on top of** the tier points, so a flagged Tier 3 entry contributes 0.25 effective points instead of 0.5.
- See `AI_DESIGN_RATIONALE.md` §11 for the full rationale.

### Countries covered in tier database

| Country | Tier 1 | Tier 2 | Tier 3 | Total |
|---------|--------|--------|--------|-------|
| USA | 30+ | 15+ | 5+ | 50+ |
| UK | 8 | 10 | 2 | 20 |
| Germany | 3 | 7 | 3 | 13 |
| Canada | 3 | 7 | 7 | 17 |
| Finland | 2 | 3 | 4 | 9 |
| Mexico | 1 | 4 | 3 | 8 |
| South Korea | 3 | 6 | 8 | 17 |

---

## 2026-07-01 — Phase 4.5 pipeline (parse + chunk + score 721 resumes)

### Added
- `scripts/phase45_pipeline.py` — end-to-end batch pipeline: parse → header normalization → structured profile → chunk → score → intelligence report. Accepts `--role`, `--all-roles`, `--skip-scoring`.
- 721 parsed profiles in `data/processed/<role>/` (8 role folders, one JSON per candidate).
- 721 structured profile records in `data/processed/<role>/<id>_structured_profile.json`.
- 721 chunk files in `data/chunks/<role>/<candidate_id>.jsonl` (Document-Aware chunking with full metadata schema: `section_type`, `parent_structure`, `temporal_context.calculated_duration_months`, `skills_asserted`, `experience_type`).
- 8 ranked score files in `data/scores/graded/<role>_ranked.json` with per-item evidence (matched, years_detected, snippet, reason, section).
- 721 Candidate Intelligence Reports in `data/processed/<role>/<id>_intelligence_report.json`.

### Changed
- `CURRENT_PROGRESS.md` — Candidate Intelligence Report status 🟡→✅; Next Recommended Unit of Work reframed around remaining Phase 4.5 items.
- `RELEASE_NOTES.md` — 2026-07-01 entry added.

### Decision
- The pipeline currently scores in **code-only mode** (`graded_scorer.evaluate_candidate`) because the `unified_scorer` routes skill items to rubric-bound LLM mode, which returns zero when no LLM caller is provided. The code-only graded scorer handles skill presence + years detection with synonym match and regex, producing non-zero evidence-backed scores. Wiring the rubric-bound LLM scorer (which scores skill depth, relevant experience, project complexity) requires an LLM caller and is the next step.

---

## 2026-06-30 — Two-mode scoring engine + foundation modules

### Added
- `src/resume_parsing/header_normalization.py` — Layer 1 synonym table + Layer 2 LLM fallback for 7 canonical sections (Personal_Info, Education, Experience, Projects, Skills, Certifications, Languages).
- `src/resume_parsing/structured_profile.py` — deterministic Structured Candidate Profile extraction (degrees, institutions, certifications, total experience with no double-counting, companies, roles, employment dates).
- `src/rag/section_routed.py` — Section-Routed Evidence Retrieval: fixed requirement→section mapping table, exact label match, metadata filtering for long sections. No embeddings, no cosine.
- `src/scoring/rubrics.py` — 12 rubric templates with anchored scales (0.0/0.25/0.5/0.75/1.0), sub-questions, and formulas per dimension type. Code-only vs rubric-bound LLM classification.
- `src/scoring/rubric_scorer.py` — RUBRIC-SCORE-001 prompt construction, LLM response parsing, formula evaluation in code, `CachedScoringTrace` frozen at scoring time, `explain_score_from_cache` for score explanation.
- `src/scoring/unified_scorer.py` — Unified scoring engine: routes each requirement to code-only or rubric-bound LLM mode, produces `UnifiedCandidateEvaluation` with per-item scoring traces.
- `src/scoring/tier_lookup.py` — code-only tier lookup for institutes and certificates with word-boundary matching.
- `data/Institutes/institute_tiers.json` — 115 Tier 1, 54 Tier 2, 155 Tier 3 institutes; not-listed=0.50.
- `data/Certificates/certificate_tiers.json` — 115 Tier 1, 45 Tier 2, 10 Tier 3 certificates; not-listed=0.50.
- `src/rag/chunker.py` updated — chunk metadata schema: `section_type`, `parent_structure` (organization, role_title, location, temporal_context with `calculated_duration_months`), `skills_asserted`, `experience_type`.
- 279 unit tests across all new modules.

### Changed
- `WORKING_LOGIC.md` — tier system updated from 4 tiers (A/B/C/D) to 3 tiers (1/2/3) + not-listed=0.50.
- `CURRENT_PROGRESS.md` — all foundation modules and scoring modes marked ✅.
- `MODEL_REGISTRY.md` — registered all new modules (header normalization, section-routed retrieval, rubric templates, rubric scorer, unified scorer, tier databases, structured profile).
- `PROMPT_LIBRARY.md` — RUBRIC-SCORE-001 marked Active (v1.0).

### Decision
- **Two-mode scoring engine implemented.** Code-only mode scores education, certification, and location using tier databases and structured profiles (no LLM). Rubric-bound LLM mode scores skill depth, experience, leadership, projects, languages, and communication quality using anchored rubric scales (LLM never sees weight or computes aggregation).
- **Section-Routed Evidence Retrieval replaces cosine for per-candidate scoring.** Dense cosine remains only for cross-candidate pool search and resume chat.
- **Tier databases are recruiter-editable JSON files.** Not-listed institutes/certs default to 0.50 (same as Tier 3) unless evidence places them in Tier 1 or Tier 2.

---

## 2026-06-19 (PM) — Doc alignment sweep (WORKING_LOGIC.md as canonical)

### Added
- `docs/CURRENT_PROGRESS.md` — single status doc mapping every step of `WORKING_LOGIC.md` to ✅ / 🟡 / ⬜.
- `docs/WORKING_LOGIC.md` is now the canonical scoring/evaluation spec (DEC-011). All other docs defer to it for scoring details.

### Changed
- `PROJECT_OVERVIEW.md` — added JD clarification loop (Green / Yellow / Red), per-item `expected_years`, single canonical scorer, RAG-as-explanation flow.
- `SYSTEM_ARCHITECTURE.md` — Job Service now runs the clarification loop; Scoring Engine is the single canonical scorer; RAG Engine is explanation-only.
- `AI_ARCHITECTURE.md` — §3 (JD processing) now includes the clarification classifier; §5 (Candidate Evaluation) rewritten around the single canonical scorer; legacy triad marked retired.
- `RECRUITER_WORKFLOWS.md` — Workflow 2 now includes Green/Yellow/Red classification; Workflow 3 includes `expected_years`; Workflow 5 includes resume cleaning; Workflow 6 includes the years-proportional scoring rule.
- `EVALUATION.md` — added per-item scoring evaluation metrics (Skill Presence Precision/Recall, Years Detection MAE, Per-item Score Accuracy, Evidence Section Precision, Snippet Faithfulness, Score Reproducibility).
- `PROMPT_LIBRARY.md` — added SCORE-EXPLAIN-001 and CANDIDATE-COMPARE-001 prompt specs; marked RESUME-CHAT-001 as Active.
- `IMPLEMENTATION_ROADMAP.md` — added Phase 4.5 (clarification loop + quality tiers + Candidate Intelligence Report); updated Phase 6 to reflect the mostly-built RAG pieces.
- `DECISIONS.md` — added DEC-010 (single canonical scorer) and DEC-011 (WORKING_LOGIC.md is canonical); superseded DEC-008.

### Decision
- **WORKING_LOGIC.md is the canonical scoring/evaluation spec.** All other docs defer to it for scoring details. `CURRENT_PROGRESS.md` is the single status doc.

---

## 2026-06-19 (PM) — Phase 4 scorer consolidation

### Added
- Single canonical scorer (`src/scoring/graded_scorer.py`) that satisfies `docs/WORKING_LOGIC.md`.
- Per-item scoring rule: `min(importance, candidate_years / expected_years × importance)` with `importance × 0.3` partial credit for mention-only matches.
- Structured-profile search priority: `experience.entries → skills → education.entries → certifications → projects → summary`.
- Summary-years fallback gated on item category (only non-Education / non-Certification items may use it).
- CLI (`scripts/evaluate_one.py`) prints the recruiter-facing report in the exact format from `docs/PROJECT_OVERVIEW.md` Phase 4.
- Batch CLI (`python -m src.scoring.batch_score`) writes ranked output to `data/scores/graded/<role>_ranked.json`.
- `scripts/compare_scores.py` shows the canonical ranked table + per-candidate top strengths and gaps.

### Removed
- `src/scoring/keyword_scorer.py`
- `src/scoring/semantic_scorer.py`
- `src/scoring/hybrid_scorer.py`
- `src/scoring/evidence.py`
- `src/scoring/evaluate.py` (re-export shim)
- `data/scores/keyword/`, `data/scores/semantic/`, `data/scores/hybrid/`
- `data/scores/BusinessAnalyst_ranked.json` (orphan)
- `tests/unit/test_hybrid_scorer.py`
- `tests/unit/test_semantic_scorer.py`
- `tests/unit/test_scoring.py`

### Changed
- Candidate scoring is no longer a triad of `keyword / semantic / hybrid` modules; those are deprecated and removed. The new `graded_scorer` is the single ranking signal.
- Total normalized to 0-100 using the config's `scale_factor = 100 / max_score`.
- `scripts/compare_two.py` reads from `data/scores/graded/`, surfaces per-item evidence, and accepts `--strategy graded` as the canonical choice (legacy strategy names print a deprecation warning and forward to graded).
- `scripts/demo_scoring.py` shows the canonical per-item breakdown for the top-ranked candidate.

### Decision
- **Single deterministic scorer** — `WORKING_LOGIC.md` is explicit: *"you don't need so many different scoring or ranking systems, just one is enough."* Per-component breakdowns still come from the structured profile, not from running multiple scorers.
- **RAG is reserved for explanations and resume chat** — never for ranking. The scorer itself is deterministic and offline.

---

## 2026-06-19 (PM) — Phase 5

### Added
- Candidate comparison engine (`scripts/compare_two.py`) for side-by-side recruiter-friendly candidate analysis.
  - Loads scored candidate profiles from `data/processed/<role>/<id>.json`.
  - Retrieves canonical graded scores from `data/scores/graded/<role>_ranked.json`.
  - Generates deterministic "Why A ranked above B" narratives using score deltas and component breakdowns.
  - Displays component-level evidence: matched requirement counts, top strengths by category.
- Integration tests for comparison workflow (`tests/integration/test_candidate_comparison.py`, 6 tests passing).
- Evidence-based ranking explanations (no LLM black-box scoring, LLM reserved for future explanation enhancement).

### Changed
- Comparison output format: side-by-side table with normalized scores, score deltas, component breakdowns.
- Phase 5 completes the candidate ranking & comparison pillar of the end-to-end workflow.

### Decision
- **No LLM in scoring chain (Phase 5)** — Explanations are deterministic and auditable. LLM integration deferred to Phase 6+ for enhanced summaries.
- **Candidate ID resolution** — Script auto-resolves user input (file stem or candidate_id) to internal identifiers by searching scores and profiles.

---

## 2026-06-19

### Added
- Established modular service-oriented architecture in `SYSTEM_ARCHITECTURE.md`.
- Established AI workflow architecture in `AI_ARCHITECTURE.md`.
- Established AI design rationale for chunking, embeddings, vector database, LLM usage, scoring, retrieval, RAG grounding, and evaluation.
- Added required governance docs for decisions, model registry, prompt library, evaluation, recruiter workflows, release notes, troubleshooting, and environment notes.
- Added production package foundation under `src/hireintel_ai/` with application entry points, shared config, schemas, ingestion, JD, resume, scoring, ranking, RAG, LLM, storage, and evaluation modules.
- Added test foundation under `tests/unit/`, `tests/integration/`, and `tests/fixtures/`.

### Changed
- Updated `AGENTS.md` architecture compliance references from missing legacy files to current source-of-truth docs.
- Updated the implementation roadmap to include production code foundation before feature implementation.
- Standardized the public product and production package naming on `HireIntel AI` / `hireintel_ai`.

### Risks
- The workspace folder is still named `talentlens_ai`, but product-facing docs and production package names now use `HireIntel AI` / `hireintel_ai`.
