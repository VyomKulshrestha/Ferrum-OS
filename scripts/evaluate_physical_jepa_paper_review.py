#!/usr/bin/env python3
"""Reproduce reviewer-requested uncertainty and PyBullet marginal attribution.

This is post-hoc characterization only. It has no selection, promotion, or
deployment authority and refuses to overwrite its evidence output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_physical_jepa_paper as paper  # noqa: E402
import evaluate_physical_jepa_robustness as robustness  # noqa: E402
import physical_incident_scenarios as incidents  # noqa: E402


DEFAULT_PROTOCOL = ROOT / "docs" / "research" / "physical_jepa_paper_review_protocol_v1.json"
DEFAULT_OUTPUT = ROOT / "docs" / "research" / "physical_jepa_paper_review_result_v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wilson_interval(successes: int, trials: int) -> tuple[float, float]:
    z = 1.959963984540054
    proportion = successes / trials
    denominator = 1.0 + z * z / trials
    center = (proportion + z * z / (2.0 * trials)) / denominator
    half_width = z * math.sqrt(
        proportion * (1.0 - proportion) / trials
        + z * z / (4.0 * trials * trials)
    ) / denominator
    return center - half_width, center + half_width


def exact_mcnemar_p(first_only: int, second_only: int) -> float:
    discordant = first_only + second_only
    if discordant == 0:
        return 1.0
    smaller = min(first_only, second_only)
    lower_tail = sum(math.comb(discordant, k) for k in range(smaller + 1))
    return min(1.0, 2.0 * lower_tail / (2**discordant))


def predictor_for(name: str, path: Path):
    if name == "ordinary_supervised_mlp":
        weights = paper.load_supervised_mlp(path)
        return lambda state, action, features: paper.supervised_prediction(
            weights, state, action, features
        )
    weights = robustness.load_artifact(path)
    return lambda state, action, features: robustness.prediction(
        weights, state, action, features
    )


def decision_for(name, rows, labels, paper_protocol, paper_results):
    artifact = paper_protocol["artifacts"][name]
    path = ROOT / artifact["path"]
    if sha256(path) != artifact["sha256"]:
        raise ValueError(f"{name} artifact drifted")
    _, _, scores = paper.score_rows(rows, predictor_for(name, path))
    result = paper_results["methods"][name]
    params = result["platt_parameters"]
    probability = paper.probabilities(
        scores, np.asarray([params["slope"], params["intercept"]])
    )
    decisions = probability >= result["selected_probability_threshold"]
    actual = paper.confusion(labels, decisions)
    if actual != result["test_operating_point"]:
        raise ValueError(f"{name} decisions do not reproduce the frozen report")
    return decisions


def matched_fpr_audit(review_protocol, paper_protocol, paper_results):
    spec = paper_protocol["paper_test_partition"]
    rows, _ = incidents.generate_partition(
        spec["partition"],
        spec["episodes_per_source"],
        spec["steps"],
        spec["seed"],
        ROOT / spec["catalog"],
    )
    labels, _, _ = paper.score_rows(rows)
    methods = review_protocol["matched_fpr_uncertainty"]["methods"]
    decisions = {
        name: decision_for(name, rows, labels, paper_protocol, paper_results)
        for name in methods
    }
    positives = int(labels.sum())
    summaries = {}
    misses = {}
    for name in methods:
        miss = labels & ~decisions[name]
        misses[name] = miss
        count = int(miss.sum())
        lower, upper = wilson_interval(count, positives)
        summaries[name] = {
            "false_negatives": count,
            "dangerous_transitions": positives,
            "false_negative_rate": count / positives,
            "wilson_95_percent": {"lower": lower, "upper": upper},
        }

    first, second = methods
    first_only = int(np.sum(misses[first] & ~misses[second]))
    second_only = int(np.sum(misses[second] & ~misses[first]))
    both = int(np.sum(misses[first] & misses[second]))
    return {
        "methods": summaries,
        "paired_exact_mcnemar": {
            f"{first}_miss_v5_catch": first_only,
            f"v5_miss_{first}_catch": second_only,
            "both_miss": both,
            "discordant": first_only + second_only,
            "two_sided_p_value": exact_mcnemar_p(first_only, second_only),
            "separable_at_alpha_0_05": exact_mcnemar_p(first_only, second_only)
            < 0.05,
        },
    }


def pybullet_catalog_audit(result):
    cases = result["cases"]
    family_sizes = {}
    for case in cases:
        family_sizes[case["family"]] = family_sizes.get(case["family"], 0) + 1
    learned_only = [
        case
        for case in cases
        if case["learned_alert"] and not case["deterministic_block"]
    ]
    learned_only_collisions = [case for case in learned_only if case["unshielded_collision"]]
    missed_caught_by_rule = [
        case
        for case in cases
        if case["unshielded_collision"]
        and case["deterministic_block"]
        and not case["learned_alert"]
    ]
    return {
        "catalog_sha256": result["catalog_sha256"],
        "episodes": len(cases),
        "family_sizes": dict(sorted(family_sizes.items())),
        "interventions": result["summary"]["interventions"],
        "learned_only_interventions": len(learned_only),
        "learned_only_intervention_families": dict(
            sorted(
                {
                    family: sum(case["family"] == family for case in learned_only)
                    for family in {case["family"] for case in learned_only}
                }.items()
            )
        ),
        "learned_only_collisions_avoided": len(learned_only_collisions),
        "learned_missed_collisions_caught_by_rule": len(missed_caught_by_rule),
        "unshielded_collisions": result["summary"]["unshielded_collisions"],
        "shielded_collisions": result["summary"]["shielded_collisions"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite evidence: {args.output}")

    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    if protocol["analysis_status_at_registration"] != "not_run":
        raise ValueError("review protocol was not registered before analysis")
    inputs = {}
    for name, record in protocol["inputs"].items():
        path = ROOT / record["path"]
        actual = sha256(path)
        if actual != record["sha256"]:
            raise ValueError(f"registered input drifted: {name}")
        inputs[name] = {"path": record["path"], "sha256": actual}

    paper_protocol = json.loads(
        (ROOT / protocol["inputs"]["paper_protocol"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    paper_results = json.loads(
        (ROOT / protocol["inputs"]["paper_results"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    v1 = json.loads(
        (ROOT / protocol["inputs"]["blinded_benchmark_v1"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    v2 = json.loads(
        (ROOT / protocol["inputs"]["blinded_benchmark_v2"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    matched_fpr = matched_fpr_audit(protocol, paper_protocol, paper_results)
    pybullet = {
        "sealed_v1": pybullet_catalog_audit(v1),
        "sealed_v2": pybullet_catalog_audit(v2),
    }
    checks = {
        "frozen_inputs_match": True,
        "mlp_and_v5_counts_reproduce": all(
            item["false_negatives"]
            == paper_results["methods"][name]["test_operating_point"]["fn"]
            for name, item in matched_fpr["methods"].items()
        ),
        "v5_point_estimate_is_not_significantly_separable_from_mlp": not matched_fpr[
            "paired_exact_mcnemar"
        ]["separable_at_alpha_0_05"],
        "both_catalogs_have_structural_83_interventions": all(
            item["interventions"] == 83
            and item["family_sizes"]
            == {
                "boundary_safe": 128,
                "clear_safe": 176,
                "collision_course": 80,
                "near_safe": 128,
            }
            and item["learned_only_interventions"] == 3
            and item["learned_only_intervention_families"] == {"boundary_safe": 3}
            for item in pybullet.values()
        ),
        "v2_learned_path_avoids_no_incremental_collision": pybullet["sealed_v2"][
            "learned_only_collisions_avoided"
        ]
        == 0,
        "v2_rule_catches_four_learned_misses": pybullet["sealed_v2"][
            "learned_missed_collisions_caught_by_rule"
        ]
        == 4,
        "deployed_artifact_unchanged": sha256(
            ROOT / protocol["inputs"]["deployed_artifact"]["path"]
        )
        == protocol["inputs"]["deployed_artifact"]["sha256"],
    }
    report = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(args.protocol),
        "analysis_role": protocol["analysis_role"],
        "inputs": inputs,
        "matched_fpr_uncertainty": matched_fpr,
        "pybullet_marginal_audit": pybullet,
        "checks": checks,
        "all_checks_pass": all(checks.values()),
        "claim_boundary": "Post-hoc statistical and attribution audit of frozen deterministic-simulator and third-party software-simulation evidence; not model selection, promotion, HIL, physical deployment, certification, or independent assessment.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["all_checks_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
