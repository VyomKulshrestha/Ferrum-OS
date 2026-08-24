#!/usr/bin/env python3
"""Verify paper evidence, simulator provenance, and deployment immutability."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs" / "research" / "physical_jepa_paper_protocol_v1.json"
RESULTS = ROOT / "docs" / "research" / "physical_jepa_paper_results_v1.json"
TABLE = ROOT / "docs" / "research" / "physical_jepa_paper_ablation_v1.csv"
BLINDED_PROTOCOL = ROOT / "docs" / "research" / "physical_jepa_blinded_benchmark_v2_protocol.json"
BLINDED_V1 = ROOT / "docs" / "research" / "physical_jepa_blinded_benchmark_v1_result.json"
BLINDED_V2 = ROOT / "docs" / "research" / "physical_jepa_blinded_benchmark_v2_result.json"
BLINDED_V2_VERIFICATION = ROOT / "docs" / "research" / "physical_jepa_blinded_benchmark_v2_verification.json"
SOURCE = ROOT / "docs" / "research" / "paper" / "learned_caution_deterministic_authority.md"
PDF = ROOT / "docs" / "research" / "paper" / "learned_caution_deterministic_authority_v1.0.pdf"
DEPLOYED = ROOT / "userland" / "heliox-daemon" / "physical_world_model.bin"
DEFAULT_OUTPUT = ROOT / "docs" / "research" / "physical_jepa_paper_verification_v1.json"


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


def formatted_interval(successes: int, trials: int) -> str:
    lower, upper = wilson_interval(successes, trials)
    return f"[{100.0 * lower:.2f}%, {100.0 * upper:.2f}%]"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    blinded_protocol = json.loads(BLINDED_PROTOCOL.read_text(encoding="utf-8"))
    blinded_v1 = json.loads(BLINDED_V1.read_text(encoding="utf-8"))
    integration = json.loads(BLINDED_V2.read_text(encoding="utf-8"))
    blinded_verification = json.loads(
        BLINDED_V2_VERIFICATION.read_text(encoding="utf-8")
    )
    manuscript = SOURCE.read_text(encoding="utf-8")
    pdf = PdfReader(str(PDF))
    expected_methods = {
        "rules_only",
        "ordinary_supervised_mlp",
        "v3",
        "failed_v4",
        "v5",
        "rules_plus_v5",
    }
    with TABLE.open(newline="", encoding="utf-8") as handle:
        table_rows = list(csv.DictReader(handle))
    reference_fpr = results["matched_fpr_reference"]["false_positive_rate"]
    checks = {
        "protocol_registered_as_posthoc_before_analysis": protocol[
            "analysis_status_at_registration"
        ]
        == "not_run",
        "result_binds_exact_protocol": results["protocol_sha256"] == sha256(PROTOCOL),
        "blinded_v2_binds_exact_protocol": integration["protocol_sha256"]
        == sha256(BLINDED_PROTOCOL),
        "all_artifact_digests_match": all(
            sha256(ROOT / spec["path"]) == spec["sha256"]
            for spec in protocol["artifacts"].values()
        ),
        "six_registered_methods_present": set(results["methods"])
        == expected_methods,
        "csv_matches_registered_methods": {row["method"] for row in table_rows}
        == expected_methods,
        "validation_fpr_is_matched": all(
            math.isclose(
                item["calibration_operating_point"]["false_positive_rate"],
                reference_fpr,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            for item in results["methods"].values()
        ),
        "calibration_metrics_are_finite_probabilistic_scores": all(
            all(
                math.isfinite(item["test_calibration"][key])
                and 0.0 <= item["test_calibration"][key] <= 1.0
                for key in ("ece", "brier_score")
            )
            and math.isfinite(item["test_calibration"]["negative_log_likelihood"])
            for item in results["methods"].values()
        ),
        "v5_is_best_learned_only_final_fnr": results["methods"]["v5"][
            "test_operating_point"
        ]["false_negative_rate"]
        == min(
            results["methods"][name]["test_operating_point"]["false_negative_rate"]
            for name in ("ordinary_supervised_mlp", "v3", "failed_v4", "v5")
        ),
        "v5_is_best_learned_only_ece": results["methods"]["v5"][
            "test_calibration"
        ]["ece"]
        == min(
            results["methods"][name]["test_calibration"]["ece"]
            for name in ("ordinary_supervised_mlp", "v3", "failed_v4", "v5")
        ),
        "rules_plus_v5_does_not_exceed_rules_final_fpr": results["methods"][
            "rules_plus_v5"
        ]["test_operating_point"]["false_positive_rate"]
        <= results["methods"]["rules_only"]["test_operating_point"][
            "false_positive_rate"
        ],
        "rules_plus_v5_reduces_rules_final_fn": results["methods"][
            "rules_plus_v5"
        ]["test_operating_point"]["fn"]
        < results["methods"]["rules_only"]["test_operating_point"]["fn"],
        "pybullet_is_direct_simulation_without_actuator_authority": integration[
            "backend"
        ]["connection_mode"]
        == "DIRECT"
        and integration["backend"]["evidence_class"] == "simulated"
        and not integration["backend"]["actuator_enabled"],
        "pybullet_episode_count_is_registered": integration["summary"]["episodes"]
        == sum(blinded_protocol["case_distribution"]["families"].values()),
        "all_bridge_evidence_is_simulated": integration["summary"][
            "all_observations_simulated"
        ],
        "all_simulator_acks_are_accepted": integration["summary"][
            "all_acknowledgements_accepted"
        ],
        "failed_v1_is_retained": not blinded_v1["all_sealed_gates_pass"]
        and not blinded_v1["sealed_gates"]["task_completion_rate"],
        "blinded_v2_passes_every_frozen_gate": integration["all_sealed_gates_pass"]
        and all(integration["sealed_gates"].values())
        and blinded_verification["all_checks_pass"],
        "blinded_v2_has_high_completion_and_low_intervention": integration["summary"][
            "task_completion_rate"
        ]
        >= 0.8
        and integration["summary"]["intervention_rate"] <= 0.2,
        "blinded_v2_preserves_collision_avoidance": integration["summary"][
            "shielded_collisions"
        ]
        == 0
        and integration["summary"]["unshielded_collisions"] > 0,
        "deployment_digest_unchanged_by_integration": integration[
            "deployment_integrity"
        ]["unchanged"],
        "deployed_digest_matches_registered_v5": sha256(DEPLOYED)
        == protocol["artifacts"]["v5"]["sha256"],
        "manuscript_contains_claim_boundary": "not a robotics-deployment or safety-guarantee claim"
        in manuscript,
        "contribution_wording_is_unambiguous": "An integration executed through the third-party PyBullet physics engine, with every observation explicitly labelled simulated and physical actuator authority disabled."
        in manuscript
        and "independently executed third-party" not in manuscript,
        "pybullet_wilson_intervals_are_reported": all(
            formatted_interval(successes, 512) in manuscript
            for successes in (429, 83, 0)
        ),
        "zero_event_claim_is_statistically_bounded": "No shielded collisions were observed in 512 trials; this does not establish a zero underlying collision probability."
        in manuscript,
        "submission_identity_is_present": all(
            value in manuscript
            for value in (
                "Vyom Kulshrestha",
                "Independent Researcher, India",
                "vyomkulshrestha2004@gmail.com",
            )
        )
        and pdf.metadata.author == "Vyom Kulshrestha",
        "paper_is_frozen_submission_candidate": "Submission candidate v1.0 - 25 August 2026"
        in manuscript,
        "paper_pdf_is_submission_length": 8 <= len(pdf.pages) <= 9,
    }
    evidence = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "checks": checks,
        "all_checks_pass": all(checks.values()),
        "artifacts": {
            "protocol_sha256": sha256(PROTOCOL),
            "results_sha256": sha256(RESULTS),
            "table_sha256": sha256(TABLE),
            "blinded_protocol_sha256": sha256(BLINDED_PROTOCOL),
            "blinded_v1_sha256": sha256(BLINDED_V1),
            "blinded_v2_sha256": sha256(BLINDED_V2),
            "blinded_v2_verification_sha256": sha256(BLINDED_V2_VERIFICATION),
            "manuscript_sha256": sha256(SOURCE),
            "pdf_sha256": sha256(PDF),
            "deployed_artifact_sha256": sha256(DEPLOYED),
        },
        "claim_boundary": "Verification covers deterministic reproduction, document integrity, and simulated bridge evidence only; it is not HIL, physical deployment, certification, or independent assessment.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    return 0 if evidence["all_checks_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
