#!/usr/bin/env python3
"""Open the frozen pre-HIL model challenge without selecting a checkpoint."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_physical_jepa_robustness as robustness  # noqa: E402
import physical_qualification_scenarios as scenarios  # noqa: E402
import train_physical_world_model as simulator  # noqa: E402

PROTOCOL = (
    ROOT / "docs" / "research" / "physical_deployment_qualification_protocol_v1.json"
)
ARTIFACT = ROOT / "userland" / "heliox-daemon" / "physical_world_model.bin"
OUTPUT = (
    ROOT / "docs" / "research" / "physical_deployment_qualification_evaluation_v1.json"
)


def main() -> int:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    challenge = protocol["model_boundary_challenge"]
    digest = hashlib.sha256(ARTIFACT.read_bytes()).hexdigest()
    if digest != challenge["checkpoint_sha256"]:
        raise SystemExit("checkpoint digest differs from the registered challenge")
    if challenge["selection_enabled"]:
        raise SystemExit("qualification challenge must not select a checkpoint")

    rows, case_counts = scenarios.generate(challenge["rows"], challenge["seed"])
    weights = robustness.load_artifact(ARTIFACT)
    combined = robustness.diagnostics(rows, weights)
    rules = simulator.confusion(
        rows, lambda row: simulator.rules_block(row[2], row[3], row[4])
    )
    rules_fn = rules["fn"]
    combined_fn = combined["rules_plus_jepa"]["fn"]
    reduction = (rules_fn - combined_fn) / max(1, rules_fn)
    frozen = challenge["frozen_gates"]
    gates = {
        "all_predictions_finite": combined["all_predictions_finite"]
        is frozen["all_predictions_finite"],
        "normalized_one_step_error_within_limit": combined["normalized_one_step_error"]
        <= frozen["maximum_normalized_one_step_error"],
        "false_negative_rate_within_limit": combined["rules_plus_jepa"][
            "false_negative_rate"
        ]
        <= frozen["maximum_false_negative_rate"],
        "rules_false_negatives_reduced_enough": reduction
        >= frozen["minimum_rules_false_negative_reduction"],
        "false_positive_rate_within_limit": combined["rules_plus_jepa"][
            "false_positive_rate"
        ]
        <= frozen["maximum_false_positive_rate"],
    }
    result = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "challenge_protocol": challenge["protocol"],
        "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        "artifact_sha256": digest,
        "selection_enabled": False,
        "rows": len(rows),
        "seed": challenge["seed"],
        "case_counts": case_counts,
        "rules_only": rules,
        "rules_plus_jepa": combined["rules_plus_jepa"],
        "normalized_one_step_error": combined["normalized_one_step_error"],
        "p95_normalized_one_step_error": combined["p95_normalized_one_step_error"],
        "rules_false_negative_reduction": reduction,
        "gates": gates,
        "passed": all(gates.values()),
        "training_decision": "retain_checkpoint_no_retraining_justified"
        if all(gates.values())
        else "register_new_training_protocol_before_retraining",
        "claim_boundary": [
            "The challenge is a deterministic systematic simulator sweep, not HIL or robot evidence.",
            "Passing can justify retaining the simulator checkpoint; it cannot qualify physical deployment.",
            "Conservative false positives include intentional safety margin near transition thresholds.",
            "The learned model remains unable to issue permits or activate a live driver.",
        ],
    }
    OUTPUT.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps({"output": str(OUTPUT), "passed": result["passed"], "gates": gates})
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
