# Role Baseline Report: SQLDeveloper

This report compares a **Raw Vector Similarity Baseline** (Cosine similarity of JD sub-queries against resume chunks) with the **Production LLM Rubric Scorer**.

## 📈 Alignment Metrics
* **Spearman's Rank Correlation (Rho):** 0.0017 (p-value: 9.88e-01)
* **Kendall's Tau Correlation:** -0.0012 (p-value: 9.87e-01)
* **Jaccard Overlap @ Top-10:** 0.1111

## 📊 Top 10 Comparison

| Rank | Raw Embedding Baseline (No-LLM) | Production LLM Rubric Scorer |
| :---: | :--- | :--- |
| 1 | SQLDeveloper_CAND_0052 (63.52%) | SQLDeveloper_CAND_0024 (94.27%) |
| 2 | SQLDeveloper_CAND_0024 (62.29%) | SQLDeveloper_CAND_0008 (85.64%) |
| 3 | SQLDeveloper_CAND_0036 (62.25%) | SQLDeveloper_CAND_0001 (84.64%) |
| 4 | SQLDeveloper_CAND_0023 (62.01%) | SQLDeveloper_CAND_0033 (83.75%) |
| 5 | SQLDeveloper_CAND_0013 (61.92%) | SQLDeveloper_CAND_0043 (81.67%) |
| 6 | SQLDeveloper_CAND_0062 (61.92%) | SQLDeveloper_CAND_0023 (81.38%) |
| 7 | SQLDeveloper_CAND_0055 (61.90%) | SQLDeveloper_CAND_0047 (80.34%) |
| 8 | SQLDeveloper_CAND_0018 (61.89%) | SQLDeveloper_CAND_0067 (79.73%) |
| 9 | SQLDeveloper_CAND_0004 (61.75%) | SQLDeveloper_CAND_0007 (79.39%) |
| 10 | SQLDeveloper_CAND_0003 (61.67%) | SQLDeveloper_CAND_0040 (78.21%) |

## 💡 Findings
1. **Clustering:** The raw embedding top 10 scores span only **1.86%**, failing to differentiate candidates.
2. **Correlation:** A rank correlation of **0.0017** indicates that raw vector lookup behaves fundamentally differently from structured human-aligned grading.
