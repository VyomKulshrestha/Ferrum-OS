# FerrumOS World-Model Transition Dataset

## Summary

This dataset records before/action/after transitions produced by FerrumOS in
QEMU for training and evaluating the ring-3 Heliox world-model transition
predictor. The version-1 release contains 13,697 accepted rows from 3,639
episodes. After excluding 373 actions that were not executed and 54
policy-only kernel-upgrade rows, 13,270 transitions are eligible for learned
model fitting.

The data supports research on provider-independent OS action prediction and
hybrid rule/learned screening. It does **not** establish that the collected
traffic is representative of natural deployment, that authored danger labels
are independent human judgements, or that a model trained on it is safe.

## Contents and schema

Each JSONL row identifies an episode and step, RAM profile, canonical action,
16 normalized action features, 128-dimensional before and after states,
execution/success fields, reward, and collection provenance. Hybrid rows may
also contain the task prompt, provider label/model label, raw model response,
expected/actual tool, and tags. Provider identity and raw text are provenance;
they are not runtime model inputs.

State features cover normalized process, heap, disk, filesystem, device,
network, UI, and recent-action signals. The exact ordered action and feature
contracts live in `scripts/train_world_model.py` and
`userland/heliox-daemon/src/cognitive/world_model/`.

## Collection

- 9,700 transitions came from real syscall-backed synthetic rotation and were
  later repaired with recovered argument features where possible.
- 3,997 transitions came from provider/replay hybrid episodes routed through
  Heliox's production world-model gate and real tool implementations.
- Recorded RAM profiles are 512 MiB and 2,048 MiB.
- All 41 canonical actions were observed under both memory profiles. Forty are
  represented in learned fitting; `trigger_kernel_upgrade` is policy-only and
  excluded from learned fitting.

"Synthetic" describes how the next action was selected, not the transition:
state snapshots and action effects were observed from an executing QEMU guest.

## Split and leakage controls

Complete episodes are shuffled with seed 42. The registered eligible-row split
is 9,104 train, 2,197 validation, and 1,969 test rows with zero episode overlap.
Consumers must preserve episode grouping; row-level random splitting is not a
valid comparison with the published metrics.

## Intended uses

- OS state-transition prediction and representation-learning research.
- Reproduction of the FerrumOS JEPA, autoencoder, and transition baselines.
- Safety-gate regression tests and analysis of failure modes.
- Development of uncertainty, temporal, and semantic-policy extensions.

## Out-of-scope uses

- Certification of an autonomous agent or operating system as safe.
- Training a model to bypass confirmation, capability, or syscall validation.
- Claims about natural dangerous-action prevalence or deployment precision.
- Re-identification, provider benchmarking, or extraction of provider data.

## Sensitive-content and privacy considerations

The public release builder scans all nested strings for common private-key,
API-token, bearer-token, and cloud-credential patterns and refuses to package
on a match. It reports email-pattern counts and maximum prompt/response sizes.
This automated scan is not a substitute for manual sampling before publication.
Although the registered corpus was generated for research rather than from
personal user activity, hybrid rows contain prompts and model responses and
must be reviewed before public archival.

## Known biases and limitations

- Collection is QEMU- and FerrumOS-specific and overrepresents boundary and
  regression scenarios relative to natural traffic.
- Safety episodes are authored and programmatically labelled.
- The registered fixture is deliberately balanced 250/250 and cannot estimate
  natural prevalence or positive predictive value.
- Some actions remain sparse near resource thresholds; the initial validation
  split contains only six `hud_update` rows for residual calibration.
- Action repetition and numeric state cannot express all semantic asset or
  long-horizon plan risks.

## Reproduction and integrity

Build the release package:

```text
python scripts/package_world_model_dataset.py
python scripts/verify_world_model_dataset_release.py target/world-model-dataset-release
```

The generated directory contains exactly ten files: the deterministic gzip
archive, `README.md`, this card as `DATA_CARD.md`, `LICENSE`, `MANIFEST.json`,
`SHA256SUMS`, `schema.json`, `episode_split_audit.json`,
`credential_scan_report.json`, and the standalone `verify_release.py`. Zenodo DOI
`10.5281/zenodo.21829193` is reserved for this exact archive. The record is not
public and the DOI is not registered until the Zenodo draft is published. After
publication, download the assets again and run the same verifier before describing
the dataset as publicly archived.

## Licence and citation

The dataset is released under the explicit terms in `LICENSE` in the archival
package (sourced from `WORLD_MODEL_DATASET_LICENSE.md` in the repository). Cite the
reserved dataset DOI as `https://doi.org/10.5281/zenodo.21829193`, together with the
release name `ferrumos-world-model-dataset-v1.0.0`, exact archive SHA-256, and
evidence commit. Until publication, label the DOI as reserved rather than registered.
