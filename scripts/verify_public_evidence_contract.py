#!/usr/bin/env python3
"""Verify FerrumOS public JSON, provenance, and agent-readable evidence contracts."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS  {message}")


def canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def portable_text_sha256(path: Path) -> str:
    """Hash UTF-8 source text after normalizing checkout-specific line endings."""
    normalized = (
        path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def validate_schema_required(document: dict, schema: dict, label: str) -> None:
    missing = [key for key in schema["required"] if key not in document]
    require(not missing, f"{label} contains every schema-required top-level field")
    require(
        document["$schema"] == schema["$id"], f"{label} references its canonical schema"
    )


def validate_sources(provenance: dict, label: str) -> None:
    paths: set[str] = set()
    for source in provenance["inputs"]:
        relative = source["path"]
        require(relative not in paths, f"{label} provenance path is unique: {relative}")
        paths.add(relative)
        path = ROOT / relative
        require(path.is_file(), f"{label} provenance source exists: {relative}")
        actual = portable_text_sha256(path)
        require(
            actual == source["sha256"], f"{label} provenance hash matches: {relative}"
        )


def command_sweep_count() -> int:
    source = (ROOT / "scripts" / "command_sweep.mjs").read_text(encoding="utf-8")
    start = source.index("const tests = [")
    end = source.index("\n];", start)
    return len(re.findall(r'^\s*\["', source[start:end], re.MULTILINE))


def main() -> int:
    capabilities = load_json(ROOT / "capabilities.json")
    benchmarks = load_json(ROOT / "benchmarks.json")
    capability_schema = load_json(ROOT / "schemas" / "capabilities.schema.json")
    benchmark_schema = load_json(ROOT / "schemas" / "benchmarks.schema.json")
    llms_full = (ROOT / "llms-full.txt").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    architecture = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")

    require(
        capability_schema["$schema"].endswith("2020-12/schema"),
        "capability schema uses JSON Schema 2020-12",
    )
    require(
        benchmark_schema["$schema"].endswith("2020-12/schema"),
        "benchmark schema uses JSON Schema 2020-12",
    )
    validate_schema_required(capabilities, capability_schema, "capabilities.json")
    validate_schema_required(benchmarks, benchmark_schema, "benchmarks.json")
    require(
        capabilities["schema_version"] == "2.0.0",
        "capability schema version is explicit",
    )
    require(
        benchmarks["schema_version"] == "2.1.0", "benchmark schema version is explicit"
    )

    actions = capabilities["actions"]
    names = [action["name"] for action in actions]
    require(
        len(actions) == capabilities["canonical_action_count"],
        "capability count matches action records",
    )
    require(len(names) == len(set(names)), "canonical action names are unique")
    tier_names = ["observe", "safe", "network", "modify", "destructive"]
    action_required = capability_schema["$defs"]["action"]["required"]
    for action in actions:
        if not all(key in action for key in action_required):
            raise AssertionError(f"action contract is incomplete: {action['name']}")
        tier = action["permission_tier"]
        if action["permission_tier_name"] != tier_names[tier]:
            raise AssertionError(
                f"action tier name does not match level: {action['name']}"
            )
        if action["operator_confirmation_required"] != (tier >= 3):
            raise AssertionError(
                f"default confirmation does not match tier: {action['name']}"
            )
        if action["availability"] != "current-main-source":
            raise AssertionError(f"action release scope is missing: {action['name']}")
        if f"`{action['name']}`" not in llms_full:
            raise AssertionError(f"llms-full omits action: {action['name']}")
    require(
        True,
        "every action satisfies schema, tier, confirmation, scope, and llms-full contracts",
    )

    expected_catalog_hash = canonical_sha256(actions)
    require(
        capabilities["provenance"]["action_catalog_sha256"] == expected_catalog_hash,
        "capability catalog hash matches canonical action records",
    )
    validate_sources(capabilities["provenance"], "capability")
    validate_sources(benchmarks["provenance"], "benchmark")

    sections = [
        "paper_release",
        "current_ring3_preview",
        "paired_preview_queue",
        "physical_simulator_jepa",
        "neural_synthetic",
        "qemu_command_audit",
        "cyber_physical_software",
    ]
    protocol_ids = [benchmarks[name]["protocol_id"] for name in sections]
    require(
        len(protocol_ids) == len(set(protocol_ids)),
        "benchmark protocol identifiers are unique",
    )
    for name in sections:
        require(
            bool(benchmarks[name]["evidence_grade"]),
            f"benchmark evidence grade is present: {name}",
        )
    require(
        benchmarks["paper_release"]["rules_plus_jepa_balanced_accuracy"]
        - benchmarks["paper_release"]["rules_plus_mean_balanced_accuracy"]
        < 0.01,
        "published JEPA result is not represented as a material baseline gain",
    )
    require(
        benchmarks["physical_simulator_jepa"]["validated_for_gating"] is False,
        "physical simulator artifact remains shadow-only",
    )
    require(
        benchmarks["neural_synthetic"]["emitted_intents"] == 0,
        "neural no-control soak remains zero",
    )
    qemu = benchmarks["qemu_command_audit"]
    require(
        qemu["command_sweep_cases"] == qemu["command_sweep_passed"] == 101,
        "dated QEMU command sweep records 101 passing cases",
    )
    require(
        qemu["catalog_entries"] == qemu["catalog_passed"] == 81
        and qemu["unknown_command_paths"] == 0,
        "dated QEMU catalog audit records 81 passing entries",
    )
    cyber = benchmarks["cyber_physical_software"]
    require(
        cyber["contract_tests_passed"] == 152 and cyber["contract_tests_failed"] == 0,
        "cyber-physical software contract records 152 passing tests",
    )
    require(
        cyber["model_and_decoder_gates_passed"] == 32
        and cyber["model_and_decoder_gates_failed"] == 0,
        "cyber-physical model and decoder checks record 32 passing gates",
    )
    require(
        "does not prove" in cyber["claim_boundary"],
        "cyber-physical software evidence preserves external claim boundaries",
    )
    require(
        "not directly comparable" in " ".join(benchmarks["global_limitations"]),
        "cross-protocol comparison is prohibited",
    )

    count = command_sweep_count()
    require(count == 101, "source-defined command sweep contains 101 cases")
    require("101/101" in readme, "README command-sweep count matches source")
    require(
        "101-case" in architecture, "architecture command-sweep count matches source"
    )
    require(
        "102/102" not in readme and "102-case" not in architecture,
        "stale command-sweep counts are absent",
    )

    print("\nPublic evidence contract verification passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, ValueError, json.JSONDecodeError) as error:
        print(f"FAIL  {error}", file=sys.stderr)
        raise SystemExit(1)
