#!/usr/bin/env python3
"""Build the deterministic Zenodo package for the incident-dynamics and real-telemetry evidence.

Collects every committed incident-dynamics (v1-v4) and real-telemetry (rt1, rt2) protocol,
selection, result, verification, development ledger, retained final catalog and compact model
archive, plus the code needed to regenerate and audit them (the import closure inside scripts/).
Upstream HAI and SMD files are never packaged: the data manifest pins their URLs, commits and
hashes and fetch_real_telemetry.py retrieves and verifies them. Only Git-tracked files are used.
"""
from __future__ import annotations

import argparse
import ast
import gzip  # noqa: F401  (kept for parity with earlier release builders)
import hashlib
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "target" / "incident-dynamics-dataset-release-v1.0.0"
DATA_CARD = ROOT / "docs" / "research" / "INCIDENT_DYNAMICS_DATASET_CARD.md"
LICENSE = ROOT / "docs" / "research" / "PHYSICAL_JEPA_DATASET_LICENSE.md"
VERIFIER = ROOT / "scripts" / "verify_incident_dynamics_dataset_release.py"
RELEASE_VERSION = "1.0.0"
RELEASE_NAME = "ferrumos-incident-dynamics-real-telemetry-evidence-v1.0.0"
ARCHIVE_NAME = f"{RELEASE_NAME}.zip"
RELEASE_FILES = {ARCHIVE_NAME, "README.md", "DATA_CARD.md", "LICENSE", "MANIFEST.json", "SHA256SUMS",
                 "credential_scan_report.json", "verify_release.py"}
DOI_PATTERN = re.compile(r"^10\.5281/zenodo\.\d+$")
TEXT_SUFFIXES = {".csv", ".json", ".jsonl", ".md", ".py", ".txt"}
SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "github_token": re.compile(r"\bgh[opsu]_[A-Za-z0-9]{30,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "bearer_token": re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{24,}=*", re.IGNORECASE),
}
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
RECORD_PATTERNS = ("docs/research/incident_dynamics_", "docs/research/real_telemetry_")
ARTIFACT_PREFIXES = ("docs/research/artifacts/incident-dynamics-", "docs/research/artifacts/real-telemetry-")
SCRIPT_SEEDS = ("incident_dynamics", "run_incident_dynamics", "real_telemetry", "fetch_real_telemetry",
                "build_incident_dynamics_v3_tables", "verify_incident_dynamics", "test_incident_dynamics",
                "train_incident_dynamics", "fit_incident_dynamics", "evaluate_incident_dynamics",
                "probe_incident_dynamics", "package_incident_dynamics", "verify_incident_dynamics_dataset")
EXTRA = ["requirements-prediction-report-v1_2.txt", "docs/research/INCIDENT_DYNAMICS_DATASET_CARD.md",
         "docs/research/figures/cross_domain_world_model/incident_dynamics_v3_v4_results.png",
         "docs/research/figures/cross_domain_world_model/real_telemetry_results_v1_3.png"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tracked() -> list[str]:
    return subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()


def script_closure(files: list[str]) -> list[str]:
    available = {Path(f).stem: f for f in files if f.startswith("scripts/") and f.endswith(".py") and f.count("/") == 1}
    todo = [f for s, f in available.items() if s.startswith(SCRIPT_SEEDS)]
    seen = set()
    while todo:
        f = todo.pop()
        if f in seen:
            continue
        seen.add(f)
        tree = ast.parse((ROOT / f).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) and node.module else []
            for name in names:
                stem = name.split(".")[0]
                if stem in available and available[stem] not in seen:
                    todo.append(available[stem])
    return sorted(seen)


def payload_sources() -> dict[str, str]:
    files = tracked()
    sources = {}
    for f in files:
        if f.startswith(RECORD_PATTERNS) and f.endswith(".json"):
            sources[f"records/{Path(f).name}"] = f
        elif f.startswith(ARTIFACT_PREFIXES):
            sources["artifacts/" + f[len("docs/research/artifacts/"):]] = f
    for f in script_closure(files):
        sources[f] = f
    for f in EXTRA:
        if f in files:
            sources[f.replace("docs/research/figures/cross_domain_world_model/", "figures/").replace("docs/research/", "")] = f
    return dict(sorted(sources.items()))


def inspect(paths) -> dict:
    hits = {k: 0 for k in SECRET_PATTERNS}
    emails, files, size = 0, 0, 0
    for p in paths:
        if p.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        files += 1
        size += p.stat().st_size
        for k, pattern in SECRET_PATTERNS.items():
            hits[k] += len(pattern.findall(text))
        emails += len(EMAIL_PATTERN.findall(text))
    return {"scanned_text_files": files, "scanned_bytes": size, "secret_pattern_hits": hits, "email_like_strings": emails,
            "note": "Email-like strings are the author's public contact address and literature/vendor addresses in source records."}


def add_member(archive, source: Path, member: str):
    info = zipfile.ZipInfo(member, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def build(out: Path, dataset_doi: str, report_doi: str) -> dict:
    for doi in (dataset_doi, report_doi):
        if not DOI_PATTERN.fullmatch(doi):
            raise ValueError(f"invalid Zenodo DOI {doi}")
    sources = payload_sources()
    missing = [s for s in sources.values() if not (ROOT / s).is_file()]
    if missing:
        raise FileNotFoundError(missing)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    archive_path = out / ARCHIVE_NAME
    with zipfile.ZipFile(archive_path, "w", allowZip64=True) as archive:
        for member, source in sources.items():
            add_member(archive, ROOT / source, member)
    inspection = inspect(ROOT / s for s in sources.values())
    members = [{"path": m, "bytes": (ROOT / s).stat().st_size, "sha256": sha256(ROOT / s), "source": s} for m, s in sources.items()]
    upstream = json.loads((ROOT / "docs/research/real_telemetry_data_manifest_v1.json").read_text(encoding="utf-8"))
    manifest = {
        "schema_version": 1, "release_name": RELEASE_NAME, "release_version": RELEASE_VERSION,
        "provenance_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "creator": {"name": "Vyom Kulshrestha", "affiliation": "Independent Researcher, India", "orcid": "0009-0009-1434-7148"},
        "publication": {"dataset_doi": dataset_doi, "dataset_doi_url": f"https://doi.org/{dataset_doi}", "report_doi": report_doi,
                        "report_doi_url": f"https://doi.org/{report_doi}", "dataset_relation": "isSupplementTo",
                        "report_reciprocal_relation": "isSupplementedBy"},
        "archive": {"file_name": ARCHIVE_NAME, "bytes": archive_path.stat().st_size, "sha256": sha256(archive_path),
                    "format": "ZIP with sorted members, fixed 1980-01-01 timestamps, Unix 0644 modes, DEFLATE level 9"},
        "payload_members": members,
        "upstream_real_telemetry_not_redistributed": {
            k: {"repository": v["repository"], "commit": v["commit"], "license": v["license"], "files": len(v["files"])}
            for k, v in upstream["datasets"].items()},
        "content_inspection": inspection,
        "license": {"identifier": "MIT", "file": "LICENSE",
                    "scope": "Author-created code, records, generated simulator catalogs and model archives. Upstream HAI (CC BY-SA 4.0) and SMD (MIT) data are not included."},
        "release_files": sorted(RELEASE_FILES),
        "claim_boundary": [
            "Incident-dynamics catalogs are generated by researcher-designed simulators; public incident reports motivate mechanisms and supply no telemetry.",
            "Real-telemetry results come from public recorded datasets (HAI, SMD) evaluated locally; no runtime authority or actuator is involved.",
            "Nothing here is HIL, physical deployment, certification, a formal safety proof, independent execution or independent assessment.",
        ],
    }
    card = DATA_CARD.read_text(encoding="utf-8").rstrip() + f"""

## Archival identifiers

Dataset DOI: https://doi.org/{dataset_doi}

Related technical report DOI: https://doi.org/{report_doi}

The dataset record uses `isSupplementTo`; the report record uses the reciprocal `isSupplementedBy` relation.
"""
    (out / "DATA_CARD.md").write_text(card, encoding="utf-8", newline="\n")
    shutil.copy2(LICENSE, out / "LICENSE")
    shutil.copy2(VERIFIER, out / "verify_release.py")
    (out / "credential_scan_report.json").write_text(json.dumps(inspection, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "README.md").write_text(readme(dataset_doi, report_doi, manifest), encoding="utf-8", newline="\n")
    names = sorted(RELEASE_FILES - {"SHA256SUMS"})
    (out / "SHA256SUMS").write_text("".join(f"{sha256(out / n)}  {n}\n" for n in names), encoding="ascii", newline="\n")
    return manifest


def readme(dataset_doi, report_doi, manifest) -> str:
    return f"""# FerrumOS Incident-Dynamics and Real-Telemetry Evidence Dataset v{RELEASE_VERSION}

Archival package for the registered incident-dynamics studies (v1-v4) and the real-telemetry
attack and incident detection studies (rt1, rt2) reported in *Prediction Is Not Permission*,
Technical Report v1.3. It contains {len(manifest['payload_members'])} files: protocols, selections,
results, verifications, development ledgers, retained final catalogs, compact model archives,
incident and literature source catalogs, and the code that regenerates and audits them.

Upstream HAI and SMD recordings are not redistributed. `scripts/fetch_real_telemetry.py`
retrieves them at pinned commits and verifies every file against
`records/real_telemetry_data_manifest_v1.json`.

## Files

- `{ARCHIVE_NAME}` - structured evidence payload
- `DATA_CARD.md` - provenance, contents, uses, limitations and claim boundaries
- `LICENSE` - MIT License for the author-created materials
- `MANIFEST.json` - payload members, SHA-256 digests and DOI relations
- `SHA256SUMS` - checksums for every other release file
- `credential_scan_report.json` - automated credential-pattern scan
- `verify_release.py` - dependency-free release verifier

## Verify

```text
python verify_release.py
```

## Citation and identifiers

Creator: Vyom Kulshrestha (Independent Researcher, India), ORCID https://orcid.org/0009-0009-1434-7148

Dataset DOI: https://doi.org/{dataset_doi}

Related technical report DOI: https://doi.org/{report_doi}

Repository: https://github.com/VyomKulshrestha/Ferrum-OS
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--dataset-doi", required=True)
    parser.add_argument("--report-doi", required=True)
    parser.add_argument("--list", action="store_true", help="only list payload members")
    args = parser.parse_args()
    if args.list:
        for member, source in payload_sources().items():
            print(member, "<-", source)
        return
    manifest = build(args.out_dir.resolve(), args.dataset_doi, args.report_doi)
    print(json.dumps({"archive": manifest["archive"], "members": len(manifest["payload_members"]),
                      "secret_hits": manifest["content_inspection"]["secret_pattern_hits"]}, indent=2))


if __name__ == "__main__":
    main()
