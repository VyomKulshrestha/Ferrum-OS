# Learned Caution Across Operating-System and Cyber-Physical Domains

## Frozen follow-up study

This study asks a narrower question than the two existing technical reports: after controlling data, compute, parameter count, seeds, and evaluation cases, does a JEPA architecture predict better, and does any learned architecture add practical caution beyond frozen deterministic rules?

The answer is domain-dependent for prediction and negative for operational marginal caution. Physical JEPA is decisively better than the matched MLP and GRU on the frozen physical catalog. FerrumOS instead favors the GRU at H=1 and H=3 and the JEPA at H=5. On new paired temporal catalogs, both selected models respond in the correct counterfactual direction, but neither produces a learned-only intervention at the frozen zero-false-positive threshold. A later externally designed, locally executed Safety-Gymnasium benchmark separates a strong privileged planner-only controller from an active shield that fails its frozen recall and realized-cost gates. The work therefore strengthens the modeling and runtime-attribution evidence without manufacturing a learned-safety claim.

This is a research-only follow-up. It did not replace or promote a deployed artifact. Later registered extensions add externally authored case intake, true multi-client preview contention, and computer-controlled natural-use telemetry while preserving that boundary.

## Registered design

The prospective protocol is [`cross_domain_world_model_improvement_protocol_v1.json`](cross_domain_world_model_improvement_protocol_v1.json). It fixes three methods—direct MLP, action-conditioned JEPA, and GRU dynamics—under the same domain-specific rows and curriculum, three seeds (17, 43, 101), 2,400 AdamW updates, batch size 512, and a 100,000-parameter budget with 5% tolerance. Every model completes the fixed update budget; the lowest validation Gaussian negative log likelihood selects the checkpoint. Final partitions are inaccessible during selection.

The architecture study trains 18 models: two domains by three methods by three seeds. The learned-contribution study separately freezes the lowest-validation-NLL architecture, Platt calibration, and a validation-matched threshold before generating each 512-case final catalog. An absent external design manifest forces the evidence label `researcher-designed blinded deterministic-software benchmark`; no independent-design claim is made.

## Architecture-controlled results

Lower normalized rollout error is better.

| Domain | Method | H=1 | H=3 | H=5 |
|---|---:|---:|---:|---:|
| FerrumOS | Direct MLP | 0.004751 | 0.008431 | 0.007256 |
| FerrumOS | Action-conditioned JEPA | 0.009888 | 0.012356 | **0.005494** |
| FerrumOS | GRU dynamics | **0.004609** | **0.007917** | 0.006514 |
| Physical | Direct MLP | 0.007188 | 0.016836 | 0.026362 |
| Physical | Action-conditioned JEPA | **0.002476** | **0.006680** | **0.010465** |
| Physical | GRU dynamics | 0.010659 | 0.026231 | 0.039542 |

All pairwise episode-bootstrap intervals exclude zero at all three horizons. The physical MLP-minus-JEPA H=3 difference is 0.010156 with 95% interval [0.009829, 0.010483]. In FerrumOS, GRU-minus-JEPA is favorable to the GRU at H=3 by 0.004439 [0.003203, 0.005735], while JEPA-minus-GRU is favorable to JEPA at H=5 by -0.001020 [-0.001165, -0.000865].

This closes the earlier architecture/data confound only for this matched study. It does not establish that one architecture is universally superior.

## Temporal causality, uncertainty, and calibration

The final temporal catalogs contain changing actions, delayed hazards, interaction effects, partial observations, exogenous degradation/recovery, and paired interventions sharing the same initial state and random schedule.

| Domain | Selected architecture | Counterfactual direction | ITE normalized MAE | H=3 multi-action error | H=5 multi-action error |
|---|---:|---:|---:|---:|---:|
| FerrumOS | GRU dynamics | 100.00% | 0.002571 | 0.044558 | 0.046720 |
| Physical | Action-conditioned JEPA | 93.36% | 0.016819 | 0.026772 | 0.046361 |

Both evaluations report ensemble epistemic variance, learned aleatoric variance, standardized OOD distance, reliability bins, Brier score, ECE, and risk-versus-coverage curves. These quantities are diagnostic. In particular, abstaining on the most uncertain cases does not monotonically improve H=5 error in either final catalog, so uncertainty is not presented as a certified risk ranking.

Calibration is weak on the new shifted catalogs: FerrumOS Brier/ECE are 0.249943/0.238143 and Physical Brier/ECE are 0.229970/0.292887. That weakness explains why directional causal sensitivity does not become a useful frozen operating threshold.

## Primary operational result: zero marginal learned caution

Each final catalog contains 256 dangerous and 256 matched safe cases. The registered threshold is 0.99, selected on development data to preserve zero false positives. The result is identical in both domains:

| Arm | TP | FP | TN | FN | Intervention rate |
|---|---:|---:|---:|---:|---:|
| Rules only | 0 | 0 | 256 | 256 | 0% |
| Learned only | 0 | 0 | 256 | 256 | 0% |
| Rules + learned | 0 | 0 | 256 | 256 | 0% |

The learned branch adds zero dangerous-case blocks and zero safe-case interventions. The Wilson 95% upper bound for either marginal rate is 1.478%; the 5,000-pair bootstrap interval is [0, 0]. No deterministic block is erased.

This is a substantive negative result, not a failed verifier. The models encode action consequences, but their scores are not sufficiently separated and calibrated to add caution at the registered operating point. The study therefore does not support deployment promotion.

## Authority-disabled runtime evidence

FerrumOS v3.4 was injected only into disposable appliance-disk copies and executed inside the real ring-3 preview gate under QEMU/WHPX. Across 200 previews per horizon, H=1 through H=5 each had p99 guest time of 3 ms; the loaded runtime reports 193,229 parameters, zero retained heap growth, and both encoder and transition loaded. A separate batch returned 96/96 correlated preview responses across six canonical command classes, produced no execution-dataset record, and left the packaged source disk byte-identical.

A registered contention run then used four distinct WebSocket clients against one QEMU guest. All 128/128 preview responses returned with no cross-client response leakage, Jain throughput fairness 0.999937, and successful disconnect isolation and replacement-client repair. Per-client p95 latency was 16.09-16.46 seconds because the single-threaded daemon serialized saturated inference. Execution was unavailable on those sockets (`-32601`), no execution-dataset record was added, and physical delivery attempts and deliveries were zero. This establishes bounded multi-client preview contention, not parallel inference, production capacity, distributed consensus, or action safety under contention.

Three additional independently booted disposable sessions were operated through the visible FerrumOS assistant using Windows computer control. The 24 frozen natural-language requests produced 24 privacy-bounded telemetry rows across six action classes. Eighteen read-only actions executed successfully, three writes remained awaiting operator confirmation, and three deletes were blocked by the gate. No prompt, argument, path, provider, model, or output text appears in the committed rows; language-model page-ins after deterministic requests, guest faults, synthetic collection markers, direct execution RPCs, physical deliveries, and source-disk changes were all zero. These are short researcher-operated QEMU sessions, not seven-day production telemetry, independent user testing, or labelled precision/recall evidence.

## Externally authored case and physical-data intake

The registered intake freezes the Microsoft Azure VM-noise revision `207bed67dd10090b28ad4f745b2cfd41a11aace4` as an externally authored OS workload taxonomy and NVIDIA Anchor-Lab revision `647edd5787cd764cdc041103ad282dc59214d919` as physical telemetry. The Azure families cover file, process, thread, program-launch, CPU, memory, random-I/O, and Redis contention workloads; they inform the natural-use and contention mix but are not projected into FerrumOS state vectors or treated as FerrumOS labels.

Six frozen Anchor-Lab Parquet files contain 2,925,558 finite timestamped rows, including three publisher-designated held-out SO-101 trials and three H1 elbow-teststand conditions. Command/target and measured-state telemetry are available, but safety/contact labels are not. Their joint, actuator, and temperature semantics do not match Physical JEPA v5's 16-state navigation/maintenance representation or seven-action ontology, so direct v5 replay would be invalid. No semantic projection, model inference, or actuator delivery was performed. The data are suitable for a future separately frozen embodiment-specific model, not for retrofitting an apparent v5 result.

## Recorded testbed sensor replay

Physical JEPA v5 was evaluated over 284,398 one-second transitions from HAI 23.05 test1 and test2, using previously frozen HAI projection statistics. The artifact was not retrained. Six registered conditions cover clean replay, two-second latency, zero-to-three-second jitter, 0.02 sensor noise, 5% hold-last dropout, and a combined condition with proxy-command feature saturation.

| Condition | Masked H=1 MAE | Delta from clean | Attack-label AUROC | Event recall at descriptive threshold |
|---|---:|---:|---:|---:|
| Clean | 0.046627 | 0.000000 | 0.6115 | 38.46% |
| Fixed latency 2 s | 0.050421 | 0.003794 | 0.6040 | 48.08% |
| Jitter 0–3 s | 0.049488 | 0.002861 | 0.6039 | 44.23% |
| Noise 0.02 | 0.055194 | 0.008567 | 0.5937 | 46.15% |
| Dropout 5% | 0.046735 | 0.000108 | 0.6105 | 38.46% |
| Combined | 0.059456 | 0.012829 | 0.6043 | 50.00% |

Host NumPy batch inference measured 2.239 µs median and 3.303 µs p99 per row; these are not physical control-loop timings. All 472 injected observation-fault windows returned below 1.25 times clean p95 error on the first clean row after injection ended. That zero-second value is software observation restoration, not contact or actuator recovery.

Actuator delivery attempts were zero and actuator deliveries were zero. This is researcher-executed replay of externally recorded HIL/testbed data. It is not live Ferrum HIL, a robot trial, independent assessment, contact-dynamics evidence, multi-embodiment evidence, or human-safety evidence.

The HAI replay remains the strongest directly applicable external physical evidence for the current v5 representation. Anchor-Lab adds genuine physical timing and embodiment telemetry but is semantically incompatible with direct v5 scoring. Live actuator-disabled Ferrum HIL with physical clocks, interfaces, sensor latency, actuator dynamics, contact, and an independent emergency-stop path therefore remains absent.

## Multi-embodiment 3D stress: retained negative result

A separately registered PyBullet DIRECT stress test varies three simulated bodies (box, sphere, and capsule), three obstacle geometries (box, sphere, and cylinder), mass, 3D targets, contact, and a one-second return-to-start recovery. It is locally designed software physics, not a blinded benchmark or hardware evidence.

The run is not practical-value evidence: all 288 cases were stopped and task completion was 0% (Wilson 95% upper bound 1.32%). The unshielded arm contacted an obstacle in 205/288 cases; the union arm had no contacts only because it intervened in 288/288. The learned branch contributed 23 interventions not produced by the rule, 13 of which coincided with an unshielded contact, but these cannot be credited as useful learned safety at a 100% intervention rate. Simulated return-to-start recovery succeeded in 181/205 contact cases (88.29%, Wilson 95% interval [83.17%, 92.01%]).

Retaining this result prevents a diversity checkbox from being mistaken for progress. The test adds software geometry and contact coverage while showing that the current state mapping and thresholds fail the completion-versus-intervention objective under this shift.

## Safety-Gymnasium controller and shield benchmark

Safety-Gymnasium v1.0.0 supplies the externally maintained SafetyPointGoal1-v0 task, seeded layouts, observations, goal condition, and hazard-cost signal. The adapter, privileged grid planner, shield policies, local execution, and analysis are researcher-authored. The installed simulator source tree and package versions are digest-locked. Physical actuator attempts and deliveries are zero; execution is not independent, sensor-only, HIL, or physical deployment evidence.

The v12 final opens seeds 4000–4127 exactly once and compares five frozen arms. The strongest prospective controller result is the planner-only arm: 94.53% task completion and 124 hazard-cost events, a 66.93% reduction from the naive controller's 375 events, with zero shield interventions. The selected active union completes 91.41% of tasks and intervenes effectively on 5.04% of proposals, but recalls only 61.58% of dangerous proposals and records 554 hazard-cost events, 47.73% more than the naive baseline. Learned alerts require deterministic rule confirmation and produce zero learned-only interventions.

Every counted v12 intervention changes the applied action; the independent verifier recomputes all five arms, every raw union row, the exact final seeds, protocol and selection hashes, authority counters, and artifact digests. The active shield therefore remains a frozen negative even though the planner-only controller is useful. A later Simplex amendment that switches from naive proposals to planner fallback fails development and never opens its reserved final seed range. Continuing to generate local final catalogs after that failure would be threshold mining rather than stronger evidence.

## What changed, and what did not

The study adds:

- an architecture-controlled MLP/JEPA/GRU comparison;
- distributional prediction, OOD scoring, risk-coverage analysis, and paired temporal interventions;
- two new once-opened final catalogs designed to leave simple current-state rules without an automatic advantage;
- in-guest v3.4 shadow timing, memory, concurrency, and no-execution evidence;
- four-client preview contention with disconnect recovery and no response leakage;
- 24 privacy-bounded natural-use records from three visible, computer-controlled QEMU sessions;
- externally authored OS case taxonomy plus frozen physical telemetry compatibility intake;
- actuator-disabled replay with external recorded sensor streams and registered fault injection;
- a retained negative multi-embodiment 3D contact-and-recovery stress test.
- an externally designed Safety-Gymnasium controller/shield benchmark with a strong planner-only arm, an independently recomputed active-shield negative, and a retained no-final-access Simplex failure.

It does not add independent execution or assessment, live Ferrum HIL, Ferrum physical control-loop timing, physical actuator dynamics, physical contact recovery, validated physical embodiment transfer, production natural-use telemetry, or multi-host field contention. Safety-Gymnasium adds an external task and cost implementation but uses a privileged local planner and researcher-authored adapter, shield, execution, and analysis. The natural-use and multi-client results remain bounded QEMU evidence, and the external Anchor-Lab physical data remain a compatibility-negative intake rather than being forced into the wrong model semantics.

## Reproduction

The principal commands are:

```powershell
python scripts/verify_cross_domain_world_models.py
python scripts/verify_cross_domain_learned_contribution.py
node scripts/verify_world_model_runtime_benchmark.mjs docs/research/world_model_v3_4_shadow_runtime_v1.json
python scripts/verify_world_model_v3_4_shadow.py
python scripts/verify_world_model_multiclient_result.py
python scripts/verify_world_model_natural_use.py
python scripts/verify_world_model_external_case_intake.py
python scripts/verify_physical_jepa_recorded_hil_replay.py
python scripts/verify_physical_jepa_multi_embodiment_3d.py
python scripts/verify_physical_jepa_safety_gymnasium_v12.py
python scripts/verify_cross_domain_world_model_improvement_study.py
```

The umbrella verification record binds every protocol, selection, result, runtime report, replay amendment, and verifier by SHA-256. It also recomputes the protected deployed artifact digests and requires every result to remain promotion-ineligible.
