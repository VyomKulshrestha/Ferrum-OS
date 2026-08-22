#!/usr/bin/env python3
"""Fetch registered HAI 21.03 gzip files and verify their Git blob identity."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs" / "research" / "physical_hai_v2_cross_version_protocol.json"
DEFAULT_CACHE = ROOT / "target" / "external-data" / "hai-21.03"
BASE_URL = "https://raw.githubusercontent.com/icsdataset/hai/master/hai-21.03"


def git_blob_sha1(path: Path) -> str:
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(f"blob {path.stat().st_size}\0".encode())
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(path: Path, item: dict) -> tuple[bool, str]:
    if not path.is_file():
        return False, "missing"
    if path.stat().st_size != item["bytes"]:
        return False, f"size {path.stat().st_size} != {item['bytes']}"
    actual = git_blob_sha1(path)
    if actual != item["git_blob_sha1"]:
        return False, f"git blob {actual} != {item['git_blob_sha1']}"
    return True, "verified"


def download(path: Path, item: dict) -> None:
    partial = path.with_suffix(path.suffix + ".partial")
    partial.unlink(missing_ok=True)
    request = urllib.request.Request(
        f"{BASE_URL}/{item['name']}",
        headers={"User-Agent": "FerrumOS-HAI-cross-version-reproducibility/1.0"},
    )
    with (
        urllib.request.urlopen(request, timeout=60) as response,
        partial.open("wb") as output,
    ):
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    valid, reason = verify(partial, item)
    if not valid:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"downloaded {item['name']} failed verification: {reason}")
    os.replace(partial, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("normal", "final", "all"), default="normal")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    groups = {
        "normal": protocol["target_domain_normal_files"],
        "final": protocol["sealed_final_files"],
    }
    items = (
        groups["normal"] + groups["final"]
        if args.split == "all"
        else groups[args.split]
    )
    args.cache.mkdir(parents=True, exist_ok=True)
    failures = []
    for item in items:
        path = args.cache / item["name"]
        valid, reason = verify(path, item)
        if not valid and not args.verify_only:
            print(f"fetching {item['name']} ({item['bytes']} bytes)", flush=True)
            download(path, item)
            valid, reason = verify(path, item)
        print(f"[{'PASS' if valid else 'FAIL'}] {item['name']}: {reason}")
        if not valid:
            failures.append(item["name"])
    if failures:
        print("missing or invalid: " + ", ".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
