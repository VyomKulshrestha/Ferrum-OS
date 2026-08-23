#!/usr/bin/env python3
"""Verify the compact public manifest against the frozen HAI v2 evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "research" / "physical_hai_v2_evidence_manifest.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for entry in manifest["artifacts"].values():
        path = ROOT / entry["path"]
        require(path.is_file(), f"missing evidence artifact: {entry['path']}")
        require(sha256(path) == entry["sha256"], f"digest drift: {entry['path']}")

    report_path = ROOT / manifest["artifacts"]["final_test"]["path"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    evidence = manifest["dataset"]
    metrics = manifest["final_metrics"]
    require(report["evidence"]["files"] == evidence["files"], "file count drift")
    require(
        report["evidence"]["recorded_seconds"] == evidence["recorded_seconds"],
        "recorded duration drift",
    )
    require(report["evidence"]["attack_windows"] == evidence["attack_windows"], "window drift")
    require(
        report["detection"]["detected_attack_windows"]
        == metrics["detected_attack_windows"],
        "detected-window drift",
    )
    require(
        report["detection"]["false_alert_events"] == metrics["false_alert_events"],
        "false-alert drift",
    )
    require(
        report["transition"]["selected_model"]["geometric_h1_h3_h5_error"]
        == metrics["transition_geometric_h1_h3_h5_error"],
        "transition error drift",
    )
    require(report["all_registered_gates_pass_on_final_test"], "final HAI gate failed")
    require(not manifest["artifacts"]["model"]["runtime_loaded"], "HAI model mislabeled loaded")
    authority = manifest["authority"]
    require(
        not any(value for key, value in authority.items() if key.startswith("may_")),
        "HAI artifact gained authority",
    )
    print(
        "PASS physical HAI v2 evidence: 48/50 windows, "
        "0.555 false alerts/hour, advisory only"
    )


if __name__ == "__main__":
    main()
