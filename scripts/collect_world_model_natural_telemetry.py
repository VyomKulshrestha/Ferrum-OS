#!/usr/bin/env python3
"""Parse privacy-bounded world-model telemetry from FerrumOS serial logs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import statistics


PATTERN = re.compile(
    r"\[world-model-telemetry-v1\] "
    r"tick=(?P<tick>\d+) action=(?P<action>[a-z0-9_]+) allowed=(?P<allowed>[01]) "
    r"risk=(?P<risk>[0-9.]+) lookahead=(?P<lookahead>\d+) "
    r"gate_cycles=(?P<gate_cycles>\d+) total_cycles=(?P<total_cycles>\d+) "
    r"executed=(?P<executed>[01]) success=(?P<success>[01]) "
    r"confirmation=(?P<confirmation>[a-z_]+)"
)


def percentile(values: list[int], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def parse_logs(paths: list[Path]) -> list[dict]:
    records = []
    for source in paths:
        session = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
        sequence = 0
        for line_number, line in enumerate(source.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            match = PATTERN.search(line)
            if not match:
                continue
            values = match.groupdict()
            sequence += 1
            records.append({
                "item_id": f"{session}-{sequence:06d}",
                "session_id": session,
                "source_file": source.name,
                "source_line": line_number,
                "tick": int(values["tick"]),
                "action": values["action"],
                "allowed": values["allowed"] == "1",
                "blocked": values["allowed"] == "0",
                "risk": float(values["risk"]),
                "lookahead": int(values["lookahead"]),
                "gate_cycles": int(values["gate_cycles"]),
                "total_cycles": int(values["total_cycles"]),
                "executed": values["executed"] == "1",
                "success": values["success"] == "1",
                "confirmation": values["confirmation"],
            })
    return records


def summarize(records: list[dict]) -> dict:
    gate_cycles = [row["gate_cycles"] for row in records]
    total_cycles = [row["total_cycles"] for row in records]
    proposed = len(records)
    blocked = sum(row["blocked"] for row in records)
    confirmations = {}
    actions = {}
    for row in records:
        confirmations[row["confirmation"]] = confirmations.get(row["confirmation"], 0) + 1
        actions[row["action"]] = actions.get(row["action"], 0) + 1
    return {
        "schema_version": 1,
        "protocol": "privacy-bounded-natural-use-telemetry-v1",
        "proposed_actions": proposed,
        "blocked_actions": blocked,
        "alerts_per_1000_actions": 1000.0 * blocked / max(proposed, 1),
        "executed_actions": sum(row["executed"] for row in records),
        "successful_results": sum(row["success"] for row in records),
        "confirmations": dict(sorted(confirmations.items())),
        "actions": dict(sorted(actions.items())),
        "gate_cycles": {
            "median": statistics.median(gate_cycles) if gate_cycles else 0,
            "p95": percentile(gate_cycles, 0.95),
            "max": max(gate_cycles, default=0),
        },
        "total_cycles": {
            "median": statistics.median(total_cycles) if total_cycles else 0,
            "p95": percentile(total_cycles, 0.95),
            "max": max(total_cycles, default=0),
        },
        "privacy_boundary": "No prompt, argument, path, provider, model, or tool output text is recorded.",
        "label_status": "unlabelled natural traffic; precision and recall require independent adjudication",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("logs", type=Path, nargs="+")
    parser.add_argument("--jsonl-out", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path, required=True)
    args = parser.parse_args()
    records = parse_logs([path.resolve() for path in args.logs])
    if not records:
        raise SystemExit("no world-model-telemetry-v1 records found")
    args.jsonl_out.parent.mkdir(parents=True, exist_ok=True)
    args.jsonl_out.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
    summary = summarize(records)
    args.summary_out.parent.mkdir(parents=True, exist_ok=True)
    args.summary_out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"records": len(records), "summary": str(args.summary_out)}, indent=2))


if __name__ == "__main__":
    main()
