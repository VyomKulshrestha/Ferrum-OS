#!/usr/bin/env python3
"""Verify the generated world-model dataset release end to end."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import tempfile


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(release_dir: Path) -> list[str]:
    manifest_path = release_dir / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    archive = release_dir / manifest["archive"]["file_name"]
    checks = []

    if sha256(archive) != manifest["archive"]["sha256"]:
        raise ValueError("archive checksum does not match manifest")
    checks.append("archive checksum")

    declared = {}
    for line in (release_dir / "SHA256SUMS.txt").read_text(encoding="ascii").splitlines():
        digest, name = line.split("  ", 1)
        declared[name] = digest
    for name, digest in declared.items():
        if sha256(release_dir / name) != digest:
            raise ValueError(f"SHA256SUMS mismatch for {name}")
    checks.append("release checksums")

    with tempfile.TemporaryDirectory(prefix="ferrumos-dataset-verify-") as temp:
        restored = Path(temp) / "dataset.jsonl"
        with gzip.open(archive, "rb") as source, restored.open("wb") as destination:
            while chunk := source.read(1024 * 1024):
                destination.write(chunk)
        if sha256(restored) != manifest["source"]["sha256"]:
            raise ValueError("decompressed JSONL does not match source checksum")
        rows = 0
        episodes = set()
        with restored.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                if len(row["before"]) != manifest["schema"]["state_embedding_size"]:
                    raise ValueError(f"row {rows} has an invalid before embedding")
                if len(row["after"]) != manifest["schema"]["state_embedding_size"]:
                    raise ValueError(f"row {rows} has an invalid after embedding")
                if len(row.get("action_features", [])) != manifest["schema"]["action_feature_size"]:
                    raise ValueError(f"row {rows} has invalid action features")
                episodes.add(str(row.get("episode_id")))
                rows += 1
        if rows != manifest["source"]["rows"] or len(episodes) != manifest["source"]["episodes"]:
            raise ValueError("decompressed row or episode count does not match manifest")
    checks.append("lossless decompression and schema")

    if any(manifest["split"]["episode_overlap"].values()):
        raise ValueError("manifest reports episode leakage")
    checks.append("episode-disjoint split")
    if any(manifest["content_inspection"]["credential_pattern_hits"].values()):
        raise ValueError("manifest reports credential-like content")
    checks.append("credential scan")
    if manifest["licence"]["identifier"] != "MIT":
        raise ValueError("unexpected or absent dataset licence")
    checks.append("explicit licence")
    return checks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("release_dir", type=Path)
    args = parser.parse_args()
    checks = verify(args.release_dir.resolve())
    print(f"world-model dataset release verified: {len(checks)}/{len(checks)} checks")
    for check in checks:
        print(f"  PASS {check}")


if __name__ == "__main__":
    main()
