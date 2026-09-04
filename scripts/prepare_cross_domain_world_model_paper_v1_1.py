#!/usr/bin/env python3
"""Prepare Technical Report v1.1 from v1.0 and the verified v14 benchmark."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/research/paper/prediction_is_not_permission_technical_report_v1_0.md"
OUTPUT = ROOT / "docs/research/paper/prediction_is_not_permission_technical_report_v1_1.md"
RESULT = ROOT / "docs/research/physical_jepa_safety_gymnasium_result_v14.json"
VERIFICATION = ROOT / "docs/research/physical_jepa_safety_gymnasium_verification_v14.json"
PAIRED_RESULT = ROOT / "docs/research/physical_jepa_safety_gymnasium_paired_uncertainty_result_v1.json"
PAIRED_VERIFICATION = ROOT / "docs/research/physical_jepa_safety_gymnasium_paired_uncertainty_verification_v1.json"


def replace_exact(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"expected exactly one source block, found {count}: {old[:80]!r}")
    return text.replace(old, new)


def pct(value: float) -> str:
    return f"{100.0 * value:.2f}%"


def main() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    verification = json.loads(VERIFICATION.read_text(encoding="utf-8"))
    paired = json.loads(PAIRED_RESULT.read_text(encoding="utf-8"))
    paired_verification = json.loads(PAIRED_VERIFICATION.read_text(encoding="utf-8"))
    if (
        result.get("all_frozen_gates_pass") is not True
        or verification.get("overall_pass") is not True
        or not all(verification.get("checks", {}).values())
        or paired_verification.get("overall_pass") is not True
        or not all(paired_verification.get("checks", {}).values())
    ):
        raise SystemExit("v14 must pass every independently recomputed frozen gate")

    headline = result["headline"]
    arms = result["arms"]
    full = arms["planner_rules_plus_learned"]["metrics"]
    naive = arms["naive_unshielded"]["metrics"]
    planner = arms["planner_unshielded"]["metrics"]
    rules = arms["planner_rules_only"]["metrics"]
    learned = arms["planner_learned_only"]["metrics"]
    seeds = result["final_seed_range"]
    seed_end = seeds["start"] + seeds["count"] - 1
    planner_reduction = (
        naive["actual_hazard_cost_events"] - planner["actual_hazard_cost_events"]
    ) / naive["actual_hazard_cost_events"]
    union_reduction = headline["actual_hazard_cost_reduction_fraction"]
    marginal_cost_delta = (
        full["actual_hazard_cost_events"] - planner["actual_hazard_cost_events"]
    )
    paired_completion = paired["differences_union_minus_planner"][
        "completion_rate_percentage_points"
    ]
    paired_hazard = paired["differences_union_minus_planner"][
        "realized_hazard_cost_steps"
    ]

    text = SOURCE.read_text(encoding="utf-8")
    text = replace_exact(
        text,
        "Technical Report v1.0 - 30 August 2026",
        "Technical Report v1.1 — 4 September 2026",
    )
    text = replace_exact(
        text,
        "A separately registered 3D PyBullet stress test produces the opposite unusable extreme: 288 interventions in 288 cases and 0% task completion.",
        (
            "A separately registered 3D PyBullet stress test produces an operationally unusable "
            "extreme: 288 interventions in 288 cases and 0% task completion. A subsequent "
            "externally designed, locally executed Safety-Gymnasium benchmark separates controller value, "
            f"warning quality, and effective action changes on {seeds['count']} untouched seeds. The privileged "
            f"planner completes {pct(planner['task_completion_rate'])} of tasks and records "
            f"{pct(planner_reduction)} fewer hazard-cost events than the naive controller. The active union "
            f"completes {pct(full['task_completion_rate'])}, changes {pct(full['intervention_rate'])} of commands, "
            f"has {pct(full['warning_recall'])} warning recall on 20-step oracle-labelled dangerous "
            "nominal-controller trajectories, and records "
            f"{pct(union_reduction)} fewer hazard-cost events than the naive controller. Relative to the planner, "
            f"it completes {full['task_completions'] - planner['task_completions']} more tasks but records "
            f"{marginal_cost_delta} additional hazard-cost steps; paired episode-bootstrap intervals for both "
            "planner-relative differences include zero."
        ),
    )
    text = replace_exact(
        text,
        "All negative results are retained, protected deployed artifacts remain byte-identical, and promotion eligibility is false.",
        (
            "All negative and failed frozen attempts are retained, the planner-only contrast and active-union "
            "tradeoff are reported together, protected deployed artifacts "
            "remain byte-identical, and promotion eligibility is false."
        ),
    )
    text = replace_exact(
        text,
        "learned operational safety value at the frozen operating point.",
        (
            "independent replication, physical deployment safety, or a learned collision-avoidance advantage "
            "over the privileged planner: the union passes its registered naive-baseline objective, but its "
            "completion gain over the planner accompanies higher realized hazard cost."
        ),
    )
    text = replace_exact(
        text,
        "The present work adds an architecture-controlled comparison, paired temporal interventions, uncertainty and calibration analysis, authority-disabled runtime tests, externally authored data intake, and retained negative stress tests.",
        (
            "The present work adds an architecture-controlled comparison, paired temporal interventions, "
            "uncertainty and calibration analysis, authority-disabled runtime tests, externally authored "
            "data intake, retained negative stress tests, and a prospective useful-autonomy evaluation in "
            "the externally maintained Safety-Gymnasium task environment [17]."
        ),
    )
    text = replace_exact(
        text,
        "This report contributes five things.",
        "This report contributes six things.",
    )
    text = replace_exact(
        text,
        "Fifth, it reports operational negatives as primary results: zero learned marginal interventions at the conservative frozen threshold, no deployment promotion, semantic incompatibility of an external robotics corpus, and a 3D test whose 100% intervention rate makes its apparent collision avoidance practically uninformative.",
        (
            "Fifth, it reports operational negatives as primary results: zero learned marginal interventions "
            "at the conservative frozen threshold, no deployment promotion, semantic incompatibility of an "
            "external robotics corpus, and a 3D test whose 100% intervention rate makes its apparent collision "
            "avoidance practically uninformative. Sixth, it prospectively freezes a joint completion, "
            "intervention, recall, false-positive, and realized-cost objective, retains every failed or "
            "non-beneficial protocol stage, and reports a once-opened Safety-Gymnasium final where the "
            "selected union passes the registered joint objective while remaining worse than the privileged "
            "planner on realized hazard cost."
        ),
    )
    text = replace_exact(
        text,
        "The final temporal catalogs and the 3D stress benchmark are researcher-designed deterministic-software evaluations.",
        (
            "The final temporal catalogs and 3D stress benchmark are researcher-designed deterministic-software "
            "evaluations. Safety-Gymnasium supplies an external task definition, layouts, observations, and "
            "hazard costs, but the adapter, privileged planner, shield, local execution, and analysis are "
            "researcher-authored."
        ),
    )
    text = replace_exact(
        text,
        "Physical evaluation has three separate components.",
        "Physical evaluation has four separate components.",
    )
    text = replace_exact(
        text,
        "A local PyBullet DIRECT stress test varies bodies, obstacles, mass, 3D targets, contact, and return-to-start recovery with physical actuator authority disabled.",
        (
            "A local PyBullet DIRECT stress test varies bodies, obstacles, mass, 3D targets, contact, and "
            "return-to-start recovery with physical actuator authority disabled. Finally, Safety-Gymnasium "
            "v1.0.0 supplies the externally maintained SafetyPointGoal1-v0 task and simulator costs. A "
            "registered adapter compares a naive local controller, a privileged deterministic grid planner, "
            "rules-only and learned-only shields, and their monotone union while keeping actuator authority zero."
        ),
    )

    safety_section = f"""#### 8.4 Prospective Safety-Gymnasium controller and shield benchmark

The v14 amendment freezes Safety-Gymnasium v1.0.0, Gymnasium 0.28.1, MuJoCo 2.3.3, the installed simulator-source digest, the protected Physical JEPA v5 digest, a deterministic risk adapter fitted on opened seeds 4000-4095, candidate choice on opened seeds 4096-4127, and untouched final seeds {seeds['start']}-{seed_end}. The 20-step oracle rolls out the nominal receding-horizon controller from synchronized simulator state; it does not repeat the current command for 20 steps. Warning recall and warning FPR evaluate the detector, whereas intervention rate counts only commands that actually change. The external project supplies the task, layouts, observations, goal condition, and hazard costs [17]. This study supplies the adapter, privileged planner, tangent shield, execution, and analysis. Execution is local, actuator authority is disabled, and no independent replication is claimed.

| Final arm | Completion | Effective intervention | Warning recall | Warning FPR | Effective-action recall | Hazard-cost events |
|---|---:|---:|---:|---:|---:|---:|
| Naive unshielded | {pct(naive['task_completion_rate'])} | {pct(naive['intervention_rate'])} | {pct(naive['warning_recall'])} | {pct(naive['warning_false_positive_rate'])} | {pct(naive['effective_intervention_recall'])} | {naive['actual_hazard_cost_events']} |
| Planner unshielded | {pct(planner['task_completion_rate'])} | {pct(planner['intervention_rate'])} | {pct(planner['warning_recall'])} | {pct(planner['warning_false_positive_rate'])} | {pct(planner['effective_intervention_recall'])} | **{planner['actual_hazard_cost_events']}** |
| Planner + rules | {pct(rules['task_completion_rate'])} | {pct(rules['intervention_rate'])} | {pct(rules['warning_recall'])} | {pct(rules['warning_false_positive_rate'])} | {pct(rules['effective_intervention_recall'])} | {rules['actual_hazard_cost_events']} |
| Planner + learned | **{pct(learned['task_completion_rate'])}** | {pct(learned['intervention_rate'])} | **{pct(learned['warning_recall'])}** | {pct(learned['warning_false_positive_rate'])} | {pct(learned['effective_intervention_recall'])} | {learned['actual_hazard_cost_events']} |
| Planner + rules + learned | **{pct(full['task_completion_rate'])}** | {pct(full['intervention_rate'])} | **{pct(full['warning_recall'])}** | {pct(full['warning_false_positive_rate'])} | {pct(full['effective_intervention_recall'])} | {full['actual_hazard_cost_events']} |

The union passes every registered joint-objective gate relative to the frozen benchmark criteria; these gates do not require superiority over the privileged planner: {pct(full['task_completion_rate'])} completion, {pct(full['intervention_rate'])} effective intervention, {pct(full['warning_recall'])} warning recall, {pct(full['warning_false_positive_rate'])} warning FPR, and {pct(union_reduction)} fewer hazard-cost events than the naive controller ({naive['actual_hazard_cost_events']} to {full['actual_hazard_cost_events']}). Its effective action-change recall is {pct(full['effective_intervention_recall'])} ({full['true_positive_interventions']}/{full['dangerous_proposals']}): warned dangerous proposals do not count as interventions when the tangent command is already identical to the planner command. Its episode-bootstrap 95% intervals are {pct(full['episode_bootstrap_95']['task_completion_rate'][0])}-{pct(full['episode_bootstrap_95']['task_completion_rate'][1])} for completion, {pct(full['episode_bootstrap_95']['intervention_rate'][0])}-{pct(full['episode_bootstrap_95']['intervention_rate'][1])} for intervention, {pct(full['episode_bootstrap_95']['dangerous_proposal_recall'][0])}-{pct(full['episode_bootstrap_95']['dangerous_proposal_recall'][1])} for warning recall, and {pct(full['episode_bootstrap_95']['safe_proposal_false_positive_rate'][0])}-{pct(full['episode_bootstrap_95']['safe_proposal_false_positive_rate'][1])} for warning FPR. No final rerun or recovery path was used.

Relative to the privileged planner, the union changes completion by {paired_completion['estimate']:+.4f} percentage points (paired 10,000-resample episode-bootstrap 95% CI [{paired_completion['bootstrap_95_percent'][0]:.4f}, {paired_completion['bootstrap_95_percent'][1]:.4f}]) and realized hazard cost by {paired_hazard['estimate']:+.0f} steps (95% CI [{paired_hazard['bootstrap_95_percent'][0]:.3f}, {paired_hazard['bootstrap_95_percent'][1]:.3f}]). Neither interval excludes zero, so the observed two-task gain and 14-step increase are descriptive rather than statistically stable at this sample size.

Attribution remains essential. The privileged planner alone reduces hazard cost from {naive['actual_hazard_cost_events']} to {planner['actual_hazard_cost_events']} ({pct(planner_reduction)}). Adding the learned tangent branch increases completion from {planner['task_completions']}/{seeds['count']} to {full['task_completions']}/{seeds['count']} but increases hazard-cost events from {planner['actual_hazard_cost_events']} to {full['actual_hazard_cost_events']} (plus {marginal_cost_delta}). All {headline['learned_only_interventions']} effective union interventions are learned-only because the high-closeness rule never changes a command on this final distribution. The adapter warns on {full['true_positive_warnings']}/{full['dangerous_proposals']} dangerous controller trajectories, while {full['true_positive_interventions']}/{full['dangerous_proposals']} receive a different command; the remaining warned cases already propose the saturated tangent-compatible turn. The benchmark therefore supports a passing naive-baseline runtime objective and a completion/cost tradeoff over the planner, not learned collision-avoidance superiority over privileged planning.

"""
    text = replace_exact(text, "### 9. Cross-domain synthesis", safety_section + "### 9. Cross-domain synthesis")
    text = replace_exact(
        text,
        "The new 512-case catalogs show no interventions from either rules or learning. The 3D stress shows intervention on every case. One extreme has no hazard recall; the other has no task completion. Together they show why a shield should be evaluated on both avoided harm and intervention cost at a registered operating point. Deterministic authority is necessary as a control boundary but is not automatically sufficient as an engineering policy.",
        (
            "The new 512-case catalogs show no interventions from either rules or learning, while the 3D stress "
            "intervenes on every case. The prospective Safety-Gymnasium result separates a useful privileged "
            "planner-only controller from an active union that passes the naive-baseline objective but trades "
            "higher completion for higher hazard cost relative to the planner. The contrast shows why controller "
            "quality cannot be credited to a shield and why warning recall cannot substitute for marginal executed "
            "outcomes. These three outcomes show why deterministic authority must be "
            "evaluated with task completion, intervention, proposal recall, false positives, realized cost, and "
            "controller divergence rather than a collision count alone."
        ),
    )
    text = replace_exact(
        text,
        "Recorded sensors are not live HIL. PyBullet contact is not physical collision evidence.",
        (
            "Recorded sensors are not live HIL. PyBullet contact is not physical collision evidence. An "
            "externally maintained simulator task executed by the author is not an independent replication, and "
            "a planner with direct simulator geometry is not a sensor-only robot controller."
        ),
    )
    text = replace_exact(
        text,
        "The final temporal catalogs and 3D benchmark use deterministic simulator labels designed locally. They are blinded after registration but not independently designed or assessed.",
        (
            "The final temporal catalogs and 3D benchmark use deterministic simulator labels designed locally. "
            "Safety-Gymnasium improves task and cost provenance, but its adapter, controller, shield, execution, "
            "and assessment remain local; no independent replication is claimed."
        ),
    )
    text = replace_exact(
        text,
        "4. The operational zero-result is threshold-specific. Lower thresholds could increase recall and false positives, but selecting one after final access would invalidate the frozen operating-point claim.",
        (
            "4. The 512-case operational zero-result remains threshold-specific. The later Safety-Gymnasium "
            "protocol selects a different registered navigation operating point on development seeds and evaluates "
            "it once on untouched seeds; it does not retroactively repair the earlier estimand."
        ),
    )
    text = replace_exact(
        text,
        "9. The PyBullet environment is locally designed and simple relative to robotics benchmarks. Its 100% intervention rate and 0% completion make it a negative stress test, not evidence of practical collision avoidance.",
        (
            "9. The PyBullet environment is locally designed and simple relative to robotics benchmarks. Its "
            "100% intervention rate and 0% completion remain a negative stress result. Safety-Gymnasium adds an "
            "external task implementation, but only the Point navigation subset is covered."
        ),
    )
    text = replace_exact(
        text,
        "10. Deterministic rules are engineering predicates, not formally verified invariants. The empirical absence of an effect does not prove that every execution path is impossible.",
        (
            "10. The strongest Safety-Gymnasium controller uses direct simulator geometry in a deterministic "
            "grid planner. Its high proposal divergence must not be confused with low shield intervention or "
            "sensor-only deployability. Deterministic rules remain engineering predicates, not formally verified invariants."
        ),
    )
    text = replace_exact(
        text,
        "11. No protected research result was promoted. The report therefore evaluates a research lineage, not a deployed policy change.",
        (
            "11. No live actuator timing, physical contact, hardware emergency stop, actuator dynamics, sensor-interface "
            "latency, human-contact dynamics, or independent execution is established. The report remains a "
            "CPS/runtime-assurance study, not a robotics-deployment study.\n\n"
            "12. No protected research result was promoted. The report therefore evaluates a research lineage, not a deployed policy change."
        ),
    )
    text = replace_exact(
        text,
        "python scripts/verify_physical_jepa_multi_embodiment_3d.py\n",
        (
            "python scripts/verify_physical_jepa_multi_embodiment_3d.py\n"
            "python scripts/verify_physical_jepa_safety_gymnasium_v14.py\n"
            "python scripts/evaluate_physical_jepa_safety_gymnasium_paired_uncertainty.py\n"
            "python scripts/verify_physical_jepa_safety_gymnasium_paired_uncertainty.py\n"
        ),
    )
    text = replace_exact(
        text,
        "used for Technical Report v1.0.",
        "used for Technical Report v1.1.",
    )
    text = replace_exact(
        text,
        "This report finds a real architecture-controlled advantage for Physical JEPA and a different ranking in FerrumOS. It also finds that neither selected learned model adds a single intervention at the frozen conservative operating point. The 3D stress test fails in the opposite direction by stopping every task. Those are not contradictory results. They locate three different engineering problems: learning dynamics, calibrating decisions under shift, and designing authority policies that preserve both safety and useful completion.",
        (
            "This report finds a real architecture-controlled advantage for Physical JEPA and a different ranking "
            "in FerrumOS. It also finds zero learned intervention at the original conservative operating point and "
            "an all-stop failure in the 3D stress test. In the later prospective Safety-Gymnasium benchmark, the "
            f"privileged planner alone reaches {pct(planner['task_completion_rate'])} completion with "
            f"{pct(planner_reduction)} fewer realized hazard-cost events than the naive baseline. The active "
            f"union passes the registered objective with {pct(full['warning_recall'])} warning recall and "
            f"{pct(union_reduction)} lower hazard cost than naive, but adds {marginal_cost_delta} hazard-cost steps "
            "relative to the planner while completing two additional tasks; the paired 95% intervals for both "
            "planner-relative differences include zero. "
            "These results locate distinct engineering problems: learning dynamics, "
            "calibrating decisions under shift, designing useful authority policies, and separating planner effects "
            "from shield and learned-model effects."
        ),
    )
    text = replace_exact(
        text,
        "and deployment remains unchanged unless every frozen gate supports promotion. In this study, they do not.",
        (
            "and deployment remains unchanged unless a separate prospective deployment protocol passes. The "
            "union passes this software benchmark, but the privileged-planner marginal tradeoff and absence of "
            "HIL or independent execution keep every research artifact explicitly ineligible for promotion."
        ),
    )
    old_next = """#### 12.2 Highest-value next evidence

The next study should not add another locally designed benchmark merely to increase case count. It should target the two observed decision failures: no recall at the conservative shifted threshold and no completion under the 3D all-stop policy. A blinded benchmark should freeze a useful-operating-region objective before data access, jointly requiring materially lower harmful outcomes, high task completion, and low intervention. Calibration should be fitted without final access and reported with uncertainty. For the physical lineage, actuator-disabled live HIL with measured sensor latency, actuator-interface timing, independent emergency stop, and recorded physical clocks is the shortest path to a stronger evidence class. For FerrumOS, a longer independently operated natural-use study and a concurrent inference implementation are higher value than additional synthetic prompts.

| Priority | Frozen success criterion | Why it changes the evidence tier |
|---|---|---|
| Blinded useful-autonomy benchmark | High completion, lower harmful outcomes, low intervention | Replaces the zero-recall/all-stop extremes with a joint operating objective |
| Actuator-disabled live HIL | Physical clocks and interfaces observed; authority remains zero | Adds live integration without claiming autonomous actuation |
| Independent execution and assessment | Protocol run and labels controlled outside the author workflow | Reduces local-design and researcher-operation bias |
| Calibration under shift | Pre-registered threshold with reliability and uncertainty intervals | Tests whether predictive skill becomes stable decision value |
| FerrumOS concurrent preview | Bounded latency under independent clients with no leakage | Addresses the measured serial contention bottleneck |
"""
    new_next = """#### 12.2 Remaining evidence tier

The prospective joint objective now passes on an external simulator task, while the planner-relative comparison remains a completion/cost tradeoff rather than learned collision-avoidance superiority. Another local seed range or threshold sweep has low scientific value. The next evidence-class changes are a controller/shield design fixed before an externally executed benchmark, actuator-disabled live HIL with physical clocks and interfaces, and execution of a frozen protocol by an independent party. For FerrumOS, independently operated longitudinal use and concurrent preview remain more valuable than additional synthetic prompts. These are next-tier studies, not claims that can be fabricated inside the present software-only report.
"""
    text = replace_exact(text, old_next, new_next)
    text = replace_exact(
        text,
        "| 3D geometry/contact stress is exercised | 288 local PyBullet DIRECT cases | Contact and simulated recovery are measured | Not practical learned safety at 100% intervention |",
        (
            "| 3D geometry/contact stress is exercised | 288 local PyBullet DIRECT cases | Contact and simulated "
            "recovery are measured | Not practical learned safety at 100% intervention |\n"
            f"| Controller and shield are jointly evaluated | Safety-Gymnasium final seeds {seeds['start']}-{seed_end} | "
            f"Planner-only: {pct(planner['task_completion_rate'])} completion and {pct(planner_reduction)} cost "
            f"reduction; union passes all registered naive-baseline gates with {pct(full['warning_recall'])} warning "
            f"recall, but costs {marginal_cost_delta} more hazard steps than planner | Not independent, sensor-only, "
            "physical, or learned-superiority evidence |"
        ),
    )
    text = replace_exact(
        text,
        "A scientific negative is a completed comparison whose registered estimand does not support the hoped-for effect, as in zero learned marginal caution.",
        (
            "A scientific negative is a completed comparison whose registered estimand does not support the hoped-for "
            "effect, as in zero learned marginal caution. A gate pass can still contain a negative marginal contrast, "
            "as v14 does when the union improves completion but worsens hazard cost relative to the planner."
        ),
    )
    text = replace_exact(
        text,
        "| 3D stress | Bodies, obstacles, cases, recovery rule | All outcomes and Wilson intervals retained | PyBullet DIRECT; actuator authority zero |",
        (
            "| 3D stress | Bodies, obstacles, cases, recovery rule | All outcomes and Wilson intervals retained | "
            "PyBullet DIRECT; actuator authority zero |\n"
            "| External useful-autonomy test | Runtime lock, dev/final seeds, candidates, five arms, joint gates | "
            "One untouched final opening; raw union rows and all arms independently recompute | Safety-Gymnasium "
            "DIRECT; privileged planner; actuator authority zero |\n"
            "| Paired planner-union uncertainty | Seed pairing, estimands, 10,000 resamples, bootstrap seed | "
            "Completion and hazard-cost differences independently recompute; both intervals include zero | "
            "Post-hoc analysis of committed episode summaries; no final rerun |"
        ),
    )
    text = replace_exact(text, "Technical Report v1.0 is intended", "Technical Report v1.1 is intended")
    text = replace_exact(
        text,
        "| 3D stress result | `docs/research/physical_jepa_multi_embodiment_3d_result_v1.json` | Recompute completion, intervention, contact and recovery |",
        (
            "| 3D stress result | `docs/research/physical_jepa_multi_embodiment_3d_result_v1.json` | Recompute "
            "completion, intervention, contact and recovery |\n"
            "| External useful-autonomy protocol | `docs/research/physical_jepa_safety_gymnasium_protocol_v14.json` | "
            "Inspect runtime lock, seed boundary, candidate policy and frozen joint gates |\n"
            "| External useful-autonomy result | `docs/research/physical_jepa_safety_gymnasium_result_v14.json` | "
            "Recompute five arms, planner divergence, learned-only attribution and realized-cost reduction |\n"
            "| External useful-autonomy verification | `docs/research/physical_jepa_safety_gymnasium_verification_v14.json` | "
            "Confirm raw cases, exact seeds, hashes, gates, authority zero and non-promotion |\n"
            "| Paired planner-union uncertainty | `docs/research/physical_jepa_safety_gymnasium_paired_uncertainty_result_v1.json` | "
            "Recompute seed-matched completion and realized hazard-cost difference intervals |"
        ),
    )
    text = replace_exact(
        text,
        "Continue to the runtime and physical records only for the integration claims they support.",
        (
            "Continue to the runtime and physical records only for the integration claims they support. In the "
            "Safety-Gymnasium evidence, compare all five arms and planner divergence before attributing any outcome "
            "to the learned branch."
        ),
    )
    text = replace_exact(
        text,
        '[1] M. Assran et al. "V-JEPA: Latent Video Prediction for Visual Representation Learning." arXiv:2404.08471, 2024. https://arxiv.org/abs/2404.08471',
        (
            '[1] A. Bardes, Q. Garrido, J. Ponce, X. Chen, M. Rabbat, Y. LeCun, M. Assran, and N. Ballas. '
            '"Revisiting Feature Prediction for Learning Visual Representations from Video." arXiv:2404.08471, 2024. '
            'https://arxiv.org/abs/2404.08471'
        ),
    )
    text += (
        "\n[17] Safety-Gymnasium Contributors. \"Safety-Gymnasium: A Unified Safe Reinforcement Learning "
        "Benchmark.\" Thirty-seventh Conference on Neural Information Processing Systems Datasets and "
        "Benchmarks Track, 2023. https://openreview.net/forum?id=WZmlxIuIGR\n"
    )
    text = replace_exact(
        text,
        "The study extends two artifact-backed FerrumOS research lineages. The operating-system lineage evaluates action-conditioned forecasts in the unprivileged Heliox daemon before capability-gated kernel effects. The physical lineage evaluates a compact world model in simulated and recorded-sensor settings while disabling actuator authority. Both lineages already retain failed iterations and distinguish learned caution from deterministic control. The present work adds an architecture-controlled comparison, paired temporal interventions, uncertainty and calibration analysis, authority-disabled runtime tests, externally authored data intake, retained negative stress tests, and a prospective useful-autonomy evaluation in the externally maintained Safety-Gymnasium task environment [17].",
        "The study extends two artifact-backed FerrumOS lineages: unprivileged action-conditioned OS forecasts before capability-gated effects, and a compact physical model evaluated with actuator authority disabled. It adds matched architectures, paired interventions, calibration, authority-disabled runtime tests, external-data intake, retained negative stress tests, and a prospective Safety-Gymnasium evaluation [17].",
    )
    text = replace_exact(
        text,
        "The final temporal catalogs and 3D stress benchmark are researcher-designed deterministic-software evaluations. Safety-Gymnasium supplies an external task definition, layouts, observations, and hazard costs, but the adapter, privileged planner, shield, local execution, and analysis are researcher-authored. The external physical evidence is recorded sensor replay, not live Ferrum hardware-in-the-loop. FerrumOS evidence comes from disposable QEMU guests and short researcher-operated sessions, not production users. No experiment establishes formal safety, independent assessment, human-contact safety, broad embodiment transfer, or a universally superior architecture. The selected research artifacts are not deployed, and no protected deployed artifact is replaced.",
        "The temporal catalogs and 3D stress are locally designed software tests. Safety-Gymnasium supplies the task and costs, but the adapter, privileged planner, shield, execution, and analysis are local. Physical evidence is replay, not live HIL; FerrumOS evidence is disposable QEMU, not production use. No result establishes formal, independent, human-contact, broad-transfer, or deployment safety, and no protected artifact is replaced.",
    )
    text = replace_exact(
        text,
        "No shielded contact in this run should be read as a zero underlying collision probability.",
        "No shielded contact was observed in this run; this does not establish a zero underlying collision probability.",
    )
    if "reviewer-requested" in text.lower() or "opposite unusable extreme" in text.lower():
        raise ValueError("forbidden archival wording remains")
    OUTPUT.write_text(text, encoding="utf-8", newline="\n")
    print(OUTPUT.relative_to(ROOT).as_posix())


if __name__ == "__main__":
    main()
