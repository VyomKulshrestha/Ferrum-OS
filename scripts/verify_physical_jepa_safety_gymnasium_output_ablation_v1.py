#!/usr/bin/env python3
"""Verify the sealed frozen-JEPA-output Safety-Gymnasium ablation."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
from pathlib import Path
import subprocess

import numpy as np

import run_physical_jepa_safety_gymnasium as benchmark
import run_physical_jepa_safety_gymnasium_output_ablation_v1 as ablation


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = (
    ROOT
    / "docs/research/physical_jepa_safety_gymnasium_output_ablation_protocol_v1.json"
)
RESULT_PATH = (
    ROOT / "docs/research/physical_jepa_safety_gymnasium_output_ablation_result_v1.json"
)
VERIFICATION_PATH = (
    ROOT
    / "docs/research/physical_jepa_safety_gymnasium_output_ablation_verification_v1.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def close(left: float, right: float) -> bool:
    return math.isclose(float(left), float(right), rel_tol=1e-12, abs_tol=1e-12)


def same(left: object, right: object) -> bool:
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            same(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            same(left_item, right_item) for left_item, right_item in zip(left, right)
        )
    if isinstance(left, (float, int)) and isinstance(right, (float, int)):
        return close(left, right)
    return left == right


def main() -> None:
    protocol = load_json(PROTOCOL_PATH)
    result = load_json(RESULT_PATH)
    expected_arms = [arm["id"] for arm in protocol["arms"]]
    boundary = protocol["prospective_boundary"]["fresh_final_seed_range"]
    expected_seeds = list(
        range(boundary["start"], boundary["start"] + boundary["count"])
    )
    adapter_record = protocol["frozen_warning_pipeline"]["adapter"]
    adapter = load_json(ROOT / adapter_record["path"])
    registered_commit = result["protocol"]["registered_commit"]
    checks: dict[str, bool] = {
        "result_protocol_digest_matches": result["protocol"]["sha256"]
        == sha256(PROTOCOL_PATH),
        "registration_commit_recorded": bool(registered_commit),
        "protocol_matches_registration_commit": subprocess.run(
            [
                "git",
                "diff",
                "--quiet",
                registered_commit,
                "--",
                PROTOCOL_PATH.relative_to(ROOT).as_posix(),
            ],
            cwd=ROOT,
            check=False,
        ).returncode
        == 0,
        "fresh_seed_range_matches": result["fresh_final_seed_range"] == boundary,
        "single_registered_two_arm_access": result[
            "final_seed_range_opened_once_for_registered_two_arm_run"
        ]
        is True,
        "runtime_versions_match": result["runtime"]["versions_match"],
        "runtime_source_matches": result["runtime"]["source_matches"],
        "arm_set_exact": set(result["arms"]) == set(expected_arms),
        "same_runner_arm": protocol["frozen_warning_pipeline"]["runner_arm"]
        == "planner_rules_plus_learned",
        "same_operating_threshold": all(
            close(
                result["arms"][name]["learned_risk_threshold"],
                protocol["frozen_policy"]["learned_risk_threshold"],
            )
            for name in expected_arms
        ),
        "same_adapter_all_arms": all(
            result["arms"][name]["adapter"] == adapter_record for name in expected_arms
        ),
        "frozen_adapter_digest": sha256(ROOT / adapter_record["path"])
        == adapter_record["sha256"],
        "frozen_jepa_digest": sha256(ROOT / protocol["frozen_artifact"]["path"])
        == protocol["frozen_artifact"]["sha256"],
        "all_registered_inputs_match": all(
            sha256(ROOT / record["path"]) == record["sha256"]
            for record in protocol["registered_inputs"].values()
        ),
        "all_toolchain_digests_match": all(
            sha256(ROOT / record["path"]) == record["sha256"]
            for record in protocol["toolchain"].values()
        ),
        "physical_actuator_attempts_zero": result["authority"][
            "physical_actuator_attempts"
        ]
        == 0,
        "physical_actuator_deliveries_zero": result["authority"][
            "physical_actuator_deliveries"
        ]
        == 0,
        "promotion_ineligible": result["authority"]["promotion_eligible"] is False,
        "promotion_not_attempted": result["authority"]["promotion_attempted"] is False,
        "claim_boundary_exact": result["claim_boundary"] == protocol["claim_boundary"],
        "all_outcomes_retained": all(
            result["outcome_retention"][key]
            for key in (
                "all_registered_arms_written",
                "all_episode_summaries_written",
                "all_step_cases_written",
                "all_paired_effects_and_signs_written",
            )
        ),
        "prior_negative_evidence_set_exact": set(
            result["outcome_retention"][
                "prior_negative_and_failed_evidence_left_in_place"
            ]
        )
        == set(protocol["retained_prior_evidence"]),
    }

    for name, record in protocol["protected_files"].items():
        current = sha256(ROOT / record["path"])
        checks[f"{name}_matches_registration"] = current == record["sha256"]
        checks[f"{name}_before_after_current_identical"] = (
            result["authority"]["protected_before_sha256"][name]
            == result["authority"]["protected_after_sha256"][name]
            == current
        )
    checks["all_protected_files_unchanged"] = result["authority"][
        "protected_files_unchanged"
    ]

    masked_spec = next(
        arm["feature_intervention"]
        for arm in protocol["arms"]
        if arm["id"] == "development-mean-masked-jepa"
    )
    masked_indices = [int(value) for value in masked_spec["raw_feature_indices"]]
    replacement_values = np.asarray(masked_spec["replacement_values"], dtype=np.float64)
    all_indices = set(range(int(adapter["raw_feature_count"])))
    nonmasked_indices = sorted(all_indices - set(masked_indices))
    raw_differences = np.zeros(len(masked_indices), dtype=bool)

    for name in expected_arms:
        record = result["arms"][name]
        episodes = record["episode_summaries"]
        checks[f"{name}_seed_set"] = (
            sorted(int(item["seed"]) for item in episodes) == expected_seeds
        )
        recomputed = benchmark.aggregate(episodes)
        recomputed["intervention_precision"] = recomputed[
            "true_positive_interventions"
        ] / max(1, recomputed["interventions"])
        checks[f"{name}_aggregate_recomputes"] = same(recomputed, record["aggregate"])
        catalog = ROOT / record["case_catalog"]["path"]
        checks[f"{name}_case_digest"] = (
            sha256(catalog) == record["case_catalog"]["sha256"]
        )
        rows = 0
        case_seeds = set()
        features_valid = True
        scores_recompute = True
        with gzip.open(catalog, "rt", encoding="utf-8") as handle:
            for line in handle:
                case = json.loads(line)
                rows += 1
                case_seeds.add(int(case["seed"]))
                raw = np.asarray(case["risk_adapter_features"], dtype=np.float64)
                scored = np.asarray(
                    case["risk_adapter_scored_features"], dtype=np.float64
                )
                if raw.shape != scored.shape or raw.size != int(
                    adapter["raw_feature_count"]
                ):
                    features_valid = False
                    continue
                if name == "observed-frozen-jepa":
                    features_valid = features_valid and np.array_equal(raw, scored)
                else:
                    features_valid = features_valid and np.array_equal(
                        scored[masked_indices], replacement_values
                    )
                    features_valid = features_valid and np.array_equal(
                        raw[nonmasked_indices], scored[nonmasked_indices]
                    )
                    raw_differences |= raw[masked_indices] != replacement_values
                scores_recompute = scores_recompute and close(
                    benchmark.risk_adapter_score(scored, adapter),
                    case["learned_risk_score"],
                )
        checks[f"{name}_case_rows"] = (
            rows == record["case_catalog"]["rows"] == record["aggregate"]["proposals"]
        )
        checks[f"{name}_case_seed_set"] = sorted(case_seeds) == expected_seeds
        checks[f"{name}_feature_intervention_exact"] = features_valid
        checks[f"{name}_scores_recompute"] = scores_recompute
    checks["masked_jepa_values_were_nonconstant_before_intervention"] = bool(
        np.all(raw_differences)
    )

    recomputed_contrast = ablation.paired_bootstrap(
        result["arms"]["observed-frozen-jepa"]["episode_summaries"],
        result["arms"]["development-mean-masked-jepa"]["episode_summaries"],
        seed=protocol["uncertainty"]["paired_bootstrap_seed"],
        resamples=protocol["uncertainty"]["paired_bootstrap_resamples"],
    )
    checks["paired_effects_recompute"] = same(
        recomputed_contrast, result["paired_output_contribution"]
    )
    checks["null_intervals_retained_exactly"] = (
        result["outcome_retention"]["null_intervals_written"]
        == recomputed_contrast["intervals_including_zero_retained"]
    )
    checks["prior_evidence_digests_match"] = all(
        sha256(ROOT / record["path"]) == record["sha256"]
        for record in protocol["retained_prior_evidence"].values()
    )

    all_checks_pass = all(checks.values())
    verification = {
        "schema": "physical-jepa-safety-gymnasium-output-ablation-verification-v1",
        "protocol": {
            "path": PROTOCOL_PATH.relative_to(ROOT).as_posix(),
            "sha256": sha256(PROTOCOL_PATH),
        },
        "result": {
            "path": RESULT_PATH.relative_to(ROOT).as_posix(),
            "sha256": sha256(RESULT_PATH),
        },
        "checks": checks,
        "all_checks_pass": all_checks_pass,
        "promotion_eligible": False,
        "claim_boundary": protocol["claim_boundary"],
    }
    VERIFICATION_PATH.write_text(
        json.dumps(verification, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(verification, indent=2, sort_keys=True))
    if not all_checks_pass:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
