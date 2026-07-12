# Baseline-Centric Rank Stability Report — JavaDeveloper

- **Created at:** 2026-07-12T15:23:26Z
- **Configurations evaluated:** 44
- **Baseline locked parameters:** {'config_id': 'baseline_v1', 'locked_at': '2026-07-12', 'chunk_size': 1000, 'chunk_overlap': 500, 'top_k': 20, 'theta': 0.35, 'embedding_model': 'all-MiniLM-L6-v2', 'note': 'Baseline derived from first production scoring run. Fixed per 18_EVALUATION.md §Baseline Configuration.'}

## Summary Metrics (Average vs Baseline)

| Metric | Value | Soft Target | Status |
| :--- | ---: | :---: | :---: |
| **Top-10 Jaccard (Overlap)** | `0.5472` | `≥ 0.60` | ⚠️ Review |
| **Top-50 Jaccard (Overlap)** | `0.8943` | — | — |
| **Worst-Case Max Rank Shift** | `38.0` | `≤ 50.0` | ✅ Pass |
| **Mean Absolute Rank Shift** | `6.3068` | `≤ 15.0` | ✅ Pass |
| **Median Absolute Rank Shift** | `6.3611` | — | — |
| **P95 Absolute Rank Shift** | `10.8250` | — | — |
| **Kendall Tau** | `0.7634` | `≥ 0.60` | ✅ Pass |
| **Spearman Rho** | `0.9045` | `≥ 0.65` | ✅ Pass |
| **Mean Newcomer Rate (Top-10)** | `0.3068` | `≤ 0.30` | ⚠️ Review |
| **Mean Drop Rate (Top-10)** | `0.3068` | — | — |

## Hyperparameter Axis Sensitivity (Explained Variance R^2)

| Hyperparameter | R^2 |
| :--- | ---: |
| `theta` | `0.3355` |
| `chunk_overlap` | `0.0077` |
| `chunk_size` | `0.0077` |
| `top_k` | `0.0044` |

## Safe Operating Verdict

> [!WARNING]
> **VERDICT: REVIEW**
> High ranking sensitivity detected. Recommend restricting the allowed similarity threshold bounds or checking edge-case candidate chunks.