"""Threshold trajectories (Figures 2 and 3), shared drawing code.

Reads ../figure_data/threshold_trajectories.csv only. Nothing is smoothed,
resampled or dropped: every row of the selected stream is drawn; missing
score values (NaN) are left as gaps.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.transforms as mtransforms
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import LogLocator, FuncFormatter
from tt1_style import (DATA, RULE_COLOR, RULE_LS, SCORE_COLOR, ATTACK_SHADE,
                       apply_style, save, check_layout)

RULES = ["frozen", "tracker", "daily", "spot_mle", "dspot"]   # order as requested


def load(dataset):
    df = pd.read_csv(os.path.join(DATA, "threshold_trajectories.csv"))
    return df[df.dataset == dataset].copy()


def intervals(g):
    """Contiguous runs of attack == 1 -> list of (row_start, row_end) inclusive."""
    a = g.attack.to_numpy()
    d = np.diff(np.r_[0, a, 0])
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0] - 1))


def caught(g, rule):
    """Caught = score_max > tau_<rule> in at least one row of the interval."""
    s = g.score_max.to_numpy(); tau = g["tau_" + rule].to_numpy()
    return [bool(np.any(s[i:j + 1] > tau[i:j + 1])) for i, j in intervals(g)]


def consistency(df, expected):
    """Event counts over all streams of the dataset vs. the counts the README records."""
    got = {}
    for r in expected:
        n_c = n = 0
        for _, g in df.groupby("stream", sort=False):
            g = g.sort_values("t")
            c = caught(g, r); n_c += sum(c); n += len(c)
        got[r] = (n_c, n)
    return got


def _log_fmt(v, _):
    return f"{v:g}" if v >= 1 else f"{v:.1g}"


def draw(dataset, stream, per_day, unit_label, zoom, zoom_title, stem, expected):
    apply_style()
    df = load(dataset)
    g = df[df.stream == stream].sort_values("t").reset_index(drop=True)
    n_rows = len(g)
    # checks against the CSV before drawing
    assert n_rows == len(df[df.stream == stream]), "rows lost"
    assert (np.diff(g.t) == 1).all(), "time index not contiguous"
    got = consistency(df, expected)
    for r, (c, n) in expected.items():
        assert got[r] == (c, n), f"{r}: CSV gives {got[r]}, README records {(c, n)}"
    iv = intervals(g)
    hit = caught(g, "tracker")
    days = g.t.to_numpy() / per_day
    step = 1.0 / per_day

    fig, axes = plt.subplots(2, 1, figsize=(7.0, 4.6), gridspec_kw=dict(hspace=0.42))
    for k, ax in enumerate(axes):
        for (i, j) in iv:
            ax.axvspan(days[i], days[j] + step, color=ATTACK_SHADE, lw=0, zorder=0)
        ax.plot(days, g.score_max, color=SCORE_COLOR, lw=0.45, alpha=0.75, zorder=1)
        for r in RULES:
            ax.plot(days, g["tau_" + r], color=RULE_COLOR[r], ls=RULE_LS[r],
                    lw=1.5 if r == "frozen" else 1.1, zorder=3 if r == "frozen" else 2)
        ax.set_yscale("log")
        ax.yaxis.set_major_locator(LogLocator(base=10))
        ax.yaxis.set_major_formatter(FuncFormatter(_log_fmt))
        ax.set_ylabel("score / threshold (log)")
        # caught / missed by tracker, one marker per attack interval, above the data
        trans = mtransforms.blended_transform_factory(ax.transData, ax.transAxes)
        for (i, j), h in zip(iv, hit):
            xm = (days[i] + days[j] + step) / 2
            if k == 1 and not (zoom[0] <= xm <= zoom[1]):
                continue
            ax.plot([xm], [1.03], marker="o", ms=4.2, transform=trans, clip_on=False,
                    mfc=RULE_COLOR["tracker"] if h else "white", mec=RULE_COLOR["tracker"], mew=1.0)
        ax.margins(x=0.005)
    axes[0].set_xlim(days[0], days[-1] + step)
    axes[1].set_xlim(*zoom)
    yl = axes[0].get_ylim(); axes[1].set_ylim(yl)
    axes[1].set_xlabel(f"time since start of {stream} (days; one row per {unit_label})")
    axes[0].set_title(f"{dataset} {stream}: whole stream ({len(iv)} attack intervals, "
                      f"tracker caught {sum(hit)}, missed {len(hit) - sum(hit)})", pad=12)
    axes[1].set_title(zoom_title, pad=12)

    handles = [Line2D([], [], color=SCORE_COLOR, lw=0.8, label="score_max")]
    handles += [Line2D([], [], color=RULE_COLOR[r], ls=RULE_LS[r], lw=1.5 if r == "frozen" else 1.1,
                       label="tau_" + r) for r in RULES]
    handles += [Patch(fc=ATTACK_SHADE, ec="none", label="attack = 1"),
                Line2D([], [], ls="none", marker="o", ms=4.2, mfc=RULE_COLOR["tracker"],
                       mec=RULE_COLOR["tracker"], label="caught by tracker"),
                Line2D([], [], ls="none", marker="o", ms=4.2, mfc="white",
                       mec=RULE_COLOR["tracker"], label="missed by tracker")]
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, -0.06), ncol=5,
               handlelength=2.4, columnspacing=1.2)
    report = dict(dataset=dataset, stream=stream, rows=n_rows,
                  score_missing=int(g.score_max.isna().sum()),
                  missing_t=g.t[g.score_max.isna()].tolist(),
                  intervals=len(iv), tracker_caught=int(sum(hit)),
                  counts_all_streams={r: f"{c}/{n}" for r, (c, n) in got.items()})
    return fig, report


def main(**kw):
    fig, report = draw(**kw)
    fig.canvas.draw()
    print("text overlaps:", check_layout(fig))
    print("checks:", report)
    print(save(fig, kw["stem"]))
    return fig, report
