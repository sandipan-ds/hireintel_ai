# Graph Report - C:\Users\sandi\Desktop\ML Working Folder\hireintel_ai\src  (2026-07-08)

## Corpus Check
- 48 files · ~58,677 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 910 nodes · 1948 edges · 39 communities (33 shown, 6 thin omitted)
- Extraction: 73% EXTRACTED · 27% INFERRED · 0% AMBIGUOUS · INFERRED: 520 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Threshold Retrieval Core|Threshold Retrieval Core]]
- [[_COMMUNITY_Structured Profile + Total Experience|Structured Profile + Total Experience]]
- [[_COMMUNITY_Ranking Diff Investigator|Ranking Diff Investigator]]
- [[_COMMUNITY_Embedding Index Builder|Embedding Index Builder]]
- [[_COMMUNITY_Per-REQ SubQuery Retrieval|Per-REQ SubQuery Retrieval]]
- [[_COMMUNITY_Weight Config REST API|Weight Config REST API]]
- [[_COMMUNITY_Graded Code-Only Scorer|Graded Code-Only Scorer]]
- [[_COMMUNITY_Rubric Templates + LLMScoreCache|Rubric Templates + LLMScoreCache]]
- [[_COMMUNITY_Rubric LLM Scorer + Banded Years|Rubric LLM Scorer + Banded Years]]
- [[_COMMUNITY_RoleRequirement REST API|Role/Requirement REST API]]
- [[_COMMUNITY_Chunk Report Generator|Chunk Report Generator]]
- [[_COMMUNITY_RecursiveChunker|RecursiveChunker]]
- [[_COMMUNITY_Resume Parser Sectionizer|Resume Parser Sectionizer]]
- [[_COMMUNITY_DocumentAwareChunker (legacy)|DocumentAwareChunker (legacy)]]
- [[_COMMUNITY_CandidateRegistry|CandidateRegistry]]
- [[_COMMUNITY_SubQuery Parser|SubQuery Parser]]
- [[_COMMUNITY_SubQuery Cache Key + Batched Prompt|SubQuery Cache Key + Batched Prompt]]
- [[_COMMUNITY_InstituteCert Tier Lookup|Institute/Cert Tier Lookup]]
- [[_COMMUNITY_FastAPI HTMX Page Handlers|FastAPI HTMX Page Handlers]]
- [[_COMMUNITY_DB Models + Session|DB Models + Session]]
- [[_COMMUNITY_ScoreRank REST API|Score/Rank REST API]]
- [[_COMMUNITY_LLM Caller Factory (OllamaOpenCode)|LLM Caller Factory (Ollama/OpenCode)]]
- [[_COMMUNITY_Pydantic API Schemas|Pydantic API Schemas]]
- [[_COMMUNITY_Candidate ID Parsing + Errors|Candidate ID Parsing + Errors]]
- [[_COMMUNITY_JSON Config Export Service|JSON Config Export Service]]
- [[_COMMUNITY_Legacy ChunkIndex|Legacy ChunkIndex]]
- [[_COMMUNITY_Audit Flag Writer|Audit Flag Writer]]
- [[_COMMUNITY_Resume Parser Entry Point|Resume Parser Entry Point]]
- [[_COMMUNITY_OCR Hybrid PDF Bridge|OCR Hybrid PDF Bridge]]
- [[_COMMUNITY_Rubric Type Classifier|Rubric Type Classifier]]
- [[_COMMUNITY_App Startup + Healthcheck|App Startup + Healthcheck]]
- [[_COMMUNITY_Embedding Model Lazy Load|Embedding Model Lazy Load]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]

## God Nodes (most connected - your core abstractions)
1. `ChunkRecord` - 37 edges
2. `Role` - 29 edges
3. `RankingDiff` - 27 edges
4. `UnifiedItemEvaluation` - 27 edges
5. `UnifiedCategoryEvaluation` - 27 edges
6. `Any` - 26 edges
7. `Requirement` - 23 edges
8. `VectorIndex` - 23 edges
9. `UnifiedCandidateEvaluation` - 23 edges
10. `Session` - 22 edges

## Surprising Connections (you probably didn't know these)
- `ndarray` --uses--> `ChunkRecord`  [INFERRED]
  services/subquery_retrieval.py → rag/document_aware_chunker.py
- `Any` --uses--> `Requirement`  [INFERRED]
  api/pages.py → models/database.py
- `Any` --uses--> `Role`  [INFERRED]
  api/pages.py → models/database.py
- `HTMLResponse` --uses--> `Requirement`  [INFERRED]
  api/pages.py → models/database.py
- `HTMLResponse` --uses--> `Role`  [INFERRED]
  api/pages.py → models/database.py

## Import Cycles
- None detected.

## Communities (39 total, 6 thin omitted)

### Community 0 - "Threshold Retrieval Core"
Cohesion: 0.06
Nodes (79): ChunkRecord, One chunk of a resume, ready for embedding + retrieval.      The chunk carries, Any, ThresholdRetriever, load_default_retriever(), Threshold-based cosine retrieval for HireIntel AI (DEC-018, active 2026-07-05)., A chunk plus its cosine similarity to the query., Threshold-based cosine retriever (DEC-018, the active strategy).      Given a pr (+71 more)

### Community 1 - "Structured Profile + Total Experience"
Cohesion: 0.07
Nodes (52): list_available_configs(), List all weight config names available for a role., parse_temporal_context(), Parse a date range string into a temporal_context dict.      This is the deter, CertificationEntry, _compute_total_experience_years(), DegreeEntry, EmploymentEntry (+44 more)

### Community 2 - "Ranking Diff Investigator"
Cohesion: 0.06
Nodes (36): diff_from_pairs(), _format_sub_score_value(), investigate_case(), load_reasoning(), Any, Path, RankingDiff, Ranking diff: compare two rankings of the same role (DEC-026).  Given two ``List (+28 more)

### Community 3 - "Embedding Index Builder"
Cohesion: 0.06
Nodes (37): Namespace, _backup_existing(), build(), _chunk_metadata(), chunk_profile(), discover_profiles(), embed_texts(), _load_embedder() (+29 more)

### Community 4 - "Per-REQ SubQuery Retrieval"
Cohesion: 0.06
Nodes (35): embed_sub_queries(), _load_embed_model(), SubQuery, Per-REQ retrieval — embed the REQ's sub-query SET, retrieve chunks per sub-query, Embed each sub-query text with the chunk-index embedding model.      Args:, Retrieve unioned evidence chunks for one (candidate, REQ) pair.      Embeds each, Load the sentence-transformers model (lazy, cached)., retrieve_evidence_for_req() (+27 more)

### Community 5 - "Weight Config REST API"
Cohesion: 0.15
Nodes (45): create_configuration(), delete_configuration(), get_configuration(), get_weight_summary(), list_configurations(), Any, Session, API routes for weight configuration management. (+37 more)

### Community 6 - "Graded Code-Only Scorer"
Cohesion: 0.09
Nodes (38): Pattern, _aliases_for(), _detect_years_in_text(), evaluate_candidate(), evaluate_candidate_code_only_v2(), evaluate_role(), _expected_years_for(), extract_expected_years() (+30 more)

### Community 7 - "Rubric Templates + LLMScoreCache"
Cohesion: 0.12
Nodes (27): LLMScoreCache, get_rubric(), One sub-question within a rubric template.      Attributes:         key: Short i, Retrieve the rubric template for a dimension type.      Args:         dimension_, A complete rubric for one dimension type.      Attributes:         dimension_typ, RubricTemplate, SubQuestion, get_cache() (+19 more)

### Community 8 - "Rubric LLM Scorer + Banded Years"
Cohesion: 0.11
Nodes (26): _banded_years_ratio(), _build_rubric_prompt(), _default_sub_scores(), _evaluate_formula(), explain_score_from_cache(), _extract_json_lenient(), _format_employment_history(), get_rubric_formula_sub_questions() (+18 more)

### Community 9 - "Role/Requirement REST API"
Cohesion: 0.14
Nodes (26): get_role(), get_role_by_name(), get_role_requirements(), list_roles(), Any, Session, API routes for role and requirement management., Get all requirements for a role, optionally filtered by category. (+18 more)

### Community 10 - "Chunk Report Generator"
Cohesion: 0.12
Nodes (25): ChunkReport, ChunkStatistics, _compute_statistics(), _derive_findings(), _derive_recommendation(), generate_chunk_report(), _iter_jsonl(), _now_iso() (+17 more)

### Community 11 - "RecursiveChunker"
Cohesion: 0.12
Nodes (23): _apply_overlap(), _entry_to_text(), _hard_split(), max_overlap_for(), min_overlap_for(), Any, ChunkRecord, Recursive chunker for parsed resume profiles (DEC-019, active 2026-07-05).  Repl (+15 more)

### Community 12 - "Resume Parser Sectionizer"
Cohesion: 0.13
Nodes (25): _entry_has_signal(), extract_contact(), extract_education_entries(), extract_experience_entries(), extract_list_from_section(), extract_name(), extract_summary(), identify_section_heading() (+17 more)

### Community 13 - "DocumentAwareChunker (legacy)"
Cohesion: 0.10
Nodes (22): chunk_profile(), chunks_to_jsonl(), _classify_experience_type(), DocumentAwareChunker, _emit_section_chunks(), _entry_to_text(), _extract_skills_asserted(), _months_between() (+14 more)

### Community 14 - "CandidateRegistry"
Cohesion: 0.12
Nodes (13): CandidateRegistry, _normalize_path(), Any, Path, The candidate registry (DEC-025).      A ``CandidateRegistry`` wraps the on-disk, Load the registry from ``path``. Returns an empty registry if absent.          M, Persist the registry to its ``path``.          Atomic write via a temp file + re, Return the candidate id for ``source_path`` under ``role``.          If the sour (+5 more)

### Community 15 - "SubQuery Parser"
Cohesion: 0.13
Nodes (25): calculate_category_totals(), categorize_requirements(), _extract_category_and_type(), _extract_description(), _extract_requirements(), _extract_role_name(), _extract_sub_queries(), _extract_subquery_info() (+17 more)

### Community 16 - "SubQuery Cache Key + Batched Prompt"
Cohesion: 0.16
Nodes (20): _build_batched_prompt(), LLMScoreCache, make_cache_key(), parse_anchored_response(), _parse_batched_response(), _parse_single_value(), Any, Sub-query similarity retrieval for per-candidate scoring.  This module replaces (+12 more)

### Community 17 - "Institute/Cert Tier Lookup"
Cohesion: 0.15
Nodes (23): _check_flagged_institute(), get_certificate_tier_points(), get_flagged_institutes(), get_institute_tier_points(), is_institute_flagged(), _load_tier_db(), lookup_certificate_tier(), lookup_institute_tier() (+15 more)

### Community 18 - "FastAPI HTMX Page Handlers"
Cohesion: 0.24
Nodes (19): configure_page(), home(), htmx_configurations_list(), htmx_requirements_form(), htmx_roles_list(), htmx_save_weights(), htmx_validate_weights(), Session (+11 more)

### Community 19 - "DB Models + Session"
Cohesion: 0.13
Nodes (16): Any, DeclarativeBase, Base, get_db(), get_db_session(), Session, Database configuration and models for scalable weight configuration system.  Use, Weight configuration model - stores weight configs for each role/recruiter. (+8 more)

### Community 20 - "Score/Rank REST API"
Cohesion: 0.16
Nodes (18): CategoryScoreResponse, ItemScoreResponse, Session, rank_candidates(), RankResponse, Scoring API endpoints.  Bridges the recruiter weight-config UI to the determinis, Rank all candidates in a role against a saved weight config.      Iterates every, Score a single candidate against a saved weight config.      Returns the full ev (+10 more)

### Community 21 - "LLM Caller Factory (Ollama/OpenCode)"
Cohesion: 0.13
Nodes (14): get_default_caller(), get_rubric_caller(), LLMRubricCaller, _load_env(), OllamaRubricCaller, Any, Real LLM caller using the opencode.ai/zen/v1 OpenAI-compatible endpoint.  Reads, Get a module-level default LLM caller (lazy-initialized). (+6 more)

### Community 22 - "Pydantic API Schemas"
Cohesion: 0.17
Nodes (13): BaseModel, Config, DashboardResponse, Pydantic schemas for weight configuration API., Validate that weight items are provided., Validation request schema., Dashboard response schema., Base requirement schema. (+5 more)

### Community 23 - "Candidate ID Parsing + Errors"
Cohesion: 0.17
Nodes (14): Exception, CandidateRegistryError, _format_id(), InvalidCandidateIdError, _now_iso(), _parse_id(), Candidate registry: stable, role-encoded candidate identifiers (DEC-025).  Repla, Split a candidate id into ``(role, counter)``.      Raises:         InvalidCandi (+6 more)

### Community 24 - "JSON Config Export Service"
Cohesion: 0.20
Nodes (13): _build_interpretation(), delete_json_config(), export_config_to_json(), list_json_configs(), load_config_from_json(), Any, Path, JSON export service for weight configurations.  Saves weight configurations as J (+5 more)

### Community 25 - "Legacy ChunkIndex"
Cohesion: 0.21
Nodes (9): build_index_from_chunks_dir(), ChunkIndex, ChunkRecord, Path, Persist the index to disk for fast reload., Load the index from disk if it exists., Build the chunk index by scanning ``chunks_dir/<role>/*.jsonl``.      Skips alre, In-memory index of all chunks for fast similarity search. (+1 more)

### Community 26 - "Audit Flag Writer"
Cohesion: 0.24
Nodes (11): clear_flags(), Any, Path, Audit flag writer for the composed RAG scorer + experience parser (Track 2, DEC-, Append one no-evidence flag entry to the audit JSONL log.      Args:         can, Append one inferred-full-year flag entry to the audit JSONL log.      Track 7.2, Truncate the audit log. Used by tests to start each case cleanly.      Productio, Read all entries from the audit log. Used by tests + the dashboard.      Args: (+3 more)

### Community 27 - "Resume Parser Entry Point"
Cohesion: 0.21
Nodes (12): CandidateRegistry, fresh_registry(), Return a new in-memory registry (no path, no auto-save)., candidate_id_from_path(), extract_text_from_path(), parse_resume(), Path, Parse a resume from a file path into a structured profile.      The returned d (+4 more)

### Community 28 - "OCR Hybrid PDF Bridge"
Cohesion: 0.29
Nodes (10): extract_text_hybrid(), _extract_with_pdf2image_ocr(), _extract_with_pdfplumber(), _extract_with_pypdfium(), Path, Hybrid text extraction for PDF resumes.  This module is the optional PDF -> text, Extract text from scanned PDFs via ``pdf2image`` (Pre-Poppler).      Returns an, Extract plain text from a PDF using a hybrid strategy.      Args:         path: (+2 more)

### Community 29 - "Rubric Type Classifier"
Cohesion: 0.22
Nodes (9): all_rubric_types(), Anchor, is_code_only(), is_rubric_bound_llm(), Rubric templates — fixed, recruiter-visible scoring rules per dimension type.  P, One anchor point on an anchored scale.      Attributes:         value: The numer, Check whether a dimension type is scored code-only (no LLM).      Code-only dime, Check whether a dimension type requires the rubric-bound LLM judge.      Args: (+1 more)

### Community 30 - "App Startup + Healthcheck"
Cohesion: 0.25
Nodes (7): health_check(), FastAPI application for HireIntel AI Weight Configuration System., Initialize database on startup., Health check endpoint., startup_event(), init_db(), Initialize the database and create all tables.

### Community 31 - "Embedding Model Lazy Load"
Cohesion: 0.40
Nodes (5): embed_texts(), get_model(), ndarray, Lazy-load the sentence-transformers model., Embed a list of texts. Returns shape (n, 384).

## Knowledge Gaps
- **2 isolated node(s):** `Any`, `Config`
  These have ≤1 connection - possible missing edges or undocumented components.
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ChunkRecord` connect `Threshold Retrieval Core` to `Structured Profile + Total Experience`, `Rubric Templates + LLMScoreCache`, `RecursiveChunker`, `DocumentAwareChunker (legacy)`, `SubQuery Cache Key + Batched Prompt`, `Legacy ChunkIndex`, `Embedding Model Lazy Load`?**
  _High betweenness centrality (0.184) - this node is a cross-community bridge._
- **Why does `Role` connect `Score/Rank REST API` to `Role/Requirement REST API`, `FastAPI HTMX Page Handlers`, `DB Models + Session`, `Weight Config REST API`?**
  _High betweenness centrality (0.179) - this node is a cross-community bridge._
- **Are the 30 inferred relationships involving `ChunkRecord` (e.g. with `Any` and `ChunkRecord`) actually correct?**
  _`ChunkRecord` has 30 INFERRED edges - model-reasoned connections that need verification._
- **Are the 25 inferred relationships involving `Role` (e.g. with `Any` and `Session`) actually correct?**
  _`Role` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Are the 20 inferred relationships involving `UnifiedItemEvaluation` (e.g. with `ChunkRecord` and `ScoredChunk`) actually correct?**
  _`UnifiedItemEvaluation` has 20 INFERRED edges - model-reasoned connections that need verification._
- **Are the 20 inferred relationships involving `UnifiedCategoryEvaluation` (e.g. with `ChunkRecord` and `ScoredChunk`) actually correct?**
  _`UnifiedCategoryEvaluation` has 20 INFERRED edges - model-reasoned connections that need verification._
- **What connects `API module for HireIntel AI.`, `FastAPI application for HireIntel AI Weight Configuration System.`, `Initialize database on startup.` to the rest of the system?**
  _373 weakly-connected nodes found - possible documentation gaps or missing edges._