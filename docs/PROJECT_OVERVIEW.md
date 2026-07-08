# HireIntel AI – Explainable Candidate Intelligence Platform

> **Source of truth for scoring, evaluation, and ranking:**
> [`WORKING_LOGIC.md`](WORKING_LOGIC.md). This document is the high-level
> product overview; details about how scoring works live in `WORKING_LOGIC.md`.
> For "what is implemented today vs what's planned", see
> [`CURRENT_PROGRESS.md`](CURRENT_PROGRESS.md).

## Project Overview

HireIntel AI is an AI-powered Candidate Intelligence Platform designed to help recruiters screen, evaluate, rank, compare, and interact with job applicants in a transparent and explainable manner.

Unlike traditional ATS systems that rely on keyword matching or black-box scoring, HireIntel AI allows recruiters to define their own hiring priorities and scoring weights — including the expected years of experience per requirement. The platform then evaluates candidates using evidence extracted from resumes, generates recruiter-friendly summaries, provides explainable rankings, and enables conversational exploration of candidate profiles through Retrieval-Augmented Generation (RAG) — with strict grounding so the LLM never invents candidate information.

The goal is to reduce recruiter workload, improve screening consistency, and provide transparent, evidence-based hiring recommendations.

---

# Problem Statement

Recruiters often review hundreds of resumes for a single position.

Current recruitment workflows suffer from:

* Manual resume screening
* Inconsistent candidate evaluation
* Black-box AI recommendations
* Limited transparency in candidate ranking
* Difficulty comparing multiple candidates
* Time-consuming resume reviews

HireIntel AI addresses these challenges by combining NLP, LLMs, Explainable AI, and RAG-based candidate intelligence.

---

# Key Differentiators

Unlike generic ATS systems and resume chatbots, HireIntel AI provides:

* Recruiter-controlled scoring policies
* Explainable candidate rankings
* Evidence-based candidate evaluation
* Deterministic scoring engine
* Resume-grounded AI reasoning
* Candidate comparison engine
* Conversational candidate intelligence
* Transparent hiring recommendations
* Multi-level AI evaluation framework

---

# End-to-End Workflow

```text
Job Description Upload
          │
          ▼
JD Validation & Clarification (Green / Yellow / Red)
          │
          ▼
Requirement Extraction
          │
          ▼
Recruiter Clarification (Yellow + Red items)
          │
          ▼
Recruiter Weight Configuration (weights + expected_years)
          │
          ▼
Resume Upload
          │
          ▼
Resume Cleaning + Parsing
          │
          ▼
Recursive Chunking + Embedding
          │
          ▼
Candidate Intelligence Report
          │
          ▼
Deterministic Scoring Engine (single canonical scorer)
          │
          ▼
Candidate Ranking
          │
          ▼
Candidate Summaries (LLM-narrated, evidence-grounded)
          │
          ▼
Candidate Comparison
          │
          ▼
Resume Chat (RAG)
          │
          ▼
Hiring Recommendations
```

The clarification loop is mandatory: the platform must not silently assume experience
durations, degree equivalencies, or certification providers when the JD is ambiguous.
See [`WORKING_LOGIC.md`](WORKING_LOGIC.md) for the full rules.

---

# Phase 1: Job Description Intelligence

## Objective

Understand hiring requirements before evaluating candidates — including asking for
clarification when the JD is ambiguous.

## Input

* Job Description (PDF, DOCX, Text)

## Information Extracted

* Required Skills
* Preferred Skills
* Required Experience (with **expected years** per skill)
* Education Requirements (with degree equivalencies)
* Certifications (with provider reputation)
* Industry Experience
* Leadership Requirements
* Technology Stack

## Clarification Loop (per `WORKING_LOGIC.md` Step 0)

Every requirement is classified **Green / Yellow / Red**:

* **Green** — Clear and measurable (e.g. "Python with 5+ years"). Enters the scoring policy directly.
* **Yellow** — Partially defined (e.g. "Strong Python Skills"). The platform must ask the recruiter a follow-up question before scoring.
* **Red** — Missing critical information (e.g. no experience duration). The platform must block the scoring policy until the recruiter clarifies.

Yellow and Red items produce a `clarifications.json` next to the role's weight
config listing the open questions. The scoring policy is locked only when all
items are Green.

## Example

```text
Required Skills:
HTML
CSS
JavaScript
React

Experience:
6+ Years

Education:
B.Tech

Preferred:
NIT / IIT
```

---

# Phase 2: Recruiter Weight Configuration

## Objective

Allow recruiters to define what matters most for a particular role — and to set
the expected years of experience per skill.

Instead of AI deciding candidate importance, recruiters assign weights.

## Weights + Expected Years

Each item in the recruiter's scoring policy carries:

* `name` — the criterion.
* `weight_percentage` — recruiter weight 0–100% (all percentages must sum to exactly 100%).
* `expected_years` — target years of experience for this item (configurable,
  default `10` when omitted).

The total candidate score is the sum of (weight_percentage × sub-score) for each requirement.

## Example

```text
Core Skills (Required):
├─ Business Analysis & Req Gathering    → 12%
├─ SQL                                  → 8%
├─ Process Mapping                      → 7%
├─ Stakeholder Management               → 10%
└─ Documentation & User Stories         → 8%
   Subtotal: 45%

Preferred Skills:
├─ BI Tools (Power BI, Tableau)         → 6%
├─ CRM/ERP/Data Warehouse               → 5%
├─ Agile & Scrum                        → 4%
└─ Product-Led / Digital Transformation → 3%
   Subtotal: 18%

Experience (Required):
├─ 6+ Years BA Experience               → 12%
├─ Leadership or Senior Analyst Role    → 8%
└─ Cross-Functional & Fast-Paced        → 5%
   Subtotal: 25%

Education & Certifications:
├─ Bachelor's Degree                    → 8%
└─ Advanced Degree / Certification      → 4%
   Subtotal: 12%

TOTAL: 100% ✅
```

These weights + expected years become the hiring policy for candidate evaluation.

---

# Phase 3: Resume Parsing

## Objective

Convert unstructured resumes into structured candidate profiles.

## Information Extracted

* Candidate Name
* Contact Information
* Education
* Skills
* Certifications
* Languages Known
* Work Experience
* Projects
* Technology Stack
* Leadership Experience

## Techniques

* NLP
* LLM-based Information Extraction
* Resume Structure Analysis
* Document Parsing

---

# Phase 4: Candidate Evaluation Engine

## Objective

Objectively evaluate candidates using recruiter-defined scoring policies.

The platform does not generate black-box scores.

Every score must be supported by evidence.

The canonical scorer lives in `src/scoring/graded_scorer.py`. It is the **only**
ranking signal — `WORKING_LOGIC.md` is explicit that the platform must not
implement multiple competing ranking systems.

---

## Two Scoring Modes

Per `WORKING_LOGIC.md` ("Fundamental Rule"), the scoring engine operates in two modes. In both modes, weight application and final aggregation are computed in code — never by the LLM.

* **Code-only scoring** — used wherever a requirement is fully measurable: total years of experience (linear formula), institute tier (lookup table), certification tier (lookup table), skill presence + years (synonym match + regex detection). No LLM is involved.
* **Rubric-bound LLM evidence scoring** — used wherever genuine judgment is required: skill depth, project complexity, relevant/same-role/leadership experience, domain expertise. The LLM reads the chunks retrieved by the threshold-based retrieval pipeline (cosine ≥ θ) **plus a pre-computed EMPLOYMENT HISTORY block** (deterministic date math from the structured profile) and scores against a recruiter-defined rubric. The years-of-experience sub-question uses a **banded ratio** (≥ target → 1.0; ≥ 50% → 0.5; ≥ 25% → 0.25; else 0.0) for audit-friendliness. The LLM never sees the weight and never computes the final contribution. Production rubric LLM is the local Ollama endpoint (`qwen2.5:3b`) — see `MODEL_REGISTRY.md`.

See [`AI_ARCHITECTURE.md`](AI_ARCHITECTURE.md) §5 for the full scoring workflow and output contract, and [`WORKING_LOGIC.md`](WORKING_LOGIC.md) "Scoring Rubrics" for the formulas.

---

# Candidate Evaluation Dimensions

The platform evaluates candidates across multiple dimensions. See [`WORKING_LOGIC.md`](WORKING_LOGIC.md) "Objective Candidate Evaluation" for the canonical list, and [`CURRENT_PROGRESS.md`](CURRENT_PROGRESS.md) for the implementation status of each.

Objective metrics (skill coverage, relevant experience, education alignment, certification alignment) receive higher weighting than subjective metrics (communication quality, resume organization) per `AGENTS.md`.

---

# Quality-Based Evaluation (planned)

When the recruiter enables it, the scorer consults:

* **Institution quality tiers** — IIT / NIT / Tier-1 Private University / Regional.
* **Certification provider reputation** — AWS / Microsoft / Google / Unknown.

See `CURRENT_PROGRESS.md` and `IMPLEMENTATION_ROADMAP.md` Phase 4.5.

---

# Candidate Ranking

## Objective

Rank candidates based on recruiter-defined priorities.

## Important Principle

Large Language Models do not determine candidate rankings.

Rankings are generated using:

* Recruiter-defined weights
* Structured candidate profiles
* Deterministic scoring formulas

This ensures:

* Reproducibility
* Explainability
* Auditability

---

# Candidate Comparison Engine

Recruiters can compare shortlisted candidates.

Example Questions:

* Which candidate has the strongest React experience?
* Which candidate has worked longest in a similar role?
* Which candidate has the most relevant projects?
* Why is Candidate A ranked above Candidate B?

The system provides evidence-backed comparisons.

---

# Candidate Intelligence Summaries

The platform generates recruiter-friendly summaries.

Example:

> Candidate has 5 years of experience as a Front-End Developer with expertise in HTML, CSS, JavaScript, and React. Has worked on multiple large-scale web applications and demonstrates strong alignment with the target role requirements.

---

# Resume Chat (RAG)

## Objective

Enable conversational exploration of candidate information via grounded RAG.

Example Questions:

* Does this candidate have NLP experience?
* What projects demonstrate machine learning expertise?
* Has this candidate worked with cloud technologies?
* Summarize leadership experience.
* What certifications does this candidate possess?

All responses must be grounded in retrieved resume content. If no relevant chunk
is found, the LLM responds with exactly:
**"Information not found in candidate documents."**

No speculation. No fabrication. The chunking strategy that supports this is
Recursive Chunking (`src/rag/chunker.py` `RecursiveChunker`); the retrieval
strategy that supports this is threshold-based cosine over the embedding
index (DEC-018).

---

# Resume Matching (Cross-Candidate Pool Search)

Embeddings and cosine similarity belong in **one place only**: searching across the whole candidate pool, not inside a single resume. The embedding pipeline (`src/rag/embeddings.py`) produces 384-dim vectors; the in-memory index (`data/embeddings/index.npz`) supports dense cosine retrieval for JD ↔ resume top-K triage and resume chat.

Per-candidate evidence retrieval uses **Section-Routed Evidence Retrieval** instead — full, intact sections, not similarity-ranked fragments. See [`WORKING_LOGIC.md`](WORKING_LOGIC.md) "Section-Routed Evidence Retrieval".

The similarity score is **not** the final ranking score. It is only one
supporting/triage signal. Candidate ranking must always be driven by the
deterministic scoring engine.

---

# RAG Architecture

RAG is the single retrieval strategy for explanations, resume chat, cross-candidate pool search, **and per-candidate evidence retrieval** (post-2026-07-05, DEC-017). The scoring engine remains the only ranking signal — the RAG pivot changes how evidence is gathered, not who decides the score. See [`AI_ARCHITECTURE.md`](AI_ARCHITECTURE.md) §11–§12 for the full architecture.

**Single retrieval strategy (active 2026-07-05):**

* **Threshold-based cosine over Recursive chunks** — embeddings via `sentence-transformers/all-MiniLM-L6-v2` (384-dim), in-memory index (`data/embeddings/index.npz`). Return all chunks with cosine ≥ θ (default `θ = 0.25`, Optuna-tuned; bounds `[0.10, 0.50]`), capped at `max_chunks_per_query = 20` for safety. The same pipeline serves per-candidate scoring, pool search, and resume chat — only the `candidate_id` filter changes. The default was lowered from 0.30 to 0.25 on 2026-07-07 to surface more date-bearing chunks per REQ. The prompt also includes a pre-computed EMPLOYMENT HISTORY block so the rubric LLM can correlate skill mentions with parser-computed role durations.

**Chunking (active 2026-07-05, refined 2026-07-07):** Recursive Chunking (`src/rag/recursive_chunker.py` `RecursiveChunker`), `chunk_size = 1000`, `chunk_overlap = 500` (50% overlap). Both are Optuna hyperparameters (DEC-021). Bounds: `chunk_size ∈ [500, 1000]`, `chunk_overlap ∈ [50%, 60%] of chunk_size`. Widened on 2026-07-07 from the prior 500/100 defaults to reduce date/skill split incidents across chunks.

**Experiment tracking:** Every retrieval / scoring run is logged to a local MLflow server (DEC-020). The shipped `θ`, `chunk_size`, and `chunk_overlap` are always the Optuna-recommended point on the Pareto front (DEC-021), not hand-picked.

**RAG grounding rule (unchanged):** If no chunk meets `θ`, the LLM responds with exactly *"Information not found in candidate documents."*

---

# AI Evaluation Framework

The platform tracks AI quality across parsing, retrieval, generation, ranking, hallucination, and business metrics. See [`EVALUATION.md`](EVALUATION.md) for the full metric definitions and targets.

---

# AI Design Principles

## Explainability Over Black-Box Scoring

Every recommendation must be explainable.

---

## Recruiter-Controlled Priorities

Recruiters decide what matters.

The AI applies those priorities consistently.

---

## Evidence-Based Reasoning

All evaluations must reference extracted resume evidence.

---

## Grounded AI Responses

All conversational responses must be grounded in retrieved resume content.

---

## Reproducible Rankings

Candidate rankings must be deterministic and auditable.

---

## Transparent Hiring Recommendations

Every recommendation must include supporting evidence.

---

# Technology Stack

## NLP

* spaCy
* NLTK
* Regex

## LLMs

* GPT
* Claude
* Gemini
* Open-source LLMs

## Embeddings

* BGE-M3
* E5
* Nomic

## Vector Databases

* Qdrant
* ChromaDB
* Pinecone

## Backend

* Python
* FastAPI

## Frontend

* Streamlit

---

# Skills Demonstrated

* Natural Language Processing (NLP)
* Information Extraction
* Explainable AI (XAI)
* Large Language Models (LLMs)
* Retrieval-Augmented Generation (RAG)
* Prompt Engineering
* Vector Databases
* Semantic Search
* Candidate Ranking Systems
* Recommendation Systems
* AI Evaluation Frameworks
* Applied AI Product Design
* End-to-End GenAI Application Development
* Recruitment Intelligence Systems
