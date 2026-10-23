"""Figure 4: recall against the frozen threshold (forest plot), score D1.

Reads ../figure_data/recall_and_false_alarms_by_rule.csv only.
Run: python -B fig4_recall_forest.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from tt1_style import DATA, RULE_COLOR, RULE_MARKER, GREY, apply_style, save, check_layout

RULES = ["daily", "tracker", "tracker_slow", "one_sided:none", "spot", "spot_mle", "dspot"]
GROUPS = [  # (section header, [(dataset, status)])
    ("Registered", [("hai-20.07", "registered tt1"), ("hygrid-ics", "registered tt1"),
                    ("voraus-ad", "registered tt1"), ("batadal", "registered tt1b")]),
    ("Exploratory: spent HAI releases", [("hai-21.03", "exploratory (spent data)"),
                                         ("hai-22.04", "exploratory (spent data)"),
                                         ("hai-23.05", "exploratory (spent data)")]),
    ("Post-hoc: tt1 datasets reopened after the finals",
     [("hai-20.07", "post-hoc (after finals)"), ("hygrid-ics", "post-hoc (after finals)"),
      ("voraus-ad", "post-hoc (after finals)")]),
]
UNIT = {"voraus-ad": "anomalous samples"}

apply_style()
df = pd.read_csv(os.path.join(DATA, "recall_and_false_alarms_by_rule.csv"))
d1 = df[(df.score == "D1") & (df.rule.isin(RULES))]
# every (dataset, status) in the CSV must be one of the plotted blocks, so no D1 block is silently left out
blocks = {b for _, bl in GROUPS for b in bl}
assert set(map(tuple, d1[["dataset", "status"]].drop_duplicates().to_numpy())) == blocks
assert not d1.duplicated(["dataset", "status", "rule"]).any()

BAND, DODGE = 1.0, 0.12
fig, ax = plt.subplots(figsize=(7.0, 7.4))
y = 0.0
yt, ylab, plotted, gaps = [], [], [], []
for gi, (header, bl) in enumerate(GROUPS):
    y -= 0.55
    ax.text(-1.06, y + 0.05, header, ha="left", va="center", fontsize=8, fontweight="bold",
            transform=ax.transData)
    y -= 0.8
    top = y + 0.5
    for ds, st in bl:
        sub = d1[(d1.dataset == ds) & (d1.status == st)].set_index("rule")
        ev = sub.events.dropna().unique()
        n_txt = (f"{int(ev[0])} {UNIT.get(ds, 'attacks')}" if len(ev) == 1 else "events not given in CSV")
        yt.append(y); ylab.append(f"{ds}  [{st}]\n{n_txt}")
        missing = []
        for k, r in enumerate(RULES):
            yy = y - (k - (len(RULES) - 1) / 2) * DODGE  # first rule on top
            if r not in sub.index:
                missing.append(r); continue
            row = sub.loc[r]
            ax.plot([row.ci_low, row.ci_high], [yy, yy], color=RULE_COLOR[r], lw=1.3, solid_capstyle="butt", zorder=2)
            ax.plot([row.diff_vs_frozen], [yy], marker=RULE_MARKER[r], color=RULE_COLOR[r], ms=4.2,
                    mec="black", mew=0.35, ls="none", zorder=3)
            plotted.append((ds, st, r, row.diff_vs_frozen, row.ci_low, row.ci_high, yy))
        if missing:
            gaps.append((ds, st, missing))
            ax.text(0.04, y, "no row in CSV: " + ", ".join(missing) + "\n(not part of the tt1 registration)",
                    ha="left", va="center", fontsize=6.5, color=GREY, style="italic")
        y -= BAND
    bottom = y + 0.5
    if gi % 2 == 0:
        ax.axhspan(bottom, top + 0.1, color="#F2F2F2", lw=0, zorder=0)
    if gi < len(GROUPS) - 1:
        ax.axhline(bottom - 0.02, color="black", lw=0.8)

ax.axvline(0, color="black", lw=0.8, zorder=1)
ax.set_yticks(yt); ax.set_yticklabels(ylab, fontsize=6.5)
ax.tick_params(axis="y", length=0)
ax.set_ylim(y + 0.45, 0.05)
ax.set_xlim(-1.06, 0.62)
ax.set_xlabel("recall difference vs. frozen threshold (D1 score, 95% interval)")
ax.text(-0.02, 1.005, "lower recall than frozen", transform=ax.get_xaxis_transform(), ha="right", va="bottom", fontsize=7)
ax.text(0.02, 1.005, "higher", transform=ax.get_xaxis_transform(), ha="left", va="bottom", fontsize=7)
handles = [Line2D([], [], color=RULE_COLOR[r], marker=RULE_MARKER[r], mec="black", mew=0.35, ms=4.2,
                  lw=1.3, label=r) for r in RULES]
fig.subplots_adjust(bottom=0.11)
fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.56, 0.0), ncol=7, columnspacing=1.0,
           handlelength=1.8)

# check what is drawn against the CSV
for ds, st, r, dv, lo, hi, _ in plotted:
    row = d1[(d1.dataset == ds) & (d1.status == st) & (d1.rule == r)].iloc[0]
    assert (row.diff_vs_frozen, row.ci_low, row.ci_high) == (dv, lo, hi)
    assert lo <= dv <= hi
assert len(plotted) == len(d1), (len(plotted), len(d1))
report = dict(rows_plotted=len(plotted), rows_in_csv_subset=len(d1), gaps=gaps)

if __name__ == "__main__":
    fig.canvas.draw()
    print("text overlaps:", check_layout(fig))
    print("checks:", report)
    print(save(fig, "fig4_recall_forest"))
