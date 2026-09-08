#!/usr/bin/env python3
"""Prepare Technical Report v1.1 from v1.0 and the complete verified evidence chain."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT / "docs/research/paper/prediction_is_not_permission_technical_report_v1_0.md"
)
OUTPUT = (
    ROOT / "docs/research/paper/prediction_is_not_permission_technical_report_v1_1.md"
)
RESULT = ROOT / "docs/research/physical_jepa_safety_gymnasium_result_v14.json"
VERIFICATION = (
    ROOT / "docs/research/physical_jepa_safety_gymnasium_verification_v14.json"
)
PAIRED_RESULT = (
    ROOT
    / "docs/research/physical_jepa_safety_gymnasium_paired_uncertainty_result_v1.json"
)
PAIRED_VERIFICATION = (
    ROOT
    / "docs/research/physical_jepa_safety_gymnasium_paired_uncertainty_verification_v1.json"
)
LEARNED_CONTRIBUTION = (
    ROOT / "docs/research/cross_domain_learned_contribution_result_v1.json"
)
ARCHITECTURE_SELECTION = ROOT / "docs/research/cross_domain_world_model_selection_v1.json"
ARCHITECTURE_RESULT = ROOT / "docs/research/cross_domain_world_model_architecture_result_v1.json"
ATTRIBUTION_RESULT = (
    ROOT / "docs/research/physical_jepa_safety_gymnasium_attribution_result_v2.json"
)
ATTRIBUTION_VERIFICATION = (
    ROOT / "docs/research/physical_jepa_safety_gymnasium_attribution_verification_v2.json"
)
POSTHOC_RESULT = (
    ROOT / "docs/research/cross_domain_world_model_posthoc_sensitivity_result_v1.json"
)
POSTHOC_VERIFICATION = (
    ROOT
    / "docs/research/cross_domain_world_model_posthoc_sensitivity_verification_v1.json"
)
AUTHORITY_TEST_INVENTORY = (
    ROOT / "docs/research/cross_domain_authority_test_inventory_v1.json"
)


def replace_exact(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(
            f"expected exactly one source block, found {count}: {old[:80]!r}"
        )
    return text.replace(old, new)


def replace_section(text: str, start: str, end: str, replacement: str) -> str:
    left = text.find(start)
    if left < 0:
        raise ValueError(f"section start not found: {start!r}")
    right = text.find(end, left + len(start))
    if right < 0:
        raise ValueError(f"section end not found: {end!r}")
    return text[:left] + replacement.rstrip() + "\n\n" + text[right:]


def pct(value: float) -> str:
    return f"{100.0 * value:.2f}%"


def main() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    verification = json.loads(VERIFICATION.read_text(encoding="utf-8"))
    paired = json.loads(PAIRED_RESULT.read_text(encoding="utf-8"))
    paired_verification = json.loads(PAIRED_VERIFICATION.read_text(encoding="utf-8"))
    learned_contribution = json.loads(LEARNED_CONTRIBUTION.read_text(encoding="utf-8"))
    architecture_selection = json.loads(ARCHITECTURE_SELECTION.read_text(encoding="utf-8"))
    architecture_result = json.loads(ARCHITECTURE_RESULT.read_text(encoding="utf-8"))
    attribution = json.loads(ATTRIBUTION_RESULT.read_text(encoding="utf-8"))
    attribution_verification = json.loads(
        ATTRIBUTION_VERIFICATION.read_text(encoding="utf-8")
    )
    posthoc = json.loads(POSTHOC_RESULT.read_text(encoding="utf-8"))
    posthoc_verification = json.loads(POSTHOC_VERIFICATION.read_text(encoding="utf-8"))
    authority_inventory = json.loads(AUTHORITY_TEST_INVENTORY.read_text(encoding="utf-8"))
    if (
        result.get("all_frozen_gates_pass") is not True
        or verification.get("overall_pass") is not True
        or not all(verification.get("checks", {}).values())
        or paired_verification.get("overall_pass") is not True
        or not all(paired_verification.get("checks", {}).values())
        or learned_contribution.get("evaluation_passed") is not True
        or learned_contribution.get("final_open_count") != 1
        or architecture_selection.get("selection_passed") is not True
        or architecture_result.get("evaluation_passed") is not True
        or attribution_verification.get("all_checks_pass") is not True
        or not all(attribution_verification.get("checks", {}).values())
        or attribution.get("final_seed_access_count") != 1
        or attribution.get("authority", {}).get("promotion_eligible") is not False
        or posthoc_verification.get("all_checks_pass") is not True
        or not all(posthoc_verification.get("checks", {}).values())
        or posthoc.get("authority", {}).get("promotion_eligible") is not False
        or authority_inventory.get("all_checks_pass") is not True
    ):
        raise SystemExit("the complete frozen evidence chain must verify")

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
    intervention_precision = full["true_positive_interventions"] / full["interventions"]
    attribution_baseline = attribution["baseline_planner_unshielded"]
    attribution_variants = attribution["variants"]
    attribution_full = attribution_variants["full-frozen-v14-adapter"]
    attribution_local = attribution_variants["local-sensing-without-jepa"]
    attribution_jepa = attribution_variants["jepa-outputs-only"]
    attribution_geometry = attribution_variants["hazard-closeness-only"]
    jepa_vs_full = attribution_jepa["versus_full_adapter_paired_bootstrap"]
    posthoc_attribution = posthoc["attribution_diagnostics"]
    posthoc_jepa = posthoc_attribution["comparisons"][
        "jepa-outputs-only_minus_full"
    ]
    posthoc_jepa_adjusted = posthoc_jepa["bonferroni_98_333333_percent"]
    posthoc_jepa_directions = posthoc_jepa["paired_episode_directions"]
    posthoc_jepa_loo = posthoc_attribution[
        "jepa_outputs_only_minus_full_leave_one_out"
    ]
    common_warning = posthoc_attribution["common_proposal_warning_analysis"]
    common_ferrumos = posthoc["common_episode_horizon_analysis"]["domains"][
        "ferrumos"
    ]
    expected_families = {
        "ferrumos": {
            "delayed_heap_pressure",
            "delayed_process_pressure",
            "coupled_resource_pressure",
            "exogenous_heap_degradation",
        },
        "physical": {
            "delayed_battery_depletion",
            "delayed_boundary_crossing",
            "sensor_masked_human_approach",
            "link_degradation",
        },
    }
    for domain, families in expected_families.items():
        records = learned_contribution["domains"][domain]["case_records"]
        if {row["family"] for row in records} != families or any(
            row["rule_block"] for row in records
        ):
            raise SystemExit(f"unexpected deterministic-rule coverage in {domain}")

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
            f"nominal-controller trajectories and {pct(full['effective_intervention_recall'])} effective-action "
            "recall, and records "
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
        "The learned branch adds zero dangerous-case blocks and zero safe-case interventions. The Wilson 95% upper bound for either marginal rate is 1.478%, and the 5,000-pair bootstrap interval is [0, 0]. This is not a verifier failure: the registered programs completed, final catalogs were opened once, and the estimates are finite. It is a substantive negative result. At this operating point, neither selected learned model provides deployable marginal caution.",
        (
            "The learned branch adds zero dangerous-case blocks and zero safe-case interventions. The Wilson "
            "95% upper bound for either marginal rate is 1.478%, and the 5,000-pair bootstrap interval is "
            "[0, 0]. All eight final families are delayed, coupled, masked, or exogenous: their danger labels "
            "materialize in later transitions, whereas the deterministic predicates inspect the current state "
            "and requested action. Consequently, `rule_block` is false in all 1,024 domain-case records by "
            "construction of this estimand; rules-only recall here is not an estimate of general rule quality. "
            "At the zero-FP-calibrated threshold, the learned branch also does not extend the authority boundary "
            "into this delayed-hazard regime, making the union arm uninformative because neither branch fires. "
            "This is a construct-coverage negative about threshold-based caution under latent hazards, not merely "
            "a completed program with finite zero estimates. No final-set retuning or deployment promotion follows."
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

The v14 amendment freezes Safety-Gymnasium v1.0.0, Gymnasium 0.28.1, MuJoCo 2.3.3, the installed simulator-source digest, the protected Physical JEPA v5 digest, a deterministic risk adapter fitted on opened seeds 4000-4095, candidate choice on opened seeds 4096-4127, and untouched final seeds {seeds["start"]}-{seed_end}. The 20-step oracle rolls out the nominal receding-horizon controller from synchronized simulator state; it does not repeat the current command for 20 steps. Warning recall and warning FPR evaluate the detector, whereas intervention rate counts only commands that actually change. The external project supplies the task, layouts, observations, goal condition, and hazard costs [17]. This study supplies the adapter, privileged planner, tangent shield, execution, and analysis. Execution is local, actuator authority is disabled, and no independent replication is claimed.

| Final arm | Completion | Effective intervention | Warning recall | Warning FPR | Effective-action recall | Hazard-cost events |
|---|---:|---:|---:|---:|---:|---:|
| Naive unshielded | {pct(naive["task_completion_rate"])} | {pct(naive["intervention_rate"])} | — | — | {pct(naive["effective_intervention_recall"])} | {naive["actual_hazard_cost_events"]} |
| Planner unshielded | {pct(planner["task_completion_rate"])} | {pct(planner["intervention_rate"])} | — | — | {pct(planner["effective_intervention_recall"])} | **{planner["actual_hazard_cost_events"]}** |
| Planner + rules | {pct(rules["task_completion_rate"])} | {pct(rules["intervention_rate"])} | {pct(rules["warning_recall"])} | {pct(rules["warning_false_positive_rate"])} | {pct(rules["effective_intervention_recall"])} | {rules["actual_hazard_cost_events"]} |
| Planner + learned | **{pct(learned["task_completion_rate"])}** | {pct(learned["intervention_rate"])} | **{pct(learned["warning_recall"])}** | {pct(learned["warning_false_positive_rate"])} | {pct(learned["effective_intervention_recall"])} | {learned["actual_hazard_cost_events"]} |
| Planner + rules + learned | **{pct(full["task_completion_rate"])}** | {pct(full["intervention_rate"])} | **{pct(full["warning_recall"])}** | {pct(full["warning_false_positive_rate"])} | {pct(full["effective_intervention_recall"])} | {full["actual_hazard_cost_events"]} |

The union passes every registered joint-objective gate relative to the frozen benchmark criteria; these gates do not require superiority over the privileged planner: {pct(full["task_completion_rate"])} completion, {pct(full["intervention_rate"])} effective intervention, {pct(full["warning_recall"])} warning recall, {pct(full["warning_false_positive_rate"])} warning FPR, and {pct(union_reduction)} fewer hazard-cost events than the naive controller ({naive["actual_hazard_cost_events"]} to {full["actual_hazard_cost_events"]}). Its effective action-change recall is {pct(full["effective_intervention_recall"])} ({full["true_positive_interventions"]}/{full["dangerous_proposals"]}): warned dangerous proposals do not count as interventions when the tangent command is already identical to the planner command. Executed intervention precision is {pct(intervention_precision)} ({full["true_positive_interventions"]}/{full["interventions"]}): {full["false_positive_interventions"]} of {full["interventions"]} changed commands occur on oracle-labelled non-dangerous trajectories. That low precision is mechanistically consistent with the observed planner-relative hazard-cost increase, but the design does not identify causality and the paired interval includes zero. Its episode-bootstrap 95% intervals are {pct(full["episode_bootstrap_95"]["task_completion_rate"][0])}-{pct(full["episode_bootstrap_95"]["task_completion_rate"][1])} for completion, {pct(full["episode_bootstrap_95"]["intervention_rate"][0])}-{pct(full["episode_bootstrap_95"]["intervention_rate"][1])} for intervention, {pct(full["episode_bootstrap_95"]["dangerous_proposal_recall"][0])}-{pct(full["episode_bootstrap_95"]["dangerous_proposal_recall"][1])} for warning recall, and {pct(full["episode_bootstrap_95"]["safe_proposal_false_positive_rate"][0])}-{pct(full["episode_bootstrap_95"]["safe_proposal_false_positive_rate"][1])} for warning FPR. No final rerun or recovery path was used.

Relative to the privileged planner, the union changes completion by {paired_completion["estimate"]:+.4f} percentage points (paired 10,000-resample episode-bootstrap 95% CI [{paired_completion["bootstrap_95_percent"][0]:.4f}, {paired_completion["bootstrap_95_percent"][1]:.4f}]) and realized hazard cost by {paired_hazard["estimate"]:+.0f} steps (95% CI [{paired_hazard["bootstrap_95_percent"][0]:.3f}, {paired_hazard["bootstrap_95_percent"][1]:.3f}]). Neither interval excludes zero, so the observed two-task gain and 14-step increase are descriptive rather than statistically stable at this sample size.

Attribution remains essential. The privileged planner alone reduces hazard cost from {naive["actual_hazard_cost_events"]} to {planner["actual_hazard_cost_events"]} ({pct(planner_reduction)}). Adding the learned tangent branch increases completion from {planner["task_completions"]}/{seeds["count"]} to {full["task_completions"]}/{seeds["count"]} but increases hazard-cost events from {planner["actual_hazard_cost_events"]} to {full["actual_hazard_cost_events"]} (plus {marginal_cost_delta}). All {headline["learned_only_interventions"]} effective union interventions are learned-only because the high-closeness rule never changes a command on this final distribution. The adapter warns on {full["true_positive_warnings"]}/{full["dangerous_proposals"]} dangerous controller trajectories, while {full["true_positive_interventions"]}/{full["dangerous_proposals"]} receive a different command; the remaining warned cases already propose the saturated tangent-compatible turn. The benchmark therefore supports a passing naive-baseline runtime objective and a completion/cost tradeoff over the planner, not learned collision-avoidance superiority over privileged planning.

"""
    text = replace_exact(
        text,
        "### 9. Cross-domain synthesis",
        safety_section + "### 9. Cross-domain synthesis",
    )
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
            "4. The 512-case operational zero-result remains threshold-specific. The 512-case "
            "families also sit outside the present-state deterministic predicates' evaluation window, so their "
            "rules-only zero is a catalog-coverage property rather than a general estimate of rule quality. The "
            "later Safety-Gymnasium protocol selects a different registered navigation operating point on "
            "development seeds and evaluates it once on untouched seeds; it does not retroactively repair the "
            "earlier estimand."
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
            f"recall, {pct(full['effective_intervention_recall'])} effective-action recall, and "
            f"{pct(intervention_precision)} intervention precision, but costs {marginal_cost_delta} more hazard "
            "steps than planner | Not independent, sensor-only, "
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
    text = replace_exact(
        text, "Technical Report v1.0 is intended", "Technical Report v1.1 is intended"
    )
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
            "[1] A. Bardes, Q. Garrido, J. Ponce, X. Chen, M. Rabbat, Y. LeCun, M. Assran, and N. Ballas. "
            '"Revisiting Feature Prediction for Learning Visual Representations from Video." arXiv:2404.08471, 2024. '
            "https://arxiv.org/abs/2404.08471"
        ),
    )
    text += (
        '\n[17] Safety-Gymnasium Contributors. "Safety-Gymnasium: A Unified Safe Reinforcement Learning '
        'Benchmark." Thirty-seventh Conference on Neural Information Processing Systems Datasets and '
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

    # Major-revision pass: make the evaluation method, model specification,
    # authority threat model, and attribution result self-contained in the paper.
    text = text.replace(
        "Technical Report v1.1 — 4 September 2026",
        "Technical Report v1.1 — 8 September 2026",
        1,
    )
    abstract = f"""### Abstract

World-model papers often move too quickly from predictive error to operational safety. This report contributes a registered evaluation method that separates six evidence objects: dynamics prediction, counterfactual response, warning quality, effective intervention, realized outcome, and independently enforced authority. It applies the method separately to FerrumOS and Physical JEPA across an 18-run matched architecture study, sealed threshold tests, authority-separated software integrations, a prospective Safety-Gymnasium controller/shield benchmark, and a fresh risk-source attribution. Failed and non-beneficial frozen stages remain in the record.

The registered Physical JEPA ensemble leads at H=1, H=3, and H=5. In FerrumOS, GRU leads at H=1 and H=3 and JEPA at H=5, but a registered post-hoc comparison on the same 238 H=5-eligible episodes favors JEPA at every horizon. The apparent reversal therefore cannot be isolated from episode composition. At the frozen 0.99 threshold, rules, learning, and their union all miss 256/256 delayed-hazard cases without intervening; a separate PyBullet stress instead stops every case and completes none.

On Safety-Gymnasium v14, the privileged planner accounts for most realized-cost reduction. The union passes its registered naive-baseline criteria with {pct(full['warning_recall'])} warning recall and {pct(full['effective_intervention_recall'])} effective-action recall, but superiority over the planner was not established. In the exploratory fresh-seed attribution, JEPA-output-only versus the full adapter changes hazard steps by {jepa_vs_full['actual_hazard_cost_steps']['estimate']:+.0f} and intervention rate by {jepa_vs_full['intervention_percentage_points']['estimate']:+.2f} percentage points; multiplicity-adjusted intervals exclude zero, while completion and planner-superiority claims remain unresolved. QEMU previews, recorded replay, and software physics exercise scoped integrations with execution or actuator authority denied where stated. No result establishes physical safety, independent replication, architecture-only causality, or deployment eligibility; protected artifacts remain unchanged.
"""
    text = replace_section(text, "### Abstract", "### 1. Introduction", abstract)

    intro = """#### 1.1 Contributions

The primary contribution is an evaluation method, not a new JEPA objective. It predefines the same six evidence objects named in the abstract; specifies how final data are sealed; retains invalid, failed, and non-beneficial stages; and binds each claim to a machine-readable record. The empirical contributions are: (1) an 18-run matched small-model comparison in two distinct domains; (2) paired temporal, calibration, and common-episode analyses that expose when predictive skill fails to become operational value; (3) an authority factorization in which learning may only add caution; (4) QEMU, recorded-sensor, PyBullet, and Safety-Gymnasium integrations labelled by evidence class; (5) a prospective controller/shield benchmark with planner-relative uncertainty; and (6) a fresh risk-source attribution with multiplicity, paired-direction, leave-one-out, and common-proposal diagnostics.

#### 1.2 Claim boundary

*Cross-domain* denotes application of the same evaluation and authority methodology to two domains. The models, state meanings, action spaces, labels, controllers, and datasets are not transferred between them. The temporal catalogs and PyBullet stress are locally designed software tests. Safety-Gymnasium supplies a third-party task and costs, but the adapters, privileged planner, correction, execution, and analysis are local. Physical evidence is replay and software simulation, not live HIL; FerrumOS evidence is disposable QEMU, not production use. No result establishes formal non-bypass, independent replication, human-contact safety, universal model superiority, or deployment safety, and no protected artifact is replaced.
"""
    text = replace_section(text, "#### 1.1 Contributions", "<!-- PAGE BREAK -->", intro)

    evidence_and_threat = """#### 3.3 Evidence classes

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
"""
    text = replace_section(text, "#### 3.3 Evidence classes", "<!-- PAGE BREAK -->", evidence_and_threat)
    text = text.replace(
        "Monotonicity means the learned branch cannot convert a deterministic *block* to *allow*; it does not mean an intervention is beneficial, as the PyBullet all-stop and planner-relative Safety-Gymnasium costs demonstrate.\n\n<!-- PAGE BREAK -->",
        "Monotonicity means the learned branch cannot convert a deterministic *block* to *allow*; it does not mean an intervention is beneficial, as the PyBullet all-stop and planner-relative Safety-Gymnasium costs demonstrate.",
        1,
    )

    methods = f"""#### 4.1 Domains, representations, and partitions

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
"""
    text = replace_section(text, "#### 4.1 Domains and representations", "#### 4.4 Learned-contribution benchmark", methods)

    common_rows = []
    common_methods = common_ferrumos["methods"]
    common_pairs = common_ferrumos["paired_architecture_comparisons"]
    for horizon in ("h1", "h3", "h5"):
        mlp = common_methods["direct_mlp"]["rollout"][horizon]["ensemble"]
        jepa = common_methods["action_conditioned_jepa"]["rollout"][horizon][
            "ensemble"
        ]
        gru = common_methods["gru_dynamics"]["rollout"][horizon]["ensemble"]
        mlp_minus_jepa = common_pairs["direct_mlp_minus_action_conditioned_jepa"][
            horizon
        ]
        jepa_minus_gru = common_pairs[
            "action_conditioned_jepa_minus_gru_dynamics"
        ][horizon]
        common_rows.append(
            "| {label} | {mlp:.6f} | **{jepa:.6f}** | {gru:.6f} | "
            "{mj:+.6f} [{mj_lo:.6f}, {mj_hi:.6f}] | "
            "{jg:+.6f} [{jg_lo:.6f}, {jg_hi:.6f}] |".format(
                label=horizon.upper().replace("H", "H="),
                mlp=mlp["estimate"],
                jepa=jepa["estimate"],
                gru=gru["estimate"],
                mj=mlp_minus_jepa["estimate"],
                mj_lo=mlp_minus_jepa["bootstrap_95_percent"][0],
                mj_hi=mlp_minus_jepa["bootstrap_95_percent"][1],
                jg=jepa_minus_gru["estimate"],
                jg_lo=jepa_minus_gru["bootstrap_95_percent"][0],
                jg_hi=jepa_minus_gru["bootstrap_95_percent"][1],
            )
        )
    common_episode_table = "\n".join(
        [
            "Table 2 reports the complete post-hoc common-episode comparison. All estimates are three-member ensemble normalized errors on the same 238 FerrumOS episodes; lower is better. Contrast intervals are paired, unadjusted 10,000-resample 95% bootstrap intervals conditional on the fixed checkpoints and this episode population.",
            "",
            "| Horizon | Direct MLP | JEPA | GRU | MLP - JEPA, paired 95% | JEPA - GRU, paired 95% |",
            "|---|---:|---:|---:|---:|---:|",
            *common_rows,
            "",
            "JEPA has the lowest common-episode estimate at every horizon, and both displayed paired contrasts exclude zero. This post-hoc table changes the interpretation of the registered horizon-specific ranking; it does not replace the registered result or model selection.",
        ]
    )

    text = replace_exact(
        text,
        "The present study differs in scope. It does not propose a new large-scale pretraining objective. It compares small matched dynamics models at a runtime decision boundary, holds compute and data constant, and measures whether offline ranking survives calibration and an operational threshold. Its novelty is primarily systems and methodology: authority remains separately enforceable, and every evidence class is labelled by what it can and cannot support.",
        "The present study differs in scope. It does not propose a new large-scale pretraining objective. It compares small models using matched domain-specific data, seeds, parameter budgets, and update budgets at a runtime decision boundary, then measures whether offline ranking survives calibration and an operational threshold. FLOPs and wall time are not equalized. Its novelty is primarily systems and methodology: authority remains separately enforceable, and every evidence class is labelled by what it can and cannot support.",
    )

    attribution_method = """#### 4.6 Frozen risk-source attribution

The v2 attribution protocol holds SafetyPointGoal1-v0, the privileged planner, one-command tangent correction, 20-step oracle, Physical JEPA v5 artifact, episode limit, runtime lock, and seeds fixed. It varies only the warning pipeline: the full frozen v14 adapter; local lidar/action/goal/closeness/speed with JEPA weights zero; frozen JEPA clearance/velocity/progress outputs only; or current maximum hazard closeness only. Alternative logistic adapters are fitted on seeds 4000–4095 and select thresholds on 4096–4127 by matching the full adapter's validation FPR, then minimizing false negatives, then choosing the higher threshold. Final seeds 8000–8127 are opened once.

The first registered attribution attempt on seeds 7000–7127 failed after the baseline and full arm because the alternative JSON schema omitted a runner-required threshold alias. Its partial catalog is retained and excluded. The v2 repair adds only that alias, preserves every numeric adapter field and threshold, commits the repair before final access, and uses a new seed range.

#### 4.7 Frozen gates, hashes, and non-promotion

Validation means checking an existing record against its schema, hashes, and gates. Recompute means deriving metrics again from committed rows or episode summaries without simulator execution. Rerun means executing the simulator or QEMU workload again. The verifiers distinguish these operations. SHA-256 establishes byte identity of named files, not scientific correctness; program logs establish only the events instrumented by those programs; and a verifier may share assumptions with its producer. Git commit timestamps provide externally hosted chronology after push, not proof that equivalent data were never observed elsewhere. Passing any study verifier does not imply deployment eligibility. Protected FerrumOS and Physical JEPA deployment digests must remain unchanged, and the study explicitly sets `promotion_eligible=false`.
"""
    text = replace_section(text, "#### 4.6 Frozen gates and non-promotion rule", "### 5. Architecture-controlled results", attribution_method)

    text = replace_exact(
        text,
        "Table 1 reports final normalized rollout error. Physical JEPA wins at every horizon. FerrumOS does not reproduce that ranking: the GRU is best at H=1 and H=3, while the JEPA is best at H=5. All reported pairwise episode-bootstrap intervals exclude zero at all three horizons.",
        "Table 1 reports the error of the three-seed ensemble prediction defined in Section 4.3. Physical JEPA wins at every horizon. FerrumOS does not reproduce that ranking: the GRU is best at H=1 and H=3, while the JEPA is best at H=5. The registered pairwise intervals for the stated leaders exclude zero, conditional on the fixed trained checkpoints; Appendix D shows all seed members.",
    )
    text = replace_exact(
        text,
        "The physical MLP-minus-JEPA H=3 difference is 0.010156 with 95% interval [0.009829, 0.010483]. In FerrumOS, GRU-minus-JEPA is favorable to the GRU at H=3 by 0.004439 [0.003203, 0.005735]. At H=5 the sign reverses: JEPA-minus-GRU is -0.001020 [-0.001165, -0.000865]. These are not marginal three-case classification differences; the shared-catalog rollout contrasts are statistically separated under the registered resampling procedure.",
        "The physical MLP-minus-JEPA H=3 difference is 0.010156 with 95% interval [0.009829, 0.010483]. In FerrumOS, GRU-minus-JEPA at H=3 is -0.004439 [-0.005735, -0.003203], so the sign correctly favors the GRU. At H=5, JEPA-minus-GRU is -0.001020 [-0.001165, -0.000865]. These registered, horizon-specific contrasts are statistically separated under the stated resampling procedure, conditional on their eligible episode populations.",
    )
    text = replace_exact(
        text,
        "The result closes a data and compute confound that affected historical comparisons, but only within this study. The physical representation and curriculum favor the action-conditioned JEPA decisively. FerrumOS contains short-horizon structured state changes for which recurrent dynamics are more effective, while the JEPA has the lowest long-horizon error at H=5. Architecture choice should therefore be treated as an empirical property of the state, action, horizon, and training regime rather than a brand-level claim.",
        f"The result closes data, parameter-count, and update-budget confounds that affected historical comparisons, but not FLOP or training-time differences. In the registered table, the tested three-member FerrumOS GRU ensemble leads at H=1 and H=3; this does not describe the mean individual checkpoint at H=1, where MLP is lower by only 0.000008. H=3 averages 318 eligible episodes, whereas H=5 averages {common_ferrumos['common_episode_count']} and excludes a source whose sequences are too short. Thus the registered ranking reversal cannot be isolated as a horizon effect: episode composition changes it. The original table and model selection remain unchanged.\n\n{common_episode_table}",
    )

    calibration = """#### 6.2 Calibration under shift

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
"""
    text = replace_section(text, "#### 6.2 Calibration under shift", "<!-- PAGE BREAK -->", calibration)
    text = text.replace(
        "![Figure 4. Predictive and causal evidence do not become operational learned value at the frozen threshold. The gap is measured rather than hidden by final-set retuning.](docs/research/figures/cross_domain_world_model/causal_vs_operational.png)\n\n<!-- PAGE BREAK -->",
        "![Figure 4. Predictive and causal evidence do not become operational learned value at the frozen threshold. The gap is measured rather than hidden by final-set retuning.](docs/research/figures/cross_domain_world_model/causal_vs_operational.png)",
        1,
    )

    runtime_section = """### 7. FerrumOS authority-separated runtime evidence

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
"""
    text = replace_section(text, "### 7. FerrumOS authority-disabled runtime evidence", "### 8. Physical evidence and retained negatives", runtime_section)

    text = replace_exact(
        text,
        "The replay is the strongest external physical evidence directly compatible with the present v5 representation, but it remains researcher-executed replay. It does not include live Ferrum hardware, physical clocks and interfaces, actuator dynamics, physical contact recovery, or an independently tested emergency-stop path.",
        "The projection is fixed from 698,400 HAI train1–train3 rows and maps only eight available source channels into the 16-state representation; missing state dimensions retain registered constants. Test1 labels align at exact second resolution; test2 labels align positionally only after matching the source file's minute precision, with equal row counts and no shifting, interpolation, nearest-neighbor matching, fill, or imputation. Event labels and proxy commands are descriptive anomaly diagnostics, not equivalent to the model's maintenance/action ontology. The replay is therefore bounded external-stream compatibility evidence, not live Ferrum HIL, end-to-end safety validation, physical timing, actuator dynamics, contact recovery, or an independently tested emergency stop.",
    )

    def attribution_row(label: str, record: dict) -> str:
        values = record["aggregate"]
        stats = record["episode_statistics"]
        return (
            f"| {label} | {pct(values['task_completion_rate'])} | {pct(values['effective_intervention_recall'])} | {pct(values['intervention_rate'])} | "
            f"{pct(values['intervention_precision'])} | {values['actual_hazard_cost_events']} | "
            f"{stats['episodes_with_actual_hazard_cost']}/128 | {stats['mean_episode_steps']:.1f} |"
        )

    def warning_row(label: str, variant_id: str, record: dict) -> str:
        values = record["aggregate"]
        common = common_warning["variants"][variant_id]
        validation_fpr = posthoc_attribution["validation_warning_false_positive_rates"][
            variant_id
        ]
        return (
            f"| {label} | {pct(validation_fpr)} | {pct(values['warning_recall'])} | "
            f"{pct(values['warning_false_positive_rate'])} | {pct(common['warning_recall'])} | "
            f"{pct(common['warning_false_positive_rate'])} |"
        )

    attribution_section = f"""#### 8.5 Frozen risk-source attribution on fresh layouts

The v2 attribution opens seeds 8000-8127 once after committing every adapter, threshold, and simulator setting. The planner baseline records {attribution_baseline['aggregate']['task_completions']}/128 completions, {attribution_baseline['aggregate']['actual_hazard_cost_events']} hazard steps, and {attribution_baseline['episode_statistics']['episodes_with_actual_hazard_cost']}/128 hazardous episodes. Table 6 changes only the warning source; all rows retain the deterministic rule union and the same one-command tangent correction.

| Risk source | Completion | Effective recall | Intervention | Precision | Hazard steps | Hazardous episodes | Mean steps |
|---|---:|---:|---:|---:|---:|---:|---:|
{attribution_row('Full local + JEPA adapter', attribution_full)}
{attribution_row('Local sensing, no JEPA', attribution_local)}
{attribution_row('JEPA outputs only', attribution_jepa)}
{attribution_row('Hazard closeness only', attribution_geometry)}

JEPA-only versus full was a prospectively specified member of a four-pipeline family, but not the uniquely designated primary contrast. The original 95% intervals are pointwise and unadjusted, so confirmatory interpretation would be inappropriate. A registered post-hoc sensitivity controls a 5% familywise error rate across the three non-full-versus-full pipeline contrasts within each endpoint separately; it does not adjust jointly across every endpoint or comparison in the report. For JEPA-only minus full, the Bonferroni-adjusted 98.33% interval is [{posthoc_jepa_adjusted['hazard_steps']['percentile_interval'][0]:.0f}, {posthoc_jepa_adjusted['hazard_steps']['percentile_interval'][1]:.0f}] for a {posthoc_jepa_adjusted['hazard_steps']['estimate']:+.0f}-step hazard contrast and [{posthoc_jepa_adjusted['intervention_percentage_points']['percentile_interval'][0]:.2f}, {posthoc_jepa_adjusted['intervention_percentage_points']['percentile_interval'][1]:.2f}] for a {posthoc_jepa_adjusted['intervention_percentage_points']['estimate']:+.2f}-point intervention contrast. Both exclude zero. Hazard steps improve/worsen/remain unchanged in {posthoc_jepa_directions['hazard_steps']['improved']}/{posthoc_jepa_directions['hazard_steps']['worsened']}/{posthoc_jepa_directions['hazard_steps']['unchanged']} paired episodes; intervention counts are lower/higher/unchanged in {posthoc_jepa_directions['intervention_count']['improved']}/{posthoc_jepa_directions['intervention_count']['worsened']}/{posthoc_jepa_directions['intervention_count']['unchanged']}. Every one of 128 leave-one-seed-out 95% intervals still excludes zero for both quantities (hazard endpoints across omissions [{posthoc_jepa_loo['hazard_interval_endpoint_range'][0]:.0f}, {posthoc_jepa_loo['hazard_interval_endpoint_range'][1]:.0f}]; intervention endpoints [{posthoc_jepa_loo['intervention_interval_endpoint_range'][0]:.2f}, {posthoc_jepa_loo['intervention_interval_endpoint_range'][1]:.2f}]). These leave-one-out checks are sensitivity analyses, not independent replications. Its {jepa_vs_full['completion_percentage_points']['estimate']:+.2f}-point completion contrast has pointwise CI [{jepa_vs_full['completion_percentage_points']['bootstrap_95_percent'][0]:.2f}, {jepa_vs_full['completion_percentage_points']['bootstrap_95_percent'][1]:.2f}], which shows no statistically resolved difference and is not a non-inferiority result. Against the unshielded planner, JEPA-only changes hazard cost by {attribution_jepa['versus_planner_paired_bootstrap']['actual_hazard_cost_steps']['estimate']:+.0f} steps with CI [{attribution_jepa['versus_planner_paired_bootstrap']['actual_hazard_cost_steps']['bootstrap_95_percent'][0]:.0f}, {attribution_jepa['versus_planner_paired_bootstrap']['actual_hazard_cost_steps']['bootstrap_95_percent'][1]:.0f}], so superiority to the planner is not established.

The original warning metrics are on-policy: each pipeline changes actions and therefore changes the states and proposals it later visits. Keeping the oracle logic fixed does not keep the evaluation population fixed. Table 7 reports both those on-policy values and a direct post-hoc detector comparison on the identical {common_warning['catalog_rows']:,}-proposal catalog visited by the full pipeline. The common catalog contains {common_warning['dangerous_proposals']} dangerous and {common_warning['safe_proposals']:,} safe proposals and reproduces the full arm exactly; it remains conditional on full-arm visitation and is not an independent sample.

| Risk source | Validation FPR | Final on-policy recall | Final on-policy FPR | Common recall | Common FPR |
|---|---:|---:|---:|---:|---:|
{warning_row('Full local + JEPA', 'full-frozen-v14-adapter', attribution_full)}
{warning_row('Local, no JEPA', 'local-sensing-without-jepa', attribution_local)}
{warning_row('JEPA outputs only', 'jepa-outputs-only', attribution_jepa)}
{warning_row('Hazard closeness', 'hazard-closeness-only', attribution_geometry)}

Warning recall and realized outcomes rank differently: full has higher 20-step dangerous-trajectory warning recall, while JEPA-only intervenes less and records fewer realized hazard steps. The finding is exploratory pipeline-level evidence for a lower-intervention operating point under this fixed correction design. It does not isolate JEPA architecture, prove detector superiority on an independently sampled population, establish preserved completion, or establish safety superiority. The failed v1 attribution attempt and its excluded 7000-range partial catalog remain archived.

"""
    text = text.replace("\n### 9. Cross-domain synthesis", "\n" + attribution_section + "### 9. Cross-domain synthesis", 1)

    text = replace_exact(
        text,
        "This work does not claim the first JEPA world model, first safety filter, first calibrated predictor, or first runtime-assurance architecture. Its contribution is the cross-domain combination of: matched architecture control; explicit separation of prediction, policy, capability, and effect; sealed validation-only selection; paired causal and operational estimands; runtime evidence with authority disabled; semantic compatibility checks for external data; retained operational negatives; and digest-verified non-promotion. The principal hypothesis supported is methodological: predictive evidence and authority evidence should be registered, measured, and reviewed separately.",
        "This work does not claim the first JEPA world model, safety filter, calibrated predictor, or runtime-assurance architecture. Its central novelty is an executable evaluation method with named estimands and named failure modes: prediction error, counterfactual response, calibration, warnings, effective interventions, realized outcomes, and authority are registered and reviewed separately. Applying that method in two domains exposes a composition-sensitive registered ranking, a thresholded latent-hazard zero, an all-stop policy, a planner-dominated result, and a risk-source attribution that warning recall alone would conceal. The cross-domain claim is methodological replication across distinct systems, not learned representation or policy transfer.",
    )
    text = replace_exact(
        text,
        "The matched study rejects the simplest architecture story. Physical dynamics strongly favor the JEPA in this registered setting. FerrumOS short-horizon prediction favors the GRU, with the JEPA best only at H=5. The result is more useful than a universal-winner claim because it exposes where architecture selection must remain empirical. It also gives the Physical JEPA paper a controlled dynamics comparison while making the FerrumOS systems claim less dependent on a JEPA label.",
        "The registered table rejects a universal architecture story. Physical dynamics favor the tested three-member JEPA ensemble at all horizons. FerrumOS favors the tested three-member GRU ensemble at H=1 and H=3, with JEPA leading at H=5; however, the common-H5-eligible episode sensitivity favors JEPA at every horizon. The apparent FerrumOS reversal is therefore composition-sensitive and cannot be isolated as a horizon effect. This makes architecture selection an empirical, estimand-specific decision rather than a model-family claim.",
    )

    limitations = """### 10. Threats to validity and limitations

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

13. Source tests cover enumerated protocol, daemon, and physical-runtime paths. Deterministic predicates are engineering rules, not formally verified invariants, and empirical tests do not prove universal non-bypass.

14. There is no live actuator timing, physical contact, hardware emergency stop, human-contact dynamics, or independent execution. All research artifacts remain ineligible for promotion and protected deployed artifacts are unchanged.
"""
    text = replace_section(text, "### 10. Threats to validity and limitations", "### 11. Reproducibility and artifact integrity", limitations)

    reproducibility = """### 11. Reproducibility and artifact integrity

Every evidence object names its scope and digest. Hashes prove byte identity only; they do not validate labels, scientific assumptions, or instrument completeness. Result producers and verifiers share repository code in places, so independent replication remains a higher evidence tier. The report uses three distinct verbs: **validate** an existing record and gates; **recompute** metrics from committed rows without environment execution; and **rerun** the registered environment or QEMU workload. Commands below are labelled accordingly.

The architecture and post-hoc analysis record Python 3.12.6, NumPy 2.2.6, and PyTorch 2.6.0+cu124 on Windows; `requirements-research.txt` pins the remaining analysis and PDF packages. Safety-Gymnasium uses its separate locked environment: Python 3.10.20, Safety-Gymnasium 1.0.0, Gymnasium 0.28.1, Gymnasium-Robotics 1.2.2, MuJoCo 2.3.3, NumPy 1.23.5, and pygame 2.1.0. Protocols bind simulator source trees, checkpoints, catalogs, and results. Wall time is machine-dependent; the post-hoc verifier performs checkpoint inference and 10,000-resample analyses without launching the simulator.

The exact scientific-evidence snapshot for this review freeze is Git commit `e8805eb3ed70d848887b954f33871c1fbdb8ef39`. A short headline-table audit is: run the umbrella verifier, run the post-hoc verifier, then run the paper verifier. These validate or recompute committed evidence; they do not rerun a final simulator catalog.

```powershell
# Recompute or validate committed evidence; no new final simulator execution
python scripts/verify_cross_domain_world_models.py
python scripts/verify_cross_domain_learned_contribution.py
python scripts/verify_cross_domain_world_model_posthoc_sensitivity_v1.py
python scripts/verify_physical_jepa_safety_gymnasium_v14.py
python scripts/verify_physical_jepa_safety_gymnasium_paired_uncertainty.py
target\\safety-gymnasium-venv\\Scripts\\python.exe scripts/verify_physical_jepa_safety_gymnasium_attribution_v1.py
python scripts/verify_cross_domain_world_model_improvement_study.py
python scripts/verify_cross_domain_world_model_paper_v1_1.py
cargo test --manifest-path userland/neural-protocol/Cargo.toml --target x86_64-pc-windows-msvc
cargo test --manifest-path userland/physical-runtime/Cargo.toml --target x86_64-pc-windows-msvc

# Rerun only under a new prospective protocol and output paths
# node scripts/verify_world_model_combined_gate.mjs
# target\\safety-gymnasium-venv\\Scripts\\python.exe scripts/evaluate_physical_jepa_safety_gymnasium_attribution_v1.py
```

The attribution verifier recomputes every aggregate from 128 per-seed summaries, checks all four compressed row catalogs, exact seed membership, 10,000 paired resamples, adapter/protocol digests, locked runtime source, zero actuator authority, and non-promotion. The post-hoc verifier independently reconstructs the common-episode rollouts, adjusted intervals, leave-one-out results, and common-proposal scores. The authority inventory records 9/9 neural-protocol and 128/128 physical-runtime tests while distinguishing them from QEMU evidence. The paper verifier checks required claim boundaries, PDF metadata, figures, tables, page count, source/PDF digests, and the umbrella evidence snapshot.
"""
    text = replace_section(text, "### 11. Reproducibility and artifact integrity", "### 12. Conclusion", reproducibility)

    conclusion = f"""### 12. Conclusion

The paper's strongest result is methodological. A world model can lead a matched rollout table, respond directionally to interventions, fail at a frozen operational threshold, and still remain correctly subordinate to policy and capability. The same evaluation method reveals a horizon-composition-sensitive architecture ranking in FerrumOS, a zero-coverage latent-hazard estimand, an all-stop PyBullet policy, planner-dominated Safety-Gymnasium outcomes, and an exploratory risk-source comparison in which JEPA-only caution reduces interventions and hazard steps relative to the full adapter without establishing superiority to the planner.

The defensible claim is not that FerrumOS or Physical JEPA is safe. It is that predictive evidence, warning quality, effective action changes, realized outcomes, and authority can be measured as separate objects with frozen access boundaries and retained failures. Deterministic blocking is empirically monotone on tested paths, but monotonicity is not benefit; capability, confirmation, revision checks, and actuator denial remain independently necessary. No protected artifact is promoted.

#### 12.1 Submission scope

The appropriate venue identity is cyber-physical systems, runtime assurance, dependable agents, or evaluation methodology. Cross-domain means the method is exercised separately in an agentic OS and a physical-runtime simulation—not that one model transfers between them. The absence of live hardware and independent execution excludes robotics-deployment claims.

#### 12.2 Remaining evidence tier

The targeted local attribution and its registered post-hoc sensitivity checks are complete on fresh, frozen seeds. Another local threshold sweep would add little. The next evidence-class changes are independent execution of a frozen controller/shield benchmark, actuator-disabled live HIL with physical clocks and interfaces, and externally controlled labels or assessment. For FerrumOS, independently operated longitudinal use and concurrent preview remain higher value than more synthetic prompts.

#### 12.3 Release rule

This is the first reviewable Technical Report v1.1 freeze; earlier v1.1 builds were private mutable drafts, not archival releases. The repository tag `prediction-is-not-permission-v1.1` identifies the exact reviewable source, PDF, verifier, and freeze manifest. Future evidence-changing work must create a new immutable report version and retain failed frozen results. Promotion requires a separate prospective deployment protocol naming exact targets, rollback, capabilities, post-execution verification, and gates. Publication of this report is not that protocol.
"""
    text = replace_section(text, "### 12. Conclusion", "<!-- PAGE BREAK -->\n\n### Appendix A", conclusion)
    text = text.replace(
        "Publication of this report is not that protocol.\n\n<!-- PAGE BREAK -->\n\n### Appendix A",
        "Publication of this report is not that protocol.\n\n### Appendix A",
        1,
    )

    text = text.replace(
        "| Learned models add operational caution | Three-arm 512-case catalogs | Zero marginal blocks at threshold 0.99 | No learned safety-value claim |",
        "| Learned marginal caution is evaluated | Three-arm 512-case catalogs | Zero marginal blocks at threshold 0.99 | No learned safety-value claim |",
        1,
    )
    text = text.replace(
        "| FerrumOS ranking differs | Shared frozen FerrumOS final catalog | GRU leads H=1 and H=3; JEPA leads H=5 | Not evidence that recurrent models are universally best |",
        "| FerrumOS registered ranking differs | Horizon-specific FerrumOS endpoints plus common-episode sensitivity | GRU ensemble leads registered H=1/H=3; JEPA leads all common-episode horizons | Ranking reversal is not isolated from episode composition |",
        1,
    )
    text = text.replace(
        "![Figure 3. Matched rollout errors for the three model families. The ranking reversal is the main architecture result: no family dominates both domains and all horizons.](docs/research/figures/cross_domain_world_model/matched_rollout_results.png)",
        "![Figure 3. Registered matched rollout errors for three model families. The FerrumOS horizon populations differ; the common-episode sensitivity is reported separately.](docs/research/figures/cross_domain_world_model/matched_rollout_results.png)",
        1,
    )
    text = text.replace(
        "| Controller and shield are jointly evaluated | Safety-Gymnasium final seeds 6000-6127 | Planner-only: 94.53% completion and 87.08% cost reduction; union passes all registered naive-baseline gates with 95.62% warning recall, 55.00% effective-action recall, and 23.04% intervention precision, but costs 14 more hazard steps than planner | Not independent, sensor-only, physical, or learned-superiority evidence |",
        "| Controller and shield are jointly evaluated | Safety-Gymnasium final seeds 6000-6127 | Planner-only explains most cost reduction; union passes naive-baseline gates; no statistically resolved planner difference in completion or cost | Not independent, sensor-only, physical, or learned-superiority evidence |\n| Risk-source pipelines are compared | Frozen attribution seeds 8000-8127 | Exploratory JEPA-only versus full: -25 hazard steps and -0.81 intervention points; adjusted and leave-one-out intervals exclude zero | Not architecture-only causality, preserved completion, or superiority to planner |",
        1,
    )
    text = text.replace(
        "| Paired planner-union uncertainty | Seed pairing, estimands, 10,000 resamples, bootstrap seed | Completion and hazard-cost differences independently recompute; both intervals include zero | Post-hoc analysis of committed episode summaries; no final rerun |\n| Paper freeze |",
        "| Paired planner-union uncertainty | Seed pairing, estimands, 10,000 resamples, bootstrap seed | Completion and hazard-cost differences independently recompute; both intervals include zero | Post-hoc analysis of committed episode summaries; no final rerun |\n| Registered sensitivity v1 | Common episodes/proposals, three-comparison family, 128 omissions | Exact recomputation, adjusted intervals, and source-arm reproduction pass | No simulator, retraining, threshold change, or promotion |\n| Paper freeze |",
        1,
    )

    amendment_table = """#### B.1 Protocol and amendment chronology

Hosted Git history timestamps the registered files after commit; it does not prove absence of any earlier equivalent observation. The table is an audit index, not a claim that every stage was scientifically successful.

| Stage | Registration commit / time (IST) | Frozen change | Outcome |
|---|---|---|---|
| Safety-Gym v1–v4 | `383e525`–`f9d1a52`, 30 Aug 17:32–19:24 | Initial recovery, new final ranges, realized-cost gate | v1 selection failed; v3 final failed; v4 retained mixed record |
| Safety-Gym v5–v8 | `5a2a07c`–`2ae1502`, 30–31 Aug | Earlier warning, bounded steering, braking, adaptive exit | Development failures; no promoted final |
| Safety-Gym v9–v13 | `22f9774`–`4f62544`, 31 Aug | Privileged planner factorization, tangent correction, recall repair, Simplex trial | v10/v12 finals failed; v13 failed development |
| Safety-Gym v14 | `bcca0b6`, 1 Sep 23:21 | Synchronized 20-step nominal oracle and corrected cost accounting | One final pass against naive-baseline gates; planner-relative tradeoff retained |
| Attribution v1 | `df58e72`, 5 Sep | Four fixed risk sources, seeds 7000–7127 | Schema failure after two stages; partial catalog retained and excluded |
| Attribution v2 | `e954a2c`, 5 Sep | Threshold alias only; new seeds 8000–8127 | Completed once; all evidence checks pass; no promotion |
| Post-hoc sensitivity v1 | `cd5e9b6`–`da32691`, 8 Sep | Common episodes/proposals, multiplicity, paired directions, leave-one-out | Exact recomputation passes; no simulator, retraining, or promotion |

#### B.2 Protected deployment inventory

The umbrella record protects four deployed objects: the FerrumOS encoder, FerrumOS transition, FerrumOS manifest, and Physical JEPA transition. Their observed digests equal their registered expected digests. Architecture checkpoints, adapters, catalogs, replay projections, and simulator results remain research artifacts. A passing verifier cannot change that status.
"""
    text = replace_section(text, "#### B.1 Protected deployment inventory", "#### B.2 Reproduction order", amendment_table)
    text = text.replace("#### B.2 Reproduction order", "#### B.3 Reproduction order", 1)
    text = text.replace("#### B.3 Archival boundary", "#### B.4 Archival boundary", 1)

    text = text.replace(
        "| Paired planner-union uncertainty | `docs/research/physical_jepa_safety_gymnasium_paired_uncertainty_result_v1.json` | Recompute seed-matched completion and realized hazard-cost difference intervals |",
        "| Paired planner-union uncertainty | `docs/research/physical_jepa_safety_gymnasium_paired_uncertainty_result_v1.json` | Recompute seed-matched completion and realized hazard-cost difference intervals |\n| Risk-source attribution protocol | `docs/research/physical_jepa_safety_gymnasium_attribution_protocol_v2.json` | Inspect fixed factors, thresholds, recovery, and fresh seed boundary |\n| Risk-source attribution result | `docs/research/physical_jepa_safety_gymnasium_attribution_result_v2.json` | Recompute four pipeline arms, episode statistics, and paired differences |\n| Risk-source attribution verification | `docs/research/physical_jepa_safety_gymnasium_attribution_verification_v2.json` | Confirm row catalogs, seed sets, digests, runtime, authority, and non-promotion |\n| Registered post-hoc sensitivity | `docs/research/cross_domain_world_model_posthoc_sensitivity_result_v1.json` | Common episodes, common proposals, adjusted intervals, paired directions, and leave-one-out checks |\n| Post-hoc sensitivity verification | `docs/research/cross_domain_world_model_posthoc_sensitivity_verification_v1.json` | Exact independent recomputation without simulator execution |\n| Authority test inventory | `docs/research/cross_domain_authority_test_inventory_v1.json` | Map component, test class, committed pass, and execution availability |",
        1,
    )

    method_labels = {
        "direct_mlp": "Direct MLP",
        "action_conditioned_jepa": "Action-conditioned JEPA",
        "gru_dynamics": "GRU dynamics",
    }
    member_rows = []
    for domain, domain_label in (("ferrumos", "FerrumOS"), ("physical", "Physical")):
        for method in ("direct_mlp", "action_conditioned_jepa", "gru_dynamics"):
            rollout = architecture_result["domains"][domain]["methods"][method]["rollout"]
            triplets = []
            for position in range(3):
                triplets.append(
                    " / ".join(
                        f"{rollout[horizon]['members'][position]['estimate']:.6f}"
                        for horizon in ("h1", "h3", "h5")
                    )
                )
            member_rows.append(
                f"| {domain_label} | {method_labels[method]} | {triplets[0]} | {triplets[1]} | {triplets[2]} |"
            )
    appendix_d = """### Appendix D. Seed-level architecture results

Each cell reports H=1/H=3/H=5 normalized endpoint error for one independently initialized checkpoint. Table 1 instead reports error after averaging the three state predictions. These seed results show training variability; the paper's episode bootstrap does not resample this training process.

| Domain | Method | Seed 17 | Seed 43 | Seed 101 |
|---|---|---:|---:|---:|
""" + "\n".join(member_rows) + "\n\n<!-- PAGE BREAK -->\n\n"
    text = text.replace("### References", appendix_d + "### References", 1)

    text = replace_exact(
        text,
        '[3] T. Zhou et al. "DINO-WM: World Models on Pre-trained Visual Features Enable Zero-shot Planning." arXiv:2411.04983, 2024. https://arxiv.org/abs/2411.04983',
        '[3] G. Zhou et al. "DINO-WM: World Models on Pre-trained Visual Features enable Zero-shot Planning." arXiv:2411.04983, 2024. https://arxiv.org/abs/2411.04983',
    )
    text = replace_exact(
        text,
        '[6] N. Phan et al. "Neural Simplex Architecture." NASA Formal Methods, 2020. https://doi.org/10.1007/978-3-030-55754-6_6',
        '[6] D. T. Phan et al. "Neural Simplex Architecture." NASA Formal Methods, LNCS 12229, 2020. https://doi.org/10.1007/978-3-030-55754-6_6',
    )
    text = replace_exact(
        text,
        '[7] N. Phan et al. "The Black-Box Simplex Architecture for Runtime Assurance of Autonomous CPS." NASA Formal Methods, 2022. https://doi.org/10.1007/978-3-031-06773-0_32',
        '[7] U. Mehmood et al. "The Black-Box Simplex Architecture for Runtime Assurance of Autonomous CPS." NASA Formal Methods, LNCS 13260, 2022. https://doi.org/10.1007/978-3-031-06773-0_12',
    )
    text = replace_exact(
        text,
        '[8] NASA. "Formal Verification Framework for Runtime Assurance." NASA Technical Reports Server. https://ntrs.nasa.gov/citations/20210010253',
        '[8] J. T. Slagel, L. M. White, A. Dutle, C. Muñoz, and N. Crespo. "A Formal Verification Framework for Runtime Assurance." NASA Formal Methods, LNCS 14627, pp. 322–328, 2024. https://doi.org/10.1007/978-3-031-60698-4_19',
    )
    text = replace_exact(
        text,
        '[9] NASA. "Runtime Assurance for Unmanned Aircraft Systems." NASA Technical Reports Server. https://ntrs.nasa.gov/citations/20210014050',
        '[9] J. T. Slagel, L. M. White, A. Dutle, C. Muñoz, and N. Crespo. "A Verification Framework for Runtime Assurance of Autonomous UAS." 43rd Digital Avionics Systems Conference, 2024. https://shemesh.larc.nasa.gov/fm/plaidypvs/',
    )
    # Keep Appendix C with the short archival-boundary subsection instead of
    # stranding B.4 alone on an otherwise empty page.
    text = text.replace(
        "\n<!-- PAGE BREAK -->\n\n### Appendix C. Artifact locator",
        "\n\n### Appendix C. Artifact locator",
        1,
    )
    text = text.replace(
        "\n<!-- PAGE BREAK -->\n\n### Appendix B. Frozen-gate and artifact audit",
        "\n\n### Appendix B. Frozen-gate and artifact audit",
        1,
    )
    text = text.replace(
        "\n<!-- PAGE BREAK -->\n\n### Appendix D. Seed-level architecture results",
        "\n\n### Appendix D. Seed-level architecture results",
        1,
    )
    if (
        "reviewer-requested" in text.lower()
        or "requested by the present review" in text.lower()
        or "opposite unusable extreme" in text.lower()
        or "missed population rate is 1.478%" in text.lower()
        or "holds compute and data constant" in text.lower()
    ):
        raise ValueError("forbidden archival wording remains")
    OUTPUT.write_text(text, encoding="utf-8", newline="\n")
    print(OUTPUT.relative_to(ROOT).as_posix())


if __name__ == "__main__":
    main()
