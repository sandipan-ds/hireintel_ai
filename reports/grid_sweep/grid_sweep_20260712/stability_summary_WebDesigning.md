# Baseline-Centric Rank Stability Report — WebDesigning

- **Created at:** 2026-07-12T15:23:26Z
- **Configurations evaluated:** 44
- **Baseline locked parameters:** {'config_id': 'baseline_v1', 'locked_at': '2026-07-12', 'chunk_size': 1000, 'chunk_overlap': 500, 'top_k': 20, 'theta': 0.35, 'embedding_model': 'all-MiniLM-L6-v2', 'note': 'Baseline derived from first production scoring run. Fixed per 18_EVALUATION.md §Baseline Configuration.'}

## Summary Metrics (Average vs Baseline)

| Metric | Value | Soft Target | Status |
| :--- | ---: | :---: | :---: |
| **Top-10 Jaccard (Overlap)** | `0.4856` | `≥ 0.60` | ⚠️ Review |
| **Top-50 Jaccard (Overlap)** | `0.6984` | — | — |
| **Worst-Case Max Rank Shift** | `101.0` | `≤ 50.0` | ⚠️ Review |
| **Mean Absolute Rank Shift** | `12.1826` | `≤ 15.0` | ✅ Pass |
| **Median Absolute Rank Shift** | `11.3929` | — | — |
| **P95 Absolute Rank Shift** | `21.8054` | — | — |
| **Kendall Tau** | `0.6893` | `≥ 0.60` | ✅ Pass |
| **Spearman Rho** | `0.8308` | `≥ 0.65` | ✅ Pass |
| **Mean Newcomer Rate (Top-10)** | `0.3886` | `≤ 0.30` | ⚠️ Review |
| **Mean Drop Rate (Top-10)** | `0.3886` | — | — |

## Hyperparameter Axis Sensitivity (Explained Variance R^2)

| Hyperparameter | R^2 |
| :--- | ---: |
| `theta` | `0.1975` |
| `top_k` | `0.0031` |
| `chunk_overlap` | `0.0000` |
| `chunk_size` | `0.0000` |

## Safe Operating Verdict

> [!WARNING]
> **VERDICT: REVIEW**
> High ranking sensitivity detected. Recommend restricting the allowed similarity threshold bounds or checking edge-case candidate chunks.