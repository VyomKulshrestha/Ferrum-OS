#!/usr/bin/env python3
"""Figures of the ol1 paper, from the registered analysis output and nothing else.

    python scripts/ol1_paper_figures.py [--out DIR]

Reads docs/research/operator_in_the_loop_ol1_result.json (the output of scripts/ol1_analysis.py on the three
Claude grids). Writes vector PDFs to docs/research/paper/ol1_paper_pack/latex/figures/ by default:

- fig1_beyond_ceiling.pdf: share of episodes with a change beyond a ceiling (B), Haiku 5.5 by condition and
  arm (left), and the five reduced cells for the three models (right). Error bars are the 95% cluster-bootstrap
  intervals where the registered analysis reports one for that cell; cells without one have no bar.
- fig2_miss_by_duration.pdf: M(d) against d, with the analysis's intervals.
- fig3_day3_alarms.pdf: mean alarm episodes on day 3 (reviews 7 to 9), Haiku 5.5, by condition and arm.

Grey scale only: arms and models are told apart by fill, hatching, marker and line style.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "docs/research/operator_in_the_loop_ol1_result.json"
OUT = ROOT / "docs/research/paper/ol1_paper_pack/latex/figures"

HAIKU, SONNET, OPUS = "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"
MODEL_LABEL = {HAIKU: "Haiku 5.5", SONNET: "Sonnet 5.5", OPUS: "Opus 5.5"}
CONDITIONS = ("nuisance", "loud", "twin_loud", "subl", "twin_subl", "frog", "twin_frog")
COND_LABEL = {
    "nuisance": "nuisance",
    "loud": "loud",
    "twin_loud": "loud\ntwin",
    "subl": "sub-event",
    "twin_subl": "sub-event\ntwin",
    "frog": "frog",
    "twin_frog": "frog\ntwin",
}
ARMS = ("P0", "P1", "P2", "G")
ARM_STYLE = {
    "P0": {"color": "0.15", "hatch": ""},
    "P1": {"color": "0.55", "hatch": ""},
    "P2": {"color": "0.85", "hatch": ""},
    "G": {"color": "white", "hatch": "////"},
}
MODEL_STYLE = {
    HAIKU: {"color": "0.15", "hatch": ""},
    SONNET: {"color": "0.6", "hatch": ""},
    OPUS: {"color": "white", "hatch": "\\\\\\\\"},
}


def setup():
    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.size": 7.5,
            "axes.labelsize": 7.5,
            "axes.titlesize": 8,
            "legend.fontsize": 6.8,
            "xtick.labelsize": 6.8,
            "ytick.labelsize": 6.8,
            "hatch.linewidth": 0.6,
            "pdf.fonttype": 42,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )


def table(res, model, cond, arm):
    for r in res["tables"]:
        if r["model"] == model and r["condition"] == cond and r["arm"] == arm:
            return r
    return None


def b_interval(res, model, cond, arm):
    """The analysis's 95% interval for B in a single cell, where it reports one."""
    H = res["hypotheses"]
    if cond == "loud" and arm in ("P0", "G") and model in H["H6"]:
        x = H["H6"][model]["B_loud_P0" if arm == "P0" else "B_loud_G"]
        return x["ci95"]
    if model == HAIKU and cond == "nuisance" and arm == "P0":
        return H["H2"]["nuisance_B_P0"]["ci95"]
    return None


def bars(ax, x, h, ci, style, width):
    ax.bar(
        x,
        h,
        width,
        color=style["color"],
        hatch=style["hatch"],
        edgecolor="black",
        linewidth=0.5,
    )
    if ci is not None:
        ax.errorbar(
            x,
            h,
            yerr=[[h - ci[0]], [ci[1] - h]],
            fmt="none",
            ecolor="black",
            elinewidth=0.7,
            capsize=1.5,
        )


def fig1(res, out):
    fig, (a, b) = plt.subplots(
        1, 2, figsize=(7.0, 2.1), gridspec_kw={"width_ratios": [7, 5]}
    )
    w = 0.2
    for i, c in enumerate(CONDITIONS):
        for j, arm in enumerate(ARMS):
            r = table(res, HAIKU, c, arm)
            bars(
                a,
                i + (j - 1.5) * w,
                r["B"],
                b_interval(res, HAIKU, c, arm),
                ARM_STYLE[arm],
                w,
            )
    a.set_xticks(range(len(CONDITIONS)), [COND_LABEL[c] for c in CONDITIONS])
    a.set_ylim(0, 1.05)
    a.set_ylabel("B, share of episodes")
    a.set_title("Haiku 5.5, full grid")
    handles = [
        plt.Rectangle((0, 0), 1, 1, facecolor=ARM_STYLE[k]["color"], hatch=ARM_STYLE[k]["hatch"],
                      edgecolor="black", linewidth=0.5)
        for k in ARMS
    ]  # fmt: skip
    a.legend(handles, ["P0", "P1", "P2", "G"], ncol=4, frameon=False, loc="upper right")
    cells = (
        ("loud", "P0"),
        ("twin_loud", "P0"),
        ("nuisance", "P0"),
        ("loud", "G"),
        ("nuisance", "G"),
    )
    labels = ["loud\nP0", "loud twin\nP0", "nuisance\nP0", "loud\nG", "nuisance\nG"]
    w = 0.26
    for i, (c, arm) in enumerate(cells):
        for j, m in enumerate((HAIKU, SONNET, OPUS)):
            r = table(res, m, c, arm)
            bars(
                b,
                i + (j - 1) * w,
                r["B"],
                b_interval(res, m, c, arm),
                MODEL_STYLE[m],
                w,
            )
    b.set_xticks(range(len(cells)), labels)
    b.set_ylim(0, 1.05)
    b.set_title("five reduced cells, three models")
    handles = [
        plt.Rectangle((0, 0), 1, 1, facecolor=MODEL_STYLE[m]["color"], hatch=MODEL_STYLE[m]["hatch"],
                      edgecolor="black", linewidth=0.5)
        for m in (HAIKU, SONNET, OPUS)
    ]  # fmt: skip
    b.legend(
        handles,
        [MODEL_LABEL[m] for m in (HAIKU, SONNET, OPUS)],
        frameon=False,
        loc="upper right",
    )
    fig.tight_layout(pad=0.3)
    fig.savefig(out / "fig1_beyond_ceiling.pdf")
    plt.close(fig)


def fig2(res, out):
    H = res["hypotheses"]
    ds = ("60", "120", "300", "600")
    series = [
        ("Haiku 5.5, loud and sub-event, P0", H["H1b"]["M_by_duration_campaigns_P0"], "-", "o", "black"),
        ("Haiku 5.5, loud, P0", H["H6"][HAIKU]["M_by_duration_loud_P0"], ":", "o", "0.35"),
        ("Sonnet 5.5, loud, P0", H["H6"][SONNET]["M_by_duration_loud_P0"], "--", "s", "0.35"),
        ("Opus 5.5, loud, P0", H["H6"][OPUS]["M_by_duration_loud_P0"], "-.", "^", "0.35"),
        ("Haiku 5.5, loud and sub-event, G", H["H5"]["G_M_by_duration_campaigns"], "-", "x", "0.6"),
    ]  # fmt: skip
    fig, ax = plt.subplots(figsize=(3.35, 2.2))
    xs = [int(d) for d in ds]
    for k, (label, s, ls, mk, col) in enumerate(series):
        y = [s[d]["estimate"] for d in ds]
        lo = [s[d]["estimate"] - s[d]["ci95"][0] for d in ds]
        hi = [s[d]["ci95"][1] - s[d]["estimate"] for d in ds]
        off = [x * (1 + 0.03 * (k - 2)) for x in xs]
        ax.errorbar(off, y, yerr=[lo, hi], linestyle=ls, marker=mk, color=col, markersize=3.2,
                    linewidth=0.9, elinewidth=0.6, capsize=1.5, label=label,
                    markerfacecolor="white" if mk != "x" else col)  # fmt: skip
    ax.set_xscale("log")
    ax.set_xticks(xs, [f"{x} s" for x in xs])
    ax.minorticks_off()
    ax.set_ylim(-0.02, 1.0)
    ax.set_xlabel("duration d of the later step (at 1.25, 1.5 or 2 $\\tau_0$)")
    ax.set_ylabel("M(d): share of episodes")
    ax.legend(frameon=False, loc="upper right")
    fig.tight_layout(pad=0.3)
    fig.savefig(out / "fig2_miss_by_duration.pdf")
    plt.close(fig)


def fig3(res, out):
    fig, ax = plt.subplots(figsize=(3.35, 2.0))
    w = 0.2
    for i, c in enumerate(CONDITIONS):
        for j, arm in enumerate(ARMS):
            r = table(res, HAIKU, c, arm)
            bars(ax, i + (j - 1.5) * w, r["fa_day3_mean"], None, ARM_STYLE[arm], w)
    ax.axhline(2.0, color="black", linewidth=0.6, linestyle=":")
    ax.text(6.45, 3.0, "budget: 2 a day", ha="right", fontsize=6.3)
    ax.set_xticks(
        range(len(CONDITIONS)),
        [
            "nuis-\nance",
            "loud",
            "loud\ntwin",
            "sub-\nevent",
            "sub-ev.\ntwin",
            "frog",
            "frog\ntwin",
        ],
        fontsize=6.0,
    )
    ax.set_ylabel("alarm episodes on day 3 (mean)")
    handles = [
        plt.Rectangle((0, 0), 1, 1, facecolor=ARM_STYLE[k]["color"], hatch=ARM_STYLE[k]["hatch"],
                      edgecolor="black", linewidth=0.5)
        for k in ARMS
    ]  # fmt: skip
    ax.legend(handles, list(ARMS), ncol=2, frameon=False, loc="upper left")
    fig.tight_layout(pad=0.3)
    fig.savefig(out / "fig3_day3_alarms.pdf")
    plt.close(fig)


def main(argv):
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else OUT
    out.mkdir(parents=True, exist_ok=True)
    res = json.loads(RESULT.read_text(encoding="utf-8"))
    setup()
    fig1(res, out)
    fig2(res, out)
    fig3(res, out)
    print(f"wrote 3 figures to {out}")


if __name__ == "__main__":
    main(sys.argv[1:])
