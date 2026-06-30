# Implementation Roadmap

## Overview
This roadmap defines the step-by-step execution plan for HireIntel AI, aligned
with `AGENTS.md`, `docs/PROJECT_OVERVIEW.md`, and the canonical scoring spec
[`docs/WORKING_LOGIC.md`](WORKING_LOGIC.md). For "what is implemented today vs
what's planned", see [`docs/CURRENT_PROGRESS.md`](CURRENT_PROGRESS.md).

---

## Phase 0: Foundation & alignment
1. Confirm repository structure
   - Ensure `/docs` exists and contains required docs.
   - Treat `/docs` as source of truth.
2. Establish documentation process
   - Keep `PROJECT_OVERVIEW.md`, `SYSTEM_ARCHITECTURE.md`, `AI_ARCHITECTURE.md`, `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md`, `PROMPT_LIBRARY.md`, `EVALUATION.md`, `RECRUITER_WORKFLOWS.md`, and `RELEASE_NOTES.md` synchronized with implementation.
3. Establish production code foundation
   - Use `src/hireintel_ai/` as the production package.
   - Keep application entry points under `src/hireintel_ai/app/`.
   - Keep shared configuration under `src/hireintel_ai/core/`.
   - Keep shared typed contracts under `src/hireintel_ai/schemas/`.
   - Keep tests under `tests/unit/`, `tests/integration/`, and `tests/fixtures/`.

---

## Phase 1: Job Description Intelligence
1. Build JD ingestion
   - Support PDF, DOCX, Text input.
2. Extract requirements
   - Required/Preferred skills
   - Experience
   - Education
   - Certifications
   - Industry experience
   - Leadership requirements
   - Technology stack
3. Store structured JD output
   - Use as hiring policy input for scoring and matching.

---

## Phase 2: Recruiter Weight Configuration
1. Create recruiter-configurable scoring policy
   - Support weights for skills and categories.
2. Ensure explicit policy
   - Recruiters assign points.
   - Policy becomes deterministic evaluation rules.

---

## Phase 3: Resume Parsing ✅ Shipped 2026-06-19
1. Build resume ingestion and normalization
   - Support formats in `data/original`. ✅ (PDF + TXT)
   - Use parsing + OCR if needed. ✅ (`pdfplumber` → `pypdfium2` OCR → `pdf2image` fallback)
2. Extract structured candidate profiles
   - Name, contact, education, skills, certifications, languages, experience, projects, technologies, leadership indicators. ✅
3. Capture evidence
   - Link each extracted field to source resume text for explainability. ✅ (`raw_text` + `sections[].start/end` char spans; `candidate_id` SHA1 of source path)

**Artifacts:**
- 721 profile JSONs in `data/processed/<role>/`.
- `src/resume_parsing/{parser, ocr, batch_parse}.py`.
- `tests/unit/test_resume_parser.py` — passing.

---

## Phase 4: Candidate Evaluation Engine ✅ Shipped 2026-06-19 (Mode 1) + 2026-06-30 (Mode 2)

Per `WORKING_LOGIC.md` "Fundamental Rule": the platform ships **one**
deterministic scorer operating in **two modes**:

* **Code-only** — for fully measurable requirements (total experience, degree
  match, institute tier, cert match, provider tier, location). No LLM.
* **Rubric-bound LLM** — for requirements requiring judgment (skill depth,
  relevant experience, leadership, project complexity, language proficiency,
  communication quality). LLM scores against anchored rubric scales; weight
  application and aggregation in code.

1. Implement deterministic scoring (Mode 1)
   - Use recruiter weights + `expected_years` + structured profiles. ✅ (`graded_scorer.py`)
   - Per-item `min(importance, candidate_years / expected_years × importance)`. ✅
2. Implement rubric-bound LLM evidence scoring (Mode 2)
   - 12 rubric templates with anchored scales (0.0/0.25/0.5/0.75/1.0). ✅ (`rubrics.py`)
   - RUBRIC-SCORE-001 prompt: LLM extracts evidence, scores against rubric. ✅ (`rubric_scorer.py`)
   - LLM never sees weight, never computes aggregation. ✅
   - Cached scoring trace frozen at scoring time. ✅ (`CachedScoringTrace`)
3. Implement unified scoring engine
   - Routes each requirement to code-only or rubric-bound LLM. ✅ (`unified_scorer.py`)
   - Both modes feed same weight × sub-score aggregation. ✅
   - Produces `UnifiedCandidateEvaluation` with per-item scoring traces. ✅
4. Produce evidence-backed scoring
   - Score value ✅
   - Supporting evidence ✅ (matched section, snippet, cited text, anchor description)
   - Resume source snippets ✅
   - Cached sub-scores + cited evidence ✅
5. Avoid black-box ranking
   - LLMs support scoring against fixed rubrics only — never final ranking. ✅
   - Final scores must be auditable and reproducible. ✅
   - Score explanation reads from cached trace — no re-scoring. ✅ (`explain_score_from_cache`)

**Scoring modules:**

| File | Purpose |
|---|---|
| `src/scoring/graded_scorer.py` | Mode 1: code-only synonym + regex + years-proportional scoring |
| `src/scoring/rubrics.py` | 12 rubric templates with anchored scales, sub-questions, formulas |
| `src/scoring/rubric_scorer.py` | Mode 2: RUBRIC-SCORE-001 prompt, LLM judge, cached scoring trace |
| `src/scoring/unified_scorer.py` | Routes per dimension type; produces unified evaluation with traces |
| `src/scoring/tier_lookup.py` | Code-only institute + certificate tier lookup from JSON databases |

**Legacy triad (`keyword` / `semantic` / `hybrid`) retired 2026-06-19.** Passing
the legacy strategy names to `batch_score` / `compare_two` prints a
deprecation warning and forwards to `graded`.

**Batch CLI:** `python -m src.scoring.batch_score --role <Role>` → `data/scores/graded/<Role>_ranked.json` (ranked, 0-100 normalized, per-item evidence included).
**Per-candidate report:** `python scripts/evaluate_one.py --candidate <id> --role <Role>`.
**Comparison view:** `python scripts/compare_scores.py --role <Role> --top 10` shows the canonical graded ranking + per-candidate strengths and gaps.

---

## Phase 4.5: Clarification Loop + Pipeline Rewiring ⬜ Planned

The foundation modules (Header Normalization, Chunk Metadata, Structured
Profile, Section-Routed Retrieval, Rubric Templates, Tier Databases) are
shipped as standalone modules (Phase 4.6). This phase wires them into the
batch pipeline and builds the remaining recruiter-facing features.

1. **Re-parse all resumes with Header Normalization**
   - Produce new `data/processed/` with canonical section labels.
   - Produce `data/processed/<role>/<id>_structured_profile.json`.
2. **Re-chunk with updated chunker**
   - Produce new `data/chunks/` with full metadata schema.
3. **Wire `unified_scorer` into batch pipeline**
   - Replace `graded_scorer` call in `batch_score.py` with `unified_scorer.evaluate_candidate_unified`.
   - Pass chunks + structured profile + LLM caller.
   - Output includes scoring traces per item.
4. **JD clarification loop** (Green / Yellow / Red)
   - Auto-classify each extracted requirement.
   - Auto-generate follow-up questions for Yellow items.
   - Hard-block the scoring policy until all items are Green.
   - Persist `clarifications.json` next to the role's weight config.
5. **Per-item `expected_years` in the recruiter UI**
   - Surface as a per-item field next to `importance`.
6. **Resume cleaning pipeline**
   - Dedicated step between "raw text" and "structured profile" that strips headers, footers, template noise, decorative elements, and duplicate content.
7. **Candidate Intelligence Report artifact**
   - Aggregate unified scorer per-item evidence + scoring traces into a single `data/processed/<role>/<id>_intelligence_report.json`.
8. **Score explanation UI**
   - Wire `explain_score_from_cache` into the recruiter UI for per-item score explanations.

---

## Phase 5: Candidate Ranking & Comparison ✅ Shipped 2026-06-19

*Note: Phase 4.6 below documents the foundation modules shipped 2026-06-30
that the scoring engine depends on. It is placed after Phase 4.5 because the
modules are built but not yet wired into the batch pipeline.*

---

## Phase 4.6: Scoring Foundation Modules ✅ Shipped 2026-06-30

Standalone modules implementing the two-mode scoring architecture from
`WORKING_LOGIC.md`. These are built and unit-tested (279 tests) but not yet
wired into the batch pipeline (that is Phase 4.5).

1. **Header Normalization** ✅
   - `src/resume_parsing/header_normalization.py`
   - Layer 1: synonym lookup table → 7 canonical sections
   - Layer 2: LLM fallback classification for unmatched headers
2. **Chunk Metadata Schema** ✅
   - `src/rag/chunker.py` (updated)
   - `section_type`, `parent_structure`, `temporal_context` with `calculated_duration_months`
   - `skills_asserted`, `experience_type` (professional/personal_project/academic)
   - Deterministic date parsing in code, never by LLM
3. **Structured Candidate Profile** ✅
   - `src/resume_parsing/structured_profile.py`
   - Degrees + institutions, certifications, total experience (no double-count), companies, roles
   - Separate deterministic record, no LLM, no retrieval
4. **Section-Routed Evidence Retrieval** ✅
   - `src/rag/section_routed.py`
   - Fixed requirement→section mapping table (not a model decision)
   - Exact label match — no embeddings, no cosine, no top-K
   - Metadata filtering for long sections
5. **Rubric Templates** ✅
   - `src/scoring/rubrics.py`
   - 12 templates: skill, experience, leadership, same_role, domain, education, certification, project, language, location, communication, resume_organization
   - Anchored scales (0.0/0.25/0.5/0.75/1.0) with explicit descriptions
   - Code-only vs rubric-bound LLM classification
6. **Rubric-Bound LLM Scorer** ✅
   - `src/scoring/rubric_scorer.py`
   - RUBRIC-SCORE-001 prompt (weight excluded, extract-before-score, anchored scales)
   - `CachedScoringTrace` frozen at scoring time
   - `explain_score_from_cache` narrates trace without re-scoring
7. **Unified Scorer** ✅
   - `src/scoring/unified_scorer.py`
   - Routes each requirement to code-only or rubric-bound LLM
   - `UnifiedCandidateEvaluation` with per-item `scoring_mode` + `scoring_trace`
8. **Tier Databases** ✅
   - `src/scoring/tier_lookup.py` + `data/Institutes/institute_tiers.json` + `data/Certificates/certificate_tiers.json`
   - 3 tiers (1.0/0.75/0.50) + not-listed (0.50)
   - Recruiter-editable JSON, word-boundary matching

---

## Phase 5: Candidate Ranking & Comparison ✅ Shipped 2026-06-19
1. Build candidate comparison engine
   - Load two candidates' profiles and scores ✅
   - Diff the two side by side ✅ (matched components, top strengths)
   - Generate recruiter-friendly "Why A ranked above B" narrative ✅
2. Produce deterministic side-by-side comparison tables
   - Score values ✅
   - Matched requirement counts ✅
   - Component breakdowns ✅
3. Avoid LLM-driven final rankings (LLM supports explanation only)
   - Scores computed by deterministic engine ✅

**Artifacts:**
- `scripts/compare_two.py` — CLI: `python scripts/compare_two.py --candidate-a <id_a> --candidate-b <id_b> --role <R>`
- `tests/integration/test_candidate_comparison.py` — 6 integration tests passing.

**Example output:**
```
Score:                   58.39        vs 37.07
Matched Requirements:   10           vs 4
Top Strengths:          Requirements Gathering, Stakeholder Management, Process Mapping
Why A ranked above B:   [SCORE] BUSINESS ANALYST RESUME ranked HIGHER by 21.3 points.
                        [MATCH] Matched 10 requirements vs 4 for John Wood.
```

---

## Phase 6: Resume Chat / RAG 🟡 Mostly built, CLI pending
1. Implement chunking strategy
   - Document-aware chunking by section. ✅ (`src/rag/chunker.py`)
   - Header Normalization with 7 canonical sections. ✅ (`src/resume_parsing/header_normalization.py`)
   - Chunk metadata schema with `calculated_duration_months`, `experience_type`, `skills_asserted`. ✅
2. Build embedding and retrieval pipeline
   - Embedding model: `sentence-transformers/all-MiniLM-L6-v2` ✅
   - Vector store: in-memory numpy (`data/embeddings/index.npz`) ✅
   - Cosine retrieval (pool-level only): ✅
   - Section-Routed Evidence Retrieval (per-candidate scoring): ✅ (`src/rag/section_routed.py`)
   - Documented in `AI_DESIGN_RATIONALE.md` and `MODEL_REGISTRY.md`. ✅
3. Build recruiter-facing chat CLI
   - `scripts/resume_chat.py --candidate <id> --question "..." --role <Role>` — CLI. ⬜
   - Streamlit chat UI. ⬜
4. Ensure grounded conversational answers
   - LLM service via OpenRouter (`src/hireintel_ai/llm/service.py`) ✅
   - Strict-grounding prompt (see `docs/PROMPT_LIBRARY.md` RESUME-CHAT-001). ⬜ (prompt spec exists; not implemented in code)
   - "Information not found in candidate documents." fallback. ⬜ (string appears only in docs; not in any `.py` file)
   - Cite retrieved resume content. ⬜ (citation pattern planned; recruiter UI not yet built)
5. Score explanation from cached trace
   - `explain_score_from_cache` reads frozen trace. ✅ (`src/scoring/rubric_scorer.py`)
   - RAG follow-up for questions beyond cached trace. ⬜

---

## Phase 7: Evaluation & validation
1. Define metrics
   - Resume parsing: precision, recall, F1
   - Retrieval: Recall@K, Precision@K, MRR, nDCG
   - Generation: faithfulness, groundedness, relevancy
   - RAG: context recall, context precision
   - Ranking: Top-K accuracy, recruiter agreement
   - Hallucination: unsupported statements, hallucination rate
   - Business: screening efficiency, time saved, satisfaction
2. Validate and iterate
   - Measure performance
   - Refine parsing, retrieval, scoring

---

## Phase 8: Technology & deployment
1. Assemble stack
   - Backend: Python, FastAPI
   - Frontend: Streamlit
   - NLP: spaCy, NLTK, regex
   - LLM/embeddings: chosen models
   - Vector DB: chosen engine
2. Document implementation
   - Keep architecture and decision docs updated.
   - Add release notes for feature completion and bug fixes.

---

## Recommended execution order
1. Define documentation and architecture ✅
2. Establish production package structure, configuration, schemas, and test layout ✅
3. Build JD extraction + clarification loop (Phase 1) — clarification loop ⬜
4. Build weight configuration (weights + expected_years) (Phase 2) — expected_years UI ⬜
5. Build resume parsing + cleaning (Phase 3) — cleaning ⬜
6. Build scoring engine — Mode 1 code-only ✅ + Mode 2 rubric-bound LLM ✅ + unified scorer ✅ (Phases 4 + 4.6)
7. Build ranking/comparison (Phase 5) ✅
8. **Phase 4.5: re-parse with Header Normalization, re-chunk, wire unified scorer into batch pipeline, clarification loop, expected_years UI, resume cleaning, Candidate Intelligence Report, score explanation UI**
9. Add retrieval, then grounded RAG/chat (Phase 6) — chunking ✅, section-routed ✅, cosine ✅, chat CLI ⬜
10. Evaluate, harden, deploy, and document (Phases 7 + 8)
