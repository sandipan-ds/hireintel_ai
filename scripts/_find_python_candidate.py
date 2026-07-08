import json, glob, sys
sys.path.insert(0, '.')

files = sorted(p for p in glob.glob('data/processed/DataScience/*.json')
    if not p.endswith('_intelligence_report.json')
    and not p.endswith('_structured_profile.json'))

found = []
for f in files:
    d = json.loads(open(f, encoding='utf-8').read())
    exp = d.get('experience', {})
    entries = exp.get('entries', []) if isinstance(exp, dict) else (exp if isinstance(exp, list) else [])
    for e in entries:
        details = e.get('details', [])
        text = ' '.join(str(x) for x in details).lower()
        if 'python' in text and e.get('dates'):
            print(f"{f}: title={e.get('title')} dates={e.get('dates')}")
            break
    if len(found) >= 5:
        break
