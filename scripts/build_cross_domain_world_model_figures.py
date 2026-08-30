#!/usr/bin/env python3
"""Build deterministic figures for the cross-domain world-model paper."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/research/figures/cross_domain_world_model"
NAVY = "#16324F"
TEAL = "#16777A"
ORANGE = "#D97941"
BLUE = "#4C78A8"
GREEN = "#3D8B6D"
RED = "#B84A4A"
PALE = "#EDF3F5"
GRID = "#C5D2DA"
INK = "#1B2733"


def save(fig: plt.Figure, name: str) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT / name, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def authority_figure() -> None:
    fig, ax = plt.subplots(figsize=(11.2, 4.9))
    ax.set_xlim(0, 11.2)
    ax.set_ylim(0, 4.9)
    ax.axis("off")

    boxes = [
        (0.25, 1.65, 1.55, 1.4, "Agent or\ncontroller", BLUE),
        (2.15, 1.65, 1.65, 1.4, "Canonical action\nand state", NAVY),
        (4.25, 2.65, 1.75, 1.25, "Learned world\nmodel", TEAL),
        (4.25, 0.85, 1.75, 1.25, "Deterministic\npredicates", ORANGE),
        (6.55, 1.65, 1.65, 1.4, "Monotone union\nblock / caution", NAVY),
        (8.55, 1.65, 1.55, 1.4, "Capabilities and\nconfirmation", GREEN),
        (10.35, 1.65, 0.62, 1.4, "Effect", RED),
    ]
    for x, y, w, h, label, color in boxes:
        ax.add_patch(FancyBboxPatch(
            (x, y), w, h, boxstyle="round,pad=0.05,rounding_size=0.08",
            linewidth=1.4, edgecolor=color, facecolor="white",
        ))
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center",
                fontsize=10.2 if label != "Effect" else 9, color=INK, weight="bold")

    arrows = [
        ((1.8, 2.35), (2.15, 2.35)),
        ((3.8, 2.35), (4.25, 3.28)),
        ((3.8, 2.35), (4.25, 1.48)),
        ((6.0, 3.28), (6.55, 2.55)),
        ((6.0, 1.48), (6.55, 2.15)),
        ((8.2, 2.35), (8.55, 2.35)),
        ((10.1, 2.35), (10.35, 2.35)),
    ]
    for start, end in arrows:
        ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=13,
                                     color="#627384", linewidth=1.35))
    ax.text(5.12, 4.18, "may add caution; never grants permission", ha="center",
            fontsize=9.2, color=TEAL, weight="bold")
    ax.text(5.12, 0.48, "exact policy remains independently active", ha="center",
            fontsize=9.2, color=ORANGE, weight="bold")
    ax.text(9.33, 1.28, "permit still requires authority", ha="center",
            fontsize=8.9, color=GREEN, weight="bold")
    ax.set_title("Prediction and permission are separate runtime objects", loc="left",
                 fontsize=15, color=NAVY, weight="bold", pad=6)
    save(fig, "authority_factorization.png")


def rollout_figure() -> None:
    horizons = ["H=1", "H=3", "H=5"]
    ferrum = {
        "Direct MLP": [0.004751, 0.008431, 0.007256],
        "Action-conditioned JEPA": [0.009888, 0.012356, 0.005494],
        "GRU dynamics": [0.004609, 0.007917, 0.006514],
    }
    physical = {
        "Direct MLP": [0.007188, 0.016836, 0.026362],
        "Action-conditioned JEPA": [0.002476, 0.006680, 0.010465],
        "GRU dynamics": [0.010659, 0.026231, 0.039542],
    }
    colors = [BLUE, TEAL, ORANGE]
    fig, axes = plt.subplots(1, 2, figsize=(11.2, 4.6), sharey=False)
    width = 0.24
    x = np.arange(len(horizons))
    for ax, title, data in zip(axes, ["FerrumOS", "Physical runtime"], [ferrum, physical]):
        for index, (method, values) in enumerate(data.items()):
            ax.bar(x + (index - 1) * width, values, width, label=method,
                   color=colors[index], edgecolor="white", linewidth=0.7)
        ax.set_xticks(x, horizons)
        ax.set_title(title, color=NAVY, weight="bold")
        ax.set_ylabel("Normalized rollout error (lower is better)")
        ax.grid(axis="y", color=GRID, linewidth=0.6, alpha=0.75)
        ax.set_axisbelow(True)
        ax.spines[["top", "right"]].set_visible(False)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=3, frameon=False,
               bbox_to_anchor=(0.5, 1.02), fontsize=9)
    fig.suptitle("Architecture leadership is domain- and horizon-dependent",
                 x=0.06, y=1.12, ha="left", fontsize=15, color=NAVY, weight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    save(fig, "matched_rollout_results.png")


def evidence_ladder_figure() -> None:
    fig, ax = plt.subplots(figsize=(11.2, 5.2))
    ax.set_xlim(0, 10.5)
    ax.set_ylim(0, 5.7)
    ax.axis("off")
    steps = [
        (0.35, 0.55, 2.0, 0.8, "Software catalogs", "matched models + paired cases", TEAL),
        (1.85, 1.55, 2.0, 0.8, "QEMU shadow", "H=1..5, no authority", BLUE),
        (3.35, 2.55, 2.0, 0.8, "Natural use", "3 boots, 24 records", GREEN),
        (4.85, 3.55, 2.0, 0.8, "Multi-client", "4 sockets, 128 replies", ORANGE),
        (6.35, 4.55, 2.0, 0.8, "Recorded testbed", "284,398 transitions", NAVY),
    ]
    for x, y, w, h, title, subtitle, color in steps:
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.05",
                                    facecolor=PALE, edgecolor=color, linewidth=1.5))
        ax.text(x + 0.12, y + 0.52, title, ha="left", va="center",
                fontsize=10.2, weight="bold", color=color)
        ax.text(x + 0.12, y + 0.22, subtitle, ha="left", va="center",
                fontsize=8.4, color=INK)
    ax.add_patch(FancyBboxPatch((8.55, 4.55), 1.55, 0.8, boxstyle="round,pad=0.05",
                                facecolor="white", edgecolor=RED, linewidth=1.5,
                                linestyle="--"))
    ax.text(9.325, 5.07, "Live Ferrum HIL", ha="center", va="center",
            fontsize=9.5, color=RED, weight="bold")
    ax.text(9.325, 4.77, "not established", ha="center", va="center",
            fontsize=8.4, color=RED)
    ax.add_patch(FancyArrowPatch((8.35, 4.95), (8.55, 4.95), arrowstyle="-|>",
                                 mutation_scale=12, color=RED, linewidth=1.2))
    ax.text(0.35, 5.42, "Evidence strength rises; claim scope remains explicit",
            fontsize=15, color=NAVY, weight="bold")
    ax.text(0.35, 5.08,
            "No rung is relabelled as hardware deployment, independent assessment, or formal safety.",
            fontsize=9.2, color="#526276")
    save(fig, "evidence_ladder.png")


def operational_figure() -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11.2, 3.8))
    domains = ["FerrumOS", "Physical"]
    values = [100.0, 93.36]
    colors = [BLUE, TEAL]
    axes[0].bar(domains, values, color=colors, width=0.56)
    axes[0].set_ylim(0, 105)
    axes[0].set_ylabel("Counterfactual direction accuracy (%)")
    axes[0].set_title("Models respond to interventions", color=NAVY, weight="bold")
    for idx, value in enumerate(values):
        axes[0].text(idx, value + 2, f"{value:.2f}%", ha="center", fontsize=9, weight="bold")
    axes[0].grid(axis="y", color=GRID, linewidth=0.6, alpha=0.7)
    axes[0].set_axisbelow(True)

    labels = ["Rules only", "Learned only", "Rules + learned"]
    x = np.arange(3)
    axes[1].bar(x, [0, 0, 0], color=[ORANGE, TEAL, NAVY], width=0.58)
    axes[1].set_ylim(0, 1.0)
    axes[1].set_xticks(x, labels, rotation=12)
    axes[1].set_ylabel("Intervention rate at frozen 0-FP threshold")
    axes[1].set_title("But add zero operational caution", color=NAVY, weight="bold")
    for idx in x:
        axes[1].text(idx, 0.06, "0 / 512", ha="center", fontsize=9, weight="bold")
    axes[1].grid(axis="y", color=GRID, linewidth=0.6, alpha=0.7)
    axes[1].set_axisbelow(True)
    for ax in axes:
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Predictive sensitivity does not imply deployable operating value",
                 x=0.06, y=1.05, ha="left", fontsize=15, color=NAVY, weight="bold")
    fig.tight_layout()
    save(fig, "causal_vs_operational.png")


def main() -> None:
    authority_figure()
    rollout_figure()
    evidence_ladder_figure()
    operational_figure()
    print(f"wrote figures to {OUTPUT}")


if __name__ == "__main__":
    main()
