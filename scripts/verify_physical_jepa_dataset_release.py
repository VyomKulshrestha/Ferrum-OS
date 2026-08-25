#!/usr/bin/env python3
"""Verify the standalone Physical JEPA evidence-dataset release."""

from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import zipfile


RELEASE_NAME = "ferrumos-physical-jepa-safety-runtime-evidence-v1.0.0"
ARCHIVE_NAME = f"{RELEASE_NAME}.zip"
REQUIRED_FILES = {
    ARCHIVE_NAME,
    "README.md",
    "DATA_CARD.md",
    "LICENSE",
    "MANIFEST.json",
    "SHA256SUMS",
    "credential_scan_report.json",
    "verify_release.py",
}
DOI_PATTERN = re.compile(r"^10\.5281/zenodo\.\d+$")
EXPECTED_BENCHMARK_FAMILIES = {
    "boundary_safe": 128,
    "clear_safe": 176,
    "collision_course": 80,
    "near_safe": 128,
}
EXPECTED_MODEL_DIGESTS = {
    "models/ordinary_supervised_mlp.bin": "f8f081d1c250de1194330e7c412d268c83a6e58a879afb17775d280cf9a74b29",
    "models/v3_baseline.bin": "f267dc092f9fb2ab752b6d5ef6c5dc60cb799e15ca679da52bc5e707cc66ee60",
    "models/failed_v4_candidate.bin": "db0d5b16576490acde44bdfb60b884616b669a03aa3c3056dc28845a3b248b64",
    "models/v5_selected_candidate.bin": "23a06f37d668ee3f323bb8868dba4eed2baedef642fc32ab6410d4ee1da6e864",
    "models/deployed_physical_world_model.bin": "23a06f37d668ee3f323bb8868dba4eed2baedef642fc32ab6410d4ee1da6e864",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def parse_checksums(path: Path) -> dict[str, str]:
    declared: dict[str, str] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        digest, name = line.split("  ", 1)
        if Path(name).name != name or len(digest) != 64:
            raise ValueError(f"unsafe or malformed checksum entry: {line!r}")
        declared[name] = digest
    return declared


def verify_transition_table(blob: bytes, expected: dict) -> None:
    raw = gzip.decompress(blob)
    if bytes_sha256(raw) != expected["jsonl_sha256"]:
        raise ValueError(f"uncompressed transition digest mismatch for {expected['member']}")
    rows = 0
    dangerous = 0
    episodes: set[int] = set()
    source_counts: Counter[str] = Counter()
    for line in io.BytesIO(raw):
        if not line.strip():
            continue
        row = json.loads(line)
        if len(row["state"]) != 16 or len(row["next_state"]) != 16:
            raise ValueError(f"invalid state width in {expected['member']} row {rows}")
        if len(row["action_features"]) != 3:
            raise ValueError(f"invalid action-feature width in {expected['member']} row {rows}")
        if row["transition_source"] != "deterministic_ferrum_simulator":
            raise ValueError(f"invalid transition provenance in {expected['member']} row {rows}")
        if row["incident_role"] != "defensive_state_distribution_prior":
            raise ValueError(f"invalid incident-role boundary in {expected['member']} row {rows}")
        if row["partition"] != expected["partition"]:
            raise ValueError(f"partition mismatch in {expected['member']} row {rows}")
        rows += 1
        dangerous += int(bool(row["dangerous"]))
        episodes.add(int(row["episode"]))
        source_counts[str(row["source_id"])] += 1
    if rows != expected["transitions"]:
        raise ValueError(f"transition count mismatch for {expected['member']}")
    if len(episodes) != expected["episodes"]:
        raise ValueError(f"episode count mismatch for {expected['member']}")
    if dangerous != expected["dangerous_transitions"]:
        raise ValueError(f"danger-label count mismatch for {expected['member']}")
    expected_rows_by_source = {
        key: value * expected["steps"]
        for key, value in expected["source_episode_counts"].items()
    }
    if dict(sorted(source_counts.items())) != expected_rows_by_source:
        raise ValueError(f"source row counts mismatch for {expected['member']}")


def verify(release_dir: Path) -> list[str]:
    actual_files = {path.name for path in release_dir.iterdir() if path.is_file()}
    if actual_files != REQUIRED_FILES:
        raise ValueError(
            "release file contract mismatch: "
            f"missing={sorted(REQUIRED_FILES - actual_files)}, "
            f"unexpected={sorted(actual_files - REQUIRED_FILES)}"
        )
    checks = ["exact eight-file contract"]

    manifest = json.loads((release_dir / "MANIFEST.json").read_text(encoding="utf-8"))
    if manifest["release_name"] != RELEASE_NAME or manifest["release_version"] != "1.0.0":
        raise ValueError("unexpected release identity")
    if set(manifest["release_files"]) != REQUIRED_FILES:
        raise ValueError("manifest release-file contract mismatch")
    checks.append("release identity and manifest contract")

    publication = manifest["publication"]
    for key in ("dataset_doi", "report_doi"):
        if not DOI_PATTERN.fullmatch(publication[key]):
            raise ValueError(f"invalid reserved DOI in {key}")
    if publication["dataset_doi_url"] != f"https://doi.org/{publication['dataset_doi']}":
        raise ValueError("dataset DOI URL mismatch")
    if publication["report_doi_url"] != f"https://doi.org/{publication['report_doi']}":
        raise ValueError("report DOI URL mismatch")
    if publication["dataset_relation"] != "isSupplementTo":
        raise ValueError("dataset does not declare isSupplementTo")
    if publication["report_reciprocal_relation"] != "isSupplementedBy":
        raise ValueError("report reciprocal relation is absent")
    if publication["status"] != "publication-ready; reserved DOIs bound to exact release":
        raise ValueError("publication lifecycle status is not final-draft stable")
    for name in ("README.md", "DATA_CARD.md"):
        text = (release_dir / name).read_text(encoding="utf-8")
        if publication["dataset_doi"] not in text or publication["report_doi"] not in text:
            raise ValueError(f"{name} does not cite both reserved DOIs")
    checks.append("reserved DOI and reciprocal-relation consistency")

    declared = parse_checksums(release_dir / "SHA256SUMS")
    if set(declared) != REQUIRED_FILES - {"SHA256SUMS"}:
        raise ValueError("SHA256SUMS does not cover every non-checksum release file")
    for name, digest in declared.items():
        if sha256(release_dir / name) != digest:
            raise ValueError(f"release checksum mismatch for {name}")
    checks.append("release SHA-256 checksums")

    archive_path = release_dir / ARCHIVE_NAME
    if sha256(archive_path) != manifest["archive"]["sha256"]:
        raise ValueError("archive digest does not match manifest")
    if archive_path.stat().st_size != manifest["archive"]["bytes"]:
        raise ValueError("archive byte count does not match manifest")
    checks.append("archive identity")

    expected_members = {item["path"]: item for item in manifest["payload_members"]}
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(expected_members):
            raise ValueError("ZIP payload member contract mismatch")
        for name in names:
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts:
                raise ValueError(f"unsafe ZIP member path: {name}")
            blob = archive.read(name)
            expected = expected_members[name]
            if len(blob) != expected["bytes"] or bytes_sha256(blob) != expected["sha256"]:
                raise ValueError(f"payload digest or byte count mismatch for {name}")
        checks.append("safe payload paths and member SHA-256 digests")

        for partition in manifest["generated_partitions"].values():
            blob = archive.read(partition["member"])
            if bytes_sha256(blob) != partition["gzip_sha256"]:
                raise ValueError(f"generated gzip digest mismatch for {partition['member']}")
            verify_transition_table(blob, partition)
        checks.append("generated transition tables, schemas, counts, and provenance")

        for label, member in (
            ("sealed_v1", "data/physical_jepa_blinded_benchmark_v1_catalog.json"),
            ("sealed_v2", "data/physical_jepa_blinded_benchmark_v2_catalog.json"),
        ):
            catalog = json.loads(archive.read(member))
            if catalog["episodes"] != 512 or len(catalog["cases"]) != 512:
                raise ValueError(f"{label} does not contain exactly 512 cases")
            family_counts = Counter(str(case["family"]) for case in catalog["cases"])
            if dict(sorted(family_counts.items())) != EXPECTED_BENCHMARK_FAMILIES:
                raise ValueError(f"{label} family counts do not match the frozen design")
            canonical = json.dumps(
                catalog["cases"], sort_keys=True, separators=(",", ":")
            ).encode()
            if bytes_sha256(canonical) != catalog["cases_sha256"]:
                raise ValueError(f"{label} sealed case digest mismatch")
            if manifest["sealed_benchmarks"][label]["cases_sha256"] != catalog["cases_sha256"]:
                raise ValueError(f"{label} manifest digest mismatch")
        checks.append("sealed benchmark catalogs and family counts")

        if manifest["frozen_models"] != EXPECTED_MODEL_DIGESTS:
            raise ValueError("frozen model digest contract mismatch")
        for member, digest in EXPECTED_MODEL_DIGESTS.items():
            if bytes_sha256(archive.read(member)) != digest:
                raise ValueError(f"frozen model digest mismatch for {member}")
        if archive.read("models/v5_selected_candidate.bin") != archive.read(
            "models/deployed_physical_world_model.bin"
        ):
            raise ValueError("selected v5 and deployed artifact are not byte-identical")
        checks.append("four-model lineage and deployed-artifact identity")

    inspection = json.loads(
        (release_dir / "credential_scan_report.json").read_text(encoding="utf-8")
    )
    if inspection != manifest["content_inspection"] or inspection["status"] != "passed":
        raise ValueError("credential scan evidence is absent or inconsistent")
    if any(inspection["credential_pattern_hits"].values()):
        raise ValueError("credential scan reports actionable hits")
    checks.append("credential-pattern scan evidence")

    if manifest["license"]["identifier"] != "MIT":
        raise ValueError("unexpected dataset license")
    if not (release_dir / "LICENSE").read_text(encoding="utf-8").startswith("MIT License"):
        raise ValueError("explicit MIT license text is missing")
    checks.append("explicit dataset license")

    boundaries = " ".join(manifest["claim_boundary"]).lower()
    for required in (
        "deterministic ferrum simulator",
        "initial-state priors only",
        "physical actuator authority disabled",
        "not hil",
        "not physical deployment",
        "not certification",
        "not independent assessment",
    ):
        if required not in boundaries:
            raise ValueError(f"claim boundary is missing: {required}")
    card = " ".join(
        (release_dir / "DATA_CARD.md").read_text(encoding="utf-8").lower().split()
    )
    for required in ("simulation evidence", "avoids no collision", "zero underlying collision probability"):
        if required not in card:
            raise ValueError(f"data card is missing the claim boundary: {required}")
    checks.append("simulation-only and statistical claim boundaries")
    return checks


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    default_release_dir = script_dir
    if not (default_release_dir / "MANIFEST.json").is_file():
        default_release_dir = script_dir.parent / "target" / "physical-jepa-dataset-release-v1.0.0"
    parser = argparse.ArgumentParser()
    parser.add_argument("release_dir", type=Path, nargs="?", default=default_release_dir)
    args = parser.parse_args()
    checks = verify(args.release_dir.resolve())
    print(f"Physical JEPA dataset release verified: {len(checks)}/{len(checks)} checks")
    for check in checks:
        print(f"  PASS {check}")


if __name__ == "__main__":
    main()
