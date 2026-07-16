# Role Baseline Report: WebDesigning

This report compares a **Raw Vector Similarity Baseline** (Cosine similarity of JD sub-queries against resume chunks) with the **Production LLM Rubric Scorer**.

## 📈 Alignment Metrics
* **Spearman's Rank Correlation (Rho):** 0.2833 (p-value: 3.11e-03)
* **Kendall's Tau Correlation:** 0.1956 (p-value: 2.83e-03)
* **Jaccard Overlap @ Top-10:** 0.0000

## 📊 Top 10 Comparison

| Rank | Raw Embedding Baseline (No-LLM) | Production LLM Rubric Scorer |
| :---: | :--- | :--- |
| 1 | WebDesigning_CAND_0051 (62.14%) | WebDesigning_CAND_0067 (75.41%) |
| 2 | WebDesigning_CAND_0071 (62.00%) | WebDesigning_CAND_0014 (74.22%) |
| 3 | WebDesigning_CAND_0042 (61.98%) | WebDesigning_CAND_0112 (72.66%) |
| 4 | WebDesigning_CAND_0033 (61.92%) | WebDesigning_CAND_0047 (71.57%) |
| 5 | WebDesigning_CAND_0054 (61.75%) | WebDesigning_CAND_0003 (69.32%) |
| 6 | WebDesigning_CAND_0082 (61.75%) | WebDesigning_CAND_0099 (69.11%) |
| 7 | WebDesigning_CAND_0011 (61.48%) | WebDesigning_CAND_0058 (67.83%) |
| 8 | WebDesigning_CAND_0074 (61.43%) | WebDesigning_CAND_0041 (67.69%) |
| 9 | WebDesigning_CAND_0078 (61.40%) | WebDesigning_CAND_0049 (66.08%) |
| 10 | WebDesigning_CAND_0015 (61.40%) | WebDesigning_CAND_0068 (64.95%) |

## 💡 Findings
1. **Clustering:** The raw embedding top 10 scores span only **0.74%**, failing to differentiate candidates.
2. **Correlation:** A rank correlation of **0.2833** indicates that raw vector lookup behaves fundamentally differently from structured human-aligned grading.
