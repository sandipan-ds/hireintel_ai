# Role Baseline Report: SrPythonDeveloper

This report compares a **Raw Vector Similarity Baseline** (Cosine similarity of JD sub-queries against resume chunks) with the **Production LLM Rubric Scorer**.

## 📈 Alignment Metrics
* **Spearman's Rank Correlation (Rho):** 0.4902 (p-value: 3.99e-07)
* **Kendall's Tau Correlation:** 0.3461 (p-value: 5.89e-07)
* **Jaccard Overlap @ Top-10:** 0.1765

## 📊 Top 10 Comparison

| Rank | Raw Embedding Baseline (No-LLM) | Production LLM Rubric Scorer |
| :---: | :--- | :--- |
| 1 | SrPythonDeveloper_CAND_0010 (61.06%) | SrPythonDeveloper_CAND_0009 (84.71%) |
| 2 | SrPythonDeveloper_CAND_0052 (61.06%) | SrPythonDeveloper_CAND_0077 (84.16%) |
| 3 | SrPythonDeveloper_CAND_0026 (60.59%) | SrPythonDeveloper_CAND_0066 (82.99%) |
| 4 | SrPythonDeveloper_CAND_0078 (60.55%) | SrPythonDeveloper_CAND_0063 (80.50%) |
| 5 | SrPythonDeveloper_CAND_0065 (60.48%) | SrPythonDeveloper_CAND_0093 (80.50%) |
| 6 | SrPythonDeveloper_CAND_0073 (60.48%) | SrPythonDeveloper_CAND_0092 (74.42%) |
| 7 | SrPythonDeveloper_CAND_0087 (60.48%) | SrPythonDeveloper_CAND_0094 (73.35%) |
| 8 | SrPythonDeveloper_CAND_0093 (60.39%) | SrPythonDeveloper_CAND_0076 (72.61%) |
| 9 | SrPythonDeveloper_CAND_0063 (60.39%) | SrPythonDeveloper_CAND_0080 (72.25%) |
| 10 | SrPythonDeveloper_CAND_0009 (60.31%) | SrPythonDeveloper_CAND_0051 (70.79%) |

## 💡 Findings
1. **Clustering:** The raw embedding top 10 scores span only **0.75%**, failing to differentiate candidates.
2. **Correlation:** A rank correlation of **0.4902** indicates that raw vector lookup behaves fundamentally differently from structured human-aligned grading.
