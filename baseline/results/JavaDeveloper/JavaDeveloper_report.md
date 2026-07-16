# Role Baseline Report: JavaDeveloper

This report compares a **Raw Vector Similarity Baseline** (Cosine similarity of JD sub-queries against resume chunks) with the **Production LLM Rubric Scorer**.

## 📈 Alignment Metrics
* **Spearman's Rank Correlation (Rho):** 0.0846 (p-value: 4.89e-01)
* **Kendall's Tau Correlation:** 0.0554 (p-value: 5.01e-01)
* **Jaccard Overlap @ Top-10:** 0.0526

## 📊 Top 10 Comparison

| Rank | Raw Embedding Baseline (No-LLM) | Production LLM Rubric Scorer |
| :---: | :--- | :--- |
| 1 | JavaDeveloper_CAND_0016 (60.75%) | JavaDeveloper_CAND_0018 (80.29%) |
| 2 | JavaDeveloper_CAND_0007 (60.69%) | JavaDeveloper_CAND_0047 (77.53%) |
| 3 | JavaDeveloper_CAND_0040 (60.64%) | JavaDeveloper_CAND_0045 (77.38%) |
| 4 | JavaDeveloper_CAND_0015 (60.64%) | JavaDeveloper_CAND_0065 (76.96%) |
| 5 | JavaDeveloper_CAND_0005 (60.58%) | JavaDeveloper_CAND_0013 (76.26%) |
| 6 | JavaDeveloper_CAND_0058 (60.47%) | JavaDeveloper_CAND_0002 (73.92%) |
| 7 | JavaDeveloper_CAND_0060 (60.26%) | JavaDeveloper_CAND_0064 (71.82%) |
| 8 | JavaDeveloper_CAND_0065 (60.19%) | JavaDeveloper_CAND_0066 (71.73%) |
| 9 | JavaDeveloper_CAND_0036 (60.03%) | JavaDeveloper_CAND_0046 (70.53%) |
| 10 | JavaDeveloper_CAND_0032 (60.03%) | JavaDeveloper_CAND_0042 (70.37%) |

## 💡 Findings
1. **Clustering:** The raw embedding top 10 scores span only **0.72%**, failing to differentiate candidates.
2. **Correlation:** A rank correlation of **0.0846** indicates that raw vector lookup behaves fundamentally differently from structured human-aligned grading.
