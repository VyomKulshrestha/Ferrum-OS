#!/usr/bin/env python3
"""Verify the frozen v5 decoder protocol and unseen incident families."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "docs" / "research"
BASE = RESEARCH / "physical_incident_sources.json"
V2 = RESEARCH / "physical_incident_sources_v2.json"
V5_SOURCES = RESEARCH / "physical_incident_v5_test_sources.json"
PROTOCOL = RESEARCH / "physical_jepa_v5_protocol.json"
V4_RESULT = RESEARCH / "physical_jepa_v4_evaluation.json"
DEPLOYED = ROOT / "userland" / "heliox-daemon" / "physical_world_model.bin"


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    base = read(BASE)
    v2 = read(V2)
    v5 = read(V5_SOURCES)
    protocol = read(PROTOCOL)
    previous = [*base["sources"], *v2["additional_sources"]]
    sources = v5["sources"]
    previous_ids = {source["id"] for source in previous}
    previous_urls = {source["url"] for source in previous}
    previous_families = {source["source_family"] for source in previous}
    require(len(sources) == 8, "v5 must freeze exactly eight final families")
    require(len({source["id"] for source in sources}) == 8, "duplicate v5 source ID")
    require(len({source["url"] for source in sources}) == 8, "duplicate v5 URL")
    require(len({source["source_family"] for source in sources}) == 8, "duplicate v5 family")
    require(not (previous_ids & {source["id"] for source in sources}), "v5 ID was seen")
    require(not (previous_urls & {source["url"] for source in sources}), "v5 URL was seen")
    require(
        not (previous_families & {source["source_family"] for source in sources}),
        "v5 family was seen",
    )
    allowed = set(v5["allowed_hazard_tags"])
    for source in sources:
        parsed = urlparse(source["url"])
        require(parsed.scheme == "https" and parsed.netloc, "invalid source URL")
        require(source["training_partition"] == "test", "v5 source is not final-only")
        require(source["use_for_scenario_generation"], "v5 source is not generating")
        require(set(source["hazard_tags"]) <= allowed, "unknown v5 hazard tag")
        require(source["defensive_abstraction"] and source["limitations"], "missing boundary")
    require(protocol["registered_before_v5_test_generation"], "v5 was not preregistered")
    require(protocol["v5_test_open_count"] == 0, "v5 test was already opened")
    require(protocol["baseline_artifact_sha256"] == sha256(DEPLOYED), "baseline drift")
    require(protocol["v4_negative_report_sha256"] == sha256(V4_RESULT), "v4 result drift")
    require(protocol["final_test"]["catalog"] == V5_SOURCES.name, "v5 catalog drift")
    require(protocol["final_test"]["expected_transitions"] == 20480, "v5 size drift")
    require("unable to grant permits" in protocol["authority"], "authority weakened")
    print("PASS physical v5 protocol: eight new final-only incident families remain sealed")


if __name__ == "__main__":
    main()
