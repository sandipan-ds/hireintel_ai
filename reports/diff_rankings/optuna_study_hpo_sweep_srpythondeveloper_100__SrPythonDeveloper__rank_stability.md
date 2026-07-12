# Rank Stability Report — hpo_sweep_srpythondeveloper_100 / SrPythonDeveloper

- **Schema version:** 1.0
- **Created at:** 2026-07-12T13:39:25Z
- **Trials:** 100
- **Pairs compared:** 4950

## Shortlist overlap

- **top_10_jaccard:** `0.4932` (soft target ≥ 0.60)
- **top_50_jaccard:** `0.8234`

## Positional movement

- **max_rank_shift:** `90.00` (soft target ≤ 50)
- **mean_abs_rank_shift:** `8.7979` (soft target ≤ 15)

## Distribution shape agreement

- **kendall_tau:** `0.7538` (soft target ≥ 0.60)
- **spearman_rho:** `0.8941` (soft target ≥ 0.65)

## Shortlist churn

- **newcomer_rate_top_10:** `0.3699` (soft target ≤ 0.30)
- **drop_rate_top_10:** `0.3699`

## HP axis explained variance (R^2 of mean_abs_rank_shift)

| HP axis | R^2 |
| --- | ---: |
| `threshold` | `0.5204` |
| `chunk_size` | `0.0017` |
| `top_k` | `0.0006` |
| `chunk_overlap` | `0.0001` |

## Flags (informational — review before promotion)

- top_10_jaccard=0.493 < 0.60 shortlist overlap is below the soft target
- max_rank_shift=90.0 > 50 a candidate swings more than the soft cap across HP perturbations
- newcomer_rate_top_10=0.370 > 0.30 shortlist turnover exceeds the soft target
