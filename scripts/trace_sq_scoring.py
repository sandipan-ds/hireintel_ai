"""Trace SQ classification + actual years extraction for DataScience REQ-001.

Uses the first candidate currently present under data/processed/DataScience/
so the trace is runnable in any checkout state.
"""
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, '.')
from src.scoring.unified_scorer import (
    _is_binary_subquery,
    _is_years_subquery,
    _score_presence_sq,
    _score_years_sq,
)
from src.services.subquery_parser import get_all_role_subqueries

# Use the first non-downstream DataScience parse available.
candidates = sorted(
    p for p in glob.glob('data/processed/DataScience/*.json')
    if not p.endswith('_intelligence_report.json')
    and not p.endswith('_structured_profile.json')
)
if not candidates:
    raise SystemExit('No DataScience candidate parses found.')
path = Path(candidates[0])
print(f'Using candidate file: {path.name}')
with path.open(encoding='utf-8') as f:
    profile = json.load(f)

all_roles = get_all_role_subqueries()
ds = all_roles['DataScience']
for r in ds['requirements']:
    if r['req_id'] == 'REQ-001':
        print(f"REQ-001: {r['name']}")
        print('Sub-queries:')
        for sq in r['sub_queries']:
            sq_t = sq.get('type', '')
            is_y = _is_years_subquery(sq)
            is_b = _is_binary_subquery(sq)
            print(f"  {sq.get('key')}: type={sq_t!r} is_years={is_y} is_binary={is_b}")
            print(f"    text: {sq.get('text')[:120]}")
            if is_b:
                score = _score_presence_sq(sq, requirement_name=r['name'], profile=profile)
                print(f'    -> presence score = {score}')
            elif is_y:
                score, years, expected = _score_years_sq(sq, requirement_name=r['name'], profile=profile)
                print(f'    -> years score={score} years_detected={years} expected={expected}')
        break

print()
print('Profile snippets relevant to Python:')
exp = profile.get('experience', [])
for i, job in enumerate(exp[:5]):
    txt = json.dumps(job)[:200]
    print(f'  exp[{i}]: {txt}')
skills = profile.get('skills', [])
print(f'  skills: {json.dumps(skills)[:200]}')
