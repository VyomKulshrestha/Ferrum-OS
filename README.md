# FerrumOS — Rust agentic operating system with a JEPA safety gate

[![CI](https://github.com/VyomKulshrestha/Ferrum-OS/actions/workflows/ci.yml/badge.svg)](https://github.com/VyomKulshrestha/Ferrum-OS/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Rust: nightly](https://img.shields.io/badge/rust-nightly-orange.svg)](rust-toolchain.toml)
[![Architecture: x86_64](https://img.shields.io/badge/arch-x86__64-blue.svg)](rust-toolchain.toml)
[![Research report DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21829808.svg)](https://doi.org/10.5281/zenodo.21829808)
[![Explore FerrumOS](https://img.shields.io/badge/Explore-FerrumOS-29d9c2)](https://ferrum-os.vercel.app)
[![Sponsor FerrumOS](https://img.shields.io/badge/Sponsor-FerrumOS-EA4AAA?logo=githubsponsors)](https://github.com/sponsors/VyomKulshrestha)

FerrumOS is a Rust AI-native and simulator-backed cyber-physical research OS: a
bootable x86_64 operating system for studying AI agents that act below the
application layer and across bounded physical-work contracts. It combines a
deterministic kernel, real Ring-3 userland, capability-gated syscalls, a
graphical desktop, and a provider-independent JEPA world-model preview before
agent actions reach implemented OS and device services.

FerrumOS keeps the kernel deterministic and independent from probabilistic AI
systems. The AI brain runs natively as a freestanding userspace process
(`heliox-daemon`). Its actions cross explicit capability, world-model, and
operator-confirmation boundaries instead of receiving unrestricted kernel
authority.

**Open-access research:** [Read *When Agents Control the Kernel: A JEPA World
Model Safety Gate with Empirical False-Negative Decomposition*](https://doi.org/10.5281/zenodo.21829808).
The report, software, and dataset are separate artifacts; use the
[citation guide](docs/CITATION.md) for the one you relied on.

**Physical-runtime technical report:** [Read *Learned Caution, Deterministic
Authority: A Calibration-First Runtime Boundary for Action-Conditioned Latent
World Models in Cyber-Physical Systems*](docs/research/paper/learned_caution_deterministic_authority_technical_report_v1.1.pdf).
Version 1.1 adds reviewer-requested uncertainty and explicit marginal PyBullet
attribution. It is an artifact-backed CPS/safety-runtime technical report, not
a robotics-deployment or safety-guarantee claim.

> [!IMPORTANT]
> The latest tagged release is v0.1.1; current-main evidence targets a
> documented QEMU/Bochs profile. Camera input is synthetic. The runtime-loaded
> physical JEPA may add caution only in a digest-bound simulation session;
> a separate external recorded HIL/testbed diagnostic remains advisory and is
> not loaded by FerrumOS. Both learned paths lack permit and adapter authority;
> hardware-in-the-loop and live promotion requires measured real-device
> evidence. Neural results use
> deterministic synthetic EEG fixtures. Broad physical-PC,
> live-EEG, medical, robot-deployment, and formal-safety claims are out of
> scope. ROS 2, MQTT, CAN, Gazebo, Webots, and actuator-disabled interfaces are
> software-tested contracts, not evidence of installed infrastructure or
> physical execution.

> [!NOTE]
> The latest tagged software release is `v0.1.1`; its GitHub release has source
> archives but no prebuilt OS image. Build it with the instructions below.
> `capabilities.json`, `benchmarks.json`, and the research links on `main`
> describe the current source tree and post-release evidence—they do not claim
> that every current capability shipped in `v0.1.1`.

## Start here

| Goal | Canonical source |
| --- | --- |
| Explore the project | [Cinematic FerrumOS website](https://ferrum-os.vercel.app) |
| See what is implemented | [Feature inventory](#features) and [architecture](docs/ARCHITECTURE.md) |
| Check measured results | [Proof center](proof.md), [benchmarks](docs/BENCHMARKS.md), and [raw summary](benchmarks.json) |
| Inspect agent authority | [41-action capability catalog](capabilities.json) and [security policy](SECURITY.md) |
| Read as an AI agent | [Concise context](llms.txt), [full context](llms-full.txt), and versioned [capability](schemas/capabilities.schema.json) / [benchmark](schemas/benchmarks.schema.json) schemas |
| Reproduce the research | [World-model study](docs/research/WORLD_MODEL_PAPER_EVALUATION.md), [physical-runtime paper](docs/research/paper/learned_caution_deterministic_authority_technical_report_v1.1.pdf), [report DOI](https://doi.org/10.5281/zenodo.21829808), and [dataset DOI](https://doi.org/10.5281/zenodo.21829193) |
| Cite an artifact | [Software, report, and dataset citation guide](docs/CITATION.md) |
| Build or contribute | [Build instructions](#build) and [contribution guide](CONTRIBUTING.md) |

## Evidence snapshot

| Layer | Reproduced evidence | Boundary |
| --- | --- | --- |
| OS world-model study | Rules + JEPA: **81.4%** balanced accuracy; rules + per-action mean: **81.2%** on the authored 500-episode fixture | No material JEPA safety advantage established |
| Ring-3 preview | **1.29-1.57 ms** run-mean range across H=1..5; **0 bytes** heap growth in three runs | Excludes provider, action, and approval latency |
| Paired preview queue | **96/96** responses in every run; median batch improved **10.4%** after cadence optimization | Serialized previews, not parallel inference |
| Physical JEPA | **187,200** training transitions; unseen-family H=3 error **0.36%** vs **0.75%** frozen baseline; **0 FN/39 FP** | May add simulator-only caution; HIL/live are not promoted without real-device evidence |
| External HIL diagnostic | HAI: **48/50** attack windows across **111.668 h**, **0.555** false alerts/hour | Separate advisory artifact; not runtime-loaded or a Ferrum hardware trial |
| Neural decoder | **600/600** synthetic signals, **400/400** artifact abstentions, 0 candidates in 10,000 no-control windows | No live EEG or human accuracy claim |
| QEMU command/storage paths | **101/101** focused, **81/81** exhaustive, **3/3** copied-disk cold-restart checks | Exact-image emulator evidence, not broad physical-PC coverage |
| Cyber-physical software | **163/163** contracts, **91/91** model/decoder gates, **259/259** build/QEMU checks | Local software evidence; no installed simulator/transport, robot, hard-real-time, certification, or independent-replication claim |

Every value above is derived and checked by
`scripts/generate_public_evidence.py`; protocols, raw results, commit IDs, and
limitations are in [docs/BENCHMARKS.md](docs/BENCHMARKS.md).

## What makes FerrumOS different

This is a category-level architecture comparison, not a superiority claim.

| Question | Desktop AI copilot | Typical agent framework | FerrumOS |
| --- | --- | --- | --- |
| Where does it run? | Application on an existing OS | Host process, container, or service | Bootable Rust kernel plus freestanding Ring-3 userland |
| How do actions reach the system? | Product/host automation APIs | Tool or plugin APIs | Capability-gated syscalls through a 5-tier policy |
| Where is probabilistic inference? | Product-specific | Framework runtime | Ring 3; never in the deterministic kernel |
| How are risky forecasts composed? | Product-specific | Framework-specific guardrails | Monotonic union of deterministic rules and learned preview; Tier 3/4 confirmation remains independent |
| What is the verified hardware scope? | Host platform support | Host platform support | Documented QEMU/Bochs device profile |

## Research and development use cases

- Agentic operating-system and capability-security research.
- Reproducible JEPA/world-model screening at an OS action boundary.
- Ring-0/Ring-3, syscall, scheduler, filesystem, driver, and desktop OS work in Rust.
- Safe simulation of physical operations, transport-conformance research,
  actuator-disabled delivery, and proposal-only neural intent.
- QEMU-based evaluation of agent actions, confirmation gates, failure modes,
  and provider-independent policy enforcement.

## Features

### Kernel & Core
- Bootloader integration through `bootloader`
- GDT, IDT, CPU exception handlers, PIC timer and hardware IRQs
- Page-table setup, boot-info frame allocation with scrubbed frame recycling, and a 12 MiB kernel heap (increased to support VBE double-buffering)
- Preemptive task scheduler with per-task context switching and priority queues
- Interactive shell with a documented, exhaustively audited command catalog including `dashboard`
- ACPI table discovery, AP-trampoline staging, emulator power-off ports, and 8042 reboot (full AP bring-up and AML `_S5` power-off are not implemented yet)
- Real userspace execution: ELF loader, Ring-3 entry, per-process address spaces, on-demand page-fault lazy allocation, and file-backed memory mapping (`mmap`)

### Graphical Desktop Environment (GUI)
- Custom Compositor and Window Manager
- Interactive desktop taskbar with a Start-menu launcher, paged entries that keep every open window reachable, and a Power menu for lock, sign out, restart, and shut down
- Movable, focusable GUI windows with close, minimize, and maximize buttons and interactive titles
- **Generic app-window framework**: any userland process can call `CreateWindow`/`PresentWindow`/`PollWindowInput` to own a real window backed by its own RGBA8 canvas and a per-window input queue — every window on the desktop, including the AI assistant panel, is a real userland app, not a kernel-hardcoded window type
- The launcher spawns real new ELF processes on demand (`crate::process::spawn_elf`), not just a fixed set of kernel-drawn windows
- App Store: browses built-in apps plus the kernel-verified signed package cache; installs, removes, rolls back, and launches packages with explicit capability/removal confirmation
- PS/2 Mouse integration with 9-bit signed delta parsing and auto-recovery
- CPU-efficient main loop with interrupt-driven `hlt` architecture and off-screen double-buffering
- Hardware cursor rendering with dynamic drop-shadows
- Optional VirtIO-GPU 2D acceleration (`-device virtio-gpu-pci`) — when present, every composited frame is also delivered through the GPU's own resource/transfer/flush command set instead of only a raw framebuffer copy; purely additive, the existing Bochs VBE path remains the fallback when the device isn't attached

### Userland Apps
- **Heliox Assistant** — the AI agent's chat panel: setup wizard, message history, and live thinking/error/done state, all driven over a structured IPC protocol with the agent daemon (see Agent Daemon below)
- **Text Editor**, **Calculator**, **File Manager**, **Settings**, **Browser**, **App Store**, **Notification Center**, **Task Manager** — installed apps built on the generic app-window framework, all launchable from the desktop's Start menu or the App Store; File Manager includes Back/Forward history, Up, Refresh, path/status bars, directory navigation, previews, and document associations that launch Text Editor with the selected path
- Desktop notifications: bounded 32-entry history, capability-gated post/read/manage operations, top-right toast rendering, and a Notification Center with clear controls
- Keyboard task switching: PS/2 and USB HID normalize Alt+Tab into one compositor-only action that raises/restores the previous window without leaking the shortcut into the focused app
- Settings persists validated theme/accent preferences to `/disk/desktop.conf` and applies them to the live desktop; System Monitor renders live task, heap, uptime, and CPU-sampling telemetry
- **`libferrumgui`** — shared `no_std` SDK crate (window/input, IPC, trusted app-launcher, and signed-package syscall wrappers plus an RGBA8 `Canvas`) so new apps don't hand-roll pixel math or the raw syscall ABI

Desktop windows support minimize, maximize/restore, taskbar activation, and Windows-style edge placement: drag a title bar left or right for a half-screen snap, or to the top to maximize while preserving the original floating geometry. Closing an app's main window terminates and reaps its Ring-3 process. The taskbar includes a hardware-RTC-backed UTC clock rather than an uptime placeholder. The privacy lock deliberately resumes with Enter because account passwords are not implemented; it does not pretend to authenticate a user.

### Package Manager (`ferrumpkg`)
- Real `pkg list|verify|install|remove|run|status|rollback` shell command — Ed25519-signed manifests bind package identity, version, requested capabilities, and the ELF's SHA-256 digest to a kernel trust root before install or launch; privileged capabilities require `pkg install <name> --confirm`
- Install/remove are serialized transactions recorded in two checksummed, generation-numbered registry slots. A torn/corrupt newest write falls back to the prior valid generation, the next mutation repairs it, and `pkg rollback` restores the previous valid package set; launch authorization and ELF loading are atomic with respect to these transactions
- Packages are ordinary ELF binaries staged onto the appliance disk at build time (`scripts/make-appliance.ps1`), loaded and executed at runtime via the VFS — the kernel runs genuinely new code it was never compiled with, not just bookkeeping around pre-embedded apps
- Honestly scoped: this is a local package cache, not a network-fetched repository — no package server exists or is pretended to

### Multi-User Accounts
- Real, persistent user accounts (`useradd`, `login`, `whoami`, `accounts`) with a username, uid, capability profile, and home directory, stored at `/disk/accounts.txt`
- Logging in as a different account genuinely swaps the shell's held capabilities — a non-root `user` account can spawn processes and open GUI windows but is denied admin-only actions (reading the audit log, bypassing confirmation gates, quota exemption), not just cosmetically relabeled
- Three profiles: `root` (full access), `user` (a real usable desktop account), `guest` (read-only)
- Current accounts are authorization profiles, not credential authentication: no password hashing, login challenge, or per-file uid/mode enforcement exists yet

### Filesystem
- Volatile in-memory RAM filesystem with VFS mount table
- ATA PIO block storage driver
- Read-write Ext2 filesystem with block/inode allocation
- VFS layer with longest-prefix mount matching and sync
- Binary-safe file reads and writes on both RamFS and Ext2, so model checkpoints and ELF payloads do not pass through unchecked UTF-8 conversions
- Ring-3 file syscalls enforce each process manifest's read/write capabilities; package repository and registry paths additionally require the non-delegatable `cap:pkg:manage` token, so a normal file-capable app cannot replace signed packages or installation state

### Security & Services
- Capability registry and caller-held capability authorization
- Ring-3 process creation requires the explicit `cap:process:spawn` token; GUI access alone cannot launch child apps
- 5-tier permission model with operator confirmation gates (gated Tier 3/4 syscalls require physical key confirmation, using RIP-2 instruction rewinding for restartable blocking calls)
- Persistent Audit Logging: Out-of-interrupt deadlock-free writing to `/disk/heliox/audit.log` (128KB log size cap with automated FIFO truncation)
- Resource Quotas: Syscall rate limiting, continuous CPU execution limits, and memory mapping bounds check (default 8 MiB)
- Modular service manager with typed service manifests
- IPC broker with capability-checked send/receive, live or preloaded service
  ownership, process-owned receive mailboxes, and bounded per-service
  backpressure so one absent or stalled consumer cannot starve Heliox

### Networking
- RTL8139 PCI NIC driver with real TCP/IP via smoltcp
- Socket syscalls: `socket`, `bind`, `listen`, `accept`, `connect`, `send`, `recv`
- `accept` blocks until the TCP state machine reaches `Established`; a listening or half-open socket is never reported as an accepted connection
- HTTP/1.1 client (GET + POST) with 32KB response buffer
- WebSocket client (RFC 6455) for streaming LLM responses

### Hardware Drivers
- VGA framebuffer (Bochs VBE) with 1024×768 graphical console
- VirtIO-GPU 2D driver (PCI modern-capability discovery, virtqueues, `RESOURCE_CREATE_2D`/`ATTACH_BACKING`/`SET_SCANOUT`/`TRANSFER_TO_HOST_2D`/`RESOURCE_FLUSH`), optional and additive
- Intel HDA audio controller with play/record/volume DMA
- XHCI USB 3.0 host controller with device enumeration
- USB HID keyboard and mouse (boot protocol)
- PS/2 keyboard and mouse via 8042 controller (IRQ1 & IRQ12)
- PIT 8254 timer programmed at 1 kHz, UART 16550 serial

### Agent Daemon (`heliox-daemon`)
- Bare-metal ReAct orchestrator (observe → think → act → verify → reflect)
- Multi-Provider Support: Natively connects to local Ollama or cloud models (OpenAI, Gemini, Claude) via host proxy
- Ambient Background Logic: Samples HDA input without stalling other tasks, routes transcribed voice intent through the normal gated ReAct action path, and performs anomaly screen vision checks
- Chat state (thinking / done / error, with the actual response text) streamed to the Heliox Assistant app over a structured IPC channel; user messages flow back the same way
- Stays genuinely idle — no autonomous ticking or inference — until the user has completed setup; a missing config file is never treated as an implicit choice
- Boot-scoped console-token pairing for external models. Paired clients choose
  an `exclusive` lease (built-in planning pauses) or `cooperative` control;
  unpaired clients cannot execute tools or inspect privileged agent state.
- JSON-RPC 2.0 surface over a non-blocking WebSocket listener: `ping`, `pair`,
  `set_control_mode`, `execute_tool`, `agent_step`, `world_model_preview`,
  `physical_status`, `physical_maintenance_demo`, `gesture_event`, `health`,
  `neural_status`, `neural_calibrate`, `neural_intent_preview`,
  `neural_intent_commit`, `neural_disarm`, `get_config`, `system_status`, and
  `agent_stats`.
  Camera, audio, IPC, and controller input are ingested before each planning
  step, so absent clients or slow inference cannot make the listener own the
  autonomous event loop.
- **World model safety gate**: every public tool path — provider-generated ReAct actions, internal memory/planner actions, and JSON-RPC `execute_tool` calls — passes through one predictive gate before execution. It blocks dangerous predictions (for example, deleting the daemon config, filling the disk, or unsafe kernel upgrades) alongside, not instead of, Tier 3/4 confirmation. Release 0.1.1 packages a hash-verified action-conditioned JEPA encoder and 512-wide transition MLP trained across all 40 learnable actions; kernel upgrade remains deterministic policy only. The model sees OS state, canonical tool id, and 16 normalized argument features, never provider identity. Three-step lookahead retains deterministic safety fields and accumulates repeated process growth.
- The deterministic transition table and JEPA forecast run independently, and
  their monotonic union keeps a learned false-safe estimate from replacing a
  rule catch. Three-step lookahead runs on both forecasts; deterministic disk
  growth is derived from content bytes and ext2 block geometry instead of a
  fixed per-write nudge.
- Hierarchical planner with dependency-ordered task decomposition
- TF-IDF vector store with cosine similarity for persistent memory
- `no_std` JSON parser and LLM response decoder supporting OpenAI Chat Completions format
- 41 canonical executable agent operations backed by the 61-syscall kernel ABI
  (37 are advertised directly to the model; local inference, kernel upgrade,
  HUD update, and hit testing remain controlled runtime/bridge actions)
- Config-driven setup via `/disk/heliox/config.json`

### Neural Intent Interface

Ferrum includes a provider-independent, fail-closed neural-intent path for
research and simulation. It is not a claim that a consumer EEG headset or a
medical BCI is included. Raw EEG stays in the host-side `tools/neurod` service;
the OS accepts only a fixed 210-byte `NIV1` intent carrying bounded signal
quality, confidence, dwell, sequence, expiry, session, calibration, focus, and
state-revision evidence protected by HMAC-SHA-256.

- `userland/neural-protocol` is a `no_std` parser and state machine. It rejects
  malformed, replayed, reordered, stale, future, weak, artifacted, or
  revision-racy evidence and disarms on a fail-closed error.
- A paired client may calibrate and preview, but arming requires the local
  console command `heliox neural arm`. Control-mode changes and disconnects
  disarm the session; an old session or intent cannot be reused.
- Committable actions are limited to focus-left, focus-right, select, cancel,
  and three compiled read-only goals: system information, process listing, and
  physical-runtime status. The read-only goals still traverse the OS world
  model and normal capability dispatch.
- A neural physical goal is always proposal-only. It receives a separate H=3
  physical-JEPA shadow forecast and deterministic-supervisor trace, but cannot
  issue a permit, invoke an adapter, or commit an actuator action.
- Multimodal fusion stores at most 16 coarse class/scope events. It never
  retains raw EEG, spectral features, provider text, or signing material.

Run the deterministic service, safety evaluation, and optional localhost-only
fixture dashboard with:

```powershell
python tools/neurod/neurod.py synthetic --frequency 12 --windows 3
python scripts/evaluate_neural_simulator.py
python tools/neurod/dashboard.py
```

The registered synthetic evaluation records 600/600 accepted signal windows,
400/400 artifact-window abstentions, and zero emitted candidates across 10,000
no-control windows. These are reproducible fixture results, not human EEG
accuracy. Real OpenBCI acquisition, independent participants, multi-day
no-control use, hardware-in-the-loop robotics, and qualified safety/human-
factors review remain external N1/N5 evidence.

### Physical Operations Reference Runtime

Ferrum now includes a `no_std` physical-operations runtime and one end-to-end
facility-maintenance reference workflow. It is an architectural bridge from the
agentic computer OS to coordinated AI, robot, and human work—not a claim of
real-hardware or certified industrial deployment.

- Typed sites, assets, human/robot/agent actors, capabilities, qualifications,
  work orders, dependency graphs, deterministic dispatch, and approval-aware
  task lifecycle.
- Versioned observation/command envelopes, bounded logical clocks, checksummed
  evidence sessions, deterministic replay/fork, explicit fault manifests, and
  virtual sensor/actuator/EEG/watchdog/stop device lifecycles.
- Attested adapter identities, endpoints, replay-protected telemetry, canonical
  commands, single-use execution claims, an operational digital twin, fleet
  provisioning/health/signed-update rollback, reliability objectives, and
  consent/retention/tenant privacy enforcement.
- Independent deterministic physical safety for geofences, proximity, human
  occupancy, emergency stops, approval, stale telemetry, and policy/twin
  revision races. Ambiguous delivery becomes `Uncertain` and is never blindly
  retried.
- A separate 16-state/7-action physical EMA-target JEPA (`PJE1`). The current
  v5 checkpoint retains the selected v3 representation and predictor, then
  fits a domain-balanced, baseline-regularized decoder on 187,200 deterministic
  simulator transitions. Its immutable SHA-256 is
  `23a06f37d668ee3f323bb8868dba4eed2baedef642fc32ab6410d4ee1da6e864`.
  It does not reuse the 41-action OS JEPA.
- Forty-eight authoritative incident reports, regulatory filings, standards,
  postmortems, and papers provide coarse defensive state-distribution priors.
  They are not raw incident telemetry or Ferrum trajectories; the simulator
  generates every transition and danger label. The final test contains 2,560
  episodes and 20,480 transitions from eight wholly unseen source families.
- On that once-opened final set, v5 reduces H=3 rollout error from 0.75% for
  the frozen baseline to 0.36%; the geometric H1/H3/H5 error ratio is 0.4842.
  Binary safety records 0 FN/39 FP. Known base, stress, and OOD suites record
  7, 1, and 0 false negatives respectively; OOD records 17 false positives
  while rejecting 682 inconsistent observations. These results improve the
  simulator model without converting it into a physical-safety authority.
- A separately registered post-hoc paper analysis compares rules-only, the
  historical supervised MLP, v3, failed v4, v5, and rules+v5 at the rules-only
  validation FPR. On the v5 final partition, learned-only v5 records 5 FN/14 FP,
  ECE 0.000443, and Brier 0.000827. Rules+v5 records 18 FN/35 FP versus 46 FN/35
  FP for rules-only. The final set was already open before this paper protocol;
  these metrics are characterization, not a new blinded promotion gate.
- Separately, a site-adapted diagnostic evaluated 111.668 hours of external
  recorded HAI 21.03 realistic ICS/HIL-testbed telemetry. It detects 48/50
  attack windows, reaches 87.38% point balanced accuracy, and records 0.555
  false alerts/hour. Its geometric H1/H3/H5 transition error is 2.30% versus
  2.98% persistence and 3.00% per-action mean. This NPZ artifact is not PJE1
  compatible, is not runtime-loaded, and cannot block, approve, permit, invoke
  an adapter, or actuate hardware.
- Model bytes cannot self-promote: a serialized flag never grants authority.
  Ferrum binds the exact checkpoint digest to a simulation session, where its
  forecast can raise `Allow` to approval/block but cannot issue a permit.
  A research-informed four-stage qualification contract now names the exact
  software, actuator-disabled HIL, low-energy robot-trial, and bounded-live
  evidence requirements. Unqualified `Live` delivery is structurally rejected
  before a physical driver is called; no current artifact satisfies the
  external HIL, robot-trial, or independent-assessment stages. The deterministic
  supervisor alone issues permits. Only
  telemetry-confirmed execution can enter the bounded transition-fit
  experience stream; refusals, uncertain deliveries, and simulated predictions
  remain audit-only.
- A fresh validation-only calibration retains a 0.20 predicted-clearance
  caution margin. Its single unseen 12,288-case test records 4 false negatives
  and a 6.63% false-positive rate. This changes only monotonic simulator
  caution; the immutable v5 weights and all deterministic interlocks remain
  unchanged.
  The conditions, sources, results, and remaining external gates are documented
  in [the physical-deployment qualification report](docs/research/PHYSICAL_DEPLOYMENT_QUALIFICATION.md).
- A transport-neutral host bridge implements deterministic scripted tests,
  headless PyBullet DIRECT execution, plus optional Gazebo/ROS 2 and Webots
  connectors. A selection-blinded 512-case benchmark retains a failed v1 run,
  then passes every controller-amended v2 gate with 83.79% task completion,
  16.21% intervention, and 0 shielded collisions against 79 paired unshielded
  collisions. This remains local simulation, not robotics deployment evidence.
  ROS 2, MQTT, and CAN conformance
  rules cover bounded QoS, mTLS/ACL, expiry, retained-message rejection,
  CRC/counter checks, bus-off, replay, and common-state semantics.
- Watchdogs, stop-priority queues, bounded resources/rates, recovery latches,
  actuator-disabled acknowledgements, and permit revalidation fail closed.
- Host-managed agent cells define attested identity, proposal-only capability,
  IPC, quota, restart, quarantine, and termination contracts. Ferrum does not
  claim a native hypervisor or measured microVM containment.

Run the model reproduction and the booted maintenance vertical with:

```powershell
python scripts/verify_physical_world_model.py
python scripts/verify_physical_incident_sources.py
python scripts/verify_physical_incident_dataset.py
python scripts/verify_physical_jepa_robustness.py
python scripts/verify_physical_simulation_caution.py
python scripts/verify_physical_jepa_v5_final.py
python scripts/verify_physical_jepa_v5_runtime.py
python scripts/verify_physical_hai_v2_evidence.py
python scripts/verify_physical_deployment_qualification.py
python scripts/evaluate_physical_jepa_paper.py
python scripts/evaluate_physical_jepa_paper_review.py
python scripts/run_physical_jepa_pybullet_integration.py
python scripts/verify_physical_jepa_blinded_benchmark.py
python scripts/verify_physical_jepa_blinded_benchmark_v2.py
python scripts/verify_physical_jepa_paper.py
python scripts/verify_physical_jepa_paper_freeze.py
python scripts/verify_physical_jepa_paper_freeze.py --freeze docs/research/physical_jepa_paper_freeze_v1_1.json
python scripts/build_physical_jepa_paper.py --source docs/research/paper/learned_caution_deterministic_authority_technical_report_v1.1.md --output docs/research/paper/learned_caution_deterministic_authority_technical_report_v1.1.pdf --running-header "LEARNED CAUTION, DETERMINISTIC AUTHORITY - TECHNICAL REPORT v1.1"
python -m unittest tools.physical_sim_bridge.test_bridge
cargo test --manifest-path userland/physical-runtime/Cargo.toml --target x86_64-pc-windows-msvc
node scripts/verify_bridge.mjs
node scripts/verify_all_audits.mjs
node scripts/verify_ata_pio_persistence.mjs
```

Reproduce the frozen v5 validation-only selection without reading its final
catalog or targeting the deployed checkpoint:

```powershell
python scripts/select_physical_jepa_v5.py --report target/physical_world_model/v5-research-reproduction/selection.json --artifact target/physical_world_model/v5-research-reproduction/selected_candidate.bin
python scripts/verify_physical_jepa_v5_selection.py --report target/physical_world_model/v5-research-reproduction/selection.json --result target/physical_world_model/v5-research-reproduction/verification.json
```

The demo requires `confirm_simulation=true`, routes provider-equivalent and
direct RPC calls through the same service, and compares rules-only, ordinary
shadow, and rules + JEPA on the same rules-safe command. The digest-bound JEPA
blocks the risky simulator rollout without receiving a permit; a bounded safe
control is still delivered. Unqualified live delivery is disabled, and HIL/live
learned use remains unpromoted pending measured real-device evidence. The
repository now implements and tests ROS 2/MQTT/CAN and simulator-facing
software contracts; it does not claim a running third-party deployment,
wearable gateway, field
telemetry, physical emergency controller, robot execution, or natural-use
validation.

### Hybrid World-Model Training

The hybrid pipeline combines controlled coverage, real provider/local-model
responses, and actual FerrumOS transitions. Language models propose canonical
tool calls; FerrumOS supplies the before/after state, outcome, risk, and
arguments. Provider/model identity is provenance only, so the world model is
independent of OpenAI, Claude, Gemini, Ollama, and the bundled 15M model.

```powershell
# Generate a balanced, varied 12k scenario corpus spanning all 41 actions.
node scripts/generate_world_model_hybrid_corpus.mjs --count 12000

# Optionally acquire and validate responses before spending QEMU time.
$env:WM_PROVIDER_KEY = "..."
node scripts/prefetch_world_model_responses.mjs --input target/world_model_hybrid_corpus.jsonl --out target/world_model_prefetched.jsonl --provider openai --url "https://provider.example/v1/chat/completions" --model "model-name" --resume

# Collect in resumable, episode-atomic boots at both RAM profiles, then audit.
node scripts/collect_world_model_hybrid.mjs --corpus target/world_model_prefetched.jsonl --ram 512,2048 --resume
node scripts/reconcile_world_model_dataset.mjs --dataset target/world_model_hybrid_dataset.jsonl
node scripts/merge_world_model_datasets.mjs --input target/world_model_dataset.jsonl --input target/world_model_hybrid_dataset.jsonl --out target/world_model_dataset_release.jsonl
node scripts/audit_world_model_dataset.mjs --dataset target/world_model_dataset_release.jsonl --strict

# Reproduce the selected JEPA representation and transition checkpoint on one
# fixed episode split. The explicit settings are also hash-bound in
# docs/research/world_model_training_config.json.
python scripts/train_world_model_jepa.py --dataset target/world_model_dataset_release_repaired2.jsonl --out target/world_model_encoder_jepa_repaired.bin --encoded-dataset target/world_model_dataset_jepa_repaired.jsonl --metrics-out target/world_model_jepa_repaired_metrics.json --hidden 256 --epochs 300 --batch-size 256 --lr 0.001 --ema 0.99 --reconstruction-weight 0.25 --action-weight 0.1 --patience 12 --seed 42 --split-seed 42
python scripts/train_world_model.py --dataset target/world_model_dataset_jepa_repaired.jsonl --out target/world_model_learned.bin --metrics-out target/world_model_transition_metrics.json --hidden 512 --epochs 2000 --lr 0.05 --seed 17 --split-seed 42 --max-rollout-horizon 5 --min-train-per-tool 32 --require-covered-tools 40
python scripts/select_world_model_candidate.py --baseline target/baseline_metrics.json --candidate target/jepa_metrics.json --representation target/jepa_representation_metrics.json --out target/world_model_selection.json --require-candidate

# Deterministic corpus checks plus real QEMU provider and safety smokes.
node scripts/verify_world_model_hybrid.mjs
node scripts/verify_world_model_learned.mjs
python scripts/verify_world_model_safety_evaluation.py
python scripts/verify_world_model_paper_evaluation.py
```

The accepted corpus contains 13,697 transitions from 3,639 episodes, including
1,300 multi-step episodes, both 512 MiB and 2 GiB observations, all 41 actions,
and at least three variants for every argument-bearing tool. Exactly 373 rows
record actions whose execution was not attempted and 54 executed historical
kernel-upgrade rows are policy-only; the remaining 13,270 rows are eligible for
fitting. The episode-disjoint 9,104/2,197/1,969 split has zero episode overlap.
A corrective collection replaced stale pre-ABI-fix
`ipc_send` episodes with 128 successful live transitions. Against the matched
autoencoder baseline, the accepted JEPA pair reduces normalized held-out error
from 2.30% to 1.68% at one step, 2.96% to 1.71% macro-per-tool, 6.45% to 3.87%
at H=3, and 6.70% to 4.03% at H=5. H
remains 3: H=4 offered no material safety gain beyond the verified disk-H2 and
process-H3 catches, while H=5 increased raw compounding error. The exact pair,
hashes, dataset fingerprint, and metrics are versioned in
`appliance/world-model/manifest.json`; clean builds verify that matched pair,
and partial local overrides fail closed.

Current `main` carries a post-study runtime refinement of the same JEPA/FWM2
model. A validation-only core-state loss sweep selected weight 128; on the
untouched test split it reduces one-step error from 1.68% to 1.36%, macro-tool
error from 1.71% to 1.25%, core-state error from 3.81% to 3.40%, and H=3 error
from 3.87% to 3.78%. H=5 is effectively unchanged at 4.04% and remains inside
the 2% promotion tolerance. The published checkpoint is preserved under
`docs/research/artifacts/world-model-study-v1.0.0/`; the runtime-v2 protocol and
evidence are in `docs/research/WORLD_MODEL_RUNTIME_V2.md`.

A registered 500-episode paired stress evaluation now compares rules only,
JEPA only, and their deployed union on the same 250 safe and 250 dangerous
episodes. Rules + JEPA reduces the false-negative rate from 41.2% to 20.8%
and improves balanced accuracy from 75.2% to 81.4%, while increasing the
false-positive rate from 8.4% to 16.4%. It adds 51 dangerous catches and loses
no deterministic catches. The fixture, all 1,500 arm-by-episode predictions,
Wilson intervals, formal threat model, limitations, and primary-literature
comparison are in [`docs/research/`](docs/research/WORLD_MODEL_RESEARCH.md).
These are offline counterfactual gate results grounded in the untouched QEMU
split, not a claim that 500 destructive actions were executed on a live disk.
The complete 52-FN audit finds three exhaustive clusters: 21 unmodeled
persistent-state deletions, 20 long-horizon process accumulations, and 11
action-specific heap underpredictions. Publication-ready, reproducible
[comparison](docs/research/figures/figure_1_three_arm_comparison.svg) and
[architecture](docs/research/figures/figure_2_jepa_architecture.svg) figures are
generated directly from the registered baseline and appliance manifest.
The expanded paper evidence adds always-allow/block controls, an action-mean
transition baseline, the matched autoencoder safety baseline, an action-
conditioning ablation, H=1..5 safety results, five full JEPA-to-transition pipelines,
validation-only residual calibration, AUROC/AUPRC, bootstrap intervals, and an
untouched 1,969-row QEMU safe-traffic replay. The 81.4% combined result is the
fixed-encoder transition seed-17 condition: it uses representation seed 42 and
re-trains only the transition model with seed 17. The independently trained
full-pipeline seed-17 condition instead reaches 80.6% balanced accuracy, 28.4%
FNR, and 10.4% FPR. Across all five complete pipelines, balanced accuracy averages
79.76% (95% t interval 76.87%--82.65%); the simple rules+mean-delta baseline reaches
81.2%. These limits are part of the research claim, not hidden.
A post-training 240-episode QEMU HUD boundary study spans 12 argument-size regimes,
records zero observed heap delta and zero false resource alarms, and remains outside
the registered split. The release gate's real ring-3 mean preview cost is 1.35 ms at
H=1 and 1.59 ms at H=5 (p95 2 ms at 1 ms PIT resolution), with 30 ms model loading
and zero heap growth across 500 measured previews. A 96-request concurrent preview
burst returns 96/96 correlated, deterministic responses without dispatch or guest
fault. See
[`WORLD_MODEL_PAPER_EVALUATION.md`](docs/research/WORLD_MODEL_PAPER_EVALUATION.md).

The exact 13,697-row corpus can be packaged deterministically with
`scripts/package_world_model_dataset.py`; the exact ten-file archival package includes
`MANIFEST.json`, `SHA256SUMS`, an MIT dataset licence, a data card, standalone schema,
split/credential audit reports, and a dependency-free verifier. The exact release is
published open access at Zenodo under version DOI
[`10.5281/zenodo.21829193`](https://doi.org/10.5281/zenodo.21829193); the all-versions
DOI is [`10.5281/zenodo.21829192`](https://doi.org/10.5281/zenodo.21829192). A fresh
public download matched all ten local release files byte-for-byte and passed the
standalone release verifier 11/11. The machine-readable publication check is in
[`world_model_dataset_publication.json`](docs/research/world_model_dataset_publication.json).
The accompanying technical report is published open access at Zenodo under version
DOI [`10.5281/zenodo.21829808`](https://doi.org/10.5281/zenodo.21829808); all
versions resolve through DOI
[`10.5281/zenodo.21829807`](https://doi.org/10.5281/zenodo.21829807). This is a
separate publication identifier from the dataset DOI above. The public record serves
the DOI-stamped 14-page PDF, and its machine-readable publication state is tracked in
[`world_model_technical_report_publication.json`](docs/research/world_model_technical_report_publication.json).
Independent human/natural-use results are intentionally not claimed: the repo
provides privacy-bounded telemetry plus a blinded two-annotator/adjudication workflow,
but elapsed collection and real independent annotators remain external study steps.

## Architecture

```text
+----------------------------------------------------------+
| Agent Layer (heliox-daemon)                              |
| ReAct orchestrator, multi-provider network client (LLM),  |
| ambient mic/vision recording, multi-agent domain routing  |
+----------------------------------------------------------+
| Cognitive Layer (heliox-daemon)                          |
| Vector store, TF-IDF, planner, reflector, JSON decoder    |
+----------------------------------------------------------+
| Runtime Layer                                            |
| Services, permissions, IPC, config, 37 tool ↔ syscall map |
+----------------------------------------------------------+
| GUI & Compositor Layer                                   |
| Window manager, generic app-window framework, taskbar    |
+----------------------------------------------------------+
| Kernel Layer                                             |
| Boot, memory, interrupts, scheduling, ELF loader, Ring-3  |
+----------------------------------------------------------+
| Storage / VFS Layer                                      |
| ATA PIO block driver, Ext2 filesystem, VFS mount table    |
+----------------------------------------------------------+
| Network / Hardware Layer                                 |
| RTL8139 NIC, Intel HDA (audio), XHCI USB, smoltcp (TCP)   |
+----------------------------------------------------------+
```

## Build

Prerequisites:

- Rust nightly through rustup
- `x86_64-unknown-none` target
- `bootimage`
- QEMU for local boot testing

```powershell
rustup toolchain install nightly
rustup target add x86_64-unknown-none --toolchain nightly
cargo install bootimage

.\build.ps1 check
.\build.ps1 build
```

The boot image is created at:

```text
target\x86_64-unknown-none\debug\bootimage-ferrumos.bin
```

## QEMU Launch

```bash
qemu-system-x86_64 \
  -drive format=raw,file=target/x86_64-unknown-none/debug/bootimage-ferrumos.bin \
  -serial stdio \
  -vga std \
  -netdev user,id=net0,hostfwd=tcp::8785-:8785 \
  -device rtl8139,netdev=net0 \
  -device intel-hda -device hda-duplex \
  -device qemu-xhci -device usb-kbd -device usb-mouse
```

Or use the build script:

```powershell
.\build.ps1 run
```

## Appliance Packaging (Real Local Model)

`scripts/make-appliance.ps1` builds the kernel and packages a real, trained language-model checkpoint onto a disk image the OS mounts at `/disk` — this is what powers Heliox's on-device ("local") brain, as opposed to the tiny synthetic fixture used only by the automated test suite. It builds the boot image, then packages `appliance/models/stories15M-q8.bin` and `appliance/models/tokenizer.bin` (real weights and vocabulary — see `appliance/models/README.md` for provenance and how to regenerate them) into a fresh ext2 disk image at `target/heliox-disk.img`. The script fails loudly if those model assets are missing rather than silently shipping a placeholder.

The 2026-08-21 QEMU gate at `ba17f8e` passed all 7 checks: the packaged checkpoint and both world-model artifacts loaded, a paired JSON-RPC `local_inference` call generated `", there was"`, the live WebSocket response matched, and no userspace/page-fault panic occurred. The exact artifact hashes, observed warning, and scope limits are recorded in [`docs/benchmarks/raw/2026-08-21/qemu-real-model.txt`](docs/benchmarks/raw/2026-08-21/qemu-real-model.txt).

```powershell
.\scripts\make-appliance.ps1
.\build.ps1 run-appliance
```

## Command Verification

Run both shell command audits sequentially against QEMU:

```powershell
node scripts\verify_all_audits.mjs
```

The consolidated runner executes `command_sweep.mjs` and
`audit_all_commands.mjs`, stops on the first failure, and returns a non-zero
exit code for automation. Feature-specific end-to-end verifiers remain
available as `scripts\verify_*.mjs`. The current baseline is 101/101
command-sweep cases and 81/81 exhaustive catalog entries, with every command
returning its expected prompt and no unknown-command or kernel-fault signature.

## Shell Commands

| Command | Description |
| --- | --- |
| `help` | Show available commands |
| `clear` | Clear the screen |
| `echo <text>` | Print text |
| `ps` | List running tasks |
| `mem` | Show heap usage |
| `ls [path]` | List directory contents |
| `cat <file>` | Display file contents |
| `stat <path>` | Show filesystem metadata |
| `mounts` | Show mounted filesystems |
| `mkdir <dir>` | Create directory |
| `touch <file>` | Create empty file |
| `write <file> <text>` | Write text to file |
| `rm <path>` | Remove file or directory |
| `devices` | List registered hardware devices |
| `net` | Show network interfaces and counters |
| `net send <text>` | Deliver a capability-checked loopback packet |
| `caps` | List security capabilities |
| `services` | List registered services |
| `services start/stop <id>` | Start or stop a service |
| `ipc` | Show IPC broker statistics |
| `clipboard get\|set\|clear\|status` | Inspect or update the capability-gated shared clipboard |
| `notify <title> <body>` | Post a desktop notification |
| `notifications [clear]` | List or clear desktop notification history |
| `syscalls` | Show the complete syscall ABI table (0–60) |
| `programs` | List userspace program manifests |
| `users` | List launched userspace processes |
| `run <program>` | Launch a manifest-backed userspace process |
| `pkg list\|verify\|install\|remove\|run\|status\|rollback [name]` | Manage signed packages (use `pkg install <name> --confirm` for privileged capabilities) |
| `useradd <name> [root\|user\|guest]` | Create a real user account |
| `login <name>` | Log in as an account, switching capabilities |
| `accounts` | List all registered user accounts |
| `whoami` | Show the current identity and held capabilities |
| `dashboard` | Full-screen system status TUI |
| `desktop` | Launch Graphical Desktop Environment (GUI) |
| `agent status` | Show agent runtime boundary state |
| `agent start` | Start the sandboxed agent boundary |
| `heliox status` | Show Heliox daemon state |
| `heliox tiers` | List the 5-tier permission model |
| `log` | Show audit log |
| `uptime` | Show system uptime in ticks |
| `uname` | Show system information |
| `shutdown` | Shut down via ACPI |
| `reboot` | Reboot via ACPI |
| `disk` | List ATA drives or read sectors |

## Syscall Table

| # | Name | Description |
|---|------|-------------|
| 0 | Yield | Cooperative yield |
| 1 | IpcSend | Send an IPC message |
| 2 | IpcReceive | Receive an IPC message |
| 3 | ServiceStart | Start a registered service |
| 4 | ServiceStop | Stop a registered service |
| 5 | CapabilityCheck | Check if a capability is held |
| 6 | AuditWrite | Write to the audit log |
| 7 | Socket | Create a TCP socket |
| 8 | Bind | Bind a socket to an address |
| 9 | Listen | Listen on a socket |
| 10 | Accept | Wait for and accept an established connection |
| 11 | Recv | Receive data from a socket |
| 12 | Send | Send data through a socket |
| 13 | Wait | Block until any child exits (compatibility alias for `WaitPid(any)`) |
| 14 | Connect | Connect to a remote host |
| 15 | ReadFile | Read a file from the VFS |
| 16 | WriteFile | Write/create a file in the VFS |
| 17 | ReadDir | List directory contents |
| 18 | Exec | Execute an ELF binary as a new process |
| 19 | ReadFramebufferInfo | Get framebuffer dimensions |
| 20 | ReadTextBuffer | Capture screen text contents |
| 21 | CreateDir | Create a directory |
| 22 | DeleteFile | Delete a file or directory |
| 23 | PlayAudio | Play PCM audio via HDA DMA |
| 24 | RecordAudio | Record audio from HDA input |
| 25 | SetVolume | Set audio output volume |
| 26 | InjectKey | Inject a keyboard event |
| 27 | InjectMouse | Inject a mouse event |
| 28 | PollInput | Poll the input event queue |
| 29 | SystemQuery | Query live system data as JSON |
| 30 | Exit | Terminate the calling process |
| 31 | GetPid | Get process ID of the caller |
| 32 | Sleep | Cooperatively sleep/suspend process |
| 33 | WaitPid | Poll child process exit status |
| 34 | Write | Write bytes to console or serial |
| 35 | Close | Close a socket |
| 36 | ReadCameraFrame | Read a YUYV frame from the camera driver |
| 37 | CameraInfo | Get camera details (width, height, status) |
| 38 | Kexec | Gated warm reboot/relocation to new kernel image |
| 39 | HudUpdate | Update HUD suggestion overlay |
| 40 | HitTest | Perform a visual element hit-test |
| 41 | Mmap | Memory map a file |
| 42 | GetRandom | RDRAND-backed CSPRNG bytes |
| 43 | GetTime | Read RTC time (for TLS cert validity checks) |
| 44 | CreateWindow | Create an app-owned GUI window with a caller-sized canvas |
| 45 | PresentWindow | Submit an RGBA8 pixel buffer to an owned window |
| 46 | PollWindowInput | Poll one pending input event scoped to an owned window |
| 47 | PackageList | Read the kernel-verified signed package catalog |
| 48 | PackageInstall | Install a signed package transactionally |
| 49 | PackageRemove | Remove an installed package transactionally |
| 50 | PackageRollback | Restore the prior valid package registry snapshot |
| 51 | AppLaunch | Launch a trusted compiled-in app with its own manifest |
| 52 | PackageLaunch | Validate, load, and launch an installed signed package |
| 53 | ClipboardRead | Copy the volatile shared clipboard into a caller buffer |
| 54 | ClipboardWrite | Replace the bounded volatile shared clipboard |
| 55 | NotificationPost | Post a bounded notification to the desktop service |
| 56 | NotificationList | Read newest-first notification history |
| 57 | NotificationDismiss | Dismiss one notification or clear all history |
| 58 | ProcessKill | Terminate a non-critical task through the privileged task broker |
| 59 | LaunchContext | Read pid-scoped startup metadata such as an associated document path |
| 60 | DesktopPreferences | Validate and apply desktop theme/accent preferences |

## JSON-RPC Methods (WebSocket, port 8785)

| Method | Description |
|---|---|
| `ping` | Liveness check, returns `"pong"` |
| `pair` | Authorize the connection with the boot-scoped physical-console token and choose `exclusive` or `cooperative` control |
| `set_control_mode` | Switch an already paired connection between exclusive and cooperative planning |
| `execute_tool` | Run a public agent operation by name with args |
| `agent_step` | Run one provider-backed ReAct cycle for a supplied goal and return its actions |
| `world_model_preview` | Predict risk, lookahead depth, reason, and safer suggestion without executing the action |
| `physical_status` | Read physical-runtime, simulator-caution, live-shadow, and model provenance status |
| `physical_maintenance_demo` | Run the explicitly confirmed simulator maintenance reference workflow |
| `neural_status` | Read paired neural session, arm, pending-preview, and bounded fusion status |
| `neural_calibrate` | Bind a stream descriptor and calibration to the paired session |
| `neural_intent_preview` | Verify signed `NIV1` evidence and produce a non-executing preview |
| `neural_intent_commit` | Commit only the previewed safe UI/read-only allowlist after all revisions are rechecked |
| `neural_disarm` | Cancel pending evidence and return the session to observe-only state |
| `gesture_event` | Report a gesture/HUD input event |
| `health` | Whether the daemon is configured yet, and which provider is active |
| `get_config` | Current runtime configuration (excludes the API key) |
| `system_status` | Live tick count, current goal, and hardware info |
| `agent_stats` | Telemetry ring-buffer summary: event count and the last event |

## Canonical Agent Operations (41 total)

The provider prompt advertises 37 operations. `local_inference`,
`trigger_kernel_upgrade`, `hud_update`, and `hit_test` are controlled
runtime/bridge actions but use the same canonical dispatch and world-model gate.

| Tier | Tools |
|------|-------|
| **0 — Observe** | `system_info`, `list_processes`, `query_memory`, `get_config`, `add_subtask`, `camera_capture`, `gesture_status`, `hud_update`, `hit_test` |
| **1 — Safe** | `ipc_send`, `audit_write`, `yield_cpu`, `report_status`, `capability_check`, `read_file`, `read_dir`, `sleep`, `read_screen`, `set_volume`, `poll_input`, `local_inference` |
| **2 — Network** | `net_connect`, `net_send`, `net_recv`, `http_get`, `load_memory`, `set_goal`, `record_audio`, `browse_url` |
| **3 — Modify** | `write_file`, `create_directory`, `save_memory`, `service_start`, `service_stop`, `play_audio`, `keyboard_type`, `mouse_click`, `mouse_move` |
| **4 — Destructive** | `exec_process`, `delete_file`, `trigger_kernel_upgrade` |

## Heliox Daemon Setup

Heliox is always the OS's native agent — it isn't something you choose to enable. The only thing setup decides is **which brain powers it**: an on-device model, or a cloud provider's API. There are two ways to set this up:

> [!NOTE]
> **RAM Filesystem Fallback**: The kernel pre-creates `/disk/heliox/` as a directory within the RAM filesystem (`RamFS`) at boot. If a physical Ext2 formatted ATA disk is not mounted at `/disk`, all configuration writing and loading will transparently fall back to the RAM filesystem, allowing you to use the setup wizard or shell without any partition setup.

### Option A: Interactive Setup (Heliox Assistant)
1. Boot the OS and launch the graphical desktop:
   ```
   FerrumOS:~$ desktop
   ```
   If no configuration exists yet, the **Heliox Assistant** app window launches automatically.
2. Click inside the **Heliox Assistant** window to focus it.
3. Follow the setup wizard by typing your choice at each step and pressing **Enter**:
   * **Step 1 — Local or Cloud?** Type `local` (on-device, works offline) or `cloud` (OpenAI / Claude / Gemini).
   * If **local**: choose `tiny` (the built-in model, auto-sized to your hardware tier) or `ollama` (a local Ollama server — you'll then be asked for its `host:port`, e.g. `10.0.2.2:11434`).
   * If **cloud**: choose a provider (`openai`, `claude`, or `gemini`), then enter your API key.
4. Once completed, the GUI compositor writes `/disk/heliox/config.json` and signals the daemon via IPC (`CONFIG_UPDATED`) to reload configuration and wake from the unconfigured state.

### Option B: Manual Configuration
Create or edit the configuration file at `/disk/heliox/config.json` via the shell. For a cloud provider:
```json
{
  "provider": "gemini",
  "api_host": "generativelanguage.googleapis.com",
  "api_port": 443,
  "api_key": "YOUR_GEMINI_API_KEY",
  "model_name": "default"
}
```
For the on-device model, set `"provider": "local"` (auto-sizes to your hardware tier) and omit the API fields. If you edit the file manually via the shell, reboot or run `services start heliox-daemon` (or signal the daemon via IPC) to reload the config.

## Design Rules

- Keep the kernel deterministic — no AI inference in kernel space.
- Every kernel or hardware effect crosses a real syscall; planning and memory logic remain isolated in Ring 3.
- Capability-checked boundaries between kernel and agent.
- Use Rust safety by default; keep unsafe blocks small and documented.
- Hardware first — if you want an agentic OS, you need drivers.

## Release Scope and Known Limits

FerrumOS v0.1.1 is a bootable x86_64 research OS and QEMU appliance, not a
drop-in Windows replacement. Its release acceptance target is the documented
QEMU/Bochs device profile and the included Ring-3 desktop/apps, services,
Heliox paths, and world-model safety gate. Current boundaries are explicit:

- Camera syscalls are backed by the deterministic synthetic YUYV generator;
  there is no UVC hardware driver yet.
- SMP currently discovers processor topology and stages an AP trampoline, but
  does not send INIT/SIPI or schedule work on application processors.
- Shut down uses QEMU/Bochs/VirtualBox power ports; ACPI AML `_S5` evaluation is
  not implemented. Reboot uses the 8042 reset pulse.
- Accounts switch real capability profiles but do not authenticate passwords,
  and ext2 uid/mode ownership is not enforced.
- Maximized Ring-3 windows retain their fixed canvas size and pad the extra
  area; there is no application resize event or dynamic canvas negotiation.
- Driver coverage targets the enumerated emulator/selected device set above;
  broad PC hardware compatibility, installer/update UX, accessibility, and
  production credential management remain future release work.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the
dev environment setup, code style, and pull request process. Please also
review the [Code of Conduct](CODE_OF_CONDUCT.md). Found a security issue?
See [SECURITY.md](SECURITY.md) — please don't open a public issue for it.

## License

FerrumOS is licensed under the [MIT License](LICENSE).
