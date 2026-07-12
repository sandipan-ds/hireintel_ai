# Baseline-Centric Rank Stability Report — SalesManager

- **Created at:** 2026-07-12T15:23:26Z
- **Configurations evaluated:** 44
- **Baseline locked parameters:** {'config_id': 'baseline_v1', 'locked_at': '2026-07-12', 'chunk_size': 1000, 'chunk_overlap': 500, 'top_k': 20, 'theta': 0.35, 'embedding_model': 'all-MiniLM-L6-v2', 'note': 'Baseline derived from first production scoring run. Fixed per 18_EVALUATION.md §Baseline Configuration.'}

## Summary Metrics (Average vs Baseline)

| Metric | Value | Soft Target | Status |
| :--- | ---: | :---: | :---: |
| **Top-10 Jaccard (Overlap)** | `0.3839` | `≥ 0.60` | ⚠️ Review |
| **Top-50 Jaccard (Overlap)** | `0.6998` | — | — |
| **Worst-Case Max Rank Shift** | `118.0` | `≤ 50.0` | ⚠️ Review |
| **Mean Absolute Rank Shift** | `16.3478` | `≤ 15.0` | ⚠️ Review |
| **Median Absolute Rank Shift** | `15.0488` | — | — |
| **P95 Absolute Rank Shift** | `31.1665` | — | — |
| **Kendall Tau** | `0.7198` | `≥ 0.60` | ✅ Pass |
| **Spearman Rho** | `0.8590` | `≥ 0.65` | ✅ Pass |
| **Mean Newcomer Rate (Top-10)** | `0.4636` | `≤ 0.30` | ⚠️ Review |
| **Mean Drop Rate (Top-10)** | `0.4636` | — | — |

## Hyperparameter Axis Sensitivity (Explained Variance R^2)

| Hyperparameter | R^2 |
| :--- | ---: |
| `theta` | `0.1195` |
| `chunk_overlap` | `0.0089` |
| `chunk_size` | `0.0089` |
| `top_k` | `0.0034` |

## Safe Operating Verdict

> [!WARNING]
> **VERDICT: REVIEW**
> High ranking sensitivity detected. Recommend restricting the allowed similarity threshold bounds or checking edge-case candidate chunks.