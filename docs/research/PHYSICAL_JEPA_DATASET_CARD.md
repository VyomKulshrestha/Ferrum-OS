# FerrumOS Physical JEPA Safety-Runtime Evidence Dataset

## Summary

This archival dataset accompanies the technical report *Learned Caution,
Deterministic Authority: A Calibration-First Runtime Boundary for
Action-Conditioned Latent World Models in Cyber-Physical Systems*. It freezes
the deterministic simulator catalogs, generated transition tables, sealed
PyBullet benchmark cases, protocols, results, figures, model artifacts, and
reproduction sources used by technical report v1.1.

The main final table contains 20,480 deterministic-simulator transitions from
2,560 eight-step episodes across eight held-out incident-informed source
families. A separate 23,040-transition validation table from 2,880 episodes is
used for probability calibration and threshold selection. The release also contains two prospective,
selection-blinded PyBullet DIRECT catalogs of 512 cases each. The first attempt
is retained even though it failed the registered completion gate.

This is software-simulation evidence. Public incident reports provide defensive
initial-state priors only; they are not trajectories from the cited facilities.
No observation was produced by a physical robot, actuator, hardware-in-the-loop
rig, or independently operated test facility.

## Primary data

- `data/physical_jepa_calibration_validation_transitions.jsonl.gz` contains the
  validation partition used for Platt scaling and matched-FPR threshold
  selection.
- `data/physical_jepa_v5_final_test_transitions.jsonl.gz` contains the frozen
  held-out final partition used by the v5 and paper evaluators.
- `data/physical_jepa_blinded_benchmark_v1_catalog.json` and
  `data/physical_jepa_blinded_benchmark_v2_catalog.json` contain the two sealed
  512-case PyBullet catalogs.
- `catalogs/` retains the source-prior definitions from which the transition
  tables are deterministically regenerated.
- `protocols/`, `results/`, `models/`, `figures/`, `scripts/`, and
  `tools/physical_sim_bridge/` preserve the registered lineage and reproduction
  implementation.

Each transition JSONL row records the episode, step, partition, source and
source family, hazard tags, 16-dimensional state, action identifier and name,
three action features, 16-dimensional next state, deterministic danger label,
and explicit simulator provenance.

## Experimental lineage

The release preserves four learned baselines/artifacts:

- the historical ordinary supervised MLP;
- the v3 JEPA baseline;
- the failed v4 candidate;
- the selected v5 decoder-only candidate.

v5 selection examined only the registered base, incident-v2, and stress
validation partitions. The v5 final catalog remained unopened during selection.
The selected model was evaluated once on the final catalog, and no retraining
followed that open. The later calibration, matched-FPR, uncertainty, and
shared-catalog MLP analyses are explicitly registered as post-hoc.

## PyBullet benchmark

Both sealed catalogs contain 80 collision-course, 128 boundary-safe, 128
near-safe, and 176 clear-safe cases. The v1 benchmark retained zero observed
shielded collisions and 16.21% intervention but failed completion. Before a new
catalog was sealed, v2 changed only the fixed command budget from one to two
cycles. v2 recorded 429/512 completed tasks, 83/512 interventions, 79
unshielded collisions, and zero observed shielded collisions.

All observed collision avoidance in v2 is attributable to the deterministic
path rule. The learned v5 component adds three conservative stops on
non-colliding boundary cases and avoids no collision not already prevented by
the rule. Zero observed collisions does not establish a zero underlying
collision probability.

## Intended uses

- Reproduce the frozen v5 selection and final evaluation.
- Compare multi-horizon dynamics and thresholded risk decisions on identical
  deterministic catalogs.
- Audit calibration, uncertainty intervals, and threshold sensitivity.
- Re-run the two selection-blinded software-physics integrations.
- Study monotone learned-caution boundaries in safety-runtime architectures.

## Out-of-scope uses

- Claiming physical-robot, actuator, HIL, field, or real-time validation.
- Treating deterministic danger labels as independent human annotations.
- Treating public incident reports as Ferrum trajectories or reconstructions.
- Claiming formal safety, certification, or a zero collision probability.
- Claiming an architecture-controlled JEPA advantage over the MLP; their
  historical training distributions differ.

## Biases and limitations

The transition labels and dynamics are deterministic and share one simulator
family. Source priors overrepresent boundary, incident, and recovery scenarios
and do not estimate natural operational prevalence. The PyBullet environment is
a locally executed two-body planar box scenario. Sensor latency, actuator
dynamics, contact dynamics, human behavior, hardware faults, and embodiment
diversity are absent. The engineering rules are not formally verified invariant
sets.

## Integrity and verification

The Zenodo release contains a deterministic ZIP payload plus `README.md`, this
card as `DATA_CARD.md`, `LICENSE`, `MANIFEST.json`, `SHA256SUMS`,
`credential_scan_report.json`, and a dependency-free `verify_release.py`.

Run:

```text
python verify_release.py
```

The verifier enforces the exact eight-file release contract, verifies every
release and payload SHA-256 digest, checks the two generated transition tables
and their registered counts, validates the sealed benchmark family counts,
confirms all four model digests, and checks the explicit simulation-only claim
boundary.

## Licence and citation

The archival dataset is released under the MIT License included in `LICENSE`.
Creator: Vyom Kulshrestha, Independent Researcher, India, ORCID
`0009-0009-1434-7148`.

Use the version DOI recorded in the final `MANIFEST.json` when citing these
exact bytes. The related technical-report DOI identifies the interpretation and
claim boundaries; cite both records when using the data to reproduce the paper.
