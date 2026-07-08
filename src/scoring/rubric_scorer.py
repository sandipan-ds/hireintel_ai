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
    lines = ["EMPLOYMENT HISTORY (computed deterministically from date ranges — use these durations to answer `years_experience` sub-questions; correlate them with the skill/bullets in the SECTION CONTENT):"]
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
            lines.append(
                f"- {company} | {role} | {dates} | {months} months (~{years} yrs){inferred_marker}"
            )
        except Exception:
            # Defensive: a malformed entry should not break the prompt.
            continue
    if len(lines) <= 1:
        return None
    return "\n".join(lines)


def _build_rubric_prompt(
    requirement_name: str,
    rubric: RubricTemplate,
    evidence: SectionEvidence,
    target_years: Optional[float] = None,
    employment_history: Optional[List[Any]] = None,
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
        employment_history: Optional list of :class:`EmploymentEntry`
            (or duck-typed dicts) from the parsed candidate's
            structured profile. When non-empty, the prompt appends an
            ``EMPLOYMENT HISTORY`` block right after the SECTION
            CONTENT so the LLM can correlate skill mentions in the
            retrieved chunks with the parser-computed role durations.
            Mitigates the failure mode where Recursive chunking splits
            a role's date line away from its bullet points.

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
            # NOTE: The target_years value is intentionally NOT shown to the
            # LLM. A small local model (qwen2.5:3b) may rationalize toward
            # the target when it sees it. The LLM is asked only to extract
            # the number of years; code applies the banded ratio afterwards
            # (see _parse_llm_response → _banded_years_ratio).
            sub_q_lines.append(
                f"    Count the total years of experience the candidate has with this requirement."
            )
            sub_q_lines.append(
                "    Return \"extracted_years\" as a plain NUMBER only (e.g. 3, 2.5, 0). "
                "Do NOT write \"3 years\" or \"approximately 3\" — write only the digit. "
                "Return null (JSON null, not the string \"null\") if there is absolutely no evidence."
            )
            sub_q_lines.append(
                "    Also return \"sub_score\" as 0.0 (code will recompute it from extracted_years)."
            )
            if employment_history:
                sub_q_lines.append(
                    "    IMPORTANT: A pre-computed employment history is provided below. "
                    "Sum the durations (in years) of all roles where this skill/requirement "
                    "is mentioned in the SECTION CONTENT bullets. Do not re-parse raw dates."
                )
        elif sq.type == "anchored":
            sub_q_lines.append(f"    Pick EXACTLY one anchor value from the list below (copy the number exactly):")
            for anchor in sq.anchors:
                sub_q_lines.append(f"      {anchor.value} — {anchor.description}")
            sub_q_lines.append(f"    Return: \"sub_score\" set to that anchor number, \"anchor_description\" set to the anchor text.")

        if sq.extract_first:
            sub_q_lines.append(
                f"    Step 1 — copy the relevant text from SECTION CONTENT into "
                f"\"extracted_evidence\" and \"cited_text\" before you score."
            )
        sub_q_lines.append("")

    sub_questions_text = "\n".join(sub_q_lines)

    # The formula (for transparency, but the LLM does NOT compute it).
    formula_text = rubric.formula

    employment_block = _format_employment_history(employment_history)
    employment_section = ""
    if employment_block:
        employment_section = f"""
{employment_block}
---

"""
    # Build a pre-populated JSON skeleton so small models (qwen2.5:3b) do not
    # decide how many array entries to produce — they only need to fill in the
    # values. Without this, qwen2.5:3b typically outputs only the first entry
    # and stops, leaving all subsequent sub-questions at 0.
    skeleton_entries: List[str] = []
    for sq in rubric.sub_questions:
        if sq.type == "binary":
            entry = (
                f'    {{\n'
                f'      "key": "{sq.key}",\n'
                f'      "extracted_evidence": "FILL: paste relevant resume text here",\n'
                f'      "cited_text": "FILL: short exact quote",\n'
                f'      "sub_score": FILL_0_OR_1,\n'
                f'      "extracted_years": null,\n'
                f'      "anchor_description": ""\n'
                f'    }}'
            )
        elif sq.type == "linear":
            entry = (
                f'    {{\n'
                f'      "key": "{sq.key}",\n'
                f'      "extracted_evidence": "FILL: paste relevant resume text here",\n'
                f'      "cited_text": "FILL: short exact quote",\n'
                f'      "sub_score": 0,\n'
                f'      "extracted_years": FILL_NUMBER_OR_NULL,\n'
                f'      "anchor_description": ""\n'
                f'    }}'
            )
        else:  # anchored
            anchor_vals = " / ".join(str(a.value) for a in sq.anchors)
            entry = (
                f'    {{\n'
                f'      "key": "{sq.key}",\n'
                f'      "extracted_evidence": "FILL: paste relevant resume text here",\n'
                f'      "cited_text": "FILL: short exact quote",\n'
                f'      "sub_score": FILL_ONE_OF_{anchor_vals},\n'
                f'      "extracted_years": null,\n'
                f'      "anchor_description": "FILL: which anchor you chose and why"\n'
                f'    }}'
            )
        skeleton_entries.append(entry)

    skeleton_json = ",\n".join(skeleton_entries)

    prompt = f"""You are a resume evidence scorer. Score the candidate for ONE requirement.

REQUIREMENT: {requirement_name}

RUBRIC sub-questions to answer:
{sub_questions_text}
RESUME CONTENT:
---
{evidence.full_text}
---
{employment_section}
TASK: Fill in the JSON below. Replace every FILL_... placeholder with the real value.
- For binary keys: sub_score must be 0 or 1 (integer, no quotes).
- For linear keys: extracted_years must be a plain number like 3 or 2.5, NOT a string. Use JSON null if no evidence.
- Do NOT add extra keys. Do NOT change the "key" values. Output ONLY the JSON, nothing else.

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


def _parse_llm_response(
    response: str,
    rubric: RubricTemplate,
    target_years: Optional[float] = None,
) -> List[SubScoreResult]:
    """Parse the LLM's JSON response into SubScoreResult objects.

    The parser is deliberately lenient toward small-model quirks
    (qwen2.5:3b):

    * Uses :func:`_extract_json_lenient` to survive truncated JSON.
    * Uses :func:`_coerce_years` to handle ``extracted_years`` values
      that are strings (``"3 years"``) instead of JSON numbers.
    * When ``extracted_years`` is ``null`` / ``None`` for a linear
      sub-question but the LLM returned a non-zero ``sub_score``,
      that clamped score is used as-is rather than forced to 0 — this
      preserves partial credit when the LLM can't count years but at
      least signals the skill is present.

    Args:
        response: The raw LLM response text.
        rubric: The rubric template (for sub-question metadata).
        target_years: Target years for linear sub-questions.

    Returns:
        List of SubScoreResult, one per sub-question in the rubric.
    """
    # Always log the raw response at DEBUG level so the years-parsing
    # failure mode is immediately visible without adding print()s.
    logger.debug(
        "[rubric_scorer] raw LLM response (first 800 chars): %.800s",
        response or "(empty)",
    )

    data = _extract_json_lenient(response)
    if data is None:
        logger.warning(
            "[rubric_scorer] No JSON found in LLM response. "
            "Raw response (first 400 chars): %.400s",
            response or "(empty)",
        )
        return _default_sub_scores(rubric, target_years)

    raw_sub_scores = data.get("sub_scores", [])
    if not raw_sub_scores:
        logger.warning(
            "[rubric_scorer] LLM JSON had no 'sub_scores' list. "
            "Parsed data keys: %s",
            list(data.keys()),
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
        # Defensive: handle "sub_score": null or missing → 0.0.
        if raw_score is None:
            sub_score = 0.0
        else:
            try:
                sub_score = float(raw_score)
            except (TypeError, ValueError):
                logger.warning(
                    "[rubric_scorer] Invalid sub_score %r for key %s — defaulting to 0.0",
                    raw_score, key,
                )
                sub_score = 0.0
        # Clamp to 0.0–1.0.
        sub_score = max(0.0, min(1.0, sub_score))

        # For binary, force to 0 or 1.
        if sq.type == "binary":
            sub_score = 1.0 if sub_score >= 0.5 else 0.0

        # For linear sub-questions: robustly parse extracted_years (which
        # small models often return as a string) then apply the banded ratio.
        if sq.type == "linear":
            raw_ey = raw.get("extracted_years")
            # Use the robust coercer rather than a bare float() call.
            # This handles "3 years", "~4", "approximately 3", etc.
            extracted_years = _coerce_years(raw_ey)

            if extracted_years is None and raw_ey is not None:
                logger.warning(
                    "[rubric_scorer] Could not coerce extracted_years %r for "
                    "key %s to float — treating as None.",
                    raw_ey, key,
                )

            if extracted_years is not None and target_years and target_years > 0:
                # Banded years-ratio (owner spec 2026-07-07):
                #   >= target → 1.0; >= 50% → 0.5; >= 25% → 0.25; else 0.0.
                sub_score = _banded_years_ratio(extracted_years, target_years)
                logger.debug(
                    "[rubric_scorer] key=%s extracted_years=%.1f target=%.1f "
                    "→ banded sub_score=%.2f",
                    key, extracted_years, target_years, sub_score,
                )
            elif extracted_years is None and sub_score > 0:
                # The LLM could not extract a years figure but it DID
                # assign a non-zero sub_score. Trust the clamped score
                # as partial credit rather than zeroing it out. This
                # avoids the failure mode where the 3B model correctly
                # identifies the skill but fails the years field format.
                logger.debug(
                    "[rubric_scorer] key=%s: extracted_years=None but "
                    "LLM sub_score=%.2f retained as partial credit.",
                    key, sub_score,
                )
            else:
                # extracted_years is None AND sub_score == 0 (or target
                # is missing). No credit — correct behaviour.
                if target_years is None or target_years <= 0:
                    logger.debug(
                        "[rubric_scorer] key=%s: target_years is %r — "
                        "no banded ratio applied; sub_score=%.2f kept.",
                        key, target_years, sub_score,
                    )

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
                logger.debug(
                    "[rubric_scorer] Sub-question key %r missing from LLM "
                    "response — defaulting to 0.0.",
                    sq.key,
                )
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

def _apply_partial_credit_for_unknown_years(
    sub_scores: List[SubScoreResult],
    rubric: RubricTemplate,
) -> None:
    """Apply minimum partial credit when skill is confirmed but years unknown.

    This fixes the most common qwen2.5:3b failure mode: the model correctly
    identifies that the candidate has a skill (binary gate = 1) but returns
    ``extracted_years = null`` for the linear years sub-question because it
    sees dates in text format ("2016 - Ongoing") and can't compute duration.

    Without this rescue, the formula ``gate * years_ratio`` evaluates to
    ``1.0 * 0.0 = 0.0``, which is misleading — we KNOW the candidate has
    the skill.

    Resolution:
    * If the binary sub-question has ``sub_score == 1.0``.
    * AND the linear sub-question has ``sub_score == 0.0`` AND
      ``extracted_years is None``.
    * THEN set the linear sub_score to the minimum banded credit (0.25).

    This is deliberately conservative: 0.25 corresponds to the
    ``< 25% of target years`` banded band. The recruiter should treat this
    as "skill confirmed, duration indeterminate" in the explanation.

    The function mutates ``sub_scores`` in place.

    Args:
        sub_scores: Parsed sub-score results from the LLM response.
        rubric: The rubric template used for scoring.
    """
    # Find binary and linear sub-questions in this rubric.
    binary_keys = {sq.key for sq in rubric.sub_questions if sq.type == "binary"}
    linear_keys = {sq.key for sq in rubric.sub_questions if sq.type == "linear"}

    if not binary_keys or not linear_keys:
        return  # rubric doesn't have the gate+years pattern

    # Check whether ANY binary gate passed.
    gate_passed = any(
        ss.sub_score >= 0.5
        for ss in sub_scores
        if ss.key in binary_keys
    )
    if not gate_passed:
        return  # skill not confirmed — zero is correct

    # Apply minimum credit to linear sub-questions that have no years.
    for ss in sub_scores:
        if ss.key in linear_keys and ss.extracted_years is None and ss.sub_score == 0.0:
            ss.sub_score = 0.25
            logger.debug(
                "[rubric_scorer] partial-credit rescue: key=%s gate passed "
                "but extracted_years=None — applying minimum credit 0.25.",
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
        employment_history: Optional list of ``EmploymentEntry`` (or
            duck-typed dicts with the same shape) from the candidate's
            structured profile. When non-empty, the prompt appends an
            ``EMPLOYMENT HISTORY`` block so the LLM can correlate skill
            mentions in the retrieved chunks with the parser-computed
            role durations. Mitigates the failure mode where Recursive
            chunking splits a role's date line away from its bullets.

    Returns:
        ``CachedScoringTrace`` with all sub-scores, evidence, and computed scores.
    """
    rubric = get_rubric(dimension_type)

    # If no evidence was found AND no employment history is provided,
    # return a zero trace. (When employment_history is provided but
    # evidence.full_text is empty, we still call the LLM — the
    # employment_history block alone may be enough for the LLM to
    # score presence/years. The evidence-empty short-circuit only
    # fires when BOTH inputs are empty.)
    if not evidence.full_text and not employment_history:
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

    # Build the prompt (weight is NOT included). When employment_history
    # is non-empty, the prompt includes an EMPLOYMENT HISTORY block right
    # after the SECTION CONTENT so the LLM can correlate skill mentions
    # in retrieved chunks with parser-computed role durations.
    prompt = _build_rubric_prompt(
        requirement_name,
        rubric,
        evidence,
        target_years=target_years,
        employment_history=employment_history,
    )

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

    # Partial-credit rescue: if the binary gate passed (skill confirmed present)
    # but the linear years sub-question returned null (model saw dates in text
    # but can't compute duration — typical qwen2.5:3b failure), apply the
    # minimum banded credit (0.25) rather than zeroing the entire REQ.
    #
    # Rationale: the candidate demonstrably HAS the skill (gate=1) so a zero
    # contribution is misleading. 0.25 corresponds to the "<= 25% of target"
    # banded band — the most conservative non-zero credit.
    _apply_partial_credit_for_unknown_years(sub_scores, rubric)

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
