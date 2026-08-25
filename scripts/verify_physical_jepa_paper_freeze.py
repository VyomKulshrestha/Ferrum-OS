#!/usr/bin/env python3
"""Verify an immutable Physical JEPA paper freeze."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FREEZE = ROOT / "docs" / "research" / "physical_jepa_paper_freeze_v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wilson_interval(successes: int, trials: int, z: float) -> tuple[float, float]:
    proportion = successes / trials
    denominator = 1.0 + z * z / trials
    center = (proportion + z * z / (2.0 * trials)) / denominator
    half_width = z * math.sqrt(
        proportion * (1.0 - proportion) / trials
        + z * z / (4.0 * trials * trials)
    ) / denominator
    return center - half_width, center + half_width


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE)
    args = parser.parse_args()
    freeze = json.loads(args.freeze.read_text(encoding="utf-8"))
    artifacts = freeze["artifacts"]
    checks = {
        f"{name}_digest_matches": sha256(ROOT / record["path"])
        == record["sha256"]
        for name, record in artifacts.items()
    }

    manuscript_path = ROOT / artifacts["manuscript"]["path"]
    manuscript = manuscript_path.read_text(encoding="utf-8")
    contribution = (
        "An integration executed through the third-party PyBullet physics engine, "
        "with every observation explicitly labelled simulated and physical actuator "
        "authority disabled."
    )
    caveat = (
        "No shielded collisions were observed in 512 trials; this does not establish "
        "a zero underlying collision probability."
    )
    checks.update(
        {
            "freeze_identity_matches": freeze["freeze_id"].startswith(
                "learned-caution-deterministic-authority-"
            )
            and freeze["status"]
            in ("frozen_submission_candidate", "frozen_technical_report"),
            "manuscript_identity_matches": freeze.get(
                "status_line", "Submission candidate v1.0 - 25 August 2026"
            )
            in manuscript,
            "contribution_is_unambiguous": contribution in manuscript
            and "independently executed third-party" not in manuscript,
            "zero_event_caveat_is_present": caveat in manuscript,
        }
    )
    for index, required in enumerate(freeze.get("required_manuscript_strings", [])):
        checks[f"required_manuscript_string_{index}_present"] = required in manuscript
    for index, forbidden in enumerate(freeze.get("forbidden_manuscript_strings", [])):
        checks[f"forbidden_manuscript_string_{index}_absent"] = forbidden not in manuscript

    benchmark = json.loads(
        (ROOT / artifacts["blinded_benchmark_result"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    summary = benchmark["summary"]
    recorded = freeze["pybullet_wilson_95_percent"]
    trials = recorded["trials"]
    counts = {
        "completion": summary["task_completions"],
        "intervention": summary["interventions"],
        "shielded_collision": summary["shielded_collisions"],
    }
    for name, successes in counts.items():
        lower, upper = wilson_interval(successes, trials, recorded["z"])
        item = recorded[name]
        checks[f"{name}_wilson_interval_matches"] = (
            item["successes"] == successes
            and math.isclose(item["estimate"], successes / trials, abs_tol=1e-15)
            and math.isclose(item["lower"], lower, abs_tol=1e-15)
            and math.isclose(item["upper"], upper, abs_tol=1e-15)
            and f"[{100.0 * lower:.2f}%, {100.0 * upper:.2f}%]" in manuscript
        )

    selection_verification = json.loads(
        (ROOT / artifacts["v5_selection_verification"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    final_test = json.loads(
        (ROOT / artifacts["v5_final_test"]["path"]).read_text(encoding="utf-8")
    )
    checks.update(
        {
            "selection_was_validation_only_and_final_catalog_unopened": (
                selection_verification["all_frozen_selection_gates_passed"]
                and not selection_verification["final_catalog_access"]["opened"]
                and not selection_verification["final_catalog_access"]["access_attempted"]
                and not selection_verification["deployment"]["attempted"]
            ),
            "frozen_final_model_gates_pass": final_test[
                "all_model_evidence_gates_pass"
            ]
            and final_test["no_retraining_after_final_test_open"],
            "blinded_benchmark_gates_pass": benchmark["all_sealed_gates_pass"]
            and benchmark["deployment_integrity"]["unchanged"],
            "deployed_digest_matches_registered_candidate": (
                artifacts["deployed_artifact"]["sha256"]
                == final_test["candidate_artifact_sha256"]
                == benchmark["deployment_integrity"]["after_sha256"]
            ),
        }
    )

    if "review_result" in artifacts:
        review = json.loads(
            (ROOT / artifacts["review_result"]["path"]).read_text(encoding="utf-8")
        )
        checks.update(
            {
                "review_audit_passes": review["all_checks_pass"],
                "review_audit_binds_registered_protocol": review["protocol_sha256"]
                == artifacts["review_protocol"]["sha256"],
                "review_audit_preserves_deployed_artifact": review["inputs"][
                    "deployed_artifact"
                ]["sha256"]
                == artifacts["deployed_artifact"]["sha256"],
            }
        )

    if "dynamics_calibration_result_v2" in artifacts:
        dynamics = json.loads(
            (ROOT / artifacts["dynamics_calibration_result_v2"]["path"]).read_text(
                encoding="utf-8"
            )
        )
        failed_gate = json.loads(
            (
                ROOT
                / artifacts["dynamics_calibration_failed_gate_result_v1"]["path"]
            ).read_text(encoding="utf-8")
        )
        checks.update(
            {
                "dynamics_calibration_audit_passes": dynamics["all_checks_pass"]
                and all(dynamics["checks"].values()),
                "dynamics_calibration_audit_binds_gate_repair_protocol": dynamics[
                    "protocol_sha256"
                ]
                == artifacts["dynamics_calibration_protocol_v2"]["sha256"],
                "failed_dynamics_gate_is_retained": not failed_gate[
                    "all_checks_pass"
                ]
                and not failed_gate["checks"][
                    "v3_and_v5_dynamics_reproduce_frozen_final_test"
                ],
                "gate_repair_reproduces_all_estimates": dynamics["checks"][
                    "statistical_estimates_reproduce_failed_gate_v1"
                ],
                "dynamics_audit_preserves_deployed_artifact": dynamics["inputs"][
                    "deployed_artifact"
                ]["sha256"]
                == artifacts["deployed_artifact"]["sha256"],
            }
        )

    pdf = PdfReader(str(ROOT / artifacts["pdf"]["path"]))
    first_page = pdf.pages[0].extract_text()
    checks["pdf_identity_and_length_match"] = (
        pdf.metadata.author == freeze["author"]
        and len(pdf.pages) == freeze.get("expected_pages", 8)
        and freeze.get("running_header", "SUBMISSION CANDIDATE v1.0")
        in first_page
    )

    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise SystemExit("paper freeze verification failed: " + ", ".join(failed))
    print(
        f"paper freeze verified: {freeze['freeze_id']} "
        f"({len(checks)} checks, deployed artifact unchanged)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
