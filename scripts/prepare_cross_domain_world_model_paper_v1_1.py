#!/usr/bin/env python3
"""Prepare Technical Report v1.1 from v1.0 and the verified v12 benchmark."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/research/paper/prediction_is_not_permission_technical_report_v1_0.md"
OUTPUT = ROOT / "docs/research/paper/prediction_is_not_permission_technical_report_v1_1.md"
RESULT = ROOT / "docs/research/physical_jepa_safety_gymnasium_result_v12.json"
VERIFICATION = ROOT / "docs/research/physical_jepa_safety_gymnasium_verification_v12.json"


def replace_exact(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"expected exactly one source block, found {count}: {old[:80]!r}")
    return text.replace(old, new)


def pct(value: float) -> str:
    return f"{100.0 * value:.2f}%"


def main() -> None:
    if OUTPUT.exists():
        raise SystemExit(f"refusing to overwrite {OUTPUT.relative_to(ROOT)}")
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    verification = json.loads(VERIFICATION.read_text(encoding="utf-8"))
    verification_checks = verification.get("checks", {})
    expected_negative = {
        name: value
        for name, value in verification_checks.items()
        if name != "all_frozen_gates_pass_independently"
    }
    if (
        result.get("all_frozen_gates_pass") is not False
        or verification.get("overall_pass") is not False
        or not expected_negative
        or not all(expected_negative.values())
    ):
        raise SystemExit("v12 must be an independently recomputed frozen-gate negative")

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

    text = SOURCE.read_text(encoding="utf-8")
    text = replace_exact(
        text,
        "Technical Report v1.0 - 30 August 2026",
        "Technical Report v1.1 - 31 August 2026",
    )
    text = replace_exact(
        text,
        "A separately registered 3D PyBullet stress test produces the opposite unusable extreme: 288 interventions in 288 cases and 0% task completion.",
        (
            "A separately registered 3D PyBullet stress test produces an operationally unusable "
            "extreme: 288 interventions in 288 cases and 0% task completion. A subsequent "
            "externally designed, locally executed Safety-Gymnasium benchmark separates controller value "
            f"from shield value on {seeds['count']} untouched seeds. The privileged planner completes "
            f"{pct(planner['task_completion_rate'])} of tasks and records {pct(planner_reduction)} fewer "
            "hazard-cost events than the naive controller with zero shield interventions. The active union "
            f"completes {pct(full['task_completion_rate'])}, intervenes on {pct(full['intervention_rate'])} "
            f"of proposals, recalls {pct(full['dangerous_proposal_recall'])} of dangerous proposals, and "
            f"increases realized hazard cost by {pct(-headline['actual_hazard_cost_reduction_fraction'])}."
        ),
    )
    text = replace_exact(
        text,
        "All negative results are retained, protected deployed artifacts remain byte-identical, and promotion eligibility is false.",
        (
            "All negative and failed frozen attempts are retained, the planner-only contrast and active-shield "
            "failure are reported together, protected deployed artifacts "
            "remain byte-identical, and promotion eligibility is false."
        ),
    )
    text = replace_exact(
        text,
        "learned operational safety value at the frozen operating point.",
        (
            "independent replication, physical deployment safety, or learned collision-avoidance "
            "value: the final benchmark's hazard reduction is attributed to privileged deterministic "
            "planning, while the active shield fails its frozen joint objective and the learned branch remains advisory."
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
            "planner-only arm generalizes but the selected active shield does not."
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

The final amendment freezes Safety-Gymnasium v1.0.0, Gymnasium 0.28.1, MuJoCo 2.3.3, the installed simulator-source digest, the protected Physical JEPA v5 digest, effective-intervention choice on already-opened development seeds 3000-3127, and untouched final seeds {seeds['start']}-{seed_end}. The external project supplies the task definition, seeded layouts, observations, goal condition, and hazard-cost signal [17]. This study supplies the navigation adapter, proposed controllers, deterministic shield, learned caution branch, execution, and analysis. Execution is local, physical actuator authority is disabled, and no independent replication is claimed.

| Final arm | Completion | Intervention | Dangerous recall | Safe FPR | Hazard-cost events |
|---|---:|---:|---:|---:|---:|
| Naive unshielded | {pct(naive['task_completion_rate'])} | {pct(naive['intervention_rate'])} | {pct(naive['dangerous_proposal_recall'])} | {pct(naive['safe_proposal_false_positive_rate'])} | {naive['actual_hazard_cost_events']} |
| Planner unshielded | **{pct(planner['task_completion_rate'])}** | {pct(planner['intervention_rate'])} | {pct(planner['dangerous_proposal_recall'])} | {pct(planner['safe_proposal_false_positive_rate'])} | **{planner['actual_hazard_cost_events']}** |
| Planner + rules | {pct(rules['task_completion_rate'])} | {pct(rules['intervention_rate'])} | {pct(rules['dangerous_proposal_recall'])} | {pct(rules['safe_proposal_false_positive_rate'])} | {rules['actual_hazard_cost_events']} |
| Planner + learned | {pct(learned['task_completion_rate'])} | {pct(learned['intervention_rate'])} | {pct(learned['dangerous_proposal_recall'])} | {pct(learned['safe_proposal_false_positive_rate'])} | {learned['actual_hazard_cost_events']} |
| Planner + rules + learned | {pct(full['task_completion_rate'])} | {pct(full['intervention_rate'])} | {pct(full['dangerous_proposal_recall'])} | {pct(full['safe_proposal_false_positive_rate'])} | {full['actual_hazard_cost_events']} |

The privileged planner-only arm is the strongest prospective controller result: it completes {pct(planner['task_completion_rate'])} of tasks and reduces realized hazard-cost events from {naive['actual_hazard_cost_events']} to {planner['actual_hazard_cost_events']} ({pct(planner_reduction)}) without a shield intervention. The selected active union does not pass the frozen joint objective. It passes completion, intervention, safe-FPR, authority, and artifact-integrity gates, but dangerous-proposal recall is {pct(full['dangerous_proposal_recall'])} against an 80% minimum and realized hazard cost increases from {naive['actual_hazard_cost_events']} to {full['actual_hazard_cost_events']} ({pct(-headline['actual_hazard_cost_reduction_fraction'])}). Episode-bootstrap intervals are preserved in the result artifact rather than selectively summarized here.

Attribution is essential. The privileged deterministic planner changes {pct(full['base_controller_divergence_rate'])} of union proposals relative to the naive local controller; that is controller divergence, not shield intervention. An intervention is counted only when the applied action differs from the proposal. The learned branch accounts for {headline['learned_only_interventions']} rule-exclusive interventions because learned alerts require deterministic rule confirmation before they can alter control. The benchmark therefore supports prospective deterministic-planner value and a retained active-shield negative, not a claim that v5 produced the hazard-cost reduction. The repository retains selection failures, a serializer failure, fresh-final recall and realized-cost failures, a nominal replan that often repeated the original action, and a subsequent Simplex fallback that failed before final access.

"""
    text = replace_exact(text, "### 9. Cross-domain synthesis", safety_section + "### 9. Cross-domain synthesis")
    text = replace_exact(
        text,
        "The new 512-case catalogs show no interventions from either rules or learning. The 3D stress shows intervention on every case. One extreme has no hazard recall; the other has no task completion. Together they show why a shield should be evaluated on both avoided harm and intervention cost at a registered operating point. Deterministic authority is necessary as a control boundary but is not automatically sufficient as an engineering policy.",
        (
            "The new 512-case catalogs show no interventions from either rules or learning, while the 3D stress "
            "intervenes on every case. The prospective Safety-Gymnasium result separates a useful privileged "
            "planner-only controller from an active union that fails recall and worsens realized hazard cost. "
            "The contrast shows why controller quality cannot be credited to a shield and why a shield's recall "
            "cannot substitute for executed outcomes. These three outcomes show why deterministic authority must be "
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
        "python scripts/verify_physical_jepa_multi_embodiment_3d.py\npython scripts/verify_physical_jepa_safety_gymnasium_v12.py\n",
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
            f"{pct(planner_reduction)} fewer realized hazard-cost events than the naive baseline, while the active "
            f"union reaches only {pct(full['dangerous_proposal_recall'])} dangerous recall and increases hazard cost. "
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
            "planner contrast is useful research evidence, but the active shield fails its frozen gates and every "
            "research artifact remains explicitly ineligible for promotion."
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

The prospective joint objective is now measured on an external simulator task and fails for the active shield despite a strong planner-only arm. Another local seed range or threshold sweep has low scientific value. The next evidence-class changes are a controller/shield design fixed before an externally executed benchmark, actuator-disabled live HIL with physical clocks and interfaces, and execution of a frozen protocol by an independent party. For FerrumOS, independently operated longitudinal use and concurrent preview remain more valuable than additional synthetic prompts. These are declared next-tier studies, not missing rows that can be fabricated inside the present software-only report.
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
            f"reduction; active union fails recall and cost gates | Not a passing shield, independent, sensor-only, "
            "physical, or learned-safety result |"
        ),
    )
    text = replace_exact(
        text,
        "A scientific negative is a completed comparison whose registered estimand does not support the hoped-for effect, as in zero learned marginal caution.",
        (
            "A scientific negative is a completed comparison whose registered estimand does not support the hoped-for "
            "effect, as in zero learned marginal caution. A gate pass can still be an engineering negative when the "
            "executed outcome worsens, as retained in the pre-v12 Safety-Gymnasium lineage."
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
            "DIRECT; privileged planner; actuator authority zero |"
        ),
    )
    text = replace_exact(text, "Technical Report v1.0 is intended", "Technical Report v1.1 is intended")
    text = replace_exact(
        text,
        "| 3D stress result | `docs/research/physical_jepa_multi_embodiment_3d_result_v1.json` | Recompute completion, intervention, contact and recovery |",
        (
            "| 3D stress result | `docs/research/physical_jepa_multi_embodiment_3d_result_v1.json` | Recompute "
            "completion, intervention, contact and recovery |\n"
            "| External useful-autonomy protocol | `docs/research/physical_jepa_safety_gymnasium_protocol_v12.json` | "
            "Inspect runtime lock, seed boundary, candidate policy and frozen joint gates |\n"
            "| External useful-autonomy result | `docs/research/physical_jepa_safety_gymnasium_result_v12.json` | "
            "Recompute five arms, planner divergence, learned-only attribution and realized-cost reduction |\n"
            "| External useful-autonomy verification | `docs/research/physical_jepa_safety_gymnasium_verification_v12.json` | "
            "Confirm raw cases, exact seeds, hashes, gates, authority zero and non-promotion |"
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
        "Architecture rankings are domain-dependent. On the frozen physical catalog, the JEPA has the lowest normalized rollout error at horizons 1, 3, and 5; the MLP-minus-JEPA H=3 difference is 0.010156 with a paired episode-bootstrap 95% interval [0.009829, 0.010483]. FerrumOS instead favors the GRU at H=1 and H=3 and the JEPA at H=5. Both selected models show counterfactual directional sensitivity on paired temporal cases, yet calibration weakens under the registered distribution shift. At the frozen 0.99 threshold, rules-only, learned-only, and their union all intervene in 0 of 512 cases in each domain and miss all 256 simulator-labelled dangerous cases. The learned branch therefore adds zero marginal hazard blocks and zero safe-case interventions. A separately registered 3D PyBullet stress test produces an operationally unusable extreme: 288 interventions in 288 cases and 0% task completion. A subsequent externally designed, locally executed Safety-Gymnasium benchmark separates controller value from shield value on 128 untouched seeds. The privileged planner completes 94.53% of tasks and records 66.93% fewer hazard-cost events than the naive controller with zero shield interventions. The active union completes 91.41%, intervenes on 5.04% of proposals, recalls 61.58% of dangerous proposals, and increases realized hazard cost by 47.73%.",
        "Architecture rankings are domain-dependent. Physical JEPA has the lowest normalized rollout error at H=1, H=3, and H=5; its MLP-minus-JEPA H=3 difference is 0.010156 [0.009829, 0.010483]. FerrumOS favors the GRU at H=1 and H=3 and the JEPA at H=5. Both selected models are counterfactually directional, but calibration weakens under shift. At threshold 0.99, every arm intervenes in 0 of 512 cases per domain. A 3D PyBullet stress test reaches the other operationally unusable extreme: 288/288 interventions and 0% completion. On 128 untouched Safety-Gymnasium seeds, the privileged planner completes 94.53% of tasks and reduces hazard cost by 66.93%; the active union completes 91.41%, intervenes on 5.04%, recalls 61.58% of dangerous proposals, and increases hazard cost by 47.73%.",
    )
    text = replace_exact(
        text,
        "The runtime contribution is an authority factorization and evidence ladder rather than a claim of universal model superiority. FerrumOS previews execute in an authority-disabled QEMU path with no action dispatch, while Physical JEPA is evaluated through recorded testbed replay and actuator-disabled software physics. Deterministic policy, capability checks, operator confirmation, and physical actuator denial remain independent of learned prediction. All negative and failed frozen attempts are retained, the planner-only contrast and active-shield failure are reported together, protected deployed artifacts remain byte-identical, and promotion eligibility is false. The evidence supports a reproducible safety-runtime methodology and domain-specific predictive modeling; it does not establish production agent safety, live robot safety, formal correctness, or independent replication, physical deployment safety, or learned collision-avoidance value: the final benchmark's hazard reduction is attributed to privileged deterministic planning, while the active shield fails its frozen joint objective and the learned branch remains advisory.",
        "The contribution is an authority factorization and evidence ladder, not universal model superiority. FerrumOS previews run in authority-disabled QEMU; physical evidence is recorded replay and actuator-disabled software physics. Policy, capability, confirmation, and actuator denial remain independent of prediction. Every negative is retained, protected artifacts are byte-identical, and promotion is false. The evidence supports reproducible runtime methodology, not production, live-robot, formal, independent, physical-deployment, or learned-safety claims. The planner receives the final hazard reduction credit; the active shield fails its frozen joint objective and learning remains advisory.",
    )
    text = replace_exact(
        text,
        "The study extends two artifact-backed FerrumOS research lineages. The operating-system lineage evaluates action-conditioned forecasts in the unprivileged Heliox daemon before capability-gated kernel effects. The physical lineage evaluates a compact world model in simulated and recorded-sensor settings while disabling actuator authority. Both lineages already retain failed iterations and distinguish learned caution from deterministic control. The present work adds an architecture-controlled comparison, paired temporal interventions, uncertainty and calibration analysis, authority-disabled runtime tests, externally authored data intake, retained negative stress tests, and a prospective useful-autonomy evaluation in the externally maintained Safety-Gymnasium task environment [17].",
        "The study extends two artifact-backed FerrumOS lineages: unprivileged action-conditioned OS forecasts before capability-gated effects, and a compact physical model evaluated with actuator authority disabled. It adds matched architectures, paired interventions, calibration, authority-disabled runtime tests, external-data intake, retained negative stress tests, and a prospective Safety-Gymnasium evaluation [17].",
    )
    text = replace_exact(
        text,
        "This report contributes six things. First, it provides a matched two-domain architecture study covering MLP, action-conditioned JEPA, and GRU dynamics under equal data, optimization, parameter, seed, and final-case conditions. Second, it separates distributional prediction, counterfactual sensitivity, calibration, and thresholded intervention into independently reported outcomes. Third, it specifies an authority factorization in which learned prediction can add caution but cannot create execution authority or erase a deterministic block. Fourth, it builds a cross-domain evidence ladder spanning sealed offline catalogs, QEMU shadow execution, visible researcher-operated sessions, externally recorded testbed replay, and actuator-disabled software physics. Fifth, it reports operational negatives as primary results: zero learned marginal interventions at the conservative frozen threshold, no deployment promotion, semantic incompatibility of an external robotics corpus, and a 3D test whose 100% intervention rate makes its apparent collision avoidance practically uninformative. Sixth, it prospectively freezes a joint completion, intervention, recall, false-positive, and realized-cost objective, retains every failed or non-beneficial protocol stage, and reports a once-opened Safety-Gymnasium final where the planner-only arm generalizes but the selected active shield does not.",
        "This report contributes six things: a matched MLP/JEPA/GRU study across two domains; separate prediction, causal, calibration, and intervention estimands; an authority factorization where learning cannot grant permission or erase deterministic denial; an evidence ladder from sealed catalogs to authority-disabled runtime tests; primary reporting of zero learned marginal caution, incompatible external data, and an all-stop 3D negative; and a prospective external-task result where the planner-only arm generalizes but the selected active shield does not.",
    )
    text = replace_exact(
        text,
        "The final temporal catalogs and 3D stress benchmark are researcher-designed deterministic-software evaluations. Safety-Gymnasium supplies an external task definition, layouts, observations, and hazard costs, but the adapter, privileged planner, shield, local execution, and analysis are researcher-authored. The external physical evidence is recorded sensor replay, not live Ferrum hardware-in-the-loop. FerrumOS evidence comes from disposable QEMU guests and short researcher-operated sessions, not production users. No experiment establishes formal safety, independent assessment, human-contact safety, broad embodiment transfer, or a universally superior architecture. The selected research artifacts are not deployed, and no protected deployed artifact is replaced.",
        "The temporal catalogs and 3D stress are locally designed software tests. Safety-Gymnasium supplies the task and costs, but the adapter, privileged planner, shield, execution, and analysis are local. Physical evidence is replay, not live HIL; FerrumOS evidence is disposable QEMU, not production use. No result establishes formal, independent, human-contact, broad-transfer, or deployment safety, and no protected artifact is replaced.",
    )
    if "reviewer-requested" in text.lower() or "opposite unusable extreme" in text.lower():
        raise ValueError("forbidden archival wording remains")
    OUTPUT.write_text(text, encoding="utf-8", newline="\n")
    print(OUTPUT.relative_to(ROOT).as_posix())


if __name__ == "__main__":
    main()
