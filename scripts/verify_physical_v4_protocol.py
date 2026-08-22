#!/usr/bin/env python3
"""Validate the registered v4 incident corpus and HAI transfer protocol."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "docs" / "research"
BASE_CATALOG = RESEARCH / "physical_incident_sources.json"
V2_CATALOG = RESEARCH / "physical_incident_sources_v2.json"
HAI_PROTOCOL = RESEARCH / "physical_hai_transfer_protocol_v1.json"
V4_PROTOCOL = RESEARCH / "physical_jepa_v4_protocol.json"
V4_AMENDMENT = RESEARCH / "physical_jepa_v4_amendment1.json"
DEPLOYED_ARTIFACT = ROOT / "userland" / "heliox-daemon" / "physical_world_model.bin"
PARTITIONS = {"train", "validation", "test"}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    base = read_json(BASE_CATALOG)
    extension = read_json(V2_CATALOG)
    hai = read_json(HAI_PROTOCOL)
    v4 = read_json(V4_PROTOCOL)
    amendment = read_json(V4_AMENDMENT)
    require(extension["extends"] == BASE_CATALOG.name, "v2 must extend immutable v1")
    sources = [*base["sources"], *extension["additional_sources"]]

    ids = [source["id"] for source in sources]
    require(len(ids) == len(set(ids)), "source IDs must be unique")
    require(len(sources) >= 40, "v4 must retain at least 40 catalogued sources")
    require(len(extension["additional_sources"]) >= 24, "v4 expansion is incomplete")
    require(len(extension["search_scope"]["sectors"]) >= 8, "sector matrix is incomplete")
    require(extension["rejected_candidates"], "rejected-candidate log is required")

    allowed_tags = set(base["allowed_hazard_tags"])
    generating = [source for source in sources if source["use_for_scenario_generation"]]
    require(len(generating) >= 29, "too few scenario-generating event families")
    partition_counts = Counter(source["training_partition"] for source in generating)
    require(set(partition_counts) == PARTITIONS, "all three partitions are required")
    require(min(partition_counts.values()) >= 8, "each partition needs at least eight sources")
    families = {partition: set() for partition in PARTITIONS}
    for source in sources:
        parsed = urlparse(source["url"])
        require(parsed.scheme == "https" and parsed.netloc, f"invalid HTTPS URL: {source['id']}")
        require(set(source["hazard_tags"]) <= allowed_tags, f"unknown hazard tag: {source['id']}")
        require(source["defensive_abstraction"], f"missing abstraction: {source['id']}")
        require(source["limitations"], f"missing limitations: {source['id']}")
        if source["use_for_scenario_generation"]:
            partition = source["training_partition"]
            require(partition in PARTITIONS, f"invalid partition: {source['id']}")
            families[partition].add(source["source_family"])
        else:
            require(source["training_partition"] is None, f"non-generating source partitioned: {source['id']}")
    require(not (families["train"] & families["validation"]), "train/validation family leak")
    require(not (families["train"] & families["test"]), "train/test family leak")
    require(not (families["validation"] & families["test"]), "validation/test family leak")

    dataset = hai["dataset"]
    registered = [
        *dataset["train_files"],
        dataset["normal_calibration_file"],
        *dataset["validation_files"],
        *dataset["final_test_files"],
        dataset["technical_manual"],
    ]
    names = [item["name"] for item in registered]
    require(len(names) == len(set(names)), "HAI files must be unique")
    require(all(len(item["sha256"]) == 64 for item in registered), "HAI digest missing")
    require(hai["registered_before_final_test_download"], "HAI test was not pre-registered")
    require(hai["split_policy"]["test_open_count"] == 1, "HAI test may open only once")
    require(hai["projection"]["error_mask_indices"] == [6, 8, 9, 10, 11, 12, 13, 14], "projection mask drift")
    require(len(hai["projection"]["unavailable_dimensions"]) == 8, "unavailable dimensions must be explicit")
    require("label" in hai["projection"]["forbidden_inputs"], "attack labels must be forbidden inputs")

    artifact_hash = hashlib.sha256(DEPLOYED_ARTIFACT.read_bytes()).hexdigest()
    require(artifact_hash == v4["baseline_artifact_sha256"], "v4 baseline does not match runtime artifact")
    require(v4["incident_catalog"] == V2_CATALOG.name, "v4 catalog binding drift")
    require(v4["hil_transfer_protocol"] == HAI_PROTOCOL.name, "v4 HAI binding drift")
    require(v4["registered_before_test_open"], "v4 was not registered before test open")
    require(v4["simulator_candidate_selection"]["test_open_count"] == 1, "simulator test may open only once")
    require("Neither model may grant permits" in v4["integration_policy"]["authority"], "authority boundary weakened")
    require(
        amendment["parent_protocol"] == V4_PROTOCOL.name,
        "v4 execution amendment is not bound to the protocol",
    )
    require(
        amendment["registered_before_incident_v2_test_generation"]
        and amendment["incident_v2_test_open_count"] == 0,
        "v4 execution amendment was not registered before test generation",
    )
    require(
        amendment["incident_partition"]["catalog"] == V2_CATALOG.name
        and amendment["incident_partition"]["seed"] == v4["incident_dataset"]["seed"],
        "v4 incident execution settings drifted",
    )
    require(
        amendment["inherited_fixed_partitions"]["ood"]["protocol"] == "v2",
        "v4 must retain the registered fail-closed OOD protocol",
    )

    print(
        "PASS physical v4 protocol: "
        f"{len(sources)} sources, {len(generating)} generating families, "
        f"partitions={dict(sorted(partition_counts.items()))}, 8/16 HAI dimensions measured"
    )


if __name__ == "__main__":
    main()
