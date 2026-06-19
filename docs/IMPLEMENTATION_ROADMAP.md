# Implementation Roadmap

## Overview
This roadmap defines the step-by-step execution plan for HireIntel AI, aligned with `AGENTS.md` and `docs/PROJECT_OVERVIEW.md`.

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

## Phase 4: Candidate Evaluation Engine ✅ Shipped 2026-06-19
1. Implement deterministic scoring
   - Use recruiter weights + structured profiles. ✅ (`keyword_scorer.py`)
2. Produce evidence-backed scoring
   - Score value ✅
   - Supporting evidence ✅ (chunk_id, snippet, source_file)
   - Resume source snippets ✅
3. Avoid black-box ranking
   - LLMs support extraction/summarization only. ✅ (LLM not in scoring loop)
   - Final scores must be auditable and reproducible. ✅

**Three independent scoring strategies shipped:**

| Strategy | Output folder | Purpose |
|---|---|---|
| Keyword | `data/scores/keyword/` | Hard requirements, audit-first |
| Semantic | `data/scores/semantic/` | Synonyms + paraphrases (cosine vs candidate's chunks) |
| Hybrid | `data/scores/hybrid/` | Default — `α × keyword + (1-α) × semantic`, α = 0.5 |

**Comparison view:** `scripts/compare_scores.py --role <Role> --top 10` shows rank deltas across strategies.

---

## Phase 5: Candidate Ranking & Comparison ✅ Shipped 2026-06-19
1. Build candidate comparison engine
   - Load two candidates' profiles and scores ✅
   - Diff the two side by side ✅ (matched components, top strengths)
   - Generate recruiter-friendly "Why A ranked above B" narrative ✅
2. Produce determinis side-by-side comparison tables
   - Score values ✅
   - Matched requirement counts ✅
   - Component breakdowns ✅
3. Avoid LLM-driven final rankings (LLM supports explanation only)
   - Scores computed by deterministic engine ✅

**Artifacts:**
- `scripts/compare_two.py` — CLI: `python scripts/compare_two.py --candidate-a <id_a> --candidate-b <id_b> --role <R> --strategy hybrid`
- `tests/integration/test_candidate_comparison.py` — 6 integration tests passing.

**Example output:**
```
Hybrid Score:           58.39        vs 37.07
Matched Requirements:   10           vs 4
Top Strengths:          Requirements Gathering, Stakeholder Management, Process Mapping
Why A ranked above B:   [SCORE] BUSINESS ANALYST RESUME ranked HIGHER by 21.3 points.
                        [MATCH] Matched 10 requirements vs 4 for John Wood.
```

---

## Phase 6: Resume Chat / RAG
1. Implement chunking strategy
   - Document-aware chunking by section.
   - Optional semantic chunking for large sections.
2. Build embedding and retrieval pipeline
   - Select embedding model and vector store.
   - Document decisions in `AI_DESIGN_RATIONALE.md` and `MODEL_REGISTRY.md`.
3. Ensure grounded conversational answers
   - Cite retrieved resume content.
   - If missing, respond with: “Information not found in candidate documents.”

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
1. Define documentation and architecture
2. Establish production package structure, configuration, schemas, and test layout
3. Build JD extraction
4. Build weight configuration
5. Build resume parsing
6. Build scoring engine
7. Build ranking/comparison
8. Add retrieval, then grounded RAG/chat
9. Evaluate, harden, deploy, and document
