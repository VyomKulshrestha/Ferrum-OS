"""Shared style for the Thresholds That Travel figures.

One colour (and one line style) per threshold rule, used in every figure.
Palette: Paul Tol "muted" (9 colours, designed to stay distinguishable under
colour-vision deficiency). Rule names are written exactly as in the CSVs.
Data are read only from ../figure_data/.
"""
import os
import matplotlib as mpl

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(HERE, "..", "figure_data"))

RULE_COLOR = {
    "frozen":         "#332288",  # indigo
    "margin":         "#DDCC77",  # sand
    "daily":          "#999933",  # olive
    "tracker":        "#CC6677",  # rose
    "tracker_slow":   "#882255",  # wine
    "one_sided:none": "#117733",  # green
    "spot":           "#88CCEE",  # cyan
    "spot_mle":       "#44AA99",  # teal
    "dspot":          "#AA4499",  # purple
}
RULE_LS = {
    "frozen": "-", "margin": (0, (1, 1)), "daily": (0, (6, 2)),
    "tracker": "-", "tracker_slow": (0, (1, 1.5)), "one_sided:none": (0, (5, 1.5, 1, 1.5)),
    "spot": (0, (3, 1)), "spot_mle": (0, (4, 1.5, 1, 1.5, 1, 1.5)), "dspot": (0, (2, 1)),
}
RULE_MARKER = {
    "frozen": "s", "margin": "P", "daily": "D", "tracker": "o", "tracker_slow": "v",
    "one_sided:none": "X", "spot": "^", "spot_mle": "<", "dspot": ">",
}
SCORE_COLOR = "#555555"   # the score itself, not a rule
ATTACK_SHADE = "#D9D9D9"  # labelled attack minutes / steps
GREY = "#777777"


def apply_style():
    mpl.rcParams.update({
        "font.family": "sans-serif", "font.sans-serif": ["DejaVu Sans"],
        "font.size": 8, "axes.labelsize": 8, "axes.titlesize": 8,
        "legend.fontsize": 7, "xtick.labelsize": 6.5, "ytick.labelsize": 6.5,
        "axes.linewidth": 0.6, "xtick.direction": "out", "ytick.direction": "out",
        "xtick.major.size": 3, "ytick.major.size": 3,
        "xtick.major.width": 0.6, "ytick.major.width": 0.6,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": False, "legend.frameon": False,
        "axes.titleweight": "normal", "axes.titlelocation": "left",
        "lines.linewidth": 1.0, "patch.linewidth": 0.6,
        "savefig.dpi": 300, "savefig.bbox": "tight",
        "pdf.fonttype": 42, "ps.fonttype": 42,
        "svg.fonttype": "path", "svg.hashsalt": "tt1",  # text as outlines: identical rendering in any viewer
    })


def save(fig, stem):
    """Write figures/<stem>.pdf and .svg (no timestamps, so reruns are byte-stable)."""
    out = []
    for ext, md in (("pdf", {"CreationDate": None, "ModDate": None, "Producer": None}),
                    ("svg", {"Date": None})):
        p = os.path.join(HERE, f"{stem}.{ext}")
        fig.savefig(p, metadata=md)
        out.append(p)
    return out


def check_layout(fig):
    """Return overlapping visible text pairs (empty list = clean)."""
    r = fig.canvas.get_renderer()
    texts = [(t, t.get_window_extent(r)) for t in fig.findobj(mpl.text.Text)
             if t.get_visible() and t.get_text().strip() and t.get_alpha() != 0]
    bad = []
    for i, (a, ba) in enumerate(texts):
        for b, bb in texts[i + 1:]:
            if ba.overlaps(bb):
                bad.append((a.get_text(), b.get_text()))
    return bad
