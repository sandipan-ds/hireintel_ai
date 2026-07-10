"""Launch the local MLflow tracking server (DEC-020, Track M0.5c).

This is a thin convenience wrapper around the canonical MLflow launch command
documented in ``docs/EVALUATION.md`` §"MLflow contract". It exists so the
operator does not have to memorize the backend-store / artifact-root paths and
so the configuration stays in one place (alongside
:mod:`src.services.mlflow_wiring`).

Usage::

    python scripts/start_mlflow_server.py
    python scripts/start_mlflow_server.py --port 5001 --host 0.0.0.0
    python scripts/start_mlflow_server.py --dry-run   # print the command only

The script blocks until the server is killed (Ctrl+C), exactly like the
bare ``mlflow server`` invocation.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.services.mlflow_wiring import (  # noqa: E402
    DEFAULT_ARTIFACT_ROOT,
    DEFAULT_BACKEND_STORE,
    DEFAULT_TRACKING_URI,
)


def build_command(
    host: str,
    port: int,
    backend_store: str,
    artifact_root: str,
) -> list[str]:
    """Assemble the ``mlflow server`` argument vector.

    Args:
        host: Bind address.
        port: TCP port.
        backend_store: SQLite backend store URI (relative to CWD).
        artifact_root: Filesystem artifact root (relative to CWD).

    Returns:
        List of CLI tokens suitable for :func:`subprocess.run`.
    """
    return [
        "mlflow", "server",
        "--host", host,
        "--port", str(port),
        "--backend-store-uri", f"sqlite:///{backend_store}",
        "--default-artifact-root", artifact_root,
    ]


def main(argv: list[str] | None = None) -> int:
    """Parse CLI flags, prepare the SQLite/artifact dirs, then exec mlflow.

    Args:
        argv: Optional argv for testing; defaults to ``sys.argv[1:]``.

    Returns:
        Exit code propagated from the ``mlflow server`` process.
    """
    parser = argparse.ArgumentParser(
        description="Launch the local MLflow tracking server (DEC-020).",
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Bind address (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port", type=int, default=5000,
        help="TCP port (default: 5000).",
    )
    parser.add_argument(
        "--backend-store", default=DEFAULT_BACKEND_STORE,
        help=f"SQLite backend store path (default: {DEFAULT_BACKEND_STORE}).",
    )
    parser.add_argument(
        "--artifact-root", default=DEFAULT_ARTIFACT_ROOT,
        help=f"Artifact root directory (default: {DEFAULT_ARTIFACT_ROOT}).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the command and exit without launching the server.",
    )
    args = parser.parse_args(argv)

    # Pre-create the SQLite directory + artifact root so the first run does
    # not fail with ENOENT. ``mlflow server`` is tolerant of missing parents
    # for the artifact root but the SQLite backend requires the directory
    # to exist.
    Path(args.backend_store).parent.mkdir(parents=True, exist_ok=True)
    Path(args.artifact_root).mkdir(parents=True, exist_ok=True)

    cmd = build_command(args.host, args.port, args.backend_store, args.artifact_root)
    print("Launching MLflow server:")
    print("  " + " ".join(cmd))
    print(f"  Tracking URI: {DEFAULT_TRACKING_URI}")
    if args.dry_run:
        return 0
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT))
        return proc.returncode
    except KeyboardInterrupt:
        print("\nInterrupted; MLflow server stopping.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
