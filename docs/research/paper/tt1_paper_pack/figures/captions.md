# Figures for "Thresholds That Travel" (draft v0.1)

All five figures are drawn only from `figure_data/`, and nothing was recomputed from raw data. Each figure has a PDF
and an SVG next to the script that draws it. To regenerate, run `python -B <script>` from this folder
(matplotlib 3.11, Python 3.11). Each script checks its figure against the CSV before saving and stops with an error if a check fails.

Shared files: `tt1_style.py` holds the palette, line styles, markers and save settings. `trajectories.py` holds the drawing
code used by Figures 2 and 3.

**Colours.** Each threshold rule has one colour in every figure, taken from Paul Tol's "muted" palette, which is
designed to stay distinguishable under colour-vision deficiency. Lines and markers also differ, so colour is never the
only cue. Rule names are written exactly as in the CSVs.

| rule | colour | rule | colour |
|---|---|---|---|
| frozen | #332288 indigo | one_sided:none | #117733 green |
| margin | #DDCC77 sand | spot | #88CCEE cyan |
| daily | #999933 olive | spot_mle | #44AA99 teal |
| tracker | #CC6677 rose | dspot | #AA4499 purple |
| tracker_slow | #882255 wine | score_max (not a rule) | #555555 grey |

---

## Figure 1. Learning regions — `fig1_learning_regions.{pdf,svg}`, script `fig1_learning_regions.py`

**Caption.** Learning regions of the threshold rules (schematic). The vertical axis is the monitor score s_t. The alarm
threshold tau_t and, for SPOT and DSPOT, the base level t below it split the score range into three regions:
exceedances (s_t > tau_t, which raise alarms), the band (t < s_t <= tau_t) and values below t. A filled column segment
marks the region a rule fits its threshold to. Daily recalibration and the trackers (tracker, tracker_slow) learn from
exceedances, so the attacks they are meant to detect raise their thresholds; the tracker also steps down on every
non-exceedance. SPOT (spot, spot_mle) and DSPOT learn from the band. DSPOT's moving mean also absorbs every non-alarm
value (hatched). frozen and the static margin learn from nothing after calibration. The tighten-only rule
(one_sided:none) can only move its threshold downward. Data status: schematic with no data, so the registered /
exploratory / post-hoc label does not apply. The rule behaviour follows the learning-region table in Section 3.

**Checks.** No data. The rule semantics were checked against the Section 3 table of the current draft. No overlapping text.

---

## Figure 2. Threshold trajectories on HAI 20.07 — `fig2_trajectories_hai2007.{pdf,svg}`, script `fig2_trajectories_hai2007.py`

**Caption.** Threshold trajectories on the HAI 20.07 test1 stream, which has one row per minute (4,860 minutes,
3.375 days). The grey trace is score_max, the D1 score. Coloured lines are the thresholds of frozen, tracker, daily,
spot_mle and dspot, on a log scale. Grey shading marks minutes labelled attack = 1. Each marker above the panel is one
attack interval: filled if the tracker caught it (score_max > tau_tracker in at least one minute of the interval),
open if it missed it. test1 holds 28 of HAI 20.07's 38 attacks; the tracker caught 12 and missed 16. The lower panel
zooms to the first two days. Early attacks raise the tracker and daily thresholds far above frozen (tau_0 = 17.26),
and the later attacks arrive under the inflated thresholds. Data status: **post-hoc analysis**. The trajectories were
computed after the registered finals and are ledgered as post-hoc; `threshold_trajectories.csv` has no `status`
column, so this label comes from the pack README. The recomputed calibration threshold equals the registered one
exactly (`trajectory_consistency.json`, relative difference 0). Over test1 and test2 together the traces give frozen
36/38 and tracker 20/38, matching the registered tt1 result, and spot_mle 35/38 and dspot 36/38, matching the post-hoc
file (SPOT and DSPOT were not part of the tt1 registration). test2 (10 attacks) is not drawn. The CSV also holds
tau_tracker_slow, tau_spot and tau_one_sided:none, which are not drawn here. test1 has no missing values.

**Checks (from the script, before saving).** 4,860 rows drawn, out of 4,860 in the CSV for test1. The time index is
contiguous. There are 28 attack intervals, and the tracker caught 12 of them. Totals over both streams: frozen 36/38,
tracker 20/38, spot_mle 35/38, dspot 36/38, equal to the counts recorded in the README. The only overlap the text check
reports is an out-of-range y tick label ("1") in the zoom panel, which is not drawn.

---

## Figure 3. Threshold trajectories on BATADAL — `fig3_trajectories_batadal.{pdf,svg}`, script `fig3_trajectories_batadal.py`

**Caption.** Threshold trajectories on the BATADAL test_dataset_1 stream, which has one row per 15-minute step
(18,433 steps, 192 days). The layout is the same as Figure 2: score_max (D1) in grey, the frozen, tracker, daily,
spot_mle and dspot thresholds on a log scale, shading where attack = 1, and filled or open markers for attack intervals
the tracker caught or missed. test_dataset_1 holds 7 of BATADAL's 14 attacks; the tracker caught 2 and missed 5. The
lower panel zooms to days 68 to 100, which cover the first three attacks, instead of the first two days, because the
first attack starts on day 72. score_max is missing for the first 10 steps (t = 0 to 9, 2.5 h). Those steps are left as
a gap, and the thresholds are drawn there as given. The days-long attacks lift the tracker to about 10^4 and keep
DSPOT's threshold far above tau_0 (9.39), while frozen and spot_mle stay near tau_0. Data status: **post-hoc
analysis** of the tt1b dataset, which was opened once for the registered study. The trajectories were computed after
the registered final; `threshold_trajectories.csv` has no `status` column, so this label comes from the pack README. The
recomputed tau_0 equals the registered value exactly (`trajectory_consistency.json`). Over both test files the traces
give frozen 14/14, tracker 6/14, spot_mle 14/14 and dspot 6/14, the registered tt1b counts. test_dataset_2 (7 attacks)
is not drawn.

**Checks.** 18,433 rows drawn, out of 18,433. The index is contiguous. There are 7 intervals, and the tracker caught 2.
Totals over both files: 14/14, 6/14, 14/14 and 6/14, as recorded. Ten missing score values, at t = 0 to 9. No overlapping text.

---

## Figure 4. Recall against the frozen threshold — `fig4_recall_forest.{pdf,svg}`, script `fig4_recall_forest.py`

**Caption.** Paired difference in event recall between each adaptive rule and the frozen threshold on the D1 score,
with 95% intervals (`diff_vs_frozen`, `ci_low`, `ci_high`). Rules are daily, tracker, tracker_slow, one_sided:none,
spot, spot_mle and dspot, grouped by dataset. Values left of the vertical line at 0 mean lower recall than frozen. The
figure has three blocks, separated by rules and shading, and each row label carries its CSV `status`:
(1) **registered** results from tt1 (hai-20.07, hygrid-ics, voraus-ad) and tt1b (batadal);
(2) **exploratory** development results on the spent HAI releases (hai-21.03, hai-22.04, hai-23.05;
`threshold_transfer_tt1b_dev_v1.json`);
(3) **post-hoc** results on the tt1 datasets, reopened after the finals (`threshold_transfer_tt1b_posthoc_v1.json`).
spot, spot_mle and dspot have no rows for the registered tt1 datasets because those rules were not part of the tt1
registration. The gaps are labelled in the figure, and the post-hoc block supplies those comparisons. In the post-hoc
block, the daily, tracker, tracker_slow and one_sided:none values are identical to the registered values for the same
datasets. The CSV gives no event count for the post-hoc voraus-ad rows; the registered row lists 755 anomalous samples,
and voraus-AD units are samples, not attacks. one_sided:none equals frozen (0 [0, 0]) in every block. The
positive spot and spot_mle values for voraus-ad (post-hoc) are not a gain: with 190 calibration samples SPOT ran at a
per-sample false-positive rate of 0.32 against the 0.05 target, so it is unusable there (draft, Section 7.1).
[Added by the author after review of the figure.]

**Checks.** All 61 D1 rows for these seven rules are drawn, out of 61 in the CSV, and every (dataset, status) block in
the CSV is present. Each plotted point and interval was compared with its CSV row, and every point lies inside its
interval. Gaps: hai-20.07, hygrid-ics and voraus-ad (registered tt1) have no spot, spot_mle or dspot row. No overlapping text.

---

## Figure 5. Attack campaigns — `fig5_attack_campaigns.{pdf,svg}`, script `fig5_attack_campaigns.py`

**Caption.** Terminal attacks caught after each campaign (solid bars) and in the matching control without the campaign
(hatched bars), for frozen, tracker, spot_mle and dspot. Each bar is the mean over the three spent HAI releases
(hai-21.03, hai-22.04, hai-23.05), and the dots are the per-release values. Every release had the same number of
placements, so the mean equals the pooled fraction. Panels: the supra-threshold pulse campaign (E4; 10 placements per
release); the score-level closed-loop frog with 1 h and 24 h campaigns (10 placements per release); and the physical
frog, which spoofs noise on three sensors for 6 h (4 placements per release). Data status: all four panels are
**exploratory** results on the normal data of the spent releases (`status` = "exploratory (normal data)"; sources
`threshold_transfer_dev_v3.json` and `threshold_transfer_tt1b_attacks_dev_v1.json` for E4,
`threshold_transfer_tt1b_frog_dev_v1.json` for the score-level frog, and `threshold_transfer_tt1b_physfrog_dev_v1.json`
for the physical frog). The CSV has no spot_mle row for E4 and no tracker row for the physical frog. Both slots are
left empty and labelled "no row in CSV". The CSV also holds rows not drawn here because they have a different status
or campaign and are not averaged with these: the registered HAI 20.07 pulse rows (G1), the registered BATADAL frog
rows (tt1b), and the 6 h and fixed-level frogs. Pooled counts, after / control: E4: frozen 30/30 / 30/30,
tracker 1/30 / 23/30, dspot 23/30 / 25/30. Frog 1 h: frozen 30/30 / 30/30, tracker 20/30 / 20/30,
spot_mle 13/30 / 30/30, dspot 0/30 / 24/30. Frog 24 h: frozen 30/30 / 30/30, tracker 20/30 / 20/30,
spot_mle 8/30 / 30/30, dspot 0/30 / 24/30. Physical frog: frozen 12/12 / 12/12, spot_mle 4/12 / 12/12,
dspot 9/12 / 9/12.

**Checks.** For each campaign and rule, all three releases are present and none is duplicated, and the number of
placements is the same in every release. No value in the drawn cells is missing. The pooled counts above match
Sections 7.4 and 7.5 of the current draft. Gaps: E4 has no spot_mle row, and the physical frog has no tracker row. No
overlapping text.

---

## Notes for the draft (proposals only; the draft was not edited)

- The README says the traces "reproduce the registered event counts" for MLE SPOT 35/38 and DSPOT 36/38 on HAI 20.07.
  SPOT and DSPOT were not registered in tt1, so those two counts match the post-hoc file, not a registered result. The
  Figure 2 caption says so.
- `threshold_trajectories.csv` has no `status` column. The post-hoc label for Figures 2 and 3 comes from the README.
  Adding the column would make the CSV self-describing.
