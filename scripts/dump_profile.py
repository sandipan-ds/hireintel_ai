"""Dump the candidate profile structure + experience + skills of 06f12df20c0ed54e."""
import json
from pathlib import Path

path = Path('data/processed/DataScience/06f12df20c0ed54e.json')
profile = json.loads(path.read_text(encoding='utf-8'))
print(f"Top-level keys: {list(profile.keys())}")
print(f"Type of profile['experience']: {type(profile.get('experience')).__name__}")
exp = profile.get('experience')
if isinstance(exp, dict):
    print(f"  experience keys: {list(exp.keys())}")
    entries = exp.get('entries') or exp.get('items') or exp.get('list')
else:
    entries = exp  # may be a list directly
print(f"  entries type: {type(entries).__name__}, n={len(entries) if hasattr(entries, '__len__') else 'n/a'}")
if isinstance(entries, list) and entries:
    print(f"  first entry type: {type(entries[0]).__name__}")
    print(f"  first entry keys: {list(entries[0].keys()) if isinstance(entries[0], dict) else 'n/a'}")
    print(f"  first entry sample (300 chars): {json.dumps(entries[0])[:400]}")
    print()
    print('  experience[*] all first 3:')
    for i, e in enumerate(entries[:3]):
        print(f"    [{i}]: {json.dumps(e)[:400]}")

print()
print(f"Type of profile['skills']: {type(profile.get('skills')).__name__}")
print(f"  skills value: {json.dumps(profile.get('skills'))[:400]}")
print()
print(f"Type of profile['summary']: {type(profile.get('summary')).__name__}")
print(f"  summary value: {json.dumps(profile.get('summary'))[:400]}")
