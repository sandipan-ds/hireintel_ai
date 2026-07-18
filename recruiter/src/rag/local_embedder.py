"""LocalEmbedder — wrapper around the fastembed library to run local, quantized ONNX models (768-dim, no PyTorch).

Why this exists:
    Replaced the legacy Gemini API calling logic (which suffered from rate limits).
    Uses FastEmbed:
      - Runs 100% locally with ONNX Runtime (highly optimized for CPU/Cloud Run).
      - No PyTorch runtime needed.
      - Zero network requests, rate limits, or API key requirements.
      - Outputs 768-dim vectors compatible with the existing index.npz.
"""

from __future__ import annotations

import logging
from typing import List, Union

import numpy as np

logger = logging.getLogger(__name__)


class FastEmbedder:
    """Wrapper around FastEmbed TextEmbedding for CPU-optimized local embeddings."""

    embedding_dim: int = 768

    def __init__(
        self,
        model_name: str = "BAAI/bge-base-en-v1.5",
        task_type: str = "RETRIEVAL_DOCUMENT",
    ) -> None:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise ImportError(
                "fastembed is required. Install it with: pip install fastembed"
            ) from exc

        self.model_name = model_name
        self.task_type = task_type

        logger.info("Initializing FastEmbed with model: %s", self.model_name)
        self._model = TextEmbedding(model_name=self.model_name)
        logger.info("FastEmbed initialized successfully.")

    def encode(
        self,
        sentences: Union[str, List[str]],
        batch_size: int = 32,
        normalize_embeddings: bool = True,
        show_progress_bar: bool = False,
        convert_to_numpy: bool = True,
        **_kwargs,   # absorb extra kwargs (e.g. device=) without error
    ) -> np.ndarray:
        """Embed sentences locally and return an ``(N, 768)`` float32 numpy array."""
        if isinstance(sentences, str):
            sentences = [sentences]

        if not sentences:
            return np.zeros((0, self.embedding_dim), dtype=np.float32)

        # Apply BGE query prefix if task_type is RETRIEVAL_QUERY
        if self.task_type == "RETRIEVAL_QUERY":
            prefixed = []
            for s in sentences:
                if not s.startswith("Represent this sentence for searching relevant passages: "):
                    prefixed.append(f"Represent this sentence for searching relevant passages: {s}")
                else:
                    prefixed.append(s)
            sentences = prefixed

        # Generate embeddings using FastEmbed
        # .embed returns a generator of numpy arrays
        embeddings_gen = self._model.embed(sentences, batch_size=batch_size)
        result = np.array(list(embeddings_gen), dtype=np.float32)

        if normalize_embeddings:
            norms = np.linalg.norm(result, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1.0, norms)
            result = result / norms

        return result
