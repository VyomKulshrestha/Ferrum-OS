#!/usr/bin/env python3
"""Build a deterministic, auditable FerrumOS world-model dataset release.

The release directory is intentionally generated outside Git.  It contains the
exact training JSONL as a reproducible gzip stream, a machine-readable manifest,
the data card, the explicit dataset licence, and a SHA256SUMS file suitable for
a GitHub or DOI-bearing archive release.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Iterable

import numpy as np

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

SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "github_token": re.compile(r"\bgh[opsu]_[A-Za-z0-9]{30,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "bearer_token": re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{24,}=*", re.IGNORECASE),
}
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


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


def build_release(dataset: Path, out_dir: Path) -> dict:
    if not dataset.is_file():
        raise FileNotFoundError(dataset)
    for required in (DATA_CARD, DATASET_LICENSE):
        if not required.is_file():
            raise FileNotFoundError(required)

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
    archive = out_dir / "ferrumos-world-model-dataset-v1.jsonl.gz"
    deterministic_gzip(dataset, archive)
    shutil.copy2(DATA_CARD, out_dir / DATA_CARD.name)
    shutil.copy2(DATASET_LICENSE, out_dir / DATASET_LICENSE.name)

    manifest = {
        "schema_version": 1,
        "release_name": "ferrumos-world-model-dataset-v1",
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
            "episode_overlap": overlap,
        },
        "content_inspection": inspection,
        "licence": {
            "identifier": "MIT",
            "file": DATASET_LICENSE.name,
        },
        "publication": {
            "doi": None,
            "status": "release package ready; DOI must be filled only after external archival",
        },
    }
    manifest_path = out_dir / "dataset_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    checksummed = [archive, out_dir / DATA_CARD.name, out_dir / DATASET_LICENSE.name, manifest_path]
    sums = "".join(f"{sha256(path)}  {path.name}\n" for path in sorted(checksummed))
    (out_dir / "SHA256SUMS.txt").write_text(sums, encoding="ascii")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    manifest = build_release(args.dataset.resolve(), args.out_dir.resolve())
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
