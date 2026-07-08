"""MLflow experiment-tracking wiring for batch scoring runs (Track M0.5c, DEC-020).

This module is the single integration point between the HireIntel scoring
pipeline and the local MLflow tracking server. It exists so that:

1. Pipeline code (``scripts/score_batch_composed.py`` and future Optuna
   drivers) never imports :mod:`mlflow` directly. Every call goes through
   the typed helpers here, which keeps the DEC-020 contract (params /
   metrics / artifacts / tags) in one auditable place.
2. Test code can exercise the logging contract without a running MLflow
   server. ``MLflowRun`` accepts an in-memory SQLite tracking URI
   (``sqlite:///<tmp>/mlflow.db``) so unit tests are hermetic and fast.
3. Production runs degrade gracefully if :mod:`mlflow` is not installed.
   Every helper becomes a no-op that logs a single warning, so a missing
   dependency never breaks a scoring run — it only breaks experiment
   tracking.

Canonical MLflow configuration (DEC-020, ``docs/EVALUATION.md`` §"MLflow
contract"):

    Tracking URI   http://127.0.0.1:5000
    Backend store  data/mlflow/mlflow.db   (SQLite)
    Artifact root  data/mlflow/artifacts/
    Per-run tags   experiment_set, role
    Required params   chunk_size, chunk_overlap, embedding_model, vector_store,
                      similarity, retrieval_mode, threshold, top_k, llm
    Required metrics  *_at_theta, mrr, ndcg, avg_chunks_returned,
                      p95_chunks_returned, cap_hit_rate, faithfulness,
                      groundedness, answer_relevancy, hallucination_rate
    Required artifacts  retrieved_chunks.json, eval_set.jsonl,
                        study_summary.json (Optuna-only)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional mlflow import.
#
# ``mlflow`` is conditionally required: production runs expect it installed,
# but unit tests and minimal dev boxes may not have it. We probe at import
# time and route every public helper through ``_available`` so the absence
# of the dependency degrades to a no-op rather than an ImportError.
# ---------------------------------------------------------------------------
try:
    import mlflow  # type: ignore[import-not-found]

    _available = True
    _import_error: str | None = None
except ImportError as exc:  # pragma: no cover - exercised via monkeypatch.
    ml = None  # type: ignore[assignment]
    _available = False
    _import_error = str(exc)

__all__ = [
    "DEFAULT_TRACKING_URI",
    "DEFAULT_BACKEND_STORE",
    "DEFAULT_ARTIFACT_ROOT",
    "PipelineParams",
    "RetrievalMetrics",
    "MLflowRun",
    "configure_tracking",
    "is_available",
]


# Canonical DEC-020 server configuration. Exposed as module constants so the
# convenience launcher (``scripts/start_mlflow_server.py``) and tests share a
# single source of truth rather than re-string-encoding the contract.
DEFAULT_TRACKING_URI: str = "http://127.0.0.1:5000"
DEFAULT_BACKEND_STORE: str = "data/mlflow/mlflow.db"
DEFAULT_ARTIFACT_ROOT: str = "data/mlflow/artifacts/"


def is_available() -> bool:
    """Return ``True`` iff the :mod:`mlflow` dependency is importable.

    Used by the batch CLI to decide whether to log a hard warning when the
    operator asked for tracking but the library is missing.
    """
    return _available


# ---------------------------------------------------------------------------
# Typed config containers.
#
# These dataclasses centralize the DEC-020 required params/metrics so the
# batch CLI passes a single structured object rather than a dozen kwargs.
# Adding a field here is the only change needed to widen the contract; every
# caller picks it up automatically.
# ---------------------------------------------------------------------------


@dataclass
class PipelineParams:
    """DEC-020 required params for a single scoring run.

    Every field maps to an ``mlflow.log_param`` key. Defaults mirror the
    shipped RecursiveChunker + ThresholdRetriever config so a run that forgets
    to populate a field still records a meaningful baseline rather than
    ``None``.
    """

    chunk_size: int = 500
    chunk_overlap: int = 100
    embedding_model: str = "all-MiniLM-L6-v2"
    vector_store: str = "npz"
    similarity: str = "cosine"
    retrieval_mode: str = "threshold"
    threshold: float = 0.30
    top_k: int = 20
    llm: str = "off"  # "off" when --no-llm; otherwise the model id.

    def to_dict(self) -> dict[str, Any]:
        """Return the param dict in the exact key order of the contract."""
        return {
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "embedding_model": self.embedding_model,
            "vector_store": self.vector_store,
            "similarity": self.similarity,
            "retrieval_mode": self.retrieval_mode,
            "threshold": float(self.threshold),
            "top_k": int(self.top_k),
            "llm": self.llm,
        }


@dataclass
class RetrievalMetrics:
    """DEC-020 required metrics for a single scoring run.

    Fields default to ``0.0`` so partial runs (e.g. ``--no-llm`` smoke
    tests where faithfulness is undefined) still emit every required metric
    key; MLflow treats the zero entries as "not measured this run" rather
    than "missing contract field".
    """

    recall_at_theta: float = 0.0
    precision_at_theta: float = 0.0
    mrr: float = 0.0
    ndcg: float = 0.0
    avg_chunks_returned: float = 0.0
    p95_chunks_returned: float = 0.0
    cap_hit_rate: float = 0.0
    faithfulness: float = 0.0
    groundedness: float = 0.0
    answer_relevancy: float = 0.0
    hallucination_rate: float = 0.0

    def to_dict(self) -> dict[str, float]:
        """Return the metric dict keyed by the DEC-020 contract names."""
        return {
            "recall_at_theta": float(self.recall_at_theta),
            "precision_at_theta": float(self.precision_at_theta),
            "mrr": float(self.mrr),
            "ndcg": float(self.ndcg),
            "avg_chunks_returned": float(self.avg_chunks_returned),
            "p95_chunks_returned": float(self.p95_chunks_returned),
            "cap_hit_rate": float(self.cap_hit_rate),
            "faithfulness": float(self.faithfulness),
            "groundedness": float(self.groundedness),
            "answer_relevancy": float(self.answer_relevancy),
            "hallucination_rate": float(self.hallucination_rate),
        }


# ---------------------------------------------------------------------------
# Tracking configuration.
# ---------------------------------------------------------------------------


def configure_tracking(
    tracking_uri: str = DEFAULT_TRACKING_URI,
    backend_store: str = DEFAULT_BACKEND_STORE,
    artifact_root: str = DEFAULT_ARTIFACT_ROOT,
) -> None:
    """Point :mod:`mlflow` at the DEC-020 tracking server.

    Args:
        tracking_uri: HTTP URI of the running MLflow server.
        backend_store: SQLite path (only used when the caller starts a local
            server; passed through to ``scripts/start_mlflow_server.py``).
        artifact_root: Filesystem path for MLflow artifacts.

    Side effects:
        Calls ``mlflow.set_tracking_uri`` globally. Creates the artifact
        root directory if missing so the first run does not fail.
    """
    if not _available:
        logger.warning("mlflow not installed; configure_tracking is a no-op.")
        return
    mlflow.set_tracking_uri(tracking_uri)
    Path(artifact_root).mkdir(parents=True, exist_ok=True)
    _ = backend_store  # reserved for the launcher; tracked for symmetry.


# ---------------------------------------------------------------------------
# Run context manager.
# ---------------------------------------------------------------------------


@dataclass
class MLflowRun:
    """Context manager wrapping a single ``mlflow.start_run`` block.

    Why a class rather than a bare ``contextlib.contextmanager``: the batch
    CLI needs to call typed helpers (``log_pipeline_params``,
    ``log_retrieval_metrics``) *during* the run, and a class gives those
    helpers a stable owner. Each helper no-ops cleanly when ``mlflow`` is
    unavailable, so the caller does not need to gate every site on
    :func:`is_available`.

    Attributes:
        experiment_name: MLflow experiment (created on first use).
        run_name: Human-readable name for this run.
        experiment_set: Tag value written to ``experiment_set`` (DEC-020).
        role: Tag value written to ``role`` (e.g. ``BusinessAnalyst``).
        tracking_uri: Override the default server URI (used by tests).
    """

    experiment_name: str
    run_name: str
    experiment_set: str = "default"
    role: str = "all"
    tracking_uri: str = DEFAULT_TRACKING_URI

    _active: bool = field(default=False, init=False, repr=False)

    def __enter__(self) -> MLflowRun:
        if not _available:
            logger.warning(
                "mlflow not installed (%s); run '%s' will not be tracked.",
                _import_error, self.run_name,
            )
            return self
        mlflow.set_tracking_uri(self.tracking_uri)
        mlflow.set_experiment(self.experiment_name)
        # ``mlflow.start_run`` returns an ActiveRun; we deliberately do not
        # keep a reference because the helpers below resolve the active run
        # via the module-level ``mlflow.active_run()`` lookup. This keeps the
        # class picklable for future Optuna drivers that may fork workers.
        mlflow.start_run(run_name=self.run_name)
        mlflow.set_tag("experiment_set", self.experiment_set)
        mlflow.set_tag("role", self.role)
        self._active = True
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self._active:
            return
        # ``end_run`` accepts a status; on exception we mark the run FAILED
        # rather than leaving it in an unfinished state. MLflow otherwise
        # auto-finalizes to FINISHED on process exit, but FAILED is more
        # honest for an aborted scoring pass.
        status = "FAILED" if exc_type is not None else "FINISHED"
        mlflow.end_run(status=status)
        self._active = False

    # -- Typed log helpers -------------------------------------------------

    def log_pipeline_params(self, params: PipelineParams) -> None:
        """Log every DEC-020 required param from ``params``.

        Args:
            params: The :class:`PipelineParams` for this run.
        """
        if not self._active:
            return
        for key, value in params.to_dict().items():
            mlflow.log_param(key, value)

    def log_retrieval_metrics(self, metrics: RetrievalMetrics) -> None:
        """Log every DEC-020 required metric from ``metrics``.

        Args:
            metrics: The :class:`RetrievalMetrics` for this run.
        """
        if not self._active:
            return
        for key, value in metrics.to_dict().items():
            mlflow.log_metric(key, value)

    def log_metric(self, key: str, value: float) -> None:
        """Log a single additional metric outside the DEC-020 contract.

        Used for run-level rollups like ``n_candidates`` and ``time_seconds``
        that are useful for dashboards but not part of the required set.
        """
        if not self._active:
            return
        mlflow.log_metric(key, float(value))

    def log_artifact(self, local_path: Path | str) -> None:
        """Log a single artifact file (e.g. ``<role>_ranked.json``).

        Args:
            local_path: Path to the file to upload.
        """
        if not self._active:
            return
        path = Path(local_path)
        if not path.exists():
            logger.warning("log_artifact: %s does not exist; skipped.", path)
            return
        mlflow.log_artifact(str(path))

    def set_tag(self, key: str, value: str) -> None:
        """Set a free-form tag in addition to the canonical pair."""
        if not self._active:
            return
        mlflow.set_tag(key, str(value))


# Backwards-compatible contextmanager-style alias: callers that prefer
# ``with start_run(...) as run:`` over constructing MLflowRun directly get
# the same object back.
def start_run(
    experiment_name: str,
    run_name: str,
    experiment_set: str = "default",
    role: str = "all",
    tracking_uri: str = DEFAULT_TRACKING_URI,
) -> MLflowRun:
    """Construct an :class:`MLflowRun` for use as a ``with`` target."""
    return MLflowRun(
        experiment_name=experiment_name,
        run_name=run_name,
        experiment_set=experiment_set,
        role=role,
        tracking_uri=tracking_uri,
    )
