# Rank Stability Report — hpo_sweep_webdesigning_100 / WebDesigning

- **Schema version:** 1.0
- **Created at:** 2026-07-12T13:50:00Z
- **Trials:** 100
- **Pairs compared:** 4950

## Shortlist overlap

- **top_10_jaccard:** `0.4891` (soft target ≥ 0.60)
- **top_50_jaccard:** `0.7051`

## Positional movement

- **max_rank_shift:** `105.00` (soft target ≤ 50)
- **mean_abs_rank_shift:** `12.3092` (soft target ≤ 15)

## Distribution shape agreement

- **kendall_tau:** `0.6919` (soft target ≥ 0.60)
- **spearman_rho:** `0.8335` (soft target ≥ 0.65)

## Shortlist churn

- **newcomer_rate_top_10:** `0.3765` (soft target ≤ 0.30)
- **drop_rate_top_10:** `0.3765`

## HP axis explained variance (R^2 of mean_abs_rank_shift)

| HP axis | R^2 |
| --- | ---: |
| `threshold` | `0.4896` |
| `top_k` | `0.0025` |
| `chunk_overlap` | `0.0010` |
| `chunk_size` | `0.0002` |

## Flags (informational — review before promotion)

- top_10_jaccard=0.489 < 0.60 shortlist overlap is below the soft target
- max_rank_shift=105.0 > 50 a candidate swings more than the soft cap across HP perturbations
- newcomer_rate_top_10=0.377 > 0.30 shortlist turnover exceeds the soft target
