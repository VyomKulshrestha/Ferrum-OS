#!/usr/bin/env python3
"""Verify a validation-only v5 decoder selection without opening final evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_physical_jepa_robustness as robustness  # noqa: E402


PROTOCOL = ROOT / "docs" / "research" / "physical_jepa_v5_protocol.json"
REPORT = ROOT / "docs" / "research" / "physical_jepa_v5_selection.json"
BASELINE = ROOT / "docs" / "research" / "artifacts" / "physical-jepa-v5" / "baseline_v3.bin"
DEPLOYED = ROOT / "userland" / "heliox-daemon" / "physical_world_model.bin"
SELECTOR = ROOT / "scripts" / "select_physical_jepa_v5.py"
VERIFIER = Path(__file__).resolve()

EXPECTED_SELECTION_GATES = [
    "all predictions finite",
    "no base-validation H1, H3 or H5 regression greater than two percent",
    "incident-v2 validation geometric H1/H3/H5 error improves by at least five percent with no individual-horizon regression",
    "stress-validation geometric H1/H3/H5 error does not regress with no individual-horizon regression",
    "incident-v2 and stress validation false negatives do not increase",
    "prediction-delta variance ratio is at least 0.10",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def resolve_report_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def repository_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(resolved).replace("\\", "/")


def geometric(values) -> float:
    return math.exp(sum(math.log(max(value, 1e-12)) for value in values) / len(values))


def candidate_protocol_checks(candidate: dict, baseline: dict) -> tuple[dict, dict]:
    ratios = {}
    for name in ("base", "incident", "stress"):
        ratios[name] = {
            horizon: candidate[name]["rollout"][horizon]
            / baseline[name]["rollout"][horizon]
            for horizon in ("h1", "h3", "h5")
        }
    checks = {
        "original_validation_no_regression_over_2_percent": all(
            value <= 1.02 for value in ratios["base"].values()
        ),
        "incident_validation_geometric_improvement_at_least_5_percent": geometric(
            ratios["incident"].values()
        )
        <= 0.95,
        "incident_validation_no_horizon_regression": all(
            value <= 1.0 for value in ratios["incident"].values()
        ),
        "stress_validation_geometric_no_regression": geometric(
            ratios["stress"].values()
        )
        <= 1.0,
        "stress_validation_no_horizon_regression": all(
            value <= 1.0 for value in ratios["stress"].values()
        ),
        "all_predictions_finite": all(
            candidate[name]["diagnostics"]["all_predictions_finite"]
            for name in ("base", "incident", "stress")
        ),
        "incident_validation_false_negatives_not_increased": candidate["incident"][
            "diagnostics"
        ]["rules_plus_jepa"]["fn"]
        <= baseline["incident"]["diagnostics"]["rules_plus_jepa"]["fn"],
        "stress_validation_false_negatives_not_increased": candidate["stress"][
            "diagnostics"
        ]["rules_plus_jepa"]["fn"]
        <= baseline["stress"]["diagnostics"]["rules_plus_jepa"]["fn"],
        "prediction_variance_ratio": candidate["anti_collapse"][
            "prediction_variance_ratio"
        ]
        >= 0.10,
    }
    return checks, ratios


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--result", type=Path)
    args = parser.parse_args()

    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    report = json.loads(args.report.read_text(encoding="utf-8"))
    require(report["protocol_id"] == protocol["protocol_id"], "protocol ID drift")
    require(report["protocol_sha256"] == sha256(PROTOCOL), "protocol hash drift")
    require(report["baseline_artifact_sha256"] == sha256(BASELINE), "baseline drift")
    require(
        protocol["selection_gates"] == EXPECTED_SELECTION_GATES,
        "frozen selection gates drifted",
    )
    require(not report["final_test_opened"], "selection opened final test")
    catalog_access = report.get("final_catalog_access")
    if catalog_access is not None:
        require(
            catalog_access["path"]
            == f"docs/research/{protocol['final_test']['catalog']}",
            "final catalog guard path drifted",
        )
        require(
            catalog_access["guard"] == "python_audit_hook_fail_closed",
            "final catalog guard was not enforced",
        )
        require(
            not catalog_access["access_attempted"] and not catalog_access["opened"],
            "selection attempted to access the final catalog",
        )

    grid = protocol["candidate_grid"]
    registered_grid = [
        (ridge, blend)
        for ridge in grid["decoder_ridge_lambda"]
        for blend in grid["decoder_blend"]
    ]
    observed_grid = [
        (candidate["decoder_ridge_lambda"], candidate["decoder_blend"])
        for candidate in report["candidates"]
    ]
    require(observed_grid == registered_grid, "candidate grid drift")

    recomputed_checks = []
    for index, candidate in enumerate(report["candidates"]):
        expected_checks, ratios = candidate_protocol_checks(
            candidate, report["baseline_validation"]
        )
        recorded_checks = candidate["selection"]["checks"]
        for name, expected in expected_checks.items():
            require(recorded_checks.get(name) == expected, f"candidate {index} gate drift: {name}")
        require(
            candidate["selection"]["accepted"] == all(expected_checks.values()),
            f"candidate {index} acceptance drift",
        )
        for recorded_name, domain in (
            ("original_ratios", "base"),
            ("incident_ratios", "incident"),
            ("stress_ratios", "stress"),
        ):
            for horizon, expected in ratios[domain].items():
                require(
                    np.isclose(candidate["selection"][recorded_name][horizon], expected),
                    f"candidate {index} ratio drift: {domain}.{horizon}",
                )
        expected_score = geometric(
            [
                *ratios["incident"].values(),
                *ratios["incident"].values(),
                *ratios["base"].values(),
                *ratios["stress"].values(),
            ]
        )
        require(
            np.isclose(candidate["selection"]["selection_score"], expected_score),
            f"candidate {index} selection score drift",
        )
        recomputed_checks.append(expected_checks)

    accepted = [
        index
        for index, checks in enumerate(recomputed_checks)
        if all(checks.values())
    ]
    require(accepted == report["accepted_candidate_indices"], "accepted set drift")
    selected_index = report["selected_candidate_index"]
    require(report["selection_passed"] == bool(accepted), "selection status drift")
    require(selected_index in accepted, "selected arm was not accepted")
    expected = min(
        accepted,
        key=lambda index: report["candidates"][index]["selection"]["selection_score"],
    )
    require(selected_index == expected, "selection rule drift")
    require(all(recomputed_checks[selected_index].values()), "selected gate failed")
    artifact = resolve_report_path(report["selected_artifact"])
    require(report["selected_artifact_sha256"] == sha256(artifact), "artifact drift")
    reference = json.loads(REPORT.read_text(encoding="utf-8"))
    require(
        report["selected_artifact_sha256"] == reference["selected_artifact_sha256"],
        "reproduced candidate differs from the frozen selection",
    )
    require(
        report["selected_candidate_index"] == reference["selected_candidate_index"]
        and report["accepted_candidate_indices"]
        == reference["accepted_candidate_indices"],
        "reproduced selection decision differs from the frozen selection",
    )
    baseline = robustness.load_artifact(BASELINE)
    candidate = robustness.load_artifact(artifact)
    for name in (
        "encoder_w",
        "encoder_b",
        "predictor_w1",
        "predictor_b1",
        "predictor_w2",
        "predictor_b2",
    ):
        require(np.array_equal(baseline[name], candidate[name]), f"{name} was not frozen")
    require(
        not np.array_equal(baseline["state_w"], candidate["state_w"])
        and not np.array_equal(baseline["state_b"], candidate["state_b"]),
        "decoder did not change",
    )

    deployment = report.get("deployment")
    if deployment is not None:
        deployed_sha = sha256(DEPLOYED)
        require(not deployment["attempted"], "selection attempted deployment")
        require(deployment["unchanged"], "selection reported deployment mutation")
        require(
            deployment["sha256_before"] == deployment["sha256_after"] == deployed_sha,
            "deployed artifact checksum changed",
        )
        require(
            not deployment["final_promotion_gates_evaluated"]
            and deployment["promotion_eligibility"] == "not_evaluated_validation_only",
            "validation-only run claimed promotion eligibility",
        )

    if args.result is not None:
        result = {
            "schema_version": 1,
            "workflow": "physical_jepa_v5_validation_only_selection",
            "verified_at_utc": datetime.now(timezone.utc).isoformat(),
            "protocol_id": protocol["protocol_id"],
            "protocol_sha256": sha256(PROTOCOL),
            "selector_sha256": sha256(SELECTOR),
            "verifier_sha256": sha256(VERIFIER),
            "selection_report": repository_path(args.report),
            "selection_report_sha256": sha256(args.report),
            "reference_selection_report": repository_path(REPORT),
            "reference_selection_report_sha256": sha256(REPORT),
            "reproduces_frozen_selection": True,
            "candidate_artifact_sha256": report["selected_artifact_sha256"],
            "candidate_count": len(report["candidates"]),
            "accepted_candidate_count": len(accepted),
            "selected_candidate_index": selected_index,
            "frozen_selection_gates": recomputed_checks[selected_index],
            "all_frozen_selection_gates_passed": True,
            "final_catalog_access": catalog_access,
            "final_promotion_gates": {
                "evaluated": False,
                "passed": None,
                "promotion_eligibility": "not_evaluated_validation_only",
            },
            "deployment": deployment,
            "runtime": {
                "python": platform.python_version(),
                "numpy": np.__version__,
            },
            "claim_boundary": [
                "This reproduces deterministic simulator selection evidence, not physical or independently replicated evidence.",
                "The final catalog was preexisting in this post-final checkout but was blocked from access by the selection process.",
                "No final-promotion gate was evaluated and no deployment action was authorized or attempted.",
            ],
        }
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(
        f"PASS physical v5 selection: {len(accepted)}/{len(report['candidates'])} arms accepted; decoder-only candidate "
        f"{report['selected_artifact_sha256'][:12]} remains frozen"
    )


if __name__ == "__main__":
    main()
