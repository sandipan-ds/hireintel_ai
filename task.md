# Tasks: True Score Evaluation Using Judge LLMs

- [x] Create isolated evaluation directory structure under `data/eval/judge_eval/`
- [x] Implement `src/evaluation/score_comparator.py` containing comparison metrics (8 categories)
- [x] Implement `src/evaluation/judge_prompt_builder.py` to build the multimodal judge prompt and format the rubric and candidate/weight configurations
- [x] Implement `scripts/run_judge_eval.py` to run the evaluation loop, handle 10% sampling, render PDFs, execute APIs with the 5-key rotation pool, and save candidate evaluations
- [x] Implement `scripts/generate_judge_eval_report.py` to compile comparison metrics, output JSON report, and generate Markdown report with flagged candidates
- [x] Dry-run the evaluation to verify sampling, file checking, and configuration validation
- [x] Perform a full run with Gemini 2.5 Flash and Minimax-M3 across all roles
- [x] Generate and verify the final evaluation report (`comparison_report.md`)
