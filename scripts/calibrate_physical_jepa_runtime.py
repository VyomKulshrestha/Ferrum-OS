#!/usr/bin/env python3
"""Select and test a conservative runtime-clearance threshold on frozen splits."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_physical_jepa_robustness as robustness  # noqa: E402
import physical_qualification_scenarios as scenarios  # noqa: E402
import train_physical_world_model as simulator  # noqa: E402

PROTOCOL = (
    ROOT / "docs" / "research" / "physical_jepa_runtime_calibration_v1_protocol.json"
)
ARTIFACT = ROOT / "userland" / "heliox-daemon" / "physical_world_model.bin"
OUTPUT = ROOT / "docs" / "research" / "physical_jepa_runtime_calibration_v1.json"


def evaluate(rows, weights, clearance_threshold: float) -> dict:
    predictions = []
    finite = True
    errors = []
    for row in rows:
        state, action, features, actual = row[2], row[3], row[4], row[5]
        predicted = robustness.prediction(weights, state, action, features)
        finite = finite and bool(np.isfinite(predicted).all())
        errors.append(
            float(np.mean(np.abs(predicted - actual) / simulator.STATE_RANGES))
        )
        moving = action == simulator.MOVE and features[2] > 0.1
        learned = bool(
            (moving and predicted[simulator.CLEARANCE] < clearance_threshold)
            or (
                moving
                and state[simulator.HUMANS] > 0
                and predicted[simulator.VELOCITY] > 0.16
            )
            or predicted[simulator.MARGIN] < 0.01
            or (moving and predicted[simulator.BATTERY] < 0.08)
            or (moving and predicted[simulator.LINK] < 0.08)
            or (action != simulator.STOP and state[simulator.ESTOP] > 0.5)
            or (action == simulator.REPAIR and state[simulator.APPROVAL] < 0.5)
        )
        predictions.append(simulator.rules_block(state, action, features) or learned)
    prediction_iter = iter(predictions)
    confusion = simulator.confusion(rows, lambda row: next(prediction_iter))
    return {
        **confusion,
        "all_predictions_finite": finite,
        "normalized_one_step_error": float(np.mean(errors)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    parser.add_argument("--artifact", type=Path, default=ARTIFACT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    digest = hashlib.sha256(args.artifact.read_bytes()).hexdigest()
    if digest != protocol["artifact_sha256"]:
        raise SystemExit("artifact digest differs from registered calibration")
    weights = robustness.load_artifact(args.artifact)
    validation_rows, validation_cases = scenarios.generate(
        protocol["validation"]["rows"], protocol["validation"]["seed"]
    )
    candidates = []
    for threshold in protocol["candidate_clearance_thresholds"]:
        metrics = evaluate(validation_rows, weights, threshold)
        candidates.append({"clearance_threshold": threshold, "validation": metrics})
    selection = protocol["selection"]
    if selection.get("mode") == "validation_budgeted_false_positive":
        eligibility = selection["eligibility"]
        eligible = [
            candidate
            for candidate in candidates
            if candidate["validation"]["fn"]
            <= eligibility["validation_false_negatives_maximum"]
            and candidate["validation"]["false_positive_rate"]
            <= eligibility["validation_false_positive_rate_maximum"]
        ]
    else:
        eligible = [
            candidate
            for candidate in candidates
            if candidate["validation"]["false_positive_rate"] <= 0.10
        ]
    if not eligible:
        raise SystemExit("no registered threshold satisfies validation eligibility")
    budget_false_positive = (
        selection.get("mode") == "validation_budgeted_false_positive"
    )

    def selection_key(candidate):
        if budget_false_positive:
            return (
                candidate["validation"]["false_positive_rate"],
                candidate["validation"]["fn"],
                candidate["clearance_threshold"],
            )
        return (
            candidate["validation"]["fn"],
            candidate["validation"]["false_positive_rate"],
            candidate["clearance_threshold"],
        )

    selected = min(eligible, key=selection_key)

    test_rows, test_cases = scenarios.generate(
        protocol["test"]["rows"], protocol["test"]["seed"]
    )
    test = evaluate(test_rows, weights, selected["clearance_threshold"])
    gates_spec = protocol["promotion_gates"]
    gates = {
        "test_false_negatives_not_above_precursor": test["fn"]
        <= gates_spec["test_false_negatives_not_above_precursor"],
        "test_false_positive_rate_within_limit": test["false_positive_rate"]
        <= gates_spec["test_false_positive_rate_maximum"],
        "test_balanced_accuracy_within_limit": test["balanced_accuracy"]
        >= gates_spec["test_balanced_accuracy_minimum"],
        "all_predictions_finite": test["all_predictions_finite"]
        is gates_spec["all_predictions_finite"],
        "normalized_one_step_error_within_limit": test["normalized_one_step_error"]
        <= gates_spec["normalized_one_step_error_maximum"],
    }
    result = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": hashlib.sha256(args.protocol.read_bytes()).hexdigest(),
        "artifact_sha256": digest,
        "test_metrics_used_for_selection": False,
        "validation_case_counts": validation_cases,
        "test_case_counts": test_cases,
        "candidates": candidates,
        "selected_clearance_threshold": selected["clearance_threshold"],
        "selected_validation": selected["validation"],
        "test": test,
        "promotion": {"gates": gates, "passed": all(gates.values())},
        "claim_boundary": protocol["claim_boundary"],
    }
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "selected_clearance_threshold": selected["clearance_threshold"],
                "test_fn": test["fn"],
                "test_fp": test["fp"],
                "passed": result["promotion"]["passed"],
            }
        )
    )
    return 0 if result["promotion"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
