"""Find malformed DataScience processed JSONs."""
import json, pathlib

role = 'DataScience'
parse_errors = []
for f in sorted(pathlib.Path(f'data/processed/{role}').glob('*.json')):
    try:
        json.load(open(f))
    except Exception as e:
        parse_errors.append((f, e))

print(f"Parse errors: {len(parse_errors)}")
for f, e in parse_errors:
    print(f"\nFILE: {f.name}  ({f.stat().st_size} bytes)")
    print(f"Error: {e}")
    raw = open(f, encoding='utf-8', errors='replace').read(300)
    print(f"First 300 chars: {repr(raw)}")
