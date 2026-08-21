#!/usr/bin/env python3
"""Verify deterministic, disjoint incident-derived physical scenario data."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import numpy as np

import physical_incident_scenarios as incidents
import train_physical_world_model as simulator


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL  {message}")
    print(f"PASS  {message}")


def rows_digest(rows, metadata) -> str:
    with tempfile.TemporaryDirectory(prefix="ferrum-incident-data-") as directory:
        path = Path(directory) / "rows.jsonl"
        incidents.write_jsonl(path, rows, metadata)
        return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    generated = {}
    for partition in ("train", "validation", "test"):
        first = incidents.generate_partition(partition, 24, 6, 42)
        second = incidents.generate_partition(partition, 24, 6, 42)
        require(
            rows_digest(*first) == rows_digest(*second),
            f"{partition} partition reproduces byte-for-byte",
        )
        generated[partition] = first

    episode_sets = {
        partition: set(metadata) for partition, (_, metadata) in generated.items()
    }
    require(
        episode_sets["train"].isdisjoint(episode_sets["validation"])
        and episode_sets["train"].isdisjoint(episode_sets["test"])
        and episode_sets["validation"].isdisjoint(episode_sets["test"]),
        "episode identifiers are disjoint across partitions",
    )
    family_sets = {
        partition: {item["source_family"] for item in metadata.values()}
        for partition, (_, metadata) in generated.items()
    }
    require(
        family_sets["train"].isdisjoint(family_sets["validation"])
        and family_sets["train"].isdisjoint(family_sets["test"])
        and family_sets["validation"].isdisjoint(family_sets["test"]),
        "source families are disjoint across partitions",
    )

    for partition, (rows, metadata) in generated.items():
        summary = incidents.summarize(rows, metadata)
        actions = {row[3] for row in rows}
        require(
            len(rows) == len(metadata) * 6,
            f"{partition} contains six transitions per episode",
        )
        require(
            actions == set(range(simulator.ACTION_COUNT)),
            f"{partition} covers every physical action",
        )
        require(
            summary["dangerous_transitions"] > 0,
            f"{partition} retains dangerous rare-state transitions",
        )
        require(
            all(
                row[2].shape == (simulator.STATE_SIZE,)
                and row[5].shape == (simulator.STATE_SIZE,)
                and np.isfinite(row[2]).all()
                and np.isfinite(row[5]).all()
                for row in rows
            ),
            f"{partition} states match the finite runtime schema",
        )
        require(
            all(
                metadata[row[0]]["partition"] == partition
                and metadata[row[0]]["source_id"]
                and metadata[row[0]]["hazard_tags"]
                for row in rows
            ),
            f"{partition} rows retain provenance",
        )

    changed_seed = incidents.generate_partition("train", 24, 6, 43)
    require(
        rows_digest(*generated["train"]) != rows_digest(*changed_seed),
        "dataset seed changes the generated trajectories",
    )
    print("\nPhysical incident-dataset verification passed.")


if __name__ == "__main__":
    main()
