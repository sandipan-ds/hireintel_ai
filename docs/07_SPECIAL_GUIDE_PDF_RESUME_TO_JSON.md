# Special Guide: Turning Mixed-Format Resume PDFs into Structured JSON

## 1. What you are really trying to solve

The problem is not just “extract text from PDF.” The real problem is:

- resumes come as native-text PDFs, scanned PDFs, mixed PDFs, and DOCX
- layouts vary: one-column, two-column, sidebars, icons, tables, graphics, portfolios, fancy headings
- the same field may appear in many forms, for example `Experience`, `Work History`, `Professional Journey`, or just role bullets under company names
- naive PDF text extractors often break reading order, merge columns, miss text in images, or destroy section structure

So the correct goal is not simple text extraction. The correct goal is:

**document understanding → section understanding → field normalization → evidence-backed JSON**

---

## 2. How systems like Claude or ChatGPT handle PDFs at a high level

Public docs do not expose every internal implementation detail, but the high-level pattern is clear.

OpenAI’s official API docs say models can accept PDF files as inputs and that the API extracts **both text and page images** from PDFs.<sup data-citation="1"></sup> Anthropic’s official Claude PDF docs say Claude can answer questions about **text, pictures, charts, and tables** in PDFs you provide.<sup data-citation="6"></sup>

That strongly suggests a **multimodal document understanding approach**, not a plain `pdftotext` style pipeline. In practice, the broad pattern is usually something like this:

1. detect whether the PDF already has text
2. also treat pages as visual documents
3. use OCR when needed
4. detect layout and reading order
5. recover document elements like paragraphs, headings, tables, and images
6. pass structured content into a language model for interpretation and normalization

So if you want something 90 percent similar with free tools, your architecture should imitate that pattern.

---

## 3. The key idea: do not use one library, use a routed pipeline

Do **not** build this as:

`PDF -> one parser -> final JSON`

Build it as:

`File classifier -> extraction route -> layout-aware text recovery -> section builder -> LLM/rule normalization -> validation -> JSON`

This is the single biggest design decision that will improve your results.

---

## 4. Recommended free / open-source stack

If you want a mostly free stack, this is the strongest practical combination.

### 4.1 Primary document parsing

Use **Docling** as a strong primary parsing layer for complex PDFs and structured extraction.<sup data-citation="11"></sup><sup data-citation="12"></sup>

Why:

- it is built for document understanding, not just raw text extraction
- it supports advanced PDF handling
- it is suitable for downstream AI / structured processing

### 4.2 Alternative / backup parser

Use **Unstructured** as a secondary parser or fallback path. Its partitioning system extracts structured elements from PDFs rather than giving you one flat text blob.<sup data-citation="16"></sup><sup data-citation="17"></sup>

Why:

- useful for element-level parsing
- good for chunking and section-aware processing
- helpful when you want paragraph/title/table separation

### 4.3 OCR for scanned/image resumes

Use **PaddleOCR** and/or **Surya** for scanned or image-heavy resumes. PaddleOCR is positioned as turning PDFs or images into structured data.<sup data-citation="21"></sup> Surya focuses on OCR, layout analysis, reading order, and table support for documents.<sup data-citation="26"></sup><sup data-citation="27"></sup>

Why:

- scanned resumes need OCR first
- layout-heavy resumes benefit from reading-order recovery
- Surya is especially interesting for document-oriented OCR instead of generic OCR only

### 4.4 Optional low-level PDF helpers

You can also keep these as support utilities:

- **PyMuPDF** for page-level access, rendering, and text layer checks
- **pdfplumber** for native text PDF inspection
- **python-docx** if you later want DOCX ingestion too

These are not enough alone, but they are useful utilities in the pipeline.

---

## 5. Best practical architecture for your project

Here is the architecture I recommend.

### Stage A: classify the input document

Before extraction, determine:

- is there a usable text layer?
- is it mostly scanned images?
- is it mixed?
- is it PDF or DOCX?
- how many columns appear on a page?
- are there visual sidebars or blocks?

A simple classifier can route into:

- **native-text path**
- **OCR path**
- **hybrid path**

### Stage B: recover layout-aware content

For native-text resumes:

- use Docling or Unstructured first
- preserve headings, paragraphs, tables, and reading order
- do not flatten the whole page too early

For scanned resumes:

- render pages to images
- run OCR with PaddleOCR or Surya
- run layout analysis and reading-order reconstruction
- merge OCR output into logical blocks

For mixed resumes:

- use native text where reliable
- OCR image-only regions or pages
- merge both outputs carefully

### Stage C: reconstruct logical sections

You need to convert raw blocks into sections such as:

- personal info
- summary
- skills
- experience
- education
- certifications
- projects
- links / portfolio
- languages

This is extremely important. Claude and ChatGPT feel “fluent” partly because they do not stop at text extraction; they interpret document structure.

### Stage D: normalize into canonical JSON

Once sections are built, convert them into your schema:

- contact
- skills
- education entries
- experience entries
- project entries
- certifications
- evidence chunks
- confidence metadata

### Stage E: validate and score extraction confidence

Before storing final JSON, run checks such as:

- valid email format
- valid phone format
- date ranges make sense
- no impossible overlaps unless explicitly allowed
- skills deduplicated and canonicalized
- suspicious empty sections flagged
- OCR confidence stored

This is how you get reliable output rather than beautiful but wrong JSON.

---

## 6. Why ChatGPT and Claude feel better than naive parsers

The reason they often feel much better is that they do not behave like simple PDF text readers.

They are closer to this pattern:

- read the document visually and textually
- understand document layout
- infer section semantics
- connect scattered evidence across the document
- normalize varied wording into standard concepts

For example, they can understand that these are all related to experience:

- `Experience`
- `Employment`
- `Work History`
- `Professional Background`
- role + company + dates shown without a heading

That is why your system also needs a **semantic normalization layer**, not just extraction.

---

## 7. The most important free-tool strategy: two-pass extraction

If you want 90 percent quality, use a **two-pass approach**.

### Pass 1: document recovery

Goal: recover the document faithfully.

Output:

- raw text blocks
- titles/headings
- tables if any
- page metadata
- section candidates
- OCR confidence
- reading order

### Pass 2: resume normalization

Goal: transform recovered content into resume JSON.

Output:

- canonical schema
- field-to-evidence mapping
- normalized dates
- canonical skill names
- confidence per field

Do not merge these into one step. Keep them separate.

---

## 8. Concrete routing logic you can implement

A very workable strategy is this.

### 8.1 If native text quality is good

Use:

- Docling first
- Unstructured as fallback
- optional low-level checks with PyMuPDF/pdfplumber

### 8.2 If page is scanned or text layer is missing

Use:

- page rendering
- Surya or PaddleOCR
- layout reconstruction
- then section extraction

### 8.3 If document is mixed

Use hybrid extraction:

- parse text layer where possible
- OCR only bad pages or bad regions
- merge blocks by page and region order

This saves time and improves quality.

---

## 9. A very important rule: preserve evidence, not just final fields

Do not only store:

```json
{
  "skills": ["Python", "SQL"]
}
```

Also store where the evidence came from.

For example:

```json
{
  "skills": [
    {
      "name_raw": "Python",
      "name_canonical": "Python",
      "confidence": 0.95,
      "evidence_chunk_ids": ["chunk_14", "chunk_27"]
    }
  ]
}
```

This will matter later for your JD matching and score explanations.

---

## 10. Suggested JSON output pattern

Your output should contain at least these top-level blocks:

```json
{
  "schema_version": "1.0.0",
  "candidate_id": "cand_001",
  "document": {
    "file_name": "resume.pdf",
    "file_type": "pdf",
    "ingestion_type": "native_pdf",
    "ocr_used": false,
    "parser_name": "docling+normalizer"
  },
  "candidate_profile": {
    "full_name": null,
    "emails": [],
    "phones": [],
    "locations": [],
    "skills": [],
    "education": [],
    "experience": [],
    "projects": [],
    "certifications": [],
    "languages": []
  },
  "normalized_features": {},
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
    "raw_text": ""
  }
}
```

---

## 11. How to build section reconstruction

This is where many systems fail.

You should not rely only on exact section names. Use a combination of:

- heading patterns
- font/position/layout hints if available
- lexical patterns
- nearby entities
- date ranges
- line grouping
- bullet styles

For example:

- if a block contains a company name, role title, and date range, it is likely an experience block even if the heading is missing
- if a block contains degree + institution + graduation date, it is likely education
- if a block is a short comma-separated group near the top or sidebar, it may be skills or contact info

This is exactly why layout-aware recovery matters.

---

## 12. Use a canonicalizer after extraction

After parsing, normalize common variants.

### Skills canonicalization

Examples:

- `Node Js` -> `Node.js`
- `Postgres` -> `PostgreSQL`
- `MS Excel` -> `Microsoft Excel`
- `PBI` -> `Power BI`

### Date canonicalization

Examples:

- `Jan 2022 - Present` -> `start_date=2022-01`, `end_date=null`, `is_current=true`
- `2021 to 2023` -> normalized monthless range rule

### Degree canonicalization

Examples:

- `B.Tech CSE`
- `Bachelor of Technology in Computer Science`
- `B.E. Computer Science`

These may map into related normalized degree families.

---

## 13. How to use an LLM properly here

The LLM should be used as a **normalizer and interpreter**, not as the only parser.

Bad approach:

- send the whole raw PDF text dump to the LLM
- ask “extract everything”
- trust output blindly

Better approach:

1. recover structured text and layout first
2. split into logical blocks
3. provide a fixed JSON schema
4. ask the model to fill only supported fields
5. require `null` or `[]` for missing values
6. optionally ask for field confidence and evidence references

A good prompt pattern is:

```text
You are a resume information extraction system.
Extract only facts explicitly supported by the provided resume content.
Return valid JSON matching the schema exactly.
If a field is missing, return null or [].
Do not invent any value.
For each populated field, prefer evidence from professional experience over summary keywords.
```

If sending chunks, also tell it which section each chunk belongs to.

---

## 14. If you want a fully free approach

A solid free pipeline can be:

1. **PyMuPDF** to inspect the PDF and render pages if needed
2. **Docling** as primary parser
3. **Unstructured** as fallback parser
4. **PaddleOCR** or **Surya** for scanned/image pages
5. custom Python logic for:
   - section grouping
   - date parsing
   - phone/email parsing
   - skill canonicalization
   - JSON assembly
6. optional LLM normalization if you have access to a low-cost or local model

If you truly want fully free and local, you can still do a lot without a paid API. But accuracy on tricky resumes will improve noticeably if you use at least some LLM normalization.

---

## 15. What 90 percent similarity actually looks like

If you want something “90 percent similar,” the realistic meaning is:

- very good on normal text resumes
- decent on multi-column resumes
- decent to strong on scanned resumes if OCR is good
- occasional misses on:
  - fancy sidebars
  - icon-only contact fields
  - heavy graphics
  - unusual portfolio layouts
  - deeply nested design resumes

That is normal. The way you make the system reliable is not by pretending extraction is perfect. You do it by adding:

- confidence scores
- fallback routes
- validation rules
- human review on low-confidence cases

---

## 16. Practical extraction heuristics that matter a lot

These are high-value heuristics.

### 16.1 Contact extraction

Look in the first page top region first.

Use regex plus cleanup for:

- email
- phone
- LinkedIn
- GitHub
- portfolio URL

### 16.2 Experience block detection

Identify repeated patterns of:

- title
- company
- date range
- bullet list

Use this pattern even if the heading says nothing obvious.

### 16.3 Skills extraction

Do not trust only one “Skills” section. Also gather skills from:

- experience bullets
- project descriptions
- certifications
- tools under portfolio projects

Then mark the source type, for example:

- explicit keyword listing
- professional usage
- project usage
- certification evidence

### 16.4 Education extraction

Use institution + degree + date clustering rather than heading-only logic.

### 16.5 Portfolio and design resumes

For creative roles, do not ignore URLs and project artifacts. Portfolio links may be critical evidence.

---

## 17. Recommended confidence strategy

Store confidence at multiple levels.

### Document-level confidence

How trustworthy was the full extraction overall?

Signals:

- OCR quality
- parser agreement
- text completeness
- section coverage

### Field-level confidence

How trustworthy is each extracted field?

Examples:

- full name confidence
- email confidence
- experience block confidence
- education confidence
- skills confidence

### Cross-parser confidence boost

A powerful trick is to compare outputs from two extraction routes.

If both routes agree on email, phone, name, and date ranges, raise confidence.
If they disagree, keep the raw values and add a warning.

---

## 18. Best strategy for reliability: parser ensemble

If accuracy matters more than speed, use an ensemble approach.

Example:

- run Docling
- run Unstructured
- if scanned, run OCR path too
- compare outputs
- build a merged canonical representation
- resolve conflicts with rules
- only use LLM on uncertain parts

This often works better than trusting one parser completely.

---

## 19. Suggested implementation flow in Python

```text
for each uploaded resume:
    detect file type
    inspect for native text layer
    if native text strong:
        parse with docling
        optionally parse with unstructured
    else:
        render pages
        run OCR with surya or paddleocr
        reconstruct reading order

    build logical blocks
    detect sections
    extract structured entities
    canonicalize skills, dates, degrees, links
    create evidence chunks with metadata
    map fields to chunk ids
    run validation checks
    assign confidence
    output final JSON
```

---

## 20. What not to do

Avoid these mistakes:

- relying only on `PyPDF2` or raw text dump libraries
- flattening all text before layout reconstruction
- trusting OCR text order blindly
- asking an LLM to parse an entire messy resume with no schema
- storing only final fields and not storing evidence
- mixing extraction logic with scoring logic
- assuming the Skills section is the only place skills appear

---

## 21. Best recommendation for your exact project

For your resume-shortlisting system, I would recommend this exact build order.

### Phase 1

Build a robust extraction contract and JSON schema.

### Phase 2

Implement routed extraction:

- native-text path
- OCR path
- hybrid path

### Phase 3

Implement section reconstruction and evidence chunks.

### Phase 4

Implement canonicalization and validation.

### Phase 5

Add LLM normalization only where rules are weak or ambiguity is high.

### Phase 6

Feed the structured output into your requirement-based scoring engine.

This keeps your system modular and explainable.

---

## 22. My strongest recommendation in one sentence

If you want Claude/ChatGPT-like PDF fluency with free tools, the closest practical method is:

**use a multimodal-style routed pipeline that combines layout-aware parsing, OCR for bad pages, section reconstruction, schema-based normalization, and confidence-backed JSON output rather than relying on one PDF text extractor alone.**

---

## 23. Final tool recommendation summary

If I had to choose one free-stack combination for you, it would be:

- **Docling** as the main parser<sup data-citation="11"></sup><sup data-citation="12"></sup>
- **Unstructured** as a secondary parser / fallback<sup data-citation="16"></sup><sup data-citation="17"></sup>
- **Surya** or **PaddleOCR** for scanned/layout-heavy resumes<sup data-citation="21"></sup><sup data-citation="26"></sup>
- custom Python normalization and validation
- optional LLM only for schema filling or ambiguity resolution

That is probably the best free-path to something close to the document fluency you are looking for.
