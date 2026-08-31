#!/usr/bin/env python3
"""Verify the sealed non-author Safety-Gymnasium execution handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = (
    ROOT / "docs" / "research" / "physical_jepa_external_execution_manifest_v1.json"
)
STUDY = ROOT / "docs" / "research" / "CROSS_DOMAIN_WORLD_MODEL_IMPROVEMENT_STUDY.md"
HANDOFF = ROOT / "docs" / "research" / "PHYSICAL_JEPA_EXTERNAL_EXECUTION_HANDOFF_v1.md"
DEFAULT_OUTPUT = (
    ROOT
    / "docs"
    / "research"
    / "physical_jepa_external_execution_handoff_verification_v1.json"
)
PAPER_AUTHOR_NAMES = {"vyom kulshrestha"}
PAPER_AUTHOR_IDENTIFIERS = {"0009-0009-1434-7148"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def registered_bytes(path: Path, entry: dict) -> bytes:
    data = path.read_bytes()
    policy = entry.get("line_endings")
    if policy is None:
        return data
    text = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    if policy == "lf":
        return text.encode("utf-8")
    if policy == "crlf":
        return text.replace("\n", "\r\n").encode("utf-8")
    raise ValueError(f"unsupported line-ending policy: {policy}")


def registered_sha256(path: Path, entry: dict) -> str:
    return hashlib.sha256(registered_bytes(path, entry)).hexdigest()


def normalize_result(result: dict) -> dict:
    normalized = json.loads(json.dumps(result, sort_keys=True))
    normalized["case_catalog"]["path"] = "<external-output>/raw_cases.jsonl"
    normalized["protocol"]["path"] = "<frozen-input>/protocol.json"
    normalized["selection"]["path"] = "<frozen-input>/selection.json"
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--execution-dir", type=Path)
    args = parser.parse_args()

    manifest = load_json(MANIFEST)
    study = STUDY.read_text(encoding="utf-8")
    handoff = HANDOFF.read_text(encoding="utf-8")
    checks: dict[str, bool] = {}
    for group_name in ("frozen_inputs", "registered_reference_outputs"):
        for name, entry in manifest[group_name].items():
            path = ROOT / entry["path"]
            checks[f"{group_name}.{name}.present"] = path.is_file()
            checks[f"{group_name}.{name}.sha256"] = (
                path.is_file() and registered_sha256(path, entry) == entry["sha256"]
            )

    reference = load_json(
        ROOT / manifest["registered_reference_outputs"]["result"]["path"]
    )
    planner = reference["arms"]["planner_unshielded"]["metrics"]
    headline = reference["headline"]
    checks.update(
        {
            "planner_completion_is_94_53_percent": planner[
                "task_completion_rate"
            ]
            == 0.9453125,
            "planner_hazard_cost_is_124": planner["actual_hazard_cost_events"]
            == 124,
            "naive_hazard_cost_is_375": headline[
                "unshielded_actual_hazard_cost_events"
            ]
            == 375,
            "active_union_recall_gate_failed": reference["frozen_gates"][
                "dangerous_proposal_recall"
            ]
            is False,
            "active_union_realized_cost_gate_failed": reference["frozen_gates"][
                "actual_hazard_cost_reduction_fraction"
            ]
            is False,
            "active_union_all_gates_failed": reference["all_frozen_gates_pass"]
            is False,
            "physical_actuator_attempts_zero": reference[
                "physical_actuator_attempts"
            ]
            == 0,
            "physical_actuator_deliveries_zero": reference[
                "physical_actuator_deliveries"
            ]
            == 0,
            "promotion_remains_false": reference["promotion_eligible"] is False,
            "reference_independent_execution_false": reference[
                "independent_execution"
            ]
            is False,
            "canonical_summary_in_study": manifest["canonical_public_summary"]
            in study,
            "misleading_summary_absent_from_study": manifest[
                "forbidden_public_summary"
            ]
            not in study,
            "handoff_declares_pending": "not evidence of independent execution"
            in handoff,
            "handoff_rejects_live_hil_claim": "is not live HIL evidence" in handoff,
            "paper_source_remains_frozen": sha256(
                ROOT / manifest["frozen_inputs"]["paper_source"]["path"]
            )
            == manifest["frozen_inputs"]["paper_source"]["sha256"],
            "paper_pdf_remains_frozen": sha256(
                ROOT / manifest["frozen_inputs"]["paper_pdf"]["path"]
            )
            == manifest["frozen_inputs"]["paper_pdf"]["sha256"],
        }
    )
    external_execution_completed = False
    if args.execution_dir is not None:
        execution_dir = args.execution_dir.resolve()
        raw_result_path = execution_dir / "raw_result.json"
        raw_cases_path = execution_dir / "raw_cases.jsonl"
        stdout_path = execution_dir / "runner.stdout.txt"
        stderr_path = execution_dir / "runner.stderr.txt"
        attestation_path = execution_dir / "execution_attestation.json"
        execution_files = {
            "raw_result": raw_result_path,
            "raw_cases": raw_cases_path,
            "runner_stdout": stdout_path,
            "runner_stderr": stderr_path,
            "attestation": attestation_path,
        }
        for name, path in execution_files.items():
            checks[f"execution.{name}.present"] = path.is_file()
        if all(path.is_file() for path in execution_files.values()):
            attestation = load_json(attestation_path)
            raw_result = load_json(raw_result_path)
            executor = attestation.get("executor", {})
            name = str(executor.get("name", "")).strip().casefold()
            identifier = str(executor.get("identifier", "")).strip().casefold()
            checks.update(
                {
                    "execution.executor_attested_non_author": executor.get(
                        "attested_not_a_paper_author"
                    )
                    is True,
                    "execution.executor_name_not_registered_author": name
                    not in PAPER_AUTHOR_NAMES,
                    "execution.executor_identifier_not_registered_author": not any(
                        value in identifier for value in PAPER_AUTHOR_IDENTIFIERS
                    ),
                    "execution.raw_result_hash_matches_attestation": sha256(
                        raw_result_path
                    )
                    == attestation["outputs"]["raw_result_sha256"],
                    "execution.raw_cases_hash_matches_attestation": sha256(
                        raw_cases_path
                    )
                    == attestation["outputs"]["raw_cases_sha256"],
                    "execution.stdout_hash_matches_attestation": sha256(stdout_path)
                    == attestation["outputs"]["runner_stdout_sha256"],
                    "execution.stderr_hash_matches_attestation": sha256(stderr_path)
                    == attestation["outputs"]["runner_stderr_sha256"],
                    "execution.cases_byte_identical_to_reference": sha256(
                        raw_cases_path
                    )
                    == manifest["registered_reference_outputs"]["cases"]["sha256"],
                    "execution.normalized_result_identical_to_reference": normalize_result(
                        raw_result
                    )
                    == normalize_result(reference),
                    "execution.attestation_marks_exact_replication": attestation[
                        "claim_eligibility"
                    ]["exact_non_author_execution_replication"]
                    is True,
                    "execution.zero_physical_authority": raw_result[
                        "physical_actuator_attempts"
                    ]
                    == 0
                    and raw_result["physical_actuator_deliveries"] == 0,
                    "execution.active_union_negative_retained": raw_result[
                        "all_frozen_gates_pass"
                    ]
                    is False
                    and raw_result["frozen_gates"]["dangerous_proposal_recall"]
                    is False
                    and raw_result["frozen_gates"][
                        "actual_hazard_cost_reduction_fraction"
                    ]
                    is False,
                }
            )
            external_execution_completed = all(
                value
                for name, value in checks.items()
                if name.startswith("execution.")
            )
    report = {
        "schema": "physical-jepa-external-execution-handoff-verification-v1",
        "all_checks_pass": all(checks.values()),
        "external_execution_completed": external_execution_completed,
        "non_author_execution_evidence_eligible": external_execution_completed,
        "executor_identity_requires_human_cross_check": external_execution_completed,
        "live_hil_completed": False,
        "paper_v1_1_modified": False,
        "promotion_eligible": False,
        "checks": checks,
        "canonical_public_summary": manifest["canonical_public_summary"],
        "claim_boundary": (
            "An exact, attested non-author execution bundle is present; this supports "
            "independently executed replication after human identity cross-check, not "
            "independent design, independent assessment, or live HIL."
            if external_execution_completed
            else "The controller, shield, inputs, gates, and reproduction command are "
            "frozen for execution by a non-author. This local verification does not "
            "constitute independent execution, independent assessment, or live HIL."
        ),
    }
    if not args.check_only:
        output = args.output.resolve()
        output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["all_checks_pass"]:
        raise SystemExit("external-execution handoff verification failed")


if __name__ == "__main__":
    main()
