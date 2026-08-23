#!/usr/bin/env python3
"""Open the frozen v5 incident test once and evaluate the selected decoder."""

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

import evaluate_physical_jepa_robustness as robustness  # noqa: E402
import physical_incident_scenarios as incidents  # noqa: E402
import physical_stress_scenarios as stress  # noqa: E402
import select_physical_jepa_v5 as v5  # noqa: E402
import train_physical_jepa as jepa  # noqa: E402
import train_physical_world_model as simulator  # noqa: E402


PROTOCOL = ROOT / "docs" / "research" / "physical_jepa_v5_protocol.json"
SELECTION = ROOT / "docs" / "research" / "physical_jepa_v5_selection.json"
BASELINE = ROOT / "userland" / "heliox-daemon" / "physical_world_model.bin"
FINAL_CATALOG = ROOT / "docs" / "research" / "physical_incident_v5_test_sources.json"
DEFAULT_REPORT = ROOT / "docs" / "research" / "physical_jepa_v5_final_test.json"
SELECTION_COMMIT = "58c88a6"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def geometric(values) -> float:
    return math.exp(sum(math.log(max(value, 1e-12)) for value in values) / len(values))


def ratios(candidate: dict, baseline: dict) -> dict:
    values = {
        horizon: candidate["rollout"][horizon] / baseline["rollout"][horizon]
        for horizon in ("h1", "h3", "h5")
    }
    return {**values, "geometric_h1_h3_h5": geometric(values.values())}


def h3_paired_bootstrap(prepared: dict, baseline: dict, candidate: dict) -> dict:
    item = prepared["rollouts"][3]

    def errors(weights: dict) -> np.ndarray:
        predicted = item["state"].copy()
        for offset in range(3):
            predicted = v5.batch_prediction(
                weights,
                predicted,
                item["action"][:, offset],
                item["features"][:, offset],
            )
        return np.mean(
            np.abs(predicted - item["actual"]) / simulator.STATE_RANGES, axis=1
        )

    baseline_errors = errors(baseline)
    candidate_errors = errors(candidate)
    episodes = 2560
    windows_per_episode = len(baseline_errors) // episodes
    if windows_per_episode * episodes != len(baseline_errors):
        raise AssertionError("v5 H3 windows are not episode aligned")
    paired = (
        baseline_errors.reshape(episodes, windows_per_episode).mean(axis=1)
        - candidate_errors.reshape(episodes, windows_per_episode).mean(axis=1)
    )
    rng = np.random.default_rng(20260830)
    draws = []
    for _ in range(20):
        indices = rng.integers(0, episodes, size=(500, episodes))
        draws.extend(paired[indices].mean(axis=1).tolist())
    lower, upper = np.percentile(np.asarray(draws), (2.5, 97.5))
    return {
        "unit": "episode",
        "episodes": episodes,
        "resamples": 10000,
        "seed": 20260830,
        "mean_absolute_normalized_error_reduction": float(paired.mean()),
        "percentile_95_interval": [float(lower), float(upper)],
        "interval_excludes_zero": bool(lower > 0.0),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    if not selection["selection_passed"] or selection["final_test_opened"]:
        raise AssertionError("v5 selection is not final-test eligible")
    artifact = ROOT / selection["selected_artifact"]
    if selection["selected_artifact_sha256"] != sha256(artifact):
        raise AssertionError("v5 selected artifact drifted")
    if protocol["baseline_artifact_sha256"] != sha256(BASELINE):
        raise AssertionError("v5 baseline drifted before final evaluation")
    baseline = robustness.load_artifact(BASELINE)
    candidate = robustness.load_artifact(artifact)

    final_rows, final_metadata = incidents.generate_partition(
        "test", 320, 8, 20260829, FINAL_CATALOG
    )
    final_prepared = v5.prepare_evaluation(final_rows)
    v5.verify_batched_equivalence(final_rows, baseline)
    final_baseline = v5.batched_evaluation(final_prepared, baseline)
    final_candidate = v5.batched_evaluation(final_prepared, candidate)
    final_ratios = ratios(final_candidate, final_baseline)

    base_rows = simulator.generate(12000, 8, 20260824)
    _, _, _, _, base_test = jepa.split_rows(base_rows, 12000, 20260824)
    stress_test, stress_metadata = stress.generate_partition(
        "test", 2000, 8, 20260826
    )
    base_prepared = v5.prepare_evaluation(base_test)
    stress_prepared = v5.prepare_evaluation(stress_test)
    base_regression = {
        "baseline": v5.batched_evaluation(base_prepared, baseline),
        "candidate": v5.batched_evaluation(base_prepared, candidate),
    }
    base_regression["ratios"] = ratios(
        base_regression["candidate"], base_regression["baseline"]
    )
    stress_regression = {
        "baseline": v5.batched_evaluation(stress_prepared, baseline),
        "candidate": v5.batched_evaluation(stress_prepared, candidate),
    }
    stress_regression["ratios"] = ratios(
        stress_regression["candidate"], stress_regression["baseline"]
    )
    ood_rows = robustness.ood_v2_rows(4096, 20260825)
    ood_regression = {
        "baseline": robustness.diagnostics(ood_rows, baseline, fail_closed_invalid=True),
        "candidate": robustness.diagnostics(ood_rows, candidate, fail_closed_invalid=True),
    }

    final_base_gate = final_baseline["diagnostics"]["rules_plus_jepa"]
    final_candidate_gate = final_candidate["diagnostics"]["rules_plus_jepa"]
    stress_base_gate = stress_regression["baseline"]["diagnostics"]["rules_plus_jepa"]
    stress_candidate_gate = stress_regression["candidate"]["diagnostics"]["rules_plus_jepa"]
    ood_base_gate = ood_regression["baseline"]["rules_plus_jepa"]
    ood_candidate_gate = ood_regression["candidate"]["rules_plus_jepa"]
    requirements = {
        "all_predictions_finite": all(
            (
                final_candidate["diagnostics"]["all_predictions_finite"],
                base_regression["candidate"]["diagnostics"]["all_predictions_finite"],
                stress_regression["candidate"]["diagnostics"]["all_predictions_finite"],
                ood_regression["candidate"]["all_predictions_finite"],
            )
        ),
        "v5_geometric_improvement_at_least_5_percent": final_ratios[
            "geometric_h1_h3_h5"
        ]
        <= 0.95,
        "v5_no_horizon_regression": all(
            final_ratios[horizon] <= 1.0 for horizon in ("h1", "h3", "h5")
        ),
        "v5_false_negatives_not_increased": final_candidate_gate["fn"]
        <= final_base_gate["fn"],
        "v5_false_positive_rate_within_2_points": final_candidate_gate[
            "false_positive_rate"
        ]
        <= final_base_gate["false_positive_rate"] + 0.02,
        "base_test_no_regression_over_2_percent": all(
            base_regression["ratios"][horizon] <= 1.02
            for horizon in ("h1", "h3", "h5")
        ),
        "stress_false_negatives_not_increased": stress_candidate_gate["fn"]
        <= stress_base_gate["fn"],
        "stress_false_positive_rate_within_2_points": stress_candidate_gate[
            "false_positive_rate"
        ]
        <= stress_base_gate["false_positive_rate"] + 0.02,
        "ood_false_negatives_not_increased": ood_candidate_gate["fn"]
        <= ood_base_gate["fn"],
        "ood_false_positive_rate_within_2_points": ood_candidate_gate[
            "false_positive_rate"
        ]
        <= ood_base_gate["false_positive_rate"] + 0.02,
    }
    bootstrap = h3_paired_bootstrap(final_prepared, baseline, candidate)
    report = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(PROTOCOL),
        "selection_commit": SELECTION_COMMIT,
        "selection_report_sha256": sha256(SELECTION),
        "baseline_artifact_sha256": sha256(BASELINE),
        "candidate_artifact_sha256": sha256(artifact),
        "final_test_open_count": 1,
        "final_catalog": str(FINAL_CATALOG.relative_to(ROOT)).replace("\\", "/"),
        "final_catalog_resolved_sha256": incidents.catalog_sha256(FINAL_CATALOG),
        "final_evidence": incidents.summarize(final_rows, final_metadata),
        "baseline_final": final_baseline,
        "candidate_final": final_candidate,
        "candidate_to_baseline_rollout_ratios": final_ratios,
        "h3_paired_bootstrap": bootstrap,
        "known_regression_suites": {
            "base_test": base_regression,
            "stress_test": {
                "evidence": stress.summarize(stress_test, stress_metadata),
                **stress_regression,
            },
            "registered_ood_v2": ood_regression,
        },
        "final_requirements": requirements,
        "all_model_evidence_gates_pass": all(requirements.values())
        and bootstrap["interval_excludes_zero"],
        "no_retraining_after_final_test_open": True,
        "claim_boundary": [
            "This is the single evaluation of the committed decoder on eight source families absent from the prior incident catalogs.",
            "Public incident reports select defensive initial-state priors; Ferrum's deterministic simulator supplies every transition and danger label.",
            "The result is software simulation evidence, not replay of the reported facilities, a Ferrum hardware trial, a field deployment, certification or an independent safety assessment.",
            "Passing model gates does not grant permits or adapter authority; runtime integration remains separately gated by no_std authority-boundary tests.",
        ],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        "FINAL physical v5: "
        f"ratio={final_ratios['geometric_h1_h3_h5']:.4f} "
        f"fn={final_base_gate['fn']}->{final_candidate_gate['fn']} "
        f"fp_rate={final_base_gate['false_positive_rate']:.4f}"
        f"->{final_candidate_gate['false_positive_rate']:.4f} "
        f"all_gates={report['all_model_evidence_gates_pass']}"
    )
    return 0 if report["all_model_evidence_gates_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
