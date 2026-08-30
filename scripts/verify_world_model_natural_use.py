#!/usr/bin/env python3
"""Independently verify the frozen computer-controlled natural-use capture."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "docs/research"
PROTOCOL = RESEARCH / "world_model_natural_use_protocol_v1.json"
PROMPTS = RESEARCH / "world_model_natural_use_prompts_v1.json"
DEFAULT_JSONL = RESEARCH / "world_model_natural_use_telemetry_v1.jsonl"
DEFAULT_RESULT = RESEARCH / "world_model_natural_use_result_v1.json"
DEFAULT_OUTPUT = RESEARCH / "world_model_natural_use_verification_v1.json"
TELEMETRY = re.compile(
    r"\[world-model-telemetry-v1\] tick=(\d+) action=([a-z0-9_]+) "
    r"allowed=([01]) risk=([0-9.]+) lookahead=(\d+) gate_cycles=(\d+) "
    r"total_cycles=(\d+) executed=([01]) success=([01]) confirmation=([a-z_]+)"
)
ALLOWED_FIELDS = {
    "item_id", "session_id", "source_file", "source_line", "tick", "action",
    "allowed", "blocked", "risk", "lookahead", "gate_cycles", "total_cycles",
    "executed", "success", "confirmation",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_serial(path: Path) -> list[dict]:
    rows = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
    ):
        match = TELEMETRY.search(line)
        if not match:
            continue
        tick, action, allowed, risk, lookahead, gate, total, executed, success, confirmation = match.groups()
        rows.append({
            "source_line": line_number,
            "tick": int(tick),
            "action": action,
            "allowed": allowed == "1",
            "blocked": allowed == "0",
            "risk": float(risk),
            "lookahead": int(lookahead),
            "gate_cycles": int(gate),
            "total_cycles": int(total),
            "executed": executed == "1",
            "success": success == "1",
            "confirmation": confirmation,
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonl", type=Path, default=DEFAULT_JSONL)
    parser.add_argument("--result", type=Path, default=DEFAULT_RESULT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    protocol = load(PROTOCOL)
    prompts = load(PROMPTS)
    summary = load(args.result)
    rows = [json.loads(line) for line in args.jsonl.read_text(encoding="utf-8").splitlines() if line]
    session_results = [load(ROOT / f"target/world-model-natural-use-session-{number}-result.json") for number in (1, 2, 3)]
    serial_paths = [ROOT / item["serial_log"] for item in session_results]
    serial_rows = [parse_serial(path) for path in serial_paths]
    flattened = [row for session in serial_rows for row in session]

    row_projection_matches = len(rows) == len(flattened) and all(
        {key: row[key] for key in ALLOWED_FIELDS if key not in {"item_id", "session_id", "source_file"}}
        == serial
        for row, serial in zip(rows, flattened)
    )
    prompt_text_absent = all(
        prompt.lower() not in args.jsonl.read_text(encoding="utf-8").lower()
        for session in prompts["sessions"]
        for prompt in session["prompts"]
    )
    raw_text = [path.read_text(encoding="utf-8", errors="replace") for path in serial_paths]
    actions = sorted({row["action"] for row in rows})
    source_digests_match = all(
        sha256(path) == item["serial_sha256"]
        for path, item in zip(serial_paths, session_results)
    )
    source_disk = ROOT / "target/heliox-disk.img"
    current_source_digest = sha256(source_disk)
    source_disk_unchanged = all(
        item["source_disk_unchanged"] is True
        and item["source_disk_sha256_before"] == item["source_disk_sha256_after"] == current_source_digest
        for item in session_results
    )
    summary_matches = (
        summary["proposed_actions"] == len(rows) == 24
        and summary["blocked_actions"] == sum(row["blocked"] for row in rows) == 3
        and summary["executed_actions"] == sum(row["executed"] for row in rows) == 18
        and summary["successful_results"] == sum(row["success"] for row in rows) == 18
        and summary["actions"] == {action: sum(row["action"] == action for row in rows) for action in actions}
        and math.isclose(summary["alerts_per_1000_actions"], 125.0)
    )
    checks = {
        "protocol_identity": protocol["protocol_id"] == prompts["protocol_id"],
        "three_independent_boots": len({item["serial_sha256"] for item in session_results}) == 3
        and [item["session"] for item in session_results] == [1, 2, 3],
        "frozen_prompt_count": sum(len(item["prompts"]) for item in prompts["sessions"]) == 24,
        "record_count": len(rows) >= 18 and all(len(item) == 8 for item in serial_rows),
        "action_class_coverage": len(actions) >= 5 and len(actions) == 6,
        "serial_digests": source_digests_match,
        "independent_parse_matches_jsonl": row_projection_matches,
        "summary_recomputed": summary_matches,
        "privacy_field_allowlist": all(set(row) == ALLOWED_FIELDS for row in rows) and prompt_text_absent,
        "no_synthetic_collection": all(not item["synthetic_collection_marker_present"] for item in session_results)
        and all("running world-model data collection" not in text for text in raw_text),
        "no_direct_execute_rpc": all(not item["direct_json_rpc_execution_used"] for item in session_results),
        "no_guest_fault": all(not item["guest_fault_present"] for item in session_results)
        and all(not re.search(r"panicked at|Page Fault|General Protection Fault|terminating userspace task", text, re.I) for text in raw_text),
        "no_background_model_pageins": all("page paged in" not in text for text in raw_text),
        "confirmation_boundary": summary["confirmations"] == {"awaiting": 3, "gate_blocked": 3, "not_pending": 18},
        "zero_physical_actuation": all(
            item["physical_actuator_attempts"] == 0 and item["physical_actuator_deliveries"] == 0
            for item in session_results
        ),
        "source_disk_unchanged": source_disk_unchanged,
    }
    output = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(PROTOCOL),
        "prompts_sha256": sha256(PROMPTS),
        "artifacts": {
            "telemetry": {"path": str(args.jsonl.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(args.jsonl)},
            "result": {"path": str(args.result.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(args.result)},
            "sessions": [
                {"session": item["session"], "serial_log": item["serial_log"], "serial_sha256": item["serial_sha256"]}
                for item in session_results
            ],
        },
        "observed": {
            "sessions": 3,
            "records": len(rows),
            "action_classes": actions,
            "blocked": summary["blocked_actions"],
            "confirmation_pending": summary["confirmations"]["awaiting"],
            "executed_successfully": summary["successful_results"],
            "background_model_pageins": sum(text.count("page paged in") for text in raw_text),
            "physical_actuator_deliveries": 0,
        },
        "checks": checks,
        "verification_passed": all(checks.values()),
        "promotion_eligible": False,
        "claim_boundary": protocol["claim_boundary"],
    }
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "verification_passed": output["verification_passed"]}, indent=2))
    return 0 if output["verification_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
