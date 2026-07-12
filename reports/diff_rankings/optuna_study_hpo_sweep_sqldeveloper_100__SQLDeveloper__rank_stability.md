# Rank Stability Report — hpo_sweep_sqldeveloper_100 / SQLDeveloper

- **Schema version:** 1.0
- **Created at:** 2026-07-12T13:27:58Z
- **Trials:** 100
- **Pairs compared:** 4950

## Shortlist overlap

- **top_10_jaccard:** `0.5772` (soft target ≥ 0.60)
- **top_50_jaccard:** `0.7093`

## Positional movement

- **max_rank_shift:** `77.00` (soft target ≤ 50)
- **mean_abs_rank_shift:** `12.1335` (soft target ≤ 15)

## Distribution shape agreement

- **kendall_tau:** `0.5967` (soft target ≥ 0.60)
- **spearman_rho:** `0.7261` (soft target ≥ 0.65)

## Shortlist churn

- **newcomer_rate_top_10:** `0.2860` (soft target ≤ 0.30)
- **drop_rate_top_10:** `0.2860`

## HP axis explained variance (R^2 of mean_abs_rank_shift)

| HP axis | R^2 |
| --- | ---: |
| `threshold` | `0.4935` |
| `chunk_overlap` | `0.0003` |
| `top_k` | `0.0001` |
| `chunk_size` | `0.0000` |

## Flags (informational — review before promotion)

- top_10_jaccard=0.577 < 0.60 shortlist overlap is below the soft target
- max_rank_shift=77.0 > 50 a candidate swings more than the soft cap across HP perturbations
- kendall_tau=0.597 < 0.60 pairwise ordering agreement is below the soft target
