# Rank Stability Report — hpo_sweep_datascience_100 / DataScience

- **Schema version:** 1.0
- **Created at:** 2026-07-12T12:55:58Z
- **Trials:** 100
- **Pairs compared:** 4950

## Shortlist overlap

- **top_10_jaccard:** `0.3962` (soft target ≥ 0.60)
- **top_50_jaccard:** `1.0000`

## Positional movement

- **max_rank_shift:** `35.00` (soft target ≤ 50)
- **mean_abs_rank_shift:** `7.5675` (soft target ≤ 15)

## Distribution shape agreement

- **kendall_tau:** `0.4877` (soft target ≥ 0.60)
- **spearman_rho:** `0.5986` (soft target ≥ 0.65)

## Shortlist churn

- **newcomer_rate_top_10:** `0.4746` (soft target ≤ 0.30)
- **drop_rate_top_10:** `0.4746`

## HP axis explained variance (R^2 of mean_abs_rank_shift)

| HP axis | R^2 |
| --- | ---: |
| `threshold` | `0.5066` |
| `chunk_size` | `0.0056` |
| `chunk_overlap` | `0.0015` |
| `top_k` | `0.0007` |

## Flags (informational — review before promotion)

- top_10_jaccard=0.396 < 0.60 shortlist overlap is below the soft target
- kendall_tau=0.488 < 0.60 pairwise ordering agreement is below the soft target
- spearman_rho=0.599 < 0.65 monotonic ordering agreement is below the soft target
- newcomer_rate_top_10=0.475 > 0.30 shortlist turnover exceeds the soft target
