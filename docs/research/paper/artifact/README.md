# Thresholds That Travel: review artifact

Artifact for the anonymous submission *Thresholds That Travel: Adaptive Alarm Thresholds Let Attacks
Through in ICS Anomaly Detection*. It holds the three pre-registrations, the data-access ledger, the
harnesses that ran the registered finals and every exploratory and post-hoc analysis, the verifiers, the
result file behind every number in the paper, and the figure data and plotting code. The raw datasets are
public and are not redistributed here.

## Layout

| Path | Contents |
|---|---|
| `docs/research/threshold_transfer_tt1_protocol.json` | Registration of study tt1: HAI 20.07 (primary), HyGrid-ICS and voraus-AD; rules, splits, gates, seeds and the SHA-256 of every frozen file |
| `docs/research/threshold_transfer_tt1b_protocol.json` | Registration of study tt1b: BATADAL (SWaT and WADI registered, pending data) |
| `docs/research/threshold_transfer_tt1d_protocol.json`, `..._tt1d_amendment_1.md` | Registration of study tt1d: the Tennessee Eastman attack dataset and ProvICS; both detection counts, first against follower attacks, campaigns on sealed attack-free runs, ceilings. The amendment records the failed first ProvICS attempt and the one change |
| `docs/research/real_telemetry_detection_protocol_v2*.json` | A separate registered study that shared tt1's single data access (amendment 2) |
| `docs/research/real_telemetry_protocol_{v1,rt2}*.json` | Earlier registrations that fixed the D1 world-model monitor |
| `docs/research/threshold_transfer_tt1*_data_access.json` | How each dataset was fetched and hashed before registration |
| `target/real-telemetry/final_access.jsonl` | The access ledger: one line per opening of recorded attack data, with its reason and time |
| `docs/research/threshold_transfer_tt1_result_*.json`, `..._tt1b_result_batadal.json`, `..._tt1d_result_{tep59,provics}.json` | Registered results (the harness computes the gates itself). The tt1d files hold every per-run record |
| `docs/research/threshold_transfer_tt1*_verification*.json` | Verifier reports: 27 of 27 checks (tt1), 8 of 8 (tt1b), 14 of 14 and 15 of 15 (tt1d) |
| `docs/research/threshold_transfer_*dev*.json`, `*posthoc*.json`, `*memory_check.json` | Exploratory analyses on the spent development releases and post-hoc analyses of the registered data, labelled as such in the paper |
| `docs/research/threshold_transfer_tt1c_dev_plan.md`, `..._tt1c_dev_v1.json` | Stronger adaptive baselines and canonical SPOT (exploratory); the plan was fixed before the runs |
| `docs/research/threshold_transfer_tt1e_dev_plan.md`, `..._tt1e_dev_v1.json` | Ceilings, sub-event pulses, an approval gate, the frog at several terminal sizes and a reconstruction score (exploratory); the plan was fixed before the runs |
| `docs/research/threshold_transfer_tt1_findings.md` | Running findings record of the study |
| `docs/research/paper/figure_data/`, `docs/research/paper/figures/` | Plot-ready CSVs and the scripts that draw Figures 1-5 |
| `scripts/` | Rules, loaders, monitor, harnesses, campaigns and verifiers |

## Setup

Python 3.12 and `pip install -r requirements.txt`. Fetch the public datasets with
`python scripts/fetch_real_telemetry.py --only <name>` (`hai`, `hai-20.07`, `hai-21.03`, `hai-23.05`,
`hygrid-ics`, `voraus-ad`, `batadal`). Files land in `target/real-telemetry/raw/` and are checked against
the sizes and hashes recorded in the data-access logs. The two tt1d datasets are fetched by hand: the
Tennessee Eastman archives `attacks.zip` and `single_states.zip` from kas.pr/ics-research/dataset_tep_59 into
`target/real-telemetry/raw/tep59/` (read in place), and the two `physical_state.csv` files and four
ground-truth files of ProvICS (Hugging Face `trucyberlab/multimodal-ICS-provenance`, whose terms forbid
redistribution) into `target/real-telemetry/raw/provics/` with the repository's folder names.

## What can be rerun

- **Development rehearsal of the registered pipeline.** `python scripts/tt1_final.py rehearse hai-20.07`
  runs the frozen harness on normal training data with injected events; it never reads a test file.
  `python scripts/tt1_final.py dry-run <dataset>` reports whether a final would be allowed.
- **Registered finals.** `python scripts/tt1_final.py final <dataset>`,
  `python scripts/tt1b_final.py final batadal` and `python scripts/tt1d_final.py final tep59`; the ProvICS
  final ran as `python scripts/tt1d_provics_amendment1.py` (amendment 1). `python scripts/tt1d_final.py
  rehearse <dataset>` runs the tt1d pipeline on development data only. The ledger here already records each final, so the
  harness refuses a second one; to reproduce a final on a fresh copy, move the ledger aside. The
  harness also refuses when a frozen file's digest differs from the registration, which in this
  anonymized copy is true for two files (see `ANONYMIZATION.md`). The post-hoc reruns in this artifact
  (`scripts/tt1_paper_pack.py trajectories`, `scripts/tt1_posthoc_alarm_time.py`) reran the registered
  pipelines and reproduced every registered event count and calibration threshold exactly.
- **Verifiers.** `python scripts/verify_tt1.py`, `python scripts/verify_tt1b.py` and
  `python scripts/verify_tt1d.py <tep59|provics>` recompute the gates
  from the result files and check the ledger and the frozen-file digests. Their registration-timing
  checks read the git history of the original repository, which is withheld for double-blind review,
  so in this copy those checks report the protocol as uncommitted. The stored verifier reports were
  produced on the full repository.
- **Exploratory and post-hoc analyses.** `scripts/tt1b_dev.py`, `tt1b_attacks_dev.py`,
  `tt1b_frog_dev.py`, `tt1b_physfrog_dev.py`, `tt1b_frog_synthetic.py`, `tt1b_posthoc.py`,
  `tt1c_baselines_dev.py`, `tt1e_defense_dev.py`, `tt1_posthoc_alarm_time.py`; `tt1_memory_check.py` uses the figure data only.
  Each script's docstring gives its commands and output file.
- **Figures.** From `docs/research/paper/figures/`, `python -B fig1_learning_regions.py` (and `fig2` to
  `fig5`); each script checks its figure against the CSV before saving.

## Anonymization

`ANONYMIZATION.md` lists every string replaced in this copy (project name, commit hashes of the
authors' repository). Nothing executable changed. The camera-ready version will link the original
repository with its full history.
