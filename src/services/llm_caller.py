"""Real LLM caller using the opencode.ai/zen/v1 OpenAI-compatible endpoint.

Reads API key from ``.env`` file. Uses the official OpenAI Python SDK
with a custom base_url.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
ENV_PATH = ROOT / ".env"


def _load_env() -> Dict[str, str]:
    """Load simple KEY=VALUE pairs from .env (no dependency on python-dotenv)."""
    env: Dict[str, str] = {}
    if not ENV_PATH.exists():
        return env
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        # Strip quotes if present
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


# Load once at import time
_ENV = _load_env()
OPENCODE_API_KEY: Optional[str] = _ENV.get("OPENCODE_API_KEY")
OPENCODE_BASE_URL: str = _ENV.get("base_url", "https://opencode.ai/zen/v1")
OPENCODE_MODEL: str = _ENV.get("model", "MiMo V2.5 Free")


class LLMRubricCaller:
    """Real LLM caller for the rubric-bound scoring.

    Holds the API key and model name. Each call() invocation sends the
    prompt to the opencode.ai/zen/v1 chat completions endpoint and
    returns the raw assistant text.

    The caller is *stateful* (holds a client) so the SDK doesn't reinitialize
    on every call. Use ``model_name`` attribute so the cache can include it
    in the cache key.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 2000,
        temperature: float = 0.0,
    ) -> None:
        self.api_key = api_key or OPENCODE_API_KEY
        self.base_url = base_url or OPENCODE_BASE_URL
        self.model_name = model or OPENCODE_MODEL
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client = None
        self._available = False

        if not self.api_key:
            logger.warning(
                "OPENCODE_API_KEY not found in .env — LLM caller will return empty string"
            )
            return

        try:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            self._available = True
            logger.info("LLM caller ready: model=%s base_url=%s", self.model_name, self.base_url)
        except Exception as e:
            logger.warning("Failed to initialize OpenAI client: %s", e)
            self._client = None

    def __call__(self, prompt: str) -> str:
        """Send a prompt and return the assistant's raw text response."""
        if not self._available or self._client is None:
            return ""
        try:
            response = self._client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a strict rubric scorer. You read resume chunks and "
                            "answer each sub-question with the EXACT anchored value "
                            "shown. You do not explain. You do not add prose. You output "
                            "ONLY one line per sub-question in the format `key: value`."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            content = response.choices[0].message.content or ""
            return content.strip()
        except Exception as e:
            logger.warning("LLM call failed: %s", e)
            return ""


# Module-level default instance for convenience
_default_caller: Optional[LLMRubricCaller] = None


def get_default_caller() -> LLMRubricCaller:
    """Get a module-level default LLM caller (lazy-initialized)."""
    global _default_caller
    if _default_caller is None:
        _default_caller = LLMRubricCaller()
    return _default_caller
