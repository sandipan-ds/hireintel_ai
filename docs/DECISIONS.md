# Decisions

## Overview

This document records significant product, architecture, AI, data, and implementation decisions.

Every major architecture or AI change must be documented here before implementation, then reflected in the affected source-of-truth documents.

---

## Decision Log

| ID | Date | Decision | Status | Related Docs |
| --- | --- | --- | --- | --- |
| DEC-001 | 2026-06-19 | Use documentation-first development with `docs/` as source of truth. | Accepted | `AGENTS.md`, `PROJECT_OVERVIEW.md` |
| DEC-002 | 2026-06-19 | Use deterministic scoring for final candidate scores and rankings. | Accepted | `AI_ARCHITECTURE.md`, `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md` |
| DEC-003 | 2026-06-19 | Use document-aware chunking as the primary resume chunking strategy. | Accepted | `AI_ARCHITECTURE.md`, `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md` |
| DEC-004 | 2026-06-19 | Use Qdrant as the proposed vector database. | Superseded | `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md` |
| DEC-005 | 2026-06-19 | Use BGE-M3 as the proposed primary embedding model. | Superseded | `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md` |
| DEC-006 | 2026-06-19 | Use an in-memory numpy vector index until scale demands a hosted vector DB. | Accepted | `MODEL_REGISTRY.md`, `AI_ARCHITECTURE.md` |
| DEC-007 | 2026-06-19 | Use `sentence-transformers/all-MiniLM-L6-v2` as the active embedding model (CPU-runnable, no API key, PII-safe). | Accepted | `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md` |
| DEC-008 | 2026-06-19 | Ship three independent scoring strategies (keyword, semantic, hybrid) runnable side by side; default production strategy is hybrid with `α = 0.5`. | Superseded | `AI_ARCHITECTURE.md`, `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md` |
| DEC-009 | 2026-06-19 | Use `pypdfium2` (no Poppler required) as the primary OCR fallback renderer for image-only PDFs. | Accepted | `AI_ARCHITECTURE.md`, `MODEL_REGISTRY.md` |
| DEC-010 | 2026-06-19 | Ship a **single canonical deterministic scorer** (`src/scoring/graded_scorer.py`) in two modes (code-only + rubric-bound LLM evidence scoring); retire the keyword / semantic / hybrid triad. Code-only: per-item `min(importance, candidate_years / expected_years × importance)` with partial credit. Rubric-bound LLM: scores against recruiter-defined rubric, weight application in code. | Accepted | `WORKING_LOGIC.md`, `AI_DESIGN_RATIONALE.md`, `AI_ARCHITECTURE.md`, `MODEL_REGISTRY.md` |
| DEC-011 | 2026-06-19 | Make `WORKING_LOGIC.md` the canonical scoring/evaluation spec; all other docs defer to it for scoring details. | Accepted | `WORKING_LOGIC.md`, `CURRENT_PROGRESS.md`, all docs |
| DEC-012 | 2026-06-30 | Use Section-Routed Evidence Retrieval (exact label match on canonical sections) for per-candidate scoring, replacing cosine similarity. Dense cosine remains only for cross-candidate pool search and resume chat. | Accepted | `AI_ARCHITECTURE.md`, `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md`, `WORKING_LOGIC.md` |
| DEC-013 | 2026-06-30 | Ship recruiter-editable tier databases for institutes and certifications. 3 tiers (1.0/0.75/0.50) + not-listed default 0.50. Code-only lookup, no LLM, no web search at scoring time. | Accepted | `WORKING_LOGIC.md`, `MODEL_REGISTRY.md`, `AI_ARCHITECTURE.md` |

---

## Decision Template

```text
## DEC-XXX: Title

Date:
Status:

Context:

Decision:

Alternatives Considered:

Consequences:

Related Documents:
```

---

## DEC-006: In-memory numpy vector index (defer Qdrant)

**Date:** 2026-06-19
**Status:** Accepted

**Context:** We needed a vector store for ~4k chunks to enable retrieval for both JD matching and semantic scoring. `Qdrant` was previously proposed but introduces a separate service to deploy, monitor, and secure.

**Decision:** Persist chunk vectors to `data/embeddings/index.npz` (compressed numpy). Load on first retrieval. Keep Qdrant as the planned upgrade when scale exceeds single-machine memory or we need hosted multi-user concurrency.

**Alternatives Considered:**
- **Qdrant:** Best long-term option, but operational overhead before we have users.
- **ChromaDB:** Lighter than Qdrant but still a service.
- **FAISS:** Fast but poor metadata filtering.

**Consequences:**
- Zero infra dependencies to run locally / on a single machine.
- 6 MB on disk for 4k chunks × 384 dims; trivial to load.
- Trivial to swap to Qdrant later — `src/rag/index.py.VectorIndex` is the only abstraction to replace.

**Related Documents:** `MODEL_REGISTRY.md`, `AI_ARCHITECTURE.md`

---

## DEC-007: MiniLM-L6-v2 as primary embedding model (defer BGE-M3)

**Date:** 2026-06-19
**Status:** Accepted

**Context:** BGE-M3 was previously proposed. After scoping the v1 system to English-only JDs and resumes with ~4k chunks, we evaluated latency, cost, and PII constraints.

**Decision:** Use `sentence-transformers/all-MiniLM-L6-v2` (384-dim, ~80 MB, CPU-runnable, no API key) as the active embedding model. Keep BGE-M3 as the planned upgrade path for multilingual candidates.

**Alternatives Considered:**
- **BGE-M3:** Multilingual, larger model.
- **OpenAI `text-embedding-3-small`:** Highest quality, but per-token API cost and PII egress.
- **E5 / Nomic:** Comparable to MiniLM but with weaker English retrieval.

**Consequences:**
- Fully offline, no API key, no candidate data egress — strong PII story.
- One embedding call per (JD bullet × candidate) at scoring time → fast enough for our scale.
- Model swap is isolated to `src/rag/embeddings.DEFAULT_MODEL_NAME`.

**Related Documents:** `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md`

---

## DEC-008: Three scoring strategies (keyword, semantic, hybrid) with `α = 0.5` default

**Date:** 2026-06-19
**Status:** Superseded by DEC-010

**Context:** Keyword-only scoring is fast and auditable but misses synonyms. LLM-direct ranking is prohibited by `AGENTS.md`. We needed a way to add synonym awareness without giving up explainability or reproducibility.

**Decision (original):** Ship three independent scorers, each writing to its own output folder:
- `keyword_scorer.py` — deterministic binary match against recruiter weights.
- `semantic_scorer.py` — JD-bullet cosine vs candidate's chunks (mean × 100).
- `hybrid_scorer.py` — `α × keyword + (1-α) × semantic`, default `α = 0.5`.

**Superseded by DEC-010:** the canonical scorer (`graded_scorer.py`) replaces
the triad. The legacy modules were removed 2026-06-19; the CLI accepts the
legacy strategy names only as deprecated aliases.

**Related Documents:** `AI_ARCHITECTURE.md`, `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md`

---

## DEC-009: pypdfium2 as primary OCR fallback renderer

**Date:** 2026-06-19
**Status:** Accepted

**Context:** Image-only PDFs in `data/original/WebDesigning/` failed to extract text via `pdfplumber`. OCR fallback via `pdf2image` requires Poppler to be installed on the host — fragile for local dev.

**Decision:** Use `pypdfium2` (which bundles PDFium) as the primary PDF→image renderer for the OCR fallback. Keep `pdf2image` as a secondary fallback when `pypdfium2` is unavailable.

**Alternatives Considered:**
- `pdf2image` only (requires Poppler install).
- `PyMuPDF` (mupdf-based; similar trade-offs to pdfium but heavier dependency).

**Consequences:**
- Zero host-system dependencies for OCR fallback in most cases.
- Same `pytesseract` text extraction layer regardless of renderer.
- Documented in `src/resume_parsing/ocr.py`.

**Related Documents:** `AI_ARCHITECTURE.md`, `MODEL_REGISTRY.md`

---

## DEC-010: Single canonical deterministic scorer (`graded_scorer.py`)

**Date:** 2026-06-19
**Status:** Accepted

**Context:** `WORKING_LOGIC.md` is explicit: *"you don't need so many different scoring or ranking systems, just one is enough."* The legacy keyword / semantic / hybrid triad produced three non-comparable numbers and made recruiter interpretation harder, not easier. We also needed years-proportional scoring (a candidate with 1 year of Power BI should not score the same as one with 6 years), which the binary keyword scorer couldn't express.

**Decision:** Ship one deterministic scorer (`src/scoring/graded_scorer.py`) that operates in **two modes** per `WORKING_LOGIC.md` ("Fundamental Rule"):

1. **Code-only scoring** — for fully measurable requirements (total experience, skill presence + years, degree match, certification match, institute/cert tier lookups). Uses synonym dictionary + structured profile search + regex years detection. Per-item raw score = `min(importance, candidate_years / expected_years × importance)`, with `importance × 0.3` partial credit for mention-only matches. No LLM involved.

2. **Rubric-bound LLM evidence scoring** — for requirements requiring judgment (skill depth, relevant/same-role/leadership experience, project complexity, domain expertise). The LLM receives the full content of the mapped section(s) via Section-Routed Evidence Retrieval (exact label match, not similarity-ranked) and scores against a recruiter-defined rubric. The LLM does not see the weight and never computes the final weighted contribution.

In both modes:
- Weight application and final aggregation are computed in code, never by the LLM.
- Total normalized to 0–100 via `scale_factor = 100 / max_score` from the recruiter config.
- Per-item evidence is recorded: matched section, exact snippet, years detected, recruiter-readable reason.
- Rubric sub-scores and cited evidence are cached at scoring time for fast, consistent score explanations.

The legacy `keyword_scorer.py`, `semantic_scorer.py`, `hybrid_scorer.py` modules were removed. The CLI accepts `--strategy keyword|semantic|hybrid` only as a deprecated alias that prints a `DeprecationWarning` and forwards to `graded`.

**Alternatives Considered:**
- Keep the triad (rejected — spec says one scorer is enough).
- LLM-direct ranking (rejected by `AGENTS.md`).
- ML-trained ranker (deferred — see `AI_DESIGN_RATIONALE.md` §5 future upgrade path).
- Code-only scoring for everything (rejected — skill depth, relevant experience, and project complexity require genuine judgment that synonym+regex cannot provide).

**Consequences:**
- One canonical ranking signal per role; cross-role comparisons are direct.
- Per-item evidence is auditable from the candidate's own words.
- Years-proportional scoring rewards demonstrated depth, not just keyword presence.
- Summary-years fallback only applies to experience-style items, so credentials (BE/BTech, CBAP) aren't contaminated by total tenure.
- Rubric-bound LLM mode ensures judgment-based scoring is anchored to recruiter-defined rubrics, not LLM opinions.

**Related Documents:** `WORKING_LOGIC.md`, `AI_DESIGN_RATIONALE.md`, `AI_ARCHITECTURE.md`, `MODEL_REGISTRY.md`, `ARCHITECTURE_CHANGELOG.md`

---

## DEC-011: `WORKING_LOGIC.md` is the canonical scoring/evaluation spec

**Date:** 2026-06-19
**Status:** Accepted

**Context:** `PROJECT_OVERVIEW.md` and `WORKING_LOGIC.md` both describe scoring, but they drifted apart — `PROJECT_OVERVIEW.md` still referenced the legacy triad while `WORKING_LOGIC.md` was the source of truth for the single-scorer design. Recruiters and contributors reading the docs got conflicting answers.

**Decision:** `WORKING_LOGIC.md` is the canonical spec for scoring, evaluation, and ranking. All other docs (`PROJECT_OVERVIEW.md`, `SYSTEM_ARCHITECTURE.md`, `AI_ARCHITECTURE.md`, `RECRUITER_WORKFLOWS.md`, `EVALUATION.md`, etc.) defer to it for scoring details and link to it at the top. `CURRENT_PROGRESS.md` is the status snapshot ("what's done vs planned") mapped to every step of `WORKING_LOGIC.md`.

**Alternatives Considered:**
- Promote `PROJECT_OVERVIEW.md` to canonical (rejected — `WORKING_LOGIC.md` is more detailed and more recent).
- Merge both into a single doc (rejected — `WORKING_LOGIC.md` is the spec; `PROJECT_OVERVIEW.md` is the high-level product overview).

**Consequences:**
- One source of truth for scoring rules; no more drift.
- `CURRENT_PROGRESS.md` becomes the single status doc, replacing ad-hoc status notes scattered across the other docs.

**Related Documents:** `WORKING_LOGIC.md`, `CURRENT_PROGRESS.md`, all docs

---

## DEC-012: Section-Routed Evidence Retrieval for per-candidate scoring

**Date:** 2026-06-30
**Status:** Accepted

**Context:** The original design used dense cosine similarity to retrieve resume chunks for per-candidate scoring. This was the wrong tool: a single resume is a short document (1,000–3,000 tokens) that should be read, not searched. Cosine retrieval risks silently dropping relevant chunks (e.g. a second Python role falling below the top-K cutoff), and produces non-deterministic evidence depending on the embedding model's ranking.

`WORKING_LOGIC.md` ("Section-Routed Evidence Retrieval") specifies that each requirement should be mapped to canonical section(s) by a fixed table, and retrieval should be an exact label match — fetch every chunk tagged with the mapped section(s), never a ranked top-K subset.

**Decision:** Implement Section-Routed Evidence Retrieval (`src/rag/section_routed.py`) as the sole retrieval strategy for per-candidate scoring. Dense cosine retrieval remains only for:
- Cross-candidate pool search (JD ↔ resume triage via `jd_match.py`)
- Resume chat (RAG via `retriever.py`)

The fixed routing table maps requirement types to canonical sections:
- Skill → Experience + Projects + Skills
- Education → Education
- Certification → Certifications
- Experience → Experience
- etc.

For unusually long sections, deterministic metadata filtering (`skills_asserted contains "Python"`) narrows the content — still an exact filter, not a similarity rank.

**Alternatives Considered:**
- Keep cosine for per-candidate scoring (rejected — non-deterministic, risks silent chunk drops, wrong tool for a single short document).
- Hybrid: cosine + section routing (rejected — adds complexity without benefit; section routing is strictly better for per-candidate evidence).
- LLM decides which sections to read (rejected — the routing must be fixed and auditable, not a model decision).

**Consequences:**
- Same requirement against same resume always returns the same content — fully deterministic.
- No relevant chunk can be silently missed (no top-K cutoff).
- No embeddings or cosine needed for scoring — only for pool search and chat.
- Fields that belong together (institute, branch, CGPA) can never be split across retrieval calls.

**Related Documents:** `AI_ARCHITECTURE.md`, `AI_DESIGN_RATIONALE.md`, `MODEL_REGISTRY.md`, `WORKING_LOGIC.md`

---

## DEC-013: Recruiter-editable tier databases for institutes and certifications

**Date:** 2026-06-30
**Status:** Accepted

**Context:** `WORKING_LOGIC.md` ("Institute and Certification Tier Lookup") requires the platform to maintain a recruiter-editable tier database for institutions and certification providers. The original spec defined 4 tiers (A/B/C/D) with 100%/80%/60%/40% point multipliers. The user requested a simpler 3-tier system with a 0.50 default for unlisted institutes/certs (same as Tier 3), since verifying whether an unknown institute is legitimate would require either a database or a web search — and web search at scoring time introduces non-determinism.

**Decision:** Ship two recruiter-editable JSON tier databases:

1. `data/Institutes/institute_tiers.json` — 115 Tier 1 (1.0), 54 Tier 2 (0.75), 155 Tier 3 (0.50), not-listed (0.50). Sources: Wikipedia "List of state universities in India" (459 state universities), Wikipedia "List of deemed universities" (124 deemed universities), world top 100 universities.

2. `data/Certificates/certificate_tiers.json` — 115 Tier 1 (1.0), 45 Tier 2 (0.75), 10 Tier 3 (0.50), not-listed (0.50). Sources: Wikipedia "Professional certification", industry knowledge.

Scoring rules:
- Tier 1 → 1.0 × allotted points (premier/renowned)
- Tier 2 → 0.75 × allotted points (recognized/second-grade)
- Tier 3 → 0.50 × allotted points (regional/local)
- Not listed → 0.50 × allotted points (same as Tier 3 — innocent until proven guilty)

Lookup is code-only (`src/scoring/tier_lookup.py`) with word-boundary regex matching. No LLM, no web search at scoring time. Web search may be used only to enrich the tier databases offline.

**Alternatives Considered:**
- 4 tiers (A/B/C/D) per original WORKING_LOGIC.md (rejected — user requested 3 tiers for simplicity).
- Not-listed = 0.0 (rejected — penalizes legitimate but unlisted institutes; user requested 0.50 default).
- Not-listed = 0.25 (rejected — user changed to 0.50 after further consideration).
- LLM classifies institute tier at scoring time (rejected — non-deterministic, violates code-only principle).
- Web search at scoring time (rejected — non-deterministic, adds latency, PII concern).

**Consequences:**
- Fully deterministic tier lookup — same institute always gets the same tier.
- Recruiter can edit JSON files to move institutes/certs between tiers or add new ones.
- Unlisted institutes get 0.50 (same as Tier 3) — no penalty for being unrecognized.
- `reload_tier_databases()` clears the `lru_cache` after edits.

**Related Documents:** `WORKING_LOGIC.md`, `MODEL_REGISTRY.md`, `AI_ARCHITECTURE.md`
