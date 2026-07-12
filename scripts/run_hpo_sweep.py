#!/usr/bin/env python3
"""RAG Hyperparameter Optimization (HPO) Sweep Script (DEC-021, Prong 6, Track 7).

This script performs multi-objective hyperparameter optimization (HPO) for RAG
parameters (chunk_size, chunk_overlap, threshold, top_k) using Optuna, logs the
trials to MLflow, and generates Prong 6 rank stability reports.

Objectives:
  1. Maximize Retrieval Quality (mean NDCG / MRR on eval set).
  2. Minimize Avg Chunks Returned (cost/latency control).
"""

import argparse
import json
import logging
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Sequence

import numpy as np

# Ensure project root is in sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.rag.recursive_chunker import (
    RecursiveChunker,
    min_overlap_for,
    max_overlap_for,
)
from src.rag.retriever import (
    DEFAULT_EMBEDDING_MODEL,
    IndexedChunk,
    ThresholdRetriever,
    VectorIndex,
)
from src.services.subquery_parser import parse_subquery_document
from src.reporting.rank_stability import (
    compute_rank_stability,
    write_stability_report,
)

# Setup logging
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("run_hpo_sweep")

# Try to import Optuna and MLflow dynamically to handle environment differences gracefully
try:
    import optuna
    _OPTUNA_AVAILABLE = True
except ImportError:
    _OPTUNA_AVAILABLE = False
    logger.error("Optuna is not installed in the environment. Please run 'pip install optuna'")

try:
    import mlflow
    _MLFLOW_AVAILABLE = True
except ImportError:
    _MLFLOW_AVAILABLE = False
    logger.warning("MLflow is not installed in the environment. Run logs will only be stored locally.")

# Canonical folders
EVAL_DIR = ROOT / "data/eval"
OPTUNA_DIR = ROOT / "data/optuna"
PROCESSED_DIR = ROOT / "data/processed"
REPORTS_DIR = ROOT / "reports/diff_rankings"
JOB_DESCRIPTIONS_DIR = ROOT / "data/job_descriptions"

# ---------------------------------------------------------------------------
# Metrics Math
# ---------------------------------------------------------------------------

def compute_mrr(retrieved_ids: List[str], expected_ids: List[str]) -> float:
    """Compute Mean Reciprocal Rank (MRR) for a query."""
    for idx, rid in enumerate(retrieved_ids):
        if rid in expected_ids:
            return 1.0 / (idx + 1)
    return 0.0


def compute_ndcg(retrieved_ids: List[str], expected_ids: List[str]) -> float:
    """Compute Normalized Discounted Cumulative Gain (NDCG) for a query."""
    dcg = 0.0
    for idx, rid in enumerate(retrieved_ids):
        if rid in expected_ids:
            dcg += 1.0 / math.log2(idx + 2)
            
    idcg = 0.0
    for idx in range(min(len(expected_ids), len(retrieved_ids))):
        idcg += 1.0 / math.log2(idx + 2)
        
    if idcg == 0.0:
        return 0.0
    return dcg / idcg


def compute_recall(retrieved_ids: List[str], expected_ids: List[str]) -> float:
    """Compute Recall at threshold for a query."""
    if not expected_ids:
        return 0.0
    found = sum(1 for rid in retrieved_ids if rid in expected_ids)
    return found / len(expected_ids)


# ---------------------------------------------------------------------------
# Evaluation Loader
# ---------------------------------------------------------------------------

def load_evaluation_set(path: Path) -> List[Dict[str, Any]]:
    """Load line-delimited JSONL queries from the eval set."""
    queries = []
    if not path.exists():
        logger.error("Evaluation set file not found: %s", path)
        return queries
    
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                queries.append(json.loads(line))
            except Exception as exc:
                logger.warning("Skipping invalid JSON lines: %s", exc)
    return queries


def find_weight_config(role: str) -> Optional[Path]:
    """Glob the weight config file for the role pool."""
    role_dir = JOB_DESCRIPTIONS_DIR / role
    if not role_dir.exists():
        return None
    configs = sorted(role_dir.glob(f"{role}_WeightConfig_*.json"))
    return configs[0] if configs else None


# ---------------------------------------------------------------------------
# Execution and Optuna Sweep Wrapper
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Optuna RAG Hyperparameter Optimization (HPO) Sweep")
    parser.add_argument("--role", default="BusinessAnalyst", help="The role pool to use for tuning.")
    parser.add_argument("--trials", type=int, default=10, help="Number of search trials to run.")
    parser.add_argument("--study-name", default="rag_tuning_sweep", help="Name of the Optuna study.")
    parser.add_argument("--eval-set", default="data/eval/v1.jsonl", help="Evaluation set path.")
    parser.add_argument("--no-mlflow", action="store_true", help="Disable MLflow run logging.")
    args = parser.parse_args()

    if not _OPTUNA_AVAILABLE:
        sys.exit(1)

    OPTUNA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Load eval set and extract targets
    eval_path = ROOT / args.eval_set
    all_eval_queries = load_evaluation_set(eval_path)
    if not all_eval_queries:
        logger.error("No queries loaded from %s. Cannot run tuning.", eval_path)
        sys.exit(1)
        
    eval_queries = [q for q in all_eval_queries if q.get("candidate_id", "").startswith(args.role)]
    if not eval_queries:
        logger.warning("No evaluation queries found in %s for role %s. Using all queries as fallback.", eval_path, args.role)
        eval_queries = all_eval_queries
        
    eval_candidates = {q["candidate_id"] for q in eval_queries if "candidate_id" in q}
    logger.info("Loaded %d evaluation queries targeting %d candidates", len(eval_queries), len(eval_candidates))

    # 2. Pre-load all candidates for the target role pool
    role_dir = PROCESSED_DIR / args.role
    if not role_dir.exists():
        logger.error("Role directory %s does not exist. Run extraction first.", role_dir)
        sys.exit(1)
        
    candidate_profiles: Dict[str, Dict[str, Any]] = {}
    for f in role_dir.glob("*.json"):
        if f.name.endswith(("_intelligence_report.json", "_structured_profile.json")):
            continue
        try:
            profile = json.loads(f.read_text(encoding="utf-8"))
            candidate_profiles[f.stem] = profile
        except Exception as exc:
            logger.warning("Failed to load parsed file %s: %s", f.name, exc)
            
    logger.info("Pre-loaded %d candidate profiles for role %s", len(candidate_profiles), args.role)

    # 3. Load sub-queries and weight configs for target pool rankings
    subquery_file = JOB_DESCRIPTIONS_DIR / args.role / f"{args.role}_SubQuery.md"
    if not subquery_file.exists():
        logger.error("SubQuery file not found at %s", subquery_file)
        sys.exit(1)
        
    parsed_subqueries = parse_subquery_document(subquery_file)
    requirements = parsed_subqueries.get("requirements", [])
    
    # Flatten subqueries to a list of (req_id, text) tuples
    req_subqueries: List[Tuple[str, str]] = []
    for req in requirements:
        req_id = req.get("req_id", "")
        for sq in req.get("sub_queries", []):
            sq_text = sq.get("text", "")
            if sq_text:
                req_subqueries.append((req_id, sq_text))
                
    logger.info("Parsed %d subqueries for candidate pool scoring", len(req_subqueries))

    weight_config_path = find_weight_config(args.role)
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
            logger.info("Loaded weight config from %s", weight_config_path.name)
        except Exception as exc:
            logger.warning("Failed to load weight config: %s", exc)
    else:
        # Fallback: equal weighting
        unique_reqs = list({req_id for req_id, _ in req_subqueries})
        if unique_reqs:
            default_wt = 100.0 / len(unique_reqs)
            weights = {req_id: default_wt for req_id in unique_reqs}
            logger.warning("No weight config found. Assigned equal weight fraction to %d requirements.", len(unique_reqs))

    # 4. Lazy-load the SentenceTransformer model once
    logger.info("Loading embedding model '%s'...", DEFAULT_EMBEDDING_MODEL)
    from sentence_transformers import SentenceTransformer
    embed_model = SentenceTransformer(DEFAULT_EMBEDDING_MODEL)

    # Embed evaluation queries
    logger.info("Pre-embedding %d evaluation queries...", len(eval_queries))
    query_texts = [q["query"] for q in eval_queries]
    query_embeddings = embed_model.encode(query_texts, normalize_embeddings=True)
    
    # Embed role sub-queries for pool ranking
    logger.info("Pre-embedding %d requirement subqueries...", len(req_subqueries))
    sq_texts = [sq_text for _, sq_text in req_subqueries]
    sq_embeddings = embed_model.encode(sq_texts, normalize_embeddings=True)

    # 5. Initialize Optuna database study
    db_path = OPTUNA_DIR / "studies.db"
    study_url = f"sqlite:///{db_path}"
    
    # We optimize to maximize retrieval quality (NDCG) and minimize average chunks returned
    study = optuna.create_study(
        study_name=args.study_name,
        storage=study_url,
        directions=["maximize", "minimize"],
        load_if_exists=True,
    )

    # Dictionary to collect rankings across trials for Prong 6 stability report
    trial_rankings: List[Dict[str, Any]] = []

    # Caches to avoid redundant chunking and embedding of the same (chunk_size, chunk_overlap) combinations
    eval_index_cache: Dict[Tuple[int, int], VectorIndex] = {}
    pool_index_cache: Dict[Tuple[int, int], VectorIndex] = {}

    # 6. Objective function
    def objective(trial: optuna.Trial) -> Tuple[float, float]:
        # Suggest HPs within Optuna search-space bounds (DEC-021)
        chunk_size = trial.suggest_int("chunk_size", 500, 1000, step=100)
        min_overlap = min_overlap_for(chunk_size)
        max_overlap = max_overlap_for(chunk_size)
        chunk_overlap = trial.suggest_int("chunk_overlap", min_overlap, max_overlap, step=50)
        threshold = trial.suggest_float("threshold", 0.10, 0.50, step=0.05)
        top_k = trial.suggest_int("top_k", 5, 20)

        cache_key = (chunk_size, chunk_overlap)

        # -------------------------------------------------------------------
        # Step A: Evaluate on target evaluation dataset candidates
        # -------------------------------------------------------------------
        if cache_key in eval_index_cache:
            eval_index = eval_index_cache[cache_key]
        else:
            chunker = RecursiveChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            
            # Chunk target candidates referenced in eval queries
            eval_chunks: List[IndexedChunk] = []
            for cid in eval_candidates:
                profile = candidate_profiles.get(cid)
                if not profile:
                    continue
                chunks = chunker.chunk_profile(profile, role_bucket=args.role)
                for c in chunks:
                    eval_chunks.append(IndexedChunk(
                        chunk_id=c.chunk_id,
                        vector=np.zeros(384, dtype=np.float32),  # Filled below
                        text=c.text,
                        metadata={
                            "candidate_id": c.candidate_id,
                            "role_bucket": c.role_bucket,
                            "source_file": c.source_file,
                            "section": c.section,
                            "chunk_index": c.chunk_index,
                            **dict(c.metadata)
                        }
                    ))
                    
            # Embed evaluation candidate chunks
            if eval_chunks:
                chunk_texts = [c.text for c in eval_chunks]
                chunk_vectors = embed_model.encode(chunk_texts, batch_size=32, normalize_embeddings=True)
                for idx, c in enumerate(eval_chunks):
                    c.vector = chunk_vectors[idx]
                    
            # Build evaluation VectorIndex
            eval_index = VectorIndex(eval_chunks, normalize=False)
            eval_index_cache[cache_key] = eval_index

        eval_retriever = ThresholdRetriever(index=eval_index, threshold=threshold, max_chunks_per_query=top_k)

        # Run queries
        mrr_scores = []
        ndcg_scores = []
        recall_scores = []
        chunks_returned_counts = []
        
        for q_idx, q in enumerate(eval_queries):
            cid = q["candidate_id"]
            expected_chunk_ids = q["expected_chunk_ids"]
            query_vector = query_embeddings[q_idx]
            
            # Retrieve chunks for this candidate
            hits = eval_retriever.retrieve_scored(query_vector, candidate_id=cid)
            retrieved_ids = [h.chunk_id for h in hits]
            
            mrr_scores.append(compute_mrr(retrieved_ids, expected_chunk_ids))
            ndcg_scores.append(compute_ndcg(retrieved_ids, expected_chunk_ids))
            recall_scores.append(compute_recall(retrieved_ids, expected_chunk_ids))
            chunks_returned_counts.append(len(retrieved_ids))
            
        mean_ndcg = float(np.mean(ndcg_scores))
        mean_mrr = float(np.mean(mrr_scores))
        mean_recall = float(np.mean(recall_scores))
        mean_chunks_returned = float(np.mean(chunks_returned_counts))

        # -------------------------------------------------------------------
        # Step B: Score and rank the entire candidate pool for rank stability
        # -------------------------------------------------------------------
        if cache_key in pool_index_cache:
            pool_index = pool_index_cache[cache_key]
        else:
            chunker = RecursiveChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            
            # Chunk all pool candidates
            pool_chunks: List[IndexedChunk] = []
            for cid, profile in candidate_profiles.items():
                chunks = chunker.chunk_profile(profile, role_bucket=args.role)
                for c in chunks:
                    pool_chunks.append(IndexedChunk(
                        chunk_id=c.chunk_id,
                        vector=np.zeros(384, dtype=np.float32),
                        text=c.text,
                        metadata={
                            "candidate_id": c.candidate_id,
                            "role_bucket": c.role_bucket,
                            "source_file": c.source_file,
                            "section": c.section,
                            "chunk_index": c.chunk_index,
                            **dict(c.metadata)
                        }
                    ))
                    
            # Embed pool chunks
            if pool_chunks:
                pool_texts = [c.text for c in pool_chunks]
                pool_vectors = embed_model.encode(pool_texts, batch_size=32, normalize_embeddings=True)
                for idx, c in enumerate(pool_chunks):
                    c.vector = pool_vectors[idx]
                    
            pool_index = VectorIndex(pool_chunks, normalize=False)
            pool_index_cache[cache_key] = pool_index

        pool_retriever = ThresholdRetriever(index=pool_index, threshold=threshold, max_chunks_per_query=top_k)

        # For each candidate, score their matches against requirements
        pool_scores: Dict[str, float] = {}
        for cid in candidate_profiles.keys():
            total_candidate_score = 0.0
            
            # Group query embeddings by requirement ID to compute unified sub-scores
            req_similarities: Dict[str, List[float]] = {}
            for sq_idx, (req_id, _) in enumerate(req_subqueries):
                sq_vector = sq_embeddings[sq_idx]
                hits = pool_retriever.retrieve_scored(sq_vector, candidate_id=cid)
                max_cosine = max([h.cosine for h in hits]) if hits else 0.0
                req_similarities.setdefault(req_id, []).append(max_cosine)
                
            # Aggregate requirement sub-scores (additive formula)
            for req_id, sims in req_similarities.items():
                req_weight = weights.get(req_id, 0.0)
                # Sub-score matches the mean max similarity, or 0.01 floor if empty
                mean_sim = float(np.mean(sims)) if sims else 0.01
                total_candidate_score += req_weight * mean_sim
                
            pool_scores[cid] = total_candidate_score

        # Generate candidate pool ranking list
        sorted_candidates = sorted(pool_scores.items(), key=lambda x: x[1], reverse=True)
        ranking = [
            {"candidate_id": cid, "total_score": round(score, 4), "rank": i + 1}
            for i, (cid, score) in enumerate(sorted_candidates)
        ]
        
        # Save ranking record to memory for rank stability report at study completion
        trial_rankings.append({
            "trial_number": trial.number,
            "params": {
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "threshold": threshold,
                "top_k": top_k,
            },
            "ranking": ranking
        })

        # -------------------------------------------------------------------
        # Step C: Log to MLflow if enabled
        # -------------------------------------------------------------------
        if _MLFLOW_AVAILABLE and not args.no_mlflow:
            try:
                # Use active run or start a new nested run for this trial
                mlflow.set_tracking_uri("sqlite:///data/mlflow/mlflow.db")
                mlflow.set_experiment(f"optuna_{args.study_name}")
                with mlflow.start_run(run_name=f"trial_{trial.number}", nested=True):
                    mlflow.log_params({
                        "chunk_size": chunk_size,
                        "chunk_overlap": chunk_overlap,
                        "threshold": threshold,
                        "top_k": top_k,
                    })
                    mlflow.log_metrics({
                        "mean_ndcg": mean_ndcg,
                        "mean_mrr": mean_mrr,
                        "mean_recall": mean_recall,
                        "mean_chunks_returned": mean_chunks_returned,
                    })
            except Exception as mlflow_exc:
                logger.warning("Failed to log metrics to MLflow: %s", mlflow_exc)

        # Optuna objectives: maximize NDCG, minimize avg chunks returned
        return mean_ndcg, mean_chunks_returned

    # 7. Run optimization loop
    logger.info("Starting hyperparameter optimization sweep of %d trials...", args.trials)
    study.optimize(objective, n_trials=args.trials)
    
    logger.info("Optimization sweep complete!")
    
    # 8. Export rankings JSON and generate stability reports (Prong 6)
    rankings_payload = {
        "study_name": args.study_name,
        "role": args.role,
        "trials": trial_rankings
    }
    
    rankings_file = REPORTS_DIR / f"optuna_study_{args.study_name}__{args.role}__rankings.json"
    with rankings_file.open("w", encoding="utf-8") as fh:
        json.dump(rankings_payload, fh, indent=2)
        
    logger.info("Wrote study trial rankings to %s", rankings_file)

    # Call Prong 6 stability report generator
    try:
        report = compute_rank_stability(rankings_payload, role=args.role)
        json_out, md_out = write_stability_report(report, str(rankings_file))
        logger.info("Prong 6 stability analysis written to %s and %s", json_out.name, md_out.name)
    except Exception as exc:
        logger.error("Failed to generate stability reports: %s", exc)


if __name__ == "__main__":
    main()
