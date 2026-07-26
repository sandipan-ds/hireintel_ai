# Candidate Ranking Variation Analysis Report

This document records the empirical consistency and rank variation metrics across independent candidate evaluation runs stored locally in `recruiter/data/scores/composed/`.

---

## Executive Summary

- **Top 1 Consistency**: **100.0%** across both analyzed role categories (**Orlando Campa** for Business Analyst Lead, **CAND_0001** for React Developer).
- **Top 3 Consistency**:
  - **Business Analyst Lead**: **33.3%** strict common across all 3 runs (Average Pairwise Overlap: **44.4%**).
  - **Verify React Developer**: **100.0%** strict common across all 8 runs (Average Pairwise Overlap: **100.0%**).
- **Top 5 Consistency**:
  - **Business Analyst Lead**: **40.0%** strict common across all 3 runs (Average Pairwise Overlap: **66.7%**).
  - **Verify React Developer**: **60.0%** (3/5 common across all 8 runs; total pool size: 3 candidates).

---

## 1. Business Analyst Lead (3 Runs Analyzed)

### Candidate Name Mappings
- `CAND_0001`: **Orlando Campa**
- `CAND_0002`: **Mary O'Brien**
- `CAND_0003`: **Robert Smith**
- `CAND_0004`: **Jestina Mangol**
- `CAND_0005`: **Allen Chaudhari**
- `CAND_0006`: **Glenn D. Young**

### Run-by-Run Leaderboard Comparison

| Run / File | Top 1 | Top 3 | Top 5 |
|---|---|---|---|
| **Run 1** (`20260715_7da59bc2`) | Orlando Campa (`0001`) | `[0001, 0007, 0006]` | `[0001, 0007, 0006, 0002, 0005]` |
| **Run 2** (`20260716_4b55b9ac`) | Orlando Campa (`0001`) | `[0001, 0002, 0007]` | `[0001, 0002, 0007, 0006, 0004]` |
| **Run 3** (`20260716_ebec8999`) | Orlando Campa (`0001`) | `[0001, 0004, 0003]` | `[0001, 0004, 0003, 0005, 0006]` |

### Consistency Metrics
- **Top 1 Common**: **100.0%** (1/1 common) — **Orlando Campa** (`0001`) ranked #1 in 100% of runs.
- **Top 3 Common**: **33.3%** strict common across ALL runs (Average Pairwise Overlap: **44.4%**)
  - Common candidate: **Orlando Campa** (`0001`).
- **Top 5 Common**: **40.0%** strict common across ALL runs (Average Pairwise Overlap: **66.7%**)
  - Common candidates: **Orlando Campa** (`0001`), **Glenn D. Young** (`0006`).

---

## 2. Verify React Developer (8 Runs Analyzed)

### Run-by-Run Leaderboard Comparison

Across 8 independent benchmark runs (`20260714` to `20260715`):
- `VerifyReactDeveloper_20260714_492790e6_ranked.json`: Top 3 `[CAND_0001, CAND_0002, CAND_0003]`
- `VerifyReactDeveloper_20260714_8e58f58b_ranked.json`: Top 3 `[CAND_0001, CAND_0002, CAND_0003]`
- `VerifyReactDeveloper_20260714_8e59331c_ranked.json`: Top 3 `[CAND_0001, CAND_0002, CAND_0003]`
- `VerifyReactDeveloper_20260714_b2aba0cd_ranked.json`: Top 3 `[CAND_0001, CAND_0002, CAND_0003]`
- `VerifyReactDeveloper_20260714_b92a3c1a_ranked.json`: Top 3 `[CAND_0001, CAND_0002, CAND_0003]`
- `VerifyReactDeveloper_20260714_ranked.json`: Top 3 `[CAND_0001, CAND_0002, CAND_0003]`
- `VerifyReactDeveloper_20260715_9f32fec1_ranked.json`: Top 3 `[CAND_0001, CAND_0002, CAND_0003]`
- `VerifyReactDeveloper_20260715_bb9e0b8a_ranked.json`: Top 3 `[CAND_0001, CAND_0002, CAND_0003]`

### Consistency Metrics
- **Top 1 Common**: **100.0%** (1/1 common) — `CAND_0001` took #1 rank in 100% of runs.
- **Top 3 Common**: **100.0%** (3/3 common) — Exact same set of 3 candidates in 100% of runs.
- **Top 5 Common**: **60.0%** (3/5 common; pool size = 3 candidates).

---

## Summary Comparative Table

| Role | Top 1 Common % | Top 3 Common % (Strict / Avg Pairwise) | Top 5 Common % (Strict / Avg Pairwise) | Total Pool Size |
|---|---|---|---|---|
| **Business Analyst Lead** (3 Runs) | **100.0%** (`Orlando Campa`) | **33.3%** / **44.4%** | **40.0%** / **66.7%** | 10 Candidates |
| **Verify React Developer** (8 Runs) | **100.0%** (`CAND_0001`) | **100.0%** / **100.0%** | **60.0%** / **60.0%** | 3 Candidates |
