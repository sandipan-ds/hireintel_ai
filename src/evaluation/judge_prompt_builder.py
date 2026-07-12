"""Multimodal prompt builder for True Score Evaluation.

Constructs prompts that send the full rubric, weight config, and formatting
instructions to Gemini 2.5 and Minimax-M3 judge models.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def build_judge_prompt_for_role(
    role: str,
    candidate_id: str,
    requirements: List[Dict[str, Any]],
) -> str:
    """Build the multimodal judge evaluation prompt.

    Args:
        role: The role name (e.g. BusinessAnalyst).
        candidate_id: The candidate ID (e.g. BusinessAnalyst_CAND_0001).
        requirements: List of parsed requirement dicts including weight configs and sub-queries.

    Returns:
        Prompt string.
    """
    req_descriptions = []
    skeleton_reqs = []

    for req in requirements:
        req_id = req["req_id"]
        name = req["name"]
        category = req["category"]
        weight_pct = req.get("weight_percentage", 0.0)
        expected_years = req.get("expected_years", None)
        desc = req.get("description", "")

        sq_lines = []
        sq_skeleton_scores = {}
        for sq in req.get("sub_queries", []):
            sq_key = sq["key"]
            sq_text = sq["text"]
            sq_scale = sq.get("scale", "")
            sq_assessment = sq.get("assessment_method", "")
            sq_lines.append(
                f"  - Key: {sq_key}\n"
                f"    Question: {sq_text}\n"
                f"    Scale/Rubric: {sq_scale}\n"
                f"    Assessment Method: {sq_assessment}"
            )
            # Add placeholders
            sq_skeleton_scores[sq_key] = "FILL_FLOAT_OR_BINARY"

        sq_text_block = "\n".join(sq_lines)
        expected_years_str = f"Expected Years: {expected_years}" if expected_years else ""

        req_descriptions.append(
            f"### Requirement {req_id}: {name}\n"
            f"Category: {category}\n"
            f"{expected_years_str}\n"
            f"Description: {desc}\n"
            f"Sub-Queries:\n"
            f"{sq_text_block}\n"
        )

        skeleton_reqs.append({
            "requirement_id": req_id,
            "requirement_name": name,
            "weight_percentage": weight_pct,
            "rubric_sq_scores": sq_skeleton_scores,
            "sub_score": "FILL_SUM_OF_SUB_SCORES",
            "contribution": "FILL_WEIGHT * (sub_score / n_queries)",
            "justification": "FILL_SHORT_EXPLANATION_WITH_CITED_TEXT_FROM_RESUME",
        })

    requirements_rubric_str = "\n---\n".join(req_descriptions)
    skeleton_json = {
        "candidate_id": candidate_id,
        "role": role,
        "total": "FILL_SUM_OF_ALL_CONTRIBUTIONS",
        "reqs": skeleton_reqs
    }

    # Semantic rules block to align the judge with our semantic expectations
    semantic_rules = """
SEMANTIC INFERENCE RULES — apply when deciding score values:
- "dashboard", "report", "chart", "plot", "visualization", "BI", "Tableau", "Power BI",
  "matplotlib", "seaborn", "Looker", "Grafana" → counts as Data Visualization
- "clean", "cleaning", "preprocess", "transform", "wrangle", "ETL", "pipeline",
  "feature engineering", "imputation" → counts as Data Wrangling / Data Pipelines
- "deploy", "deployment", "serve", "API", "endpoint", "container", "Docker",
  "Kubernetes", "MLflow", "monitoring", "production" → counts as Model Deployment / MLOps
- "Bachelor" / "B.Sc" / "B.Tech" / "B.E." / "B.S." / "undergraduate" in CS, Statistics,
  Mathematics, Engineering, or related field → counts as Bachelor Degree Match
- "Master" / "M.Sc" / "M.Tech" / "M.S." / "MSc" / "M.A." in Data Science, ML,
  Statistics, Mathematics, CS, Engineering → counts as Advanced Degree Match
- "SQL", "database", "MySQL", "PostgreSQL", "BigQuery", "Redshift", "Snowflake",
  "relational", "query", "schema" → counts as SQL / Relational Databases
- "Spark", "Hadoop", "Databricks", "Hive", "Kafka", "distributed", "large-scale"
  → counts as Big Data Ecosystems
- "classification", "regression", "clustering", "forecasting", "prediction",
  "model", "algorithm", "neural network", "XGBoost", "random forest"
  → counts as Design & Develop ML Models
- "NLP", "text", "language model", "sentiment", "entity", "time series",
  "forecasting", "ARIMA", "LSTM" → counts as NLP or Time-Series
- "AWS", "Azure", "GCP", "cloud", "S3", "EC2", "SageMaker"
  → counts as Cloud Platforms
- "accuracy", "precision", "recall", "F1", "AUC", "cross-validation", "A/B test",
  "validation", "evaluation", "error rate", "benchmark" → counts as Model Evaluation
- "EDA", "exploratory", "analysis", "feature", "correlation", "distribution"
  → counts as Exploratory Data Analysis
- "stakeholder", "team", "collaborate", "cross-functional", "present", "communicate"
  → counts as Collaboration
- "insight", "finding", "report", "recommendation", "data-driven"
  → counts as Communicate Findings
"""

    prompt = f"""You are a strict, senior recruiter LLM serving as an expert judge.
Your task is to score the attached resume PDF images against the following job requirements.

Role: {role}
Candidate ID: {candidate_id}

{semantic_rules}

### SCORING INSTRUCTIONS:
1. Examine the attached resume PDF pages directly.
2. For each job requirement listed below, answer and score each sub-query:
   - For Binary type sub-queries: Score must be exactly 0 or 1.
   - For Float or Four-band qualitative/quantitative type sub-queries: Score must be exactly 0.01, 0.25, 0.50, or 1.00 based on the rubric.
   - Do not invent score values outside of [0, 1] for binary, or outside of [0.01, 0.25, 0.50, 1.00] for rubrics.
3. Compute the `sub_score` for each requirement as the sum of its sub-query scores.
4. Compute the `contribution` for each requirement as: weight_percentage * (sub_score / n_queries).
   (For example: if weight is 8.5, sub_score sum is 1.5, and N=3 queries, contribution is 8.5 * (1.5 / 3) = 4.25).
5. Compute the final `total` score as the sum of all contributions.
6. Provide a short justification citing specific text/experience from the resume.

### REQUIREMENTS RUBRIC:
---
{requirements_rubric_str}
---

### OUTPUT FORMAT:
You must output ONLY a valid JSON object matching the following skeleton.
Do not add markdown formatting other than JSON. Do not include commentary outside the JSON block.

```json
{json.dumps(skeleton_json, indent=2)}
```
"""
    return prompt
