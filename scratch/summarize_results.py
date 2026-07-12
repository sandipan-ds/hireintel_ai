# Summarization script for Optuna studies and stability reports.
#
# This script connects to the Optuna SQLite database to fetch the Pareto front
# trials for each of the 8 roles, extracts their RAG parameters and objective
# scores, and parses the corresponding Prong 6 rank stability JSON reports
# to build a consolidated summary table.

import json
import sqlite3
from pathlib import Path
import optuna

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data/optuna/studies.db"
REPORTS_DIR = ROOT / "reports/diff_rankings"

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
    if not DB_PATH.exists():
        print(f"Error: Database not found at {DB_PATH}")
        return

    print("=== Consolidating Hyperparameter Optimization and Rank Stability Results ===")
    
    # We will build a list of summaries for all roles to generate a Markdown table.
    markdown_lines = []
    markdown_lines.append("# RAG HPO and Rank Stability Consolidated Report")
    markdown_lines.append("")
    markdown_lines.append("This report summarizes the Pareto-optimal RAG parameter configurations and candidate pool rank stability metrics across all 8 roles pool sweeps (100 trials each).")
    markdown_lines.append("")
    markdown_lines.append("## Pareto Front Configurations (Tuned Tradeoffs)")
    markdown_lines.append("")
    markdown_lines.append("| Role | Trial | Chunk Size | Chunk Overlap | Similarity Theta | Top K | Mean NDCG (Goal) | Avg Chunks (Cost) |")
    markdown_lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")

    # Connect to the Optuna storage
    storage_url = f"sqlite:///{DB_PATH}"
    
    for role in ROLES:
        study_name = f"hpo_sweep_{role.lower()}_100"
        try:
            study = optuna.load_study(study_name=study_name, storage=storage_url)
            best_trials = study.best_trials
            
            # Add each Pareto trial to the markdown table
            for t in best_trials:
                trial_num = t.number
                params = t.params
                chunk_size = params.get("chunk_size", "-")
                chunk_overlap = params.get("chunk_overlap", "-")
                threshold = params.get("threshold", "-")
                top_k = params.get("top_k", "-")
                
                # Objectives: NDCG (maximize), Avg Chunks (minimize)
                ndcg_val = t.values[0]
                chunks_val = t.values[1]
                
                markdown_lines.append(
                    f"| **{role}** | #{trial_num} | {chunk_size} | {chunk_overlap} | {threshold:.2f} | {top_k} | {ndcg_val:.4f} | {chunks_val:.2f} |"
                )
        except Exception as exc:
            print(f"Warning: Failed to load study {study_name}: {exc}")
            markdown_lines.append(f"| **{role}** | *Failed to load study* | | | | | | |")

    markdown_lines.append("")
    markdown_lines.append("## Prong 6 Rank Stability Metrics (Robustness Analysis)")
    markdown_lines.append("")
    markdown_lines.append("| Role | Jaccard @10 (Overlap) | Max Shift | Mean Abs Shift | Kendall Tau | Spearman Rho | Primary HP Variance |")
    markdown_lines.append("| --- | ---: | ---: | ---: | ---: | ---: | --- |")

    for role in ROLES:
        stability_file = REPORTS_DIR / f"optuna_study_hpo_sweep_{role.lower()}_100__{role}__rank_stability.json"
        if not stability_file.exists():
            print(f"Warning: Stability report not found for {role}")
            markdown_lines.append(f"| **{role}** | *No report* | | | | | |")
            continue
            
        try:
            data = json.loads(stability_file.read_text(encoding="utf-8"))
            hp_importance = data.get("hp_axis_explained_variance", {})
            
            jaccard = data.get("top_10_jaccard", 0.0)
            max_shift = data.get("max_rank_shift", 0.0)
            mean_abs_shift = data.get("mean_abs_rank_shift", 0.0)
            kendall = data.get("kendall_tau", 0.0)
            spearman = data.get("spearman_rho", 0.0)
            
            # Find the most important HP axis (highest R^2)
            sorted_hps = sorted(hp_importance.items(), key=lambda x: x[1], reverse=True)
            top_hp_desc = "None"
            if sorted_hps:
                top_hp, r2 = sorted_hps[0]
                top_hp_desc = f"`{top_hp}` (R²={r2:.3f})"
                
            markdown_lines.append(
                f"| **{role}** | {jaccard:.4f} | {max_shift:.1f} | {mean_abs_shift:.2f} | {kendall:.4f} | {spearman:.4f} | {top_hp_desc} |"
            )
        except Exception as exc:
            print(f"Warning: Failed to load stability report for {role}: {exc}")
            markdown_lines.append(f"| **{role}** | *Error reading report* | | | | | |")

    # Write the markdown report to artifact folder
    report_path = ROOT / "reports/diff_rankings/consolidated_hpo_stability_report.md"
    report_path.write_text("\n".join(markdown_lines), encoding="utf-8")
    print(f"\nWrote consolidated report to {report_path}")

if __name__ == "__main__":
    main()
