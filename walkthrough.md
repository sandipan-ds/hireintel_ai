# Walkthrough: True Score Evaluation Using Judge LLMs

We have successfully implemented and verified the sample-based score validation protocol defined in [19_EVALUATION.md](file:///c:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/docs/19_EVALUATION.md).

---

## 1. Implementation Details

We implemented the evaluation framework under a new package `src.evaluation` and a set of command-line scripts, ensuring full isolation from production scoring directories:

### Core Modules
1. **`src/evaluation/score_comparator.py`**:
   - Calculates the **true mathematical candidate scores** based on sub-query scores (preventing LLM arithmetic errors from affecting the comparative metrics).
   - Computes all 8 metrics: Schema Agreement, Arithmetic Consistency, Per-Criterion Absolute Error, Total Score Absolute Error, Relative Percentage Error, Deviation Direction, Bias Direction, and batch-level stats (MAE, RMSE, StdDev, Max deviation).
   - Flagging logic: flags candidate evaluations for manual review if their relative error exceeds ±10% or if any structural/arithmetic errors occur.

2. **`src/evaluation/judge_prompt_builder.py`**:
   - Compiles a single comprehensive, multimodal prompt containing the entire SubQuery rubric (categories, subqueries, scales, assessment instructions), weight configuration, and strict JSON output formatting guidelines.

### Command-Line Scripts
3. **`scripts/run_judge_eval.py`**:
   - Manages candidate sampling (default: stratified 10% sample per role, min 2 candidates).
   - Resolves original PDF paths from registry and renders the first 5 pages to base64 JPEGs via `pypdfium2`.
   - Coordinates dual-judge API execution against Gemini 2.5/3.1 Flash and Minimax-M3.
   - Reuses a unified **5-key circular rotation pool** with rate-limit cooldown management.
   - Tracks batch execution state via a progress ledger (`progress.json`) to allow seamless resumption via the `--resume` flag.

4. **`scripts/generate_judge_eval_report.py`**:
   - Compiles all metrics across candidate folders, generating `comparison_report.json` (machine-readable metrics), `flagged_for_review.json` (flagged candidate list), and `comparison_report.md` (detailed Markdown report with candidate summary and requirement-level divergence analytics).

---

## 2. Verification Results

We executed a full evaluation run on the `ReactDeveloper` role to verify the end-to-end pipeline:

```bash
python scripts/run_judge_eval.py --role ReactDeveloper --seed 42
```

### Log Execution Summary
- **Key Queue Initialization**: Circular pools established for Google (2 keys) and NVIDIA (3 keys).
- **Candidate Sampling**: Sampled 2 out of 18 React candidates (`ReactDeveloper_CAND_0004` and `ReactDeveloper_CAND_0001`).
- **Multimodal LLM Calls**: Successful page renderings and completion calls on both Gemini 2.5 Flash and Minimax-M3.
- **Key Rotation Verification**: Verified that for Candidate 1, it used key `KEY_1`, and round-robin rotated to `KEY_2` for Candidate 2 for both Google and NVIDIA providers.
- **Report Generation**: Successfully compiled metrics and generated JSON, flagged, and Markdown reports under `data/eval/judge_eval/batch_20260712_223647/`.

### Comparative Metrics Analysis
The evaluation report shows a massive score gap between the production scorer (qwen2.5:3b) and the multimodal judge LLMs:

- **Mean Absolute Error (MAE)**: **70.96** points (on a 0–100 scale).
- **Flagged Candidates**: 2 / 2 (both flagged with ~99% relative error).
- **Root Cause of Divergence**:
  - The production scorer blocked 15 out of 19 requirements because it could not retrieve evidence or because target years were unresolvable from context.
  - The multimodal judges, inspecting the original PDF pages directly, easily found the evidence and successfully awarded scores (resulting in totals of 58.39 and 85.21 vs scorer's 0.84 floor totals).

This confirms the value of the True Score Evaluation audit: it highlights where the production scorer is failing structurally, without relying on naive ranking stability.
