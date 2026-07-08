"""Full trace of SQ004 years-extraction failure for DataScience REQ-001."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, '.')
from src.scoring.graded_scorer import (
    _aliases_for,
    _detect_years_in_text,
    _search_profile,
    _summary_text,
    _SYNONYMS,
    _YEARS_RE,
)

candidate_path = Path('data/processed/DataScience/06f12df20c0ed54e.json')
profile = json.loads(candidate_path.read_text(encoding='utf-8'))

req_name = "Python & Data Science Libraries (pandas, NumPy, scikit-learn, TensorFlow, PyTorch)"
patterns = _aliases_for(req_name)

print("=" * 80)
print("ALIAS PATTERNS GENERATED FOR REQ-001:")
print("=" * 80)
for i, p in enumerate(patterns):
    print(f"  [{i}] {p.pattern!r}  flags={p.flags}")

print()
print("=" * 80)
print("EXPERIENCE ENTRIES (details):")
print("=" * 80)
entries = profile.get('experience', {}).get('entries', [])
for i, entry in enumerate(entries):
    details = entry.get('details') or []
    section_text = " | ".join(str(d) for d in details if d)
    print(f"  Entry [{i}]: title={entry.get('title')!r} dates={entry.get('dates')!r}")
    for j, line in enumerate(details):
        match = any(p.search(line) for p in patterns)
        mark = " <== MATCH" if match else ""
        print(f"    detail[{j}]: {line!r}{mark}")
    # Does any line match?
    any_match = False
    for line in details:
        if isinstance(line, str) and any(p.search(line) for p in patterns):
            any_match = True
            break
    if not any_match:
        print(f"    -> NO experience entry [{i}] matches any alias pattern")
    else:
        years = _detect_years_in_text(section_text, patterns)
        print(f"    -> matched; years_detected in section_text = {years}")

print()
print("=" * 80)
print("SKILLS SECTION:")
print("=" * 80)
skills = profile.get('skills') or []
skills_text = " | ".join(str(s) for s in skills) if isinstance(skills, list) else str(skills)
print(f"  skills list (first 10): {skills[:10]}")
print(f"  joined skills_text (first 300 chars): {skills_text[:300]!r}")
for p in patterns:
    m = p.search(skills_text)
    if m:
        print(f"  PATTERN MATCH: {p.pattern!r} at pos {m.start()}: ...{skills_text[max(0,m.start()-20):m.end()+20]}...")
    else:
        print(f"  no match: {p.pattern!r}")

years_in_skills = _detect_years_in_text(skills_text, patterns)
print(f"  -> years_detected in skills_text = {years_in_skills}")

print()
print("=" * 80)
print("YEARS REGEX (_YEARS_RE) MATCHES IN SKILLS_TEXT:")
print("=" * 80)
for m in _YEARS_RE.finditer(skills_text):
    print(f"  match: {m.group()!r} num={m.group('num')!r} pos={m.start()}")
    window = skills_text[max(0, m.start()-80): m.end()+80]
    near_alias = any(p.search(window) for p in patterns)
    print(f"  alias-near? {near_alias}")
if not list(_YEARS_RE.finditer(skills_text)):
    print("  (no 'N year(s)' phrases found anywhere in skills_text)")

print()
print("=" * 80)
print("SUMMARY TEXT:")
print("=" * 80)
summary = _summary_text(profile)
print(f"  summary = {summary!r}")
years_in_summary = _detect_years_in_text(summary, patterns)
print(f"  -> years_detected in summary = {years_in_summary}")

print()
print("=" * 80)
print("FULL _search_profile RESULT:")
print("=" * 80)
result = _search_profile(profile, patterns, allow_summary_years=True)
print(f"  matched={result[0]} section={result[1]!r} snippet={result[2][:100]!r} years={result[3]}")
print()
print("CONCLUSION:")
print(f"  years_detected = {result[3]}")
print(f"  expected_years from SQ text = 3.0")
print(f"  code_only_score for SQ004 = min({result[3]}/3, 1.0) = {min(result[3]/3, 1.0) if result[3] > 0 else 0.0}")