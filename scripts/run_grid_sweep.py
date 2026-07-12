#!/usr/bin/env python3
"""Grid Search Parameter Sweep Runner for Candidate Retrieval and Ranking.

Iterates uniformly through a defined parameter grid (45 configurations) across
all 8 candidate pools. Uses in-memory candidate-level caching for chunking/embeddings 
to perform efficient retrieval. Saves candidate rankings to disk for stability analysis.
"""

import argparse
import json
import logging
import math
import sys
from datetime import datetime
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
logger = logging.getLogger("run_grid_sweep")

# Directories
PROCESSED_DIR = ROOT / "data/processed"
JOB_DESCRIPTIONS_DIR = ROOT / "data/job_descriptions"
GRID_SWEEP_BASE_DIR = ROOT / "reports/grid_sweep"


def get_roles() -> List[str]:
    """Find all role subdirectories within processed candidates directory."""
    roles = []
    for item in PROCESSED_DIR.iterdir():
        if item.is_dir() and not item.name.startswith((".", "evaluation_results")):
            roles.append(item.name)
    return sorted(roles)


def build_grid_configs() -> List[Dict[str, Any]]:
    """Construct the list of 45 parameter configurations in the search grid.

    Returns:
        List of configuration dictionaries.
    """
    configs = []
    cfg_idx = 1
    for cs in [500, 700, 1000]:
        overlap = cs // 2
        for tk in [5, 10, 20]:
            for th in [0.10, 0.25, 0.35, 0.40, 0.50]:
                is_base = (cs == 1000 and tk == 20 and math.isclose(th, 0.35))
                configs.append({
                    "config_id": f"cfg_{cfg_idx:02d}",
                    "chunk_size": cs,
                    "chunk_overlap": overlap,
                    "top_k": tk,
                    "theta": th,
                    "is_baseline": is_base
                })
                cfg_idx += 1
    return configs


def main():
    parser = argparse.ArgumentParser(description="Structured Parameter Grid Sweep for RAG Stability")
    parser.add_argument("--roles", nargs="+", help="Specify roles pools to run (default: all).")
    args = parser.parse_args()

    # Determine roles pools
    all_roles = get_roles()
    target_roles = args.roles if args.roles else all_roles
    if not target_roles:
        logger.error("No candidate pools found in data/processed/")
        sys.exit(1)

    logger.info("Initializing parameter grid sweep for roles: %s", target_roles)

    # Establish output directory for this run
    run_date = datetime.now().strftime("%Y%m%d")
    output_dir = GRID_SWEEP_BASE_DIR / f"grid_sweep_{run_date}"
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Output directory established at: %s", output_dir)

    # Generate and save grid configurations manifest
    grid_configs = build_grid_configs()
    manifest_path = output_dir / "config_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(grid_configs, fh, indent=2)
    logger.info("Grid manifest containing %d configurations written to %s", len(grid_configs), manifest_path)

    # Pre-load embedding model
    logger.info("Loading embedding model '%s'...", DEFAULT_EMBEDDING_MODEL)
    from sentence_transformers import SentenceTransformer
    embed_model = SentenceTransformer(DEFAULT_EMBEDDING_MODEL)

    for role in target_roles:
        logger.info("=== Starting Grid Sweep for Role: %s ===", role)
        role_dir = PROCESSED_DIR / role
        if not role_dir.exists():
            logger.warning("Directory for role %s not found, skipping.", role)
            continue

        # Load candidate profiles
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
            logger.warning("No profiles loaded for role %s, skipping.", role)
            continue

        # Parse subqueries
        subquery_file = JOB_DESCRIPTIONS_DIR / role / f"{role}_SubQuery.md"
        if not subquery_file.exists():
            logger.warning("SubQuery file not found for role %s, skipping.", role)
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

        # Load weight config
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
                logger.warning("Failed to load weight config for %s: %s", role, exc)

        if not weights:
            unique_reqs = list({req_id for req_id, _ in req_subqueries})
            if unique_reqs:
                default_wt = 100.0 / len(unique_reqs)
                weights = {req_id: default_wt for req_id in unique_reqs}

        # Cache of candidate-level indices per (chunk_size, chunk_overlap)
        index_cache: Dict[Tuple[int, int], Dict[str, VectorIndex]] = {}

        for cfg in grid_configs:
            cfg_id = cfg["config_id"]
            cs = cfg["chunk_size"]
            co = cfg["chunk_overlap"]
            tk = cfg["top_k"]
            th = cfg["theta"]
            is_base = cfg["is_baseline"]

            cache_key = (cs, co)

            # Lazy construct VectorIndex maps for each candidate under this chunk config
            if cache_key not in index_cache:
                logger.info("Chunking & Indexing role %s (cs=%d, co=%d)...", role, cs, co)
                chunker = RecursiveChunker(chunk_size=cs, chunk_overlap=co)
                role_chunks: List[IndexedChunk] = []

                for cid, profile in candidate_profiles.items():
                    cand_id = profile.get("candidate_metadata", {}).get("candidate_id", cid)
                    chunks = chunker.chunk_profile(profile, role_bucket=role)
                    for c in chunks:
                        role_chunks.append(IndexedChunk(
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

                if role_chunks:
                    chunk_texts = [c.text for c in role_chunks]
                    chunk_vectors = embed_model.encode(chunk_texts, batch_size=32, normalize_embeddings=True)
                    for idx, c in enumerate(role_chunks):
                        c.vector = chunk_vectors[idx]

                # Group chunks by candidate_id
                cand_chunks: Dict[str, List[IndexedChunk]] = {}
                for c in role_chunks:
                    cand_chunks.setdefault(c.metadata["candidate_id"], []).append(c)

                # Build a VectorIndex for each candidate individually
                cand_indices: Dict[str, VectorIndex] = {}
                for cand_id, chunks in cand_chunks.items():
                    cand_indices[cand_id] = VectorIndex(chunks, normalize=False)

                index_cache[cache_key] = cand_indices

            cand_indices = index_cache[cache_key]

            # Execute scoring
            pool_scores: Dict[str, float] = {}
            for cid, profile in candidate_profiles.items():
                cand_id = profile.get("candidate_metadata", {}).get("candidate_id", cid)
                total_candidate_score = 0.0

                if cand_id in cand_indices:
                    retriever = ThresholdRetriever(
                        index=cand_indices[cand_id],
                        threshold=th,
                        max_chunks_per_query=tk
                    )

                    req_similarities: Dict[str, List[float]] = {}
                    for sq_idx, (req_id, _) in enumerate(req_subqueries):
                        sq_vector = sq_embeddings[sq_idx]
                        hits = retriever.retrieve_scored(sq_vector)
                        max_cosine = max([h.cosine for h in hits]) if hits else 0.0
                        req_similarities.setdefault(req_id, []).append(max_cosine)

                    for req_id, sims in req_similarities.items():
                        req_weight = weights.get(req_id, 0.0)
                        mean_sim = float(np.mean(sims)) if sims else 0.01
                        total_candidate_score += req_weight * mean_sim
                else:
                    unique_reqs = {req_id for req_id, _ in req_subqueries}
                    total_candidate_score = sum(weights.get(req_id, 0.0) * 0.01 for req_id in unique_reqs)

                pool_scores[cand_id] = total_candidate_score

            # Sort and format rankings
            sorted_candidates = sorted(pool_scores.items(), key=lambda x: x[1], reverse=True)
            ranking = [
                {"candidate_id": cid, "total_score": round(score, 6), "rank": idx + 1}
                for idx, (cid, score) in enumerate(sorted_candidates)
            ]

            # Save ranking output to disk
            out_file = output_dir / f"{cfg_id}_{role}_ranking.json"
            with open(out_file, "w", encoding="utf-8") as fh:
                json.dump(ranking, fh, indent=2)

            # If this matches the baseline config, write the anchor file as well
            if is_base:
                base_file = output_dir / f"baseline_ranking_{role}.json"
                with open(base_file, "w", encoding="utf-8") as fh:
                    json.dump(ranking, fh, indent=2)

        logger.info("SUCCESS: Grid sweep finished for role %s.", role)

    logger.info("Structured parameter grid sweep successfully completed.")


if __name__ == "__main__":
    main()
