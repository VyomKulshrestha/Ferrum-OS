#!/usr/bin/env python3
"""Record execution-path scope for the authority tests cited by the report."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/research/cross_domain_authority_test_inventory_v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run(command: list[str]) -> dict:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    summary = re.findall(r"test result: (?:ok|FAILED)\.[^\r\n]*", completed.stdout)
    return {
        "command": " ".join(command),
        "exit_code": completed.returncode,
        "passed": completed.returncode == 0,
        "summaries": summary,
        "output_sha256": hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite {args.output}")
    failure_path = ROOT / "docs/research/world_model_failure_modes.json"
    natural_path = ROOT / "docs/research/world_model_natural_use_verification_v1.json"
    physical_path = ROOT / "docs/research/physical_jepa_safety_gymnasium_runtime_verification_v14.json"
    failure = load_json(failure_path)
    natural = load_json(natural_path)
    physical = load_json(physical_path)
    neural_tests = run(
        [
            "cargo",
            "test",
            "--manifest-path",
            "userland/neural-protocol/Cargo.toml",
            "--target",
            "x86_64-pc-windows-msvc",
        ]
    )
    daemon_tests = run(
        [
            "cargo",
            "test",
            "--manifest-path",
            "userland/physical-runtime/Cargo.toml",
            "--target",
            "x86_64-pc-windows-msvc",
        ]
    )
    components = [
        {
            "component": "FerrumOS learned-plus-deterministic gate",
            "test_class": "in-guest integration",
            "committed_evidence": failure_path.relative_to(ROOT).as_posix(),
            "committed_pass": failure.get("result") == "pass",
            "execution_available": True,
            "execution_scope": "disposable QEMU guest command path; valid false-safe, missing, non-finite, and forbidden-coverage artifacts",
        },
        {
            "component": "FerrumOS assistant mediation",
            "test_class": "in-guest system observation",
            "committed_evidence": natural_path.relative_to(ROOT).as_posix(),
            "committed_pass": bool(natural.get("verification_passed")),
            "execution_available": True,
            "execution_scope": "authorized guest reads executed; writes awaited confirmation; deletes were blocked",
        },
        {
            "component": "signed neural permit protocol",
            "test_class": "host unit test",
            "committed_evidence": args.output.relative_to(ROOT).as_posix(),
            "committed_pass": neural_tests["passed"],
            "execution_available": True,
            "execution_scope": "protocol library only; does not exercise the FerrumOS syscall path",
        },
        {
            "component": "physical runtime permit and actuator-disabled driver",
            "test_class": "host unit test",
            "committed_evidence": args.output.relative_to(ROOT).as_posix(),
            "committed_pass": daemon_tests["passed"],
            "execution_available": False,
            "execution_scope": "simulated/offline physical adapter; physical actuator delivery remains structurally disabled",
        },
        {
            "component": "Safety-Gymnasium risk adapter runtime",
            "test_class": "host integration verification",
            "committed_evidence": physical_path.relative_to(ROOT).as_posix(),
            "committed_pass": bool(physical.get("verification_passed")),
            "execution_available": False,
            "execution_scope": "malformed/non-finite adapter behavior and simulator-only commands; no physical delivery",
        },
    ]
    record = {
        "schema": "cross-domain-authority-test-inventory-v1",
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "evidence_inputs": {
            path.relative_to(ROOT).as_posix(): sha256(path)
            for path in (failure_path, natural_path, physical_path)
        },
        "fresh_test_runs": {
            "neural_protocol": neural_tests,
            "physical_daemon": daemon_tests,
        },
        "components": components,
        "all_checks_pass": all(item["committed_pass"] for item in components),
        "claim_boundary": "The inventory distinguishes host unit, host integration, and QEMU in-guest coverage. Physical permit tests do not establish FerrumOS syscall-path enforcement, and no physical actuator was available.",
        "promotion_eligible": False,
    }
    args.output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0 if record["all_checks_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
