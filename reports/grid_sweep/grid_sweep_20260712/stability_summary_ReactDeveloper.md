# Baseline-Centric Rank Stability Report — ReactDeveloper

- **Created at:** 2026-07-12T15:23:26Z
- **Configurations evaluated:** 44
- **Baseline locked parameters:** {'config_id': 'baseline_v1', 'locked_at': '2026-07-12', 'chunk_size': 1000, 'chunk_overlap': 500, 'top_k': 20, 'theta': 0.35, 'embedding_model': 'all-MiniLM-L6-v2', 'note': 'Baseline derived from first production scoring run. Fixed per 18_EVALUATION.md §Baseline Configuration.'}

## Summary Metrics (Average vs Baseline)

| Metric | Value | Soft Target | Status |
| :--- | ---: | :---: | :---: |
| **Top-10 Jaccard (Overlap)** | `0.6723` | `≥ 0.60` | ✅ Pass |
| **Top-50 Jaccard (Overlap)** | `1.0000` | — | — |
| **Worst-Case Max Rank Shift** | `13.0` | `≤ 50.0` | ✅ Pass |
| **Mean Absolute Rank Shift** | `2.8106` | `≤ 15.0` | ✅ Pass |
| **Median Absolute Rank Shift** | `2.5556` | — | — |
| **P95 Absolute Rank Shift** | `6.1111` | — | — |
| **Kendall Tau** | `0.5829` | `≥ 0.60` | ⚠️ Review |
| **Spearman Rho** | `0.6955` | `≥ 0.65` | ✅ Pass |
| **Mean Newcomer Rate (Top-10)** | `0.2045` | `≤ 0.30` | ✅ Pass |
| **Mean Drop Rate (Top-10)** | `0.2045` | — | — |

## Hyperparameter Axis Sensitivity (Explained Variance R^2)

| Hyperparameter | R^2 |
| :--- | ---: |
| `theta` | `0.2464` |
| `chunk_overlap` | `0.0045` |
| `chunk_size` | `0.0045` |
| `top_k` | `0.0026` |

## Safe Operating Verdict

> [!TIP]
> **VERDICT: PASS**
> The shortlist is operationally stable and safe for recruiter use across all sweep boundaries.