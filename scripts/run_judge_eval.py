#!/usr/bin/env python3
"""Run Judge LLM evaluation protocol (docs/19_EVALUATION.md).

Evaluates the production scorer (Ollama qwen2.5:3b) against Gemini 2.5 Flash
and Minimax-M3 multimodal judges by feeding the original resume PDFs.
Uses 5-key rotation pool across providers and supports resume from interruption.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import logging
import math
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pypdfium2 as pdfium
from openai import OpenAI

# Add project root to sys.path so src imports resolve
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.judge_prompt_builder import build_judge_prompt_for_role
from src.evaluation.score_comparator import verify_arithmetic_consistency
from src.services.subquery_parser import parse_subquery_document

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s [%(name)s]: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("run_judge_eval")

# Path Constants
ENV_AUDIT_PATH = ROOT / ".env.audit"
REGISTRY_PATH = ROOT / "data/candidate_registry.json"
SCORES_COMPOSED_DIR = ROOT / "data/scores/composed"
JUDGE_EVAL_DIR = ROOT / "data/eval/judge_eval"
JOB_DESCRIPTIONS_DIR = ROOT / "data/job_descriptions"


# ---------------------------------------------------------------------------
# Key Queue with Cooldown Rotation logic
# ---------------------------------------------------------------------------

class KeyQueue:
    """Circular queue of API keys for a provider with cooldown rotation on rate limits."""

    def __init__(self, key_names: List[str], env_data: Dict[str, List[str]], cooldown_s: float = 60.0) -> None:
        """Initialize the key queue.

        Args:
            key_names: List of environment variable key names to retrieve.
            env_data: Dictionary of parsed environment variables.
            cooldown_s: Cooldown duration in seconds when a key is rate limited.
        """
        self.cooldown_s = cooldown_s
        self.keys: List[Tuple[str, str]] = []  # List of (key_name, key_value)
        self.cooldowns: Dict[str, float] = {}  # Map key_name -> cooldown end timestamp
        self.index = 0

        for name in key_names:
            vals = env_data.get(name, [])
            for val in vals:
                # Deduplicate key values
                if (name, val) not in self.keys:
                    self.keys.append((name, val))

        logger.info(
            "Initialized KeyQueue with %d unique keys from variables %s",
            len(self.keys), key_names,
        )

    def next_key(self) -> Tuple[str, str]:
        """Retrieve the next available key not in cooldown.

        Returns:
            Tuple of (key_name, key_value).

        Raises:
            RuntimeError: If all keys are currently cooling down.
        """
        if not self.keys:
            raise ValueError("No keys configured in this queue.")

        start_index = self.index
        now = time.time()

        while True:
            name, value = self.keys[self.index]
            cooldown_end = self.cooldowns.get(name, 0.0)

            if now >= cooldown_end:
                # Key is available, advance index for next call and return
                current_key = (name, value)
                self.index = (self.index + 1) % len(self.keys)
                return current_key

            # Advance index to check next key
            self.index = (self.index + 1) % len(self.keys)

            # If we cycled back to start_index, all keys are in cooldown
            if self.index == start_index:
                # Find the key that finishes cooldown first
                min_wait = min(self.cooldowns.get(n, 0.0) - now for n, _ in self.keys)
                logger.warning(
                    "All keys are rate limited. Waiting %.1f seconds for cooldown to clear...",
                    min_wait,
                )
                time.sleep(max(0.1, min_wait))
                now = time.time()


    def mark_rate_limited(self, key_name: str) -> None:
        """Mark a key as rate limited, putting it in cooldown.

        Args:
            key_name: Name of the key variable to cool down.
        """
        self.cooldowns[key_name] = time.time() + self.cooldown_s
        logger.warning("Key '%s' marked as rate limited. Cooling down for %.1f s", key_name, self.cooldown_s)


# ---------------------------------------------------------------------------
# Setup Environment Parsing
# ---------------------------------------------------------------------------

def load_env_audit() -> Dict[str, List[str]]:
    """Parse .env.audit file, supporting duplicates and different delimiter conventions."""
    result: Dict[str, List[str]] = {}
    if not ENV_AUDIT_PATH.exists():
        logger.warning(".env.audit file not found at %s", ENV_AUDIT_PATH)
        return result

    for raw_line in ENV_AUDIT_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
        elif "-" in line:
            k, _, v = line.partition("-")
        else:
            continue

        key = k.strip()
        val = v.strip().strip('"').strip("'")
        if val:
            result.setdefault(key, []).append(val)
    return result


# ---------------------------------------------------------------------------
# PDF Visual Rendering Helper
# ---------------------------------------------------------------------------

def pdf_to_base64_images(pdf_path: Path, max_pages: int = 5, scale: float = 2.0) -> List[str]:
    """Render the first max_pages of a PDF into base64 JPEGs for the multimodal model."""
    images_b64 = []
    try:
        pdf = pdfium.PdfDocument(str(pdf_path))
        num_pages = min(len(pdf), max_pages)
        for i in range(num_pages):
            page = pdf[i]
            bitmap = page.render(scale=scale)
            pil_img = bitmap.to_pil()

            buf = io.BytesIO()
            pil_img.save(buf, format="JPEG")
            b64_str = base64.b64encode(buf.getvalue()).decode("utf-8")
            images_b64.append(b64_str)
        pdf.close()
    except Exception as exc:
        logger.error("Failed to render PDF %s: %s", pdf_path, exc)
    return images_b64


# ---------------------------------------------------------------------------
# Registry Parsing and Sub-query Utilities
# ---------------------------------------------------------------------------

def get_pdf_path(candidate_id: str) -> Optional[Path]:
    """Retrieve original resume PDF path from candidate_registry.json."""
    if not REGISTRY_PATH.exists():
        logger.error("Candidate registry not found at %s", REGISTRY_PATH)
        return None
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        cands = data.get("candidates", {})
        if candidate_id in cands:
            path_str = cands[candidate_id].get("source_path")
            if path_str:
                return Path(path_str)
    except Exception as exc:
        logger.error("Failed to parse registry: %s", exc)
    return None


def get_subquery_md_path(role: str) -> Path:
    """Retrieve SubQuery markdown document path for a role."""
    return JOB_DESCRIPTIONS_DIR / role / f"{role}_SubQuery.md"


def get_scorer_output_path(role: str, candidate_id: str) -> Path:
    """Retrieve scorer output composed JSON path."""
    return SCORES_COMPOSED_DIR / role / f"{candidate_id}.json"


# ---------------------------------------------------------------------------
# Multimodal LLM calling wrapper
# ---------------------------------------------------------------------------

def call_judge_llm(
    queue: KeyQueue,
    base_url: str,
    model: str,
    prompt_text: str,
    images_b64: List[str],
) -> str:
    """Execute LLM call using KeyQueue rotation pool for rate limit resilience."""
    max_attempts = len(queue.keys)
    if max_attempts == 0:
        logger.error("No credentials available in KeyQueue.")
        return ""

    for attempt in range(max_attempts):
        key_name, api_key = queue.next_key()
        label = f"{base_url} ({model}) using {key_name}"

        # Build multimodal payload message
        content_list: List[Dict[str, Any]] = [
            {"type": "text", "text": prompt_text}
        ]
        for img in images_b64:
            content_list.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img}"}
            })

        try:
            client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0)
            logger.info("Executing LLM call to %s (images=%d)...", label, len(images_b64))

            # Attempt JSON Mode first
            response_text = ""
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a strict resume evaluation judge. Output ONLY a valid JSON object matching the requested schema.",
                        },
                        {"role": "user", "content": content_list},
                    ],
                    temperature=0.0,
                    max_tokens=3000,
                    timeout=120.0,
                    response_format={"type": "json_object"},
                )
                if response.choices and response.choices[0].message.content:
                    response_text = response.choices[0].message.content.strip()
            except Exception as json_err:
                logger.debug("JSON Mode not supported or failed: %s. Falling back to default completions...", json_err)

            if not response_text:
                # Standard fallback call
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a strict resume evaluation judge. Output ONLY a valid JSON object matching the requested schema.",
                        },
                        {"role": "user", "content": content_list},
                    ],
                    temperature=0.0,
                    max_tokens=3000,
                    timeout=120.0,
                )
                if response.choices and response.choices[0].message.content:
                    response_text = response.choices[0].message.content.strip()

            if response_text:
                return response_text

            logger.warning("%s returned empty response.", label)

        except Exception as exc:
            exc_str = str(exc)
            # Check for rate-limiting errors (429)
            if "429" in exc_str or "rate_limit" in exc_str.lower() or "too many requests" in exc_str.lower():
                queue.mark_rate_limited(key_name)
                # Loop will immediately retry with next key in queue
                continue
            else:
                logger.error("%s invocation failed: %s", label, exc)
                break

    return ""


# ---------------------------------------------------------------------------
# Strict JSON Cleaning helper
# ---------------------------------------------------------------------------

def clean_llm_json(response: str) -> str:
    """Clean the raw LLM response markdown formatting to extract raw JSON block."""
    clean = response.strip()
    if "</thought>" in clean:
        idx = clean.find("</thought>")
        clean = clean[idx + len("</thought>"):].strip()

    # Find JSON block boundaries
    start = clean.find("{")
    end = clean.rfind("}")
    if start != -1 and end != -1 and end > start:
        clean = clean[start:end + 1].strip()
    return clean


# ---------------------------------------------------------------------------
# Main Evaluation Batch Process Runner
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Run True Score Evaluation using Judge LLMs.")
    parser.add_argument("--role", type=str, help="Restrict evaluation to a single role.")
    parser.add_argument("--sample-size", type=int, help="Override default sample size (10%% per role).")
    parser.add_argument("--seed", type=int, default=42, help="Seed for sampling reproducibility.")
    parser.add_argument("--dry-run", action="store_true", help="Print candidate sampling configuration without calling APIs.")
    parser.add_argument("--resume", action="store_true", help="Resume the latest interrupted batch run.")
    parser.add_argument("--judges", type=str, choices=["gemini", "minimax", "both"], default="gemini", help="Which judge models to run (default: gemini).")
    args = parser.parse_args()

    # Load environment variables
    env_data = load_env_audit()

    # Establish KeyQueues
    google_keys = ["GOOGLE_API_KEY_1", "GOOGLE_API_KEY_2"]
    nvidia_keys = ["NVIDIA_NIM_API_KEY_1", "NVIDIA_NIM_API_KEY_2", "NVIDIA_NIM_API_KEY_3"]

    google_queue = KeyQueue(google_keys, env_data)
    nvidia_queue = KeyQueue(nvidia_keys, env_data)

    google_model = "gemini-2.5-flash"
    # Fallback to model label in .env.audit if available
    g_models = env_data.get("FREE_MULTIMODAL_MODELS", [])
    # In .env.audit, the second occurrence corresponds to gemini
    if len(g_models) > 1:
        google_model = g_models[1]
    elif len(g_models) == 1 and "gemini" in g_models[0]:
        google_model = g_models[0]

    minimax_model = "minimaxai/minimax-m3"
    m_models = env_data.get("FREE_MULTIMODAL_MODELS", [])
    if m_models and "minimax" in m_models[0]:
        minimax_model = m_models[0]

    # Google endpoint URL
    google_base = "https://generativelanguage.googleapis.com/v1beta/openai/"
    g_bases = env_data.get("base_url", [])
    if len(g_bases) > 1:
        google_base = g_bases[1]
    elif len(g_bases) == 1 and "googleapis" in g_bases[0]:
        google_base = g_bases[0]

    # NVIDIA endpoint URL
    nvidia_base = "https://integrate.api.nvidia.com/v1"
    nv_bases = env_data.get("base_url", [])
    if nv_bases and "nvidia" in nv_bases[0]:
        nvidia_base = nv_bases[0]

    # 1. Discover roles to evaluate
    if args.role:
        roles = [args.role]
    else:
        roles = [d.name for d in SCORES_COMPOSED_DIR.iterdir() if d.is_dir()]

    if not roles:
        logger.error("No candidate score directory found under %s", SCORES_COMPOSED_DIR)
        return

    # 2. Determine batch session directories
    batch_dir = None
    progress = {"batch_id": "", "candidates": {}}

    if args.resume:
        # Find latest batch run directory
        if JUDGE_EVAL_DIR.exists():
            batches = sorted(JUDGE_EVAL_DIR.glob("batch_*"))
            if batches:
                batch_dir = batches[-1]
                logger.info("Resuming batch run under directory: %s", batch_dir)
                # Load existing config and progress
                progress_file = batch_dir / "progress.json"
                if progress_file.exists():
                    try:
                        progress = json.loads(progress_file.read_text(encoding="utf-8"))
                    except Exception as e:
                        logger.error("Failed to load progress file: %s", e)
                        return
                else:
                    logger.error("Progress ledger progress.json not found in batch dir %s", batch_dir)
                    return

        if not batch_dir:
            logger.error("No previous batch found to resume. Please run without --resume.")
            return
    else:
        # Create a new batch session
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        batch_id = f"batch_{timestamp}"
        batch_dir = JUDGE_EVAL_DIR / batch_id
        batch_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Initializing new True Score Evaluation batch: %s", batch_id)
        progress["batch_id"] = batch_id

        # Generate sampling plan
        sampling_plan = {}
        random.seed(args.seed)

        for role in sorted(roles):
            role_dir = SCORES_COMPOSED_DIR / role
            if not role_dir.exists():
                continue
            cand_files = sorted(role_dir.glob("*.json"))
            cand_ids = [f.stem for f in cand_files]

            if not cand_ids:
                continue

            # Determine sample size (10% of candidates per role, min 2)
            n_candidates = len(cand_ids)
            if args.sample_size:
                sample_size = min(n_candidates, args.sample_size)
            else:
                sample_size = max(2, math.ceil(n_candidates * 0.10))

            sampled_ids = random.sample(cand_ids, sample_size)
            sampling_plan[role] = sampled_ids
            logger.info("Role '%s': Sampled %d out of %d candidates.", role, sample_size, n_candidates)

            # Initialize candidate statuses
            for cid in sampled_ids:
                progress["candidates"][cid] = {
                    "role": role,
                    "status": "pending",
                    "judge_status": "pending",
                }

        # Save config.json
        config = {
            "batch_id": batch_id,
            "timestamp": timestamp,
            "seed": args.seed,
            "sample_pct": 0.10,
            "judge_models": {
                "gemini": google_model,
                "minimax": minimax_model,
            },
            "sampling_plan": sampling_plan,
        }
        (batch_dir / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

        # Save initial progress.json
        (batch_dir / "progress.json").write_text(json.dumps(progress, indent=2), encoding="utf-8")

    # If dry-run, stop here after configuration
    if args.dry_run:
        logger.info("Dry-run configured. Candidate evaluations configuration complete. Stopping.")
        return

    # 3. Execution loop over sampled candidates
    candidates_dict = progress.setdefault("candidates", {})
    pending_cands = [cid for cid, info in candidates_dict.items() if info["status"] in ("pending", "in_progress")]

    total_pending = len(pending_cands)
    logger.info("Processing %d pending candidate evaluations...", total_pending)

    for i, cid in enumerate(pending_cands, 1):
        info = candidates_dict[cid]
        role = info["role"]
        logger.info("[%d/%d] Candidate: %s (Role: %s)", i, total_pending, cid, role)

        # Mark in progress
        info["status"] = "in_progress"
        (batch_dir / "progress.json").write_text(json.dumps(progress, indent=2), encoding="utf-8")

        # Create sample folder
        sample_folder = batch_dir / "samples" / cid
        sample_folder.mkdir(parents=True, exist_ok=True)

        # A. Load Scorer output (copy it to evaluation snapshot)
        scorer_path = get_scorer_output_path(role, cid)
        if not scorer_path.exists():
            logger.error("Scorer outputcomposed file not found at %s. Skipping candidate.", scorer_path)
            info["status"] = "skipped"
            info["judge_status"] = "scorer_json_missing"
            continue

        try:
            scorer_data = json.loads(scorer_path.read_text(encoding="utf-8"))
            (sample_folder / "scorer_output.json").write_text(json.dumps(scorer_data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error("Failed to load scorer JSON for candidate %s: %s", cid, e)
            info["status"] = "skipped"
            info["judge_status"] = "scorer_json_corrupt"
            continue

        # B. Find original PDF path and convert to image frames
        pdf_path = get_pdf_path(cid)
        if not pdf_path or not pdf_path.exists():
            logger.error("Original resume PDF not found for candidate %s. Skipping candidate.", cid)
            info["status"] = "skipped"
            info["judge_status"] = "pdf_missing"
            continue

        logger.info("Rendering PDF pages for visual inspection: %s", pdf_path)
        images = pdf_to_base64_images(pdf_path, max_pages=5, scale=2.0)
        if not images:
            logger.error("Failed to render pages for candidate %s. Skipping.", cid)
            info["status"] = "skipped"
            info["judge_status"] = "pdf_render_failed"
            continue

        # C. Load Job Description Rubric (SubQuery and weights)
        subquery_path = get_subquery_md_path(role)
        if not subquery_path.exists():
            logger.error("SubQuery markdown document not found at %s. Skipping.", subquery_path)
            info["status"] = "skipped"
            info["judge_status"] = "subquery_doc_missing"
            continue

        try:
            subquery_data = parse_subquery_document(subquery_path)
            requirements = subquery_data["requirements"]
        except Exception as e:
            logger.error("Failed to parse SubQuery markdown: %s. Skipping.", e)
            info["status"] = "skipped"
            info["judge_status"] = "subquery_parse_failed"
            continue

        # Map weight percentages from scorer output to rubric
        req_weights = {}
        for req in scorer_data.get("reqs", []):
            req_id = req.get("requirement_id")
            if req_id:
                req_weights[req_id] = {
                    "weight_percentage": req.get("weight_percentage", 0.0),
                    "expected_years": req.get("expected_years", None),
                }

        for req in requirements:
            req_id = req["req_id"]
            if req_id in req_weights:
                req.update(req_weights[req_id])

        # D. Construct prompt
        prompt = build_judge_prompt_for_role(role, cid, requirements)

        # E. Call Gemini 2.5 Flash Judge
        gemini_response = ""
        gemini_json = None
        if args.judges in ("gemini", "both"):
            try:
                gemini_response = call_judge_llm(google_queue, google_base, google_model, prompt, images)
                if gemini_response:
                    clean_json = clean_llm_json(gemini_response)
                    gemini_json = json.loads(clean_json)
                    (sample_folder / "judge_gemini.json").write_text(json.dumps(gemini_json, indent=2), encoding="utf-8")
                    logger.info("Gemini 2.5 Flash evaluation succeeded.")
            except Exception as e:
                logger.warning("Gemini 2.5 Flash evaluation failed: %s", e)

        # F. Call Minimax-M3 Judge
        minimax_response = ""
        minimax_json = None
        if args.judges in ("minimax", "both"):
            try:
                minimax_response = call_judge_llm(nvidia_queue, nvidia_base, minimax_model, prompt, images)
                if minimax_response:
                    clean_json = clean_llm_json(minimax_response)
                    minimax_json = json.loads(clean_json)
                    (sample_folder / "judge_minimax.json").write_text(json.dumps(minimax_json, indent=2), encoding="utf-8")
                    logger.info("Minimax-M3 evaluation succeeded.")
            except Exception as e:
                logger.warning("Minimax-M3 evaluation failed: %s", e)

        # G. Update progress
        if gemini_json is not None or minimax_json is not None:
            info["status"] = "done"
            status_desc = []
            if gemini_json:
                status_desc.append("gemini")
            if minimax_json:
                status_desc.append("minimax")
            info["judge_status"] = f"success_{'+'.join(status_desc)}"
            logger.info("Candidate %s successfully evaluated by: %s", cid, "+".join(status_desc))
        else:
            info["status"] = "failed"
            info["judge_status"] = "all_judges_failed"
            logger.error("Candidate %s evaluation failed across all active judge models.", cid)

        (batch_dir / "progress.json").write_text(json.dumps(progress, indent=2), encoding="utf-8")

        # Prevent rate limits with short inter-call delay
        time.sleep(2.0)

    logger.info("Evaluation loop complete. Generating batch comparison report...")
    # Execute batch report compilation
    try:
        from scripts.generate_judge_eval_report import compile_report_for_batch
        compile_report_for_batch(batch_dir)
    except Exception as err:
        logger.error("Failed to automatically generate report: %s", err)


if __name__ == "__main__":
    main()
