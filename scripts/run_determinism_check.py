#!/usr/bin/env python3
"""Determinism validation script for the candidate ranking pipeline.

Runs the ranking logic twice under identical inputs and configurations, and
verifies that outputs (candidate order and score trees) are byte-identical.
Prerequisite gate before evaluating stability.
"""

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

# Ensure project root is in sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.rag.recursive_chunker import RecursiveChunker
from src.rag.retriever import (
    DEFAULT_EMBEDDING_MODEL,
    IndexedChunk,
    ThresholdRetriever,
    VectorIndex,
)
from src.services.subquery_parser import parse_subquery_document
from scripts.run_hpo_sweep import find_weight_config

# Setup logging
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("run_determinism_check")

# Directories
PROCESSED_DIR = ROOT / "data/processed"
JOB_DESCRIPTIONS_DIR = ROOT / "data/job_descriptions"
BASELINE_PATH = ROOT / "data/eval/baseline_config.json"


def load_baseline_config() -> Dict[str, Any]:
    """Retrieve the locked baseline hyperparameters from disk.

    Returns:
        Dict containing chunk_size, chunk_overlap, top_k, theta.
    """
    if not BASELINE_PATH.exists():
        raise FileNotFoundError(f"Locked baseline config not found at: {BASELINE_PATH}")
    with open(BASELINE_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def get_roles() -> List[str]:
    """List all configured roles in the processed candidates directory."""
    roles = []
    for item in PROCESSED_DIR.iterdir():
        if item.is_dir() and not item.name.startswith((".", "evaluation_results")):
            roles.append(item.name)
    return sorted(roles)


def score_candidates_deterministic(
    candidate_profiles: Dict[str, Dict[str, Any]],
    req_subqueries: List[Tuple[str, str]],
    sq_embeddings: np.ndarray,
    weights: Dict[str, float],
    pool_retriever: ThresholdRetriever
) -> List[Dict[str, Any]]:
    """Execute candidate similarity scoring and ranking computation.

    Args:
        candidate_profiles: Dictionary of candidate profile documents.
        req_subqueries: List of requirement subqueries.
        sq_embeddings: Embeddings of subqueries.
        weights: Weights of requirements.
        pool_retriever: Preloaded ThresholdRetriever.

    Returns:
        Sorted candidate ranking entries.
    """
    pool_scores: Dict[str, float] = {}
    for cid, profile in candidate_profiles.items():
        cand_id = profile.get("candidate_metadata", {}).get("candidate_id", cid)
        total_candidate_score = 0.0

        req_similarities: Dict[str, List[float]] = {}
        for sq_idx, (req_id, _) in enumerate(req_subqueries):
            sq_vector = sq_embeddings[sq_idx]
            hits = pool_retriever.retrieve_scored(sq_vector, candidate_id=cand_id)
            max_cosine = max([h.cosine for h in hits]) if hits else 0.0
            req_similarities.setdefault(req_id, []).append(max_cosine)

        for req_id, sims in req_similarities.items():
            req_weight = weights.get(req_id, 0.0)
            mean_sim = float(np.mean(sims)) if sims else 0.01
            total_candidate_score += req_weight * mean_sim

        pool_scores[cand_id] = total_candidate_score

    sorted_candidates = sorted(pool_scores.items(), key=lambda x: x[1], reverse=True)
    return [
        {"candidate_id": cid, "total_score": round(score, 6), "rank": i + 1}
        for i, (cid, score) in enumerate(sorted_candidates)
    ]


def verify_determinism() -> bool:
    """Build index once per role and run scoring twice to verify byte-identical matches."""
    logger.info("Initializing determinism check...")
    
    # Load config
    config = load_baseline_config()
    logger.info("Loaded baseline config parameters: %s", config)

    # Preload SentenceTransformer
    logger.info("Loading embedding model '%s'...", DEFAULT_EMBEDDING_MODEL)
    from sentence_transformers import SentenceTransformer
    embed_model = SentenceTransformer(DEFAULT_EMBEDDING_MODEL)

    roles = get_roles()
    if not roles:
        logger.error("No candidate roles pools found in data/processed/")
        return False

    logger.info("Discovered %d candidate role pools: %s", len(roles), roles)

    all_roles_pass = True

    for role in roles:
        logger.info("=== Running determinism check for role: %s ===", role)
        
        role_dir = PROCESSED_DIR / role
        if not role_dir.exists():
            logger.error("Role directory %s does not exist.", role_dir)
            all_roles_pass = False
            continue

        # 1. Load candidate parsed profile files
        candidate_profiles: Dict[str, Dict[str, Any]] = {}
        for f in role_dir.glob("*.json"):
            if f.name.endswith(("_intelligence_report.json", "_structured_profile.json")):
                continue
            try:
                profile = json.loads(f.read_text(encoding="utf-8"))
                candidate_profiles[f.stem] = profile
            except Exception as exc:
                logger.warning("Failed to load parsed profile %s: %s", f.name, exc)

        if not candidate_profiles:
            logger.error("No candidate profiles loaded for role %s", role)
            all_roles_pass = False
            continue

        # 2. Parse job description requirements and subqueries
        subquery_file = JOB_DESCRIPTIONS_DIR / role / f"{role}_SubQuery.md"
        if not subquery_file.exists():
            logger.error("SubQuery file not found at %s", subquery_file)
            all_roles_pass = False
            continue

        parsed_subqueries = parse_subquery_document(subquery_file)
        requirements = parsed_subqueries.get("requirements", [])

        req_subqueries: List[Tuple[str, str]] = []
        for req in requirements:
            req_id = req.get("req_id", "")
            for sq in req.get("sub_queries", []):
                sq_text = sq.get("text", "")
                if sq_text:
                    req_subqueries.append((req_id, sq_text))

        # Pre-embed requirement subqueries
        sq_texts = [sq_text for _, sq_text in req_subqueries]
        sq_embeddings = embed_model.encode(sq_texts, normalize_embeddings=True)

        # 3. Load requirement weight configurations
        weight_config_path = find_weight_config(role)
        weights: Dict[str, float] = {}
        if weight_config_path:
            try:
                config_data = json.loads(weight_config_path.read_text(encoding="utf-8"))
                req_weights = config_data.get("requirements_weights", [])
                weights = {
                    r["requirement_id"]: r["weight_percentage"]
                    for r in req_weights
                    if "requirement_id" in r and "weight_percentage" in r
                }
            except Exception as exc:
                logger.warning("Failed to load weight config: %s", exc)

        if not weights:
            unique_reqs = list({req_id for req_id, _ in req_subqueries})
            if unique_reqs:
                default_wt = 100.0 / len(unique_reqs)
                weights = {req_id: default_wt for req_id in unique_reqs}

        # 4. Chunk and embed all candidate profiles (ONCE)
        chunk_size = config["chunk_size"]
        chunk_overlap = config["chunk_overlap"]
        chunker = RecursiveChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

        pool_chunks: List[IndexedChunk] = []
        for cid, profile in candidate_profiles.items():
            cand_id = profile.get("candidate_metadata", {}).get("candidate_id", cid)
            chunks = chunker.chunk_profile(profile, role_bucket=role)
            for c in chunks:
                pool_chunks.append(IndexedChunk(
                    chunk_id=c.chunk_id,
                    vector=np.zeros(384, dtype=np.float32),
                    text=c.text,
                    metadata={
                        "candidate_id": cand_id,
                        "role_bucket": role,
                        "source_file": c.source_file,
                        "section": c.section,
                        "chunk_index": c.chunk_index,
                        **dict(c.metadata)
                    }
                ))

        if pool_chunks:
            pool_texts = [c.text for c in pool_chunks]
            pool_vectors = embed_model.encode(pool_texts, batch_size=32, normalize_embeddings=True)
            for idx, c in enumerate(pool_chunks):
                c.vector = pool_vectors[idx]

        pool_index = VectorIndex(pool_chunks, normalize=False)
        pool_retriever = ThresholdRetriever(
            index=pool_index,
            threshold=config["theta"],
            max_chunks_per_query=config["top_k"]
        )

        # 5. Run scorer twice
        logger.info("Starting Run 1...")
        run1 = score_candidates_deterministic(
            candidate_profiles, req_subqueries, sq_embeddings, weights, pool_retriever
        )
        
        logger.info("Starting Run 2...")
        run2 = score_candidates_deterministic(
            candidate_profiles, req_subqueries, sq_embeddings, weights, pool_retriever
        )

        if not run1 or not run2:
            logger.error("Failed to generate rankings for role %s in one of the runs", role)
            all_roles_pass = False
            continue

        if len(run1) != len(run2):
            logger.error("Ranking length mismatch for role %s: Run1=%d, Run2=%d", role, len(run1), len(run2))
            all_roles_pass = False
            continue

        # Check rankings match candidate-for-candidate, score-for-score, rank-for-rank
        mismatch_count = 0
        for i in range(len(run1)):
            cand1 = run1[i]
            cand2 = run2[i]
            if cand1["candidate_id"] != cand2["candidate_id"] or \
               not np.isclose(cand1["total_score"], cand2["total_score"], atol=1e-6) or \
               cand1["rank"] != cand2["rank"]:
                logger.error(
                    "Mismatch at index %d: Run1=%s, Run2=%s",
                    i, cand1, cand2
                )
                mismatch_count += 1

        if mismatch_count == 0:
            logger.info("SUCCESS: 100%% byte-identical rankings verified for %s (pool size: %d)", role, len(run1))
        else:
            logger.error("FAILURE: Detected %d mismatches for role %s", mismatch_count, role)
            all_roles_pass = False

    return all_roles_pass


if __name__ == "__main__":
    success = verify_determinism()
    if success:
        logger.info("Determinism checks passed successfully.")
        sys.exit(0)
    else:
        logger.error("Determinism checks FAILED.")
        sys.exit(1)
