"""Rubric LLM callers for the scoring pipeline.

Reads API keys and backend config from the project ``.env`` file.
Uses the official OpenAI Python SDK with a custom ``base_url`` so every
backend (opencode.ai, NVIDIA NIM, Google AI) is driven identically.

Backend selection (``LLM_BACKEND`` in ``.env`` or process env):
  - ``nvidia``   — NVIDIA NIM with round-robin rotation across
                   ``NVIDIA_NIM_API_KEY_1/2/3``.  Model defaults to
                   ``NVIDIA_NIM_RUBRIC_MODEL`` (e.g. google/gemma-3-27b-it).
  - ``google``   — Google AI Studio OpenAI-compatible endpoint using
                   ``GOOGLE_API_KEY_1/2`` with round-robin rotation.
  - ``opencode`` — legacy opencode.ai endpoint (single key).

Default when ``LLM_BACKEND`` is unset: ``nvidia``.
"""

from __future__ import annotations

import itertools
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

class RateLimitException(Exception):
    """Custom exception raised when the LLM provider returns a 429/rate-limit error."""
    pass

ROOT = Path(__file__).resolve().parent.parent.parent
ENV_PATH = ROOT / ".env"


# ---------------------------------------------------------------------------
# .env loader
# ---------------------------------------------------------------------------

def _load_env() -> Dict[str, str]:
    """Load simple KEY=VALUE pairs from .env (no dependency on python-dotenv).

    When the same key appears multiple times (e.g. NVIDIA_NIM_API_KEY_1
    defined twice by mistake), the LAST value wins for plain lookups.
    """
    env: Dict[str, str] = {}
    if not ENV_PATH.exists():
        return env
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


# ---------------------------------------------------------------------------
# Helpers: collect the *ordered* list of values for a numbered key family.
# e.g. NVIDIA_NIM_API_KEY_1, NVIDIA_NIM_API_KEY_2, NVIDIA_NIM_API_KEY_3
# ---------------------------------------------------------------------------

def _collect_key_family(env: Dict[str, str], prefix: str) -> List[str]:
    """Return all non-empty values whose key matches ``prefix + _N``.

    The keys are sorted numerically (1, 2, 3, …). Only keys with a
    numeric suffix are collected; the bare prefix is ignored.
    """
    collected: List[tuple[int, str]] = []
    for k, v in env.items():
        if k.startswith(prefix + "_") and v:
            suffix = k[len(prefix) + 1:]
            if suffix.isdigit():
                collected.append((int(suffix), v))
    collected.sort(key=lambda t: t[0])
    return [v for _, v in collected]


# Load once at import time
_ENV = _load_env()


# ---------------------------------------------------------------------------
# Round-robin key pool — thread-safe cycling over a list of API keys.
# ---------------------------------------------------------------------------

class _KeyPool:
    """Thread-safe round-robin pool of API keys.

    Args:
        keys: Ordered list of API key strings.
    """

    def __init__(self, keys: List[str]) -> None:
        self._keys = keys
        self._cycle = itertools.cycle(keys)
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._keys)

    def next(self) -> str:
        """Return the next key in round-robin order."""
        with self._lock:
            return next(self._cycle)


# ---------------------------------------------------------------------------
# NVIDIA NIM rubric caller  (google/gemma-3-27b-it by default)
# ---------------------------------------------------------------------------

class NvidiaRubricCaller:
    """Rubric LLM caller backed by NVIDIA NIM.

    Rotates round-robin across up to three NVIDIA NIM API keys
    (``NVIDIA_NIM_API_KEY_1``, ``NVIDIA_NIM_API_KEY_2``,
    ``NVIDIA_NIM_API_KEY_3``) configured in ``.env``.  On a 429
    rate-limit response the caller automatically retries with the next
    key (up to ``len(pool)`` attempts per call).

    The default model is ``google/gemma-3-27b-it`` — a text-only 27 B
    reasoning model available on NVIDIA NIM.  It requires no multimodal
    input and is well-suited for structured rubric scoring tasks.

    Args:
        model:      Override the model name (default: ``NVIDIA_NIM_RUBRIC_MODEL``
                    from ``.env``, or ``google/gemma-3-27b-it``).
        base_url:   Override the NIM endpoint URL.
        max_tokens: Maximum tokens to generate per call.
        temperature: Sampling temperature (0.0 = deterministic).
        timeout:    HTTP timeout in seconds.
    """

    # Default model: 27 B text reasoning model on NVIDIA NIM.
    _DEFAULT_MODEL = "google/gemma-3-27b-it"
    _DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
    _COOLDOWN_SECONDS = 60  # wait before reusing a rate-limited key

    def __init__(
        self,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        max_tokens: int = 4000,
        temperature: float = 0.0,
        timeout: float = 120.0,
    ) -> None:
        self.model_name = (
            model
            or _ENV.get("NVIDIA_NIM_RUBRIC_MODEL")
            or self._DEFAULT_MODEL
        )
        self.base_url = (
            base_url
            or _ENV.get("NVIDIA_NIM_BASE_URL")
            or self._DEFAULT_BASE_URL
        )
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout

        # Collect the API key pool from .env
        self._keys = _collect_key_family(_ENV, "NVIDIA_NIM_API_KEY")
        if not self._keys:
            logger.warning(
                "NvidiaRubricCaller: no NVIDIA_NIM_API_KEY_N found in .env — "
                "caller will return empty string."
            )
            self._available = False
            return

        self._pool = _KeyPool(self._keys)
        self._cooldown_until: Dict[str, float] = {}  # key → timestamp
        self._available = True
        logger.info(
            "NvidiaRubricCaller ready: model=%s base_url=%s keys=%d",
            self.model_name, self.base_url, len(self._keys),
        )

    def _next_available_key(self) -> Optional[str]:
        """Return the next key that is not currently in cooldown."""
        now = time.monotonic()
        for _ in range(len(self._keys)):
            key = self._pool.next()
            if self._cooldown_until.get(key, 0) <= now:
                return key
        # All keys in cooldown — wait for the soonest to clear.
        soonest = min(self._cooldown_until.values())
        wait = max(0.0, soonest - now)
        logger.warning(
            "NvidiaRubricCaller: all keys in cooldown, sleeping %.1fs", wait
        )
        time.sleep(wait)
        return self._pool.next()

    def __call__(self, prompt: str) -> str:
        """Send a rubric-scoring prompt and return the model's text response.

        Args:
            prompt: The full rubric-scoring prompt (text only).

        Returns:
            The assistant's raw text, or ``""`` on failure.
        """
        if not self._available:
            return ""

        from openai import OpenAI, RateLimitError

        attempts = len(self._keys)
        for attempt in range(attempts):
            key = self._next_available_key()
            if key is None:
                break
            try:
                client = OpenAI(
                    api_key=key,
                    base_url=self.base_url,
                    timeout=self.timeout,
                )
                response = client.chat.completions.create(
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
            except RateLimitError:
                logger.warning(
                    "NvidiaRubricCaller: 429 on key ...%s, cooling down %ds",
                    key[-6:], self._COOLDOWN_SECONDS,
                )
                self._cooldown_until[key] = time.monotonic() + self._COOLDOWN_SECONDS
            except Exception as exc:
                logger.warning(
                    "NvidiaRubricCaller: call failed (attempt %d/%d): %s",
                    attempt + 1, attempts, exc,
                )
        logger.error("NvidiaRubricCaller: all %d key attempts exhausted.", attempts)
        return ""


# ---------------------------------------------------------------------------
# Google AI rubric caller  (text-only, round-robin over GOOGLE_API_KEY_N)
# ---------------------------------------------------------------------------

class GoogleRubricCaller:
    """Rubric LLM caller backed by Google AI Studio (OpenAI-compatible).

    Rotates round-robin across ``GOOGLE_API_KEY_1`` and ``GOOGLE_API_KEY_2``
    configured in ``.env``.

    Rate-limit design:
    - Proactive throttle: at least ``_MIN_CALL_INTERVAL`` seconds between
      successive calls on the same key to stay safely under 15 RPM.
    - On 429: key goes into ``_COOLDOWN_SECONDS`` cooldown; immediately
      rotates to the next available key.
    - When ALL keys are in cooldown: sleeps exactly until the soonest key
      recovers (with exponential backoff between successive all-cooldown
      events to handle sustained throttling gracefully).
    - Never returns an empty string due to rate-limiting alone; retries for
      up to ``_MAX_RETRY_SECONDS`` (5 minutes) before giving up.

    Args:
        model:      Override the model name (default: ``gemini-3.1-flash-lite``).
        base_url:   Override the Google AI endpoint URL.
        max_tokens: Maximum tokens to generate per call.
        temperature: Sampling temperature (0.0 = deterministic).
        timeout:    HTTP timeout in seconds.
    """

    _DEFAULT_MODEL = "gemini-3.1-flash-lite"
    _DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
    # How long a key stays in cooldown after a 429.
    _COOLDOWN_SECONDS = 65
    # Minimum gap between successive calls on ANY key (15 RPM = 4 s/call;
    # with 2 keys interleaved this gives ~2 s effective gap per call).
    _MIN_CALL_INTERVAL = 2.1
    # Maximum wall-clock seconds to keep retrying before giving up entirely.
    _MAX_RETRY_SECONDS = 300

    def __init__(
        self,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        max_tokens: int = 4000,
        temperature: float = 0.0,
        timeout: float = 120.0,
    ) -> None:
        self.model_name = model or _ENV.get("GOOGLE_RUBRIC_MODEL") or self._DEFAULT_MODEL
        self.base_url = base_url or _ENV.get("GOOGLE_AI_BASE_URL") or self._DEFAULT_BASE_URL
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout

        self._keys = _collect_key_family(_ENV, "GOOGLE_API_KEY")
        if not self._keys:
            logger.warning(
                "GoogleRubricCaller: no GOOGLE_API_KEY_N found in .env — "
                "caller will return empty string."
            )
            self._available = False
            return

        self._pool = _KeyPool(self._keys)
        self._cooldown_until: Dict[str, float] = {}
        # Per-key last-call timestamp for proactive throttling.
        self._last_call: Dict[str, float] = {}
        self._available = True
        logger.info(
            "GoogleRubricCaller ready: model=%s keys=%d",
            self.model_name, len(self._keys),
        )

    def _next_available_key(self) -> Optional[str]:
        """Return a non-rate-limited key ready for a call, or None if all are cooling."""
        now = time.monotonic()
        for _ in range(len(self._keys)):
            key = self._pool.next()
            if self._cooldown_until.get(key, 0) <= now:
                return key
        return None  # All keys still in cooldown.

    def _throttle_key(self, key: str) -> None:
        """Sleep if needed so the minimum inter-call interval is respected for ``key``."""
        last = self._last_call.get(key, 0.0)
        elapsed = time.monotonic() - last
        if elapsed < self._MIN_CALL_INTERVAL:
            time.sleep(self._MIN_CALL_INTERVAL - elapsed)

    def __call__(self, prompt: str) -> str:
        """Send a rubric-scoring prompt and return the model's text response.

        Uses a time-budget retry loop: retries indefinitely (with appropriate
        sleeps) for up to ``_MAX_RETRY_SECONDS`` before returning an empty
        string. This prevents the caller from giving up prematurely on 429s.
        """
        if not self._available:
            return ""

        from openai import OpenAI, RateLimitError

        deadline = time.monotonic() + self._MAX_RETRY_SECONDS
        all_cooldown_count = 0  # consecutive all-keys-in-cooldown events

        while time.monotonic() < deadline:
            key = self._next_available_key()

            if key is None:
                # All keys in cooldown — sleep until the soonest recovers.
                now = time.monotonic()
                soonest = min(self._cooldown_until.values())
                wait = max(1.0, soonest - now)
                all_cooldown_count += 1
                # Add small exponential padding to avoid immediately re-429ing.
                extra = min(2.0 ** (all_cooldown_count - 1), 10.0)
                total_wait = wait + extra
                logger.warning(
                    "GoogleRubricCaller: all %d keys in cooldown, sleeping %.1fs "
                    "(cooldown_event=%d).",
                    len(self._keys), total_wait, all_cooldown_count,
                )
                time.sleep(total_wait)
                continue

            # Proactive throttle: pace calls to stay under 15 RPM/key.
            self._throttle_key(key)

            try:
                client = OpenAI(
                    api_key=key,
                    base_url=self.base_url,
                    timeout=self.timeout,
                )
                response = client.chat.completions.create(
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
                self._last_call[key] = time.monotonic()
                all_cooldown_count = 0  # reset on success
                content = response.choices[0].message.content or ""
                return content.strip()

            except RateLimitError:
                logger.warning(
                    "GoogleRubricCaller: 429 on key ...%s, cooling down %ds — "
                    "rotating to next key.",
                    key[-6:], self._COOLDOWN_SECONDS,
                )
                self._cooldown_until[key] = time.monotonic() + self._COOLDOWN_SECONDS
                # Immediately loop to try the next available key (no sleep here).
                continue

            except Exception as exc:
                logger.warning(
                    "GoogleRubricCaller: call failed: %s — will retry.",
                    exc,
                )
                # Brief pause before retrying on non-429 errors.
                time.sleep(2.0)

        logger.error(
            "GoogleRubricCaller: gave up after %.0fs of retries.",
            self._MAX_RETRY_SECONDS,
        )
        return ""




# ---------------------------------------------------------------------------
# OpenRouter caller  (3-key rotation, google/gemma-4-31b-it by default)
# ---------------------------------------------------------------------------


class OpenRouterRubricCaller:
    """Rubric LLM caller via OpenRouter (OpenAI-compatible endpoint).

    Rotates across up to ``OPENROUTER_API_KEY_N`` keys from ``.env``.
    Default model: ``google/gemma-4-31b-it:free`` (Gemma 4, 31B — free tier).

    Rate-limit design (mirrors GoogleRubricCaller):
    - Proactive throttle: minimum interval between calls per key to stay
      safely under 16 RPM (OpenRouter free-models-per-min limit).
    - On 429: key enters cooldown; immediately rotates to next key.
    - When ALL keys cooling: sleeps with exponential backoff padding.
    - Never returns empty string due to rate-limiting alone (5-min budget).

    Args:
        model:      Override model string. Reads ``OPENROUTER_RUBRIC_MODEL``
                    from ``.env`` if not provided.
        base_url:   Override base URL. Reads ``OPENROUTER_BASE_URL`` from
                    ``.env`` if not provided.
        max_tokens: Maximum tokens in the LLM response.
        temperature: Sampling temperature (0.0 = deterministic).
        timeout:    HTTP timeout in seconds.
    """

    _DEFAULT_MODEL = "google/gemma-4-31b-it:free"
    # Fallback model tried on the SAME key when the primary hits 429 upstream.
    # minimax-m3 uses a different provider pool so it rarely co-limits.
    _FALLBACK_MODEL = "minimax/minimax-m3"
    _DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
    # 16 RPM free limit → 3.75 s/call; with N keys interleaved, min_interval
    # between calls on the *same* key is 3.9 s to stay safely below the limit.
    _COOLDOWN_SECONDS = 65
    _MIN_CALL_INTERVAL = 3.9
    _MAX_RETRY_SECONDS = 300

    def __init__(
        self,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        max_tokens: int = 4000,
        temperature: float = 0.0,
        timeout: float = 120.0,
    ) -> None:
        self.model_name = model or _ENV.get("OPENROUTER_RUBRIC_MODEL") or self._DEFAULT_MODEL
        self.base_url = base_url or _ENV.get("OPENROUTER_BASE_URL") or self._DEFAULT_BASE_URL
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout

        self._keys = _collect_key_family(_ENV, "OPENROUTER_API_KEY")
        if not self._keys:
            logger.warning(
                "OpenRouterRubricCaller: no OPENROUTER_API_KEY_N found in .env — "
                "caller will return empty string."
            )
            self._available = False
            return

        self._pool = _KeyPool(self._keys)
        self._cooldown_until: Dict[str, float] = {}
        self._last_call: Dict[str, float] = {}
        self._available = True
        logger.info(
            "OpenRouterRubricCaller ready: model=%s keys=%d",
            self.model_name, len(self._keys),
        )

    def _next_available_key(self) -> Optional[str]:
        """Return a non-rate-limited key, or None if all keys are in cooldown."""
        now = time.monotonic()
        for _ in range(len(self._keys)):
            key = self._pool.next()
            if self._cooldown_until.get(key, 0) <= now:
                return key
        return None

    def _throttle_key(self, key: str) -> None:
        """Sleep if needed to respect the minimum per-key call interval."""
        last = self._last_call.get(key, 0.0)
        elapsed = time.monotonic() - last
        if elapsed < self._MIN_CALL_INTERVAL:
            time.sleep(self._MIN_CALL_INTERVAL - elapsed)

    def _call_model(self, client: Any, model: str, prompt: str) -> str:
        """Make a single chat completion call with the given model.

        Args:
            client: Initialized OpenAI client.
            model:  Model string to pass to the API.
            prompt: Full rubric-scoring prompt.

        Returns:
            Stripped response text.

        Raises:
            RateLimitError: propagated so the caller can handle rotation.
            Exception: any other API error.
        """
        response = client.chat.completions.create(
            model=model,
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
        return (response.choices[0].message.content or "").strip()

    def __call__(self, prompt: str) -> str:
        """Send a rubric-scoring prompt and return the model's text response.

        Strategy per iteration:
          1. Get an available (non-cooling) key.
          2. Throttle to stay under 16 RPM/key.
          3. Try the PRIMARY model (gemma-4-31b-it:free).
          4. On 429, immediately try the FALLBACK model (minimax-m3) on the
             SAME key — different provider pool, rarely co-rate-limits.
          5. Only if fallback also 429s does the key enter cooldown and
             the loop rotates to the next key.
          6. Never returns empty string due to rate-limits alone (5-min budget).
        """
        if not self._available:
            return ""

        from openai import OpenAI, RateLimitError

        deadline = time.monotonic() + self._MAX_RETRY_SECONDS
        all_cooldown_count = 0

        while time.monotonic() < deadline:
            key = self._next_available_key()

            if key is None:
                now = time.monotonic()
                soonest = min(self._cooldown_until.values())
                wait = max(1.0, soonest - now)
                all_cooldown_count += 1
                extra = min(2.0 ** (all_cooldown_count - 1), 10.0)
                total_wait = wait + extra
                logger.warning(
                    "OpenRouterRubricCaller: all %d keys in cooldown, sleeping %.1fs "
                    "(cooldown_event=%d).",
                    len(self._keys), total_wait, all_cooldown_count,
                )
                time.sleep(total_wait)
                continue

            self._throttle_key(key)

            try:
                client = OpenAI(
                    api_key=key,
                    base_url=self.base_url,
                    timeout=self.timeout,
                )
                # --- Primary model attempt ---
                try:
                    result = self._call_model(client, self.model_name, prompt)
                    self._last_call[key] = time.monotonic()
                    all_cooldown_count = 0
                    return result
                except RateLimitError:
                    logger.warning(
                        "OpenRouterRubricCaller: 429 on primary model '%s' key ...%s "
                        "— trying fallback '%s' on same key.",
                        self.model_name, key[-6:], self._FALLBACK_MODEL,
                    )

                # --- Fallback model attempt (same key, different provider pool) ---
                try:
                    result = self._call_model(client, self._FALLBACK_MODEL, prompt)
                    self._last_call[key] = time.monotonic()
                    all_cooldown_count = 0
                    logger.info(
                        "OpenRouterRubricCaller: fallback '%s' succeeded on key ...%s.",
                        self._FALLBACK_MODEL, key[-6:],
                    )
                    return result
                except RateLimitError:
                    logger.warning(
                        "OpenRouterRubricCaller: fallback also 429 on key ...%s — "
                        "cooling down %ds and rotating.",
                        key[-6:], self._COOLDOWN_SECONDS,
                    )
                    self._cooldown_until[key] = time.monotonic() + self._COOLDOWN_SECONDS
                    continue

            except Exception as exc:
                logger.warning(
                    "OpenRouterRubricCaller: call failed: %s — will retry.",
                    exc,
                )
                time.sleep(2.0)


        logger.error(
            "OpenRouterRubricCaller: gave up after %.0fs of retries.",
            self._MAX_RETRY_SECONDS,
        )
        return ""


# ---------------------------------------------------------------------------
# Legacy opencode.ai caller  (single key, kept for backward compatibility)
# ---------------------------------------------------------------------------

OPENCODE_API_KEY: Optional[str] = _ENV.get("OPENCODE_API_KEY_1") or _ENV.get("OPENCODE_API_KEY")
OPENCODE_BASE_URL: str = "https://opencode.ai/zen/go/v1"
OPENCODE_MODEL: str = _ENV.get("model", "MiMo V2.5 Free")


class LLMRubricCaller:
    """Legacy opencode.ai rubric caller (single key, kept for compatibility).

    For new deployments prefer :class:`NvidiaRubricCaller` or
    :class:`GoogleRubricCaller` which support key rotation.
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
            logger.info(
                "LLM caller ready: model=%s base_url=%s", self.model_name, self.base_url
            )
        except Exception as e:
            logger.warning("Failed to initialize OpenAI client: %s", e)

    def __call__(self, prompt: str) -> str:
        if not self._available or self._client is None:
            return ""
        
        import openai
        import random
        import time

        max_retries = 3
        
        for attempt in range(max_retries + 1):
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
            except openai.RateLimitError as rle:
                if attempt < max_retries:
                    backoff = (3.0 + random.uniform(0.0, 2.0)) * (2 ** attempt)
                    logger.warning(
                        "LLMRubricCaller rate limited (primary/fallback model). Retrying in %.2fs (attempt %d/%d)...",
                        backoff, attempt + 1, max_retries
                    )
                    time.sleep(backoff)
                    continue
                else:
                    logger.error("LLMRubricCaller: Rate limit retries exhausted.")
                    raise RateLimitException("Provider rate limit encountered after retries") from rle
            except Exception as e:
                # Some API providers return rate limit messages in error text instead of correct status code/class
                err_text = str(e).lower()
                is_rate_limit = "rate limit" in err_text or "too many requests" in err_text or "429" in err_text
                if is_rate_limit:
                    if attempt < max_retries:
                        backoff = (3.0 + random.uniform(0.0, 2.0)) * (2 ** attempt)
                        logger.warning(
                            "LLMRubricCaller rate limited (exception text). Retrying in %.2fs (attempt %d/%d)...",
                            backoff, attempt + 1, max_retries
                        )
                        time.sleep(backoff)
                        continue
                    else:
                        logger.error("LLMRubricCaller: Rate limit retries exhausted.")
                        raise RateLimitException("Provider rate limit encountered after retries") from e
                
                logger.warning("LLMRubricCaller call failed: %s", e)
                if attempt < max_retries:
                    time.sleep(2.0)
                    continue
                return ""


# ---------------------------------------------------------------------------
# Module-level default caller (lazy-initialized)
# ---------------------------------------------------------------------------

_default_caller: Optional[Any] = None


def get_default_caller() -> Any:
    """Return the module-level default rubric caller (lazy-initialized)."""
    global _default_caller
    if _default_caller is None:
        _default_caller = get_rubric_caller()
    return _default_caller


# ---------------------------------------------------------------------------
# Factory: get_rubric_caller()
# ---------------------------------------------------------------------------

def get_rubric_caller() -> Any:
    """Factory returning the configured rubric LLM caller.

    Checks RECRUITER_API_KEY from environment variables first (recruiter BYOK).
    """
    recruiter_key = os.environ.get("RECRUITER_API_KEY")
    recruiter_base = os.environ.get("RECRUITER_BASE_URL")
    recruiter_model = os.environ.get("RECRUITER_MODEL")
    if recruiter_key:
        return LLMRubricCaller(
            api_key=recruiter_key,
            base_url=recruiter_base or "https://openrouter.ai/api/v1",
            model=recruiter_model or "google/gemma-4-31b-it"
        )

    backend = (
        os.environ.get("LLM_BACKEND")
        or _ENV.get("LLM_BACKEND")
        or "openrouter"
    ).lower().strip()

    if backend == "openrouter":
        caller = OpenRouterRubricCaller()
        if caller._available:
            return caller
        logger.warning(
            "LLM_BACKEND=openrouter but OpenRouterRubricCaller is not available — "
            "falling back to google backend."
        )
        caller = GoogleRubricCaller()
        if caller._available:
            return caller
        return LLMRubricCaller()

    if backend == "nvidia":
        caller = NvidiaRubricCaller()
        if caller._available:
            return caller
        logger.warning(
            "LLM_BACKEND=nvidia but NvidiaRubricCaller is not available — "
            "falling back to google backend."
        )
        caller = GoogleRubricCaller()
        if caller._available:
            return caller
        logger.warning("GoogleRubricCaller also not available — falling back to opencode.")
        return LLMRubricCaller()

    if backend == "google":
        caller = GoogleRubricCaller()
        if caller._available:
            return caller
        logger.warning(
            "LLM_BACKEND=google but GoogleRubricCaller is not available — "
            "falling back to openrouter backend."
        )
        caller = OpenRouterRubricCaller()
        if caller._available:
            return caller
        return LLMRubricCaller()

    # opencode or unknown
    return LLMRubricCaller()
