#!/usr/bin/env python3
"""Verify the registered cross-domain world-model selection and final audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cross_domain_world_model_models as models  # noqa: E402
import evaluate_cross_domain_world_models as study  # noqa: E402


PROTOCOL = ROOT / "docs/research/cross_domain_world_model_improvement_protocol_v1.json"
DEFAULT_SELECTION = ROOT / "docs/research/cross_domain_world_model_selection_v1.json"
DEFAULT_RESULT = (
    ROOT / "docs/research/cross_domain_world_model_architecture_result_v1.json"
)
DEFAULT_OUTPUT = ROOT / "docs/research/cross_domain_world_model_verification_v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def finite(value) -> bool:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    if isinstance(value, list):
        return all(finite(item) for item in value)
    if isinstance(value, dict):
        return all(finite(item) for item in value.values())
    return False


def verify_selection(protocol: dict, selection: dict) -> tuple[dict, dict]:
    settings = protocol["architecture_controlled_comparison"]["shared_conditions"]
    checks = {
        "protocol_id_matches": selection.get("protocol_id") == protocol["protocol_id"],
        "protocol_digest_matches": selection.get("protocol_sha256") == sha256(PROTOCOL),
        "stage_is_validation_only": selection.get("stage")
        == "validation-only-selection",
        "selection_passed": selection.get("selection_passed") is True,
        "final_test_not_opened": selection.get("final_test_opened") is False,
        "promotion_disabled": selection.get("promotion_eligible") is False,
        "recorded_checks_pass": all(selection.get("checks", {}).values()),
        "registered_seeds_match": selection.get("seeds") == settings["training_seeds"],
        "registered_settings_match": selection.get("settings") == settings,
        "domains_match": set(selection.get("domains", {})) == {"ferrumos", "physical"},
        "all_numeric_values_finite": finite(selection),
    }
    checkpoints = []
    parameter_counts = {}
    for domain_name, domain in selection.get("domains", {}).items():
        checks[f"{domain_name}_methods_match"] = set(domain.get("methods", {})) == set(
            models.METHODS
        )
        parameter_counts[domain_name] = {}
        for method, runs in domain.get("methods", {}).items():
            checks[f"{domain_name}_{method}_seed_count"] = len(runs) == len(
                settings["training_seeds"]
            )
            parameter_counts[domain_name][method] = []
            for run in runs:
                checkpoint = ROOT / run["checkpoint"]["path"]
                checkpoint_ok = (
                    checkpoint.is_file()
                    and sha256(checkpoint) == run["checkpoint"]["sha256"]
                    and checkpoint.stat().st_size == run["checkpoint"]["bytes"]
                )
                checkpoints.append(
                    {
                        "domain": domain_name,
                        "method": method,
                        "seed": run["seed"],
                        "path": run["checkpoint"]["path"],
                        "verified": checkpoint_ok,
                    }
                )
                parameter_counts[domain_name][method].append(
                    run["trainable_parameters"]
                )
                checks[f"checkpoint_{domain_name}_{method}_{run['seed']}"] = (
                    checkpoint_ok
                )
                checks[f"updates_{domain_name}_{method}_{run['seed']}"] = (
                    run["optimizer_updates_completed"] == settings["optimizer_updates"]
                )
                minimum = settings["trainable_parameter_budget"] * (
                    1.0 - settings["parameter_budget_tolerance_fraction"]
                )
                checks[f"parameters_{domain_name}_{method}_{run['seed']}"] = (
                    minimum
                    <= run["trainable_parameters"]
                    <= settings["trainable_parameter_budget"]
                )
                checks[f"finite_{domain_name}_{method}_{run['seed']}"] = run[
                    "validation"
                ]["all_predictions_finite"]
    protected = study.verify_digest_map(protocol["protected_deployed_artifacts"])
    frozen = study.verify_digest_map(protocol["frozen_research_inputs"])
    checks["protected_deployed_digests_match"] = all(protected.values())
    checks["frozen_research_inputs_match"] = all(frozen.values())
    return checks, {"checkpoints": checkpoints, "parameter_counts": parameter_counts}


def verify_result(protocol: dict, selection_path: Path, result: dict) -> dict:
    checks = {
        "protocol_id_matches": result.get("protocol_id") == protocol["protocol_id"],
        "protocol_digest_matches": result.get("protocol_sha256") == sha256(PROTOCOL),
        "selection_digest_matches": result.get("selection_sha256")
        == sha256(selection_path),
        "stage_matches": result.get("stage")
        == "architecture-controlled-final-evaluation",
        "opened_once": result.get("final_open_count") == 1,
        "evaluation_passed": result.get("evaluation_passed") is True,
        "promotion_disabled": result.get("promotion_eligible") is False,
        "recorded_checks_pass": all(result.get("checks", {}).values()),
        "all_numeric_values_finite": finite(result),
        "domains_match": set(result.get("domains", {})) == {"ferrumos", "physical"},
    }
    for domain_name, domain in result.get("domains", {}).items():
        checks[f"{domain_name}_methods_match"] = set(domain.get("methods", {})) == set(
            models.METHODS
        )
        comparisons = domain.get("paired_architecture_comparisons", {})
        checks[f"{domain_name}_three_pairwise_comparisons"] = len(comparisons) == 3
        for method, record in domain.get("methods", {}).items():
            checks[f"{domain_name}_{method}_horizons"] = set(
                record.get("rollout", {})
            ) == {
                "h1",
                "h3",
                "h5",
            }
            checks[f"{domain_name}_{method}_coverage_curve"] = [
                item["coverage"] for item in record["uncertainty"]["risk_coverage"]
            ] == [1.0, 0.9, 0.75, 0.5, 0.25]
    protected = study.verify_digest_map(protocol["protected_deployed_artifacts"])
    checks["protected_deployed_digests_match"] = all(protected.values())
    checks["recorded_deployed_digests_unchanged"] = result.get(
        "deployed_digests_before"
    ) == result.get("deployed_digests_after")
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--result", type=Path, default=DEFAULT_RESULT)
    parser.add_argument("--selection-only", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    protocol = load(PROTOCOL)
    selection = load(args.selection)
    selection_checks, details = verify_selection(protocol, selection)
    payload = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "selection_path": study.repository_path(args.selection),
        "selection_sha256": sha256(args.selection),
        "selection_checks": selection_checks,
        "selection_verified": all(selection_checks.values()),
        "details": details,
        "result_verified": None,
        "promotion_eligible": False,
    }
    if not args.selection_only:
        result = load(args.result)
        result_checks = verify_result(protocol, args.selection, result)
        payload.update(
            {
                "result_path": study.repository_path(args.result),
                "result_sha256": sha256(args.result),
                "result_checks": result_checks,
                "result_verified": all(result_checks.values()),
            }
        )
    payload["verification_passed"] = payload["selection_verified"] and (
        payload["result_verified"] in (None, True)
    )
    study.write_json(args.output, payload)
    print(
        json.dumps(
            {
                "output": study.repository_path(args.output),
                "verification_passed": payload["verification_passed"],
            },
            indent=2,
        )
    )
    return 0 if payload["verification_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
