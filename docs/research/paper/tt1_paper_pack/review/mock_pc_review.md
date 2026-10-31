# Mock program-committee review: ACM ASIA CCS 2027

**Submission:** *Thresholds That Travel: Adaptive Alarm Thresholds Let Attacks Through in ICS Anomaly Detection* (anonymous).
**Reviewed version:** `latex/main.tex` sha256 prefix `62d4fb1eee94` (modified 2026-10-31 21:26:57 UTC) and its compiled `latex/main.pdf` (sha256 prefix `74f83f760019`, 21:27:42 UTC; 11 pages: body and references end on page 10, Ethical considerations and Open science appendices on page 11).
**Instructions carried out:** `prompts/5_mock_pc_review.md`. No file other than this one was written in the pack.

## How this review was produced (read first)

- **Literature report: absent.** `review/literature_report.md` did not exist when the reviews began, and it still did not exist when this file was written. The reviewers therefore handled related work from their own reading. Every citation they suggest is marked *"from reviewer's own knowledge, not checked"* unless the chair's audit (Part 2) says it was verified. One concurrent preprint named by R3 was confirmed to exist (arXiv:2609.23254, A.-R. Atarmla, submitted 19 Sep 2026); only its abstract was read.
- **The paper changed three times during the review.** Reviews began on the version of 02:21 local (42,696 bytes). The pack was rebuilt at 21:19 UTC (version 2, 50,942 bytes) and again at 21:26:57 UTC (version 3). Version 2 added §3.1 with Propositions 1-3, a post-hoc time-in-alarm / onset-recall paragraph in §6.2, an attacks-only / unlabelled-only rerun in §7.3, design recommendation 5, the completed D0 list in §7.2, and an Ethical considerations appendix. It came with three new post-hoc result files: `threshold_transfer_tt1_memory_check.json`, `threshold_transfer_tt1_posthoc_alarm_time.json` and `threshold_transfer_tt1_posthoc_transient.json`. Version 3 changed two passages: the HyGrid-ICS onset counts in §6.2 and the Fig. 2 caption. The registered result files are unchanged since 2026-10-23. The verifier files were rewritten at 21:19 UTC and still pass 27/27 (tt1) and 8/8 (tt1b).
- **Independence.** Each reviewer was a separate agent session. Each read the paper and the result and protocol files itself, saw neither this prompt's summary nor the other reviews, and returned its review without writing to the pack. All three updated their reviews against version 2. R2 and R3 also folded in the version-3 delta. R1 finished before version 3 appeared, so the chair's audit (Part 2, item A6) records where version 3 changes an R1 point.
- **Evidence checking.** Each reviewer checked every weakness against `results/` and `protocols/` and gave it a status: *confirmed*, *answered in the paper adequately / inadequately*, or *not supported by the files*. The chair then re-checked every weakness that carries weight in the meta-review against the files (Part 2). Reviewers were told not to load `figure_data/threshold_trajectories.csv` because memory was short; the chair did load it to settle the claims that depend on it.
- **Status tags** used throughout: **[reg tt1]**, **[reg tt1b]** (registered studies); **[expl]** (exploratory, on the development data of the spent HAI 21.03 / 22.04 / 23.05 releases or synthetic data); **[post-hoc]** (analyses run after the registered finals, including the trajectory figure data). Nothing was recomputed from raw data, and none is in the pack. Chair checks are reads of stored fields, or arithmetic on stored fields and on the post-hoc trajectory figure data.
- **Section numbers** follow the printed PDF: 1 Introduction, 2 Background, 3 Threat model, 3.1 How long a threshold remembers, 4 Monitor/rules/data, 5 How the hypothesis changed, 6 Registered results (6.1-6.3), 7 Learning regions under attack (7.1 EVT, 7.2 score, 7.3 mechanism, 7.4 pulses, 7.5 frog, 7.6 BATADAL), 8 Design guidance, 9 Limitations, 10 Conclusion.

**Scores:** R1 2 (weak reject), confidence 4. R2 2 (weak reject), confidence 4. R3 2 (weak reject), confidence 3.
**Meta-review decision: major revision** (Part 3). If the cycle has no revision outcome, the equivalent decision is reject and encourage resubmission.

---

## Decision at a glance

- **Major revision.** All three reviewers score 2 (weak reject); confidence 4, 4 and 3.
- **Robust registered core.** The tracker loses real-attack recall against the frozen threshold on HAI 20.07 (any-alarm metric) **[reg tt1]** and on BATADAL (also under onset counting) **[reg tt1b]**, as Proposition 1 predicts.
- **What sinks the current version:**
  - It misattributes the BATADAL SPOT/DSPOT failure to attacks. Both rules start at 46-49 τ0 at t = 0, before any attack.
  - Its headline outruns the metric-robust and registered evidence: HAI 20.07 onset counting, HyGrid-ICS, and the exploratory frog.
  - Registered outcomes the protocol promised to report are omitted.
  - It credits operator-gated loosening with a by-construction guarantee.
  - Its baselines and SPOT variants are the naive ones.
  - The artifact link is still a placeholder.
- **Where the fixes fall.** Most fixes are writing and record-based analysis (Part 4a). The decisive new evidence comes from stronger baselines and canonical extreme-value rules on the spent HAI development data (Part 4b). Registered SWaT/WADI outcomes need new data (Part 4c).

## Part 1. The three reviews (step 1 of the prompt)

The reviews are reproduced as each reviewer returned them in its final round. R1 is written against version 2; see Part 2, item A6, for the one version-3 change that affects it. Their evidence claims are audited in Part 2, which records four reviewer corrections: A2, A8, A14 and A17.


### R1: ICS security researcher (SWaT/WADI/HAI detectors and attacks)

**Overall score: 2 / 5. Reviewer confidence: 4 / 4.**

##### Changes since the first version
The revision adds Sec. 3.1 (Propositions 1-3), a post-hoc time-in-alarm/onset-recall paragraph (6.2, 6.3), an attacks-only/unlabelled-only rerun (7.3), new design rec. 5, the D0 sentence for voraus-AD/BATADAL (7.2) and an Ethical considerations appendix. I re-read the whole paper and the three new result files: memory_check, posthoc_alarm_time and posthoc_transient, all post-hoc and all ledgered in the updated verifiers. Every number in the new text that maps to a stored field matches it.

**Now answered:** W7(a) (Prop. 3 makes tighten-only's recall a construction property, and the tables now measure its cost), W11 (alarm time is reported) and the ethics half of W15. W10 and W14 remain adequately answered.

**Not answered, or made worse by the new material:**
- W4: the authors' own attacks-only/unlabelled-only rerun shows SPOT/DSPOT lose the same recall on BATADAL either way, contradicting the retained explanation.
- W3: Prop. 1 is used to argue η-independence, which holds per step but not per attack.
- W7(b, c): the oracle 1/10 result is still unreported.
- W9: the opening-transient sensitivity analysis is also unreported.

**New weaknesses:**
- N1 (major): the paper extends Prop. 3's guarantee to operator-approved loosening, where its premise fails, and the registered oracle result is a counterexample.
- N2 (major): the frozen threshold was in alarm 39% of the time on HAI 20.07, and under onset counting the registered primary's tracker gap is not significant; the headline framing is unchanged.
- N3 (minor): four new numbers cannot be traced to a stored field.
- N4 (minor): Prop. 1 is over-interpreted; Prop. 3 does not hold for onset recall in general.
- N5 (minor): data-status labelling slipped in the new text.

Score unchanged at 2. The revision is more transparent, but its new evidence weakens the primary result and the BATADAL story rather than strengthening them.

#### Review R1 (updated) — "Thresholds That Travel: Adaptive Alarm Thresholds Let Attacks Through in ICS Anomaly Detection" (ASIA CCS 2027)

Reviewer background: ICS security (SWaT/WADI/HAI/BATADAL; residual, reconstruction and CUSUM-style detectors; evasion and poisoning).
Tags: **[reg tt1]**, **[reg tt1b]** = registered; **[expl]** = exploratory development data (spent HAI 21.03/22.04/23.05); **[post-hoc]** = after the registered finals. Section numbers follow the printed PDF (3.1 How long a threshold remembers, 6.2, 7.6 BATADAL, 8 Design, 9 Limitations, 10 Conclusion).

##### Summary
The paper studies the threshold layer of process-level ICS anomaly detectors. It compares a frozen threshold with daily recalibration, symmetric quantile trackers, SPOT/DSPOT and a tighten-only rule, framing each rule by the score values it learns from ("learning region"). Sec. 3.1 now derives three simple properties: tracker memory per exceedance step is (1−p)/p quiet steps; daily recalibration is lifted by any attack lasting more than pN+1 steps of a day; and a threshold capped at τ0 cannot miss a frozen-detected event.
- **tt1 [reg tt1]:** on HAI 20.07 the tracker detected 20/38 against 36/38 for frozen (−0.42 [−0.58, −0.26]).
- **Post-hoc caveat:** the new post-hoc analysis shows the frozen threshold in alarm for 39% of unlabelled time. Counting only alarms that start inside an attack, the gap becomes −0.16 [−0.37, 0.05] **[post-hoc]**.
- **tt1b [reg tt1b]:** on BATADAL, H1 (tracker 6/14 vs 14/14) and H2 pass, but the primary fails on H3.
- **Exploratory:** pulse and closed-loop "frog" campaigns on spent HAI data.

The recommendation is unchanged: thresholds may tighten automatically and loosen only with operator approval.

##### Strengths
- **Registration and ledger discipline remain exemplary.** Every new post-hoc re-opening is ledgered and listed by the updated verifiers. The new post-hoc analyses are labelled as such in 6.2 and 6.3, and the authors report results that cut against their own headline (6.2: "the tracker's HAI 20.07 gap depends on crediting the frozen threshold's long alarms").
- **Sec. 3.1 is a genuine improvement.** The propositions are short and correct as stated, and they make the mechanism checkable. The integrality check of recorded tracker changes against Prop. 1 (error 7.5×10⁻⁶ of a step **[post-hoc]**) is a nice consistency test.
- **Time-in-alarm is an operationally important metric** that ICS-IDS papers usually ignore. Rec. 5 ("budget alarm time as well as episodes") is good advice.
- **The tighten-only framing is now honest:** recall equality holds by construction, and the cost is reported (BATADAL 2.43× vs 0.70× budget **[reg tt1b]**).
- **The ethics appendix is present and reasonable.**

##### Weaknesses (re-checked against the revision)
**W1 (major) — A0 is mostly a benchmark artefact; post-alarm freeze/reset still not modelled.** Prop. 1 sharpens the point: one exceedance minute is remembered 23 h on HAI 20.07 (from registered p; checked post-hoc). That is an argument for gating updates on alarms, yet no gated variant is tested. *Answered inadequately* (3.1, 6.2, 7.3, 9).

**W2 (major) — Straw-man risk is unchanged.** There is still no deployment evidence for these exceedance learners and no recalibration that excludes alarmed windows. The ethics appendix calls the rules "textbook algorithms". *Still unanswered (confirmed).*

**W3 (major) — The BATADAL H1 result is still driven by a mis-scaled step.** η = 64.6 = 6.9 τ0 per step **[reg tt1b]**. The tracker peaked at 1131/1195 τ0 and would need 133/209 days to return **[post-hoc]**. Prop. 1's "whatever η" holds per exceedance step only. How many steps an attack generates, and how high the threshold rises, both scale with η (N4). *Answered inadequately* (3.1, 7.6, 9).

**W4 (major) — SPOT/DSPOT inflation on BATADAL is misattributed; the new file contradicts it.** The 7.6 explanation ("real attacks had already blinded DSPOT") and the abstract sentence are unchanged.
- At the first attack of each test file, before any attack in that file, moments-SPOT stood at 26.9/43.8 τ0 and DSPOT at 24.5/40.7 τ0 **[reg tt1b]**.
- The new rerun gives the same answer whether the update sees only attack samples (SPOT 6/14, DSPOT 6/14) or only unlabelled samples (6/14 and 7/14) **[post-hoc]**.

The inflation does not depend on the attacks; tail-fit initialisation on heavy-tailed calibration data is the likely cause. *Still unanswered (confirmed), now with the authors' own evidence.*

**W5 (major) — A2 still has no registered support** (registered BATADAL frog: after = control for all D1 rules except 24 h MLE-SPOT 0.7 vs 0.9 **[reg tt1b]**; physical frog DSPOT 9/12 vs 9/12 **[expl]**). The abstract still lacks an exploratory tag. *Answered inadequately.*

**W6 (major) — The A2 threat model and success metric are unrealistic for a plant** (direct concealment is available; binary detection of a just-detectable step; 8×10¹⁵ τ0 runaway **[expl]**). The new ethics text ("attacks are not new in kind") narrows the novelty further. *Answered inadequately.*

**W7 (major) — Design guidance, partly answered.**
- (a) *Answered adequately* by Prop. 3 and the revised framing.
- (b) Still unreported: the registered oracle permit caught the terminal step in 1/10 E4 controls against 10/10 for frozen **[reg tt1, not gated]**.
- (c) Unaddressed: operator gating conflicts with the threat model's dismissive operators.

*Overall answered inadequately.*

**W8 (major) — Secondary datasets are still over-counted.** On HyGrid-ICS the new onset count shows the tracker *above* frozen (8 vs 3 of 91, +0.055 [0.00, 0.11] **[post-hoc]**), and the paper calls this "not informative" without the numbers. voraus-AD is unchanged (AUROC 0.706 **[reg tt1]**). SWaT and WADI are pending. *Answered inadequately.*

**W9 (minor) — Omitted outcomes, now including a new post-hoc analysis.**
- Still missing: S1 half split (tracker 0.474→0.579, slow 0.579→0.842 **[reg tt1]**), detection-v2, E5, oracle E4.
- Newly missing: the ledgered opening-transient sensitivity **[post-hoc]**. Hiding the 23.8 h opening run raises the tracker from 20 to 25, slow from 27 to 33 (−0.08 [−0.18, 0.00]) and daily from 18 to 24.

*Confirmed.*

**W10 (minor) — G1 passes vacuously.** *Answered adequately* (6.1).

**W11 (minor) — The frozen threshold's budget adherence is now answered:** time in alarm is reported (39% / 4.1% / 1.4% **[post-hoc]**), with recs 3 and 5. Residual: "held 0.66 to 2.23 episodes per day", although 2.23 exceeds the 2.0 budget (**[reg tt1]**, G3 within-budget false). *Answered adequately.*

**W12 (minor) — The exchangeable event bootstrap is unchanged,** and there is no multiplicity control over the growing set of post-hoc variants. *Confirmed.*

**W13 (minor) — No time-to-detect.** Onset recall helps, but delays are in the record (BATADAL median 52 min, up to 15–16 h **[reg tt1b]**) and not reported. *Answered inadequately.*

**W14 (minor) — Detector coverage is narrow.** *Answered adequately* as a limitation (9).

**W15 (minor) — Ethics: answered. Related work: unchanged.** *Answered inadequately.*

**W16 (suspected) — Registration hygiene.** *Not supported by the files.* The new post-hoc accesses are ledgered. Residual: HAI 20.07 has now been re-opened post-hoc four times, partly in response to review, which carries forking-path risk.

**N1 (major, new) — The operator-gated design is credited with a guarantee it lacks.** The introduction (and Sec. 8) says a threshold that "loosens only when an operator approves … keeps the frozen threshold's recall by construction". Prop. 3 requires τ_t ≤ τ0 at every step, and an approved loosening breaks exactly that. The registered oracle permit, a simulated operator who refuses to loosen during events, missed the terminal step in 9/10 E4 controls, where frozen caught 10/10 **[reg tt1]**. The guarantee holds for tighten-only *without* a permit only. *Confirmed.*

**N2 (major, new) — The time-in-alarm finding undercuts the registered primary, but the headline is unchanged.**
- The frozen D1 threshold was in alarm for 39% of HAI 20.07's unlabelled time, including the first 23.8 h of test1 **[post-hoc]**. G3 (2.23 episodes/day **[reg tt1]**) therefore hides an alarm duty cycle no operator would accept.
- Under onset counting, frozen detects 26/38; the tracker gap is −0.16 [−0.37, 0.05] and the slow tracker +0.03 [−0.18, 0.24] **[post-hoc]**.

The disclosure in 6.2 is commendable. Still, intro bullet 1, contribution 2 and the conclusion continue to present HAI 20.07 as clean evidence of attack poisoning. A monitor in alarm for the whole first day of a fresh stream also raises a validity question about D1 transfer, which the paper does not discuss. *Answered inadequately.*

**N3 (minor, new) — Some new numbers cannot be traced.** "0.4% of minutes below τ0", "3.2% of the test time", "most of a 17-hour stretch of test2" and "attacks last one to five days" are in neither memory_check.json nor posthoc_alarm_time.json, the files the draft names as sources. They may come from the trajectory CSV, which I did not load. "1.7 to 24 days" between attacks checks out **[reg tt1b]**. *Confirmed.*

**N4 (minor, new) — The propositions are correct but over-interpreted.**
- **Prop. 1** holds per exceedance step: 1385 quiet steps on HAI 20.07 and 133 on BATADAL, matching memory_check **[post-hoc]**. For an attack long enough for the tracker to catch up with its score S, the number of exceedance steps is about (S−τ0)/(η(1−p)), so the time to forget it scales as 1/η. Whether the next attack is missed depends on the rise height, which also scales with η. "Follows from its calibrated false-alarm rate alone" (10; contribution 3) therefore overreaches. The record itself shows E depending on η: 2817 vs 9758 exceedance steps for tracker vs tracker_slow on test1 **[post-hoc]**. "Which is why [the slow tracker] lost recall too" also sits poorly with that loss vanishing under onset counting or with the opening transient hidden **[post-hoc]**.
- **Prop. 2** is correct up to the quantile convention (64 s on HAI 20.07; 2 steps on BATADAL).
- **Prop. 3** is correct for any-alarm recall but not, in general, for the paper's own onset metric: a lower threshold can start an episode before the event that merges into it. The data happen to show equality (26 = 26, 14 = 14 **[post-hoc]**).

*Confirmed.*

**N5 (minor, new) — Data-status labelling slipped.** The post-hoc trajectory checks in 3.1 carry no tag. The D0 sentence in 7.2 mixes registered-tt1b (BATADAL [−0.86, −0.36]) and post-hoc (voraus-AD [−0.04, −0.01]) intervals under an "exploratory" heading. *Confirmed.*

##### Questions for the authors
1. What were the moments-SPOT and DSPOT initial alarm levels z_q/τ0 on BATADAL at t = 0? Given that the attacks-only and unlabelled-only reruns give identical SPOT/DSPOT recall, will you re-attribute H3's failure to initialisation?
2. Will you restrict the guarantee of Prop. 3 to tighten-only without permits, and report and explain the registered oracle E4 control result (1/10)?
3. Why does D1 sit above τ0 for the first 23.8 h of HAI 20.07 test1? Is this a warm-up or state-initialisation artefact of the monitor, or a genuine regime shift? Would a monitor-side fix change G2?
4. Why is the opening-transient sensitivity analysis omitted from the paper? The file says it is superseded by the alarm-time analysis, but the latter does not contain that variant.
5. Can you state Prop. 1's consequence per attack, i.e. the time to forget and the rise height as functions of η, attack length and score? Can you show H1 on BATADAL with η set in τ0 units?
6. As in the first round, what happens with recalibration that excludes alarmed windows and a post-alarm hold-off, and is there evidence that these adaptive rules are deployed in ICS?
7. Where do 0.4%, 3.2%, the 17-hour stretch and "one to five days" come from?

##### Related work to consider (from reviewer's own knowledge, not checked)
- Cárdenas et al., ASIACCS 2011 (attacks against process control; CUSUM).
- Urbina et al., CCS 2016 (impact of stealthy attacks under detector thresholds).
- Ghafouri et al., GameSec 2016 (optimal or adaptive thresholds against strategic attackers).
- Giraldo et al., ACM CSUR 2018 (survey of physics-based detection).
- Murguia & Ruths, CCA 2016 (CUSUM / χ² against sensor attacks).
- Su et al. (OmniAnomaly, KDD 2019) and Tuli et al. (TranAD, VLDB 2022), both of which use POT/SPOT thresholds.
- Erba & Tippenhauer et al. on concealment against model-free ICS detectors (ACSAC 2022).
- Wolsing et al. (ESORICS 2022) and Kus et al. (CPSS 2022) on ICS-IDS evaluation.
- Barreno et al. (ASIACCS 2006) on causative attacks.

##### Overall assessment
The revision is more transparent and Sec. 3.1 is a real gain in clarity. Its new evidence, however, mostly weakens the security case:
- The registered HAI 20.07 primary's tracker gap is not significant once attacks inside a running day-long frozen alarm stop counting **[post-hoc]**.
- The BATADAL tracker loss rests on a step of 6.9 τ0.
- The BATADAL SPOT/DSPOT loss now demonstrably does not come from attacks **[post-hoc]**.
- The closed-loop attack remains exploratory.
- The recommended operator-gated design is credited with a guarantee that only the permit-free variant has, and the registered oracle result contradicts it.

A practitioner would take away "keep the threshold frozen, recalibrate under change control, and watch alarm time". That is useful, but it is already common practice and below the bar for a top security venue. Registered SWaT/WADI results with η in τ0 units, corrected attributions and realistic baselines could change this.

**Score: 2 (weak reject)**   **Confidence: 4 (expert)**

##### What would change my score
- **To 3:**
  - Re-attribute the BATADAL SPOT/DSPOT loss (W4) and reframe H1 as an η-scaling effect (W3, N4).
  - Restrict Prop. 3 to tighten-only without permits and report the oracle result (N1, W7b).
  - Rewrite the intro, contribution 2 and the conclusion so that HAI 20.07 is presented with the onset caveat (N2).
  - Report the transient sensitivity, S1, detection-v2 and E5 outcomes (W9).
  - Tag A2 as exploratory in the abstract (W5).
  - Source or drop the untraceable numbers (N3).
- **To 4:**
  - Registered SWaT/WADI results with η and the SPOT initialisation fixed in τ0 units by amendment before access.
  - Alarm-gated recalibration and post-alarm hold-off baselines (W1, W2).
  - An impact-based A2 evaluation against a direct-concealment baseline (W6).
  - Delay-to-detect (W13).
- **Lower:** if the BATADAL SPOT/DSPOT initialisation turns out to be an implementation bug that also affects the exploratory HAI frog results.

---


### R2: statistician (streaming anomaly detection, extreme-value theory, conformal prediction)

**Overall score: 2 / 5. Reviewer confidence: 4 / 4.**

#### ASIA CCS 2027 — Review R2, revised (statistics: streaming EVT, conformal/online quantile tracking, inferential design)

**Paper:** Thresholds That Travel: Adaptive Alarm Thresholds Let Attacks Through in ICS Anomaly Detection (main.tex sha256 prefix 62d4fb1eee94)

**Overall score: 2 (weak reject), unchanged** | **Reviewer confidence: 4**

##### Changes since the first version

I re-read the revised paper: Section 3.1 with Propositions 1–3, the post-hoc "Time in alarm and onset recall" paragraph (Sec. 6.2), the attacks-only rerun (Sec. 7.3), the rewritten abstract, Sec. 8 and Sec. 10, and the Ethical considerations appendix. I also checked the three new result files (all post-hoc). In the latest small revision I checked the two changed passages. The HyGrid onset counts added to Sec. 6.2 match the file. The rewritten Fig. 2 caption now describes the 23.8-h opening alarm.

**What the revision answers.**

1. Proposition 3 makes tighten-only recall a theorem, and the registered BATADAL cost is now cited (W2 is answered; lowered to minor).
2. Proposition 1 makes the tracker's memory analytic (W3 is largely answered).
3. The time-in-alarm, onset-recall and HyGrid reversal numbers are now disclosed honestly.

**What the new material shows.**

1. **The HAI 20.07 primary result does not survive a stricter metric.** Under onset counting it becomes −0.16 [−0.37, 0.05], and the G3 pass masks a 23.8-h opening alarm (N1).
2. **The attacks-only attribution is overdetermined**, and the Fig. 2 caption now itself credits a benign opening stretch with lifting the tracker to 5.25 τ0. Sec. 7.3 still says "attacks are what raise the tracker", and an unreported post-hoc transient analysis remains in results/ (N2).
3. **The new file adds evidence against W1, which the revision leaves unchanged.** With attacks removed from the update, BATADAL SPOT and DSPOT are equally inflated, yet the abstract still attributes the inflation to days-long attacks.
4. **On HyGrid the disclosure is complete but the inference is not adjusted** (W10). The merging argument applies equally to the registered count, yet the abstract still lists HyGrid as a replication.
5. **New minor issues are N3–N6:**
   - Proposition 3 holds only for the registered metric (N3).
   - Propositions 1–2 are over-interpreted in places (N4).
   - Some status labels are missing (N5).
   - The Fig. 2 caption says "no attack label", but the file records 7 attacks in the opening run (N6).

**Score:** stays at 2.

Status convention: **[reg tt1]**, **[reg tt1b]**, **[expl]** (development or synthetic data), **[post-hoc]**, **[reviewer arithmetic]** (my arithmetic on stored fields). Section numbers follow the printed PDF.

##### 1. Summary

The paper studies the threshold layer of process-monitoring anomaly detectors. It compares a frozen threshold with daily recalibration, symmetric quantile trackers (ACI-style), tighten-only variants, a static margin and SPOT/DSPOT, applied to a world-model residual score (D1) and a model-free score (D0). Section 3.1 derives how long the tracker and daily recalibration remember an exceedance as a function of the calibrated exceedance rate p, and shows that tighten-only cannot lose any-alarm recall against frozen. A pre-registered study (tt1) found that the tracker detected 20/38 HAI 20.07 attacks against 36/38 for frozen [reg tt1]. A second study (tt1b) found 6/14 against 14/14 on BATADAL [reg tt1b], but its primary rule failed because H3 was untestable. New post-hoc analyses report time in alarm, an onset-based recall, and reruns in which the threshold update sees only attack or only unlabelled samples. The authors recommend thresholds that tighten automatically and loosen only with operator approval.

##### 2. Strengths

1. **Research hygiene is exemplary and has been verified**: hash-frozen code, a single-access ledger, a verifier, a reported failed primary, and accesses after registration (verification JSONs).
2. **The primary rules are intersection-union conjunctions**, so "no multiplicity correction" is correct for them.
3. **Section 3.1 is a real improvement.** Propositions 1–3 are correct under their update rules, and their constants match the stored fields: 1385 steps, 23.1 h per exceedance minute, 133 steps, 33.2 h, 64 s, 43–209 days to return [post-hoc check of registered parameters].
4. **The new post-hoc analyses are reported even where they cut against the headline**: onset −0.16 [−0.37, 0.05] in the abstract, and the HyGrid sign reversal in Sec. 6.2. "Budget alarm time as well as episodes" (Sec. 8) is a useful practical lesson.
5. **The Ethical considerations appendix is appropriate.**
6. **The record agrees with the text** for every new number I could check (W16), with one caption exception (N6).

##### 3. Weaknesses

Each item gives its severity, the evidence I checked, and its status in the current version.

**W1 (major, unanswered; stronger evidence). BATADAL: the extreme-value conclusion is contradicted by the record.**

- **Before any attack:** at the first attack of test file 1 (no earlier attack, around day 72), SPOT stood at 26.9 τ0 and DSPOT at 24.5 τ0. At the first attack of test file 2 they stood at 43.8 and 40.7 τ0. Both then *fall* across the attack sequence [reg tt1b, per_event onset_inflation].
- **With attacks removed:** the new unlabelled-only rerun, with no attack in the update, still gives SPOT 6/14 at 25.8 τ0 and DSPOT 7/14 at 23.5 τ0. Attacks-only gives SPOT 6/14 at 31.7 τ0 [post-hoc].

The inflation is not caused by attacks. It is most plausibly an initialisation or estimation failure of method-of-moments POT on a tail with spread/τ0 ≈ 688 [reg tt1b]. The abstract, Sec. 7.6 and Sec. 10 should be corrected, and z_q at t = 0 reported.

**W2 (minor, answered adequately). Tighten-only recall holds by construction.** This is now Proposition 3, with the registered BATADAL cost (2.43× against 0.70× budget [reg tt1b]) in the abstract and Sec. 10. Residual: Sec. 8 cites only the development cost (5.98 against 4.05 [expl]).

**W3 (major, largely answered). The tracker's loss follows from its update rule.** Proposition 1 answers the predictability point. Two residuals remain:

1. The *size* of the rise depends on η, even though recovery time does not. On BATADAL, η = 64.6 gives 6.8 τ0 per exceedance step [reviewer arithmetic on reg tt1b], so H1 stays confounded with the spread pathology.
2. No mitigation that Proposition 1 suggests is evaluated: a step cap, no upward updates during alarms, or an alarm-time budget.

**W4 (major, unanswered). The unit of inference does not match the claim.** All intervals, old and new, come from a paired event bootstrap within single streams. The memory check (tracker at about 20 τ0, 43–209 days to return [post-hoc]) makes the serial dependence explicit; the effective sample is closer to one trajectory per stream. τ0 variability is not propagated, and the voraus-AD intervals ignore clustering.

**W5 (major, unanswered). The H2 non-inferiority pass comes from a degenerate interval.** 14/14 against 14/14 gives a bootstrap interval of [0, 0] [reg tt1b]. The exact Clopper–Pearson lower bound is about −0.23 [reviewer arithmetic], below the registered margin of −0.143.

**W6 (major, answered inadequately). G1 and H3 are judged differently.** G1 "passed" with the adaptive controls already at 0.0 [reg tt1], while H3 failed for the same floor reason and is called uninformative. Table 3 is unchanged.

**W7 (major, answered inadequately). The SPOT/DSPOT implementations are non-standard.**

1. Method-of-moments GPD is used instead of Grimshaw's MLE refitted at every peak.
2. MLE refits every 2048 peaks (16 on BATADAL), so estimator is confounded with refit cadence.
3. Peaks from the smoothed score are not declustered.
4. The fitted shape is unbounded: the runaway reached 8.2×10^15 τ0 and Inf [expl].

W1 adds a pre-attack error of about 25 τ0.

**W8 (major, answered inadequately). The silent-poisoning claim rests on weak evidence.** The attacker is an unbounded score-level attacker, the terminal bump is only 5% above τ0, and the data are exploratory. The physical frog has 4 placements per release and was not silent on HAI 23.05 (189.5 alarm steps under frozen [expl]). H3 could not be run, and there is no dose-response.

**W9 (major, answered inadequately). Recall is compared at unmatched operating points.** On HAI 20.07 the frozen threshold was in alarm 39% of the time against 0.2% for the tracker [post-hoc]. Under onset counting tracker_slow becomes +0.03 [−0.18, 0.24] [post-hoc]. There is still no matched-false-alarm or ROC/AMOC comparison.

**W10 (major, answered inadequately). The secondary datasets do not show the mechanism.** Sec. 6.2 now reports HyGrid onset recall: frozen 3/91, tracker 8/91 (+0.05 [0.00, 0.11]), slow tracker 5 [post-hoc; matches the file]. It says the reversal "measures how alarms merge across back-to-back attacks more than what the threshold detects". I agree, but the argument applies equally to the *registered* any-alarm count: a single long frozen alarm episode spanning back-to-back attacks credits every attack it covers. HyGrid therefore cannot count as a replication, yet the abstract still says "the same loss appeared on HyGrid-ICS". The supporting facts:

- tracker onset inflation on HyGrid is only 1.02 [reg tt1];
- 83% of HyGrid's final rows are attack-labelled [post-hoc], and 64% of voraus-AD's final samples are anomalous;
- HyGrid's 19.2 false-alarm episodes per day amounts to 2 episodes.

**W11 (major, confirmed). Evidence types are mixed, there is no multiplicity control, and one abstract sentence is mislabelled.** "Seven datasets" pools development, post-hoc and registered data, and "lost recall on at least one" is an uncorrected union. The abstract's "fed only the attack samples, the tracker lost exactly as much" is post-hoc but appears before the word "Post-hoc". "Exactly" fails on BATADAL (7/14 against 6/14 [post-hoc]).

**W12 (major, unanswered). Registered secondaries are still omitted.**

- S1 half-split: tracker 0.474 → 0.579, tracker_slow 0.579 → 0.842 [reg tt1].
- E5: 1 usable placement.
- S4 permits: spread −0.26 [−0.39, −0.13], shift −0.11 [−0.21, −0.03] [reg tt1].
- BATADAL frog variants: MLE SPOT 0.7 against control 0.9 [reg tt1b].

Sec. 7.3's 6-h proximity framing is superseded by Proposition 1: on BATADAL all 14 attacks are isolated, and the tracker still missed 8.

**W13 (minor).** Table 1 understates SPOT's learning region: values ≤ t lower z_q.

**W14 (minor).** Registration timestamps exist only in self-hosted git, and gates are recomputed only for HAI 20.07.

**W15 (minor, answered adequately).** SPOT on voraus-AD has about 4 peaks (FPR 0.32 [post-hoc]).

**W16 (checked, not supported).** There is no access-order problem, and the new numbers match the files, except N6. Not verifiable without the trajectory CSV (not loaded): 0.4% and 3.2% time below τ0, the 17-h stretch of test2, and the tracker at 5.25 τ0 before the first attack.

###### New weaknesses introduced by the revision

**N1 (major, answered inadequately). The HAI 20.07 primary result is not robust, and the G3 pass masks a miscalibrated baseline.**

- **The opening alarm:** D1 stood above τ0 for the first 23.8 h of test1 [post-hoc]. The frozen threshold was in alarm for 39% of unlabelled time, and 10 of its 36 detections began inside running alarms.
- **Under onset counting:**
  - tracker −0.16 [−0.37, 0.05];
  - tracker_slow +0.03 [−0.18, 0.24];
  - only daily recalibration keeps a clear loss, −0.40 [−0.55, −0.24] [post-hoc].
- **G3** (2.23 episodes per day [reg tt1]) passes only because the episode metric counts a 24-h alarm once.

All of this is disclosed (Sec. 6.2, Sec. 8 items 3 and 5, Sec. 9), but the abstract, Contribution 2 and Sec. 10 still lead with −0.42 and its causal reading. The metric-robust registered evidence is now BATADAL alone: 14 events, with the η confound of W3.

**N2 (major, confirmed). The attacks-only rerun does not identify the cause, and the paper now contradicts itself.**

- **The effect is overdetermined.** 2817 exceedance steps (about 47 min) lift the tracker to about 20 τ0, after which it needs more than 40 days to come back [post-hoc; reviewer arithmetic].
- **The benign source alone already does much of the damage.** Unlabelled-only gives −0.21 [−0.34, −0.08] [post-hoc].
- **The paper now contradicts itself.** The revised Fig. 2 caption says the unlabelled opening stretch "lifted the tracker to 5.25 τ0 before the first attack", which is benign poisoning. Sec. 7.3 still opens with an unqualified "Attacks are what raise the tracker".
- **The transient analysis is still unreported.** `posthoc_transient.json` shows that hiding the opening run recovers 5 tracker and 6 tracker_slow detections: tracker −0.29 [−0.45, −0.16], tracker_slow −0.08 [−0.18, 0.00] [post-hoc].

The paper should report it, reconcile the caption with Sec. 7.3, and separate the sources with an order-permutation or factorial rerun.

**N3 (minor). Proposition 3 holds only for the registered recall definition.** It is correct for any-alarm recall but not for onset recall: a lower threshold can open an episode before the event starts. "On any input and against any attacker" should be restricted accordingly.

**N4 (minor). Propositions 1–2 are over-interpreted or under-specified in places.**

1. "23 attack-free hours" should read "exceedance-free".
2. "Whatever η" holds for recovery time only. "Which is why [tracker_slow] lost recall too" does not follow (−0.24 against −0.42 [reg tt1]; none under onset counting [post-hoc]).
3. Proposition 2 needs a stated quantile convention and non-overlapping windows.
4. The integrality check verifies the code, not the proposition.

**N5 (minor, partly fixed). Status labels are incomplete.** `memory_check.json` has no status field, and Sec. 3.1's empirical sentences are not labelled post-hoc. The Fig. 2 caption now describes the opening alarm.

**N6 (minor). The Fig. 2 caption conflicts with the record.** It says the score stays above τ0 "for the first 23.8 h of test1 with no attack label". The alarm-time file instead describes that opening run as "23.8 h with 7 attacks", and its counts fit attacks inside running alarms: frozen detects 26 in test1 under any-alarm counting, 18 under onset counting [post-hoc]. If "no attack label" means only the stretch before the first attack, the caption should say so and give its length.

##### 4. Questions for the authors

1. What is z_q/τ0 for SPOT and DSPOT at t = 0 on each BATADAL file? Given the unlabelled-only reruns, will you withdraw "days-long attacks inflate SPOT and DSPOT"?
2. What caused the 23.8-h opening alarm on HAI 20.07 test1? How many attacks fall inside it, and how long is the attack-free part before the first one (cf. N6)?
3. Will you report `posthoc_transient.json` and every other post-hoc variant, and reconcile Sec. 7.3 with the Fig. 2 caption?
4. Can you separate attack-driven from transient-driven exceedances, for example by permuting the order of exceedance blocks?
5. Will you report H2 with an exact interval, relabel G1 consistently with H3, and qualify G3 by time in alarm?
6. Will you report the registered S1, E5, S4 and BATADAL frog-variant results, and present HyGrid as uninformative under both counts?
7. Can you run the extreme-value analyses with matched refit cadence, runs declustering and a bounded shape, and add a frog dose-response?
8. Will you add a block or stream-level bootstrap?

##### 5. Assessment

The revision adds sound analytic content and honest post-hoc checks. Those checks, however, move the evidence against both registered headline claims:

- **HAI 20.07:** the tracker's loss is not robust once the frozen threshold's long opening alarm is not credited (N1).
- **Attribution:** the attacks-only rerun cannot attribute the loss to attacks, and the revised caption concedes a benign contribution (N2).
- **BATADAL extreme-value inflation:** it occurs with no attack in the update (W1).

What remains well supported:

- Proposition 3, at a measured cost of 2.43× budget [reg tt1b].
- The BATADAL tracker loss [reg tt1b], confounded by η.
- The exploratory pulse and frog results, with the caveats of W7 and W8.

**Score 2, confidence 4.**

##### 6. What would change my score

- **Toward 3:**
  1. Correct the BATADAL extreme-value attribution, with z_q at t = 0 (W1).
  2. Put the onset result and the 39% alarm share next to G2 and G3 in the abstract and contributions, and drop the causal "because earlier attacks" wording for HAI 20.07 (N1).
  3. Report the transient analysis, reconcile Sec. 7.3 with Fig. 2, and fix the "no attack label" wording (N2, N6).
  4. Label the attacks-only abstract sentence post-hoc (W11).
  5. Use an exact H2 interval and treat G1 like H3 (W5, W6).
  6. Report the omitted registered secondaries (W12).
  7. Present HyGrid as uninformative (W10).
- **Toward 4:**
  1. Run a source-separating tracker design (N2).
  2. Fix the extreme-value implementation and test declustering, with a frog dose-response (W7, W8).
  3. Use stream- or block-level resampling (W4).
  4. Add SWaT/WADI results.

*Suggested related work (from reviewer's own knowledge, not checked):*

- Grimshaw (1993), MLE of the GPD.
- Coles (2001); Ferro and Segers (2003), extremal index and declustering.
- Angelopoulos, Candès and Tibshirani (2023), conformal PID control and quantile tracking.
- Zaffran et al. (2022), AgACI; Bhatnagar et al. (2023), SAOCP.
- Bates et al. (2023), conformal p-values for outlier detection.
- Barreno et al. (2006); Nelson et al. (2008).
- EEMUA 191 alongside ISA-18.2.

---


### R3: systems-security generalist (threat models, baselines, claims against evidence)

**Overall score: 2 / 5. Reviewer confidence: 3 / 4.**

#### ASIA CCS 2027 review (updated): "Thresholds That Travel: Adaptive Alarm Thresholds Let Attacks Through in ICS Anomaly Detection"

**Reviewer:** R3 (systems security, generalist)  **Overall score:** 2 (weak reject, unchanged)  **Confidence:** 3

##### Changes since the first version
**Update for the second, small revision** (main.tex sha256 prefix 62d4fb1eee94; result files unchanged). Two passages changed, and I re-checked both against `results/`:
- **Sec 6.2 now reports the HyGrid-ICS onset counts:** frozen 3/91, tracker 8 (+0.05 [0.00, 0.11]), slow tracker 5 (post-hoc). All match `posthoc_alarm_time.json`. The paper's reading, that the stricter count mostly measures alarm merging across back-to-back attacks, is plausible. This answers the HyGrid sub-point of W5, but W5 stays open because the abstract is unchanged.
- **The Fig. 2 caption now attributes the first tracker lift (to 5.25 tau0, post-hoc, not checkable from results/) to an unlabelled 23.8 h opening stretch.** That strengthens N1 and N3: on the primary dataset, the first inflation was not caused by an attack.
- **New N4 (minor):** the caption's 'no attack label' conflicts with the authors' own record, which describes that same 23.8 h opening run as containing 7 attacks.

The score is unchanged.

I re-read the revised paper in full (main.tex, 50,942 bytes). I also read the three new result files (`threshold_transfer_tt1_memory_check.json`, `..._posthoc_alarm_time.json`, `..._posthoc_transient.json`, all post-hoc) and the updated verifiers. Both verifiers still pass (tt1 27/27, tt1b 8/8), and the new reopenings are ledgered as post-hoc.

**What the revision fixes:**
- **W2 is resolved.** The new Proposition 3 states and proves that tighten-only's recall property holds by construction, and the abstract and conclusion now present the rule's false-alarm cost as the empirical result.
- **W3 is half resolved.** Propositions 1-2 add the analytic memory bound I asked for.
- **W10 is half resolved.** An adequate Ethical considerations appendix has been added.
- **Time in alarm is now reported.** The new post-hoc paragraph in Sec 6.2 reports time in alarm and onset recall honestly.

**What that new paragraph exposes (new weakness N1, major):**
- On the primary dataset, HAI 20.07, the frozen threshold was in alarm for 39% of unlabelled time.
- Under onset counting, the tracker's gap shrinks to -0.16 [-0.37, 0.05] and tracker_slow's to +0.03 (post-hoc).
- So the registered core finding is robust to the scoring rule only on BATADAL, which has 14 attacks.

**Still unchanged:** the abstract, introduction and conclusion have not been re-weighted. The closed-loop frog claim is still stated without an exploratory label (W1). The omitted registered permit and E5 results (W6), the threat model (W7), related work (W8), the SPOT estimator choices (W9) and the placeholder artifact link (W10) are all as before.

**New minor issues:** scope limits of the propositions (N2), and the lead sentence of Sec 7.3 plus one unreported ledgered sensitivity analysis (N3).

**Net effect:** the paper is more candid but its evidence base is narrower, so the score stays at 2.

*Data-status tags:* **[reg-tt1]**, **[reg-tt1b]** = registered; **[expl]** = exploratory development data on the spent HAI releases; **[post-hoc]** = after the registered finals.

##### Paper summary
The paper studies adaptive alarm thresholds for ICS anomaly detectors: daily recalibration, ACI-style symmetric quantile tracking, SPOT/DSPOT extreme-value refitting, and a tighten-only rule, all against a threshold frozen after calibration. It introduces the *learning region* of a rule (the score values that move its future thresholds) and argues that each region is an attack surface. Real attacks inflate exceedance learners. Nuisance pulses do so deliberately. A closed-loop attacker holding the score just under the threshold inflates SPOT/DSPOT silently. A new Sec 3.1 derives how long the tracker and daily recalibration "remember" an exceedance as a function of the calibrated rate p alone, and proves that tighten-only never loses recall. The evidence comes from two pre-registered, one-access studies with verifiers: tt1 (HAI 20.07 primary, HyGrid-ICS and voraus-AD secondary) and tt1b (BATADAL; registered primary rule failed). Exploratory work on spent HAI releases supplies the attack experiments, and new post-hoc analyses cover time in alarm and attribution. The paper recommends that thresholds may tighten automatically but loosen only with operator approval.

##### Strengths
1. **Exemplary registration discipline.** Code is frozen by hash, a ledger allows one access per dataset, and the verifiers pass (27/27 and 8/8). Every new post-hoc reopening is listed in the verifier output.
2. **Candour.** The revision reports, unprompted, the post-hoc finding that weakens its own primary result: "G2 stands as registered, but the tracker's HAI 20.07 gap depends on crediting the frozen threshold's long alarms" (Sec 6.2). Failed and uninformative registered tests (H3, G1) are reported as such.
3. **A correct and useful analytic core (new).** Propositions 1-2 explain the losses from the update rules. With p = 7.2e-4/s, a tracker needs 1,385 quiet steps per exceedance step (about 23 h per exceedance minute), and from the levels it reached it would need 43-209 days to return to tau0. These figures match `memory_check.json` [post-hoc arithmetic]. Proposition 3 correctly turns tighten-only from an empirical claim into a theorem, so its evaluation becomes a cost measurement.
4. **A robust registered replication on BATADAL.** The tracker caught 6/14 against 14/14 for frozen, -0.57 [-0.79, -0.29] [reg-tt1b], and the onset count changes nothing [post-hoc]. tracker_slow lost at the same episode budget as frozen: 5/14 vs 14/14 [reg-tt1b], with alarm time 0.52% vs 1.37% [post-hoc].
5. **Numerical fidelity.** I checked every new number against the files: 39%, 26/38, -0.16 [-0.37, 0.05], +0.03, 11/38 with -0.40, 1.4%, 4.1%, the 0.2%/0.3%/0.4% tracker alarm shares, the attacks-only and unlabelled-only counts, 1,385, 133, 33 h, 64 s, 43-209 days and 7e-6. All match. The first-round checks of about 40 numbers still hold. A few new statements cannot be checked without the trajectory CSV, which I was told not to load (see N2).

##### Weaknesses
Each item gives severity, status with the revised section number, and the evidence checked. W-numbers carry over from the first round; N1-N3 came with the first revision and N4 with the second.
**W1 (major; status: answered in paper inadequately; location: Abstract para 3; Sec 1 bullet 3; Sec 7 header (labelled exploratory there); Sec 7.6-7.7 (Tables 8-10); Sec 10).** [Unchanged in revision.] The closed-loop ('silent') poisoning claim rests only on exploratory data, yet the abstract states it without a label: the attacker 'drove their thresholds upward without raising one alarm and blinded them within an hour'. The Sec 1 bullet ('no alarm is ever raised') and the Sec 10 conclusion repeat it. The only registered test of the frog (tt1b H3) could not be evaluated. The registered secondary frog result for MLE SPOT on BATADAL shows a small effect. The physically realizable frog did not blind DSPOT, and it raised many alarms on one release.

*Evidence checked:* results/threshold_transfer_tt1b_result_batadal.json gates.H3_frog_blinds_dspot_not_frozen_or_tighten_only=false, H3_placements=10 (registered tt1b). figure_data/attack_campaigns.csv, batadal closed_24h D1 (registered tt1b secondary): dspot 0.0 after / 0.0 control; spot_mle 0.7 after / 0.9 control. results/threshold_transfer_tt1b_physfrog_dev_v1.json (exploratory): dspot after 1.0/0.75/0.5, control 0.75/1.0/0.5 (x4 placements), i.e. 9/12 vs 9/12; hai-23.05 median_campaign_alarm_steps 189.5 (frozen), 171 (spot), 153.5 (spot_mle), 61 (dspot). Revised main.tex abstract para 3, Sec 1 bullet 3 and Sec 10 are unchanged on this point.

**W2 (minor; status: answered in paper adequately; location: Abstract; Sec 1; Sec 3.1 (Prop. 3); Sec 8; Sec 10).** [Resolved in revision; severity lowered from major.] The first version presented tighten-only's recall equality as an empirical finding. The revision states and proves that it holds by construction (Proposition 3, Sec 3.1). The abstract now says the rule 'cannot miss an event the frozen threshold catches, on any input', with cost 2.43x vs 0.70x the budget on BATADAL. Sec 3.1 says the tighten-only results 'measure its cost, not its recall'. The conclusion is consistent with this. Residual scope issues with Proposition 3 are covered under N2.

*Evidence checked:* Revised main.tex abstract para 3, Sec 1 (para after the bullets), Sec 3.1 Proposition 3, Sec 8 item 1, Sec 10. Numbers check: figure_data/recall_and_false_alarms_by_rule.csv batadal one_sided:none fa_ratio_to_budget 2.427161 vs frozen 0.70118 (registered tt1b); voraus-ad one_sided:none fpr 0.081146 = frozen (registered tt1).

**W3 (major; status: answered in paper inadequately; location: Sec 1 para 1; Sec 2 'Threshold rules'; Sec 3.1 (Props 1-2); Sec 4 'Rules').** [Partly addressed.] Propositions 1-2 now give the analytic memory of the tracker and of daily recalibration, which I asked for. The core finding is now shown to follow from the update rules: each exceedance step costs (1-p)/p quiet steps, whatever eta. That makes the empirical result more convincing. It also confirms that the rules tested are the naive variants that feed alarmed values back into the threshold. The stronger adaptive baselines a practitioner would use are still absent: recalibration that excludes alarmed or post-alarm windows, a hold-off that freezes adaptation during and after alarms, clipped or robust tracker updates, Telemanom with pruning (cited in Sec 1, not run), and drift-gated recalibration. Nor is there any citation for the claim that 'deployments often let it adapt' in the naive form.

*Evidence checked:* results/threshold_transfer_tt1_memory_check.json (post-hoc, arithmetic on stored fields): hai-20.07 recovery_steps_per_exceedance_step 1385.14, recovery_hours_per_exceedance_minute 23.09; batadal 132.85 and 33.21 h per step. These agree with my first-round arithmetic (p=7.214e-4, eta=0.1227 from threshold_transfer_tt1_result_hai-20.07.json, registered tt1). A grep of revised main.tex finds no new baseline rule; protocol threshold_rules is unchanged.

**W4 (major; status: answered in paper inadequately; location: Sec 6.2 (new post-hoc paragraph); Sec 6.3 (Table 5 and text)).** [Partly addressed; the new data make it sharper.] Recall is compared at unmatched operating points.
- The revision adds time in alarm (post-hoc): on HAI 20.07 the frozen threshold was in alarm for 39% of unlabelled time, against 0.2% for the tracker and 1.6% for tracker_slow.
- My first-round argument that tracker_slow gives a matched-false-alarm comparison on HAI 20.07 (same 2.23 episodes/day) therefore no longer holds: matched episodes are not matched alarm time.
- On voraus-AD, tracker_slow still matches the static margin's recall at less than half its FPR.
- Only BATADAL now offers a roughly matched comparison (tracker_slow 0.52% vs frozen 1.37% alarm time, same 0.70x episode budget).
The paper still gives no recall at a matched operating point, for instance frozen re-thresholded to each adaptive rule's realised alarm time. Sec 6.3 still says the adaptive rules 'bought [fewer false alarms] with the recall losses'.

*Evidence checked:* results/threshold_transfer_tt1_posthoc_alarm_time.json (post-hoc) hai-20.07.baseline.rules: frozen unlabelled_alarm_share 0.391, tracker 0.00177, tracker_slow 0.01558, fa_episodes_per_day 2.225 for both frozen and tracker_slow; batadal frozen 0.01368, tracker_slow 0.00518, fa 0.1002 for both. figure_data/recall_and_false_alarms_by_rule.csv voraus-ad (registered tt1): tracker_slow recall 0.213245 fpr 0.01432; margin recall 0.211921 fpr 0.033413.

**W5 (major; status: answered in paper inadequately; location: Abstract para 2; Contribution 2; Sec 6.2 (HyGrid onset counts, second revision); Sec 7.3; Sec 9 bullet 2; Sec 10).** [Partly addressed; HyGrid onset counts added in the second revision.] The new post-hoc attacks-only run (Sec 7.3) shows that on HyGrid-ICS attack samples alone reproduce the tracker's loss (14/91). That helps attribution. It does not show the paper's mechanism, a threshold inflated at the next attack's onset. In that same attacks-only run the HyGrid tracker's median onset inflation is 0.998. The loss comes from within-attack or adjacent-attack rises in a stream where 83% of rows are attack-labelled and attacks are about 100 s apart. Under the onset count the HyGrid tracker beats frozen. The second revision now reports this in Sec 6.2 (frozen 3/91, tracker 8, +0.05 [0.00, 0.11], slow tracker 5) and explains, plausibly, that on back-to-back attacks the stricter count measures alarm merging more than detection. That sub-point is answered. The abstract still says 'the same loss appeared on HyGrid-ICS and voraus-AD' and that daily recalibration lost recall, but daily equals frozen on HyGrid. voraus-AD (anomalies, not attacks) is absent from the attacks-only analysis, yet the conclusion still says 'missed attacks' on four never-opened datasets.

*Evidence checked:* results/threshold_transfer_tt1_posthoc_alarm_time.json (post-hoc): hygrid-ics.attacks_only.rules.tracker detected 14, median_onset_inflation 0.99799; baseline tracker onset_detected 8 vs frozen 3, paired tracker_vs_frozen_onset +0.055 [0.0, 0.110]. figure_data/recall_and_false_alarms_by_rule.csv hygrid-ics daily diff 0.0 (registered tt1). threshold_transfer_tt1_posthoc.json final_attack_fraction 0.826. Second revision (main.tex sha256 62d4fb1eee94) Sec 6.2: frozen 3, tracker 8 (+0.05 [0.00, 0.11]), slow tracker 5 match posthoc_alarm_time.json hygrid-ics.baseline onset_detected 3/8/5 and paired tracker_vs_frozen_onset +0.0549 [0.0, 0.1099] (post-hoc). The abstract's 'same loss appeared on HyGrid-ICS and voraus-AD' is unchanged.

**W6 (major; status: confirmed; location: Sec 4 'Rules' (eleven rules); Table 4; Sec 8 para 1).** [Unchanged.] Registered results are still omitted, although the protocol requires every rule to be reported. The four tighten-only rules with automatic permits (registered secondary S4) all lost recall on the real HAI 20.07 attacks, with intervals below zero, and on voraus-AD. Sec 8 still attributes the permit failures only to 'pulses and benign drift' seen in development. The registered E5 result is also not reported: 1 usable placement, none of 12 others stealthy.

*Evidence checked:* results/threshold_transfer_tt1_result_hai-20.07.json real_events.paired (registered tt1): one_sided:spread -0.263 [-0.395,-0.132]; spread6 -0.211 [-0.342,-0.079]; shift -0.105 [-0.211,-0.026]; shift6 -0.132 [-0.237,-0.026]. E5_noise_campaign placements_used=1, placements_without_stealthy_level=12. A grep of revised main.tex for 'one\_sided:spread', '0.684' and 'E5' returns no hits.

**W7 (major; status: answered in paper inadequately; location: Sec 3 (A0-A2); Sec 3.1 (Prop. 1 partly answers c); Sec 9 bullet 3; Ethical considerations appendix).** [Unchanged.] The threat model is not fully coherent.
(a) A2 reads tau_t, runs the monitor and spoofs three sensors. Such an attacker could conceal the terminal attack directly (Erba et al., cited; Urbina et al. CCS'16, from reviewer's own knowledge, not checked). The paper never says what poisoning the threshold adds.
(b) A1's 12 extra alarm episodes a day are six times the 2/day budget, and frozen alarms on 92% of the pulses. Assuming operators ignore them conflicts with the ISA-18.2 targets the paper cites.
(c) A0 relies on benchmark attack density. BATADAL, where all attacks are isolated, partly answers this, and Proposition 1 now explains why a single detected incident suffices.
The new Ethical considerations appendix does not address (a) or (b).

*Evidence checked:* results/threshold_transfer_tt1_result_hai-20.07.json E4_pulse_campaign.rules.frozen.pulse_alarm_frac=0.9167 (registered tt1). figure_data/recall_and_false_alarms_by_rule.csv hai-20.07 n_close=31/n_isolated=7 (post-hoc); batadal n_close=0/n_isolated=14, tracker 6/14 (registered tt1b).

**W8 (major; status: confirmed; location: Sec 2; Sec 3.1; Contributions 3-4; Sec 8).** [Unchanged; arguably sharper.] Novelty over prior work is modest and the related work has not grown.
- Proposition 1 makes explicit that natural poisoning is a direct consequence of the quantile-tracker update and of ACI's rate guarantee, which the paper concedes in Sec 2.
- A concurrent preprint (arXiv:2609.23254, 'The Price of Self-Calibration: Exact Evidence Budgets and Manufactured Blind Sets in Adaptive Monitoring', 2026) appears to derive closely related absorption boundaries for adaptive monitors. It is not cited.
- The closed-loop frog is the online-centroid / boiling-frog attack (Kloft & Laskov; Chan-Tin et al.) applied to a 1-D EVT threshold.
- The design rule matches ISA-18.2 management-of-change for alarm setpoints (reviewer's own knowledge, not checked).
Still missing (all from reviewer's own knowledge, not checked): Urbina et al. CCS'16; Kravchik & Shabtai's later poisoning paper (arXiv:2012.15740), which reports successful poisoning for some SWaT attacks, so the paper's 'resisted' is too strong; Barreno/Huang on causative attacks; adaptive threshold tuning in IDS (Ali, Khayam et al., ACM TISSEC 2013); threshold-learning poisoning in smart grids (CPSS 2022).

*Evidence checked:* latex/refs.bib last modified 2026-10-24 (unchanged; no '2609' or 'Urbina' entries). The revised Sec 2 'Poisoning of anomaly detectors' is unchanged. arXiv:2609.23254 and the CPSS'22 item were seen only in web-search snippets, not read.

**W9 (major; status: answered in paper inadequately; location: Sec 4 'Rules'; Sec 7.1; Sec 7.6; Sec 9 bullet 4).** [Unchanged.] The SPOT/DSPOT conclusions depend on non-canonical estimator settings.
- 'SPOT (moments)' and DSPOT use method-of-moments GPD fits, which are unreliable for heavy tails. Thresholds above 1e15 tau0 look like estimator divergence.
- Siffer et al.'s reference SPOT uses Grimshaw MLE (reviewer's own knowledge, not checked).
- The MLE variant here refits only every 2048 peaks (16 at 15 min), which makes it nearly static. This confounds both 'escapes natural poisoning' and the size of the frog effect.

*Evidence checked:* results/threshold_transfer_tt1b_frog_dev_v1.json hai-21.03 closed_24h spot median_inflation 8.25e15, dspot 2.05e15 (exploratory). protocols/threshold_transfer_tt1b_protocol.json rules: spot = moments GPD; spot_mle refit every 2048/16 peaks; dspot = moments GPD.

**W10 (major; status: answered in paper inadequately; location: Sec 1 Contribution 5; Ethical considerations appendix; Open science appendix).** [Partly addressed.] An Ethical considerations appendix has been added. It is adequate: offline public data, no live systems, and the defence is a configuration change. The anonymized artifact link is still the placeholder 'https://anonymous.4open.science/...' in Contribution 5 and in the Open science appendix, so reviewers cannot inspect the ledger, verifiers or the new post-hoc result files on which the revision leans. Until it is replaced, this is a desk-reject risk under the ASIA CCS Open Science requirement. The D1 monitor is still cited as '[anonymized]' prior work.

*Evidence checked:* Revised main.tex: \url{https://anonymous.4open.science/...} with TODO comments (Contribution 5; Open science appendix); new section* 'Ethical considerations'. The first-round .tex/.bib identifier search (0 hits) was not repeated on the revision; refs.bib is unchanged.

**W11 (minor; status: answered in paper inadequately; location: Abstract; Sec 7 header and 7.2; Sec 10).** [Partly addressed.] The abstract now labels the onset-recall result 'Post-hoc'. Other claims still mix evidence tiers without a label:
- 'fed only the attack samples, the tracker lost exactly as much' is post-hoc but unlabelled.
- 'with a second, model-free score' is post-hoc on the tt1 datasets, exploratory on the spent releases, and registered only on BATADAL.
- 'three earlier HAI releases' is exploratory.
- 'seven datasets' pools registered, post-hoc and exploratory results.
- 'never-opened' is true of test data only (the HAI 20.07 training data was used for development, as the access log discloses).
Sec 7.2 now lists the BATADAL D0 interval, which is registered tt1b secondary, under a section headed '(exploratory)'.

*Evidence checked:* results/threshold_transfer_tt1_posthoc_alarm_time.json status 'post-hoc analysis after the registered tt1 and tt1b finals (not registered)'. figure_data/recall_and_false_alarms_by_rule.csv D0 status labels: post-hoc for hai-20.07/hygrid/voraus, registered tt1b for batadal (tracker [-0.857,-0.357]). protocols/threshold_transfer_tt1_data_access.json hai-20.07.seen_so_far.

**W12 (minor; status: answered in paper inadequately; location: Sec 6.2; Sec 6.3; Sec 8 items 3 and 5).** [Partly addressed; reframed.] The first version never showed the benefit side of adaptation. The revision's own post-hoc data now show it on the primary dataset. The frozen threshold that 'travelled' (registered G3, 2.23 episodes/day) was in alarm for 39% of unlabelled time, including the first 23.8 h of test1. An operator would recalibrate such a threshold, which is exactly the adaptation the paper warns against. Sec 8 now recommends offline recalibration and budgeting alarm time (items 3 and 5). That is sensible, but offline recalibration is evaluated nowhere, and its own exposure to attack data is not discussed.

*Evidence checked:* results/threshold_transfer_tt1_posthoc_alarm_time.json hai-20.07 frozen unlabelled_alarm_share 0.391 (post-hoc). results/threshold_transfer_tt1_posthoc_transient.json opening_run_seconds 85689 for test1 (post-hoc). results/threshold_transfer_tt1_result_hai-20.07.json gates.G3_frozen_fa_per_day 2.225 (registered tt1).

**W13 (minor; status: answered in paper adequately; location: Sec 6.1).** [Unchanged.] Registered G1 passed but is uninformative, since the controls were already blind. The paper says so plainly. Together with H3, neither registered attack test confirms an attack effect, and this should be stated explicitly in one place.

*Evidence checked:* results/threshold_transfer_tt1_result_hai-20.07.json E4_pulse_campaign daily/tracker/tracker_slow terminal_detected_control 0.0 (registered tt1).

**W14 (minor; status: confirmed; location: Table 10; Sec 7.6; Sec 1; Sec 1 bullet 1).** [Unchanged.] Presentation and accuracy details:
(i) Table 10 still lists DSPOT as '9 / 9' under a '12 placements' header; the file gives 9/12 after and 9/12 in the control.
(ii) The light-tail synthetic control: MLE SPOT also missed 1 of 5 seeds in the 24 h, 6 h and fixed variants, which the text omits.
(iii) Sec 1 still says 'none of the adaptive rules we tested is safe', while the paragraph that follows declares the adaptive tighten-only rule safe by construction.
(iv) '16 of [18 misses] caught by frozen' cannot be checked from the stored fields.
(v) No multiplicity correction is applied across the many secondary comparisons.

*Evidence checked:* results/threshold_transfer_tt1b_physfrog_dev_v1.json dspot after/control; results/threshold_transfer_tt1b_frog_synthetic_v1.json spot_mle terminal_after_campaign 0.8 (closed_24h, closed_6h, fixed_24h).

**N1 (major; status: answered in paper inadequately; location: Abstract para 2; Sec 1 bullet 1; Contribution 2; Table 3 (G3); Sec 6.2; Fig. 2 caption (second revision); Sec 6.3; Sec 10).** [New; introduced by the revision's own data.] On the primary dataset, natural poisoning is no longer robust.
- The new post-hoc onset count credits an attack only if an alarm episode starts inside it. On HAI 20.07 the tracker's gap shrinks from -0.42 to -0.16 [-0.37, 0.05], which includes zero, and tracker_slow is +0.03 [-0.18, 0.24].
- The reason is that the frozen threshold was in alarm for 39% of unlabelled time, so 10 of its 36 detections were attacks that began inside an alarm already running.
- The registered G2 still stands, and the paper says plainly that 'the tracker's HAI 20.07 gap depends on crediting the frozen threshold's long alarms'.
The headline claims have not been re-weighted. The abstract still leads with -0.42 'because earlier attacks had raised its threshold'. It still says the 'ten times slower tracker also lost recall', which is false under the onset count on HAI 20.07. Sec 1 bullet 1, Contribution 2 and the Sec 6.3 sentence about recall losses are unchanged. Registered G3 is still reported as a plain 'pass'. As a result, the registered evidence that is robust to the scoring rule now rests on BATADAL alone: 14 attacks, onset count unchanged, -0.57 [-0.79, -0.29]. The second revision's Fig. 2 caption adds a further point. It says the unlabelled opening stretch of test1 'lifted the tracker to 5.25 tau0 before the first attack' (post-hoc). If so, the first inflation on the primary dataset came from an unlabelled score excursion during which the frozen threshold was itself in alarm, not from an attack. That further contradicts the abstract's 'because earlier attacks had raised its threshold'. N4 covers a conflict between this caption and the authors' own post-hoc record.

*Evidence checked:* results/threshold_transfer_tt1_posthoc_alarm_time.json (post-hoc), hai-20.07.baseline: frozen onset_detected 26/38 (detected 36), tracker 20, tracker_slow 27, daily 11; paired tracker_vs_frozen_onset -0.158 [-0.368, 0.053], tracker_slow_vs_frozen_onset +0.026 [-0.184, 0.237], daily_vs_frozen_onset -0.395 [-0.553, -0.237]; frozen unlabelled_alarm_share 0.391. batadal.baseline.paired tracker_vs_frozen_onset -0.571 [-0.786, -0.286]. Registered G2 in threshold_transfer_tt1_result_hai-20.07.json is unchanged (-0.421 [-0.579, -0.263]). Second revision Fig. 2 caption: 'The score stays above tau0 = 17.26 for the first 23.8 h of test1 with no attack label ... this unlabelled stretch lifted the tracker to 5.25 tau0 before the first attack'. The 5.25 figure has no field in results/; it would need the trajectory CSV, which I was told not to load, so it is unverified. Plausibility arithmetic on registered p and eta: reaching 5.25 tau0 needs about 600 s of cumulative score-above-tracker time (4.25 x 17.26 / 0.1226).

**N2 (minor; status: confirmed; location: Sec 3.1 (Props 1-3); Sec 8 para 1).** [New.] Propositions 1-3 are correct for what they state, and their numbers match the files. They need tighter scope:
(a) Prop. 1: 'a rise built from E exceedance steps' means the gross rise eta(1-p)E. When quiet steps interleave with the attack, the net rise is smaller, so E(1-p)/p is an upper bound on the recovery time.
(b) 'Keeps it raised for 23 hours' conflates full recovery with blindness. Detection resumes as soon as q falls below the next attack's score, which may be much earlier, so the 43-209-day figure is a recovery time, not a blind time.
(c) Prop. 3 holds for the registered any-alarm event metric. It need not hold for the paper's new onset metric, since a lower threshold can start an episode before the attack and merge across the gap. It also does not cover the permit variants or the oracle (operator-gated) rule, whose ceiling can rise. Sec 8 nevertheless counts 'tighten-only ... with an operator-gated one' among the rules that held.
(d) The 'integrality' check (largest deviation 7e-6 of a step) confirms that the implementation matches the update rule. It is not evidence about the data.

*Evidence checked:* results/threshold_transfer_tt1_memory_check.json (post-hoc): 1385.14, 23.09 h/min, batadal 132.85 and 33.2 h/step, predicted_days_to_return_from_final 42.6 / 59.2 / 132.9 / 208.7, max_integrality_error_tracker 7.46e-6 (tracker_slow 7.4e-5), daily_steps_above_level_to_lift_next_day 62.33 (hai; +1 gives the paper's 64 s) and 0.717 (batadal; two steps). Prop. 2 is correct under a standard empirical-quantile definition. Not verifiable from the pack without the trajectory CSV, which I was told not to load: 'below tau0 in 0.4% of minutes' (HAI) and 3.2% (BATADAL), BATADAL attack durations of 1-5 days and gaps of 1.7-24 days, and the '17-hour stretch' of test2.

**N3 (minor; status: confirmed; location: Sec 7.3; Sec 6.2; Fig. 2 caption).** [New.] Labelling and completeness of the new post-hoc analyses:
(a) The Sec 7.3 lead sentence, 'Attacks are what raise the tracker', overstates the attacks-only result. Fed only unlabelled samples, the tracker still loses on HAI 20.07: -0.21 [-0.34, -0.08], half the registered gap (post-hoc). The text concedes 'a smaller loss of their own', but the lead sentence should match. After the second revision it also contradicts the paper's own Fig. 2 caption, which credits the unlabelled opening stretch with the first lift of the tracker to 5.25 tau0.
(b) A ledgered post-hoc sensitivity analysis sits in results/ but is not reported. Hiding the 23.8 h opening transient of test1 from the threshold update cuts the HAI 20.07 gaps to tracker -0.29 [-0.45, -0.16], tracker_slow -0.08 [-0.18, 0.00] and daily -0.32. The file is marked superseded because the opening run contained 7 attacks. That rationale is plausible, but given the paper's full-reporting stance it should be mentioned in a sentence.
(c) All new analyses are correctly ledgered and the verifiers still pass. I found no labelling error in Sec 6.2 itself, and its numbers match the file.

*Evidence checked:* results/threshold_transfer_tt1_posthoc_alarm_time.json hai-20.07.unlabelled_only.paired tracker_vs_frozen -0.211 [-0.342, -0.079]; batadal.unlabelled_only tracker 11/14, -0.214 [-0.429, 0.0]; attacks_only tracker 20/38 (hai), 14/91 (hygrid), 7/14 (batadal), matching Sec 7.3. results/threshold_transfer_tt1_posthoc_transient.json status 'post-hoc ... (not registered)', opening_transient_hidden paired: tracker -0.289 [-0.447, -0.158], tracker_slow -0.079 [-0.184, 0.0], daily -0.316. The alarm_time file has supersedes: 'threshold_transfer_tt1_posthoc_transient.json (its opening run was 23.8 h with 7 attacks)'. results/threshold_transfer_tt1_verification.json (27 checks, passed) lists both post-hoc reopenings; tt1b verification (8 checks, passed) lists the BATADAL one. A grep of main.tex for 'transient' finds no hits.

**N4 (minor; status: confirmed; location: Fig. 2 caption (second revision); Sec 6.2; Sec 7.3).** [New in the second revision.] The new Fig. 2 caption conflicts with the authors' post-hoc record. The caption says the score stays above tau0 'for the first 23.8 h of test1 with no attack label', with the frozen threshold 'in alarm throughout that stretch', and that this unlabelled stretch lifted the tracker to 5.25 tau0 'before the first attack'. The record describes the same 23.8 h opening run (85,689 s) as containing 7 attacks: that is the stated reason the opening-transient sensitivity analysis was superseded. Both cannot be true. If attacks fall inside the run, 'no attack label' is wrong, and the 5.25 tau0 lift happened in an unlabelled prefix of unstated length. If none do, the supersession reason is wrong, and the unreported transient analysis (tracker -0.29, tracker_slow -0.08 [-0.18, 0.00], post-hoc) becomes a valid sensitivity result that should be reported. Either way it bears on N1 and N3: how much of the HAI 20.07 loss comes from attacks rather than benign drift. The per-stream onset counts are consistent with the record's version: 8 of frozen's 26 test1 detections were attacks that began inside an already-running alarm. They do not prove it. I could not settle this without the trajectory CSV, which I was told not to load. The authors should state the onset time of the first test1 attack and how many attack intervals fall inside the opening run.

*Evidence checked:* results/threshold_transfer_tt1_posthoc_alarm_time.json field supersedes = 'threshold_transfer_tt1_posthoc_transient.json (its opening run was 23.8 h with 7 attacks)'. results/threshold_transfer_tt1_posthoc_transient.json opening_transient_hidden.per_stream test1 opening_run_seconds 85689 (= 23.80 h). posthoc_alarm_time.json hai-20.07.baseline.rules.frozen per_stream_detected [26, 10], per_stream_onset_detected [18, 8] (post-hoc). Second-revision main.tex Fig. 2 caption text as quoted. No results/ field gives the 5.25 tau0 level or the first-attack onset time.

###### Suspicions that the files did *not* support
- *The new post-hoc analyses might have been run without a ledger entry.* Not supported. The tt1 and tt1b verifiers list every reopening as post-hoc after the finals, and both still pass.
- *The propositions might be wrong.* Not supported for what they state. Props 1-3 are correct, and their numbers match `memory_check.json`. Only their scope is at issue (N2).
- *The new Sec 6.2 numbers might be cherry-picked.* Not supported: they match `posthoc_alarm_time.json` exactly, including the unfavourable ones. The one omission is the superseded transient file (N3b).

##### Does each headline claim follow from the evidence? (revised paper)
| Claim | Evidence tier | Verdict |
|---|---|---|
| Exceedance-learning trackers lose recall because earlier attacks inflate them | reg-tt1 G2, reg-tt1b H1; post-hoc onset count | **Robust on BATADAL; fragile on HAI 20.07** (N1). The abstract now mentions the onset caveat for the tracker but not for tracker_slow |
| "Fed only the attack samples, the tracker lost exactly as much" | post-hoc | True for HAI 20.07 (20/38) and HyGrid (14/91); BATADAL 7/14 vs 6/14. Unlabelled samples alone also cost -0.21 on HAI (N3a), and Fig. 2 now credits an unlabelled stretch with the first lift; the caption conflicts with the record (N4). Unlabelled in the abstract (W11) |
| Memory set by p alone (23 h per exceedance minute) | analytic + post-hoc check | **Correct** for full recovery; not equal to blind time (N2b) |
| Tighten-only cannot miss what frozen catches | theorem (Prop. 3) | **Correct** for the registered metric; scope caveats (N2c) |
| Same loss on HyGrid-ICS and voraus-AD | reg-tt1 secondary; post-hoc onset | Loss yes, inflation mechanism no; daily shows no loss on HyGrid; under the onset count the HyGrid sign reverses, which the paper now reports (W5) |
| Pulses blind exceedance learners | expl (G1 uninformative) | Supported only as exploratory, and labelled as such |
| Closed-loop attacker silently blinds SPOT/DSPOT within an hour | expl, score level only | **Overclaimed** (W1, W9) |
| Thresholds may tighten; loosening needs a human | analytic + empirical | Sound, but close to ISA-18.2 practice (W8). The new alarm-time evidence argues for offline recalibration, which is untested (W12) |

##### Questions for the authors
1. Given N1, will you lead the abstract and introduction with BATADAL, and present HAI 20.07 as registered-but-fragile under the onset count, for tracker_slow too?
2. Can you report recall at a matched operating point, for example frozen re-thresholded to the tracker's realised alarm time on HAI 20.07 and voraus-AD?
3. Why are the registered recalls of the permit variants and the registered E5 result not reported, when the protocol requires every rule to be reported?
4. Why should a white-box sensor-spoofing attacker poison the threshold instead of concealing the terminal attack directly?
5. How do alarm-excluding recalibration, a post-alarm hold-off, a clipped tracker, Telemanom with pruning, and per-peak Grimshaw-MLE SPOT behave post-hoc?
6. Does Proposition 3 hold under your onset metric? Please state explicitly that it does not cover the permit or oracle rules.
7. Please report the opening-transient sensitivity analysis (`posthoc_transient.json`) in a sentence, with the reason it was superseded. Please also reconcile the Fig. 2 caption ('first 23.8 h ... with no attack label') with the record's 'opening run was 23.8 h with 7 attacks', giving the onset time of the first test1 attack (N4).
8. How does Proposition 1 relate to arXiv:2609.23254?
9. When will the SWaT and WADI outcomes be added, and will the paper be updated whatever they show?

##### Score and confidence
- **Overall: 2 (weak reject; unchanged).** The revision is more honest and gains a correct analytic section. Its own new evidence shows that the primary registered result depends on how alarms are counted, so the robust registered support is a single 14-attack replication. The attack claims remain exploratory, and the closed-loop claim is still unlabelled in the abstract. Registered results are still omitted, the baselines remain the naive variants, related work has not grown, and the artifact link is a placeholder.
- **Confidence: 3.**

##### What would change my score
1. Re-weight the abstract, introduction and conclusion: lead with BATADAL, state the HAI 20.07 onset fragility (including tracker_slow), and label every tier, in particular the closed-loop frog as exploratory (N1, W1, W11). With W6 also fixed, this would move me to 3.
2. Report all registered rules, including the permit variants and E5 (W6).
3. Add a matched-operating-point comparison and at least two stronger adaptive baselines, labelled post-hoc (W3, W4, W9). If natural poisoning survives these on BATADAL and HAI, I would move to 4.
4. Tighten the scope statements of the propositions (N2), fix the Sec 7.3 lead sentence and the transient omission (N3), and resolve the Fig. 2 caption-vs-record conflict (N4).
5. Justify the A2 and A1 threat-model assumptions (W7), expand the related work, including arXiv:2609.23254 (W8), and replace the artifact placeholder (W10).
6. Add the registered SWaT and WADI outcomes.

---

## Part 2. Chair's evidence audit (step 2 of the prompt)

The audit re-checks the weaknesses that drive the decision, including the reviewers' own evidence claims. Corrections to reviewers are marked **correction**.

| # | Claim (raised by) | Check (file -> field) | Status | Verdict |
|---|---|---|---|---|
| A1 | SPOT (moments) and DSPOT on BATADAL were already inflated before any attack, so "real attacks had already blinded DSPOT" (§7.6), "slow, days-long attacks also inflate SPOT and DSPOT" (abstract) and "not on days-long BATADAL attacks" (§10) are wrong (R1 W4, R2 W1) | `threshold_transfer_tt1b_result_batadal.json` -> `scores.D1.real_events.rules.{spot,dspot}.per_event[0],[7].onset_inflation` = 26.9 / 43.8 and 24.5 / 40.7 at the first attack of each test file. `figure_data/threshold_trajectories.csv` -> `tau_spot/tau0` = **49.04** and `tau_dspot/tau0` = **45.79** at t = 0 of *both* test files, falling to 26.9 / 24.5 (file 1, step 6908) and 43.8 / 40.7 (file 2, step 1344) before the first attack. `threshold_transfer_tt1_posthoc_alarm_time.json` -> `batadal.unlabelled_only`: SPOT 6/14, DSPOT 7/14 with no attack in the update | reg tt1b; post-hoc | **Confirmed and strengthened.** The two rules start about 46-49 τ0 above calibration because of the tail fit at initialisation, and decline through the test streams. H3's DSPOT control of 0/10 is an initialisation failure of the moments GPD on a heavy-tailed calibration set (spread 6461.9 against τ0 = 9.39), not attack poisoning. This is the one factual error in the paper's interpretation of a registered result |
| A2 | Tighten-only's recall equality holds by construction (R1 W7a, R2 W2, R3 W2) | Version 2 adds Proposition 3. `threshold_transfer_tt1_result_*.json` -> `one_sided:none` is identical to frozen in recall and false alarms on HAI 20.07 (36/38, 2.225/day), HyGrid-ICS and voraus-AD (FPR 0.0811). BATADAL: `fa_ratio_to_budget` 2.43 against 0.70 | reg tt1, tt1b | **Answered in v2/v3.** **Correction** to R1's first round: "identical in recall *and* false alarms on all six tt1/development datasets" does not hold for development false alarms. `threshold_transfer_dev_v2.json` HAI 23.05 E1 gives `one_sided:none@eta0.01` 5.976× against frozen 4.048× **[expl]** (4.048× at η 0.001) |
| A3 | Operator-gated loosening is credited with Proposition 3's guarantee, and the registered oracle permit contradicts it (R1 N1, R3 N2c) | `threshold_transfer_tt1_result_hai-20.07.json` -> `E4_pulse_campaign.rules.one_sided:oracle.terminal_detected_control` = 0.1, `..._after_campaign` = 0.7; frozen 1.0 / 1.0 | reg tt1 (not gated) | **Confirmed.** §1 (paragraph after the bullets) and §8 extend "by construction" to a rule whose ceiling can rise |
| A4 | BATADAL H1 is driven by a spread-scaled step (R1 W3, R2 W3) | `threshold_transfer_tt1b_result_batadal.json` -> `scores.D1.thresholds.eta` = 64.62, `tau0` = 9.393 (η/τ0 = 6.88). `memory_check.json` -> BATADAL `predicted_days_to_return_from_final` 132.9 / 208.7 | reg tt1b; post-hoc | **Confirmed.** All 14 BATADAL attacks are isolated (`n_close` = 0). The loss is the slow-recovery mechanism of Proposition 1 combined with a step of 6.9 τ0, not attacks following attacks |
| A5 | HAI 20.07: the frozen threshold was in alarm for 39% of unlabelled time; under onset counting the tracker gap is −0.16 [−0.37, 0.05] (R1 N2, R2 N1, R3 N1) | `posthoc_alarm_time.json` -> `hai-20.07.baseline.rules.frozen.unlabelled_alarm_share` 0.391, `onset_detected` 26; `paired.tracker_vs_frozen_onset` −0.158 [−0.368, 0.053]; `tracker_slow_vs_frozen_onset` +0.026 [−0.184, 0.237]; `daily_vs_frozen_onset` −0.395 [−0.553, −0.237]. BATADAL `tracker_vs_frozen_onset` −0.571 [−0.786, −0.286] | post-hoc | **Confirmed.** The paper reports these numbers (§6.2) but does not re-weight the abstract, the contributions or §10 |
| A6 | HyGrid-ICS onset count reverses the sign (R1 W8, R2 W10, R3 W5) | `posthoc_alarm_time.json` -> `hygrid-ics.baseline`: frozen 3/91, tracker 8/91, `tracker_vs_frozen_onset` +0.055 [0.0, 0.110] | post-hoc | **Confirmed; disclosed in v3 §6.2.** R1's "the paper calls this not informative without the numbers" refers to version 2 and is answered in version 3. The abstract's "the same loss appeared on HyGrid-ICS" is unchanged |
| A7 | Fig. 2 caption: "the score stays above τ0 for the first 23.8 h of test1 with no attack label" (R2 N6, R3 N4) | Trajectory CSV (HAI 20.07 test1): score above τ0 for the first 1,429 minutes (23.8 h). **7 attack intervals begin inside that run, the first at minute 160 (2.7 h).** Tracker/τ0 = 5.02 on the last row before the first attack and 5.25 on the first attack-labelled row. `posthoc_alarm_time.json` -> `supersedes`: "its opening run was 23.8 h with 7 attacks" | post-hoc | **Confirmed: the caption is wrong.** Only the first 2.7 h are unlabelled. The 5.25 τ0 figure is the value at the onset row, not "before the first attack" |
| A8 | Four new numbers are untraceable: 0.4% and 3.2% of time below τ0, "most of a 17-hour stretch of test2", BATADAL attacks of "one to five days" (R1 N3; R2 and R3 marked them unverified) | Trajectory CSV: one_sided:none below τ0 in 0.43% of HAI 20.07 minutes; BATADAL tracker (and one_sided:none) below τ0 in 3.2% of steps; longest test2 run above τ0 is 1,030 min (17.2 h), with 44% of test2 minutes above τ0; BATADAL attack durations 1.0-4.58 days | post-hoc | **Correction: not supported.** All four can be traced to `figure_data/threshold_trajectories.csv`. What remains is that §3.1 does not label them post-hoc |
| A9 | Registered outcomes are omitted from the paper (R1 W9, R2 W12, R3 W6) | `threshold_transfer_tt1_result_hai-20.07.json`: S4 permit rules `one_sided:spread` −0.263 [−0.395, −0.132], `spread6` −0.211, `shift` −0.105 [−0.211, −0.026], `shift6` −0.132; S1 halves tracker 0.474 -> 0.579, tracker_slow 0.579 -> 0.842; E5 `placements_used` 1 (12 without a stealthy level); oracle E4 (A3). BATADAL frog variants: MLE SPOT 24 h 0.7 against control 0.9 (D1), 0.0 against 0.4 (D0). Protocol `gates.reporting`: "Every rule, dataset, gate and failure is reported" | reg tt1, tt1b | **Confirmed.** None of these appears in v3 `main.tex` |
| A10 | An unreported post-hoc sensitivity analysis (R1 W9, R2 N2, R3 N3b) | `posthoc_transient.json` -> `opening_transient_hidden`: tracker 25/38, −0.289 [−0.447, −0.158]; tracker_slow 33/38, −0.079 [−0.184, 0.0]; daily 24/38 | post-hoc | **Confirmed.** The file is marked superseded, because its opening run contained 7 attacks (A7). One sentence in §6.2 or §7.3 would settle it |
| A11 | Physical frog is not silent on HAI 23.05 (R2 W8, R3 W1) | `threshold_transfer_tt1b_physfrog_dev_v1.json` -> `releases.hai-23.05.rules.frozen.median_campaign_alarm_steps` 189.5; spot 171; spot_mle 153.5; dspot 61. HAI 22.04: SPOT variants 0 | expl | **Confirmed.** "No alarm is ever raised" (§1, bullet 3) holds for the score-level attacker only |
| A12 | Light-tail synthetic control: MLE SPOT missed 1 of 5 seeds (R3 W14ii) | `threshold_transfer_tt1b_frog_synthetic_v1.json` -> `spot_mle.terminal_after_campaign` 0.8 (closed_24h, closed_6h, fixed_24h) | expl | **Confirmed.** §7.5 says only that MLE SPOT "rose only to 1.02 to 1.04 τ0" |
| A13 | H2 passes on a degenerate [0, 0] interval (R2 W5) | `gates.H2_spot_mle_vs_frozen.recall_difference_interval` [0, 0]; tolerance −0.143. Exact bound with 0 discordant out of 14: 1 − 0.025^(1/14) = 0.232 | reg tt1b; reviewer arithmetic | **Confirmed** as a statement about the interval method. The registered procedure was followed |
| A14 | "16 of the 18 tracker misses were attacks the frozen threshold caught" cannot be checked (R3 W14iv) | Trajectory CSV, event = score_max > τ in any row of a labelled run (reproduces every registered count: 36, 20, 27, 18; BATADAL 14, 6, 5, 14). HAI 20.07: frozen-only 16, tracker-only 0 (exact McNemar p = 3.1×10⁻⁵); tracker_slow 9 / 0; daily 18 / 0. BATADAL: tracker 8 / 0 (p = 0.0078) | post-hoc | **Correction: it can be checked, and it holds.** The one-directional discordance also answers part of R2 W4: under any-alarm counting the sign of the registered effect does not depend on the bootstrap |
| A15 | Artifact link is a placeholder; ethics appendix (R3 W10, R1 W15) | v3 `main.tex`: `\url{https://anonymous.4open.science/...}` with `% TODO`, in contribution 5 and the Open science appendix; `Ethical considerations` appendix present | n/a | **Confirmed.** The link is a desk-reject risk under the CFP. The ethics appendix answers the second point |
| A16 | Registration hygiene suspected (R1 W16, R2 W16, R3) | Verifiers: every final access follows its registration commit (HyGrid 43 s after, BATADAL 86 s after). Post-hoc reopenings are ledgered and listed | reg | **Not supported**, as all three reviewers found |
| A17 | Location labels | R3 cites "Sec 7.6-7.7 (Tables 8-10)" for the frog. The PDF has §7.5 (frog) and §7.6 (BATADAL), and no §7.7 | n/a | **Correction (cosmetic).** R3's frog-related locations should read §7.5-7.6 |
| A18 | Literature items | arXiv:2609.23254 exists (web search: abstract page, submitted 19 Sep 2026). Not verified: Kravchik & Shabtai arXiv:2012.15740 / ACM TOPS; "CPSS 2022 smart-grid threshold poisoning"; Ali, Khayam et al. TISSEC 2013; every other reviewer suggestion | n/a | Treat every unverified item as a lead for `review/literature_report.md`, not as a citation |

---
## Part 3. Meta-review

**Decision: major revision.** If the cycle has no revision outcome, the equivalent is reject and encourage resubmission. All three reviewers score 2 (weak reject), with confidence 4, 4 and 3. The disagreements are about emphasis, not direction.

### Consensus

**What the committee values:**
- **Rigour.** Registration with hash-frozen code, a one-access ledger, verifiers that recompute the gates, and honest reporting of a failed registered primary (tt1b) and an uninformative gate (G1).
- **Clarity.** The learning-region framing and the new §3.1 propositions, which are correct as stated.
- **Candour.** The revision volunteers post-hoc analyses that cut against its own headline.

**The robust registered core, narrower than the paper claims:**
- A symmetric quantile tracker and daily recalibration lose real-attack recall against a frozen threshold on HAI 20.07 under the registered any-alarm metric: tracker −0.42 [−0.58, −0.26] **[reg tt1]**, discordant pairs 16 to 0 **[post-hoc]**.
- The tracker also loses on BATADAL, −0.57 [−0.79, −0.29] **[reg tt1b]**, unchanged under onset counting **[post-hoc]**.
- Both losses follow from Proposition 1.

**What would sink the paper in its current form** (all three reviewers, verified in Part 2):
1. **A registered result is misinterpreted** (A1). The paper explains H3's failure, and the abstract and §10 claim, that days-long attacks inflated SPOT/DSPOT on BATADAL. The registered per-event record and the post-hoc trajectories show both rules at 46-49 τ0 from t = 0, before any attack, and *falling* through the streams. With no attack in the update they still miss 7-8 of 14 events.
2. **The headline outruns the registered, metric-robust evidence** (A5, A6, A11):
   - On HAI 20.07 the frozen threshold was in alarm 39% of the time, and the tracker's gap is not significant under onset counting.
   - HyGrid-ICS reverses sign under onset counting.
   - The closed-loop "silent" frog is exploratory, and its one registered test (H3) could not be evaluated.
   - The physical frog did not affect DSPOT (9/12 against 9/12) and was not silent on HAI 23.05.

   The abstract, contributions and conclusion still present all of these as established.
3. **Registered outcomes are missing** (A9, A10), although the protocol commits to reporting every rule, dataset, gate and failure. Missing: the four permit rules (all lost recall on HAI 20.07), S1, E5, the oracle E4 control, and the BATADAL frog variants. One post-hoc sensitivity analysis is also unreported.
4. **The design rule is stronger in the text than in the evidence** (A2, A3). Tighten-only's recall guarantee is now a theorem, but its measured benefit is nil. It equals frozen on HAI 20.07, HyGrid-ICS and voraus-AD, and costs 2.43× against 0.70× budget on BATADAL. The operator-gated variant is credited with the same guarantee although its ceiling can rise, and the registered oracle proxy caught 1/10 E4 controls.
5. **Baselines and estimators are the weak ones** (R1 W2, R2 W7, R3 W3/W9). The trackers and daily recalibration learn from alarmed values. There is no alarm-excluding recalibration, hold-off, step cap in τ0 units, or Telemanom run. SPOT is non-canonical: moments GPD, MLE refit every 2048 peaks, no declustering, unbounded shape. Natural poisoning is therefore shown for naive rules, and estimator dependence is not identified.
6. **The threat model has gaps** (R1 W6, R3 W7). An A2 attacker who can read τ_t, run the monitor and spoof sensors could conceal the terminal attack directly. The paper does not show what poisoning adds, and success is binary detection of a step only 5% above τ0.
7. **Submission compliance** (A15). The anonymized artifact link is still a placeholder.

### Changes that would move the decision, ranked by how much each would help

| Rank | Change | Raised by | Expected effect | Data needed (Part 4) |
|---|---|---|---|---|
| 0 (prerequisite) | Replace both `anonymous.4open.science/...` placeholders with a working anonymized artifact | R3 W10 | Removes a desk-reject risk; the paper's main claim (registration discipline) is not checkable without it | (a) |
| 1 | Correct the BATADAL SPOT/DSPOT attribution: H3 failed because of tail-fit initialisation, not attack poisoning | R1 W4, R2 W1 | Removes the one factual error; all three reviewers condition a higher score on it | (a) |
| 2 | Re-weight abstract, contributions, §6 and §10 around the registered, metric-robust evidence. Lead with BATADAL. Present HAI 20.07 as registered but fragile under onset counting, HyGrid-ICS as uninformative, and the frog as exploratory. Treat G1 like H3 (uninformative) | all three | Brings the claims into line with the evidence; R3 says this plus rank 3 moves to 3 | (a) |
| 3 | Report every registered outcome (S4 permit rules, S1, E5, oracle E4, BATADAL frog variants, a pointer to detection-v2) and the transient sensitivity | all three | Discharges the protocol's reporting commitment; S4 supports the paper's thesis | (a) |
| 4 | Restrict Proposition 3 to tighten-only without a permit; report the oracle result; quantify tighten-only's cost on registered data | R1 N1, R2 N3, R3 N2 | Makes the design rule honest; prerequisite for the guidance to survive | (a) |
| 5 | Stronger adaptive baselines and canonical extreme-value rules on the spent development data, labelled exploratory | all three | Decides whether "natural poisoning" is a property of adaptive thresholds or of naive ones. R1 and R3 say a result that survives these moves them to 4 | (b) |
| 6 | Frog dose-response over terminal magnitude, a matched refit cadence, a declustered SPOT, and a direct-concealment baseline for A2 | R1 W6, R2 W7-W8, R3 W7 | Turns the silent-poisoning claim from an upper-bound anecdote into a measured effect | (b) |
| 7 | Inference repairs: exact paired tests and discordant counts, exact H2 bound, matched-operating-point comparisons, stream-level resampling | R2 W4-W5, W9; R3 W4 | Answers the statistician's main objections | (a) and (b) |
| 8 | Related work: CPS stealthy-attack and impact line, causative-attack taxonomy, quantile-tracking/ACI literature, EVT estimation and declustering, the concurrent arXiv:2609.23254 | all three | Positions the novelty claim; R3 rates novelty modest without it | (a), pending `review/literature_report.md` |
| 9 | Presentation fixes (Fig. 2 caption, Table 10 "9 / 9", synthetic MLE miss, §7.3 lead sentence, status tags in §3.1 and §7.2, "attack-free" -> "exceedance-free") | R2 N4-N6, R3 W14/N3-N4 | Small but cheap | (a) |
| 10 | Registered SWaT/WADI outcomes, ideally with a new registration that fixes η in τ0 units and checks SPOT initialisation before access | all three | The largest single gain for the replication claim, but it needs new data | (c) |

---

## Part 4. What can be done without new data

Constraints: the raw datasets allowed one registered access each, and that access is used; SWaT and WADI are not yet available. Every addition below states its status in the text. Nothing in (a) or (b) can become *registered* evidence. The ACM body currently ends on page 10 of 12, which leaves about two pages; appendices may add up to ten more.

### (a) Writing, framing and analysis that need no new data

Analyses in this list use only stored fields in `results/` and `figure_data/`. That includes the post-hoc trajectory CSV, which reproduces every registered event count.

1. **Correct the BATADAL extreme-value attribution.**
   - **§7.6, paragraph after Table 7.** Replace "H3 failed because real attacks had already blinded DSPOT: its threshold stood 24 times above τ0 at attack onsets" with: "H3 could not be tested because DSPOT's control was already blind. The blindness predates the attacks. Initialised from the calibration tail (spread 6461.9 against τ0 = 9.39), the moments-GPD alarm level started at 49.0 τ0 (SPOT) and 45.8 τ0 (DSPOT) at t = 0 of each test file, and it fell to 24-44 τ0 by the first attack [post-hoc trajectories; registered per-event onset inflation]. With no attack sample in the update, SPOT still caught 6 of 14 and DSPOT 7 of 14 [post-hoc]. MLE SPOT, initialised at 1.22 τ0, caught 14 of 14."
   - **Abstract, paragraph 3.** Replace "showed that slow, days-long attacks also inflate SPOT and DSPOT" with "showed that method-of-moments SPOT and DSPOT can start blind on a heavy-tailed score".
   - **§10.** Replace "but not on days-long BATADAL attacks" accordingly.
   - **Fig. 5 caption.** Add τ_spot and τ_dspot from t = 0 to the existing BATADAL trajectory panel (the CSV already holds them).
2. **Re-weight the headline claims.**
   - **Abstract, paragraph 2.** Keep −0.42 [−0.58, −0.26] as the registered G2 result. Add in the same sentence that the frozen threshold was in alarm for 39% of unlabelled time and that, counting only alarms that start inside an attack, the gap is −0.16 [−0.37, 0.05] [post-hoc]. Make BATADAL (−0.57, unchanged under onset counting) the metric-robust registered result.
   - **Attacks-only sentence.** Tag "fed only the attack samples ..." as post-hoc, and drop "exactly": BATADAL gave 7/14 against 6/14.
   - **Closed-loop frog.** Tag it as exploratory wherever it appears: abstract paragraph 3, §1 bullet 3, §10. Restrict "no alarm is ever raised" to the score-level attacker. The physical frog raised a median of 189.5 alarm steps on HAI 23.05 [expl].
   - **Abstract and contribution 2.** Remove HyGrid-ICS from the list of datasets where "the same loss appeared", or say that its sign reverses under onset counting [post-hoc]. Remove daily recalibration from the HyGrid claim (daily = frozen there [reg tt1]).
   - **"Seven datasets."** Replace with "four registered test sets and three development releases" wherever it appears.
   - **Table 3 (G1 row).** Add "uninformative: adaptive controls already 0/10", parallel to H3 in Table 7.
   - **§6.1.** Add one sentence saying that neither registered attack test (G1, H3) could show an attack effect.
   - **G3.** Qualify it in Table 3 and §6.1 with the 39% alarm share.
3. **Report every registered outcome.** Add a table to an appendix, with a pointer from §6.2. Status for all rows: registered (tt1, tt1b).
   - S4 permit rules on HAI 20.07: spread −0.26 [−0.39, −0.13], spread6 −0.21 [−0.34, −0.08], shift −0.11 [−0.21, −0.03], shift6 −0.13 [−0.24, −0.03]; HyGrid-ICS and voraus-AD likewise; permits per week.
   - S1 first/second-half recall.
   - E5: 1 usable placement, 12 without a stealthy level.
   - The oracle E4 result (0.7 after the campaign, 0.1 in control).
   - BATADAL frog variants for every rule and both scores.
   - A pointer to the detection-v2 result.

   In §8 paragraph 1, cite the registered S4 losses instead of attributing permit failures only to development pulses and drift. In §6.2 or §7.3, add one sentence on `posthoc_transient.json` (tracker −0.29, tracker_slow −0.08 [−0.18, 0.00]) and why it was superseded.
4. **Scope the design rule.**
   - **Proposition 3 (§3.1).** Restrict it to "tighten-only without a permit" and to any-alarm recall. Note that it need not hold for onset recall.
   - **§1 (paragraph after the bullets) and §8 paragraph 1.** Remove "and loosens only when an operator approves ... by construction".
   - **§8.** Report the oracle E4 control (1/10).
   - **Table 5.** Add a tighten-only column: HAI 20.07 2.23, HyGrid-ICS 19.2, voraus-AD 0.081, all equal to frozen [reg tt1]. Move BATADAL's 2.43× against 0.70× [reg tt1b] into the §8 cost paragraph beside the development figure (5.98× against 4.05×, which drops to 4.05× at η/10 [expl]).
5. **Inference repairs from the stored record.** Add to §6.2, or as a footnote to Table 4, labelled post-hoc where the trajectory CSV is used.
   - **Exact McNemar tests on the discordant pairs:** HAI 20.07 tracker 16/0 (p = 3.1×10⁻⁵), tracker_slow 9/0 (p = 0.0039), daily 18/0 (p = 7.6×10⁻⁶); BATADAL tracker 8/0 (p = 0.0078). These come from the trajectory CSV, which reproduces every registered count.
   - **H2.** State that the [0, 0] interval comes from 0 discordant pairs, and give the exact one-sided bound (about −0.23 against the −0.143 margin). Report H2 as "pass under the registered procedure, not informative under an exact method".
   - **Matched operating points.** Re-threshold frozen at each adaptive rule's realised alarm-time share and compare event recall, using the minute-level `score_max` in the trajectory CSV (HAI 20.07, BATADAL). State the minute resolution.
6. **Tie Proposition 1 to the observations (§3.1).**
   - Plot predicted against observed tracker level, using `memory_check.json` (exceedance steps × η(1−p)).
   - State that recovery time does not depend on η but rise height does: BATADAL η = 6.9 τ0 per step.
   - Replace "attack-free hours" with "exceedance-free hours".
   - Distinguish recovery time (43-209 days) from blind time.
   - Tag the empirical sentences in §3.1 as post-hoc, and the BATADAL figures in Proposition 2 as registered tt1b.
7. **Threat-model argument (§3, after A2).** Add a paragraph on what poisoning buys over direct concealment for an attacker who can spoof sensors. State the A1 operator assumption against ISA-18.2 alarm-rate targets. The pulses add 12 episodes a day, and frozen alarms on 92% of them [reg tt1].
8. **Time to detect (§6.2 or the Table 8 caption).** Report it from the stored BATADAL per-event delays [reg tt1b]: frozen median 3.5 steps (52 min), maximum 65 steps (16.3 h). The tt1 result files store no per-event delay, so the HAI version belongs in (b).
9. **Related work (§2).** Add the CPS stealthy-attack and impact work, causative-attack taxonomy, online quantile tracking (conformal PID), GPD estimation and declustering, and the concurrent arXiv:2609.23254 (existence verified). Take every citation from `review/literature_report.md` once it exists; the reviewers' suggestions here are unverified leads.
10. **Presentation.**
    - **Fig. 2 caption.** Replace "for the first 23.8 h of test1 with no attack label" with "for the first 23.8 h of test1; only the first 2.7 h carry no attack label, and 7 attacks begin inside this run". Say "5.0 τ0 before the first attack (5.25 at its onset)".
    - **Table 10 (DSPOT row).** Write 9/12 and 9/12.
    - **§7.5.** Add that light-tail MLE SPOT missed 1 of 5 seeds in the 24 h, 6 h and fixed variants [expl].
    - **§1.** Fix "none of the adaptive rules we tested is safe" (tighten-only is adaptive).
    - **§7.3.** Qualify the lead sentence "Attacks are what raise the tracker": unlabelled samples alone cost −0.21 [−0.34, −0.08] on HAI 20.07 [post-hoc].
    - **§7.2.** Tag the D0 intervals individually: BATADAL is registered tt1b, voraus-AD is post-hoc.
    - **§8 recommendation 3.** Fix "held 0.66 to 2.23": 2.23 is above the 2.0 budget.

### (b) Experiments on the already-spent development data (HAI 21.03, 22.04, 23.05 normal and attack files)

All of these are exploratory and go in §7 or a new appendix with that label. Every placement design should be fixed in writing before running, and every run ledgered, so the record matches the paper's own discipline.

1. **Stronger adaptive baselines** for the natural-poisoning comparison on the three spent attack files. Report recall, any-alarm and onset recall, episodes per day and alarm-time share. Add rows to Table 6 (§7.1) or a new §7.1 table. The baselines:
   - daily recalibration that excludes alarm episodes and a hold-off window after them;
   - the tracker with upward updates frozen during alarms and for H hours after;
   - the tracker with η in τ0 units and a per-day rise cap;
   - Telemanom's pruned dynamic threshold.

   R1 and R3 tie a score of 4 to whether natural poisoning survives these.
2. **Canonical extreme-value rules.**
   - SPOT and DSPOT with Grimshaw MLE refitted at every peak.
   - Moments against MLE at a matched refit cadence.
   - Runs declustering, or an extremal-index correction.
   - A bounded shape parameter.

   Run them on the spent attack files (natural poisoning) and on the normal data (score-level and physical frog). Report the initial z_q/τ0 for each, which tests whether the BATADAL initialisation failure (A1) also affects the development releases. Goes in §7.1 and §7.5, Tables 6 and 8. This identifies contribution 3's estimator-dependence claim.
3. **Frog dose-response.** Score-level and physical frog with terminal magnitudes of 1.05, 1.5, 2, 5 and 10 τ0. Report the largest undetected terminal step after the campaign against the control, and the matching setpoint deviation. Add a new panel to Fig. 4 or a table in §7.5.
4. **Direct-concealment baseline for A2.** Give the same white-box, three-sensor attacker the option of concealing the terminal setpoint step directly, by spoofing during the step instead of before it. Compare detection under frozen, SPOT and DSPOT with the poisoning strategy. Goes in §7.5, physical-frog paragraph, and §3 (A2).
5. **Pulse campaigns against the new baselines.** Run E4 and E6 against item 1's alarm-gated and capped rules. Add rows to Table 9 (§7.4).
6. **Onset recall, alarm-time share and per-event delays** for every rule on the three spent releases. This makes the §6.2 metric comparison available beyond the registered sets. Add columns to Table 6.
7. **Resampling across streams.** Bootstrap or jackknife over the three releases' test files as units, and permute attack-block order within each release by re-splicing recorded attack segments into normal data at random positions. This estimates how much the tracker loss depends on schedule density, which addresses R2 W4 and R1 W1. Goes in §7.3, or an appendix with the statistical design.
8. **Operator-gate stress test.** A permit approved only when the trailing window shows no alarm. Attack it with the pulse campaign and with the frog, to test whether an operator-gated loosening can be socially engineered. Goes in §8 and closes R1 N1 / W7c empirically.

### (c) Changes that need new data

1. **Registered SWaT and WADI outcomes** under tt1b, once the loader amendment is written from documentation and normal files only. The registered rules cannot change for tt1b. The replication claim remains the set of per-dataset outcomes, reported whatever they show.
2. **A new registration (call it tt1c)** on data no analysis has opened: the SWaT/WADI attack files if tt1b has not yet used them, or a further dataset. It would fix:
   - η and the margin in τ0 units;
   - a check of SPOT/DSPOT initial z_q;
   - the canonical extreme-value variants and the alarm-gated baselines from (b);
   - onset recall and alarm time as co-primary metrics;
   - a frog hypothesis whose control is not at the floor, so that it can pass or fail.

   Only such a study can make the claims in (b) registered.
3. **Native-resolution reanalyses of the spent registered data:** order permutation, matched-operating-point recall at 1 Hz, and per-event delays on HAI 20.07. These would need another access to HAI 20.07 or BATADAL beyond the ledgered final. Under the pack's access rules the honest course is to run them on the new data of item 2.
4. **External validity:** a reconstruction-based detector (R1 W14) and real operator alarm logs to test the acknowledgement assumption behind A1 (R3 W7b). Both need data the pack does not hold.

---


*End of mock PC review. Written into `review/` only; `manuscript/`, `results/`, `protocols/`, `figure_data/` and `latex/` were not modified.*
