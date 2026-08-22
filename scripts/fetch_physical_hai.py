#!/usr/bin/env python3
"""Fetch and verify the registered HAI 23.05 files outside version control."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs" / "research" / "physical_hai_transfer_protocol_v1.json"
DEFAULT_CACHE = ROOT / "target" / "external-data" / "hai-23.05"
MEDIA_BASE = "https://media.githubusercontent.com/media/icsdataset/hai/master/hai-23.05"
MANUAL_URL = "https://raw.githubusercontent.com/icsdataset/hai/master/hai_dataset_technical_details.pdf"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def registered_files(protocol: dict, split: str) -> list[dict]:
    dataset = protocol["dataset"]
    groups = {
        "fit": dataset["train_files"],
        "calibration": [dataset["normal_calibration_file"]],
        "validation": dataset["validation_files"],
        "test": dataset["final_test_files"],
        "manual": [dataset["technical_manual"]],
    }
    if split == "all":
        names = ("fit", "calibration", "validation", "test", "manual")
        return [item for name in names for item in groups[name]]
    return list(groups[split])


def source_url(item: dict) -> str:
    if item["name"] == "hai_dataset_technical_details.pdf":
        return MANUAL_URL
    return f"{MEDIA_BASE}/{item['name']}"


def verify(path: Path, item: dict) -> tuple[bool, str]:
    if not path.is_file():
        return False, "missing"
    expected_size = item.get("bytes")
    if expected_size is not None and path.stat().st_size != expected_size:
        return False, f"size {path.stat().st_size} != {expected_size}"
    actual = sha256(path)
    if actual != item["sha256"]:
        return False, f"sha256 {actual} != {item['sha256']}"
    return True, "verified"


def download(path: Path, item: dict) -> None:
    partial = path.with_suffix(path.suffix + ".partial")
    if partial.exists():
        partial.unlink()
    request = urllib.request.Request(
        source_url(item), headers={"User-Agent": "FerrumOS-HAI-reproducibility/1.0"}
    )
    with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    valid, reason = verify(partial, item)
    if not valid:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"downloaded {item['name']} failed verification: {reason}")
    os.replace(partial, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--split",
        choices=("fit", "calibration", "validation", "test", "manual", "all"),
        default="fit",
    )
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    items = registered_files(protocol, args.split)
    args.cache.mkdir(parents=True, exist_ok=True)
    failures = []
    for item in items:
        path = args.cache / item["name"]
        valid, reason = verify(path, item)
        if not valid and not args.verify_only:
            print(f"fetching {item['name']} ({item.get('bytes', 'registered')} bytes)")
            download(path, item)
            valid, reason = verify(path, item)
        status = "PASS" if valid else "FAIL"
        print(f"[{status}] {item['name']}: {reason}")
        if not valid:
            failures.append(item["name"])
    if failures:
        print("missing or invalid: " + ", ".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
