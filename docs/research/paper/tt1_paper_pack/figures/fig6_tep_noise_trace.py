"""Figure 6: one Tennessee Eastman noise-attack run under the frozen threshold and the tracker.

Reads ../figure_data/tep_noise_run_trace.csv only (written by scripts/tt1f_tep_dev.py analyse B; the run was
fixed in the tt1f plan before any score was looked at: the type-24 run of mode 0 with the lowest id). One row
per 36 s: the largest D1 score of the interval, tau0, the tracker threshold and the attack indicator key.
Run: python -B fig6_tep_noise_trace.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from tt1_style import DATA, RULE_COLOR, RULE_LS, SCORE_COLOR, ATTACK_SHADE, apply_style, save, check_layout

apply_style()
df = pd.read_csv(os.path.join(DATA, "tep_noise_run_trace.csv"))
h, s = df["hours"].to_numpy(), df["score_max"].to_numpy()
key = df["attack_key"].to_numpy()
edges = np.flatnonzero(np.diff(key) != 0) + 1
starts, ends = np.concatenate([[0], edges]), np.concatenate([edges, [len(key)]])
events = [(h[a], h[b - 1]) for a, b in zip(starts, ends) if key[a] != 0]

fig, ax = plt.subplots(figsize=(3.35, 2.25))
for a, b in events:
    ax.axvspan(a, b, color=ATTACK_SHADE, lw=0)
for a, _ in events[1:]:
    ax.axvline(a, color="white", lw=0.8)
ax.plot(h, s, color=SCORE_COLOR, lw=0.4, label="score")
ax.plot(h, df["tau0"], color=RULE_COLOR["frozen"], ls=RULE_LS["frozen"], lw=1.0, label="frozen")
ax.plot(h, df["tau_tracker"], color=RULE_COLOR["tracker"], ls=RULE_LS["tracker"], lw=1.0, label="tracker")
ax.set_yscale("log")
ax.set_xlim(0, h[-1])
ax.set_xlabel("hours")
ax.set_ylabel("D1 score and thresholds")
for i, (a, b) in enumerate(events):
    ax.text((a + b) / 2, 1.0, f"attack {i + 1}" if i == 0 else str(i + 1), transform=ax.get_xaxis_transform(), ha="center", va="bottom", fontsize=6.5)
ax.legend(loc="upper left", ncol=3, handlelength=1.6, columnspacing=1.6, bbox_to_anchor=(0.0, 1.24))
bad = check_layout(fig)
if bad:
    print("overlapping text:", bad)
print(save(fig, "fig6_tep_noise_trace"), "events (h):", [(round(a, 1), round(b, 1)) for a, b in events])
