"""Test batched scoring: 15 REQs in 1 LLM call."""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.services.scoring_pipeline import score_candidate_batched_end_to_end
from src.services.llm_caller import LLMRubricCaller

# Clear cache for clean test
cache_path = Path("data/embeddings/llm_cache.jsonl")
if cache_path.exists():
    cache_path.unlink()

caller = LLMRubricCaller()
print(f"Model: {caller.model_name}\n")

candidate_id = "cand_433d020a3cd7"
role = "BusinessAnalyst"
config_name = "Business_Analyst"

print("=" * 70)
print("BATCHED SCORING: 1 LLM call for all 15 REQs")
print("=" * 70)
t = time.time()
result = score_candidate_batched_end_to_end(
    role=role,
    candidate_id=candidate_id,
    config_name=config_name,
    llm_caller=caller,
)
dt = time.time() - t
print(f"  Time: {dt:.1f}s (one LLM call covers all 15 REQs)")
print(f"  Total: {result.total:.3f} / 100")
print(f"  Total raw: {result.total_raw:.2f}, max: {result.total_max:.2f}")
print(f"  Flagged institute: {result.has_flagged_institute}")
print()
print("  Per-category breakdown:")
for cat in result.categories:
    if cat.items:
        print(f"    {cat.name:30s}: {cat.score:5.2f} / {cat.max_score:5.1f}  ({len(cat.items)} items)")
        for item in cat.items:
            mode = item.scoring_mode
            print(f"      [{mode:11s}] {item.item_name[:40]:40s} = {item.raw_score:5.2f}  (importance={item.importance:.1f}%)")

print()
print("=" * 70)
print("Second call — should be cache hits for LLM parts, instant")
print("=" * 70)
t = time.time()
result2 = score_candidate_batched_end_to_end(
    role=role,
    candidate_id=candidate_id,
    config_name=config_name,
    llm_caller=caller,
)
dt2 = time.time() - t
print(f"  Time: {dt2:.2f}s")
print(f"  Total: {result2.total:.3f}  (expected == {result.total:.3f})")
print(f"  Match: {abs(result.total - result2.total) < 0.01}")
