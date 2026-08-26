# Citing FerrumOS

FerrumOS publishes software and two report-dataset pairs with different scopes.
Cite the artifact you actually used rather than treating the repository,
report, and dataset as interchangeable.

## Software

Use the repository's [`CITATION.cff`](../CITATION.cff) for FerrumOS software.
The version in that file is the latest tagged software release, `v0.1.1`.
Current `main` contains later source changes and should be identified by its
commit when reproducibility depends on post-release behavior.

## Technical report

**When Agents Control the Kernel: A JEPA World Model Safety Gate with Empirical
False-Negative Decomposition**, Technical Report version 1.2.

- Version DOI: <https://doi.org/10.5281/zenodo.22116399>
- All-versions DOI: <https://doi.org/10.5281/zenodo.21829807>
- Frozen release: <https://github.com/VyomKulshrestha/Ferrum-OS/releases/tag/world-model-study-v1.0.0>

## Dataset

**FerrumOS World-Model Safety Dataset**, version 1.0.0.

- DOI: <https://doi.org/10.5281/zenodo.21829193>
- Scope: 13,697 accounted transitions from 3,639 QEMU episodes

The dataset and report do not establish formal safety, natural-use prevalence,
live-EEG performance, physical-robot safety, or a material JEPA advantage over
the published per-action mean baseline. See the [benchmark boundaries](BENCHMARKS.md)
before reusing a metric.

## Physical-runtime technical report

**Learned Caution, Deterministic Authority: A Calibration-First Runtime Boundary
for Action-Conditioned Latent World Models in Cyber-Physical Systems**, version
1.1.

- DOI: <https://doi.org/10.5281/zenodo.22092356>
- License: CC BY 4.0
- Related dataset: <https://doi.org/10.5281/zenodo.22092320>

## Physical JEPA simulation-evidence dataset

**FerrumOS Physical JEPA Safety-Runtime Simulation Evidence Dataset**, version
1.0.0.

- DOI: <https://doi.org/10.5281/zenodo.22092320>
- License: MIT
- Related report: <https://doi.org/10.5281/zenodo.22092356>

The report and dataset are reciprocally linked Zenodo records. They support an
artifact-backed cyber-physical systems and safety-runtime claim based on
deterministic simulation and locally executed PyBullet software physics. They do
not establish HIL, physical deployment, formal safety, certification,
independent execution, or independent assessment. Public publication evidence,
including redownload hashes and the 12/12 dataset-verifier result, is recorded in
[`physical_jepa_zenodo_publication_v1.json`](research/physical_jepa_zenodo_publication_v1.json).
