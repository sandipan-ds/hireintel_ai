"""Diagnostic: fire one rubric scoring call and print every step.

Usage (from repo root):
    python scripts/debug_llm_response.py

What this shows:
    1. The full prompt sent to qwen2.5:3b.
    2. The raw LLM response.
    3. The parsed sub-scores (after _coerce_years + banded ratio).
    4. The final normalized_score produced by the formula.

Helpful for diagnosing why years sub-scores are zero.
"""
from __future__ import annotations

import glob
import json
import logging
import sys
from pathlib import Path

# ---- Path setup so we can run without pip install ----
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Enable DEBUG logging so _coerce_years and banded-ratio logs are visible.
logging.basicConfig(
    level=logging.DEBUG,
    format="[%(levelname)s %(name)s] %(message)s",
)
# Silence noisy third-party loggers.
for noisy in ("httpx", "openai", "urllib3", "sentence_transformers"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

from src.scoring.rubric_scorer import (
    _build_rubric_prompt,
    _coerce_years,
    _parse_llm_response,
    score_requirement_with_rubric,
)
from src.scoring.rubrics import get_rubric
from src.rag.section_routed import SectionEvidence
from src.services.llm_caller import get_rubric_caller


def main() -> None:
    print("=" * 70)
    print("DEBUG: rubric scorer with qwen2.5:3b")
    print("=" * 70)

    # ------------------------------------------------------------------
    # 1. Load a real candidate profile.
    # ------------------------------------------------------------------
    # Use a candidate that has Python explicitly in experience with date ranges.
    specific = Path("data/processed/DataScience/843364b33ef03162.json")
    if specific.exists():
        path = specific
    else:
        candidates = sorted(
            p for p in glob.glob("data/processed/DataScience/*.json")
            if not p.endswith("_intelligence_report.json")
            and not p.endswith("_structured_profile.json")
        )
        if not candidates:
            print("ERROR: no DataScience candidate parses found.")
            sys.exit(1)
        path = Path(candidates[0])
    print(f"\nCandidate file: {path.name}")
    with path.open(encoding="utf-8") as fh:
        profile = json.load(fh)

    # ------------------------------------------------------------------
    # 2. Build a minimal SectionEvidence for Python (REQ-001).
    # ------------------------------------------------------------------
    exp = profile.get("experience", {})
    entries = exp.get("entries", []) if isinstance(exp, dict) else (exp if isinstance(exp, list) else [])

    exp_parts = []
    for entry in entries[:5]:
        title = entry.get("title", "")
        company = entry.get("company", "")
        dates = entry.get("dates", "")
        details = entry.get("details", [])
        block = f"{title} at {company} ({dates})\n" + "\n".join(
            f"  - {d}" for d in details[:10] if d
        )
        exp_parts.append(block)

    skills = profile.get("skills", [])
    skills_text = "Skills: " + ", ".join(str(s) for s in (skills if isinstance(skills, list) else []))
    resume_text = ("\n\n".join(exp_parts) + "\n\n" + skills_text)[:2500]

    print(f"\n--- RESUME TEXT EXCERPT (first 500 chars) ---")
    print(resume_text[:500])
    print("...")

    evidence = SectionEvidence(
        requirement_type="skill",
        requirement_name="Python & Data Science Libraries",
        sections=["Experience", "Skills"],
        chunks=[],
        full_text=resume_text,
        chunk_count=0,
    )

    # ------------------------------------------------------------------
    # 3. Build and print the prompt.
    # ------------------------------------------------------------------
    rubric = get_rubric("skill")
    target_years = 3.0  # from REQ-001 spec

    prompt = _build_rubric_prompt(
        requirement_name="Python & Data Science Libraries (pandas, NumPy, scikit-learn)",
        rubric=rubric,
        evidence=evidence,
        target_years=target_years,
        employment_history=None,
    )
    print(f"\n--- FULL PROMPT ({len(prompt)} chars) ---")
    print(prompt)

    # ------------------------------------------------------------------
    # 4. Call the LLM.
    # ------------------------------------------------------------------
    caller = get_rubric_caller()
    if not getattr(caller, "_available", False):
        print("\nERROR: LLM caller not available. Check .env for LLM_BACKEND=ollama.")
        sys.exit(1)

    print(f"\n--- CALLING LLM ({caller.model_name}) ---")
    raw_response = caller(prompt)
    print(f"\n--- RAW LLM RESPONSE ---")
    print(raw_response)

    # ------------------------------------------------------------------
    # 5. Parse the response.
    # ------------------------------------------------------------------
    print(f"\n--- PARSED SUB-SCORES ---")
    sub_scores = _parse_llm_response(raw_response, rubric, target_years=target_years)
    for ss in sub_scores:
        print(
            f"  {ss.key}: sub_score={ss.sub_score:.4f}  "
            f"extracted_years={ss.extracted_years}  "
            f"cited={ss.cited_text[:80]!r}"
        )

    # ------------------------------------------------------------------
    # 6. Full score call.
    # ------------------------------------------------------------------
    print(f"\n--- score_requirement_with_rubric result ---")
    trace = score_requirement_with_rubric(
        requirement_name="Python & Data Science Libraries",
        dimension_type="skill",
        weight=15.0,
        evidence=evidence,
        target_years=target_years,
        llm_caller=caller,
    )
    print(f"  normalized_score : {trace.normalized_score:.4f}")
    print(f"  weighted_score   : {trace.weighted_score:.4f}  (weight=15%)")
    print(f"  formula          : {trace.formula}")
    for ss in trace.sub_scores:
        print(f"    {ss.key}: {ss.sub_score:.4f}")

    print("\n" + "=" * 70)
    if trace.normalized_score > 0:
        print("RESULT: normalized_score > 0  --> FIX WORKED.")
    else:
        print("RESULT: normalized_score == 0  --> still broken; check raw response above.")
    print("=" * 70)


if __name__ == "__main__":
    main()
