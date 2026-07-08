"""Production batch CLI using the composed Mode1 × Mode2 scorer (Track 7.4, DEC-031).

This is the canonical end-to-end runner that scores every candidate in every
role using the new composed scorer from Track 2-S
(:func:`src.scoring.unified_scorer.evaluate_candidate_composed`). It replaces
the legacy ``src/scoring/batch_score.py`` path (which delegated to
:func:`graded_scorer.evaluate_role` under the old ``scale_factor`` +
``DEFAULT_EXPECTED_YEARS`` regime).

The pipeline per role:

    1. Load the sub-query embedding cache (in-memory + on-disk at
       ``data/embeddings/subqueries_cache.npz``).
    2. Pre-encode the role's SubQuery file via
       :meth:`SubQueryCache.preencode_role` (~5 sec first time, instant on
       warm cache). Pass the resulting ``cached_embedder`` closure into the
       composed scorer as ``sq_embedder`` — eliminates the per-candidate
       redundant re-encoding that would otherwise cost ~12 minutes per role.
    3. Load the Recursive embedding index (``data/embeddings/recursive_chunking/
       index.npz``) and wrap it in a :class:`ThresholdRetriever` with the
       caller-supplied ``--theta``.
    4. Optionally load the LLM caller (``--no-llm`` skips rubric scoring;
       rubric contributions zero out, code-only path still runs).
    5. For each parsed-resume JSON under ``data/processed/<role>/*.json``
       (filtering out the ``_intelligence_report.json`` +
       ``_structured_profile.json`` downstream artifacts):
         * Load the parsed profile.
         * Call ``evaluate_candidate_composed`` with the cached embedder.
         * Collect the per-REQ ``ComposedREQResult`` + total score.
    6. Sort candidates by ``total_score`` desc, write the per-role ranking
       JSON to ``data/scores/composed/<role>_ranked.json``.
    7. Print per-role summary (top-5, mean, total candidates evaluated).
    8. On exit, optionally flush the sub-query cache to disk so the next
       batch run is cache-hot from the start (``--flush-cache``).

Usage examples::

    # Dry run on DataScience only (no LLM, no flush; fast smoke test).
    python scripts/score_batch_composed.py --role DataScience --no-llm

    # Full run on all 8 roles, with LLM, flush cache on exit.
    python scripts/score_batch_composed.py --flush-cache

    # Tune theta + cap.
    python scripts/score_batch_composed.py --role BusinessAnalyst --theta 0.40 --max-chunks 15
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Path setup so the script can be invoked as ``python scripts/score_batch_composed.py``
# without requiring ``pip install -e .``.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.rag.retriever import (
    DEFAULT_CHUNKS_PATH,
    DEFAULT_INDEX_PATH,
    DEFAULT_MAX_CHUNKS_PER_QUERY,
    DEFAULT_THRESHOLD,
    ThresholdRetriever,
    VectorIndex,
)
from src.rag.subquery_cache import SubQueryCache
from src.resume_parsing.structured_profile import (
    StructuredCandidateProfile,
    extract_structured_profile,
)
from src.scoring.unified_scorer import ComposedCandidateEvaluation, evaluate_candidate_composed
from src.services.llm_caller import LLMRubricCaller, get_rubric_caller
from src.services.subquery_parser import get_all_role_subqueries

logger = logging.getLogger("score_batch_composed")

# Canonical corpus paths. The weight config filename pattern is
# ``<role>_WeightConfig_<name>.json`` in ``data/job_descriptions/<role>/``;
# we discover it via glob so the CLI is robust to future config renames.
PROCESSED_DIR = Path("data/processed")
JOB_DESCRIPTIONS_DIR = Path("data/job_descriptions")
DEFAULT_OUTPUT_DIR = Path("data/scores/composed")

# Files to skip during candidate iteration. The Document-Aware index
# originally produced these as downstream artifacts; they are not parses
# themselves and must not appear in the candidate count.
DOWNSTREAM_SUFFIXES = ("_intelligence_report.json", "_structured_profile.json")


# ---------------------------------------------------------------------------
# Discovery helpers.
# ---------------------------------------------------------------------------


def discover_roles() -> List[str]:
    """Return the sorted list of role-folders with both a SubQuery + WeightConfig."""
    roles = []
    for d in sorted(JOB_DESCRIPTIONS_DIR.iterdir()):
        if not d.is_dir():
            continue
        has_subq = (d / f"{d.name}_SubQuery.md").exists()
        has_weights = any(
            fn.name.startswith(f"{d.name}_WeightConfig_") and fn.suffix == ".json"
            for fn in d.iterdir() if fn.is_file()
        )
        if has_subq and has_weights:
            roles.append(d.name)
    return roles


def find_weight_config(role: str) -> Path:
    """Return the weight-config JSON path for the role.

    If multiple weight configs exist for the same role, the first (alphabetical)
    is returned. Production callers should pass ``--weight-config`` to choose a
    non-default config for a role.
    """
    role_dir = JOB_DESCRIPTIONS_DIR / role
    candidates = sorted(role_dir.glob(f"{role}_WeightConfig_*.json"))
    if not candidates:
        raise FileNotFoundError(f"No weight config found for role '{role}' in {role_dir}")
    return candidates[0]


def iter_candidate_files(role: str, limit: Optional[int] = None) -> List[Path]:
    """Yield parsed-resume JSON paths for ``role``, excluding downstream artifacts."""
    role_dir = PROCESSED_DIR / role
    if not role_dir.exists():
        return []
    out = []
    for f in sorted(role_dir.glob("*.json")):
        # Skip the downstream ``_intelligence_report.json`` +
        # ``_structured_profile.json`` artifacts — only the raw parse feeds
        # the chunker (matches ``src/rag/build_index.py``'s filter).
        if any(f.name.endswith(suf) for suf in DOWNSTREAM_SUFFIXES):
            continue
        out.append(f)
        if limit is not None and len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Per-role scoring loop.
# ---------------------------------------------------------------------------


def score_role(
    role: str,
    retriever: ThresholdRetriever,
    cache: SubQueryCache,
    llm_caller: Optional[Any],
    role_subqueries: Optional[Dict[str, Any]] = None,
    threshold: float = DEFAULT_THRESHOLD,
    max_chunks_per_query: Optional[int] = None,
    limit: Optional[int] = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> Dict[str, Any]:
    """Score every candidate in ``role`` and write the ranking JSON.

    Returns:
        A summary dict with ``role``, ``n_candidates``, ``mean_score``,
        ``top_5``, ``time_seconds``, ``output_path``, ``n_zero_evidence``.
    """
    t_start = time.time()
    weight_config_path = find_weight_config(role)
    with weight_config_path.open(encoding="utf-8") as fh:
        weights = json.load(fh)

    # Pre-encode this role's sub-queries if not already cached. The
    # cache wraps ``embed_sub_queries``; calling ``preencode_role`` once
    # at the start of the role loop warms the cache so the per-candidate
    # ``sq_embedder`` closure only does in-memory lookups for the rest of
    # the run.
    n_new_sq_entries = cache.preencode_role(role)
    if n_new_sq_entries > 0:
        logger.info("[%s] pre-encoded %d new sub-query entries", role, n_new_sq_entries)
    cached_embedder = cache.wrap_embed_sub_queries()

    # Lazy-load the SubQuery doc if the caller didn't supply it.
    if role_subqueries is None:
        role_subqueries = get_all_role_subqueries()

    chunker_id = (
        f"Recursive(chunk_size={getattr(retriever, 'chunk_size', 500)}, "
        f"chunk_overlap={getattr(retriever, 'chunk_overlap', 100)})"
    )

    candidate_files = iter_candidate_files(role, limit=limit)
    if not candidate_files:
        logger.warning("[%s] no candidate files found under %s", role, PROCESSED_DIR / role)
        return {
            "role": role,
            "n_candidates": 0,
            "mean_score": 0.0,
            "top_5": [],
            "time_seconds": time.time() - t_start,
            "output_path": None,
            "n_zero_evidence": 0,
            "weight_config_path": str(weight_config_path),
        }

    evaluations: List[ComposedCandidateEvaluation] = []
    n_zero_evidence = 0
    for f in candidate_files:
        try:
            with f.open(encoding="utf-8") as fh:
                profile = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("[%s] skipping malformed candidate file %s: %s", role, f.name, exc)
            continue
        # Re-extract the structured profile (Track 7.2 inferred-full-year
        # logic is in ``extract_structured_profile`` so we use the freshest
        # record, not the on-disk snapshot which may predate the fix).
        structured = extract_structured_profile(profile)
        eval_result = evaluate_candidate_composed(
            profile=profile,
            weights=weights,
            retriever=retriever,
            structured_profile=structured,
            llm_caller=llm_caller,
            role_subqueries=role_subqueries,
            role_name=role,
            threshold=threshold,
            max_chunks_per_query=max_chunks_per_query,
            chunker_id=chunker_id,
            sq_embedder=cached_embedder,
        )
        evaluations.append(eval_result)
        # Use the dataclass's own ``zero_evidence_reqs`` property which
        # canonicalizes the count (REQs where the rubric LLM was called
        # but got zero chunks, excluding blocked REQs which are counted
        # separately via ``blocked_reqs``).
        n_zero_evidence += len(eval_result.zero_evidence_reqs)

    # Sort by total score desc.
    evaluations.sort(key=lambda e: e.total, reverse=True)

    # Serialize: per-candidate summary + full per-REQ breakdown. Use the
    # ``to_dict()`` snapshots the dataclasses already provide so the JSON
    # schema stays identical to the in-memory representation.
    ranked = [
        {
            "rank": i + 1,
            **e.to_dict(),
        }
        for i, e in enumerate(evaluations)
    ]

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{role}_ranked.json"
    summary = {
        "role": role,
        "weight_config_path": str(weight_config_path),
        "theta": float(threshold),
        "max_chunks_per_query": int(max_chunks_per_query) if max_chunks_per_query else DEFAULT_MAX_CHUNKS_PER_QUERY,
        "n_candidates": len(evaluations),
        "mean_score": round(sum(e.total for e in evaluations) / max(1, len(evaluations)), 4),
        "top_5": [
            {
                "rank": i + 1,
                "candidate_id": e.candidate_id,
                "total": round(e.total, 4),
            }
            for i, e in enumerate(evaluations[:5])
        ],
        "n_zero_evidence_reqs": n_zero_evidence,
        "time_seconds": round(time.time() - t_start, 2),
        "output_path": str(output_path),
        "rankings": ranked,
    }
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)

    return summary


# ---------------------------------------------------------------------------
# CLI entry point.
# ---------------------------------------------------------------------------


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Production batch scorer using the composed Mode1 × Mode2 scorer "
                    "(Track 7.4 / DEC-031).",
    )
    parser.add_argument(
        "--role", default=None,
        help="Specific role to run (default: all 8). Use a role name as it appears "
             "in data/job_descriptions/, e.g. 'DataScience'.",
    )
    parser.add_argument(
        "--theta", type=float, default=DEFAULT_THRESHOLD,
        help=f"Cosine threshold for retrieval (default: {DEFAULT_THRESHOLD}; "
             f"Optuna bounds [0.10, 0.50]).",
    )
    parser.add_argument(
        "--max-chunks", type=int, default=None,
        help=f"Cap on unioned chunks per REQ. Default uses the retriever's own "
             f"cap ({DEFAULT_MAX_CHUNKS_PER_QUERY}).",
    )
    parser.add_argument(
        "--no-llm", action="store_true",
        help="Skip rubric-bound LLM scoring. Rubric contributions = 0; code-only "
             "path still runs. Fast smoke test.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Limit per-role candidate count (useful for smoke tests).",
    )
    parser.add_argument(
        "--output-dir", default=str(DEFAULT_OUTPUT_DIR),
        help=f"Output directory for ``<role>_ranked.json`` (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--flush-cache", action="store_true",
        help="Flush the sub-query embedding cache to disk on exit. The next "
             "batch run is then cache-hot from the start.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logger output.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    )

    # ---------------------------------------------------------------
    # 1. Resolve roles.
    # ---------------------------------------------------------------
    if args.role:
        roles = [args.role]
    else:
        roles = discover_roles()
    if not roles:
        logger.error("No roles with both a SubQuery file and a weight config found.")
        return 2
    logger.info("Roles to score: %s", roles)

    # ---------------------------------------------------------------
    # 2. Load the sub-query embedding cache.
    # ---------------------------------------------------------------
    cache = SubQueryCache.load()
    logger.info(
        "Sub-query cache loaded with %d pre-encoded entries.", len(cache),
    )

    # ---------------------------------------------------------------
    # 3. Load the retriever from the on-disk Recursive index.
    # ---------------------------------------------------------------
    if not Path(DEFAULT_INDEX_PATH).exists():
        logger.error(
            "Recursive embedding index not found at %s — run "
            "`python -m src.rag.build_index` first.",
            DEFAULT_INDEX_PATH,
        )
        return 3
    logger.info("Loading Recursive embedding index from %s ...", DEFAULT_INDEX_PATH)
    index_load_start = time.time()
    index = VectorIndex.load_npz(DEFAULT_INDEX_PATH)
    retriever = ThresholdRetriever(
        index=index,
        threshold=float(args.theta),
        max_chunks_per_query=int(args.max_chunks) if args.max_chunks else DEFAULT_MAX_CHUNKS_PER_QUERY,
    )
    logger.info(
        "Index loaded in %.2fs (%d chunks, theta=%.3f).",
        time.time() - index_load_start, len(index.chunk_ids), retriever.threshold,
    )

    # ---------------------------------------------------------------
    # 4. LLM caller (unless --no-llm).
    # ---------------------------------------------------------------
    llm_caller = None
    if not args.no_llm:
        llm_caller = get_rubric_caller()
        # ``_available`` reflects whether the API client initialized
        # successfully (env API key present + SDK installed). When False,
        # the caller returns empty strings — the rubric scorer produces
        # ``normalized_score = 0.0`` for every REQ.
        if not getattr(llm_caller, "_available", False):
            logger.warning(
                "LLM caller is not available. Rubric contributions will be 0. "
                "Pass --no-llm to silence this warning."
            )
    else:
        logger.info("Rubric LLM skipped (--no-llm); rubric contributions = 0.")

    # Pre-load the SubQuery doc once so we don't re-parse for every
    # candidate. The dict is keyed by role.
    role_subqueries = get_all_role_subqueries()

    # ---------------------------------------------------------------
    # 5. Per-role scoring loop.
    # ---------------------------------------------------------------
    output_dir = Path(args.output_dir)
    t_total_start = time.time()
    summaries = []
    for role in roles:
        logger.info("=" * 70)
        logger.info("Scoring role: %s", role)
        summary = score_role(
            role=role,
            retriever=retriever,
            cache=cache,
            llm_caller=llm_caller,
            role_subqueries=role_subqueries,
            threshold=float(args.theta),
            max_chunks_per_query=int(args.max_chunks) if args.max_chunks else None,
            limit=args.limit,
            output_dir=output_dir,
        )
        summaries.append(summary)
        logger.info(
            "[%s] scored %d candidates in %.2fs (mean=%.2f; top-1 score=%.2f); "
            "ranked → %s",
            role, summary["n_candidates"], summary["time_seconds"],
            summary["mean_score"],
            summary["top_5"][0]["total"] if summary["top_5"] else 0.0,
            summary["output_path"] or "(no output)",
        )

    # ---------------------------------------------------------------
    # 6. Optional: flush the sub-query cache to disk.
    # ---------------------------------------------------------------
    if args.flush_cache:
        cache.flush()
        logger.info("Sub-query cache flushed to disk (%d entries).", len(cache))
    elif cache.is_dirty:
        logger.info(
            "Sub-query cache has %d new entries but was not flushed "
            "(pass --flush-cache to persist).",
            cache.size,
        )

    # ---------------------------------------------------------------
    # 7. Aggregate summary print.
    # ---------------------------------------------------------------
    logger.info("=" * 70)
    logger.info("Batch scoring complete in %.2fs. Per-role summary:", time.time() - t_total_start)
    print()
    print(f"{'Role':25s}  {'N':>5s}  {'Mean':>7s}  {'Top-1':>7s}  {'0-Evid':>7s}  Output")
    print("-" * 100)
    for s in summaries:
        top1 = s["top_5"][0]["total"] if s["top_5"] else 0.0
        out = Path(s["output_path"]).name if s["output_path"] else "(none)"
        print(
            f"{s['role']:25s}  {s['n_candidates']:>5d}  {s['mean_score']:>7.2f}  "
            f"{top1:>7.2f}  {s['n_zero_evidence_reqs']:>7d}  {out}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())