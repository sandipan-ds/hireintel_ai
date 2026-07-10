# Codebase Map

> **Auto-generated** from `graphify-out/cache/ast/` AST analysis.
> Re-generate: `python scripts/generate_codebase_map.py`
>
> Each section: defined classes/functions (with line numbers),
> internal module dependencies, third-party dependencies, and
> which modules reference symbols from this module.

---

## Module Index

| Module | Classes | Functions | Internal deps |
|--------|---------|-----------|---------------|
| `scripts/audit_llm_hallucination.py` | 0 | 0 | 7 |
| `scripts/backfill_candidate_registry.py` | 1 | 4 | 1 |
| `scripts/diff_rankings.py` | 3 | 6 | 1 |
| `scripts/dump_profile.py` | 0 | 0 | 0 |
| `scripts/full_trace_years.py` | 0 | 0 | 1 |
| `scripts/init_database.py` | 0 | 1 | 2 |
| `scripts/investigate_zero_evidence.py` | 0 | 0 | 0 |
| `scripts/score_batch_composed.py` | 6 | 9 | 9 |
| `scripts/start_mlflow_server.py` | 0 | 2 | 1 |
| `scripts/start_server.py` | 0 | 1 | 0 |
| `scripts/test_batched.py` | 0 | 0 | 2 |
| `scripts/trace_sq_scoring.py` | 0 | 0 | 2 |
| `api/__init__.py` | 0 | 0 | 0 |
| `api/app.py` | 0 | 2 | 1 |
| `api/pages.py` | 4 | 8 | 2 |
| `api/roles.py` | 5 | 5 | 3 |
| `api/scoring.py` | 6 | 4 | 2 |
| `api/weights.py` | 10 | 8 | 3 |
| `audit/__init__.py` | 0 | 0 | 0 |
| `audit/no_evidence_flags.py` | 2 | 4 | 0 |
| `eval/__init__.py` | 0 | 0 | 0 |
| `eval/ranking_diff.py` | 3 | 28 | 0 |
| `models/database.py` | 8 | 8 | 0 |
| `rag/__init__.py` | 0 | 0 | 3 |
| `rag/build_index.py` | 4 | 10 | 2 |
| `rag/document_aware_chunker.py` | 3 | 12 | 0 |
| `rag/per_req_retrieval.py` | 4 | 3 | 1 |
| `rag/recursive_chunker.py` | 3 | 11 | 1 |
| `rag/retriever.py` | 5 | 14 | 0 |
| `rag/section_routed.py` | 3 | 5 | 1 |
| `rag/subquery_cache.py` | 3 | 19 | 1 |
| `reporting/__init__.py` | 0 | 0 | 0 |
| `reporting/chunk_report.py` | 4 | 11 | 0 |
| `reporting/rank_stability.py` | 3 | 20 | 0 |
| `resume_parsing/__init__.py` | 0 | 0 | 0 |
| `resume_parsing/candidate_registry.py` | 7 | 18 | 0 |
| `resume_parsing/ocr.py` | 1 | 4 | 0 |
| `resume_parsing/parser.py` | 3 | 19 | 0 |
| `resume_parsing/structured_profile.py` | 5 | 8 | 2 |
| `schemas/weight_config.py` | 20 | 1 | 0 |
| `scoring/__init__.py` | 0 | 0 | 0 |
| `scoring/graded_scorer.py` | 8 | 26 | 0 |
| `scoring/rubric_scorer.py` | 5 | 13 | 2 |
| `scoring/rubrics.py` | 3 | 6 | 0 |
| `scoring/tier_lookup.py` | 2 | 10 | 0 |
| `scoring/unified_scorer.py` | 11 | 22 | 11 |
| `services/json_export.py` | 2 | 5 | 0 |
| `services/llm_caller.py` | 3 | 7 | 0 |
| `services/mlflow_wiring.py` | 5 | 12 | 0 |
| `services/scoring_pipeline.py` | 7 | 13 | 5 |
| `services/scoring_subquery.py` | 4 | 7 | 3 |
| `services/subquery_parser.py` | 2 | 11 | 0 |
| `services/subquery_retrieval.py` | 6 | 20 | 1 |

---

## `scripts.audit_llm_hallucination`
**File:** [`scripts/audit_llm_hallucination.py`](../scripts/audit_llm_hallucination.py)

**Imports from (internal modules):**
- [`rag/per_req_retrieval.py`](../src/rag/per_req_retrieval.py)
- [`rag/retriever.py`](../src/rag/retriever.py)
- [`rag/section_routed.py`](../src/rag/section_routed.py)
- [`rag/subquery_cache.py`](../src/rag/subquery_cache.py)
- [`scoring/rubric_scorer.py`](../src/scoring/rubric_scorer.py)
- [`services/llm_caller.py`](../src/services/llm_caller.py)
- [`services/subquery_parser.py`](../src/services/subquery_parser.py)

---

## `scripts.backfill_candidate_registry`
**File:** [`scripts/backfill_candidate_registry.py`](../scripts/backfill_candidate_registry.py)

**Classes:**
- `Path` — L117

**Functions / Methods:**
- `_iter_existing_candidates()` — L67
- `_is_candidate_profile_path()` — L117
- `backfill()` — L131
- `main()` — L216

**Imports from (internal modules):**
- [`resume_parsing/candidate_registry.py`](../src/resume_parsing/candidate_registry.py)

**Referenced by:**
- `scripts/start_mlflow_server.py`
- `rag/retriever.py`
- `scoring/unified_scorer.py`
- `services/scoring_subquery.py`

---

## `scripts.diff_rankings`
**File:** [`scripts/diff_rankings.py`](../scripts/diff_rankings.py)

**Classes:**
- `Namespace` — L161
- `RankingDiff` — L218
- `Path` — L84

**Functions / Methods:**
- `_normalize_label()` — L73
- `_load_ranking_from_json()` — L84
- `_load_id_file()` — L131
- `_resolve_inputs()` — L161
- `_cases_to_investigate()` — L218
- `main()` — L236

**Imports from (internal modules):**
- [`eval/ranking_diff.py`](../src/eval/ranking_diff.py)

**Referenced by:**
- `scripts/start_mlflow_server.py`
- `rag/retriever.py`
- `scoring/unified_scorer.py`
- `services/scoring_subquery.py`

---

## `scripts.dump_profile`
**File:** [`scripts/dump_profile.py`](../scripts/dump_profile.py)

---

## `scripts.full_trace_years`
**File:** [`scripts/full_trace_years.py`](../scripts/full_trace_years.py)

**Imports from (internal modules):**
- [`scoring/graded_scorer.py`](../src/scoring/graded_scorer.py)

---

## `scripts.init_database`
**File:** [`scripts/init_database.py`](../scripts/init_database.py)

**Functions / Methods:**
- `initialize_database()` — L16

**Imports from (internal modules):**
- [`models/database.py`](../src/models/database.py)
- [`services/subquery_parser.py`](../src/services/subquery_parser.py)

---

## `scripts.investigate_zero_evidence`
**File:** [`scripts/investigate_zero_evidence.py`](../scripts/investigate_zero_evidence.py)

---

## `scripts.score_batch_composed`
**File:** [`scripts/score_batch_composed.py`](../scripts/score_batch_composed.py)

**Classes:**
- `Path` — L128
- `ThresholdRetriever` — L165
- `SubQueryCache` — L165
- `Any` — L165
- `Namespace` — L311
- `PipelineParams` — L311

**Functions / Methods:**
- `discover_roles()` — L112
- `find_weight_config()` — L128
- `iter_candidate_files()` — L142
- `score_role()` — L165
- `.__enter__()` — L305
- `.__exit__()` — L307
- `_build_pipeline_params()` — L311
- `_log_run_to_mlflow()` — L335
- `main()` — L372

**Imports from (internal modules):**
- [`rag/per_req_retrieval.py`](../src/rag/per_req_retrieval.py)
- [`rag/recursive_chunker.py`](../src/rag/recursive_chunker.py)
- [`rag/retriever.py`](../src/rag/retriever.py)
- [`rag/subquery_cache.py`](../src/rag/subquery_cache.py)
- [`resume_parsing/structured_profile.py`](../src/resume_parsing/structured_profile.py)
- [`scoring/unified_scorer.py`](../src/scoring/unified_scorer.py)
- [`services/llm_caller.py`](../src/services/llm_caller.py)
- [`services/mlflow_wiring.py`](../src/services/mlflow_wiring.py)
- [`services/subquery_parser.py`](../src/services/subquery_parser.py)

**Referenced by:**
- `scripts/start_mlflow_server.py`
- `rag/retriever.py`
- `scoring/unified_scorer.py`
- `services/scoring_subquery.py`

---

## `scripts.start_mlflow_server`
**File:** [`scripts/start_mlflow_server.py`](../scripts/start_mlflow_server.py)

**Functions / Methods:**
- `build_command()` — L36
- `main()` — L62

**Imports from (internal modules):**
- [`services/mlflow_wiring.py`](../src/services/mlflow_wiring.py)

---

## `scripts.start_server`
**File:** [`scripts/start_server.py`](../scripts/start_server.py)

**Functions / Methods:**
- `main()` — L11

---

## `scripts.test_batched`
**File:** [`scripts/test_batched.py`](../scripts/test_batched.py)

**Imports from (internal modules):**
- [`services/llm_caller.py`](../src/services/llm_caller.py)
- [`services/scoring_pipeline.py`](../src/services/scoring_pipeline.py)

---

## `scripts.trace_sq_scoring`
**File:** [`scripts/trace_sq_scoring.py`](../scripts/trace_sq_scoring.py)

**Imports from (internal modules):**
- [`scoring/unified_scorer.py`](../src/scoring/unified_scorer.py)
- [`services/subquery_parser.py`](../src/services/subquery_parser.py)

---

## `api.__init__`
**File:** [`api/__init__.py`](../src/api/__init__.py)

---

## `api.app`
**File:** [`api/app.py`](../src/api/app.py)

**Functions / Methods:**
- `startup_event()` — L31
- `health_check()` — L37

**Imports from (internal modules):**
- [`models/database.py`](../src/models/database.py)

**Third-party dependencies:**
- `fastapi`
- `fastapi_staticfiles`
- `uvicorn`

---

## `api.pages`
**File:** [`api/pages.py`](../src/api/pages.py)

**Classes:**
- `Any` — L27
- `HTMLResponse` — L27
- `Request` — L35
- `Session` — L35

**Functions / Methods:**
- `_render()` — L27
- `home()` — L35
- `configure_page()` — L42
- `htmx_roles_list()` — L49
- `htmx_requirements_form()` — L56
- `htmx_validate_weights()` — L87
- `htmx_save_weights()` — L151
- `htmx_configurations_list()` — L259

**Imports from (internal modules):**
- [`models/database.py`](../src/models/database.py)
- [`services/json_export.py`](../src/services/json_export.py)

**Third-party dependencies:**
- `fastapi`
- `fastapi_responses`
- `jinja2`
- `sqlalchemy_orm`

---

## `api.roles`
**File:** [`api/roles.py`](../src/api/roles.py)

**Classes:**
- `Any` — L154
- `Session` — L23
- `RoleListResponse` — L23
- `RoleResponse` — L51
- `RequirementListResponse` — L99

**Functions / Methods:**
- `list_roles()` — L23
- `get_role()` — L51
- `get_role_by_name()` — L75
- `get_role_requirements()` — L99
- `sync_roles_from_subquery()` — L154

**Imports from (internal modules):**
- [`models/database.py`](../src/models/database.py)
- [`schemas/weight_config.py`](../src/schemas/weight_config.py)
- [`services/subquery_parser.py`](../src/services/subquery_parser.py)

**Third-party dependencies:**
- `fastapi`
- `sqlalchemy_orm`

---

## `api.scoring`
**File:** [`api/scoring.py`](../src/api/scoring.py)

**Classes:**
- `BaseModel` — 
- `Session` — L104
- `ItemScoreResponse` — L37
- `CategoryScoreResponse` — L53
- `ScoreCandidateResponse` — L62
- `RankResponse` — L75

**Functions / Methods:**
- `list_available_configs()` — L89
- `rank_candidates()` — L104
- `score_one_candidate()` — L163
- `_to_response()` — L199

**Imports from (internal modules):**
- [`models/database.py`](../src/models/database.py)
- [`services/scoring_pipeline.py`](../src/services/scoring_pipeline.py)

**Third-party dependencies:**
- `fastapi`
- `pydantic`
- `sqlalchemy_orm`

---

## `api.weights`
**File:** [`api/weights.py`](../src/api/weights.py)

**Classes:**
- `Session` — L109
- `WeightConfigurationListResponse` — L109
- `WeightConfigurationResponse` — L185
- `WeightConfigurationCreate` — L243
- `WeightConfigurationUpdate` — L296
- `Any` — L343
- `Requirement` — L36
- `WeightItemCreate` — L36
- `ValidationResponse` — L36
- `WeightSummary` — L389

**Functions / Methods:**
- `_validate_weight_configuration()` — L36
- `list_configurations()` — L109
- `get_configuration()` — L185
- `create_configuration()` — L243
- `update_configuration()` — L296
- `delete_configuration()` — L343
- `validate_configuration()` — L373
- `get_weight_summary()` — L389

**Imports from (internal modules):**
- [`models/database.py`](../src/models/database.py)
- [`schemas/weight_config.py`](../src/schemas/weight_config.py)
- [`services/json_export.py`](../src/services/json_export.py)

**Third-party dependencies:**
- `fastapi`
- `pydantic`
- `sqlalchemy_orm`

**Referenced by:**
- `scripts/init_database.py`
- `api/roles.py`

---

## `audit.__init__`
**File:** [`audit/__init__.py`](../src/audit/__init__.py)

---

## `audit.no_evidence_flags`
**File:** [`audit/no_evidence_flags.py`](../src/audit/no_evidence_flags.py)

**Classes:**
- `Path` — L95
- `Any` — L95

**Functions / Methods:**
- `write_flag()` — L95
- `write_inferred_full_year_flag()` — L157
- `clear_flags()` — L240
- `read_flags()` — L253

**Referenced by:**
- `scripts/start_mlflow_server.py`
- `rag/retriever.py`
- `resume_parsing/structured_profile.py`
- `scoring/unified_scorer.py`
- `services/scoring_subquery.py`

---

## `eval.__init__`
**File:** [`eval/__init__.py`](../src/eval/__init__.py)

---

## `eval.ranking_diff`
**File:** [`eval/ranking_diff.py`](../src/eval/ranking_diff.py)

**Classes:**
- `Any` — L239
- `Path` — L288
- `RankingDiff` — L35

**Functions / Methods:**
- `.baseline_rank()` — L74
- `.current_rank()` — L79
- `.baseline_score()` — L84
- `.current_score()` — L88
- `.total_candidates()` — L92
- `.big_swap_threshold()` — L100
- `.rank_delta()` — L114
- `.score_delta()` — L127
- `.shared_candidates()` — L135
- `.only_in_baseline()` — L140
- `.only_in_current()` — L143
- `.top_k()` — L150
- `.new_in_top_k()` — L157
- `.dropped_from_top_k()` — L162
- `.rank_changes_sorted()` — L167
- `.average_rank_change()` — L183
- `.max_rank_change()` — L188
- `.categorize()` — L200
- `.summary_dict()` — L239
- `.case_dict()` — L263
- `.to_dict()` — L271
- `load_reasoning()` — L288
- `_summarize_reasoning()` — L340
- `_format_sub_score_value()` — L364
- `investigate_case()` — L372
- `write_diff_report()` — L414
- `_render_markdown()` — L473
- `diff_from_pairs()` — L595

**Referenced by:**
- `scripts/diff_rankings.py`
- `scripts/start_mlflow_server.py`
- `rag/retriever.py`
- `scoring/unified_scorer.py`
- `services/scoring_subquery.py`

---

## `models.database`
**File:** [`models/database.py`](../src/models/database.py)

**Classes:**
- `DeclarativeBase` — 
- `WeightConfiguration` — L116
- `WeightItem` — L144
- `Session` — L176
- `Base` — L42
- `Role` — L47
- `Requirement` — L72
- `Recruiter` — L97

**Functions / Methods:**
- `.__repr__()` — L68
- `.__repr__()` — L93
- `.__repr__()` — L112
- `.__repr__()` — L140
- `.__repr__()` — L165
- `init_db()` — L170
- `get_db()` — L176
- `get_db_session()` — L185

**Third-party dependencies:**
- `sqlalchemy`
- `sqlalchemy_orm`

**Referenced by:**
- `scripts/init_database.py`
- `api/app.py`
- `api/pages.py`
- `api/roles.py`
- `api/weights.py`

---

## `rag.__init__`
**File:** [`rag/__init__.py`](../src/rag/__init__.py)

**Imports from (internal modules):**
- [`rag/document_aware_chunker.py`](../src/rag/document_aware_chunker.py)
- [`rag/recursive_chunker.py`](../src/rag/recursive_chunker.py)
- [`rag/retriever.py`](../src/rag/retriever.py)

---

## `rag.build_index`
**File:** [`rag/build_index.py`](../src/rag/build_index.py)

**Classes:**
- `Path` — L108
- `Any` — L167
- `RecursiveChunker` — L167
- `Namespace` — L546

**Functions / Methods:**
- `discover_profiles()` — L108
- `chunk_profile()` — L167
- `_load_embedder()` — L205
- `embed_texts()` — L222
- `_backup_existing()` — L263
- `write_index()` — L308
- `_chunk_metadata()` — L364
- `build()` — L386
- `_parse_args()` — L546
- `main()` — L595

**Imports from (internal modules):**
- [`rag/recursive_chunker.py`](../src/rag/recursive_chunker.py)
- [`rag/retriever.py`](../src/rag/retriever.py)

**Third-party dependencies:**
- `numpy`

**Referenced by:**
- `scripts/start_mlflow_server.py`
- `rag/retriever.py`
- `scoring/unified_scorer.py`
- `services/scoring_subquery.py`

---

## `rag.document_aware_chunker`
**File:** [`rag/document_aware_chunker.py`](../src/rag/document_aware_chunker.py)

**Classes:**
- `Any` — L158
- `ChunkRecord` — L319
- `DocumentAwareChunker` — L725

**Functions / Methods:**
- `_parse_single_date()` — L96
- `_months_between()` — L134
- `parse_temporal_context()` — L158
- `_extract_skills_asserted()` — L255
- `_classify_experience_type()` — L288
- `.to_dict()` — L344
- `chunk_profile()` — L369
- `chunks_to_jsonl()` — L589
- `_entry_to_text()` — L601
- `_emit_section_chunks()` — L623
- `.__init__()` — L742
- `.chunk_profile()` — L750

**Referenced by:**
- `resume_parsing/structured_profile.py`

---

## `rag.per_req_retrieval`
**File:** [`rag/per_req_retrieval.py`](../src/rag/per_req_retrieval.py)

**Classes:**
- `ThresholdRetriever` — L136
- `Any` — L136
- `ScoredChunk` — L136
- `SubQuery` — L97

**Functions / Methods:**
- `_load_embed_model()` — L84
- `embed_sub_queries()` — L97
- `retrieve_evidence_for_req()` — L136

**Imports from (internal modules):**
- [`rag/retriever.py`](../src/rag/retriever.py)

**Referenced by:**
- `rag/subquery_cache.py`
- `scoring/unified_scorer.py`

---

## `rag.recursive_chunker`
**File:** [`rag/recursive_chunker.py`](../src/rag/recursive_chunker.py)

**Classes:**
- `RecursiveChunker` — L276
- `Any` — L340
- `ChunkRecord` — L340

**Functions / Methods:**
- `min_overlap_for()` — L76
- `max_overlap_for()` — L87
- `recursive_split_text()` — L106
- `_split_recursive()` — L177
- `_hard_split()` — L241
- `_apply_overlap()` — L254
- `.__init__()` — L307
- `.chunk_text()` — L340
- `.chunk_profile()` — L410
- `_renumber_chunks()` — L533
- `_entry_to_text()` — L547

**Imports from (internal modules):**
- [`rag/document_aware_chunker.py`](../src/rag/document_aware_chunker.py)

---

## `rag.retriever`
**File:** [`rag/retriever.py`](../src/rag/retriever.py)

**Classes:**
- `IndexedChunk` — L110
- `VectorIndex` — L119
- `Any` — L191
- `ScoredChunk` — L260
- `ThresholdRetriever` — L269

**Functions / Methods:**
- `.__init__()` — L140
- `.add()` — L155
- `.__len__()` — L173
- `.dim()` — L177
- `.chunk_ids()` — L183
- `.texts()` — L187
- `.metadatas()` — L191
- `.cosine()` — L194
- `.save_npz()` — L220
- `.load_npz()` — L234
- `.__init__()` — L297
- `.retrieve_scored()` — L315
- `.retrieve()` — L392
- `load_default_retriever()` — L412

**Third-party dependencies:**
- `numpy`

**Referenced by:**
- `rag/build_index.py`

---

## `rag.section_routed`
**File:** [`rag/section_routed.py`](../src/rag/section_routed.py)

**Classes:**
- `SectionEvidence` — L176
- `Any` — L203
- `ChunkRecord` — L306

**Functions / Methods:**
- `.to_dict()` — L203
- `route_requirement_to_sections()` — L220
- `classify_requirement_type()` — L236
- `section_routed_retrieval()` — L306
- `retrieve_evidence_for_requirement()` — L383

**Imports from (internal modules):**
- [`rag/document_aware_chunker.py`](../src/rag/document_aware_chunker.py)

**Referenced by:**
- `scoring/unified_scorer.py`
- `services/scoring_subquery.py`

---

## `rag.subquery_cache`
**File:** [`rag/subquery_cache.py`](../src/rag/subquery_cache.py)

**Classes:**
- `Path` — L114
- `SubQueryCache` — L147
- `SubQuery` — L377

**Functions / Methods:**
- `_sha256()` — L109
- `_file_sha256()` — L114
- `_utc_now_iso()` — L125
- `_cache_key()` — L130
- `_subquery_file_for_role()` — L142
- `.__init__()` — L161
- `.size()` — L189
- `.is_dirty()` — L194
- `.__len__()` — L198
- `.__contains__()` — L201
- `.load()` — L209
- `.flush()` — L309
- `._write_manifest_jsonl()` — L359
- `.lookup()` — L369
- `.get_or_encode()` — L377
- `._add_entry()` — L438
- `.preencode_role()` — L473
- `.preencode_all_roles()` — L517
- `.wrap_embed_sub_queries()` — L545

**Imports from (internal modules):**
- [`rag/per_req_retrieval.py`](../src/rag/per_req_retrieval.py)

**Third-party dependencies:**
- `numpy`

**Referenced by:**
- `scripts/start_mlflow_server.py`
- `rag/retriever.py`
- `scoring/unified_scorer.py`
- `services/scoring_subquery.py`

---

## `reporting.__init__`
**File:** [`reporting/__init__.py`](../src/reporting/__init__.py)

---

## `reporting.chunk_report`
**File:** [`reporting/chunk_report.py`](../src/reporting/chunk_report.py)

**Classes:**
- `Path` — L160
- `ChunkStatistics` — L40
- `Any` — L53
- `ChunkReport` — L58

**Functions / Methods:**
- `.to_dict()` — L53
- `.to_dict()` — L72
- `generate_chunk_report()` — L84
- `_now_iso()` — L153
- `_compute_statistics()` — L160
- `_percentile()` — L209
- `_iter_jsonl()` — L223
- `_derive_findings()` — L247
- `_derive_recommendation()` — L281
- `write_json_report()` — L305
- `write_markdown_report()` — L314

**Referenced by:**
- `scripts/start_mlflow_server.py`
- `rag/retriever.py`
- `scoring/unified_scorer.py`
- `services/scoring_subquery.py`

---

## `reporting.rank_stability`
**File:** [`reporting/rank_stability.py`](../src/reporting/rank_stability.py)

**Classes:**
- `Path` — L619
- `RankStabilityReport` — L68
- `Any` — L95

**Functions / Methods:**
- `.to_dict()` — L95
- `top_k_jaccard()` — L104
- `rank_shift_stats()` — L134
- `distribution_correlations()` — L164
- `newcomer_drop_rates()` — L201
- `_extract_rank_pair()` — L245
- `_accumulate_pair()` — L268
- `_hp_axis_explained_variance()` — L303
- `_r_squared_for_axis()` — L352
- `_derive_flags()` — L401
- `compute_rank_stability()` — L449
- `_accumulate_all_pairs()` — L534
- `_now_iso()` — L586
- `load_study_file()` — L593
- `_derive_output_path()` — L619
- `write_stability_report()` — L643
- `_render_markdown()` — L679
- `_render_metric_sections()` — L705
- `_render_hp_axis_table()` — L742
- `_render_flags_section()` — L761

**Third-party dependencies:**
- `numpy`
- `scipy_stats`

**Referenced by:**
- `scripts/start_mlflow_server.py`
- `rag/retriever.py`
- `scoring/unified_scorer.py`
- `services/scoring_subquery.py`

---

## `resume_parsing.__init__`
**File:** [`resume_parsing/__init__.py`](../src/resume_parsing/__init__.py)

---

## `resume_parsing.candidate_registry`
**File:** [`resume_parsing/candidate_registry.py`](../src/resume_parsing/candidate_registry.py)

**Classes:**
- `Exception` — 
- `CandidateRegistry` — L132
- `Any` — L169
- `CandidateRegistryError` — L66
- `InvalidCandidateIdError` — L70
- `RoleNotFoundError` — L74
- `Path` — L88

**Functions / Methods:**
- `_now_iso()` — L83
- `_normalize_path()` — L88
- `_format_id()` — L98
- `_parse_id()` — L111
- `.__init__()` — L169
- `.load()` — L190
- `.save()` — L214
- `._invalidate_index()` — L239
- `._build_index()` — L242
- `._get_index()` — L250
- `.allocate_or_lookup()` — L259
- `.lookup()` — L326
- `.role_counter()` — L355
- `.all_candidates()` — L360
- `.candidates_for_role()` — L365
- `.__len__()` — L374
- `.__contains__()` — L377
- `fresh_registry()` — L386

**Referenced by:**
- `scripts/start_mlflow_server.py`
- `rag/retriever.py`
- `resume_parsing/parser.py`
- `scoring/unified_scorer.py`
- `services/scoring_subquery.py`

---

## `resume_parsing.ocr`
**File:** [`resume_parsing/ocr.py`](../src/resume_parsing/ocr.py)

**Classes:**
- `Path` — L67

**Functions / Methods:**
- `_extract_with_pdfplumber()` — L67
- `_extract_with_pypdfium()` — L84
- `_extract_with_pdf2image_ocr()` — L103
- `extract_text_hybrid()` — L130

**Third-party dependencies:**
- `pdf2image`

**Referenced by:**
- `scripts/start_mlflow_server.py`
- `rag/retriever.py`
- `resume_parsing/parser.py`
- `scoring/unified_scorer.py`
- `services/scoring_subquery.py`

---

## `resume_parsing.parser`
**File:** [`resume_parsing/parser.py`](../src/resume_parsing/parser.py)

**Classes:**
- `Path` — L70
- `CandidateRegistry` — L98
- `Any` — L98

**Functions / Methods:**
- `parse_experience_date_line()` — L58
- `candidate_id_from_path()` — L70
- `_role_from_path()` — L89
- `parse_resume()` — L98
- `extract_text_from_path()` — L138
- `parse_resume_text()` — L153
- `normalize_text()` — L215
- `sectionize()` — L221
- `identify_section_heading()` — L281
- `_looks_like_name()` — L370
- `extract_name()` — L425
- `extract_contact()` — L461
- `extract_section_text()` — L467
- `extract_summary()` — L471
- `extract_list_from_section()` — L478
- `_entry_has_signal()` — L493
- `_looks_like_job_title()` — L510
- `extract_experience_entries()` — L545
- `extract_education_entries()` — L620

**Referenced by:**
- `scripts/start_mlflow_server.py`
- `rag/retriever.py`
- `scoring/unified_scorer.py`
- `services/scoring_subquery.py`

---

## `resume_parsing.structured_profile`
**File:** [`resume_parsing/structured_profile.py`](../src/resume_parsing/structured_profile.py)

**Classes:**
- `CertificationEntry` — L104
- `EmploymentEntry` — L120
- `StructuredCandidateProfile` — L158
- `DegreeEntry` — L79
- `Any` — L94

**Functions / Methods:**
- `.to_dict()` — L94
- `.to_dict()` — L115
- `.to_dict()` — L146
- `.to_dict()` — L187
- `extract_structured_profile()` — L205
- `_parse_degree_entry()` — L347
- `_parse_certification_entry()` — L399
- `_compute_total_experience_years()` — L446

**Imports from (internal modules):**
- [`audit/no_evidence_flags.py`](../src/audit/no_evidence_flags.py)
- [`rag/document_aware_chunker.py`](../src/rag/document_aware_chunker.py)

**Referenced by:**
- `scripts/score_batch_composed.py`
- `services/scoring_pipeline.py`

---

## `schemas.weight_config`
**File:** [`schemas/weight_config.py`](../src/schemas/weight_config.py)

**Classes:**
- `BaseModel` — 
- `WeightConfigurationCreate` — L101
- `WeightConfigurationUpdate` — L116
- `WeightConfigurationResponse` — L123
- `WeightConfigurationListResponse` — L143
- `RoleBase` — L15
- `ValidationResponse` — L153
- `CategoryValidation` — L163
- `ValidationRequest` — L172
- `WeightSummary` — L182
- `CategorySummary` — L193
- `DashboardResponse` — L207
- `RoleResponse` — L22
- `Config` — L32
- `RoleListResponse` — L36
- `RequirementBase` — L46
- `RequirementResponse` — L57
- `RequirementListResponse` — L67
- `WeightItemCreate` — L78
- `WeightItemResponse` — L86

**Functions / Methods:**
- `.validate_weight_items()` — L109

**Third-party dependencies:**
- `pydantic`

**Referenced by:**
- `api/roles.py`
- `api/weights.py`

---

## `scoring.__init__`
**File:** [`scoring/__init__.py`](../src/scoring/__init__.py)

---

## `scoring.graded_scorer`
**File:** [`scoring/graded_scorer.py`](../src/scoring/graded_scorer.py)

**Classes:**
- `ItemEvaluation` — L131
- `Any` — L147
- `CategoryEvaluation` — L152
- `CandidateEvaluation` — L179
- `Pattern` — L207
- `Path` — L470
- `CodeOnlyItemResult` — L731
- `CodeOnlyCandidateEvaluation` — L776

**Functions / Methods:**
- `.to_dict()` — L147
- `.raw_score()` — L157
- `.max_score()` — L161
- `.score()` — L165
- `.to_dict()` — L168
- `.to_dict()` — L187
- `_normalize()` — L202
- `_aliases_for()` — L207
- `_detect_years_in_text()` — L247
- `_snippet_for()` — L276
- `_text_matches()` — L289
- `_summary_text()` — L293
- `_search_profile()` — L302
- `_normalize_importance()` — L382
- `_expected_years_for()` — L392
- `_is_experience_item()` — L405
- `_make_reason()` — L424
- `load_weights()` — L470
- `evaluate_candidate()` — L490
- `evaluate_role()` — L593
- `render_report()` — L612
- `extract_expected_years()` — L693
- `.blocked_items()` — L790
- `.to_dict()` — L794
- `_is_years_requirement()` — L804
- `evaluate_candidate_code_only_v2()` — L819

**Referenced by:**
- `scripts/start_mlflow_server.py`
- `rag/retriever.py`
- `scoring/unified_scorer.py`
- `services/scoring_subquery.py`

---

## `scoring.rubric_scorer`
**File:** [`scoring/rubric_scorer.py`](../src/scoring/rubric_scorer.py)

**Classes:**
- `RubricTemplate` — L190
- `SectionEvidence` — L190
- `SubScoreResult` — L42
- `Any` — L67
- `CachedScoringTrace` — L81

**Functions / Methods:**
- `.to_dict()` — L67
- `.to_dict()` — L112
- `_format_employment_history()` — L130
- `_build_rubric_prompt()` — L190
- `_extract_json_lenient()` — L308
- `_banded_years_ratio()` — L403
- `_parse_llm_response()` — L455
- `_default_sub_scores()` — L565
- `_evaluate_formula()` — L593
- `get_rubric_formula_sub_questions()` — L712
- `_is_binary_key()` — L719
- `score_requirement_with_rubric()` — L729
- `explain_score_from_cache()` — L839

**Imports from (internal modules):**
- [`rag/section_routed.py`](../src/rag/section_routed.py)
- [`scoring/rubrics.py`](../src/scoring/rubrics.py)

**Referenced by:**
- `scoring/unified_scorer.py`

---

## `scoring.rubrics`
**File:** [`scoring/rubrics.py`](../src/scoring/rubrics.py)

**Classes:**
- `Anchor` — L39
- `SubQuestion` — L52
- `RubricTemplate` — L89

**Functions / Methods:**
- `.to_dict()` — L76
- `.to_dict()` — L109
- `get_rubric()` — L556
- `is_code_only()` — L577
- `is_rubric_bound_llm()` — L592
- `all_rubric_types()` — L604

**Referenced by:**
- `scoring/rubric_scorer.py`
- `scoring/unified_scorer.py`
- `services/scoring_subquery.py`
- `services/subquery_retrieval.py`

---

## `scoring.tier_lookup`
**File:** [`scoring/tier_lookup.py`](../src/scoring/tier_lookup.py)

**Classes:**
- `Path` — L152
- `Any` — L65

**Functions / Methods:**
- `_load_tier_db()` — L65
- `reload_tier_databases()` — L86
- `_lookup_tier()` — L98
- `lookup_institute_tier()` — L152
- `lookup_certificate_tier()` — L174
- `get_institute_tier_points()` — L196
- `get_certificate_tier_points()` — L213
- `_check_flagged_institute()` — L234
- `is_institute_flagged()` — L267
- `get_flagged_institutes()` — L285

**Referenced by:**
- `scripts/start_mlflow_server.py`
- `rag/retriever.py`
- `resume_parsing/structured_profile.py`
- `scoring/unified_scorer.py`
- `services/scoring_subquery.py`

---

## `scoring.unified_scorer`
**File:** [`scoring/unified_scorer.py`](../src/scoring/unified_scorer.py)

**Classes:**
- `ItemEvaluation` — 
- `UnifiedCandidateEvaluation` — L113
- `SectionEvidence` — L1326
- `StructuredCandidateProfile` — L213
- `ChunkRecord` — L451
- `UnifiedItemEvaluation` — L62
- `Any` — L76
- `ComposedREQResult` — L821
- `UnifiedCategoryEvaluation` — L84
- `ComposedCandidateEvaluation` — L903
- `ThresholdRetriever` — L945

**Functions / Methods:**
- `.to_dict()` — L76
- `.raw_score()` — L91
- `.max_score()` — L95
- `.score()` — L99
- `.to_dict()` — L102
- `.to_dict()` — L129
- `_token_boundary_match()` — L150
- `_score_education_code_only()` — L213
- `_score_certification_code_only()` — L313
- `_score_location_code_only()` — L386
- `evaluate_candidate_unified()` — L451
- `_is_years_subquery()` — L679
- `_is_binary_subquery()` — L696
- `_is_rubric_subquery()` — L706
- `_score_presence_sq()` — L720
- `_score_years_sq()` — L781
- `.to_dict()` — L880
- `.blocked_reqs()` — L917
- `.zero_evidence_reqs()` — L921
- `.to_dict()` — L929
- `evaluate_candidate_composed()` — L945
- `_build_section_evidence()` — L1326

**Imports from (internal modules):**
- [`audit/no_evidence_flags.py`](../src/audit/no_evidence_flags.py)
- [`rag/document_aware_chunker.py`](../src/rag/document_aware_chunker.py)
- [`rag/per_req_retrieval.py`](../src/rag/per_req_retrieval.py)
- [`rag/retriever.py`](../src/rag/retriever.py)
- [`rag/section_routed.py`](../src/rag/section_routed.py)
- [`resume_parsing/structured_profile.py`](../src/resume_parsing/structured_profile.py)
- [`scoring/graded_scorer.py`](../src/scoring/graded_scorer.py)
- [`scoring/rubric_scorer.py`](../src/scoring/rubric_scorer.py)
- [`scoring/rubrics.py`](../src/scoring/rubrics.py)
- [`scoring/tier_lookup.py`](../src/scoring/tier_lookup.py)
- [`services/subquery_parser.py`](../src/services/subquery_parser.py)

**Third-party dependencies:**
- `numpy`

**Referenced by:**
- `scripts/score_batch_composed.py`
- `services/scoring_pipeline.py`

---

## `services.json_export`
**File:** [`services/json_export.py`](../src/services/json_export.py)

**Classes:**
- `Any` — L17
- `Path` — L17

**Functions / Methods:**
- `export_config_to_json()` — L17
- `load_config_from_json()` — L102
- `list_json_configs()` — L115
- `delete_json_config()` — L132
- `_build_interpretation()` — L152

**Referenced by:**
- `scripts/start_mlflow_server.py`
- `api/pages.py`
- `api/weights.py`
- `rag/retriever.py`
- `scoring/unified_scorer.py`
- `services/scoring_subquery.py`

---

## `services.llm_caller`
**File:** [`services/llm_caller.py`](../src/services/llm_caller.py)

**Classes:**
- `Any` — L121
- `OllamaRubricCaller` — L149
- `LLMRubricCaller` — L42

**Functions / Methods:**
- `_load_env()` — L20
- `.__init__()` — L54
- `.__call__()` — L85
- `get_default_caller()` — L121
- `.__init__()` — L162
- `.__call__()` — L196
- `get_rubric_caller()` — L233

**Referenced by:**
- `scripts/score_batch_composed.py`
- `api/scoring.py`

---

## `services.mlflow_wiring`
**File:** [`services/mlflow_wiring.py`](../src/services/mlflow_wiring.py)

**Classes:**
- `PipelineParams` — L101
- `Any` — L120
- `RetrievalMetrics` — L136
- `MLflowRun` — L210
- `Path` — L300

**Functions / Methods:**
- `is_available()` — L81
- `.to_dict()` — L120
- `.to_dict()` — L157
- `configure_tracking()` — L179
- `.__enter__()` — L236
- `.__exit__()` — L255
- `.log_pipeline_params()` — L268
- `.log_retrieval_metrics()` — L279
- `.log_metric()` — L290
- `.log_artifact()` — L300
- `.set_tag()` — L314
- `start_run()` — L324

**Third-party dependencies:**
- `mlflow`

**Referenced by:**
- `scripts/score_batch_composed.py`
- `scripts/start_mlflow_server.py`
- `rag/retriever.py`
- `scoring/unified_scorer.py`
- `services/scoring_subquery.py`

---

## `services.scoring_pipeline`
**File:** [`services/scoring_pipeline.py`](../src/services/scoring_pipeline.py)

**Classes:**
- `Path` — L154
- `StructuredCandidateProfile` — L215
- `ChunkRecord` — L269
- `UnifiedCandidateEvaluation` — L368
- `WeightItem` — L59
- `Any` — L70
- `WeightConfig` — L83

**Functions / Methods:**
- `.to_dict()` — L70
- `.to_unified_scorer_format()` — L93
- `list_configs_for_role()` — L154
- `load_weight_config()` — L162
- `_load_structured_profile_from_json()` — L215
- `_load_chunks_from_jsonl()` — L269
- `find_candidate_files()` — L296
- `list_candidate_ids()` — L341
- `score_candidate()` — L368
- `_code_only_education_score()` — L449
- `_code_only_certification_score()` — L453
- `_code_only_location_score()` — L457
- `score_candidate_batched_end_to_end()` — L461

**Imports from (internal modules):**
- [`rag/document_aware_chunker.py`](../src/rag/document_aware_chunker.py)
- [`resume_parsing/structured_profile.py`](../src/resume_parsing/structured_profile.py)
- [`scoring/tier_lookup.py`](../src/scoring/tier_lookup.py)
- [`scoring/unified_scorer.py`](../src/scoring/unified_scorer.py)
- [`services/scoring_subquery.py`](../src/services/scoring_subquery.py)

**Referenced by:**
- `scripts/start_mlflow_server.py`
- `api/pages.py`
- `api/scoring.py`
- `api/weights.py`
- `rag/retriever.py`
- `scoring/unified_scorer.py`
- `services/scoring_subquery.py`

---

## `services.scoring_subquery`
**File:** [`services/scoring_subquery.py`](../src/services/scoring_subquery.py)

**Classes:**
- `LLMScoreCache` — L44
- `RubricTemplate` — L52
- `SubQuestion` — L66
- `Any` — L73

**Functions / Methods:**
- `get_index()` — L35
- `get_cache()` — L44
- `sub_queries_for_rubric()` — L52
- `_template_var()` — L66
- `score_requirement()` — L73
- `_resolve_rubric_type()` — L162
- `score_candidate_all_reqs()` — L188

**Imports from (internal modules):**
- [`rag/section_routed.py`](../src/rag/section_routed.py)
- [`scoring/rubrics.py`](../src/scoring/rubrics.py)
- [`services/subquery_retrieval.py`](../src/services/subquery_retrieval.py)

**Referenced by:**
- `services/scoring_pipeline.py`

---

## `services.subquery_parser`
**File:** [`services/subquery_parser.py`](../src/services/subquery_parser.py)

**Classes:**
- `Path` — L18
- `Any` — L18

**Functions / Methods:**
- `parse_subquery_document()` — L18
- `_extract_role_name()` — L47
- `_extract_requirements()` — L58
- `_extract_sub_queries()` — L134
- `_extract_category_and_type()` — L181
- `_extract_description()` — L205
- `_extract_subquery_info()` — L225
- `get_all_role_subqueries()` — L238
- `get_role_subquery()` — L264
- `categorize_requirements()` — L282
- `calculate_category_totals()` — L302

**Referenced by:**
- `scripts/init_database.py`
- `scripts/score_batch_composed.py`
- `scripts/start_mlflow_server.py`
- `api/roles.py`
- `rag/retriever.py`
- `rag/subquery_cache.py`
- `scoring/unified_scorer.py`
- `services/scoring_subquery.py`

---

## `services.subquery_retrieval`
**File:** [`services/subquery_retrieval.py`](../src/services/subquery_retrieval.py)

**Classes:**
- `Path` — L175
- `SubQueryHit` — L227
- `LLMScoreCache` — L331
- `Any` — L359
- `ChunkIndex` — L84
- `ChunkRecord` — L91

**Functions / Methods:**
- `get_model()` — L62
- `embed_texts()` — L72
- `.add_chunk()` — L91
- `.finalize()` — L96
- `.save()` — L106
- `.load()` — L134
- `build_index_from_chunks_dir()` — L175
- `retrieve_chunks_for_requirement()` — L235
- `make_cache_key()` — L298
- `.__init__()` — L340
- `._load()` — L346
- `.get()` — L359
- `.put()` — L363
- `.stats()` — L370
- `score_requirement_with_similarity()` — L379
- `parse_anchored_response()` — L521
- `score_candidate_batched()` — L608
- `_build_batched_prompt()` — L778
- `_parse_batched_response()` — L868
- `_parse_single_value()` — L937

**Imports from (internal modules):**
- [`rag/document_aware_chunker.py`](../src/rag/document_aware_chunker.py)

**Third-party dependencies:**
- `numpy`

**Referenced by:**
- `scripts/start_mlflow_server.py`
- `rag/retriever.py`
- `scoring/unified_scorer.py`
- `services/scoring_subquery.py`

---
