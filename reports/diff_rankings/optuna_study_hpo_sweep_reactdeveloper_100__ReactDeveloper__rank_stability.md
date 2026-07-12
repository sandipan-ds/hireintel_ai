# Rank Stability Report — hpo_sweep_reactdeveloper_100 / ReactDeveloper

- **Schema version:** 1.0
- **Created at:** 2026-07-12T13:04:21Z
- **Trials:** 100
- **Pairs compared:** 4950

## Shortlist overlap

- **top_10_jaccard:** `0.6201` (soft target ≥ 0.60)
- **top_50_jaccard:** `1.0000`

## Positional movement

- **max_rank_shift:** `14.00` (soft target ≤ 50)
- **mean_abs_rank_shift:** `3.3075` (soft target ≤ 15)

## Distribution shape agreement

- **kendall_tau:** `0.4838` (soft target ≥ 0.60)
- **spearman_rho:** `0.5659` (soft target ≥ 0.65)

## Shortlist churn

- **newcomer_rate_top_10:** `0.2551` (soft target ≤ 0.30)
- **drop_rate_top_10:** `0.2551`

## HP axis explained variance (R^2 of mean_abs_rank_shift)

| HP axis | R^2 |
| --- | ---: |
| `threshold` | `0.6265` |
| `top_k` | `0.0011` |
| `chunk_size` | `0.0003` |
| `chunk_overlap` | `0.0002` |

## Flags (informational — review before promotion)

- kendall_tau=0.484 < 0.60 pairwise ordering agreement is below the soft target
- spearman_rho=0.566 < 0.65 monotonic ordering agreement is below the soft target
