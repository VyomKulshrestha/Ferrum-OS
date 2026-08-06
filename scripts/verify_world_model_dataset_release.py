#!/usr/bin/env python3
"""Verify the generated world-model dataset release end to end."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import tempfile


REQUIRED_FILES = {
    "ferrumos-world-model-dataset-v1.0.0.jsonl.gz",
    "README.md",
    "DATA_CARD.md",
    "LICENSE",
    "MANIFEST.json",
    "SHA256SUMS",
    "schema.json",
    "episode_split_audit.json",
    "credential_scan_report.json",
    "verify_release.py",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(release_dir: Path) -> list[str]:
    actual_files = {path.name for path in release_dir.iterdir() if path.is_file()}
    if actual_files != REQUIRED_FILES:
        missing = sorted(REQUIRED_FILES - actual_files)
        unexpected = sorted(actual_files - REQUIRED_FILES)
        raise ValueError(f"release file contract mismatch: missing={missing}, unexpected={unexpected}")

    manifest_path = release_dir / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    archive = release_dir / manifest["archive"]["file_name"]
    checks = ["exact ten-file contract"]

    if set(manifest["artifacts"]) != REQUIRED_FILES:
        raise ValueError("manifest artifact list does not match the release contract")
    checks.append("manifest artifact contract")

    if sha256(archive) != manifest["archive"]["sha256"]:
        raise ValueError("archive checksum does not match manifest")
    checks.append("archive checksum")

    declared = {}
    for line in (release_dir / "SHA256SUMS").read_text(encoding="ascii").splitlines():
        digest, name = line.split("  ", 1)
        if Path(name).name != name:
            raise ValueError(f"unsafe checksum path: {name}")
        declared[name] = digest
    if set(declared) != REQUIRED_FILES - {"SHA256SUMS"}:
        raise ValueError("SHA256SUMS does not cover every non-checksum release file")
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

    schema = json.loads((release_dir / "schema.json").read_text(encoding="utf-8"))
    if schema["x-ferrumos"]["state_embedding_size"] != manifest["schema"]["state_embedding_size"]:
        raise ValueError("schema and manifest disagree on state embedding size")
    if schema["x-ferrumos"]["action_feature_size"] != manifest["schema"]["action_feature_size"]:
        raise ValueError("schema and manifest disagree on action feature size")
    if set(schema["properties"]) != set(manifest["schema"]["fields"]):
        raise ValueError("schema properties do not cover the manifest field set")
    checks.append("standalone schema")

    if any(manifest["split"]["episode_overlap"].values()):
        raise ValueError("manifest reports episode leakage")
    split_audit = json.loads((release_dir / "episode_split_audit.json").read_text(encoding="utf-8"))
    if split_audit["status"] != "passed":
        raise ValueError("episode split audit is not marked passed")
    for key, value in manifest["split"].items():
        if split_audit.get(key) != value:
            raise ValueError(f"episode split audit mismatch for {key}")
    if split_audit["train_rows"] + split_audit["validation_rows"] + split_audit["test_rows"] != split_audit["eligible_rows"]:
        raise ValueError("split row counts do not sum to eligible rows")
    if split_audit["train_episodes"] + split_audit["validation_episodes"] + split_audit["test_episodes"] != split_audit["eligible_episodes"]:
        raise ValueError("split episode counts do not sum to eligible episodes")
    if split_audit["eligible_rows"] + split_audit["excluded_rows"] != split_audit["accounted_rows"]:
        raise ValueError("eligible and excluded rows do not sum to accounted rows")
    checks.append("episode-disjoint split")
    if any(manifest["content_inspection"]["credential_pattern_hits"].values()):
        raise ValueError("manifest reports credential-like content")
    credential_report = json.loads(
        (release_dir / "credential_scan_report.json").read_text(encoding="utf-8")
    )
    if credential_report["status"] != "passed":
        raise ValueError("credential scan report is not marked passed")
    if credential_report["credential_pattern_hits"] != manifest["content_inspection"][
        "credential_pattern_hits"
    ]:
        raise ValueError("credential scan report does not match manifest")
    checks.append("credential scan")
    if manifest["licence"]["identifier"] != "MIT":
        raise ValueError("unexpected or absent dataset licence")
    if not (release_dir / "LICENSE").read_text(encoding="utf-8").strip():
        raise ValueError("dataset licence file is empty")
    checks.append("explicit licence")
    for documentation in ("README.md", "DATA_CARD.md"):
        if not (release_dir / documentation).read_text(encoding="utf-8").strip():
            raise ValueError(f"{documentation} is empty")
    checks.append("release documentation")
    return checks


def main() -> None:
    parser = argparse.ArgumentParser()
    script_dir = Path(__file__).resolve().parent
    default_release_dir = script_dir
    if not (default_release_dir / "MANIFEST.json").is_file():
        default_release_dir = script_dir.parent / "target" / "world-model-dataset-release"
    parser.add_argument("release_dir", type=Path, nargs="?", default=default_release_dir)
    args = parser.parse_args()
    checks = verify(args.release_dir.resolve())
    print(f"world-model dataset release verified: {len(checks)}/{len(checks)} checks")
    for check in checks:
        print(f"  PASS {check}")


if __name__ == "__main__":
    main()
