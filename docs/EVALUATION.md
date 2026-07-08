# Evaluation

> **Source of truth for scoring, evaluation, and ranking:**
> [`WORKING_LOGIC.md`](WORKING_LOGIC.md). For "what is implemented today vs
> what's planned", see [`CURRENT_PROGRESS.md`](CURRENT_PROGRESS.md).

## Overview

This document defines how HireIntel AI will measure AI quality, scoring reliability, retrieval performance, hallucination risk, and business impact.

Evaluation is required before promoting AI behavior, model changes, prompt changes, scoring changes, or retrieval changes into production.

---

## Test Dataset

The platform is evaluated against a real-world dataset of **721 resumes** across **8 roles** (extracted 2026-07-01).

### Resumes by Role

| Role | Count |
|------|-------|
| BusinessAnalyst | 133 |
| SalesManager | 164 |
| WebDesigning | 112 |
| SrPythonDeveloper | 98 |
| SQLDeveloper | 82 |
| JavaDeveloper | 72 |
| DataScience | 42 |
| ReactDeveloper | 18 |
| **Total** | **721** |

### Geographic Distribution (Top 7 Countries)

| Country | Resume Count |
|---------|--------------|
| USA | 41 |
| UK | 7 |
| Germany | 4 |
| Canada | 2 |
| Finland | 1 |
| Mexico | 1 |
| South Korea | 1 |

### Top US Locations

| Location | Count |
|----------|-------|
| New York, NY | 4 |
| Los Angeles, CA | 3 |
| San Francisco, CA | 3 |
| Chicago, IL | 3 |
| Phoenix, AZ | 3 |
| Pittsburgh, PA | 3 |
| San Antonio, TX | 3 |

### Most Common Institutions (extracted)

Simmons College (8), Singapore University (7), Mohave Community College (7), California State University (3), Stanford University (3), Academy of Art University (3), University of Chicago (2), University of Pittsburgh (2), University of California (2), Grand Valley State University (2), MIT (1), Wharton School of Business (1).

### Most Common Certifications (extracted)

Adobe Certified Expert (ACE) (6), Microsoft Professional Program Certificate in Data Science (4), OCA - Oracle Database SQL Certified Associate (3), Adobe Creative Suite (3), Level 3 CBAP (2), Spring Professional Certification (2), Oracle Certified Professional: Java SE (2), NLP Practitioner Certification (2), Python Developer Certification (2), AWS Solutions Architect (1), Azure Solutions Architect (1), Google Cloud Professional (1), PMP (1), CISSP (1), CCNA (1), Scrum Master (1), Tableau Certified (1), Power BI Certified (1).

### Data Quality Notes

- Some location entries contain noise (e.g., `"9 London, UK"`, `"@ New York, USA"`) — extraction filters this out.
- Some institution entries contain extra text (e.g., `"Singapore University\nSKILLS & OTHER"`) — multi-line parsing handles it.
- 13 **flagged/fake universities** were identified (XYZ University, Cowell University, etc.) — see `AI_DESIGN_RATIONALE.md` §11 for the flagging system and penalty rules.

---

## Resume Parsing Evaluation

**Goal:** Measure whether unstructured resumes are converted into accurate structured candidate profiles.

**Metrics:**
- Precision
- Recall
- F1 score
- field-level extraction accuracy
- evidence-link coverage

**Target Fields:**
- candidate name
- contact information
- education
- skills
- certifications
- languages
- work experience
- projects
- technology stack
- leadership indicators

---

## Job Description Extraction Evaluation

**Goal:** Measure whether hiring requirements are extracted correctly from job descriptions.

**Metrics:**
- required skill precision and recall
- preferred skill precision and recall
- experience requirement accuracy
- education requirement accuracy
- requirement evidence coverage

---

## Retrieval Evaluation

**Goal:** Measure whether recruiter questions retrieve the right resume evidence under the threshold-based retrieval pipeline (DEC-018).

**Per-Configuration Metrics** (logged per MLflow run, DEC-020):
- `recall_at_theta` — fraction of ground-truth-relevant chunks that meet the cosine threshold and are returned.
- `precision_at_theta` — fraction of returned chunks that are ground-truth-relevant.
- `mrr` — Mean Reciprocal Rank of the first relevant chunk in the returned set.
- `ndcg` — Normalized Discounted Cumulative Gain of the returned set.
- `avg_chunks_returned` — average number of chunks returned per query (Optuna objective: minimize).
- `p95_chunks_returned` — 95th percentile of returned chunks (sanity check on the cap).
- `cap_hit_rate` — fraction of queries where `len(returned) == max_chunks_per_query` (if > 10%, θ is too low).

**Per-Eval-Set Aggregate Metrics** (logged per Optuna trial, DEC-021):
- `faithfulness` — fraction of generated answers whose claims are supported by retrieved chunks (LLM-as-judge or recruiter-spot-check).
- `groundedness` — fraction of generated answers that contain no claims outside retrieved chunks.
- `answer_relevancy` — fraction of generated answers that address the recruiter's question.
- `hallucination_rate` — fraction of generated answers containing unsupported claims.

**Baseline (default config, DEC-019/018 defaults):**
- `chunk_size = 500`
- `chunk_overlap = 50`
- `θ = 0.70`
- `max_chunks_per_query = 20`
- `embedding_model = all-MiniLM-L6-v2`

**Promotion Criteria** (config → `Active` in `MODEL_REGISTRY.md`):
- A new configuration must improve on the baseline `faithfulness` **and** not regress `groundedness` by more than 1%.
- The promoting Optuna trial must exist in `data/optuna/studies.db` and the corresponding MLflow run must include all metrics above.
- The shipped config is the Optuna-recommended point on the Pareto front, not a hand-picked value.

---

## Generation Evaluation

**Goal:** Measure quality of summaries, comparisons, chat answers, and recommendation text.

**Metrics:**
- faithfulness
- groundedness
- answer relevancy
- completeness
- unsupported statement rate

---

## Candidate Scoring Evaluation (per-item, per `WORKING_LOGIC.md`)

**Goal:** Measure whether the deterministic scorer awards the correct per-item score for the correct reason.

### Code-Only Scoring Metrics

- **Skill Presence Precision/Recall** — does the scorer correctly mark a skill as present vs absent?
- **Skill Coverage Precision/Recall** — for JD items with N synonyms, does the scorer match all of them?
- **Years Detection MAE** — mean absolute error between `candidate_years` and ground-truth years.
- **Per-item Score Accuracy** — fraction of items where the awarded raw score equals the ground truth within ±0.5.
- **Evidence Section Precision** — fraction of matched items where the cited profile section is the most informative one.
- **Snippet Faithfulness** — fraction of snippets that contain the matched keyword (no fabricated text).
- **Score Reproducibility** — same inputs → same score, byte-for-byte.

### Rubric-Bound LLM Evidence Scoring Metrics

- **Rubric Adherence** — fraction of LLM sub-scores that fall within the rubric-defined point anchors (does the LLM score against the recruiter rubric, not its own internal scale?).
- **Extraction Completeness** — did the LLM extract all relevant evidence from the mapped section(s) before scoring? (Recall of evidence extraction.)
- **LLM Judge Consistency** — same evidence + same rubric → same sub-score across repeated calls (test-retest reliability).
- **Weight Blindness** — verify that the LLM never receives the requirement's weight during scoring (audit prompt construction).
- **No-Aggregation Compliance** — verify that the LLM never computes the final weighted contribution (audit prompt + output schema).
- **Double-Count Detection** — verify that overlapping experience (e.g. 6 years Python on cluster systems + 6 years managing recommendation projects) is not summed to 12 years.
- **Sub-score Calibration** — correlation between LLM sub-scores and recruiter-expert ground-truth sub-scores on a labeled dataset.

## Candidate Ranking Evaluation

**Goal:** Measure whether deterministic ranking aligns with recruiter-defined scoring policies and expert review.

**Metrics:**
- top-k accuracy
- recruiter agreement
- ranking accuracy
- tie-break correctness
- score reproducibility

**Ground truth:** for each role, hand-score the top-N candidates against the recruiter's locked scoring policy, then compare to the deterministic scorer's output.

---

## Hallucination Evaluation

**Goal:** Ensure recruiter-facing answers do not invent candidate information.

**Metrics:**
- hallucination rate
- unsupported statements
- missing-evidence handling accuracy

Expected missing-information response:

```text
Information not found in candidate documents.
```

---

## Business Evaluation

**Goal:** Measure whether the platform improves recruiting workflows.

**Metrics:**
- screening efficiency
- recruiter time saved
- recruiter satisfaction
- shortlisting accuracy
- explanation usefulness

---

## Evaluation Artifacts

Evaluation datasets and outputs should be stored under `data/processed/evaluation_results/` or a future secure evaluation storage path. Candidate PII must not be written to logs or public artifacts.

## Experiment Tracking & Hyperparameter Search (added 2026-07-05, DEC-020 + DEC-021)

**Every retrieval / scoring run is logged to MLflow** (DEC-020) and is reproducible from the logged `params` + `artifacts`. **The shipped `θ`, `chunk_size`, and `chunk_overlap` are always the Optuna-recommended point on the Pareto front** (DEC-021), not hand-picked.

**MLflow contract:**

| Aspect | Value |
|---|---|
| Tracking URI | `http://127.0.0.1:5000` |
| Backend store | `data/mlflow/mlflow.db` (SQLite) |
| Artifact root | `data/mlflow/artifacts/` |
| Launch | `mlflow server --host 127.0.0.1 --port 5000 --backend-store-uri sqlite:///data/mlflow/mlflow.db --default-artifact-root ./data/mlflow/artifacts/` |
| Per-run tags | `experiment_set` (e.g. `chunking_v1`), `role` (e.g. `BusinessAnalyst`) |
| Required params | `chunk_size`, `chunk_overlap`, `embedding_model`, `vector_store`, `similarity`, `retrieval_mode`, `threshold`, `top_k`, `llm` |
| Required metrics | All `*_at_theta`, `mrr`, `ndcg`, `avg_chunks_returned`, `p95_chunks_returned`, `cap_hit_rate`, `faithfulness`, `groundedness`, `answer_relevancy`, `hallucination_rate` |
| Required artifacts | `retrieved_chunks.json` (per query), `eval_set.jsonl` (the inputs), `study_summary.json` (Optuna-only) |

**Optuna contract:**

| Aspect | Value |
|---|---|
| Study store | `sqlite:///data/optuna/studies.db` (SQLite) |
| Sampler | TPE (Tree-structured Parzen Estimator) |
| Default objectives | `["maximize", "minimize"]` = `[faithfulness, avg_chunks_returned]` |
| Search space | `chunk_size ∈ [200, 1000]` step 100; `chunk_overlap ∈ [0, 150]` step 25; `θ ∈ [0.50, 0.90]` step 0.05; `top_k ∈ [3, 20]` |
| Naming | `<experiment_set>_<yyyymmdd>` (e.g. `chunking_v1_20260705`) |
| MLflow bridge | `optuna.integration.MLflowCallback` |
| Dashboard | `optuna-dashboard sqlite:///data/optuna/studies.db` |

**Eval set requirement (gate on M0.5b):**

The Optuna search is only as good as the eval set. A small or biased eval set will produce a confidently-wrong shipped config. Eval set schema:

```text
data/eval/<set_name>.jsonl   (line-delimited JSON)

{
  "query_id": "q_001",
  "query": "5+ years of Python experience with recommendation systems",
  "candidate_id": "cand_042",
  "expected_chunk_ids": ["cand_042__2", "cand_042__7"],
  "expected_answer": "Candidate has 7 years of Python experience ...",
  "expected_faithfulness": 1.0,        // ground truth
  "weight": 1.0,                        // optional per-query weight
  "tags": ["skill", "python", "mid-senior"]
}
```

Minimum viable eval set: 50 triples spanning at least 3 roles and at least 4 dimensions (skill, experience, education, certification).

**Promotion gate:**
1. Build the eval set (M0.5b prerequisite).
2. Run the Optuna study until the Pareto front stabilizes (typically 100–200 trials).
3. Pick the operating point on the Pareto front that meets the team's faithfulness bar (e.g. `faithfulness ≥ 0.85`).
4. Export the params to `MODEL_REGISTRY.md` as the new "Active" config.
5. Promote only if the new config improves on the prior "Active" config on the baseline eval set.

## Ranking Evaluation Without Labeled Data (added 2026-07-05, DEC-024)

**The problem:** the platform ranks candidates against recruiter-defined weight configs, but there is no single labeled "ground truth" ranking to compare against. Recruiters disagree among themselves; the "right" candidate is a judgment call; labeled sets are expensive and decay over time. A traditional ML evaluation (precision@K, NDCG against labels) does not apply.

**The approach:** five independent signals for "is our ranking correct?", none of which require a single labeled ground truth. The platform's claim "rankings are correct" is now backed by **all five signals**, not one. If all five agree, the ranking is good. If any one disagrees, we investigate.

### The Five Prongs

#### Prong 1: Counterfactual Tests (always, cheap, automated)

Construct test cases where the expected ranking change is **unambiguous** and verify the system obeys. The expected behavior is hard-coded; the system either passes or fails.

**Eval set:** `data/eval/counterfactual_v1.jsonl`. Each row is a test case with two configs and an expected ranking delta:

```json
{
  "test_id": "cf_001",
  "description": "Increasing Python weight should rank the Python-heavy candidate above the Java-heavy candidate",
  "config_a": { "weights": { "python": 5, "java": 5 }, "expected_top": "cand_java_heavy" },
  "config_b": { "weights": { "python": 15, "java": 5 }, "expected_top": "cand_python_heavy" },
  "candidates": ["cand_python_heavy", "cand_java_heavy"]
}
```

The system runs both configs on the test candidates and asserts the expected ranking. **Pass rate target: ≥ 0.95.**

**Categories of counterfactual tests:**

| Category | Test description |
|---|---|
| Weight monotonicity | Increasing a skill's weight should rank candidates with that skill higher (and vice versa) |
| Must-have gate | Adding a "must have" requirement should drop candidates without it below the gate |
| Years-proportionality | A candidate with 2× the years of experience should score at least 2× as much (capped at the weight) |
| Synonym equivalence | "Power BI" and "PowerBI" should produce the same score (after synonym normalization) |
| Recruiter agreement | For two candidates with similar profiles, small weight changes should produce small ranking changes |
| Cache stability | Re-running the same config returns the same ranking (covered by DEC-022) |

**Coverage target:** ≥ 50 counterfactual tests spanning at least 4 categories.

#### Prong 2: Synthetic Labeled Set (quarterly, moderate cost)

Hand-rank **30–50 (candidate, role) pairs** across 2–3 recruiters. The majority or median ranking is the "ground truth". The platform is evaluated against this set with NDCG, MRR, top-K accuracy, and Spearman correlation.

**Eval set:** `data/eval/ranking_v1.jsonl`. Each row is:

```json
{
  "set_id": "ranking_v1",
  "role": "BusinessAnalyst",
  "candidates": ["cand_001", "cand_002", ..., "cand_010"],
  "expected_ranking": ["cand_005", "cand_002", "cand_008", ...],
  "recruiters": ["recruiter_A", "recruiter_B"],
  "inter_rater_agreement": 0.73,
  "created_at": "2026-07-15"
}
```

**Metrics:**

| Metric | Definition | Target |
|---|---|---|
| `ndcg_at_10` | NDCG of system ranking vs. expected ranking | ≥ 0.80 |
| `top_3_accuracy` | Fraction of test cases where the top-3 system candidates are in the top-3 expected | ≥ 0.80 |
| `spearman_correlation` | Rank correlation between system and expected | ≥ 0.70 |
| `inter_rater_agreement` | Cohen's kappa or Krippendorff's alpha among recruiters | ≥ 0.60 (else the "ground truth" itself is suspect) |

**Refresh cadence:** quarterly. Recruiting ground truth decays fast (a "great" candidate last year may not be a "great" candidate this year); a 30–50-case high-quality set, refreshed quarterly, is more durable than a 1000-case set refreshed annually.

#### Prong 3: Stability Tests (always, free)

Re-run the same config twice, verify byte-identical ranking. Already covered by the per-resume cache key from DEC-022, but worth measuring explicitly.

**Metric:** `ranking_stability_rate` = `(identical_rankings) / (total_rankings)` across the test set. **Target: 1.0 (byte-identical).**

A drop below 1.0 indicates a cache key bug — the same (candidate, req, query, θ) is producing different sub-scores across runs. Investigate immediately.

#### Prong 4: Recruiter Agreement (periodic, high cost)

Multiple recruiters rank the same candidate pool. Measure inter-rater agreement:

- **Pairwise:** Cohen's kappa.
- **Multi-rater:** Krippendorff's alpha.
- **System-vs-recruiter:** how often does the system's top-K match the recruiter's top-K?

**Target:** the system's agreement with the median recruiter should be **at least as high** as the inter-recruiter agreement. If recruiters agree at kappa = 0.6, the system should also be at kappa = 0.6 with the median recruiter. If the system is significantly below, the system is regressing; if significantly above, the system is over-fitting to a single recruiter's taste.

**Cadence:** quarterly study; not on the hot path.

#### Prong 5: Behavioral Signals (production only, noisy)

In production, track:

| Signal | Definition | Use |
|---|---|---|
| `top_1_interview_rate` | Fraction of top-1 candidates who are interviewed | If < 50%, recruiters don't trust the top-1 |
| `top_3_interview_rate` | Fraction of top-3 candidates who are interviewed | If < 70%, recruiters don't trust the shortlist |
| `bottom_rejection_rate` | Fraction of bottom-10 candidates who are rejected | If < 80%, recruiters are not using the bottom |
| `revisit_rate` | Fraction of recruiters who re-open the same candidate's profile | High revisit = recruiters are second-guessing the rank |

**Important:** these are tracked, not enforced. An empty behavioral signal is **not a regression** — it just means we don't have production data yet. A change in the trend is a signal worth investigating; an absence of signal is not.

### Promotion Gate (revised)

A new "Active" config is promoted to `MODEL_REGISTRY.md` only if **all four of the following hold**:

1. **Counterfactual pass rate ≥ 0.95** on `data/eval/counterfactual_v1.jsonl`.
2. **Stability rate = 1.0** on the eval set.
3. **NDCG@10 ≥ 0.80** on the latest quarterly `data/eval/ranking_v1.jsonl` (if the set exists; skip if no labeled set has been built yet).
4. **No regression in the prior "Active" config's** counterfactual pass rate (the new config must not break what already works).

The Optuna study (M0.5d) optimizes `faithfulness` and `avg_chunks_returned` against the eval set (M0.5b). The counterfactual + stability gate is applied **after** the Optuna-recommended point is identified, before promotion. This is a hard gate: an Optuna-recommended config that fails the gate is not promoted.

### Prong 6: Optuna Ranking Stability Across Hyperparameter Values (added 2026-07-06, Track 7)

**Motivation:** The Optuna sweep (M0.5d) tries many `(chunk_size, chunk_overlap, theta, max_chunks_per_query)` combinations. Each produces a different ranking for the same candidate pool. Two questions arise naturally:

1. **How sensitive is the ranking to HP changes?** If `theta=0.35` and `theta=0.40` produce wildly different top-10s, the ranker is fragile — small perturbations can flip interview shortlists. If they produce nearly identical top-10s, the ranker is robust.
2. **Which HP dimension drives the most rank churn?** Is `theta` the dominant axis of ranking change, or `chunk_size`? This tells us which HP we must tune carefully and which we can leave at the default.

**This is orthogonal to Prong 3 (Stability Tests).** Prong 3 re-runs the *same* config and asks for byte-identical results (the cache-key determinism test). Prong 6 compares *different* configs (the HP-sensitivity test) and asks how much ranking changes. Both matter — Prong 3 is correctness, Prong 6 is robustness.

#### Datasets

Each trial in the Optuna study already produces a full per-candidate ranking `(candidate_id, total_score)` for one role. Prong 6 collects these rankings across the full sweep and computes pairwise metrics:

- **Pair** = `(trial_A, trial_B)` where both trials ran the same role.
- Per pair, compute the rank-difference vectors and aggregate.

#### Metrics (per role, per Optuna study)

| Metric | Definition | Interpretation |
|---|---|---|
| `top_10_jaccard` | Mean Jaccard similarity of top-10 candidate sets across all trial pairs: `|A ∩ B| / |A ∪ B|` | 1.0 = identical top-10. 0.0 = no overlap. High = robust; low = fragile. |
| `top_50_jaccard` | Same for top-50 | Wider-net version of `top_10_jaccard`. |
| `max_rank_shift` | `max(|rank_A(c) - rank_B(c)|)` for any candidate `c` across all pairs | Max positional movement. Big values indicate a candidate can swing wildly. |
| `mean_abs_rank_shift` | Mean of `|rank_A(c) - rank_B(c)|` across candidates and pairs | Average positional movement. Smoothed-over max-outlier view. |
| `kendall_tau` | Kendall's tau-b between every pair of trial rankings (averaged) | Distribution-shape agreement. 1.0 = same order; -1.0 = inverse; 0.0 = uncorrelated. |
| `spearman_rho` | Spearman's rho between every pair of trial rankings (averaged) | Monotonic-shape agreement. |
| `newcomer_rate_top_10` | Mean fraction of top-10 candidates in trial B that were NOT in trial A's top-10 (per pair, asymmetric) | "How often does a candidate enter the shortlist from outside?" High = shortlist churn; low = shortlist stable. |
| `drop_rate_top_10` | Symmetric counterpart of `newcomer_rate` (candidates who left the top-10) | Same info, opposite direction. Should equal `newcomer_rate_top_10` over a symmetric pair-average, but split for diagnostic value. |
| `HP_axis_explained_variance` | For each HP (`chunk_size`, `chunk_overlap`, `theta`, ...), the R² of how much of the `mean_abs_rank_shift` variance it explains | "Which HP dimension drives rank churn?" Identifies the HP to tune carefully vs. the HP we can let sit at default. |

**Note on the +/− cancellation problem:** the user explicitly raised the failure mode of naive signed rank-shift aggregation (`+5` for one candidate and `-5` for another can sum to 0 and hide the magnitude). All metrics above use unsigned magnitudes (`|rank_A(c) - rank_B(c)|`) or distribution-shape coefficients (Kendall, Spearman) — never a signed sum. We never let negative and positive rank-shifts cancel across candidates.

#### Targets

These are tracked-not-enforced knobs for the first sweep; we'll refine them once we see the empirical distribution on real studies. Initial soft targets (Track 7 calibration):

| Metric | Soft target (Track 7) | Rationale |
|---|---|---|
| `top_10_jaccard` | ≥ 0.60 | At least 6/10 candidates shared between typical sweep trials. Less than this = the shortlist is too sensitive to HP perturbation to be useful to a recruiter. |
| `max_rank_shift` | ≤ 50 | No candidate swings more than half the pool's size across HP perturbations. |
| `mean_abs_rank_shift` | ≤ 15 | Average swing is contained. |
| `kendall_tau` | ≥ 0.60 | Pairwise agreement is moderate or better. |
| `spearman_rho` | ≥ 0.65 | Monotonic agreement is moderate or better. |
| `newcomer_rate_top_10` | ≤ 0.30 | No more than 30% of the top-10 turns over between typical trial pairs. |

These are **not** hard promotion gates yet — they are diagnostics that ship with every Optuna run so the team can see whether a candidate's shortlist appearance is brittle. If a particular HP axis drives the churn (e.g., `theta` causes > 50% top-10 turnover for a small `delta_theta=0.05`), we widen the Optuna search space and let the model find a flatter region.

#### Where the rankings come from

The Optuna study (M0.5d) records the full ranking for every trial. We persist these to `reports/diff_rankings/` as JSON:

```
reports/diff_rankings/optuna_study_<study_name>__<role>__rankings.json
{
  "study_name": "m05d_first_sweep_2026-07-15",
  "role": "BusinessAnalyst",
  "trials": [
    {
      "trial_number": 14,
      "params": {"chunk_size": 500, "chunk_overlap": 100, "theta": 0.35},
      "ranking": [
        {"candidate_id": "BusinessAnalyst_CAND_0040", "total_score": 78.2, "rank": 1},
        {"candidate_id": "BusinessAnalyst_CAND_0011", "total_score": 76.8, "rank": 2},
        ...
      ]
    },
    ...
  ]
}
```

The metric computation is done by a small reporter `src/reporting/rank_stability.py` (Track 7) that reads the JSON, computes all the metrics above per role, and writes:

- `reports/diff_rankings/optuna_study_<study_name>__<role>__rank_stability.json` — the raw metric values per (role, study).
- `reports/diff_rankings/optuna_study_<study_name>__<role>__rank_stability.md` — a human-readable summary with the HP-axis explained-variance breakdown.

The MD file is what a recruiter-facing team member reads. The JSON is the artifact that MLflow logs as a metric set for the study.

#### Promotion gate impact (Track 7 addition)

Prong 6 metrics are **informational**. An Optuna-recommended "Active" config candidate **cannot** be blocked solely by Prong 6 — the metrics are diagnostic-only. However, if Prong 6 finds that the new "Active" candidate sits in a high-churn region (e.g., `top_10_jaccard` < 0.30 against the prior "Active" config), the promotion is **flagged for human review** before being merged. The flag is a comment in the `MODEL_REGISTRY.md` "Active" row + a release-notes entry. Reviewer can override.

### Summary

| Prong | Cost | Cadence | Gate? | Target |
|---|---|---|---|---|
| Counterfactual | Cheap | Every run | **Yes** | Pass rate ≥ 0.95 |
| Stability | Free | Every run | **Yes** | Rate = 1.0 |
| Synthetic labeled | Moderate | Quarterly | **Yes** | NDCG ≥ 0.80 |
| Recruiter agreement | High | Quarterly study | Informational | Kappa ≥ 0.60 |
| Behavioral | Production data | Continuous | Informational | Tracked, not enforced |
| **Optuna rank stability** *(Track 7 addition)* | **Free (uses Optuna trial artifacts)** | **Every Optuna study** | **Informational (flag for human review on high-churn)** | **`top_10_jaccard` ≥ 0.60, `max_rank_shift` ≤ 50** |

## Per-Resume Reasoning Cache Metrics (added 2026-07-05, DEC-022)

**Goal:** Measure the cost and determinism impact of the per-resume reasoning storage.

**Per-Run Metrics** (logged per pipeline invocation):

| Metric | Definition | Target |
|---|---|---|
| `cache_hit_rate` | `(cache_hits) / (cache_hits + cache_misses)` | ≥ 0.95 after the first scoring pass |
| `cache_hit_rate_by_key` | Hit rate broken down by key component (chunk_id, model_name, θ) | identify which invalidation source dominates |
| `llm_calls_avoided` | `cache_hits` (each is a round-trip saved) | non-negative integer |
| `disk_usage_per_candidate` | Mean bytes in `data/per_candidate/<role>/<candidate_id>/` | ≤ 5 MB (theoretical 43,000 entries × ~120 B compressed text is wrong — actual is 5–20 KB per entry × ~60 entries per candidate = 0.3–1.2 MB) |
| `disk_usage_total` | `du -sb data/per_candidate/` | ≤ 5 GB (alert threshold) |
| `archive_entries_count` | Entries in `data/per_candidate_archive/` | growing slowly; alert if > 50% of active |
| `backfilled_entries_count` | Entries with `"backfilled": true` from the legacy cache migration | 0 after one full re-run |

**Determinism Metrics** (re-run twice with the same config, compare outputs):

| Metric | Definition | Target |
|---|---|---|
| `sub_score_match_rate` | `(matching sub_scores) / (total sub_scores)` across the two runs | 1.0 (byte-identical) |
| `reasoning_match_rate` | `(matching reasoning text) / (total reasoning text)` | 1.0 |
| `basis_match_rate` | `(matching basis entries) / (total basis entries)` | 1.0 |

A `sub_score_match_rate < 1.0` indicates a cache key bug — the same (candidate, req, query, θ) is producing different sub-scores across runs. Investigate immediately; this is a hard regression of DEC-022's determinism promise.

**Storage Cost Tradeoff (per DEC-022):**

| Scenario | LLM calls | Storage | Re-run time |
|---|---|---|---|
| No cache (re-call every time) | O(N × R × Q) | 0 | minutes per candidate |
| `llm_cache.jsonl` (sub-scores only) | O(1) on exact key match | ~50 MB | seconds per candidate |
| **`data/per_candidate/.../reasoning/` (DEC-022)** | **O(1) on exact key match** | **~1–2 GB peak** | **<1 sec per candidate** |
| No cache + Optuna sweep (200 trials × 50 queries) | 1,000,000 LLM calls | 0 | days |
| **Per-resume cache + Optuna sweep (200 trials × 50 queries)** | **50,000 LLM calls (first pass) + 0 (cache hits)** | **~1–2 GB peak** | **hours** |

The Optuna sweep is where DEC-022's storage cost pays for itself: the same 50,000 LLM calls happen once, then every subsequent trial re-reads the cache.

## Chunk Reports (added 2026-07-05, DEC-024)

**Goal:** Per-experiment diagnostics committed to git for historical record.

**Reports location:** `reports/chunk_reports/`. Report file names mirror the experiment folder names:

- `document_aware_chunking_report.{json,md}` — historical diagnostic of the 721-resume Document-Aware corpus. Captures the 49% missing-`section_type` finding (DEC-015).
- `recursive_chunking_<chunk_size>_<overlap>_<top_k>_<threshold×100>_report.{json,md}` — per-experiment Recursive diagnostic.

**Per-experiment metrics captured in each report:**

| Category | Metrics |
|---|---|
| Chunk statistics | `total_chunks`, `chunks_per_role`, `chunks_per_resume` (mean, median, min, max, p95), `chunks_with_section_type_empty` (the DEC-015 bug), `section_type_distribution` |
| Retrieval statistics | `avg_chunks_returned`, `p95_chunks_returned`, `cap_hit_rate`, retrieval hit rate by section |
| LLM statistics | `llm_calls_total`, `cache_hit_rate`, `avg_sub_scores` |
| Eval metrics | `recall_at_theta`, `precision_at_theta`, `mrr`, `ndcg`, `faithfulness`, `groundedness`, `answer_relevancy`, `hallucination_rate` |
| Ranking evaluation | `counterfactual_pass_rate`, `ranking_stability_rate`, `ndcg_at_10` (synthetic), `inter_rater_agreement` |
| Key findings | 1-5 bullet points of the most important takeaways |
| Recommendation | Retire / promote / investigate |

**Document-Aware report is generated once** from the existing 721 chunk files. Recursive reports are generated per experiment at scoring time. The `reports/` tree is **fully tracked by git** — reports are small text files (a few KB each) and the historical record of every experiment matters. Binaries stay in `.gitignore`; reports do not.

