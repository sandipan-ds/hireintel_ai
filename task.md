# Stage 3 — PDF Resume → JSON Extraction Tasks

## 1. Setup & Package Structure
- [ ] Create `src/resume_parsing/extraction/` package with `__init__.py`
- [ ] Add new dependency packages to `requirements.txt`

## 2. Extraction Pipeline Modules
- [ ] Implement `file_classifier.py` (`classify_file`, `FileType` enum)
- [ ] Implement `docling_parser.py` (`extract_with_docling`)
- [ ] Implement `unstructured_parser.py` (`extract_with_unstructured`)
- [ ] Implement `ocr_parser.py` (`extract_with_ocr` using PaddleOCR + Surya)
- [ ] Implement `section_builder.py` (`build_sections` into 7 canonical sections)
- [ ] Implement `llm_normalizer.py` (regex for contact, Ollama `qwen2.5:3b` LLM for date/experience/skills/education normalization)
- [ ] Implement `schema_validator.py` (validation per schema, confidence score calculation)
- [ ] Implement `pipeline.py` (`extract_resume` orchestrator)

## 3. Batch Extraction & Re-indexing
- [ ] Create `scripts/batch_extract_resumes.py` to extract all 721 resumes to JSON
- [ ] Run extraction and save JSONs to `data/processed/<role>/<candidate_id>.json`
- [ ] Rebuild embedding index over newly parsed recursive chunks

## 4. Verification & Testing
- [ ] Write unit tests: `test_file_classifier.py`, `test_section_builder.py`, `test_schema_validator.py`
- [ ] Write integration test: `test_extraction_pipeline.py`
- [ ] Run batch scorer and verify candidate scores improve
