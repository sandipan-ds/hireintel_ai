# Rank Stability Report — test_ranking_fix / WebDesigning

- **Schema version:** 1.0
- **Created at:** 2026-07-12T12:23:40Z
- **Trials:** 2
- **Pairs compared:** 1

## Shortlist overlap

- **top_10_jaccard:** `0.3333` (soft target ≥ 0.60)
- **top_50_jaccard:** `0.5385`

## Positional movement

- **max_rank_shift:** `56.00` (soft target ≤ 50)
- **mean_abs_rank_shift:** `14.4643` (soft target ≤ 15)

## Distribution shape agreement

- **kendall_tau:** `0.6322` (soft target ≥ 0.60)
- **spearman_rho:** `0.8208` (soft target ≥ 0.65)

## Shortlist churn

- **newcomer_rate_top_10:** `0.5000` (soft target ≤ 0.30)
- **drop_rate_top_10:** `0.5000`

## HP axis explained variance (R^2 of mean_abs_rank_shift)

| HP axis | R^2 |
| --- | ---: |
| `chunk_overlap` | `0.0000` |
| `chunk_size` | `0.0000` |
| `threshold` | `0.0000` |
| `top_k` | `0.0000` |

## Flags (informational — review before promotion)

- top_10_jaccard=0.333 < 0.60 shortlist overlap is below the soft target
- max_rank_shift=56.0 > 50 a candidate swings more than the soft cap across HP perturbations
- newcomer_rate_top_10=0.500 > 0.30 shortlist turnover exceeds the soft target
