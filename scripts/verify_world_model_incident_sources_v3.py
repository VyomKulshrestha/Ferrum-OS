#!/usr/bin/env python3
"""Verify the OS-JEPA v3 incident-source catalogs and frozen protocol."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "docs" / "research"
DEVELOPMENT = RESEARCH / "world_model_incident_sources_v3.json"
FINAL = RESEARCH / "world_model_incident_final_sources_v3.json"
PROTOCOL = RESEARCH / "world_model_jepa_v3_protocol.json"
APPLIANCE = ROOT / "appliance" / "world-model"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS\t{message}")


def verify_url(url: str) -> int:
    request = Request(url, headers={"User-Agent": "FerrumOS-research-verifier/1.0"})
    context = ssl.create_default_context()
    try:
        with urlopen(request, timeout=25, context=context) as response:
            return int(response.status)
    except HTTPError as error:
        return int(error.code)
    except URLError as error:
        raise AssertionError(f"source URL unavailable: {url}: {error.reason}") from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--online", action="store_true", help="also resolve every source URL")
    args = parser.parse_args()

    development = load(DEVELOPMENT)
    final = load(FINAL)
    protocol = load(PROTOCOL)
    dev_sources = development["sources"]
    final_sources = final["sources"]
    all_sources = [*dev_sources, *final_sources]

    require(development["schema_version"] == 1, "development source schema is supported")
    require(final["schema_version"] == 1, "final source schema is supported")
    require(len(dev_sources) >= 15, "development catalog contains at least fifteen sources")
    require(len(final_sources) == 4, "final catalog contains exactly four held-out sources")
    require(len({item["id"] for item in all_sources}) == len(all_sources), "source IDs are unique")
    require(len({item["url"] for item in all_sources}) == len(all_sources), "source URLs are unique")
    require(
        all(urlparse(item["url"]).scheme == "https" and urlparse(item["url"]).netloc for item in all_sources),
        "every source uses an absolute HTTPS URL",
    )

    generated = [item for item in dev_sources if item["use_for_scenario_generation"]]
    counts = Counter(item["training_partition"] for item in generated)
    require(counts == {"train": 6, "validation": 4}, "development partitions are frozen at six train and four validation sources")
    require(
        all(item["training_partition"] is None for item in dev_sources if not item["use_for_scenario_generation"]),
        "corroborating sources cannot enter scenario generation",
    )
    require(
        not ({item["source_family"] for item in generated} & {item["source_family"] for item in final_sources}),
        "final source families are held out from development",
    )
    require(
        all(item["scenario_profile"] in development["allowed_profiles"] for item in generated),
        "development scenarios use only registered defensive profiles",
    )
    require(
        all(item["scenario_profile"] in development["allowed_profiles"] for item in final_sources),
        "final scenarios use only registered defensive profiles",
    )
    require(
        all(item.get("verified_fact") and item.get("defensive_abstraction") and item.get("limitations") for item in all_sources),
        "every source records fact, defensive abstraction, and limitation",
    )
    require(
        {"peer_reviewed_research", "government_incident_advisory", "security_standard"}
        <= {item["source_kind"] for item in dev_sources},
        "papers, government guidance, and a standard are represented",
    )

    require(protocol["registered_before_candidate_selection"], "protocol predates candidate selection")
    require(protocol["registered_before_final_scenario_generation"], "protocol predates final scenario generation")
    require(protocol["final_scenario_open_count"] == 0, "final scenarios have not been opened")
    require(protocol["source_catalogs"]["development"]["sha256"] == sha256(DEVELOPMENT), "development catalog digest is frozen")
    require(protocol["source_catalogs"]["final"]["sha256"] == sha256(FINAL), "final catalog digest is frozen")
    require(protocol["frozen_lineage"]["encoder_sha256"] == sha256(APPLIANCE / "model_encoder.bin"), "deployed encoder matches protocol")
    require(protocol["frozen_lineage"]["runtime_v2_transition_sha256"] == sha256(APPLIANCE / "model_learned.bin"), "runtime-v2 transition matches protocol")
    require(protocol["frozen_lineage"]["runtime_v2_manifest_sha256"] == sha256(APPLIANCE / "manifest.json"), "runtime-v2 manifest matches protocol")
    require("cannot grant capabilities" in protocol["authority"], "learned authority remains subordinate")

    if args.online:
        with ThreadPoolExecutor(max_workers=8) as pool:
            values = list(pool.map(lambda item: verify_url(item["url"]), all_sources))
        statuses = {item["id"]: status for item, status in zip(all_sources, values)}
        require(all(200 <= status < 400 or status in {403, 429} for status in statuses.values()), "all source URLs resolve or explicitly rate-limit automated access")
        print(json.dumps({"online_status": statuses}, indent=2))

    print("23/23 OS-JEPA v3 source and protocol checks passed")


if __name__ == "__main__":
    main()
