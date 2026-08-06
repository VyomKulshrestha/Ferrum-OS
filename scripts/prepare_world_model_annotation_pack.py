#!/usr/bin/env python3
"""Create two independently randomized, decision-blinded annotation sheets."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import random


FIELDS = (
    "blind_id", "annotator_id", "action_summary", "state_summary", "context_notes",
    "label", "threat_category", "confidence", "rationale",
)
HIDDEN_KEYS = {"blocked", "allowed", "risk", "lookahead", "reason", "dangerous", "label"}


def stable_id(source_id: str, salt: str) -> str:
    return "wm-" + hashlib.sha256(f"{salt}:{source_id}".encode()).hexdigest()[:16]


def load_context(path: Path | None) -> dict[str, dict]:
    if path is None:
        return {}
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            result[str(row["item_id"])] = row
    return result


def load_items(path: Path, context: dict[str, dict], salt: str) -> tuple[list[dict], dict]:
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_items = payload.get("cases", payload if isinstance(payload, list) else [])
    else:
        raw_items = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    items = []
    key = {}
    for index, raw in enumerate(raw_items):
        source_id = str(raw.get("item_id") or raw.get("id") or f"row-{index}")
        blind_id = stable_id(source_id, salt)
        companion = context.get(source_id, {})
        if any(name in companion for name in HIDDEN_KEYS):
            raise ValueError(f"context for {source_id} contains a decision or label field")
        if raw.get("steps"):
            action_summary = json.dumps([
                {"name": step.get("action", {}).get("name"), "args": step.get("action", {}).get("args", {})}
                for step in raw["steps"]
            ], sort_keys=True)
            state = raw.get("initial_raw", [])
            state_summary = json.dumps({
                "process_fraction": state[0] if len(state) > 0 else None,
                "heap_fraction": state[1] if len(state) > 1 else None,
                "disk_fraction": state[3] if len(state) > 3 else None,
                "steps": len(raw["steps"]),
            }, sort_keys=True)
        else:
            action_summary = str(companion.get("action_summary") or raw.get("action") or "")
            state_summary = str(companion.get("state_summary") or "context not collected")
        items.append({
            "blind_id": blind_id,
            "annotator_id": "",
            "action_summary": action_summary,
            "state_summary": state_summary,
            "context_notes": str(companion.get("context_notes") or ""),
            "label": "",
            "threat_category": "",
            "confidence": "",
            "rationale": "",
        })
        key[blind_id] = {
            "source_id": source_id,
            "oracle_label": "dangerous" if raw.get("dangerous") is True else "safe" if raw.get("dangerous") is False else None,
            "gate_blocked": raw.get("blocked"),
        }
    return items, key


def write_sheet(path: Path, items: list[dict], seed: int) -> None:
    shuffled = list(items)
    random.Random(seed).shuffle(shuffled)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(shuffled)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--context", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260806)
    parser.add_argument("--salt", default="ferrumos-world-model-annotation-v1")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    items, key = load_items(args.input, load_context(args.context), args.salt)
    if not items:
        raise SystemExit("no annotation items found")
    write_sheet(args.out_dir / "annotator_a.csv", items, args.seed)
    write_sheet(args.out_dir / "annotator_b.csv", items, args.seed + 1)
    (args.out_dir / "blinding_key.json").write_text(json.dumps({
        "schema_version": 1,
        "items": key,
        "warning": "Keep this file from annotators until both sheets are locked.",
    }, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"items": len(items), "out_dir": str(args.out_dir)}, indent=2))


if __name__ == "__main__":
    main()
