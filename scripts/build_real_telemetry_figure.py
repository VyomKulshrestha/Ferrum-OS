#!/usr/bin/env python3
"""Figure for report v1.3: recorded-attack recall per detector on three HAI releases (retained results)."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from build_cross_domain_world_model_figures import BLUE, GREEN, INK, NAVY, ORANGE, OUTPUT, RED, TEAL

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / "docs/research"
DETECTORS = [("D0", "D0 persistence residual", "#9AA5B1"), ("DR", "DR bound and gradient check", "#7B8794"),
             ("D1", "D1 world model, normal-only", NAVY), ("D2", "D2 incident-informed classifier", ORANGE),
             ("D3", "D3 generic-noise classifier", TEAL), ("D2c", "D2c: D2 at D1's alarm fraction", GREEN)]


def main() -> None:
    rt1 = json.loads((R / "real_telemetry_result_v1.json").read_text(encoding="utf-8"))["datasets"]
    rt2 = json.loads((R / "real_telemetry_result_rt2.json").read_text(encoding="utf-8"))["releases"]
    panels = [("HAI 22.04 (rt1, 58 attacks)", rt1["hai-22.04"]["detectors"]),
              ("HAI 21.03 (rt2, earlier-used data)", rt2["hai-21.03"]["detectors"]),
              ("HAI 23.05 (rt2, earlier-used data)", rt2["hai-23.05"]["detectors"])]
    fig, axes = plt.subplots(1, 3, figsize=(14.5, 4.9), sharey=True)
    for ax, (title, det) in zip(axes, panels):
        keys = [d for d in DETECTORS if d[0] in det]
        x = np.arange(len(keys))
        recall = [100 * det[k]["event_recall"] for k, _, _ in keys]
        bars = ax.bar(x, recall, color=[c for _, _, c in keys], width=0.68)
        for bar, (k, _, _) in zip(bars, keys):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.5,
                    f"{det[k]['detected']}/{det[k]['events']}\n{det[k]['false_episodes_per_day']:.1f}/day",
                    ha="center", va="bottom", fontsize=7.0, color=INK)
        ax.set_xticks(x, [k for k, _, _ in keys], fontsize=9)
        ax.set_title(title, fontsize=10, color=NAVY, weight="bold")
        ax.set_ylim(0, 112)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", color="#E4E7EB", linewidth=0.8)
        ax.set_axisbelow(True)
    axes[0].set_ylabel("Recorded attacks detected (%)", fontsize=9.5)
    from matplotlib.patches import Patch
    fig.legend(handles=[Patch(color=c, label=label) for _, label, c in DETECTORS], loc="lower center", ncol=3,
               fontsize=8.6, frameon=False, bbox_to_anchor=(0.5, -0.1))
    fig.suptitle("Recorded-attack detection at a budget of 2 false alarm episodes per day (labels: found/total, false episodes per day)",
                 fontsize=10.5, color=INK, y=1.02)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT / "real_telemetry_results_v1_3.png", dpi=220, bbox_inches="tight", facecolor="white",
                metadata={"Software": None})
    plt.close(fig)
    print(OUTPUT / "real_telemetry_results_v1_3.png")


if __name__ == "__main__":
    main()
