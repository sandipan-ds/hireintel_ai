# Database Schema for Resume Chunks, Requirement Blocks, and Reasoning Storage

This document proposes a production-oriented database design for a resume shortlisting system that uses extracted resume data, requirement-wise retrieval, rubric-based evaluation, deterministic scoring, and explainable recruiter reports.

The schema is organized so that candidate ranking is reproducible. The final score is computed from recruiter-defined requirement weights and deterministic formulas. Evidence retrieval and language models support extraction and explanation, but do not directly set final rank.

## 1. Storage strategy

A practical implementation works well with three storage layers:

1. a relational database for canonical entities and scoring records
2. a vector store for resume chunk embeddings and similarity retrieval
3. an object store for original files and raw extraction artifacts

The relational schema below assumes PostgreSQL, but the same concepts apply elsewhere.

## 2. Core entities

The core entities are:

- jobs
- job_requirements
- candidates
- resume_documents
- candidate_profiles
- resume_chunks
- requirement_retrievals
- requirement_evaluations
- scorecards

## 3. Relational schema

### 3.1 candidates

```sql
CREATE TABLE candidates (
  candidate_id UUID PRIMARY KEY,
  external_ref TEXT,
  full_name TEXT,
  primary_email TEXT,
  primary_phone TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

This table stores the stable candidate identity used across resume uploads and scoring runs.

### 3.2 resume_documents

```sql
CREATE TABLE resume_documents (
  document_id UUID PRIMARY KEY,
  candidate_id UUID NOT NULL REFERENCES candidates(candidate_id),
  file_name TEXT NOT NULL,
  file_type TEXT NOT NULL,
  storage_uri TEXT NOT NULL,
  ingestion_type TEXT NOT NULL,
  page_count INT,
  source_language TEXT,
  ocr_used BOOLEAN NOT NULL DEFAULT FALSE,
  parser_name TEXT,
  parser_version TEXT,
  raw_text TEXT,
  extraction_json JSONB NOT NULL,
  validation_status TEXT NOT NULL DEFAULT 'pending',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

This table stores the canonical extraction payload for a specific uploaded resume.

### 3.3 candidate_profiles

```sql
CREATE TABLE candidate_profiles (
  profile_id UUID PRIMARY KEY,
  candidate_id UUID NOT NULL REFERENCES candidates(candidate_id),
  document_id UUID NOT NULL REFERENCES resume_documents(document_id),
  profile_json JSONB NOT NULL,
  normalized_features JSONB NOT NULL,
  confidence_json JSONB NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

This table separates the recruiter-facing structured profile from raw document storage.

### 3.4 resume_chunks

```sql
CREATE TABLE resume_chunks (
  chunk_id UUID PRIMARY KEY,
  candidate_id UUID NOT NULL REFERENCES candidates(candidate_id),
  document_id UUID NOT NULL REFERENCES resume_documents(document_id),
  page_number INT,
  section TEXT,
  chunk_type TEXT NOT NULL,
  text_content TEXT NOT NULL,
  metadata_json JSONB NOT NULL,
  char_start INT,
  char_end INT,
  embedding_status TEXT NOT NULL DEFAULT 'pending',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

This table is the bridge between extraction and retrieval. Each row should correspond to one chunk of evidence-ready resume text.

### 3.5 jobs

```sql
CREATE TABLE jobs (
  job_id UUID PRIMARY KEY,
  title TEXT NOT NULL,
  recruiter_id UUID,
  job_description_raw TEXT NOT NULL,
  job_description_cleaned TEXT,
  jd_status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 3.6 job_requirements

```sql
CREATE TABLE job_requirements (
  requirement_id UUID PRIMARY KEY,
  job_id UUID NOT NULL REFERENCES jobs(job_id),
  requirement_code TEXT NOT NULL,
  category TEXT NOT NULL,
  label TEXT NOT NULL,
  description TEXT NOT NULL,
  requirement_type TEXT NOT NULL,
  must_have BOOLEAN NOT NULL DEFAULT FALSE,
  weight_percent NUMERIC(5,2) NOT NULL,
  rubric_json JSONB NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(job_id, requirement_code)
);
```

This is the most important recruiter-controlled table. Each row represents one requirement block from the job description, along with its weight and rubric.

### 3.7 job_requirement_clarifications

```sql
CREATE TABLE job_requirement_clarifications (
  clarification_id UUID PRIMARY KEY,
  job_id UUID NOT NULL REFERENCES jobs(job_id),
  requirement_id UUID REFERENCES job_requirements(requirement_id),
  issue_type TEXT NOT NULL,
  issue_text TEXT NOT NULL,
  recruiter_resolution TEXT,
  resolved BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

This table helps preserve the JD validation workflow when requirements are ambiguous or missing.

### 3.8 requirement_retrievals

```sql
CREATE TABLE requirement_retrievals (
  retrieval_id UUID PRIMARY KEY,
  job_id UUID NOT NULL REFERENCES jobs(job_id),
  requirement_id UUID NOT NULL REFERENCES job_requirements(requirement_id),
  candidate_id UUID NOT NULL REFERENCES candidates(candidate_id),
  document_id UUID NOT NULL REFERENCES resume_documents(document_id),
  retrieval_threshold NUMERIC(6,4) NOT NULL,
  retrieval_strategy TEXT NOT NULL,
  retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

This table records the retrieval event for one candidate against one requirement.

### 3.9 requirement_retrieval_items

```sql
CREATE TABLE requirement_retrieval_items (
  retrieval_item_id UUID PRIMARY KEY,
  retrieval_id UUID NOT NULL REFERENCES requirement_retrievals(retrieval_id),
  chunk_id UUID NOT NULL REFERENCES resume_chunks(chunk_id),
  similarity_score NUMERIC(8,6) NOT NULL,
  rank_position INT NOT NULL,
  accepted BOOLEAN NOT NULL DEFAULT TRUE
);
```

This table stores the actual retrieved evidence chunks and their similarity scores.

### 3.10 requirement_evaluations

```sql
CREATE TABLE requirement_evaluations (
  evaluation_id UUID PRIMARY KEY,
  job_id UUID NOT NULL REFERENCES jobs(job_id),
  requirement_id UUID NOT NULL REFERENCES job_requirements(requirement_id),
  candidate_id UUID NOT NULL REFERENCES candidates(candidate_id),
  document_id UUID NOT NULL REFERENCES resume_documents(document_id),
  retrieval_id UUID REFERENCES requirement_retrievals(retrieval_id),
  evidence_summary TEXT,
  rubric_subscores_json JSONB NOT NULL,
  raw_requirement_score NUMERIC(8,4) NOT NULL,
  evaluator_type TEXT NOT NULL,
  evaluation_status TEXT NOT NULL DEFAULT 'complete',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(job_id, requirement_id, candidate_id, document_id)
);
```

This table stores the scored result for one candidate against one requirement, along with rubric sub-scores and summarized evidence.

### 3.11 scorecards

```sql
CREATE TABLE scorecards (
  scorecard_id UUID PRIMARY KEY,
  job_id UUID NOT NULL REFERENCES jobs(job_id),
  candidate_id UUID NOT NULL REFERENCES candidates(candidate_id),
  document_id UUID NOT NULL REFERENCES resume_documents(document_id),
  total_score NUMERIC(8,4) NOT NULL,
  scoring_formula_version TEXT NOT NULL,
  weight_snapshot_json JSONB NOT NULL,
  score_breakdown_json JSONB NOT NULL,
  rank_position INT,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(job_id, candidate_id, document_id)
);
```

This table stores the final deterministic score for a job-candidate pair.

### 3.12 score_explanations

```sql
CREATE TABLE score_explanations (
  explanation_id UUID PRIMARY KEY,
  scorecard_id UUID NOT NULL REFERENCES scorecards(scorecard_id),
  explanation_text TEXT NOT NULL,
  evidence_refs_json JSONB NOT NULL,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

This table stores recruiter-facing explanations derived from stored sub-scores and cited evidence.

## 4. Vector index design

In addition to the relational schema, store chunk embeddings in a vector index keyed by `chunk_id`. The metadata stored alongside each vector should include:

- candidate_id
- document_id
- section
- page_number
- job_family if available
- source confidence if useful

That makes it possible to retrieve only relevant candidate chunks for one requirement block at a time.

## 5. Example entity relationships

The main relationships are:

- one candidate can have many resume documents
- one resume document can produce one or more candidate profiles over time, though usually one active profile is enough
- one job has many requirement blocks
- one requirement block is evaluated against many candidates
- one retrieval event can return many chunks
- one requirement evaluation references one retrieval event
- one scorecard aggregates many requirement evaluations

## 6. Recommended indexes

Useful relational indexes include:

```sql
CREATE INDEX idx_resume_documents_candidate_id ON resume_documents(candidate_id);
CREATE INDEX idx_candidate_profiles_candidate_id ON candidate_profiles(candidate_id);
CREATE INDEX idx_resume_chunks_candidate_doc ON resume_chunks(candidate_id, document_id);
CREATE INDEX idx_resume_chunks_section ON resume_chunks(section);
CREATE INDEX idx_job_requirements_job_id ON job_requirements(job_id);
CREATE INDEX idx_requirement_evaluations_lookup ON requirement_evaluations(job_id, candidate_id);
CREATE INDEX idx_scorecards_job_rank ON scorecards(job_id, rank_position);
```

If using PostgreSQL with pgvector, add a vector index on chunk embeddings in the vector table or extension-backed column.

## 7. Minimal scoring flow mapped to tables

A clean end-to-end data flow looks like this:

1. upload resume into `resume_documents`
2. extract profile into `candidate_profiles`
3. split content into `resume_chunks`
4. upload job into `jobs`
5. create requirement blocks in `job_requirements`
6. retrieve relevant chunks into `requirement_retrievals` and `requirement_retrieval_items`
7. evaluate each requirement into `requirement_evaluations`
8. aggregate weighted scores into `scorecards`
9. generate recruiter-facing narratives into `score_explanations`

## 8. Why this schema fits your project

This design matches a deterministic candidate evaluation workflow because it keeps the system modular. Resume extraction, evidence retrieval, rubric evaluation, final scoring, and explanation generation are all stored separately. That separation makes the system easier to debug, audit, and improve.

It also allows you to upgrade extractors or retrieval methods later without corrupting the scoring logic. For example, you can reprocess a resume with a better OCR engine while keeping the same requirement definitions and deterministic scoring formula.

## 9. Final recommendation

Use the relational schema as the source of truth for candidate, job, requirement, and scoring state. Use the vector index only for retrieval. Never let the vector search itself determine candidate rank. Candidate rank should be computed only from stored requirement evaluations and recruiter-defined weights.

## 10. Multi-role refinement based on the scoring guides

The attached documents imply that this database design should support not just one Data Science role but a reusable scoring platform for multiple job families. The main reusable pattern is that every role should be represented by a role-specific requirement pack built on a consistent scoring engine.

### 10.1 Add explicit role templates

A single role such as Data Scientist may have 20 requirements and 56 sub-queries, but another role such as Business Analyst Lead, Sales Manager, or Web Designer may have different counts. Because of that, the schema should store role definitions independently from live jobs.

Add these tables.

```sql
CREATE TABLE role_templates (
  role_template_id UUID PRIMARY KEY,
  role_name TEXT NOT NULL,
  role_family TEXT,
  version TEXT NOT NULL,
  description TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(role_name, version)
);
```

```sql
CREATE TABLE role_template_requirements (
  template_requirement_id UUID PRIMARY KEY,
  role_template_id UUID NOT NULL REFERENCES role_templates(role_template_id),
  requirement_code TEXT NOT NULL,
  category TEXT NOT NULL,
  label TEXT NOT NULL,
  description TEXT NOT NULL,
  requirement_type TEXT NOT NULL,
  default_weight_percent NUMERIC(5,2),
  active BOOLEAN NOT NULL DEFAULT TRUE,
  UNIQUE(role_template_id, requirement_code)
);
```

This allows you to define a reusable skeleton for each role before a recruiter customizes it for a live job.

### 10.2 Add sub-query definition tables

The attached Data Science documents show that each requirement should break into atomic sub-queries with variable counts. That pattern should be modeled explicitly in the database.

```sql
CREATE TABLE requirement_subqueries (
  subquery_id UUID PRIMARY KEY,
  requirement_id UUID NOT NULL REFERENCES job_requirements(requirement_id),
  subquery_code TEXT NOT NULL,
  prompt_text TEXT NOT NULL,
  scoring_type TEXT NOT NULL,
  scale_definition JSONB NOT NULL,
  sort_order INT NOT NULL,
  UNIQUE(requirement_id, subquery_code)
);
```

For reusable templates, you may also want a template-level version.

```sql
CREATE TABLE template_requirement_subqueries (
  template_subquery_id UUID PRIMARY KEY,
  template_requirement_id UUID NOT NULL REFERENCES role_template_requirements(template_requirement_id),
  subquery_code TEXT NOT NULL,
  prompt_text TEXT NOT NULL,
  scoring_type TEXT NOT NULL,
  scale_definition JSONB NOT NULL,
  sort_order INT NOT NULL,
  UNIQUE(template_requirement_id, subquery_code)
);
```

This is important because the scoring engine needs to know not just the final requirement but the exact sub-questions that were used to produce its normalized contribution.

### 10.3 Add recruiter weight snapshots as first-class artifacts

The guides consistently require recruiter-defined percentages summing to 100. Although `job_requirements` already stores weights, it is useful to store the recruiter’s completed weighting artifact separately for audit and versioning.

```sql
CREATE TABLE recruiter_weight_configs (
  weight_config_id UUID PRIMARY KEY,
  job_id UUID NOT NULL REFERENCES jobs(job_id),
  role_template_id UUID REFERENCES role_templates(role_template_id),
  config_json JSONB NOT NULL,
  total_percentage NUMERIC(5,2) NOT NULL,
  is_valid BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

This table preserves the exact configuration that the scoring engine consumed.

### 10.4 Store requirement section mappings

The working logic document indicates that requirements should map to canonical resume sections. That mapping should be persisted so retrieval remains auditable.

```sql
CREATE TABLE requirement_section_mappings (
  mapping_id UUID PRIMARY KEY,
  requirement_id UUID NOT NULL REFERENCES job_requirements(requirement_id),
  section_type TEXT NOT NULL,
  priority_order INT NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Even if retrieval is threshold-based across chunks, keeping an auditable section mapping is useful for debugging and reporting.

### 10.5 Add deterministic normalized contribution storage

The attached documents emphasize the formula:

`Contribution = Weight × (Sub-Score / Number_of_Sub_Queries)`

That means each requirement evaluation should ideally store both the raw sub-score sum and its normalized contribution.

You can extend `requirement_evaluations` conceptually with the following fields:

- `subquery_count`
- `subquery_score_sum`
- `normalized_requirement_score`
- `weighted_contribution`

If you prefer a separate table for transparency, use:

```sql
CREATE TABLE requirement_score_components (
  component_id UUID PRIMARY KEY,
  evaluation_id UUID NOT NULL REFERENCES requirement_evaluations(evaluation_id),
  subquery_count INT NOT NULL,
  subquery_score_sum NUMERIC(8,4) NOT NULL,
  normalized_requirement_score NUMERIC(8,4) NOT NULL,
  recruiter_weight_percent NUMERIC(5,2) NOT NULL,
  weighted_contribution NUMERIC(8,4) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

This makes the final score mathematically transparent for recruiters and developers.

### 10.6 Recommended category governance

The attached documents repeatedly recommend consistent categories across roles. So in the database, categories should be controlled vocabulary rather than free text. Use a fixed allowed set such as:

- `core_skill`
- `preferred_skill`
- `experience`
- `education_certification`
- `responsibility`

The role-specific difference should come from the labels and rubrics, not from inventing new category systems for each job family.

## 11. Final multi-role recommendation

Use the database as a general scoring platform with three layers. First, store role templates and reusable sub-query packs. Second, instantiate job-specific requirements and recruiter weights from those templates. Third, evaluate each candidate through retrieval, rubric scoring, normalized contribution calculation, and deterministic aggregation. That structure matches the reusable patterns shown in the attached documents while keeping the system explainable and auditable.
