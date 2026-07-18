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
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from concurrent.futures import ThreadPoolExecutor, as_completed

# Make the local recruiter/src package importable
_LOCAL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_LOCAL_DIR))

from src.rag.per_req_retrieval import DEFAULT_EMBEDDING_MODEL
from src.rag.recursive_chunker import RECURSIVE_CHUNK_OVERLAP, RECURSIVE_CHUNK_SIZE
from src.rag.retriever import (
    DEFAULT_INDEX_PATH,
    DEFAULT_MAX_CHUNKS_PER_QUERY,
    DEFAULT_THRESHOLD,
    ThresholdRetriever,
    VectorIndex,
)
from src.rag.subquery_cache import SubQueryCache
from src.resume_parsing.structured_profile import (
    extract_structured_profile,
)
from src.scoring.unified_scorer import (
    ComposedCandidateEvaluation,
    evaluate_candidate_composed,
)
from src.services.llm_caller import get_rubric_caller
# No MLflow imports needed (M0.5c/mlflow removed per instruction)
from src.services.subquery_parser import get_all_role_subqueries

logger = logging.getLogger("score_batch_composed")

# Canonical corpus paths. The weight config filename pattern is
# ``<role>_WeightConfig_<name>.json`` in ``data/job_descriptions/<role>/``;
# we discover it via glob so the CLI is robust to future config renames.
RECRUITER_INDEX_PATH = "recruiter/data/embeddings/index.npz"
PROCESSED_DIR = Path("recruiter/data/processed")
JOB_DESCRIPTIONS_DIR = Path("recruiter/data/job_descriptions")
DEFAULT_OUTPUT_DIR = Path("recruiter/data/scores/composed")

# Files to skip during candidate iteration. The Document-Aware index
# originally produced these as downstream artifacts; they are not parses
# themselves and must not appear in the candidate count.
DOWNSTREAM_SUFFIXES = ("_intelligence_report.json", "_structured_profile.json")

# ---------------------------------------------------------------------------
# Progress ledger helpers & loading wrapper for --resume
# ---------------------------------------------------------------------------

PROGRESS_FILE = Path("recruiter/data/scoring_progress.json")

class LoadedComposedEvaluation:
    """Wrapper that duck-types ComposedCandidateEvaluation for resume-on-disk loads."""
    def __init__(self, data: dict) -> None:
        self._data = data
        self.candidate_id = data["candidate_id"]
        self.role = data.get("role", "")
        self.total = data["total"]
        
    @property
    def zero_evidence_reqs(self) -> list[dict]:
        return [
            r for r in self._data.get("reqs", [])
            if r.get("rubric_sq_scores")
            and r.get("rubric_llm_part") == 0.0
            and not r.get("blocked")
            and not r.get("rubric_skipped")
        ]
        
    @property
    def reqs(self) -> list[Any]:
        class DictWrapper:
            def __init__(self, d: dict) -> None:
                self.requirement_name = d.get("requirement_name")
                self.requirement_id = d.get("requirement_id", "")
                self.category = d.get("category", "")
                self.weight_percentage = d.get("weight_percentage", 0.0)
                self.code_only_sq_scores = d.get("code_only_sq_scores", {})
                self.rubric_sq_scores = d.get("rubric_sq_scores", {})
                self.code_only_part = d.get("code_only_part", 1.0)
                self.rubric_llm_part = d.get("rubric_llm_part", 1.0)
                self.sub_score = d.get("sub_score", 0.0)
                self.contribution = d.get("contribution", 0.0)
                self.rubric_skipped = d.get("rubric_skipped", False)
                self.blocked = d.get("blocked", False)
                self.blocked_reason = d.get("blocked_reason", "")
                self.retrieved_chunks = d.get("retrieved_chunks", [])
                
                trace = d.get("rubric_trace")
                if trace:
                    class TraceWrapper:
                        def __init__(self, t: dict) -> None:
                            self.sub_scores = [
                                type("SubScore", (), {
                                    "sub_score": ss.get("sub_score", 0.0),
                                    "evidence_found": ss.get("evidence_found", False),
                                    "key": ss.get("key", ""),
                                    "closest_evidence": ss.get("closest_evidence", "")
                                })()
                                for ss in t.get("sub_scores", [])
                            ]
                    self.rubric_trace = TraceWrapper(trace)
                else:
                    self.rubric_trace = None
        return [DictWrapper(r) for r in self._data.get("reqs", [])]
        
    def to_dict(self) -> dict:
        return self._data

def load_progress() -> dict:
    """Load the progress ledger, or return a fresh empty ledger."""
    if PROGRESS_FILE.exists():
        try:
            with PROGRESS_FILE.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as exc:
            logger.warning("Failed to load progress ledger from %s: %s. Starting fresh.", PROGRESS_FILE, exc)
    return {"completed_roles": [], "scored_candidates": {}}

_PROGRESS_LOCK = threading.Lock()

def save_progress(progress: dict) -> None:
    """Atomically write the progress ledger to disk."""
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = PROGRESS_FILE.with_suffix(".tmp")
    with _PROGRESS_LOCK:
        try:
            with tmp_path.open("w", encoding="utf-8") as fh:
                json.dump(progress, fh, indent=2)
            if PROGRESS_FILE.exists():
                try:
                    PROGRESS_FILE.unlink()
                except Exception:
                    pass
            tmp_path.replace(PROGRESS_FILE)
        except Exception as exc:
            logger.error("Failed to save progress ledger: %s", exc)


def is_role_complete(progress: dict, role: str) -> bool:
    """Return True if the role is marked complete in progress."""
    return role in progress.get("completed_roles", [])

def is_candidate_scored(progress: dict, role: str, candidate_id: str) -> bool:
    """Return True if candidate_id has been scored for role."""
    return candidate_id in progress.get("scored_candidates", {}).get(role, [])

def mark_candidate_done(progress: dict, role: str, candidate_id: str) -> None:
    """Record candidate_id as completed in ledger and flush to disk."""
    if "scored_candidates" not in progress:
        progress["scored_candidates"] = {}
    if role not in progress["scored_candidates"]:
        progress["scored_candidates"][role] = []
    if candidate_id not in progress["scored_candidates"][role]:
        progress["scored_candidates"][role].append(candidate_id)
        progress["last_updated"] = datetime.now().isoformat()
        save_progress(progress)

def mark_role_done(progress: dict, role: str) -> None:
    """Record role as completed in ledger and flush to disk."""
    if "completed_roles" not in progress:
        progress["completed_roles"] = []
    if role not in progress["completed_roles"]:
        progress["completed_roles"].append(role)
        progress["last_updated"] = datetime.now().isoformat()
        save_progress(progress)


# ---------------------------------------------------------------------------
# Discovery helpers.
# ---------------------------------------------------------------------------


def discover_roles() -> list[str]:
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


def iter_candidate_files(role: str, limit: int | None = None) -> list[Path]:
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
    retriever: VectorIndex,
    cache: SubQueryCache,
    llm_caller: Any | None,
    role_subqueries: dict[str, Any] | None = None,
    top_k: int = 10,
    threshold: float = DEFAULT_THRESHOLD,
    max_chunks_per_query: int | None = None,
    limit: int | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    progress: dict | None = None,
    resume: bool = False,
    n_workers: int | None = None,
    candidate_workers: int | None = None,
) -> dict[str, Any]:
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

    chunker_id = f"DocumentAware(BGE-base-en-v1.5, top_k={top_k})"

    candidate_files = iter_candidate_files(role, limit=limit)
    if not candidate_files:
        logger.warning("[%s] no candidate files found under %s", role, PROCESSED_DIR / role)
        return {
            "role": role,
            "weight_config_path": str(weight_config_path),
            "theta": float(threshold),
            "max_chunks_per_query": int(max_chunks_per_query) if max_chunks_per_query else DEFAULT_MAX_CHUNKS_PER_QUERY,
            "n_candidates": 0,
            "mean_score": 0.0,
            "top_5": [],
            "n_zero_evidence_reqs": 0,
            "time_seconds": time.time() - t_start,
            "output_path": None,
        }

    evaluations: list[Any] = []
    n_zero_evidence = 0
    diagnostic_lines: list[str] = []
    
    per_cand_dir = output_dir / role
    per_cand_dir.mkdir(parents=True, exist_ok=True)
    
    def process_cand_file(f):
        candidate_id = f.stem
        
        # --- RESUME: skip already-scored candidates ---
        if resume and progress and is_candidate_scored(progress, role, candidate_id):
            scored_file = per_cand_dir / f"{candidate_id}.json"
            if scored_file.exists():
                try:
                    with scored_file.open("r", encoding="utf-8") as fh:
                        eval_data = json.load(fh)
                    eval_result = LoadedComposedEvaluation(eval_data)
                    logger.info("[%s] Loaded scored candidate %s from disk (resume)", role, candidate_id)
                    return eval_result, "loaded"
                except Exception as exc:
                    logger.warning("[%s] Failed to load saved candidate %s: %s. Re-scoring.", role, candidate_id, exc)

        try:
            with f.open(encoding="utf-8") as fh:
                profile = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("[%s] skipping malformed candidate file %s: %s", role, f.name, exc)
            return None, "failed"
            
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
            top_k=top_k,
            threshold=threshold,
            max_chunks_per_query=max_chunks_per_query,
            chunker_id=chunker_id,
            sq_embedder=cached_embedder,
            n_workers=effective_req_workers,
        )
        
        # Write per-candidate JSON immediately
        try:
            with (per_cand_dir / f"{candidate_id}.json").open("w", encoding="utf-8") as fh:
                json.dump(eval_result.to_dict(), fh, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.error("[%s] Failed to write candidate JSON for %s: %s", role, candidate_id, exc)

        # Mark candidate done in progress ledger
        if progress is not None:
            mark_candidate_done(progress, role, candidate_id)
            
        return eval_result, "scored"

    # Set default concurrency levels
    n_reqs = len(weights.get("requirements_weights", []))
    effective_candidate_workers = 10
    effective_req_workers = n_reqs

    from src.services.llm_caller import RateLimitException

    remaining_candidates = list(candidate_files)
    completed_evals = []
    level_retries = 2

    # Level 1 Execution
    level = 1
    logger.info("[%s] Concurrency Level 1: candidate_workers=%d, requirement_workers=%d", role, effective_candidate_workers, effective_req_workers)
    
    for attempt in range(level_retries + 1):
        if not remaining_candidates:
            break
        try:
            if len(remaining_candidates) > 1:
                with ThreadPoolExecutor(max_workers=min(len(remaining_candidates), effective_candidate_workers)) as pool:
                    futures = {
                        pool.submit(process_cand_file, f): f for f in remaining_candidates
                    }
                    
                    for future in as_completed(futures):
                        f = futures[future]
                        try:
                            eval_result, status = future.result()
                            if eval_result is not None:
                                completed_evals.append(eval_result)
                                n_zero_evidence += len(eval_result.zero_evidence_reqs)
                            remaining_candidates.remove(f)
                        except RateLimitException as rle:
                            logger.warning("[%s] RateLimitException caught in Concurrency Level 1: %s", role, rle)
                            # Cancel all pending futures in this pool
                            for fut in futures:
                                fut.cancel()
                            raise
            else:
                if remaining_candidates:
                    eval_result, status = process_cand_file(remaining_candidates[0])
                    if eval_result is not None:
                        completed_evals.append(eval_result)
                        n_zero_evidence += len(eval_result.zero_evidence_reqs)
                    remaining_candidates.clear()
            break  # Succeeded this level!
        except RateLimitException:
            if attempt < level_retries:
                logger.warning("[%s] Level 1 failed due to rate limit. Retry %d/%d after 30s sleep...", role, attempt + 1, level_retries)
                time.sleep(30.0)
            else:
                logger.warning("LOG LEVEL TRANSITION: Fallback from Concurrency Level 1 to Concurrency Level 2 (sequential candidate evaluation) due to persistent rate limits.")
                time.sleep(30.0)
                level = 2

    # Level 2 Execution (sequential candidate evaluation, full requirements)
    if level == 2 and remaining_candidates:
        effective_candidate_workers = 1
        effective_req_workers = n_reqs
        logger.info("[%s] Concurrency Level 2: sequential candidate execution (candidate_workers=1), requirement_workers=%d", role, effective_req_workers)
        
        for attempt in range(level_retries + 1):
            if not remaining_candidates:
                break
            try:
                for f in list(remaining_candidates):
                    eval_result, status = process_cand_file(f)
                    if eval_result is not None:
                        completed_evals.append(eval_result)
                        n_zero_evidence += len(eval_result.zero_evidence_reqs)
                    remaining_candidates.remove(f)
                break  # Succeeded Level 2!
            except RateLimitException as rle:
                if attempt < level_retries:
                    logger.warning("[%s] Level 2 failed due to rate limit. Retry %d/%d after 30s sleep...", role, attempt + 1, level_retries)
                    time.sleep(30.0)
                else:
                    logger.warning("[%s] RateLimitException caught in Concurrency Level 2 after all retries: %s", role, rle)
                    logger.warning("LOG LEVEL TRANSITION: Fallback from Concurrency Level 2 to Concurrency Level 3 (reduced requirement workers) due to persistent rate limits.")
                    time.sleep(30.0)
                    level = 3
                    break

    # Level 3 Execution (sequential candidate evaluation, 5 requirements)
    if level == 3 and remaining_candidates:
        effective_candidate_workers = 1
        effective_req_workers = 5
        logger.info("[%s] Concurrency Level 3: sequential candidate execution (candidate_workers=1), requirement_workers=%d", role, effective_req_workers)
        
        for attempt in range(level_retries + 1):
            if not remaining_candidates:
                break
            try:
                for f in list(remaining_candidates):
                    eval_result, status = process_cand_file(f)
                    if eval_result is not None:
                        completed_evals.append(eval_result)
                        n_zero_evidence += len(eval_result.zero_evidence_reqs)
                    remaining_candidates.remove(f)
                break  # Succeeded Level 3!
            except RateLimitException as rle:
                if attempt < level_retries:
                    logger.warning("[%s] Level 3 failed due to rate limit. Retry %d/%d after 30s sleep...", role, attempt + 1, level_retries)
                    time.sleep(30.0)
                else:
                    logger.warning("[%s] RateLimitException caught in Concurrency Level 3 after all retries: %s", role, rle)
                    logger.warning("LOG LEVEL TRANSITION: Fallback from Concurrency Level 3 to Concurrency Level 4 (minimal requirement workers) due to persistent rate limits.")
                    time.sleep(30.0)
                    level = 4
                    break

    # Level 4 Execution (sequential candidate evaluation, 1 requirement)
    if level == 4 and remaining_candidates:
        effective_candidate_workers = 1
        effective_req_workers = 1
        logger.info("[%s] Concurrency Level 4: sequential candidate execution (candidate_workers=1), requirement_workers=%d", role, effective_req_workers)
        
        for attempt in range(level_retries + 1):
            if not remaining_candidates:
                break
            try:
                for f in list(remaining_candidates):
                    eval_result, status = process_cand_file(f)
                    if eval_result is not None:
                        completed_evals.append(eval_result)
                        n_zero_evidence += len(eval_result.zero_evidence_reqs)
                    remaining_candidates.remove(f)
                break  # Succeeded Level 4!
            except RateLimitException as rle:
                if attempt < level_retries:
                    logger.warning("[%s] Level 4 failed due to rate limit. Retry %d/%d after 30s sleep...", role, attempt + 1, level_retries)
                    time.sleep(30.0)
                else:
                    logger.error("[%s] RateLimitException caught in Concurrency Level 4 after all retries: %s", role, rle)
                    logger.error("LOG LEVEL TRANSITION: Failure at Concurrency Level 4. Aborting scoring batch run.")
                    level = 5
                    break

    # Level 5 Execution (failure and abort)
    if level == 5:
        sys.stderr.write(
            "\n[ERROR] The number of parallel calls is being limited by the provider/server even at minimal settings.\n\n"
        )
        sys.stderr.flush()
        logger.error("The number of parallel calls is being limited by the provider/server even at minimal settings. Aborting batch run.")
        sys.exit(429)

    evaluations.extend(completed_evals)
            
    # Re-build diagnostic lines for ALL evaluations (including loaded ones)
    for eval_result in evaluations:
        for req in eval_result.reqs:
            if req.rubric_skipped or req.blocked or req.rubric_trace is None:
                # Skip: LLM never ran for this REQ — not a scoring quality issue.
                continue
            for ss in req.rubric_trace.sub_scores:
                if ss.sub_score > 0.0:
                    # Non-zero sub-score: no diagnostic needed.
                    continue
                tag = "ZERO_NO_EVIDENCE" if not ss.evidence_found else "ZERO_WRONG_INFERENCE"
                logger.debug(
                    "[%s] cand=%s | req=%s | sq=%s | evidence_found=%s | closest=%s",
                    tag,
                    eval_result.candidate_id,
                    req.requirement_name,
                    ss.key,
                    ss.evidence_found,
                    (ss.closest_evidence or "")[:120],
                )
                tag_padded = f"[{tag}]"
                tag_padded = f"{tag_padded:<24}"
                msg = "no matching text found" if tag == "ZERO_NO_EVIDENCE" else "text found but LLM did not infer"
                diagnostic_lines.append(
                    f"{tag_padded} {eval_result.candidate_id} {req.requirement_name} {ss.key} — {msg}"
                )

    # Write zero-score diagnostics to run_reports/
    if diagnostic_lines:
        run_reports_dir = Path("run_reports")
        run_reports_dir.mkdir(parents=True, exist_ok=True)
        diag_file = run_reports_dir / f"score_diagnostic_{role}.txt"
        with diag_file.open("w", encoding="utf-8") as df:
            df.write("\n".join(diagnostic_lines) + "\n")
        logger.info("[%s] Wrote %d zero-score diagnostics to %s", role, len(diagnostic_lines), diag_file)

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


def run_rag_evaluation(role: str, judge_model: str, output_dir: Path) -> None:
    """Run sample-based RAG correctness evaluation on the scored candidates for a role."""
    import os
    import random
    import re
    import time
    
    logger.info("=" * 70)
    logger.info("▶ Starting RAG Correctness Evaluation using Judge model: %s", judge_model)
    logger.info("=" * 70)
    ranked_file = output_dir / f"{role}_ranked.json"
    if not ranked_file.exists():
        logger.error("Ranked JSON file %s not found. Skipping RAG evaluation.", ranked_file)
        return
        
    try:
        with ranked_file.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        logger.error("Failed to load ranked file: %s", exc)
        return
        
    rankings = data.get("rankings", [])
    if not rankings:
        logger.info("No candidates scored for role '%s'. Skipping evaluation.", role)
        return
        
    # Sample up to 5 candidates (lightweight to avoid quota limits)
    sample_size = min(5, len(rankings))
    sampled_candidates = random.sample(rankings, sample_size)
    logger.info("Sampled %d candidates for RAG correctness audit.", sample_size)
    
    api_key = os.environ.get("RECRUITER_API_KEY")
    base_url = os.environ.get("RECRUITER_BASE_URL") or "https://openrouter.ai/api/v1"
    
    if not api_key:
        logger.warning("RECRUITER_API_KEY environment variable not set. Skipping RAG correctness evaluation.")
        return
        
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url)
    except Exception as exc:
        logger.error("Failed to initialize Judge LLM client: %s", exc)
        return

    context_relevance_scores = []
    faithfulness_scores = []
    answer_relevance_scores = []
    
    rate_limit_encountered = False

    def judge_call_with_retry(system_prompt: str, user_prompt: str, max_tokens: int) -> Optional[str]:
        nonlocal rate_limit_encountered
        import random
        max_retries = 4
        for attempt in range(max_retries + 1):
            try:
                resp = client.chat.completions.create(
                    model=judge_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    max_tokens=max_tokens,
                    temperature=0.0
                )
                return (resp.choices[0].message.content or "").strip()
            except Exception as e:
                err_text = str(e).lower()
                is_rate_limit = (
                    "rate limit" in err_text 
                    or "too many requests" in err_text 
                    or "429" in err_text 
                    or "quota" in err_text
                )
                if is_rate_limit:
                    rate_limit_encountered = True
                    if attempt < max_retries:
                        backoff = (4.0 + random.uniform(0.0, 2.0)) * (2 ** attempt)
                        logger.warning(
                            "⚖️ Judge LLM rate limited (429). Retrying in %.2fs (attempt %d/%d)...",
                            backoff, attempt + 1, max_retries
                        )
                        time.sleep(backoff)
                        continue
                
                # For non-rate limit errors or exhausted retries, log and return None
                logger.warning("⚖️ Judge LLM call failed: %s", e)
                if attempt < max_retries:
                    time.sleep(2.0)
                    continue
                return None

    # Evaluate a few requirements per candidate
    for cand in sampled_candidates:
        candidate_id = cand.get("candidate_id", "Unknown")
        reqs = cand.get("reqs", [])
        if not reqs:
            continue
            
        # Select up to 2 requirements
        selected_reqs = reqs[:2]
        for req in selected_reqs:
            req_name = req.get("requirement_name", "")
            trace = req.get("rubric_trace") or {}
            sub_scores = trace.get("sub_scores") or []
            
            retrieved_chunks = []
            for sq in sub_scores:
                evidence = sq.get("closest_evidence") or sq.get("cited_text") or ""
                if evidence and evidence.lower() != "none" and evidence.lower() != "unknown":
                    retrieved_chunks.append(evidence)
                    
            if not retrieved_chunks:
                continue
                
            retrieved_text = "\n---\n".join(retrieved_chunks)
            explanation = trace.get("justification") or req.get("blocked_reason") or ""
            if not explanation:
                explanation_parts = []
                for sq in sub_scores:
                    desc = sq.get("anchor_description")
                    if desc and desc != "none":
                        explanation_parts.append(f"{sq.get('question', '')}: {desc}")
                explanation = "; ".join(explanation_parts)
                
            if not explanation:
                continue
                
            # Select up to 2 sub-scores
            for sq in sub_scores[:2]:
                sub_query = sq.get("question", "")
                if not sub_query:
                    continue
                    
                # 1. Context Relevance (Precision)
                for chunk in retrieved_chunks[:1]:
                    prompt_cr = f"Analyze the sub-query: {sub_query}. Now read the retrieved text chunk: {chunk}. Does this chunk contain concrete evidence that directly helps in answering the sub-query? Answer strictly YES or NO."
                    cr_ans = judge_call_with_retry(
                        system_prompt="You are a strict evaluator for RAG context relevance. Answer strictly YES or NO.",
                        user_prompt=prompt_cr,
                        max_tokens=10
                    )
                    if cr_ans is not None:
                        is_relevant = 1.0 if "YES" in cr_ans.upper() else 0.0
                        context_relevance_scores.append(is_relevant)
                        
                # 2. Faithfulness
                prompt_f = (
                    f"Compare the scoring explanation: {explanation} against the raw source evidence text:\n"
                    f"```\n{retrieved_text}\n```\n\n"
                    f"Is every claim, qualification statement, or number of years mentioned in the explanation "
                    f"directly supported by the source evidence? Answer strictly YES or NO."
                )
                f_ans = judge_call_with_retry(
                    system_prompt="You are a strict evaluator for RAG faithfulness. Output YES if all claims in the explanation are grounded, or NO if there are any claims that are not grounded. Do not output anything else.",
                    user_prompt=prompt_f,
                    max_tokens=10
                )
                if f_ans is not None:
                    is_faithful = 1.0 if "YES" in f_ans.upper() else 0.0
                    faithfulness_scores.append(is_faithful)
                    
                # 3. Answer Relevance
                prompt_ar = f"Evaluate if the explanation: {explanation} directly and completely answers the question raised in the sub-query: {sub_query}. Rate the answer relevance from 0.0 (completely off-topic/evasive) to 1.0 (directly answers). Output only the numeric score."
                ar_ans = judge_call_with_retry(
                    system_prompt="You are a strict evaluator for RAG answer relevance. Output a single numeric rating from 0.0 to 1.0.",
                    user_prompt=prompt_ar,
                    max_tokens=10
                )
                if ar_ans is not None:
                    match = re.search(r"(\d+(\.\d+)?)", ar_ans)
                    if match:
                        answer_relevance_scores.append(float(match.group(1)))
                    else:
                        answer_relevance_scores.append(0.5)

    # Compute averages
    avg_cr = sum(context_relevance_scores) / len(context_relevance_scores) if context_relevance_scores else 0.0
    avg_f = sum(faithfulness_scores) / len(faithfulness_scores) if faithfulness_scores else 0.0
    avg_ar = sum(answer_relevance_scores) / len(answer_relevance_scores) if answer_relevance_scores else 0.0
    
    eval_results = {
        "role": role,
        "judge_model": judge_model,
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "metrics": {
            "context_relevance": round(avg_cr, 4),
            "faithfulness": round(avg_f, 4),
            "answer_relevance": round(avg_ar, 4)
        },
        "sample_size": sample_size
    }
    
    # If rate limit encountered, log recommendations banner
    if rate_limit_encountered:
        logger.warning("=" * 70)
        logger.warning("⚠️ RAG RETRIEVAL CORRECTNESS AUDIT ENCOUNTERED RATE LIMITS")
        logger.warning("-" * 70)
        logger.warning("The Judge LLM calls returned 429 Too Many Requests errors.")
        logger.warning("To resolve this and optimize throughput:")
        logger.warning("1. In the Recruiter Wizard UI, lower your Candidate Concurrency and Requirement Concurrency.")
        logger.warning("2. Or supply a paid/higher-tier API key with higher RPM limits.")
        logger.warning("=" * 70)
        
    eval_file = output_dir / f"{role}_rag_evaluation.json"
    try:
        eval_file.write_text(json.dumps(eval_results, indent=2), encoding="utf-8")
        logger.info("=" * 70)
        logger.info("📊 RAG RETRIEVAL CORRECTNESS EVALUATION SUMMARY:")
        logger.info("-" * 70)
        logger.info("1. Context Relevance (Precision): %.2f%% (Target: >= 75%%)", avg_cr * 100)
        logger.info("2. Faithfulness (Groundedness):   %.2f%% (Target: 100%%)", avg_f * 100)
        logger.info("3. Answer Relevance:              %.2f%% (Target: >= 90%%)", avg_ar * 100)
        logger.info("Saved evaluation results to %s", eval_file)
        logger.info("=" * 70)
    except Exception as exc:
        logger.error("Failed to save evaluation results: %s", exc)


# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# CLI entry point.
# ---------------------------------------------------------------------------


# A no-op context manager used when MLflow tracking is disabled. Returning
# a ``with run or _NullCtx():`` keeps the loop body uniform regardless of
# whether tracking is on, which avoids a fully duplicated code path.
class _NullCtx:
    """Trivial context manager that does nothing (used when MLflow is off)."""
    def __enter__(self) -> _NullCtx:
        return self
    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def _build_pipeline_params(args: argparse.Namespace) -> PipelineParams:
    """Construct the DEC-020 :class:`PipelineParams` from the CLI args.

    Args:
        args: The parsed argparse Namespace.

    Returns:
        PipelineParams populated with the chunker / retriever / LLM config
        actually used for this batch run.
    """
    llm_label = "off" if args.no_llm else "on"
    return PipelineParams(
        chunk_size=RECURSIVE_CHUNK_SIZE,
        chunk_overlap=RECURSIVE_CHUNK_OVERLAP,
        embedding_model=DEFAULT_EMBEDDING_MODEL,
        vector_store="npz",
        similarity="cosine",
        retrieval_mode="threshold",
        threshold=float(args.theta),
        top_k=int(args.max_chunks) if args.max_chunks else DEFAULT_MAX_CHUNKS_PER_QUERY,
        llm=llm_label,
    )


def _log_run_to_mlflow(
    run,
    summary: dict[str, Any],
    role: str,
    args: argparse.Namespace,
) -> None:
    """Log the per-role summary as MLflow params/metrics/artifacts after a run.

    The retrieval-quality metrics from DEC-020 (recall_at_theta, mrr, ndcg,
    faithfulness, etc.) are not computed by this CLI under the scoring-only
    path — they require the eval-set harness (M0.5b). When those numbers are
    unavailable the metrics are logged as ``0.0`` so every required key is
    present per the contract; a real evaluator will overwrite them.

    Args:
        run: An opened :class:`MLflowRun` instance.
        summary: Dict returned by :func:`score_role`.
        role: Role identifier (also used as the artifact tag).
        args: The parsed argparse Namespace (for param extraction).
    """
    params = _build_pipeline_params(args)
    run.log_pipeline_params(params)
    # Run-level rollups: useful for dashboards, not part of the DEC-020 metric
    # contract. Logged separately from the required retrieval metrics set.
    run.log_metric("n_candidates", float(summary["n_candidates"]))
    run.log_metric("mean_score", float(summary["mean_score"]))
    run.log_metric("n_zero_evidence_reqs", float(summary["n_zero_evidence_reqs"]))
    run.log_metric("time_seconds", float(summary["time_seconds"]))
    # DEC-020 contract metrics: populated with 0.0 here because the batch CLI
    # does not run the eval harness. Real evaluator runs (M0.5d) will overwrite
    # the same metric keys with measured values.
    run.log_retrieval_metrics(RetrievalMetrics())
    if summary.get("output_path") and Path(summary["output_path"]).exists():
        run.log_artifact(Path(summary["output_path"]))
    run.set_tag("weight_config_path", str(summary.get("weight_config_path", "")))


def main(argv: list[str] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Production batch scorer using the composed Mode1 × Mode2 scorer "
                    "(Track 7.4 / DEC-031).",
    )
    parser.add_argument(
        "--role", nargs="+", default=None, metavar="ROLE",
        help="One or more specific roles to run (default: all roles). Use role "
             "names as they appear in data/job_descriptions/, e.g. "
             "--role DataScience or --role SalesManager SQLDeveloper.",
    )
    parser.add_argument(
        "--top-k", type=int, default=10,
        help="Number of top-K chunks to return per sub-query (DEC-035 top-K retrieval). Default: 10.",
    )
    parser.add_argument(
        "--theta", type=float, default=DEFAULT_THRESHOLD,
        help=f"Cosine threshold (legacy, kept for backward compat). Default: {DEFAULT_THRESHOLD}.",
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
        "--index-path", default=RECRUITER_INDEX_PATH,
        help=f"Path to the VectorIndex .npz file (default: {RECRUITER_INDEX_PATH}).",
    )
    parser.add_argument(
        "--flush-cache", action="store_true",
        help="Flush the sub-query embedding cache to disk on exit. The next "
             "batch run is then cache-hot from the start.",
    )
    parser.add_argument(
        "--clean-output", action="store_true",
        help="Delete all existing score files in the output directory before "
             "scoring begins.  Gives a guaranteed clean slate so stale files "
             "from a previous broken run cannot pollute the results.  "
             "Ignored when --resume is also passed.",
    )
    parser.add_argument(
        "--clean-role", nargs="+", metavar="ROLE",
        help="Delete score files for specific role(s) before scoring begins, "
             "leaving all other roles untouched.  Accepts one or more role "
             "names (e.g. --clean-role JavaDeveloper ReactDeveloper).  "
             "Ignored when --resume is also passed.",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Resume a previously interrupted scoring run using progress ledger.",
    )
    parser.add_argument(
        "--workers", type=int, default=None,
        help="Number of REQs to evaluate in parallel per candidate "
             "(uses ThreadPoolExecutor). Defaults to the number of requirements. "
             "Set to 1 to force sequential execution (debug / rate-limit mode).",
    )
    parser.add_argument(
        "--candidate-workers", type=int, default=None,
        help="Number of candidates to evaluate in parallel (uses ThreadPoolExecutor). "
             "Defaults to 10. Set to 1 to force sequential execution.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logger output.",
    )
    parser.add_argument(
        "--judge-model", default=None,
        help="Model slug to use as the Judge LLM (e.g. google/gemini-3.1-pro) "
             "for running sample-based RAG correctness evaluation.",
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
        roles = args.role  # already a list from nargs="+"
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
    # 3. Load the DocumentAware embedding index (DEC-035).
    # ---------------------------------------------------------------
    if not Path(args.index_path).exists():
        logger.error(
            "DocumentAware embedding index not found at %s — run "
            "`python recruiter/build_index.py` first.",
            args.index_path,
        )
        return 3
    logger.info("Loading DocumentAware index from %s ...", args.index_path)
    index_load_start = time.time()
    index = VectorIndex.load_npz(args.index_path)
    logger.info(
        "Index loaded in %.2fs (%d chunks).",
        time.time() - index_load_start, len(index.chunk_ids),
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
    # (MLflow tracking setup removed)

    # Initialize progress ledger
    progress = None
    if args.resume:
        progress = load_progress()
        logger.info("Resuming scoring batch run. Loaded progress ledger with %d completed roles.", len(progress.get("completed_roles", [])))
    else:
        if PROGRESS_FILE.exists():
            try:
                PROGRESS_FILE.unlink()
                logger.info("Fresh run: Deleted old progress ledger at %s.", PROGRESS_FILE)
            except Exception as exc:
                logger.warning("Failed to delete old progress ledger: %s", exc)
        progress = {"completed_roles": [], "scored_candidates": {}}

        # --clean-output: wipe all existing score files.
        if getattr(args, "clean_output", False):
            import shutil
            clean_dir = Path(args.output_dir)
            if clean_dir.exists():
                logger.info(
                    "--clean-output: removing all existing score files under %s",
                    clean_dir,
                )
                for child in clean_dir.iterdir():
                    try:
                        if child.is_dir():
                            shutil.rmtree(child)
                        else:
                            child.unlink()
                    except Exception as exc:
                        logger.warning("Failed to remove %s: %s", child, exc)
                logger.info("--clean-output: output directory cleared.")

        # --clean-role: delete score files for specific roles only.
        clean_roles = getattr(args, "clean_role", None) or []
        if clean_roles:
            import shutil
            out_base = Path(args.output_dir)
            for role_name in clean_roles:
                role_dir = out_base / role_name
                if role_dir.exists():
                    try:
                        shutil.rmtree(role_dir)
                        logger.info("--clean-role: deleted score dir %s", role_dir)
                    except Exception as exc:
                        logger.warning("--clean-role: failed to remove %s: %s", role_dir, exc)
                else:
                    logger.info("--clean-role: %s not found, nothing to delete.", role_dir)

                # Always delete the stale ranked file — unconditionally, regardless
                # of whether the score subdirectory existed. This prevents the
                # evaluator from reading stale ranked data after a flush.
                ranked_file = out_base / f"{role_name}_ranked.json"
                if ranked_file.exists():
                    try:
                        ranked_file.unlink()
                        logger.info("--clean-role: deleted stale ranked file %s", ranked_file)
                    except Exception as exc:
                        logger.warning("--clean-role: failed to remove ranked file %s: %s", ranked_file, exc)
                else:
                    logger.info("--clean-role: no ranked file found for %s (already clean).", role_name)


    for role in roles:
        # Check if role is already completed in ledger
        if args.resume and is_role_complete(progress, role):
            logger.info("Role '%s' already fully completed. Skipping.", role)
            ranked_file = output_dir / f"{role}_ranked.json"
            if ranked_file.exists():
                try:
                    with ranked_file.open("r", encoding="utf-8") as fh:
                        summaries.append(json.load(fh))
                    continue
                except Exception as exc:
                    logger.warning("Failed to load completed roleranked JSON for '%s': %s. Re-scoring.", role, exc)
            else:
                logger.warning("Role ranked JSON not found for completed role '%s'. Re-scoring.", role)

        summary = score_role(
            role=role,
            retriever=index,
            cache=cache,
            llm_caller=llm_caller,
            role_subqueries=role_subqueries,
            top_k=args.top_k,
            threshold=float(args.theta),
            max_chunks_per_query=int(args.max_chunks) if args.max_chunks else None,
            limit=args.limit,
            output_dir=output_dir,
            progress=progress,
            resume=args.resume,
            n_workers=args.workers,
            candidate_workers=args.candidate_workers,
        )
        summaries.append(summary)
        
        # Mark role as fully done in ledger if all candidates for the role were scored
        if progress is not None and summary.get("n_candidates", 0) > 0:
            unlimited_files = len(iter_candidate_files(role, limit=None))
            if summary.get("n_candidates", 0) == unlimited_files:
                mark_role_done(progress, role)
            
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
    # ---------------------------------------------------------------
    # 8. Run RAG evaluation if requested
    # ---------------------------------------------------------------
    if args.judge_model:
        for s in summaries:
            if s.get("role"):
                run_rag_evaluation(s["role"], args.judge_model, output_dir)

    return 0


if __name__ == "__main__":
    sys.exit(main())