#!/usr/bin/env python3
"""Verify the provenance and defensive boundaries of the physical incident corpus."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "docs" / "research" / "physical_incident_sources.json"
PARTITIONS = {"train", "validation", "test"}
REQUIRED_KINDS = {
    "government_incident_report",
    "peer_reviewed_research",
    "company_postmortem_blog",
    "vendor_research_blog",
    "security_standard",
}
FORBIDDEN_FIELDS = {
    "credentials",
    "exploit_steps",
    "malware_payload",
    "packet_payload",
    "ports",
    "reproduction_steps",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL  {message}")
    print(f"PASS  {message}")


def main() -> None:
    document = json.loads(CATALOG.read_text(encoding="utf-8"))
    sources = document["sources"]
    allowed_tags = set(document["allowed_hazard_tags"])

    require(document["schema_version"] == 1, "incident catalog schema is supported")
    require(len(sources) >= 15, "catalog contains a broad authoritative incident corpus")
    require(len(document["claim_boundary"]) >= 4, "claim boundary is explicit")

    ids = [source["id"] for source in sources]
    urls = [source["url"] for source in sources]
    require(len(ids) == len(set(ids)), "source identifiers are unique")
    require(len(urls) == len(set(urls)), "source URLs are unique")
    require(
        all(urlparse(url).scheme == "https" and urlparse(url).netloc for url in urls),
        "all sources use absolute HTTPS URLs",
    )

    kinds = Counter(source["source_kind"] for source in sources)
    require(REQUIRED_KINDS <= set(kinds), "government, paper, company, vendor-blog, and standard sources are represented")
    require(
        all(set(source["hazard_tags"]) <= allowed_tags for source in sources),
        "every defensive abstraction uses registered hazard tags",
    )
    require(
        all(not (set(source) & FORBIDDEN_FIELDS) for source in sources),
        "catalog excludes operational intrusion fields",
    )

    generated = [source for source in sources if source["use_for_scenario_generation"]]
    require(len(generated) >= 10, "at least ten independent sources drive scenario generation")
    require(
        all(source["training_partition"] in PARTITIONS for source in generated),
        "every generated source has a registered partition",
    )
    require(
        all(
            source["training_partition"] is None
            for source in sources
            if not source["use_for_scenario_generation"]
        ),
        "corroborating-only sources cannot leak into training",
    )

    family_partitions: dict[str, set[str]] = defaultdict(set)
    for source in generated:
        family_partitions[source["source_family"]].add(source["training_partition"])
    require(
        all(len(partitions) == 1 for partitions in family_partitions.values()),
        "incident families are disjoint across train, validation, and test",
    )
    partition_counts = Counter(source["training_partition"] for source in generated)
    require(
        all(partition_counts[partition] >= 3 for partition in PARTITIONS),
        "each incident partition contains at least three source families",
    )
    require(
        all(source["defensive_abstraction"] and source["limitations"] for source in sources),
        "every source records abstraction and limitations",
    )
    print("\nPhysical incident-source verification passed.")


if __name__ == "__main__":
    main()
