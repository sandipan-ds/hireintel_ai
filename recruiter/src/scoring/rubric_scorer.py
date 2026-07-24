"""Rubric-bound LLM evidence scorer — the Mode 2 scoring engine.

Per ``WORKING_LOGIC.md`` ("Rubric-bound LLM evidence scoring"):

Used wherever genuine judgment is required: skill depth, project complexity,
domain expertise. The LLM reads the full content of the section(s) that the
requirement maps to (see Section-Routed Evidence Retrieval) and maps it onto a
recruiter-defined point scale (years used, project complexity, frameworks/tools,
ownership level) — never onto a free-form label.

Key constraints:
* The LLM must NOT see the requirement's weight while scoring evidence.
* The LLM must NEVER compute the final weighted contribution.
* The LLM scores strictly against a recruiter-defined rubric — never against
  its own internal notion of "Advanced" or "Strong."
* Weight application and final score aggregation are always computed in code.

This module implements the RUBRIC-SCORE-001 prompt (see ``PROMPT_LIBRARY.md``)
and produces a ``CachedScoringTrace`` that the score-explanation flow
(SCORE-EXPLAIN-001) can narrate later without re-scoring.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.rag.section_routed import SectionEvidence
from src.scoring.rubrics import RubricTemplate, SubQuestion, BINARY_ANCHORS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cached scoring trace — frozen at scoring time for later explanation.
# ---------------------------------------------------------------------------

@dataclass
class SubScoreResult:
    """The result of one sub-question scored by the LLM (or code).

    Attributes:
        key: The sub-question key (e.g., "skill_presence", "years_experience").
        question: The question that was asked.
        sub_score: The numeric score (0.0–1.0).
        evidence_found: Whether the LLM explicitly confirmed it found matching
            evidence (``True``) or merely cited the closest available text
            without a direct match (``False``). Populated from the LLM's
            ``evidence_found`` field ("yes" / "no"). Defaults to ``False``
            for code-only sub-questions.
        closest_evidence: The most relevant resume text the LLM located,
            regardless of whether it directly proves the requirement. When
            ``evidence_found`` is ``False`` this text is the *closest* the
            retriever found, not a confirmed match — reported as
            "No direct evidence (closest: ...)" in explanations.
        cited_text: The exact short resume quote cited as evidence.
        anchor_description: For anchored sub-questions, the description of the
            chosen anchor. Empty for binary and linear types.
        extracted_years: For linear sub-questions, the years extracted by the LLM.
        target_years: For linear sub-questions, the target/ideal years from config.
    """

    key: str
    question: str
    sub_score: float
    evidence_found: bool = False
    closest_evidence: str = ""
    cited_text: str = ""
    anchor_description: str = ""
    extracted_years: Optional[float] = None
    target_years: Optional[float] = None

    # Back-compat alias: callers that read ``extracted_evidence`` still work.
    @property
    def extracted_evidence(self) -> str:
        """Alias for ``closest_evidence`` (backward compatibility)."""
        return self.closest_evidence

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "question": self.question,
            "sub_score": self.sub_score,
            "evidence_found": self.evidence_found,
            "closest_evidence": self.closest_evidence,
            "cited_text": self.cited_text,
            "anchor_description": self.anchor_description,
            "extracted_years": self.extracted_years,
            "target_years": self.target_years,
        }


@dataclass
class CachedScoringTrace:
    """The full scoring trace for one requirement — frozen at scoring time.

    This is what the score-explanation flow (SCORE-EXPLAIN-001) reads to
    narrate "why did this candidate get this score?" without re-scoring.

    Attributes:
        requirement_name: The original requirement from the JD/weight config.
        dimension_type: The dimension type (e.g., "skill", "education").
        weight: The recruiter-assigned weight (0–10). NOTE: this is stored
            here for explanation purposes only — the LLM never saw it during
            scoring.
        sub_scores: The ordered list of sub-score results.
        normalized_score: The combined sub-score (0.0–1.0), computed in code
            from the formula.
        weighted_score: weight × normalized_score, computed in code.
        formula: The formula string used to combine sub-scores.
        sections_read: Which canonical sections were fetched.
        chunk_ids: IDs of the chunks that provided the evidence.
    """

    requirement_name: str
    dimension_type: str
    weight: float
    sub_scores: List[SubScoreResult]
    normalized_score: float
    weighted_score: float
    formula: str
    sections_read: List[str]
    chunk_ids: List[str]

    @property
    def justification(self) -> str:
        """Auto-generate a human-readable justification from sub-score evidence.

        The RAG evaluation layer reads this field to judge faithfulness
        and answer relevance. Without a proper justification, the Judge
        LLM receives an empty string and returns NO/0.0 by default.

        Returns:
            A multi-sentence summary describing what evidence was found
            (or not found) for each sub-question, including cited text
            and anchor descriptions.
        """
        parts: List[str] = []
        for ss in self.sub_scores:
            frag = f"For '{ss.question}': "
            if ss.evidence_found and ss.closest_evidence:
                frag += f"evidence found — {ss.closest_evidence}."
            elif ss.closest_evidence:
                frag += f"no direct evidence (closest: {ss.closest_evidence})."
            else:
                frag += "no evidence found."
            if ss.cited_text:
                frag += f" Cited: \"{ss.cited_text}\"."
            if ss.anchor_description and ss.anchor_description.lower() != "none":
                frag += f" Level: {ss.anchor_description}."
            if ss.extracted_years is not None:
                target_str = f"{ss.target_years}" if ss.target_years else "unspecified"
                frag += f" Years detected: {ss.extracted_years} (target: {target_str})."
            frag += f" Score: {ss.sub_score:.2f}."
            parts.append(frag)
        return " ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requirement_name": self.requirement_name,
            "dimension_type": self.dimension_type,
            "weight": self.weight,
            "sub_scores": [s.to_dict() for s in self.sub_scores],
            "normalized_score": self.normalized_score,
            "weighted_score": self.weighted_score,
            "formula": self.formula,
            "sections_read": self.sections_read,
            "chunk_ids": self.chunk_ids,
            "justification": self.justification,
        }


# ---------------------------------------------------------------------------
# Prompt construction — RUBRIC-SCORE-001.
# ---------------------------------------------------------------------------

def _format_employment_history(employment_history: Optional[List[Any]]) -> Optional[str]:
    """Format the parser-computed employment history as a human-readable block.

    The :class:`StructuredCandidateProfile.employment_history` list is
    produced deterministically by ``src.resume_parsing.structured_profile``
    from the resume's parsed date ranges. Each entry carries
    ``company``, ``role``, ``dates``, ``calculated_duration_months``,
    and ``inferred_full_year``. This helper renders that list as a
    newline-bulleted block the LLM can read alongside the retrieved
    chunks.

    Why pass this to the LLM:
      The Recursive chunker may split a resume role's date line away
      from its bullet points across two different chunks. Without the
      precomputed date math, the LLM often sees a chunk that mentions
      the skill but contains no dates, and incorrectly returns
      ``extracted_years=0`` even when the parser already computed the
      role's duration. By passing the parser-computed
      ``employment_history`` here, the LLM can correlate a skill mention
      in a chunk with a duration from the structured profile — without
      having to re-parse date strings itself.

    Args:
        employment_history: A list of :class:`EmploymentEntry` (or
            duck-typed dicts with the same shape) — typically
            ``StructuredCandidateProfile.employment_history``. Pass
            ``None`` or an empty list to omit the block entirely.

    Returns:
        Formatted string starting with a header line, or ``None`` when
        the input is empty/unusable.
    """
    if not employment_history:
        return None
    # Header row makes the column layout explicit so the LLM can correctly
    # correlate job titles with skill bullets regardless of parse quirks.
    lines = [
        "EMPLOYMENT HISTORY (computed deterministically from date ranges — use this pre-computed employment history"
        " to answer `years_experience` sub-questions; correlate them with"
        " the skill/bullets in the SECTION CONTENT):",
        "  Columns: Role | Company | Dates | Duration",
    ]
    for e in employment_history:
        try:
            # Support both EmploymentEntry dataclass and plain dict.
            company = getattr(e, "company", None) or (e.get("company") if isinstance(e, dict) else "") or ""
            role = getattr(e, "role", None) or (e.get("role") if isinstance(e, dict) else "") or ""
            dates = getattr(e, "dates", None) or (e.get("dates") if isinstance(e, dict) else "") or ""
            months = getattr(e, "calculated_duration_months", None)
            if months is None and isinstance(e, dict):
                months = e.get("calculated_duration_months")
            inferred = getattr(e, "inferred_full_year", False)
            if inferred is False and isinstance(e, dict):
                inferred = e.get("inferred_full_year", False)
            years = round((months or 0) / 12.0, 1) if months else 0
            inferred_marker = " (inferred full year)" if inferred else ""
            # Emit Role | Company order (more natural for LLM correlation with
            # skill bullets that typically reference the job title first).
            lines.append(
                f"- {role} | {company} | {dates} | {months} months (~{years} yrs){inferred_marker}"
            )
        except Exception:
            # Defensive: a malformed entry should not break the prompt.
            continue
    if len(lines) <= 2:  # only header rows, no real entries
        return None
    return "\n".join(lines)


def _build_rubric_prompt(
    requirement_name: str,
    rubric: RubricTemplate,
    evidence: SectionEvidence,
    target_years: Optional[float] = None,
    employment_history: Optional[List[Any]] = None,
) -> str:
    """Build the prompt for the LLM judge.

    Key constraints enforced by the prompt:
    * The weight is NOT included — the LLM never sees it.
    * The LLM must extract evidence BEFORE scoring.
    * The LLM must return structured JSON.

    Args:
        requirement_name: The requirement from the JD (e.g., "Python").
        rubric: The rubric template for this dimension type.
        evidence: The section-routed evidence (full text).
        target_years: The recruiter-defined target years.
        employment_history: Optional list of employment entries.

    Returns:
        The prompt string to send to the LLM.
    """
    # Format sub-questions with the requirement name.
    sub_q_lines: List[str] = []
    for i, sq in enumerate(rubric.sub_questions, 1):
        question_text = sq.question.replace("{skill}", requirement_name)
        sub_q_lines.append(f"  Sub-question {i} (key: {sq.key}):")
        sub_q_lines.append(f"    Q: {question_text}")
        sub_q_lines.append(f"    Type: {sq.type}")

        if sq.type == "binary":
            sub_q_lines.append(f"    Answer: 0 (No) or 1 (Yes)")
        elif sq.type == "four_band":
            sub_q_lines.append(
                "    Check if the resume content mentions explicit duration, dates, or years of experience for this skill.\n"
                "    - If YES: extract the number of years in `extracted_years` (as a plain number, e.g. 3, 2.5) and set `level` to \"\".\n"
                "    - If NO: leave `extracted_years` as null and set `level` to one of: \"substantial\" | \"some\" | \"few\" | \"none\"."
            )

        if sq.extract_first:
            sub_q_lines.append(
                f"    Step 1 — copy the relevant text from SECTION CONTENT into "
                f"\"extracted_evidence\" and \"cited_text\" before you score."
            )
        sub_q_lines.append("")

    sub_questions_text = "\n".join(sub_q_lines)

    employment_block = _format_employment_history(employment_history)
    employment_section = ""
    if employment_block:
        employment_section = f"""
{employment_block}
---

"""
    skeleton_entries: List[str] = []
    for sq in rubric.sub_questions:
        if sq.type == "binary":
            entry = (
                f'    {{\n'
                f'      "key": "{sq.key}",\n'
                f'      "evidence_found": "no",\n'
                f'      "closest_evidence": "none",\n'
                f'      "cited_text": "none",\n'
                f'      "sub_score": 0,\n'
                f'      "extracted_years": null,\n'
                f'      "level": ""\n'
                f'    }}'
            )
        else:  # four_band
            entry = (
                f'    {{\n'
                f'      "key": "{sq.key}",\n'
                f'      "evidence_found": "no",\n'
                f'      "closest_evidence": "none",\n'
                f'      "cited_text": "none",\n'
                f'      "sub_score": 0,\n'
                f'      "extracted_years": null,\n'
                f'      "level": "none"\n'
                f'    }}'
            )
        skeleton_entries.append(entry)

    skeleton_json = ",\n".join(skeleton_entries)

    semantic_rules = """
SEMANTIC INFERENCE RULES — apply BEFORE deciding evidence_found:
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

    prompt = f"""You are a resume evidence scorer. Score the candidate for ONE requirement.

REQUIREMENT: {requirement_name}
{semantic_rules}
HEXAGON sub-questions to answer:
{sub_questions_text}
RESUME CONTENT:
---
{evidence.full_text}
---
{employment_section}
TASK: Output a JSON response following the template below. Replace the default values with your assessment.
- For binary keys: sub_score must be 0 or 1.
- For four_band keys: extracted_years must be a plain number like 3 or 2.5, NOT a string. Use JSON null if no evidence.
- For level: use the qualitative level "substantial" | "some" | "few" | "none" if no explicit years are present.
- For evidence_found: use the string "yes" if the resume directly proves the requirement (use SEMANTIC INFERENCE RULES above), else use "no".
- For closest_evidence: always paste the most relevant text you found, even if it is indirect.
- Do NOT add extra keys. Do NOT change the "key" values. Output ONLY the JSON, starting with {{ and ending with }}.

{{
  "sub_scores": [
{skeleton_json}
  ]
}}"""

    return prompt


# ---------------------------------------------------------------------------
# Response parsing — extract structured sub-scores from LLM output.
# ---------------------------------------------------------------------------

def _extract_json_lenient(text: str) -> Optional[Dict[str, Any]]:
    """Extract the first JSON object from ``text``, tolerating truncation.

    Free-tier LLM endpoints sometimes cap ``completion_tokens`` mid-response,
    cutting the JSON payload mid-key or mid-value. A strict
    ``json.loads`` on the substring fails in those cases and the rubric
    scorer falls back to zero scores, silently defeating the LLM call.

    This helper:
      1. Strips markdown code fences if present.
      2. Locates the first ``{`` and scans forward, tracking nesting
         depth.
      3. At every depth-back-to-zero position (i.e. a syntactically
         complete object), tries ``json.loads``. The longest valid
         prefix wins.
      4. If no complete object is found (truncated), attempts a
         structural recovery: clip at the last complete sub_score
         object (``}`` followed by ``,`` or ``]``), then synthetically
         close with ``]}``.
      5. Returns the parsed dict, or ``None`` if nothing parses.

    Args:
        text: The raw LLM response text.

    Returns:
        Parsed dict (top-level keys ``sub_scores`` etc.) or ``None``.
    """
    if not text:
        return None
    # Strip <think>...</think> and <thought>...</thought> reasoning blocks if present.
    text = re.sub(r"<(think|thought)>.*?</(think|thought)>", "", text, flags=re.DOTALL).strip()
    # Strip ```json ... ``` style fences.
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    best_end = -1
    best_data: Optional[Dict[str, Any]] = None
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start:i + 1]
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict):
                        # Prefer the longest valid parse.
                        best_end = i
                        best_data = parsed
                except json.JSONDecodeError:
                    pass
    if best_data is not None:
        return best_data
    # Truncated JSON recovery: clip at the last complete sub_score object.
    # Look for the last `}` preceded by a complete object boundary.
    body = text[start:]
    # Find the index of the last `}` that is followed by either `,` or `]`
    # (i.e. a sub-score boundary, not a value-close).
    last_obj_end = -1
    for m in re.finditer(r"\}\s*(?:,|\])", body):
        last_obj_end = m.start() + 1
    if last_obj_end > 0:
        candidate = body[:last_obj_end] + "]}"
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                logger.info(
                    "Recovered truncated JSON (%d chars kept out of %d) "
                    "with %d sub-scores",
                    last_obj_end, len(body),
                    len(parsed.get("sub_scores", [])),
                )
                return parsed
        except json.JSONDecodeError:
            pass
    return None


def _banded_years_ratio(extracted_years: float, target_years: float) -> float:
    """Compute a banded years-ratio sub-score per owner spec (2026-07-07).

    Replaces the continuous ``min(years / target, 1.0)`` with a discrete
    4-band rule that is easier to audit and explain to a recruiter:

        years >= target           → 1.00   (meets-or-exceeds)
        years >= 50% of target    → 0.50   (substantial partial credit)
        years >= 25% of target    → 0.25   (marginal partial credit)
        years <  25% of target    → 0.00   (insufficient)

    Why banded (vs continuous):
      * Continuous ratios (e.g. 0.667 for 4/6) are difficult to defend in a
        recruiter UI — "why did this candidate get a 0.67 instead of the
        other candidate's 0.71?" Bands map directly to explainable labels
        ("meets expectation", "substantial partial", "marginal").
      * Reduces LLM-extraction noise: a 4.2-vs-4.0 extraction becomes the
        same band (both 1.0 at expected=3), instead of two different
        continuous numbers.
      * Still preserves ordering: candidates with more years never score
        lower than candidates with fewer years at the same target.

    The band thresholds (50%, 25%) are owner-specified and align with the
    four anchor values used on the :data:`RELEVANCE_ANCHORS` scale
    (1.0, 0.75, 0.5, 0.25) — though this rubric uses 1.0/0.5/0.25/0.0 to
    keep "no evidence" firmly at zero rather than crediting 0.25 for
    a single passing mention.

    Args:
        extracted_years: Years value extracted by the LLM (from the
            employment_history context block, or from a chunk if no
            structured profile is supplied). May be 0 or negative when
            the LLM finds no evidence — caller should still apply the
            0.0 band.
        target_years: The recruiter-specified expected/required years.
            Must be > 0 (caller enforces this — the linear branch
            only invokes this helper when ``target_years > 0``).

    Returns:
        One of ``1.0``, ``0.5``, ``0.25``, ``0.0``.
    """
    if extracted_years <= 0 or target_years <= 0:
        return 0.0
    if extracted_years >= target_years:
        return 1.0
    if extracted_years >= 0.5 * target_years:
        return 0.5
    if extracted_years >= 0.25 * target_years:
        return 0.25
    return 0.0


def _coerce_years(raw_val: Any) -> Optional[float]:
    """Robustly coerce the LLM's ``extracted_years`` value to a float.

    Small models (qwen2.5:3b) frequently return the years field as a
    string rather than a JSON number, e.g. ``"3 years"``,
    ``"approximately 4"``, ``"~2.5"``, ``"3+"``.  A plain
    ``float()`` call on any of these raises ``ValueError`` and the
    caller silently falls back to ``None``, forcing a 0 score even
    when the candidate clearly has the skill.

    Strategy:
      1. If ``raw_val`` is already numeric (int/float), return it.
      2. If it is a string, strip whitespace, remove leading ``~``,
         ``>`` ``<`` ``+`` characters and trailing unit words
         (``years``, ``yrs``, ``year``, ``y``), then try
         ``float()`` on the remainder.
      3. Fall back to ``None`` only when no digit sequence can be
         parsed at all.

    Args:
        raw_val: The value of the ``extracted_years`` field from the
            LLM JSON response. May be ``int``, ``float``, ``str``,
            or ``None``.

    Returns:
        A non-negative float, or ``None`` when the value is
        genuinely absent or uninterpretable.
    """
    if raw_val is None:
        return None
    if isinstance(raw_val, (int, float)):
        return float(raw_val)
    if not isinstance(raw_val, str):
        return None

    # Strip whitespace, then remove common prefix/suffix noise.
    cleaned = raw_val.strip()
    # Remove leading approximate markers and comparison operators.
    cleaned = re.sub(r"^[~<>≈≥≤+\-]+", "", cleaned).strip()
    # Remove trailing unit words ("years", "yrs", "year", "y").
    cleaned = re.sub(r"\s*(years?|yrs?|y)\s*$", "", cleaned,
                     flags=re.IGNORECASE).strip()
    # Remove any remaining trailing non-numeric noise.
    cleaned = re.sub(r"[^0-9.]+$", "", cleaned).strip()
    if not cleaned:
        return None

    # Try a direct float conversion on the cleaned string.
    try:
        val = float(cleaned)
        return val if val >= 0 else None
    except ValueError:
        pass

    # Last resort: grab the first number-like substring.
    m = re.search(r"(\d+(?:\.\d+)?)", raw_val)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass

    return None


def classify_subquery_type(sq: Dict[str, Any]) -> str:
    """Classify the sub-query type based on text and key.

    Args:
        sq: Sub-query dict.

    Returns:
        One of "binary", "cgpa", "institution_rank", "certificate_rank", "four_band".
    """
    text = (sq.get("text") or "").lower()
    key = (sq.get("key") or "").lower()
    sq_type = (sq.get("type") or "").lower()

    if sq_type in ("binary", "boolean", "bool"):
        return "binary"

    if "cgpa" in text or "percentage" in text or "marks" in text or "grade" in text:
        return "cgpa"

    if "tier of the institute" in text or "institute_tier" in key or "university tier" in text:
        return "institution_rank"

    if "tier of the certificate" in text or "provider_tier" in key or "certification tier" in text:
        return "certificate_rank"

    # BUG-7 FIX: Broader patterns to catch real SubQuery.md text like
    # "institute tier (Tier 1, Tier 2, Tier 3)" or "certification prestige level".
    _TIER_WORDS = ("tier", "prestige", "ranking", "ranked")
    _INST_WORDS = ("institute", "institution", "university", "college", "school")
    _CERT_WORDS = ("certif", "provider", "certification", "credential")

    has_tier_word = any(w in text or w in key for w in _TIER_WORDS)
    has_inst_word = any(w in text or w in key for w in _INST_WORDS)
    has_cert_word = any(w in text or w in key for w in _CERT_WORDS)

    if "institute_tier" in key or "institution_rank" in key:
        return "institution_rank"
    if "provider_tier" in key or "certificate_rank" in key or "cert_tier" in key:
        return "certificate_rank"

    if has_tier_word and has_cert_word and has_inst_word:
        return "certificate_rank"

    if has_tier_word and has_inst_word:
        return "institution_rank"

    if has_tier_word and has_cert_word:
        return "certificate_rank"

    return "four_band"




def _parse_fallback_regex(text: str, rubric_keys: List[str]) -> List[Dict[str, Any]]:
    """Regex-based fallback parser to extract sub-scores from unstructured LLM output."""
    results = []
    if not text:
        return results
    for key in rubric_keys:
        key_pattern = re.escape(key)
        # Search for a block of text starting with the key up to the next key or end of text
        match_block = re.search(rf"{key_pattern}\b(.*?(?=(?:SQ\d+|[A-Za-z0-9_]+_presence|[A-Za-z0-9_]+_depth)\b|$))", text, re.DOTALL | re.IGNORECASE)
        if not match_block:
            continue
            
        block_content = match_block.group(1).strip()
        block_content_lower = block_content.lower()
        
        # 1. Parse sub_score
        sub_score = 0.0
        score_match = re.search(r"(?:score|sub_score|value|rating)\s*[:=-]?\s*(\d+(?:\.\d+)?)", block_content_lower)
        if score_match:
            try:
                sub_score = float(score_match.group(1))
            except ValueError:
                pass
        else:
            # Fallback: look for "1" or "0" or "yes"/"no" close to key name
            simple_val_match = re.match(r"^\s*[:=-]?\s*(yes|no|1|0|true|false)\b", block_content_lower)
            if simple_val_match:
                val_str = simple_val_match.group(1)
                if val_str in ("yes", "1", "true"):
                    sub_score = 1.0
                else:
                    sub_score = 0.0
        
        # 2. Parse evidence_found
        evidence_found = "no"
        if "evidence_found" in block_content_lower:
            ev_match = re.search(r"evidence_found\s*[:=-]?\s*\"?(yes|no|true|false)\"?", block_content_lower)
            if ev_match:
                val = ev_match.group(1)
                evidence_found = "yes" if val in ("yes", "true") else "no"
        else:
            if sub_score >= 0.5 or any(w in block_content_lower for w in ("yes", "found", "exhibit", "present", "proven")):
                evidence_found = "yes"
                
        # 3. Parse level
        level = "none"
        level_match = re.search(r"level\s*[:=-]?\s*\"?(substantial|some|few|none)\"?", block_content_lower)
        if level_match:
            level = level_match.group(1)
        else:
            for l_word in ("substantial", "some", "few", "none"):
                if l_word in block_content_lower:
                    level = l_word
                    break
        
        # 4. Parse extracted_years
        extracted_years = None
        years_match = re.search(r"(?:extracted_years|years|duration)\s*[:=-]?\s*(\d+(?:\.\d+)?|null)", block_content_lower)
        if years_match:
            val_str = years_match.group(1)
            if val_str != "null":
                extracted_years = _coerce_years(val_str)
        else:
            m_ey = re.search(r"(\d+(?:\.\d+)?)\s*(?:years?|yrs?|y)\b", block_content_lower)
            if m_ey:
                extracted_years = _coerce_years(m_ey.group(1))

        # 5. Closest evidence / cited text
        closest_evidence = "none"
        cited_text = "none"
        ce_match = re.search(r"closest_evidence\s*[:=-]?\s*\"([^\"]+)\"", block_content)
        if ce_match:
            closest_evidence = ce_match.group(1)
        ct_match = re.search(r"cited_text\s*[:=-]?\s*\"([^\"]+)\"", block_content)
        if ct_match:
            cited_text = ct_match.group(1)
            
        if closest_evidence == "none" and block_content:
            clean_block = re.sub(r"\s+", " ", block_content).strip()
            clean_block = re.sub(r"^[:\-=\s]+", "", clean_block).strip()
            closest_evidence = clean_block[:150]
            cited_text = clean_block[:80]
            
        results.append({
            "key": key,
            "evidence_found": evidence_found,
            "closest_evidence": closest_evidence,
            "cited_text": cited_text,
            "sub_score": sub_score,
            "extracted_years": extracted_years,
            "level": level
        })
    return results


def _parse_llm_response(
    response: str,
    rubric: RubricTemplate,
    target_years: Optional[float] = None,
) -> List[SubScoreResult]:
    """Parse the LLM's JSON response into SubScoreResult objects.

    The parser is deliberately lenient toward small-model quirks (qwen2.5:3b).
    """
    logger.debug(
        "[rubric_scorer] raw LLM response (first 800 chars): %.800s",
        response or "(empty)",
    )

    data = _extract_json_lenient(response)
    raw_sub_scores = []
    if data is not None:
        raw_sub_scores = data.get("sub_scores", [])

    if not raw_sub_scores:
        logger.warning(
            "[rubric_scorer] JSON parsing failed or had no 'sub_scores' list. "
            "Attempting regex fallback parsing on raw text."
        )
        raw_sub_scores = _parse_fallback_regex(response, [sq.key for sq in rubric.sub_questions])

    if not raw_sub_scores:
        logger.warning(
            "[rubric_scorer] Regex fallback parsing also failed to extract sub-scores."
        )
        return _default_sub_scores(rubric, target_years)

    # Build a lookup from the rubric for validation.
    rubric_lookup = {sq.key: sq for sq in rubric.sub_questions}

    results: List[SubScoreResult] = []
    for raw in raw_sub_scores:
        key = raw.get("key", "")
        sq = rubric_lookup.get(key)
        if sq is None:
            logger.warning(
                "[rubric_scorer] Unknown sub-question key %r in LLM response. "
                "Known keys: %s",
                key, list(rubric_lookup.keys()),
            )
            continue

        raw_score = raw.get("sub_score")
        if raw_score is None:
            sub_score = 0.0
        else:
            try:
                sub_score = float(raw_score)
            except (TypeError, ValueError):
                sub_score = 0.0
        sub_score = max(0.0, min(1.0, sub_score))

        # Parse evidence_found / closest_evidence
        raw_ev_found = raw.get("evidence_found", "")
        evidence_found = str(raw_ev_found).strip().lower() == "yes"
        closest_ev = raw.get("closest_evidence") or raw.get("extracted_evidence", "")
        cited_txt = raw.get("cited_text", "")

        extracted_years = None

        if sq.type == "binary":
            from src.scoring.rubrics import score_binary
            # Score using the binary function
            sub_score = score_binary(sub_score >= 0.5 or evidence_found)
        elif sq.type == "four_band":
            raw_ey = raw.get("extracted_years")
            extracted_years = _coerce_years(raw_ey)
            level = raw.get("level") or ""

            from src.scoring.rubrics import score_four_band_quantitative, score_four_band_qualitative

            # Apply the either-or logic for quantitative vs qualitative
            if extracted_years is not None:
                sub_score = score_four_band_quantitative(extracted_years, target_years or 0.0)
            else:
                sub_score = score_four_band_qualitative(level)

        results.append(SubScoreResult(
            key=key,
            question=sq.question.replace("{skill}", ""),
            sub_score=sub_score,
            evidence_found=evidence_found,
            closest_evidence=closest_ev,
            cited_text=cited_txt,
            extracted_years=extracted_years,
            target_years=target_years if sq.type == "four_band" else None,
            anchor_description=raw.get("level", "") if sq.type == "four_band" else "",
        ))

    # Ensure all rubric sub-questions are represented.
    if len(results) < len(rubric.sub_questions):
        existing_keys = {r.key for r in results}
        for sq in rubric.sub_questions:
            if sq.key not in existing_keys:
                logger.debug(
                    "[rubric_scorer] Sub-question key %r missing from LLM response — defaulting to 0.01.",
                    sq.key,
                )
                results.append(SubScoreResult(
                    key=sq.key,
                    question=sq.question.replace("{skill}", ""),
                    sub_score=0.01,
                ))

    return results


def _default_sub_scores(
    rubric: RubricTemplate,
    target_years: Optional[float] = None,
) -> List[SubScoreResult]:
    """Return floor sub-scores for all sub-questions (fallback when LLM fails)."""
    return [
        SubScoreResult(
            key=sq.key,
            question=sq.question.replace("{skill}", ""),
            sub_score=0.01,
            target_years=target_years if sq.type == "four_band" else None,
        )
        for sq in rubric.sub_questions
    ]


def _evaluate_formula(formula: str, sub_scores: List[SubScoreResult]) -> float:
    """Evaluate the rubric formula to produce a normalized score.

    Under the new additive aggregation, Sub-Score is a simple sum of the sub-scores.
    We return the sum of sub-scores.
    """
    return sum(s.sub_score for s in sub_scores)


def _apply_partial_credit_for_unknown_years(
    sub_scores: List[SubScoreResult],
    rubric: RubricTemplate,
) -> None:
    """Apply minimum partial credit when skill is confirmed but score was floor. Mutates in place."""
    binary_keys = {sq.key for sq in rubric.sub_questions if sq.type == "binary"}
    four_band_keys = {sq.key for sq in rubric.sub_questions if sq.type == "four_band"}

    if not binary_keys or not four_band_keys:
        return

    # Check whether ANY binary gate passed.
    gate_passed = any(
        ss.sub_score >= 0.5
        for ss in sub_scores
        if ss.key in binary_keys
    )
    if not gate_passed:
        return

    # Apply minimum credit of 0.25 to four_band sub-questions that have score <= 0.01 (meaning no years and no level)
    for ss in sub_scores:
        if ss.key in four_band_keys and ss.sub_score <= 0.01:
            ss.sub_score = 0.25
            logger.debug(
                "[rubric_scorer] partial-credit rescue: key=%s gate passed "
                "but score was floor — applying minimum credit 0.25.",
                ss.key,
            )


def score_requirement_with_rubric(
    requirement_name: str,
    dimension_type: str,
    weight: float,
    evidence: SectionEvidence,
    target_years: Optional[float] = None,
    llm_caller: Optional[Callable[[str], str]] = None,
    employment_history: Optional[List[Any]] = None,
    sub_queries: Optional[List[Dict[str, Any]]] = None,
) -> CachedScoringTrace:
    """Score a single requirement using the rubric-bound LLM evidence scoring.

    Constructs the RubricTemplate dynamically from parsed sub-queries.
    """
    if not sub_queries:
        # Default sub-queries for backwards compatibility (e.g., unit tests)
        sub_queries = [
            {
                "key": f"{dimension_type}_presence",
                "text": f"Is there evidence of the candidate possessing {requirement_name}?",
                "type": "Binary",
            },
            {
                "key": f"{dimension_type}_depth",
                "text": f"How strong is their experience with {requirement_name}?",
                "type": "Float",
            }
        ]

    # Dynamically build RubricTemplate
    sub_questions = []
    for sq in sub_queries:
        sq_key = sq.get("key") or ""
        sq_txt = sq.get("text") or ""
        sq_type = classify_subquery_type(sq)

        sub_questions.append(SubQuestion(
            key=sq_key,
            question=sq_txt,
            type=sq_type,
            anchors=BINARY_ANCHORS if sq_type == "binary" else [],
            target_field="expected_years" if "years" in sq_txt.lower() else None,
            extract_first=True
        ))

    rubric = RubricTemplate(
        dimension_type=dimension_type,
        sub_questions=sub_questions,
        formula="",
        sections=evidence.sections,
        description=requirement_name
    )

    if not evidence.full_text and not employment_history:
        sub_scores = _default_sub_scores(rubric, target_years)
        return CachedScoringTrace(
            requirement_name=requirement_name,
            dimension_type=dimension_type,
            weight=weight,
            sub_scores=sub_scores,
            normalized_score=0.0,
            weighted_score=0.0,
            formula=rubric.formula,
            sections_read=evidence.sections,
            chunk_ids=[c.chunk_id for c in evidence.chunks],
        )

    # Build the prompt
    prompt = _build_rubric_prompt(
        requirement_name,
        rubric,
        evidence,
        target_years=target_years,
        employment_history=employment_history,
    )

    # Call the LLM
    if llm_caller is None:
        logger.warning("No LLM caller provided; returning zero scores for '%s'", requirement_name)
        sub_scores = [
            SubScoreResult(
                key=sq.key,
                question=sq.question.replace("{skill}", ""),
                sub_score=0.0,
                target_years=target_years if sq.type == "four_band" else None,
            )
            for sq in rubric.sub_questions
        ]
    else:
        try:
            response = llm_caller(prompt)
            sub_scores = _parse_llm_response(response, rubric, target_years)
        except Exception as exc:
            logger.warning("LLM call failed for '%s': %s", requirement_name, exc)
            sub_scores = _default_sub_scores(rubric, target_years)

    # BUG-8 FIX: Override years-type SQ sub-scores with deterministic code.
    #
    # The LLM cannot reliably count years from chunk text — it reads project
    # descriptions and experience bullets, not structured date ranges. As a
    # result all candidates score identically (0.25 floor) on SQs like "How
    # many years of relevant experience?". We replace those LLM scores with a
    # BUG-8 FIX v2: Compute total experience months from start_date/end_date strings.
    #
    # The previous version tried to read `duration_months` from each job entry, but
    # that field is never populated — processed profiles only have `start_date` and
    # `end_date` as strings like "2019-06" or "2017". We parse those directly here.
    if employment_history is not None and target_years and target_years > 0:
        _YEARS_KEYWORDS = ("how many years", "years of", "years in", "years relevant",
                           "years experience", "number of years", "total years")

        def _compute_months_from_dates(jobs) -> int:
            """Sum experience months from start_date/end_date strings across all jobs."""
            from datetime import date
            import re as _re

            today = date.today()
            total = 0

            def _parse_date(s):
                if not s:
                    return None
                s = str(s).strip()
                m = _re.match(r'^(\d{4})-(\d{2})$', s)
                if m:
                    return date(int(m.group(1)), int(m.group(2)), 1)
                m = _re.match(r'^(\d{4})$', s)
                if m:
                    return date(int(m.group(1)), 1, 1)
                return None

            for job in jobs:
                # Support both dataclass attrs and dict keys
                if isinstance(job, dict):
                    start_str = job.get('start_date') or job.get('start') or ''
                    end_str   = job.get('end_date')   or job.get('end')   or ''
                    is_curr   = job.get('is_current', False)
                else:
                    start_str = getattr(job, 'start_date', '') or getattr(job, 'start', '') or ''
                    end_str   = getattr(job, 'end_date', '')   or getattr(job, 'end',   '') or ''
                    is_curr   = getattr(job, 'is_current', False)

                start = _parse_date(start_str)
                end   = _parse_date(end_str) if (end_str and not is_curr) else today
                if start and end and end >= start:
                    months = (end.year - start.year) * 12 + (end.month - start.month)
                    total += months

            return total

        # Try structured-profile attribute first, then raw-list computation
        total_months = getattr(employment_history, 'total_months', None)
        if not total_months and isinstance(employment_history, list):
            total_months = _compute_months_from_dates(employment_history)
        elif not total_months:
            # EmploymentHistory object without total_months — iterate its entries
            entries = getattr(employment_history, 'entries', None) or []
            if entries:
                total_months = _compute_months_from_dates(entries)

        if total_months and total_months > 0:
            detected_years = round(total_months / 12.0, 2)
            from src.scoring.rubrics import score_four_band_quantitative
            for ss in sub_scores:
                sq_txt = ss.question.lower()
                if any(kw in sq_txt for kw in _YEARS_KEYWORDS):
                    code_score = score_four_band_quantitative(detected_years, target_years)
                    logger.debug(
                        "rubric_scorer[BUG-8v2]: overriding '%s' LLM score %.2f -> %.2f "
                        "(%.1f yrs detected / %.0f months vs %.1f target)",
                        ss.key, ss.sub_score, code_score, detected_years, total_months, target_years,
                    )
                    ss.sub_score = code_score
                    ss.extracted_years = detected_years
                    ss.target_years = target_years


    # Partial-credit rescue
    _apply_partial_credit_for_unknown_years(sub_scores, rubric)


    # Evaluate sum sub-score
    normalized = _evaluate_formula(rubric.formula, sub_scores)

    # Compute the weighted contribution score in code: weight * (SubScore / N)
    n_queries = len(sub_scores)
    weighted = weight * (normalized / n_queries) if n_queries > 0 else 0.0

    return CachedScoringTrace(
        requirement_name=requirement_name,
        dimension_type=dimension_type,
        weight=weight,
        sub_scores=sub_scores,
        normalized_score=normalized,
        weighted_score=weighted,
        formula=rubric.formula,
        sections_read=evidence.sections,
        chunk_ids=[c.chunk_id for c in evidence.chunks],
    )


def explain_score_from_cache(trace: CachedScoringTrace) -> str:
    """Narrate a cached scoring trace in recruiter-friendly language."""
    parts: List[str] = []
    parts.append(f"Requirement: {trace.requirement_name}")
    parts.append(f"Weight: {trace.weight}")
    parts.append(f"Sum Sub-Score: {trace.normalized_score:.2f}")
    parts.append(f"Weighted Score: {trace.weighted_score:.1f} / {trace.weight}")
    parts.append("")
    parts.append("Breakdown:")

    for ss in trace.sub_scores:
        parts.append(f"  • {ss.key}: {ss.sub_score:.2f}")
        if ss.closest_evidence:
            if ss.evidence_found:
                parts.append(f"    Evidence of: {ss.closest_evidence}")
            else:
                parts.append(f"    No direct evidence (closest: {ss.closest_evidence})")
        if ss.cited_text:
            parts.append(f"    Cited: \"{ss.cited_text}\"")
        if ss.anchor_description:
            parts.append(f"    Anchor/Level: {ss.anchor_description}")
        if ss.extracted_years is not None:
            target = ss.target_years or "unspecified"
            parts.append(f"    Years: {ss.extracted_years} (target: {target})")

    parts.append("")
    parts.append(f"Sections read: {', '.join(trace.sections_read)}")

    return "\n".join(parts)
