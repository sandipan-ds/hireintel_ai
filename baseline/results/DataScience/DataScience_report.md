# Role Baseline Report: DataScience

This report compares a **Raw Vector Similarity Baseline** (Cosine similarity of JD sub-queries against resume chunks) with the **Production LLM Rubric Scorer**.

## 📈 Alignment Metrics
* **Spearman's Rank Correlation (Rho):** -0.1340 (p-value: 4.10e-01)
* **Kendall's Tau Correlation:** -0.0949 (p-value: 3.89e-01)
* **Jaccard Overlap @ Top-10:** 0.1111

## 📊 Top 10 Comparison

| Rank | Raw Embedding Baseline (No-LLM) | Production LLM Rubric Scorer |
| :---: | :--- | :--- |
| 1 | DataScience_CAND_0029 (60.94%) | DataScience_CAND_0038 (75.13%) |
| 2 | DataScience_CAND_0008 (60.68%) | DataScience_CAND_0039 (74.08%) |
| 3 | DataScience_CAND_0022 (60.67%) | DataScience_CAND_0008 (73.55%) |
| 4 | DataScience_CAND_0026 (60.48%) | DataScience_CAND_0014 (71.01%) |
| 5 | DataScience_CAND_0031 (60.46%) | DataScience_CAND_0030 (69.80%) |
| 6 | DataScience_CAND_0024 (60.41%) | DataScience_CAND_0024 (69.68%) |
| 7 | DataScience_CAND_0020 (60.38%) | DataScience_CAND_0004 (68.72%) |
| 8 | DataScience_CAND_0012 (60.37%) | DataScience_CAND_0042 (68.08%) |
| 9 | DataScience_CAND_0013 (60.37%) | DataScience_CAND_0016 (66.20%) |
| 10 | DataScience_CAND_0017 (60.16%) | DataScience_CAND_0006 (65.82%) |

## 💡 Findings
1. **Clustering:** The raw embedding top 10 scores span only **0.78%**, failing to differentiate candidates.
2. **Correlation:** A rank correlation of **-0.1340** indicates that raw vector lookup behaves fundamentally differently from structured human-aligned grading.
