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
from src.scoring.rubrics import RubricTemplate, SubQuestion, get_rubric

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
        extracted_evidence: What the LLM extracted as relevant (for
            extract_first sub-questions). Empty for code-only sub-questions.
        cited_text: The exact resume text cited as evidence.
        anchor_description: For anchored sub-questions, the description of the
            chosen anchor. Empty for binary and linear types.
        extracted_years: For linear sub-questions, the years extracted by the LLM.
        target_years: For linear sub-questions, the target/ideal years from config.
    """

    key: str
    question: str
    sub_score: float
    extracted_evidence: str = ""
    cited_text: str = ""
    anchor_description: str = ""
    extracted_years: Optional[float] = None
    target_years: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "question": self.question,
            "sub_score": self.sub_score,
            "extracted_evidence": self.extracted_evidence,
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
        }


# ---------------------------------------------------------------------------
# Prompt construction — RUBRIC-SCORE-001.
# ---------------------------------------------------------------------------

def _build_rubric_prompt(
    requirement_name: str,
    rubric: RubricTemplate,
    evidence: SectionEvidence,
    target_years: Optional[float] = None,
) -> str:
    """Build the RUBRIC-SCORE-001 prompt for the LLM judge.

    Key constraints enforced by the prompt:
    * The weight is NOT included — the LLM never sees it.
    * The LLM must extract evidence BEFORE scoring.
    * The LLM must pick from anchored scales, not free-form labels.
    * The LLM must return structured JSON.

    Args:
        requirement_name: The requirement from the JD (e.g., "Python").
        rubric: The rubric template for this dimension type.
        evidence: The section-routed evidence (full section content).
        target_years: The recruiter-defined target years (for linear sub-questions).

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
        elif sq.type == "linear":
            target = target_years or "not specified"
            sub_q_lines.append(f"    Extract the years of experience, then the ratio will be computed as min(years/{target}, 1.0)")
            sub_q_lines.append(f"    Return: extracted_years (number)")
        elif sq.type == "anchored":
            sub_q_lines.append(f"    Pick EXACTLY one anchor:")
            for anchor in sq.anchors:
                sub_q_lines.append(f"      {anchor.value} — {anchor.description}")
            sub_q_lines.append(f"    Return: sub_score (one of the anchor values)")

        if sq.extract_first:
            sub_q_lines.append(f"    First, extract the relevant evidence from the section content, then score.")
        sub_q_lines.append("")

    sub_questions_text = "\n".join(sub_q_lines)

    # The formula (for transparency, but the LLM does NOT compute it).
    formula_text = rubric.formula

    prompt = f"""You are a resume evidence scorer. You will score a candidate against a specific job requirement using a fixed rubric.

CRITICAL RULES:
1. You must NOT consider the importance or point value of this requirement — you are only scoring evidence quality.
2. You must NOT compute any aggregated score — just return sub-scores.
3. You must score strictly against the rubric below — never use your own notions of "Advanced" or "Strong".
4. For each sub-question with "extract first", you MUST list the relevant evidence you found BEFORE giving the score.
5. If evidence is insufficient for a sub-question, return 0 for that sub-question — do not speculate.

REQUIREMENT: {requirement_name}
DIMENSION TYPE: {rubric.dimension_type}

RUBRIC (formula applied in code, NOT by you: {formula_text}):

{sub_questions_text}

SECTION CONTENT (from the candidate's resume):
---
{evidence.full_text}
---

Respond with ONLY a JSON object (no other text) in this format:
{{
  "sub_scores": [
    {{
      "key": "<sub-question key>",
      "extracted_evidence": "<what you found that's relevant>",
      "cited_text": "<exact text from the resume that supports the score>",
      "sub_score": <numeric score — 0 or 1 for binary, anchor value for anchored, 0.0-1.0 for linear>,
      "extracted_years": <number or null — only for linear type>,
      "anchor_description": "<description of chosen anchor — only for anchored type>"
    }}
  ]
}}"""

    return prompt


# ---------------------------------------------------------------------------
# Response parsing — extract structured sub-scores from LLM output.
# ---------------------------------------------------------------------------

def _parse_llm_response(
    response: str,
    rubric: RubricTemplate,
    target_years: Optional[float] = None,
) -> List[SubScoreResult]:
    """Parse the LLM's JSON response into SubScoreResult objects.

    Args:
        response: The raw LLM response text.
        rubric: The rubric template (for sub-question metadata).
        target_years: Target years for linear sub-questions.

    Returns:
        List of SubScoreResult, one per sub-question in the rubric.
    """
    # Extract JSON from the response (handles markdown code fences).
    json_match = re.search(r'\{[^{}]*"(?:sub_scores)"[^{}]*\[.*?\]\s*\}', response, re.DOTALL)
    if not json_match:
        # Try a simpler approach — find the first { and last }.
        first = response.find("{")
        last = response.rfind("}")
        if first != -1 and last != -1:
            json_str = response[first:last + 1]
        else:
            logger.warning("No JSON found in LLM response")
            return _default_sub_scores(rubric, target_years)
    else:
        json_str = json_match.group()

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON in LLM response: %s", json_str[:200])
        return _default_sub_scores(rubric, target_years)

    raw_sub_scores = data.get("sub_scores", [])
    if not raw_sub_scores:
        return _default_sub_scores(rubric, target_years)

    # Build a lookup from the rubric for validation.
    rubric_lookup = {sq.key: sq for sq in rubric.sub_questions}

    results: List[SubScoreResult] = []
    for raw in raw_sub_scores:
        key = raw.get("key", "")
        sq = rubric_lookup.get(key)
        if sq is None:
            logger.warning("Unknown sub-question key '%s' in LLM response", key)
            continue

        sub_score = float(raw.get("sub_score", 0.0))
        # Clamp to 0.0–1.0.
        sub_score = max(0.0, min(1.0, sub_score))

        # For binary, force to 0 or 1.
        if sq.type == "binary":
            sub_score = 1.0 if sub_score >= 0.5 else 0.0

        # For linear, compute the ratio from extracted years.
        if sq.type == "linear":
            extracted_years = raw.get("extracted_years")
            if extracted_years is not None:
                try:
                    extracted_years = float(extracted_years)
                except (ValueError, TypeError):
                    extracted_years = None

            if extracted_years is not None and target_years and target_years > 0:
                sub_score = min(extracted_years / target_years, 1.0)
            else:
                # If no years extracted, use the LLM's score directly.
                pass

            results.append(SubScoreResult(
                key=key,
                question=sq.question.replace("{skill}", ""),
                sub_score=sub_score,
                extracted_evidence=raw.get("extracted_evidence", ""),
                cited_text=raw.get("cited_text", ""),
                extracted_years=extracted_years,
                target_years=target_years,
            ))
            continue

        results.append(SubScoreResult(
            key=key,
            question=sq.question.replace("{skill}", ""),
            sub_score=sub_score,
            extracted_evidence=raw.get("extracted_evidence", ""),
            cited_text=raw.get("cited_text", ""),
            anchor_description=raw.get("anchor_description", ""),
        ))

    # Ensure all rubric sub-questions are represented.
    if len(results) < len(rubric.sub_questions):
        existing_keys = {r.key for r in results}
        for sq in rubric.sub_questions:
            if sq.key not in existing_keys:
                results.append(SubScoreResult(
                    key=sq.key,
                    question=sq.question.replace("{skill}", ""),
                    sub_score=0.0,
                ))

    return results


def _default_sub_scores(
    rubric: RubricTemplate,
    target_years: Optional[float] = None,
) -> List[SubScoreResult]:
    """Return zero sub-scores for all sub-questions (fallback when LLM fails).

    Args:
        rubric: The rubric template.
        target_years: Target years for linear sub-questions.

    Returns:
        List of SubScoreResult with sub_score=0.0.
    """
    return [
        SubScoreResult(
            key=sq.key,
            question=sq.question.replace("{skill}", ""),
            sub_score=0.0,
            target_years=target_years if sq.type == "linear" else None,
        )
        for sq in rubric.sub_questions
    ]


# ---------------------------------------------------------------------------
# Formula evaluation — compute the normalized score from sub-scores in code.
# ---------------------------------------------------------------------------

def _evaluate_formula(formula: str, sub_scores: List[SubScoreResult]) -> float:
    """Evaluate the rubric formula to produce a normalized score (0.0–1.0).

    The formula references sub-question keys. This function looks up each
    key's sub_score and evaluates the formula safely.

    Args:
        formula: The formula string (e.g., "gate * years_ratio * relevance").
        sub_scores: The list of sub-score results.

    Returns:
        Normalized score (0.0–1.0).
    """
    # Build a lookup of key → sub_score.
    score_map = {s.key: s.sub_score for s in sub_scores}

    # Map formula variable names to sub-question keys.
    # The formula uses short names; we need to resolve them to actual keys.
    # For the standard formulas, the mapping is:
    #   gate / presence / match → the binary gate sub-question
    #   years_ratio → the linear years sub-question
    #   relevance → the anchored relevance sub-question
    #   leadership_gate → the leadership_gate sub-question
    #   complexity → the complexity sub-question
    #   proficiency → the proficiency sub-question
    #   communication_score → the communication_score sub-question
    #   organization_score → the organization_score sub-question
    #   degree_match → the degree_match sub-question
    #   institute_tier_points → the institute_tier sub-question
    #   cert_match → the cert_match sub-question
    #   provider_tier_points → the provider_tier sub-question

    # Strategy: try to match each variable name in the formula to a sub-question
    # key. If the variable name is itself a key, use it directly. Otherwise,
    # try common mappings.
    var_map: Dict[str, float] = {}

    # First pass: direct key matches.
    for s in sub_scores:
        var_map[s.key] = s.sub_score

    # Second pass: formula-specific variable resolution.
    # The formula references variables like "gate", "years_ratio", etc.
    # We need to find which sub-question each variable refers to.
    formula_vars = re.findall(r'[a-z_]+', formula)

    # Binary gate resolution: find the first binary sub-question.
    binary_keys = [s.key for s in sub_scores
                   if any(sq.type == "binary" and sq.key == s.key
                          for sq in get_rubric_formula_sub_questions(sub_scores))]

    # Simpler approach: for each formula variable, try to find a matching
    # sub-question key, or use a heuristic mapping.
    for var in formula_vars:
        if var in var_map:
            continue  # Already resolved

        # Try to find a sub-question key that contains the variable name.
        for s in sub_scores:
            if var in s.key or s.key in var:
                var_map[var] = s.sub_score
                break

        if var not in var_map:
            # Common mappings.
            if var in ("gate", "presence", "match"):
                # Find the first binary sub-question.
                for s in sub_scores:
                    if _is_binary_key(s.key, sub_scores):
                        var_map[var] = s.sub_score
                        break
            elif var == "years_ratio":
                # Find the linear sub-question.
                for s in sub_scores:
                    if s.target_years is not None or "years" in s.key:
                        var_map[var] = s.sub_score
                        break
            elif var == "relevance":
                for s in sub_scores:
                    if "relevance" in s.key:
                        var_map[var] = s.sub_score
                        break
            elif var == "complexity":
                for s in sub_scores:
                    if "complexity" in s.key:
                        var_map[var] = s.sub_score
                        break
            elif var == "proficiency":
                for s in sub_scores:
                    if "proficiency" in s.key:
                        var_map[var] = s.sub_score
                        break

        # If still not found, default to 1.0 (neutral element for multiplication).
        if var not in var_map:
            var_map[var] = 1.0
            logger.debug("Formula variable '%s' not found in sub-scores; defaulting to 1.0", var)

    # Evaluate the formula safely.
    # Replace variable names with their values.
    expr = formula
    for var, val in sorted(var_map.items(), key=lambda x: -len(x[0])):
        expr = expr.replace(var, str(val))

    # Replace " * " with " * " (already correct), evaluate.
    try:
        result = eval(expr, {"__builtins__": {}}, {})
        result = max(0.0, min(1.0, float(result)))
    except Exception as exc:
        logger.warning("Formula evaluation failed for '%s': %s", formula, exc)
        # Fallback: multiply all sub-scores.
        product = 1.0
        for s in sub_scores:
            product *= s.sub_score
        result = max(0.0, min(1.0, product))

    return result


def get_rubric_formula_sub_questions(sub_scores: List[SubScoreResult]):
    """Helper to get rubric sub-question metadata for formula resolution."""
    # This is a placeholder — in practice, the rubric is passed alongside.
    # For now, we return empty to force the key-based lookup.
    return []


def _is_binary_key(key: str, sub_scores: List[SubScoreResult]) -> bool:
    """Check if a sub-question key is likely a binary gate."""
    binary_indicators = ("presence", "gate", "match", "match_")
    return any(ind in key for ind in binary_indicators)


# ---------------------------------------------------------------------------
# Public API — score a requirement with the rubric-bound LLM.
# ---------------------------------------------------------------------------

def score_requirement_with_rubric(
    requirement_name: str,
    dimension_type: str,
    weight: float,
    evidence: SectionEvidence,
    target_years: Optional[float] = None,
    llm_caller: Optional[Callable[[str], str]] = None,
) -> CachedScoringTrace:
    """Score a single requirement using the rubric-bound LLM evidence scoring.

    This is the main entry point for Mode 2 scoring. It:
    1. Looks up the rubric template for the dimension type.
    2. Builds the RUBRIC-SCORE-001 prompt (weight NOT included).
    3. Calls the LLM to get structured sub-scores.
    4. Parses the response into SubScoreResult objects.
    5. Evaluates the formula in code to get the normalized score.
    6. Computes the weighted score (weight × normalized_score) in code.
    7. Returns a CachedScoringTrace for later explanation.

    Args:
        requirement_name: The requirement from the JD (e.g., "Python").
        dimension_type: The dimension type (e.g., "skill", "experience").
        weight: The recruiter-assigned weight (0–10). NOT passed to the LLM.
        evidence: The Section-Routed evidence (full section content).
        target_years: Target/ideal years for linear sub-questions.
        llm_caller: Callable that takes a prompt string and returns the LLM
            response. If None, returns a zero-score trace.

    Returns:
        ``CachedScoringTrace`` with all sub-scores, evidence, and computed scores.
    """
    rubric = get_rubric(dimension_type)

    # If no evidence was found, return a zero trace.
    if not evidence.full_text:
        sub_scores = _default_sub_scores(rubric, target_years)
        normalized = 0.0
        weighted = 0.0
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

    # Build the prompt (weight is NOT included).
    prompt = _build_rubric_prompt(requirement_name, rubric, evidence, target_years)

    # Call the LLM (or fall back to zero scores).
    if llm_caller is None:
        logger.warning("No LLM caller provided; returning zero scores for '%s'", requirement_name)
        sub_scores = _default_sub_scores(rubric, target_years)
    else:
        try:
            response = llm_caller(prompt)
            sub_scores = _parse_llm_response(response, rubric, target_years)
        except Exception as exc:
            logger.warning("LLM call failed for '%s': %s", requirement_name, exc)
            sub_scores = _default_sub_scores(rubric, target_years)

    # Evaluate the formula in code (never by the LLM).
    normalized = _evaluate_formula(rubric.formula, sub_scores)

    # Compute the weighted score in code.
    weighted = weight * normalized

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


# ---------------------------------------------------------------------------
# Score explanation — narrate the cached trace (SCORE-EXPLAIN-001).
# ---------------------------------------------------------------------------

def explain_score_from_cache(trace: CachedScoringTrace) -> str:
    """Narrate a cached scoring trace in recruiter-friendly language.

    This is the SCORE-EXPLAIN-001 implementation. It reads the cached trace
    (frozen at scoring time) and produces a human-readable explanation
    without re-scoring.

    Args:
        trace: The cached scoring trace for one requirement.

    Returns:
        A recruiter-readable explanation string.
    """
    parts: List[str] = []
    parts.append(f"Requirement: {trace.requirement_name}")
    parts.append(f"Weight: {trace.weight}")
    parts.append(f"Normalized Score: {trace.normalized_score:.2f} / 1.0")
    parts.append(f"Weighted Score: {trace.weighted_score:.1f} / {trace.weight}")
    parts.append("")
    parts.append("Breakdown:")

    for ss in trace.sub_scores:
        parts.append(f"  • {ss.key}: {ss.sub_score:.2f}")
        if ss.extracted_evidence:
            parts.append(f"    Evidence: {ss.extracted_evidence}")
        if ss.cited_text:
            parts.append(f"    Cited: \"{ss.cited_text}\"")
        if ss.anchor_description:
            parts.append(f"    Anchor: {ss.anchor_description}")
        if ss.extracted_years is not None:
            target = ss.target_years or "unspecified"
            parts.append(f"    Years: {ss.extracted_years} (target: {target})")

    parts.append("")
    parts.append(f"Formula: {trace.formula}")
    parts.append(f"Sections read: {', '.join(trace.sections_read)}")

    return "\n".join(parts)
