"""Sub-query similarity retrieval for per-candidate scoring.

This module replaces the Section-Routed Evidence Retrieval approach with
sub-query similarity, as agreed in 2026-07-04. The spec at line 470-471 of
``WORKING_LOGIC.md`` says:

    "We will not do a direct vector embedding based similarity search
     based on the JD requirements. Rather we will break each requirement
     into small set of sub-queries, and those sub-queries be used to see
     what output do we get from the retrieved similar chunks."

This module:

1. Embeds every chunk once (cached on disk at ``data/embeddings/index.npz``)
2. For each REQ, takes the rubric's sub-questions as sub-queries
3. Embeds each sub-query and retrieves the relevant chunks via cosine
4. Union + dedup → input to the rubric-bound LLM judge
5. Caches the (candidate_id, REQ-id, chunk-hash-set) → LLM sub-scores
6. **Batched mode** (2026-07-04): one LLM call per candidate for all REQs
   (15x speedup over per-REQ calls)

The LLM does not score in a free-form way; it answers the anchored
sub-questions in the rubric (binary 0/1, linear, or anchored 0.0/0.25/
0.5/0.75/1.0). The rubric is fixed at design time, so the LLM's output
space is bounded and reliable across runs.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.rag.document_aware_chunker import ChunkRecord

logger = logging.getLogger(__name__)

# Embedding model is the one selected in MODEL_REGISTRY.md.
DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384  # MiniLM-L6-v2 output dim

# Paths.
ROOT = Path(__file__).resolve().parent.parent.parent
EMBEDDINGS_DIR = ROOT / "data" / "embeddings"
INDEX_PATH = EMBEDDINGS_DIR / "recursive_chunking" / "index.npz"
CHUNKS_PATH = EMBEDDINGS_DIR / "recursive_chunking" / "chunks.jsonl"
CACHE_PATH = EMBEDDINGS_DIR / "llm_cache.jsonl"


# ---------------------------------------------------------------------------
# Embedding model singleton
# ---------------------------------------------------------------------------

_MODEL = None


def get_model():
    """Lazy-load the sentence-transformers model."""
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading embedding model %s (first call only)...", DEFAULT_MODEL_NAME)
        _MODEL = SentenceTransformer(DEFAULT_MODEL_NAME)
    return _MODEL


def embed_texts(texts: List[str]) -> np.ndarray:
    """Embed a list of texts. Returns shape (n, 384)."""
    model = get_model()
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vectors, dtype=np.float32)


# ---------------------------------------------------------------------------
# Embedding index over all chunks
# ---------------------------------------------------------------------------

@dataclass
class ChunkIndex:
    """In-memory index of all chunks for fast similarity search."""
    chunk_ids: List[str] = field(default_factory=list)
    texts: List[str] = field(default_factory=list)
    vectors: Optional[np.ndarray] = None  # shape (n, 384), L2-normalized
    chunk_by_id: Dict[str, ChunkRecord] = field(default_factory=dict)

    def add_chunk(self, chunk: ChunkRecord) -> None:
        if chunk.chunk_id in self.chunk_by_id:
            return
        self.chunk_by_id[chunk.chunk_id] = chunk

    def finalize(self) -> None:
        """Build the vectors matrix from the collected chunks."""
        if not self.chunk_by_id:
            return
        self.chunk_ids = list(self.chunk_by_id.keys())
        self.texts = [self.chunk_by_id[cid].text for cid in self.chunk_ids]
        if self.texts:
            self.vectors = embed_texts(self.texts)
            logger.info("Built index over %d chunks (dim=%d)", len(self.texts), self.vectors.shape[1])

    def save(self) -> None:
        """Persist the index to disk for fast reload."""
        EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)
        if self.vectors is not None:
            np.savez_compressed(
                INDEX_PATH,
                vectors=self.vectors,
                chunk_ids=np.array(self.chunk_ids, dtype=object),
            )
        with open(CHUNKS_PATH, "w", encoding="utf-8") as f:
            for cid in self.chunk_ids:
                chunk = self.chunk_by_id[cid]
                f.write(json.dumps({
                    "chunk_id": chunk.chunk_id,
                    "candidate_id": chunk.candidate_id,
                    "role_bucket": chunk.role_bucket,
                    "source_file": chunk.source_file,
                    "section": chunk.section,
                    "section_type": chunk.section_type,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                    "char_span": list(chunk.char_span),
                    "parent_structure": chunk.parent_structure,
                    "skills_asserted": chunk.skills_asserted,
                    "experience_type": chunk.experience_type,
                }) + "\n")

    @classmethod
    def load(cls) -> Optional["ChunkIndex"]:
        """Load the index from disk if it exists."""
        if not INDEX_PATH.exists() or not CHUNKS_PATH.exists():
            return None
        data = np.load(INDEX_PATH, allow_pickle=True)
        vectors = data["vectors"]
        chunk_ids = list(data["chunk_ids"])

        # Load full chunk records (with text) so the LLM gets real evidence
        chunk_by_id: Dict[str, ChunkRecord] = {}
        texts: List[str] = []
        for line in CHUNKS_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            text = d.get("text", "")
            chunk_by_id[d["chunk_id"]] = ChunkRecord(
                chunk_id=d["chunk_id"],
                candidate_id=d["candidate_id"],
                role_bucket=d.get("role_bucket", ""),
                source_file=d.get("source_file", ""),
                section=d.get("section", ""),
                chunk_index=d.get("chunk_index", 0),
                text=text,
                char_span=tuple(d.get("char_span", (0, 0))),
                section_type=d.get("section_type", ""),
                parent_structure=d.get("parent_structure", {}),
                skills_asserted=d.get("skills_asserted", []),
                experience_type=d.get("experience_type", "unknown"),
            )
            texts.append(text)

        return cls(
            chunk_ids=chunk_ids,
            texts=texts,
            vectors=vectors,
            chunk_by_id=chunk_by_id,
        )


def build_index_from_chunks_dir(chunks_dir: Path) -> ChunkIndex:
    """Build the chunk index by scanning ``chunks_dir/<role>/*.jsonl``.

    Skips already-indexed chunks (re-runs are safe).
    """
    index = ChunkIndex.load() or ChunkIndex()

    files_processed = 0
    chunks_added = 0
    for jl in chunks_dir.rglob("*.jsonl"):
        files_processed += 1
        for line in jl.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            chunk = ChunkRecord(
                chunk_id=d["chunk_id"],
                candidate_id=d["candidate_id"],
                role_bucket=d.get("role_bucket", ""),
                source_file=d.get("source_file", ""),
                section=d.get("section", ""),
                chunk_index=int(d.get("chunk_index", 0)),
                text=d.get("text", ""),
                char_span=tuple(d.get("char_span", (0, 0))),
                metadata=d.get("metadata", {}),
                section_type=d.get("section_type", ""),
                parent_structure=d.get("parent_structure", {}),
                skills_asserted=d.get("skills_asserted", []),
                experience_type=d.get("experience_type", "unknown"),
            )
            if chunk.chunk_id not in index.chunk_by_id:
                index.add_chunk(chunk)
                chunks_added += 1

    if chunks_added > 0:
        index.finalize()
        index.save()
        logger.info(
            "Indexed %d new chunks from %d files",
            chunks_added, files_processed,
        )
    else:
        logger.info("Index already up to date (%d chunks across %d files)", len(index.chunk_ids), files_processed)

    return index


# ---------------------------------------------------------------------------
# Sub-query similarity retrieval
# ---------------------------------------------------------------------------

@dataclass
class SubQueryHit:
    """One chunk retrieved for a sub-query."""
    chunk_id: str
    chunk: ChunkRecord
    similarity: float
    sub_query_key: str  # Which sub-question this chunk supports


def retrieve_chunks_for_requirement(
    index: ChunkIndex,
    candidate_id: str,
    sub_queries: List[Tuple[str, str]],  # [(sub_question_key, sub_question_text)]
    threshold: float = 0.0,
) -> List[SubQueryHit]:
    """Retrieve relevant chunks for a candidate's REQ via sub-query similarity.

    Args:
        index: The chunk index (built once, reused).
        candidate_id: Filter to this candidate's chunks.
        sub_queries: List of (key, text) tuples for the sub-questions.
        threshold: Cosine threshold. Default 0.0 = send everything; the LLM
            does the final filtering. Set higher (e.g. 0.2) to drop noise.

    Returns:
        List of SubQueryHit, deduplicated by chunk_id, sorted by similarity desc.
    """
    if index.vectors is None or not sub_queries:
        return []

    # Filter to this candidate's chunk IDs
    candidate_chunk_indices = [
        i for i, cid in enumerate(index.chunk_ids) if index.chunk_by_id[cid].candidate_id == candidate_id
    ]
    if not candidate_chunk_indices:
        return []

    candidate_vectors = index.vectors[candidate_chunk_indices]
    candidate_chunk_ids = [index.chunk_ids[i] for i in candidate_chunk_indices]

    # Embed each sub-query and compute cosine vs candidate's chunks
    sub_query_texts = [sq[1] for sq in sub_queries]
    sq_vectors = embed_texts(sub_query_texts)  # (n_sq, 384)

    # Cosine: since vectors are L2-normalized, dot product == cosine
    # Result: (n_sq, n_candidate_chunks)
    sims = sq_vectors @ candidate_vectors.T

    # Collect hits
    seen: Dict[str, SubQueryHit] = {}
    for sq_idx, (sq_key, _sq_text) in enumerate(sub_queries):
        for c_idx, cid in enumerate(candidate_chunk_ids):
            score = float(sims[sq_idx, c_idx])
            if score < threshold:
                continue
            if cid in seen and seen[cid].similarity >= score:
                continue  # Keep highest similarity
            seen[cid] = SubQueryHit(
                chunk_id=cid,
                chunk=index.chunk_by_id[cid],
                similarity=score,
                sub_query_key=sq_key,
            )

    hits = sorted(seen.values(), key=lambda h: h.similarity, reverse=True)
    return hits


# ---------------------------------------------------------------------------
# Cache for LLM sub-scores
# ---------------------------------------------------------------------------

def make_cache_key(
    candidate_id: str,
    req_id: str,
    chunk_ids: Tuple[str, ...],
    llm_model: str = "stub",
    theta: Optional[float] = None,
) -> str:
    """Compute a cache key for an LLM sub-score call.

    Includes the chunk IDs (so any re-chunk invalidates the cache), the
    model name (so model upgrades invalidate the cache), and the cosine
    theta used for this retrieval pass.

    Why theta is in the key (M0.5a Step 5, 2026-07-06):
        During an Optuna sweep (DEC-021) different ``theta`` values may
        yield the *same* chunk-id set (when every retrieved chunk clears
        both candidate thresholds). In that case the LLM sees identical
        evidence and would produce the same score, so the cache could
        return a hit. Folding ``theta`` into the key makes each Optuna
        trial strictly isolated: a sweep across theta in [0.10, 0.50]
        never reuses a sub-score that was computed under a different
        theta. The tradeoff is more cache misses (lower hit rate during
        the sweep) but a simpler, auditable per-trial invariant —
        every cached value is tagged with the theta that produced it.
    """
    h = hashlib.sha256()
    theta_repr = "" if theta is None else f"{float(theta):.6f}"
    h.update(f"{candidate_id}|{req_id}|{llm_model}|theta={theta_repr}|".encode("utf-8"))
    for cid in sorted(chunk_ids):
        h.update(f"{cid}|".encode("utf-8"))
    return h.hexdigest()


class LLMScoreCache:
    """File-backed cache for LLM sub-scores.

    Key: hash(candidate_id, req_id, chunk-ids, model-name)
    Value: the LLM's anchored sub-scores (binary gates + floats)

    Stored as JSONL in ``data/embeddings/llm_cache.jsonl``.
    """

    def __init__(self, path: Path = CACHE_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    d = json.loads(line)
                    self._cache[d["key"]] = d
        self._loaded = True

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        self._load()
        return self._cache.get(key)

    def put(self, key: str, value: Dict[str, Any]) -> None:
        self._load()
        self._cache[key] = value
        # Append to file (line-by-line so it's easy to inspect / gc)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"key": key, **value}) + "\n")

    def stats(self) -> Dict[str, int]:
        self._load()
        return {"size": len(self._cache)}


# ---------------------------------------------------------------------------
# End-to-end: sub-query similarity + LLM scoring
# ---------------------------------------------------------------------------

def score_requirement_with_similarity(
    index: ChunkIndex,
    candidate_id: str,
    req_id: str,
    req_name: str,
    sub_queries: List[Tuple[str, str]],
    llm_caller,
    cache: Optional[LLMScoreCache] = None,
    threshold: float = 0.0,
) -> Dict[str, Any]:
    """Score one REQ for one candidate via sub-query similarity.

    Args:
        index: Chunk index.
        candidate_id: Candidate.
        req_id: Requirement ID (e.g., "REQ-002").
        req_name: Requirement name (e.g., "SQL for Data Validation & Analysis").
        sub_queries: List of (key, text) sub-questions.
        llm_caller: Callable(prompt: str) -> str returning the LLM's anchored sub-scores
            (or None to skip the LLM call and return zeros).
        cache: Optional LLM score cache.
        threshold: Cosine threshold (default 0.0 = no filtering).

    Returns:
        Dictionary with:
          - "hits": List of SubQueryHit (chunks that were retrieved)
          - "sub_scores": Dict of sub-question_key -> anchored float
          - "normalized_score": product of sub-scores (0.0-1.0)
          - "from_cache": bool
    """
    # 1. Retrieve relevant chunks
    hits = retrieve_chunks_for_requirement(
        index, candidate_id, sub_queries, threshold=threshold,
    )

    if not hits:
        return {
            "hits": [],
            "sub_scores": {k: 0.0 for k, _ in sub_queries},
            "normalized_score": 0.0,
            "from_cache": False,
        }

    # 2. Build cache key. Include ``threshold`` so an Optuna sweep across
    # theta does not reuse sub-scores computed under a different theta
    # even if the retrieved chunk-id set happens to coincide.
    cache_key = make_cache_key(
        candidate_id, req_id,
        tuple(h.chunk_id for h in hits),
        llm_model=getattr(llm_caller, "model_name", "stub"),
        theta=threshold,
    )

    # 3. Check cache
    if cache:
        cached = cache.get(cache_key)
        if cached:
            return {
                "hits": hits,
                "sub_scores": cached.get("sub_scores", {}),
                "normalized_score": cached.get("normalized_score", 0.0),
                "from_cache": True,
            }

    # 4. Call LLM (or stub)
    chunks_text = "\n\n---\n\n".join(h.chunk.text for h in hits)

    # Build a detailed anchored-scale legend for the prompt
    from src.scoring.rubrics import get_rubric as _get_rubric
    rubric_obj = _get_rubric(sub_queries[0][0].split("_")[0] if sub_queries else "skill")
    if rubric_obj is None:
        # Fall back: just list the keys
        anchors_block = "\n".join(f"- {key}" for key, _ in sub_queries)
    else:
        anchor_lines = []
        for sq in rubric_obj.sub_questions:
            if sq.type == "binary":
                anchor_lines.append(f"  {sq.key}: 0.0 or 1.0 (binary gate)")
            elif sq.type == "linear":
                anchor_lines.append(f"  {sq.key}: float in [0.0, 1.0] = min(years/expected, 1.0)")
            else:  # anchored
                desc_lines = [f"  {sq.key}: one of"]
                for anc in sq.anchors:
                    desc_lines.append(f"    {anc.value} = {anc.description}")
                anchor_lines.append("\n".join(desc_lines))
        anchors_block = "\n".join(anchor_lines)

    sub_questions_block = "\n".join(
        f"- {key}: {text}" for key, text in sub_queries
    )

    output_keys = "\n".join(f"{key}: <value>" for key, _ in sub_queries)

    prompt = f"""TASK: Score a candidate's resume against the sub-questions for one JD requirement.

REQUIREMENT: {req_id} = {req_name}

SUB-QUESTIONS (answer each with the anchored value shown):
{sub_questions_block}

ANCHORED VALUE SCALES:
{anchors_block}

EVIDENCE (resume chunks retrieved by sub-query similarity; "---" separates chunks):
{chunks_text}

OUTPUT FORMAT (strictly follow this; one line per sub-question, in the order shown above, no extra text, no explanation, no markdown):
{output_keys}
"""

    try:
        raw = llm_caller(prompt)
    except Exception as e:
        logger.warning("LLM call failed: %s", e)
        raw = ""

    sub_scores = parse_anchored_response(raw, sub_queries)

    # 5. Compute normalized sub-score (product of sub-scores, per spec)
    normalized = 1.0
    for k, _ in sub_queries:
        normalized *= sub_scores.get(k, 0.0)

    result = {
        "hits": hits,
        "sub_scores": sub_scores,
        "normalized_score": round(normalized, 4),
        "from_cache": False,
    }

    # 6. Cache
    if cache:
        cache.put(cache_key, {
            "candidate_id": candidate_id,
            "req_id": req_id,
            "sub_scores": sub_scores,
            "normalized_score": result["normalized_score"],
        })

    return result


def parse_anchored_response(
    raw: str,
    sub_queries: List[Tuple[str, str]],
) -> Dict[str, float]:
    """Parse the LLM's response into per-sub-question anchored floats.

    Expected format (one per line):
        key: <value>
    where <value> is one of:
        - 0, 1, 0.0, 0.25, 0.5, 0.75, 1.0 (numeric anchored)
        - yes/no, true/false (mapped to 1.0/0.0 for binary)
        - "high"/"medium"/"low" (mapped to 1.0/0.5/0.25)
        - "12+ years", "5 years", etc. (linear years: parsed as a number)
    Missing sub-questions default to 0.0.
    """
    out: Dict[str, float] = {}
    valid_values = {0.0, 0.25, 0.5, 0.75, 1.0}
    text_map = {
        "yes": 1.0, "true": 1.0, "high": 1.0, "strong": 1.0, "very": 1.0, "excellent": 1.0,
        "no": 0.0, "false": 0.0, "low": 0.0, "none": 0.0, "weak": 0.0, "absent": 0.0,
        "partial": 0.5, "medium": 0.5, "moderate": 0.5, "some": 0.5,
        "mostly": 0.75, "tangential": 0.25,
    }

    import re

    for line in raw.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key_part, _, val_part = line.partition(":")
        key = key_part.strip().lower()
        val_str = val_part.strip().lower()

        # Match a valid sub-question key (exact, then suffix match)
        matched_key = None
        for sq_key, _ in sub_queries:
            sk = sq_key.lower()
            if sk == key or sk.endswith(key) or key.endswith(sk):
                matched_key = sq_key
                break
        if matched_key is None:
            continue

        # Try numeric parse first
        try:
            v = float(val_str)
        except ValueError:
            # Try text-to-value map
            v = text_map.get(val_str, None)
            if v is None:
                # Try to extract a number from strings like "12+ years", "5 years", "0 yrs", "8+"
                # For years_experience type, we want to extract the leading number
                num_match = re.match(r"(\d+(?:\.\d+)?)", val_str)
                if num_match:
                    # Linear years: the LLM is giving a raw years count. Caller
                    # is expected to know the expected_years and snap, but for now
                    # we just record 1.0 if > 0, 0.0 otherwise (LLM is already doing
                    # the linear scaling per rubric formula).
                    raw_years = float(num_match.group(1))
                    # If the value mentions "0", treat as 0. Otherwise 1.0
                    # (we don't have expected_years here; the LLM should output
                    # 0.0-1.0 directly per the rubric's anchored scale).
                    v = 1.0 if raw_years > 0 else 0.0
                else:
                    continue

        # Snap to nearest anchored value if not exact
        if v in valid_values:
            out[matched_key] = v
        elif 0.0 <= v <= 1.0:
            closest = min(valid_values, key=lambda x: abs(x - v))
            out[matched_key] = closest
        else:
            out[matched_key] = 0.0  # out of range

    # Fill missing keys with 0.0
    for sq_key, _ in sub_queries:
        out.setdefault(sq_key, 0.0)

    return out


# ---------------------------------------------------------------------------
# Batched scoring: one LLM call per candidate for all REQs
# ---------------------------------------------------------------------------

def score_candidate_batched(
    index: ChunkIndex,
    candidate_id: str,
    requirements: List[Dict[str, Any]],
    llm_caller,
    cache: Optional[LLMScoreCache] = None,
    threshold: float = 0.0,
) -> Dict[str, Dict[str, Any]]:
    """Score all REQs for one candidate in a single LLM call.

    This replaces the per-REQ ``score_requirement_with_similarity`` loop
    with a single batched call. For 15 REQs, this is a 15x speedup
    (one LLM round-trip instead of 15).

    The LLM receives all REQs + their sub-questions + the joined chunks,
    and returns sub-scores for every REQ in one response.

    Args:
        index: Chunk index.
        candidate_id: Candidate.
        requirements: List of dicts, one per REQ:
            {
                "req_id": "REQ-002",
                "req_name": "SQL for Data Validation & Analysis",
                "sub_queries": [("skill_presence", "Does the candidate know SQL?"), ...],
                "rubric_type": "skill",  # for the anchored-scale legend
            }
        llm_caller: Callable(prompt: str) -> str returning the LLM's response.
        cache: Optional LLM score cache (per-REQ keys, so partial hits work).
        threshold: Cosine threshold (default 0.0).

    Returns:
        Dict mapping req_id -> result dict (same shape as
        ``score_requirement_with_similarity``):
            {
                "req_id": "REQ-002",
                "req_name": "...",
                "hits": [SubQueryHit, ...],
                "sub_scores": {"skill_presence": 1.0, ...},
                "normalized_score": 0.6,
                "from_cache": True/False,
            }
    """
    if not requirements:
        return {}

    # 1. Per-REQ retrieval, then union the chunks
    all_hits: Dict[str, SubQueryHit] = {}  # chunk_id -> hit (any REQ)
    per_req_hits: Dict[str, List[SubQueryHit]] = {}

    for req in requirements:
        req_id = req["req_id"]
        sub_queries = req["sub_queries"]
        hits = retrieve_chunks_for_requirement(
            index, candidate_id, sub_queries, threshold=threshold,
        )
        per_req_hits[req_id] = hits
        for h in hits:
            # Keep highest similarity across REQs
            if h.chunk_id not in all_hits or all_hits[h.chunk_id].similarity < h.similarity:
                all_hits[h.chunk_id] = h

    if not all_hits:
        # No hits at all — return zeros for every REQ
        return {
            req["req_id"]: {
                "req_id": req["req_id"],
                "req_name": req["req_name"],
                "hits": [],
                "sub_scores": {k: 0.0 for k, _ in req["sub_queries"]},
                "normalized_score": 0.0,
                "from_cache": False,
            }
            for req in requirements
        }

    # 2. Build the union chunk list (deduped, ordered by max similarity)
    union_chunks = sorted(all_hits.values(), key=lambda h: h.similarity, reverse=True)
    chunks_text = "\n\n---\n\n".join(h.chunk.text for h in union_chunks)

    # 3. Check cache per-REQ
    model_name = getattr(llm_caller, "model_name", "stub")
    union_chunk_ids = tuple(h.chunk_id for h in union_chunks)

    results: Dict[str, Dict[str, Any]] = {}
    missing_for_llm: List[Dict[str, Any]] = []

    for req in requirements:
        req_id = req["req_id"]
        # Per-REQ cache key uses the REQ's own hits (not the union).
        # If the cached entry was made by per-REQ scoring, hits match.
        # If the cached entry was made by batched scoring, hits may differ
        # — we re-fetch by REQ-keyed chunks to be consistent.
        per_req_chunk_ids = tuple(h.chunk_id for h in per_req_hits[req_id])
        cache_key = make_cache_key(
            candidate_id, req_id, per_req_chunk_ids, model_name,
            theta=threshold,
        )
        if cache:
            cached = cache.get(cache_key)
            if cached:
                results[req_id] = {
                    "req_id": req_id,
                    "req_name": req["req_name"],
                    "hits": per_req_hits[req_id],
                    "sub_scores": cached.get("sub_scores", {}),
                    "normalized_score": cached.get("normalized_score", 0.0),
                    "from_cache": True,
                }
                continue
        missing_for_llm.append({
            "req_id": req_id,
            "req_name": req["req_name"],
            "sub_queries": req["sub_queries"],
            "rubric_type": req.get("rubric_type", "skill"),
        })

    if not missing_for_llm:
        return results  # All REQs served from cache

    # 4. Build the batched prompt
    prompt = _build_batched_prompt(missing_for_llm, chunks_text, union_chunks)

    # 5. Call LLM once
    try:
        raw = llm_caller(prompt)
    except Exception as e:
        logger.warning("Batched LLM call failed: %s", e)
        raw = ""

    # 6. Parse the batched response
    parsed = _parse_batched_response(raw, missing_for_llm)

    # 7. Compute per-REQ results, cache them
    for req in missing_for_llm:
        req_id = req["req_id"]
        sub_scores = parsed.get(req_id, {})
        # Normalize: product of sub-scores
        normalized = 1.0
        for k, _ in req["sub_queries"]:
            normalized *= sub_scores.get(k, 0.0)
        normalized = round(normalized, 4)

        result = {
            "req_id": req_id,
            "req_name": req["req_name"],
            "hits": per_req_hits[req_id],
            "sub_scores": sub_scores,
            "normalized_score": normalized,
            "from_cache": False,
        }
        results[req_id] = result

        # Cache per-REQ (so a future single-REQ call hits the same key)
        if cache:
            per_req_chunk_ids = tuple(h.chunk_id for h in per_req_hits[req_id])
            cache_key = make_cache_key(
                candidate_id, req_id, per_req_chunk_ids, model_name,
                theta=threshold,
            )
            cache.put(cache_key, {
                "candidate_id": candidate_id,
                "req_id": req_id,
                "sub_scores": sub_scores,
                "normalized_score": normalized,
            })

    return results


def _build_batched_prompt(
    requirements: List[Dict[str, Any]],
    chunks_text: str,
    union_chunks: List[SubQueryHit],
) -> str:
    """Build the batched prompt: all REQs + sub-questions + chunks.

    Output format expected from the LLM:
        REQ-001:
          skill_presence: 1.0
          years_experience: 0.8
          project_relevance: 0.75

        REQ-002:
          ...
    """
    # Per-REQ blocks
    req_blocks = []
    output_keys = []
    for req in requirements:
        req_id = req["req_id"]
        req_name = req["req_name"]
        sub_queries = req["sub_queries"]
        # Sub-questions block
        sq_lines = "\n".join(f"    {k}: {txt}" for k, txt in sub_queries)
        # Anchored-scale legend (per REQ)
        from src.scoring.rubrics import get_rubric
        rubric_obj = get_rubric(req.get("rubric_type", "skill"))
        anchor_lines = []
        if rubric_obj:
            for sq in rubric_obj.sub_questions:
                if sq.type == "binary":
                    anchor_lines.append(f"    {sq.key}: 0.0 or 1.0 (binary gate)")
                elif sq.type == "linear":
                    anchor_lines.append(f"    {sq.key}: float in [0.0, 1.0]")
                else:
                    inner = "\n".join(
                        f"      {a.value} = {a.description}" for a in sq.anchors
                    )
                    anchor_lines.append(f"    {sq.key}:\n{inner}")
        anchors_str = "\n".join(anchor_lines) if anchor_lines else "  (no anchors defined)"
        # Output keys for this REQ
        for k, _ in sub_queries:
            output_keys.append((req_id, k))

        # Build the REQ block
        output_lines = "\n".join(
            f"      {k}: <value>" for k, _ in sub_queries
        )
        req_block = f"""REQUIREMENT: {req_id} = {req_name}

  SUB-QUESTIONS (answer each):
{sq_lines}

  ANCHORED VALUE SCALES:
{anchors_str}

  OUTPUT (one line per sub-question):
{output_lines}
"""
        req_blocks.append(req_block)

    all_reqs_block = "\n---\n".join(req_blocks)

    # Master output template
    output_template_lines = []
    for req_id, k in output_keys:
        output_template_lines.append(f"{req_id}::{k}: <value>")
    output_template = "\n".join(output_template_lines)

    prompt = f"""TASK: Score a candidate's resume against MULTIPLE JD requirements in one response.

The candidate's resume is provided as EVIDENCE below. For EACH requirement, answer
each sub-question with the anchored value shown. Be strict — if the evidence does not
support a high score, output a low score.

EVIDENCE (resume chunks, joined; "---" separates chunks):
{chunks_text}

REQUIREMENTS TO SCORE (one per block):
{all_reqs_block}

OUTPUT FORMAT (strictly follow this; one line per (req_id, sub_question) pair, in the
order shown above, no extra text, no explanation, no markdown; use "::" to separate
req_id from sub_question_key):
{output_template}
"""
    return prompt


def _parse_batched_response(
    raw: str,
    requirements: List[Dict[str, Any]],
) -> Dict[str, Dict[str, float]]:
    """Parse the LLM's batched response into per-REQ sub-scores.

    Expected format: "<req_id>::<sub_question_key>: <value>" (one per line).
    Falls back to "<sub_question_key>: <value>" if req_id is missing.
    """
    out: Dict[str, Dict[str, float]] = {req["req_id"]: {} for req in requirements}

    for line in raw.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue

        # Parse "<req_id>::<key>: <value>" or "<key>: <value>"
        if "::" in line:
            req_id, _, rest = line.partition("::")
            req_id = req_id.strip()
            key_part, _, val_part = rest.partition(":")
        else:
            req_id = None
            key_part, _, val_part = line.partition(":")

        key = key_part.strip().lower()
        val_str = val_part.strip().lower()

        # Find which REQ this line belongs to
        target_req = None
        for req in requirements:
            if req_id and req["req_id"] == req_id:
                target_req = req
                break
        if target_req is None:
            # No req_id — try to match by sub-query key across all REQs
            for req in requirements:
                for k, _ in req["sub_queries"]:
                    if k.lower() == key or key.endswith(k.lower()):
                        target_req = req
                        break
                if target_req:
                    break
        if target_req is None:
            continue

        # Match the sub-question key
        matched_key = None
        for sq_key, _ in target_req["sub_queries"]:
            sk = sq_key.lower()
            if sk == key or sk.endswith(key) or key.endswith(sk):
                matched_key = sq_key
                break
        if matched_key is None:
            continue

        # Parse the value (reuse logic from parse_anchored_response)
        parsed_val = _parse_single_value(val_str)
        if parsed_val is not None:
            out[target_req["req_id"]][matched_key] = parsed_val

    # Fill missing sub-scores with 0.0
    for req in requirements:
        for k, _ in req["sub_queries"]:
            out[req["req_id"]].setdefault(k, 0.0)

    return out


def _parse_single_value(val_str: str) -> Optional[float]:
    """Parse one anchored value string. Returns None on failure."""
    import re
    valid_values = {0.0, 0.25, 0.5, 0.75, 1.0}
    text_map = {
        "yes": 1.0, "true": 1.0, "high": 1.0, "strong": 1.0, "very": 1.0, "excellent": 1.0,
        "no": 0.0, "false": 0.0, "low": 0.0, "none": 0.0, "weak": 0.0, "absent": 0.0,
        "partial": 0.5, "medium": 0.5, "moderate": 0.5, "some": 0.5,
        "mostly": 0.75, "tangential": 0.25,
    }

    try:
        v = float(val_str)
    except ValueError:
        v = text_map.get(val_str, None)
        if v is None:
            num_match = re.match(r"(\d+(?:\.\d+)?)", val_str)
            if num_match:
                raw_years = float(num_match.group(1))
                v = 1.0 if raw_years > 0 else 0.0
            else:
                return None

    if v in valid_values:
        return v
    elif 0.0 <= v <= 1.0:
        return min(valid_values, key=lambda x: abs(x - v))
    return 0.0
