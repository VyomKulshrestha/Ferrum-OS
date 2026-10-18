# Prediction Is Not Permission: Cross-Domain World Models Under Deterministic Runtime Authority

## Architecture-Controlled Evidence Across an Agentic Operating System and a Cyber-Physical Runtime

Technical Report v1.2 — 8 September 2026

Vyom Kulshrestha
Independent Researcher, India
ORCID: 0009-0009-1434-7148
vyomkulshrestha2004@gmail.com
github.com/VyomKulshrestha/Ferrum-OS

Research artifact accompanying the FerrumOS world-model evidence lineage.

### Abstract

World-model papers often move too quickly from predictive error to operational safety. This report contributes a registered evaluation method that separates six evidence objects: dynamics prediction, counterfactual response, warning quality, effective intervention, realized outcome, and independently enforced authority. It applies the method separately to FerrumOS and Physical JEPA across an 18-run matched architecture study, sealed threshold tests, authority-separated software integrations, a prospective Safety-Gymnasium controller/shield benchmark, a fresh risk-source attribution, and a retained-catalog intervention on the Physical JEPA output values. Failed and non-beneficial frozen stages remain in the record.

The registered Physical JEPA ensemble leads at H=1, H=3, and H=5. In FerrumOS, GRU leads at H=1 and H=3 and JEPA at H=5, but a registered post-hoc comparison on the same 238 H=5-eligible episodes favors JEPA at every horizon. The apparent reversal therefore cannot be isolated from episode composition. At the frozen 0.99 threshold, rules, learning, and their union all miss 256/256 delayed-hazard cases without intervening; a separate PyBullet stress instead stops every case and completes none.

On Safety-Gymnasium v14, the privileged planner accounts for most realized-cost reduction. The union passes its registered naive-baseline criteria with 95.62% warning recall and 55.00% effective-action recall, but superiority over the planner was not established. In the exploratory fresh-seed attribution, JEPA-output-only versus the full adapter changes hazard steps by -25 and intervention rate by -0.81 percentage points; multiplicity-adjusted intervals exclude zero, while completion and planner-superiority claims remain unresolved. A later output-value ablation on complete retained seeds 9000-9127 compares observed frozen JEPA values with preregistered development-mean masking. Observed values increase warning FPR by 1.67 points and intervention rate by 0.96 points; both pointwise 95% and post-hoc seven-endpoint Bonferroni-adjusted 99.29% intervals exclude zero. Intervention precision falls by 15.26 points pointwise, but its adjusted interval includes zero; completion, warning recall, effective recall, and hazard-step intervals also include zero. The design, estimands, fresh seed range, and bootstrap seeds were fixed before the catalogs existed. The v1 result lost prospective eligibility when an unrelated concurrent report rebuild failed its final protected-file check; the v2 reportable analysis is retrospective and the v3 verifier passes 51/51 checks without a simulator rerun. QEMU previews, recorded replay, and software physics exercise scoped integrations with execution or actuator authority denied where stated. No result establishes physical safety, independent replication, architecture-only causality, prospective confirmation, or deployment eligibility; protected artifacts remain unchanged.

### 1. Introduction

An autonomous system can predict what may happen without possessing the authority to make it happen. That distinction is easy to state and easy to blur. A world model may forecast that a file operation will exhaust disk space, that a service restart will destabilize a workload, or that a commanded motion will approach an obstacle. The forecast may be useful even when imperfect. It does not follow that a low predicted risk should grant a capability, bypass confirmation, or energize an actuator.

This report asks two connected questions. First, when training conditions are controlled, is one common model family consistently better at multi-horizon prediction across an agentic operating system and a cyber-physical state space? Second, does the selected learned model add useful caution beyond a frozen deterministic authority boundary at a registered false-positive operating point? The first question concerns predictive modeling. The second concerns operational decision value. Treating them as different estimands is the paper's central methodological choice.

The study extends two artifact-backed FerrumOS lineages: unprivileged action-conditioned OS forecasts before capability-gated effects, and a compact physical model evaluated with actuator authority disabled. It adds matched architectures, paired interventions, calibration, authority-disabled runtime tests, external-data intake, retained negative stress tests, a prospective Safety-Gymnasium evaluation [17], and a retrospective analysis of complete catalogs retained from a failed prospective output-value ablation.

#### 1.1 Contributions

The primary contribution is an evaluation method, not a new JEPA objective. It predefines the same six evidence objects named in the abstract; specifies how final data are sealed; retains invalid, failed, and non-beneficial stages; and binds each claim to a machine-readable record. The empirical contributions are: (1) an 18-run matched small-model comparison in two distinct domains; (2) paired temporal, calibration, and common-episode analyses that expose when predictive skill fails to become operational value; (3) an authority factorization in which learning may only add caution; (4) QEMU, recorded-sensor, PyBullet, and Safety-Gymnasium integrations labelled by evidence class; (5) a prospective controller/shield benchmark with planner-relative uncertainty; (6) a fresh risk-source attribution with multiplicity, paired-direction, leave-one-out, and common-proposal diagnostics; and (7) a retained-catalog output-value intervention that separates observed frozen JEPA values from development-mean masking while preserving the failed prospective record.

#### 1.2 Claim boundary

*Cross-domain* denotes application of the same evaluation and authority methodology to two domains. The models, state meanings, action spaces, labels, controllers, and datasets are not transferred between them. The temporal catalogs and PyBullet stress are locally designed software tests. Safety-Gymnasium supplies a third-party task and costs, but the adapters, privileged planner, correction, execution, and analysis are local. Physical evidence is replay and software simulation, not live HIL; FerrumOS evidence is disposable QEMU, not production use. No result establishes formal non-bypass, independent replication, human-contact safety, universal model superiority, or deployment safety, and no protected artifact is replaced.

<!-- PAGE BREAK -->

### 2. Related work and research position

#### 2.1 Predictive representations and action-conditioned world models

Joint-embedding predictive architectures learn in representation space instead of reconstructing every observation detail. V-JEPA demonstrates feature prediction for video without pixel-level reconstruction [1], while V-JEPA 2 extends predictive representation learning toward action-conditioned planning and reports deployment on Franka robot arms [2]. DINO-WM shows that visual features can support world-model prediction across control tasks without task-specific visual encoders [3]. These results motivate predictive abstractions, but they do not imply that the same architecture will dominate in compact structured state spaces or that a prediction should carry authority.

The present study differs in scope. It does not propose a new large-scale pretraining objective. It compares small models using matched domain-specific data, seeds, parameter budgets, and update budgets at a runtime decision boundary, then measures whether offline ranking survives calibration and an operational threshold. FLOPs and wall time are not equalized. Its novelty is primarily systems and methodology: authority remains separately enforceable, and every evidence class is labelled by what it can and cannot support.

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

The study uses an evidence ladder rather than a single benchmark label. Sealed prediction supports comparative accuracy; deterministic catalogs support controlled estimands; QEMU shadow execution supports tested integration and no-dispatch claims; recorded testbed replay supports a bounded external-stream projection; and software physics supports simulated geometry and contact. Higher rungs add realism but do not retroactively turn lower-rung evidence into physical or independent assurance.

![Figure 2. Evidence ladder and the strongest claim supported at each level. Higher levels add realism but do not erase the boundaries of lower-level measurements.](docs/research/figures/cross_domain_world_model/evidence_ladder.png)

#### 3.4 Authority threat model and enforcement tests

The threat model assumes a learned component may be wrong, missing, malformed, non-finite, stale, delayed, replayed, or paired with changed arguments or state. It also assumes callers may lack a capability or attempt to reach an effect through a separately enumerated interface. The tested contract is monotone blocking and independent authorization—not that blocking necessarily improves safety.

| Component exercised | Test class | Committed pass evidence | Execution availability during test |
|---|---|---|---|
| FerrumOS learned-plus-rule gate | In-guest integration | `world_model_failure_modes.json`: pass | QEMU command path available; false-safe, missing, non-finite, and forbidden-coverage cases exercised |
| FerrumOS assistant mediation | In-guest system observation | `world_model_natural_use_verification_v1.json`: pass | Authorized reads available; writes required confirmation; deletes blocked |
| Signed neural permit protocol | Host unit | `cross_domain_authority_test_inventory_v1.json`: 9/9 | Protocol library available; FerrumOS syscall path not exercised |
| Physical permit and disabled driver | Host unit | `cross_domain_authority_test_inventory_v1.json`: 128/128 | Simulator/offline adapter only; physical actuator unavailable |
| Safety-Gym risk adapter runtime | Host integration | `physical_jepa_safety_gymnasium_runtime_verification_v14.json`: pass | Simulator command available; physical actuator unavailable |

The mapped cases cover false-safe prediction, missing and non-finite artifacts, capability and permit denial, stale or replayed provenance, state revision, idempotency, and disabled physical delivery. They cover named protocol, daemon, and physical-runtime entry points, not every possible implementation path. In particular, physical permit unit tests do not establish FerrumOS syscall-path enforcement. Monotonicity means the learned branch cannot convert a deterministic *block* to *allow*; it does not mean an intervention is beneficial, as the PyBullet all-stop and planner-relative Safety-Gymnasium costs demonstrate.

### 4. Registered methods

#### 4.1 Domains, representations, and partitions

FerrumOS uses 48-state and 57-action-feature vectors for canonical operating-system transitions. Physical JEPA uses 16-state and 10-action-feature vectors (seven action identities plus three continuous features). Both use a three-step causal history; short prefixes repeat the first state and prepend zero actions. They share metric code but not semantics. FerrumOS contains 13,712 training, 3,477 validation, and 3,249 final transition examples; its final set combines 1,969 base-test rows with four held-out incident sources. Physical contains 187,200 training, 45,440 validation, and 20,480 final transitions; its final set has eight held-out incident families. Selection programs cannot read final paths.

#### 4.2 Matched architecture study

All methods predict the same normalized observable next-state delta, `(next_state - current_state) / registered_scale`, and a diagonal log variance. H-step rollout repeatedly adds the predicted delta in physical units while consuming the registered future action sequence. Normalized rollout error is the per-row mean absolute endpoint error divided componentwise by the same scale. Gaussian NLL and MAE therefore evaluate the same normalized target; NLL differs only by incorporating the predicted variance.

The direct MLP flattens three state-action pairs into `Linear-GELU-Linear`. The action-conditioned JEPA applies a linear state encoder, `tanh`, and a `Linear-GELU-Linear` latent predictor; a stop-gradient target encoder is updated with EMA coefficient 0.99, and training minimizes Gaussian NLL plus 0.25 times latent-target MSE. The GRU receives the same state-action sequence, uses its zero-initialized recurrent state, and maps the final hidden state to mean and variance. Collapse prevention is the stop-gradient EMA target plus the observable-delta NLL; constant-representation trials are separately rejected.

| Domain | Method | Hidden / latent | Trainable parameters | Selected checkpoint updates for seeds 17 / 43 / 101 |
|---|---|---:|---:|---:|
| FerrumOS | Direct MLP | 242 / — | 99,800 | 1800 / 2000 / 2100 |
| FerrumOS | Action-conditioned JEPA | 211 / 64 | 99,748 | 2400 / 2400 / 2400 |
| FerrumOS | GRU dynamics | 125 / — | 99,096 | 2400 / 2200 / 2200 |
| Physical | Direct MLP | 900 / — | 99,932 | 2400 / 2200 / 1800 |
| Physical | Action-conditioned JEPA | 777 / 24 | 99,911 | 2400 / 2400 / 2400 |
| Physical | GRU dynamics | 164 / — | 99,744 | 2400 / 2100 / 2400 |

Every run receives the same domain-specific split, seed set, batch size 512, maximum 2,400 AdamW updates, learning rate 0.001, weight decay 0.0001, and gradient clipping at 5. Lowest validation Gaussian NLL at 100-update checkpoints selects the saved state. The comparison is parameter- and update-matched, not strictly compute-controlled: FLOPs, wall-clock training time, and recurrent versus feed-forward execution cost were not equalized.

#### 4.3 Aggregation, temporal causality, and uncertainty

Table 1 uses an ensemble prediction: the three seed checkpoints each predict, their state predictions are averaged, and the endpoint error is then computed. It is not the best seed or the mean of the three member errors. Appendix D reports every member result. Episode bootstrap intervals resample final episodes while holding the trained checkpoints fixed; they measure final-layout sampling uncertainty, not the variability of retraining the architecture on new seeds.

Paired temporal catalogs vary an intervention while sharing the initial state and random schedule. Directional accuracy asks whether the consequence ranking changes in the registered direction; ITE normalized MAE measures the magnitude difference. Multi-action rollouts use the actual registered action sequence rather than repeating one command. Uncertainty diagnostics include ensemble dispersion, learned variance, OOD distance, reliability bins, Brier score, ECE, and risk-coverage curves; none is an authority token.

#### 4.4 Learned-contribution benchmark

For each domain, the lowest-validation-NLL architecture is frozen. Platt calibration and the intervention threshold are fitted on development data. The registered selection rule preserves zero false positives and produces a threshold of 0.99. Only after the model, calibration, and threshold are fixed does the generator create a 512-case final catalog containing 256 simulator-labelled dangerous cases and 256 matched safe cases.

Three paired arms are evaluated: rules only, learned only, and rules plus learned. Marginal learned hazard avoidance counts dangerous cases blocked by the learned branch but not by rules. Marginal safe intervention counts safe cases stopped only by the learned branch. Wilson intervals summarize binomial zero counts; a 5,000-pair bootstrap evaluates the marginal difference. The absent external-design manifest forces the label `researcher-designed blinded deterministic-software benchmark`.

#### 4.5 Runtime and external evidence

FerrumOS shadow evaluation injects the research artifact only into disposable appliance-disk copies under QEMU/WHPX. Read-only preview follows the real ring-3 inference path but cannot call the execution method. A multi-client protocol uses four distinct WebSocket clients. A natural-use protocol operates three separately booted visible guests through ordinary assistant interactions and records only privacy-bounded event fields.

Physical evaluation has four separate components. Recorded HAI testbed streams are projected through previously frozen statistics and replayed with registered latency, jitter, noise, dropout, and combined faults. NVIDIA Anchor-Lab files are inspected for semantic compatibility before inference. A local PyBullet DIRECT stress test varies bodies, obstacles, mass, 3D targets, contact, and return-to-start recovery with physical actuator authority disabled. Finally, Safety-Gymnasium v1.0.0 supplies the externally maintained SafetyPointGoal1-v0 task and simulator costs. A registered adapter compares a naive local controller, a privileged deterministic grid planner, rules-only and learned-only shields, and their monotone union while keeping actuator authority zero.

#### 4.6 Frozen risk-source attribution

The v2 attribution protocol holds SafetyPointGoal1-v0, the privileged planner, one-command tangent correction, 20-step oracle, Physical JEPA v5 artifact, episode limit, runtime lock, and seeds fixed. It varies only the warning pipeline: the full frozen v14 adapter; local lidar/action/goal/closeness/speed with JEPA weights zero; frozen JEPA clearance/velocity/progress outputs only; or current maximum hazard closeness only. Alternative logistic adapters are fitted on seeds 4000–4095 and select thresholds on 4096–4127 by matching the full adapter's validation FPR, then minimizing false negatives, then choosing the higher threshold. Final seeds 8000–8127 are opened once.

The first registered attribution attempt on seeds 7000–7127 failed after the baseline and full arm because the alternative JSON schema omitted a runner-required threshold alias. Its partial catalog is retained and excluded. The v2 repair adds only that alias, preserves every numeric adapter field and threshold, commits the repair before final access, and uses a new seed range.

#### 4.7 Retained-catalog output-value intervention

The output-ablation v1 protocol fixed SafetyPointGoal1-v0, the full v14 risk adapter, threshold 0.72, tangent correction, final seeds 9000-9127, two paired arms, all estimands, and bootstrap seeds before either catalog existed. The observed arm passes the three frozen Physical JEPA v5 outputs into the unchanged adapter. The masked arm computes the same outputs but replaces raw adapter features 22-24 with their preregistered development means immediately before scoring. A 10,000-resample paired episode bootstrap estimates observed-minus-masked changes. Pointwise 95% intervals are accompanied by a post-hoc Bonferroni sensitivity controlling 5% familywise error across the seven endpoints displayed in Section 8.6, yielding 99.29% intervals. A stricter audit across all 11 registered paired outputs checks whether the displayed-endpoint family changes the survivor set. This is a direct closed-loop intervention on output values within one fixed software pipeline; it is not an architecture replacement or an architecture-wide causal claim.

Both 128-episode catalogs completed during the prospectively specified v1 execution before a post-run protected-file check detected that another task had rebuilt the v1.1 PDF. The design and simulator execution were prospective, but the v1 result remains failed and ineligible because that final integrity gate did not pass. Recovery protocol v2 reused the retained catalogs without simulator execution and wrote the complete retrospective reportable analysis. Verification amendment v3 corrects checkout-dependent newline hashing, validates the historical v1.1 PDF blob at the recovery registration commit, and passes 51/51 checks. It changes no estimand, metric, result, seed, model, adapter, or authority state and does not reclassify the v1 result as successful.

#### 4.8 Frozen gates, hashes, and non-promotion

Validation means checking an existing record against its schema, hashes, and gates. Recompute means deriving metrics again from committed rows or episode summaries without simulator execution. Rerun means executing the simulator or QEMU workload again. The verifiers distinguish these operations. SHA-256 establishes byte identity of named files, not scientific correctness; program logs establish only the events instrumented by those programs; and a verifier may share assumptions with its producer. Git commit timestamps provide externally hosted chronology after push, not proof that equivalent data were never observed elsewhere. Passing any study verifier does not imply deployment eligibility. Protected FerrumOS and Physical JEPA deployment digests must remain unchanged, and the study explicitly sets `promotion_eligible=false`.

### 5. Architecture-controlled results

#### 5.1 Domain-dependent ranking

Table 1 reports the error of the three-seed ensemble prediction defined in Section 4.3. Physical JEPA wins at every horizon. FerrumOS does not reproduce that ranking: the GRU is best at H=1 and H=3, while the JEPA is best at H=5. The registered pairwise intervals for the stated leaders exclude zero, conditional on the fixed trained checkpoints; Appendix D shows all seed members.

| Domain | Method | H=1 | H=3 | H=5 |
|---|---|---:|---:|---:|
| FerrumOS | Direct MLP | 0.004751 | 0.008431 | 0.007256 |
| FerrumOS | Action-conditioned JEPA | 0.009888 | 0.012356 | **0.005494** |
| FerrumOS | GRU dynamics | **0.004609** | **0.007917** | 0.006514 |
| Physical | Direct MLP | 0.007188 | 0.016836 | 0.026362 |
| Physical | Action-conditioned JEPA | **0.002476** | **0.006680** | **0.010465** |
| Physical | GRU dynamics | 0.010659 | 0.026231 | 0.039542 |

The physical MLP-minus-JEPA H=3 difference is 0.010156 with 95% interval [0.009829, 0.010483]. In FerrumOS, GRU-minus-JEPA at H=3 is -0.004439 [-0.005735, -0.003203], so the sign correctly favors the GRU. At H=5, JEPA-minus-GRU is -0.001020 [-0.001165, -0.000865]. These registered, horizon-specific contrasts are statistically separated under the stated resampling procedure, conditional on their eligible episode populations.

![Figure 3. Registered matched rollout errors for three model families. The FerrumOS horizon populations differ; the common-episode sensitivity is reported separately.](docs/research/figures/cross_domain_world_model/matched_rollout_results.png)

#### 5.2 Interpretation

The result closes data, parameter-count, and update-budget confounds that affected historical comparisons, but not FLOP or training-time differences. In the registered table, the tested three-member FerrumOS GRU ensemble leads at H=1 and H=3; this does not describe the mean individual checkpoint at H=1, where MLP is lower by only 0.000008. H=3 averages 318 eligible episodes, whereas H=5 averages 238 and excludes a source whose sequences are too short. Thus the registered ranking reversal cannot be isolated as a horizon effect: episode composition changes it. The original table and model selection remain unchanged.

Table 2 reports the complete post-hoc common-episode comparison. All estimates are three-member ensemble normalized errors on the same 238 FerrumOS episodes; lower is better. Contrast intervals are paired, unadjusted 10,000-resample 95% bootstrap intervals conditional on the fixed checkpoints and this episode population.

| Horizon | Direct MLP | JEPA | GRU | MLP - JEPA, paired 95% | JEPA - GRU, paired 95% |
|---|---:|---:|---:|---:|---:|
| H=1 | 0.002343 | **0.001018** | 0.002401 | +0.001325 [0.001295, 0.001356] | -0.001383 [-0.001408, -0.001358] |
| H=3 | 0.006709 | **0.005028** | 0.006147 | +0.001681 [0.001614, 0.001746] | -0.001119 [-0.001218, -0.001016] |
| H=5 | 0.007256 | **0.005494** | 0.006514 | +0.001763 [0.001646, 0.001874] | -0.001020 [-0.001164, -0.000871] |

JEPA has the lowest common-episode estimate at every horizon, and both displayed paired contrasts exclude zero. This post-hoc table changes the interpretation of the registered horizon-specific ranking; it does not replace the registered result or model selection.

The matched study also changes how the two earlier reports should be read. The Physical JEPA result can now be described as an architecture-controlled rollout advantage in its registered domain. The FerrumOS lineage cannot claim that a JEPA is the strongest general small dynamics model. Its stronger contribution is the mediation architecture, evidence discipline, and the request-bounded separation between prediction and authority.

### 6. Causal sensitivity, calibration, and operational value

#### 6.1 Paired temporal results

The selected FerrumOS GRU produces the correct counterfactual direction in 100.00% of pairs, ITE normalized MAE 0.002571, H=3 multi-action error 0.044558, and H=5 error 0.046720. The selected Physical JEPA reaches 93.36% directional accuracy, ITE normalized MAE 0.016819, H=3 error 0.026772, and H=5 error 0.046361.

| Domain | Selected model | Direction | ITE MAE | H=3 multi | H=5 multi |
|---|---|---:|---:|---:|---:|
| FerrumOS | GRU dynamics | 100.00% | 0.002571 | 0.044558 | 0.046720 |
| Physical | JEPA | 93.36% | 0.016819 | 0.026772 | 0.046361 |

Directional sensitivity establishes that the models do not merely reproduce a static current-state score. It does not establish calibrated hazard probability, adequate recall, or useful intervention. Multi-action errors are also substantially larger than the matched single-policy H=3 values in Table 1, which is consistent with a harder shifted temporal task.

#### 6.2 Calibration under shift

FerrumOS Brier and ECE are 0.249943 and 0.238143. Physical Brier and ECE are 0.229970 and 0.292887. Because each final catalog is balanced, the constant-prevalence predictor has Brier 0.25; FerrumOS is effectively at that baseline and Physical improves it modestly. ECE remains bin-dependent, and the registered risk-coverage curves are non-monotonic. These scores describe the shifted catalog and do not certify an error ordering or an operational probability.

The frozen 0.99 threshold was selected on 256 development cases per domain to match the rules-only FPR of zero, breaking ties by lower FNR and then higher threshold. Zero observed development FPs do not guarantee zero population FPR. No threshold is retuned after final access.

#### 6.3 Primary operational result

On each 512-case balanced final catalog, rules-only, learned-only, and union record TP=0, FP=0, TN=256, and FN=256 at threshold 0.99.

| Domain | Arm | TP | FP | TN | FN | Intervention |
|---|---|---:|---:|---:|---:|---:|
| FerrumOS | Rules only | 0 | 0 | 256 | 256 | 0% |
| FerrumOS | Learned only | 0 | 0 | 256 | 256 | 0% |
| FerrumOS | Rules + learned | 0 | 0 | 256 | 256 | 0% |
| Physical | Rules only | 0 | 0 | 256 | 256 | 0% |
| Physical | Learned only | 0 | 0 | 256 | 256 | 0% |
| Physical | Rules + learned | 0 | 0 | 256 | 256 | 0% |

For each domain, the learned branch produces 0/256 marginal interventions on dangerous cases and 0/256 on safe cases. The two-sided Wilson 95% upper bound for either zero-observed marginal intervention rate is 1.478%. That quantity is not a miss-rate bound: the observed false-negative rate is 256/256, with an approximate two-sided Wilson interval of [98.52%, 100.00%]. The 5,000-pair bootstrap interval for the observed marginal difference is exactly [0, 0] because every paired value is zero. All eight final families are delayed, coupled, masked, or exogenous: danger materializes later, while the deterministic predicates inspect current state and action. `rule_block` is false in all 1,024 records by construction of this estimand, so rules-only recall is not a general rule-quality estimate. The learned branch likewise does not extend the authority boundary at the zero-FP-calibrated threshold. This is a thresholded latent-hazard coverage negative, and no final-set retuning or promotion follows.

![Figure 4. Predictive and causal evidence do not become operational learned value at the frozen threshold. The gap is measured rather than hidden by final-set retuning.](docs/research/figures/cross_domain_world_model/causal_vs_operational.png)

### 7. FerrumOS authority-separated runtime evidence

#### 7.1 Lineage and measurement boundaries

Three model objects must not be conflated. The architecture study trains approximately 100k-parameter research models solely for matched offline comparison. The QEMU runtime loads the earlier 193,229-parameter FerrumOS v3.4 encoder-plus-transition lineage. Physical experiments use the distinct frozen Physical JEPA v5 binary. No architecture-study checkpoint is silently substituted into either runtime.

| Evidence object | Model object | Clock and workload | Supported timing claim |
|---|---|---|---|
| Guest horizon probe | FerrumOS v3.4, one preview at a time | 1 kHz guest timer; 200 previews per horizon | 3 ms guest-reported p99 in that probe |
| Four-client saturation | Same serial QEMU daemon | Host WebSocket wall clock; 128 responses | 17.545 s batch wall time, about 7.30 responses/s; client median 8.45–8.83 s and p95 16.09–16.46 s |
| Natural-use sessions | Same mediation lineage | Guest cycle counters without calibrated frequency | Ordering and bounded counts only, not milliseconds |
| HAI NumPy batch | Physical JEPA v5 on host arrays | Host batch timing, 4096 rows | Microseconds per row, not control-loop latency |

These clocks and workloads are not directly comparable. The study has no synchronized decomposition of model compute, guest scheduling, serialization queueing, transport, and polling. “Serialized inference” is therefore a supported mechanism-level explanation for saturation, not a complete latency attribution.

#### 7.2 Shadow integration and contention

The v3.4 model is injected only into disposable appliance-disk copies and loaded by the actual ring-3 preview gate. The one-at-a-time probe reports 3 ms p99 at H=1 through H=5, zero retained heap growth, and 96/96 correlated command-class responses. The preview emits no execution record and the source disk remains byte-identical. Under four-client saturation, all 128 responses return without leakage, Jain fairness is 0.999937, disconnect isolation succeeds, and a replacement client completes. Execution RPC is unavailable with error −32601, and execution records and physical deliveries remain zero.

#### 7.3 Visible natural-use sessions

Three separately booted disposable guests produce 24 privacy-bounded rows: 18 reads execute, three writes await operator confirmation, and three deletes are blocked. Telemetry excludes prompts, arguments, paths, provider/model identifiers, and output text. This is short researcher-operated QEMU evidence, not production telemetry or independent user testing.

#### 7.4 Runtime interpretation

The supported claim is narrow: a learned preview runs inside the tested unprivileged mediation path while capability, confirmation, revision checks, and execution remain separate. The source tests in Section 3.4 exercise false-safe prediction, malformed artifacts, stale/replayed messages, capability denial, and actuator-disabled delivery. This establishes empirical enforcement for enumerated paths—not a formal proof of non-bypass and not evidence that every block improves safety.

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

The projection is fixed from 698,400 HAI train1–train3 rows and maps only eight available source channels into the 16-state representation; missing state dimensions retain registered constants. Test1 labels align at exact second resolution; test2 labels align positionally only after matching the source file's minute precision, with equal row counts and no shifting, interpolation, nearest-neighbor matching, fill, or imputation. Event labels and proxy commands are descriptive anomaly diagnostics, not equivalent to the model's maintenance/action ontology. The replay is therefore bounded external-stream compatibility evidence, not live Ferrum HIL, end-to-end safety validation, physical timing, actuator dynamics, contact recovery, or an independently tested emergency stop.

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
| Naive unshielded | 100.00% | 0.00% | — | — | 0.00% | 542 |
| Planner unshielded | 94.53% | 0.00% | — | — | 0.00% | **70** |
| Planner + rules | 94.53% | 0.00% | 0.00% | 0.00% | 0.00% | 70 |
| Planner + learned | **96.09%** | 1.86% | **95.62%** | 3.24% | 55.00% | 84 |
| Planner + rules + learned | **96.09%** | 1.86% | **95.62%** | 3.24% | 55.00% | 84 |

The union passes every registered joint-objective gate relative to the frozen benchmark criteria; these gates do not require superiority over the privileged planner: 96.09% completion, 1.86% effective intervention, 95.62% warning recall, 3.24% warning FPR, and 84.50% fewer hazard-cost events than the naive controller (542 to 84). Its effective action-change recall is 55.00% (88/160): warned dangerous proposals do not count as interventions when the tangent command is already identical to the planner command. Executed intervention precision is 23.04% (88/382): 294 of 382 changed commands occur on oracle-labelled non-dangerous trajectories. That low precision is mechanistically consistent with the observed planner-relative hazard-cost increase, but the design does not identify causality and the paired interval includes zero. Its episode-bootstrap 95% intervals are 92.19%-99.22% for completion, 1.18%-2.55% for intervention, 81.58%-100.00% for warning recall, and 2.19%-4.31% for warning FPR. No final rerun or recovery path was used.

Relative to the privileged planner, the union changes completion by +1.5625 percentage points (paired 10,000-resample episode-bootstrap 95% CI [-1.5625, 4.6875]) and realized hazard cost by +14 steps (95% CI [-22.025, 54.000]). Neither interval excludes zero, so the observed two-task gain and 14-step increase are descriptive rather than statistically stable at this sample size.

Attribution remains essential. The privileged planner alone reduces hazard cost from 542 to 70 (87.08%). Adding the learned tangent branch increases completion from 121/128 to 123/128 but increases hazard-cost events from 70 to 84 (plus 14). All 382 effective union interventions are learned-only because the high-closeness rule never changes a command on this final distribution. The adapter warns on 153/160 dangerous controller trajectories, while 88/160 receive a different command; the remaining warned cases already propose the saturated tangent-compatible turn. The benchmark therefore supports a passing naive-baseline runtime objective and a completion/cost tradeoff over the planner, not learned collision-avoidance superiority over privileged planning.

#### 8.5 Frozen risk-source attribution on fresh layouts

The v2 attribution opens seeds 8000-8127 once after committing every adapter, threshold, and simulator setting. The planner baseline records 122/128 completions, 116 hazard steps, and 7/128 hazardous episodes. Table 6 changes only the warning source; all rows retain the deterministic rule union and the same one-command tangent correction.

| Risk source | Completion | Effective recall | Intervention | Precision | Hazard steps | Hazardous episodes | Mean steps |
|---|---:|---:|---:|---:|---:|---:|---:|
| Full local + JEPA adapter | 94.53% | 47.53% | 2.16% | 24.27% | 129 | 8/128 | 186.1 |
| Local sensing, no JEPA | 93.75% | 46.62% | 1.66% | 31.71% | 132 | 8/128 | 184.1 |
| JEPA outputs only | 96.09% | 20.25% | 1.35% | 15.00% | 104 | 7/128 | 184.9 |
| Hazard closeness only | 94.53% | 51.08% | 2.63% | 22.83% | 144 | 9/128 | 184.5 |

JEPA-only versus full was a prospectively specified member of a four-pipeline family, but not the uniquely designated primary contrast. The original 95% intervals are pointwise and unadjusted, so confirmatory interpretation would be inappropriate. A registered post-hoc sensitivity controls a 5% familywise error rate across the three non-full-versus-full pipeline contrasts within each endpoint separately; it does not adjust jointly across every endpoint or comparison in the report. For JEPA-only minus full, the Bonferroni-adjusted 98.33% interval is [-57, -3] for a -25-step hazard contrast and [-1.58, -0.01] for a -0.81-point intervention contrast. Both exclude zero. Hazard steps improve/worsen/remain unchanged in 6/0/122 paired episodes; intervention counts are lower/higher/unchanged in 26/16/86. Every one of 128 leave-one-seed-out 95% intervals still excludes zero for both quantities (hazard endpoints across omissions [-51, -3]; intervention endpoints [-1.52, -0.07]). These leave-one-out checks are sensitivity analyses, not independent replications. Its +1.56-point completion contrast has pointwise CI [0.00, 3.91], which shows no statistically resolved difference and is not a non-inferiority result. Against the unshielded planner, JEPA-only changes hazard cost by -12 steps with CI [-39, 4], so superiority to the planner is not established.

The original warning metrics are on-policy: each pipeline changes actions and therefore changes the states and proposals it later visits. Keeping the oracle logic fixed does not keep the evaluation population fixed. Table 7 reports both those on-policy values and a direct post-hoc detector comparison on the identical 23,815-proposal catalog visited by the full pipeline. The common catalog contains 263 dangerous and 23,552 safe proposals and reproduces the full arm exactly; it remains conditional on full-arm visitation and is not an independent sample.

| Risk source | Validation FPR | Final on-policy recall | Final on-policy FPR | Common recall | Common FPR |
|---|---:|---:|---:|---:|---:|
| Full local + JEPA | 0.40% | 92.40% | 3.35% | 92.40% | 3.35% |
| Local, no JEPA | 0.37% | 90.60% | 2.53% | 90.49% | 2.41% |
| JEPA outputs only | 0.43% | 57.81% | 2.66% | 51.71% | 2.90% |
| Hazard closeness | 0.37% | 80.58% | 2.64% | 79.85% | 2.32% |

Warning recall and realized outcomes rank differently: full has higher 20-step dangerous-trajectory warning recall, while JEPA-only intervenes less and records fewer realized hazard steps. The finding is exploratory pipeline-level evidence for a lower-intervention operating point under this fixed correction design. It does not isolate JEPA architecture, prove detector superiority on an independently sampled population, establish preserved completion, or establish safety superiority. The failed v1 attribution attempt and its excluded 7000-range partial catalog remain archived.

#### 8.6 Retained-catalog Physical JEPA output-value ablation

The output-value ablation compares the same frozen model, adapter, operating threshold, planner, correction, and 128 seeds under two feature interventions. `observed-frozen-jepa` uses the three observed frozen JEPA outputs. `development-mean-masked-jepa` replaces only those values with the preregistered development means immediately before the unchanged adapter score. The observed arm completes 118/128 episodes with 173 hazard steps; the masked arm completes 119/128 with 183 hazard steps. The observed and masked catalogs contain 25,497 and 25,389 proposal rows respectively, so proposal-rate metrics are computed within arm while the uncertainty analysis pairs episodes by seed.

| Observed minus development-mean masked | Estimate | Pointwise paired bootstrap 95% CI | Pointwise conclusion |
|---|---:|---:|---|
| Task completion, percentage points | -0.78125 | [-2.34375, 0.00000] | Includes zero |
| Warning recall, percentage points | +3.02959 | [-6.09578, 12.20268] | Includes zero |
| Warning FPR, percentage points | +1.66982 | [0.95734, 2.47918] | Excludes zero |
| Effective intervention recall, percentage points | +0.50818 | [-4.41887, 4.50930] | Includes zero |
| Intervention rate, percentage points | +0.96180 | [0.58641, 1.38473] | Excludes zero |
| Intervention precision, percentage points | -15.25735 | [-29.32521, -3.00212] | Excludes zero |
| Realized hazard-cost steps | -10 | [-98, 59] | Includes zero |

The seven displayed endpoints form the report-level multiplicity family. Applying Bonferroni control at 5% familywise error to the same 10,000 paired resamples uses two-sided 0.003571 and 0.996429 quantiles, or 99.29% intervals:

| Observed minus development-mean masked | Bonferroni-adjusted 99.29% CI | Adjusted conclusion |
|---|---:|---|
| Task completion | [-3.12500, 0.00000] | Includes zero |
| Warning recall | [-11.25330, 18.18255] | Includes zero |
| Warning FPR | **[0.78468, 2.81866]** | **Excludes zero** |
| Effective intervention recall | [-7.62912, 6.22118] | Includes zero |
| Intervention rate | **[0.47780, 1.57510]** | **Excludes zero** |
| Intervention precision | [-34.86661, 1.35705] | Includes zero |
| Realized hazard-cost steps | [-134, 81] | Includes zero |

Observed JEPA output values therefore produce more false-positive warnings and more effective action changes in this fixed closed-loop software pipeline. Warning FPR and intervention rate remain separated from zero after adjustment, and neither is evidence of benefit. The lower precision appears only in the pointwise analysis; its adjusted interval includes zero. Completion, warning recall, effective recall, and realized hazard cost remain unresolved. The -10 observed hazard-step estimate is especially not a superiority result because its interval is wide and includes zero. As a stricter family-definition audit, adjustment across all 11 registered paired outputs gives the same survivor set: warning FPR [0.73638, 2.89725] and intervention rate [0.45556, 1.59936].

These tables report a retrospectively recovered analysis of complete catalogs produced by a prospectively specified and executed experiment that failed its final protected-file check. The failed v1 result remains ineligible; recovery v2 did not rerun the simulator; verification v3 recomputes the catalogs, scores, aggregates, paired effects, seeds, and feature intervention and passes all 51 checks. The multiplicity sensitivity is post-hoc and changes no registered endpoint, seed, or bootstrap replicate. The evidence supports only the direct effect of observed-versus-masked output values in this fixed local pipeline. It does not provide a successful prospective result, architecture-wide causality, independent assessment, HIL, physical safety, deployment safety, or promotion eligibility.

### 9. Cross-domain synthesis

#### 9.1 Prediction quality is domain-specific

The registered table rejects a universal architecture story. Physical dynamics favor the tested three-member JEPA ensemble at all horizons. FerrumOS favors the tested three-member GRU ensemble at H=1 and H=3, with JEPA leading at H=5; however, the common-H5-eligible episode sensitivity favors JEPA at every horizon. The apparent FerrumOS reversal is therefore composition-sensitive and cannot be isolated as a horizon effect. This makes architecture selection an empirical, estimand-specific decision rather than a model-family claim.

#### 9.2 Causal response is not calibrated authority

Both selected models react to paired interventions in the intended direction. Neither generates an operational intervention at the conservative frozen threshold on the shifted final catalogs. These findings are compatible: a model can encode direction and approximate magnitude while its calibrated score lacks separation at a chosen false-positive constraint. Reporting only rollout or directional accuracy would conceal the actual decision failure.

#### 9.3 Deterministic authority can fail differently

The new 512-case catalogs show no interventions from either rules or learning, while the 3D stress intervenes on every case. The prospective Safety-Gymnasium result separates a useful privileged planner-only controller from an active union that passes the naive-baseline objective but trades higher completion for higher hazard cost relative to the planner. The retained-catalog output intervention then shows that observed JEPA values increase warning FPR and intervention rate under both pointwise and multiplicity-adjusted intervals. Precision decreases only pointwise; its seven-endpoint adjusted interval includes zero, as do completion and realized hazard cost. These contrasts show why controller quality cannot be credited to a shield and why warning recall or intervention count cannot substitute for marginal executed outcomes. Deterministic authority must be evaluated with task completion, intervention, proposal recall, false positives, precision, realized cost, and controller divergence rather than a collision count alone.

#### 9.4 Evidence ladders prevent category errors

QEMU timing is not production throughput. Researcher-operated sessions are not independent user evidence. Recorded sensors are not live HIL. PyBullet contact is not physical collision evidence. An externally maintained simulator task executed by the author is not an independent replication, and a planner with direct simulator geometry is not a sensor-only robot controller. A publisher-heldout robotics file is not compatible merely because it contains robot telemetry. Labelling those boundaries does not weaken the contribution; it makes the evidence composable and reproducible.

#### 9.5 Novelty statement

This work does not claim the first JEPA world model, safety filter, calibrated predictor, or runtime-assurance architecture. Its central novelty is an executable evaluation method with named estimands and named failure modes: prediction error, counterfactual response, calibration, warnings, effective interventions, realized outcomes, and authority are registered and reviewed separately. Applying that method in two domains exposes a composition-sensitive registered ranking, a thresholded latent-hazard zero, an all-stop policy, a planner-dominated result, and a risk-source attribution that warning recall alone would conceal. The cross-domain claim is methodological replication across distinct systems, not learned representation or policy transfer.

### 10. Threats to validity and limitations

1. The temporal catalogs and PyBullet stress use locally designed deterministic labels. Safety-Gymnasium improves task provenance, but adapter design, execution, and assessment remain local; no independent replication is claimed.

2. The architecture study matches data, seeds, parameters, and updates, not FLOPs or training wall time. Its episode bootstrap conditions on fixed trained checkpoints and omits retraining variability. Registered horizon populations differ; the common-episode post-hoc sensitivity changes the FerrumOS ranking, so the registered reversal cannot be isolated as a horizon effect.

3. The attribution varies complete risk-source pipelines, not architecture alone. JEPA-only retains a historically trained v5 artifact, so its lower hazard count cannot be attributed purely to a JEPA objective. JEPA-only versus full was one prospectively specified family member, not a unique primary contrast. The Bonferroni sensitivity is familywise across three non-full-versus-full pipeline contrasts within each endpoint, not across every endpoint or comparison; the leave-one-out checks are sensitivity analyses, not independent replications.

4. Calibration is weak under shift. The constant-prevalence Brier baseline is 0.25, ECE is bin-dependent, and risk-coverage ordering is non-monotonic. Zero observed false positives are not a population guarantee.

5. The 512-case families place danger beyond present-state rules by construction. Their rules-only zero is catalog coverage, not general rule quality; the [0,0] bootstrap reflects an all-zero observed vector.

6. FerrumOS runtime evidence uses QEMU/WHPX, one serial daemon, four local clients, and 24 requests from one researcher. No production, multi-host, independent-user, or long-duration evidence exists.

7. Timing uses different clocks and workloads. No synchronized model/queue/transport/polling decomposition or calibrated natural-use cycle conversion is available.

8. The HAI replay projects eight recorded channels into a 16-state representation using frozen training statistics. Labels and proxy actions are not equivalent to the model ontology; it is replay, not live HIL.

9. Anchor-Lab telemetry is externally authored but semantically incompatible with direct v5 scoring. It supports future embodiment-specific work, not present-model transfer.

10. The PyBullet environment is locally designed and simple. Its 100% intervention and 0% completion remain a negative stress result, not useful collision avoidance.

11. The strongest Safety-Gymnasium controller uses privileged simulator geometry. Planner effects must not be credited to the shield, and the fixed rule's inactivity is distribution-specific.

12. Warning recall uses a 20-step nominal-controller oracle. It is dangerous-trajectory warning recall, not a generic system-safety metric; effective action recall and realized cost are separate. Original arm values are on-policy and therefore use different visited proposals. The common-proposal check is conditional on the full-arm catalog, not an independently sampled detector benchmark.

13. The output-value ablation's design, estimands, fresh seed range, and bootstrap seeds were registered before either catalog existed, and both catalogs completed during the prospective v1 execution. Its result nevertheless failed eligibility because an unrelated concurrent rebuild changed a protected report PDF before the final integrity check. Recovery v2 is a subsequently registered retrospective reportable analysis of those retained catalogs, not a successful prospective result or rerun. The seven-endpoint and stricter 11-output multiplicity sensitivities are post-hoc. All paired estimates remain conditional on the fixed seed set, planner, correction, threshold, and local simulator pipeline; the intervention does not isolate architecture or establish benefit.

14. Source tests cover enumerated protocol, daemon, and physical-runtime paths. Deterministic predicates are engineering rules, not formally verified invariants, and empirical tests do not prove universal non-bypass.

15. There is no live actuator timing, physical contact, hardware emergency stop, human-contact dynamics, or independent execution. All research artifacts remain ineligible for promotion and protected deployed artifacts are unchanged.

### 11. Reproducibility and artifact integrity

Every evidence object names its scope and digest. Hashes prove byte identity only; they do not validate labels, scientific assumptions, or instrument completeness. Result producers and verifiers share repository code in places, so independent replication remains a higher evidence tier. The report uses three distinct verbs: **validate** an existing record and gates; **recompute** metrics from committed rows without environment execution; and **rerun** the registered environment or QEMU workload. Commands below are labelled accordingly.

The architecture and post-hoc analysis record Python 3.12.6, NumPy 2.2.6, and PyTorch 2.6.0+cu124 on Windows; `requirements-research.txt` pins the remaining analysis and PDF packages. Safety-Gymnasium uses its separate locked environment: Python 3.10.20, Safety-Gymnasium 1.0.0, Gymnasium 0.28.1, Gymnasium-Robotics 1.2.2, MuJoCo 2.3.3, NumPy 1.23.5, and pygame 2.1.0. Protocols bind simulator source trees, checkpoints, catalogs, and results. Wall time is machine-dependent; the post-hoc verifier performs checkpoint inference and 10,000-resample analyses without launching the simulator.

The exact pre-report scientific-evidence snapshot for this review freeze is Git commit `6a6da0a2dd1a352df5c929ee1e93831b29640acd`. A short headline-table audit is: run the umbrella verifier, run the post-hoc verifier, run the portable output-ablation verifier, then run the paper verifier. These validate or recompute committed evidence; they do not rerun a final simulator catalog.

```powershell
# Recompute or validate committed evidence; no new final simulator execution
python scripts/verify_cross_domain_world_models.py
python scripts/verify_cross_domain_learned_contribution.py
python scripts/verify_cross_domain_world_model_posthoc_sensitivity_v1.py
python scripts/verify_physical_jepa_safety_gymnasium_v14.py
python scripts/verify_physical_jepa_safety_gymnasium_paired_uncertainty.py
target\safety-gymnasium-venv\Scripts\python.exe scripts/verify_physical_jepa_safety_gymnasium_attribution_v1.py
target\safety-gymnasium-venv\Scripts\python.exe scripts/verify_physical_jepa_safety_gymnasium_output_ablation_recovery_v3.py
python scripts/verify_cross_domain_world_model_improvement_study.py
python scripts/verify_cross_domain_world_model_paper_v1_2.py
cargo test --manifest-path userland/neural-protocol/Cargo.toml --target x86_64-pc-windows-msvc
cargo test --manifest-path userland/physical-runtime/Cargo.toml --target x86_64-pc-windows-msvc

# Rerun only under a new prospective protocol and output paths
# node scripts/verify_world_model_combined_gate.mjs
# target\safety-gymnasium-venv\Scripts\python.exe scripts/evaluate_physical_jepa_safety_gymnasium_attribution_v1.py
```

The attribution verifier recomputes every aggregate from 128 per-seed summaries, checks all four compressed row catalogs, exact seed membership, 10,000 paired resamples, adapter/protocol digests, locked runtime source, zero actuator authority, and non-promotion. The output-ablation v3 verifier performs the analogous retained-catalog recomputation for both arms and 51 provenance, toolchain, authority, and interpretation checks without simulator execution; it validates the historical report blob at the recovery registration commit rather than treating later report versions as experimental drift. The post-hoc verifier independently reconstructs the common-episode rollouts, adjusted intervals, leave-one-out results, and common-proposal scores. The authority inventory records 9/9 neural-protocol and 128/128 physical-runtime tests while distinguishing them from QEMU evidence. The paper verifier recomputes the seven-endpoint and 11-output Bonferroni sensitivities and checks required claim boundaries, PDF metadata, figures, tables, page count, source/PDF digests, and the evidence snapshot.

### 12. Conclusion

The paper's strongest result is methodological. A world model can lead a matched rollout table, respond directionally to interventions, fail at a frozen operational threshold, and still remain correctly subordinate to policy and capability. The same evaluation method reveals a horizon-composition-sensitive architecture ranking in FerrumOS, a zero-coverage latent-hazard estimand, an all-stop PyBullet policy, planner-dominated Safety-Gymnasium outcomes, an exploratory risk-source comparison, and a retained-catalog output intervention in which observed JEPA values increase warning FPR and intervention rate under both pointwise and multiplicity-adjusted intervals. Precision decreases only pointwise, while completion and realized hazard cost remain unresolved.

The defensible claim is not that FerrumOS or Physical JEPA is safe. It is that predictive evidence, warning quality, effective action changes, realized outcomes, and authority can be measured as separate objects with frozen access boundaries and retained failures. Deterministic blocking is empirically monotone on tested paths, but monotonicity is not benefit; capability, confirmation, revision checks, and actuator denial remain independently necessary. No protected artifact is promoted.

#### 12.1 Submission scope

The appropriate venue identity is cyber-physical systems, runtime assurance, dependable agents, or evaluation methodology. Cross-domain means the method is exercised separately in an agentic OS and a physical-runtime simulation—not that one model transfers between them. The absence of live hardware and independent execution excludes robotics-deployment claims.

#### 12.2 Remaining evidence tier

The targeted local attribution, its registered post-hoc sensitivity checks, and the retrospectively recovered output-value analysis are complete. The output-ablation design and simulator execution were prospective, but its v1 result failed the final integrity gate; the recovered estimates are therefore not a successful prospective result. Repeating that evidence class would require a newly registered untouched seed range rather than relabelling the recovery. The higher-value evidence-class changes remain independent execution of a frozen controller/shield benchmark, actuator-disabled live HIL with physical clocks and interfaces, and externally controlled labels or assessment. For FerrumOS, independently operated longitudinal use and concurrent preview remain higher value than more synthetic prompts.

#### 12.3 Release rule

Technical Report v1.2 is the prepublication evidence-changing successor to v1.1. Version 1.1 and its repository tag remain intact; v1.2 adds the retained-catalog output-value evidence and the associated provenance boundary. Until v1.2 is published or tagged, review-driven corrections replace the previous private candidate and refresh its freeze manifest. Publication or tagging makes that source, PDF, verifier, and manifest immutable; later evidence-changing work must then create a new report version and retain failed frozen results. Promotion requires a separate prospective deployment protocol naming exact targets, rollback, capabilities, post-execution verification, and gates. Publication of this report is not that protocol.

### Appendix A. Claim-to-evidence ledger

This ledger is part of the report rather than a supplementary marketing summary. It identifies the evidence object that supports each major statement and the closest claim that the same object does not support. The purpose is to make category errors visible during review.

| Claim | Primary evidence | Supported result | Explicit exclusion |
|---|---|---|---|
| Physical JEPA leads matched alternatives | Shared frozen physical final catalog | Lowest H=1, H=3, H=5 rollout error; paired intervals exclude zero | Not universal JEPA superiority |
| FerrumOS registered ranking differs | Horizon-specific FerrumOS endpoints plus common-episode sensitivity | GRU ensemble leads registered H=1/H=3; JEPA leads all common-episode horizons | Ranking reversal is not isolated from episode composition |
| Selected models encode interventions | Paired temporal counterfactual catalogs | 100.00% and 93.36% directional accuracy | Not calibrated hazard recall |
| Shifted scores are weakly calibrated | Frozen reliability, Brier, and ECE outputs | ECE 0.238143 and 0.292887 | Not a formal probability guarantee |
| Learned marginal caution is evaluated | Three-arm 512-case catalogs | Zero marginal blocks at threshold 0.99 | No learned safety-value claim |
| Runtime preview is integrated | FerrumOS QEMU ring-3 shadow path | H=1-H=5 p99 guest time 3 ms | Not production or hard real-time timing |
| Multiple clients remain correlated and isolated | Four WebSocket clients, 128 responses | No leakage; Jain fairness 0.999937 | Not parallel inference or distributed execution |
| Visible assistant mediation works in bounded sessions | Three QEMU boots, 24 requests | Reads execute; writes await confirmation; deletes block | Not independent users or production telemetry |
| External physical streams can be replayed | 284,398 HAI transitions | Fault-condition error and event diagnostics | Not live Ferrum HIL or physical recovery |
| Anchor-Lab adds external embodiment data | Six publisher files, 2,925,558 rows | Timing and command/state fields are finite | Not semantically valid for direct v5 scoring |
| 3D geometry/contact stress is exercised | 288 local PyBullet DIRECT cases | Contact and simulated recovery are measured | Not practical learned safety at 100% intervention |
| Controller and shield are jointly evaluated | Safety-Gymnasium final seeds 6000-6127 | Planner-only explains most cost reduction; union passes naive-baseline gates; no statistically resolved planner difference in completion or cost | Not independent, sensor-only, physical, or learned-superiority evidence |
| Risk-source pipelines are compared | Frozen attribution seeds 8000-8127 | Exploratory JEPA-only versus full: -25 hazard steps and -0.81 intervention points; adjusted and leave-one-out intervals exclude zero | Not architecture-only causality, preserved completion, or superiority to planner |
| Observed JEPA output values are intervened on | Prospectively specified experiment; complete retained paired catalogs, seeds 9000-9127 | Warning FPR +1.67 and intervention +0.96 points survive seven-endpoint and 11-output Bonferroni checks; precision -15.26 points is pointwise only; completion and hazard intervals include zero | Recovered result is retrospective; not architecture-wide causality, successful prospective evidence, or benefit |
| Deployment stayed unchanged | Recomputed protected SHA-256 digests | Every protected artifact is byte-identical | Not a deployment or release result |

#### A.1 Evidence precedence

When two measurements appear to support different narratives, the operationally closer measurement takes precedence for the operational claim. For example, the physical JEPA's rollout advantage remains valid even though its learned-only intervention count is zero. The former supports dynamics prediction; the latter controls any statement about safety-gate value at threshold 0.99. Likewise, zero union contacts in the 3D run does not supersede 0% task completion and 100% intervention. The complete outcome vector is the result.

#### A.2 Negative-result taxonomy

The study distinguishes several types of negative evidence. A scientific negative is a completed comparison whose registered estimand does not support the hoped-for effect, as in zero learned marginal caution. A gate pass can still contain a negative marginal contrast, as v14 does when the union improves completion but worsens hazard cost relative to the planner. An engineering negative is a system behavior that is measurable but unusable, as in serial multi-client latency or the all-stop 3D policy. A compatibility negative occurs before model scoring when external data do not share the required semantics, as with Anchor-Lab. A failed result is different: the output-ablation design and simulator execution were prospective and its catalogs completed, but the final protected-file check failed, so only the subsequently registered v2 recovery may report them as retrospective estimates. These categories must not be rewritten as missing data or collapsed into a successful prospective result.


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
| Registered sensitivity v1 | Common episodes/proposals, three-comparison family, 128 omissions | Exact recomputation, adjusted intervals, and source-arm reproduction pass | No simulator, retraining, threshold change, or promotion |
| Output-ablation v1 execution | Two feature interventions, seeds 9000-9127, estimands, and bootstrap seeds fixed pre-catalog | Both prospectively executed catalogs complete; final protected-report digest check fails | Prospective result ineligible; failure retained |
| Output-ablation recovery v2 / verification v3 | Retained catalog digests and unchanged estimands | 51/51 checks pass; aggregates, scores, features, seeds, and paired effects recompute | Retrospective reportable analysis only; no simulator rerun, result reclassification, or promotion |
| Paper freeze | Required claims, boundaries, figures, metadata | Text, hashes, pages, evidence snapshot pass | Documentation artifacts only |

#### B.1 Protocol and amendment chronology

Hosted Git history timestamps the registered files after commit; it does not prove absence of any earlier equivalent observation. The table is an audit index, not a claim that every stage was scientifically successful.

| Stage | Registration commit / time (IST) | Frozen change | Outcome |
|---|---|---|---|
| Safety-Gym v1–v4 | `383e525`–`f9d1a52`, 30 Aug 17:32–19:24 | Initial recovery, new final ranges, realized-cost gate | v1 selection failed; v3 final failed; v4 retained mixed record |
| Safety-Gym v5–v8 | `5a2a07c`–`2ae1502`, 30–31 Aug | Earlier warning, bounded steering, braking, adaptive exit | Development failures; no promoted final |
| Safety-Gym v9–v13 | `22f9774`–`4f62544`, 31 Aug | Privileged planner factorization, tangent correction, recall repair, Simplex trial | v10/v12 finals failed; v13 failed development |
| Safety-Gym v14 | `bcca0b6`, 1 Sep 23:21 | Synchronized 20-step nominal oracle and corrected cost accounting | One final pass against naive-baseline gates; planner-relative tradeoff retained |
| Attribution v1 | `df58e72`, 5 Sep | Four fixed risk sources, seeds 7000–7127 | Schema failure after two stages; partial catalog retained and excluded |
| Attribution v2 | `e954a2c`, 5 Sep | Threshold alias only; new seeds 8000-8127 | Completed once; all evidence checks pass; no promotion |
| Post-hoc sensitivity v1 | `cd5e9b6`-`da32691`, 8 Sep | Common episodes/proposals, multiplicity, paired directions, leave-one-out | Exact recomputation passes; no simulator, retraining, or promotion |
| Output ablation v1 | `6f70724`, 8 Sep | Observed frozen JEPA values versus preregistered development-mean masking; estimands, seeds 9000-9127, and bootstrap seeds fixed pre-catalog | Both catalogs completed prospectively; protected-report digest check failed; prospective result ineligible |
| Output recovery v2 | `c47b8ba`, 8 Sep | Analysis-only reuse of complete retained paired catalogs | Retrospective estimates written; no simulator rerun or prospective reclassification |
| Output verification v3 | `9cd2c0a`-`6a6da0a`, 8 Sep | Portable text-digest rule and historical report-blob validation | 51/51 checks pass in current and clean Windows checkouts; evidence values unchanged |

#### B.2 Protected deployment inventory

The umbrella record protects four deployed objects: the FerrumOS encoder, FerrumOS transition, FerrumOS manifest, and Physical JEPA transition. Their observed digests equal their registered expected digests. Architecture checkpoints, adapters, catalogs, replay projections, and simulator results remain research artifacts. A passing verifier cannot change that status.

#### B.3 Reproduction order

A reviewer can begin with `verify_cross_domain_world_model_improvement_study.py`, which checks the original subordinate verification records and protected digests. For deeper inspection, the architecture and learned-contribution verifiers expose selection-access logs and final-open accounting; runtime verifiers expose no-execution and source-disk checks; physical verifiers expose actuator-authority counters and result attribution. Run `verify_physical_jepa_safety_gymnasium_output_ablation_recovery_v3.py` separately because the output ablation postdates the original umbrella record; it validates the recovery record, historical report blob, both retained catalogs, and all paired effects without simulator execution. The final v1.2 paper verifier then checks that the manuscript says what the evidence permits, not merely that a PDF exists.

#### B.4 Archival boundary

Technical Report v1.2 is intended to be archived together with its manuscript, figures, paper verification record, and freeze manifest while v1.1 remains separately retrievable. Dataset or software records may receive their own archival identifiers because they are independently reusable objects. Reciprocal links should identify the exact immutable report version and the exact dataset or software version without implying that a repository's moving branch is itself frozen. The DOI fields are intentionally not invented in this pre-archive build; they can be added only after the archival service reserves or publishes the corresponding identifiers.


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
| Risk-source attribution protocol | `docs/research/physical_jepa_safety_gymnasium_attribution_protocol_v2.json` | Inspect fixed factors, thresholds, recovery, and fresh seed boundary |
| Risk-source attribution result | `docs/research/physical_jepa_safety_gymnasium_attribution_result_v2.json` | Recompute four pipeline arms, episode statistics, and paired differences |
| Risk-source attribution verification | `docs/research/physical_jepa_safety_gymnasium_attribution_verification_v2.json` | Confirm row catalogs, seed sets, digests, runtime, authority, and non-promotion |
| Registered post-hoc sensitivity | `docs/research/cross_domain_world_model_posthoc_sensitivity_result_v1.json` | Common episodes, common proposals, adjusted intervals, paired directions, and leave-one-out checks |
| Post-hoc sensitivity verification | `docs/research/cross_domain_world_model_posthoc_sensitivity_verification_v1.json` | Exact independent recomputation without simulator execution |
| Output-ablation failed attempt | `docs/research/physical_jepa_safety_gymnasium_output_ablation_failed_attempt_v1.json` | Confirm prospective v1 failure, complete catalog retention, and result ineligibility |
| Output-ablation recovery protocol | `docs/research/physical_jepa_safety_gymnasium_output_ablation_recovery_protocol_v2.json` | Inspect the subsequently registered analysis-only recovery boundary |
| Output-ablation recovery result | `docs/research/physical_jepa_safety_gymnasium_output_ablation_recovery_result_v2.json` | Recompute observed-versus-masked aggregates and paired intervals from retained catalogs |
| Output-ablation verification amendment | `docs/research/physical_jepa_safety_gymnasium_output_ablation_verification_amendment_v3.json` | Inspect the portable digest and historical report-blob verification policy |
| Output-ablation recovery verification | `docs/research/physical_jepa_safety_gymnasium_output_ablation_recovery_verification_v3.json` | Confirm 51/51 checks, failed-v1 interpretation, authority zero, and non-promotion |
| Authority test inventory | `docs/research/cross_domain_authority_test_inventory_v1.json` | Map component, test class, committed pass, and execution availability |
| Umbrella verification | `docs/research/cross_domain_world_model_improvement_verification_v1.json` | Confirm subordinate passes, claim boundaries and protected hashes |
| Narrative study | `docs/research/CROSS_DOMAIN_WORLD_MODEL_IMPROVEMENT_STUDY.md` | Read the compact evidence-first study before this full report |

#### C.1 Recommended audit path

Begin with the prospective protocol and umbrella verification. Confirm `promotion_eligible=false`, all protected `unchanged` fields, and the claim-boundary list. Then inspect the architecture and learned-contribution results together: this prevents a favorable rollout table from being detached from the operational zero-result. Continue to the runtime and physical records only for the integration claims they support. In the Safety-Gymnasium evidence, compare all five arms and planner divergence before attributing any outcome to the learned branch. For the output ablation, read the failed v1 record before the recovery result and require the v3 verification interpretation to remain retrospective. Finally, execute the v1.2 paper verifier and compare its recorded manuscript and PDF digests with the archived files.

#### C.2 Versioning rule

The report version identifies a fixed document, not a promise that every moving repository file will remain identical forever. Version 1.2 is evidence-changing because it binds the retained-catalog output ablation; it does not mutate or supersede the evidentiary status of v1.1. Corrections that alter prose, evidence binding, or layout should create a new immutable report version and retain the old version in archival history. Dataset and software deposits should use their own versioned records when they are independently reusable. A concept DOI may identify the evolving record, while the paper should cite the immutable version DOI used during review.


### Appendix D. Seed-level architecture results

Each cell reports H=1/H=3/H=5 normalized endpoint error for one independently initialized checkpoint. Table 1 instead reports error after averaging the three state predictions. These seed results show training variability; the paper's episode bootstrap does not resample this training process.

| Domain | Method | Seed 17 | Seed 43 | Seed 101 |
|---|---|---:|---:|---:|
| FerrumOS | Direct MLP | 0.006589 / 0.011355 / 0.010724 | 0.006766 / 0.010380 / 0.008943 | 0.005904 / 0.009543 / 0.008113 |
| FerrumOS | Action-conditioned JEPA | 0.011977 / 0.014114 / 0.006823 | 0.011571 / 0.015009 / 0.006900 | 0.012893 / 0.015745 / 0.007215 |
| FerrumOS | GRU dynamics | 0.006254 / 0.009522 / 0.008289 | 0.006649 / 0.010079 / 0.009221 | 0.006380 / 0.009540 / 0.007955 |
| Physical | Direct MLP | 0.008923 / 0.022246 / 0.035243 | 0.008352 / 0.019819 / 0.031014 | 0.007903 / 0.018208 / 0.028402 |
| Physical | Action-conditioned JEPA | 0.002967 / 0.007682 / 0.011869 | 0.003056 / 0.008098 / 0.012635 | 0.003017 / 0.007989 / 0.012481 |
| Physical | GRU dynamics | 0.013441 / 0.032976 / 0.049582 | 0.012091 / 0.028457 / 0.041401 | 0.012486 / 0.032275 / 0.050767 |

<!-- PAGE BREAK -->

### References

[1] A. Bardes, Q. Garrido, J. Ponce, X. Chen, M. Rabbat, Y. LeCun, M. Assran, and N. Ballas. "Revisiting Feature Prediction for Learning Visual Representations from Video." arXiv:2404.08471, 2024. https://arxiv.org/abs/2404.08471

[2] A. Bardes et al. "V-JEPA 2: Self-Supervised Video Models Enable Understanding, Prediction and Planning." arXiv:2506.09985, 2025. https://arxiv.org/abs/2506.09985

[3] G. Zhou et al. "DINO-WM: World Models on Pre-trained Visual Features enable Zero-shot Planning." arXiv:2411.04983, 2024. https://arxiv.org/abs/2411.04983

[4] T. Xie et al. "OSWorld: Benchmarking Multimodal Agents for Open-Ended Tasks in Real Computer Environments." arXiv:2404.07972, 2024. https://arxiv.org/abs/2404.07972

[5] D. Seto, B. Krogh, L. Sha, and A. Chutinan. "The Simplex Architecture for Safe Online Control System Upgrades." Proceedings of the American Control Conference, 1998.

[6] D. T. Phan et al. "Neural Simplex Architecture." NASA Formal Methods, LNCS 12229, 2020. https://doi.org/10.1007/978-3-030-55754-6_6

[7] U. Mehmood et al. "The Black-Box Simplex Architecture for Runtime Assurance of Autonomous CPS." NASA Formal Methods, LNCS 13260, 2022. https://doi.org/10.1007/978-3-031-06773-0_12

[8] J. T. Slagel, L. M. White, A. Dutle, C. Muñoz, and N. Crespo. "A Formal Verification Framework for Runtime Assurance." NASA Formal Methods, LNCS 14627, pp. 322–328, 2024. https://doi.org/10.1007/978-3-031-60698-4_19

[9] J. T. Slagel, L. M. White, A. Dutle, C. Muñoz, and N. Crespo. "A Verification Framework for Runtime Assurance of Autonomous UAS." 43rd Digital Avionics Systems Conference, 2024. https://shemesh.larc.nasa.gov/fm/plaidypvs/

[10] L. Yang, B. Werner, R. K. Cosner, D. Fridovich-Keil, P. Culbertson, and A. D. Ames. "SHIELD: Safety on Humanoids via CBFs In Expectation on Learned Dynamics." arXiv:2505.11494, 2025. https://arxiv.org/abs/2505.11494

[11] K. Zhong, T. Liu, and Y. Wang. "Calibrated Predictive Safety for Heterogeneous Robots: An Action-Conditioned JEPA Framework with Model-Based Safety Shields." arXiv:2608.17496, 2026. https://arxiv.org/abs/2608.17496

[12] C. Guo, G. Pleiss, Y. Sun, and K. Q. Weinberger. "On Calibration of Modern Neural Networks." Proceedings of ICML, 2017. https://proceedings.mlr.press/v70/guo17a.html

[13] G. W. Brier. "Verification of Forecasts Expressed in Terms of Probability." Monthly Weather Review 78(1), 1950. https://doi.org/10.1175/1520-0493(1950)078%3C0001:VOFEIT%3E2.0.CO;2

[14] E. Coumans and Y. Bai. "PyBullet, a Python Module for Physics Simulation for Games, Robotics and Machine Learning." 2016-2021. https://pybullet.org

[15] Vyom Kulshrestha. "When Agents Control the Kernel: A JEPA World Model Safety Gate with Empirical False-Negative Decomposition." Technical Report v1.2, 2026. https://doi.org/10.5281/zenodo.22116399

[16] Vyom Kulshrestha. "Learned Caution, Deterministic Authority: An Action-Conditioned JEPA Safety Runtime for Cyber-Physical Systems." Technical Report v1.1, 2026. https://doi.org/10.5281/zenodo.22092356

[17] Safety-Gymnasium Contributors. "Safety-Gymnasium: A Unified Safe Reinforcement Learning Benchmark." Thirty-seventh Conference on Neural Information Processing Systems Datasets and Benchmarks Track, 2023. https://openreview.net/forum?id=WZmlxIuIGR
