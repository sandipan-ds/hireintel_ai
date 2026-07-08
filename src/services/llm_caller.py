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
        max_tokens: int = 4000,
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
                            "You are a strict rubric scorer for resume evidence. "
                            "Follow the format instructions in the user message "
                            "EXACTLY. Do not add explanations, prose, or "
                            "commentary beyond what the format requires. Do not "
                            "speculate beyond the resume content. If evidence is "
                            "insufficient, return 0 / \"unknown\" / null as the "
                            "format allows."
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
_default_caller: Optional[Any] = None


def get_default_caller() -> Any:
    """Get a module-level default LLM caller (lazy-initialized)."""
    global _default_caller
    if _default_caller is None:
        _default_caller = get_rubric_caller()
    return _default_caller


# ---------------------------------------------------------------------------
# Ollama local-LLM caller (OpenAI-compatible endpoint at port 11434).
#
# Free-tier cloud LLM endpoints truncate the JSON response mid-stream (server-
# side `completion_tokens` cap), so local inference is the path of least
# resistance for rubric scoring. Ollama exposes an OpenAI-compatible REST API
# at http://localhost:11434/v1, so the same OpenAI Python SDK drives both
# backends — only ``base_url``, ``api_key`` (any non-empty string works), and
# ``model`` differ.
#
# Select Ollama via the env var ``LLM_BACKEND=ollama`` (read from .env or the
# process environment). The default remains ``opencode`` (the existing
# endpoint) so existing callers are unaffected.
# ---------------------------------------------------------------------------

OLLAMA_BASE_URL: str = _ENV.get("ollama_base_url", "http://localhost:11434/v1")
OLLAMA_MODEL: str = _ENV.get("ollama_model", "qwen2.5:3b")
OLLAMA_API_KEY: str = _ENV.get("ollama_api_key", "ollama")  # any non-empty str


class OllamaRubricCaller:
    """Ollama-local LLM caller for the rubric-bound scoring.

    Uses Ollama's OpenAI-compatible endpoint at
    ``http://localhost:11434/v1``. Any non-empty API key is accepted; we use
    ``"ollama"`` by default. The model name (e.g. ``qwen2.5:3b``) must be
    one of the models listed by ``ollama list`` on the host.

    Designed to be a drop-in replacement for :class:`LLMRubricCaller`:
    same ``__call__(prompt) -> str`` contract and same ``model_name`` /
    ``_available`` attributes used by callers / tests.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        max_tokens: int = 4000,
        temperature: float = 0.0,
        timeout: float = 120.0,
    ) -> None:
        self.model_name = model or OLLAMA_MODEL
        self.base_url = base_url or OLLAMA_BASE_URL
        self.api_key = api_key or OLLAMA_API_KEY
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        self._client = None
        self._available = False

        try:
            from openai import OpenAI
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
            )
            self._available = True
            logger.info(
                "Ollama caller ready: model=%s base_url=%s",
                self.model_name, self.base_url,
            )
        except Exception as e:
            logger.warning("Failed to initialize Ollama OpenAI client: %s", e)
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
                            "You are a strict rubric scorer for resume evidence. "
                            "Follow the format instructions in the user message "
                            "EXACTLY. Do not add explanations, prose, or "
                            "commentary beyond what the format requires. Do not "
                            "speculate beyond the resume content. If evidence is "
                            "insufficient, return 0 / \"unknown\" / null as the "
                            "format allows."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            if not response.choices:
                logger.warning(
                    "Ollama returned empty choices for model %s", self.model_name,
                )
                return ""
            content = response.choices[0].message.content or ""
            return content.strip()
        except Exception as e:
            logger.warning("Ollama LLM call failed: %s", e)
            return ""


def get_rubric_caller() -> Any:
    """Factory returning the configured rubric LLM caller.

    Selection order (first match wins):
      1. ``LLM_BACKEND`` env var in the process environment (``ollama`` or
         ``opencode``).
      2. ``LLM_BACKEND`` key in the ``.env`` file.
      3. Default: ``opencode`` (the existing cloud endpoint).

    Returns:
        An ``LLMRubricCaller`` or ``OllamaRubricCaller`` instance. Both
        implement the ``__call__(prompt) -> str`` contract.
    """
    backend = (
        os.environ.get("LLM_BACKEND")
        or _ENV.get("LLM_BACKEND")
        or "opencode"
    ).lower().strip()
    if backend == "ollama":
        caller = OllamaRubricCaller()
        if not caller._available:
            logger.warning(
                "LLM_BACKEND=ollama but Ollama caller is not available — "
                "falling back to opencode backend."
            )
            return LLMRubricCaller()
        return caller
    return LLMRubricCaller()
