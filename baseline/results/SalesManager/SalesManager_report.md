# Role Baseline Report: SalesManager

This report compares a **Raw Vector Similarity Baseline** (Cosine similarity of JD sub-queries against resume chunks) with the **Production LLM Rubric Scorer**.

## 📈 Alignment Metrics
* **Spearman's Rank Correlation (Rho):** 0.1674 (p-value: 3.32e-02)
* **Kendall's Tau Correlation:** 0.1037 (p-value: 5.00e-02)
* **Jaccard Overlap @ Top-10:** 0.1111

## 📊 Top 10 Comparison

| Rank | Raw Embedding Baseline (No-LLM) | Production LLM Rubric Scorer |
| :---: | :--- | :--- |
| 1 | SalesManager_CAND_0012 (63.49%) | SalesManager_CAND_0011 (83.12%) |
| 2 | SalesManager_CAND_0135 (63.23%) | SalesManager_CAND_0150 (81.46%) |
| 3 | SalesManager_CAND_0090 (63.16%) | SalesManager_CAND_0009 (80.33%) |
| 4 | SalesManager_CAND_0052 (62.84%) | SalesManager_CAND_0108 (78.00%) |
| 5 | SalesManager_CAND_0019 (62.61%) | SalesManager_CAND_0140 (76.58%) |
| 6 | SalesManager_CAND_0040 (62.52%) | SalesManager_CAND_0092 (75.23%) |
| 7 | SalesManager_CAND_0056 (62.44%) | SalesManager_CAND_0133 (75.17%) |
| 8 | SalesManager_CAND_0042 (62.25%) | SalesManager_CAND_0087 (74.08%) |
| 9 | SalesManager_CAND_0087 (62.23%) | SalesManager_CAND_0137 (74.00%) |
| 10 | SalesManager_CAND_0100 (62.13%) | SalesManager_CAND_0090 (73.89%) |

## 💡 Findings
1. **Clustering:** The raw embedding top 10 scores span only **1.35%**, failing to differentiate candidates.
2. **Correlation:** A rank correlation of **0.1674** indicates that raw vector lookup behaves fundamentally differently from structured human-aligned grading.
