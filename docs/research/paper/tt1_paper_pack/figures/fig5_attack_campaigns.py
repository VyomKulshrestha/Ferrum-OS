"""Figure 5: terminal attacks caught after a campaign and in its control.

Reads ../figure_data/attack_campaigns.csv only. Bars = mean over the three spent
HAI releases (hai-21.03, hai-22.04, hai-23.05); dots = the per-release values.
Run: python -B fig5_attack_campaigns.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
from tt1_style import DATA, RULE_COLOR, GREY, apply_style, save, check_layout

RULES = ["frozen", "tracker", "spot_mle", "dspot"]
STATUS = "exploratory (normal data)"
CAMPAIGNS = [  # (campaign value in the CSV, panel title)
    ("E4 supra-threshold pulses", "Supra-threshold pulse campaign (E4)"),
    ("score-level frog closed_1h", "Score-level closed-loop frog, 1 h"),
    ("score-level frog closed_24h", "Score-level closed-loop frog, 24 h"),
    ("physical frog (sensor-noise spoofing, 6h)", "Physical frog (sensor-noise spoofing, 6 h)"),
]
RELEASES = ["hai-21.03", "hai-22.04", "hai-23.05"]
REL_MARK = {"hai-21.03": "o", "hai-22.04": "s", "hai-23.05": "D"}

apply_style()
df = pd.read_csv(os.path.join(DATA, "attack_campaigns.csv"))

fig, axes = plt.subplots(2, 2, figsize=(7.0, 4.6), sharey=True, gridspec_kw=dict(wspace=0.06, hspace=0.55))
axes = axes.ravel()
W = 0.36
offsets = {"terminal_after": -W / 2, "terminal_control": W / 2}
report, gaps = [], []
for ax, (camp, title) in zip(axes, CAMPAIGNS):
    sub = df[(df.campaign == camp) & (df.status == STATUS) & (df.rule.isin(RULES))]
    assert not sub.duplicated(["dataset", "rule"]).any()
    assert set(sub.dataset) == set(RELEASES), (camp, set(sub.dataset))
    pl = sub.placements.unique(); assert len(pl) == 1, (camp, pl)
    for k, r in enumerate(RULES):
        rr = sub[sub.rule == r].set_index("dataset")
        if rr.empty:
            gaps.append((camp, r))
            ax.text(k, 0.04, "no row in CSV", ha="center", va="bottom", fontsize=6, color=GREY, style="italic")
            continue
        assert set(rr.index) == set(RELEASES), (camp, r, list(rr.index))
        for col, dx in offsets.items():
            vals = rr.loc[RELEASES, col].to_numpy(dtype=float)
            assert not np.isnan(vals).any()
            m = vals.mean()
            kw = dict(color=RULE_COLOR[r], ec=RULE_COLOR[r], lw=0.8) if col == "terminal_after" else \
                 dict(color="white", ec=RULE_COLOR[r], hatch="/////", lw=0.8)
            ax.bar(k + dx, m, W * 0.92, zorder=1, **kw)
            if m == 0:   # visible stub for a zero mean
                ax.plot([k + dx - W * 0.46, k + dx + W * 0.46], [0, 0], color=RULE_COLOR[r], lw=2.0, zorder=2,
                        solid_capstyle="butt")
            jit = np.array([-0.09, 0.0, 0.09])
            for rel, v, j in zip(RELEASES, vals, jit):
                ax.plot(k + dx + j, v, marker=REL_MARK[rel], ms=3.4, mfc="white" if col == "terminal_after" else "black",
                        mec="black", mew=0.6, ls="none", zorder=3, clip_on=False)
            report.append(dict(campaign=camp, rule=r, column=col, per_release=dict(zip(RELEASES, vals.tolist())),
                               mean=m, caught=round(m * len(RELEASES) * int(pl[0])), of=len(RELEASES) * int(pl[0])))
    ax.set_xticks(range(len(RULES)))
    ax.set_xticklabels(RULES)
    ax.set_xlim(-0.6, len(RULES) - 0.4)
    ax.set_ylim(0, 1.08)
    ax.set_title(f"{title}\n{int(pl[0])} placements per release, n = 3 releases")
for ax in axes[::2]:
    ax.set_ylabel("terminal attacks caught\n(fraction of placements)")
for ax in axes[1::2]:
    ax.tick_params(axis="y", labelleft=False)

handles = [Patch(fc=GREY, ec=GREY, label="after campaign (mean of 3 releases)"),
           Patch(fc="white", ec=GREY, hatch="/////", label="control, no campaign (mean)")]
handles += [Line2D([], [], marker=REL_MARK[r], ls="none", mfc="white", mec="black", mew=0.6, ms=3.5, label=r)
            for r in RELEASES]
handles += [Line2D([], [], marker="o", ls="none", fillstyle="right", mfc="black", mfcalt="white",
                   mec="black", mew=0.6, ms=4.5, label="release dot: open = after, filled = control")]
fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, 0.035), ncol=3, columnspacing=1.6)

if __name__ == "__main__":
    fig.canvas.draw()
    print("text overlaps:", check_layout(fig))
    print("gaps:", gaps)
    for rec in report:
        print(rec)
    print(save(fig, "fig5_attack_campaigns"))
