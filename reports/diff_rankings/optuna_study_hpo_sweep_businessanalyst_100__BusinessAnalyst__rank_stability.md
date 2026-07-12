# Rank Stability Report — hpo_sweep_businessanalyst_100 / BusinessAnalyst

- **Schema version:** 1.0
- **Created at:** 2026-07-12T12:52:16Z
- **Trials:** 100
- **Pairs compared:** 4950

## Shortlist overlap

- **top_10_jaccard:** `0.3724` (soft target ≥ 0.60)
- **top_50_jaccard:** `0.5915`

## Positional movement

- **max_rank_shift:** `126.00` (soft target ≤ 50)
- **mean_abs_rank_shift:** `20.0977` (soft target ≤ 15)

## Distribution shape agreement

- **kendall_tau:** `0.5741` (soft target ≥ 0.60)
- **spearman_rho:** `0.7081` (soft target ≥ 0.65)

## Shortlist churn

- **newcomer_rate_top_10:** `0.4980` (soft target ≤ 0.30)
- **drop_rate_top_10:** `0.4980`

## HP axis explained variance (R^2 of mean_abs_rank_shift)

| HP axis | R^2 |
| --- | ---: |
| `threshold` | `0.5717` |
| `chunk_overlap` | `0.0047` |
| `chunk_size` | `0.0019` |
| `top_k` | `0.0002` |

## Flags (informational — review before promotion)

- top_10_jaccard=0.372 < 0.60 shortlist overlap is below the soft target
- max_rank_shift=126.0 > 50 a candidate swings more than the soft cap across HP perturbations
- mean_abs_rank_shift=20.1 > 15 average positional movement exceeds the soft target
- kendall_tau=0.574 < 0.60 pairwise ordering agreement is below the soft target
- newcomer_rate_top_10=0.498 > 0.30 shortlist turnover exceeds the soft target
