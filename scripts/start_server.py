"""Startup script for HireIntel AI Weight Configuration API."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    """Start the HireIntel AI Weight Configuration API."""
    print("=" * 60)
    print("HireIntel AI - Weight Configuration API")
    print("=" * 60)
    print()

    # Initialize database
    print("[1/3] Initializing database...")
    subprocess.run([sys.executable, "scripts/init_database.py"], check=True)

    # Start server
    print()
    print("[2/3] Starting server...")
    print()
    print("Server will be available at:")
    print("  - Home: http://localhost:8000/")
    print("  - Configure: http://localhost:8000/configure")
    print("  - API Docs: http://localhost:8000/docs")
    print("  - Health: http://localhost:8000/health")
    print()
    print("Press Ctrl+C to stop the server")
    print("=" * 60)
    print()

    # Start uvicorn
    subprocess.run([
        sys.executable, "-m", "uvicorn",
        "src.api.app:app",
        "--reload",
        "--host", "0.0.0.0",
        "--port", "8000",
    ], cwd=str(ROOT))


if __name__ == "__main__":
    main()
