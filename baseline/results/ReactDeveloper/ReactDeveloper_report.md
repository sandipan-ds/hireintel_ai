# Role Baseline Report: ReactDeveloper

This report compares a **Raw Vector Similarity Baseline** (Cosine similarity of JD sub-queries against resume chunks) with the **Production LLM Rubric Scorer**.

## 📈 Alignment Metrics
* **Spearman's Rank Correlation (Rho):** -0.0753 (p-value: 7.66e-01)
* **Kendall's Tau Correlation:** -0.0850 (p-value: 6.54e-01)
* **Jaccard Overlap @ Top-10:** 0.4286

## 📊 Top 10 Comparison

| Rank | Raw Embedding Baseline (No-LLM) | Production LLM Rubric Scorer |
| :---: | :--- | :--- |
| 1 | ReactDeveloper_CAND_0012 (61.76%) | ReactDeveloper_CAND_0004 (90.00%) |
| 2 | ReactDeveloper_CAND_0010 (61.53%) | ReactDeveloper_CAND_0014 (78.00%) |
| 3 | ReactDeveloper_CAND_0003 (61.35%) | ReactDeveloper_CAND_0001 (64.81%) |
| 4 | ReactDeveloper_CAND_0013 (61.31%) | ReactDeveloper_CAND_0015 (63.92%) |
| 5 | ReactDeveloper_CAND_0017 (61.25%) | ReactDeveloper_CAND_0010 (59.22%) |
| 6 | ReactDeveloper_CAND_0002 (61.16%) | ReactDeveloper_CAND_0018 (58.00%) |
| 7 | ReactDeveloper_CAND_0006 (61.10%) | ReactDeveloper_CAND_0009 (57.58%) |
| 8 | ReactDeveloper_CAND_0001 (61.04%) | ReactDeveloper_CAND_0013 (56.43%) |
| 9 | ReactDeveloper_CAND_0008 (61.01%) | ReactDeveloper_CAND_0012 (55.97%) |
| 10 | ReactDeveloper_CAND_0009 (60.06%) | ReactDeveloper_CAND_0006 (54.73%) |

## 💡 Findings
1. **Clustering:** The raw embedding top 10 scores span only **1.70%**, failing to differentiate candidates.
2. **Correlation:** A rank correlation of **-0.0753** indicates that raw vector lookup behaves fundamentally differently from structured human-aligned grading.
