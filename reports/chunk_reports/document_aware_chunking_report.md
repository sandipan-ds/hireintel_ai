# Chunk Report — document_aware_chunking

- **Schema version:** 1.0
- **Created at:** 2026-07-05T13:45:00Z
- **Source:** pre-DEC-019 production chunks (721 resumes, 8 roles)
- **Chunker:** DocumentAwareChunker
- **Folder:** `data\document_aware_chunking`

## Config

- **max_chunk_chars:** `1200`
- **split_overlap_chars:** `120`

## Chunk statistics

- **Total chunks:** 6377
- **Total resumes:** 721
- **Chunks per resume:** mean=8.84, median=8.0, min=0, max=77, p95=21

### Chunks per role

| Role | Chunks |
| --- | ---: |
| SalesManager | 1339 |
| BusinessAnalyst | 1291 |
| SrPythonDeveloper | 1055 |
| WebDesigning | 926 |
| SQLDeveloper | 629 |
| JavaDeveloper | 606 |
| DataScience | 426 |
| ReactDeveloper | 105 |

- **Chunks with `section_type=''`:** 3136
- **`section_type=''` rate:** 49.2%

### Section type distribution

| Section type | Count |
| --- | ---: |
| (empty) | 3136 |
| experience | 1780 |
| education | 1021 |
| projects | 440 |

## Key findings

- 49.2% of chunks have section_type='' and are invisible to Section-Routed retrieval (DEC-015 finding). This is the empirical justification for retiring the DocumentAwareChunker.
- Chunks per resume: mean=8.84, median=8.0, min=0, max=77, p95=21.
- Largest role bucket: SalesManager with 1339 chunks.

## Recommendation

Retire DocumentAwareChunker as the active strategy. The 40%+ missing-section_type rate makes Section-Routed retrieval unreliable (DEC-019, DEC-015).
