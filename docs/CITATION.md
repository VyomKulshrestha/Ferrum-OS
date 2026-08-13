# Citing FerrumOS

FerrumOS publishes three related artifacts with different scopes. Cite the
artifact you actually used rather than treating the repository, report, and
dataset as interchangeable.

## Software

Use the repository's [`CITATION.cff`](../CITATION.cff) for FerrumOS software.
The version in that file is the latest tagged software release, `v0.1.1`.
Current `main` contains later source changes and should be identified by its
commit when reproducibility depends on post-release behavior.

## Technical report

**When Agents Control the Kernel: A JEPA World Model Safety Gate with Empirical
False-Negative Decomposition**, version 1.0.0.

- DOI: <https://doi.org/10.5281/zenodo.21829808>
- Frozen release: <https://github.com/VyomKulshrestha/Ferrum-OS/releases/tag/world-model-study-v1.0.0>

## Dataset

**FerrumOS World-Model Safety Dataset**, version 1.0.0.

- DOI: <https://doi.org/10.5281/zenodo.21829193>
- Scope: 13,697 accounted transitions from 3,639 QEMU episodes

The dataset and report do not establish formal safety, natural-use prevalence,
live-EEG performance, physical-robot safety, or a material JEPA advantage over
the published per-action mean baseline. See the [benchmark boundaries](BENCHMARKS.md)
before reusing a metric.
