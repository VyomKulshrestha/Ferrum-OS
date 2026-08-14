# FerrumOS Proof Center

FerrumOS is a bootable x86_64 Rust research OS with a deterministic kernel, a Ring-3 agent daemon, capability-gated syscalls, and a provider-independent predictive safety screen. This page links claims to reproducible evidence; it is not a formal safety certificate. The latest tagged software release is `v0.1.1`; current-main capability and benchmark evidence is labeled separately and does not retroactively describe that tag.

| Surface | Current evidence |
| --- | --- |
| Build | GitHub Actions builds the kernel and userland on Windows with the pinned Rust/LLVM setup |
| Agent actions | 41 canonical operations across 5 permission tiers; unknown tools fail closed |
| OS world model | Published fixture: 81.40% rules + JEPA vs 81.20% rules + mean baseline |
| Ring-3 preview | Three H=1..5 runs, 100 measured previews per horizon, zero heap growth |
| Preview queue | 96/96 responses in every run; 10.40% median batch improvement after cadence optimization |
| Physical model | 99.44% simulator balanced accuracy; permanently shadow-only |
| Neural input | 600 synthetic signals, 400 artifact abstentions, zero candidates in 10,000 no-control windows |
| QEMU command paths | 101/101 focused cases and 81/81 exhaustive entries for OS source `c92056d` |
| Cyber-physical software | 152 contract tests and 32 model/decoder gates passed at source `167b047` |

Read the [full benchmark protocol and limitations](docs/BENCHMARKS.md), [machine-readable benchmark summary](benchmarks.json), [capability catalog](capabilities.json), [full agent-readable context](llms-full.txt), [citation guide](docs/CITATION.md), [architecture](docs/ARCHITECTURE.md), [security policy](SECURITY.md), and [published research release](https://github.com/VyomKulshrestha/Ferrum-OS/releases/tag/world-model-study-v1.0.0).

## Claim boundaries

- The current release targets a documented QEMU/Bochs device profile, not broad physical-PC compatibility.
- Camera frames are synthetic; physical camera, gaze, and gesture accuracy are not claimed.
- Neural results are synthetic software evidence, not live EEG or medical evidence.
- Physical-world results use a deterministic simulator; the learned artifact has no actuator authority.
- Simulator connectors and ROS 2/MQTT/CAN contracts are software-tested boundaries, not evidence of installed infrastructure or physical delivery.
- Host-managed agent cells define an isolation contract; Ferrum does not claim a native hypervisor or measured microVM containment.
- The published 500-episode safety fixture is authored and balanced; it is not natural-use prevalence.
- JEPA does not materially outperform the per-action mean safety baseline on the published fixture.
- Passing automated checks does not establish formal safety or independent replication.
