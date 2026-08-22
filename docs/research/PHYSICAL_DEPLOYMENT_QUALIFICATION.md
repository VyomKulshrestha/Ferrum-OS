# FerrumOS physical-deployment qualification

## Claim boundary

Ferrum can automate software qualification and prepare an actuator-disabled
HIL path. It cannot convert simulator metrics into market-ready physical safety.
The exact robot application still needs measured hardware timing and stopping
behavior, contact-force assessment where applicable, an independent electrical
emergency stop, representative robot trials, and independent assessment.

The current runtime therefore permits JEPA caution only in a digest-bound
simulation session. A `Live` session is rejected before a physical driver is
called because no authenticated external qualification authority exists yet.
The deterministic supervisor remains the sole permit authority in every mode.

## Research basis

The protocol applies a common thread across primary standards and published
validation methods:

- [ISO 12100:2010](https://www.iso.org/standard/51528.html) requires a lifecycle
  process for hazard identification, risk estimation/evaluation, risk reduction,
  documentation, and verification.
- [ISO 10218-1:2025](https://www.iso.org/standard/73933.html) addresses the
  industrial robot itself, while
  [ISO 10218-2:2025](https://www.iso.org/standard/73934.html) addresses the
  integrated application across commissioning, operation, maintenance, and
  decommissioning. Applicability depends on the selected robot/application.
- [ISO/TS 15066:2016](https://www.iso.org/standard/62996.html) describes
  collaborative techniques including monitored stop, speed and separation
  monitoring, and power/force limiting.
  [ISO/PAS 5672:2023](https://www.iso.org/standard/82488.html) provides methods
  for measuring human-robot contact forces and pressures.
- [ISO 13849-1:2023](https://www.iso.org/standard/73481.html) supplies a design
  and integration methodology for safety-related control-system parts. It does
  not choose Ferrum's application-specific safety functions or required
  performance level.
- [IEC 61508](https://webstore.iec.ch/publication/5515) motivates lifecycle
  functional-safety evidence and assessor independence. This report does not
  claim Ferrum conforms to IEC 61508.
- [UL 4600 Edition 3](https://www.ul.com/news/ul-4600-edition-3-updates-incorporate-autonomous-trucking)
  uses a claim-based safety-case approach and explains why analysis, simulation,
  closed-course testing, operational evidence, and update evidence are
  complementary rather than interchangeable.
- [NIST response-robot test methods](https://www.nist.gov/el/intelligent-systems-division-73500/standard-test-methods-response-robots/ground-robot-tests)
  motivate repeatable apparatus, procedure, metric, and exact-configuration
  reporting.
- ROS 2 documents explicit
  [deadline, lifespan, and liveliness QoS](https://docs.ros.org/en/humble/Concepts/Intermediate/About-Quality-of-Service-Settings.html)
  and the need to measure real-time deadline latency/jitter while avoiding
  nondeterministic control-path operations in its
  [real-time guidance](https://docs.ros.org/en/eloquent/Tutorials/Real-Time-Programming.html).
- [VerifAI (CAV 2019)](https://people.eecs.berkeley.edu/~sseshia/pubs/b2hd-verifai-cav19.html)
  supports simulation-guided falsification, systematic fuzzing, counterexample
  analysis, and dataset augmentation.
  [Scenic (PLDI 2019)](https://www-cad.eecs.berkeley.edu/~sseshia/pubs/b2hd-fremont-pldi19.html)
  supports explicit scenario distributions for rare-event training and testing.
- [NASA software assurance and safety](https://sma.nasa.gov/sma-disciplines/software-assurance-and-software-safety)
  distinguishes development evidence from technically, managerially, and
  financially independent verification and validation.

These sources inform the checklist; they do not establish compliance or decide
which standard governs a future product.

## Machine-enforced stages

| Stage | Additional required evidence | Current status |
| --- | --- | --- |
| Software simulation | Hazard register; independent deterministic authority; no model permits; immutable identities; scenario falsification; fault injection/replay; deadline/freshness/liveliness; actuator-disabled path | Software evidence available |
| Actuator-disabled HIL | Exact-application risk assessment; measured real hardware timing; independent physical emergency stop | External evidence required |
| Supervised low-energy trial | Measured stopping time/distance; force/pressure assessment or justified exclusion; safety-control performance validation; representative robot trials | External evidence required |
| Bounded live operation | Independent safety assessment; change-impact and post-update regression plan | External evidence required |

`userland/physical-runtime/src/qualification.rs` evaluates these requirements as
cumulative sets. It reports missing evidence; it cannot certify a document,
authenticate an assessor, or activate a driver.

## New model evidence

### Incident-derived defensive challenge

Ferrum's physical JEPA was already trained and evaluated with defensive priors
abstracted from 16 public sources, including government incident reports,
company postmortems, peer-reviewed incident analyses, and the MITRE ATT&CK for
ICS taxonomy. The sources cover reported events such as Stuxnet, TRITON,
CrashOverride, the Aurora generator experiment, the German steel-mill event,
and compromises affecting water controllers. Operational intrusion procedures
are deliberately excluded.

These are real published incident sources, but they are not raw traces from an
attacked Ferrum system or robot. The deterministic simulator generates every
state transition and danger label from the registered defensive abstractions.
Source families are disjoint across training, validation, and test partitions.
On the deployed v3 checkpoint's 7,680-transition incident test, rules + JEPA
records 1 false negative and 56 false positives. The source catalog, generated
dataset, checkpoint-selection history, and remaining miss are independently
reproducible with:

```powershell
python scripts/verify_physical_incident_sources.py
python scripts/verify_physical_incident_dataset.py
python scripts/verify_physical_world_model.py
```

This supports robustness to simulator states derived from reported incident
effects. It does not demonstrate resistance to an unknown live attacker,
malware execution, compromised firmware, or an adversarial physical device.

### Systematic boundary challenge

The `systematic-boundary-sweep-v1` protocol was frozen before opening its
12,288-row challenge. It balances 1,024 cases across 12 families including
speed/separation, protective stop, geofence, battery, link/liveliness,
emergency stop, authorization, human motion, compound hazards, payload/health,
nominal control, and recovery.

| Pipeline | FN | FP | FNR | FPR | Balanced accuracy |
| --- | ---: | ---: | ---: | ---: | ---: |
| Rules only | 289 | 342 | 4.41% | 5.96% | 94.81% |
| Rules + JEPA | 12 | 403 | 0.18% | 7.02% | 96.40% |

The JEPA's normalized one-step error is 0.441% (p95 0.848%) on this sweep.
All frozen gates passed, so the protocol did not justify changing the immutable
weights.

The misses motivated a separate validation-only runtime calibration. Candidate
predicted-clearance thresholds were selected on 12,288 rows with seed 20260902;
the chosen 0.20 threshold was then opened once on 12,288 different rows with
seed 20260903.

| Calibration test | Value |
| --- | ---: |
| False negatives | 4 |
| False positives | 411 |
| False-negative rate | 0.061% |
| False-positive rate | 7.148% |
| Balanced accuracy | 96.395% |
| Normalized one-step error | 0.445% |

This is an improvement to the monotonic simulator caution margin, not evidence
that the model or system is safe on hardware. Four simulator misses remain and
must not be hidden. Future physical observations may support a new registered
training protocol, but only after configuration-bound data collection and
episode/source-disjoint validation are defined.

## Reproduce

```powershell
python scripts/evaluate_physical_deployment_qualification.py
python scripts/calibrate_physical_jepa_runtime.py
python scripts/verify_physical_deployment_qualification.py
cargo test --manifest-path userland/physical-runtime/Cargo.toml --target x86_64-pc-windows-msvc
```

The canonical machine-readable protocol and results are:

- `physical_deployment_qualification_protocol_v1.json`
- `physical_deployment_qualification_evaluation_v1.json`
- `physical_jepa_runtime_calibration_v1_protocol.json`
- `physical_jepa_runtime_calibration_v1.json`
