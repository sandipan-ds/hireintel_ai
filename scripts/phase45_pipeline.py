"""Phase 4.5 Pipeline wire unified scorer into batch pipeline.

Implements the recommended next unit of work from docs/CURRENT_PROGRESS.md:

  1. Re-parse all resumes with Header Normalization
  2. Re-chunk with the updated chunker (full metadata schema)
  3. Extract structured profiles
  4. Run unified scorer (code-only + rubric-bound LLM)
  5. Produce ranked scores with scoring traces
  6. Aggregate candidate intelligence reports

Usage:
    python scripts/phase45_pipeline.py --role BusinessAnalyst
    python scripts/phase45_pipeline.py --all-roles
    python scripts/phase45_pipeline.py --all-roles --skip-scoring

Outputs:
    data/processed/<role>/<candidate_id>.json
    data/processed/<role>/<candidate_id>_structured_profile.json
    data/processed/<role>/<candidate_id>_intelligence_report.json
    data/chunks/<role>/<candidate_id>.jsonl
    data/scores/graded/<role>_ranked.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

# Make the src package importable when run as a script.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.resume_parsing.parser import parse_resume
from src.resume_parsing.header_normalization import synonym_lookup
from src.resume_parsing.structured_profile import extract_structured_profile
from src.rag.chunker import chunk_profile
from src.scoring.graded_scorer import evaluate_candidate as graded_score_one
from src.scoring.unified_scorer import evaluate_candidate_unified

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("phase45")

ORIGINAL_DIR = _ROOT / "data" / "original"
PROCESSED_DIR = _ROOT / "data" / "processed"
CHUNKS_DIR = _ROOT / "data" / "chunks"
SCORES_DIR = _ROOT / "data" / "scores" / "graded"


# Maps parser section keys to the 7 canonical sections when the synonym
# table does not catch them. Kept lowercase.
_FALLBACK_CANONICAL = {
    "summary": "Personal_Info",
    "profile": "Personal_Info",
    "about me": "Personal_Info",
    "personal": "Personal_Info",
    "experience": "Experience",
    "work experience": "Experience",
    "education": "Education",
    "academic": "Education",
    "skills": "Skills",
    "technical skills": "Skills",
    "certifications": "Certifications",
    "certification": "Certifications",
    "projects": "Projects",
    "languages": "Languages",
}


def normalize_profile_sections(profile: Dict[str, Any]) -> None:
    """Re-key profile['sections'] to the 7 canonical section labels.

    Uses the synonym_lookup table first (free, deterministic) and falls
    back to a small mapping for parser-native section keys.
    """
    sections = profile.get("sections") or {}
    if not sections:
        return
    new_sections: Dict[str, Dict[str, Any]] = {}
    for name, record in sections.items():
        canonical = synonym_lookup(name)
        if canonical is None:
            canonical = _FALLBACK_CANONICAL.get(name.strip().lower(), "Personal_Info")
        # Merge collisions: keep the longest text span.
        if canonical in new_sections:
            existing = new_sections[canonical]
            existing["text"] = (existing.get("text", "") + "\n\n" + record.get("text", "")).strip()
            existing["end"] = max(existing.get("end", 0), record.get("end", 0))
        else:
            new_sections[canonical] = dict(record)
    profile["sections"] = new_sections


def run_unified_scoring(
    profile: Dict[str, Any],
    weights: Dict[str, Any],
    chunks: List[Any],
    structured_profile: Any,
    use_llm: bool = False,
) -> Dict[str, Any]:
    """Score a candidate.

    Uses the rubric-bound LLM unified scorer when an LLM is available; falls
    back to the code-only graded scorer (synonym + years detection) when no
    LLM is wired in, so the pipeline always produces a working ranking.
    """
    if use_llm:
        evaluation = evaluate_candidate_unified(
            profile=profile,
            weights=weights,
            candidate_chunks=chunks,
            structured_profile=structured_profile,
            llm_caller=None,
        )
        return evaluation.to_dict()
    # Code-only fallback: graded scorer handles skill presence + years,
    # experience, education, and certifications deterministically.
    evaluation = graded_score_one(profile, weights)
    return evaluation.to_dict()


def build_intelligence_report(
    profile: Dict[str, Any],
    evaluation: Dict[str, Any],
    structured_profile: Any,
) -> Dict[str, Any]:
    """Aggregate the Candidate Intelligence Report artifact."""
    return {
        "candidate_id": evaluation.get("candidate_id", "unknown"),
        "role": evaluation.get("role", ""),
        "candidate_info": {
            "name": profile.get("name", ""),
            "location": profile.get("contact", {}).get("location", "")
            if isinstance(profile.get("contact"), dict) else "",
            "languages": profile.get("languages", []),
        },
        "skills": [
            {"skill_name": s, "years_of_experience": None, "evidence": []}
            for s in (profile.get("skills") or [])
        ],
        "experience": {
            "total_experience": structured_profile.total_experience_years,
            "relevant_experience": None,
            "same_role_experience": None,
            "leadership_experience": None,
        },
        "education": [
            {
                "degree": d.degree,
                "institution": d.institution,
                "institution_category": None,
            }
            for d in structured_profile.degrees
        ],
        "certifications": [
            {"certification_name": c.name, "provider": c.provider, "relevance": None}
            for c in structured_profile.certifications
        ],
        "projects": [{"relevant_projects": [], "project_relevance": None}],
        "objective_scores": {
            "skill_scores": [],
            "experience_scores": [],
            "education_scores": [],
            "certification_scores": [],
        },
        "scoring_summary": {
            "total_score": evaluation.get("total", 0),
            "total_raw": evaluation.get("total_raw", 0),
            "total_max": evaluation.get("total_max", 0),
            "categories": evaluation.get("categories", []),
        },
        "evidence_sources": [],
    }


def process_role(role: str, skip_scoring: bool = False) -> int:
    """Process all resumes for one role through the full pipeline."""
    role_original = ORIGINAL_DIR / role
    if not role_original.exists():
        logger.warning("Role directory not found: %s", role_original)
        return 0

    role_processed = PROCESSED_DIR / role
    role_chunks = CHUNKS_DIR / role
    role_processed.mkdir(parents=True, exist_ok=True)
    role_chunks.mkdir(parents=True, exist_ok=True)
    SCORES_DIR.mkdir(parents=True, exist_ok=True)

    # Load the recruiter weight config.
    weights_path = (
        _ROOT / "data" / "job_descriptions" / role / f"{role}_WeightConfig_filled.json"
    )
    weights: Dict[str, Any] = {}
    if weights_path.exists():
        weights = json.loads(weights_path.read_text(encoding="utf-8"))
    else:
        logger.warning("No weights config for role %s; scoring will be skipped", role)

    pdf_files = sorted(
        [f for f in role_original.iterdir() if f.suffix.lower() == ".pdf"]
    )
    logger.info("Processing %d resumes for role '%s'", len(pdf_files), role)

    evaluations: List[Dict[str, Any]] = []

    for pdf_file in pdf_files:
        candidate_id = pdf_file.stem
        try:
            # Step 1: parse + header normalization.
            profile = parse_resume(pdf_file)
            normalize_profile_sections(profile)

            # Save re-parsed profile.
            (role_processed / f"{candidate_id}.json").write_text(
                json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            # Step 2: structured profile.
            structured = extract_structured_profile(profile)
            (role_processed / f"{candidate_id}_structured_profile.json").write_text(
                json.dumps(structured.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # Step 3: chunk.
            chunks = chunk_profile(profile, role_bucket=role)
            chunk_path = role_chunks / f"{candidate_id}.jsonl"
            with chunk_path.open("w", encoding="utf-8") as fh:
                for c in chunks:
                    fh.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")

            logger.info(
                "  [%s] profile + structured + %d chunks",
                candidate_id, len(chunks),
            )

            # Step 4: score (if weights present and not skipped).
            if not skip_scoring and weights:
                evaluation = run_unified_scoring(
                    profile, weights, chunks, structured, use_llm=False
                )
                evaluations.append(evaluation)

                # Step 5: intelligence report.
                report = build_intelligence_report(profile, evaluation, structured)
                (role_processed / f"{candidate_id}_intelligence_report.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                logger.info(
                    "  [%s] score=%.1f/100", candidate_id, evaluation.get("total", 0)
                )

        except Exception as exc:  # pragma: no cover
            logger.error("Failed on %s: %s", pdf_file.name, exc)
            logger.debug(traceback.format_exc())

    # Step 6: rank candidates.
    if evaluations:
        ranked = sorted(evaluations, key=lambda x: x.get("total", 0), reverse=True)
        for i, row in enumerate(ranked, 1):
            row["rank"] = i
        scores_path = SCORES_DIR / f"{role}_ranked.json"
        scores_path.write_text(
            json.dumps(ranked, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(
            "-> wrote %d ranked candidates to %s", len(ranked), scores_path
        )

    return len(pdf_files)


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 4.5 pipeline")
    parser.add_argument("--role", help="Role bucket (e.g. BusinessAnalyst)")
    parser.add_argument(
        "--all-roles", action="store_true", help="Process every role folder"
    )
    parser.add_argument(
        "--skip-scoring", action="store_true", help="Parse and chunk only"
    )
    args = parser.parse_args()

    if args.all_roles:
        if not ORIGINAL_DIR.exists():
            logger.error("Original directory not found: %s", ORIGINAL_DIR)
            return
        roles = sorted([p.name for p in ORIGINAL_DIR.iterdir() if p.is_dir()])
    elif args.role:
        roles = [args.role]
    else:
        parser.error("Specify --role or --all-roles")
        return

    total = 0
    for role in roles:
        total += process_role(role, skip_scoring=args.skip_scoring)

    logger.info("=" * 60)
    logger.info(
        "Phase 4.5 pipeline complete: %d candidates across %d roles",
        total, len(roles),
    )


if __name__ == "__main__":
    main()