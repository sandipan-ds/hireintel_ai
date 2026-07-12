#!/usr/bin/env python3
"""Runner to execute RAG HPO sweep across all 8 roles with 100 sweeps each."""

import subprocess
import sys
from pathlib import Path

# Ensure project root is in path
ROOT = Path(__file__).resolve().parent.parent

ROLES = [
    "BusinessAnalyst",
    "DataScience",
    "JavaDeveloper",
    "ReactDeveloper",
    "SalesManager",
    "SQLDeveloper",
    "SrPythonDeveloper",
    "WebDesigning",
]

def main():
    print(f"=== Starting HPO sweeps across all {len(ROLES)} roles (100 trials each) ===")
    
    for idx, role in enumerate(ROLES):
        print(f"\n[{idx+1}/{len(ROLES)}] Running 100 trials sweep for role: {role}")
        study_name = f"hpo_sweep_{role.lower()}_100"
        
        cmd = [
            sys.executable,
            "-u",
            str(ROOT / "scripts/run_hpo_sweep.py"),
            "--role", role,
            "--study-name", study_name,
            "--trials", "100"
        ]
        
        try:
            # Run the sweep for this role and stream output in real-time
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            if process.stdout:
                for line in iter(process.stdout.readline, ""):
                    print(line, end="", flush=True)
            process.wait()
            if process.returncode != 0:
                print(f"ERROR: [{role}] sweep failed with exit code {process.returncode}")
            else:
                print(f"[{role}] Completed successfully.")
        except Exception as exc:
            print(f"ERROR: [{role}] sweep encountered exception: {exc}")
            
    print("\n=== All HPO sweeps complete! ===")

if __name__ == "__main__":
    main()
