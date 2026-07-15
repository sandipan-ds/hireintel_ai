# 📊 Comparing No-LLM Approaches: HireIntel.AI vs. Redrob vs. Pure Cosine

This document provides a comparative analysis of **HireIntel.AI** (hybrid RAG + LLM rubric scorer), the **Redrob Project** (100% no-LLM runtime), and **Pure Cosine Similarity** (baseline).

---

## 1. Context & constraints comparison

| Dimension | Pure Cosine Similarity | Redrob Project | HireIntel.AI |
| :--- | :--- | :--- | :--- |
| **Objective** | Keyword/semantic search | **Database Search** (rank top 100 of 100,000 candidates in $\le$ 5 minutes on CPU) | **Recruiter Screening** (rank and audit an intake batch of ~50-200 applicants) |
| **Runtime LLM** | None | **None** (Hosted APIs forbidden; local LLMs blow CPU time budget) | **Hybrid:** LLM acts as a **rubric-bound judge** on retrieved evidence; code handles factual rules |
| **Rank Mechanism** | Sort by raw similarity | Multi-feature composite (weights, behavioral multiplier, multiplicative penalty gates) | Deterministic score engine aggregating LLM rubric grades and factual year/degree math |
| **Explanation** | None | Deterministic string-template generation (~70 lines of Python, hallucination-free) | Context-aware, citation-backed waterfall RAG chat |

---

## 2. Technical implementation of similarity scoring

### Pure Cosine Similarity (Baseline)
* **Logic:** Computes the cosine similarity of the Job Description requirements against all candidate chunks:
  $$s = \text{embedding}(\text{Query}) \cdot \text{embedding}(\text{Resume Chunk})$$
* **Weaknesses:** Highly vulnerable to keyword stuffing, negations (*"did not use Python"*), aspirations (*"interested in ML"*), and fails to differentiate candidates (top-10 scores cluster within **<1.5%** variance).

### Redrob Project (No-LLM Advanced Caching)
To rank 100,000 candidates without an LLM under a strict 5-minute time limit, Redrob utilizes a **pre-computed, pooled, and weighted cosine similarity** system:
1. **Description-Only Matching:** Ignores gameable job titles and self-summaries. It embeds only the candidate's `career_history[].description` (the actual work done).
2. **Multi-Query Intent Set:** Matches candidate career chunks against **4 frozen role-fit intent queries** and takes the **maximum similarity** across them to avoid diluting specialized experience.
3. **Combined Duration & Recency Decay:**Reweights each job description's contribution based on tenure and recency:
   $$\text{weight} = \text{duration\_norm} \times \text{recency\_decay}$$
4. **Top-K Mean Pooling:** Averaging the top $K=2$ highest job cosines to ensure repeated, consistent experience in the role.
5. **Lexical Blend:** Blends semantic similarity ($80\%$) with keyword matching ($20\%$) to capture rare acronyms like "NDCG" or "Pinecone".

### HireIntel.AI (Our Hybrid RAG Scorer)
Designed for high-precision recruiter screening, we separate **evidence retrieval** from **evidence evaluation**:
1. **Evidence Retrieval:** We use `BAAI/bge-base-en-v1.5` to retrieve the top $K=10$ candidate chunks relevant to each Job Description sub-query.
2. **LLM Rubric Judge:** The LLM reads the retrieved text chunks and evaluates them against a strict, four-band rubric (assigning `0.01`, `0.25`, `0.50`, or `1.00`).
3. **Factual Rules in Python:** Factual checks (like numeric years of experience, degree validation, and university/certification tier lookup) are performed deterministically in Python (via [graded_scorer.py](file:///c:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/src/scoring/graded_scorer.py)) to ensure $100\%$ accuracy and reproducibility.

---

## 3. Comparative Summary: Which Approach is Better?

### When Redrob's No-LLM Approach is Superior:
For large-scale **database retrieval (100,000+ candidates)**. You cannot call an LLM 100,000 times at runtime without blowing API budgets and CPU execution limits. Redrob's pre-computed embedding cache paired with NumPy vector matrix operations is the state-of-the-art approach for this scale.

### When HireIntel.AI's Hybrid Approach is Superior:
For focused **applicant screening (50-200 candidates)**. In recruiter workflows, precision and auditability are critical. 
* Cosine pooling (even with Redrob's adjustments) cannot capture nuance (e.g. distinguishing a *lead* developer from a *junior* team member).
* Pure embeddings cluster scores extremely closely, making rank stability weak. 
* HireIntel.AI uses vector similarity simply to find the evidence, but relies on a **rubric-bound LLM Judge** to perform qualitative grading, providing high score differentiation and clear, auditable explanations.
