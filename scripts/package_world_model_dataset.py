#!/usr/bin/env python3
"""Build the deterministic ten-file FerrumOS dataset archival package."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Iterable

from train_world_model import (
    ACTION_FEATURE_SIZE,
    EMBEDDING_SIZE,
    TOOL_NAMES,
    dataset_fingerprint,
    load_dataset,
    split_indices,
    transition_eligible,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "target" / "world_model_dataset_release_repaired2.jsonl"
DEFAULT_OUT = ROOT / "target" / "world-model-dataset-release"
DATA_CARD = ROOT / "docs" / "research" / "WORLD_MODEL_DATASET_CARD.md"
DATASET_LICENSE = ROOT / "docs" / "research" / "WORLD_MODEL_DATASET_LICENSE.md"
RELEASE_VERIFIER = ROOT / "scripts" / "verify_world_model_dataset_release.py"
RELEASE_VERSION = "1.0.0"
DATASET_DOI = "10.5281/zenodo.21829193"
ARCHIVE_NAME = "ferrumos-world-model-dataset-v1.0.0.jsonl.gz"
RELEASE_FILES = (
    ARCHIVE_NAME,
    "README.md",
    "DATA_CARD.md",
    "LICENSE",
    "MANIFEST.json",
    "SHA256SUMS",
    "schema.json",
    "episode_split_audit.json",
    "credential_scan_report.json",
    "verify_release.py",
)
LEGACY_RELEASE_FILES = (
    "ferrumos-world-model-dataset-v1.jsonl.gz",
    "WORLD_MODEL_DATASET_CARD.md",
    "WORLD_MODEL_DATASET_LICENSE.md",
    "dataset_manifest.json",
    "SHA256SUMS.txt",
)

SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "github_token": re.compile(r"\bgh[opsu]_[A-Za-z0-9]{30,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "bearer_token": re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{24,}=*", re.IGNORECASE),
}
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
DOI_PATTERN = re.compile(r"^10\.5281/zenodo\.\d+$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from iter_strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from iter_strings(nested)


def inspect_rows(rows: list[dict]) -> dict:
    secret_hits = {name: 0 for name in SECRET_PATTERNS}
    email_hits = 0
    fields: set[str] = set()
    sources: dict[str, int] = {}
    providers: dict[str, int] = {}
    action_counts = {name: 0 for name in TOOL_NAMES}
    max_prompt_bytes = 0
    max_response_bytes = 0

    for row in rows:
        fields.update(row)
        source = str(row.get("source", "unknown"))
        sources[source] = sources.get(source, 0) + 1
        if row.get("provider"):
            provider = str(row["provider"])
            providers[provider] = providers.get(provider, 0) + 1
        action_id = int(row.get("action", -1))
        if 0 <= action_id < len(TOOL_NAMES):
            action_counts[TOOL_NAMES[action_id]] += 1
        max_prompt_bytes = max(max_prompt_bytes, len(str(row.get("prompt", "")).encode("utf-8")))
        max_response_bytes = max(max_response_bytes, len(str(row.get("model_response", "")).encode("utf-8")))
        for text in iter_strings(row):
            email_hits += len(EMAIL_PATTERN.findall(text))
            for name, pattern in SECRET_PATTERNS.items():
                secret_hits[name] += len(pattern.findall(text))

    actionable_hits = {name: count for name, count in secret_hits.items() if count}
    if actionable_hits:
        raise ValueError(f"credential-like material found; refusing to package: {actionable_hits}")
    return {
        "fields": sorted(fields),
        "sources": dict(sorted(sources.items())),
        "providers": dict(sorted(providers.items())),
        "action_counts": action_counts,
        "credential_pattern_hits": secret_hits,
        "email_pattern_hits": email_hits,
        "max_prompt_bytes": max_prompt_bytes,
        "max_model_response_bytes": max_response_bytes,
        "review_status": "automated credential scan passed; manual sampling is still required before publication",
    }


def git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def deterministic_gzip(source: Path, destination: Path) -> None:
    with source.open("rb") as src, destination.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as zipped:
            shutil.copyfileobj(src, zipped, length=1024 * 1024)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def normalize_doi(value: str) -> str:
    doi = value.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):].strip()
            break
    if not DOI_PATTERN.fullmatch(doi):
        raise ValueError(f"invalid Zenodo DOI: {value!r}")
    return doi


def build_schema(fields: list[str]) -> dict[str, Any]:
    number_array = {"type": "array", "items": {"type": "number"}}
    properties: dict[str, Any] = {
        "source": {"type": "string"},
        "episode_id": {"type": "string"},
        "step": {"type": "integer", "minimum": 0},
        "ram_mb": {"type": "integer", "minimum": 0},
        "schema_version": {"type": "integer", "minimum": 1},
        "tick": {"type": "integer", "minimum": 0},
        "action": {"type": "integer", "minimum": 0, "maximum": len(TOOL_NAMES) - 1},
        "reward": {"type": "number"},
        "before": {**number_array, "minItems": EMBEDDING_SIZE, "maxItems": EMBEDDING_SIZE},
        "after": {**number_array, "minItems": EMBEDDING_SIZE, "maxItems": EMBEDDING_SIZE},
        "executed": {"type": "boolean"},
        "action_features": {
            **number_array,
            "minItems": ACTION_FEATURE_SIZE,
            "maxItems": ACTION_FEATURE_SIZE,
        },
        "observation_schema": {"type": "string"},
        "masked_features": {"type": "array", "items": {"type": "integer", "minimum": 0}},
        "actual_tool": {"type": "string"},
        "expected_tool": {"type": "string"},
        "expected_tool_match": {"type": "boolean"},
        "model_response": {"type": "string"},
        "prompt": {"type": "string"},
        "provider": {"type": "string"},
        "provider_model": {"type": ["string", "null"]},
        "risk": {"type": "number"},
        "success": {"type": "boolean"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "transition_in_step": {"type": "integer", "minimum": 0},
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:ferrumos:world-model-dataset:transition:v1.0.0",
        "title": "FerrumOS World-Model Safety Dataset transition",
        "description": "Schema for one JSONL transition record in release v1.0.0.",
        "type": "object",
        "required": [
            "source",
            "episode_id",
            "step",
            "ram_mb",
            "schema_version",
            "tick",
            "action",
            "reward",
            "before",
            "after",
            "executed",
            "action_features",
            "observation_schema",
            "masked_features",
        ],
        "properties": {field: properties[field] for field in fields},
        "additionalProperties": False,
        "x-ferrumos": {
            "release_version": RELEASE_VERSION,
            "state_embedding_size": EMBEDDING_SIZE,
            "action_feature_size": ACTION_FEATURE_SIZE,
            "canonical_actions": TOOL_NAMES,
        },
    }


def build_readme(manifest: dict[str, Any]) -> str:
    split = manifest["split"]
    doi = manifest["publication"]["doi"]
    return f"""# FerrumOS World-Model Safety Dataset v{RELEASE_VERSION}

This archival package contains the deterministic FerrumOS OS-level action-transition
dataset used by the accompanying world-model safety study. It contains
{manifest['source']['rows']:,} accounted transitions from {manifest['source']['episodes']:,}
episodes; {manifest['source']['eligible_rows']:,} executed, transition-eligible rows are
partitioned episode-disjointly into {split['train_rows']:,}/{split['validation_rows']:,}/
{split['test_rows']:,} train/validation/test rows.

## Contents

- `{ARCHIVE_NAME}` - deterministic gzip-compressed JSONL corpus
- `DATA_CARD.md` - provenance, uses, limitations, and privacy notes
- `LICENSE` - MIT licence for this dataset release
- `MANIFEST.json` - hashes, counts, schema constants, and release provenance
- `SHA256SUMS` - SHA-256 checksums for every other file in this package
- `schema.json` - JSON Schema for individual transition records
- `episode_split_audit.json` - episode-disjoint split evidence
- `credential_scan_report.json` - automated secret and identifier scan evidence
- `verify_release.py` - dependency-free package integrity verifier

## Verify

```text
python verify_release.py
```

The verifier checks the exact ten-file contract, all declared checksums, lossless
decompression, row dimensions and counts, split isolation, credential-scan status,
and the MIT licence declaration.

## Citation and DOI

Creator: Vyom Kulshrestha (Independent Researcher, India)

Repository: https://github.com/VyomKulshrestha/Ferrum-OS

Dataset DOI: https://doi.org/{doi}

This DOI is assigned to this exact archive. Zenodo manages DOI registration when the
record is published. Verify that the landing page resolves and that downloaded file
checksums match this package before describing the release as independently retrievable.
"""


def build_release(dataset: Path, out_dir: Path, doi: str = DATASET_DOI) -> dict:
    if not dataset.is_file():
        raise FileNotFoundError(dataset)
    for required in (DATA_CARD, DATASET_LICENSE, RELEASE_VERIFIER):
        if not required.is_file():
            raise FileNotFoundError(required)

    doi = normalize_doi(doi)
    rows = load_dataset(dataset)
    eligible = [row for row in rows if transition_eligible(row)]
    train, validation, test, split_mode = split_indices(eligible, 0.15, 0.15, 42)
    if split_mode != "episode":
        raise ValueError("public release requires an episode-disjoint split")
    episodes = {str(row.get("episode_id")) for row in rows}
    eligible_episodes = {str(row.get("episode_id")) for row in eligible}
    train_episodes = {str(eligible[int(index)].get("episode_id")) for index in train}
    validation_episodes = {str(eligible[int(index)].get("episode_id")) for index in validation}
    test_episodes = {str(eligible[int(index)].get("episode_id")) for index in test}
    overlap = {
        "train_validation": len(train_episodes & validation_episodes),
        "train_test": len(train_episodes & test_episodes),
        "validation_test": len(validation_episodes & test_episodes),
    }
    if any(overlap.values()):
        raise ValueError(f"episode leakage detected: {overlap}")

    inspection = inspect_rows(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    for legacy_name in LEGACY_RELEASE_FILES:
        legacy_path = out_dir / legacy_name
        if legacy_path.is_file():
            legacy_path.unlink()

    archive = out_dir / ARCHIVE_NAME
    deterministic_gzip(dataset, archive)
    shutil.copy2(DATA_CARD, out_dir / "DATA_CARD.md")
    shutil.copy2(DATASET_LICENSE, out_dir / "LICENSE")
    shutil.copy2(RELEASE_VERIFIER, out_dir / "verify_release.py")

    manifest = {
        "schema_version": 1,
        "release_name": "ferrumos-world-model-dataset-v1.0.0",
        "release_version": RELEASE_VERSION,
        "provenance_commit": git_head(),
        "source": {
            "file_name": dataset.name,
            "bytes": dataset.stat().st_size,
            "sha256": sha256(dataset),
            "rows": len(rows),
            "episodes": len(episodes),
            "eligible_rows": len(eligible),
            "eligible_episodes": len(eligible_episodes),
            "identity_fingerprint": dataset_fingerprint(eligible),
        },
        "archive": {
            "file_name": archive.name,
            "bytes": archive.stat().st_size,
            "sha256": sha256(archive),
            "compression": "gzip level 9, empty original filename, mtime 0",
        },
        "schema": {
            "state_embedding_size": EMBEDDING_SIZE,
            "action_feature_size": ACTION_FEATURE_SIZE,
            "canonical_actions": len(TOOL_NAMES),
            "tool_names": TOOL_NAMES,
            "fields": inspection["fields"],
        },
        "split": {
            "mode": split_mode,
            "seed": 42,
            "train_rows": len(train),
            "validation_rows": len(validation),
            "test_rows": len(test),
            "accounted_rows": len(rows),
            "eligible_rows": len(eligible),
            "excluded_rows": len(rows) - len(eligible),
            "accounted_episodes": len(episodes),
            "eligible_episodes": len(eligible_episodes),
            "train_episodes": len(train_episodes),
            "validation_episodes": len(validation_episodes),
            "test_episodes": len(test_episodes),
            "episode_overlap": overlap,
        },
        "content_inspection": inspection,
        "licence": {
            "identifier": "MIT",
            "file": "LICENSE",
        },
        "artifacts": list(RELEASE_FILES),
        "publication": {
            "doi": doi,
            "doi_url": f"https://doi.org/{doi}",
            "status": "publication-ready; DOI assigned to exact release",
            "registration_policy": "Zenodo manages DOI registration when the record is published",
        },
    }
    write_json(out_dir / "schema.json", build_schema(inspection["fields"]))
    write_json(
        out_dir / "episode_split_audit.json",
        {
            "release_version": RELEASE_VERSION,
            "status": "passed",
            **manifest["split"],
        },
    )
    write_json(
        out_dir / "credential_scan_report.json",
        {
            "release_version": RELEASE_VERSION,
            "status": "passed",
            "scope": {"rows": len(rows), "episodes": len(episodes)},
            **inspection,
        },
    )
    (out_dir / "README.md").write_text(build_readme(manifest), encoding="utf-8")
    manifest_path = out_dir / "MANIFEST.json"
    write_json(manifest_path, manifest)

    checksummed = [out_dir / name for name in RELEASE_FILES if name != "SHA256SUMS"]
    sums = "".join(f"{sha256(path)}  {path.name}\n" for path in sorted(checksummed))
    (out_dir / "SHA256SUMS").write_text(sums, encoding="ascii")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--doi",
        default=DATASET_DOI,
        help="Reserved Zenodo DOI for this exact release (default: %(default)s)",
    )
    args = parser.parse_args()
    manifest = build_release(args.dataset.resolve(), args.out_dir.resolve(), args.doi)
    print(json.dumps({
        "release_dir": str(args.out_dir.resolve()),
        "source_sha256": manifest["source"]["sha256"],
        "archive_sha256": manifest["archive"]["sha256"],
        "rows": manifest["source"]["rows"],
        "episodes": manifest["source"]["episodes"],
        "doi": manifest["publication"]["doi"],
    }, indent=2))


if __name__ == "__main__":
    main()
