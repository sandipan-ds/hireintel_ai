"""Unit tests for the MLflow experiment-tracking wiring (DEC-020, M0.5c).

These tests are hermetic: they spin up an in-memory SQLite MLflow tracking
store under a per-test tempdir so no network connection to a running MLflow
server is required. Every test verifies the DEC-020 contract directly by
re-reading the logged params / metrics / tags from the tracking store via
the official :mod:`mlflow` client API.

Covered behaviors:

* ``start_run`` produces a run that emits the canonical ``experiment_set``
  and ``role`` tags (DEC-020).
* ``log_pipeline_params`` writes every required contract param.
* ``log_retrieval_metrics`` writes every required contract metric.
* ``log_artifact`` records the artifact and the file lands under the
  experiment's artifact store.
* ``log_metric`` writes ad-hoc rollup metrics (e.g. ``n_candidates``).
* A run interrupted by an exception is finalized with ``status='FAILED'``.
* Graceful degradation: when :mod:`mlflow` is monkeypatched away, every
  helper becomes a no-op and no exception is raised.
* The convenience launcher ``scripts/start_mlflow_server.py`` produces the
  exact DEC-020 command for the default args.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

# Skip the entire module if mlflow is not installed (not required for DocumentAware
# chunking pipeline; MLflow HPO tracking is out of scope per DEC-035).
pytest.importorskip("mlflow", reason="mlflow not installed — skipping tracking tests")

# Import the wiring module fresh each time so ``_available`` reflects the
# current ``mlflow`` importability state (tests monkeypatch it).
import src.services.mlflow_wiring as wiring
from src.services.mlflow_wiring import (
    DEFAULT_ARTIFACT_ROOT,
    DEFAULT_BACKEND_STORE,
    DEFAULT_TRACKING_URI,
    MLflowRun,
    PipelineParams,
    RetrievalMetrics,
    is_available,
    start_run,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tracking_store(tmp_path: Path) -> Any:
    """Return a tracking URI pointing at a fresh in-memory SQLite store.

    The URI uses a file in ``tmp_path`` so each test gets an isolated store
    while exercising the real :mod:`mlflow` SQLite backend path.
    """
    db = tmp_path / "mlflow.db"
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)
    uri = f"sqlite:///{db.as_posix()}"
    yield uri


@pytest.fixture
def run_factory(tracking_store: str):
    """Construct an :class:`MLflowRun` bound to the in-memory tracking store."""
    def _make(
        experiment_set: str = "test_set",
        role: str = "DataScience",
        run_name: str = "test_run",
    ) -> MLflowRun:
        return start_run(
            experiment_name=experiment_set,
            run_name=run_name,
            experiment_set=experiment_set,
            role=role,
            tracking_uri=tracking_store,
        )
    return _make


def _read_run(tracking_store: str, run_name: str) -> dict[str, Any]:
    """Read the run back via the official MLflow client for assertions."""
    import mlflow
    from mlflow.tracking import MlflowClient

    mlflow.set_tracking_uri(tracking_store)
    client = MlflowClient(tracking_uri=tracking_store)
    # Search experiments + runs by name; there is at most one run per test.
    runs = []
    for exp in client.search_experiments():
        runs.extend(client.search_runs(experiment_ids=[exp.experiment_id]))
    matches = [r for r in runs if r.info.run_name == run_name]
    assert matches, f"Run '{run_name}' not found in tracking store"
    return matches[0]


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def test_is_available_returns_bool():
    """``is_available`` must return a real bool (not truthy non-bool)."""
    result = is_available()
    assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Tag contract (DEC-020): experiment_set + role
# ---------------------------------------------------------------------------


def test_canonical_tags_logged(run_factory):
    """The two DEC-020 required tags must be written on every run."""
    with run_factory(experiment_set="chunking_v1", role="BusinessAnalyst",
                     run_name="tags_run") as run:
        pass
    run_info = _read_run(run.tracking_uri, "tags_run")
    assert run_info.data.tags["experiment_set"] == "chunking_v1"
    assert run_info.data.tags["role"] == "BusinessAnalyst"


# ---------------------------------------------------------------------------
# Param contract (DEC-020): the 9 required keys
# ---------------------------------------------------------------------------


REQUIRED_PARAMS = [
    "chunk_size", "chunk_overlap", "embedding_model", "vector_store",
    "similarity", "retrieval_mode", "threshold", "top_k", "llm",
]


def test_log_pipeline_params_writes_contract_keys(run_factory):
    """Every DEC-020 required param key must appear in the run's data."""
    params = PipelineParams(
        chunk_size=400, chunk_overlap=240, embedding_model="miniLM",
        vector_store="qdrant", similarity="cosine", retrieval_mode="topk",
        threshold=0.42, top_k=12, llm="on",
    )
    with run_factory(run_name="params_run") as run:
        run.log_pipeline_params(params)
    run_info = _read_run(run.tracking_uri, "params_run")
    logged = run_info.data.params
    for key in REQUIRED_PARAMS:
        assert key in logged, f"missing required param '{key}'"
    assert logged["chunk_size"] == "400"
    assert logged["threshold"] == "0.42"
    assert logged["llm"] == "on"


def test_pipeline_params_defaults_match_shipped_config():
    """Default :class:`PipelineParams` must reflect the shipped RecursiveChunker
    + ThresholdRetriever config so forgotten fields log real values, not ``None``.
    The values reflect the canonical ``PipelineParams`` defaults used by the
    wiring module (kept conservative at the historical DEC-018 defaults of
    chunk_size=500, chunk_overlap=100, theta=0.30); individual build-time
    configs in ``recursive_chunker.py`` are tracked separately.
    """
    p = PipelineParams()
    assert p.chunk_size == 500
    assert p.chunk_overlap == 100
    assert "MiniLM-L6-v2" in p.embedding_model
    assert p.threshold == 0.30


# ---------------------------------------------------------------------------
# Metric contract (DEC-020): the 11 required keys
# ---------------------------------------------------------------------------


REQUIRED_METRICS = [
    "recall_at_theta", "precision_at_theta", "mrr", "ndcg",
    "avg_chunks_returned", "p95_chunks_returned", "cap_hit_rate",
    "faithfulness", "groundedness", "answer_relevancy",
    "hallucination_rate",
]


def test_log_retrieval_metrics_writes_contract_keys(run_factory):
    """Every DEC-020 required metric key must appear in the run's metrics."""
    metrics = RetrievalMetrics(
        recall_at_theta=0.85, precision_at_theta=0.70, mrr=0.92,
        ndcg=0.88, avg_chunks_returned=8.5, p95_chunks_returned=18.0,
        cap_hit_rate=0.12, faithfulness=0.91, groundedness=0.87,
        answer_relevancy=0.90, hallucination_rate=0.05,
    )
    with run_factory(run_name="metrics_run") as run:
        run.log_retrieval_metrics(metrics)
    run_info = _read_run(run.tracking_uri, "metrics_run")
    logged = run_info.data.metrics
    for key in REQUIRED_METRICS:
        assert key in logged, f"missing required metric '{key}'"
    assert logged["faithfulness"] == pytest.approx(0.91)
    assert logged["hallucination_rate"] == pytest.approx(0.05)


def test_log_metric_accepts_arbitrary_keys(run_factory):
    """Ad-hoc rollup metrics (e.g. ``n_candidates``) must be loggable."""
    with run_factory(run_name="adhoc_run") as run:
        run.log_metric("n_candidates", 42.0)
        run.log_metric("time_seconds", 17.34)
    run_info = _read_run(run.tracking_uri, "adhoc_run")
    assert run_info.data.metrics["n_candidates"] == pytest.approx(42.0)
    assert run_info.data.metrics["time_seconds"] == pytest.approx(17.34)


# ---------------------------------------------------------------------------
# Artifact contract (DEC-020)
# ---------------------------------------------------------------------------


def test_log_artifact_records_file(run_factory, tmp_path):
    """``log_artifact`` must upload the file to the artifact store."""
    artifact = tmp_path / "ranked.json"
    artifact.write_text('{"role": "DataScience"}', encoding="utf-8")
    with run_factory(run_name="artifact_run") as run:
        run.log_artifact(artifact)
    import mlflow
    from mlflow.tracking import MlflowClient

    client = MlflowClient(tracking_uri=run.tracking_uri)
    mlflow.set_tracking_uri(run.tracking_uri)
    exp_id = client.search_experiments()[0].experiment_id
    run_id = client.search_runs([exp_id])[0].info.run_id
    artifacts = client.list_artifacts(run_id)
    names = [a.path for a in artifacts]
    assert "ranked.json" in names


def test_log_artifact_warns_on_missing_file(run_factory, tmp_path, caplog):
    """A non-existent artifact path must log a warning, not raise."""
    missing = tmp_path / "does_not_exist.json"
    with run_factory(run_name="missing_artifact_run") as run:
        run.log_artifact(missing)
    # No assertion on absence in the store needed — the contract is "no raise"
    # plus a warning. We confirm via the log capture below.
    assert any(
        "does not exist" in rec.getMessage()
        for rec in caplog.records
    )


# ---------------------------------------------------------------------------
# Failure finalization
# ---------------------------------------------------------------------------


def test_failed_run_marked_failed_on_exception(run_factory):
    """A run whose ``with`` block raises must end with ``status='FAILED'``."""
    probe = run_factory(run_name="failed_probe")
    tracking_uri = probe.tracking_uri
    with pytest.raises(RuntimeError, match="boom"):
        with run_factory(run_name="failed_run"):
            raise RuntimeError("boom")
    run_info = _read_run(tracking_uri, "failed_run")
    assert run_info.info.status == "FAILED"


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


def test_no_op_when_mlflow_unavailable(monkeypatch, tmp_path):
    """When :mod:`mlflow` is not installed, helpers must be no-ops.

    We simulate the missing dependency by flipping ``wiring._available`` to
    ``False`` so the same code path used when the import actually fails is
    exercised (no real dependency is removed).
    """
    monkeypatch.setattr(wiring, "_available", False)
    run = start_run(experiment_name="degrading", run_name="noop_run",
                    experiment_set="degrading", role="DataScience",
                    tracking_uri=f"sqlite:///{(tmp_path / 'no.db').as_posix()}")
    with run:
        # Every helper must be a no-op (return None), not raise.
        run.log_pipeline_params(PipelineParams())
        run.log_retrieval_metrics(RetrievalMetrics())
        run.log_metric("n_candidates", 10.0)
        run.set_tag("extra", "value")
        run.log_artifact(tmp_path / "missing.json")
    # Reaching here without exception is the test's pass condition.
    assert not run._active


# ---------------------------------------------------------------------------
# Constants match DEC-020 contract
# ---------------------------------------------------------------------------


def test_default_tracking_constants_match_dec020():
    """The DEC-020 spec values must be reflected in module constants."""
    assert DEFAULT_TRACKING_URI == "http://127.0.0.1:5000"
    assert DEFAULT_BACKEND_STORE == "data/mlflow/mlflow.db"
    assert DEFAULT_ARTIFACT_ROOT == "data/mlflow/artifacts/"


# ---------------------------------------------------------------------------
# Launcher command (DEC-020 launch line)
# ---------------------------------------------------------------------------


def test_start_mlflow_server_command_shape():
    """``scripts/start_mlflow_server.py`` must produce the exact DEC-020
    launch line for the default args.
    """
    from scripts.start_mlflow_server import build_command

    cmd = build_command(
        host="127.0.0.1", port=5000,
        backend_store="data/mlflow/mlflow.db",
        artifact_root="data/mlflow/artifacts/",
    )
    expected = [
        "mlflow", "server",
        "--host", "127.0.0.1",
        "--port", "5000",
        "--backend-store-uri", "sqlite:///data/mlflow/mlflow.db",
        "--default-artifact-root", "data/mlflow/artifacts/",
    ]
    assert cmd == expected
