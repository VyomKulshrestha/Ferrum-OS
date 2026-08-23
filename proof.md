# FerrumOS Proof Center

FerrumOS is a bootable x86_64 Rust research OS with a deterministic kernel, a Ring-3 agent daemon, capability-gated syscalls, and a provider-independent predictive safety screen. This page links claims to reproducible evidence; it is not a formal safety certificate. The latest tagged software release is `v0.1.1`; current-main capability and benchmark evidence is labeled separately and does not retroactively describe that tag.

| Surface | Current evidence |
| --- | --- |
| Build | GitHub Actions builds the kernel and userland on Windows with the pinned Rust/LLVM setup |
| Agent actions | 41 canonical operations across 5 permission tiers; unknown tools fail closed |
| OS world model | Published fixture: 81.40% rules + JEPA vs 81.20% rules + mean baseline |
| Ring-3 preview | Three H=1..5 runs, 100 measured previews per horizon, zero heap growth |
| Preview queue | 96/96 responses in every run; 10.40% median batch improvement after cadence optimization |
| Physical model | 187,200 training transitions; unseen-family H=3 0.36% vs 0.75% frozen baseline; digest-bound simulator caution |
| External HIL diagnostic | HAI 48/50 windows at 0.555 false alerts/hour; advisory and not runtime-loaded |
| Neural input | 600 synthetic signals, 400 artifact abstentions, zero candidates in 10,000 no-control windows |
| QEMU command paths | 101/101 focused cases, 81/81 exhaustive entries, and 3/3 cold-restart persistence checks for OS source `f326e55` |
| Cyber-physical software | 163 contract tests, 91 model/decoder gates, and 259 build/QEMU checks passed at source `f326e55` |

Read the [full benchmark protocol and limitations](docs/BENCHMARKS.md), [machine-readable benchmark summary](benchmarks.json), [capability catalog](capabilities.json), [full agent-readable context](llms-full.txt), [citation guide](docs/CITATION.md), [architecture](docs/ARCHITECTURE.md), [security policy](SECURITY.md), and [published research release](https://github.com/VyomKulshrestha/Ferrum-OS/releases/tag/world-model-study-v1.0.0).

## Claim boundaries

- The current release targets a documented QEMU/Bochs device profile, not broad physical-PC compatibility.
- Camera frames are synthetic; physical camera, gaze, and gesture accuracy are not claimed.
- Neural results are synthetic software evidence, not live EEG or medical evidence.
- Physical incident reports and papers supply defensive priors, not Ferrum trajectories or labels. Simulator results and the separate external recorded HIL diagnostic have distinct protocols; neither learned artifact has actuator authority.
- Simulator connectors and ROS 2/MQTT/CAN contracts are software-tested boundaries, not evidence of installed infrastructure or physical delivery.
- Host-managed agent cells define an isolation contract; Ferrum does not claim a native hypervisor or measured microVM containment.
- The published 500-episode safety fixture is authored and balanced; it is not natural-use prevalence.
- JEPA does not materially outperform the per-action mean safety baseline on the published fixture.
- Passing automated checks does not establish formal safety or independent replication.
