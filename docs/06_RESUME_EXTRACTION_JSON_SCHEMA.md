# Production JSON Schema for Resume Extraction

This document defines a production-ready JSON structure for extracting information from mixed-format resumes so the data can be used for job-description-based matching, evidence retrieval, deterministic scoring, and explainable recruiter reports.

The design follows five principles. First, extracted data must preserve both structured facts and original evidence. Second, parsing must support text PDFs and scanned PDFs. Third, the schema must be usable for deterministic scoring rather than black-box ranking. Fourth, every important claim should be traceable to source evidence. Fifth, missing information must remain explicitly missing rather than hallucinated.

## 1. Design goals

The schema is designed to support:

- canonical candidate profiles
- evidence-grounded retrieval
- requirement-wise scoring
- auditability and reproducibility
- downstream recruiter review

A single resume should produce one top-level extraction object.

## 2. Top-level schema

```json
{
  "schema_version": "1.0.0",
  "candidate_id": "cand_001",
  "document": {
    "document_id": "doc_001",
    "file_name": "john_doe_resume.pdf",
    "file_type": "pdf",
    "ingestion_type": "native_pdf",
    "source_language": "en",
    "page_count": 2,
    "parsed_at": "2026-07-10T12:00:00Z",
    "ocr_used": false,
    "parser_name": "docling+llm-normalizer",
    "parser_version": "1.0.0"
  },
  "candidate_profile": {
    "full_name": null,
    "headline": null,
    "summary": null,
    "emails": [],
    "phones": [],
    "locations": [],
    "links": {
      "linkedin": null,
      "github": null,
      "portfolio": null,
      "other": []
    },
    "skills": [],
    "education": [],
    "experience": [],
    "projects": [],
    "certifications": [],
    "languages": [],
    "awards": [],
    "publications": []
  },
  "normalized_features": {
    "total_experience_months": null,
    "latest_job_title": null,
    "latest_company": null,
    "highest_degree": null,
    "skill_canonical_map": {},
    "location_normalized": null,
    "work_authorization": null
  },
  "evidence_chunks": [],
  "field_evidence_map": {},
  "validation": {
    "status": "pending",
    "warnings": [],
    "errors": []
  },
  "confidence": {
    "document_confidence": 0.0,
    "field_confidence": {}
  },
  "raw": {
    "raw_text": "",
    "sections_detected": [],
    "ocr_text": null
  }
}
```

## 3. Candidate profile object

The `candidate_profile` section stores recruiter-facing structured information.

### 3.1 Core identity

```json
{
  "full_name": "John Doe",
  "headline": "Senior Backend Engineer",
  "summary": "Backend engineer with 6 years of experience in distributed systems.",
  "emails": [
    {
      "value": "john@example.com",
      "primary": true,
      "confidence": 0.99
    }
  ],
  "phones": [
    {
      "value": "+919999999999",
      "primary": true,
      "country_code": "+91",
      "confidence": 0.95
    }
  ],
  "locations": [
    {
      "raw": "Bangalore, India",
      "city": "Bengaluru",
      "state": "Karnataka",
      "country": "India",
      "normalized": "Bengaluru, Karnataka, India",
      "confidence": 0.86
    }
  ]
}
```

### 3.2 Skills

Skills should be stored as explicit objects, not just strings, because later matching may need canonicalization, evidence lookup, and type-based filtering.

```json
[
  {
    "name_raw": "Node Js",
    "name_canonical": "Node.js",
    "category": "backend",
    "source_type": "explicit",
    "last_used": "2025-01",
    "months_of_evidence": 36,
    "confidence": 0.91
  },
  {
    "name_raw": "Postgres",
    "name_canonical": "PostgreSQL",
    "category": "database",
    "source_type": "explicit",
    "last_used": null,
    "months_of_evidence": 24,
    "confidence": 0.88
  }
]
```

Recommended fields for each skill are `name_raw`, `name_canonical`, `category`, `source_type`, `months_of_evidence`, `last_used`, and `confidence`.

### 3.3 Education

```json
[
  {
    "degree": "B.Tech",
    "specialization": "Computer Science and Engineering",
    "institution_raw": "ABC Institute of Technology",
    "institution_normalized": "ABC Institute of Technology",
    "institution_tier": null,
    "start_date": "2016-08",
    "end_date": "2020-06",
    "grade": "8.4 CGPA",
    "completed": true,
    "confidence": 0.9
  }
]
```

### 3.4 Experience

Experience is the most important section for deterministic matching. It should be normalized enough to support banded years scoring, but the original evidence must remain accessible.

```json
[
  {
    "experience_id": "exp_001",
    "job_title": "Software Engineer",
    "company": "XYZ Labs",
    "employment_type": "full_time",
    "start_date": "2021-07",
    "end_date": "2024-03",
    "is_current": false,
    "duration_months": 32,
    "location": "Remote",
    "responsibilities": [
      "Built REST APIs in Node.js",
      "Worked on PostgreSQL performance tuning"
    ],
    "tools_and_skills": ["Node.js", "PostgreSQL", "Docker"],
    "confidence": 0.92
  }
]
```

### 3.5 Projects

```json
[
  {
    "project_id": "proj_001",
    "name": "Resume Ranking Engine",
    "organization": null,
    "role": "Personal Project",
    "start_date": "2025-01",
    "end_date": null,
    "description": [
      "Built a candidate ranking workflow using requirement-based scoring"
    ],
    "skills_used": ["Python", "FAISS", "FastAPI"],
    "url": null,
    "confidence": 0.84
  }
]
```

### 3.6 Certifications and languages

```json
{
  "certifications": [
    {
      "name": "AWS Certified Developer - Associate",
      "issuer": "Amazon Web Services",
      "issue_date": "2024-09",
      "expiry_date": null,
      "credential_id": null,
      "confidence": 0.93
    }
  ],
  "languages": [
    {
      "name": "English",
      "proficiency": "professional",
      "confidence": 0.75
    }
  ]
}
```

## 4. Normalized features object

The `normalized_features` object stores derived fields that make deterministic scoring easier. These are not raw claims copied from the resume. They are normalized values computed from extracted fields.

```json
{
  "total_experience_months": 68,
  "latest_job_title": "Senior Backend Engineer",
  "latest_company": "XYZ Labs",
  "highest_degree": "B.Tech",
  "skill_canonical_map": {
    "node js": "Node.js",
    "postgres": "PostgreSQL"
  },
  "location_normalized": "Bengaluru, Karnataka, India",
  "work_authorization": null
}
```

These values are useful for quick filters, scoring formulas, and recruiter search, but they should always be derivable from evidence-backed fields.

## 5. Evidence chunks

This is the most important part for explainability. Every resume should also be stored as retrievable chunks with metadata.

```json
[
  {
    "chunk_id": "chunk_001",
    "candidate_id": "cand_001",
    "document_id": "doc_001",
    "page_number": 1,
    "section": "experience",
    "chunk_type": "text",
    "text": "Software Engineer at XYZ Labs, Jul 2021 to Mar 2024. Built REST APIs in Node.js and optimized PostgreSQL queries.",
    "char_start": 0,
    "char_end": 126,
    "embedding_ready": true,
    "ocr_confidence": null,
    "source_bbox": null
  }
]
```

Recommended metadata for each chunk includes page number, section label, chunk type, and candidate identifier. If your extractor supports layout coordinates, store bounding boxes too.

## 6. Field-to-evidence mapping

Each structured field should map back to one or more source chunks. This is what makes explanations auditable.

```json
{
  "candidate_profile.full_name": ["chunk_010"],
  "candidate_profile.skills[0]": ["chunk_001", "chunk_009"],
  "candidate_profile.experience[0].job_title": ["chunk_001"],
  "candidate_profile.education[0].degree": ["chunk_020"]
}
```

If a field is inferred from multiple places, store all source chunk identifiers.

## 7. Validation object

Validation should happen after extraction and before deterministic scoring.

```json
{
  "status": "review_required",
  "warnings": [
    "Two phone numbers found",
    "Experience dates overlap between exp_002 and exp_003"
  ],
  "errors": []
}
```

Typical checks include email format, phone normalization, date consistency, duplicate skills, degree completion ambiguity, and overlapping experience periods.

## 8. Confidence model

Confidence should be stored at both document and field level.

```json
{
  "document_confidence": 0.87,
  "field_confidence": {
    "candidate_profile.full_name": 0.98,
    "candidate_profile.skills": 0.88,
    "candidate_profile.education": 0.79,
    "candidate_profile.experience": 0.91
  }
}
```

Confidence should never directly determine candidate rank. It should only guide review workflows and help recruiters judge extraction quality.

## 9. Null-handling rules

To avoid hallucination, use these rules consistently:

- unknown scalar value becomes `null`
- unknown list value becomes `[]`
- ambiguous extracted value can be stored in a `raw` field plus warning
- do not invent dates, institutions, roles, or skill durations

## 10. Minimal JSON required for scoring

If you want a lean version for early development, the minimum useful scoring payload is:

```json
{
  "candidate_id": "cand_001",
  "candidate_profile": {
    "full_name": "John Doe",
    "skills": [
      {"name_canonical": "Python", "confidence": 0.95},
      {"name_canonical": "SQL", "confidence": 0.92}
    ],
    "education": [],
    "experience": [],
    "certifications": []
  },
  "evidence_chunks": [],
  "field_evidence_map": {},
  "validation": {"status": "pending", "warnings": [], "errors": []},
  "confidence": {"document_confidence": 0.0, "field_confidence": {}}
}
```

## 11. Recommended implementation notes

Use this schema in two layers. The first layer is the extraction layer, which fills the structured profile and chunk store. The second layer is the scoring layer, which reads from this schema but does not mutate it arbitrarily.

A good implementation pattern is to store:

- one canonical extraction JSON per uploaded resume
- one normalized chunk collection for retrieval
- one derived scoring record per job description and candidate pair

## 12. Final recommendation

For your shortlisting system, treat this schema as the contract between resume processing and JD matching. If the extraction output follows this contract, you can safely build requirement retrieval, rubric scoring, deterministic ranking, and explanation generation on top of it.

## 13. Multi-role refinement based on the scoring guides

The attached role documents show that the platform should not hardcode a Data Science-specific structure into the extraction contract. Instead, the resume extraction schema should remain role-agnostic while exposing enough structure for role-specific scoring policies to be applied later.

Across the attached documents, the most reusable pattern is that every role should be normalized into five stable requirement groups:

- Core Skills
- Preferred Skills
- Experience
- Education and Certifications
- Key Responsibilities

These categories should remain consistent across roles even when the requirement labels change. For example, Data Scientist may use Python, SQL, and model deployment, while Business Analyst Lead may use stakeholder management, requirement gathering, and BI tools. The extraction schema therefore should not encode role-specific requirement names inside the resume object itself. Instead, it should expose resume facts and evidence in a canonical form that a separate role configuration can consume.

### 13.1 Add role-agnostic evidence hooks

To support multiple roles, the extraction schema should preserve raw evidence in a way that can later answer atomic sub-queries such as:

- does evidence exist for a skill
- was the skill used in the right context
- how strong is the evidence
- how many relevant years are supported

A useful addition is an evidence-friendly enrichment block on chunks and structured experience entries.

```json
{
  "experience": [
    {
      "experience_id": "exp_001",
      "job_title": "Senior Analyst",
      "company": "ABC Corp",
      "start_date": "2021-01",
      "end_date": "2024-06",
      "duration_months": 41,
      "experience_type": "professional",
      "responsibilities": [
        "Gathered business requirements from stakeholders",
        "Built Power BI dashboards"
      ],
      "skills_used": ["SQL", "Power BI", "Stakeholder Management"]
    }
  ]
}
```

This supports the general scoring pattern from the documents, where requirement evaluation is performed through atomic sub-queries rather than whole-resume similarity.

### 13.2 Add a requirement-mapping-ready derived layer

The scoring guides imply that scoring happens after each role is decomposed into requirement IDs and sub-query sets. The extraction schema should therefore include optional derived fields that make requirement evaluation easier without embedding the role logic into the resume itself.

```json
{
  "normalized_features": {
    "total_experience_months": 68,
    "latest_job_title": "Senior Analyst",
    "highest_degree": "MBA",
    "skill_canonical_map": {
      "power bi": "Power BI",
      "biz analysis": "Business Analysis"
    },
    "role_signals": {
      "has_leadership_evidence": true,
      "has_client_facing_evidence": true,
      "has_dashboard_evidence": true,
      "has_sales_target_evidence": false
    }
  }
}
```

These `role_signals` are not final scores. They are deterministic helper facts extracted from the resume that make later requirement evaluation easier across roles.

### 13.3 Separate extracted facts from scoring policy

The attached documents repeatedly enforce that recruiter weights and requirement scoring must be role-specific and recruiter-controlled. Because of that, the extraction schema should never store fields such as `python_score`, `sales_score`, or `design_score` inside the canonical resume JSON. Those belong to downstream scorecards, not extraction output.

The extraction layer should only store:

- structured candidate facts
- normalized features
- evidence chunks
- field-to-evidence traceability
- validation and confidence

The scoring layer should separately store:

- role definition
- requirement IDs
- sub-query rubrics
- recruiter weights
- requirement evaluations
- final deterministic scores

### 13.4 Support atomic sub-query answering

The attached Data Science documents show a consistent decomposition pattern:

- binary existence checks
- binary purpose/context checks
- float evidence-strength checks using anchored bands
- float years-experience checks relative to a target

To support this across roles, the resume schema should preserve enough detail for each skill or responsibility mention to be evaluated later. For example, the extraction layer should try to retain:

- where the evidence came from
- whether it came from professional experience, academic work, or a personal project
- associated dates and computed durations when available
- nearby tools, domains, and outputs

This can be represented in chunk metadata.

```json
{
  "chunk_id": "chunk_014",
  "section": "experience",
  "text": "Led stakeholder workshops and translated business needs into BRDs and user stories.",
  "metadata": {
    "candidate_id": "cand_001",
    "page_number": 1,
    "experience_type": "professional",
    "parent_role_title": "Business Analyst Lead",
    "calculated_duration_months": 24,
    "skills_asserted": ["Stakeholder Management", "Documentation", "User Stories"]
  }
}
```

### 13.5 Reusable multi-role section model

The working logic document emphasizes canonical sections such as Personal Info, Education, Experience, Projects, Skills, Certifications, and Languages. That section model should remain fixed across roles. It is broad enough for Data Scientist, Business Analyst Lead, Sales Manager, and Web Designer without redesigning the extraction contract each time.

A role-specific scoring configuration can then decide which sections matter most for a given requirement. For example:

- a Sales Manager role may emphasize Experience, Responsibilities, and quantified business impact
- a Web Designer role may emphasize Projects, tools, portfolio links, and design responsibilities
- a Business Analyst Lead role may emphasize Experience, stakeholder collaboration, documentation, and BI tools
- a Data Scientist role may emphasize Core Skills, Experience, model development, and deployment evidence

### 13.6 Recommended additions for the next schema version

For a multi-role platform, the next schema version should add these optional fields:

- `candidate_profile.domain_experience`: list of domains such as healthcare, fintech, retail, SaaS
- `candidate_profile.portfolio_artifacts`: links or references useful for design and creative roles
- `normalized_features.role_signals`: deterministic booleans or counts used by many roles
- `normalized_features.quantified_impact_signals`: extracted metrics like revenue growth, conversion lift, cost savings, team size, or model accuracy gains
- `evidence_chunks[].metadata.experience_type`: distinguish professional, academic, and personal project evidence
- `evidence_chunks[].metadata.calculated_duration_months`: deterministic duration feature to support years-based scoring

These refinements keep the extraction schema generic while making it much more useful for the sub-query and requirement-based scoring approach shown in the attached documents.

## 14. Final multi-role recommendation

Use a single role-agnostic resume extraction contract for every resume, and build separate role packs on top of it. Each role pack should contain requirement blocks, sub-query definitions, recruiter weights, and deterministic scoring formulas. This gives you one extraction pipeline and many scoring policies, which is the scalable architecture suggested by the attached guides.
