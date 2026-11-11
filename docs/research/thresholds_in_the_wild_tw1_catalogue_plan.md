# Thresholds in the Wild (tw1): catalogue plan

Written 2026-11-11 and committed before any target beyond the two probes below was read. This step opens
no dataset and runs no detector. It is a reading of public source code and documentation.

Parent memo: `next_directions_2026-11-10.md`. Parent study: "Thresholds That Travel" (tt1), whose
vocabulary (learning region, tracker, hold-out, frog, loud pulses, sub-event pulses) is used here.

## Question

At their default settings, do shipped open-source anomaly detectors update the quantity that decides an
alarm (a threshold on a score, a baseline or band on a signal, a score normaliser, or a model retrained
on recent data) with the samples they flag?

tt1 showed that rules we implemented ourselves go quiet under sustained attacks and can be poisoned when
they learn from their own alarms. The catalogue decides whether the same test on shipped software is
worth a paper.

## Known before this plan

- `river`, `river/anomaly/filter.py`: `QuantileFilter.learn_one` updates its running quantile with every
  score, flagged or not; `protect_anomaly_detector` shields the wrapped detector only. Read 2026-11-10.
- AWS `random-cut-forest-by-aws`, `BasicThresholder.java`: the running mean and deviation are updated
  with every score passed in. Whether the caller withholds flagged points was not read.
- Telemanom's dynamic threshold and SPOT / DSPOT were re-implemented from their papers in tt1c. Their
  reference code was not compared line by line.

These probes motivated the study, so the decision rule below is set knowing that river counts as one
absorbing target.

## Scope

A target is in scope when all three hold:

1. Its source is public and its licence permits reading it. The licence is recorded per target, with a
   note where it restricts running, benchmarking or publishing results.
2. It is software that people install: a library on a package index, a monitoring product, or a plugin
   of one. Reference code of a widely re-used method (SPOT, Telemanom, the Numenta anomaly likelihood)
   is catalogued and labelled "reference code".
3. In the configuration a user gets from the project's quickstart or defaults, some quantity that
   decides whether an alarm fires changes at run time with incoming data.

Closed products (for example Datadog, CloudWatch, Azure Anomaly Detector, Splunk MLTK) get rows from
their documentation only, in a separate table. They do not count in the decision rule.

Detectors whose threshold is fixed after training (for example PyOD's contamination threshold) are
catalogued as static controls when they sit in the same libraries. They show the catalogue can return a
"does not adapt" answer.

## Candidate list

Fixed now. A target may be added during the reading; each addition is logged with the date and the
reason. A candidate that turns out to be out of scope stays in the table with the reason.

| Group | Candidates |
|---|---|
| A. Python streaming libraries | river (`QuantileFilter`, `ThresholdFilter`, scorers that normalise their own output), PySAD (probability calibrators), StreamAD (calibrators, SPOT), Merlion (calibrators and threshold post-rules), Orion (`find_anomalies`), ADTK, Luminol, alibi-detect, PyOD (static control) |
| B. Search and observability engines | AWS Random Cut Forest (thresholder and its callers), OpenSearch Anomaly Detection plugin, Elastic ML (`ml-cpp` renormalisation; licence terms checked first) |
| C. Reference code | Numenta anomaly likelihood (NAB, htm.core), Telemanom, SPOT / DSPOT (the authors' Python code, libspot), Yahoo EGADS, Kitsune |
| D. Monitoring platforms | Netdata ML, Zabbix baseline and anomaly functions, RRDtool and Graphite Holt-Winters aberrant-behaviour detection, Checkmk predictive levels, Grafana's PromQL anomaly-detection rules, Skyline |

## What is recorded for each target

1. **Identity.** Name, repository, commit hash read, release version, licence, and one line of adoption
   evidence with its source and date.
2. **Default path.** The configuration a user gets from the quickstart, and the class or function that
   decides an alarm in it.
3. **Adaptive quantity.** Threshold, baseline, normaliser or model, with its update rule in one line.
4. **Learning region.** Which samples update it: all; all except flagged ones; flagged ones at reduced
   weight; batch windows. Given with file, line numbers and a verbatim quote of the update statement
   (five lines at most).
5. **Learns from its own alarms.** Yes, no, partial, or configurable (with the default).
6. **Memory.** Window length, decay constant, or a count-based rate that goes to zero.
7. **Direction and bounds.** Symmetric or tighten-only; any floor, ceiling or clamp, with its value.
8. **Alarm logic.** On-delay, consecutive-point counts, hysteresis, suppression after an alarm.
9. **Operator controls.** Exclusion windows, a freeze switch, feedback labels.
10. **Documentation.** What the project's documentation says about anomalies entering the baseline, quoted, or
    "silent".
11. **Closest tt1 rule.** Tracker, daily, daily with episodes left out, tracker with hold-off, SPOT,
    median + MAD, EWMA limit, EWMA limit with alarms left out, static with on-delay, static, or none,
    and where the target differs from it.
12. **Predictions.** For a sustained attack, loud pulses, the frog and sub-event pulses: absorb, resist
    or unclear, with a one-line reason. These are hypotheses for the development round, written before
    any run. They are never reported as results.
13. **Runnable here.** In-process, Docker, or not feasible on a 16 GB laptop, with a resource estimate.

## Method

- Sources are cloned at a recorded commit into a directory outside this repository. Nothing in them is
  installed or executed in this step.
- The reading is done by Opus subagents, one group each. They are briefed to record what the code does,
  and to give evidence against absorption (exclusion of flagged samples, clamps, alarm delays) the same
  weight as evidence for it.
- I then re-read items 4 and 5 of every row at the cited lines. A row is marked "verified" or "agent
  only". Only verified rows count in the decision rule.
- A row whose default path cannot be established is marked "unclear" and counts as not absorbing.
- **Prior art.** A wider literature search than the triage of 2026-11-10 looks for work that tests
  shipped implementations for absorption of attacks into a threshold or baseline, and re-verifies every
  citation of the triage (the paper exists; authors, venue and year; the claim attributed to it).

## Decision rule

Fixed now. "Absorbing" means a verified row whose default path updates the alarm-deciding quantity with
samples the target itself flagged. Reference code counts. Documentation-only rows do not.

- **Go.** At least five absorbing targets, at least two of them products or plugins (groups B and D)
  and at least three runnable on this laptop. The audit is the main line of paper 2.
- **Shrink.** Two or fewer absorbing targets. The audit becomes a short negative result ("shipped
  detectors mostly hold flagged samples out, or do not adapt"), and the defence ("price of poisoning")
  becomes the main line.
- **Between.** Three or four absorbing targets, or five without two products. The audit goes ahead as a
  workshop-sized measurement paired with the defence, and only if one runnable product is among them.
- **Prior art.** If a published paper already tests three or more of the absorbing targets for this
  effect, the audit is repositioned as a registered replication and extension, and the memo is revised
  before any run.

## Outputs

- `thresholds_in_the_wild_tw1_catalogue.md`: the table, per-target notes, the additions log, the
  decision.
- `thresholds_in_the_wild_tw1_catalogue.json`: the same rows, machine-readable.
- `thresholds_in_the_wild_tw1_prior_art.md`: the search, what it found, and the citation check.

## Disclosure

The catalogue states what public code does at a given commit, in neutral terms. It contains no attack
result. Results of attack runs against a named project are kept out of this repository and out of any
preprint until that project's maintainers have been told. Contacting maintainers is the author's
decision and is not part of this step.

## Not in this step

No dataset access, including the 53 reserve Tennessee Eastman runs. No detector runs. No change to the
tt1 paper or its registered files.
