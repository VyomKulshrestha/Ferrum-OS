#!/usr/bin/env python3
"""Figures added or corrected for the revised Prediction Is Not Permission v1.2.

Writes new files only; figures bound by the frozen v1.0/v1.1 reports are never overwritten.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

from build_cross_domain_world_model_figures import BLUE, GREEN, INK, NAVY, ORANGE, OUTPUT, PALE, RED, TEAL

ROOT = Path(__file__).resolve().parents[1]


def save(fig, name):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT / name, dpi=220, bbox_inches="tight", facecolor="white",
                metadata={"Software": None, "CreationDate": None} if name.endswith(".pdf") else {"Software": None})
    plt.close(fig)


def evidence_ladder() -> None:
    """Same content as the v1.0-v1.1 ladder with boxes wide enough for every label."""
    fig, ax = plt.subplots(figsize=(11.9, 5.6))
    ax.set_xlim(0, 11.5)
    ax.set_ylim(0, 6.2)
    ax.axis("off")
    width = 2.6
    steps = [
        (0.35, 0.55, "Software catalogs", "matched models + paired cases", TEAL),
        (1.95, 1.55, "QEMU shadow", "H=1..5, no authority", BLUE),
        (3.55, 2.55, "Natural use", "3 boots, 24 records", GREEN),
        (5.15, 3.55, "Multi-client", "4 sockets, 128 replies", ORANGE),
        (6.75, 4.55, "Recorded testbed", "284,398 transitions", NAVY),
    ]
    for x, y, title, subtitle, color in steps:
        ax.add_patch(FancyBboxPatch((x, y), width, 0.8, boxstyle="round,pad=0.05",
                                    facecolor=PALE, edgecolor=color, linewidth=1.5))
        ax.text(x + 0.14, y + 0.52, title, ha="left", va="center", fontsize=10.2, weight="bold", color=color)
        ax.text(x + 0.14, y + 0.22, subtitle, ha="left", va="center", fontsize=8.4, color=INK)
    ax.add_patch(FancyBboxPatch((9.65, 4.55), 1.65, 0.8, boxstyle="round,pad=0.05", facecolor="white",
                                edgecolor=RED, linewidth=1.5, linestyle="--"))
    ax.text(10.475, 5.07, "Live Ferrum HIL", ha="center", va="center", fontsize=9.5, color=RED, weight="bold")
    ax.text(10.475, 4.77, "not established", ha="center", va="center", fontsize=8.4, color=RED)
    ax.add_patch(FancyArrowPatch((9.37, 4.95), (9.63, 4.95), arrowstyle="-|>", mutation_scale=12, color=RED, linewidth=1.2))
    ax.text(0.35, 5.95, "Evidence strength rises; claim scope remains explicit", fontsize=15, color=NAVY, weight="bold")
    ax.text(0.35, 5.60, "No rung is relabelled as hardware deployment, independent assessment, or formal safety.",
            fontsize=9.2, color="#526276")
    save(fig, "evidence_ladder_v1_2.png")


def incident_v3_figure() -> None:
    """Population A/B H5 error and warning recall versus the v2-selected models (from the retained result)."""
    result = json.loads((ROOT / "docs/research/incident_dynamics_result_v3.json").read_text(encoding="utf-8"))
    fig, axes = plt.subplots(1, 2, figsize=(11.2, 4.2))
    labels, old, new = [], [], []
    for domain, short in (("ferrumos", "OS"), ("physical", "Physical")):
        for population in ("A", "B"):
            methods = result["domains"][domain]["populations"][population]["methods"]
            labels.append(f"{short} {population}")
            old.append(methods["v2-selected"]["prediction"]["h5"]["episode_macro_mae"])
            new.append(methods["selected"]["prediction"]["h5"]["episode_macro_mae"])
    x = range(len(labels))
    relative = [n / o for n, o in zip(new, old)]
    axes[0].bar([i - 0.2 for i in x], [1.0] * len(x), 0.4, color="#B8C4CE", label="v2-selected (=1.0)")
    axes[0].bar([i + 0.2 for i in x], relative, 0.4, color=TEAL, label="v3-selected")
    for i, value in enumerate(relative):
        axes[0].text(i + 0.2, value + 0.02, f"{value:.2f}", ha="center", fontsize=8.5, color=INK)
    axes[0].set_xticks(list(x), labels)
    axes[0].set_ylabel("H=5 error relative to v2-selected")
    axes[0].set_title("Five-step prediction error (lower is better)", fontsize=10.5, color=NAVY, weight="bold")
    axes[0].legend(frameon=False, fontsize=8.5)
    old_r, new_r = [], []
    for domain in ("ferrumos", "physical"):
        for population in ("A", "B"):
            methods = result["domains"][domain]["populations"][population]["methods"]
            old_r.append(100 * methods["v2-selected"]["warning"]["recall"])
            new_r.append(100 * methods["selected"]["warning"]["recall"])
    axes[1].bar([i - 0.2 for i in x], old_r, 0.4, color="#B8C4CE", label="v2-selected")
    axes[1].bar([i + 0.2 for i in x], new_r, 0.4, color=ORANGE, label="v3-selected")
    axes[1].set_xticks(list(x), labels)
    axes[1].set_ylim(0, 105)
    axes[1].set_ylabel("Warning recall (%)")
    axes[1].set_title("Delayed-constraint warning recall", fontsize=10.5, color=NAVY, weight="bold")
    axes[1].legend(frameon=False, fontsize=8.5, loc="lower right")
    for ax in axes:
        ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    save(fig, "incident_dynamics_v3_results.png")


if __name__ == "__main__":
    evidence_ladder()
    if (ROOT / "docs/research/incident_dynamics_result_v3.json").exists():
        incident_v3_figure()
