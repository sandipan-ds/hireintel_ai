# Baseline-Centric Rank Stability Report — SQLDeveloper

- **Created at:** 2026-07-12T15:23:26Z
- **Configurations evaluated:** 44
- **Baseline locked parameters:** {'config_id': 'baseline_v1', 'locked_at': '2026-07-12', 'chunk_size': 1000, 'chunk_overlap': 500, 'top_k': 20, 'theta': 0.35, 'embedding_model': 'all-MiniLM-L6-v2', 'note': 'Baseline derived from first production scoring run. Fixed per 18_EVALUATION.md §Baseline Configuration.'}

## Summary Metrics (Average vs Baseline)

| Metric | Value | Soft Target | Status |
| :--- | ---: | :---: | :---: |
| **Top-10 Jaccard (Overlap)** | `0.4399` | `≥ 0.60` | ⚠️ Review |
| **Top-50 Jaccard (Overlap)** | `0.7705` | — | — |
| **Worst-Case Max Rank Shift** | `67.0` | `≤ 50.0` | ⚠️ Review |
| **Mean Absolute Rank Shift** | `10.0394` | `≤ 15.0` | ✅ Pass |
| **Median Absolute Rank Shift** | `8.9024` | — | — |
| **P95 Absolute Rank Shift** | `20.1707` | — | — |
| **Kendall Tau** | `0.6660` | `≥ 0.60` | ✅ Pass |
| **Spearman Rho** | `0.7997` | `≥ 0.65` | ✅ Pass |
| **Mean Newcomer Rate (Top-10)** | `0.4159` | `≤ 0.30` | ⚠️ Review |
| **Mean Drop Rate (Top-10)** | `0.4159` | — | — |

## Hyperparameter Axis Sensitivity (Explained Variance R^2)

| Hyperparameter | R^2 |
| :--- | ---: |
| `theta` | `0.1345` |
| `top_k` | `0.0029` |
| `chunk_overlap` | `0.0006` |
| `chunk_size` | `0.0006` |

## Safe Operating Verdict

> [!WARNING]
> **VERDICT: REVIEW**
> High ranking sensitivity detected. Recommend restricting the allowed similarity threshold bounds or checking edge-case candidate chunks.