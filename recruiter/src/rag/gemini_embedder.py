"""GeminiEmbedder — drop-in replacement for SentenceTransformer using the
Google Gemini ``text-embedding-004`` REST API (768-dim, free tier).

Why this exists (DEC-036):
    The previous embedding approach loaded ``BAAI/bge-base-en-v1.5`` via
    ``sentence-transformers`` + PyTorch at container startup.  This baked
    ~1.7 GB of model weights + PyTorch runtime into the Docker image (total
    image size: ~3.94 GB) and caused:
        - 60–90 second cold-start hangs while PyTorch initialised on CPU.
        - Rust tokenizer deadlocks under Cloud Run gVisor sandboxed kernels.
        - HuggingFace cache path mismatches between build-time and run-time.

    Replacing local inference with ``text-embedding-004`` via the Gemini API:
        - Drops ``torch``, ``torchvision``, ``sentence-transformers``,
          ``transformers``, and ``accelerate`` from the production image.
        - Reduces the Docker image from ~3.94 GB to ~700 MB.
        - Eliminates cold-start CPU hangs entirely.
        - The free tier allows 1,500 RPM — more than enough for all serving
          and indexing operations for the current candidate pool sizes.

Design:
    ``GeminiEmbedder`` mirrors the exact ``SentenceTransformer.encode()``
    interface used throughout the codebase so callers in ``build_index.py``
    and ``per_req_retrieval.py`` require zero signature changes.

    Key-rotation follows the same ``GOOGLE_API_KEY_1 / GOOGLE_API_KEY_2``
    convention already used by ``llm_caller.py`` (line 308).

Output dimensions:
    ``text-embedding-004`` outputs **768-dimensional** unit-normalised
    vectors — identical dimensionality to ``BAAI/bge-base-en-v1.5``.
    The existing ``index.npz`` binary format (``vectors`` shape (N, 768))
    is fully compatible; no re-indexing schema changes required.

Usage::

    from recruiter.src.rag.gemini_embedder import GeminiEmbedder

    embedder = GeminiEmbedder()           # reads GOOGLE_API_KEY_1 from env
    vectors = embedder.encode(["text 1", "text 2"], normalize_embeddings=True)
    # → np.ndarray shape (2, 768), dtype float32
"""

from __future__ import annotations

import logging
import os
import time
from typing import List, Optional, Union

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Gemini embedding model. text-embedding-004 = 768-dim, free tier, REST API.
GEMINI_EMBEDDING_MODEL: str = "text-embedding-004"

#: Gemini Generative Language REST endpoint template.
_EMBED_URL_TEMPLATE: str = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:embedContent?key={api_key}"
)

#: Maximum texts per single API request (Gemini supports batch via batchEmbedContents).
_BATCH_SIZE: int = 100

#: Seconds to wait between retries on rate-limit (429) or server errors (5xx).
_RETRY_WAIT_SECONDS: float = 2.0

#: Maximum retry attempts per batch before raising.
_MAX_RETRIES: int = 4


# ---------------------------------------------------------------------------
# Key loading helper — mirrors llm_caller.py convention (GOOGLE_API_KEY_N).
# ---------------------------------------------------------------------------

def _load_google_api_keys() -> List[str]:
    """Collect Gemini API keys from environment variables.

    Checks the following env var families in priority order:
        1. ``GEMINI_API_KEY_N``   (e.g. GEMINI_API_KEY_1, GEMINI_API_KEY_2)
        2. ``GOOGLE_API_KEY_N``   (legacy convention used by llm_caller.py)
        3. Bare ``GEMINI_API_KEY`` or ``GOOGLE_API_KEY`` as final fallback.

    Returns:
        Non-empty list of API key strings.

    Raises:
        RuntimeError:
            If no key is found in the environment.
    """
    keys: List[str] = []

    # 1. GEMINI_API_KEY_1, GEMINI_API_KEY_2, ... (user convention in .env.gcp)
    for i in range(1, 10):
        value = os.environ.get(f"GEMINI_API_KEY_{i}", "").strip()
        if value and value not in keys:
            keys.append(value)

    # 2. GOOGLE_API_KEY_1, GOOGLE_API_KEY_2, ... (llm_caller.py convention)
    for i in range(1, 10):
        value = os.environ.get(f"GOOGLE_API_KEY_{i}", "").strip()
        if value and value not in keys:
            keys.append(value)

    # 3. Bare fallbacks
    for bare_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        value = os.environ.get(bare_name, "").strip()
        if value and value not in keys:
            keys.append(value)

    if not keys:
        raise RuntimeError(
            "GeminiEmbedder: no API key found. Set GEMINI_API_KEY_1 (or "
            "GOOGLE_API_KEY_1) in your environment or Cloud Run secrets."
        )

    return keys



# ---------------------------------------------------------------------------
# GeminiEmbedder
# ---------------------------------------------------------------------------


class GeminiEmbedder:
    """Drop-in replacement for ``SentenceTransformer`` using Gemini REST API.

    This class exposes the same ``.encode()`` method signature as
    ``sentence_transformers.SentenceTransformer`` so existing callers in
    ``build_index.py`` and ``per_req_retrieval.py`` work without changes.

    Args:
        model_name:
            Gemini embedding model identifier.  Defaults to
            ``"text-embedding-004"`` (768-dim, free tier).
        task_type:
            Gemini embedding task type hint.  Use ``"RETRIEVAL_QUERY"``
            when embedding search queries and ``"RETRIEVAL_DOCUMENT"``
            when embedding passages to be indexed.  Defaults to
            ``"RETRIEVAL_DOCUMENT"`` to match BGE-base retrieval training.

    Attributes:
        model_name (str): The Gemini model being used.
        embedding_dim (int): Always 768 for ``text-embedding-004``.
    """

    embedding_dim: int = 768

    def __init__(
        self,
        model_name: str = GEMINI_EMBEDDING_MODEL,
        task_type: str = "RETRIEVAL_DOCUMENT",
    ) -> None:
        # Import requests lazily so the module can be imported without it
        # being installed (test environments skip this embedder entirely).
        try:
            import requests as _requests  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "GeminiEmbedder requires the 'requests' package. "
                "Install it with: pip install requests"
            ) from exc

        self.model_name = model_name
        self.task_type = task_type
        self._keys = _load_google_api_keys()
        self._key_index = 0  # round-robin cursor

        logger.info(
            "GeminiEmbedder initialised: model=%s  task_type=%s  keys=%d",
            self.model_name, self.task_type, len(self._keys),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _next_key(self) -> str:
        """Return the next API key in round-robin order."""
        key = self._keys[self._key_index % len(self._keys)]
        self._key_index += 1
        return key

    def _embed_batch(self, texts: List[str]) -> np.ndarray:
        """Embed one batch of texts via the Gemini batchEmbedContents endpoint.

        Args:
            texts:
                List of non-empty strings to embed (max ``_BATCH_SIZE``).

        Returns:
            ``np.ndarray`` of shape ``(len(texts), 768)``, dtype float32,
            with each row already L2-normalised (Gemini returns unit vectors
            when ``normalize_embeddings=True`` is the API default).

        Raises:
            RuntimeError:
                If all retries are exhausted without a successful response.
        """
        import requests  # already confirmed available in __init__

        # batchEmbedContents accepts a list of ``requests`` objects.
        payload = {
            "requests": [
                {
                    "model": f"models/{self.model_name}",
                    "content": {"parts": [{"text": text}]},
                    "taskType": self.task_type,
                }
                for text in texts
            ]
        }

        api_key = self._next_key()
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model_name}:batchEmbedContents?key={api_key}"
        )

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = requests.post(url, json=payload, timeout=30)

                if response.status_code == 200:
                    data = response.json()
                    embeddings = data.get("embeddings", [])
                    vectors = np.array(
                        [emb["values"] for emb in embeddings],
                        dtype=np.float32,
                    )
                    return vectors

                if response.status_code == 429:
                    # Rate limit — rotate key and wait before retry.
                    logger.warning(
                        "GeminiEmbedder: 429 rate limit on attempt %d/%d. "
                        "Rotating key and waiting %.1fs.",
                        attempt, _MAX_RETRIES, _RETRY_WAIT_SECONDS * attempt,
                    )
                    api_key = self._next_key()
                    url = (
                        f"https://generativelanguage.googleapis.com/v1beta/models/"
                        f"{self.model_name}:batchEmbedContents?key={api_key}"
                    )
                    time.sleep(_RETRY_WAIT_SECONDS * attempt)
                    continue

                # Server error — retry with backoff.
                logger.warning(
                    "GeminiEmbedder: HTTP %d on attempt %d/%d. Body: %.200s",
                    response.status_code, attempt, _MAX_RETRIES, response.text,
                )
                time.sleep(_RETRY_WAIT_SECONDS * attempt)

            except requests.RequestException as exc:
                logger.warning(
                    "GeminiEmbedder: network error on attempt %d/%d: %s",
                    attempt, _MAX_RETRIES, exc,
                )
                time.sleep(_RETRY_WAIT_SECONDS * attempt)

        raise RuntimeError(
            f"GeminiEmbedder: failed to embed batch of {len(texts)} texts "
            f"after {_MAX_RETRIES} attempts."
        )

    # ------------------------------------------------------------------
    # Public interface — mirrors SentenceTransformer.encode()
    # ------------------------------------------------------------------

    def encode(
        self,
        sentences: Union[str, List[str]],
        batch_size: int = _BATCH_SIZE,
        normalize_embeddings: bool = True,
        show_progress_bar: bool = False,
        convert_to_numpy: bool = True,
        **_kwargs,   # absorb extra kwargs (e.g. device=) without error
    ) -> np.ndarray:
        """Embed sentences and return an ``(N, 768)`` float32 numpy array.

        Drop-in replacement for ``SentenceTransformer.encode()``.  All
        keyword arguments accepted by ``SentenceTransformer.encode`` are
        accepted here; unsupported ones are silently ignored.

        Args:
            sentences:
                A single string or a list of strings to embed.
            batch_size:
                Number of texts per API request.  The Gemini free tier
                allows up to 100 texts per ``batchEmbedContents`` call.
                Defaults to 100.
            normalize_embeddings:
                If ``True`` (default), L2-normalise each row so cosine
                similarity equals dot product.  Gemini returns approximately
                unit vectors already; this step ensures exact unit norms.
            show_progress_bar:
                Accepted for API compatibility; has no effect.
            convert_to_numpy:
                Accepted for API compatibility; always returns np.ndarray.
            **_kwargs:
                Any other keyword arguments (e.g. ``device``, ``precision``)
                are silently accepted and ignored for drop-in compatibility.

        Returns:
            ``np.ndarray`` of shape ``(N, 768)``, dtype ``float32``,
            where N is the number of input sentences.
        """
        if isinstance(sentences, str):
            sentences = [sentences]

        if not sentences:
            return np.zeros((0, self.embedding_dim), dtype=np.float32)

        # Split into batches and embed.
        all_vectors: List[np.ndarray] = []
        for start in range(0, len(sentences), batch_size):
            batch = sentences[start : start + batch_size]
            vecs = self._embed_batch(batch)
            all_vectors.append(vecs)

        result = np.concatenate(all_vectors, axis=0).astype(np.float32)

        # L2-normalise so cosine similarity = dot product (identical to
        # BGE-base-en-v1.5 with normalize_embeddings=True).
        if normalize_embeddings:
            norms = np.linalg.norm(result, axis=1, keepdims=True)
            # Avoid division by zero for any degenerate zero-vectors.
            norms = np.where(norms == 0, 1.0, norms)
            result = result / norms

        return result
