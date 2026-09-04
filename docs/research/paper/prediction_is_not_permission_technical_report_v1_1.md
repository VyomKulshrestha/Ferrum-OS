# Prediction Is Not Permission: Cross-Domain World Models Under Deterministic Runtime Authority

## Architecture-Controlled Evidence Across an Agentic Operating System and a Cyber-Physical Runtime

Technical Report v1.1 — 4 September 2026

Vyom Kulshrestha
Independent Researcher, India
ORCID: 0009-0009-1434-7148
vyomkulshrestha2004@gmail.com
github.com/VyomKulshrestha/Ferrum-OS

Research artifact accompanying the FerrumOS world-model evidence lineage.

### Abstract

World models are increasingly proposed as predictive components for autonomous software and robots, but a lower rollout error does not establish that a learned score should authorize a state-changing action. This report studies that distinction in two domains with different dynamics and authority surfaces: FerrumOS, where an agent proposes canonical operating-system actions, and Physical JEPA, where a predictive model observes navigation and maintenance state. A prospective protocol matches data, curriculum, parameter budget, optimization budget, seeds, and final cases across direct multilayer perceptron, action-conditioned joint-embedding predictive architecture, and gated recurrent unit dynamics models. Eighteen models are trained without final-partition access during selection.

Architecture rankings are domain-dependent. On the frozen physical catalog, the JEPA has the lowest normalized rollout error at horizons 1, 3, and 5; the MLP-minus-JEPA H=3 difference is 0.010156 with a paired episode-bootstrap 95% interval [0.009829, 0.010483]. FerrumOS instead favors the GRU at H=1 and H=3 and the JEPA at H=5. Both selected models show counterfactual directional sensitivity on paired temporal cases, yet calibration weakens under the registered distribution shift. At the frozen 0.99 threshold, rules-only, learned-only, and their union all intervene in 0 of 512 cases in each domain and miss all 256 simulator-labelled dangerous cases. The learned branch therefore adds zero marginal hazard blocks and zero safe-case interventions. A separately registered 3D PyBullet stress test produces an operationally unusable extreme: 288 interventions in 288 cases and 0% task completion. A subsequent externally designed, locally executed Safety-Gymnasium benchmark separates controller value, warning quality, and effective action changes on 128 untouched seeds. The privileged planner completes 94.53% of tasks and records 87.08% fewer hazard-cost events than the naive controller. The active union completes 96.09%, changes 1.86% of commands, has 95.62% warning recall on 20-step oracle-labelled dangerous nominal-controller trajectories and 55.00% effective-action recall, and records 84.50% fewer hazard-cost events than the naive controller. Relative to the planner, it completes 2 more tasks but records 14 additional hazard-cost steps; paired episode-bootstrap intervals for both planner-relative differences include zero.

The runtime contribution is an authority factorization and evidence ladder rather than a claim of universal model superiority. FerrumOS previews execute in an authority-disabled QEMU path with no action dispatch, while Physical JEPA is evaluated through recorded testbed replay and actuator-disabled software physics. Deterministic policy, capability checks, operator confirmation, and physical actuator denial remain independent of learned prediction. All negative and failed frozen attempts are retained, the planner-only contrast and active-union tradeoff are reported together, protected deployed artifacts remain byte-identical, and promotion eligibility is false. The evidence supports a reproducible safety-runtime methodology and domain-specific predictive modeling; it does not establish production agent safety, live robot safety, formal correctness, or independent replication, physical deployment safety, or a learned collision-avoidance advantage over the privileged planner: the union passes its registered naive-baseline objective, but its completion gain over the planner accompanies higher realized hazard cost.

### 1. Introduction

An autonomous system can predict what may happen without possessing the authority to make it happen. That distinction is easy to state and easy to blur. A world model may forecast that a file operation will exhaust disk space, that a service restart will destabilize a workload, or that a commanded motion will approach an obstacle. The forecast may be useful even when imperfect. It does not follow that a low predicted risk should grant a capability, bypass confirmation, or energize an actuator.

This report asks two connected questions. First, when training conditions are controlled, is one common model family consistently better at multi-horizon prediction across an agentic operating system and a cyber-physical state space? Second, does the selected learned model add useful caution beyond a frozen deterministic authority boundary at a registered false-positive operating point? The first question concerns predictive modeling. The second concerns operational decision value. Treating them as different estimands is the paper's central methodological choice.

The study extends two artifact-backed FerrumOS lineages: unprivileged action-conditioned OS forecasts before capability-gated effects, and a compact physical model evaluated with actuator authority disabled. It adds matched architectures, paired interventions, calibration, authority-disabled runtime tests, external-data intake, retained negative stress tests, and a prospective Safety-Gymnasium evaluation [17].

#### 1.1 Contributions

This report contributes six things. First, it provides a matched two-domain architecture study covering MLP, action-conditioned JEPA, and GRU dynamics under equal data, optimization, parameter, seed, and final-case conditions. Second, it separates distributional prediction, counterfactual sensitivity, calibration, and thresholded intervention into independently reported outcomes. Third, it specifies an authority factorization in which learned prediction can add caution but cannot create execution authority or erase a deterministic block. Fourth, it builds a cross-domain evidence ladder spanning sealed offline catalogs, QEMU shadow execution, visible researcher-operated sessions, externally recorded testbed replay, and actuator-disabled software physics. Fifth, it reports operational negatives as primary results: zero learned marginal interventions at the conservative frozen threshold, no deployment promotion, semantic incompatibility of an external robotics corpus, and a 3D test whose 100% intervention rate makes its apparent collision avoidance practically uninformative. Sixth, it prospectively freezes a joint completion, intervention, recall, false-positive, and realized-cost objective, retains every failed or non-beneficial protocol stage, and reports a once-opened Safety-Gymnasium final where the selected union passes the registered joint objective while remaining worse than the privileged planner on realized hazard cost.

#### 1.2 Claim boundary

The temporal catalogs and 3D stress are locally designed software tests. Safety-Gymnasium supplies the task and costs, but the adapter, privileged planner, shield, execution, and analysis are local. Physical evidence is replay, not live HIL; FerrumOS evidence is disposable QEMU, not production use. No result establishes formal, independent, human-contact, broad-transfer, or deployment safety, and no protected artifact is replaced.

<!-- PAGE BREAK -->

### 2. Related work and research position

#### 2.1 Predictive representations and action-conditioned world models

Joint-embedding predictive architectures learn in representation space instead of reconstructing every observation detail. V-JEPA demonstrates feature prediction for video without pixel-level reconstruction [1], while V-JEPA 2 extends predictive representation learning toward action-conditioned planning and reports deployment on Franka robot arms [2]. DINO-WM shows that visual features can support world-model prediction across control tasks without task-specific visual encoders [3]. These results motivate predictive abstractions, but they do not imply that the same architecture will dominate in compact structured state spaces or that a prediction should carry authority.

The present study differs in scope. It does not propose a new large-scale pretraining objective. It compares small matched dynamics models at a runtime decision boundary, holds compute and data constant, and measures whether offline ranking survives calibration and an operational threshold. Its novelty is primarily systems and methodology: authority remains separately enforceable, and every evidence class is labelled by what it can and cannot support.

#### 2.2 Agentic computer environments

OSWorld evaluates multimodal agents across real computer tasks and documents a large gap between human and automated performance [4]. Such benchmarks measure task execution in interactive environments. FerrumOS instead studies the narrower mediation point between a proposed canonical action and an operating-system effect. The study does not claim a general desktop-agent benchmark. It asks whether a predictive runtime can be exercised without granting state-changing authority and whether policy, capability, and confirmation remain independently testable.

#### 2.3 Runtime assurance and safety filters

Simplex-style systems separate a high-performance controller from a trusted safety controller and use a decision module to switch when safety is threatened [5]. Neural Simplex and Black-Box Simplex extend this idea to learned components while retaining a recoverable or verified fallback boundary [6, 7]. NASA runtime-assurance work similarly treats monitoring and intervention as an architectural assurance layer rather than proof that an advanced controller is correct [8, 9]. In robot learning, SHIELD combines learned dynamics with a control-barrier-function layer and hardware evaluation [10]. Calibrated Predictive Safety makes calibrated risk and deterministic shielding central to a simulation study [11].

FerrumOS follows the same broad separation principle but targets heterogeneous authority. In the OS domain, a block, capability denial, confirmation request, and syscall validation are distinct decisions. In the physical domain, model inference, simulation command, and actuator delivery are distinct events. This paper therefore describes a monotone caution branch: learned output may increase intervention, but it cannot convert a forbidden action into an allowed one and cannot create actuator authority.

#### 2.4 Calibration and proper scoring

Thresholded safety decisions depend on probability quality, not only rank order or mean rollout error. Reliability diagrams, expected calibration error, and the Brier score expose different properties of predictive confidence [12, 13]. ECE is bin-dependent and should not be treated as a complete guarantee. This study reports Brier, ECE, reliability bins, epistemic and aleatoric diagnostics, OOD distance, and risk-coverage curves. It also tests the actual frozen threshold. The distinction matters because both selected models respond directionally to interventions while adding no operational caution at that threshold.

### 3. Authority factorization

The system separates four questions: what is predicted, what policy permits, what authority is available, and what effect is independently observed. Let `s_t` be the captured state, `a_t` a normalized proposed action, `M` a learned transition model, `R` an exact deterministic predicate, `C` a capability and confirmation decision, and `E` an effect executor. A simplified gate is:

```text
predicted_risk = M(s_t, a_t)
deterministic_block = R(s_t, a_t)
learned_block = predicted_risk >= frozen_threshold
gate_block = deterministic_block OR learned_block
execute = (NOT gate_block) AND C(a_t)
postcondition = independently_observe(E(a_t))
```

The Boolean union is monotone with respect to caution: a learned false-safe score cannot erase `deterministic_block`. Equally important, `NOT gate_block` is not an authorization token. The capability and confirmation branch remains necessary, and the effect must be observed separately. In the physical experiments, the executor is absent or actuator delivery is forced to zero.

![Figure 1. Authority factorization used in both domains. Prediction can add caution but cannot grant capabilities, bypass confirmation, or create physical actuator authority.](docs/research/figures/cross_domain_world_model/authority_factorization.png)

#### 3.1 Why rollout horizon is not authority horizon

A multi-step model estimates a counterfactual trajectory under a specified action sequence. It does not mean that every predicted repetition was requested. This distinction previously mattered in FerrumOS, where repeated hypothetical application of a requested operation could create an artificial deterministic hazard. The repaired runtime applies exact deterministic effects only to covered requested actions while retaining multi-step learned output for telemetry and caution. The paper calls this request-bounded authority.

#### 3.2 Failure semantics

The architecture is fail-closed only within stated boundaries. A missing or non-finite model cannot erase deterministic protection. A model that overestimates risk can deny useful work, so false positives and intervention rate are safety-relevant availability costs. A model that underestimates an unrepresented hazard may allow the proposal to proceed to capability and confirmation checks. Hazards absent from the state representation and deterministic predicates remain outside coverage. No empirical table converts these limitations into a formal guarantee.

#### 3.3 Evidence classes

The study uses an evidence ladder rather than a single undifferentiated benchmark claim. Sealed offline prediction supports comparative model accuracy. Deterministic software scenarios support controlled authority attribution. In-guest shadow execution supports integration, latency, memory, and no-execution claims. Recorded testbed replay supports robustness to real sensor streams under an explicit projection. Software physics supports geometry and contact stress. None of those alone supports live deployment safety.

![Figure 2. Evidence ladder and the strongest claim supported at each level. Higher levels add realism but do not erase the boundaries of lower-level measurements.](docs/research/figures/cross_domain_world_model/evidence_ladder.png)

<!-- PAGE BREAK -->

### 4. Registered methods

#### 4.1 Domains and representations

FerrumOS represents an agentic operating-system transition: a captured system state, a canonical action, and the next state or bounded rollout. The runtime normalizes provider output before prediction, keeping provider identity out of the action semantics. Physical JEPA represents compact navigation and maintenance state with a seven-action ontology. The two domains share the evaluation logic but not feature meanings, labels, or deployment surfaces.

The cross-domain protocol is prospective and digest-bound. It registers source artifacts, train/validation/final partitions, architecture families, seeds, update budget, parameter tolerance, model selection rule, bootstrap procedure, learned-contribution threshold procedure, and protected deployment digests. Selection programs are denied final paths. Final evaluation is once-opened, writes to new result paths, and cannot overwrite a deployed model.

#### 4.2 Matched architecture study

The factorial design contains 18 completed training runs: two domains by three methods by three seeds. Seeds are 17, 43, and 101. Each run receives the same domain-specific rows and curriculum, 2,400 AdamW updates, batch size 512, and a nominal 100,000-parameter budget with 5% tolerance. The methods are a direct feed-forward MLP, an action-conditioned JEPA, and GRU dynamics. Every model completes the full update budget. Lowest validation Gaussian negative log likelihood selects a checkpoint without final access.

Final evaluation measures normalized rollout error at H=1, H=3, and H=5. Paired episode bootstrap differences use the same final episodes for both methods. The estimand is architecture performance within this registered small-model setting, not a theorem about all JEPA, recurrent, or supervised models.

#### 4.3 Temporal causality and uncertainty

The paired temporal catalogs introduce changing actions, delayed hazards, interaction effects, partial observation, and exogenous degradation and recovery. Counterfactual pairs share the same initial state and random schedule while varying the intervention. Directional accuracy measures whether the selected model ranks paired consequences in the intended direction. Individual-treatment-effect normalized MAE measures the magnitude error in the predicted intervention difference. Multi-action rollout error evaluates H=3 and H=5 sequences rather than repeated single actions.

Three seeded models form an ensemble diagnostic for epistemic variation. The evaluator also records learned aleatoric variance, standardized OOD distance, reliability bins, Brier score, ECE, and risk-versus-coverage curves. These quantities are descriptive unless a registered gate states otherwise. In particular, abstention is not credited when removing high-uncertainty cases fails to monotonically reduce error.

#### 4.4 Learned-contribution benchmark

For each domain, the lowest-validation-NLL architecture is frozen. Platt calibration and the intervention threshold are fitted on development data. The registered selection rule preserves zero false positives and produces a threshold of 0.99. Only after the model, calibration, and threshold are fixed does the generator create a 512-case final catalog containing 256 simulator-labelled dangerous cases and 256 matched safe cases.

Three paired arms are evaluated: rules only, learned only, and rules plus learned. Marginal learned hazard avoidance counts dangerous cases blocked by the learned branch but not by rules. Marginal safe intervention counts safe cases stopped only by the learned branch. Wilson intervals summarize binomial zero counts; a 5,000-pair bootstrap evaluates the marginal difference. The absent external-design manifest forces the label `researcher-designed blinded deterministic-software benchmark`.

#### 4.5 Runtime and external evidence

FerrumOS shadow evaluation injects the research artifact only into disposable appliance-disk copies under QEMU/WHPX. Read-only preview follows the real ring-3 inference path but cannot call the execution method. A multi-client protocol uses four distinct WebSocket clients. A natural-use protocol operates three separately booted visible guests through ordinary assistant interactions and records only privacy-bounded event fields.

Physical evaluation has four separate components. Recorded HAI testbed streams are projected through previously frozen statistics and replayed with registered latency, jitter, noise, dropout, and combined faults. NVIDIA Anchor-Lab files are inspected for semantic compatibility before inference. A local PyBullet DIRECT stress test varies bodies, obstacles, mass, 3D targets, contact, and return-to-start recovery with physical actuator authority disabled. Finally, Safety-Gymnasium v1.0.0 supplies the externally maintained SafetyPointGoal1-v0 task and simulator costs. A registered adapter compares a naive local controller, a privileged deterministic grid planner, rules-only and learned-only shields, and their monotone union while keeping actuator authority zero.

#### 4.6 Frozen gates and non-promotion rule

The umbrella verifier requires finite results, final-open counts of one, denied final access during selection, unchanged protected digests, zero actuator authority, honest independence labels, and successful subordinate verifiers. Passing an experiment verifier does not imply deployment eligibility. The study-level result explicitly sets `promotion_eligible` to false, and the deployed FerrumOS encoder, transition, manifest, and Physical JEPA transition hashes must remain unchanged.

### 5. Architecture-controlled results

#### 5.1 Domain-dependent ranking

Table 1 reports final normalized rollout error. Physical JEPA wins at every horizon. FerrumOS does not reproduce that ranking: the GRU is best at H=1 and H=3, while the JEPA is best at H=5. All reported pairwise episode-bootstrap intervals exclude zero at all three horizons.

| Domain | Method | H=1 | H=3 | H=5 |
|---|---|---:|---:|---:|
| FerrumOS | Direct MLP | 0.004751 | 0.008431 | 0.007256 |
| FerrumOS | Action-conditioned JEPA | 0.009888 | 0.012356 | **0.005494** |
| FerrumOS | GRU dynamics | **0.004609** | **0.007917** | 0.006514 |
| Physical | Direct MLP | 0.007188 | 0.016836 | 0.026362 |
| Physical | Action-conditioned JEPA | **0.002476** | **0.006680** | **0.010465** |
| Physical | GRU dynamics | 0.010659 | 0.026231 | 0.039542 |

The physical MLP-minus-JEPA H=3 difference is 0.010156 with 95% interval [0.009829, 0.010483]. In FerrumOS, GRU-minus-JEPA is favorable to the GRU at H=3 by 0.004439 [0.003203, 0.005735]. At H=5 the sign reverses: JEPA-minus-GRU is -0.001020 [-0.001165, -0.000865]. These are not marginal three-case classification differences; the shared-catalog rollout contrasts are statistically separated under the registered resampling procedure.

![Figure 3. Matched rollout errors for the three model families. The ranking reversal is the main architecture result: no family dominates both domains and all horizons.](docs/research/figures/cross_domain_world_model/matched_rollout_results.png)

#### 5.2 Interpretation

The result closes a data and compute confound that affected historical comparisons, but only within this study. The physical representation and curriculum favor the action-conditioned JEPA decisively. FerrumOS contains short-horizon structured state changes for which recurrent dynamics are more effective, while the JEPA has the lowest long-horizon error at H=5. Architecture choice should therefore be treated as an empirical property of the state, action, horizon, and training regime rather than a brand-level claim.

The matched study also changes how the two earlier reports should be read. The Physical JEPA result can now be described as an architecture-controlled rollout advantage in its registered domain. The FerrumOS lineage cannot claim that a JEPA is the strongest general small dynamics model. Its stronger contribution is the mediation architecture, evidence discipline, and the request-bounded separation between prediction and authority.

### 6. Causal sensitivity, calibration, and operational value

#### 6.1 Paired temporal results

The selected FerrumOS GRU produces the correct counterfactual direction in 100.00% of pairs, ITE normalized MAE 0.002571, H=3 multi-action error 0.044558, and H=5 error 0.046720. The selected Physical JEPA reaches 93.36% directional accuracy, ITE normalized MAE 0.016819, H=3 error 0.026772, and H=5 error 0.046361.

| Domain | Selected model | Direction | ITE MAE | H=3 multi | H=5 multi |
|---|---|---:|---:|---:|---:|
| FerrumOS | GRU dynamics | 100.00% | 0.002571 | 0.044558 | 0.046720 |
| Physical | Action-conditioned JEPA | 93.36% | 0.016819 | 0.026772 | 0.046361 |

Directional sensitivity establishes that the models do not merely reproduce a static current-state score. It does not establish calibrated hazard probability, adequate recall, or useful intervention. Multi-action errors are also substantially larger than the matched single-policy H=3 values in Table 1, which is consistent with a harder shifted temporal task.

#### 6.2 Calibration under shift

FerrumOS Brier and ECE are 0.249943 and 0.238143. Physical Brier and ECE are 0.229970 and 0.292887. Reliability bins and risk-coverage curves show that uncertainty is not a certified error ordering: abstaining on the most uncertain cases does not monotonically improve H=5 error in either final catalog. The study therefore does not tune a new threshold after observing final results.

This is the point at which a prediction paper can accidentally become an authority claim. The models have measurable dynamics skill and causal sensitivity, yet the shifted risk scores are poorly positioned for a very conservative zero-false-positive threshold. Preserving the registered threshold reveals that mismatch instead of repairing it post hoc.

#### 6.3 Primary operational result

The operational result is identical in both domains and every arm. No case is stopped at threshold 0.99. Each arm therefore records 0 true positives, 0 false positives, 256 true negatives, and 256 false negatives.

| Domain | Arm | TP | FP | TN | FN | Intervention |
|---|---|---:|---:|---:|---:|---:|
| FerrumOS | Rules only | 0 | 0 | 256 | 256 | 0% |
| FerrumOS | Learned only | 0 | 0 | 256 | 256 | 0% |
| FerrumOS | Rules + learned | 0 | 0 | 256 | 256 | 0% |
| Physical | Rules only | 0 | 0 | 256 | 256 | 0% |
| Physical | Learned only | 0 | 0 | 256 | 256 | 0% |
| Physical | Rules + learned | 0 | 0 | 256 | 256 | 0% |

The learned branch adds zero dangerous-case blocks and zero safe-case interventions. The Wilson 95% upper bound for either marginal rate is 1.478%, and the 5,000-pair bootstrap interval is [0, 0]. All eight final families are delayed, coupled, masked, or exogenous: their danger labels materialize in later transitions, whereas the deterministic predicates inspect the current state and requested action. Consequently, `rule_block` is false in all 1,024 domain-case records by construction of this estimand; rules-only recall here is not an estimate of general rule quality. At the zero-FP-calibrated threshold, the learned branch also does not extend the authority boundary into this delayed-hazard regime, making the union arm uninformative because neither branch fires. This is a construct-coverage negative about threshold-based caution under latent hazards, not merely a completed program with finite zero estimates. No final-set retuning or deployment promotion follows.

![Figure 4. Predictive and causal evidence do not become operational learned value at the frozen threshold. The gap is measured rather than hidden by final-set retuning.](docs/research/figures/cross_domain_world_model/causal_vs_operational.png)

<!-- PAGE BREAK -->

### 7. FerrumOS authority-disabled runtime evidence

#### 7.1 In-guest shadow timing and integrity

The FerrumOS v3.4 research model was injected into disposable copies of the appliance disk and loaded by the actual ring-3 preview gate under QEMU/WHPX. Across 200 previews at each horizon from H=1 through H=5, p99 guest-reported time was 3 ms. The runtime reported 193,229 loaded parameters, both encoder and transition present, and zero retained heap growth. A separate canonical-command batch returned 96 of 96 correlated preview responses across six command classes.

The preview method did not emit an execution-dataset record, and the packaged source disk remained byte-identical after the test. These measurements establish an integrated authority-disabled path and bounded guest timing for the tested configuration. They do not establish end-to-end production latency, a hard real-time deadline, or permission to dispatch an action.

#### 7.2 Four-client contention

A registered run opened four distinct WebSocket clients against one guest. All 128 of 128 responses returned without cross-client response leakage. Jain throughput fairness was 0.999937, disconnect isolation succeeded, and a replacement client completed after one client disconnected. Per-client p95 latency ranged from 16.09 to 16.46 seconds because the single-threaded daemon serialized saturated inference.

The high latency is retained as a systems result, not averaged away. The run demonstrates response correlation, fairness, isolation, and recovery in one serial guest. It does not demonstrate parallel model execution, distributed consensus, field capacity, or multi-host availability. The action execution method was unavailable on these sockets with JSON-RPC error -32601. Execution records, physical delivery attempts, and physical deliveries were all zero.

#### 7.3 Visible natural-use sessions

Three independently booted disposable sessions were operated through the visible FerrumOS assistant using Windows computer control. A frozen prompt set produced 24 privacy-bounded telemetry rows across six action classes. Eighteen read-only actions executed successfully, three write actions remained awaiting operator confirmation, and three delete actions were blocked by the gate.

The committed telemetry excludes prompts, arguments, paths, provider identifiers, model identifiers, and output text. Language-model page-ins after deterministic requests, guest faults, synthetic collector markers, direct execution RPCs, physical deliveries, and source-disk changes were zero. This is short researcher-operated QEMU evidence. It is not a seven-day study, independent user testing, production telemetry, or a labelled precision/recall dataset.

#### 7.4 What the OS evidence supports

Together, the OS experiments support a narrow systems claim: a learned preview can run inside the real unprivileged mediation path while execution authority remains separately unavailable or gated. The experiments also expose a practical bottleneck under saturated serial inference. They do not rescue the zero learned-contribution result in Section 6. The strongest learned result remains architecture-controlled rollout prediction; the strongest authority result remains deterministic separation and absence of unauthorized effects.

### 8. Physical evidence and retained negatives

#### 8.1 Externally authored case intake

The external intake freezes Microsoft Azure VM-noise revision `207bed67dd10090b28ad4f745b2cfd41a11aace4` as an OS workload taxonomy and NVIDIA Anchor-Lab revision `647edd5787cd764cdc041103ad282dc59214d919` as physical telemetry. Azure families cover file, process, thread, program launch, CPU, memory, random I/O, and Redis contention. They inform the natural-use and contention mix but are not projected into FerrumOS vectors or treated as FerrumOS labels.

Six Anchor-Lab Parquet files contain 2,925,558 finite timestamped rows, including three publisher-designated held-out SO-101 trials and three H1 elbow-teststand conditions. The files contain command or target and measured-state telemetry but no safety or contact labels. Their joint, actuator, and temperature semantics do not match Physical JEPA v5's 16-state navigation and maintenance representation or seven-action ontology. No projection, inference, or actuator delivery was performed. The incompatibility is a useful negative intake result: it prevents a large external row count from being misrepresented as direct model validation.

#### 8.2 Recorded HAI sensor replay

The frozen Physical JEPA v5 artifact is evaluated over 284,398 one-second transitions from HAI 23.05 test1 and test2 using previously frozen projection statistics. Six conditions apply clean replay, two-second latency, zero-to-three-second jitter, 0.02 sensor noise, 5% hold-last dropout, and a combined fault with proxy-command feature saturation.

| Condition | H=1 MAE | Delta | AUROC | Event recall |
|---|---:|---:|---:|---:|
| Clean | 0.046627 | 0.000000 | 0.6115 | 38.46% |
| Latency 2 s | 0.050421 | 0.003794 | 0.6040 | 48.08% |
| Jitter 0-3 s | 0.049488 | 0.002861 | 0.6039 | 44.23% |
| Noise 0.02 | 0.055194 | 0.008567 | 0.5937 | 46.15% |
| Dropout 5% | 0.046735 | 0.000108 | 0.6105 | 38.46% |
| Combined | 0.059456 | 0.012829 | 0.6043 | 50.00% |

Host NumPy batch inference measured 2.239 microseconds median and 3.303 microseconds p99 per row. These are host software measurements, not physical control-loop timing. Across 472 injected observation-fault windows, the first clean row after the injection ended fell below 1.25 times clean p95 error. That zero-second observation restoration is not a physical recovery-time claim. Actuator delivery attempts and deliveries were both zero.

The replay is the strongest external physical evidence directly compatible with the present v5 representation, but it remains researcher-executed replay. It does not include live Ferrum hardware, physical clocks and interfaces, actuator dynamics, physical contact recovery, or an independently tested emergency-stop path.

#### 8.3 Multi-embodiment 3D stress

A separate PyBullet DIRECT protocol varies three bodies, three obstacle geometries, mass, three-dimensional targets, contact, and a one-second return-to-start recovery. All 288 cases are stopped by the union policy. Task completion is 0%, with Wilson 95% upper bound 1.32%. The unshielded arm contacts an obstacle in 205 of 288 cases. The union arm records no contacts only because it intervenes in 288 of 288 cases.

The learned branch contributes 23 interventions not produced by the rule; 13 coincide with an unshielded contact. Those cases cannot be credited as useful learned collision avoidance because the policy has no selectivity and completes no task. Simulated return-to-start recovery succeeds in 181 of 205 contact cases, or 88.29%, with Wilson interval [83.17%, 92.01%]. This locally designed software-physics test adds geometry and contact coverage while failing the completion-versus-intervention objective.

| 3D outcome | Count | Rate or interval |
|---|---:|---:|
| Union interventions | 288 / 288 | 100.00% |
| Completed tasks | 0 / 288 | 0%; upper 95% 1.32% |
| Unshielded contacts | 205 / 288 | 71.18% |
| Learned-only interventions | 23 / 288 | 7.99% |
| Learned-only and unshielded contact | 13 / 288 | 4.51% |
| Simulated recovery | 181 / 205 | 88.29% [83.17%, 92.01%] |

No shielded contact was observed in this run; this does not establish a zero underlying collision probability. More fundamentally, avoiding contact by stopping every case is not useful autonomy. Retaining the negative prevents an embodiment-diversity checkbox from being mistaken for deployment progress.

#### 8.4 Prospective Safety-Gymnasium controller and shield benchmark

The v14 amendment freezes Safety-Gymnasium v1.0.0, Gymnasium 0.28.1, MuJoCo 2.3.3, the installed simulator-source digest, the protected Physical JEPA v5 digest, a deterministic risk adapter fitted on opened seeds 4000-4095, candidate choice on opened seeds 4096-4127, and untouched final seeds 6000-6127. The 20-step oracle rolls out the nominal receding-horizon controller from synchronized simulator state; it does not repeat the current command for 20 steps. Warning recall and warning FPR evaluate the detector, whereas intervention rate counts only commands that actually change. The external project supplies the task, layouts, observations, goal condition, and hazard costs [17]. This study supplies the adapter, privileged planner, tangent shield, execution, and analysis. Execution is local, actuator authority is disabled, and no independent replication is claimed.

| Final arm | Completion | Effective intervention | Warning recall | Warning FPR | Effective-action recall | Hazard-cost events |
|---|---:|---:|---:|---:|---:|---:|
| Naive unshielded | 100.00% | 0.00% | 0.00% | 0.00% | 0.00% | 542 |
| Planner unshielded | 94.53% | 0.00% | 0.00% | 0.00% | 0.00% | **70** |
| Planner + rules | 94.53% | 0.00% | 0.00% | 0.00% | 0.00% | 70 |
| Planner + learned | **96.09%** | 1.86% | **95.62%** | 3.24% | 55.00% | 84 |
| Planner + rules + learned | **96.09%** | 1.86% | **95.62%** | 3.24% | 55.00% | 84 |

The union passes every registered joint-objective gate relative to the frozen benchmark criteria; these gates do not require superiority over the privileged planner: 96.09% completion, 1.86% effective intervention, 95.62% warning recall, 3.24% warning FPR, and 84.50% fewer hazard-cost events than the naive controller (542 to 84). Its effective action-change recall is 55.00% (88/160): warned dangerous proposals do not count as interventions when the tangent command is already identical to the planner command. Executed intervention precision is 23.04% (88/382): 294 of 382 changed commands occur on oracle-labelled non-dangerous trajectories. That low precision is mechanistically consistent with the observed planner-relative hazard-cost increase, but the design does not identify causality and the paired interval includes zero. Its episode-bootstrap 95% intervals are 92.19%-99.22% for completion, 1.18%-2.55% for intervention, 81.58%-100.00% for warning recall, and 2.19%-4.31% for warning FPR. No final rerun or recovery path was used.

Relative to the privileged planner, the union changes completion by +1.5625 percentage points (paired 10,000-resample episode-bootstrap 95% CI [-1.5625, 4.6875]) and realized hazard cost by +14 steps (95% CI [-22.025, 54.000]). Neither interval excludes zero, so the observed two-task gain and 14-step increase are descriptive rather than statistically stable at this sample size.

Attribution remains essential. The privileged planner alone reduces hazard cost from 542 to 70 (87.08%). Adding the learned tangent branch increases completion from 121/128 to 123/128 but increases hazard-cost events from 70 to 84 (plus 14). All 382 effective union interventions are learned-only because the high-closeness rule never changes a command on this final distribution. The adapter warns on 153/160 dangerous controller trajectories, while 88/160 receive a different command; the remaining warned cases already propose the saturated tangent-compatible turn. The benchmark therefore supports a passing naive-baseline runtime objective and a completion/cost tradeoff over the planner, not learned collision-avoidance superiority over privileged planning.

### 9. Cross-domain synthesis

#### 9.1 Prediction quality is domain-specific

The matched study rejects the simplest architecture story. Physical dynamics strongly favor the JEPA in this registered setting. FerrumOS short-horizon prediction favors the GRU, with the JEPA best only at H=5. The result is more useful than a universal-winner claim because it exposes where architecture selection must remain empirical. It also gives the Physical JEPA paper a controlled dynamics comparison while making the FerrumOS systems claim less dependent on a JEPA label.

#### 9.2 Causal response is not calibrated authority

Both selected models react to paired interventions in the intended direction. Neither generates an operational intervention at the conservative frozen threshold on the shifted final catalogs. These findings are compatible: a model can encode direction and approximate magnitude while its calibrated score lacks separation at a chosen false-positive constraint. Reporting only rollout or directional accuracy would conceal the actual decision failure.

#### 9.3 Deterministic authority can fail differently

The new 512-case catalogs show no interventions from either rules or learning, while the 3D stress intervenes on every case. The prospective Safety-Gymnasium result separates a useful privileged planner-only controller from an active union that passes the naive-baseline objective but trades higher completion for higher hazard cost relative to the planner. The contrast shows why controller quality cannot be credited to a shield and why warning recall cannot substitute for marginal executed outcomes. These three outcomes show why deterministic authority must be evaluated with task completion, intervention, proposal recall, false positives, realized cost, and controller divergence rather than a collision count alone.

#### 9.4 Evidence ladders prevent category errors

QEMU timing is not production throughput. Researcher-operated sessions are not independent user evidence. Recorded sensors are not live HIL. PyBullet contact is not physical collision evidence. An externally maintained simulator task executed by the author is not an independent replication, and a planner with direct simulator geometry is not a sensor-only robot controller. A publisher-heldout robotics file is not compatible merely because it contains robot telemetry. Labelling those boundaries does not weaken the contribution; it makes the evidence composable and reproducible.

#### 9.5 Novelty statement

This work does not claim the first JEPA world model, first safety filter, first calibrated predictor, or first runtime-assurance architecture. Its contribution is the cross-domain combination of: matched architecture control; explicit separation of prediction, policy, capability, and effect; sealed validation-only selection; paired causal and operational estimands; runtime evidence with authority disabled; semantic compatibility checks for external data; retained operational negatives; and digest-verified non-promotion. The principal hypothesis supported is methodological: predictive evidence and authority evidence should be registered, measured, and reviewed separately.

### 10. Threats to validity and limitations

1. The final temporal catalogs and 3D benchmark use deterministic simulator labels designed locally. Safety-Gymnasium improves task and cost provenance, but its adapter, controller, shield, execution, and assessment remain local; no independent replication is claimed.

2. The architecture result is controlled within the chosen data, state representations, parameter scale, optimizers, and update budget. It does not establish universal superiority for any model family.

3. Calibration is weak under the registered temporal shift. ECE is bin-dependent, and risk-coverage ordering is not monotonic. No calibrated safety guarantee is claimed.

4. The 512-case operational zero-result remains threshold-specific. The later Safety-Gymnasium families also sit outside the present-state deterministic predicates' evaluation window, so their rules-only zero is a catalog-coverage property rather than a general estimate of rule quality. The later Safety-Gymnasium protocol selects a different registered navigation operating point on development seeds and evaluates it once on untouched seeds; it does not retroactively repair the earlier estimand.

5. FerrumOS runtime evidence uses QEMU/WHPX, disposable disks, a serial daemon, four local clients, and 24 requests from one researcher. There is no production load, multi-host field test, independent user study, or long-duration natural-use telemetry.

6. The Physical JEPA replay uses an explicit projection of recorded testbed sensor streams. There is no live Ferrum HIL, physical actuation, physical timing, sensor-interface latency, actuator dynamics, human contact, or hardware emergency-stop validation.

7. The HAI replay's event labels and proxy features do not convert it into an end-to-end safety benchmark. Host microsecond measurements and one-row observation restoration are not control-loop or physical-recovery timings.

8. Anchor-Lab telemetry is externally authored but semantically incompatible with direct v5 scoring. It supports a future embodiment-specific model, not transfer of the present one.

9. The PyBullet environment is locally designed and simple relative to robotics benchmarks. Its 100% intervention rate and 0% completion remain a negative stress result. Safety-Gymnasium adds an external task implementation, but only the Point navigation subset is covered.

10. The strongest Safety-Gymnasium controller uses direct simulator geometry in a deterministic grid planner. Its high proposal divergence must not be confused with low shield intervention or sensor-only deployability. Deterministic rules remain engineering predicates, not formally verified invariants.

11. No live actuator timing, physical contact, hardware emergency stop, actuator dynamics, sensor-interface latency, human-contact dynamics, or independent execution is established. The report remains a CPS/runtime-assurance study, not a robotics-deployment study.

12. No protected research result was promoted. The report therefore evaluates a research lineage, not a deployed policy change.

### 11. Reproducibility and artifact integrity

The umbrella verifier binds protocols, selections, results, runtime reports, external intake, replay amendments, stress tests, and subordinate verifiers by SHA-256. It independently recomputes protected deployment digests and requires `promotion_eligible=false`. Selection attempts are logged, final paths are denied during model and threshold choice, and once-opened results write to new files.

Principal reproduction commands are:

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
python scripts/verify_physical_jepa_safety_gymnasium_v14.py
python scripts/evaluate_physical_jepa_safety_gymnasium_paired_uncertainty.py
python scripts/verify_physical_jepa_safety_gymnasium_paired_uncertainty.py
python scripts/verify_cross_domain_world_model_improvement_study.py
python scripts/verify_cross_domain_world_model_paper.py
```

The paper verifier checks required claims and boundaries in the manuscript, PDF text and metadata, figure presence, page count, source and PDF digests, the umbrella verification result, non-promotion status, and protected-artifact integrity. A paper freeze record identifies the exact manuscript, rendered PDF, figures, and evidence snapshot used for Technical Report v1.1.

### 12. Conclusion

This report finds a real architecture-controlled advantage for Physical JEPA and a different ranking in FerrumOS. It also finds zero learned intervention at the original conservative operating point and an all-stop failure in the 3D stress test. In the later prospective Safety-Gymnasium benchmark, the privileged planner alone reaches 94.53% completion with 87.08% fewer realized hazard-cost events than the naive baseline. The active union passes the registered objective with 95.62% warning recall and 84.50% lower hazard cost than naive, but adds 14 hazard-cost steps relative to the planner while completing two additional tasks; the paired 95% intervals for both planner-relative differences include zero. These results locate distinct engineering problems: learning dynamics, calibrating decisions under shift, designing useful authority policies, and separating planner effects from shield and learned-model effects.

The defensible contribution is therefore not that a world model makes an operating system or robot safe. It is that world models can be evaluated inside a reproducible authority architecture without being mistaken for authority. Prediction remains advisory; deterministic policy, capability, confirmation, and actuator denial remain independently enforceable; negative evidence remains visible; and deployment remains unchanged unless a separate prospective deployment protocol passes. The union passes this software benchmark, but the privileged-planner marginal tradeoff and absence of HIL or independent execution keep every research artifact explicitly ineligible for promotion.

#### 12.1 Submission scope

The appropriate submission identity is a cyber-physical systems, runtime-assurance, or dependable-agent-systems paper. The Physical JEPA experiments include externally recorded sensors and software physics, but no live actuation; calling the work a robotics-deployment paper would exceed the evidence. The FerrumOS experiments include a real in-guest mediation path but no production population. The cross-domain value is the shared authority method and the controlled contrast, not an assertion that the two environments are equivalent.

#### 12.2 Remaining evidence tier

The prospective joint objective now passes on an external simulator task, while the planner-relative comparison remains a completion/cost tradeoff rather than learned collision-avoidance superiority. Another local seed range or threshold sweep has low scientific value. The next evidence-class changes are a controller/shield design fixed before an externally executed benchmark, actuator-disabled live HIL with physical clocks and interfaces, and execution of a frozen protocol by an independent party. For FerrumOS, independently operated longitudinal use and concurrent preview remain more valuable than additional synthetic prompts. These are next-tier studies, not claims that can be fabricated inside the present software-only report.

#### 12.3 Release rule

Future improvements should create new versioned research artifacts and preserve every failed frozen result. A candidate may be promoted only under a separate prospective deployment protocol that identifies the exact protected targets, rollback path, capability boundary, post-execution verification, and all required gates. Publication of this report does not satisfy that protocol.

<!-- PAGE BREAK -->

### Appendix A. Claim-to-evidence ledger

This ledger is part of the report rather than a supplementary marketing summary. It identifies the evidence object that supports each major statement and the closest claim that the same object does not support. The purpose is to make category errors visible during review.

| Claim | Primary evidence | Supported result | Explicit exclusion |
|---|---|---|---|
| Physical JEPA leads matched alternatives | Shared frozen physical final catalog | Lowest H=1, H=3, H=5 rollout error; paired intervals exclude zero | Not universal JEPA superiority |
| FerrumOS ranking differs | Shared frozen FerrumOS final catalog | GRU leads H=1 and H=3; JEPA leads H=5 | Not evidence that recurrent models are universally best |
| Selected models encode interventions | Paired temporal counterfactual catalogs | 100.00% and 93.36% directional accuracy | Not calibrated hazard recall |
| Shifted scores are weakly calibrated | Frozen reliability, Brier, and ECE outputs | ECE 0.238143 and 0.292887 | Not a formal probability guarantee |
| Learned models add operational caution | Three-arm 512-case catalogs | Zero marginal blocks at threshold 0.99 | No learned safety-value claim |
| Runtime preview is integrated | FerrumOS QEMU ring-3 shadow path | H=1-H=5 p99 guest time 3 ms | Not production or hard real-time timing |
| Multiple clients remain correlated and isolated | Four WebSocket clients, 128 responses | No leakage; Jain fairness 0.999937 | Not parallel inference or distributed execution |
| Visible assistant mediation works in bounded sessions | Three QEMU boots, 24 requests | Reads execute; writes await confirmation; deletes block | Not independent users or production telemetry |
| External physical streams can be replayed | 284,398 HAI transitions | Fault-condition error and event diagnostics | Not live Ferrum HIL or physical recovery |
| Anchor-Lab adds external embodiment data | Six publisher files, 2,925,558 rows | Timing and command/state fields are finite | Not semantically valid for direct v5 scoring |
| 3D geometry/contact stress is exercised | 288 local PyBullet DIRECT cases | Contact and simulated recovery are measured | Not practical learned safety at 100% intervention |
| Controller and shield are jointly evaluated | Safety-Gymnasium final seeds 6000-6127 | Planner-only: 94.53% completion and 87.08% cost reduction; union passes all registered naive-baseline gates with 95.62% warning recall, 55.00% effective-action recall, and 23.04% intervention precision, but costs 14 more hazard steps than planner | Not independent, sensor-only, physical, or learned-superiority evidence |
| Deployment stayed unchanged | Recomputed protected SHA-256 digests | Every protected artifact is byte-identical | Not a deployment or release result |

#### A.1 Evidence precedence

When two measurements appear to support different narratives, the operationally closer measurement takes precedence for the operational claim. For example, the physical JEPA's rollout advantage remains valid even though its learned-only intervention count is zero. The former supports dynamics prediction; the latter controls any statement about safety-gate value at threshold 0.99. Likewise, zero union contacts in the 3D run does not supersede 0% task completion and 100% intervention. The complete outcome vector is the result.

#### A.2 Negative-result taxonomy

The study distinguishes three types of negative evidence. A scientific negative is a completed comparison whose registered estimand does not support the hoped-for effect, as in zero learned marginal caution. A gate pass can still contain a negative marginal contrast, as v14 does when the union improves completion but worsens hazard cost relative to the planner. An engineering negative is a system behavior that is measurable but unusable, as in serial multi-client latency or the all-stop 3D policy. A compatibility negative occurs before model scoring when external data do not share the required semantics, as with Anchor-Lab. None is a failed run, and none should be rewritten as missing data.

<!-- PAGE BREAK -->

### Appendix B. Frozen-gate and artifact audit

The paper inherits the study's frozen-gate discipline. Each verifier checks its own source objects and writes a result that is subsequently bound by the umbrella verification record. The paper verifier does not recompute every experiment; it requires the already committed umbrella result to pass, verifies its non-promotion and protected-digest assertions, and then binds the manuscript and rendered PDF to that evidence snapshot.

| Stage | Frozen before final access | Verification requirement | Mutation boundary |
|---|---|---|---|
| Architecture selection | Methods, seeds, updates, parameter tolerance, validation rule | Final inaccessible during every selection run | New research model outputs only |
| Architecture evaluation | Selected checkpoints and final-catalog generator | One final opening; paired bootstrap finite | No deployed artifact path |
| Learned contribution | Model, calibrator, threshold, three arms | One final opening; honest zero marginal result | No post-final threshold tuning |
| FerrumOS shadow | Guest image source, command classes, horizons | Correlated responses, runtime fields, source-disk hash | Disposable disk copies only |
| Multi-client contention | Four-client schedule and correlation IDs | 128 responses, isolation, fairness, recovery | Execution RPC unavailable |
| Natural use | Prompts, sessions, privacy schema | 24 bounded rows; forbidden fields absent | Researcher-operated disposable guests |
| External intake | Source revisions and semantic checklist | File counts, finite rows, compatibility decision | No invalid feature projection |
| Recorded replay | Projection, faults, descriptive threshold | All transitions finite; authority counters zero | No artifact retraining or actuation |
| 3D stress | Bodies, obstacles, cases, recovery rule | All outcomes and Wilson intervals retained | PyBullet DIRECT; actuator authority zero |
| External useful-autonomy test | Runtime lock, dev/final seeds, candidates, five arms, joint gates | One untouched final opening; raw union rows and all arms independently recompute | Safety-Gymnasium DIRECT; privileged planner; actuator authority zero |
| Paired planner-union uncertainty | Seed pairing, estimands, 10,000 resamples, bootstrap seed | Completion and hazard-cost differences independently recompute; both intervals include zero | Post-hoc analysis of committed episode summaries; no final rerun |
| Paper freeze | Required claims, boundaries, figures, metadata | Text, hashes, pages, evidence snapshot pass | Documentation artifacts only |

#### B.1 Protected deployment inventory

The umbrella record protects four deployed objects: the FerrumOS encoder, FerrumOS transition, FerrumOS manifest, and Physical JEPA transition. Their observed digests equal their registered expected digests. The cross-domain architecture models, calibration objects, final catalogs, replay projections, and 3D results are research artifacts. A passing paper verifier cannot change that status. Promotion would require a separate prospective protocol and every deployment-specific gate.

#### B.2 Reproduction order

A reviewer can begin with `verify_cross_domain_world_model_improvement_study.py`, which checks the subordinate verification records and protected digests. For deeper inspection, the architecture and learned-contribution verifiers expose selection-access logs and final-open accounting; runtime verifiers expose no-execution and source-disk checks; physical verifiers expose actuator-authority counters and result attribution. The final paper verifier then checks that the manuscript says what the evidence permits, not merely that a PDF exists.

#### B.3 Archival boundary

Technical Report v1.1 is intended to be archived together with its manuscript, figures, paper verification record, and freeze manifest. Dataset or software records may receive their own archival identifiers because they are independently reusable objects. Reciprocal links should identify the exact immutable report version and the exact dataset or software version without implying that a repository's moving branch is itself frozen. The DOI fields are intentionally not invented in this pre-archive build; they can be added only after the archival service reserves or publishes the corresponding identifiers.

<!-- PAGE BREAK -->

### Appendix C. Artifact locator

The repository is the executable supplement to the narrative. Table C.1 lists the shortest path from a headline claim to its primary machine-readable evidence. Verification files are intentionally separate from result files so that a result producer is not the sole authority for its own gate.

| Evidence object | Repository path | Review use |
|---|---|---|
| Prospective cross-domain protocol | `docs/research/cross_domain_world_model_improvement_protocol_v1.json` | Registered methods, seeds, budgets, access and promotion rules |
| Architecture selection | `docs/research/cross_domain_world_model_selection_v1.json` | Check chosen family and denied final access |
| Architecture result | `docs/research/cross_domain_world_model_architecture_result_v1.json` | Recompute H=1, H=3, H=5 tables and paired intervals |
| Learned-contribution result | `docs/research/cross_domain_learned_contribution_result_v1.json` | Recompute three-arm confusion matrices and marginal counts |
| FerrumOS shadow result | `docs/research/world_model_v3_4_shadow_runtime_v1.json` | Inspect guest timing, loaded artifact and no-execution fields |
| Multi-client result | `docs/research/world_model_multiclient_contention_result_v1.json` | Inspect correlation, fairness, leakage and recovery |
| Natural-use result | `docs/research/world_model_natural_use_result_v1.json` | Inspect bounded sessions and privacy assertions |
| External intake result | `docs/research/world_model_external_case_intake_result_v1.json` | Inspect source revisions, rows and compatibility decision |
| Recorded replay result | `docs/research/physical_jepa_recorded_hil_replay_result_v1.json` | Recompute fault-condition and authority-disabled metrics |
| 3D stress result | `docs/research/physical_jepa_multi_embodiment_3d_result_v1.json` | Recompute completion, intervention, contact and recovery |
| External useful-autonomy protocol | `docs/research/physical_jepa_safety_gymnasium_protocol_v14.json` | Inspect runtime lock, seed boundary, candidate policy and frozen joint gates |
| External useful-autonomy result | `docs/research/physical_jepa_safety_gymnasium_result_v14.json` | Recompute five arms, planner divergence, learned-only attribution and realized-cost reduction |
| External useful-autonomy verification | `docs/research/physical_jepa_safety_gymnasium_verification_v14.json` | Confirm raw cases, exact seeds, hashes, gates, authority zero and non-promotion |
| Paired planner-union uncertainty | `docs/research/physical_jepa_safety_gymnasium_paired_uncertainty_result_v1.json` | Recompute seed-matched completion and realized hazard-cost difference intervals |
| Umbrella verification | `docs/research/cross_domain_world_model_improvement_verification_v1.json` | Confirm subordinate passes, claim boundaries and protected hashes |
| Narrative study | `docs/research/CROSS_DOMAIN_WORLD_MODEL_IMPROVEMENT_STUDY.md` | Read the compact evidence-first study before this full report |

#### C.1 Recommended audit path

Begin with the prospective protocol and umbrella verification. Confirm `promotion_eligible=false`, all protected `unchanged` fields, and the claim-boundary list. Then inspect the architecture and learned-contribution results together: this prevents a favorable rollout table from being detached from the operational zero-result. Continue to the runtime and physical records only for the integration claims they support. In the Safety-Gymnasium evidence, compare all five arms and planner divergence before attributing any outcome to the learned branch. Finally, execute the paper verifier and compare its recorded manuscript and PDF digests with the archived files.

#### C.2 Versioning rule

The report version identifies a fixed document, not a promise that every moving repository file will remain identical forever. Corrections that alter prose, evidence binding, or layout should create a new immutable report version and retain the old version in archival history. Dataset and software deposits should use their own versioned records when they are independently reusable. A concept DOI may identify the evolving record, while the paper should cite the immutable version DOI used during review.

<!-- PAGE BREAK -->

### References

[1] A. Bardes, Q. Garrido, J. Ponce, X. Chen, M. Rabbat, Y. LeCun, M. Assran, and N. Ballas. "Revisiting Feature Prediction for Learning Visual Representations from Video." arXiv:2404.08471, 2024. https://arxiv.org/abs/2404.08471

[2] A. Bardes et al. "V-JEPA 2: Self-Supervised Video Models Enable Understanding, Prediction and Planning." arXiv:2506.09985, 2025. https://arxiv.org/abs/2506.09985

[3] T. Zhou et al. "DINO-WM: World Models on Pre-trained Visual Features Enable Zero-shot Planning." arXiv:2411.04983, 2024. https://arxiv.org/abs/2411.04983

[4] T. Xie et al. "OSWorld: Benchmarking Multimodal Agents for Open-Ended Tasks in Real Computer Environments." arXiv:2404.07972, 2024. https://arxiv.org/abs/2404.07972

[5] D. Seto, B. Krogh, L. Sha, and A. Chutinan. "The Simplex Architecture for Safe Online Control System Upgrades." Proceedings of the American Control Conference, 1998.

[6] N. Phan et al. "Neural Simplex Architecture." NASA Formal Methods, 2020. https://doi.org/10.1007/978-3-030-55754-6_6

[7] N. Phan et al. "The Black-Box Simplex Architecture for Runtime Assurance of Autonomous CPS." NASA Formal Methods, 2022. https://doi.org/10.1007/978-3-031-06773-0_32

[8] NASA. "Formal Verification Framework for Runtime Assurance." NASA Technical Reports Server. https://ntrs.nasa.gov/citations/20210010253

[9] NASA. "Runtime Assurance for Unmanned Aircraft Systems." NASA Technical Reports Server. https://ntrs.nasa.gov/citations/20210014050

[10] L. Yang, B. Werner, R. K. Cosner, D. Fridovich-Keil, P. Culbertson, and A. D. Ames. "SHIELD: Safety on Humanoids via CBFs In Expectation on Learned Dynamics." arXiv:2505.11494, 2025. https://arxiv.org/abs/2505.11494

[11] K. Zhong, T. Liu, and Y. Wang. "Calibrated Predictive Safety for Heterogeneous Robots: An Action-Conditioned JEPA Framework with Model-Based Safety Shields." arXiv:2608.17496, 2026. https://arxiv.org/abs/2608.17496

[12] C. Guo, G. Pleiss, Y. Sun, and K. Q. Weinberger. "On Calibration of Modern Neural Networks." Proceedings of ICML, 2017. https://proceedings.mlr.press/v70/guo17a.html

[13] G. W. Brier. "Verification of Forecasts Expressed in Terms of Probability." Monthly Weather Review 78(1), 1950. https://doi.org/10.1175/1520-0493(1950)078%3C0001:VOFEIT%3E2.0.CO;2

[14] E. Coumans and Y. Bai. "PyBullet, a Python Module for Physics Simulation for Games, Robotics and Machine Learning." 2016-2021. https://pybullet.org

[15] Vyom Kulshrestha. "When Agents Control the Kernel: A JEPA World Model Safety Gate with Empirical False-Negative Decomposition." Technical Report v1.2, 2026. https://doi.org/10.5281/zenodo.22116399

[16] Vyom Kulshrestha. "Learned Caution, Deterministic Authority: An Action-Conditioned JEPA Safety Runtime for Cyber-Physical Systems." Technical Report v1.1, 2026. https://doi.org/10.5281/zenodo.22092356

[17] Safety-Gymnasium Contributors. "Safety-Gymnasium: A Unified Safe Reinforcement Learning Benchmark." Thirty-seventh Conference on Neural Information Processing Systems Datasets and Benchmarks Track, 2023. https://openreview.net/forum?id=WZmlxIuIGR
