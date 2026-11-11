# Prior art and citation check: "Thresholds in the Wild"

Compiled 2026-11-11 from web sources only (WebSearch and WebFetch). Every claim below lists the URL it was confirmed from. Where a page could not be opened, the entry says so and says what was tried. Summaries of search results are marked as such when the primary page was not opened.

---

## Task 1: has the audit already been done?

### 1.1 Academic work, attacks on adaptive or retrained anomaly detectors

| # | Citation | What was tested | Result | Closeness to planned audit |
|---|---|---|---|---|
| A1 | B. I. P. Rubinstein, B. Nelson, L. Huang, A. D. Joseph, S. Lau, S. Rao, N. Taft, J. D. Tygar. "ANTIDOTE: Understanding and Defending against Poisoning of Anomaly Detectors." ACM IMC 2009, pp. 1-14. URLs: https://ptolemy.berkeley.edu/projects/truststc/pubs/725/IMC.2009.pdf ; dblp record https://dblp.dagstuhl.de/rec/conf/imc/RubinsteinNHJLRTT09.html (seen in search results; dblp page itself was bot-blocked when fetched for another record) ; tech report https://www2.eecs.berkeley.edu/Pubs/TechRpts/2008/EECS-2008-73.pdf | PCA-subspace traffic anomaly detector (Lakhina-style), retrained weekly, on backbone (Abilene) traffic; poisoning by chaff, including the "Boiling Frog" variant that raises poisoning slowly over several weeks. | Per search-result excerpts of the paper: one-week poisoning needs ~18% volume increase on the target flow to raise evasion from 4% to 50%; Boiling Frog gets the same with ~5% week-to-week increase over 3 weeks. Robust-PCA defense (ANTIDOTE) reduces the effect. Figures from excerpts, not re-read from the full PDF. | Same question (slow poisoning of a self-retraining detector), on the paper's own implementation of one algorithm. No shipped software, no quantile/EVT thresholds, no alarm-duration logic. |
| A2 | M. Kloft, P. Laskov. "Online Anomaly Detection under Adversarial Impact." AISTATS 2010, PMLR 9:405-412. https://proceedings.mlr.press/v9/kloft10a.html | Online centroid anomaly detector with finite sliding window; optimal greedy poisoning. | Attacker can shift the centroid with a linear amount of data; external constraints (e.g. bounded false-positive rate) can bound the attacker's gain. | Same question, theory plus own implementation; one algorithm. |
| A3 | M. Kloft, P. Laskov. "Security Analysis of Online Centroid Anomaly Detection." JMLR 13(118):3681-3724, 2012. https://jmlr.org/papers/v13/kloft12b.html | Journal version of A2; experiments on real HTTP traffic and exploits. | Optimal poisoning derived and bounded; a limited false-positive rate can make the attack arbitrarily hard. | Same question on own implementation. (Note: a search-engine summary gave pp. 3647-3690; the JMLR page itself says 3681-3724.) |
| A4 | B. Nelson, A. D. Joseph. "Bounding an Attack's Complexity for a Simple Learning Model." First Workshop on Tackling Computer Systems Problems with Machine Learning Techniques (SysML), Saint-Malo, 2006. Not opened; known only via citing works (search result https://ml.cs.rptu.de/publications/aistats2010.pdf). Status: not confirmed from the primary source. | Infinite-window centroid detector. | Bound on examples needed to shift the centre (as described by Kloft and Laskov). | Neighbouring (theory). |
| A5 | E. Chan-Tin, D. Feldman, N. Hopper, Y. Kim. "The Frog-Boiling Attack: Limitations of Anomaly Detection for Secure Network Coordinate Systems." SecureComm 2009, LNICST 19, doi:10.1007/978-3-642-05284-2_26. https://eudl.eu/doi/10.1007/978-3-642-05284-2_26 ; https://scholars.luc.edu/en/publications/the-frog-boiling-attack-limitations-of-anomaly-detection-for-secu/ ; PDF https://www-users.cs.umn.edu/~hopper/frogBoiling.pdf . Journal version: E. Chan-Tin, V. Heorhiadi, N. Hopper, Y. Kim, "Limitations of Secure Network Coordinate Systems," ACM TISSEC 2011, https://www-users.cs.umn.edu/~hopper/frogBoiling-tissec.pdf (titles/authors from search-result summary; PDFs not re-read). | Vivaldi network coordinates protected by outlier filters (Mahalanobis distance, Kalman-filter anomaly detection, Veracity); PlanetLab deployment. | Attacker that always stays inside the rejection threshold drags coordinates arbitrarily; outlier detection alone cannot secure the system. | Neighbouring field; same "stay under the adaptive threshold" mechanism as the closed-loop campaign; not anomaly-alarm software. |
| A6 | M. Kravchik, B. Biggio, A. Shabtai. "Poisoning Attacks on Cyber Attack Detectors for Industrial Control Systems." ACM SAC 2021, doi:10.1145/3412841.3441892. https://arxiv.org/abs/2012.15740 . Extended: M. Kravchik, L. Demetrio, B. Biggio, A. Shabtai, "Practical Evaluation of Poisoning Attacks on Online Anomaly Detectors in Industrial Control Systems," Computers & Security 122:102901, 2022, doi:10.1016/j.cose.2022.102901 (journal details from search-result summary citing https://www.bgu.ac.il/researcher/asaf-shabtai/publications/326318327/ and the author manuscript https://iris.unica.it/bitstream/11584/345358/3/Poisoning_Cyber_Physical_Attack_Detectors___Extended.pdf; journal page not opened). | Autoencoder / NN ICS detectors that are periodically retrained on operational data; interpolation and back-gradient poisoning; synthetic data, SWaT-type testbed data, Tennessee Eastman. | Both poisoning attacks effective (abstract). The arXiv abstract does not say whether the detection threshold is the thing that moves. | Same question in ICS, own implementation of NN detectors; not shipped tools. |
| A7 | S. Bhattacharjee, M. J. Islam, S. Abedzadeh. "Robust Anomaly based Attack Detection in Smart Grids under Data Poisoning Attacks." CPSS '22 (8th ACM Cyber-Physical System Security Workshop, at AsiaCCS '22), pp. 3-14, 2022. doi:10.1145/3494107.3522778. Metadata https://api.crossref.org/works/10.1145/3494107.3522778 ; abstract https://api.semanticscholar.org/graph/v1/paper/DOI:10.1145/3494107.3522778?fields=title,authors,venue,year,abstract | Learned anomaly thresholds for smart-meter falsification detection; white- and black-box poisoning of the threshold learning. | Poisoning hurts the detector; changing the regression type and loss used to learn the threshold makes it more robust. | Same question (poisoning of a learned threshold), own implementation, one domain. |
| A8 | Ł. Korycki, B. Krawczyk. "Adversarial concept drift detection under poisoning attacks for robust data stream mining." Machine Learning 112(10):4013-4048 (online 2 Jun 2022; issue Oct 2023). doi:10.1007/s10994-022-06177-w. https://api.crossref.org/works/10.1007/s10994-022-06177-w ; arXiv:2009.09497 | Drift detectors in stream classifiers; attacker injects data imitating drift. | Standard drift detectors cannot tell adversarial from real drift; proposes RBM-based robust detector and "Relative Loss of Robustness" metric. | Neighbouring (drift adaptation abuse in stream classification, not alarm thresholds). |
| A9 | F. Hinder, V. Vaquet, B. Hammer. "Adversarial Attacks for Drift Detection." ESANN 2025; arXiv:2411.16591. https://arxiv.org/abs/2411.16591v2 ; https://esann.org/sites/default/files/proceedings/2025/ES2025-82.pdf (from search result) | Common drift detectors. | Constructs "drift adversarials": streams that drift without being detected; conditions for their existence. | Neighbouring (drift-detector blind spots; mirrors the boiling-frog campaign). |
| A10 | D. Han et al. "Anomaly Detection in the Open World: Normality Shift Detection, Explanation, and Adaptation" (OWAD). NDSS 2023. https://www.ndss-symposium.org/ndss-paper/anomaly-detection-in-the-open-world-normality-shift-detection-explanation-and-adaptation/ | Deep-learning security anomaly detectors under benign normality shift; label-efficient adaptation. | Detects, explains and adapts to shift. Abstract does not consider an adversary steering the adaptation. | Neighbouring: the adaptation step it adds is the attack surface the planned audit measures. |
| A11 | A. Atarmla. "The Price of Self-Calibration: Exact Evidence Budgets and Manufactured Blind Sets in Adaptive Monitoring." arXiv:2609.23254, 19 Sep 2026. https://arxiv.org/abs/2609.23254 ; https://arxiv.org/html/2609.23254v1 | Online quantile tracker and self-calibrating monitors (theory). | Exact excess-alarm budget of a step (~delta/eta); windowed alarm rate fluctuates on 1/L scale; any monitor that tolerates a drift class is blind to faults in the difference class ("every fault with speed at most 2*eps*eta is invisible to every compliant rule"). Not framed adversarially. | Same mechanism as the planned "boiling frog" campaign, theory only, no software tested. |
| A12 | Z. Hong. "The Boiling Frog Threshold: Criticality and Blindness in World Model-Based Anomaly Detection Under Gradual Drift." arXiv:2603.08455, 9 Mar 2026. https://arxiv.org/abs/2603.08455 | z-score, variance and percentile detectors on an RL agent's world-model error, four MuJoCo environments; non-adversarial gradual drift. | Sharp drift-rate threshold below which drift is absorbed; sinusoidal drift evaded every detector. | Neighbouring (benign drift, own detectors). |
| A13 | B. I. P. Rubinstein et al. "Stealthy poisoning attacks on PCA-based anomaly detectors." ACM SIGMETRICS Perf. Eval. Review 2009. https://www.cs.berkeley.edu/~tygar/papers/SML/Stealthy_poisoning.pdf (seen in results, not opened) | PCA detector. | Short version of A1 results. | Same as A1. |
| A14 | D. Nkashama et al. "Deep Learning for Network Anomaly Detection under Data Contamination." arXiv:2407.08838. https://arxiv.org/abs/2407.08838 | Six unsupervised deep NIDS detectors trained on contaminated "benign" data. | Strong degradation; proposes constrained-latent autoencoder. | Neighbouring (static contamination, not adaptive thresholds). |
| A15 | A. Tuor et al. "Recurrent Neural Network Language Models for Open Vocabulary Event-Level Cyber Anomaly Detection." AAAI-18 AICS workshop; arXiv:1712.00557. https://ar5iv.labs.arxiv.org/html/1712.00557 | Online daily-updated RNN on LANL auth logs. | Updates the model each day on that day's lines; red-team labels used only for evaluation; reports AUC/AP. | Example of a detector that keeps learning through an attack period without measuring absorption. |
| A16 | Tariq et al. (authors from search summary only, not confirmed), adversarial perturbation of time-series anomaly detectors, arXiv:2208.11264 (seen in results, not opened) | Deep and graph TS anomaly detectors, FGSM/PGD on sensor data. | Detection can drop to 0% (per result summary). | Neighbouring (test-time evasion, not threshold absorption). |
| A17 | G. Lovisotto, S. Eberz, I. Martinovic. "Biometric Backdoors: A Poisoning Attack Against Unsupervised Template Updating." IEEE EuroS&P 2020, pp. 184-197, doi:10.1109/EuroSP48549.2020.00020. arXiv:1905.09162; https://ora.ox.ac.uk/objects/uuid:8f12be84-01f4-47c3-83c9-c08ac53eee8a | Face-recognition templates with unsupervised self-update. | Step-wise injected samples drift the template until the attacker is accepted (>70% white-box success with <10 injections); countermeasure based on directional consistency of updates. | Neighbouring field; same ratcheting mechanism. |
| A18 | D. Pasquini et al. (author list not opened) "When AIOps Become 'AI Oops': Subverting LLM-driven IT Operations via Telemetry Manipulation." arXiv:2508.06394; USENIX Security 2026 prepub https://www.usenix.org/system/files/conference/usenixsecurity26/sec26_prepub_pasquini.pdf (seen in results, not opened) | LLM AIOps agents fed manipulated telemetry. | Agents reach attacker-chosen conclusions (per summary). | Neighbouring (LLM agents, not statistical thresholds). |
| A19 | Siffer et al. SPOT/DSPOT (KDD 2017) https://www.eecs.yorku.ca/course_archive/2018-19/F/6412/reading/kdd17p1067.pdf ; Brutlag, "Aberrant Behavior Detection in Time Series for Network Service Monitoring," LISA 2000, https://www.usenix.org/legacy/events/lisa00/brutlag.html ; Hundman et al. Telemanom, KDD 2018, arXiv:1802.04431 | Original algorithm papers. | No adversarial evaluation found for any of the three (searches 10, 19, 33 below). | Targets, not prior art. |

Searches that found no adversarial study at all: Random Cut Forest / OpenSearch AD (queries 4, 17), Elastic ML (query 30), Netdata (18), Numenta HTM / NAB (11, forum discussions only), Holt-Winters / RRDtool (9, 19), SPOT/DSPOT (10), Zabbix / Checkmk (28), Telemanom (33), Merlion / PySAD / river (24), Kitsune poisoning (26).

### 1.2 Vendor and project documentation that warns about absorption, or ships a guard

| Product | What the documentation says | URL |
|---|---|---|
| Netdata ML | "When an anomaly occurs, the newest model will learn it as 'normal' within 3 hours." 18 k-means models per metric, 6-h windows every 3 h, flagged only if all 18 agree; full forgetting in 54 h. Accuracy page lists "Previously seen anomalous patterns become normalized" and "Gradual degradation may evade detection if it occurs over the full window". | https://learn.netdata.cloud/docs/netdata-ai/anomaly-detection ; https://learn.netdata.cloud/docs/ai-&-ml/ml-anomaly-detection/ml-accuracy |
| Azure Monitor dynamic thresholds | "Slow behavior changes probably won't trigger an alert." Thresholds "continually use all available historical data to learn"; option to set a start date for learning; prolonged outages are removed from learning. | https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/alerts-dynamic-thresholds |
| AWS CloudWatch anomaly detection | Trains on up to two weeks; retrains as metric evolves; "you can choose to exclude specified time periods of the metric from being used to train the model" (up to 10 ranges via API). | https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Anomaly_Detection.html |
| Datadog anomaly monitors | Agile algorithm: quick level-shift updates "at the expense of being less robust to recent, long-lasting anomalies"; robust algorithm: "predictions remain constant even through long-lasting anomalies"; basic uses a lagging rolling quantile. | https://docs.datadoghq.com/monitors/types/anomaly/ |
| Elastic ML | Calendars/scheduled events zero the anomaly score and (per API docs, from search summary) default skip_model_update; custom rules can "Skip model update"; docs say "Highly anomalous input increases the variance in the models" and suggest reverting to a model snapshot. Elastic staff: "Elastic ML already tries to not let anomalous values overly affect the model." | https://www.elastic.co/guide/en/machine-learning/current/ml-ad-run-jobs.html ; https://www.elastic.co/guide/en/machine-learning/7.5/ml-calendars.html ; https://discuss.elastic.co/t/does-applying-custom-rules-on-machine-learning-jobs-altert-the-ml-model/283797 |
| Splunk ITSI adaptive thresholds | Outlier exclusion removes points outside computed bounds from threshold training (per search summary of Splunk docs; page not opened directly). | https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/visualize-and-assess-service-health/5.0/advanced-thresholding/create-adaptive-kpi-thresholds-in-itsi |
| Dynatrace | Baselines are "learned typical behavior", retrained on schedule or trigger; frequent-issue detection mutes recurring alerts (summary; no absorption warning found). | https://docs.dynatrace.com/docs/shortlink/frequent-issues |
| river `anomaly.QuantileFilter` | `protect_anomaly_detector` default `True`: the wrapped detector is not updated on points flagged anomalous. Docs note the detector could otherwise gradually treat anomalous scores as normal. (The quantile itself still updates; to be checked in code.) | https://riverml.xyz/latest/api/anomaly/QuantileFilter/ |
| Numenta HTM | Forum: "an anomaly becomes new normal after being repeated for a while"; a user asks whether repeated anomalies could desensitise the model. Informal. | https://discourse.numenta.org/t/abnormal-vs-new-normal/7463 (from search result) |
| Checkmk predictive levels / Zabbix baseline functions | Docs describe floating thresholds from RRD history (Checkmk) and seasonal baselines/`trendstl` (Zabbix); no absorption or attack warning found. | https://docs.checkmk.com/2.4.0/en/predictive_monitoring.html ; https://www.zabbix.com/documentation/7.0/de/manual/appendix/functions/trends |

### 1.3 Verdict

No source found tests three or more of the listed shipped targets (river, RCF/OpenSearch AD, Elastic ML, Numenta/NAB, Telemanom, SPOT/DSPOT code, Netdata, Zabbix, RRDtool/Graphite Holt-Winters, Checkmk, PySAD, StreamAD, Merlion, Skyline) for absorption or poisoning. No source found tests even one of them adversarially. The evidence about shipped tools is vendor documentation that admits the effect (Netdata, Azure, Datadog, CloudWatch, Elastic) or ships a guard (river's `protect_anomaly_detector`, Elastic skip_model_update, CloudWatch excluded ranges, Splunk outlier exclusion, Azure outage removal), with no measurement of whether the guards hold against an adaptive attacker.

Closest single prior work: Rubinstein et al., ANTIDOTE (IMC 2009). It asks the same question (slow "Boiling Frog" poisoning of a detector that retrains on its own input) but on the authors' own PCA-subspace implementation, one algorithm, backbone traffic, weekly retraining. The planned audit adds: (1) shipped code at default settings across many tools; (2) the threshold layer (running quantiles, EVT/SPOT, anomaly likelihood, Holt-Winters bands, consensus of rolling models) rather than the model alone; (3) a closed-loop attacker that reads the current threshold; (4) sub-minimum-duration pulses against alarm-exclusion logic, which none of the found work tests; (5) a test of whether the shipped guards listed in 1.2 stop the campaigns. Atarmla (arXiv:2609.23254) gives theory for the quantile-tracker blind set and is the closest theoretical companion.

---

## Task 2: citation verification

| # | Status | Verified citation and finding | URL |
|---|---|---|---|
| 1 | Confirmed with corrections | A.-R. Atarmla, "The Price of Self-Calibration: Exact Evidence Budgets and Manufactured Blind Sets in Adaptive Monitoring," arXiv:2609.23254, 19 Sep 2026, sole author, no venue. Correction: it does not give a guarantee on robust threshold loosening. It gives exact excess-alarm budgets for steps/ramps on an online quantile tracker and proves a blind-set result: a monitor tolerant of a drift class misses every fault in the difference class (speed at most 2*eps*eta). It is non-adversarial and cites no prior attack on adaptive thresholds. | https://arxiv.org/abs/2609.23254 ; https://arxiv.org/html/2609.23254v1 |
| 2 | Confirmed | W. Wang, S. Feizi, "Temporal Robustness against Data Poisoning," NeurIPS 2023 (37th), arXiv:2302.03684. Defines earliness/duration threat model; temporal aggregation gives provable robustness against unbounded poisoning that is time-limited. | https://arxiv.org/abs/2302.03684 |
| 3 | Confirmed (no venue) | B. Wang, M. Zecchin, O. Simeone, "Online Conformal Prediction with Corrupted Feedback," arXiv:2605.20515, 19 May 2026. Corrupted (flipped) coverage feedback degrades online conformal thresholds; two robust variants with miscoverage guarantees. | https://arxiv.org/abs/2605.20515 |
| 4 | Confirmed | M. Bashari, M. Sesia, Y. Romano, "Robust Conformal Outlier Detection under Contaminated Reference Data," ICML 2025, PMLR 267:3091-3141; arXiv:2502.04807. Non-adversarial contamination of the reference set makes conformal outlier detection conservative (lower power); active cleaning recovers power. | https://arxiv.org/abs/2502.04807 ; https://proceedings.mlr.press/v267/ |
| 5 | Confirmed with corrections | Authors are S. Bhattacharjee, M. J. Islam, S. Abedzadeh (Western Michigan); title "Robust Anomaly based Attack Detection in Smart Grids under Data Poisoning Attacks"; Proc. 8th ACM Cyber-Physical System Security Workshop (CPSS '22, at AsiaCCS '22), pp. 3-14. Shows white/black-box poisoning of learned detection thresholds for smart-meter data and more robust threshold learning. | https://api.crossref.org/works/10.1145/3494107.3522778 |
| 6 | Confirmed with corrections | Ł. Korycki, B. Krawczyk, "Adversarial concept drift detection under poisoning attacks for robust data stream mining," Machine Learning 112(10):4013-4048. Year: online 2 Jun 2022, issue Oct 2023 (cite as 2023, vol 112, or 2022 online). Shows drift detectors cannot separate adversarial from real drift; proposes robust RBM detector. | https://api.crossref.org/works/10.1007/s10994-022-06177-w |
| 7 | Confirmed | M. Kloft, P. Laskov, "Security Analysis of Online Centroid Anomaly Detection," JMLR 13(118):3681-3724, 2012. Optimal poisoning of online centroid detector, with bounds; a false-positive constraint can make the attack arbitrarily hard. | https://jmlr.org/papers/v13/kloft12b.html |
| 8 | Confirmed with corrections | A. Tuor, R. Baerwolf, N. Knowles, B. Hutchinson, N. Nichols, R. Jasper, arXiv:1712.00557, AAAI-18 Workshop on AI for Cyber Security (not main AAAI). The model scores each day then updates on that day's lines, red-team labels used only for evaluation, so red-team lines appear to stay in training (inference; the paper does not state exclusion). Correction: it reports AUC and AP at user-day and line level plus a recall-vs-fraction-flagged curve, not only one aggregate AUC; it does not measure absorption. | https://arxiv.org/abs/1712.00557 ; https://ar5iv.labs.arxiv.org/html/1712.00557 |
| 9 | Confirmed | D. Han, Z. Wang, W. Chen, K. Wang, R. Yu, S. Wang, H. Zhang, Z. Wang, M. Jin, J. Yang, X. Shi, X. Yin, "Anomaly Detection in the Open World: Normality Shift Detection, Explanation, and Adaptation," NDSS 2023. Benign normality shift handling; no adversarial manipulation of adaptation in the abstract. | https://www.ndss-symposium.org/ndss-paper/anomaly-detection-in-the-open-world-normality-shift-detection-explanation-and-adaptation/ |
| 10 | Confirmed | D. K. Nkashama, J. M. Félicien, A. Soltani, J.-C. Verdier, P.-M. Tardif, M. Frappier, F. Kabanza, "Deep Learning for Network Anomaly Detection under Data Contamination: Evaluating Robustness and Mitigating Performance Degradation," arXiv:2407.08838 (v2 Sep 2024), no venue listed. Six unsupervised deep detectors degrade under contaminated training data. | https://arxiv.org/abs/2407.08838 |
| 11 | Confirmed | G. Lovisotto, S. Eberz, I. Martinovic, "Biometric Backdoors: A Poisoning Attack Against Unsupervised Template Updating," IEEE EuroS&P 2020, pp. 184-197. Gradual template drift via injected samples; countermeasure on update direction. | https://arxiv.org/abs/1905.09162v2 ; https://ora.ox.ac.uk/objects/uuid:8f12be84-01f4-47c3-83c9-c08ac53eee8a (pages/DOI per search summary; Crossref fetch returned HTTP 429) |
| 12 | Confirmed; host count from a secondary source | A. D. Kent, "Comprehensive, Multi-Source Cyber-Security Events," Los Alamos National Laboratory, 2015, doi:10.17021/1179829. 58 days, 1,648,275,307 events, 12,425 users, 17,684 computers. redteam.txt format: time,user@domain,source computer,destination computer. Neither official page states the event count (749) or number of source hosts. Bai et al., "A Machine Learning Approach for RDP-based Lateral Movement Detection" (IEEE LCN 2019) state: "all red team events in the dataset originate from four unique hosts." The 749 count was seen only in an unopened third-party table (403). | https://www.osti.gov/biblio/1179829 ; https://csr.lanl.gov/data/cyber1/ ; https://rboutaba.cs.uwaterloo.ca/Papers/Conferences/2019/BaiLCN19.pdf |
| 13 | Confirmed (no venue) | R. Pandey, A. Bhujang, "Poisoning the Watchtower: Prompt Injection Attacks Against LLM-Augmented Security Operations Through Adversarial Log Content," arXiv:2605.24421, 23 May 2026. Attacker-controlled log fields manipulate SOC LLM assistants (gpt-4o-mini, 48 configurations); defenses reduce but do not remove. | https://arxiv.org/abs/2605.24421 |
| 14 | Confirmed (no venue) | R. Karanjai, Y. Lu, H. H. Madhavarao, L. Xu, W. Shi, "Context Contamination in LLM Analysis of Network Security Logs: Poison with Passive Prompt Injection and Mitigation Evaluation," arXiv:2607.14493, 16 Jul 2026. LogInject benchmark (12,847 entries); up to 88.2% attack success; layered defenses leave 8.4%. | https://arxiv.org/abs/2607.14493 |
| 15 | Confirmed | L. Tong, A. Laszka, C. Yan, N. Zhang, Y. Vorobeychik, "Finding Needles in a Moving Haystack: Prioritizing Alerts with Adversarial Reinforcement Learning," AAAI 2020, 34(01):946-953. Alert prioritisation as a defender-attacker game solved with adversarial RL/double oracle. | https://api.crossref.org/works/10.1609/aaai.v34i01.5442 ; arXiv:1906.08805 |
| 16 | Confirmed with note | S. Patton, W. Yurcik, D. Doss, "An Achilles' Heel in Signature-Based IDS: Squealing False Positives in SNORT," presented at RAID 2001 (Davis, CA). Spoofed packets matching any Snort signature generate false alarms that can hide a real attack and repudiate IDS evidence. Not confirmed whether it appears in the LNCS 2212 proceedings (Springer and dblp pages were blocked); cite as RAID 2001 presentation/paper. | https://homeostasis.scs.carleton.ca/~soma/id-2007w/readings/patton_yurcik_doss_raid2001.pdf (PDF metadata "PattonYurcikDossRAID01.doc"); slides https://www.sambuz.com/doc/an-achilles-heel-in-signature-based-ids-squealing-false-ppt-presentation-754193 |
| 17 | Confirmed (no venue on arXiv) | T. Shi, J. He, Z. Wang, H. Li, L. Wu, W. Guo, D. Song, "Progent: Securing AI Agents with Privilege Control" (title of the current v3; titles of earlier versions not checked), arXiv:2504.11703, v1 16 Apr 2025, v3 14 May 2026. Symbolic per-tool privilege policies checked on every call. | https://arxiv.org/abs/2504.11703 |
| 18 | Confirmed (no venue on arXiv) | E. Debenedetti, I. Shumailov, T. Fan, J. Hayes, N. Carlini, D. Fabian, C. Kern, C. Shi, A. Terzis, F. Tramèr, "Defeating Prompt Injections by Design" (CaMeL), arXiv:2503.18813, 2025. Separates control flow from untrusted data; capabilities enforce data-flow policies; 77% of AgentDojo tasks with provable security. | https://arxiv.org/abs/2503.18813 |

---

## Task 3: venues for 2027

Dates were taken only from official pages opened on 2026-11-11.

| Venue | Status | Dates | Source |
|---|---|---|---|
| IEEE S&P 2027 (Montreal, 17-20 May 2027) | Announced | Cycle 1 closed (11 Jun 2026). Cycle 2: submission 17 Nov 2026 AoE; early reject 18 Jan 2027; notification 5 Mar 2027. S&P 2028 first cycle: not announced (sp2028 site does not resolve). | https://sp2027.ieee-security.org/cfpapers.html |
| USENIX Security 2027 (Denver, 11-13 Aug 2027) | Announced (preliminary CFP) | Cycle 1 closed (25 Aug 2026). Cycle 2: registration 19 Jan 2027, submission 26 Jan 2027, notification 6 May 2027 (AoE). | https://www.usenix.org/node/321195 |
| AsiaCCS 2027 (Macau, 12-16 Jul 2027) | Announced | Round 1 closed (21 Aug 2026; notification 13 Nov 2026). Round 2: submission 11 Dec 2026 AoE, notification 31 Mar 2027. | https://asiaccs2027.cityu.edu.mo/call-for-papers/ |
| EuroS&P 2027 (Madrid, 5-9 Jul 2027) | Announced | Registration 25 Nov 2026; submission 2 Dec 2026; early reject 28 Jan 2027; rebuttal 24 Feb-1 Mar 2027; notification 18 Mar 2027 (AoE). | https://eurosp2027.ieee-security.org/cfp.html |
| DSN 2027 (Berlin, 22-25 Jun 2027) | Announced | Abstract 25 Nov 2026; full paper 2 Dec 2026; early reject 26 Jan 2027; rebuttal 12-26 Feb 2027; notification 18 Mar 2027 (AoE). | https://dsn2027-berlin.github.io/important-dates/ |
| DIMVA 2027 (Enschede, 30 Jun-2 Jul 2027) | Announced | Cycle 1: abstract 3 Dec 2026, submission 10 Dec 2026, notification 28 Jan 2027. Cycle 2: abstract 11 Feb 2027, submission 18 Feb 2027, notification 8 Apr 2027. | http://www.dimva.org/dimva2027/ |
| NDSS 2027 | Both cycles closed (6 May 2026, 19 Aug 2026) | - | https://www.ndss-symposium.org/ndss2027/submissions/call-for-papers/ |
| NDSS 2028 | Not announced / not found | - | NDSS 2027 CFP page has no 2028 mention |
| CCS 2027 (Atlanta, 11-15 Oct 2027) | Site up, deadlines not announced ("Coming Soon") | - | https://www.sigsac.org/ccs/CCS2027/ |
| RAID 2027 (Chicago) | Not announced ("call for papers will be announced soon") | - | https://www.raid2027.org/ |
| ACSAC 2027 | Not announced / not found (acsac.org shows ACSAC 42, 7-11 Dec 2026) | - | https://www.acsac.org/ |
| IMC 2027 | Not found (IMC site behind bot check; a third-party listing says Atlanta, not verified) | - | tried https://conferences.sigcomm.org/imc/2027/ and /cfp |
| ESORICS 2027 | Not announced / not found | - | searches only returned ESORICS 2026 |
| AISec 2027 (ACM, with CCS) | Not announced / not found (aisec.cc shows the 2026 edition, 15 Nov 2026) | - | https://aisec.cc/ |
| CPSIoTSec 2027 (with CCS) | Not found | - | search only |
| CPSS 2027 (with AsiaCCS) | Not announced (AsiaCCS 2027 workshops "To be announced later") | - | https://asiaccs2027.cityu.edu.mo/workshops/index.html |
| LASER | Not found; laser-workshop.org lists last edition as LASER 02/2021 (with NDSS) | - | https://www.laser-workshop.org/ |
| WORLDS 2027 | Not found (no security workshop of that name located) | - | search only |

Unofficial tracker estimates (not used as dates): ACSAC 2027 ~26 May 2027, CCS 2027 ~late Apr 2027, ESORICS 2027 ~9 Jan and ~21 Apr 2027 (https://sslab.skku.edu/deadlines.html, https://www.myhuiban.com/conference/296).

---

## Search queries run

Task 1 (prior art):
1. Rubinstein ANTIDOTE "boiling frog" poisoning PCA anomaly detector IMC 2009
2. Chan-Tin "frog-boiling attack" network coordinate systems Vivaldi
3. Kloft Laskov "Online anomaly detection under adversarial impact" AISTATS 2010
4. adversarial attack Random Cut Forest anomaly detection poisoning evasion
5. poisoning attack streaming anomaly detection adaptive threshold gradual drift evade
6. Elastic machine learning anomaly detection model learns anomaly into baseline "calendar" exclude "skip model update"
7. CloudWatch anomaly detection "exclude" time periods from training anomalies model
8. Datadog anomaly monitor "learn" anomalies baseline incidents agile robust algorithm "will quickly adjust"
9. Brutlag 2000 aberrant behavior detection Holt-Winters adversarial attack slow drift adapt
10. SPOT DSPOT extreme value threshold streaming attack poisoning adversarial "peaks over threshold"
11. Numenta HTM anomaly likelihood adversarial attack gradual change learned as normal
12. "drift adaptation" poisoning attack security anomaly detection 2024 2025 continual learning intrusion detection
13. UEBA baseline poisoning attack "low and slow" adversary trains behavioral baseline evade detection
14. ICS intrusion detection adaptive threshold poisoning attack stealthy industrial control "threshold" learned online
15. AIOps anomaly detection poisoning attack adversarial metrics monitoring evaluation open-source tools
16. Kravchik Demetrio Biggio Shabtai "Practical Evaluation of Poisoning Attacks on Online Anomaly Detectors in Industrial Control Systems"
17. OpenSearch anomaly detection plugin adversarial robustness attack evaluation random cut forest security
18. Netdata machine learning anomaly detection k-means retrain anomalies learned "anomaly bit" attack evade
19. "Holt-Winters" anomaly detection evasion attacker "slowly" increase traffic RRDtool aberrant
20. Azure Monitor dynamic thresholds "learn" anomalies historical data "ignore data" before
21. Dynatrace automatic baseline anomaly "learned" outage included baseline "frequent issue detection" suppress
22. Splunk ITSI adaptive thresholds exclude outliers training "adaptive thresholding" anomalies influence
23. "Adversarial Attacks for Drift Detection" Hinder Vaquet Hammer
24. adversarial robustness evaluation time series anomaly detection libraries Merlion PySAD river benchmark attack
25. "frog boiling" OR "boiling frog" attack anomaly detection threshold 2020..2026 time series
26. Kitsune online network intrusion detection poisoning attack retraining adversary evade
27. self-calibrating alarm threshold attack "false alarm rate" constraint adversary raise threshold anomaly detector "threshold manipulation"
28. "Thresholds That Travel" adaptive alarm thresholds sustained attacks poisoned
29. Zabbix trendstl baseline anomaly attack OR Checkmk "predictive levels" attacker slowly
30. adaptive threshold intrusion detection "poisoning" "EWMA" OR "exponentially weighted" attacker slowly shift baseline network anomaly
31. evaluating open-source anomaly detection tools security attacker perspective measurement study shipped defaults
32. Rubinstein Nelson Huang Joseph Lau Rao Taft Tygar ANTIDOTE IMC 2009 pages doi
33. "Poisoning Cyber-Physical Attack Detectors" Kravchik Demetrio Biggio Shabtai journal 2022
34. Elastic machine learning anomaly detection security research evasion attacker "anomaly detection job" bypass adversarial
35. Nelson Joseph "Bounding an attack's complexity for a simple learning model" 2006
36. Telemanom nonparametric dynamic thresholding Hundman KDD 2018 adversarial OR poisoning OR evasion

Task 2 (citations):
37. Lovisotto "Biometric Backdoors" poisoning template update EuroS&P 2020
38. Patton Yurcik Doss "An Achilles' heel in signature-based IDS: Squealing false positives in SNORT" RAID 2001
39. Bhattacharjee CPSS 2022 "3494107.3522778"
40. RAID 2001 Davis program "Squealing" Patton Yurcik abstract
41. LANL "redteam.txt" 749 events source computers red team compromised hosts
42. LANL comprehensive multi-source cyber-security events red team "749" "source" hosts
43. "Finding Needles in a Moving Haystack: Prioritizing Alerts with Adversarial Reinforcement Learning" abstract

Task 3 (venues):
44. RAID 2027 call for papers submission deadline
45. ACSAC 2027 call for papers deadline
46. IEEE Symposium on Security and Privacy 2027 call for papers submission deadlines cycles
47. USENIX Security 2027 call for papers cycle 2 deadline
48. ACM CCS 2027 call for papers deadlines
49. NDSS 2028 call for papers deadline
50. IEEE EuroS&P 2027 call for papers deadline
51. ACM Internet Measurement Conference IMC 2027 call for papers deadline
52. DSN 2027 Dependable Systems and Networks call for papers deadline
53. ESORICS 2027 call for papers deadline
54. DIMVA 2027 call for papers deadline
55. "IMC 2027" Internet Measurement Conference cycle deadline November 2026
56. ESORICS 2027 symposium location dates official site call for papers
57. AISec 2027 workshop artificial intelligence and security call for papers
58. CPSIoTSec 2027 OR "CPSS 2027" workshop cyber-physical security call for papers
59. LASER workshop 2027 learning from authoritative security experiment results call for papers
60. WORLDS 2027 workshop security call for papers

Pages fetched directly (beyond search): arXiv abs pages for 2609.23254, 2302.03684, 2605.20515, 2502.04807, 1712.00557, 2407.08838, 2605.24421, 2607.14493, 2504.11703, 2503.18813, 2012.15740, 2603.08455; arXiv HTML 2609.23254v1; ar5iv 1712.00557; Crossref API for the CPSS, AAAI and Machine Learning DOIs; Semantic Scholar API for CPSS and Korycki abstracts; JMLR v13 kloft12b; NDSS OWAD page; OSTI 1179829; csr.lanl.gov cyber1; Bai et al. LCN 2019 PDF (text extracted locally); PMLR v267 index; Netdata docs (2 pages); Azure, CloudWatch, Datadog, Elastic docs; Elastic forum thread; river QuantileFilter docs; all official venue pages listed in Task 3.

Fetches that failed: ojs.aaai.org (bot block), dl.acm.org (403), link.springer.com (login redirect), dblp.org (bot block), Crossref for 10.1109/EuroSP48549.2020.00020 (429), awesome.ecosyste.ms (403), raid-symposium.org (connection refused), archive.cps-vo.org (rejected), conferences.sigcomm.org IMC 2027 (bot check), sp2028.ieee-security.org (does not resolve).
