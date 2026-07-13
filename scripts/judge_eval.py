"""Judge LLM Evaluation Script -- scripts/judge_eval.py

PURPOSE
-------
Validates the scorer LLM rubric scores by having a stronger judge LLM
independently re-score a random 20% sample of each role's candidates from the
same extracted text that the scorer used (evidence chunks + raw text).

The judge receives:
  - The full job requirements rubric (requirement name, weight, sub-queries)
  - The candidate's extracted resume text (raw_text from processed JSON)
  - Instructions to return per-requirement sub_scores in a fixed JSON schema

Metrics computed per role:
  - MAE   (Mean Absolute Error on total_score)
  - RMSE  (Root Mean Squared Error on total_score)
  - R2    (coefficient of determination)
  - Bias  (mean signed error: positive = scorer over-scores vs judge)
  - Per-REQ MAE (which requirements have most disagreement)
  - Human-review flags for candidates where |scorer - judge| > 10 pts

Config is read exclusively from .env.audit (NOT .env).

DO NOT RUN until the main scoring batch has finished.
Run: python scripts/judge_eval.py [--role ROLE ...] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import pathlib
import random
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("judge_eval")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = pathlib.Path(__file__).parent.parent.resolve()
ENV_AUDIT = ROOT / ".env.audit"
SCORES_DIR = ROOT / "data" / "scores" / "composed"
PROCESSED_DIR = ROOT / "data" / "processed"
JD_DIR = ROOT / "data" / "job_descriptions"
REPORT_DIR = ROOT / "reports" / "judge_eval"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# .env.audit loader (no python-dotenv dependency)
# ---------------------------------------------------------------------------

def _load_env_audit(path: pathlib.Path) -> Dict[str, str]:
    """Parse key=value pairs from .env.audit, ignoring comment lines."""
    env: Dict[str, str] = {}
    if not path.exists():
        raise FileNotFoundError(f".env.audit not found: {path}")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        env[key.strip()] = val.strip().strip('"').strip("'")
    return env


# ---------------------------------------------------------------------------
# Role/candidate discovery
# ---------------------------------------------------------------------------

def discover_scored_roles() -> List[str]:
    """Return all roles that have at least one per-candidate score file."""
    if not SCORES_DIR.exists():
        return []
    return [d.name for d in sorted(SCORES_DIR.iterdir())
            if d.is_dir() and any(d.glob("*.json"))]


def sample_candidates(role: str, pct: float, seed: int = 42) -> List[pathlib.Path]:
    """
    Return a reproducible random sample (pct%) of score files for a role.

    Args:
        role: Role folder name.
        pct:  Fraction to sample, e.g. 0.20.
        seed: Random seed.

    Returns:
        List of Path objects to sampled score JSON files.
    """
    files = sorted((SCORES_DIR / role).glob("*.json"))
    if not files:
        return []
    n = max(1, math.ceil(len(files) * pct))
    return random.Random(seed).sample(files, min(n, len(files)))


# ---------------------------------------------------------------------------
# Config loaders
# ---------------------------------------------------------------------------

def load_weight_config(role: str) -> List[Dict[str, Any]]:
    """
    Load requirements_weights from the role WeightConfig JSON.

    Returns:
        List of dicts: requirement_id, requirement_name, category,
        weight_percentage.

    Raises:
        FileNotFoundError: If no WeightConfig JSON exists for the role.
    """
    wc_files = sorted((JD_DIR / role).glob("*_WeightConfig_*.json"))
    if not wc_files:
        raise FileNotFoundError(f"No WeightConfig JSON in {JD_DIR / role}")
    wc = json.loads(wc_files[0].read_text(encoding="utf-8"))
    return wc.get("requirements_weights", [])


def load_subqueries(role: str) -> Dict[str, List[Dict[str, str]]]:
    """
    Load sub-queries keyed by requirement ID via src.services.subquery_parser.

    Returns:
        Dict mapping req_id -> list of {"key": str, "text": str}.
        Empty dict on failure.
    """
    try:
        sys.path.insert(0, str(ROOT))
        from src.services.subquery_parser import get_role_subquery  # type: ignore
        sqs = get_role_subquery(role)
        return {
            req["req_id"]: [
                {"key": sq.get("key", ""), "text": sq.get("text", "")}
                for sq in req.get("sub_queries", [])
            ]
            for req in sqs.get("requirements", [])
        }
    except Exception as exc:
        logger.warning("Could not load sub-queries: %s", exc)
        return {}


def load_processed_text(role: str, candidate_id: str) -> str:
    """
    Return the extracted plain-text resume for a candidate.

    Primary source: raw["raw_text"] in processed JSON.
    Fallback: concatenated evidence_chunks.

    Args:
        role:         Role name.
        candidate_id: Candidate identifier.

    Returns:
        Resume text string, or empty string if not found.
    """
    f = PROCESSED_DIR / role / f"{candidate_id}.json"
    if not f.exists():
        logger.warning("Processed file not found: %s", f)
        return ""
    data = json.loads(f.read_text(encoding="utf-8"))
    raw_text = data.get("raw", {}).get("raw_text", "")
    if raw_text and raw_text.strip():
        return raw_text.strip()
    chunks = data.get("evidence_chunks", [])
    return "\n\n".join(c.get("text", "") for c in chunks if c.get("text"))


# ---------------------------------------------------------------------------
# Judge prompt
# ---------------------------------------------------------------------------

_JUDGE_SYSTEM = """\
You are an expert resume evaluator. You will receive a candidate's resume text
and a rubric with sub-questions. Evaluate how well the candidate meets each
requirement by scoring each sub-question.

Sub-score scale per sub-question:
  0.0  = No evidence in the resume
  0.25 = Very weak or indirect evidence
  0.5  = Moderate / partial evidence
  1.0  = Clear, strong evidence

Binary presence questions ("Is there evidence of X?"):
  Use ONLY 0.0 or 1.0.

Return a single valid JSON object with this exact schema:
{
  "candidate_id": "<string>",
  "requirements": [
    {
      "requirement_id": "<string>",
      "sub_scores": { "<SQ_key>": <float 0.0-1.0>, ... },
      "sub_score_sum": <float>,
      "notes": "<optional 1-sentence rationale>"
    }
  ]
}

No text outside the JSON. Score every requirement in the rubric.
"""


def _build_judge_prompt(
    candidate_id: str,
    resume_text: str,
    requirements: List[Dict[str, Any]],
    subqueries: Dict[str, List[Dict[str, str]]],
) -> str:
    """
    Build the user-turn prompt containing the resume and rubric.

    Args:
        candidate_id: Candidate identifier.
        resume_text:  Plain-text resume content (truncated to 6000 chars).
        requirements: Requirement dicts from weight config.
        subqueries:   Sub-query dict from load_subqueries().

    Returns:
        Formatted prompt string.
    """
    if len(resume_text) > 6000:
        resume_text = resume_text[:6000] + "\n...[truncated]"

    rubric_lines = ["## RUBRIC\n"]
    for req in requirements:
        rid = req.get("requirement_id", "")
        rubric_lines.append(
            f"### {rid}: {req.get('requirement_name','')}  "
            f"[{req.get('category','')}]  weight={req.get('weight_percentage',0)}%"
        )
        for sq in subqueries.get(rid, []):
            rubric_lines.append(f"  - {sq['key']}: {sq['text']}")
        rubric_lines.append("")

    return (
        f"## CANDIDATE ID: {candidate_id}\n\n"
        f"## RESUME TEXT\n```\n{resume_text}\n```\n\n"
        + "\n".join(rubric_lines)
        + "\nEvaluate the candidate and return JSON only."
    )


# ---------------------------------------------------------------------------
# LLM caller
# ---------------------------------------------------------------------------

def call_judge_llm(
    system_prompt: str,
    user_prompt: str,
    model: str,
    api_key: str,
    base_url: str,
    temperature: float = 0.1,
    max_retries: int = 3,
) -> Optional[str]:
    """
    POST to OpenRouter-compatible chat completions endpoint.

    Args:
        system_prompt: System message content.
        user_prompt:   User message content.
        model:         OpenRouter model slug.
        api_key:       API key.
        base_url:      Base API URL.
        temperature:   Sampling temperature (low = consistent).
        max_retries:   Retry count on transient errors.

    Returns:
        Raw model response string, or None on all retries failing.
    """
    import httpx

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://hireintel.ai",
        "X-Title": "HireIntel Judge Eval",
    }
    payload = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    for attempt in range(1, max_retries + 1):
        try:
            resp = httpx.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=120.0,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            wait = 2 ** attempt
            logger.warning("Judge attempt %d/%d failed: %s -- retry in %ds",
                           attempt, max_retries, exc, wait)
            if attempt < max_retries:
                time.sleep(wait)
    return None


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

def parse_judge_response(
    raw: str,
    expected_req_ids: List[str],
) -> Optional[Dict[str, Any]]:
    """
    Extract and validate the JSON object from a judge LLM response.

    Handles markdown code fences gracefully. Warns on missing requirement IDs.

    Args:
        raw:              Raw response string.
        expected_req_ids: Requirement IDs that should appear in the response.

    Returns:
        Parsed dict, or None if parsing fails.
    """
    if not raw:
        return None
    cleaned = re.sub(r"```(?:json)?", "", raw).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}") + 1
    if start < 0 or end <= start:
        logger.warning("No JSON object in judge response")
        return None
    try:
        data = json.loads(cleaned[start:end])
    except json.JSONDecodeError as exc:
        logger.warning("JSON parse error: %s", exc)
        return None
    returned = {r.get("requirement_id") for r in data.get("requirements", [])}
    missing = set(expected_req_ids) - returned
    if missing:
        logger.warning("Judge missing REQs: %s", sorted(missing))
    return data


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _sub_score_sum(judge_req: Dict[str, Any]) -> float:
    """
    Return the judge's sub_score_sum for a requirement.

    Uses the explicit field if present; otherwise sums sub_scores dict.
    """
    if judge_req.get("sub_score_sum") is not None:
        return float(judge_req["sub_score_sum"])
    return sum(float(v) for v in (judge_req.get("sub_scores") or {}).values())


def compute_judge_total(
    judge_reqs: List[Dict[str, Any]],
    weight_config: List[Dict[str, Any]],
) -> float:
    """
    Recompute total score from judge sub_score_sums using weight config.

    Mirrors the scorer formula:
        contribution = weight_pct * (sub_score_sum / n_sub_queries)
        total = sum(contributions)

    Args:
        judge_reqs:    Requirement list from parsed judge response.
        weight_config: Weight config requirement list.

    Returns:
        Recomputed total score as float.
    """
    judge_map = {r.get("requirement_id"): r for r in judge_reqs}
    total = 0.0
    for req in weight_config:
        rid = req.get("requirement_id")
        weight_pct = float(req.get("weight_percentage", 0))
        jr = judge_map.get(rid)
        if not jr:
            continue
        sqs = jr.get("sub_scores") or {}
        n = len(sqs)
        s_sum = _sub_score_sum(jr)
        total += weight_pct * (s_sum / n) if n > 0 else 0.0
    return round(total, 4)


def compute_metrics(pairs: List[Tuple[float, float]]) -> Dict[str, float]:
    """
    Compute MAE, RMSE, R2, bias, and max deviation from (scorer, judge) pairs.

    Args:
        pairs: List of (scorer_total, judge_total).

    Returns:
        Dict: mae, rmse, r2, bias, max_dev, n.
    """
    if not pairs:
        return {"mae": 0.0, "rmse": 0.0, "r2": 0.0, "bias": 0.0, "max_dev": 0.0, "n": 0}
    n = len(pairs)
    errors = [s - j for s, j in pairs]
    abs_err = [abs(e) for e in errors]
    mae = sum(abs_err) / n
    rmse = math.sqrt(sum(e ** 2 for e in errors) / n)
    bias = sum(errors) / n
    max_dev = max(abs_err)
    judge_vals = [j for _, j in pairs]
    j_mean = sum(judge_vals) / n
    ss_res = sum((s - j) ** 2 for s, j in pairs)
    ss_tot = sum((j - j_mean) ** 2 for j in judge_vals)
    r2 = 1 - ss_res / ss_tot if ss_tot > 1e-9 else 1.0
    return {
        "mae": round(mae, 4), "rmse": round(rmse, 4), "r2": round(r2, 4),
        "bias": round(bias, 4), "max_dev": round(max_dev, 4), "n": n,
    }


def compute_per_req_mae(
    req_pairs: Dict[str, List[Tuple[float, float]]],
) -> Dict[str, float]:
    """
    Compute per-requirement MAE between scorer and judge sub_score_sums.

    Args:
        req_pairs: req_id -> list of (scorer_sub, judge_sub).

    Returns:
        Dict: req_id -> MAE float.
    """
    return {
        rid: round(sum(abs(s - j) for s, j in p) / len(p), 4)
        for rid, p in req_pairs.items() if p
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _bar(val: float, max_val: float = 2.0, width: int = 20) -> str:
    filled = int(min(val / max_val, 1.0) * width)
    return "[" + "#" * filled + "." * (width - filled) + "]"


def generate_report(
    role_results: Dict[str, Any],
    model_name: str,
    sample_pct: float,
    output_path: pathlib.Path,
) -> None:
    """
    Write a human-readable evaluation report to a text file.

    Args:
        role_results: Dict mapping role -> result dict from evaluate_role().
        model_name:   Judge model slug string.
        sample_pct:   Fraction sampled (e.g. 0.20).
        output_path:  Output .txt file path.
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "=" * 72,
        "HIREINTEL JUDGE EVALUATION REPORT",
        f"Generated : {ts}",
        f"Judge LLM : {model_name}",
        f"Sample    : {int(sample_pct * 100)}% of each role's scored candidates",
        "=" * 72, "",
    ]

    hdr = (f"{'Role':<22} | {'N':>4} | {'MAE':>6} | {'RMSE':>6} |"
           f" {'R2':>6} | {'Bias':>6} | {'MaxDev':>7} | {'Flags':>5}")
    lines += [hdr, "-" * 75]

    all_pairs: List[Tuple[float, float]] = []
    for role, res in sorted(role_results.items()):
        m = res["metrics"]
        flags = len(res.get("flagged_for_review", []))
        lines.append(
            f"{role:<22} | {m['n']:>4} | {m['mae']:>6.2f} | {m['rmse']:>6.2f} |"
            f" {m['r2']:>6.3f} | {m['bias']:>+6.2f} | {m['max_dev']:>7.2f} | {flags:>5}"
        )
        all_pairs.extend(res.get("pairs", []))

    lines.append("-" * 75)
    if all_pairs:
        ov = compute_metrics(all_pairs)
        lines.append(
            f"{'OVERALL':<22} | {ov['n']:>4} | {ov['mae']:>6.2f} | {ov['rmse']:>6.2f} |"
            f" {ov['r2']:>6.3f} | {ov['bias']:>+6.2f} | {ov['max_dev']:>7.2f} |"
        )
    lines.append("")

    for role, res in sorted(role_results.items()):
        m = res["metrics"]
        lines += [
            f"\n{'='*72}", f"ROLE: {role}", f"{'='*72}",
            f"  Candidates sampled : {m['n']}",
            f"  MAE                : {m['mae']:.2f} pts",
            f"  RMSE               : {m['rmse']:.2f} pts",
            f"  R2                 : {m['r2']:.3f}",
            f"  Bias               : {m['bias']:+.2f} pts "
            f"({'scorer over-scores' if m['bias'] > 0 else 'scorer under-scores'})",
            f"  Max deviation      : {m['max_dev']:.2f} pts",
        ]

        pr = res.get("per_req_mae", {})
        if pr:
            lines += ["\n  Per-REQ MAE (highest disagreement first):",
                      f"    {'REQ':<12} | {'MAE':>6} | Bar", f"    {'-'*42}"]
            for rid, mae in sorted(pr.items(), key=lambda x: -x[1]):
                lines.append(f"    {rid:<12} | {mae:>6.3f} | {_bar(mae)}")

        cs = res.get("candidate_scores", [])
        if cs:
            lines += ["\n  Candidate Scores (scorer vs judge):",
                      f"    {'Candidate':<30} | {'Scorer':>7} | {'Judge':>7} | {'Delta':>7} | Note",
                      f"    {'-'*72}"]
            for c in sorted(cs, key=lambda x: -abs(x["delta"])):
                note = " <-- REVIEW" if c.get("flagged") else ""
                lines.append(
                    f"    {c['candidate_id']:<30} | {c['scorer_total']:>7.2f} |"
                    f" {c['judge_total']:>7.2f} | {c['delta']:>+7.2f} |{note}"
                )

        flagged = res.get("flagged_for_review", [])
        if flagged:
            lines.append(f"\n  ** {len(flagged)} flagged (|delta| > 10 pts):")
            for f in flagged:
                lines.append(f"    {f['candidate_id']}  scorer={f['scorer_total']:.1f}"
                             f"  judge={f['judge_total']:.1f}  delta={f['delta']:+.1f}")

    lines += ["", "=" * 72, "END OF REPORT", "=" * 72]
    text = "\n".join(lines)
    output_path.write_text(text, encoding="utf-8")
    logger.info("Report written -> %s", output_path)
    print("\n" + text)


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------

def generate_plots(
    role_results: Dict[str, Any],
    output_dir: pathlib.Path,
    ts: str,
) -> None:
    """
    Generate and save evaluation plots:
      - summary_metrics.png : MAE / RMSE / R² bar chart per role
      - scatter_{role}.png  : scorer vs judge scatter per role
      - req_mae_{role}.png  : per-requirement MAE bar chart per role

    Args:
        role_results: Dict mapping role -> result dict from evaluate_role().
        output_dir:   Directory to save plots.
        ts:           Timestamp string for filenames.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")  # headless, no display needed
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        import numpy as np
    except ImportError:
        logger.warning("matplotlib not installed -- skipping plots")
        return

    roles = sorted(role_results.keys())

    # ------------------------------------------------------------------
    # 1. Summary metrics bar chart (MAE, RMSE, R²) across all roles
    # ------------------------------------------------------------------
    metrics_data = {
        r: role_results[r]["metrics"] for r in roles
        if role_results[r]["metrics"]["n"] > 0
    }
    if metrics_data:
        x = np.arange(len(metrics_data))
        width = 0.25
        fig, axes = plt.subplots(1, 2, figsize=(14, 5))
        fig.suptitle("Judge Evaluation — Score Agreement per Role", fontsize=14, fontweight="bold")

        # Left: MAE and RMSE
        ax = axes[0]
        maes  = [metrics_data[r]["mae"]  for r in metrics_data]
        rmses = [metrics_data[r]["rmse"] for r in metrics_data]
        biases = [metrics_data[r]["bias"] for r in metrics_data]
        ax.bar(x - width, maes,   width, label="MAE",  color="steelblue",  alpha=0.85)
        ax.bar(x,          rmses,  width, label="RMSE", color="darkorange", alpha=0.85)
        ax.bar(x + width,  biases, width, label="Bias", color="seagreen",   alpha=0.85)
        ax.set_xticks(x)
        ax.set_xticklabels(list(metrics_data.keys()), rotation=30, ha="right", fontsize=9)
        ax.set_ylabel("Points (0-100 scale)")
        ax.set_title("MAE / RMSE / Bias per Role")
        ax.legend()
        ax.axhline(0, color="black", linewidth=0.7, linestyle="--")
        ax.grid(axis="y", alpha=0.3)

        # Right: R²
        ax2 = axes[1]
        r2s = [metrics_data[r]["r2"] for r in metrics_data]
        bars = ax2.bar(x, r2s, 0.5,
                       color=["forestgreen" if v >= 0.7 else "goldenrod" if v >= 0.4 else "tomato"
                              for v in r2s],
                       alpha=0.85)
        ax2.set_xticks(x)
        ax2.set_xticklabels(list(metrics_data.keys()), rotation=30, ha="right", fontsize=9)
        ax2.set_ylabel("R² (coefficient of determination)")
        ax2.set_title("R² per Role  (≥0.7 = good, ≥0.4 = moderate)")
        ax2.set_ylim(-0.1, 1.05)
        ax2.axhline(0.7, color="forestgreen", linewidth=1, linestyle="--", alpha=0.5, label="0.7 threshold")
        ax2.axhline(0.4, color="goldenrod",   linewidth=1, linestyle="--", alpha=0.5, label="0.4 threshold")
        ax2.legend(fontsize=8)
        ax2.grid(axis="y", alpha=0.3)
        for bar, v in zip(bars, r2s):
            ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                     f"{v:.3f}", ha="center", va="bottom", fontsize=8)

        plt.tight_layout()
        out = output_dir / f"summary_metrics_{ts}.png"
        plt.savefig(out, dpi=130, bbox_inches="tight")
        plt.close()
        logger.info("Plot -> %s", out)

    # ------------------------------------------------------------------
    # 2. Scatter plot: scorer vs judge per role
    # ------------------------------------------------------------------
    for role in roles:
        cs = role_results[role].get("candidate_scores", [])
        if not cs:
            continue
        scorer_vals = [c["scorer_total"] for c in cs]
        judge_vals  = [c["judge_total"]  for c in cs]
        deltas      = [c["delta"]        for c in cs]
        flagged     = [c["flagged"]      for c in cs]

        fig, ax = plt.subplots(figsize=(7, 6))
        colors = ["tomato" if f else "steelblue" for f in flagged]
        ax.scatter(judge_vals, scorer_vals, c=colors, alpha=0.75, edgecolors="white", s=70)

        # Perfect agreement line
        mn = min(min(scorer_vals), min(judge_vals)) - 3
        mx = max(max(scorer_vals), max(judge_vals)) + 3
        ax.plot([mn, mx], [mn, mx], "k--", linewidth=1, alpha=0.5, label="Perfect agreement")

        m = role_results[role]["metrics"]
        ax.set_xlabel("Judge Score", fontsize=11)
        ax.set_ylabel("Scorer Score", fontsize=11)
        ax.set_title(
            f"{role} — Scorer vs Judge\n"
            f"MAE={m['mae']:.2f}  RMSE={m['rmse']:.2f}  R²={m['r2']:.3f}  Bias={m['bias']:+.2f}",
            fontsize=11,
        )
        red_patch  = mpatches.Patch(color="tomato",    label=f"Flagged |Δ|>10  (n={sum(flagged)})")
        blue_patch = mpatches.Patch(color="steelblue", label=f"Normal  (n={len(cs)-sum(flagged)})")
        ax.legend(handles=[red_patch, blue_patch], fontsize=9)
        ax.grid(alpha=0.3)
        plt.tight_layout()
        out = output_dir / f"scatter_{role}_{ts}.png"
        plt.savefig(out, dpi=130, bbox_inches="tight")
        plt.close()
        logger.info("Plot -> %s", out)

    # ------------------------------------------------------------------
    # 3. Per-REQ MAE bar chart per role
    # ------------------------------------------------------------------
    for role in roles:
        pr = role_results[role].get("per_req_mae", {})
        if not pr:
            continue
        reqs = sorted(pr.keys(), key=lambda r: -pr[r])
        vals = [pr[r] for r in reqs]

        fig, ax = plt.subplots(figsize=(max(8, len(reqs) * 0.7), 5))
        bar_colors = ["tomato" if v > 1.0 else "darkorange" if v > 0.5 else "steelblue" for v in vals]
        ax.bar(reqs, vals, color=bar_colors, alpha=0.85)
        ax.set_title(f"{role} — Per-Requirement MAE (scorer vs judge)", fontsize=12, fontweight="bold")
        ax.set_xlabel("Requirement ID")
        ax.set_ylabel("MAE (sub-score units)")
        ax.set_xticklabels(reqs, rotation=40, ha="right", fontsize=9)
        ax.axhline(1.0, color="tomato",    linewidth=1, linestyle="--", alpha=0.6, label="High (>1.0)")
        ax.axhline(0.5, color="darkorange", linewidth=1, linestyle="--", alpha=0.6, label="Moderate (>0.5)")
        ax.legend(fontsize=9)
        ax.grid(axis="y", alpha=0.3)
        for i, v in enumerate(vals):
            ax.text(i, v + 0.01, f"{v:.3f}", ha="center", va="bottom", fontsize=8)
        plt.tight_layout()
        out = output_dir / f"req_mae_{role}_{ts}.png"
        plt.savefig(out, dpi=130, bbox_inches="tight")
        plt.close()
        logger.info("Plot -> %s", out)


# ---------------------------------------------------------------------------
# Role evaluator
# ---------------------------------------------------------------------------

def _judge_one_candidate(
    sf: pathlib.Path,
    role: str,
    req_ids: List[str],
    weight_config: List[Dict[str, Any]],
    subqueries: Dict[str, List[Dict[str, str]]],
    model: str,
    api_key: str,
    base_url: str,
    dry_run: bool,
    seed: int,
) -> Optional[Dict[str, Any]]:
    """
    Judge a single candidate and return their result dict.

    This function is designed to be called from a ThreadPoolExecutor.
    Each call is fully independent — no shared mutable state.

    Args:
        sf:           Path to the candidate's score JSON file.
        role:         Role name (for logging).
        req_ids:      Ordered list of requirement IDs.
        weight_config: Requirement weight list.
        subqueries:   Sub-query dict.
        model:        Judge model slug.
        api_key:      OpenRouter API key.
        base_url:     API base URL.
        dry_run:      If True, simulate judge response with Gaussian noise.
        seed:         Random seed (combined with candidate hash for dry-run).

    Returns:
        Dict with keys: candidate_id, scorer_total, judge_total, delta,
        flagged, req_pairs (list of (rid, scorer_sub, judge_sub) tuples).
        Returns None on any unrecoverable error.
    """
    try:
        score_data = json.loads(sf.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("[%s] Load error %s: %s", role, sf.name, exc)
        return None

    cid = score_data.get("candidate_id", sf.stem)
    scorer_total = float(score_data.get("total", 0))
    scorer_sub: Dict[str, float] = {
        r["requirement_id"]: float(r.get("sub_score") or 0)
        for r in score_data.get("reqs", [])
        if r.get("requirement_id")
    }

    if dry_run:
        rng = random.Random(seed + abs(hash(cid)))
        judge_total = max(0.0, scorer_total + rng.gauss(0, 5))
        judge_req_list = [
            {
                "requirement_id": rid,
                "sub_scores": {},
                "sub_score_sum": scorer_sub.get(rid, 0) + rng.gauss(0, 0.2),
            }
            for rid in req_ids
        ]
    else:
        resume_text = load_processed_text(role, cid)
        if not resume_text:
            logger.warning("[%s] No resume text for %s -- skip", role, cid)
            return None

        prompt = _build_judge_prompt(cid, resume_text, weight_config, subqueries)
        logger.info("[%s] Judging %s ...", role, cid)
        raw = call_judge_llm(_JUDGE_SYSTEM, prompt, model, api_key, base_url)
        if not raw:
            logger.warning("[%s] No judge response for %s", role, cid)
            return None

        parsed = parse_judge_response(raw, req_ids)
        if not parsed:
            logger.warning("[%s] Parse failed for %s", role, cid)
            return None

        judge_req_list = parsed.get("requirements", [])
        judge_total = compute_judge_total(judge_req_list, weight_config)

    # Collect per-REQ sub-score pairs for later aggregation
    judge_map = {r.get("requirement_id"): r for r in judge_req_list}
    req_pairs_out = [
        (rid, scorer_sub.get(rid, 0.0), _sub_score_sum(judge_map[rid]))
        for rid in req_ids
        if rid in judge_map
    ]

    delta = scorer_total - judge_total
    is_flagged = abs(delta) > 10.0
    logger.info("[%s] %s  scorer=%.1f  judge=%.1f  delta=%+.1f%s",
                role, cid, scorer_total, judge_total, delta,
                "  ** FLAGGED **" if is_flagged else "")

    return {
        "candidate_id": cid,
        "scorer_total": round(scorer_total, 2),
        "judge_total":  round(judge_total, 2),
        "delta":        round(delta, 2),
        "flagged":      is_flagged,
        "req_pairs":    req_pairs_out,
    }


def evaluate_role(
    role: str,
    sample_pct: float,
    weight_config: List[Dict[str, Any]],
    subqueries: Dict[str, List[Dict[str, str]]],
    model: str,
    api_key: str,
    base_url: str,
    dry_run: bool = False,
    seed: int = 42,
    workers: int = 10,
) -> Dict[str, Any]:
    """
    Sample candidates for a role, call the judge in parallel, and compute metrics.

    Candidates are judged concurrently using a ThreadPoolExecutor.
    Each worker thread makes one independent LLM call; results are aggregated
    in the main thread after all futures complete.

    Args:
        role:          Role name.
        sample_pct:    Fraction to sample.
        weight_config: Requirement weight list.
        subqueries:    Sub-query dict.
        model:         Judge model slug.
        api_key:       OpenRouter API key.
        base_url:      API base URL.
        dry_run:       If True, simulate judge with Gaussian noise.
        seed:          Random seed for reproducibility.
        workers:       Number of parallel threads (default 10).

    Returns:
        Dict: role, metrics, per_req_mae, candidate_scores,
              flagged_for_review, pairs, errors.
    """
    req_ids = [r.get("requirement_id") for r in weight_config]
    sample_files = sample_candidates(role, sample_pct, seed)
    logger.info("[%s] Sampled %d / %d candidates (%.0f%%) -- workers=%d",
                role, len(sample_files),
                len(list((SCORES_DIR / role).glob("*.json"))),
                sample_pct * 100, workers)

    # Run all candidate judgements in parallel
    results: List[Optional[Dict[str, Any]]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _judge_one_candidate,
                sf, role, req_ids, weight_config, subqueries,
                model, api_key, base_url, dry_run, seed,
            ): sf
            for sf in sample_files
        }
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                logger.warning("[%s] Unexpected future error: %s", role, exc)
                results.append(None)

    # Aggregate results from all threads
    pairs: List[Tuple[float, float]] = []
    req_pairs: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    cand_scores, flagged = [], []
    error_count = sum(1 for r in results if r is None)

    for res in results:
        if res is None:
            continue
        pairs.append((res["scorer_total"], res["judge_total"]))
        for rid, s_sub, j_sub in res["req_pairs"]:
            req_pairs[rid].append((s_sub, j_sub))
        cand_scores.append({
            "candidate_id": res["candidate_id"],
            "scorer_total": res["scorer_total"],
            "judge_total":  res["judge_total"],
            "delta":        res["delta"],
            "flagged":      res["flagged"],
        })
        if res["flagged"]:
            flagged.append({
                "candidate_id": res["candidate_id"],
                "scorer_total": res["scorer_total"],
                "judge_total":  res["judge_total"],
                "delta":        res["delta"],
            })

    metrics = compute_metrics(pairs)
    logger.info("[%s] n=%d  MAE=%.2f  RMSE=%.2f  R2=%.3f  bias=%+.2f  errors=%d",
                role, metrics["n"], metrics["mae"], metrics["rmse"],
                metrics["r2"], metrics["bias"], error_count)

    return {
        "role": role,
        "metrics": metrics,
        "per_req_mae": compute_per_req_mae(req_pairs),
        "candidate_scores": cand_scores,
        "flagged_for_review": flagged,
        "pairs": pairs,
        "errors": error_count,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Entry point.

    Examples:
        python scripts/judge_eval.py
        python scripts/judge_eval.py --role BusinessAnalyst DataScience
        python scripts/judge_eval.py --dry-run
        python scripts/judge_eval.py --sample-pct 0.25 --seed 99
    """
    parser = argparse.ArgumentParser(
        description="Judge LLM evaluation: validate scorer outputs via Minimax-M3."
    )
    parser.add_argument("--role", nargs="+", metavar="ROLE", default=None,
                        help="Roles to evaluate (default: all scored roles).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simulate judge calls with noise; no LLM API calls.")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed (default: 42).")
    parser.add_argument("--sample-pct", type=float, default=None,
                        help="Override AUDIT_SAMPLE_PCT (e.g. 0.20).")
    parser.add_argument("--judge-model", default=None,
                        help="Override AUDIT_JUDGE_MODEL from .env.audit.")
    parser.add_argument("--workers", type=int, default=10,
                        help="Parallel judge threads per role (default: 10).")
    args = parser.parse_args()

    env = _load_env_audit(ENV_AUDIT)
    api_key = env.get("OPENROUTER_API_KEY", "")
    base_url = env.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    model = args.judge_model or env.get("AUDIT_JUDGE_MODEL", "minimaxai/minimax-m3")
    sample_pct = args.sample_pct or float(env.get("AUDIT_SAMPLE_PCT", "0.20"))

    if not api_key and not args.dry_run:
        logger.error("OPENROUTER_API_KEY not set in .env.audit")
        sys.exit(1)

    logger.info("Judge model : %s", model)
    logger.info("Sample pct  : %.0f%%", sample_pct * 100)
    logger.info("Dry run     : %s", args.dry_run)

    roles = args.role or discover_scored_roles()
    if not roles:
        logger.error("No scored roles found in %s", SCORES_DIR)
        sys.exit(1)
    logger.info("Roles       : %s", roles)

    role_results: Dict[str, Any] = {}
    for role in roles:
        logger.info("\n%s\nRole: %s\n%s", "=" * 60, role, "=" * 60)
        try:
            wc = load_weight_config(role)
        except FileNotFoundError as exc:
            logger.warning("Skipping %s -- %s", role, exc)
            continue
        sqs = load_subqueries(role)
        role_results[role] = evaluate_role(
            role=role, sample_pct=sample_pct, weight_config=wc,
            subqueries=sqs, model=model, api_key=api_key,
            base_url=base_url, dry_run=args.dry_run, seed=args.seed,
            workers=args.workers,
        )

    if not role_results:
        logger.error("No roles evaluated.")
        sys.exit(1)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    # Save raw JSON (exclude raw pairs list for compactness)
    json_out = REPORT_DIR / f"judge_eval_{ts}.json"
    json_out.write_text(
        json.dumps(
            {r: {k: v for k, v in res.items() if k != "pairs"}
             for r, res in role_results.items()},
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("JSON results -> %s", json_out)

    generate_report(
        role_results=role_results,
        model_name=model,
        sample_pct=sample_pct,
        output_path=REPORT_DIR / f"judge_eval_{ts}.txt",
    )

    generate_plots(
        role_results=role_results,
        output_dir=REPORT_DIR,
        ts=ts,
    )

    logger.info("All outputs saved to: %s", REPORT_DIR)


if __name__ == "__main__":
    main()
