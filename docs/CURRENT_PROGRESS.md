# Current Progress vs `WORKING_LOGIC.md`

This document maps every step of the canonical spec
[`WORKING_LOGIC.md`](WORKING_LOGIC.md) to its implementation status as of
2026-06-19. Use it as the single source of truth for "what's done vs what's
left" when planning the next session.

**Legend:** ✅ Shipped · 🟡 Partially shipped / scaffolded · ⬜ Planned

---

## Foundational Rules

| Spec rule | Status | Where |
|---|---|---|
| System is not a generic ATS / keyword matcher / RAG chatbot | ✅ | Architecture, scoring |
| Recruiter-controlled weights (0–10) | ✅ | `data/Job descriptions/<role>/<role>_WeightConfig_filled.json` |
| Recruiter-controlled `expected_years` per item | 🟡 | Default 10 in `graded_scorer.DEFAULT_EXPECTED_YEARS`; per-item field not yet exposed in UI |
| Weight normalization to 0–100 | ✅ | `scale_factor = 100 / max_score` in `src/scoring/graded_scorer.py` |
| Reproducible, auditable, explainable rankings | ✅ | `graded_scorer.evaluate_candidate` |
| LLM explains, never scores | ✅ | `src/hireintel_ai/llm/service.py`; `scripts/compare_two.py` |
| Ask for clarification, don't assume | ⬜ | No clarification loop yet |
| Document-Aware Chunking is the default | ✅ | `src/rag/chunker.py` |

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
| Recruiter weight assignment 0–10 | Done via form | ✅ | `src/ui/recruiter_weight_config.py` |
| Weight normalization to 100 | `scale_factor = 100 / max_score` | ✅ | `src/scoring/graded_scorer.py` |

---

## Resume Pipeline

| Step | Spec | Status | Where |
|---|---|---|---|
| Resume Upload (PDF, DOCX, text) | Multiple formats | ✅ | `src/resume_parsing/parser.py`, OCR fallback via `pypdfium2` |
| Resume Cleaning (headers, footers, templates, noise, duplicates) | Strip noise | 🟡 | Implicit via section parsing; no dedicated cleaning step |
| Document-Aware Chunking | One chunk per experience/education/project entry | ✅ | `src/rag/chunker.py` |
| Header Normalization | Synonym lookup + fallback classification → 7 canonical sections | ✅ | `src/resume_parsing/header_normalization.py` — Layer 1 synonym table + Layer 2 LLM fallback |
| Chunk Metadata Schema | `calculated_duration_months`, `experience_type`, `skills_asserted`, `parent_structure` | ✅ | `src/rag/chunker.py` — full schema implemented, dates parsed deterministically |
| Structured Candidate Profile Extraction | Deterministic extraction of degrees, certs, total exp, companies, dates | ✅ | `src/resume_parsing/structured_profile.py` — separate record, no double-counting of overlapping experience |
| Evidence Extraction | Linked to source text | ✅ | `char_span` in chunk records |
| Candidate Intelligence Report | Aggregated Skills + Experience + Education + Certs + Projects + Objective Scores + Evidence | ✅ | `scripts/phase45_pipeline.py` → `data/processed/<role>/<id>_intelligence_report.json` (721 reports generated across 8 roles) |

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
| Sort by deterministic total | ✅ | `batch_score._ranked_rows`; `scripts/phase45_pipeline.py` (721 candidates across 8 roles) |
| LLM never ranks | ✅ | Enforced by design |
| Cosine similarity is a supporting signal only | 🟡 | Vector index exists (`data/embeddings/index.npz`); recruiter-facing cosine match UI not built |

---

## Resume Chat

| Step | Status |
|---|---|
| Document-Aware Chunking for retrieval | ✅ |
| RAG-grounded answers | ⬜ (LLM service scaffolded; no resume-chat method implemented; `scripts/resume_chat.py` CLI not built) |
| Strict grounding prompt (no hallucination) | ⬜ (prompt spec exists in `PROMPT_LIBRARY.md` RESUME-CHAT-001; not implemented in code) |
| "Information not found in candidate documents." fallback | ⬜ (string appears only in docs; not in any `.py` file) |

---

## Candidate Comparison

| Step | Status | Where |
|---|---|---|
| Side-by-side comparison | ✅ | `scripts/compare_two.py` |
| Evidence-backed "Why A above B" | ✅ | Deterministic score deltas + component breakdown |
| LLM explanation grounded in retrieved content | 🟡 | `LlmService.explain_candidate_score` generates a comparison narrative when LLM is configured; not grounded in retrieved resume content (uses scorer output, not RAG) |

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

**Phase 4.5 status** — items 1–4 and 9 are ✅ shipped; the remaining items are:

5. Wire `explain_score_from_cache` into the recruiter UI for per-item score explanations.
6. Per-item `expected_years` field in weight-config (UI-exposed).
7. `clarifications.json` per role listing Green / Yellow / Red items and auto-generated questions.
8. Recruiter UI to answer questions before scoring policy is locked.

**Completed in this phase (2026-07-01):**
- 721 resumes parsed across 8 roles → `data/processed/<role>/<candidate_id>.json`
- 721 structured profiles extracted → `data/processed/<role>/<id>_structured_profile.json`
- 721 chunk files with full metadata schema → `data/chunks/<role>/<candidate_id>.jsonl`
- 8 ranked score files → `data/scores/graded/<role>_ranked.json`
- 721 candidate intelligence reports → `data/processed/<role>/<id>_intelligence_report.json`
- Pipeline script: `scripts/phase45_pipeline.py` (code-only mode; rubric-bound LLM mode pending LLM caller wiring)

**Recommended next unit of work:**
1. Wire the rubric-bound LLM scorer (`src/scoring/rubric_scorer.py`) into the pipeline so skill depth and relevant-experience scoring produce non-zero scores.
2. Build the JD clarification loop (Green/Yellow/Red classification → `clarifications.json`).
3. Expose per-item `expected_years` in the recruiter weight-config UI.

This unblocks **Phase 7 — Evaluation** (ground-truth the scorer against recruiter-confirmed expectations) and **Phase 8 — Deployment** (the UI has a complete data flow to wire up).

---

## How this doc relates to others

- `WORKING_LOGIC.md` is the **canonical spec** (the "what should it do").
- This doc is the **status snapshot** (the "what does it do today").
- `IMPLEMENTATION_ROADMAP.md` is the **execution plan** (the "what do we build next").
- `ARCHITECTURE_CHANGELOG.md` is the **history** (the "what changed and when").