"""Audit harness: send REQ-001 rubric scoring to multiple LLMs, check hallucination.

For each backend (Ollama, OpenRouter, opencode.ai):
  1. Build a fresh LLMRubricCaller with that backend.
  2. Run score_requirement_with_rubric on REQ-001 for the first DataScience candidate.
  3. Print sub_scores: key, sub_score, extracted_years, extracted_evidence, cited_text.
  4. Verdict: is cited_text actually present in the retrieved chunks?
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# --- Load env manually ------------------------------------------------------
env = {}
for line in (ROOT / '.env').read_text(encoding='utf-8').splitlines():
    line = line.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    k, _, v = line.partition('=')
    env[k.strip()] = v.strip().strip('"').strip("'")

OPENCODE_API_KEY = env.get('OPENCODE_API_KEY')
OPENCODE_BASE_URL = env.get('base_url', 'https://opencode.ai/zen/v1')
OPENCODE_MODEL = env.get('model', 'MiMo V2.5 Free')

OPENROUTER_API_KEY = env.get('OPENROUTER_API_KEY')
OPENROUTER_BASE_URL = 'https://openrouter.ai/api/v1'  # fix the .env typo inline.
OPENROUTER_MODEL = env.get('MODEL') or 'nvidia/nemotron-3-super-120b-a12b:free'

OLLAMA_MODEL = env.get('ollama_model', 'qwen2.5:3b')
OLLAMA_BASE_URL = env.get('ollama_base_url', 'http://localhost:11434/v1')

# --- Load retriever / candidate / cache -------------------------------------
from src.rag.per_req_retrieval import retrieve_evidence_for_req
from src.rag.retriever import (
    DEFAULT_INDEX_PATH, DEFAULT_MAX_CHUNKS_PER_QUERY,
    DEFAULT_THRESHOLD, ThresholdRetriever, VectorIndex,
)
from src.rag.subquery_cache import SubQueryCache
from src.scoring.rubric_scorer import score_requirement_with_rubric
from src.services.llm_caller import LLMRubricCaller
from src.services.subquery_parser import get_all_role_subqueries

candidates = sorted(
    p for p in Path('data/processed/DataScience').glob('*.json')
    if not p.name.endswith('_intelligence_report.json')
    and not p.name.endswith('_structured_profile.json')
)
if not candidates:
    raise SystemExit('No DataScience candidate parses available.')
cand_path = candidates[0]
print(f"Candidate file: {cand_path.name}")
profile = json.loads(cand_path.read_text(encoding='utf-8'))
print(f"Candidate name: {profile.get('name')!r}")

print(f"\nLoading Recursive embedding index from {DEFAULT_INDEX_PATH} ...")
index = VectorIndex.load_npz(DEFAULT_INDEX_PATH)
retriever = ThresholdRetriever(
    index=index, threshold=DEFAULT_THRESHOLD,
    max_chunks_per_query=DEFAULT_MAX_CHUNKS_PER_QUERY,
)
cache = SubQueryCache.load()
cache.preencode_role('DataScience')
sq_embedder = cache.wrap_embed_sub_queries()

all_subq = get_all_role_subqueries()
role_subq = all_subq['DataScience']
req_block = next(r for r in role_subq['requirements'] if r['req_id'] == 'REQ-001')
print(f"Target REQ: {req_block['name']}")
print(f"  sub-queries: {len(req_block['sub_queries'])}")

# Convert the sub_queries dict list into (key, text) tuples as the
# retriever expects.
sq_pairs = [
    (sq.get('key') or '', sq.get('text') or '')
    for sq in req_block['sub_queries']
]

# Retrieve the evidence chunks. Wrap sub-queries with the per-role cache so the
# embeddings are reusable from the warm cache.
sq_vecs = sq_embedder(sq_pairs)

evidence_chunks = retrieve_evidence_for_req(
    retriever=retriever,
    candidate_id=profile.get('candidate_id') or cand_path.stem,
    sub_queries=sq_pairs,
    sub_query_vectors=sq_vecs,
)
chunks_full_text = "\n".join(c.text for c in evidence_chunks)
print(f"\nRetrieved {len(evidence_chunks)} chunks ({len(chunks_full_text)} chars).")
print("Top chunk cosines:", [round(c.cosine, 4) for c in evidence_chunks[:6]])
print("\nChunk dump (first 600 chars):")
print(chunks_full_text[:600])

# Build the dimension type label the rubric registry expects.
dim_type = "skill"  # REQ-001 ("Python & Data Science Libraries") is a skill REQ.

# Make the SectionEvidence the rubric scorer expects.
from src.rag.section_routed import SectionEvidence
evidence = SectionEvidence(
    requirement_type=dim_type,
    requirement_name=req_block['name'],
    sections=[],
    chunks=evidence_chunks,
    full_text=chunks_full_text,
    chunk_count=len(evidence_chunks),
)
print(f"\nSectionEvidence.full_text length: {len(evidence.full_text)}")

# --- Run the rubric scorer with each backend --------------------------------

backends = []
backends.append(('ollama', 'unused', OLLAMA_BASE_URL, OLLAMA_MODEL, 180))
backends.append(('openrouter', OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL, 300))
backends.append(('opencode', OPENCODE_API_KEY, OPENCODE_BASE_URL, OPENCODE_MODEL, 300))

results = {}
for label, api_key, base_url, model, timeout in backends:
    print(f"\n{'=' * 80}")
    print(f"BACKEND: {label} - model={model}")
    print('=' * 80)
    if not api_key or api_key == 'unused':
        if label != 'ollama':
            print('  SKIP: no API key available.')
            continue
    caller = LLMRubricCaller(
        api_key=api_key, base_url=base_url, model=model, max_tokens=4000, temperature=0.0,
    )
    if not getattr(caller, '_available', False):
        print(f'  SKIP: caller not _available: {caller.base_url}')
        continue
    t0 = time.time()
    try:
        trace = score_requirement_with_rubric(
            requirement_name=req_block['name'],
            dimension_type=dim_type,
            evidence=evidence,
            weight=6.0,
            target_years=3.0,
            llm_caller=caller,
            employment_history=None,
        )
    except Exception as e:
        print(f'  SCORING FAILED: {e}')
        results[label] = {'error': str(e)}
        continue
    dt = time.time() - t0
    print(f'  Latency: {dt:.1f}s')
    print(f'  normalized_score={trace.normalized_score} weighted_score={trace.weighted_score}')
    print(f'  formula={trace.formula}')
    print(f'\n  SUB_SCORES:')
    for s in trace.sub_scores:
        cited = (s.cited_text or '').strip()
        cited_present = cited and cited in evidence.full_text
        verdict = 'CITED_PRESENT' if cited_present else 'CITED_ABSENT'
        if not cited:
            verdict = 'NO_CITE'
        print(f'    {s.key}: sub_score={s.sub_score} years={s.extracted_years} target={3.0}')
        ev = s.extracted_evidence
        print(f'      extracted_evidence: {str(ev)[:160]!r}')
        print(f'      cited_text: {str(cited)[:160]!r}')
        print(f'      VERDICT: {verdict}')
    results[label] = {
        'latency_s': dt,
        'normalized_score': trace.normalized_score,
        'weighted_score': trace.weighted_score,
        'sub_scores': [
            {
                'key': s.key, 'sub_score': s.sub_score,
                'extracted_years': s.extracted_years,
                'extracted_evidence': (str(s.extracted_evidence)[:300] if s.extracted_evidence is not None else None),
                'cited_text': (str(s.cited_text)[:300] if s.cited_text is not None else None),
                'cited_present_in_chunks': bool((s.cited_text or '').strip() and (s.cited_text or '').strip() in evidence.full_text),
            } for s in trace.sub_scores
        ],
    }

Path('scripts/_audit_results.json').write_text(
    json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8',
)
print('\n\nWrote scripts/_audit_results.json')