# tt1c development plan: stronger adaptive baselines and canonical SPOT (exploratory)

Written 2026-11-01, before any run, in answer to the Claude Science mock PC review
(`docs/research/paper/tt1_paper_pack/review/mock_pc_review.md`, Part 4b items 1, 2, 5). Status:
**exploratory development on spent data, not registered.** The data are the three spent HAI releases
(21.03, 22.04, 23.05): their normal training data, and their attack test files, which earlier
development already opened. No registered dataset (HAI 20.07, HyGrid-ICS, voraus-AD, BATADAL) is
touched. Every access goes through the ledgered loaders with the reason "EXPLORATORY tt1c development".

Question: does natural poisoning (Section 6/7 of the paper) survive adaptive thresholds that are built
not to learn from events, and does the closed-loop frog survive a canonical SPOT?

## Score and splits

D1 only (the world-model residual, 60 s smoothing, calibrated to 2 false-alarm episodes per day), fitted
exactly as in the existing harnesses:

- natural poisoning on the attack test files: the tt1-final split (fit 60 / scale 20 / calibration 20 %
  of normal data), as `scripts/tt1b_dev.py`;
- pulse (E4) and closed-loop frog campaigns on normal data: the development round r4 split (fit 50 /
  scale 15 / calibration 10 / pseudo-deployment 25 %), as `scripts/tt1b_attacks_dev.py` and
  `scripts/tt1b_frog_dev.py`, with their placement counts and seeds (10 placements, seed 7).

## New rules (fixed here; `scripts/threshold_rules_tt1c.py`)

Notation as in the paper: tau0 calibrated threshold, p calibration exceedance rate, eta = 0.01 x spread.
An *event episode* is an alarm episode (alarms merged across the 60 s gap) that has lasted at least
L = 60 s; the *hold-off* is H = 3600 s after an event episode ends.

| Rule | Definition |
|---|---|
| `daily_excl` | Daily recalibration at the (1 - p) quantile of the previous day, leaving out every sample inside an event episode (under the rule's own threshold) and in the hold-off after it. A day with fewer than 1/p kept samples keeps the previous threshold. |
| `tracker_hold` | The registered tracker (eta, p), but upward steps are skipped while the current alarm episode has lasted at least L, and during the hold-off after it. Downward steps continue. |
| `tracker_capped` | Tracker with eta = 0.01 tau0 per step, and the threshold may not rise more than 0.1 tau0 above its value at the start of the current day (day boundaries from the stream start). |
| `ndt` | Telemanom's nonparametric dynamic threshold (Hundman et al. 2018), made causal: every 70 steps the threshold is recomputed from the trailing 2,100 scores (30 windows of 70, the paper's defaults) as mean + z x sd, z in {2.5, 3.0, ..., 11.5}, choosing the z that maximises (dmean/mean + dsd/sd) / (n_anom + n_seq^2) subject to n_seq <= 5 and n_anom < half the window; z = 12 when no z qualifies. Initialised on the last 2,100 calibration scores. Anomalous indices are grouped into sequences without Telemanom's error buffer, and the anomaly-pruning step (which removes flagged sequences, not threshold values) is not used. |
| `spot_gr` | SPOT (level 0.98, q = p) with the GPD fitted by maximum likelihood (profile likelihood in theta = xi/sigma, the procedure of Grimshaw that Siffer et al. use), refitted at every new peak while there are fewer than 100 peaks and afterwards whenever the peak count has grown by 1%; z_q is recomputed at every step from the last fit and the current counts. (Refitting at literally every peak costs hours per frog run, where a peak arrives every second.) |
| `spot_gr_bounded` | `spot_gr` with the shape restricted to -0.5 <= xi <= 0.5. |
| `spot_gr_declust` | `spot_gr` with runs declustering (run length 60 steps): the GPD is fitted to cluster maxima and the tail probability uses the number of clusters, the return-level form of Coles (2001, Sec. 5.3). Values above z_q are not learned, as in SPOT. |
| `dspot_gr` | DSPOT (depth 3,600 steps) with the `spot_gr` tail. |

Reference rules rerun alongside: `frozen`, `tracker`, `daily`, `spot` (moments), `spot_mle` (refit every
2,048 peaks), `dspot` (moments).

## Experiments and outputs

1. **Natural poisoning** (attack test files): every rule; event recall (any alarm inside the event),
   onset recall (an alarm episode starts inside it), paired bootstrap against frozen for both, false-alarm
   episodes per day, share of unlabelled time in alarm, median threshold over tau0 at onsets, and each
   rule's threshold over tau0 at the start of the stream.
2. **E4 pulse campaign** (normal data): frozen, tracker, daily, daily_excl, tracker_hold, tracker_capped,
   ndt, spot_gr, spot_gr_declust; terminal step caught after the campaign and in the control.
3. **Closed-loop frog** (normal data): the 24 h and 1 h campaigns of `tt1b_frog_dev.py`, plus a 24 h
   *burst* variant that holds the score at 0.97 tau_t for 60 s and then leaves it clean for 120 s, so that
   runs declustering sees one cluster per burst instead of one cluster for the whole campaign. Rules:
   frozen, spot_mle, spot_gr, spot_gr_bounded, spot_gr_declust, dspot_gr, ndt, daily_excl, tracker_hold,
   tracker_capped; terminal caught after / control, threshold over tau0 at the terminal step, alarm steps
   during the campaign.

Output: `docs/research/threshold_transfer_tt1c_dev_v1.json` (per release and pooled), script
`scripts/tt1c_baselines_dev.py`. Whatever the results, they go into the paper as exploratory, next to
the rules they extend.

## What would change the paper

- If `daily_excl`, `tracker_hold`, `tracker_capped` or `ndt` keep frozen recall on the spent attack files
  and resist the pulses, natural poisoning is a property of naive adaptive rules, and the paper says so.
- If the canonical SPOT variants resist the frog, the silent-poisoning claim is restricted to the
  estimators that showed it.
