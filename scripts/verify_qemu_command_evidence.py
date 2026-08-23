#!/usr/bin/env python3
"""Verify the committed, source-bound FerrumOS QEMU command audit record."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = (
    ROOT / "docs" / "benchmarks" / "raw" / "2026-08-23" / "qemu-command-audit.json"
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS  {message}")


def committed_bytes(path: Path, revision: str = "HEAD") -> bytes:
    relative = path.relative_to(ROOT).as_posix()
    return subprocess.check_output(["git", "show", f"{revision}:{relative}"], cwd=ROOT)


def committed_blob_sha1(path: Path, revision: str) -> str:
    relative = path.relative_to(ROOT).as_posix()
    return subprocess.check_output(
        ["git", "rev-parse", f"{revision}:{relative}"], cwd=ROOT, text=True
    ).strip()


def commit_exists(revision: str) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{revision}^{{commit}}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def command_sweep_count(source: str) -> int:
    start = source.index("const tests = [")
    end = source.index("\n];", start)
    return len(re.findall(r'^\s*\["', source[start:end], re.MULTILINE))


def main() -> int:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    require(
        evidence["schema_version"] == 2, "QEMU evidence schema version is supported"
    )
    require(
        evidence["protocol"] == "ferrumos-qemu-command-audit-v2",
        "QEMU evidence protocol is explicit",
    )
    require(
        all(
            re.fullmatch(r"[a-f0-9]{40}", evidence[field]) is not None
            for field in ("os_source_commit", "audit_source_commit")
        ),
        "QEMU evidence names full OS and harness source commits",
    )
    require(
        commit_exists(evidence["os_source_commit"])
        and commit_exists(evidence["audit_source_commit"]),
        "named OS and harness source commits exist in repository history",
    )

    sweep = evidence["harness"]["command_sweep"]
    catalog = evidence["harness"]["exhaustive_catalog"]
    persistence = evidence["harness"]["ata_cold_restart"]
    artifacts = evidence["artifacts"]
    sweep_path = ROOT / sweep["path"]
    catalog_path = ROOT / catalog["path"]
    persistence_path = ROOT / persistence["path"]
    recorded_sweep_source = committed_bytes(
        sweep_path, evidence["audit_source_commit"]
    ).decode("utf-8")
    require(
        committed_blob_sha1(sweep_path, evidence["audit_source_commit"])
        == sweep["git_blob_sha1"],
        "recorded command sweep matches its audit-commit Git blob",
    )
    require(
        committed_blob_sha1(catalog_path, evidence["audit_source_commit"])
        == catalog["git_blob_sha1"],
        "recorded catalog audit matches its audit-commit Git blob",
    )
    require(
        committed_blob_sha1(persistence_path, evidence["audit_source_commit"])
        == persistence["git_blob_sha1"],
        "recorded ATA persistence harness matches its audit-commit Git blob",
    )
    require(
        command_sweep_count(recorded_sweep_source) == sweep["cases"],
        "command sweep case count matches its recorded audit source",
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
        persistence["boots"] == 2
        and persistence["checks"] == persistence["passed"] == 3
        and persistence["failed"] == 0
        and persistence["source_disk_is_copied_before_test"] is True,
        "committed ATA audit records a passing copied-disk cold restart",
    )
    persistence_source = committed_bytes(
        persistence_path, evidence["audit_source_commit"]
    ).decode("utf-8")
    require(
        "process.exitCode = 1" in recorded_sweep_source
        and "process.exitCode = 1"
        in committed_bytes(catalog_path, evidence["audit_source_commit"]).decode(
            "utf-8"
        )
        and "process.exit(failures.length ? 1 : 0)" in persistence_source,
        "every recorded harness returns non-zero on failure",
    )
    require(
        "fs.copyFileSync(sourceDisk, runDisk)" in persistence_source
        and 'runPhase("write"' in persistence_source
        and 'runPhase("reboot"' in persistence_source
        and "file content survives a cold QEMU restart" in persistence_source,
        "ATA harness performs write and verification on separate cold boots",
    )
    require(
        all(re.fullmatch(r"[a-f0-9]{64}", digest) for digest in artifacts.values()),
        "measured image, disk, summary, and serial artifact digests are explicit",
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
