"""Ad-hoc investigation of DataScience_ranked.json zero-evidence REQs."""
import json

data = json.load(open('data/scores/composed/DataScience_ranked.json'))
for cand in data['rankings']:
    print(f"Candidate: {cand['candidate_id']} total: {cand['total']}")
    chunk_counts = {'0': 0, '1-2': 0, '3+': 0}
    for req in cand['reqs']:
        rubric_skipped = req['rubric_skipped']
        rubric_part = req['rubric_llm_part']
        code_part = req['code_only_part']
        sub = req['sub_score']
        chunks = req['retrieved_chunk_count']
        rubric_has = bool(req['rubric_sq_scores'])
        zero_evidence = rubric_has and rubric_part == 0.0 and not rubric_skipped
        marker = ' <== ZERO_EVIDENCE' if zero_evidence else ''
        if chunks == 0:
            chunk_counts['0'] += 1
        elif chunks <= 2:
            chunk_counts['1-2'] += 1
        else:
            chunk_counts['3+'] += 1
        print(f"  {req['requirement_id']}: chunks={chunks} code_only={code_part}"
              f" rubric={rubric_part}{' SKIP' if rubric_skipped else ''} sub={sub}{marker}")
    print()
    print('Chunk-count distribution:', chunk_counts)
    print()
    # Drill into REQ-001 and REQ-004 specifically.
    for req in cand['reqs']:
        if req['requirement_id'] in ('REQ-001', 'REQ-004', 'REQ-013'):
            print(f"--- {req['requirement_id']}: {req['requirement_name']}")
            print(f"  code_only_sq_scores: {req['code_only_sq_scores']}")
            print(f"  rubric_sq_scores: {req['rubric_sq_scores']}")
            print(f"  code_only_part: {req['code_only_part']}")
            print(f"  rubric_llm_part: {req['rubric_llm_part']}")
            print(f"  sub_score: {req['sub_score']}")
            print(f"  contribution: {req['contribution']}")
            trace = req.get('rubric_trace') or {}
            print(f"  formula: {trace.get('formula')}")
            print(f"  sections_read: {trace.get('sections_read')}")
            print(f"  chunk_ids: {trace.get('chunk_ids')}")
            for s in trace.get('sub_scores', []):
                print(f"    {s['key']}: sub={s['sub_score']} years={s.get('extracted_years')} target={s.get('target_years')} ev={s.get('extracted_evidence')}")
            print()
