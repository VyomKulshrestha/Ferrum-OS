#!/usr/bin/env python3
"""Run the frozen Safety-Gymnasium v12 benchmark as a non-author replication."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = (
    ROOT / "docs" / "research" / "physical_jepa_external_execution_manifest_v1.json"
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


def validate_registered_package(manifest: dict) -> None:
    entries = list(manifest["frozen_inputs"].values()) + list(
        manifest["registered_reference_outputs"].values()
    )
    for entry in entries:
        path = ROOT / entry["path"]
        if not path.is_file():
            raise FileNotFoundError(f"registered file is missing: {entry['path']}")
        observed = registered_sha256(path, entry)
        if observed != entry["sha256"]:
            raise ValueError(
                f"registered digest mismatch for {entry['path']}: {observed}"
            )

    reference = load_json(
        ROOT / manifest["registered_reference_outputs"]["result"]["path"]
    )
    expected = manifest["reference_result"]
    planner = reference["arms"]["planner_unshielded"]["metrics"]
    headline = reference["headline"]
    observed = {
        "planner_completion_rate": planner["task_completion_rate"],
        "planner_hazard_cost_events": planner["actual_hazard_cost_events"],
        "naive_hazard_cost_events": headline["unshielded_actual_hazard_cost_events"],
        "planner_hazard_cost_reduction_fraction": (
            headline["unshielded_actual_hazard_cost_events"]
            - planner["actual_hazard_cost_events"]
        )
        / headline["unshielded_actual_hazard_cost_events"],
        "active_union_completion_rate": headline["task_completion_rate"],
        "active_union_intervention_rate": headline["intervention_rate"],
        "active_union_dangerous_proposal_recall": headline[
            "dangerous_proposal_recall"
        ],
        "active_union_safe_proposal_false_positive_rate": headline[
            "safe_proposal_false_positive_rate"
        ],
        "active_union_hazard_cost_events": headline[
            "union_actual_hazard_cost_events"
        ],
        "active_union_hazard_cost_change_fraction": -headline[
            "actual_hazard_cost_reduction_fraction"
        ],
        "active_union_all_frozen_gates_pass": reference["all_frozen_gates_pass"],
        "failed_gates": sorted(
            name for name, passed in reference["frozen_gates"].items() if not passed
        ),
    }
    expected = dict(expected)
    expected["failed_gates"] = sorted(expected["failed_gates"])
    if observed != expected:
        raise ValueError("registered reference metrics do not match the handoff manifest")


def normalize_result(result: dict) -> dict:
    normalized = json.loads(json.dumps(result, sort_keys=True))
    normalized["case_catalog"]["path"] = "<external-output>/raw_cases.jsonl"
    normalized["protocol"]["path"] = "<frozen-input>/protocol.json"
    normalized["selection"]["path"] = "<frozen-input>/selection.json"
    return normalized


def venv_python(manifest: dict) -> Path:
    environment = ROOT / "target" / "safety-gymnasium-venv"
    candidates = [environment / "Scripts" / "python.exe", environment / "bin" / "python"]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "locked environment is missing; create target/safety-gymnasium-venv "
        "using the handoff instructions"
    )


def tracked_checkout_is_clean() -> bool:
    completed = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return not completed.stdout.strip()


def git_revision() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executor-name", required=True)
    parser.add_argument("--executor-affiliation", required=True)
    parser.add_argument("--executor-identifier", required=True)
    parser.add_argument("--attest-not-a-paper-author", action="store_true")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    name = args.executor_name.strip()
    affiliation = args.executor_affiliation.strip()
    identifier = args.executor_identifier.strip()
    if not name or not affiliation or not identifier:
        raise ValueError("executor identity fields must be non-empty and truthful")
    if not args.attest_not_a_paper_author:
        raise ValueError("the non-author executor attestation is required")
    if name.casefold() in PAPER_AUTHOR_NAMES:
        raise ValueError("a paper author cannot generate independent-execution evidence")
    if any(value in identifier.casefold() for value in PAPER_AUTHOR_IDENTIFIERS):
        raise ValueError("the executor identifier belongs to a paper author")
    if not tracked_checkout_is_clean():
        raise ValueError("tracked checkout is dirty; use a fresh clean clone")

    manifest = load_json(MANIFEST_PATH)
    validate_registered_package(manifest)

    output_dir = args.output_dir.resolve()
    try:
        output_dir.relative_to(ROOT)
    except ValueError:
        raise ValueError("output directory must be inside the clean repository clone")
    output_dir.mkdir(parents=True, exist_ok=False)

    raw_result = output_dir / "raw_result.json"
    raw_cases = output_dir / "raw_cases.jsonl"
    stdout_path = output_dir / "runner.stdout.txt"
    stderr_path = output_dir / "runner.stderr.txt"
    attestation_path = output_dir / "execution_attestation.json"
    protocol_entry = manifest["frozen_inputs"]["protocol"]
    selection_entry = manifest["frozen_inputs"]["selection"]
    protocol_source = ROOT / protocol_entry["path"]
    selection_source = ROOT / selection_entry["path"]
    protocol = output_dir / "frozen_protocol.json"
    selection = output_dir / "frozen_selection.json"
    protocol.write_bytes(registered_bytes(protocol_source, protocol_entry))
    selection.write_bytes(registered_bytes(selection_source, selection_entry))
    if sha256(protocol) != protocol_entry["sha256"]:
        raise ValueError("materialized protocol does not match the registered digest")
    if sha256(selection) != selection_entry["sha256"]:
        raise ValueError("materialized selection does not match the registered digest")
    runner = ROOT / manifest["frozen_inputs"]["runner"]["path"]
    python = venv_python(manifest)
    command = [
        str(python),
        str(runner),
        "--mode",
        "final",
        "--protocol",
        str(protocol),
        "--selection",
        str(selection),
        "--output",
        str(raw_result),
        "--cases-output",
        str(raw_cases),
    ]
    started = datetime.now(timezone.utc)
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    finished = datetime.now(timezone.utc)
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")

    if not raw_result.is_file() or not raw_cases.is_file():
        raise RuntimeError(
            f"frozen runner did not produce both raw outputs (exit {completed.returncode})"
        )

    reference_result_path = (
        ROOT / manifest["registered_reference_outputs"]["result"]["path"]
    )
    reference_cases_path = (
        ROOT / manifest["registered_reference_outputs"]["cases"]["path"]
    )
    observed_result = load_json(raw_result)
    reference_result = load_json(reference_result_path)
    cases_exact = sha256(raw_cases) == sha256(reference_cases_path)
    normalized_result_exact = normalize_result(observed_result) == normalize_result(
        reference_result
    )
    actuator_authority_zero = (
        observed_result["physical_actuator_attempts"] == 0
        and observed_result["physical_actuator_deliveries"] == 0
    )
    active_union_negative_retained = (
        observed_result["all_frozen_gates_pass"] is False
        and observed_result["frozen_gates"]["dangerous_proposal_recall"] is False
        and observed_result["frozen_gates"][
            "actual_hazard_cost_reduction_fraction"
        ]
        is False
    )
    exact_replication = (
        cases_exact
        and normalized_result_exact
        and actuator_authority_zero
        and active_union_negative_retained
    )

    attestation = {
        "schema": "physical-jepa-external-execution-attestation-v1",
        "executor": {
            "name": name,
            "affiliation": affiliation,
            "identifier": identifier,
            "attested_not_a_paper_author": True,
        },
        "execution": {
            "started_utc": started.isoformat(),
            "finished_utc": finished.isoformat(),
            "git_revision": git_revision(),
            "platform": platform.platform(),
            "python_executable": str(python.relative_to(ROOT)).replace("\\", "/"),
            "runner_exit_code": completed.returncode,
            "runner_nonzero_expected_from_failed_frozen_gates": True,
        },
        "package": {
            "manifest_path": str(MANIFEST_PATH.relative_to(ROOT)).replace("\\", "/"),
            "manifest_sha256": sha256(MANIFEST_PATH),
            "all_registered_inputs_match": True,
        },
        "outputs": {
            "raw_result_sha256": sha256(raw_result),
            "raw_cases_sha256": sha256(raw_cases),
            "runner_stdout_sha256": sha256(stdout_path),
            "runner_stderr_sha256": sha256(stderr_path),
            "cases_byte_identical_to_reference": cases_exact,
            "normalized_result_identical_to_reference": normalized_result_exact,
            "materialized_protocol_sha256": sha256(protocol),
            "materialized_selection_sha256": sha256(selection),
        },
        "safety_boundary": {
            "physical_actuator_attempts": observed_result[
                "physical_actuator_attempts"
            ],
            "physical_actuator_deliveries": observed_result[
                "physical_actuator_deliveries"
            ],
            "active_union_failed_recall_and_realized_cost_gates": active_union_negative_retained,
            "promotion_eligible": False,
        },
        "claim_eligibility": {
            "exact_non_author_execution_replication": exact_replication,
            "independently_designed_benchmark": False,
            "independent_assessment": False,
            "live_hil": False,
            "physical_deployment": False,
        },
        "canonical_public_summary": manifest["canonical_public_summary"],
    }
    attestation_path.write_text(
        json.dumps(attestation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(attestation, indent=2, sort_keys=True))
    if not exact_replication:
        raise SystemExit("external execution completed with a replication discrepancy")


if __name__ == "__main__":
    main()
