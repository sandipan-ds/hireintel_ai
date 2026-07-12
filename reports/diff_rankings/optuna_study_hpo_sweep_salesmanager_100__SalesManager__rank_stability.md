# Rank Stability Report — hpo_sweep_salesmanager_100 / SalesManager

- **Schema version:** 1.0
- **Created at:** 2026-07-12T13:22:00Z
- **Trials:** 100
- **Pairs compared:** 4950

## Shortlist overlap

- **top_10_jaccard:** `0.4085` (soft target ≥ 0.60)
- **top_50_jaccard:** `0.6856`

## Positional movement

- **max_rank_shift:** `141.00` (soft target ≤ 50)
- **mean_abs_rank_shift:** `17.1314` (soft target ≤ 15)

## Distribution shape agreement

- **kendall_tau:** `0.7041` (soft target ≥ 0.60)
- **spearman_rho:** `0.8492` (soft target ≥ 0.65)

## Shortlist churn

- **newcomer_rate_top_10:** `0.4470` (soft target ≤ 0.30)
- **drop_rate_top_10:** `0.4470`

## HP axis explained variance (R^2 of mean_abs_rank_shift)

| HP axis | R^2 |
| --- | ---: |
| `threshold` | `0.3915` |
| `chunk_overlap` | `0.0221` |
| `chunk_size` | `0.0131` |
| `top_k` | `0.0000` |

## Flags (informational — review before promotion)

- top_10_jaccard=0.408 < 0.60 shortlist overlap is below the soft target
- max_rank_shift=141.0 > 50 a candidate swings more than the soft cap across HP perturbations
- mean_abs_rank_shift=17.1 > 15 average positional movement exceeds the soft target
- newcomer_rate_top_10=0.447 > 0.30 shortlist turnover exceeds the soft target
