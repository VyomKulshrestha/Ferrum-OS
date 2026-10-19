#!/usr/bin/env python3
"""Verify the standalone FerrumOS incident-dynamics and real-telemetry evidence release.

Dependency-free. Run from the folder holding the release files:  python verify_release.py
Checks SHA256SUMS, every archive member against MANIFEST.json, the DOI relations, the credential
scan, and that no upstream HAI or SMD file is redistributed inside the archive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

RELEASE_NAME = "ferrumos-incident-dynamics-real-telemetry-evidence-v1.0.0"
ARCHIVE_NAME = f"{RELEASE_NAME}.zip"
REQUIRED_FILES = {ARCHIVE_NAME, "README.md", "DATA_CARD.md", "LICENSE", "MANIFEST.json", "SHA256SUMS",
                  "credential_scan_report.json", "verify_release.py"}
DOI_PATTERN = re.compile(r"^10\.5281/zenodo\.\d+$")
UPSTREAM_NAME = re.compile(r"(^|/)(train\d|test\d|hai-train\d|hai-test\d|label-test\d)\.csv(\.gz)?$|ServerMachineDataset|machine-\d-\d+\.txt$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-dir", type=Path, default=Path(__file__).resolve().parent)
    root = parser.parse_args().release_dir
    checks = []

    def check(name, ok, detail=""):
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    present = {p.name for p in root.iterdir() if p.is_file()}
    check("required release files present", REQUIRED_FILES <= present, sorted(REQUIRED_FILES - present))
    declared = {}
    for line in (root / "SHA256SUMS").read_text(encoding="ascii").splitlines():
        digest, name = line.split("  ", 1)
        declared[name] = digest
    check("SHA256SUMS covers every other release file", set(declared) == REQUIRED_FILES - {"SHA256SUMS"})
    bad = [n for n, d in declared.items() if sha256_file(root / n) != d]
    check("release file checksums", not bad, bad)

    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    pub = manifest["publication"]
    check("dataset and report DOIs well formed", DOI_PATTERN.fullmatch(pub["dataset_doi"]) and DOI_PATTERN.fullmatch(pub["report_doi"]))
    check("archive digest matches manifest", sha256_file(root / ARCHIVE_NAME) == manifest["archive"]["sha256"])
    with zipfile.ZipFile(root / ARCHIVE_NAME) as archive:
        names = sorted(archive.namelist())
        expected = sorted(m["path"] for m in manifest["payload_members"])
        check("archive members equal manifest members", names == expected, f"{len(names)} members")
        mismatched = [m["path"] for m in manifest["payload_members"]
                      if hashlib.sha256(archive.read(m["path"])).hexdigest() != m["sha256"]]
        check("every archive member digest", not mismatched, mismatched[:5])
    check("no upstream HAI or SMD file redistributed", not [n for n in names if UPSTREAM_NAME.search(n)])
    scan = json.loads((root / "credential_scan_report.json").read_text(encoding="utf-8"))
    check("credential scan found no secrets", sum(scan["secret_pattern_hits"].values()) == 0, scan["secret_pattern_hits"])
    report = {"release": RELEASE_NAME, "checks": checks, "overall_pass": all(c["pass"] for c in checks)}
    print(json.dumps(report, indent=2))
    return 0 if report["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
