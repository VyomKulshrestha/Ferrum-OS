#!/usr/bin/env python3
"""Verify the committed, source-bound FerrumOS QEMU command audit record."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = (
    ROOT / "docs" / "benchmarks" / "raw" / "2026-08-13" / "qemu-command-audit.json"
)
FOCUSED_SERIAL = EVIDENCE.with_name("qemu-command-serial.txt")
CATALOG_SUMMARY = EVIDENCE.with_name("qemu-command-summary.json")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS  {message}")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measured_windows_text_sha256(path: Path) -> str:
    """Hash source text using the CRLF representation used by the measured run."""
    normalized = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return hashlib.sha256(normalized.replace("\n", "\r\n").encode("utf-8")).hexdigest()


def command_sweep_count(path: Path) -> int:
    source = path.read_text(encoding="utf-8")
    start = source.index("const tests = [")
    end = source.index("\n];", start)
    return len(re.findall(r'^\s*\["', source[start:end], re.MULTILINE))


def main() -> int:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    require(
        evidence["schema_version"] == 1, "QEMU evidence schema version is supported"
    )
    require(
        evidence["protocol"] == "ferrumos-qemu-command-audit-v1",
        "QEMU evidence protocol is explicit",
    )
    require(
        all(
            re.fullmatch(r"[a-f0-9]{40}", evidence[field]) is not None
            for field in ("os_source_commit", "audit_source_commit")
        ),
        "QEMU evidence names full OS and harness source commits",
    )

    sweep = evidence["harness"]["command_sweep"]
    catalog = evidence["harness"]["exhaustive_catalog"]
    artifacts = evidence["artifacts"]
    sweep_path = ROOT / sweep["path"]
    catalog_path = ROOT / catalog["path"]
    require(
        measured_windows_text_sha256(sweep_path) == sweep["sha256"],
        "command sweep content matches the measured Windows-text hash",
    )
    require(
        measured_windows_text_sha256(catalog_path) == catalog["sha256"],
        "catalog audit content matches the measured Windows-text hash",
    )
    require(
        command_sweep_count(sweep_path) == sweep["cases"],
        "command sweep case count matches source",
    )
    require(
        sweep["cases"] == sweep["passed"] and sweep["failed"] == 0,
        "committed command sweep records every case passing",
    )
    require(
        catalog["entries"] == catalog["passed"] == catalog["prompt_returns"]
        and catalog["failed"] == catalog["unknown_command_paths"] == 0,
        "committed catalog audit records every entry and prompt passing",
    )
    require(
        sha256(FOCUSED_SERIAL) == artifacts["command_serial_sha256"],
        "public focused serial log matches the measured artifact hash",
    )
    require(
        sha256(CATALOG_SUMMARY) == artifacts["catalog_summary_sha256"],
        "public catalog summary matches the measured artifact hash",
    )
    focused_serial = FOCUSED_SERIAL.read_text(encoding="utf-8")
    require(
        "[init] userspace is alive in ring 3" in focused_serial,
        "public focused serial preserves the terminal Ring-3 success marker",
    )
    command_summary = json.loads(CATALOG_SUMMARY.read_text(encoding="utf-8"))
    require(
        len(command_summary) == catalog["entries"]
        and all(record["promptReturned"] for record in command_summary),
        "public catalog summary contains every prompt-returning entry",
    )
    require(
        not any(
            "unknown command" in record.get("output", "").lower()
            for record in command_summary
        ),
        "public catalog summary contains no unknown-command route",
    )
    require(
        "process.exitCode = 1" in sweep_path.read_text(encoding="utf-8"),
        "terminal Ring-3 failure makes the command sweep non-zero",
    )
    require(
        "physical-PC" in evidence["claim_boundary"]
        and "live EEG" in evidence["claim_boundary"]
        and "formal safety" in evidence["claim_boundary"],
        "QEMU evidence preserves hardware and safety claim boundaries",
    )
    print("\nCommitted QEMU command evidence verification passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, ValueError, json.JSONDecodeError) as error:
        print(f"FAIL  {error}")
        raise SystemExit(1)
