# Architecture Changelog

## Overview

This document records architecture changes that affect system structure, runtime behavior, AI workflows, storage, APIs, or deployment.

---

## 2026-06-19 (PM) — Phase 5

### Added
- Candidate comparison engine (`scripts/compare_two.py`) for side-by-side recruiter-friendly candidate analysis.
  - Loads scored candidate profiles from `data/processed/<role>/<id>.json`.
  - Retrieves hybrid scores from `data/scores/hybrid/<role>_ranked.json`.
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
