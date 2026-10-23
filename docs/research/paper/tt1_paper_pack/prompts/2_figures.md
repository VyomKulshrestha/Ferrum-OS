# Prompt 2: make the paper's figures from the CSV files

Paste into Claude Science with this pack's folder open as the project. Each figure keeps its code and
environment, so a reviewer can rerun it.

---

Make five figures for the paper in `manuscript/thresholds_that_travel_draft_v0_1.md`, using only the CSV
files in `figure_data/`. Save each as PDF and SVG in `figures/`, with the plotting code next to it. Use
one colour per threshold rule across every figure, colour-blind safe, and the rule names as written in
the CSVs. Every caption must say whether its data are from a registered study, exploratory development
data or a post-hoc analysis (the `status` column).

1. **Learning regions (schematic, no data).** A vertical score axis with the alarm threshold tau_t and,
   for SPOT, the base level t below it. Mark three regions: above tau_t (exceedances), between t and
   tau_t (the band), and below t. Show which rule families update from which region: tracker and daily
   recalibration from exceedances; SPOT and DSPOT from the band (DSPOT's moving mean also from all
   non-alarm values); frozen and static margin from none; tighten-only moves only downward.
2. **Threshold trajectories on HAI 20.07** (`threshold_trajectories.csv`, dataset `hai-20.07`, stream
   `test1`). x: time in days (t is minutes). y: score_max and the thresholds tau_frozen, tau_tracker,
   tau_daily, tau_spot_mle and tau_dspot, on a log scale. Shade the minutes where attack = 1. Mark each
   attack interval as caught or missed by the tracker (caught if score_max exceeds tau_tracker in any
   minute of the interval). A second panel can zoom to the first two days.
3. **Threshold trajectories on BATADAL** (same file, dataset `batadal`, stream `test_dataset_1`; t is
   15-minute steps). Same layout; days on the x-axis.
4. **Recall against the frozen threshold** (`recall_and_false_alarms_by_rule.csv`, score D1). A forest
   plot of diff_vs_frozen with ci_low and ci_high for daily, tracker, tracker_slow, one_sided:none,
   spot, spot_mle and dspot, grouped by dataset. Registered rows first (hai-20.07, hygrid-ics, voraus-ad,
   batadal), then the exploratory spent HAI releases and post-hoc rows, visibly separated. A vertical
   line at 0.
5. **Attack campaigns** (`attack_campaigns.csv`). Grouped bars of terminal_after next to
   terminal_control for frozen, tracker, spot_mle and dspot under: the E4 pulse campaign (exploratory),
   the score-level frog at 1 h and 24 h (exploratory), and the physical frog (exploratory). Average over
   the three HAI releases and show the per-release values as dots.

Do not invent data, smooth it, or drop rows; if a value is missing, leave a gap and say so in the
caption. Check each figure against its CSV before saving.
