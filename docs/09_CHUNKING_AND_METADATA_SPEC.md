# CHUNKING_AND_METADATA_SPEC.md

## 1. Purpose

This document defines how extracted resume content should be transformed into **retrievable evidence chunks** with rich metadata.

The purpose of this specification is to ensure that after resumes are converted into structured JSON, the platform also preserves resume content in a form that supports:

- requirement-wise retrieval
- explainable candidate scoring
- recruiter follow-up questions
- section-aware evidence lookup
- hybrid retrieval across structured and unstructured evidence

This document is intentionally separate from:

- `RESUME_EXTRACTION_SPEC.md`
- `RETRIEVAL_STRATEGY_SPEC.md`
- `SCORING_FORMULA_SPEC.md`
- `JSON_QUALITY_AUDIT_SPEC.md`
- `WORKING_LOGIC.md`

---

## 2. Core Principle

The platform must not treat a resume only as one flat text string.

A resume should be represented in two parallel forms:

1. **structured JSON fields** for exact facts
2. **chunked evidence units with metadata** for retrieval, explanation, and requirement-level scoring

Chunking exists because many scoring questions cannot be answered reliably from flat structured fields alone.

Examples include:

- how strongly a skill was used
- whether experience was professional or academic
- whether leadership was ownership or participation
- whether a project is relevant to a job requirement
- what evidence supports a recruiter-facing explanation

---

## 3. What a chunk is

A chunk is a **small, coherent, retrievable evidence unit** extracted from a resume.

A chunk should be:

- semantically meaningful
- compact enough for precise retrieval
- large enough to preserve context
- linked to metadata that explains where it came from

A chunk is **not** just an arbitrary fixed-size text slice.

---

## 4. What chunking must support

Chunking must support the following platform needs:

- semantic evidence retrieval
- lexical or keyword-sensitive retrieval
- section-aware filtering
- role and company context preservation
- date-aware experience interpretation
- field-to-evidence traceability
- recruiter-facing explanations
- auditability of requirement-level scoring

---

## 5. Design Principles

### 5.1 Preserve semantic boundaries

Chunking should follow logical document structure whenever possible.

Examples of strong boundaries:

- a full experience role block
- one project block
- one education entry
- one certification entry
- one contact block
- one skills block subsection

### 5.2 Do not over-split important evidence

If you split too aggressively, you lose the relationship between:

- company + title + dates
- project + tools + outcomes
- degree + institution + graduation date

These should often remain together.

### 5.3 Do not under-split broad sections

If you keep an entire two-page experience section as one chunk, retrieval becomes noisy.

### 5.4 Metadata is mandatory

A chunk without metadata is much less useful than a chunk with metadata.

### 5.5 Chunks are evidence objects, not just text storage

Each chunk should be designed as a retrieval object that helps the scoring engine gather evidence for one requirement at a time.

---

## 6. Recommended chunking strategy

The recommended strategy is **structure-first chunking with recursive fallback**.

That means:

1. detect sections and entry boundaries first
2. create semantic chunks from those boundaries
3. apply recursive splitting only if a chunk is too large
4. preserve parent-child relationships between chunks when split

This is better than applying a recursive text splitter blindly to the full resume text.

---

## 7. Chunk hierarchy

The platform should support a simple chunk hierarchy.

### 7.1 Level 1: Section chunks

Examples:

- Header / Contact
- Summary
- Skills
- Experience
- Education
- Certifications
- Projects
- Links / Portfolio
- Languages

These may be used for coarse routing, but they are often too broad for final retrieval.

### 7.2 Level 2: Entry chunks

These are the most important retrieval units.

Examples:

- one work experience entry
- one project entry
- one education entry
- one certification entry
- one grouped skills subsection

These should be your primary evidence chunks.

### 7.3 Level 3: Sub-entry or bullet chunks

Use these only when an entry is too large or contains multiple independent evidence units.

Examples:

- one responsibility bullet
- one achievement bullet
- one project outcome bullet

These are useful as recursive fallback chunks.

---

## 8. Primary chunk types

Recommended chunk types are:

- `header_contact`
- `summary`
- `skills_block`
- `experience_entry`
- `experience_bullet`
- `education_entry`
- `certification_entry`
- `project_entry`
- `project_bullet`
- `links_block`
- `language_entry`
- `other`

You may add more later, but these cover most resumes well.

---

## 9. Recommended chunk object schema

A chunk should use a structure like this:

```json
{
  "chunk_id": "chunk_001",
  "candidate_id": "cand_001",
  "document_id": "doc_001",
  "chunk_type": "experience_entry",
  "section": "experience",
  "page_numbers": [1],
  "text": "Business Analyst, XYZ Ltd, Jan 2021 - Jun 2024. Led stakeholder workshops, wrote BRDs, and built Power BI dashboards.",
  "parent_chunk_id": null,
  "child_chunk_ids": ["chunk_001_a", "chunk_001_b"],
  "metadata": {},
  "embedding_ready": true,
  "lexical_index_ready": true
}
```

---

## 10. Mandatory metadata fields

Every chunk should carry core metadata.

Recommended mandatory metadata:

- `candidate_id`
- `document_id`
- `chunk_type`
- `section`
- `page_numbers`
- `source_order`
- `text`

These are the minimum needed for traceability.

---

## 11. Recommended rich metadata fields

The following metadata should be attached whenever available.

### 11.1 Structural metadata

- `source_order`
- `page_numbers`
- `char_start`
- `char_end`
- `bbox` or layout coordinates if available
- `section_heading_raw`
- `section_heading_normalized`

### 11.2 Experience metadata

For experience-related chunks:

- `company_name`
- `job_title`
- `employment_type`
- `start_date`
- `end_date`
- `is_current`
- `calculated_duration_months`
- `experience_type`

Recommended `experience_type` values:

- `professional`
- `internship`
- `academic`
- `project`
- `freelance`
- `unknown`

### 11.3 Project metadata

- `project_name`
- `organization`
- `project_role`
- `project_start_date`
- `project_end_date`
- `project_duration_months`
- `project_type`

### 11.4 Education metadata

- `degree_name`
- `specialization`
- `institution_name`
- `education_start_date`
- `education_end_date`
- `completed`

### 11.5 Certification metadata

- `certification_name`
- `issuer`
- `issue_date`
- `expiry_date`

### 11.6 Skill and entity metadata

- `skills_asserted`
- `tools_asserted`
- `domains_asserted`
- `responsibility_signals`
- `metric_signals`

### 11.7 Confidence metadata

- `ocr_confidence`
- `chunk_confidence`
- `parser_source`
- `parser_agreement_score` if ensemble used

---

## 12. Chunking rules by section

Different resume sections should be chunked differently.

### 12.1 Header / contact

Usually keep as one chunk.

This chunk may contain:

- name
- email
- phone
- LinkedIn
- GitHub
- portfolio links
- location

Recommended chunk type:

- `header_contact`

### 12.2 Summary / objective

Usually keep as one chunk unless extremely long.

Recommended chunk type:

- `summary`

### 12.3 Skills

If the skills section is small, keep it as one chunk.

If it is large or grouped by categories such as programming, frameworks, cloud, tools, then create one chunk per group.

Recommended chunk type:

- `skills_block`

### 12.4 Experience

This is the most important section for retrieval.

Default rule:

- one work role = one primary `experience_entry` chunk

If a role contains many bullets or many unrelated responsibilities, create child chunks:

- one `experience_bullet` per major bullet or outcome

But keep the parent `experience_entry` chunk for context.

### 12.5 Education

Default rule:

- one degree/institution combination = one `education_entry` chunk

### 12.6 Certifications

Default rule:

- one certification = one `certification_entry` chunk

### 12.7 Projects

Default rule:

- one project = one `project_entry` chunk

If the project has many bullets or outcomes, use child `project_bullet` chunks.

### 12.8 Links / portfolio

Keep grouped links as one `links_block` chunk unless there are many portfolio items.

### 12.9 Languages

Usually one chunk is enough unless there are many structured language entries.

---

## 13. Recommended chunk size policy

Chunking should be driven by **semantic coherence first**, not by token count alone.

Still, very large chunks should be recursively split.

Recommended policy:

- if a semantic chunk is short and coherent, keep it as-is
- if a chunk is too long for reliable retrieval, split by bullet, sentence group, or subheading
- never split date/title/company context away from the experience entry they belong to unless preserved in child metadata

A good operational target is:

- prefer entry-level chunks first
- use child chunks only for oversized entries

---

## 14. Parent-child chunk model

To preserve both context and precision, the platform should support parent-child chunking.

Example:

- parent: full work experience block
- child A: responsibility bullet 1
- child B: responsibility bullet 2
- child C: achievement bullet 3

This allows:

- precise retrieval on child chunks
- explanation or scoring context from parent chunk

Recommended rule:

- if a child chunk is retrieved, the parent chunk should also be accessible during evaluation

---

## 15. Chunk ordering rules

Each chunk should preserve source order.

Recommended ordering metadata:

- `source_order`
- `section_order`
- `entry_order`
- `bullet_order` where relevant

This helps reconstruct document flow and improves explanation readability.

---

## 16. Recursive chunking fallback

Recursive splitting should be used only when semantic chunks are still too broad.

Examples:

- a single experience entry with 14 bullets
- a long project block spanning many technologies and outcomes
- a dense summary that mixes many signals

When recursively splitting:

- preserve parent ID
- keep section metadata
- inherit role/company/date metadata where relevant
- do not lose context required for later scoring

---

## 17. Chunking for hybrid retrieval

Because your system uses hybrid retrieval, chunk design should explicitly support both structured and semantic lookup.

### 17.1 Structured support

Chunks should align with extracted JSON objects wherever possible.

Examples:

- one `education_entry` chunk maps to one education object
- one `experience_entry` chunk may map to one experience object
- one `certification_entry` chunk may map to one certification object

### 17.2 Semantic support

Chunks should contain enough local context for embeddings to capture meaning.

Examples:

- company + title + dates + bullet context together
- project name + description + tools together
- certification title + issuer together

---

## 18. Chunking examples

### 18.1 Experience example

Source content:

```text
Business Analyst, XYZ Ltd | Jan 2021 - Jun 2024
- Led stakeholder workshops and gathered requirements
- Wrote BRDs and user stories
- Built Power BI dashboards for leadership reporting
```

Recommended chunks:

Parent chunk:

```json
{
  "chunk_type": "experience_entry",
  "section": "experience",
  "text": "Business Analyst, XYZ Ltd | Jan 2021 - Jun 2024. Led stakeholder workshops, wrote BRDs and user stories, and built Power BI dashboards.",
  "metadata": {
    "company_name": "XYZ Ltd",
    "job_title": "Business Analyst",
    "start_date": "2021-01",
    "end_date": "2024-06",
    "calculated_duration_months": 41,
    "experience_type": "professional",
    "skills_asserted": ["Stakeholder Management", "BRD", "User Stories", "Power BI"]
  }
}
```

Optional child chunks:

```json
{
  "chunk_type": "experience_bullet",
  "text": "Led stakeholder workshops and gathered requirements",
  "parent_chunk_id": "chunk_exp_001"
}
```

### 18.2 Education example

```json
{
  "chunk_type": "education_entry",
  "section": "education",
  "text": "MBA, Finance, ABC University, 2018 - 2020",
  "metadata": {
    "degree_name": "MBA",
    "specialization": "Finance",
    "institution_name": "ABC University",
    "education_start_date": "2018",
    "education_end_date": "2020",
    "completed": true
  }
}
```

### 18.3 Certification example

```json
{
  "chunk_type": "certification_entry",
  "section": "certifications",
  "text": "AWS Certified Cloud Practitioner",
  "metadata": {
    "certification_name": "AWS Certified Cloud Practitioner",
    "issuer": "Amazon Web Services"
  }
}
```

---

## 19. Relationship to JSON fields

Chunks should map cleanly to extracted JSON whenever possible.

Recommended linkage pattern:

- JSON field references chunk IDs
- chunk metadata references candidate and document IDs
- audit layer can verify forward and reverse mapping

Example:

```json
{
  "field_evidence_map": {
    "candidate_profile.experience[0]": ["chunk_exp_001"],
    "candidate_profile.skills[3]": ["chunk_exp_001", "chunk_proj_004"]
  }
}
```

This is critical for explainability and quality auditing.

---

## 20. Chunk quality checks

The chunking layer should also be auditable.

Quality checks should include:

- chunk too short to be useful
- chunk too long and noisy
- missing required metadata
- parent-child linkage broken
- section label missing
- dates detached from experience context
- excessive overlap creating duplication noise

---

## 21. Anti-patterns to avoid

Do not:

- chunk the whole resume into fixed-size raw slices only
- separate company/title/dates from the responsibility text they govern
- put all skills, projects, and experience into one large chunk
- create chunks with no section metadata
- over-split every bullet without parent context
- lose source ordering
- ignore portfolio and links for creative roles

---

## 22. Operational workflow

Recommended operational flow:

1. extract structured resume content
2. identify sections and entries
3. create section-level and entry-level chunks
4. recursively split oversized entries if needed
5. attach metadata to every chunk
6. compute embeddings for retrieval-ready chunks
7. optionally build lexical indexes
8. store chunk objects and field-to-evidence mapping
9. run chunk quality checks

---

## 23. Why this document is needed

The platform already has structured JSON extraction. But JSON alone is not enough for requirement-level evidence retrieval.

Without this chunking and metadata specification, the system will struggle with:

- semantic requirement matching
- recruiter follow-up questions
- explainable scoring
- evidence traceability
- accurate hybrid retrieval

This document defines the missing bridge between extraction and retrieval.

---

## 24. Relationship to other specs

### Relation to `RESUME_EXTRACTION_SPEC.md`

That document defines how the resume becomes canonical JSON. This document defines how extracted content becomes retrievable evidence chunks.

### Relation to `RETRIEVAL_STRATEGY_SPEC.md`

That document defines when to use structured, semantic, or hybrid retrieval. This document defines what evidence objects semantic retrieval operates on.

### Relation to `JSON_QUALITY_AUDIT_SPEC.md`

That document can audit whether meaningful evidence chunks were correctly created and mapped.

### Relation to `SCORING_FORMULA_SPEC.md`

That document defines how requirement evaluations become scores. This document helps ensure the evaluator sees high-quality, contextual evidence.

---

## 25. Final recommendation

Use **structure-first, metadata-rich, parent-child-aware chunking** as the standard for the platform.

The default retrieval unit should usually be the **entry-level semantic chunk** such as:

- one work experience entry
- one project entry
- one education entry
- one certification entry

Then use recursive child chunks only when necessary.

This is the best chunking strategy for your hiring system because it preserves context, improves retrieval quality, strengthens explainability, and integrates naturally with structured JSON and deterministic scoring.
