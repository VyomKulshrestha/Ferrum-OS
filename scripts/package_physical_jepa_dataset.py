#!/usr/bin/env python3
"""Build the deterministic Physical JEPA evidence-dataset Zenodo package."""

from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Iterable
import zipfile

import physical_incident_scenarios as incidents


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "target" / "physical-jepa-dataset-release-v1.0.0"
DATA_CARD = ROOT / "docs" / "research" / "PHYSICAL_JEPA_DATASET_CARD.md"
DATASET_LICENSE = ROOT / "docs" / "research" / "PHYSICAL_JEPA_DATASET_LICENSE.md"
RELEASE_VERIFIER = ROOT / "scripts" / "verify_physical_jepa_dataset_release.py"
RELEASE_VERSION = "1.0.0"
RELEASE_NAME = "ferrumos-physical-jepa-safety-runtime-evidence-v1.0.0"
ARCHIVE_NAME = f"{RELEASE_NAME}.zip"
RELEASE_FILES = {
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

TEXT_SUFFIXES = {".csv", ".json", ".md", ".py", ".txt"}
SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "github_token": re.compile(r"\bgh[opsu]_[A-Za-z0-9]{30,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "bearer_token": re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{24,}=*", re.IGNORECASE),
}
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)

EXPECTED_MODEL_DIGESTS = {
    "models/ordinary_supervised_mlp.bin": "f8f081d1c250de1194330e7c412d268c83a6e58a879afb17775d280cf9a74b29",
    "models/v3_baseline.bin": "f267dc092f9fb2ab752b6d5ef6c5dc60cb799e15ca679da52bc5e707cc66ee60",
    "models/failed_v4_candidate.bin": "db0d5b16576490acde44bdfb60b884616b669a03aa3c3056dc28845a3b248b64",
    "models/v5_selected_candidate.bin": "23a06f37d668ee3f323bb8868dba4eed2baedef642fc32ab6410d4ee1da6e864",
    "models/deployed_physical_world_model.bin": "23a06f37d668ee3f323bb8868dba4eed2baedef642fc32ab6410d4ee1da6e864",
}

PAYLOAD_SOURCES = {
    "catalogs/physical_incident_sources_v2.json": "docs/research/physical_incident_sources_v2.json",
    "catalogs/physical_incident_v5_test_sources.json": "docs/research/physical_incident_v5_test_sources.json",
    "data/physical_jepa_blinded_benchmark_v1_catalog.json": "docs/research/physical_jepa_blinded_benchmark_v1_catalog.json",
    "data/physical_jepa_blinded_benchmark_v2_catalog.json": "docs/research/physical_jepa_blinded_benchmark_v2_catalog.json",
    "protocols/physical_jepa_v3_protocol.json": "docs/research/physical_jepa_v3_protocol.json",
    "protocols/physical_jepa_v4_protocol.json": "docs/research/physical_jepa_v4_protocol.json",
    "protocols/physical_jepa_v4_amendment1.json": "docs/research/physical_jepa_v4_amendment1.json",
    "protocols/physical_jepa_v5_protocol.json": "docs/research/physical_jepa_v5_protocol.json",
    "protocols/physical_jepa_paper_protocol_v1.json": "docs/research/physical_jepa_paper_protocol_v1.json",
    "protocols/physical_jepa_paper_review_protocol_v1.json": "docs/research/physical_jepa_paper_review_protocol_v1.json",
    "protocols/physical_jepa_paper_dynamics_calibration_protocol_v1.json": "docs/research/physical_jepa_paper_dynamics_calibration_protocol_v1.json",
    "protocols/physical_jepa_paper_dynamics_calibration_protocol_v2.json": "docs/research/physical_jepa_paper_dynamics_calibration_protocol_v2.json",
    "protocols/physical_jepa_blinded_benchmark_v1_protocol.json": "docs/research/physical_jepa_blinded_benchmark_v1_protocol.json",
    "protocols/physical_jepa_blinded_benchmark_v1_commitment.json": "docs/research/physical_jepa_blinded_benchmark_v1_commitment.json",
    "protocols/physical_jepa_blinded_benchmark_v2_protocol.json": "docs/research/physical_jepa_blinded_benchmark_v2_protocol.json",
    "protocols/physical_jepa_blinded_benchmark_v2_commitment.json": "docs/research/physical_jepa_blinded_benchmark_v2_commitment.json",
    "results/physical_jepa_v3_baselines.json": "docs/research/physical_jepa_v3_baselines.json",
    "results/physical_jepa_v3_evaluation.json": "docs/research/physical_jepa_v3_evaluation.json",
    "results/physical_jepa_v3_selection.json": "docs/research/physical_jepa_v3_selection.json",
    "results/physical_jepa_v4_evaluation.json": "docs/research/physical_jepa_v4_evaluation.json",
    "results/physical_jepa_v5_selection.json": "docs/research/physical_jepa_v5_selection.json",
    "results/physical_jepa_v5_selection_verification.json": "docs/research/physical_jepa_v5_selection_verification.json",
    "results/physical_jepa_v5_final_test.json": "docs/research/physical_jepa_v5_final_test.json",
    "results/physical_jepa_paper_results_v1.json": "docs/research/physical_jepa_paper_results_v1.json",
    "results/physical_jepa_paper_ablation_v1.csv": "docs/research/physical_jepa_paper_ablation_v1.csv",
    "results/physical_jepa_paper_review_result_v1.json": "docs/research/physical_jepa_paper_review_result_v1.json",
    "results/physical_jepa_paper_dynamics_calibration_result_v1.json": "docs/research/physical_jepa_paper_dynamics_calibration_result_v1.json",
    "results/physical_jepa_paper_dynamics_calibration_result_v2.json": "docs/research/physical_jepa_paper_dynamics_calibration_result_v2.json",
    "results/physical_jepa_blinded_benchmark_v1_selection.json": "docs/research/physical_jepa_blinded_benchmark_v1_selection.json",
    "results/physical_jepa_blinded_benchmark_v1_result.json": "docs/research/physical_jepa_blinded_benchmark_v1_result.json",
    "results/physical_jepa_blinded_benchmark_v1_verification.json": "docs/research/physical_jepa_blinded_benchmark_v1_verification.json",
    "results/physical_jepa_blinded_benchmark_v2_selection.json": "docs/research/physical_jepa_blinded_benchmark_v2_selection.json",
    "results/physical_jepa_blinded_benchmark_v2_result.json": "docs/research/physical_jepa_blinded_benchmark_v2_result.json",
    "results/physical_jepa_blinded_benchmark_v2_verification.json": "docs/research/physical_jepa_blinded_benchmark_v2_verification.json",
    "results/physical_jepa_pybullet_integration_v1.json": "docs/research/physical_jepa_pybullet_integration_v1.json",
    "results/physical_jepa_paper_freeze_v1_1.json": "docs/research/physical_jepa_paper_freeze_v1_1.json",
    "results/physical_world_model_evaluation.json": "docs/research/physical_world_model_evaluation.json",
    "models/ordinary_supervised_mlp.bin": "docs/research/artifacts/physical-jepa-paper/ordinary_supervised_mlp.bin",
    "models/v3_baseline.bin": "docs/research/artifacts/physical-jepa-v5/baseline_v3.bin",
    "models/failed_v4_candidate.bin": "target/physical_world_model/v4_candidate.bin",
    "models/v5_selected_candidate.bin": "docs/research/artifacts/physical-jepa-v5/selected_candidate.bin",
    "models/deployed_physical_world_model.bin": "userland/heliox-daemon/physical_world_model.bin",
    "figures/calibration_and_threshold_sensitivity.png": "docs/research/figures/physical_jepa_paper/calibration_and_threshold_sensitivity.png",
    "figures/matched_fpr_ablation.png": "docs/research/figures/physical_jepa_paper/matched_fpr_ablation.png",
    "scripts/evaluate_physical_jepa_paper.py": "scripts/evaluate_physical_jepa_paper.py",
    "scripts/evaluate_physical_jepa_paper_review.py": "scripts/evaluate_physical_jepa_paper_review.py",
    "scripts/evaluate_physical_jepa_paper_dynamics_calibration.py": "scripts/evaluate_physical_jepa_paper_dynamics_calibration.py",
    "scripts/evaluate_physical_jepa_robustness.py": "scripts/evaluate_physical_jepa_robustness.py",
    "scripts/evaluate_physical_jepa_v5_final.py": "scripts/evaluate_physical_jepa_v5_final.py",
    "scripts/physical_incident_scenarios.py": "scripts/physical_incident_scenarios.py",
    "scripts/physical_stress_scenarios.py": "scripts/physical_stress_scenarios.py",
    "scripts/run_physical_jepa_blinded_benchmark.py": "scripts/run_physical_jepa_blinded_benchmark.py",
    "scripts/run_physical_jepa_blinded_benchmark_v2.py": "scripts/run_physical_jepa_blinded_benchmark_v2.py",
    "scripts/run_physical_jepa_pybullet_integration.py": "scripts/run_physical_jepa_pybullet_integration.py",
    "scripts/select_physical_incident_jepa.py": "scripts/select_physical_incident_jepa.py",
    "scripts/select_physical_jepa_v5.py": "scripts/select_physical_jepa_v5.py",
    "scripts/train_physical_jepa.py": "scripts/train_physical_jepa.py",
    "scripts/train_physical_world_model.py": "scripts/train_physical_world_model.py",
    "scripts/verify_physical_jepa_blinded_benchmark.py": "scripts/verify_physical_jepa_blinded_benchmark.py",
    "scripts/verify_physical_jepa_blinded_benchmark_v2.py": "scripts/verify_physical_jepa_blinded_benchmark_v2.py",
    "scripts/verify_physical_jepa_paper.py": "scripts/verify_physical_jepa_paper.py",
    "scripts/verify_physical_jepa_v5_final.py": "scripts/verify_physical_jepa_v5_final.py",
    "scripts/verify_physical_jepa_v5_runtime.py": "scripts/verify_physical_jepa_v5_runtime.py",
    "scripts/verify_physical_jepa_v5_selection.py": "scripts/verify_physical_jepa_v5_selection.py",
    "tools/physical_sim_bridge/__init__.py": "tools/physical_sim_bridge/__init__.py",
    "tools/physical_sim_bridge/README.md": "tools/physical_sim_bridge/README.md",
    "tools/physical_sim_bridge/bridge.py": "tools/physical_sim_bridge/bridge.py",
    "tools/physical_sim_bridge/protocol.py": "tools/physical_sim_bridge/protocol.py",
    "tools/physical_sim_bridge/test_bridge.py": "tools/physical_sim_bridge/test_bridge.py",
    "requirements-research.txt": "requirements-research.txt",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_doi(value: str) -> str:
    doi = value.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):].strip()
            break
    if not DOI_PATTERN.fullmatch(doi):
        raise ValueError(f"invalid Zenodo DOI: {value!r}")
    return doi


def git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def deterministic_gzip(source: Path, destination: Path) -> None:
    with source.open("rb") as src, destination.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as zipped:
            shutil.copyfileobj(src, zipped, length=1024 * 1024)


def add_zip_member(archive: zipfile.ZipFile, source: Path, member: str) -> None:
    info = zipfile.ZipInfo(member, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def inspect_text_files(paths: Iterable[Path]) -> dict[str, Any]:
    secret_hits = {name: 0 for name in SECRET_PATTERNS}
    email_hits = 0
    scanned_files = 0
    scanned_bytes = 0
    for path in paths:
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8")
        scanned_files += 1
        scanned_bytes += len(text.encode("utf-8"))
        email_hits += len(EMAIL_PATTERN.findall(text))
        for name, pattern in SECRET_PATTERNS.items():
            secret_hits[name] += len(pattern.findall(text))
    actionable = {name: count for name, count in secret_hits.items() if count}
    if actionable:
        raise ValueError(f"credential-like material found; refusing to package: {actionable}")
    return {
        "status": "passed",
        "scope": "UTF-8 text members; binary models, PNG figures, and generated numeric gzip tables excluded",
        "scanned_files": scanned_files,
        "scanned_bytes": scanned_bytes,
        "credential_pattern_hits": secret_hits,
        "email_pattern_hits": email_hits,
        "review_status": "automated credential scan passed; manual release-file review remains required before publication",
    }


def write_partition(
    destination: Path,
    *,
    partition: str,
    catalog: Path,
    episodes_per_source: int,
    steps: int,
    seed: int,
) -> dict[str, Any]:
    rows, metadata = incidents.generate_partition(
        partition, episodes_per_source, steps, seed, catalog
    )
    with tempfile.TemporaryDirectory(prefix="physical-jepa-jsonl-") as temp:
        raw = Path(temp) / "transitions.jsonl"
        incidents.write_jsonl(raw, rows, metadata)
        raw_sha256 = sha256(raw)
        deterministic_gzip(raw, destination)
    return {
        "member": destination.name,
        "partition": partition,
        "catalog": catalog.relative_to(ROOT).as_posix(),
        "catalog_resolved_sha256": incidents.catalog_sha256(catalog),
        "episodes_per_source": episodes_per_source,
        "steps": steps,
        "seed": seed,
        "jsonl_sha256": raw_sha256,
        "gzip_sha256": sha256(destination),
        **incidents.summarize(rows, metadata),
    }


def benchmark_summary(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    family_counts = Counter(str(case["family"]) for case in payload["cases"])
    canonical = json.dumps(payload["cases"], sort_keys=True, separators=(",", ":")).encode()
    calculated = hashlib.sha256(canonical).hexdigest()
    if calculated != payload["cases_sha256"]:
        raise ValueError(f"sealed benchmark case digest mismatch: {path}")
    return {
        "episodes": payload["episodes"],
        "cases_sha256": payload["cases_sha256"],
        "family_counts": dict(sorted(family_counts.items())),
    }


def build_readme(dataset_doi: str, report_doi: str, manifest: dict[str, Any]) -> str:
    final = manifest["generated_partitions"]["final_test"]
    return f"""# FerrumOS Physical JEPA Safety-Runtime Evidence Dataset v{RELEASE_VERSION}

This archival package supports the technical report *Learned Caution,
Deterministic Authority*. It contains the exact simulator catalogs, generated
transition tables, sealed PyBullet cases, protocols, results, figures, models,
and reproduction sources bound by the report's frozen v1.1 evidence lineage.

The final table contains {final['transitions']:,} deterministic-simulator
transitions from {final['episodes']:,} episodes across
{len(final['source_family_episode_counts'])} held-out incident-informed source
families. It is simulation evidence only, not HIL or physical deployment.

## Files

- `{ARCHIVE_NAME}` - deterministic structured evidence payload
- `DATA_CARD.md` - provenance, schema, uses, limitations, and claim boundaries
- `LICENSE` - MIT License for the archival dataset
- `MANIFEST.json` - payload members, SHA-256 digests, counts, and DOI relations
- `SHA256SUMS` - SHA-256 checksums for every other release file
- `credential_scan_report.json` - automated credential-pattern scan evidence
- `verify_release.py` - dependency-free release verifier

## Verify

```text
python verify_release.py
```

## Citation and identifiers

Creator: Vyom Kulshrestha (Independent Researcher, India)

ORCID: https://orcid.org/0009-0009-1434-7148

Dataset DOI: https://doi.org/{dataset_doi}

Related technical report DOI: https://doi.org/{report_doi}

Repository: https://github.com/VyomKulshrestha/Ferrum-OS

The dataset record is related to the report with `isSupplementTo`; the report
uses the reciprocal `isSupplementedBy` relation. Verify the public downloads
against this manifest before claiming independent retrievability.
"""


def build_release(out_dir: Path, dataset_doi: str, report_doi: str) -> dict[str, Any]:
    dataset_doi = normalize_doi(dataset_doi)
    report_doi = normalize_doi(report_doi)
    required_sources = [DATA_CARD, DATASET_LICENSE, RELEASE_VERIFIER]
    required_sources.extend(ROOT / path for path in PAYLOAD_SOURCES.values())
    missing = [str(path) for path in required_sources if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"required release inputs are missing: {missing}")

    for member, expected in EXPECTED_MODEL_DIGESTS.items():
        actual = sha256(ROOT / PAYLOAD_SOURCES[member])
        if actual != expected:
            raise ValueError(f"frozen model digest mismatch for {member}: {actual}")

    out_dir.mkdir(parents=True, exist_ok=True)
    for child in out_dir.iterdir():
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)

    with tempfile.TemporaryDirectory(prefix="physical-jepa-release-") as temp:
        staging = Path(temp)
        staged: dict[str, Path] = {}
        for member, source_name in PAYLOAD_SOURCES.items():
            source = ROOT / source_name
            destination = staging / member
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            staged[member] = destination

        calibration_member = "data/physical_jepa_calibration_validation_transitions.jsonl.gz"
        calibration_path = staging / calibration_member
        calibration_path.parent.mkdir(parents=True, exist_ok=True)
        calibration = write_partition(
            calibration_path,
            partition="validation",
            catalog=ROOT / "docs/research/physical_incident_sources_v2.json",
            episodes_per_source=320,
            steps=8,
            seed=20260822,
        )
        calibration["member"] = calibration_member
        staged[calibration_member] = calibration_path

        final_member = "data/physical_jepa_v5_final_test_transitions.jsonl.gz"
        final_path = staging / final_member
        final = write_partition(
            final_path,
            partition="test",
            catalog=ROOT / "docs/research/physical_incident_v5_test_sources.json",
            episodes_per_source=320,
            steps=8,
            seed=20260829,
        )
        final["member"] = final_member
        staged[final_member] = final_path

        inspection = inspect_text_files(staged.values())
        payload_members = [
            {
                "path": member,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
                "source": PAYLOAD_SOURCES.get(member, "deterministically generated for archival release"),
            }
            for member, path in sorted(staged.items())
        ]

        archive_path = out_dir / ARCHIVE_NAME
        with zipfile.ZipFile(archive_path, "w", allowZip64=True) as archive:
            for member, path in sorted(staged.items()):
                add_zip_member(archive, path, member)

    benchmarks = {
        "sealed_v1": benchmark_summary(
            ROOT / "docs/research/physical_jepa_blinded_benchmark_v1_catalog.json"
        ),
        "sealed_v2": benchmark_summary(
            ROOT / "docs/research/physical_jepa_blinded_benchmark_v2_catalog.json"
        ),
    }
    manifest = {
        "schema_version": 1,
        "release_name": RELEASE_NAME,
        "release_version": RELEASE_VERSION,
        "provenance_commit": git_head(),
        "creator": {
            "name": "Vyom Kulshrestha",
            "affiliation": "Independent Researcher, India",
            "orcid": "0009-0009-1434-7148",
        },
        "publication": {
            "dataset_doi": dataset_doi,
            "dataset_doi_url": f"https://doi.org/{dataset_doi}",
            "report_doi": report_doi,
            "report_doi_url": f"https://doi.org/{report_doi}",
            "dataset_relation": "isSupplementTo",
            "report_reciprocal_relation": "isSupplementedBy",
            "status": "publication-ready; reserved DOIs bound to exact release",
        },
        "archive": {
            "file_name": ARCHIVE_NAME,
            "bytes": archive_path.stat().st_size,
            "sha256": sha256(archive_path),
            "format": "ZIP with sorted members, fixed 1980-01-01 timestamps, Unix 0644 modes, DEFLATE level 9",
        },
        "payload_members": payload_members,
        "generated_partitions": {
            "calibration_validation": calibration,
            "final_test": final,
        },
        "sealed_benchmarks": benchmarks,
        "frozen_models": EXPECTED_MODEL_DIGESTS,
        "content_inspection": inspection,
        "license": {"identifier": "MIT", "file": "LICENSE"},
        "release_files": sorted(RELEASE_FILES),
        "claim_boundary": [
            "Every main-model transition and danger label is produced by the deterministic Ferrum simulator.",
            "Public incident reports provide defensive initial-state priors only and are not Ferrum trajectories.",
            "PyBullet observations are locally executed software simulation with physical actuator authority disabled.",
            "The release is not HIL, not physical deployment, not certification, not a formal safety proof, not independent execution, and not independent assessment.",
        ],
    }

    data_card = DATA_CARD.read_text(encoding="utf-8").rstrip()
    data_card += f"""

## Archival identifiers

Dataset DOI: https://doi.org/{dataset_doi}

Related technical report DOI: https://doi.org/{report_doi}

The dataset record uses `isSupplementTo`; the report record uses the reciprocal
`isSupplementedBy` relation.
"""
    (out_dir / "DATA_CARD.md").write_text(data_card, encoding="utf-8", newline="\n")
    shutil.copy2(DATASET_LICENSE, out_dir / "LICENSE")
    shutil.copy2(RELEASE_VERIFIER, out_dir / "verify_release.py")
    write_json(out_dir / "credential_scan_report.json", inspection)
    (out_dir / "README.md").write_text(
        build_readme(dataset_doi, report_doi, manifest), encoding="utf-8", newline="\n"
    )
    write_json(out_dir / "MANIFEST.json", manifest)
    checksummed = sorted(RELEASE_FILES - {"SHA256SUMS"})
    (out_dir / "SHA256SUMS").write_text(
        "".join(f"{sha256(out_dir / name)}  {name}\n" for name in checksummed),
        encoding="ascii",
        newline="\n",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--dataset-doi", required=True, help="Reserved DOI for the dataset record")
    parser.add_argument("--report-doi", required=True, help="Reserved DOI for the technical-report record")
    args = parser.parse_args()
    manifest = build_release(args.out_dir.resolve(), args.dataset_doi, args.report_doi)
    print(json.dumps({
        "release_dir": str(args.out_dir.resolve()),
        "archive": manifest["archive"],
        "payload_file_count": len(manifest["payload_members"]),
        "calibration_transitions": manifest["generated_partitions"]["calibration_validation"]["transitions"],
        "final_transitions": manifest["generated_partitions"]["final_test"]["transitions"],
        "dataset_doi": manifest["publication"]["dataset_doi"],
        "report_doi": manifest["publication"]["report_doi"],
    }, indent=2))


if __name__ == "__main__":
    main()
