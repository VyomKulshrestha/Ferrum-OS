# Mock program-committee review, round 2: ACM ASIA CCS 2027 (second cycle)

**Submission:** *Thresholds That Travel: Adaptive Alarm Thresholds Let Attacks Through in ICS Anomaly Detection* (anonymous).
**Reviewed version:** `latex/main.tex` sha256 prefix `21484506f481` (2026-11-10 18:14 +05:30) and `latex/main.pdf` prefix `03e04d36926c`, 19 pages. The body ends at the foot of page 12, where the references begin; appendices A to E run from page 14 to page 19.
**Instructions carried out:** `prompts/6_mock_pc_review_round2.md`. This file is the only one written.

## How this review was produced (read first)

- **One session, three readings.** All three reviews were written in one reviewer session, each from its stated expertise, on one shared evidence audit. Round 1 used three separate sessions. Agreement between R1, R2 and R3 below is therefore weaker evidence than agreement between separate reviewers.
- **What was read.** `main.tex` in full, appendices included. The PDF could not be rendered as images in this environment, so page, section and table numbers come from text extraction of `main.pdf`, and the five figures were not inspected visually.
- **Evidence checks.** Reads of stored fields in `results/` and `protocols/`, plus arithmetic on stored per-run records. A value marked **[derived]** is my arithmetic, with the fields named. No experiment was run, no raw data was read, and no network was used.
- **Not verified.** The anonymized artifact link and its contents; the CFP page limits (`latex/README.md` says 12 body pages plus up to 10); every citation, including the 2026 preprints and the claim about the Sherlock authors' recommendation; the git history that the verifiers read. Numbers from development rounds r1 to r4 in Appendix D and the HyGrid-ICS contamination figures in Section 9 were not rechecked in this round.
- **Round 1 files** (`mock_pc_review.md`, `mock_pc_response.md`) were read after the reviews were drafted and are used only in Part 3.
- **Status tags:** [reg tt1], [reg tt1b], [reg tt1d] for registered hypotheses; [reg-sec] for registered secondary outcomes; [expl] for exploratory runs on the spent HAI releases; [post-hoc] for analyses after a registered final.
- **Section numbers** follow the PDF: 1 Introduction, 2 Background, 3 Threat model (3.1 memory), 4 Monitor, rules and data, 5 Registered results (5.1 to 5.4), 6 Registered replications (6.1 BATADAL, 6.2 and 6.3 Tennessee Eastman, 6.4 ProvICS), 7 Learning regions under attack (7.1 to 7.7), 8 Design guidance, 9 Limitations, 10 Conclusion. Line numbers refer to `main.tex`.

**Scores:** R1 2 (weak reject), confidence 4. R2 3 (weak accept, low end), confidence 4. R3 2 (weak reject), confidence 3.
**Meta-review decision: major revision.** If the second cycle offers no further revision round, the equivalent is reject with encouragement to resubmit.

## Decision at a glance

- The number trace is clean. Of more than 300 values checked against `results/`, two are wrong and both are small (Part 2, M1 and M2). The paper's problem is what the numbers are made to say.
- Four dataset-level primary rules were registered across the three studies. One passed (HAI 20.07). Three failed (BATADAL, Tennessee Eastman, ProvICS). The title and the first results sentence of the abstract state the hypothesis as established.
- The Tennessee Eastman result, the largest registered sample, is narrower than the abstract says. All 38 lost "attacks" are later phases of one continuous noise-attack sequence, each starting within one 3.6 s step of the phase before it, after a first phase with a median length of 25 hours [derived]. The tracker alarmed at the start of every one of those sequences.
- Under the stricter onset count the tracker's loss holds on BATADAL only: 14 attacks, post-hoc, with a tracker step of 6.9 τ0 per sample. The paper holds a fourth onset result in its favour and does not report it: on the 160 development events the loss is −0.30 under both counts [expl].
- Every registered poisoning campaign is an edit of the score stream by an attacker who, in two of the three campaigns, reads the live threshold. The abstract and the conclusion do not say so.
- Two stronger adaptive rules were not poisoned by real attacks on Tennessee Eastman (registered H2 passed). Natural poisoning is therefore shown for the plain tracker and plain daily recalibration only, which the title and the first introduction bullet do not reflect.
- The design guidance rests on two one-line propositions. Where the monitor lost its calibration (ProvICS), the recommended rules ran at 25 to 33 times the alarm budget and the rule the paper warns against ran at 6.5 with the same recall [reg-sec].
- Most of what is needed is rewriting plus four exploratory analyses on data already read (Part 5).

---

## Part 1. The three reviews

### R1: ICS security researcher (SWaT, WADI, HAI and Tennessee Eastman detectors and attacks)

**Summary.** The paper studies the rule that turns an anomaly score into alarms. It argues that rules which raise their own threshold (online quantile tracker, daily recalibration, SPOT and DSPOT) lose attacks because earlier exceedances inflate them, and that they can be poisoned deliberately. Evidence comes from three registered studies on HAI 20.07, HyGrid-ICS, voraus-AD, BATADAL, the Kaspersky Tennessee Eastman attack set and ProvICS, plus exploratory work on three earlier HAI releases. It recommends thresholds that tighten automatically and loosen only under a ceiling or with approval.

**Strengths.**
1. The threshold layer is neglected in ICS detection work, where a single threshold tuned on test labels is still common. A paper about it is welcome.
2. One-access discipline with a ledger and hash-frozen code is rare in this literature, and the paper reports results that hurt it (three failed primary rules, the ProvICS null).
3. The split of Tennessee Eastman events into first attacks and followers is a clean test of the mechanism under the any-alarm count: 116 against 116 on first events, 66 against 104 on followers [reg tt1d].
4. Stronger adaptive rules and a standard maximum-likelihood SPOT were added and registered, which answers the main baseline objection of round 1.
5. The BATADAL explanation is now correct: the moments-based rules started at 46 to 49 τ0 before any attack.

**Weaknesses.**

*W1. The Tennessee Eastman "attacks that follow attacks" are consecutive phases of one attack sequence, and the loss sits in one of four attack families.* Status: **confirmed; partly disclosed in the body, absent from the abstract and introduction.**
Evidence, from `results/threshold_transfer_tt1d_result_tep59.json`:
- `real_events.D1.rules.tracker.by_type`: type 24 (noise) 57 of 95 against 95 for frozen; types 21, 22 and 23 have the same totals as frozen (34, 63, 28).
- **[derived]** from `units[*].attack_runs[*].events` and `.scores.D1.{frozen,tracker}.{found,onset,inflation}`: noise-attack followers number 59; frozen detects 59 under the any-alarm count and 6 under the onset count; the tracker 21 and 1. Denial-of-service followers number 45; frozen 45, tracker 45. All 38 discordant followers are noise attacks.
- **[derived]** every follower begins 0 or 1 step after the previous event ends (31 and 73 of 104). The first noise attack of a run lasts a median 25,091 steps (25.1 h). The tracker stood at a median 82 τ0 (maximum 151) at the onset of noise followers and at a median 1.07 τ0 at denial-of-service followers.
- The tracker detected all 36 first noise attacks.

Read operationally: a noise attack drives the score far above τ0 for about a day, the tracker climbs to it, and when the attack changes form the tracker is silent while the frozen threshold has never left alarm. That is a real hazard (a tracker normalises a sustained attack). It is a different claim from "lost attacks that a frozen threshold caught". The operator with the tracker received an alarm at the start of each of these sequences. Section 6.2 gives "57 of 95 events against 95" and "every follower begins within one step", but the abstract, introduction bullet 1, contribution 2 and the conclusion give only "66 of the 104 attacks that follow another attack".

*W2. On HAI 20.07 the detector is not working, so the headline comparison is of who stays in alarm longest.* Status: **confirmed; answered in Sections 5.2 and 9, not in the abstract.** The frozen threshold was in alarm for 39% of the unlabelled time (`threshold_transfer_tt1_posthoc_alarm_time.json → hai-20.07.baseline.rules.frozen.unlabelled_alarm_share` = 0.391). The score sits above τ0 from the first sample (`figure_data/threshold_trajectories.csv`, test1 row 0: 71.7 against τ0 = 17.26). Under the onset count the tracker's gap is −0.16 [−0.37, 0.05]. The abstract still opens its results with "20 of HAI 20.07's 38 against 36".

*W3. The one onset-stable result, BATADAL, has an unremoved confound.* Status: **confirmed; not answered.** The registered tracker step there is 6.9 τ0 per 15-minute sample (`scores.D1.thresholds.eta` 64.62, `tau0` 9.39), because the step is 1% of a spread that a heavy tail sets at 6,462. In test file 1 the tracker stood at 3.69 τ0 before the first attack [derived from the trajectory CSV, row 6908]. tt1d registered a tracker with η = 0.01 τ0 on Tennessee Eastman, which answers the step-size question there (55 of 104 followers), but BATADAL was not rerun. The full 15-minute score trace of both BATADAL test files is in `figure_data/threshold_trajectories.csv`, so the rerun needs no new access.

*W4. The "false alarms" that adaptation removed on ProvICS may be attack aftermath.* Status: **confirmed as an open reading; not discussed.** Section 6.4 says "The monitor did not hold its calibration on this recording". On the 13 h of sealed attack-free rows of the same twin the frozen threshold ran at 0.92 times its budget with an alarm share of 0.01% (`threshold_transfer_tt1d_result_provics.json → campaigns.attack_free.rules.frozen`). On the attack recording it ran at 33 times the budget and was in alarm for 44% of the time outside the labels. Labels cover about 10% of the recording and end 60 s after each ground-truth row. A monitor that holds its budget on attack-free data and alarms for 44% of an attack recording is more plausibly seeing disturbance the labels do not cover than losing calibration. If so, "adaptation cost no recall and removed false alarms" should read "adaptation silenced alarms on a disturbed plant".

*W5. Registered poisoning is done to the score. No registered result shows a process-level attacker achieving it.* Status: **confirmed; disclosed in Sections 3 and 9 and in the protocol, not in the abstract or conclusion.** The only physical version is exploratory, on HAI, with 12 placements and an attacker who runs the monitor: maximum-likelihood SPOT 4 of 12 against 12, DSPOT unchanged (9 against 9), not silent on HAI 23.05 (frozen raised a median 190 alarm steps). There is no impact measure. Work on stealthy attacks in this field (the paper cites Urbina et al.) reports how far the process can be pushed while undetected. Here the unit is a score bump of 1.05 to 1.5 τ0 for 600 s, with no mapping to a process deviation.

*W6. The loud campaign hides less than its own pulses, and the paper omits the registered magnitude that shows it.* Status: **confirmed; not answered.** The protocol registers terminal magnitudes {1.05, 1.25, 1.5, 2} τ0 and commits to "Every campaign rule at every terminal magnitude". Table 9 prints three. At 2 τ0 the tracker caught 56 of 56 after the loud pulses (`campaigns.attacks.loud.tracker.after[3]` = 1.0): the pulses are 2 τ0 high and the tracker's median level after the campaign is 1.99 τ0. An attacker who can already produce twelve unanswered 2 τ0 excursions a day gains cover only for weaker events.

*W7. One home-grown monitor, and the PCA score disagrees.* Status: **confirmed; partly answered (D0 and D2 added), heading contradicts the result.** With D2 on Tennessee Eastman the tracker shows no follower loss ([−0.11, +0.03]) and catches 134 first events against 79, at 33 times the budget [reg-sec]. Section 7.2 is titled "The effect does not depend on the score". No published detector (autoencoder, LSTM, graph model) is run.

*W8. No evidence that the plain tracker is deployed in ICS monitoring.* Status: **confirmed; not answered.** The abstract says "deployments often let it adapt: they recalibrate it daily, track a running quantile, or refit an extreme-value tail". The citations are to method papers. SPOT, DSPOT and Telemanom's threshold have ICS and telemetry users; a fixed-step conformal tracker as an alarm threshold is, as far as I know, the authors' construction.

*W9. The frozen threshold "travels" only where nothing changes.* Status: **confirmed; partly answered in Section 8.** The 0.98 times budget over 280 days comes from simulator runs in the same seven modes as calibration. On the three recordings with any shift, the frozen threshold ran at 39% alarm time (HAI 20.07), 19.2 episodes a day against 2 (HyGrid-ICS) and 33 times the budget (ProvICS).

*W10. SWaT and WADI are still absent.* Status: **answered as far as it can be** (Section 6.1: requested 2026-10-23, registered under tt1b, not received).

**Questions for the authors.**
1. For the 59 noise-attack followers, how long before each follower had the tracker last alarmed, and would an operator who answered the first alarm have seen the plant return to normal in between?
2. On ProvICS, where in the attack recording does the frozen threshold's unlabelled alarm time fall relative to the four campaigns?
3. What does a 1.25 τ0 bump for 600 s correspond to in process units on Tennessee Eastman and on HAI?
4. Does the BATADAL tracker loss survive η = 0.01 τ0, and do the excluding and capped rules hold there as they did on Tennessee Eastman?
5. Which fielded ICS monitoring products or published deployments use a fixed-step quantile tracker or unbounded daily recalibration as the alarm threshold?
6. One of the 142 attack runs has no event (141 first events). Which run, and why?

**Score: 2 (weak reject). Confidence: 4.** I would move to 3 if W1 and W5 are stated in the abstract, the BATADAL rerun is done, and at least the sub-event pulses and the frog are realised through spoofed sensors on HAI normal data with more than 12 placements.

---

### R2: statistician (streaming anomaly detection, extreme-value theory, conformal prediction, pre-registration)

**Summary.** Three registered studies compare threshold rules by event recall against a frozen threshold with paired bootstrap intervals, and test three score-level poisoning campaigns on sealed attack-free runs. Four propositions describe tracker memory, daily memory, and the any-alarm guarantee of a tighten-only or ceiling rule.

**Strengths.**
1. Complete reporting. I traced Tables 3 to 10 and 17 and the Section 6 text to the result files and found two small errors (Part 2).
2. Failed primary rules are named in the abstract (one), contribution 1 and the first limitation.
3. Whole runs are resampled on Tennessee Eastman, discordant counts are given, and the degenerate [0, 0] interval of H2 in tt1b is called uninformative with an exact bound.
4. Proposition 1 is correct and useful: recovery takes (1 − p)/p quiet steps per exceedance step, independent of η. The credit to Gibbs and Candès and to Atarmla is fair.
5. The H1b result is reported as a failure although its upper bound is exactly 0.

**Weaknesses.**

*W1. The headline leads with component hypotheses that passed while three of four primary rules failed.* Status: **confirmed.** `gates.primary_success`: true for HAI 20.07, false for BATADAL, false for Tennessee Eastman, false for ProvICS. The one pass includes G1, which the paper itself calls uninformative, and G3, met at 2.23 against a pass band of 4 and a budget of 2. In a registered study the primary outcome goes first. The title asserts the hypothesis, the first results sentence of the abstract lists three passing components, and the failures arrive four sentences later, one of the three by name. This is the selective emphasis that registration exists to prevent. It is disclosed, which is why my score is not lower.

*W2. The any-alarm endpoint measures alarm persistence, and the paper's own registration said so.* Status: **confirmed; answered in part.** The tt1d protocol lists in advance: "a follower begins inside the alarm of the attack before it; the onset count then credits no rule, and H1b can fail for that reason alone." H1b failed: 37 against 44, −0.07 [−0.13, 0.00], discordant 10 to 3 (`real_events.D1.rules.tracker.follower.vs_frozen_onset`), exact two-sided p = 0.09 [derived]. The any-alarm effect is carried by one stratum (R1 W1). An effect that exists in one of four attack families is a stratum effect and should be estimated and reported as one.

*W3. The paper omits an onset result that supports it.* Status: **confirmed.** `threshold_transfer_tt1c_dev_v1.json → natural_pooled.tracker.vs_frozen_onset`: −0.300 [−0.369, −0.231]; frozen 124 of 160 at onset, tracker 76. The frozen threshold was in alarm for 0.3% to 0.8% of unlabelled time on those releases, so the two counts agree there. This is exploratory and on the development testbed, but it is 160 events against BATADAL's 14, and Section 9 says the loss "survives the onset count on BATADAL only".

*W4. Rules are compared at different realised alarm rates.* Status: **confirmed; asked for in round 1, not done.** On the sealed Tennessee Eastman runs tighten-only ran at 1.57 times the budget and the capped tracker at 2.12; they caught 122 and 130 first events against 116 for frozen at 0.98 [reg-sec]. Whether that gain exceeds what a frozen threshold calibrated to 1.57 or 2.12 times the budget would catch is unknown, because no static threshold below τ0 was run. The claim that tightening "can only add sensitivity in quiet periods" needs that comparison. The same gap affects HAI 20.07 in the other direction: tracker 0.2% alarm time against 39%.

*W5. The registered campaign hypotheses carry little risk.* Status: **confirmed.** H5 is arithmetic: 12 pulses of 33 steps give 396 exceedance steps, each worth η(1 − p). With η = 0.006 τ0 that is up to 2.4 τ0 of rise, so the tracker reaches the 2 τ0 pulse height and stops there (median level after the campaign 1.99 τ0). The rehearsal on development runs had already shown tracker 0 of 14 and SPOT 4 of 14 at 1.25 τ0 (protocol, `rehearsal.tep59`). The sealed runs supply background noise. These are confirmations of the update rules under realistic noise. They are worth reporting, but "registered" adds less to them than to H1. ProvICS P4 failing (SPOT rose 0.6% in 6 h) shows the frog is not automatic, and that null deserves more than one clause.

*W6. Nobody outside the authors can check that registration came first, and the margins are seconds.* Status: **confirmed from the verifier files; disclosed in the Open science appendix.** `threshold_transfer_tt1d_verification_tep59.json`: registration commit 16:24:27 +05:30, first access 10:54:55 UTC, 28 s later. ProvICS: 34 s. The amendment commit (16:27:15 +05:30) precedes the amended attempt by 17 s and follows the start of the failed attempt by 2 min 13 s. The commit times are the authors' own git metadata and the anonymized artifact withholds the history. I have no reason to doubt the order. A registration that is committed and executed by one pipeline within half a minute is a frozen analysis plan, which has value, but it has never been exposed to a third party before the data were read. Say so, and deposit future registrations with an external timestamp.

*W7. The SPOT runaway is reported as a count, without diagnosis.* Status: **confirmed.** `campaigns.attacks.frog.spot_gr`: median inflation 1.75, maximum 1.5 × 10²¹. **[derived]** from per-placement `inflation`: 23 of 56 placements end above 10 τ0 and the rest between 1.19 and 2. A bimodal outcome with values of 10²¹ points to a degenerate tail fit on a stream held at a fixed fraction of the quantile. The exploratory bounded-shape variant (|ξ| ≤ 0.5) was also blinded on HAI, which helps, but it was not registered on Tennessee Eastman, and the paper never says whether its SPOT (`spot_gr`) reproduces the reference implementation on a benchmark stream.

*W8. Small inferential points.* Status: **confirmed; minor.** Twenty-one registered tests across the three studies (three of them descriptive on ProvICS), no multiplicity control (registered as such). H3 and P3 are implementation checks that hold by construction and are counted among hypotheses that "passed". P2 passes because the two rules detect identical sets. The slow tracker lost first events (110 against 116, [−0.08, −0.01]) and that is in Table 8 but not in the text that says the loss "falls on attacks that follow attacks and not on the first attack".

*W9. Fixed-step tracking is one member of a family.* Status: **not answered; from my own knowledge, not checked.** Online conformal methods with decaying or adaptive step sizes and with integral terms exist. Proposition 1 covers the fixed step only.

**Questions for the authors.**
1. What is the tracker-against-frozen difference on Tennessee Eastman followers within each attack type, with run-level intervals?
2. What recall does a static threshold reach when set to give 1.57 and 2.12 times the budget on the sealed runs?
3. In the 23 frog placements where SPOT ended above 10 τ0, what were ξ and the number of peaks at the last refit?
4. Will you give the PC chairs access to the commit history?

**Score: 3 (weak accept, low end). Confidence: 4.** The inference is reported more completely than in any ICS detection paper I know, and every objection above can be met by rewording or by analysis of data already read. If the title and the first results sentence stay as they are, my score is 2.

---

### R3: systems-security generalist (threat models, baselines, claims against evidence)

**Summary.** As above. I read for whether each claim in the abstract, introduction and conclusion follows from a result of matching status, whether the attacker is someone a defender should plan for, and whether the paper fits its space.

**Strengths.**
1. Every table carries a data-status label, and the text tags most numbers as registered, post-hoc or exploratory.
2. The baseline objection of round 1 is met: excluding recalibration, hold-off, capped rise, Telemanom, standard SPOT with bounded shape and declustering.
3. The paper states what failed, including an approval gate that the authors might have hoped would work.
4. Propositions 3 and 4 are stated with their scope (any-alarm count, no permit).

**Weaknesses.**

*W1. The registered campaigns assume an attacker who writes the anomaly score, and two of three also read the live threshold.* Status: **confirmed; disclosed in Section 3, the protocol and Section 9; missing from the abstract, introduction bullets 2 to 4, contribution 3 and the conclusion.** Protocol, `frozen_components.campaigns`: "Frog: the attacker sets s_t = max(s_t, 0.97 x the deployed threshold) ... Sub-event pulses: s_t = max(s_t, 2 tau_t)". An attacker with that access to the monitor could suppress alarms directly. The paper's answer (Section 3, "Why poison rather than conceal") is an argument, followed by "We did not compare the two strategies". Round 1 asked for that comparison.

*W2. The paper never states per campaign what the attacker needs and what the operator sees.* Status: **confirmed.** The numbers exist in the result file and are not in the paper:
- Loud pulses: 12 alarm episodes in the campaign day under the tracker (`campaigns.attacks.loud.tracker.median_alarm_episodes` = 12.0), six times the budget of 2. Hides bumps up to 1.5 τ0; none at 2 τ0.
- Sub-event pulses: 48 alarm episodes in the day under every rule (`campaigns.attacks.subl.daily_excl.median_alarm_episodes` = 48.0), 24 times the budget. The introduction calls this being poisoned "below their notice". It is below the rule's event definition and well above an operator's notice.
- Frog: no alarm in 51 of 56 placements; needs the SPOT level at every 3.6 s step and control of a 60 s smoothed top-3 residual statistic to within 3% for 24 hours.

*W3. The abstract and introduction overclaim in specific sentences.* Status: **confirmed.** Listed with quotations in Part 2, table O.

*W4. Natural poisoning is now a property of two plain rules, and the framing has not caught up.* Status: **confirmed; answered in Sections 7.6 and 8, contradicted in the title and introduction.** Registered H2 passed: excluding recalibration and the capped tracker each caught 104 of 104 followers, and 113 and 130 first events against 116. Introduction bullet 1 still reads "Rules that learn from exceedances are poisoned by real attacks", and a capped tracker learns from exceedances.

*W5. The design guidance is two theorems, a cost, and two untested recommendations.* Status: **partly answered.**
- Recommendations 1 and 2 follow from Propositions 3 and 4. Their measured costs are given (1.57 and 1.30 against 0.98 on Tennessee Eastman, 2.43 against 0.70 on BATADAL).
- A ceiling guarantees the recall of the static threshold κτ0 and no more. On Tennessee Eastman that is 80 of 141 first events at κ = 1.1 against 116 for frozen, and 71 at κ = 1.25 (`real_events.D1.rules.static_1.1.first.detected`, [−0.33, −0.18]) [reg-sec]. Section 8 quotes the development figure ("cost no recall on the recorded attacks") and the registered floor appears only in Appendix E.
- On ProvICS tighten-only ran at 33.0 times the budget, the tracker under a 1.25 ceiling at 25.2, and the unconstrained tracker at 6.5, all with the same 25 events [reg-sec]. Section 8 gives one sentence to this.
- Recommendation 3 (operator approval "from the process, not from the alarm log") has no evidence. The only gate tested let the frog through (1 of 56 with a 6 h review) [reg-sec].
- Recommendation 4 (offline recalibration on verified clean data) is not tested, and no dataset here has labelled benign drift, so the cost of refusing to loosen under real drift is unmeasured.
Contribution 4 calls this "A design rule, supported by these results".

*W6. Too much for 12 pages.* Status: **confirmed.** The body holds three studies, six fresh datasets and three development releases, twenty rules, three scores, three campaign families in registered and exploratory versions, four propositions, ten tables and three figures in about 10,500 source words, and uses six evidence classes (registered primary, registered hypothesis, registered secondary, descriptive, post-hoc, exploratory). Section 7 repeats on HAI, as exploratory, what Section 6.3 now shows registered. Tables 8 and 9 mix cells that test a hypothesis with secondary cells under one "registered" label. A reader cannot find the tested cell for H4, H5 or H6 without the protocol.

*W7. Novelty is modest.* Status: **partly answered in Sections 2 and 8.** Poisoning of self-updating detectors, bounded false-positive rates as a limit on poisoning, and management of change for alarm settings are prior work, and the paper says so. What is new is the measurement.

*W8. Submission points.* Status: **not verified.** (i) `publish/README.md` says the anonymized artifact "must be pushed ... and refreshed on anonymous.4open.science before submission"; I could not check that it contains tt1d. (ii) The same file records a named preprint under this title on Zenodo since 2026-11-07; check the CFP's rule on preprints. (iii) The abstract is 411 words with 31 numbers.

**Questions for the authors.**
1. For each campaign: what must the attacker read, what must it write, for how long, and how many alarms does each rule raise meanwhile?
2. Why is the score-level frog "an upper bound" when its physical version changed DSPOT not at all?
3. If excluding recalibration and a capped tracker resist real attacks, what is the practical case against them, other than a closed-loop attacker with access to the monitor?
4. What would you tell an operator on ProvICS, where the frozen threshold was in alarm for 44% of the time?

**Score: 2 (weak reject). Confidence: 3.** I would move to 3 with the abstract and introduction corrected as in table O, an attacker-requirements table, and Section 7 reduced to what Section 6 does not already show.

---

## Part 2. Evidence audit

### Claims checked

| # | Claim or weakness | Check (file → field) | Verdict |
|---|---|---|---|
| E1 | One of four dataset-level primary rules passed | `tt1_result_hai-20.07.json → gates.primary_success` true; `tt1b_result_batadal.json → gates.primary_success` false; `tt1d_result_tep59.json` and `tt1d_result_provics.json → gates.primary_success` false | Confirmed. Section 9 says three failed; no sentence says one of four passed |
| E2 | Tennessee Eastman loss is confined to noise-attack followers | `tt1d_result_tep59.json → real_events.D1.rules.{frozen,tracker}.by_type`; per-run `units[*].attack_runs[*]` | Confirmed. Noise followers: frozen 59 any-alarm, 6 onset; tracker 21, 1. Denial-of-service followers: 45 and 45 [derived] |
| E3 | Followers are contiguous with the previous event | per-run `events` | Confirmed. Gap 0 steps for 31 followers, 1 step for 73 [derived]. Section 6.2 says "within one step" |
| E4 | H1b: −0.07 [−0.13, 0.00] | `real_events.D1.rules.tracker.follower.vs_frozen_onset` −0.0673 [−0.132, 0.0], discordant 10 and 3 | Matches |
| E5 | Development-release onset count not reported | `tt1c_dev_v1.json → natural_pooled.tracker.vs_frozen_onset` −0.300 [−0.369, −0.231]; frozen `onset_detected` 124, tracker 76; same in `tt1e_dev_v1.json` | Confirmed. No occurrence of these values in `main.tex` |
| E6 | Registered campaign magnitude 2 τ0 not reported | Protocol `frozen_components.campaigns` and `secondary[3]`; `campaigns.attacks.*.*.after[3]` | Confirmed. Loud: tracker 56 of 56, hold-off 56, daily 0. Sub-event: tracker 0, hold-off 0, daily 19, excluding 29. Frog: SPOT 32, 6 h gate 40, daily gate 56 |
| E7 | Alarms raised during campaigns | `campaigns.attacks.{loud,subl}.*.median_alarm_episodes` | Loud 12 (tracker) and 13 (frozen); sub-event 48 (49 frozen). Not in the paper |
| E8 | "none in 51 of the 56 registered placements" | per-placement `frog.spot_gr.alarm_steps` | Matches [derived] |
| E9 | "in 4 of the 56 placements an alarm episode of the excluding rule still reached event length" | per-placement `subl.daily_excl.longest_episode` ≥ 17 | Matches [derived] |
| E10 | SPOT inflation under the frog is bimodal | `campaigns.attacks.frog.spot_gr.{median,max}_inflation` 1.75 and 1.5 × 10²¹; per-placement values | Confirmed. 23 of 56 above 10 τ0, 40 above 1.25 τ0 [derived] |
| E11 | Static floor under a ceiling on Tennessee Eastman | `real_events.D1.rules.static_{1.1,1.25,1.5}.first.detected` 80, 71, 71 against 116 | Confirmed. In Appendix E only |
| E12 | ProvICS false alarms of the recommended rules | `real_events.D1.rules.{tighten_only,tracker_ceil_1.25,tracker_ceil_1.5,tracker}.fa_ratio_to_budget` 33.0, 25.2, 11.0, 6.5 | Confirmed. Tighten-only and ceiling values in Appendix E only |
| E13 | ProvICS frozen threshold holds on attack-free rows | `campaigns.attack_free.rules.frozen` ratio 0.921, alarm share 0.0001 | Confirmed. Not in the paper |
| E14 | D2 contradicts "does not depend on the score" | `real_events.D2.rules.tracker.follower.vs_frozen` [−0.107, 0.031]; `first.vs_frozen` +0.390 [0.305, 0.475]; `fa_ratio_to_budget` 33.3 | Confirmed. The numbers are in Section 6.2; the heading of Section 7.2 is not changed |
| E15 | Tighten-only and capped tracker gain first events at higher alarm rates | `tighten_only.first` 122, +0.043 [0.014, 0.078]; `tracker_capped.first` 130, +0.099 [0.043, 0.163]; sealed ratios 1.57 and 2.12 | Confirmed. No matched static threshold exists in the files |
| E16 | Registration precedes access by seconds | `tt1d_verification_tep59.json` and `_provics.json → checks[*].detail` | Confirmed: 28 s, 34 s, 17 s (amendment to amended attempt) |
| E17 | Verifier counts 27, 8, 17, 20 | the four verification files | Match |
| E18 | Tables 3, 4, 5, 6, 7, 11 (tt1, tt1b) | `tt1_result_*.json`, `tt1b_result_batadal.json` | All values match |
| E19 | Tables 8, 9, 17 and Section 6.2 to 6.4 text (tt1d) | `tt1d_result_tep59.json`, `tt1d_result_provics.json` | All table cells match. Two text errors: M2, M3 |
| E20 | Tables 10, 16 and Sections 7.6, 7.7 | `tt1c_dev_v1.json`, `tt1e_dev_v1.json` | All values match |
| E21 | Tables 12 to 15, Sections 7.1 to 7.5, post-hoc paragraph of 5.2, Proposition 1 and 2 arithmetic | `tt1b_dev_v1`, `tt1b_frog_dev_v1`, `tt1b_physfrog_dev_v1`, `tt1b_frog_synthetic_v1`, `tt1b_posthoc_v1`, `tt1_posthoc_alarm_time`, `tt1_memory_check` | All values checked match |
| E22 | Unreported exploratory experiment | `tt1e_dev_v1.json → campaigns.*.E4.rules.tracker_ceil_*`: after the setpoint-pulse campaign the tracker under a 1.1, 1.25, 1.5 ceiling caught 20, 9, 3 of 30 just-detectable steps (controls 28, 24, 24); static 15, 9, 3 | Experiment B of the tt1e plan is not in the paper. Consistent with Proposition 4; minor |

### Number mismatches between the paper and the files

| # | Paper | Files | Path |
|---|---|---|---|
| M1 | Table 2 (l.397): "two test files, 260 days"; Section 6.1 (l.562): "The test files hold 14 attacks in 260 days" | The two test files hold 18,433 + 10,081 = 28,514 steps of 15 minutes = 297.0 days. 259.56 days is the unlabelled time. Figure 3's caption gives 192 days for the first file alone | `figure_data/threshold_trajectories.csv` (row counts); `results/threshold_transfer_tt1b_result_batadal.json → scores.D1.real_events.normal_days` = 259.5625 |
| M2 | Section 6.3 (l.745 to 748): "the adaptive rules ran above it, from 1.21 for the tracker to 2.12 for the capped tracker, except SPOT (0.84)" | The slow tracker ran at 0.83, below the frozen threshold's 0.98. Table 8 prints 0.83 | `results/threshold_transfer_tt1d_result_tep59.json → campaigns.attack_free.rules.tracker_slow.fa_ratio_to_budget` = 0.834 |
| M3 | Section 9 (l.1006): "Tennessee Eastman is a simulated process whose attacks are large manipulations" | 36 of the 116 first attacks the frozen threshold caught never exceeded 1.1 τ0, and 45 never exceeded 1.25 τ0. Qualitative mismatch | same file → `real_events.D1.rules.static_1.1.first.detected` = 80, `static_1.25.first.detected` = 71, `frozen.first.detected` = 116 |
| M4 | Section 6.2 (l.651 to 657): "142 attack runs" and "the first of its run (141 events)" with no explanation | One type-24 run has no event. A gap in the text, not a wrong number | same file → `real_events.D1.runs` = 141; verification file: "every attack run of the archive was scored: 142" |
| M5 | Table 9 caption (l.711): terminal bumps of "1.05 / 1.25 / 1.5 τ0" | Four magnitudes were registered and run; the 2 τ0 results are in the file and not in the paper (E6). An omission against the protocol's reporting commitment | `protocols/threshold_transfer_tt1d_protocol.json → secondary[3]`; result file → `campaigns.attacks.*.*.after[3]` |

No other disagreement was found.

### Table O. Sentences in the abstract and introduction that claim more than the evidence

| # | Quotation | Why it overclaims |
|---|---|---|
| O1 | Title: "Adaptive Alarm Thresholds Let Attacks Through in ICS Anomaly Detection" | Shown for the plain tracker and plain daily recalibration under the any-alarm count. Two stronger adaptive rules held on real attacks (H2), ProvICS is a null, and with D2 the tracker caught more first attacks than frozen |
| O2 | "so deployments often let it adapt" (l.53) | No deployment is cited |
| O3 | "In three pre-registered studies on data that no earlier analysis of ours had opened, a symmetric quantile tracker lost attacks that a frozen threshold caught" (l.57 to 58) | True under the any-alarm count only. Three of the four primary rules of those studies failed, and the sentence comes before any of that |
| O4 | "66 of the 104 attacks that follow another attack in their run against 104" (l.60 to 61) | The 104 are phases that begin within one step of the previous phase. All 38 losses are noise-attack phases, and the frozen threshold begins an alarm inside 6 of those 59 |
| O5 | "that failed the third study's primary rule" (l.66) | Names one of three failed primary rules. BATADAL's and ProvICS's are not mentioned in the abstract |
| O6 | "Deliberate poisoning is cheaper." (l.69) | No cost is compared anywhere. The campaigns need write access to the score, two need the live threshold, and two raise 12 and 48 alarms a day |
| O7 | "a day of two-minute nuisance alarms left the tracker catching none of 56 later, just-detectable attacks" (l.69 to 70) | The alarms and the "attacks" are values written into the score. At 2 τ0 the tracker caught 56 of 56, which the paper does not report |
| O8 | "an attacker who held the score just under the current threshold left a standard SPOT threshold catching 16 of 56 attacks" (l.72 to 73) | Score-level, with the threshold read at every step; the 56 "attacks" are synthetic 600 s bumps |
| O9 | "ran at 0.98 times its false-alarm budget over 280 attack-free days" (l.73 to 74) | Same simulator and modes as calibration. Where conditions changed, the frozen threshold was in alarm for 39% and 44% of unlabelled time |
| O10 | "A threshold that only tightens itself cannot miss an event the frozen threshold catches" (l.74 to 75) | Holds under the any-alarm count only, as Proposition 3 says and the abstract does not |
| O11 | "none of the rules we tested that can raise their own threshold is safe" (l.106 to 107) | Against a score-level attacker. On real attacks two such rules matched the frozen threshold |
| O12 | "Rules that learn from exceedances are poisoned by real attacks." (l.110) | The capped tracker learns from exceedances and was not (104 of 104 followers, 130 first events against 116) |
| O13 | "No adversarial planning is needed; the attacks in the recording did it." (l.115 to 116) | On HAI 20.07 the unlabelled opening had lifted the tracker to 5.0 τ0 before the first attack (Figure 2 caption); the attacks-only rerun is post-hoc |
| O14 | "Twelve two-minute pulses a day ... raised these thresholds enough to hide a later attack that a frozen threshold caught every time (registered on sealed attack-free Tennessee Eastman runs; exploratory on HAI)" (l.117 to 120) | The registered version writes the score; only the exploratory HAI version perturbs a control loop. It hides nothing at or above the pulse height |
| O15 | "Rules that leave alarms out of their update can be poisoned below their notice." (l.127) | The campaign raises 48 alarm episodes a day under those rules |
| O16 | Contribution 3: "a matching attack for each class, registered on sealed attack-free runs" (l.159 to 160) | Registered at the score level only |
| O17 | Contribution 4: "A design rule, supported by these results" (l.163) | Two parts are theorems with a measured cost; operator approval and offline recalibration are untested; the ProvICS costs cut the other way |

### Whether a reader can tell the status of each number

Mostly yes for tables, less so for prose. Gaps:
- Tables 8, 9 and 17 are labelled "registered" as a whole. The cells that test H1a to H6 are not distinguished from registered secondary cells (η = 0.01 τ0 tracker, static rules, false alarms, magnitudes other than the tested one).
- Introduction bullet 1, "16 of them attacks the frozen threshold caught", is a post-hoc count with no tag.
- Section 8, recommendation 2, mixes an exploratory statement and a registered one with no tag.
- Section 6.4 reports P5 and P6 results without naming them, and the gates file marks both as passed although the protocol calls them descriptive.
- Section 5.2's onset paragraph is tagged post-hoc in its heading only; its numbers are repeated in the abstract with a tag and in Section 9 with a tag, which is correct.

---

## Part 3. Comparison with round 1

| Rank in round 1 | Change asked for | This revision |
|---|---|---|
| 0 | Working anonymized artifact link | **Done in the text** (contribution 5, Open science). Not verified here; `publish/README.md` says the copy still has to be refreshed with the tt1d material |
| 1 | Correct the BATADAL SPOT and DSPOT attribution | **Done.** Section 6.1 (l.587 to 593), Figure 3 caption; the abstract no longer makes the claim |
| 2 | Re-weight abstract, contributions, results and conclusion around registered, metric-stable evidence; lead with BATADAL; G1 uninformative | **Partly.** G1 is marked uninformative, HyGrid-ICS left the abstract, the onset failures are stated. The abstract still leads with the any-alarm numbers of HAI 20.07, and the new Tennessee Eastman and campaign sentences add overclaims (O3 to O9) |
| 3 | Report every registered outcome | **Done for tt1 and tt1b** (Section 5.4, Appendix A, Section 6.1). **Partly for tt1d**: Appendix E gives the D1 real-event outcomes, but the 2 τ0 campaign magnitude, the D0 and D2 outcomes of rules other than the tracker, and the per-type counts of sixteen rules are in the files only |
| 4 | Restrict Proposition 3; report the oracle; quantify tighten-only's cost on registered data | **Done.** Section 3.1, Section 8 cost paragraph. The abstract drops the any-alarm qualifier (O10) |
| 5 | Stronger adaptive baselines and canonical extreme-value rules on spent data | **Done and then registered** (Section 7.6, Table 16, H2 in Section 6.2). The outcome is that natural poisoning does not survive the excluding and capped rules. Round 1's R1 and R3 tied a score of 4 to the effect surviving |
| 6 | Frog dose-response, matched refit cadence, declustered SPOT, direct-concealment baseline | **Partly.** Dose-response to 10 τ0 [expl] and at four magnitudes [reg tt1d, three printed]; SPOT refit on 1% peak growth; declustering with a burst frog. **No concealment baseline** ("We did not compare the two strategies") |
| 7 | Inference repairs: exact tests, exact H2 bound, matched operating points, stream-level resampling | **Partly.** McNemar counts and the exact H2 bound are in; Tennessee Eastman resamples runs. **Matched operating points are still missing** |
| 8 | Related work | **Done** as far as the text shows. Citations not verified here. Seo et al. 2026 is now cited with specific numbers (precision 0.91 to 0.24); round 1's response listed that paper as still to read, so confirm the numbers against the paper itself |
| 9 | Presentation fixes | **Done** |
| 10 | Registered SWaT and WADI outcomes; ideally a new registration with η in τ0 units, both counts, a campaign whose control is off the floor | **Done in substance on other data.** tt1d registers η = 0.01 τ0, both counts, the stronger rules and campaigns with controls of 44 to 56 of 56. SWaT and WADI remain unavailable |

Round 1 also listed seven things that would sink the paper. Items 1 (misread registered result), 3 (missing outcomes), 5 (weak baselines) and 7 (placeholder link) are closed. Item 4 (design rule stronger than evidence) is half closed. Items 2 (headline outruns evidence) and 6 (threat-model gaps) remain, in new forms.

---

## Part 4. Meta-review

**Decision: major revision.** Scores 2, 3, 2 with confidence 4, 4, 3.

### Consensus

**What the committee values.**
- Registration with frozen code, a one-access ledger and verifiers, and failed primary rules reported.
- A correct and simple account of tracker memory (Proposition 1).
- The first-attack against follower design on Tennessee Eastman, and the campaigns whose controls could pass or fail.
- Baselines that now include the obvious fixes, and a result (H2) that limits the paper's own claim.
- A number trace with two small errors in about 300 values.

**What the evidence supports.**
- A plain fixed-step quantile tracker and plain daily recalibration stop alarming during and after long exceedances, and under the any-alarm count they detect fewer labelled events than a frozen threshold on HAI 20.07, BATADAL and Tennessee Eastman [reg].
- Counting only alarms that begin inside an attack, the loss holds on BATADAL (14 events, post-hoc, large step) and on the 160 development events (exploratory, unreported), and does not hold on HAI 20.07 or Tennessee Eastman.
- Two small changes to those rules (leave alarm episodes out; cap the daily rise) remove the loss on real attacks [reg tt1d H2], at 1.3 to 2.1 times the alarm budget.
- An attacker who can write the score, and for two campaigns read the threshold, defeats every self-loosening rule tested on Tennessee Eastman for bumps up to the campaign's reach; a ceiling limits the reach to κτ0 by construction [reg tt1d].

**What would sink the paper as submitted.**
1. Title, abstract and introduction present the hypothesis as established although three of four primary rules failed (R2 W1, R3 W3).
2. The Tennessee Eastman result is alarm drop-out inside one continuous attack sequence, in one attack family (R1 W1, R2 W2).
3. Registered poisoning is score-level, the requirements and visible alarms per campaign are not stated, and a registered magnitude that bounds the loud campaign is omitted (R1 W5, W6; R3 W1, W2).
4. The guidance is presented as supported by the results; part is theorem, part untested, and ProvICS cuts against it (R3 W5, R1 W9, R2 W4).
5. The paper is too dense to review in 12 pages (R3 W6).

### Changes that would move the decision, ranked

| Rank | Change | Raised by | Expected effect | Class (Part 5) |
|---|---|---|---|---|
| 1 | Retitle and rewrite abstract, introduction bullets, contributions 2 to 4 and conclusion: primary outcomes first, any-alarm stated as the endpoint, table O corrected | all | R2 stays at 3 or rises; R3 to 3 | (a) |
| 2 | Tennessee Eastman by attack type and contiguity in the body and abstract; development-release onset counts | R1, R2 | Removes the most damaging surprise a reviewer can find in the result file; adds the paper's best onset evidence | (a) |
| 3 | Attacker-requirements table; "score-level" in abstract and conclusion; alarms raised per campaign; the 2 τ0 column | R1, R3 | R3 to 3 | (a) |
| 4 | Matched operating points: static thresholds below τ0 at each adaptive rule's realised alarm rate | R2, R3 | Decides whether "tighten freely" beats a lower frozen threshold | (b) |
| 5 | Process-level versions of the sub-event pulses and the frog on HAI normal data with 30 placements, a variant that does not read τ_t, and the direct-concealment baseline | R1, R3 | R1 to 3 | (b) |
| 6 | BATADAL rerun from the stored 15-minute trace with η = 0.01 τ0 and the stronger rules, both counts | R1, R2 | Removes the confound from the one onset-stable registered dataset | (b) |
| 7 | Scope the guidance: registered static floors, ProvICS costs, which recommendations are untested | R3, R1 | Makes contribution 4 defensible | (a) |
| 8 | Compress: Sections 7.4 to 7.7, Figures 1 and 3, Tables 5 and 10 to appendices; mark tested cells in Tables 8 and 9 | R3 | Readability; frees about two pages for ranks 2 to 6 | (a) |
| 9 | State the registration timeline and offer the history to the chairs | R2 | Answers the verifiability point | (a) |
| 10 | Rename Section 7.2; add one published detector on the development releases | R1 | Supports or limits the generality claim | (a), (b) |
| 11 | SPOT diagnosis on the sealed frog placements; say whether `spot_gr` matches the reference implementation | R2 | Separates learning from numerical degeneracy | (b) |
| 12 | Corrections M1 to M5; ProvICS aftermath question; abstract length; stale pack READMEs | all | Small | (a) |
| 13 | A registered study with separated attacks and the onset count as sole primary; a dataset with labelled benign drift; closed-loop campaigns with impact | all | The largest gain, and the only way to a score of 4 from R1 | (c) |

With ranks 1 to 3 and 7 to 9 alone I expect 2, 3, 3. With ranks 4 to 6 as well, 3, 3 to 4, 3.

---

## Part 5. What can be done without new data

Constraint: every dataset is spent, and 53 attack-free Tennessee Eastman runs are unread and reserved. The body is full to the last line of page 12, so every addition needs a cut.

### Page budget

Cuts, with approximate space from the PDF layout (116 numbered lines per page):

| Cut | Where | Frees |
|---|---|---|
| C1. Figure 1 (schematic) and its caption; Table 1 already states each region | l.250 to 262 | 0.5 page |
| C2. Table 10 and most of Sections 7.6 and 7.7 to Appendix C; keep 12 lines saying the rules came from two written plans on HAI and what the dose response added | l.859 to 938 | 0.8 page |
| C3. Sections 7.4 and 7.5 to one paragraph with pointers to Appendices B and C; keep the physical-frog sentences | l.817 to 857 | 0.3 page |
| C4. Figure 3 (BATADAL traces) to Appendix C; the 49.0 and 45.8 τ0 values stay in the text | l.623 to 637 | 0.3 page |
| C5. Table 5 and its paragraph to Appendix A | l.518 to 540 | 0.15 page |
| C6. HyGrid-ICS and voraus-AD rows of Table 4, the HyGrid onset sentences and the superseded variant to Appendix A | l.461 to 462, 487 to 496 | 0.15 page |
| C7. BATADAL frog-variant paragraph to Appendix A | l.595 to 601 | 0.08 page |
| C8. Limitations from 13 bullets to 7 | l.1001 to 1038 | 0.15 page |
| C9. Abstract from 411 to about 250 words | l.50 to 79 | 0.1 page |
| Total | | about 2.5 pages |

The additions below total about 1.3 pages.

### (a) Writing, framing and analysis with no new run

1. **Title, abstract, introduction, conclusion.**
   - Title: name the rules and the claim that holds, for example "Plain adaptive alarm thresholds stop alarming on sustained attacks and can be poisoned through their own updates".
   - Abstract, second paragraph (l.57 to 67): open with the primary outcomes ("Four primary rules were registered; one passed"). Then the any-alarm losses, named as such. Then the onset count, adding the development releases. Replace "attacks that follow another attack" with "later phases of an attack sequence".
   - Abstract, third paragraph (l.69 to 78): "at the score level" in the first sentence; "synthetic 10-minute bumps" for the terminal events; delete "Deliberate poisoning is cheaper"; add "under the any-alarm count" to the tighten-only sentence; give the ProvICS cost beside the 0.98.
   - Introduction bullets (l.110 to 130): bullet 1 limited to the plain tracker and daily recalibration, with H2 in the same bullet; bullets 2 to 4 say score-level and give 12 and 48 alarms a day; "below their notice" becomes "below the rule's event length".
   - Contributions 2 to 4 (l.153 to 164) and conclusion (l.1043 to 1058) to match.
   - Cut: C9.
2. **Tennessee Eastman by type.** Section 6.2 (l.683 to 699): replace "(57 of 95 events against 95)" with three sentences. All 38 lost followers are noise-attack phases; of the 59, the frozen threshold detects 59 under the any-alarm count and 6 at onset, the tracker 21 and 1; the tracker stood at a median 82 τ0 when they began, after first phases with a median length of 25 h; on the 45 denial-of-service followers the two rules were equal. Add two rows to Table 8 (noise followers, denial-of-service followers). Source: per-run records already in the result file. Cut: the sentence on indicator merging (l.653 to 655) to Appendix E.
3. **Development-release onset counts.** Section 7.3 (l.804 to 808), one sentence: frozen 124 of 160 at onset, tracker 76, −0.30 [−0.37, −0.23], with the frozen threshold in alarm for under 1% of unlabelled time [expl]. Update the first limitation (l.1004 to 1005). Cut: none needed after C6.
4. **Attacker-requirements table** in Section 3, in the space of Figure 1. Columns: campaign; reads (nothing, τ0, live τ_t, event length); writes (score in registered runs, setpoint or three sensors in exploratory runs); duration; alarm episodes per day raised under the target rule (12, 48, 0 in 51 of 56); largest terminal magnitude hidden per rule (from all four registered magnitudes); status. About 0.25 page. Cut: C1.
5. **Table 9.** Print the fourth registered magnitude ("1.05 / 1.25 / 1.5 / 2"), mark with a dagger the cells that H4, H5 and H6 test, and say in the text that the loud campaign hides nothing at its own pulse height. Same dagger convention for H1a, H1b, H1c, H2 in Table 8. No extra space.
6. **Guidance.** Section 8, recommendation 2 (l.971 to 974): add the registered static floors (80 and 71 of 141 first events at 1.1 and 1.25 τ0 against 116). Cost paragraph (l.992 to 996): add tighten-only 33.0 and ceiling-1.25 25.2 against tracker 6.5 on ProvICS. Mark recommendations 3 and 4 as untested here, and state that no dataset in the paper has labelled benign drift. Contribution 4: "a design rule whose recall floor is proved and whose cost is measured on three datasets". About 8 lines. Cut: merge recommendations 5 and 6 into one.
7. **Registration paragraph** (l.404 to 412): give the time between each registration commit and the first access under it (43 s for tt1, 86 s for tt1b, 28 s for tt1d, from the verifier reports), the 17 s between the amendment and the amended attempt, say the timestamps are the repository's own, and offer the history to the chairs. Four lines. Cut: from C8.
8. **Section 7.2 heading** (l.792): "The effect across scores", with a closing sentence that D2 on Tennessee Eastman shows no follower loss and a tightening tracker.
9. **ProvICS** (l.760 to 765): report the sealed-row ratio of 0.92 and say that the 44% may be disturbance outside the labels. Two lines.
10. **Corrections.** M1 (l.397, l.562: 297 days, 260 unlabelled), M2 (l.747: add the slow tracker), M3 (l.1006: drop "large"), M4 (l.656: say one run has no event), "deployments often" (l.53: cite or write "published methods").
11. **Slow tracker and daily recalibration on first events** (l.685 to 689): add that the slow tracker also lost first events (110 against 116).

### (b) Runs on already-spent data, labelled exploratory or post-hoc

Each needs a written plan committed before the run and a ledger entry, as the paper already does.

1. **Matched operating points.** On the Tennessee Eastman sealed runs find the static multiples c < 1 at which cτ0 gives 1.30, 1.57 and 2.12 times the budget, then score those thresholds on the attack runs under both counts. Do the same on the three HAI development releases. Add two rows to Table 8 ("frozen at tighten-only's alarm rate", "frozen at the capped tracker's alarm rate") and one sentence to the Section 8 cost paragraph. Cut: C5.
2. **BATADAL from the stored trace.** `figure_data/threshold_trajectories.csv` holds the full 15-minute D1 score and labels of both test files. Run the tracker with η = 0.01 τ0, the excluding recalibration, the capped tracker, the 1.1 and 1.25 ceilings and the standard SPOT, under both counts. Two sentences after Table 7 and one row group in Appendix A. Cut: C7.
3. **Process-level campaigns on HAI normal data.** (i) Sub-event pulses and loud pulses as setpoint or three-sensor spoofs scored by the real monitor, 30 placements. (ii) The physical frog at 30 placements instead of 12, with terminal steps at several magnitudes. (iii) A frog that does not read τ_t and estimates it from the alarms it triggers, reporting the alarms spent. (iv) The direct-concealment baseline: the same three-sensor attacker hides the terminal step during the step. Results in Appendix B, five lines in Section 7.5, and the "We did not compare" sentence of Section 3 (l.288 to 289) replaced by the result. Cut: C3.
4. **Impact in process units.** For the HAI campaigns of item 3, report the largest setpoint deviation that stays undetected after each campaign against the control. One sentence in Section 7.5, one column in Appendix B.
5. **One Tennessee Eastman trace figure.** Post-hoc, one noise-attack run: score, frozen threshold, tracker, event intervals. It shows what Table 8's follower column means. In place of Figure 3. Cut: C4.
6. **SPOT under the frog.** On the 56 sealed placements log ξ, σ and the number of peaks through the campaign; rerun with the bounded shape and with declustering, which were exploratory on HAI and not registered. One sentence in Section 6.3, a small table in Appendix E. Also run `spot_gr` beside the reference SPOT code on one public stream and report the agreement.
7. **A published detector on the development releases.** One reconstruction or forecasting detector from the literature, scored with frozen, tracker, excluding and capped rules under both counts. Two sentences in Section 7.2.

### (c) Changes that need new data

1. **A registered study with separated attacks and the onset count as the only primary.** SWaT and WADI under tt1b if access arrives, with η in τ0 units added by amendment before access, or another recording whose attacks are hours apart. This is the test the title needs.
2. **Benign drift.** A recording with labelled operating-point changes or maintenance, with attacks, so that the alarm cost of refusing to loosen and the recall cost of loosening are measured on the same stream at matched budgets.
3. **Closed-loop campaigns.** The Tennessee Eastman simulator or a hardware-in-the-loop testbed with the monitor running, an attacker limited to named sensors and actuators, and impact in process units. The 53 unread attack-free runs can host a registered campaign study with an attacker that does not read τ_t, and a registered matched-operating-point false-alarm comparison.
4. **Operators.** Alarm logs or a small study for the assumption that 12 to 48 recurring alarms a day go unanswered, and for approval "from the process".
5. **External timestamps** for every future registration (a public commit or a registry entry made before access).

---

*End of round-2 mock PC review. Written into `review/` only; nothing in `latex/`, `results/`, `protocols/`, `figure_data/` or `manuscript/` was modified, and no experiment was run.*
