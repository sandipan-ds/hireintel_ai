# Open Knowledge Format (OKF) Architectural Specification

**Version:** 1.0.0  
**Author:** Google Cloud AI Specification / HireIntel.AI Engineering  
**Scope:** Knowledge Representation, Deterministic Requirement Extraction, and Sub-Query Assertions  

---

## 1. Overview & Purpose

The **Open Knowledge Format (OKF)** is a vendor-neutral, open specification introduced by Google Cloud in June 2026. It defines a standardized, human- and machine-readable method for AI agents and enterprise platforms to structure, exchange, and audit knowledge artifacts.

In **HireIntel.AI**, OKF serves as the **declarative knowledge schema layer** that bridges raw Job Descriptions (PDF, DOCX, Markdown, HTML) with the platform's deterministic scoring and RAG evaluation engines.

---

## 2. OKF vs. RAG (Retrieval-Augmented Generation)

| Feature | RAG (Retrieval-Augmented Generation) | OKF (Open Knowledge Format) |
|---|---|---|
| **Category** | **Dynamic Runtime Engine** | **Static Declarative Schema Contract** |
| **Primary Function** | Converts text into 768-dim dense vectors (`bge-base-en-v1.5`) and retrieves relevant evidence chunks at runtime. | Defines *how* Job Descriptions, REQs, and Sub-Queries are typed, validated, and structured before runtime. |
| **Output Type** | Cosine-similarity ranked text snippets. | Strongly-typed YAML metadata + Markdown rubrics. |
| **System Analogy** | **Database Query Engine / Vector Store** | **OpenAPI / Database Schema (DDL)** |

---

## 3. Structural Specification of OKF

An OKF document consists of a **single file or directory of Markdown files** pairing human-readable text with machine-readable YAML frontmatter:

```markdown
---
okf_version: "1.0"
artifact_type: "job_description | requirement_spec | subquery_assertion"
metadata:
  key: value
---

# Human-Readable Document Content
...
```

---

## 4. HireIntel.AI Implementation Workflow

### Stage 1: Document Intake (PDF / DOCX / MD → OKF Artifact)
Regardless of whether the input Job Description is a multi-column PDF, Word document (`.docx`), or plain Markdown, the parser normalizes the intake into an OKF-compliant document artifact:

```markdown
---
okf_version: "1.0"
artifact_type: "job_description"
job_slug: "business_analyst_lead"
position_title: "Lead Business Analyst"
domain: "Financial Engineering"
min_experience_years: 5
onet_code: "13-1111.00"
---

# Job Description: Lead Business Analyst

## Company Overview
We are looking for a Lead Business Analyst to drive financial product architecture...
```

---

### Stage 2: Deterministic REQ Extraction Contract
During requirement extraction, each extracted REQ is compiled into an OKF Requirement Specification:

```markdown
---
okf_type: "requirement_spec"
req_id: "REQ-001"
name: "SQL & Data Modeling"
category: "Core Skill"
is_mandatory: true
expected_years: 3
onet_element_id: "2.C.3.a"
weight_default: 15.0
---

### REQ-001 Evaluation Rubric
- **Level 1 (0.25)**: Basic querying (SELECT, JOINs).
- **Level 2 (0.50)**: Complex CTEs, window functions, and subqueries.
- **Level 3 (0.75)**: Database schema design, indexing, and query optimization.
- **Level 4 (1.00)**: Lead enterprise data warehouse architecture and ETL pipelines.
```

---

### Stage 3: Sub-Query Atomic Assertions
Sub-queries are represented as atomic, non-overlapping OKF assertions:

```markdown
---
okf_type: "subquery_assertion"
sq_id: "SQ001-1"
parent_req: "REQ-001"
assessment_method: "evidence_lookup"
scale: "0 or 1"
---

Assertion: Candidate explicitly demonstrates production experience with relational databases (e.g. PostgreSQL, SQL Server, Snowflake, or Oracle).
```

---

## 5. Architectural Benefits for HireIntel.AI

1. **Format-Agnostic Processing**: Ingestion parsers transform all incoming formats (PDF, DOCX, HTML) into unified OKF artifacts, eliminating format-specific edge cases downstream.
2. **Deterministic Validation**: Non-LLM Python routines parse OKF YAML frontmatter to validate recruiter weight balances (strictly summing to 100%) and enforce mandatory filtering without LLM hallucination.
3. **Auditability & Portability**: Recruiters and engineering teams can review, edit, and version-control OKF Markdown/YAML files in standard IDEs or web interfaces.
