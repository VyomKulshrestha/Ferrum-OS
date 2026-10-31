# Literature and novelty check: *Thresholds That Travel* (draft v0.1)

Scope: `manuscript/thresholds_that_travel_draft_v0_1.md`, abstract, Sections 1-3, 8 and the reference list. The manuscript was revised in another session at 03:41 local time while this check was running. This report was then re-checked against the revised file: the abstract, Section 1, Section 3 (new Section 3.1 with Propositions 1-3) and Section 8 changed; Section 2 and the reference list did not. The compiled `latex/main.pdf` was not re-read. Report written 31 October 2026 against prompt `prompts/4_literature_and_novelty.md`. No manuscript, result, protocol or figure-data file was changed. This report contains no result numbers from the pack; the paper's design facts (for example "eleven rules") are quoted only as the draft states them.

## Bottom line

**One preprint already demonstrates, in theory, part of the paper's central claim.** [Atarmla 2026, arXiv:2609.23254](https://arxiv.org/abs/2609.23254) (posted 19 September 2026, single author, not peer reviewed) proves that the online quantile tracker's false-alarm guarantee is "an accounting identity, insensitive to what the monitor is meant to detect". It also derives the exact excess-alarm budget a persistent step or a ramp produces before the tracker absorbs it, and shows that a monitor required to tolerate a drift class is blind to faults inside it. That is the mechanism behind contribution 2 for the symmetric tracker, and the same argument the draft makes in its "Distribution shift and calibration" paragraph. The preprint is theory and simulation only. It has no attacks, no recorded data, no ICS, no SPOT/DSPOT and no tighten-only rule. The draft must cite it and present its own tracker result as an empirical confirmation on recorded attacks, not as a new mechanism. The revised draft's Proposition 1 (Section 3.1) is the same accounting identity stated as a memory: each exceedance raises the tracker by η(1 − p) and each quiet step lowers it by ηp. Atarmla proves that identity exactly (their Proposition 1) and attributes its basic form to Gibbs and Candes 2021, Prop. 4.1 (that attribution was not checked here). Proposition 1 should cite both. Its application to the calibrated false-alarm rates of the paper's datasets is new; the identity is not.

**Three further findings narrow the draft's wording without removing a contribution.**
1. [Rubinstein et al. 2009 (ANTIDOTE)](https://doi.org/10.1145/1644893.1644895) poisoned a PCA detector that is retrained weekly, threshold included, with a slowly growing "Boiling Frog" schedule. Its defence pairs robust PCA with a robust Laplace threshold. Section 2's sentence "These works target the model or the score" is therefore too strong.
2. The closed-loop attacker A2, who holds the score just under the current threshold, is the standard stealthy attacker of control security ([Cardenas et al. 2011](https://doi.org/10.1145/1966913.1966959); [Urbina et al. 2016](https://doi.org/10.1145/2976749.2978388)), there studied against fixed thresholds. Neither is cited.
3. The design rule "loosening needs a human" overlaps established alarm-management practice. ANSI/ISA-18.2 requires that changes to an alarm, setpoint included, pass through authorised management of change.

**Nothing found demonstrates the paper's other specific claims:**
- poisoning or frog-boiling of SPOT, DSPOT or another streaming extreme-value threshold;
- an attack on Telemanom's nonparametric dynamic threshold;
- an empirical measurement of real attacks inflating adaptive thresholds on recorded ICS data;
- a tighten-only threshold rule evaluated as a defence.

**Two citation errors need fixing before submission:**
- The HAI 1.0 entry gives arXiv:2005.02315, which resolves to an unrelated computer-vision paper.
- The Kravchik and Shabtai [2020] sentence reports only the preprint's negative result. The same group's peer-reviewed SAC 2021 paper reports successful poisoning of online-retrained ICS detectors.

## 1. How the search was done

No literature connector is attached to this project (the only MCP connector is Gmail). The search used:

| Source | Use | Outcome |
|---|---|---|
| Crossref REST API | topic queries; title look-ups for every candidate; metadata (authors, venue, year, pages, DOI) | 25 of 32 topic queries returned; title look-ups succeeded for all cited DOIs |
| arXiv API and arxiv.org abstract pages | topic queries; title search; abstract and author metadata for every arXiv ID cited | 10 of 13 topic queries returned |
| doi.org handle API | confirmed that every DOI cited below resolves | 45 of 45 DOIs resolve |
| dblp | requested and granted, but no query completed (the proxy resolved dblp.org to a reserved address or returned HTTP 429) | 0 of 14 queries |
| OpenAlex | not used: no API key is configured (Customize, then Credentials, to add one) | skipped |
| Semantic Scholar API | unreachable from the sandbox (reserved-address refusal) | skipped |
| Web search | targeted look-ups of abstracts, publisher pages and identifiers; 19 queries, listed in Appendix A | used for content claims and for venues outside Crossref (USENIX, JMLR, PMLR) |

Candidates came from the topic sweep, from one step backward through the reference list of Atarmla 2026, and from a list of papers a reviewer in this area would be expected to name, each of which was then looked up. No identifier in this report was typed from memory. Every DOI, arXiv ID or URL below was returned by Crossref, arXiv, a publisher page or dblp during this session. The full programmatic query log, with the source and number of hits for each query, is in Appendix A.

**Coverage limits.**
- Fraud detection was not searched separately. Spacecraft telemetry and AIOps/cloud monitoring were searched, with no threshold-poisoning hit.
- The pre-registration literature in security, relevant to contribution 5, was not searched.
- Several papers below were confirmed only at title and metadata level; their content was not read. Those entries say so.

## 2. Closest prior work per contribution

| # | Contribution (Section 1) | Closest prior work | Verdict |
|---|---|---|---|
| 1 | Registered comparison of eleven threshold rules on three never-opened datasets | None found that is registered or that compares adaptive threshold rules under recorded attacks | New |
| 2 | Exceedance-learning thresholds lose recall because earlier attacks inflate them | Atarmla 2026 (theory, tracker); Rubinstein et al. 2009; Cretu et al. 2008 | Partly new |
| 3 | Learning-region analysis: tracker and daily memory (Section 3.1) and a matching attack per class (pulses; closed-loop frog on SPOT/DSPOT) | Atarmla 2026 (Proposition 1 identity); Chan-Tin et al. 2009/2011; Kravchik et al. 2021; Urbina et al. 2016 | Partly new (Proposition 1 already known) |
| 4 | Design rule: thresholds may tighten themselves; loosening needs a human | ANSI/ISA-18.2 management of change; Kravchik et al. 2021 (lower the threshold); Kloft and Laskov 2012 | Partly known |
| 5 | Registration, access ledger, harness and verifier | Not assessed (pre-registration literature not searched) | Not assessed |

### Contribution 1: registered comparison

No published comparison was found that pre-registers threshold rules, or that compares frozen, recalibrated, tracked and extreme-value thresholds under recorded attacks on ICS data. The surrounding evaluation literature shows that threshold choice is often uncontrolled. [Su et al. 2019 (OmniAnomaly)](https://doi.org/10.1145/3292500.3330672) sets its POT threshold offline, and its authors write: "we set the anomaly threshold thF offline". [Chahine and Noura 2026](https://doi.org/10.3390/fi18060308) is a recent HAI example where "the detection threshold is subsequently selected by maximizing PA-F1 on this same evaluation split". [Wu and Keogh 2023](https://doi.org/10.1109/TKDE.2021.3112126) is already cited.

**Verdict: new** as a registered, multi-rule comparison. That threshold choice matters in evaluations is known.

### Contribution 2: natural poisoning

[Atarmla 2026](https://arxiv.org/abs/2609.23254) proves, for the online quantile tracker, that a persistent step of height δ produces an excess alarm mass within one alarm of δ/η before it is absorbed. It also proves that a ramp slower than η(1 − α) is absorbed indefinitely, and that adversarial exploitation is possible but not required. This is the draft's A0 mechanism stated as a theorem. [Rubinstein et al. 2009](https://doi.org/10.1145/1644893.1644895) showed that poisoning a self-retraining detector "throws off the balance between false positives and false negatives". [Cretu et al. 2008](https://doi.org/10.1109/sp.2008.11) addressed attacks hidden in the training data of self-updating anomaly sensors; a 2022 survey describes it as "an early research on preventing training data poisoning". In process monitoring the same effect is long known for self-calibrating schemes. The one SPC reference retrieved (Sullivan and Jones, Technometrics 2002) predates the search window and is not used.

**Verdict: partly new.** The mechanism, adaptation absorbing persistent deviations whatever their source, is known in general and proved for the tracker. New: the empirical demonstration that recorded attacks inflate the thresholds of the very rules meant to detect them, measured on registered ICS data, with the mechanism traced in which attacks are missed. The revised contribution 2 now labels which parts are registered (HAI 20.07, BATADAL), post-hoc (the attack-only tracker rerun) and repeated on further data. That labelling should stay in any related-work text that summarises it.

### Contribution 3: learning regions

The closed-loop frog against SPOT/DSPOT is structurally the frog-boiling attack on an outlier-rejecting learner. [Chan-Tin et al. 2011](https://doi.org/10.1145/2043621.2043627) write: "We describe a new attack on network coordinate systems, Frog-Boiling, that defeats all of these defenses". SPOT discards values above its alarm level as network-coordinate systems discard outliers, and learns from the rest. Two other closely related lines exist:

- Sub-alarm poisoning of a retrained ICS detector. Kravchik and Shabtai's 2020 preprint ([arXiv:2002.02741](https://arxiv.org/abs/2002.02741)) assumes "that only the data that does not trigger alerts will be used for retraining". [Kravchik et al. 2021](https://doi.org/10.1145/3412841.3441892) carries the attack through.
- The stealthy attacker who stays just under a fixed threshold. [Urbina et al. 2016](https://doi.org/10.1145/2976749.2978388) describe attackers "injecting just enough false information at each time step to achieve their goals".

None of these targets an extreme-value tail refit, and none reports how the attack depends on the tail estimator. No prior taxonomy of threshold rules by the region of the score range they learn from was found. The sweep returned no paper attacking SPOT, DSPOT, POT or Telemanom thresholds (Appendix A, topic T1).

The revised contribution 3 also claims the Section 3.1 analysis of how long the tracker and daily recalibration remember an exceedance. For the tracker this is the accounting identity proved in [Atarmla 2026](https://arxiv.org/abs/2609.23254). No prior statement of Proposition 2 (daily recalibration) or Proposition 3 (tighten-only alarms are a superset of frozen alarms) was found. Proposition 3 follows directly from monotonicity and needs no citation.

**Verdict: partly new.** The attack template (feed a self-updating learner only values it accepts, so it drifts without alarming) is known from 2009 onward. New: the application to streaming extreme-value thresholds, the estimator dependence, the pulse campaign against exceedance learners as a separate attacker class, and the learning-region framing that predicts which attack fits which rule. Already known: the tracker-memory identity behind Proposition 1.

### Contribution 4: tighten-only design rule

ANSI/ISA-18.2-2016 already requires a management-of-change process "that ensures that changes are authorized" ([Emerson white paper on ISA-18.2 rationalisation](https://www.emerson.com/documents/automation/white-paper-alarm-rationalization-deltav-en-56654.pdf)). The standard itself is not freely available and was not read here. Operator approval of alarm-limit changes is therefore existing practice in process plants.

In the security literature, [Kravchik et al. 2021 (arXiv:2012.15740)](https://arxiv.org/abs/2012.15740) found that "decreasing the detection threshold is an effective means of poisoning mitigation". [Kloft and Laskov 2012](https://jmlr.org/papers/v13/kloft12b.html) showed that a poisoning attack "can be made arbitrarily difficult (a strict upper bound on the attacker's gain) if external constraints are properly used", a bounded false-positive rate among them.

One counterpoint bears directly on the rule. [Dhananjeyan and U 2026](https://arxiv.org/abs/2608.31062) measured human-approved loosening in the SigmaHQ detection-rule corpus and conclude: "Narrowing accumulates, is rarely revisited, and is not triaged by consequence." Routing loosening through people does not by itself stop a ratchet. The revised draft already concedes this point in Sections 1 and 8: loosening by an operator "carries no such guarantee", and the simulated-operator permit lost recall. The ratchet study is outside evidence for that concession and should be cited beside it.

**Verdict: partly known.** Human authorisation of alarm changes is established practice, and lowering thresholds against poisoning has been proposed. Not found in prior work: the asymmetric rule (automatic tightening, gated loosening) stated as a defence for adaptive detector thresholds and evaluated against natural, loud and silent poisoning. Section 8 should cite ISA-18.2 management of change as the precedent and say that the paper adds the asymmetry and its evaluation. Section 8's existing caveat about operator-gated permits should cite the evidence that human-approved loosening also accumulates.

### Contribution 5: artefacts

This is an artefact contribution, not a research claim about attacks or thresholds. Whether pre-registered empirical studies have appeared in security venues was not searched, so no novelty verdict is given.

## 3. Missing citations, ranked

Content-level entries were checked against the paper's abstract or text in this session. Entries marked *title-level* were confirmed to exist (authors, venue, year, identifier) but their content was not read.

1. **[Urbina et al. 2016, CCS](https://doi.org/10.1145/2976749.2978388).** Defines the stealthy ICS attacker who keeps the detection statistic below the threshold and compares stateless and stateful detectors under it. Belongs in Section 2 (poisoning and stealthy attacks) and in Section 3, where A2 should be introduced as this attacker turned against an adaptive threshold.
2. **[Cardenas et al. 2011, ASIACCS](https://doi.org/10.1145/1966913.1966959).** Nonparametric CUSUM detection of false-data injection in process control, with a section on stealthy attacks and on choosing the threshold to resist them. The target venue's own precedent; Section 2 and Section 3.
3. **[Kravchik, Biggio and Shabtai 2021, SAC](https://doi.org/10.1145/3412841.3441892) and [Kravchik et al. 2022, Computers & Security](https://doi.org/10.1016/j.cose.2022.102901).** Peer-reviewed successors of the cited 2020 preprint. They demonstrate poisoning of online-retrained ICS detectors with sub-alarm samples, and the SAC paper proposes lowering the threshold as mitigation. Section 2 (replacing the current characterisation) and Section 8.
4. **[Atarmla 2026, arXiv:2609.23254](https://arxiv.org/abs/2609.23254), preprint.** Exact theory of evidence absorption and manufactured blind sets for the online quantile tracker. Section 2 (distribution shift), Section 3.1 beside Proposition 1, and the mechanism discussion in Sections 6.2 and 7.3.
5. **ANSI/ISA-18.2-2016 management of change, with [EEMUA 191](https://www.eemua.org/products/publications/digital/eemua-publication-191) (4th ed., 2024) and IEC 62682.** EEMUA states that ISA-18.2 and IEC 62682:2023 are aligned with EEMUA 191. The draft cites ISA-18.2 only for nuisance alarms; reviewers from process control will expect the management-of-change clause beside the Section 8 recommendation.
6. **[Kloft and Laskov 2012, JMLR 13(118):3681-3724](https://jmlr.org/papers/v13/kloft12b.html) ([arXiv:1003.0078](https://arxiv.org/abs/1003.0078)).** Journal version of the cited AISTATS paper. Bounds on poisoning of online centroid detectors under a bounded false-positive rate support the tighten-only argument; Sections 2 and 8.
7. **[Chan-Tin, Heorhiadi, Hopper and Kim 2011, ACM TISSEC 14(3)](https://doi.org/10.1145/2043621.2043627).** Journal version of the cited SecureComm paper, extending frog-boiling to defeat outlier rejection, trusted nodes and reputation. Section 2.
8. **[Cretu et al. 2008, IEEE S&P](https://doi.org/10.1109/sp.2008.11).** Sanitising attack-contaminated training data for self-updating anomaly sensors; the precedent for Section 8's "recalibrate offline on verified clean data". Sections 2 and 8.
9. **[Pasqualetti, Dörfler and Bullo 2013, IEEE TAC](https://doi.org/10.1109/tac.2013.2266831) and [Teixeira et al. 2015, Automatica](https://doi.org/10.1016/j.automatica.2014.10.067).** Attacks that excite only zero dynamics and evade any residual detector (as described in Atarmla 2026). Section 3, to separate threshold-adaptation blind sets from model-structure blind sets.
10. **[Su et al. 2019 (OmniAnomaly), KDD](https://doi.org/10.1145/3292500.3330672).** A widely used detector that sets its threshold by an offline POT fit. Evidence for Section 2's claim that published detectors fix one threshold, and the bridge from POT to SPOT.
11. **[Shin et al. 2021, CSET '21](https://doi.org/10.1145/3474718.3474719).** Peer-reviewed documentation of HAI 21.03 (and the 20.07 renaming). Replaces part of "later releases are documented in the dataset repository"; Sections 2 and 4.
12. **[Barreno et al. 2006, ASIACCS](https://doi.org/10.1145/1128817.1128824), *title-level*.** Standard taxonomy reference for causative (training-time) attacks on learning systems; a one-clause mention in Section 2.
13. **[Bastani et al. 2022, NeurIPS](https://doi.org/10.52202/068431-2129), *title-level*; [Gibbs and Candes 2022, arXiv:2208.08401](https://arxiv.org/abs/2208.08401), *title-level*; [Zaffran et al. 2022, arXiv:2202.07282](https://arxiv.org/abs/2202.07282), *title-level*; [Angelopoulos, Candes and Tibshirani 2023, NeurIPS](https://doi.org/10.52202/075280-1000), described in Atarmla 2026 as adding proportional and derivative terms to the ACI recursion.** The online-conformal family whose guarantees hold for arbitrary or adversarial sequences; Section 2.
14. **[Alahmadi, Axon and Martinovic 2022, USENIX Security, pp. 2783-2800](https://www.usenix.org/conference/usenixsecurity22/presentation/alahmadi).** SOC practitioners confirmed high false-positive rates requiring manual validation. Supports the Section 3 assumption that persistent nuisance alarms get acknowledged; Sections 2 and 3.
15. **[Dhananjeyan and U 2026, arXiv:2608.31062](https://arxiv.org/abs/2608.31062), preprint.** Human-approved suppression accumulates and persists in a public detection-rule corpus. A limit on "loosening needs a human"; Sections 8 and 9.
16. **[Ghafouri et al. 2016, GameSec](https://doi.org/10.1007/978-3-319-47413-7_24) and [Ghafouri et al. 2019, Autonomous Agents and Multi-Agent Systems](https://doi.org/10.1007/s10458-019-09412-2).** Game-theoretic "adaptive thresholds" against a strategic attacker, evaluated on a water network. A reviewer seeing "adaptive thresholds" and "attacker" will name them; Section 2 should say these are precomputed schedules, not stream-learned.
17. **[Seo, Lee and Seo 2026, ICUFN, pp. 522-526](https://doi.org/10.1109/icufn69619.2026.11628587), *title-level*.** "Retraining Data Poisoning Attacks on Drift Adaptive Anomaly Detection for Industrial Control Systems". Its abstract was not accessible here. The author should read it before submission, because the title overlaps contribution 2.
18. **[Siffer et al. 2020 (Netspot), TrustCom](https://doi.org/10.1109/trustcom50675.2020.00122), *title-level*.** The SPOT authors applying their statistical learning to network intrusion detection. Shows SPOT-style thresholds in a security deployment; Section 2.
19. **[Wang, Yang, Chen and Shah 2016, IEEE TASE](https://doi.org/10.1109/tase.2015.2464234), *title-level*.** Overview of the causes of industrial alarm overloading; Section 2's alarm-management sentence.
20. **[Giraldo et al. 2018, ACM Computing Surveys](https://doi.org/10.1145/3203245), *title-level*.** Survey of physics-based attack detection in CPS, including stateless and stateful threshold tests; Section 2.
21. **[Gualandi and Papadopoulos 2023, ACSOS](https://doi.org/10.1109/acsos58161.2023.00029) and [Murguia and Ruths 2016, CDC](https://doi.org/10.1109/cdc.2016.7798446), both *title-level*.** Stealth attacks against CUSUM-based detectors with multiple alarms, and characterisation of a CUSUM sensor-attack detector. Section 7, if the closed-loop analysis is related to stateful detectors.
22. **Frog-boiling in other domains:**
    - [Dey et al. 2020, arXiv:2001.11821](https://arxiv.org/abs/2001.11821): frog-boiling against continually trained behavioural (UEBA) detectors.
    - [Becker et al. 2011, LNCS](https://doi.org/10.1007/978-3-642-23644-0_11), *title-level*: frog-boiling against topology-estimation networks.
    - [Stirewalt and Gebremedhin 2025, CCS poster](https://doi.org/10.1145/3719027.3760741): reframes boiling-frog attacks as habituation.
    - [Ino et al. 2024, Sensors](https://doi.org/10.3390/s24196416): physical poisoning of an on-device detector with drift adaptation.

    One sentence in Section 2 covers them.
23. **Further, lower-ranked:**
    - [Kantchelian et al. 2013, AISec](https://doi.org/10.1145/2517312.2517320), adversarial drift, *title-level*.
    - [Cretu-Ciocarlie et al. 2009, LNCS](https://doi.org/10.1007/978-3-642-04342-0_3), self-calibration and dynamic updating of anomaly sensors, *title-level*.
    - [Broadwater and Chellappa 2010, IEEE TSP](https://doi.org/10.1109/tsp.2009.2031285), adaptive EVT thresholds, *title-level*.
    - [Ozbek et al. 2026, arXiv:2608.23547](https://arxiv.org/abs/2608.23547), offline training-time contamination of eleven ICS detectors on SWaT.
    - [Li 2026, arXiv:2609.19241](https://arxiv.org/abs/2609.19241): conformal intrusion detection where a threshold calibrated on clean traffic fails under feature perturbation; evasion, not online poisoning.
    - [Principato and Stoltz 2025, arXiv:2510.15824](https://arxiv.org/abs/2510.15824): ACI as a repeated game.
    - [Ben-Eliezer et al. 2021, SIGMOD Record](https://doi.org/10.1145/3471485.3471488), adversarially robust streaming algorithms, *title-level*.
    - [Ma, Muthukrishnan and Sandler 2013, LNCS](https://doi.org/10.1007/978-3-642-40273-9_7), frugal streaming quantiles, *title-level*.
    - [Chahine and Noura 2026, Future Internet 18:308](https://doi.org/10.3390/fi18060308), label-tuned thresholds on HAI.
24. **Existence-only, evaluation genre (content not checked):**
    - [Garg et al. 2022, IEEE TNNLS](https://doi.org/10.1109/tnnls.2021.3105827)
    - [Fung et al. 2022, LNCS](https://doi.org/10.1007/978-3-031-17143-7_24)
    - [Kim et al. 2022, AAAI](https://doi.org/10.1609/aaai.v36i7.20680)

    Read them before citing them as threshold-evaluation evidence.

## 4. Corrections to existing citations

| Draft citation | Problem | Proposed fix |
|---|---|---|
| Shin et al., HAI 1.0, CSET 2020, "arXiv:2005.02315" | arXiv:2005.02315 is Tu et al., "Multi-interactive Dual-decoder for RGB-thermal Salient Object Detection". HAI 1.0 has no arXiv or DOI record; it is a CSET '20 short paper (dblp key conf/uss/ShinLYK20) | "Shin, H.-K., Lee, W., Yun, J.-H., Kim, H. HAI 1.0: HIL-based Augmented ICS Security Dataset. 13th USENIX Workshop on Cyber Security Experimentation and Test (CSET '20), 2020. https://www.usenix.org/conference/cset20/presentation/shin" |
| Kravchik and Shabtai [2020], "resisted their poisoning attacks" | Accurate for the preprint, which found the physical-state SWaT autoencoder resilient, but the same group's SAC 2021 paper reports that it demonstrates such poisoning attacks on online ICS detectors, on synthetic and real-world data | Use the Section 5 sentence below and add Kravchik et al. 2021 (SAC) and 2022 (Computers & Security) |
| Rubinstein et al. [2009]; "These works target the model or the score" | ANTIDOTE's detector is retrained weekly with its Q-statistic threshold, and the defence includes a robust Laplace threshold | Add doi:10.1145/1644893.1644895; soften to "These works target the model or the score, or assume a fixed threshold" |
| Chan-Tin et al. SecureComm 2009 | No identifier given; a journal version exists | Add doi:10.1007/978-3-642-05284-2_26 and cite TISSEC 14(3), 2011, doi:10.1145/2043621.2043627 |
| Goh et al. CRITIS 2016 | No identifier; the proceedings appeared in LNCS in 2017 | Add pp. 88-99, doi:10.1007/978-3-319-71368-7_8 |
| Kloft and Laskov AISTATS 2010 | Correct; the journal version is the usual reference | Add JMLR 13(118):3681-3724, 2012 |
| "later [HAI] releases are documented in the dataset repository" | HAI 21.03 has a peer-reviewed description | Add Shin et al., CSET '21, doi:10.1145/3474718.3474719 |
| ISA 2016 | Correct; the aligned international standard and guide are not mentioned | Optionally add IEC 62682 and EEMUA 191 (4th ed., 2024) |

Verified unchanged: Erba et al. 2020 (https://doi.org/10.1145/3427228.3427660), Hundman et al. 2018 (https://doi.org/10.1145/3219819.3219845), Siffer et al. 2017 (https://doi.org/10.1145/3097983.3098144), Gibbs and Candes 2021 ([arXiv:2106.00170](https://arxiv.org/abs/2106.00170)), Hong 2026 ([arXiv:2603.08455](https://arxiv.org/abs/2603.08455); Zhe Hong, 9 March 2026), Taormina et al. 2018 (doi:10.1061/(ASCE)WR.1943-5452.0000969). Wu and Keogh: Crossref still holds the 2021 early-access record for doi:10.1109/TKDE.2021.3112126; the draft's TKDE 35(3), 2023 is the article of record from the earlier review. Not checked here: Ahmed et al. 2017 (WADI), Hosking and Wallis 1987 (outside the search window), Brockmann et al. 2024, Yolcu 2026.

## 5. Proposed replacement for Section 2

Length: 539 words against 390 in the current section, which is unchanged in the revised draft (limit 390 + 150). Every citation not already in the draft is marked "(new)". The claims are the draft's own; two sentences are softened where the literature contradicts the current wording, and nothing is strengthened. The last sentence of the third paragraph replaces "even when the model resists poisoning" with "even when the model is not poisoned". The evidence cited for resistance has been superseded, and the paper's monitor is calibrated once rather than retrained; the author should confirm this wording matches the setup.

---

## 2. Background and related work

**ICS anomaly detection.** Process-level detectors learn normal behaviour from sensor and actuator traces and flag deviations: model residuals, autoencoder reconstruction errors, or statistical bounds. Public testbed recordings with labelled attacks (SWaT [Goh et al. 2016], WADI [Ahmed et al. 2017], BATADAL [Taormina et al. 2018], and the HAI releases [Shin et al. 2020 for HAI 1.0 (20.07); Shin et al. 2021 for 21.03 (new); later releases are documented in the dataset repository]) are the usual benchmarks. Evaluations usually fix one threshold per detector, chosen on clean data, by an offline peaks-over-threshold fit [Su et al. 2019 (new)], or, less defensibly, on the test labels. Wu and Keogh [2023] list further benchmark pitfalls.

**Threshold rules.** Static thresholds meet a quantile or false-alarm budget on clean data. Adaptive variants recalibrate on a trailing window, track a target exceedance rate online [Gibbs and Candes 2021], fit an extreme-value tail and update it per observation (SPOT, and DSPOT for drifting streams [Siffer et al. 2017]), or recompute a level on a trailing window of smoothed errors [Hundman et al. 2018]. Game-theoretic time-varying thresholds [Ghafouri et al. 2016 (new)] are precomputed, not learned from the stream. Alarm-management practice treats nuisance and chattering alarms as a condition to eliminate, with explicit alarm-rate targets, and routes setpoint changes through authorized management of change [ANSI/ISA-18.2-2016; EEMUA 191 (new)]; operators who acknowledge such alarms without investigating them are the failure mode our pulse campaigns exploit.

**Poisoning and stealthy attacks.** Rubinstein et al. [2009] showed that slowly growing ("boiling frog") poisoning of a weekly retrained PCA detector, whose threshold is re-estimated with it, can stop it flagging a later attack. Kloft and Laskov [2010; 2012 (new)] showed that bounding the false-positive rate limits poisoning of online centroid detectors. Chan-Tin et al. [2009; 2011 (new)] described frog-boiling against outlier rejection in network coordinate systems: every update stays within the rejection threshold while the system drifts. In ICS, Kravchik and Shabtai [2020] found an autoencoder on SWaT physical-state data resistant to poisoning, but later work poisoned online-retrained ICS detectors with sub-threshold samples and proposed lowering the threshold as mitigation [Kravchik et al. 2021 (new)]. Erba et al. [2020] concealed attacks from reconstruction-based detectors by manipulating sensor readings. Attackers holding a detection statistic just under a fixed threshold are standard in control security [Cardenas et al. 2011; Urbina et al. 2016 (new)]. Hong [2026] studied gradual drift against world-model monitors in simulation, without attacks or adaptive thresholds. These works target the model or the score, or assume a fixed threshold. We target the adaptive threshold rule and show that it can fail even when the model is not poisoned.

**Distribution shift and calibration.** Adaptive conformal inference and its successors keep a long-run miscoverage rate under arbitrary, even adversarial, sequences [Gibbs and Candes 2021; Bastani et al. 2022 (new)], a guarantee about the rate of exceedances. Atarmla [2026 (new)] proves that for the online quantile tracker this guarantee is an accounting identity and bounds the evidence a step or ramp produces before it is absorbed. The guarantee holds whether exceedances come from drift or attacks, the property we exploit in Section 7; Proposition 1 (Section 3.1) follows from the same identity, which we test on recorded attacks.

---

References to add for this text (all verified, see Section 6): Shin et al. 2021; Su et al. 2019; Ghafouri et al. 2016; EEMUA 191 (4th ed., 2024); Kloft and Laskov 2012; Chan-Tin et al. 2011; Kravchik, Biggio and Shabtai 2021; Urbina et al. 2016; Bastani et al. 2022; Atarmla 2026. Cardenas et al. 2011 appears unmarked in the text but is also new and must be added to the reference list.

## 6. Verified references

Found by: C = Crossref (title look-up or topic query, query in Appendix A); X = arXiv API or abstract page; W = web search (query in Appendix A); B = backward citation from Atarmla 2026; D = already in the draft. All DOIs resolve at doi.org.

| Reference | Venue, year | Identifier | Found by |
|---|---|---|---|
| Atarmla, A.-R. The Price of Self-Calibration: Exact Evidence Budgets and Manufactured Blind Sets in Adaptive Monitoring | arXiv preprint, 2026 | arXiv:2609.23254 | W ("arXiv 2603.08455 boiling frog threshold ...") then X |
| Rubinstein, Nelson, Huang, Joseph, Lau, Rao, Taft, Tygar. ANTIDOTE | IMC 2009, pp. 1-14 | 10.1145/1644893.1644895 | D; W ("ANTIDOTE ... IMC 2009 doi") |
| Urbina, Giraldo, Cardenas, Tippenhauer, Valente, Faisal, Ruths, Candell, Sandberg. Limiting the Impact of Stealthy Attacks on Industrial Control Systems | CCS 2016, pp. 1092-1105 | 10.1145/2976749.2978388 | C (title) |
| Cardenas, Amin, Lin, Huang, Huang, Sastry. Attacks against process control systems: risk assessment, detection, and response | ASIACCS 2011, pp. 355-366 | 10.1145/1966913.1966959 | C (title) |
| Kravchik, Biggio, Shabtai. Poisoning attacks on cyber attack detectors for industrial control systems | ACM SAC 2021, pp. 116-125 | 10.1145/3412841.3441892; arXiv:2012.15740 | C (title); W ("poisoning attack SPOT DSPOT ...") |
| Kravchik, Demetrio, Biggio, Shabtai. Practical evaluation of poisoning attacks on online anomaly detectors in ICS | Computers & Security 122:102901, 2022 | 10.1016/j.cose.2022.102901 | C (title) |
| Kravchik, Shabtai. Can't Boil This Frog | arXiv preprint, 2020 | arXiv:2002.02741 | D; X |
| Kloft, Laskov. Security Analysis of Online Centroid Anomaly Detection | JMLR 13(118):3681-3724, 2012 | jmlr.org/papers/v13/kloft12b; arXiv:1003.0078 | W (jmlr.org) then X |
| Chan-Tin, Heorhiadi, Hopper, Kim. The Frog-Boiling Attack: Limitations of Secure Network Coordinate Systems | ACM TISSEC 14(3):1-23, 2011 | 10.1145/2043621.2043627 | C ("frog boiling attack") |
| Chan-Tin, Feldman, Hopper, Kim. The Frog-Boiling Attack (SecureComm) | LNICST, 2009, pp. 448-458 | 10.1007/978-3-642-05284-2_26 | D; C |
| Cretu, Stavrou, Locasto, Stolfo, Keromytis. Casting out Demons: Sanitizing Training Data for Anomaly Sensors | IEEE S&P 2008, pp. 81-95 | 10.1109/sp.2008.11 | C (title) |
| Cretu-Ciocarlie, Stavrou, Locasto, Stolfo. Adaptive Anomaly Detection via Self-calibration and Dynamic Updating | LNCS, 2009, pp. 41-60 | 10.1007/978-3-642-04342-0_3 | C ("poisoning self-updating intrusion detection") |
| Pasqualetti, Dörfler, Bullo. Attack Detection and Identification in Cyber-Physical Systems | IEEE TAC 58(11):2715-2729, 2013 | 10.1109/tac.2013.2266831 | B then C |
| Teixeira, Shames, Sandberg, Johansson. A secure control framework for resource-limited adversaries | Automatica 51:135-148, 2015 | 10.1016/j.automatica.2014.10.067 | B then C |
| Su, Zhao, Niu, Liu, Sun, Pei. Robust Anomaly Detection for Multivariate Time Series through Stochastic Recurrent Neural Network | KDD 2019, pp. 2828-2837 | 10.1145/3292500.3330672 | C (title); W (POT check) |
| Shin, Lee, Yun, Min. Two ICS Security Datasets and Anomaly Detection Contest on the HIL-based Augmented ICS Testbed | CSET '21, pp. 36-40 | 10.1145/3474718.3474719 | C (title) |
| Shin, Lee, Yun, Kim. HAI 1.0: HIL-based Augmented ICS Security Dataset | CSET '20 (USENIX), 2020 | usenix.org/conference/cset20/presentation/shin | D; W |
| Barreno, Nelson, Sears, Joseph, Tygar. Can machine learning be secure? | ASIACCS 2006, pp. 16-25 | 10.1145/1128817.1128824 | C (title) |
| Bastani, Gupta, Jung, Noarov, Ramalingam, Roth. Practical Adversarial Multivalid Conformal Prediction | NeurIPS 2022, pp. 29362-29373 | 10.52202/068431-2129 | C (title) |
| Gibbs, Candes. Conformal Inference for Online Prediction with Arbitrary Distribution Shifts | arXiv, 2022 | arXiv:2208.08401 | X (title) |
| Zaffran, Dieuleveut, Féron, Goude, Josse. Adaptive Conformal Predictions for Time Series | arXiv, 2022 | arXiv:2202.07282 | X (title) |
| Angelopoulos, Candes, Tibshirani. Conformal PID Control for Time Series Prediction | NeurIPS 2023, pp. 23047-23074 | 10.52202/075280-1000; arXiv:2307.16895 | C; X |
| Alahmadi, Axon, Martinovic. 99% False Positives: A Qualitative Study of SOC Analysts' Perspectives on Security Alarms | USENIX Security 2022, pp. 2783-2800 | usenix.org/conference/usenixsecurity22/presentation/alahmadi | W (dblp and usenix.org pages) |
| Dhananjeyan, U. The Exclusion Ratchet | arXiv preprint, 2026 | arXiv:2608.31062 | W (Alahmadi query) then X |
| Ghafouri, Abbas, Laszka, Vorobeychik, Koutsoukos. Optimal Thresholds for Anomaly-Based Intrusion Detection in Dynamical Environments | GameSec 2016, LNCS, pp. 415-434 | 10.1007/978-3-319-47413-7_24 | C (title) |
| Ghafouri, Laszka, Abbas, Vorobeychik, Koutsoukos. A game-theoretic approach for selecting optimal time-dependent thresholds for anomaly detection | Auton. Agents Multi-Agent Syst., 2019 | 10.1007/s10458-019-09412-2 | W then C |
| Seo, Lee, Seo. Retraining Data Poisoning Attacks on Drift Adaptive Anomaly Detection for ICS | ICUFN 2026, pp. 522-526 | 10.1109/icufn69619.2026.11628587 | C ("gradual drift poisoning online anomaly detection") |
| Siffer, Fouque, Termier, Largouet. Netspot | TrustCom 2020, pp. 911-918 | 10.1109/trustcom50675.2020.00122 | C (title) |
| Wang, Yang, Chen, Shah. An Overview of Industrial Alarm Systems | IEEE TASE 13(2):1045-1061, 2016 | 10.1109/tase.2015.2464234 | C (title) |
| Giraldo et al. A Survey of Physics-Based Attack Detection in Cyber-Physical Systems | ACM CSUR 51(4), 2018 | 10.1145/3203245 | C (title) |
| Gualandi, Papadopoulos. Worst-Case Impact Assessment of Multi-Alarm Stealth Attacks Against Control Systems with CUSUM-Based Anomaly Detection | ACSOS 2023, pp. 117-126 | 10.1109/acsos58161.2023.00029 | C (hit for Cardenas query) |
| Murguia, Ruths. Characterization of a CUSUM model-based sensor attack detector | CDC 2016, pp. 1303-1309 | 10.1109/cdc.2016.7798446 | C (title) |
| Dey, Velay, Fauvelle, Navers. Adversarial vs behavioural-based defensive AI ... | arXiv, 2020 | arXiv:2001.11821 | X (abs:"frog-boiling") |
| Becker, Seibert, Nita-Rotaru, State. Securing Application-Level Topology Estimation Networks: Facing the Frog-Boiling Attack | LNCS, 2011, pp. 201-221 | 10.1007/978-3-642-23644-0_11 | C ("frog boiling attack") |
| Stirewalt, Gebremedhin. Poster: Adversarial Habituation Attack | CCS 2025, pp. 4830-4832 | 10.1145/3719027.3760741 | C ("frog boiling attack") |
| Ino, Yoshida, Matsutani, Fujino. Data Poisoning Attack against Neural Network-Based On-Device Learning Anomaly Detector by Physical Attacks on Sensors | Sensors 24(19):6416, 2024 | 10.3390/s24196416 | C ("boiling frog poisoning anomaly detector") |
| Kantchelian et al. Approaches to adversarial drift | AISec 2013, pp. 99-110 | 10.1145/2517312.2517320 | C (title) |
| Broadwater, Chellappa. Adaptive Threshold Estimation via Extreme Value Theory | IEEE TSP 58(2):490-500, 2010 | 10.1109/tsp.2009.2031285 | C ("evasion extreme value theory threshold ...") |
| Ozbek, Ojo, Madani, El-Khatib, Yang. Robustness of Anomaly Detection Models for ICS under Training-Time Data Contamination | arXiv, 2026 | arXiv:2608.23547 | W then X |
| Li. Robust Conformal Intrusion Detection via Traffic-Aware Calibration and Attack-Orbit Invariance | arXiv, 2026 | arXiv:2609.19241 | W then X |
| Principato, Stoltz. Adaptive Conformal Inference through the Lens of Blackwell Approachability | arXiv, 2025 | arXiv:2510.15824 | X (ACI adversarial query) |
| Ben-Eliezer, Jayaram, Woodruff, Yogev. A Framework for Adversarially Robust Streaming Algorithms | ACM SIGMOD Record 50(1):6-13, 2021 | 10.1145/3471485.3471488 | C (title) |
| Ma, Muthukrishnan, Sandler. Frugal Streaming for Estimating Quantiles | LNCS, 2013, pp. 77-96 | 10.1007/978-3-642-40273-9_7 | C (title) |
| Chahine, Noura. Features over Architecture: Physics-Informed Anomaly Detection in ICS | Future Internet 18:308, 2026 | 10.3390/fi18060308 | W (Seo query) then C |
| Goh, Adepu, Junejo, Mathur. A Dataset to Support Research in the Design of Secure Water Treatment Systems | LNCS (CRITIS 2016), 2017, pp. 88-99 | 10.1007/978-3-319-71368-7_8 | D; C |
| Garg, Zhang, Samaran, Savitha, Foo. An Evaluation of Anomaly Detection and Diagnosis in Multivariate Time Series | IEEE TNNLS 33(6):2508-2517, 2022 | 10.1109/tnnls.2021.3105827 | C (title) |
| Fung, Srinarasi, Lucas, Phee, Bauer. Perspectives from a Comprehensive Evaluation of Reconstruction-based Anomaly Detection in ICS | LNCS, 2022, pp. 493-513 | 10.1007/978-3-031-17143-7_24 | C (title) |
| Kim, Choi, Choi, Lee, Yoon. Towards a Rigorous Evaluation of Time-Series Anomaly Detection | AAAI 2022, 36(7):7194-7201 | 10.1609/aaai.v36i7.20680 | C (title) |
| EEMUA Publication 191, Alarm systems: a guide to design, management and procurement | EEMUA, 4th ed. 2024 (3rd ed. 2013, ISBN 9780859311922) | eemua.org product page | W ("EEMUA Publication 191 ...") |
| ANSI/ISA-18.2-2016, Management of Alarm Systems for the Process Industries | ISA, 2016 (standard; no DOI) | management-of-change clause confirmed via Emerson white paper | D; W |

## 7. Could not verify

| Item | What was searched | Status |
|---|---|---|
| "Adversarial Impact on Anomaly Detection in Cloud Datacenters" (IEEE Xplore document 8952139) | web search on AIOps / cloud poisoning | Authors, venue, year and DOI not retrieved; not cited |
| Master's thesis on demonstrating and characterising frog-boiling (2026, author surname Thompson) | web search on ANTIDOTE boiling frog | Seen only through an expiring repository link; no stable identifier; not cited |
| "Physics-Informed Generative AI-Framework for Secure Anomaly Detection in Class-Imbalanced ICS" (2026), whose threshold rises with false positives | web search on Seo et al. | ResearchGate page only; no DOI or arXiv ID; not cited. If it is published, it would be a direct example of an exceedance-learning threshold in a 2026 ICS detector |
| Journal (JMLR) version of Gibbs and Candes 2022 | arXiv title search | Only the arXiv record confirmed; cite arXiv:2208.08401 |
| Original PODS / J. ACM version of Ben-Eliezer et al. | Crossref title look-up | Only the SIGMOD Record 2021 version confirmed |
| Text of ANSI/ISA-18.2-2016 | web search | Not freely available; the management-of-change requirement is cited through a vendor white paper. Check the clause in the standard before quoting it |
| Abstract of Seo et al. 2026 (ICUFN) | Crossref (no abstract deposited), web search | Existence and metadata confirmed; content unknown |
| Post-2005 SPC literature on contamination of self-starting or adaptive control charts by out-of-control data | one Crossref query | Only Sullivan and Jones (Technometrics 2002) returned, outside the window; not pursued further |

## Appendix A. Search log

### A.1 Programmatic topic sweep

Topics: T1 threshold attacks; T2 frog-boiling; T3 adaptive conformal inference under adversarial shift; T4 ICS threshold practice; T5 alarm management. "request failed" means the request did not complete (proxy refusal or rate limit), not that there were zero matches.

| Topic | Source | Query | Hits returned |
|---|---|---|---|
| frog | crossref | `frog-boiling attack anomaly detection` | request failed |
| frog | crossref | `Casting out demons sanitizing training data for anomaly sensors` | request failed |
| ics | crossref | `Limiting the impact of stealthy attacks on industrial control systems` | request failed |
| ics | crossref | `Attacks against process control systems risk assessment detection and response` | 3 |
| thr | crossref | `Optimal thresholds for anomaly-based intrusion detection in dynamical environments` | 3 |
| frog | crossref | `Poisoning attacks on cyber attack detectors for industrial control systems` | 3 |
| frog | crossref | `Practical evaluation of poisoning attacks on online anomaly detectors in industrial control systems` | 3 |
| thr | crossref | `An evaluation of anomaly detection and diagnosis in multivariate time series` | 3 |
| aci | crossref | `Practical adversarial multivalid conformal prediction` | 3 |
| alarm | crossref | `An overview of industrial alarm systems main causes for alarm overloading` | 3 |
| alarm | crossref | `99% false positives qualitative study of SOC analysts perspectives on security alarms` | 3 |
| frog | crossref | `Security analysis of online centroid anomaly detection` | 3 |
| thr | crossref | `Netspot simple intrusion detection system statistical learning` | 3 |
| T1 threshold attacks | crossref | `poisoning dynamic threshold anomaly detection` | 20 |
| T1 threshold attacks | crossref | `adversarial attack adaptive threshold anomaly detection` | 20 |
| T1 threshold attacks | crossref | `evasion extreme value theory threshold anomaly detection` | 20 |
| T1 threshold attacks | crossref | `peaks over threshold streaming anomaly detection attack` | 20 |
| T1 threshold attacks | dblp | `threshold poisoning anomaly` | request failed |
| T1 threshold attacks | dblp | `adaptive threshold attack anomaly detection` | request failed |
| T1 threshold attacks | dblp | `dynamic thresholding anomaly` | request failed |
| T1 threshold attacks | dblp | `SPOT extreme value streams` | request failed |
| T1 threshold attacks | arxiv | `abs:"dynamic threshold" AND abs:anomaly AND abs:adversarial` | 1 |
| T1 threshold attacks | arxiv | `abs:"peaks-over-threshold" AND abs:anomaly` | 1 |
| T1 threshold attacks | arxiv | `abs:threshold AND abs:poisoning AND abs:"anomaly detection"` | 3 |
| T2 frog boiling | crossref | `frog boiling attack` | 20 |
| T2 frog boiling | crossref | `boiling frog poisoning anomaly detector` | 20 |
| T2 frog boiling | crossref | `gradual drift poisoning online anomaly detection` | 20 |
| T2 frog boiling | crossref | `poisoning self-updating intrusion detection` | 20 |
| T2 frog boiling | dblp | `boiling frog` | request failed |
| T2 frog boiling | dblp | `frog-boiling` | request failed |
| T2 frog boiling | dblp | `poisoning online anomaly detection` | request failed |
| T2 frog boiling | dblp | `poisoning attack anomaly detector` | request failed |
| T2 frog boiling | arxiv | `abs:"boiling frog"` | 5 |
| T2 frog boiling | arxiv | `abs:"frog-boiling"` | 1 |
| T2 frog boiling | arxiv | `abs:poisoning AND abs:"online anomaly detection"` | 0 |
| T2 frog boiling | arxiv | `abs:poisoning AND abs:telemetry AND abs:anomaly` | 2 |
| T3 ACI adversarial | crossref | `adaptive conformal inference adversarial` | 20 |
| T3 ACI adversarial | crossref | `online conformal prediction adversarial distribution shift` | 20 |
| T3 ACI adversarial | crossref | `online quantile estimation adversarial stream` | 20 |
| T3 ACI adversarial | dblp | `adaptive conformal inference` | request failed |
| T3 ACI adversarial | dblp | `conformal prediction poisoning` | request failed |
| T3 ACI adversarial | dblp | `adversarially robust streaming quantile` | request failed |
| T3 ACI adversarial | arxiv | `abs:"adaptive conformal inference" AND abs:adversarial` | 3 |
| T3 ACI adversarial | arxiv | `abs:"online conformal" AND abs:poisoning` | 0 |
| T3 ACI adversarial | arxiv | `abs:"conformal" AND abs:"anomaly detection" AND abs:"time series" AND abs:online` | 0 |
| T4 ICS thresholds | crossref | `threshold selection anomaly detection industrial control systems SWaT` | 20 |
| T4 ICS thresholds | crossref | `anomaly detection HAI dataset threshold` | 20 |
| T4 ICS thresholds | crossref | `BATADAL attack detection threshold` | 20 |
| T4 ICS thresholds | crossref | `stealthy attacks threshold CUSUM control systems` | 20 |
| T4 ICS thresholds | dblp | `HAI dataset ICS` | request failed |
| T4 ICS thresholds | dblp | `threshold industrial control anomaly detection evaluation` | request failed |
| T4 ICS thresholds | dblp | `stealthy attack CUSUM` | request failed |
| T4 ICS thresholds | arxiv | `abs:SWaT AND abs:threshold AND abs:"anomaly detection"` | request failed |
| T4 ICS thresholds | arxiv | `abs:"industrial control" AND abs:threshold AND abs:evasion` | request failed |
| T5 alarm management | crossref | `alarm management ISA 18.2 nuisance alarms` | request failed |
| T5 alarm management | crossref | `EEMUA 191 alarm systems` | request failed |
| T5 alarm management | crossref | `alarm fatigue operators process industry` | request failed |
| T5 alarm management | crossref | `alarm deadband delay timer chattering alarms` | request failed |
| T5 alarm management | arxiv | `abs:"alarm fatigue" AND abs:security` | request failed |

### A.2 Web searches

1. `poisoning attack SPOT DSPOT extreme value threshold anomaly detection` (no attack on SPOT found; surfaced Kravchik et al. 2021)
2. `adversarial attack on dynamic threshold Telemanom nonparametric thresholding evasion` (no attack on Telemanom's threshold found)
3. `arXiv 2603.08455 boiling frog threshold world model anomaly detection gradual drift` (verified Hong 2026; surfaced Atarmla 2026)
4. `online conformal prediction data poisoning attack adaptive conformal inference adversary inflate coverage` (surfaced Li 2026; no poisoning attack on ACI found)
5. `"Retraining Data Poisoning Attacks on Drift Adaptive Anomaly Detection for Industrial Control Systems"` (Kravchik et al. abstracts; Ozbek et al. 2026)
6. `"Adversarial Habituation Attack" boiling frog CCS 2025 poster`
7. `ISA-18.2 management of change alarm setpoint changes authorized approval alarm rationalization`
8. `"HAI 1.0" HIL-based augmented ICS security dataset Shin Lee Yun Kim CSET 2020 USENIX`
9. `ANTIDOTE understanding and defending against poisoning of anomaly detectors IMC 2009 doi 10.1145`
10. `Rubinstein ANTIDOTE PCA subspace Q-statistic threshold retrained boiling frog poisoning chaff weekly`
11. `Urbina Giraldo Cardenas "Limiting the impact of stealthy attacks on industrial control systems" abstract ...`
12. `Ghafouri Abbas Laszka Vorobeychik Koutsoukos "Optimal thresholds for anomaly-based intrusion detection in dynamical environments" ...`
13. `Seo Lee Seo ICUFN 2026 retraining data poisoning drift adaptive anomaly detection industrial control systems HAI threshold`
14. `jmlr.org Kloft Laskov "Security Analysis of Online Centroid Anomaly Detection" volume 13 2012`
15. `usenix.org Alahmadi Axon Martinovic "99% False Positives" SOC analysts security alarms USENIX Security 2022` (also surfaced Dhananjeyan and U 2026)
16. `AIOps cloud monitoring anomaly detection adversarial poisoning dynamic threshold attack paper` (no threshold-poisoning paper found)
17. `EEMUA Publication 191 Alarm systems a guide to design, management and procurement edition 2013`
18. `Cárdenas Amin Lin Huang Huang Sastry "Attacks against process control systems ..." ASIACCS 2011 abstract CUSUM stealthy`
19. `OmniAnomaly Su KDD 2019 threshold selection POT peaks-over-threshold automatic anomaly threshold`

### A.3 Verification look-ups

About 80 Crossref title look-ups (one per candidate; best match kept only when the returned title matched), Crossref record fetches for 38 DOIs, arXiv abstract pages or API title records for every arXiv ID cited (the abstract-page check exposed the HAI 1.0 identifier error), and doi.org handle resolution for all 45 DOIs cited above.
