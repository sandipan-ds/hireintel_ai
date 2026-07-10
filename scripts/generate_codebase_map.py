"""
generate_codebase_map.py  (v2 — fixed)
Parse graphify-out AST cache → docs/21_CODEBASE_MAP.md

Fixes from v1:
  - Internal imports: match on the underscore-encoded module ID pattern
    (graphify stores cross-module imports as src_scoring_rubric_scorer etc.)
  - Classes: skip nodes whose label looks like a docstring (contains spaces)
  - Functions: include ALL non-file nodes with () label from this file
  - "Referenced by" uses cross-file raw_calls properly
"""

import json
import re
from pathlib import Path
from collections import defaultdict

ROOT       = Path(r"C:\Users\sandi\Desktop\ML Working Folder\hireintel_ai")
CACHE_AST  = ROOT / "graphify-out" / "cache" / "ast"
STAT_INDEX = ROOT / "graphify-out" / "cache" / "stat-index.json"
OUT_FILE   = ROOT / "docs" / "21_CODEBASE_MAP.md"

INCLUDE_PREFIXES = ("src/", "scripts/")

STDLIB = {
    "json","os","sys","re","math","time","datetime","pathlib","logging",
    "typing","collections","itertools","functools","dataclasses","abc",
    "copy","hashlib","uuid","io","tempfile","traceback","warnings",
    "threading","subprocess","shutil","contextlib","enum","inspect",
    "textwrap","string","random","struct","array","heapq","bisect",
    "queue","socket","http","urllib","email","html","xml","csv",
    "zipfile","tarfile","gzip","base64","hmac","secrets","argparse",
    "unittest","pytest","pprint","types","operator","weakref","any",
    "list","dict","set","tuple","int","float","str","bool","bytes",
    "type","object","None","True","False","Optional","Union","List",
    "Dict","Set","Tuple","Any","Callable","Generator","Iterator",
    "Sequence","Mapping","Iterable","TypeVar","Generic","Protocol",
    "NamedTuple","cast","overload","dataclass","field","frozen",
}

# Known third-party packages to label nicely
THIRD_PARTY_TOP = {
    "numpy","pandas","sklearn","scipy","torch","transformers","sentence_transformers",
    "qdrant_client","chromadb","fastapi","uvicorn","flask","sqlalchemy","pydantic",
    "mlflow","click","rich","tqdm","yaml","toml","dotenv","requests","httpx",
    "docling","pdfminer","pytesseract","pdf2image","spacy","nltk","openai",
    "anthropic","ollama","langchain","llama_index","faiss","annoy","pytest",
    "hypothesis","freezegun","mock","starlette","jinja2","aiofiles","anyio",
    "sentence_transformers","FlagEmbedding","transformers",
}

def rel(abs_path: str) -> str:
    p = Path(abs_path)
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return abs_path

# ── Build path → hash map ─────────────────────────────────────────────────────
stat_index = json.loads(STAT_INDEX.read_text(encoding="utf-8"))
path_to_hash: dict[str, str] = {}
for abs_path, meta in stat_index.items():
    r = rel(abs_path)
    if r.endswith(".py") and any(r.startswith(px) for px in INCLUDE_PREFIXES):
        path_to_hash[r] = meta["hash"]

# ── Helper: is a node label a real symbol (not a docstring or file node)? ─────
def is_class_label(label: str) -> bool:
    # Real class: starts uppercase, no spaces, no punctuation except _
    return (
        bool(label)
        and label[0].isupper()
        and " " not in label
        and "(" not in label
        and not label.startswith("_")
        and len(label) < 80
    )

def is_function_label(label: str) -> bool:
    return label.endswith("()") and " " not in label and len(label) < 80

# ── Build module → "src_rag_retriever" style internal ID ─────────────────────
# graphify encodes imports using underscored IDs that reflect the file path
def path_to_graphify_id(rel_path: str) -> str:
    # src/rag/retriever.py → src_rag_retriever
    return rel_path.replace("/", "_").replace(".py", "").replace("-", "_")

internal_ids: dict[str, str] = {}  # graphify_id → rel_path
for rel_path in path_to_hash:
    gid = path_to_graphify_id(rel_path)
    internal_ids[gid] = rel_path

def resolve_target(target: str) -> tuple[str, str]:
    """Returns (kind, display) where kind = 'internal'|'stdlib'|'third_party'."""
    top = target.split(".")[0].split("_")[0]
    # Check internal
    if target in internal_ids:
        return "internal", internal_ids[target]
    # Try prefix match for internal
    for gid, rp in internal_ids.items():
        if target == gid or target.startswith(gid + "_"):
            return "internal", rp
    if top in STDLIB or target in STDLIB:
        return "stdlib", target
    return "third_party", target

# ── Parse each module ─────────────────────────────────────────────────────────
modules: dict[str, dict] = {}

for rel_path, h in sorted(path_to_hash.items()):
    ast_file = CACHE_AST / f"{h}.json"
    if not ast_file.exists():
        continue
    data      = json.loads(ast_file.read_text(encoding="utf-8"))
    nodes     = data.get("nodes", [])
    edges     = data.get("edges", [])
    raw_calls = data.get("raw_calls", [])

    functions: list[tuple[str, str]] = []
    classes:   list[tuple[str, str]] = []

    for node in nodes[1:]:  # skip file node (index 0)
        lbl      = node.get("label", "")
        loc      = node.get("source_location", "")
        src_file = node.get("source_file", "")
        if src_file and rel(src_file) != rel_path:
            continue
        if is_function_label(lbl):
            functions.append((lbl, loc))
        elif is_class_label(lbl):
            classes.append((lbl, loc))

    internal_imports: list[str] = []
    third_party_imports: list[str] = []

    seen = set()
    for edge in edges:
        if edge.get("relation") not in ("imports", "imports_from"):
            continue
        sf = edge.get("source_file", "")
        if sf and rel(sf) != rel_path:
            continue
        target = edge.get("target", "")
        if target in seen:
            continue
        seen.add(target)
        kind, display = resolve_target(target)
        if kind == "internal":
            internal_imports.append(display)
        elif kind == "third_party":
            # Only keep recognisable third-party (skip stdlib noise)
            top_name = display.split(".")[0].split("_")[0]
            if any(display.startswith(tp) for tp in THIRD_PARTY_TOP) or top_name in THIRD_PARTY_TOP:
                third_party_imports.append(display)

    modules[rel_path] = {
        "rel_path":         rel_path,
        "functions":        functions,
        "classes":          classes,
        "internal_imports": sorted(set(internal_imports)),
        "third_party":      sorted(set(third_party_imports)),
        "raw_calls":        raw_calls,
    }

# ── Reverse lookup: which modules call symbols from this module ───────────────
callee_to_callers: dict[str, list[tuple[str, str]]] = defaultdict(list)
for rel_path, info in modules.items():
    for rc in info["raw_calls"]:
        callee = rc.get("callee", "")
        loc    = rc.get("source_location", "")
        callee_to_callers[callee].append((rel_path, loc))

# ── Generate Markdown ─────────────────────────────────────────────────────────
L: list[str] = [
    "# Codebase Map",
    "",
    "> **Auto-generated** from `graphify-out/cache/ast/` AST analysis.",
    "> Re-generate: `python scripts/generate_codebase_map.py`",
    ">",
    "> Each section: defined classes/functions (with line numbers),",
    "> internal module dependencies, third-party dependencies, and",
    "> which modules reference symbols from this module.",
    "",
    "---",
    "",
    "## Module Index",
    "",
    "| Module | Classes | Functions | Internal deps |",
    "|--------|---------|-----------|---------------|",
]

for rel_path in sorted(modules.keys()):
    info  = modules[rel_path]
    short = rel_path.replace("src/", "")
    n_cls = len(info["classes"])
    n_fn  = len(info["functions"])
    n_int = len(info["internal_imports"])
    L.append(f"| `{short}` | {n_cls} | {n_fn} | {n_int} |")

L += ["", "---", ""]

# ── Per-module detail sections ────────────────────────────────────────────────
for rel_path in sorted(modules.keys()):
    info  = modules[rel_path]
    short = rel_path.replace("src/", "")
    heading = short.replace("/", ".").replace(".py", "")

    L.append(f"## `{heading}`")
    L.append(f"**File:** [`{short}`](../{rel_path})")
    L.append("")

    if info["classes"]:
        L.append("**Classes:**")
        for name, loc in sorted(info["classes"], key=lambda x: x[1]):
            L.append(f"- `{name}` — {loc}")
        L.append("")

    if info["functions"]:
        L.append("**Functions / Methods:**")
        # Sort by line number numerically
        def sort_key(item):
            loc = item[1]  # e.g. "L45"
            m = re.match(r"L(\d+)", loc)
            return int(m.group(1)) if m else 9999
        for name, loc in sorted(info["functions"], key=sort_key):
            L.append(f"- `{name}` — {loc}")
        L.append("")

    if info["internal_imports"]:
        L.append("**Imports from (internal modules):**")
        for imp in sorted(info["internal_imports"]):
            imp_short = imp.replace("src/", "")
            L.append(f"- [`{imp_short}`](../{imp})")
        L.append("")

    if info["third_party"]:
        L.append("**Third-party dependencies:**")
        for dep in info["third_party"][:8]:
            L.append(f"- `{dep}`")
        L.append("")

    # Reverse: who uses symbols from this module
    defined_names = {fn.rstrip("()") for fn, _ in info["functions"]} | \
                    {cls for cls, _ in info["classes"]}
    callers_set: set[str] = set()
    for name in defined_names:
        for caller_file, _ in callee_to_callers.get(name, []):
            if caller_file != rel_path:
                callers_set.add(caller_file)
    if callers_set:
        L.append("**Referenced by:**")
        for cf in sorted(callers_set)[:10]:
            cf_short = cf.replace("src/", "")
            L.append(f"- `{cf_short}`")
        L.append("")

    L += ["---", ""]

OUT_FILE.write_text("\n".join(L), encoding="utf-8")
print(f"Written: {OUT_FILE}  ({len(modules)} modules, {OUT_FILE.stat().st_size:,} bytes)")
