#!/usr/bin/env python3
"""Verify the learned-contribution selection, catalogs, and result."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_cross_domain_learned_contribution as audit  # noqa: E402
import evaluate_cross_domain_world_models as architecture  # noqa: E402


PROTOCOL = ROOT / "docs/research/cross_domain_learned_contribution_protocol_v1.json"
SELECTION = ROOT / "docs/research/cross_domain_learned_contribution_selection_v1.json"
RESULT = ROOT / "docs/research/cross_domain_learned_contribution_result_v1.json"
OUTPUT = ROOT / "docs/research/cross_domain_learned_contribution_verification_v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def finite(value) -> bool:
    if value is None or isinstance(value, (bool, str)):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    if isinstance(value, list):
        return all(finite(item) for item in value)
    if isinstance(value, dict):
        return all(finite(item) for item in value.values())
    return False


def verify_checkpoints(selection: dict) -> dict:
    checks = {}
    for domain, record in selection["domains"].items():
        for checkpoint in record["checkpoints"]:
            path = ROOT / checkpoint["path"]
            seed = path.stem.rsplit("-", 1)[-1]
            checks[f"{domain}_{record['method']}_{seed}"] = (
                path.is_file()
                and sha256(path) == checkpoint["sha256"]
                and path.stat().st_size == checkpoint["bytes"]
            )
    return checks


def verify_metric_shape(domain: str, metric: dict, protocol: dict, final: bool) -> dict:
    expected = (
        protocol["generator"]["final"]["expected_cases_per_domain"]
        if final
        else 2
        * protocol["generator"]["development"]["pairs_per_family"]
        * len(protocol["generator"][f"{domain}_families"])
    )
    pairs = expected // 2
    checks = {
        "case_count": metric["cases"] == expected,
        "balanced_labels": metric["dangerous"] == metric["safe"] == pairs,
        "threshold_in_grid": 0.01 <= metric["threshold"] <= 0.99,
        "counterfactual_pair_count": metric["counterfactual"]["pairs"] == pairs,
        "multi_action_horizons": set(metric["multi_action_rollout"]) == {"h3", "h5"},
        "coverage_curve": [
            item["coverage"] for item in metric["uncertainty"]["risk_coverage_h5"]
        ]
        == [1.0, 0.9, 0.75, 0.5, 0.25],
        "reliability_bins": len(metric["calibration_metrics"]["reliability_bins"])
        == protocol["statistics"]["reliability_bins"],
        "rule_blocks_not_erased": metric["marginal_learned_contribution"][
            "rule_blocks_erased"
        ]
        == 0,
        "bootstrap_resamples": all(
            metric["multi_action_rollout"][horizon]["resamples"]
            == protocol["statistics"]["paired_episode_bootstrap_resamples"]
            for horizon in ("h3", "h5")
        ),
        "all_values_finite": finite(metric),
    }
    return checks


def verify_selection(protocol: dict, selection: dict) -> tuple[dict, dict]:
    frozen = audit.verify_frozen(protocol)
    catalogs = audit.catalog_paths(protocol)
    checkpoints = verify_checkpoints(selection)
    checks = {
        "protocol_id_matches": selection["protocol_id"] == protocol["protocol_id"],
        "protocol_digest_matches": selection["protocol_sha256"] == sha256(PROTOCOL),
        "validation_only_stage": selection["stage"] == "validation-only-selection",
        "selection_passed": selection["selection_passed"] is True,
        "final_not_opened": selection["final_test_opened"] is False,
        "promotion_disabled": selection["promotion_eligible"] is False,
        "recorded_checks_pass": all(selection["checks"].values()),
        "frozen_inputs_match": all(frozen.values()),
        "final_catalogs_absent": not any(path.exists() for path in catalogs.values()),
        "checkpoints_match": all(checkpoints.values()),
        "domains_match": set(selection["domains"]) == {"ferrumos", "physical"},
        "all_values_finite": finite(selection),
    }
    metrics = {}
    for domain, record in selection["domains"].items():
        checks[f"{domain}_method"] = (
            record["method"]
            == protocol["model_selection"]["expected_from_frozen_selection"][domain]
        )
        current = verify_metric_shape(domain, record["development"], protocol, False)
        metrics[domain] = current
        checks[f"{domain}_metric_shape"] = all(current.values())
    architecture_protocol = load(audit.ARCHITECTURE_PROTOCOL)
    protected = architecture.verify_digest_map(
        architecture_protocol["protected_deployed_artifacts"]
    )
    checks["protected_deployed_digests_match"] = all(protected.values())
    return checks, {
        "frozen_inputs": frozen,
        "checkpoints": checkpoints,
        "metric_checks": metrics,
        "protected_deployed_artifacts": protected,
    }


def verify_catalog(domain: str, path: Path, protocol: dict) -> dict:
    catalog = load(path)
    final = protocol["generator"]["final"]
    expected = audit.generate(
        domain,
        protocol["generator"][f"{domain}_families"],
        final["pairs_per_family"],
        final[f"{domain}_seed"],
    )
    required = set(protocol["generator"]["required_case_fields"])
    return {
        "protocol_id_matches": catalog["protocol_id"] == protocol["protocol_id"],
        "domain_matches": catalog["domain"] == domain,
        "seed_matches": catalog["seed"] == final[f"{domain}_seed"],
        "case_count_matches": len(catalog["cases"])
        == final["expected_cases_per_domain"],
        "cases_reproduce_exactly": catalog["cases"] == expected,
        "required_fields_present": all(
            required <= set(case) for case in catalog["cases"]
        ),
        "software_evidence_label": catalog["evidence_class"]
        == protocol["independence"]["label_without_manifest"],
    }


def verify_result(protocol: dict, selection: dict, result: dict) -> tuple[dict, dict]:
    catalogs = audit.catalog_paths(protocol)
    catalog_checks = {
        domain: verify_catalog(domain, path, protocol)
        for domain, path in catalogs.items()
    }
    checks = {
        "protocol_id_matches": result["protocol_id"] == protocol["protocol_id"],
        "protocol_digest_matches": result["protocol_sha256"] == sha256(PROTOCOL),
        "selection_digest_matches": result["selection_sha256"] == sha256(SELECTION),
        "single_final_stage": result["stage"] == "single-final-evaluation",
        "opened_once": result["final_open_count"] == 1,
        "evaluation_passed": result["evaluation_passed"] is True,
        "promotion_disabled": result["promotion_eligible"] is False,
        "independent_assessment_not_claimed": result["independent_assessment"] is False,
        "evidence_class_matches": result["evidence_class"]
        == protocol["independence"]["label_without_manifest"],
        "recorded_checks_pass": all(result["checks"].values()),
        "catalogs_verify": all(all(item.values()) for item in catalog_checks.values()),
        "all_values_finite": finite(result),
    }
    metric_checks = {}
    for domain, metric in result["domains"].items():
        current = verify_metric_shape(domain, metric, protocol, True)
        metric_checks[domain] = current
        checks[f"{domain}_metric_shape"] = all(current.values())
        checks[f"{domain}_frozen_calibration"] = (
            metric["calibration"]
            == selection["domains"][domain]["development"]["calibration"]
            and metric["threshold"]
            == selection["domains"][domain]["development"]["threshold"]
        )
        path = catalogs[domain]
        checks[f"{domain}_catalog_digest"] = result["catalogs"][domain][
            "sha256"
        ] == sha256(path)
    architecture_protocol = load(audit.ARCHITECTURE_PROTOCOL)
    protected = architecture.verify_digest_map(
        architecture_protocol["protected_deployed_artifacts"]
    )
    checks["protected_deployed_digests_match"] = all(protected.values())
    return checks, {
        "catalog_checks": catalog_checks,
        "metric_checks": metric_checks,
        "protected_deployed_artifacts": protected,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection-only", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    protocol = load(PROTOCOL)
    selection = load(SELECTION)
    selection_checks, selection_details = verify_selection(protocol, selection)
    payload = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "selection_sha256": sha256(SELECTION),
        "selection_checks": selection_checks,
        "selection_verified": all(selection_checks.values()),
        "selection_details": selection_details,
        "result_verified": None,
        "promotion_eligible": False,
    }
    if not args.selection_only:
        result = load(RESULT)
        result_checks, result_details = verify_result(protocol, selection, result)
        payload.update(
            {
                "result_sha256": sha256(RESULT),
                "result_checks": result_checks,
                "result_verified": all(result_checks.values()),
                "result_details": result_details,
            }
        )
    payload["verification_passed"] = payload["selection_verified"] and payload[
        "result_verified"
    ] in (None, True)
    architecture.write_json(args.output, payload)
    print(
        json.dumps(
            {
                "output": architecture.repository_path(args.output),
                "verification_passed": payload["verification_passed"],
            },
            indent=2,
        )
    )
    return 0 if payload["verification_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
