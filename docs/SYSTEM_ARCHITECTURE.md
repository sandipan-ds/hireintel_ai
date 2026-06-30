# System Architecture

> **Source of truth for scoring, evaluation, and ranking:**
> [`WORKING_LOGIC.md`](WORKING_LOGIC.md). This document covers the high-level
> system architecture; AI-specific architecture is in
> [`AI_ARCHITECTURE.md`](AI_ARCHITECTURE.md). For "what is implemented today
> vs what's planned", see [`CURRENT_PROGRESS.md`](CURRENT_PROGRESS.md).

## Overview

This document describes the high-level architecture, system components, service interactions, and deployment model for the HireIntel AI platform.

---

## High-Level Architecture

HireIntel AI follows a modular, service-oriented architecture designed to support scalability, maintainability, and clear separation of concerns. The system is composed of several independent services that communicate via well-defined APIs.

```text
┌─────────────────────────────────────────────────────────────────┐
│                        HireIntel AI Platform                     │
├─────────────────────────────┬─────────────────────────────────────┤
│       User Interface        │         API Gateway / BFF           │
│        (Streamlit)          │            (FastAPI)                │
├─────────────────────────────┴─────────────────────────────────────┤
│                         Core Services                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────┐ │
│  │   Job       │  │  Resume     │  │  Candidate  │  │  Report  │ │
│  │   Service   │  │  Service    │  │  Service    │  │  Service │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └──────────┘ │
├─────────────────────────────────────────────────────────────────┤
│                       AI/ML Layer                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────┐ │
│  │   Parser    │  │  Embedding  │  │  Scoring    │  │   RAG    │ │
│  │   Engine    │  │  Service    │  │  Engine     │  │  Engine  │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └──────────┘ │
├─────────────────────────────────────────────────────────────────┤
│                    Infrastructure Layer                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────┐ │
│  │   Vector    │  │  Object     │  │  Document   │  │  Message │ │
│  │   Database  │  │  Storage    │  │  Database   │  │  Queue   │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └──────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

---

## Major System Components

### 1. User Interface (UI)
- **Technology:** Streamlit
- **Purpose:** Provides an intuitive web interface for recruiters to upload job descriptions, clarify ambiguous requirements, configure weights (with `expected_years` per item), upload resumes, view rankings, and interact with candidates.

### 2. API Gateway / Backend for Frontend (BFF)
- **Technology:** FastAPI
- **Purpose:** Acts as the central entry point for all client requests. Handles authentication, request routing, rate limiting, and response aggregation.

### 3. Core Services

#### Job Service
- Manages job description lifecycle (upload, storage, requirement extraction).
- Runs the **JD clarification loop** (Green / Yellow / Red classification) per `WORKING_LOGIC.md` Step 0 — refuses to lock the scoring policy until all items are Green.
- Interfaces with the Parser Engine for JD processing.
- Persists structured job requirements and the `clarifications.json` artifact.

#### Resume Service
- Manages resume upload, storage, parsing, and cleaning (headers / footers / template noise).
- Coordinates with the Parser Engine for structured profile extraction.
- Handles document chunking and embedding pipeline.

#### Candidate Service
- Orchestrates candidate evaluation and ranking using the **single canonical deterministic scorer** (`src/scoring/graded_scorer.py`).
- Manages scoring policy application (weights + expected_years).
- Provides candidate comparison and summary generation.
- Produces the **Candidate Intelligence Report** aggregating per-item evidence.

#### Report Service
- Generates evaluation reports, comparison matrices, and hiring recommendations.
- Formats data for recruiter-friendly presentation.

### 4. AI/ML Layer

#### Parser Engine
- Extracts structured information from unstructured documents (resumes, job descriptions).
- Uses a combination of NLP techniques and LLM-based information extraction.
- Output: structured profile JSON in `data/processed/<role>/<id>.json`.

#### Embedding Service
- Generates vector embeddings for resume sections and chunks.
- Active model: `sentence-transformers/all-MiniLM-L6-v2` (384-dim, CPU-runnable).

#### Scoring Engine
- Two-mode scoring engine per `WORKING_LOGIC.md` "Fundamental Rule":
  - **Code-only mode** (`src/scoring/graded_scorer.py` + `src/scoring/unified_scorer.py`): synonym match, regex years detection, institute/cert tier lookup. No LLM. `min(importance, candidate_years / expected_years × importance)` with partial credit.
  - **Rubric-bound LLM mode** (`src/scoring/rubric_scorer.py` + `src/scoring/rubrics.py`): LLM scores against anchored rubric scales (0.0/0.25/0.5/0.75/1.0). LLM never sees weight, never computes aggregation. `CachedScoringTrace` frozen at scoring time.
- Total normalized to 0–100 via `scale_factor = 100 / max_score`.
- Produces explainable, reproducible scores with per-item evidence (section, snippet, cited text, anchor description, scoring trace).
- Institute and certificate tier databases (`data/Institutes/`, `data/Certificates/`) are recruiter-editable JSON files consumed by `src/scoring/tier_lookup.py`.

#### RAG Engine
- Retrieves relevant resume chunks based on recruiter queries (dense cosine over in-memory index).
- Generates grounded, context-aware responses via OpenRouter LLM with strict-grounding prompt.
- **RAG never participates in scoring** — it only explains scores that the deterministic engine produced.

### 5. Infrastructure Layer

#### Vector Database
- Stores and indexes resume embeddings for semantic search
- Enables efficient similarity search and retrieval

#### Object Storage
- Stores original resume files (PDF, DOCX, etc.)
- Provides durable, scalable file storage

#### Document Database
- Stores structured candidate profiles, job descriptions, scoring policies, and evaluation results

#### Message Queue
- Handles asynchronous task processing (parsing, embedding, scoring)
- Decouples services for improved resilience and scalability

---

## Service Interactions

### Synchronous Interactions
- **UI <-> API Gateway:** HTTP/REST for real-time user actions (upload, query, display)
- **API Gateway <-> Core Services:** Internal REST/gRPC for service orchestration
- **Core Services <-> AI/ML Layer:** Synchronous calls for immediate results (parsing, scoring)

### Asynchronous Interactions
- **Resume Upload:** Triggers async parsing and embedding pipeline via message queue
- **Evaluation:** Async scoring and report generation to handle large candidate lists
- **Notifications:** Async email or system notifications upon job completion

---

## API Architecture

### API Style
- **RESTful HTTP APIs** for client-facing and internal service communication
- **OpenAPI (Swagger)** for API documentation and client generation
- **Versioned endpoints** (e.g., `/api/v1/jobs`, `/api/v1/resumes`)

### Key API Groups
1. **Job Management:** `POST /api/v1/jobs`, `GET /api/v1/jobs/{id}`, `DELETE /api/v1/jobs/{id}`
2. **Resume Management:** `POST /api/v1/resumes`, `GET /api/v1/resumes/{id}`, `GET /api/v1/resumes/{id}/parsed`
3. **Candidate Evaluation:** `POST /api/v1/evaluations`, `GET /api/v1/evaluations/{job_id}`, `GET /api/v1/evaluations/{job_id}/rankings`
4. **Comparison & Chat:** `POST /api/v1/compare`, `POST /api/v1/chat`

---

## Runtime Architecture

### Deployment Model
- **Containerized services** using Docker
- **Orchestrated** via Docker Compose (local) or Kubernetes (production)
- **Scalable** — individual services can be scaled horizontally based on demand

### Request Flow
1. Recruiter uploads a job description via the UI.
2. API Gateway forwards the request to the Job Service.
3. Job Service persists the JD, runs the **clarification loop** (Green / Yellow / Red), and surfaces unresolved items to the recruiter.
4. Parser Engine extracts structured requirements and stores them.
5. Recruiter configures **weights + expected_years per item**, which are persisted as a scoring policy. The policy is locked only when all items are Green.
6. Resumes are uploaded, triggering async parsing, cleaning, and embedding.
7. **Single deterministic Scoring Engine** evaluates every candidate against the policy; output is `data/scores/graded/<role>_ranked.json`.
8. Results are stored and made available via the Candidate Service.
9. RAG Engine handles free-form recruiter questions (resume chat, comparison narratives) using retrieved chunks + LLM with strict-grounding prompt. **RAG never overrides the deterministic ranking.**

---

## Data Flow Architecture

### Ingestion Flow
```text
[Job Description / Resume] -> [API Gateway] -> [Core Service] -> [Object Storage]
                                                     |
                                                     v
                                              [Parser Engine]
                                                     |
                                                     v
                                              [Document Database]
```

### Evaluation Flow
```text
[Scoring Policy] + [Structured Profiles] -> [Scoring Engine] -> [Evaluation Results]
                                                                   |
                                                                   v
                                                           [Document Database]
```

### RAG Flow
```text
[Recruiter Query] -> [RAG Engine] -> [Vector Database] -> [Retrieved Chunks] -> [LLM] -> [Grounded Response]
```

---

## Storage Architecture

### Object Storage
- **Purpose:** Stores raw uploaded files (PDFs, DOCXs)
- **Structure:** Hierarchical by tenant/job/candidate identifiers
- **Retention:** Configurable based on business and compliance requirements

### Document Database
- **Purpose:** Stores structured data — candidate profiles, job descriptions, scoring policies, evaluation results
- **Schema:** Flexible to accommodate evolving AI-extracted fields
- **Access Patterns:** Indexed by job_id, candidate_id, and evaluation_id

### Vector Database
- **Purpose:** Stores embeddings for semantic search and retrieval
- **Indexing:** Optimized for cosine similarity and nearest-neighbor search
- **Updates:** Incremental — new resumes trigger embedding and index updates

---

## Deployment Architecture

### Local Development
- Docker Compose for all services
- Local instances of object storage (MinIO), document database, and vector database

### Production
- **Container Orchestration:** Kubernetes (EKS/AKS/GKE or on-premise)
- **Load Balancer:** External and internal load balancers for traffic distribution
- **Auto-scaling:** Horizontal Pod Autoscaler (HPA) for core and AI services
- **Monitoring:** Prometheus + Grafana for metrics; ELK stack for logs
- **Security:** TLS termination, network policies, secret management (e.g., Kubernetes Secrets, Vault)
