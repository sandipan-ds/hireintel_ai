# EVALUATION.md

## True Score Evaluation Using Judge LLMs

This evaluation protocol measures the quality of a resume-scoring system by validating its **score outputs** rather than directly validating its full ranking over the entire resume pool.

The main idea is simple: in this pipeline, **ranking is a downstream consequence of scoring**. If the scoring model assigns criterion-level subscores and final total scores that closely match the outputs of stronger judge models on the same resumes, then the resulting ranking is likely to be directionally reliable as well. Instead of asking whether the scorer model can reproduce an exact human ranking over hundreds or thousands of resumes, this protocol asks a more practical question: **does the scorer model score resumes the same way a stronger multimodal judge would score them?**

This approach is intentionally sample-based. It does not require auditing the entire resume pool. It evaluates a randomly selected subset of original PDF resumes and uses score agreement, score variance, and error statistics to estimate the trustworthiness of the scoring model.

## Objective

The objective of this evaluation is to determine whether the **scorer LLM** is applying the resume-scoring rubric correctly and consistently when compared against one or more **advanced multimodal judge LLMs**.

A close agreement between the scorer model and the judge models suggests that:

- the scorer is interpreting the original resume content correctly,
- the scorer is assigning subscores in a rubric-consistent way,
- the scorer is aggregating those subscores correctly into a total score,
- and the downstream ranking induced by those scores is likely to be reliable.

## Judge Model Requirements

The judge models used in this evaluation should be **advanced multimodal LLMs** capable of reading the original PDF resumes directly. Examples must include current frontier-grade systems such as **Claude Opus-4.8**, **Sonnet-5**, **GPT-5.6**, **Gemini 3.5 Pro / 3.1 Pro**, or **GLM-5.2** to ensure superior context reasoning and objective evaluation.

A multimodal judge is required because the evaluation should not depend only on extracted text or parsed JSON. The judge must be able to inspect the original resume PDF and verify the evidence directly from the source document. This reduces the chance that the evaluation incorrectly approves a bad extraction or misses information that was visually present in the resume but lost during parsing.

## Sampling Protocol

For each evaluation batch, select a **random sample of 20 PDF resumes** from the larger candidate pool.

The sample should remain random enough to avoid cherry-picking, but it is also helpful if the batch naturally contains a reasonable spread of candidate quality, such as strong, borderline, and weak resumes. If needed, multiple random batches may be run over time to improve confidence.

This protocol is intentionally lightweight. The goal is not to perform an exhaustive review of every resume, but to create a practical and repeatable audit mechanism.

## Standardized Output Requirement

All participating models must produce the **same structured JSON format** for the same resume and the same scoring rubric.

That JSON output should include, at minimum:

- the extracted candidate information required by the rubric,
- all criterion-level subscores,
- any intermediate scoring fields required by the total score formula,
- the final total score,
- and, if applicable, short justification fields tied to the rubric dimensions.

The evaluation depends on schema consistency. If different models produce different structures, then score comparison becomes noisy and unreliable. Therefore, the output schema must be fixed before evaluation begins.

## Evaluation Procedure

For each sampled PDF resume, the following process is run:

1. The **scorer LLM** reads the resume and produces the standard JSON output, including all subscores and the final total score.
2. Each **judge LLM** independently reads the same original PDF resume and produces the **same JSON output format** using the same rubric and scoring definitions.
3. A **total score calculator** recomputes the final score from the returned subscores for both the scorer output and the judge outputs.
4. The recomputed score is checked against the declared total score to verify arithmetic consistency.
5. The scorer output is then compared with the judge outputs at both the **subscore level** and the **final total score level**.
6. Agreement, error, and variance statistics are computed over the entire sampled batch.

This procedure ensures that the evaluation checks not only the final score, but also whether the internal scoring logic appears to have been followed correctly.

## Reference Score Construction

When multiple judge LLMs are used, a single reference score should be constructed from their outputs for comparison against the scorer model.

A reference score may be defined using one of the following strategies:

- **Mean judge score**, if judge outputs are tightly clustered.
- **Median judge score**, if robustness to outliers is preferred.
- **Consensus-filtered score**, if one judge output is clearly anomalous and should be excluded under a predefined policy.

In most cases, the **median** is a good default because it is less sensitive to one abnormal judge output.

The same reference strategy should also be applied to important criterion-level subscores when subscore agreement is being measured.

## Metrics

The following metrics should be computed for the sampled resumes:

### 1. Schema Agreement

Checks whether the scorer LLM and all judge LLMs produced valid outputs in the required JSON schema.

### 2. Arithmetic Consistency

Checks whether the final total score exactly matches the score obtained by recomputing the total from the returned subscores and scoring formula.

### 3. Per-Criterion Absolute Error

Measures the absolute difference between the scorer subscore and the judge reference subscore for each rubric criterion.

### 4. Total Score Absolute Error

Measures the absolute difference between the scorer total score and the judge reference total score.

### 5. Relative Percentage Error

Measures the scorer model's total score deviation as a percentage of the judge reference score.

### 6. Judge Variance

Measures how much the judge models disagree with one another on the same resume. This is important because high judge disagreement indicates task ambiguity.

### 7. Scorer-vs-Judge Variance

Measures whether the scorer model deviates more from the judge reference than the judges deviate among themselves.

### 8. Bias Direction

Checks whether the scorer model systematically **overscores** or **underscores** resumes relative to the judge reference.

### 9. Aggregate Error Statistics

Across the full 20-resume sample, report summary statistics such as:

- **Mean Absolute Error (MAE)**
- **Root Mean Squared Error (RMSE)**
- **Standard Deviation of Error**
- **Maximum Observed Deviation**

These metrics provide a compact view of how closely the scorer model tracks the judge reference.

---

## Scoring System Health Metrics

The following two metrics are specifically designed to detect **systematic failures in the scorer engine itself** — separate from the LLM-vs-judge comparison above. They should be computed on every batch scoring run, even without judge models, as a first-pass diagnostic before any human review.

### 10. Cross-Candidate Score Variance

**What it measures:** The variance of total scores across all candidates scored in a single batch run for a given role.

**How to compute it:** For a role with N candidates, compute the standard deviation (σ) and variance (σ²) of all `total_score` values. Additionally, compute the variance of each requirement's `sub_score` across all N candidates (per-REQ variance).

**Why it matters:** If the scorer is correctly evaluating candidates against the rubric, total scores should spread meaningfully across the range — strong candidates should score much higher than weak ones. When scores are **artificially clustered** (very low variance, e.g. all candidates scoring within ±5 points of each other), it is a strong signal that the scorer is **not differentiating** candidates on one or more requirement dimensions.

The most common cause is a requirement category (e.g. education, certifications, location) where a systematic code bug or missing extraction causes **all candidates** to receive the same floor score (e.g. 0.01) regardless of their actual qualifications. Since a floor score is uniform across all candidates, it contributes zero discriminative power and collapses that slice of the score range.

**Thresholds (recommended starting values):**

| Condition | Signal |
|-----------|--------|
| σ < 5 points across all candidates | **WARNING** — scores are suspiciously clustered; investigate per-REQ sub-score distributions |
| Per-REQ σ < 0.05 across all candidates | **WARNING** — that specific REQ is not discriminating at all; likely a floor-score bug |
| σ < 2 points across all candidates | **CRITICAL** — scorer is essentially assigning a constant score; major systematic failure |

**Recommended action:** When total score variance is low, compute per-REQ sub-score variance and sort REQs by variance ascending. The lowest-variance REQs are the most likely source of the problem. Inspect their `code_only_sq_scores` or `rubric_sq_scores` for uniform floor values.

---

### 11. Sub-Score Floor Rate (SFR)

**What it measures:** The percentage of all (candidate × REQ) pairs in a batch run where the `sub_score` for a requirement is **strictly less than 0.25** — not equal to, but below.

**How to compute it:**

```
SFR = (number of REQ results where sub_score < 0.25) / (total number of REQ results) × 100
```

For a run with N candidates and R requirements per candidate, total REQ results = N × R.

**Why it matters:** A `sub_score < 0.25` is a strong signal that a requirement was either:
- blocked entirely (zero retrieved evidence, zero-evidence flag raised), or
- scored at the rubric floor across all sub-queries (e.g. 0.01 per SQ), or
- failing a binary gate that should have passed (e.g. degree match returning 0 despite the candidate having a relevant degree).

In all of these cases, the scorer is **failing to find or use evidence that is almost certainly present in the resume**. A small SFR is acceptable — some candidates genuinely lack certain skills. But when SFR is high across all candidates, it indicates a **systematic retrieval failure or a code-level parsing bug**, not a candidate quality issue.

**Thresholds (recommended starting values):**

| SFR | Signal |
|-----|--------|
| < 15% | Acceptable — some candidates genuinely lack certain skills |
| 15% – 30% | **WARNING** — investigate which REQs are driving floor scores; likely retrieval issue |
| > 30% | **CRITICAL** — scorer is failing to find evidence on the majority of requirement checks; systematic bug |

**Recommended action:** When SFR is above threshold, group floor-score results by REQ ID and check:
1. Which REQs have 100% floor rate (every candidate scores < 0.25) — these are almost certainly bugs, not candidate quality issues.
2. Which REQs have floor rates > 50% — these likely have retrieval mismatch (sub-query wording vs resume language) or wrong evaluation type assignment.
3. Cross-reference with the `no_evidence_flags.jsonl` audit file to identify retrieval zero-evidence patterns.

**Relationship to score variance (Metric 10):** SFR and variance are complementary. High SFR drives low variance — if every candidate floors on the same REQs, those REQs contribute nothing to discrimination. Fixing high-SFR REQs will typically also raise score variance to a healthier level.

---

## Retrieval Configuration Health Note

The `top_k` (max chunks per query) parameter should be set relative to the **actual number of chunks stored per candidate** in the vector index, not as an arbitrary large cap.

A typical resume produces **3–8 chunks** when using the recursive chunker at `chunk_size=1000, overlap=500`. Setting `top_k=20` is therefore meaningless — at most 3–8 chunks can ever be returned per candidate per sub-query, regardless of the cap. A high `top_k` wastes retrieval cycles and can pull in lower-quality chunks from other candidates if candidate isolation is not enforced at the retriever level.

**Recommended `top_k` setting:** Set `top_k` to the **95th percentile chunk count per candidate** in the indexed corpus — typically **5–8** for resume-length documents. Do not use a fixed value larger than the expected chunk count.

## Human Review Escalation Policy

A practical escalation rule should be added so that clear mismatches are not silently accepted.

A recommended starting policy is:

- if the scorer model's total score differs from the judge reference by more than **plus or minus 10 percent**, flag the resume for human review;
- if judge models disagree strongly among themselves, flag the resume for human review;
- if the scorer output is schema-invalid or arithmetically inconsistent, flag the resume for human review.

The **plus or minus 10 percent** threshold should be treated as an operational baseline, not a universal constant. It may be tightened or relaxed based on score distributions, rubric sensitivity, and how much a given deviation changes downstream decision boundaries.

## Why This Supports Ranking Confidence

This protocol does not directly prove that the scorer model has produced the exact correct ranking over the entire resume pool. Instead, it validates the underlying **score-generation process** on a representative audited sample.

That is still meaningful because the final ranking is generated from total scores. If the scorer model consistently produces total scores that remain close to those assigned by stronger judge models, then the resulting ranking is likely to be reasonably accurate in aggregate. Lower score error should imply lower ranking distortion, especially when score gaps between candidates are meaningful.

Conversely, if the scorer model frequently diverges from the judge models on total score or important subscores, then the downstream ranking should be treated as unreliable, even if it appears internally stable.

The evaluation claim is therefore deliberately modest and practical: **agreement on score is used as a proxy for confidence in rank**.

## Assumptions and Limitations

This protocol relies on several important assumptions.

First, it assumes that stronger multimodal judge models are a reasonable reference for rubric-following behavior. Second, it assumes that agreement on scores is a useful proxy for agreement on ranking quality. Third, it assumes that a random sample of 20 resumes is sufficient to detect major scoring issues, even though it cannot capture every possible edge case.

Because of these assumptions, this protocol should be understood as an **audit framework**, not as proof of perfect ranking correctness. Its purpose is to provide a scalable, practical, and defensible way to evaluate whether the scorer LLM is behaving consistently with stronger evaluators on real resume documents.

## Summary

This evaluation replaces full-pool ranking validation with a **sample-based score validation protocol**.

A scorer LLM is evaluated against stronger multimodal judge LLMs on a random batch of original PDF resumes. All models must produce the same JSON schema with criterion-level subscores and a final total score. A separate calculator recomputes totals, and the scorer output is compared against judge references using agreement, variance, and error metrics. Cases with material deviation or strong disagreement are escalated to humans.

This makes the evaluation practical, auditable, and closely aligned with how scoring-driven resume ranking systems actually operate.

---

## Empirical Baseline Evaluation: Raw Cosine vs. LLM Rubric Scorer

### 1. Objectives & Setup
To establish a performance baseline for the platform's ranking quality, a **Raw Vector Similarity Baseline** was implemented. This baseline computes candidate scores without any LLM judgment:
1. It extracts all requirements and sub-queries from the Job Description.
2. It embeds each sub-query using `BAAI/bge-base-en-v1.5` (768-dim).
3. For each candidate, it calculates the raw cosine similarity of the sub-query vector against all of the candidate's resume chunks.
4. The raw score for each sub-query is the **maximum cosine similarity** found across the candidate's chunks (bounded to `[0.0, 1.0]`).
5. Sub-query scores are averaged to get the requirement score, weighted according to the recruiter's weight configuration, and aggregated into a final score out of 100.

This baseline was run across all 8 pre-scored roles (covering 721 candidate resumes) and compared directly against the production **LLM Rubric-based Scorer** using rank correlation metrics.

### 2. Empirical Alignment Metrics

The evaluation yielded the following alignment results:

| Role | Candidate Count | Spearman's Rho | Kendall's Tau | Jaccard Overlap @ Top-10 | Top-10 Score clustering span | Verdict |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **BusinessAnalyst** | 132 | 0.3667 | 0.2521 | 0.1111 | 1.26% | 🟢 DISCREPANT |
| **DataScience** | 40 | -0.1340 | -0.0949 | 0.1111 | 0.78% | 🟢 DISCREPANT |
| **JavaDeveloper** | 69 | 0.0846 | 0.0554 | 0.0526 | 0.72% | 🟢 DISCREPANT |
| **ReactDeveloper** | 18 | -0.0753 | -0.0850 | 0.4286 | 1.70% | 🟢 DISCREPANT |
| **SQLDeveloper** | 81 | 0.0017 | -0.0012 | 0.1111 | 1.86% | 🟢 DISCREPANT |
| **SalesManager** | 162 | 0.1674 | 0.1037 | 0.1111 | 1.35% | 🟢 DISCREPANT |
| **SrPythonDeveloper** | 96 | 0.4902 | 0.3461 | 0.1765 | 0.75% | 🟡 WEAK CORRELATION |
| **WebDesigning** | 107 | 0.2833 | 0.1956 | 0.0000 | 0.74% | 🟢 DISCREPANT |

### 3. Shortcomings of Pure Cosine Matching

The experimental data reveals severe limitations in pure cosine similarity matching:

#### A. Score Clustering & Lack of Discrimination
In a pure cosine baseline, the top 10 candidates' scores are compressed within a tiny band of **0.70% to 1.86%** (averaging **<1.5%** variance). Because raw vectors represent overall semantic context rather than specific capabilities, they fail to assign distinct values. A recruiter looking at the dashboard sees identical-looking scores and has no signal for making a clear decision. The LLM Rubric Scorer successfully spreads candidate scores out by evaluating evidence against granular rubrics, yielding clear candidate differentiation (**~10%** score span).

#### B. Topical Similarity vs. Proficient Assertions (Negation/Aspiration)
Embeddings map vocabulary, not qualifications:
* A resume mentioning *"I do not know SQL"* and one stating *"Designed optimized SQL schemas"* are both topically highly aligned to the query *"Knows SQL"* and return near-identical cosine scores.
* Aspirations (*"Interested in learning Python"*) are scored identically to years of hands-on work (*"5 years Python development"*).
The LLM Rubric Scorer evaluates candidate assertions contextually, filtering out tutorials, class projects, passive exposure, and direct negations.

#### C. Inability to Apply Factual & Structural Rules
Pure vector models cannot:
* Perform date subtraction to verify years of experience targets.
* Check degrees and universities against database lookup lists or apply institution tier multipliers.
* Enforce binary gating checks (e.g. mandatory certifications).

### Conclusion
A pure vector cosine baseline is equivalent to soft keyword matching. The **LLM Rubric-bound Scorer** is a critical architectural requirement for delivering accurate, qualitative, and human-aligned talent ranking.

---

## Reference-Free RAG Retrieval Evaluation (LLM-as-a-Judge)

When ground-truth chunk mappings are not available, retrieval and scoring quality must be evaluated dynamically using a superior reasoning engine (e.g. **Claude Opus-4.8**, **Sonnet-5**, or **GPT-5.6**) as an auditor.

The evaluation computes three core reference-free RAG metrics:

### 12. Context Relevance (Precision)
*   **Definition:** Measures the ratio of useful evidence chunks retrieved to the total number of chunks provided to the scorer LLM.
*   **Protocol:** The Judge LLM reviews the **Sub-Query** and the **Text of each retrieved chunk** individually.
*   **Judge Prompt:** 
    > *"Analyze the sub-query: {sub_query}. Now read the retrieved text chunk: {chunk_text}. Does this chunk contain concrete evidence that directly helps in answering the sub-query? Answer strictly YES or NO."*
*   **Metric Calculation:** `Context Precision = (Number of chunks rated YES) / (Total retrieved chunks)`. An acceptable target is `>= 0.75`. Low precision indicates the retrieval query pulls in excessive semantic noise.

### 13. Faithfulness (Groundedness)
*   **Definition:** Checks if the scorer LLM's requirement explanation is strictly grounded in the retrieved chunks, preventing hallucinated qualifications or years.
*   **Protocol:** The Judge LLM compares the **Scorer's explanation** against the raw text of **all retrieved chunks**.
*   **Judge Prompt:**
    > *"Compare the scoring explanation: {explanation} against the raw source evidence text: {retrieved_text}. Is every claim, qualification statement, or number of years mentioned in the explanation directly supported by the source evidence? List any claims that are not grounded."*
*   **Metric Calculation:** `Faithfulness = (Number of grounded statements) / (Total statements in explanation)`. Target threshold is strictly `1.0` (zero tolerance for ungrounded claims).

### 14. Answer Relevance
*   **Definition:** Measures if the scorer LLM's output directly addresses the target sub-query without evasive or off-topic responses.
*   **Protocol:** The Judge LLM compares the **Sub-Query** against the **Scorer's final explanation**.
*   **Judge Prompt:**
    > *"Evaluate if the explanation: {explanation} directly and completely answers the question raised in the sub-query: {sub_query}. Rate the answer relevance from 0.0 (completely off-topic/evasive) to 1.0 (directly answers)."*
*   **Metric Calculation:** Average relevance score across all requirement evaluations. Target threshold is `>= 0.90`.