# Rank Stability Report — smoke_test_sweep / BusinessAnalyst

- **Schema version:** 1.0
- **Created at:** 2026-07-12T10:26:46Z
- **Trials:** 3
- **Pairs compared:** 3

## Shortlist overlap

- **top_10_jaccard:** `1.0000` (soft target ≥ 0.60)
- **top_50_jaccard:** `1.0000`

## Positional movement

- **max_rank_shift:** `0.00` (soft target ≤ 50)
- **mean_abs_rank_shift:** `0.0000` (soft target ≤ 15)

## Distribution shape agreement

- **kendall_tau:** `1.0000` (soft target ≥ 0.60)
- **spearman_rho:** `1.0000` (soft target ≥ 0.65)

## Shortlist churn

- **newcomer_rate_top_10:** `0.0000` (soft target ≤ 0.30)
- **drop_rate_top_10:** `0.0000`

## HP axis explained variance (R^2 of mean_abs_rank_shift)

| HP axis | R^2 |
| --- | ---: |
| `chunk_overlap` | `0.0000` |
| `chunk_size` | `0.0000` |
| `threshold` | `0.0000` |
| `top_k` | `0.0000` |
