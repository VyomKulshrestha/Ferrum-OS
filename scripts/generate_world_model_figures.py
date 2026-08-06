#!/usr/bin/env python3
"""Generate publication figures for the FerrumOS world-model paper."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT / "docs/research/world_model_safety_baseline.json"
DEFAULT_MANIFEST = ROOT / "appliance/world-model/manifest.json"
DEFAULT_PAPER_EVIDENCE = ROOT / "docs/research/world_model_paper_evaluation.json"
DEFAULT_OUT = ROOT / "docs/research/figures"

ARM_ORDER = ("rules_only", "jepa_only", "rules_plus_jepa")
ARM_LABELS = ("Rules only", "JEPA only", "Rules + JEPA")
ARM_COLORS = ("#6B7280", "#E69F00", "#0072B2")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def artifact_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def configure_style() -> None:
    mpl.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.titlesize": 10,
        "axes.labelsize": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "svg.hashsalt": "ferrumos-world-model-paper-v1",
    })


def save_figure(fig, stem: Path) -> list[Path]:
    outputs = []
    for suffix in ("png", "svg", "pdf"):
        path = stem.with_suffix(f".{suffix}")
        if suffix == "svg":
            metadata = {"Date": None}
        elif suffix == "pdf":
            metadata = {
                "Creator": "FerrumOS reproducible paper figure generator",
                "CreationDate": None,
                "ModDate": None,
            }
        else:
            metadata = {"Software": "FerrumOS reproducible paper figure generator"}
        fig.savefig(path, dpi=300, bbox_inches="tight", pad_inches=0.08,
                    metadata=metadata)
        if suffix == "svg":
            svg = path.read_text(encoding="utf-8")
            path.write_text(
                "\n".join(line.rstrip() for line in svg.splitlines()) + "\n",
                encoding="utf-8",
            )
        outputs.append(path)
    plt.close(fig)
    return outputs


def figure_one(baseline: dict, output_dir: Path) -> list[Path]:
    conditions = baseline["results"]["conditions"]
    fnr = np.asarray([conditions[arm]["false_negative_rate"] for arm in ARM_ORDER]) * 100
    fpr = np.asarray([conditions[arm]["false_positive_rate"] for arm in ARM_ORDER]) * 100
    balanced = np.asarray([conditions[arm]["balanced_accuracy"] for arm in ARM_ORDER]) * 100

    fnr_ci = np.asarray([
        conditions[arm]["false_negative_rate_wilson_95"] for arm in ARM_ORDER
    ]) * 100
    fpr_ci = np.asarray([
        conditions[arm]["false_positive_rate_wilson_95"] for arm in ARM_ORDER
    ]) * 100

    fig, (ax_error, ax_balanced) = plt.subplots(
        1, 2, figsize=(7.25, 3.65), gridspec_kw={"width_ratios": [1.65, 1]}
    )
    x = np.arange(2)
    width = 0.23
    for index, (label, color) in enumerate(zip(ARM_LABELS, ARM_COLORS)):
        values = np.asarray([fnr[index], fpr[index]])
        intervals = (fnr_ci[index], fpr_ci[index])
        lower = np.asarray([values[0] - intervals[0][0], values[1] - intervals[1][0]])
        upper = np.asarray([intervals[0][1] - values[0], intervals[1][1] - values[1]])
        bars = ax_error.bar(
            x + (index - 1) * width, values, width, label=label, color=color,
            edgecolor="white", linewidth=0.7, yerr=np.vstack((lower, upper)),
            error_kw={"elinewidth": 0.9, "capsize": 2.5, "capthick": 0.9},
        )
        ax_error.bar_label(bars, labels=[f"{value:.1f}%" for value in values],
                           padding=3, fontsize=7.5)
    ax_error.set_xticks(x, ("False-negative rate", "False-positive rate"))
    ax_error.set_ylabel("Rate (%) — lower is better")
    ax_error.set_ylim(0, 90)
    ax_error.grid(axis="y", color="#D1D5DB", linewidth=0.6, alpha=0.8)
    ax_error.set_axisbelow(True)
    ax_error.legend(frameon=False, loc="upper right", fontsize=8)
    ax_error.set_title("a  Safety errors with 95% Wilson intervals", loc="left", fontweight="bold")

    bars = ax_balanced.bar(
        np.arange(3), balanced, width=0.62, color=ARM_COLORS,
        edgecolor="white", linewidth=0.7,
    )
    ax_balanced.bar_label(bars, labels=[f"{value:.1f}%" for value in balanced],
                          padding=3, fontsize=8)
    ax_balanced.set_xticks(np.arange(3), ("Rules", "JEPA", "Combined"), rotation=18)
    ax_balanced.set_ylabel("Balanced accuracy (%) — higher is better")
    ax_balanced.set_ylim(0, 90)
    ax_balanced.grid(axis="y", color="#D1D5DB", linewidth=0.6, alpha=0.8)
    ax_balanced.set_axisbelow(True)
    ax_balanced.set_title("b  Decision balance", loc="left", fontweight="bold")

    fig.suptitle("Three-arm world-model safety comparison (500 paired episodes)",
                 x=0.06, ha="left", y=1.01, fontsize=11, fontweight="bold")
    fig.text(0.06, -0.025,
             "Same 250 safe and 250 dangerous episodes in every arm; combined is the runtime policy.",
             fontsize=7.5, color="#4B5563")
    fig.tight_layout(w_pad=2.2)
    return save_figure(fig, output_dir / "figure_1_three_arm_comparison")


def add_box(ax, x, y, width, height, text, face, edge="#374151",
            fontsize=8.1, linestyle="-"):
    patch = FancyBboxPatch(
        (x, y), width, height,
        boxstyle="round,pad=0.008,rounding_size=0.009",
        linewidth=1.05, edgecolor=edge, facecolor=face, linestyle=linestyle,
        transform=ax.transAxes,
    )
    ax.add_patch(patch)
    ax.text(x + width / 2, y + height / 2, text, ha="center", va="center",
            fontsize=fontsize, transform=ax.transAxes, color="#111827")
    return patch


def add_arrow(ax, start, end, color="#4B5563", style="-|>",
              connectionstyle="arc3", linestyle="-"):
    arrow = FancyArrowPatch(
        start, end, arrowstyle=style, mutation_scale=9, linewidth=1.05,
        color=color, connectionstyle=connectionstyle, linestyle=linestyle,
        transform=ax.transAxes,
    )
    ax.add_patch(arrow)


def figure_two(manifest: dict, output_dir: Path) -> list[Path]:
    encoder_hidden = manifest["representation"]["hidden_size"]
    latent = manifest["representation"]["latent_size"]
    transition_hidden = manifest["transition"]["hidden_size"]
    horizon = manifest["transition"]["lookahead_horizon"]

    fig, ax = plt.subplots(figsize=(10.4, 6.0))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.text(0.02, 0.965, "a  JEPA representation training", fontsize=11,
            fontweight="bold", transform=ax.transAxes)
    ax.text(0.02, 0.925, "Training-only modules are dashed; from panel a, only the online encoder is packaged.",
            fontsize=8, color="#4B5563", transform=ax.transAxes)

    add_box(ax, 0.02, 0.70, 0.105, 0.105, "OS state $x_t$\n48 raw features", "#E5E7EB")
    add_box(ax, 0.17, 0.70, 0.15, 0.105,
            f"Online encoder $E_\\theta$\n48 → {encoder_hidden} ReLU → {latent}", "#DBEAFE")
    add_box(ax, 0.365, 0.70, 0.095, 0.105, f"Context\n$z_t$ ({latent})", "#BFDBFE")
    add_box(ax, 0.365, 0.535, 0.095, 0.105,
            "Action $a_t$\n41 tool + 16 args", "#FEF3C7")
    add_box(ax, 0.515, 0.63, 0.16, 0.13,
            f"JEPA predictor $P_\\phi$\n({latent} + 57) → {encoder_hidden}\nReLU → {latent}", "#FFEDD5",
            linestyle="--")
    add_box(ax, 0.73, 0.65, 0.105, 0.09, f"Predicted\n$\\hat z_{{t+1}}$ ({latent})", "#FED7AA",
            linestyle="--")

    add_box(ax, 0.02, 0.42, 0.105, 0.105, "Next state\n$x_{t+1}$ (48)", "#E5E7EB")
    add_box(ax, 0.17, 0.42, 0.15, 0.105,
            f"EMA target $E_\\xi$\n48 → {encoder_hidden} ReLU → {latent}", "#E0E7FF",
            linestyle="--")
    add_box(ax, 0.73, 0.45, 0.105, 0.09, f"Target\n$z_{{t+1}}$ ({latent})", "#DDD6FE",
            linestyle="--")
    add_box(ax, 0.875, 0.545, 0.105, 0.10,
            "JEPA loss\n$\\|\\hat z-z\\|^2$", "#FCE7F3", linestyle="--")

    add_box(ax, 0.515, 0.37, 0.16, 0.07,
            "Training auxiliaries\nreconstruct $x_t$; decode $a_t$", "#F3F4F6",
            fontsize=7.7, linestyle="--")

    add_arrow(ax, (0.125, 0.752), (0.17, 0.752))
    add_arrow(ax, (0.32, 0.752), (0.365, 0.752))
    add_arrow(ax, (0.46, 0.752), (0.515, 0.715))
    add_arrow(ax, (0.46, 0.588), (0.515, 0.675))
    add_arrow(ax, (0.675, 0.695), (0.73, 0.695))
    add_arrow(ax, (0.125, 0.472), (0.17, 0.472))
    add_arrow(ax, (0.32, 0.472), (0.73, 0.495))
    add_arrow(ax, (0.835, 0.695), (0.875, 0.61))
    add_arrow(ax, (0.835, 0.495), (0.875, 0.58))
    add_arrow(ax, (0.412, 0.70), (0.57, 0.44), linestyle="--")
    add_arrow(ax, (0.412, 0.535), (0.60, 0.44), linestyle="--")
    ax.annotate("EMA update", xy=(0.255, 0.53), xytext=(0.255, 0.66),
                ha="center", fontsize=7.4, color="#4B5563",
                arrowprops={"arrowstyle": "-|>", "linestyle": "--",
                            "color": "#6B7280", "lw": 0.9},
                xycoords=ax.transAxes, textcoords=ax.transAxes)

    ax.plot([0.02, 0.98], [0.355, 0.355], color="#9CA3AF", linewidth=0.9,
            transform=ax.transAxes)
    ax.text(0.02, 0.315, "b  Runtime safety path", fontsize=11,
            fontweight="bold", transform=ax.transAxes)

    add_box(ax, 0.02, 0.10, 0.14, 0.12,
            f"128-state embedding\n51 fixed + {latent} latent", "#DBEAFE")
    add_box(ax, 0.19, 0.10, 0.105, 0.12, "Canonical action\n57 features", "#FEF3C7")
    add_box(ax, 0.335, 0.09, 0.15, 0.14,
            f"Transition MLP\n185 → {transition_hidden} ReLU\n→ 128-state delta", "#FFEDD5")
    add_box(ax, 0.525, 0.10, 0.11, 0.12,
            f"Learned rollout\nH = {horizon}", "#FED7AA")
    add_box(ax, 0.525, 0.255, 0.11, 0.07,
            f"Rule rollout\nH = {horizon}", "#E5E7EB")
    add_box(ax, 0.68, 0.11, 0.12, 0.105,
            "Monotonic union\nmax risk", "#FCE7F3")
    add_box(ax, 0.845, 0.10, 0.135, 0.12,
            "Safety predicates\nthen capabilities\nand syscalls", "#DCFCE7")

    add_arrow(ax, (0.16, 0.16), (0.335, 0.18))
    add_arrow(ax, (0.295, 0.16), (0.335, 0.14))
    add_arrow(ax, (0.485, 0.16), (0.525, 0.16))
    add_arrow(ax, (0.635, 0.16), (0.68, 0.16))
    add_arrow(ax, (0.635, 0.29), (0.72, 0.215))
    add_arrow(ax, (0.80, 0.16), (0.845, 0.16))
    add_arrow(ax, (0.09, 0.22), (0.525, 0.29), connectionstyle="arc3,rad=-0.12")

    ax.text(0.02, 0.035,
            "A learned false-safe forecast cannot erase a deterministic block; the neural model is ring-3, not kernel-resident.",
            fontsize=8, color="#374151", transform=ax.transAxes)
    fig.subplots_adjust(left=0.01, right=0.99, bottom=0.02, top=0.99)
    return save_figure(fig, output_dir / "figure_2_jepa_architecture")


def figure_three(evidence: dict, output_dir: Path) -> list[Path]:
    names = (
        "rules_only",
        "rules_plus_autoencoder",
        "rules_plus_mean_delta",
        "rules_plus_jepa",
        "rules_plus_validation_calibrated_jepa",
    )
    labels = ("Rules", "Rules + AE", "Rules + mean", "Rules + JEPA", "Calibrated\nRules + JEPA")
    rows = [evidence["baselines"][name] for name in names]
    balanced = np.asarray([row["balanced_accuracy"] for row in rows]) * 100
    fnr = np.asarray([1 - row["recall"] for row in rows]) * 100
    fpr = np.asarray([1 - row["specificity"] for row in rows]) * 100

    fig, (ax_accuracy, ax_errors) = plt.subplots(1, 2, figsize=(8.4, 3.65))
    x = np.arange(len(names))
    bars = ax_accuracy.bar(x, balanced, color=("#6B7280", "#56B4E9", "#009E73", "#0072B2", "#CC79A7"))
    ax_accuracy.bar_label(bars, labels=[f"{value:.1f}%" for value in balanced], padding=3, fontsize=7.4)
    ax_accuracy.set_xticks(x, labels, rotation=18, ha="right")
    ax_accuracy.set_ylim(70, 87)
    ax_accuracy.set_ylabel("Balanced accuracy (%)")
    ax_accuracy.grid(axis="y", color="#D1D5DB", linewidth=0.6, alpha=0.8)
    ax_accuracy.set_axisbelow(True)
    ax_accuracy.set_title("a  Stronger transition baselines", loc="left", fontweight="bold")

    ax_errors.plot(x, fnr, marker="o", color="#D55E00", label="False-negative rate")
    ax_errors.plot(x, fpr, marker="s", color="#0072B2", label="False-positive rate")
    for index, value in enumerate(fnr):
        ax_errors.annotate(f"{value:.1f}", (index, value), xytext=(0, 6), textcoords="offset points", ha="center", fontsize=7)
    for index, value in enumerate(fpr):
        ax_errors.annotate(f"{value:.1f}", (index, value), xytext=(0, -11), textcoords="offset points", ha="center", fontsize=7)
    ax_errors.set_xticks(x, labels, rotation=18, ha="right")
    ax_errors.set_ylim(0, 45)
    ax_errors.set_ylabel("Rate (%)")
    ax_errors.grid(axis="y", color="#D1D5DB", linewidth=0.6, alpha=0.8)
    ax_errors.set_axisbelow(True)
    ax_errors.legend(frameon=False, fontsize=8)
    ax_errors.set_title("b  Safety and availability tradeoff", loc="left", fontweight="bold")
    fig.suptitle("JEPA is competitive, but the simple mean-delta baseline is close",
                 x=0.07, ha="left", y=1.01, fontsize=11, fontweight="bold")
    fig.text(0.07, -0.04,
             "All learned conditions use the same 500 authored stress episodes; calibration uses transition validation residuals only.",
             fontsize=7.5, color="#4B5563")
    fig.tight_layout(w_pad=2.2)
    return save_figure(fig, output_dir / "figure_3_stronger_baselines")


def figure_four(evidence: dict, output_dir: Path) -> list[Path]:
    horizons = sorted(int(value) for value in evidence["horizon_ablation"])
    rows = [evidence["horizon_ablation"][str(value)]["rules_plus_jepa"] for value in horizons]
    fnr = np.asarray([1 - row["recall"] for row in rows]) * 100
    fpr = np.asarray([1 - row["specificity"] for row in rows]) * 100
    balanced = np.asarray([row["balanced_accuracy"] for row in rows]) * 100

    seeds = sorted(evidence["training_seed_sensitivity"], key=int)
    seed_rows = [evidence["training_seed_sensitivity"][seed]["safety"] for seed in seeds]
    seed_fnr = np.asarray([1 - row["recall"] for row in seed_rows]) * 100
    seed_fpr = np.asarray([1 - row["specificity"] for row in seed_rows]) * 100
    seed_balanced = np.asarray([row["balanced_accuracy"] for row in seed_rows]) * 100

    fig, (ax_horizon, ax_seed) = plt.subplots(1, 2, figsize=(8.2, 3.55))
    ax_horizon.plot(horizons, balanced, marker="o", color="#009E73", label="Balanced accuracy")
    ax_horizon.plot(horizons, fnr, marker="s", color="#D55E00", label="FNR")
    ax_horizon.plot(horizons, fpr, marker="^", color="#0072B2", label="FPR")
    ax_horizon.set_xticks(horizons)
    ax_horizon.set_xlabel("Lookahead horizon H")
    ax_horizon.set_ylabel("Rate (%)")
    ax_horizon.set_ylim(0, 90)
    ax_horizon.grid(color="#D1D5DB", linewidth=0.6, alpha=0.8)
    ax_horizon.set_axisbelow(True)
    ax_horizon.legend(frameon=False, fontsize=8)
    ax_horizon.set_title("a  Horizon sensitivity", loc="left", fontweight="bold")

    x = np.arange(len(seeds))
    width = 0.24
    ax_seed.bar(x - width, seed_balanced, width, color="#009E73", label="Balanced accuracy")
    ax_seed.bar(x, seed_fnr, width, color="#D55E00", label="FNR")
    ax_seed.bar(x + width, seed_fpr, width, color="#0072B2", label="FPR")
    ax_seed.set_xticks(x, [f"Seed {seed}" for seed in seeds])
    ax_seed.set_ylabel("Rate (%)")
    ax_seed.set_ylim(0, 90)
    ax_seed.grid(axis="y", color="#D1D5DB", linewidth=0.6, alpha=0.8)
    ax_seed.set_axisbelow(True)
    ax_seed.legend(frameon=False, fontsize=7.4)
    ax_seed.set_title("b  Transition initialization sensitivity", loc="left", fontweight="bold")
    fig.suptitle("The safety result depends on H and transition initialization",
                 x=0.07, ha="left", y=1.01, fontsize=11, fontweight="bold")
    fig.tight_layout(w_pad=2.2)
    return save_figure(fig, output_dir / "figure_4_horizon_and_seed_sensitivity")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--paper-evidence", type=Path, default=DEFAULT_PAPER_EVIDENCE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    configure_style()

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    evidence = json.loads(args.paper_evidence.read_text(encoding="utf-8"))
    outputs = (
        figure_one(baseline, args.out_dir)
        + figure_two(manifest, args.out_dir)
        + figure_three(evidence, args.out_dir)
        + figure_four(evidence, args.out_dir)
    )
    record = {
        "schema_version": 1,
        "generator": "scripts/generate_world_model_figures.py",
        "sources": {
            args.baseline.relative_to(ROOT).as_posix(): sha256(args.baseline),
            args.manifest.relative_to(ROOT).as_posix(): sha256(args.manifest),
            args.paper_evidence.relative_to(ROOT).as_posix(): sha256(args.paper_evidence),
        },
        "figures": [
            {"path": artifact_path(path), "sha256": sha256(path),
             "bytes": path.stat().st_size}
            for path in outputs
        ],
    }
    record_path = args.out_dir / "manifest.json"
    record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"generated {len(outputs)} figure files and {artifact_path(record_path)}")


if __name__ == "__main__":
    main()
