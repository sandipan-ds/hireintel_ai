# Role Baseline Report: BusinessAnalyst

This report compares a **Raw Vector Similarity Baseline** (Cosine similarity of JD sub-queries against resume chunks) with the **Production LLM Rubric Scorer**.

## 📈 Alignment Metrics
* **Spearman's Rank Correlation (Rho):** 0.3667 (p-value: 1.52e-05)
* **Kendall's Tau Correlation:** 0.2521 (p-value: 1.80e-05)
* **Jaccard Overlap @ Top-10:** 0.1111

## 📊 Top 10 Comparison

| Rank | Raw Embedding Baseline (No-LLM) | Production LLM Rubric Scorer |
| :---: | :--- | :--- |
| 1 | BusinessAnalyst_CAND_0034 (60.89%) | BusinessAnalyst_CAND_0075 (82.44%) |
| 2 | BusinessAnalyst_CAND_0080 (60.65%) | BusinessAnalyst_CAND_0025 (80.81%) |
| 3 | BusinessAnalyst_CAND_0108 (60.58%) | BusinessAnalyst_CAND_0047 (78.33%) |
| 4 | BusinessAnalyst_CAND_0131 (60.49%) | BusinessAnalyst_CAND_0054 (77.19%) |
| 5 | BusinessAnalyst_CAND_0021 (60.23%) | BusinessAnalyst_CAND_0131 (76.85%) |
| 6 | BusinessAnalyst_CAND_0064 (60.04%) | BusinessAnalyst_CAND_0088 (76.27%) |
| 7 | BusinessAnalyst_CAND_0053 (59.77%) | BusinessAnalyst_CAND_0028 (75.64%) |
| 8 | BusinessAnalyst_CAND_0132 (59.76%) | BusinessAnalyst_CAND_0033 (75.03%) |
| 9 | BusinessAnalyst_CAND_0014 (59.69%) | BusinessAnalyst_CAND_0059 (75.02%) |
| 10 | BusinessAnalyst_CAND_0054 (59.63%) | BusinessAnalyst_CAND_0089 (72.90%) |

## 💡 Findings
1. **Clustering:** The raw embedding top 10 scores span only **1.26%**, failing to differentiate candidates.
2. **Correlation:** A rank correlation of **0.3667** indicates that raw vector lookup behaves fundamentally differently from structured human-aligned grading.
