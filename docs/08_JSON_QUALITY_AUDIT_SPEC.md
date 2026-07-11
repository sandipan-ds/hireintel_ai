# JSON_QUALITY_AUDIT_SPEC.md

## 1. Purpose

This document defines the quality-audit specification for resume JSON extracted from PDFs, scanned resumes, DOCX files, and other supported resume formats.

Its purpose is to answer one critical question:

**How do we know whether important information present in the resume was correctly captured in the extracted JSON, and what do we do when it was missed, partially captured, or extracted incorrectly?**

This document defines:

- what “JSON quality” means in this platform
- how to validate extraction outputs
- how to detect missing information
- how to compare resume evidence against JSON fields
- how to assign extraction quality scores
- how to trigger manual review when necessary

This document is intentionally separate from:

- `RESUME_EXTRACTION_SPEC.md`
- `SCORING_FORMULA_SPEC.md`
- `RETRIEVAL_STRATEGY_SPEC.md`
- `WORKING_LOGIC.md`

---

## 2. Core Principle

Extracted JSON must never be treated as unquestionable truth.

It should be treated as a **candidate structured representation** of the resume that must be audited for:

- structural correctness
- field completeness
- factual consistency
- evidence coverage
- semantic omissions

The platform should therefore include a dedicated **JSON Quality Audit Layer** after extraction and before scoring.

---

## 3. What the audit layer must detect

The audit layer should detect at least these classes of issues:

- malformed JSON structure
- wrong field types
- invalid normalized values
- missing information that appears in the resume
- extracted fields with weak or missing evidence backing
- section-level under-extraction
- conflicting values between extraction routes
- low-confidence OCR or parser outputs
- suspiciously incomplete experience, education, or certification sections

---

## 4. Audit scope

The audit should compare three kinds of artifacts:

1. the **source resume evidence**
2. the **extracted canonical JSON**
3. the **field-to-evidence mapping** and chunk inventory

If multiple parsers or extraction routes were used, the audit may also compare:

4. **cross-parser outputs**

---

## 5. Audit layers

The recommended audit architecture has five layers.

### 5.1 Layer A: Schema validation

This checks whether the JSON is structurally valid.

Examples:

- required top-level keys exist
- arrays are arrays
- scalars are scalars
- dates follow allowed formats
- confidence fields are numeric
- experience entries contain expected keys

This layer answers:

**Is the JSON structurally valid?**

### 5.2 Layer B: Field and section completeness audit

This checks whether expected information appears in JSON when there is evidence that the resume contains it.

Examples:

- email-like text appears in resume but `emails` is empty
- education heading exists but `education` array is empty
- multiple role/date patterns appear in resume but only one experience entry was extracted

This layer answers:

**Did we likely miss important information?**

### 5.3 Layer C: Evidence coverage audit

This checks whether extracted fields are grounded in evidence and whether meaningful evidence was left unmapped.

Examples:

- `AWS Certified Developer` appears in a chunk but is not mapped into `certifications`
- `Power BI` appears repeatedly in project/experience chunks but not in `skills`
- a full experience block is present in chunks but not converted into an experience entry

This layer answers:

**Did the extractor map resume evidence into JSON properly?**

### 5.4 Layer D: Semantic missing-information audit

This is a post-extraction comparison step that inspects the resume content and the JSON together to identify likely omissions or mismatches.

This may use:

- rule-based logic
- LLM-based auditing
- a combination of both

This layer answers:

**What explicit information is present in the resume but absent in JSON?**

### 5.5 Layer E: Cross-parser consistency audit

If two or more extraction routes were used, compare their outputs.

Examples:

- parser A finds a certification but parser B does not
- parser A extracts 3 experience entries and parser B extracts 4
- parser A and parser B agree on name, email, and phone

This layer answers:

**How stable is the extraction across parsers?**

---

## 6. Required inputs

The audit system should consume the following inputs.

### 6.1 Source document artifacts

- original file reference
- extracted raw text
- page-level text or OCR output
- section candidates
- evidence chunks

### 6.2 Extracted JSON artifacts

- canonical extraction JSON
- normalized features
- validation object from extraction stage
- confidence object from extraction stage

### 6.3 Mapping artifacts

- field-to-evidence mapping
- chunk metadata
- section metadata

### 6.4 Optional ensemble artifacts

- parser A output
- parser B output
- OCR route output
- native-text route output

---

## 7. Canonical audit output

Each audit run should produce a machine-readable audit artifact.

Recommended structure:

```json
{
  "audit_version": "1.0.0",
  "document_id": "doc_001",
  "candidate_id": "cand_001",
  "audit_status": "review_required",
  "schema_checks": [],
  "field_checks": [],
  "section_checks": [],
  "evidence_coverage_checks": [],
  "missing_candidates": [],
  "conflicts": [],
  "quality_scores": {},
  "review_triggers": [],
  "summary": {}
}
```

---

## 8. Schema validation rules

The schema validator should check at minimum:

- top-level keys exist
- object fields contain objects
- list fields contain lists
- `emails`, `phones`, `skills`, `education`, `experience`, `projects`, `certifications`, and `languages` use the correct shape
- date fields match allowed formats such as `YYYY-MM` or `YYYY`
- confidence values are numeric and in allowed range
- boolean fields are actual booleans
- experience `end_date` is null only when `is_current` is true or equivalent logic is documented

### 8.1 Example schema check output

```json
{
  "check_id": "schema_001",
  "severity": "error",
  "field": "candidate_profile.experience[1].start_date",
  "issue": "Invalid date format",
  "expected": "YYYY-MM",
  "actual": "March 2022"
}
```

---

## 9. Field completeness rules

The audit should use heuristic detectors to estimate whether a field likely exists in the resume.

### 9.1 Contact completeness

Checks:

- email-like patterns present in source but missing in JSON
- phone-like patterns present in source but missing in JSON
- LinkedIn/GitHub/portfolio URLs present in source but missing in JSON

### 9.2 Experience completeness

Checks:

- company + title + date-range patterns detected in source
- compare detected role-block count with extracted `experience` count
- detect likely missing role entries

### 9.3 Education completeness

Checks:

- degree + institution + date patterns detected in source
- compare against `education` count

### 9.4 Certification completeness

Checks:

- certification phrases such as `Certified`, `Certification`, `AWS`, `Scrum`, `Google`, `Azure`, `PMP`
- compare against `certifications` array

### 9.5 Skills completeness

Checks:

- explicit skills block exists but extracted `skills` count is unexpectedly low
- tools repeatedly appear in experience/projects but are absent from `skills`

---

## 10. Section completeness rules

The audit should detect whether a resume section exists but was not properly converted.

Recommended section candidates:

- header / contact
- summary / objective
- skills
- experience
- education
- certifications
- projects
- links / portfolio
- languages

### 10.1 Example section warning

```json
{
  "check_id": "section_003",
  "severity": "warning",
  "section": "education",
  "issue": "Section heading detected but extracted education array is empty"
}
```

---

## 11. Evidence coverage audit

The platform should not only ask whether a field exists in JSON. It should also ask whether meaningful evidence chunks were mapped.

### 11.1 Forward coverage

For each extracted field, verify that:

- evidence chunk IDs exist
- referenced chunk IDs are valid
- chunk text actually supports the extracted field

### 11.2 Reverse coverage

For each meaningful chunk, verify that it is either:

- mapped to one or more JSON fields, or
- classified as intentionally unused / irrelevant

This is one of the strongest ways to detect silent extraction misses.

### 11.3 Example missing-evidence candidate

```json
{
  "field_family": "certifications",
  "source_chunk_id": "chunk_027",
  "resume_evidence": "AWS Certified Developer Associate",
  "issue": "Evidence present in chunk inventory but no mapped certification object exists"
}
```

---

## 12. Semantic missing-information audit

This audit should compare the source resume content and the extracted JSON semantically.

The goal is to find information that is explicitly present in the resume but absent or underrepresented in JSON.

### 12.1 Recommended outputs

The semantic auditor should return:

- likely missing fields
- suspiciously incomplete sections
- possible mismatches
- confidence for each audit finding

### 12.2 Suggested categories of semantic misses

- missing contact detail
- missing experience entry
- missing degree or institution
- missing certification
- missing project
- missing portfolio link
- missing key skill
- missing domain or tool evidence

### 12.3 Important rule

The semantic auditor must **not invent new data**.

It should only report likely omissions supported by source evidence.

---

## 13. Cross-parser consistency audit

If multiple extraction routes are available, compare them.

### 13.1 Compare fields such as:

- full name
- email
- phone
- number of experience entries
- company names
- degree names
- certification names
- top extracted skills

### 13.2 Agreement policy

If two parsers agree on a field, confidence increases.

If they disagree:

- keep both raw candidates if needed
- log a conflict
- lower confidence
- potentially trigger review

### 13.3 Example conflict object

```json
{
  "field": "candidate_profile.education[0].institution",
  "parser_a": "ABC Institute of Technology",
  "parser_b": "ABC University of Technology",
  "severity": "warning"
}
```

---

## 14. Quality scoring model

The audit system should compute a dedicated extraction-quality score. This is **not candidate scoring**.

### 14.1 Recommended score dimensions

- schema validity
- field completeness
- section completeness
- evidence mapping coverage
- parser agreement
- OCR quality if relevant

### 14.2 Example weighted formula

```text
overall_extraction_quality =
0.20 * schema_validity +
0.25 * field_completeness +
0.20 * section_completeness +
0.20 * evidence_coverage +
0.10 * parser_agreement +
0.05 * ocr_quality
```

### 14.3 Score scale

Recommended range:

```text
0.0 to 1.0
```

This score is only for extraction trustworthiness and workflow decisions.

---

## 15. Review triggers

The audit layer should trigger manual review when quality falls below policy thresholds.

### 15.1 Recommended review triggers

- extraction quality below threshold
- contact section missing critical fields
- experience section likely incomplete
- education heading detected but no education entries extracted
- meaningful certification evidence unmapped
- parser conflict on important fields
- OCR confidence too low
- too many unmapped meaningful chunks

### 15.2 Suggested severity levels

- `info`
- `warning`
- `error`
- `critical`

### 15.3 Example review trigger

```json
{
  "trigger_id": "review_001",
  "severity": "critical",
  "reason": "Three experience-like role blocks detected, but only one experience object extracted"
}
```

---

## 16. Human review policy

A flagged document should not always be rejected. Instead, the platform should support a review queue.

### 16.1 Review actions

Human reviewers may:

- approve the extraction as-is
- correct missing fields
- merge duplicate fields
- add missing experience or education entries
- confirm ambiguous dates
- mark false-positive warnings as resolved

### 16.2 Review output

The system should store:

- reviewer action
- corrected fields
- reason for correction
- timestamp
- audit issue resolution status

---

## 17. Recommended rule library

The audit engine should include reusable rule groups.

### 17.1 Regex and pattern rules

Use for:

- email detection
- phone detection
- URL detection
- date-range detection
- certification keyword detection

### 17.2 Section heuristics

Use for:

- section heading recognition
- experience block patterns
- education block patterns
- portfolio / links detection

### 17.3 Canonicalization checks

Use for:

- skill normalization mismatches
- duplicate or near-duplicate skills
- inconsistent degree naming
- malformed normalized location

### 17.4 Semantic audit rules

Use for:

- missing-field detection
- underrepresented sections
- weak evidence mapping warnings

---

## 18. Suggested audit workflow

Recommended operational flow:

1. run schema validation
2. run field-level completeness checks
3. run section completeness checks
4. run evidence coverage audit
5. run semantic missing-information audit
6. run cross-parser consistency audit if applicable
7. compute extraction-quality scores
8. assign review status
9. send low-quality cases to review queue

---

## 19. Example audit artifact

```json
{
  "audit_version": "1.0.0",
  "document_id": "doc_001",
  "candidate_id": "cand_001",
  "audit_status": "review_required",
  "missing_candidates": [
    {
      "field_family": "experience",
      "resume_evidence": "Business Analyst, XYZ Ltd, Jan 2021 - Jun 2024",
      "source_chunk_id": "chunk_041",
      "reason": "Detected role block not mapped into experience array",
      "confidence": 0.93
    },
    {
      "field_family": "certifications",
      "resume_evidence": "AWS Certified Cloud Practitioner",
      "source_chunk_id": "chunk_052",
      "reason": "Certification phrase detected in source but certification array is empty",
      "confidence": 0.88
    }
  ],
  "conflicts": [
    {
      "field": "candidate_profile.full_name",
      "parser_a": "John A. Doe",
      "parser_b": "John Doe",
      "severity": "warning"
    }
  ],
  "quality_scores": {
    "schema_validity": 1.0,
    "field_completeness": 0.78,
    "section_completeness": 0.74,
    "evidence_coverage": 0.69,
    "parser_agreement": 0.91,
    "ocr_quality": 0.84,
    "overall_extraction_quality": 0.80
  },
  "review_triggers": [
    {
      "severity": "critical",
      "reason": "Experience section likely incomplete"
    }
  ],
  "summary": {
    "human_action_recommended": true,
    "high_risk_sections": ["experience", "certifications"]
  }
}
```

---

## 20. Relationship to scoring

This audit specification must remain clearly separate from candidate scoring.

The audit score measures:

- how trustworthy the extraction is
- how complete the JSON is
- how much human review may be needed

It must not be confused with:

- candidate quality
- candidate fit score
- ranking score

However, the platform may enforce a policy such as:

- do not rank automatically if extraction quality is below threshold
- or rank provisionally with a warning

That policy should be defined at the system level.

---

## 21. What the system must never do

The audit layer must never:

- invent missing fields
- silently overwrite source evidence
- hide conflicts between parsers
- treat low-confidence guesses as confirmed facts
- confuse extraction quality with candidate quality

---

## 22. Final recommendation

Use `JSON_QUALITY_AUDIT_SPEC.md` as the formal contract for auditing extracted resume JSON before it enters high-trust scoring workflows.

The best implementation is a layered audit system that combines:

- schema checks
- completeness rules
- evidence coverage checks
- semantic missing-info detection
- cross-parser agreement
- quality scoring
- review triggers

That approach gives the platform a reliable way to answer the question:

**What important information was present in the resume but was missed, misread, or weakly captured in the extracted JSON?**
