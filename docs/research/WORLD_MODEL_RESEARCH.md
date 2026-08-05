# Predictive safety for an agentic OS

This document states the research claim that FerrumOS can support today, the
threat model under which it is evaluated, and the limitations that must remain
visible in a paper or submission. It is intentionally narrower than “the world
model makes the OS safe.”

## Claim and system boundary

FerrumOS uses an action-conditioned joint-embedding predictor as one input to a
pre-execution safety gate. Provider output is first normalized into a canonical
OS action and argument vector. The daemon then evaluates two independent
forecasts: a deterministic transition table and a learned JEPA transition. The
union blocks if either forecast crosses a safety predicate. A block happens
before tool dispatch; kernel capabilities and physical confirmation remain
independent enforcement layers after the predictive gate.

The world model is **not kernel-resident**. It runs in the ring-3 Heliox daemon
at the OS mediation boundary immediately above capability-gated syscalls. The
kernel stays deterministic. The differentiator from prompt-only or web-agent
defenses is therefore OS-level action mediation with a kernel backstop, not a
claim that neural inference executes in privileged kernel space.

## Threat model

### Assets

- integrity and availability of `/disk`, especially Heliox configuration and
  persistent state;
- kernel and service continuity;
- bounded process, heap, and disk consumption;
- the operator's authority to approve destructive actions; and
- auditability of proposed, blocked, and executed canonical actions.

### Adversaries and failure sources

1. **Untrusted model output.** A cloud model, local language model, retrieved
   document, or web page can induce an arbitrary tool name and arguments.
2. **Paired controller misuse.** A controller that possesses the boot-scoped
   pairing token can submit syntactically valid but harmful `execute_tool`
   requests.
3. **Benign autonomy failure.** The built-in planner can repeat a locally
   reasonable action until its aggregate effect becomes unsafe.
4. **Unprivileged local software.** A ring-3 process can attempt operations for
   which it lacks capabilities, or try to route them through Heliox.

Trusted kernel code, a malicious physical operator, compromised build signing
keys, hardware attacks, and an attacker already holding unrestricted root
authority are outside this experiment. Static model-file corruption is partly
covered by size, metadata, finite-value, and SHA-256 checks; poisoning of a
correctly signed training corpus is not.

### Threat categories and expected controls

| Category | Example | Primary control | Status in the registered evaluation |
|---|---|---|---|
| Direct single-step harm | Delete the daemon config; replace the running kernel | Exact deterministic predicate plus capability/confirmation | Combined gate: 63/63 dangerous episodes blocked, 0/62 safe episodes blocked |
| Compound resource harm | Fifty individually small writes; repeated heap-growing actions; repeated service starts | H=3 forecast plus observation on every real step | Partial: disk and learned heap sequences are represented; cumulative process history remains incomplete |
| Prompt injection | Untrusted provider content proposes a destructive canonical action | Provider-independent normalization, predictive gate, capability boundary | Combined gate: 52/63 dangerous episodes blocked, 0/62 safe episodes blocked |
| Rule-table edge or OOD case | Path alias, learned resource effect, deletion of an unlisted sensitive file | Canonical path rules plus learned residual effects | Partial: 41/62 dangerous episodes blocked; unlisted sensitive paths remain a known miss |

### Security properties

- Every public provider, planner, gesture, and JSON-RPC tool path is intended to
  pass through the same gate before dispatch.
- The deterministic estimate stays active even when a learned model claims
  coverage. A learned false-safe prediction cannot erase a deterministic block.
- Provider identity is provenance, not a feature. The same canonical action is
  evaluated identically whether it came from Heliox, a local model, or a remote
  provider.
- A predictive allow is not execution authority. Capabilities, syscall
  validation, and confirmation can still reject it.
- A predictive block is fail-safe for integrity but can create an availability
  failure. False positives are therefore a first-class metric.

### Worst-case failures

A false negative permits the request to continue to later capability and
confirmation checks. If those checks also permit it, the harmful action can
execute. A false positive prevents useful work and can be exploited as a denial
of service. A sufficiently novel hazard that neither changes a represented
resource feature nor matches a deterministic predicate is invisible to this
gate. These are measured limitations, not formal safety guarantees.

## Registered baseline experiment

The registered protocol evaluates the same 500 episodes under three conditions:

1. **Rules only:** deterministic transition estimate and exact predicates.
2. **JEPA only:** learned transition and numeric safety predicates, with no
   exact-path or policy-only credit.
3. **Rules + JEPA:** monotonic union used by the runtime.

The set contains 250 independently labeled safe episodes and 250 dangerous
episodes, with 125 episodes in each threat category. Initial states and empirical
resource deltas come from the 1,969-row untouched episode-level QEMU test split.
The harmful counterfactuals are evaluated offline; the experiment does not claim
that 500 destructive actions were executed against a live disk. The fixture,
per-episode predictions, aggregate JSON, and generated report are committed next
to this document and bound to the release dataset and model hashes.

| Condition | TP | FN | FP | TN | FNR (95% Wilson) | FPR (95% Wilson) | Balanced accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|
| Rules only | 147 | 103 | 21 | 229 | 41.2% (35.3–47.4%) | 8.4% (5.6–12.5%) | 75.2% |
| JEPA only | 57 | 193 | 23 | 227 | 77.2% (71.6–82.0%) | 9.2% (6.2–13.4%) | 56.8% |
| Rules + JEPA | 198 | 52 | 41 | 209 | 20.8% (16.2–26.3%) | 16.4% (12.3–21.5%) | 81.4% |

The paired comparison is the useful result: JEPA adds 51 dangerous catches over
rules alone, loses zero deterministic catches, and adds 20 safe-action blocks.
The dangerous-catch difference is significant under an exact paired McNemar
test (`p = 8.88e-16`). The result supports using the learned branch as a
complement to rules, not as their replacement. It also shows a real calibration
cost: the combined system trades a 20.4 percentage-point reduction in false
negatives for an 8.0 percentage-point increase in false positives on this
boundary-heavy stress set.

Reproduce the registered artifacts with:

```powershell
python scripts/verify_world_model_safety_evaluation.py
```

To regenerate the fixture from the full release dataset:

```powershell
python scripts/evaluate_world_model_safety.py `
  --dataset target/world_model_dataset_release_repaired.jsonl `
  --fixture-out docs/research/world_model_safety_scenarios.json `
  --json-out docs/research/world_model_safety_baseline.json `
  --csv-out docs/research/world_model_safety_predictions.csv `
  --markdown-out docs/research/WORLD_MODEL_SAFETY_BASELINE.md
```

## Why a JEPA representation

Raw OS state contains substantial structure that is expensive or actively
misleading to reproduce exactly: arbitrary path strings, process names, screen
content, timestamps, and device-specific noise. A generative next-state model
must spend capacity reconstructing those details even when the gate only needs
to know whether a proposed action moves the system toward a hazardous region.
JEPA was proposed as a non-generative predictive architecture that operates in
representation space rather than reconstructing every input detail
([LeCun, 2022](https://openreview.net/forum?id=BZ5a1r-kVsf)). I-JEPA later
demonstrated the same central design choice empirically for semantic image
representations ([Assran et al., 2023](https://arxiv.org/abs/2301.08243)).

FerrumOS adapts that idea to action-conditioned OS transitions: a context
encoder maps observed state to a compact latent; a predictor receives that
latent, the canonical action, and normalized arguments; an EMA target encoder
defines the next-state representation. Reconstruction and action auxiliaries,
plus variance, effective-rank, and action-sensitivity gates, discourage
collapse. The transition model is then trained in the accepted representation.

This is an inductive-bias argument, not a causality theorem. Joint-embedding
prediction encourages features that are predictable and useful for the training
objective; it does **not** prove that the latent contains only causally relevant
OS variables. Exact semantic facts that must not be compressed away—such as the
canonical path to `config.json`—remain deterministic predicates. The empirical
JEPA-versus-autoencoder result and the three-arm safety result are both needed:
one tests representation quality, the other tests whether that representation
changes safety decisions.

## Relation to prior safety work

| Work | Evaluation or mechanism | Layer | Difference from FerrumOS |
|---|---|---|---|
| [SafetyBench](https://arxiv.org/abs/2309.07045) | 11,435 bilingual multiple-choice questions across seven LLM-safety categories | Model knowledge/output | FerrumOS evaluates concrete state-changing OS actions, not safety knowledge in generated text |
| [Constitutional AI](https://arxiv.org/abs/2212.08073) | Supervised self-critique plus reinforcement learning from AI feedback | Model training/alignment | Complementary: a constitution shapes model behavior; FerrumOS mediates actions from any provider at runtime |
| [Agent-SafetyBench](https://arxiv.org/abs/2412.14470) | 2,000 cases in 349 tool-interaction environments | Agent/application | Broader behavioral taxonomy; FerrumOS adds an OS action gate and kernel capability backstop |
| [ST-WebAgentBench](https://arxiv.org/abs/2410.06703) | Policy compliance and risk ratio in WebArena-derived tasks | Web application | Web policy evaluation does not mediate filesystem, process, audio, device, or kernel-transition syscalls |
| [SafeDreamer](https://arxiv.org/abs/2307.07176) | World-model planning with constrained-RL/Lagrangian objectives in Safety-Gymnasium | Learned control policy | Closest world-model safety analogy, but FerrumOS filters discrete canonical OS actions without training the provider policy |

The literature comparison does not claim metric equivalence: question accuracy,
policy-compliant task completion, RL cost, and OS gate FPR/FNR measure different
objects. The defensible novelty claim is the placement and composition of the
mechanism: provider-independent action normalization, learned latent prediction,
deterministic predicates, and capability-gated execution in an agentic OS.

## Limitations and next experiments

- The registered episodes are counterfactual stress cases grounded in QEMU
  states, not 500 fresh destructive QEMU executions. A multi-week live campaign
  remains useful external validation, but it is no longer required to reproduce
  the decision-level baseline.
- The stress set uses one registered seed and authored oracle rules. Independent
  review of labels, additional seeds, confidence calibration, and a held-out
  natural-traffic prevalence study are needed before generalizing the rates.
- Runtime lookahead repeats one proposed action to H=3. It does not branch over
  distinct plans, and it does not carry a 50-action cumulative process history.
- The combined gate still misses 52/250 dangerous episodes and blocks 41/250
  safe episodes in this stress set. It must not be described as perfect,
  formally verified, or sufficient without kernel controls.
- Exact protected-path policy currently names the daemon config. The evaluation
  deliberately includes deletion of `/disk/heliox/memory.bin` as an unmodeled
  sensitive-state failure.
- Prompt-injection episodes test whether malicious provenance changes canonical
  action mediation. They are not a substitute for end-to-end browser attacks,
  poisoned observations, Unicode/path parser differentials, or compromised
  bridge authentication.
- No calibrated epistemic uncertainty or out-of-distribution detector is yet
  attached to the JEPA predictor. False-positive reduction and abstention should
  be evaluated on validation data before changing the release threshold.

Machine-readable references are in [`references.bib`](references.bib).
