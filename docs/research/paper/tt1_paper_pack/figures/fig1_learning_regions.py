"""Figure 1: learning regions (schematic, no data).

Which part of the score range each rule family learns from, following the
learning-region table in Section 3 of the draft. Run:  python -B fig1_learning_regions.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyArrowPatch, Patch
from matplotlib.lines import Line2D
from tt1_style import RULE_COLOR, ATTACK_SHADE, GREY, apply_style, save, check_layout

apply_style()

# score-axis coordinates (arbitrary units; schematic only)
Y0, T_BASE, TAU, Y1 = 0.0, 1.0, 2.0, 3.0

# columns: (label under column, [(rule, region, style)], movement note)
# region: "exc" = above tau_t, "band" = (t, tau_t], "below" = below t
COLS = [
    ("frozen",            [("frozen", None, None)],                       "none"),
    ("margin",            [("margin", None, None)],                       "none"),
    ("daily",             [("daily", "exc", "fill")],                     "up"),
    ("tracker,\ntracker_slow", [("tracker", "exc", "fill"), ("tracker_slow", "exc", "fill")], "up"),
    ("spot,\nspot_mle",   [("spot", "band", "fill"), ("spot_mle", "band", "fill")], "up"),
    ("dspot",             [("dspot", "band", "fill"), ("dspot", "below", "hatch")], "up"),
    ("one_sided:none\n(tighten-only)", [("one_sided:none", None, None)], "down"),
]
REG = {"exc": (TAU, Y1), "band": (T_BASE, TAU), "below": (Y0, T_BASE)}

fig, ax = plt.subplots(figsize=(7.0, 3.0))
x_left, colw, gap = 2.55, 0.82, 0.5
x_end = x_left + len(COLS) * (colw + gap) - gap + 0.15

# three score regions, shaded across the whole width
ax.add_patch(Rectangle((0.9, TAU), x_end - 0.9, Y1 - TAU, color=ATTACK_SHADE, alpha=0.55, lw=0, zorder=0))
ax.add_patch(Rectangle((0.9, T_BASE), x_end - 0.9, TAU - T_BASE, color=ATTACK_SHADE, alpha=0.25, lw=0, zorder=0))
ax.plot([0.9, x_end], [TAU, TAU], color="black", lw=1.2, zorder=3)
ax.plot([0.9, x_end], [T_BASE, T_BASE], color="black", lw=0.9, ls=(0, (4, 2)), zorder=3)
ax.text(x_end + 0.08, TAU, r"alarm threshold $\tau_t$", va="center", ha="left", fontsize=7)
ax.text(x_end + 0.08, T_BASE, "base level $t$\n(SPOT, DSPOT)", va="center", ha="left", fontsize=7)

# region names on the left
ax.text(0.95, (TAU + Y1) / 2, "exceedances\n$s_t > \\tau_t$\n(alarms)", va="center", ha="left", fontsize=7)
ax.text(0.95, (T_BASE + TAU) / 2, "band\n$t < s_t \\leq \\tau_t$", va="center", ha="left", fontsize=7)
ax.text(0.95, (Y0 + T_BASE) / 2, "below $t$", va="center", ha="left", fontsize=7)

# score axis arrow
ax.add_patch(FancyArrowPatch((0.7, Y0), (0.7, Y1 + 0.05), arrowstyle="-|>", mutation_scale=8, lw=0.8, color="black"))
ax.text(0.58, Y1 / 2, "score $s_t$", rotation=90, va="center", ha="right", fontsize=8)

for k, (label, parts, move) in enumerate(COLS):
    x0 = x_left + k * (colw + gap)
    edge = RULE_COLOR[parts[0][0]] if len({q[0] for q in parts}) == 1 else GREY
    ax.add_patch(Rectangle((x0, Y0), colw, Y1 - Y0, fill=False, ec=edge,
                           lw=1.6 if edge != GREY else 0.5, zorder=1))
    fills = [p for p in parts if p[1] is not None and p[2] == "fill"]
    nsub = max(1, len(fills))
    for j, (rule, region, sty) in enumerate(fills):
        lo, hi = REG[region]
        ax.add_patch(Rectangle((x0 + j * colw / nsub, lo), colw / nsub, hi - lo,
                               color=RULE_COLOR[rule], lw=0, zorder=2))
    for rule, region, sty in parts:
        if sty == "hatch":
            lo, hi = REG[region]
            ax.add_patch(Rectangle((x0, lo), colw, hi - lo, fill=False, hatch="////",
                                   ec=RULE_COLOR[rule], lw=0, zorder=2))
    if move == "none":
        ax.text(x0 + colw / 2, (Y0 + Y1) / 2, "learns\nfrom\nnothing", ha="center", va="center",
                fontsize=6.5, color="#333333")
    if move == "up":
        ax.add_patch(FancyArrowPatch((x0 + colw / 2, TAU - 0.02), (x0 + colw / 2, TAU + 0.42),
                                     arrowstyle="-|>", mutation_scale=9, lw=1.3, color="black", zorder=4))
    if move == "down":
        ax.add_patch(FancyArrowPatch((x0 + colw / 2, TAU + 0.02), (x0 + colw / 2, TAU - 0.42),
                                     arrowstyle="-|>", mutation_scale=9, lw=1.3, color=RULE_COLOR["one_sided:none"], zorder=4))
        ax.text(x0 + colw / 2, (Y0 + T_BASE) / 2 + 0.05, "moves\nonly\ndown", ha="center", va="center",
                fontsize=6.5, color="#333333")
    ax.text(x0 + colw / 2, Y0 - 0.08, label, ha="center", va="top", fontsize=7)

# key below the columns
handles = [Patch(fc=GREY, ec="none", label="region the rule fits its threshold to (colour = rule)"),
           Patch(fc="none", ec=RULE_COLOR["dspot"], hatch="////", lw=0, label="DSPOT moving mean: all non-alarm values"),
           Line2D([], [], color="black", marker="^", ls="-", lw=1.2, ms=4, label="learning can raise $\\tau_t$")]
ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.02), ncol=3, handlelength=1.6,
          columnspacing=1.4, fontsize=7)

ax.set_xlim(0.3, x_end + 1.15)
ax.set_ylim(Y0 - 0.5, Y1 + 0.05)
ax.axis("off")

if __name__ == "__main__":
    fig.canvas.draw()
    bad = check_layout(fig)
    print("text overlaps:", bad)
    print(save(fig, "fig1_learning_regions"))
