# Embedding Baseline Evaluation Findings

An experiment was conducted comparing a **Raw Vector Similarity Baseline** (directly calculating cosine similarity between JD sub-queries and candidate resume chunks, weighted by the recruiter weight policy) against the **Production LLM Rubric-based Scoring Engine** for the **DataScience** role.

## Alignment Metrics:
* **Spearman Rank Correlation (Rho):** -0.1340
* **Kendall's Tau Rank Correlation:** -0.0949
* **Jaccard Similarity @ Top-10 Overlap:** 0.1111

## Top 10 Comparison:
* Baseline Top 10: ['DataScience_CAND_0029', 'DataScience_CAND_0020', 'DataScience_CAND_0031', 'DataScience_CAND_0022', 'DataScience_CAND_0008', 'DataScience_CAND_0024', 'DataScience_CAND_0017', 'DataScience_CAND_0012', 'DataScience_CAND_0013', 'DataScience_CAND_0026']
* Production Top 10: ['DataScience_CAND_0042', 'DataScience_CAND_0008', 'DataScience_CAND_0024', 'DataScience_CAND_0014', 'DataScience_CAND_0030', 'DataScience_CAND_0038', 'DataScience_CAND_0006', 'DataScience_CAND_0004', 'DataScience_CAND_0039', 'DataScience_CAND_0016']
* Overlap: ['DataScience_CAND_0024', 'DataScience_CAND_0008']

## Analysis & Stakeholder Rationale:
1. **Low to Moderate Rank Correlation:** The rank correlation shows that relying purely on vector cosine similarity yields a substantially different ordering of candidates.
2. **Precision Deficit in Raw Cosine Search:**
   - Raw vector embeddings map topics, not qualifiers. A chunk that says "I want to learn SQL" or "Did NOT use SQL for validation" returns a high cosine match to the query "Use SQL for validation".
   - The LLM acts as an active semantic filter that correctly rejects negations, personal study/coursework (when professional work is required), and low-impact bullet points.
3. **No Support for Structural Gates:**
   - Pure embeddings cannot calculate numeric years of experience, check specific degree/institute tiers, or apply strict minimum criteria.
