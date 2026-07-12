#!/usr/bin/env python3
"""Plotting script to visualize rank stability sensitivities across RAG hyperparameters.

Generates a beautiful 3x3 PNG dashboard showing Jaccard Overlap, Mean Absolute
Rank Shift, and Maximum Rank Shift as functions of similarity threshold (theta),
chunk size, and top-k retrieval cap.
"""

import json
from pathlib import Path
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
GRID_DIR = ROOT / "reports/grid_sweep/grid_sweep_20260712"
PLOTS_DIR = ROOT / "reports/plots_and_graphs"
OUTPUT_IMAGE = PLOTS_DIR / "param_sensitivity_curves.png"


def main():
    # Ensure plots directory exists
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    # Setup aesthetic style
    sns.set_theme(style="whitegrid")
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.size": 10,
        "axes.labelsize": 11,
        "axes.titlesize": 13,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "figure.titlesize": 16
    })

    # Load configuration manifest
    configs = json.loads((GRID_DIR / "config_manifest.json").read_text())
    config_map = {c["config_id"]: c for c in configs}

    # Find roles and their summaries
    summary_files = sorted(list(GRID_DIR.glob("stability_summary_*.json")))
    
    # Create the 3x3 figure grid
    fig, axes = plt.subplots(3, 3, figsize=(18, 14), sharex=False, sharey=False)
    
    # Palette with 8 distinct, professional colors
    colors = sns.color_palette("husl", len(summary_files))

    for idx, f in enumerate(summary_files):
        role_data = json.loads(f.read_text())
        role_name = role_data["role"]
        
        # Accumulate metrics grouped by theta, chunk_size, and top_k
        theta_groups = {}
        chunk_groups = {}
        top_k_groups = {}
        
        for c in role_data["configs"]:
            cfg_id = c["config_id"]
            params = config_map[cfg_id]
            theta = params["theta"]
            chunk_size = params["chunk_size"]
            top_k = params["top_k"]
            
            j10 = c["top_10_jaccard"]
            ars = c["mean_abs_rank_shift"]
            mrs = c["max_rank_shift"]
            
            # Group by Theta
            if theta not in theta_groups:
                theta_groups[theta] = {"j10": [], "ars": [], "mrs": []}
            theta_groups[theta]["j10"].append(j10)
            theta_groups[theta]["ars"].append(ars)
            theta_groups[theta]["mrs"].append(mrs)
            
            # Group by Chunk Size
            if chunk_size not in chunk_groups:
                chunk_groups[chunk_size] = {"j10": [], "ars": [], "mrs": []}
            chunk_groups[chunk_size]["j10"].append(j10)
            chunk_groups[chunk_size]["ars"].append(ars)
            chunk_groups[chunk_size]["mrs"].append(mrs)
            
            # Group by Top-K
            if top_k not in top_k_groups:
                top_k_groups[top_k] = {"j10": [], "ars": [], "mrs": []}
            top_k_groups[top_k]["j10"].append(j10)
            top_k_groups[top_k]["ars"].append(ars)
            top_k_groups[top_k]["mrs"].append(mrs)
            
        # 1. Plot Row 1: Sensitivity vs Similarity Threshold (Theta)
        sorted_thetas = sorted(theta_groups.keys())
        mean_j10_th = [np.mean(theta_groups[th]["j10"]) for th in sorted_thetas]
        mean_ars_th = [np.mean(theta_groups[th]["ars"]) for th in sorted_thetas]
        mean_mrs_th = [np.mean(theta_groups[th]["mrs"]) for th in sorted_thetas]
        
        axes[0, 0].plot(sorted_thetas, mean_j10_th, marker="o", color=colors[idx], label=role_name, linewidth=1.8, markersize=4.5)
        axes[0, 1].plot(sorted_thetas, mean_ars_th, marker="s", color=colors[idx], label=role_name, linewidth=1.8, markersize=4.5)
        axes[0, 2].plot(sorted_thetas, mean_mrs_th, marker="D", color=colors[idx], label=role_name, linewidth=1.8, markersize=4.5)
        
        # 2. Plot Row 2: Sensitivity vs Chunk Size
        sorted_chunks = sorted(chunk_groups.keys())
        mean_j10_cs = [np.mean(chunk_groups[cs]["j10"]) for cs in sorted_chunks]
        mean_ars_cs = [np.mean(chunk_groups[cs]["ars"]) for cs in sorted_chunks]
        mean_mrs_cs = [np.mean(chunk_groups[cs]["mrs"]) for cs in sorted_chunks]
        
        axes[1, 0].plot(sorted_chunks, mean_j10_cs, marker="o", color=colors[idx], label=role_name, linewidth=1.8, markersize=4.5)
        axes[1, 1].plot(sorted_chunks, mean_ars_cs, marker="s", color=colors[idx], label=role_name, linewidth=1.8, markersize=4.5)
        axes[1, 2].plot(sorted_chunks, mean_mrs_cs, marker="D", color=colors[idx], label=role_name, linewidth=1.8, markersize=4.5)
        
        # 3. Plot Row 3: Sensitivity vs Top-K
        sorted_top_ks = sorted(top_k_groups.keys())
        mean_j10_tk = [np.mean(top_k_groups[tk]["j10"]) for tk in sorted_top_ks]
        mean_ars_tk = [np.mean(top_k_groups[tk]["ars"]) for tk in sorted_top_ks]
        mean_mrs_tk = [np.mean(top_k_groups[tk]["mrs"]) for tk in sorted_top_ks]
        
        axes[2, 0].plot(sorted_top_ks, mean_j10_tk, marker="o", color=colors[idx], label=role_name, linewidth=1.8, markersize=4.5)
        axes[2, 1].plot(sorted_top_ks, mean_ars_tk, marker="s", color=colors[idx], label=role_name, linewidth=1.8, markersize=4.5)
        axes[2, 2].plot(sorted_top_ks, mean_mrs_tk, marker="D", color=colors[idx], label=role_name, linewidth=1.8, markersize=4.5)

    # Decorate Row 1: Theta
    axes[0, 0].set_title("Shortlist Similarity vs Theta")
    axes[0, 0].set_xlabel("Similarity Threshold (Theta)")
    axes[0, 0].set_ylabel("Average Jaccard @10")
    axes[0, 0].set_ylim(-0.05, 1.05)
    axes[0, 0].axhline(0.60, color="gray", linestyle="--", alpha=0.7, label="Pass Target (>=0.60)")
    
    axes[0, 1].set_title("Mean Absolute Rank Shift vs Theta")
    axes[0, 1].set_xlabel("Similarity Threshold (Theta)")
    axes[0, 1].set_ylabel("Average Shift (Positions)")
    axes[0, 1].axhline(10.0, color="gray", linestyle="--", alpha=0.7, label="Pass Target (<=10.0)")
    
    axes[0, 2].set_title("Worst-Case Max Rank Shift vs Theta")
    axes[0, 2].set_xlabel("Similarity Threshold (Theta)")
    axes[0, 2].set_ylabel("Max Shift (Positions)")
    axes[0, 2].axhline(50.0, color="gray", linestyle="--", alpha=0.7, label="Pass Target (<=50.0)")

    # Decorate Row 2: Chunk Size
    axes[1, 0].set_title("Shortlist Similarity vs Chunk Size")
    axes[1, 0].set_xlabel("Chunk Size (Characters)")
    axes[1, 0].set_ylabel("Average Jaccard @10")
    axes[1, 0].set_ylim(-0.05, 1.05)
    axes[1, 0].axhline(0.60, color="gray", linestyle="--", alpha=0.7)
    
    axes[1, 1].set_title("Mean Absolute Rank Shift vs Chunk Size")
    axes[1, 1].set_xlabel("Chunk Size (Characters)")
    axes[1, 1].set_ylabel("Average Shift (Positions)")
    axes[1, 1].axhline(10.0, color="gray", linestyle="--", alpha=0.7)
    
    axes[1, 2].set_title("Worst-Case Max Rank Shift vs Chunk Size")
    axes[1, 2].set_xlabel("Chunk Size (Characters)")
    axes[1, 2].set_ylabel("Max Shift (Positions)")
    axes[1, 2].axhline(50.0, color="gray", linestyle="--", alpha=0.7)

    # Decorate Row 3: Top-K
    axes[2, 0].set_title("Shortlist Similarity vs Top-K")
    axes[2, 0].set_xlabel("Top-K (Retrieval Cap)")
    axes[2, 0].set_ylabel("Average Jaccard @10")
    axes[2, 0].set_ylim(-0.05, 1.05)
    axes[2, 0].axhline(0.60, color="gray", linestyle="--", alpha=0.7)
    
    axes[2, 1].set_title("Mean Absolute Rank Shift vs Top-K")
    axes[2, 1].set_xlabel("Top-K (Retrieval Cap)")
    axes[2, 1].set_ylabel("Average Shift (Positions)")
    axes[2, 1].axhline(10.0, color="gray", linestyle="--", alpha=0.7)
    
    axes[2, 2].set_title("Worst-Case Max Rank Shift vs Top-K")
    axes[2, 2].set_xlabel("Top-K (Retrieval Cap)")
    axes[2, 2].set_ylabel("Max Shift (Positions)")
    axes[2, 2].axhline(50.0, color="gray", linestyle="--", alpha=0.7)

    # Put legend outside the panels at the bottom center
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, -0.03), ncol=5, frameon=True)

    fig.suptitle("RAG Parameter Sensitivity & Stability Dashboard (grid_sweep_20260712)", y=0.99)
    plt.tight_layout(rect=[0, 0.02, 1, 0.96])
    
    # Save the plot
    plt.savefig(OUTPUT_IMAGE, dpi=180, bbox_inches="tight")
    plt.close()
    print(f"SUCCESS: Comprehensive 3x3 Plot generated and saved to {OUTPUT_IMAGE.resolve()}")


if __name__ == "__main__":
    main()
