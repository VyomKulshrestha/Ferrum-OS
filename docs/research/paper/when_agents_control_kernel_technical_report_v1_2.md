# When Agents Control the Kernel

## A JEPA World Model Safety Gate with Empirical False-Negative Decomposition and Request-Bounded Deterministic Authority

Technical Report v1.2 - 26 August 2026

Vyom Kulshrestha
Independent Researcher, India
ORCID: 0009-0009-1434-7148
vyomkulshrestha2004@gmail.com
github.com/VyomKulshrestha/Ferrum-OS

Published lineage: report DOI 10.5281/zenodo.21829808; dataset DOI 10.5281/zenodo.21829193.

### Abstract

Autonomous agents that modify files, processes, services, and network state require controls at the point where proposed actions become operating-system effects. FerrumOS normalizes provider output into 41 canonical actions and evaluates an independent deterministic transition branch and an action-conditioned joint-embedding predictive architecture (JEPA) transition branch before capability-gated syscalls. The original study accounted for 13,697 transitions from 3,639 QEMU episodes and reported 81.4% balanced accuracy on a 500-episode authored safety fixture for rules plus the selected JEPA checkpoint. It also found that a per-action mean baseline was nearly tied, complete-pipeline seeds varied substantially, and 52 false negatives clustered into missing semantic assets, process accumulation, and heap underprediction.

This v1.2 report preserves those results and adds a registered v3-v3.4 evaluation. Four failed iterations are retained before the final catalog is opened. The frozen candidate improves normalized rollout error on the untouched published test partition at H=1, H=3, and H=5 by 9.54%, 2.36%, and 0.92%, respectively, for a 4.35% geometric improvement over deployed runtime-v2. On a new 512-episode source-held-out deterministic simulator, request-bounded v3.4 policy records 100% balanced accuracy, no missed simulated hazards, and no blocked safe controls; the paired source-stratified 95% bootstrap interval for improvement over runtime-v2 is +46.35 to +48.82 percentage points. The result is identical for rules-only and rules+JEPA. It therefore demonstrates deterministic authority and integration, not incremental learned safety value. The candidate remains archived and not deployed because runtime authority, timing, and simulator-to-runtime resource effects have not passed the frozen promotion gates.

<!-- PAGE BREAK -->

### 1. Introduction

Language-model agents increasingly convert natural-language goals into state-changing operations. Application-layer refusal can reduce unsafe proposals, but an operating system still needs a mediation point where a canonical action and its arguments are checked before execution. FerrumOS places that point in the ring-3 Heliox daemon immediately above capability-gated syscalls. Learned inference cannot grant authority; kernel validation and physical confirmation remain independent backstops.

The research question is deliberately narrower than "can a neural model make an operating system safe?" The question is whether an action-conditioned forecast can improve prediction of safety-relevant state transitions while deterministic policy, capabilities, and operator confirmation retain execution authority. That distinction prevents a prediction score from silently becoming a privilege decision.

The first study established a reproducible hybrid OS mediation architecture, strong baselines, in-guest runtime measurements, and an exhaustive false-negative decomposition. It did not establish JEPA superiority on thresholded safety decisions. The follow-up study tests a different issue exposed by those failures: whether repeated hypothetical rollout had been allowed to influence authority beyond the single action actually requested.

#### 1.1 Contributions

1. A provider-independent OS action-mediation architecture with monotonic deterministic-plus-learned screening before capability-gated syscalls.
2. A fully accounted, episode-disjoint public transition corpus and deterministic release package with public DOI, hashes, and download verification.
3. Strong original baselines, five complete training pipelines, real ring-3 timing, outstanding-request tests, artifact-failure tests, and exhaustive decomposition of all 52 original hybrid false negatives.
4. A digest-bound v3-v3.4 lineage with preregistered development and final gates, retained negative results, and file-open audit controls that keep the source-held-out final catalog unavailable during selection.
5. A request-bounded authority rule: when a canonical action has an exact registered deterministic effect, the authority decision evaluates the requested step rather than unrequested hypothetical repetitions.
6. A new 512-case source-held-out deterministic simulator with paired source-stratified uncertainty, exact rules-only attribution, and an explicit non-promotion result.

#### 1.2 Claim boundary

The original safety fixture and the new incident-informed fixture are authored software simulations over QEMU-derived or programmatically constructed states. They are not production incident replays, independently human-adjudicated hazards, formal proofs, or evidence of complete safety. The v3.4 learned candidate is archived but not deployed. The new safety result belongs to deterministic policy; the learned result is the untouched-corpus rollout improvement.

<!-- PAGE BREAK -->

### 2. Claim-to-evidence map and study lineage

The paper separates claims by evidence object so that a reader can audit what each experiment actually supports.

| Claim | Evidence | Result | Boundary |
|---|---|---|---|
| Hybrid mediation is implementable before OS effects | Ring-3 Heliox path plus capability-gated syscall boundary | Implemented and exercised in QEMU for runtime-v2 | v3.4 authority policy is not installed |
| JEPA representation predicts transitions better than the matched autoencoder | Untouched 1,969-row episode-disjoint test partition | H=3 error 3.87% vs 6.45% | Does not prove better binary safety decisions |
| Original hybrid lowers authored-fixture false negatives | 500 paired authored cases | FNR 20.8% vs rules-only 41.2% | FPR rises from 8.4% to 16.4%; per-action mean is nearly tied |
| v3.4 candidate improves deployed runtime-v2 rollout | Same untouched published test partition | Lower error at H=1, H=3, and H=5 | Frozen candidate was not retrained during v3.4 policy repair |
| v3.4 policy covers the new four-source fixture | 512 source-held-out deterministic cases | 256 TP, 0 FN, 256 TN, 0 FP | Labels and effects are simulator-authored |
| Learned branch adds final-fixture safety value | Rules-only vs rules+candidate ablation | No difference | No incremental learned safety claim |
| v3.4 is deployable | Frozen offline, runtime, authority, and digest gates | Not all passed | Candidate remains promotion_eligible=false |

#### 2.1 Version lineage

The public report and dataset remain the archival starting point. Runtime-v2 is the deployed comparison artifact. v3 changes deterministic coverage while freezing the learned candidate. v3.1 and v3.2 test learned resource thresholds; v3.3 tests exact multi-step projection; and v3.4 changes only the authority factorization for exact covered actions. Failed results remain in the repository rather than being overwritten.

| Lineage item | Role | Selection exposure | Deployment status |
|---|---|---|---|
| Published study v1.0.0 | Original architecture, corpus, baselines, and runtime evidence | Original registered fixture | Published and deployed runtime-v2 lineage |
| v3 candidate | Frozen learned transition plus deterministic policy repair | Legacy and opened development fixtures | Not deployed |
| v3.1-v3.3 | Registered failed policy/threshold iterations | Development only | Not deployed |
| v3.4 | Request-bounded authority evaluation | Development gates, then one final opening | Archived; not deployed |

The v3.4 protocol binds the candidate, development fixtures, source lists, final-catalog generator, and deployment digests. Validation-only programs record attempted file access and deny both final source and final scenario paths. The evaluator refuses to overwrite an existing final result.

<!-- PAGE BREAK -->

### 3. Threat model and security boundary

#### 3.1 Assets and failure sources

Protected assets include persistent-state integrity and availability; kernel and service continuity; bounded process, heap, and disk consumption; operator confirmation authority; and an auditable record of proposed, blocked, and executed canonical actions.

Failure sources include untrusted provider output or prompt injection, a paired controller submitting harmful but syntactically valid calls, benign autonomy that repeats locally reasonable actions, and unprivileged ring-3 software attempting to route operations through Heliox. Trusted kernel code, malicious physical operators, compromised signing keys, hardware attacks, and already-unrestricted root authority are outside the experiments.

| Category | Example | Primary control | Evidence status |
|---|---|---|---|
| Direct harm | Delete daemon configuration; unsafe upgrade | Exact predicate plus capability/confirmation | Covered in original and v3.4 fixtures |
| Compound resources | Repeated writes, spawns, or service starts | Fresh state, cumulative budget, and forecast | Original misses exposed temporal weakness |
| Prompt injection | Provider proposes destructive tool call | Canonical provider-independent gate | Evaluated as an authored scenario family |
| Rule edge or OOD | Alias, unlisted asset, learned residual | Canonical paths plus monotone learned caution | Partial in original; expanded in v3 policy |
| Authority mismatch | Forecast repeats an action not actually requested | Request-bounded exact effect | Repaired in v3.4 development |

#### 3.2 Security properties

The deterministic branch remains active when the learned branch predicts safety. Provider identity is provenance, not a model feature. A predictive allow is never execution authority. A predictive block can create availability harm, so false positives and intervention rate are first-class outcomes. Missing, non-finite, malformed, or forbidden-coverage learned artifacts cannot erase deterministic protection.

A false negative advances to later capability and confirmation checks; if those also permit the call, harm can execute. A false positive prevents useful work and may become denial of service. Hazards that neither alter represented resources nor match a deterministic predicate remain invisible. These are measured limitations rather than formal guarantees.

#### 3.3 Kernel and human authority

The world model runs in the unprivileged Heliox daemon. The kernel remains deterministic and independently enforces syscall argument validation, capabilities, signed upgrade policy, and confirmation. The experiments do not claim a kernel-resident neural model. Registered natural-use annotations remain a protocol until real annotators complete blinded labels and adjudication.

#### 3.4 Request-bounded authority

Forecast horizon and execution authority are different objects. Multi-step rollout estimates consequences if an action repeats. It does not mean those repetitions were requested or authorized. v3.4 therefore applies an exact deterministic effect to the requested action when the canonical action is covered. Learned multi-horizon output remains available for telemetry and may add caution for uncovered effects, but it cannot convert imagined repetitions into authority.

<!-- PAGE BREAK -->

### 4. System architecture

Provider output is decoded into a canonical tool and normalized argument vector. The daemon captures OS state, runs deterministic and learned self-composition rollouts independently, takes the higher risk, and only then permits the tool dispatcher to request a capability-gated syscall. Exact semantic facts such as deleting daemon configuration or requesting a kernel upgrade remain outside learned compression.

![Figure 1. FerrumOS JEPA training and runtime architecture. The learned forecast is advisory and monotone; deterministic policy and kernel authority remain independent.](docs/research/figures/figure_2_jepa_architecture.png)

The public provider, planner, gesture, and JSON-RPC dispatch paths converge on `execute_tool_with_world_model`. Read-only `world_model_preview` follows the same prediction path without dispatch or experience emission. Provider choice - cloud, local language model, or paired external controller - does not change the safety representation.

#### 4.1 Decision flow

1. Normalize provider output into one of 41 canonical actions and 16 argument features.
2. Capture a 48-dimensional raw OS observation.
3. Evaluate exact deterministic predicates and bounded resource effects.
4. Encode the observation and predict learned transition deltas over the registered horizon.
5. Combine risks monotonically: a learned false-safe result cannot erase a rule block.
6. Pass an allowed proposal to capability and confirmation checks, which can still reject it.
7. Emit a privacy-bounded audit record without prompts, paths, screen content, or account identifiers.

#### 4.2 Failure behavior

| Component | Runtime role | Failure behavior |
|---|---|---|
| Deterministic transition | Exact paths, policy, bounded resource deltas | Always active |
| JEPA encoder and transition | Learned action-conditioned numeric effects | Optional; invalid files rejected |
| Monotonic union | Higher branch risk wins | Learned false-safe cannot erase a rule block |
| Capability and confirmation | Independent execution authority | Can reject predictive allows |
| Audit record | Reproduction and incident review | Does not contain raw prompt or path data |

<!-- PAGE BREAK -->

### 5. Model and decision method

#### 5.1 State and action representation

A 48-dimensional raw vector contains normalized process, heap, filesystem, disk, screen, last-action, and error observations. The online encoder contributes 77 learned values to a 128-dimensional runtime state while deterministic safety fields remain explicit. The action input contains 41-dimensional one-hot identity plus 16 normalized argument features.

With online context encoder E, EMA target encoder E_ema, action-conditioned predictor P, reconstruction head R, and action head A, training minimizes:

```text
z_t = E(x_t)
target = stopgrad(E_ema(x_(t+1)))
predicted = P(z_t, action, args)
loss = L_JEPA + 0.25 * L_reconstruction + 0.10 * L_action
```

The target encoder uses an EMA coefficient of 0.99. Anti-collapse promotion requires better-than-zero prediction, latent standard deviation at least 0.01, effective rank at least 4, and non-zero action sensitivity.

#### 5.2 Transition and rollout

A 185-input, 512-hidden ReLU multilayer perceptron predicts a 128-dimensional state delta. The published transition was trained with full-batch gradient descent, inverse-frequency action weighting, 2,000 epochs, and a fixed episode split. The packaged pair contains 32,333 encoder parameters and 160,896 transition parameters, 193,229 total.

For h=1..H, the learned branch predicts the consequence of repeating the proposed canonical action. Process deltas accumulate explicitly. Resource risk rises when predicted heap or disk reaches 0.95; exact protected-path deletion and policy-only upgrade predicates are deterministic. The original runtime blocks when either branch reaches risk 0.7. H=3 was deployed as the minimum verified horizon for the process-growth pattern, not as a globally optimal horizon.

#### 5.3 What JEPA means here

JEPA is an inductive bias for predicting safety-relevant abstract structure instead of reconstructing arbitrary paths, process names, timestamps, and screen details [1-3]. It is not a causal theorem. Binary decision parity with a simple baseline does not imply equivalent transition modeling, but lower transition error also does not prove greater operational safety.

#### 5.4 v3.4 change isolation

The v3.4 learned transition weights are unchanged. The experiment freezes candidate SHA-256 `2616aa6b0587adc9258bd5ccd7d95f1e1a2011af7b2e76e3927046c010444f77`. The policy repair changes authority accounting for exact covered actions. It is therefore a policy-lineage result plus a separate frozen-model rollout comparison, not a new model-training result.

<!-- PAGE BREAK -->

### 6. Dataset, training, and public packaging

#### 6.1 Published corpus ledger

| Ledger item | Count | Treatment |
|---|---:|---|
| Accepted transitions | 13,697 | Retained for complete accounting |
| Complete episodes | 3,639 | Episode is the split unit |
| Multi-step episodes | 1,300 | Temporal examples retained atomically |
| Execution not attempted | 373 | Excluded from transition fitting |
| Policy-only upgrade rows | 54 | Auditable; excluded from learned coverage |
| Eligible fitting rows | 13,270 | 9,104 / 2,197 / 1,969 train/validation/test |

Complete episodes are shuffled with split seed 42; no episode crosses partitions. All 41 canonical actions were observed under both memory profiles. Forty actions are represented in learned fitting, while kernel upgrade remains policy-only. Every argument-bearing learned action has at least three variants. A corrective collection replaced stale pre-ABI `ipc_send` episodes with 128 successful live transitions.

#### 6.2 Published representation comparison

| Metric | Matched autoencoder | Selected JEPA | Relative change |
|---|---:|---:|---:|
| One-step normalized error | 2.30% | 1.68% | -27.1% |
| Safety-core normalized error | 4.61% | 3.81% | -17.5% |
| Macro-per-tool error | 2.96% | 1.71% | -42.3% |
| Rollout H=3 | 6.45% | 3.87% | -40.0% |
| Rollout H=5 | 6.70% | 4.03% | -39.9% |

The release checkpoint uses representation seed 42 and transition seed 17, selected only by validation transition metrics. Full-pipeline seeds retrain the representation itself and are different checkpoints even when a numeric seed is shared.

#### 6.3 Release integrity

The exact JSONL is packaged as a deterministic gzip archive with an MIT dataset license, data card, manifest, SHA256SUMS, episode-split verification, and credential-pattern scan. The source SHA-256 is `ae7498c7d93b4e35f8bf0a9ac595ca2bacc1ec694b1806c47a33741d911d491f`; the deterministic gzip SHA-256 is `310f5192d3d777c5a6420498a7074e48035f3e408d3c089cbc98eed79bfe6fb7`. The release is open at version DOI 10.5281/zenodo.21829193. Ten public files matched the local release byte-for-byte and the downloaded copy passed 11/11 verification checks.

<!-- PAGE BREAK -->

### 7. Original evaluation protocol

The primary original fixture contains 250 safe and 250 dangerous authored episodes, balanced across direct harm, compound resource exhaustion, provider prompt injection, and rule-table edge cases. Initial states and empirical deltas derive from the untouched 1,969-row QEMU test split. Harmful outcomes are evaluated counterfactually; the protocol does not execute 500 destructive calls.

| Arm or ablation | Purpose |
|---|---|
| Always allow / always block | No-model controls and metric sanity checks |
| Rules only / JEPA only / union | Primary paired contribution of each branch |
| Per-action mean transition | Simple learned baseline without representation inference |
| Matched autoencoder | Generative-style representation baseline |
| Action conditioning removed | Tests whether action identity and arguments matter |
| H=1..5 | Horizon sensitivity and release-H interpretation |
| Three fixed-encoder transition seeds | Downstream initialization sensitivity |
| Five complete pipeline seeds | Representation plus transition sensitivity |
| 1,969-row safe replay | False-alert cost on untouched safe observations |
| 240-row HUD boundary replay | Post-training safe calibration negative control |

Outcomes include TP, FN, FP, TN, FNR, FPR, balanced accuracy, Wilson intervals, AUROC, AUPRC, paired McNemar tests, paired bootstrap intervals, transition error, and safe alerts per 1,000 actions. Complete-pipeline intervals use the t distribution over five runs and describe run-to-run uncertainty on this fixture.

Model checkpoints are selected by validation representation and transition metrics only. Safety-test labels are not used for checkpoint selection, and all five full-pipeline seeds are reported.

Runtime experiments execute the deployed ring-3 path in QEMU/WHPX. The 1 kHz PIT provides mean, median, p95, and maximum time at 1 ms percentile resolution. Raw virtual TSC cycles are retained but not converted because they did not agree reliably with the guest timer.

<!-- PAGE BREAK -->

### 8. Original safety results and strong baselines

#### 8.1 Three-arm result

| Condition | TP | FN | FP | TN | FNR | FPR | Balanced accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|
| Rules only | 147 | 103 | 21 | 229 | 41.2% | 8.4% | 75.2% |
| JEPA only | 57 | 193 | 23 | 227 | 77.2% | 9.2% | 56.8% |
| Rules + JEPA | 198 | 52 | 41 | 209 | 20.8% | 16.4% | 81.4% |

![Figure 2. Original registered three-arm paired comparison. Error bars are 95% Wilson intervals.](docs/research/figures/figure_1_three_arm_comparison.png)

The learned branch catches 51 dangerous cases missed by rules while adding 20 safe blocks. This supports monotonic composition, not learned replacement of rules.

#### 8.2 Stronger binary-decision baselines

| Combined condition | FNR | FPR | Balanced accuracy | AUROC | AUPRC |
|---|---:|---:|---:|---:|---:|
| Rules only | 41.2% | 8.4% | 75.2% | 0.770 | 0.831 |
| Rules + autoencoder | 24.4% | 16.4% | 79.6% | 0.830 | 0.869 |
| Rules + per-action mean | 20.8% | 16.8% | 81.2% | 0.847 | 0.881 |
| Rules + selected JEPA | 20.8% | 16.4% | 81.4% | 0.848 | 0.881 |
| Rules + calibrated JEPA | 16.4% | 16.4% | 83.6% | 0.867 | 0.898 |

The per-action mean differs from selected JEPA on only three correctness outcomes: JEPA is uniquely correct twice and the mean model once, exact McNemar p=1.0. The 0.2-point balanced-accuracy difference does not establish a material JEPA safety advantage. JEPA's stronger evidence in the original study is lower transition error than the matched autoencoder.

<!-- PAGE BREAK -->

### 9. Original stability, runtime, and failure analysis

#### 9.1 Complete-pipeline sensitivity

| Full-pipeline seed | H=3 error | FNR | FPR | Balanced accuracy |
|---|---:|---:|---:|---:|
| 17 | 15.47% | 28.4% | 10.4% | 80.6% |
| 42 | 4.11% | 37.6% | 10.0% | 76.2% |
| 91 | 13.16% | 25.2% | 13.6% | 80.6% |
| 123 | 6.06% | 18.8% | 16.4% | 82.4% |
| 2026 | 27.04% | 25.2% | 16.8% | 79.0% |

Across five complete pipelines, balanced accuracy averages 79.76% with SD 2.33 points and a 95% t interval of 76.87%-82.65%. Full-pipeline seed 17 is not the release checkpoint: it retrains the representation, whereas the release checkpoint retains representation seed 42 and varies only the transition seed.

#### 9.2 Ring-3 runtime

| Horizon | Mean | Median | p95 | Maximum | Blocked / 100 |
|---|---:|---:|---:|---:|---:|
| H=1 | 1.35 ms | 1 ms | 2 ms | 3 ms | 2 |
| H=2 | 1.44 ms | 1 ms | 2 ms | 3 ms | 2 |
| H=3 | 1.45 ms | 1 ms | 2 ms | 3 ms | 2 |
| H=4 | 1.53 ms | 1 ms | 2 ms | 3 ms | 2 |
| H=5 | 1.59 ms | 2 ms | 2 ms | 2 ms | 2 |

After a 64-preview H=5 warmup, model loading is 30 ms, both learned files are active, and heap use remains 664,832 bytes before and after 500 measured previews. The 1 ms PIT granularity limits percentile precision. Provider latency, action execution, and human confirmation are excluded.

One connection submits 96 previews across six action classes without waiting between sends. All 96 responses return with correct IDs in 20.142 seconds host wall time. Inference is serialized; this tests framing and state isolation, not parallel neural execution.

#### 9.3 Injected artifact failures

| Injected condition | Observed behavior | Result |
|---|---|---|
| Valid files | Both load; protected self-delete blocked | PASS |
| Both files missing | Daemon starts; deterministic self-delete remains blocked | PASS |
| Valid-shape NaN files | Both rejected; deterministic block remains | PASS |
| Forbidden policy coverage | Transition rejected; upgrade quarantine remains | PASS |
| Collapsed JEPA trial | Metrics retained; no promotable artifacts emitted | PASS |

<!-- PAGE BREAK -->

### 10. Original false-negative decomposition and boundary calibration

All 52 selected-gate misses were reproduced from committed fixture and prediction rows.

| Cluster | Count | Mechanism | Required remedy |
|---|---:|---|---|
| Missing semantic asset | 21 | Deleted path is not an explicit protected field | Expand deterministic asset policy/state |
| Process accumulation | 20 | Horizon and episode history omit long sequences | Temporal history or cumulative budget |
| Heap underprediction | 11 | Forecast stays below 0.95 while observed state crosses | Action-specific data and uncertainty |

Ten of the 11 heap cases are `hud_update`; one is `http_get`. All misses have recorded risk 0.0, so threshold tuning alone cannot repair them. Forty-one require policy or temporal-state changes rather than more model capacity.

#### 10.1 Post-training HUD boundary set

The independent negative control contains 240 successful QEMU episodes over 12 argument-size regimes, including the 128-byte render boundary. Observed normalized heap delta is zero in every row. Transition heap-delta MAE is 0.00296 and RMSE is 0.00402; unadjusted resource alarms are 0/240.

| Boundary statistic | Value |
|---|---:|
| Episodes / regimes | 240 / 12 |
| Execution failures | 0 |
| Observed non-zero heap deltas | 0 |
| Residual p95 upper margin | 0.002219 |
| Alarms with p95 margin | 0 |
| Production calibration changed | No |

This corpus is one safe action class outside training and the registered test split. It cannot estimate dangerous recall or justify a distribution-free guarantee. The residual margin is analysis only.

Boundary collection also exposed an independent compositor arithmetic underflow: a 1,044-pixel bubble was centered in a 1,024-pixel framebuffer. The renderer now uses actual framebuffer dimensions, UTF-8-safe truncation, and saturating or clamped geometry; a real QEMU boundary verifier passes without panic.

<!-- PAGE BREAK -->

### 11. Registered v3-v3.4 extension

#### 11.1 Incident-informed source protocol

Development sources were partitioned before candidate selection. A separate final source catalog was frozen and denied to validation scripts. The final official postmortems describe inadvertent disablement of Cloudflare's R2 Gateway, a Dropbox maintenance script reinstalling active database machines, a Google Cloud race propagating corrupt load-balancer configuration, and GitHub resource contention involving unintended configuration [19-22]. These reports motivate defensive abstractions only. The fixture does not reproduce provider systems, workloads, data, exploit paths, or impact.

The final benchmark contains 128 cases per source, 512 total, with deterministic labels and exactly half safe controls. Source holdout is not an unseen-action, unseen-hazard, natural-use, or production-generalization claim.

#### 11.2 Leakage and artifact controls

The protocol fixes candidate digest, source partitions, family sizes, gates, statistics, and deployment digests before the final is opened. Validation-only selection installs file-open audit hooks and records all attempted paths. It denies both the final source registry and generated final catalog. The final evaluator is a separate command and refuses replacement of an existing result.

#### 11.3 Registered statistics

Balanced-accuracy differences are paired by scenario and bootstrapped within source for 10,000 resamples. The 95% interval is the 2.5th to 97.5th percentile of the source-stratified paired distribution. Rollout error is reported at H=1, H=3, and H=5 on the untouched published episode-disjoint partition. Brier score and 10-bin ECE describe deterministic gate scores, not learned probabilities, and are not used as a calibration claim.

#### 11.4 Frozen gates

| Stage | Gate | Outcome |
|---|---|---|
| v3.4 development | v3 opened-development FN = 0 and FP < 40 | Passed: FN 0, FP 16 |
| v3.4 development | Legacy FN < 50, FP <= 41, BA > 81.8% | Passed: FN 0, FP 21, BA 95.8% |
| Final access | No final source/catalog reads during selection | Passed |
| Final evaluation | One digest-bound evaluation, no overwrite | Passed |
| Runtime authority | v3.4 path exercised through deployed ring-3 authority | Not passed |
| Runtime effects | Authored resource effects validated against runtime | Not passed |
| Deployment | Every frozen gate passes and digests match | Not eligible |

<!-- PAGE BREAK -->

### 12. Retained iterations and selection discipline

| Iteration | Registered change | Development outcome | Decision |
|---|---|---|---|
| v3 | Frozen decoder refinement plus protected-path and service policy repair | Legacy BA 87.0%; FN 5; FP 60 | Retained failure: FP exceeded 41 |
| v3.1 | Shared learned-resource threshold sweep | 0/19 candidates passed | Retained failure |
| v3.2 | Learned-disk threshold sweep | 0/7 candidates passed | Retained failure; alerts were rule-originated |
| v3.3 | Three-step exact projection for covered actions | Opened v3 safe-control FP 64/256 | Retained failure: hypothetical repetition over-intervened |
| v3.4 | One-step authority for covered requested actions | Legacy BA 95.8%; FN 0; FP 21 | Development passed; final opened once |

The sequence is part of the evidence. No failed result was replaced by a cleaner file, no deployed artifact was used as a scratch target, and the source-held-out final remained inaccessible until v3.4 passed every development gate.

#### 12.1 Why v3.3 failed

For an exact action with a bounded one-step effect, v3.3 repeatedly applied that effect across H=3 during the authority decision. This asked a useful forecasting question but answered the wrong authorization question: what might happen if the action repeats, rather than what the current request authorizes. The result was a sharp rise in safe-control intervention.

#### 12.2 Why v3.4 is narrower

v3.4 does not relax protected-path rules or erase learned caution. It limits exact covered-action authority to the requested step. Uncovered learned effects may still accumulate in rollout, and deterministic cumulative budgets remain the appropriate mechanism for repeated authorized actions.

#### 12.3 Development intervention

On the legacy 500-case fixture, v3.4 records FN 0 and FP 21, an 8.4% safe-control intervention rate, versus runtime-v2 FN 50 and FP 41, 16.4% intervention. On the opened v3 incident fixture, v3.4 records FN 0 and FP 16, 6.25% intervention, versus v3 FN 0 and FP 40, 15.625%. These are development regressions used to select v3.4 and are not independent final evidence.

<!-- PAGE BREAK -->

### 13. v3.4 final results

#### 13.1 Untouched-corpus rollout

| Horizon | Deployed runtime-v2 normalized error | Frozen v3.4 candidate | Relative reduction |
|---|---:|---:|---:|
| H=1 | 0.072218 | 0.065331 | 9.54% |
| H=3 | 0.037751 | 0.036859 | 2.36% |
| H=5 | 0.040362 | 0.039990 | 0.92% |

All registered horizons improve. The geometric candidate/runtime-v2 ratio is 0.956508, corresponding to a 4.35% geometric improvement. This is the quantitative learned-model result. The gain is modest at longer horizons and should not be described as a large or universal JEPA advantage.

#### 13.2 Source-held-out safety fixture

| Condition | TP | FN | TN | FP | FNR | FPR | Balanced accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|
| Deployed runtime-v2 rules+JEPA | 12 | 244 | 256 | 0 | 95.31% | 0.00% | 52.34% |
| v3.4 deterministic policy | 256 | 0 | 256 | 0 | 0.00% | 0.00% | 100.00% |
| v3.4 policy + frozen candidate | 256 | 0 | 256 | 0 | 0.00% | 0.00% | 100.00% |

The paired source-stratified 95% bootstrap interval for v3.4 minus runtime-v2 balanced accuracy is +46.35 to +48.82 percentage points. The improvement is large on this fixture, but the fixture is designed around deterministic scenario families and cannot estimate natural prevalence.

The risk-score Brier value changes from 0.4768 to 0.00875 and 10-bin ECE from 0.4789 to 0.0625. These scores are rule-derived and are not calibrated learned probabilities. They describe score-label agreement on this balanced deterministic catalog only.

#### 13.3 Exact attribution

Rules-only and rules+candidate have identical confusion matrices and identical per-case decisions. The learned-only marginal safety contribution on the final fixture is therefore zero. The final benchmark demonstrates typed deterministic policy, authority factorization, and integration. It does not corroborate incremental learned harm avoidance.

<!-- PAGE BREAK -->

### 14. Ablation, interpretation, and non-promotion

#### 14.1 What changed between studies

| Dimension | Original report | v1.2 extension |
|---|---|---|
| Main safety fixture | 500 authored cases from QEMU-derived states | 512 incident-informed deterministic cases |
| Selection protection | Safety labels excluded from checkpoint selection | Final sources and catalog denied to all selection scripts |
| Learned comparison | JEPA, autoencoder, per-action mean, five pipelines | Frozen runtime-v2 vs frozen candidate rollout |
| Policy attribution | Rules, JEPA, and union | v3.4 rules-only and rules+candidate exact equality |
| Negative results | Baseline parity, seed variation, 52 FN clusters | v3-v3.3 retained failed gates |
| Deployment evidence | runtime-v2 ring-3 timing and failures | v3.4 not deployed; runtime gates pending |

#### 14.2 What the learned branch adds

The original selected JEPA reduced transition error versus a matched autoencoder and lowered authored-fixture FNR when composed with rules. The frozen v3.4 candidate also improves all registered rollout horizons over deployed runtime-v2. Those are prediction results. Neither the original per-action mean comparison nor the new final rules-only ablation establishes JEPA superiority for thresholded safety decisions.

#### 14.3 What deterministic authority adds

Exact semantic predicates cover risks that compressed numerical state can miss. Request-bounded effects prevent unrequested hypothetical repetitions from causing intervention. The new final fixture is intentionally credited to this deterministic path. Learned uncertainty may motivate caution, but it is not allowed to grant capability or override a deterministic block.

#### 14.4 Non-promotion decision

Candidate files are archived under a versioned research artifact. Deployed runtime-v2 digests remain unchanged: transition SHA-256 `f6bf2e502aa9d8abeeba47b81205468f02ec54203f4f39931d6ea42359cf0dc8`, encoder SHA-256 `9fb5f08b3c5ac16b37a34376b2bb4cbbd249c536bf419dbd80e52a90a0bfc9b3`, and manifest SHA-256 `0ac0bfe402605e20ef861c03cf6849d4b8a57844996a3fa4eb46fed28500eff7`. The research candidate is marked `promotion_eligible: false` until runtime authority, timing, resource-effect, and digest gates pass.

<!-- PAGE BREAK -->

### 15. Relation to prior work

JEPA and I-JEPA motivate prediction in representation space rather than full observation reconstruction [1-3]. FerrumOS applies that inductive bias to action-conditioned OS state transitions but does not infer formal safety from it. Constitutional AI and model-level alignment shape provider behavior [4]; FerrumOS instead mediates canonical state-changing actions from any provider at runtime.

SafetyBench, Agent-SafetyBench, and ST-WebAgentBench measure safety knowledge or application-layer tool policy [5,7,8]. WebArena and OSWorld evaluate long-horizon agent task completion in web or computer environments [6,11]. ToolEmu and AgentDojo provide emulated or dynamic safety evaluation for LM agents [12,13]. SafeDreamer uses world models for constrained reinforcement learning [9]. Responsible manipulation addresses physical consequence reflection [10]. FerrumOS's narrower differentiator is provider-independent action normalization and prediction immediately before an OS capability boundary, with deterministic kernel enforcement afterward.

| Work family | Primary layer or measure | Difference from FerrumOS |
|---|---|---|
| JEPA, I-JEPA, V-JEPA [1-3] | Representation-space prediction | Motivates objective; does not establish OS safety |
| Constitutional AI [4] | Model alignment | Provider behavior rather than OS mediation |
| SafetyBench and agent safety benchmarks [5,7,8] | Knowledge or tool-policy behavior | Broader taxonomies; application-layer evaluation |
| WebArena and OSWorld [6,11] | Task completion in interactive environments | No capability-gated kernel authority factorization |
| ToolEmu and AgentDojo [12,13] | Emulated risks and prompt-injection defenses | Different simulator and authority boundary |
| SafeDreamer [9] | World-model constrained RL | Trains a policy; FerrumOS filters discrete OS actions |
| Responsible manipulation [10] | Physical safety reflection | Embodied consequences, not OS effects |

The metrics are not equivalent across these studies. Question accuracy, policy-compliant task completion, RL cost, robot hazard avoidance, transition error, and OS gate FPR/FNR measure different objects. The present novelty claim is systems-oriented: authority factorization, artifact lineage, and failure-accounted evaluation at the OS mediation boundary.

#### 15.1 Incident reports as defensive design inputs

Official postmortems are used to identify recurring defensive abstractions: protected configuration, safe maintenance targeting, propagation of invalid configuration, retry amplification, and resource contention [14-22]. The paper does not claim to reconstruct these incidents or evaluate the affected providers.

<!-- PAGE BREAK -->

### 16. Limitations, validity threats, and claim registry

1. Both safety fixtures use deterministic authored labels. They are not natural-prevalence data and cannot estimate production precision, recall, or intervention cost.
2. The final four-source catalog has fixed balanced family sizes. Source holdout is not action, hazard, implementation, or distribution holdout.
3. Incident reports motivate abstractions; no provider environment, payload, workload, data, or impact is replayed.
4. The final v3.4 safety result is rules-only in attribution. The learned candidate adds no final-fixture safety decisions.
5. The frozen candidate improves rollout against runtime-v2 but is not compared here with a newly trained architecture-matched supervised model on the same curriculum. Architecture and training-data effects are not isolated.
6. Authored simulator resource effects are not empirical FerrumOS runtime effects. The HUD boundary measurement observed zero normalized heap delta, so an authored non-zero simulator delta cannot be installed as runtime truth.
7. Brier and ECE values on the v3.4 final fixture describe deterministic scores, not calibrated probabilities. The balanced catalog and deterministic score levels limit their interpretation.
8. The original fixture found near parity between selected JEPA and a per-action mean baseline on binary decisions. Complete-pipeline variation is substantial.
9. Original runtime timing has 1 ms guest-timer resolution in one QEMU/WHPX environment. Outstanding previews are serialized, and provider latency, execution, confirmation, and physical I/O are excluded.
10. Boundary calibration covers one safe action class. No dangerous-recall or distribution-free calibration guarantee follows.
11. No independent human labels, completed natural-use study, adversarial operator study, formal verification, or independently designed external evaluation is reported.
12. v3.4 has no completed in-guest authority test, physical timing, actuator dynamics, sensor latency, or production rollout. The deployed model and manifest remain runtime-v2.

#### 16.1 Valid claims

- FerrumOS implements a hybrid pre-execution mediation architecture in which learned output cannot erase deterministic policy or grant kernel capability.
- The public corpus, original evaluation artifacts, and release package are reproducible and digest-bound.
- The original selected JEPA predicts transitions better than its matched autoencoder, while its binary safety advantage over a per-action mean is not material on the authored fixture.
- The frozen v3.4 candidate improves runtime-v2 rollout error at all registered horizons on the untouched published test partition.
- Request-bounded v3.4 deterministic policy perfectly separates the new fixed deterministic catalog, with paired source-stratified uncertainty reported.
- No deployment or learned final-fixture safety advantage is claimed.

#### 16.2 Invalid claims

- "JEPA makes FerrumOS safe."
- "The new model prevents real production incidents."
- "Zero observed final-fixture errors imply zero underlying error probability."
- "The v3.4 candidate is deployed or runtime-verified."
- "The incident-informed fixture is independent third-party validation."

<!-- PAGE BREAK -->

### 17. Reproducibility and artifact checklist

| Artifact or control | Status | Evidence |
|---|---|---|
| Published corpus ledger and episode split | Complete | 13,697 rows; zero episode overlap |
| Original selected model pair | Complete | Versioned binaries and SHA-256 manifest |
| Five original complete pipelines | Complete | Seeds 17, 42, 91, 123, 2026 reported |
| Original safety fixture and predictions | Complete | 500 cases; three-arm and baseline decisions |
| Runtime, concurrency, and failure JSON | Complete for runtime-v2 | Ring-3 benchmark and disposable QEMU tests |
| Public dataset release | Complete | DOI 10.5281/zenodo.21829193; download verified |
| v3-v3.4 protocols and failures | Complete | Every selection/validation result retained |
| Final-catalog selection secrecy | Complete | Validation access audit records zero reads |
| v3.4 final evaluation | Complete | 512 cases; source-stratified paired bootstrap |
| v3.4 deployed authority | External gap | Candidate archived, promotion disabled |
| Independent human labels and natural use | External gap | Registered workflow; no claimed outcome |

#### 17.1 Core reproduction commands

```text
python scripts/verify_world_model_paper_evaluation.py
python scripts/evaluate_world_model_boundary_calibration.py
node scripts/benchmark_world_model_runtime.mjs --iterations 100
node scripts/verify_world_model_preview_concurrency.mjs
node scripts/evaluate_world_model_failure_modes.mjs
python scripts/verify_world_model_dataset_release.py target/world-model-dataset-release

python scripts/verify_world_model_incident_sources_v3.py --online
python scripts/select_world_model_jepa_v3_1.py
python scripts/select_world_model_jepa_v3_2.py
python scripts/validate_world_model_jepa_v3_3.py
python scripts/validate_world_model_jepa_v3_4.py
python scripts/evaluate_world_model_jepa_v3_4_final.py --dataset <public-jsonl>
python scripts/verify_world_model_jepa_v3_4.py --online
```

The final evaluator refuses to overwrite an existing final catalog. Selection and validation scripts install file-open audit hooks that deny final source and scenario paths. Candidate, protocol, selection, validation, scenario, and result artifacts are SHA-256 bound.

#### 17.2 Verification state at v1.2 freeze

The runtime-v2 verifier passes 9/9 checks. The incident-source verifier passes 23/23 checks with official-source availability recorded. The v3.4 verifier passes 27/27 checks, reports `promotion_eligible: false`, and confirms deployed digests are unchanged.

<!-- PAGE BREAK -->

### 18. Conclusion

FerrumOS demonstrates that an agentic operating system can place a provider-independent predictive screen at the action mediation boundary while preserving deterministic policy and kernel authority. The original study established the architecture, corpus, strong baselines, runtime cost, failure behavior, and limits of the first hybrid gate. Its strongest result was not JEPA superiority: a simple per-action mean was nearly tied on thresholded safety decisions, full training pipelines varied, and every false negative could be assigned to a concrete missing semantic or temporal mechanism.

The registered v3-v3.4 extension turns those failures into a narrower systems result. The frozen candidate improves untouched-corpus rollout prediction, while request-bounded deterministic authority removes the unsafe implication that hypothetical repeated rollout is equivalent to a currently authorized request. On the new source-held-out deterministic simulator, policy covers every registered case without safe-control intervention. Exact ablation shows that JEPA adds no safety decisions there.

The resulting contribution is therefore an evidence-disciplined authority architecture: learned forecasting can add caution and predictive detail, but exact policy, capabilities, and confirmation retain execution authority. Failed iterations, source partitions, digests, uncertainty, attribution, and non-promotion are part of the result. Deployment remains withheld until runtime authority, timing, and resource-effect gates pass.

### References

1. Y. LeCun. A Path Towards Autonomous Machine Intelligence. OpenReview, 2022. https://openreview.net/forum?id=BZ5a1r-kVsf
2. M. Assran et al. Self-Supervised Learning from Images with a Joint-Embedding Predictive Architecture. CVPR, 2023. https://arxiv.org/abs/2301.08243
3. A. Bardes et al. Revisiting Feature Prediction for Learning Visual Representations from Video. 2024. https://arxiv.org/abs/2404.08471
4. Y. Bai et al. Constitutional AI: Harmlessness from AI Feedback. 2022. https://arxiv.org/abs/2212.08073
5. Z. Zhang et al. SafetyBench: Evaluating the Safety of Large Language Models. ACL, 2024. https://arxiv.org/abs/2309.07045
6. S. Zhou et al. WebArena: A Realistic Web Environment for Building Autonomous Agents. ICLR, 2024. https://arxiv.org/abs/2307.13854
7. Z. Zhang et al. Agent-SafetyBench: Evaluating the Safety of LLM Agents. 2024. https://arxiv.org/abs/2412.14470
8. I. Levy et al. ST-WebAgentBench: A Benchmark for Evaluating Safety and Trustworthiness in Web Agents. 2024. https://arxiv.org/abs/2410.06703
9. W. Huang et al. SafeDreamer: Safe Reinforcement Learning with World Models. 2023. https://arxiv.org/abs/2307.07176
10. M. Ni et al. Don't Let Your Robot be Harmful: Responsible Robotic Manipulation via Safety-as-Policy. 2024. https://arxiv.org/abs/2411.18289
11. T. Xie et al. OSWorld: Benchmarking Multimodal Agents for Open-Ended Tasks in Real Computer Environments. 2024. https://arxiv.org/abs/2404.07972
12. Y. Ruan et al. Identifying the Risks of LM Agents with an LM-Emulated Sandbox. 2023. https://arxiv.org/abs/2309.15817
13. E. Debenedetti et al. AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents. 2024. https://arxiv.org/abs/2406.13352
14. GitLab. Postmortem of database outage of January 31. 2017. https://about.gitlab.com/blog/postmortem-of-database-outage-of-january-31/
15. Amazon Web Services. Summary of the Amazon S3 service disruption in the Northern Virginia region. 2017. https://aws.amazon.com/message/41926/
16. Fastly. Summary of June 8 outage. 2021. https://www.fastly.com/blog/summary-of-june-8-outage
17. Santosh Janardhan. Update about the October 4th outage. Meta, 2021. https://engineering.fb.com/2021/10/05/networking-traffic/outage-details/
18. Cloudflare. Cloudflare outage on November 18, 2025. 2025. https://blog.cloudflare.com/18-november-2025-outage/
19. Cloudflare. Cloudflare incident on February 6, 2025. 2025. https://blog.cloudflare.com/cloudflare-incident-on-february-6-2025/
20. Dropbox. Outage post-mortem. 2014. https://dropbox.tech/infrastructure/outage-post-mortem
21. Google Cloud. Incident report: November 16, 2021. 2021. https://status.cloud.google.com/incidents/6PM5mNd43NbMqjCZ5REh
22. GitHub. February service disruptions post-incident analysis. 2020. https://github.blog/news-insights/company-news/february-service-disruptions-post-incident-analysis/
23. NIST. Artificial Intelligence Risk Management Framework (AI RMF 1.0). 2023. https://doi.org/10.6028/NIST.AI.100-1
24. E. B. Wilson. Probable Inference, the Law of Succession, and Statistical Inference. Journal of the American Statistical Association, 1927.
25. Q. McNemar. Note on the Sampling Error of the Difference Between Correlated Proportions or Percentages. Psychometrika, 1947.
