#!/usr/bin/env python3
"""Register the schema-only attribution repair and a new untouched final range."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V1_PROTOCOL = ROOT / "docs/research/physical_jepa_safety_gymnasium_attribution_protocol_v1.json"
FAILED_ATTEMPT = ROOT / "docs/research/physical_jepa_safety_gymnasium_attribution_failed_attempt_v1.json"
V2_PROTOCOL = ROOT / "docs/research/physical_jepa_safety_gymnasium_attribution_protocol_v2.json"
V1_DIR = ROOT / "docs/research/artifacts/physical-jepa-safety-attribution-v1"
V2_DIR = ROOT / "docs/research/artifacts/physical-jepa-safety-attribution-v2"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    if V2_PROTOCOL.exists() or V2_DIR.exists():
        raise FileExistsError("v2 recovery protocol or adapter directory already exists")
    protocol = load_json(V1_PROTOCOL)
    failure = load_json(FAILED_ATTEMPT)
    if failure["result_eligible"] or failure["promotion_eligible"]:
        raise ValueError("failed attempt must remain ineligible")
    V2_DIR.mkdir(parents=True)
    repaired_variants = []
    for registered in protocol["risk_source_variants"]:
        if registered["adapter_reused_without_refit"]:
            repaired_variants.append(copy.deepcopy(registered))
            continue
        source_path = ROOT / registered["path"]
        if sha256(source_path) != registered["sha256"]:
            raise ValueError(f"v1 adapter changed: {registered['id']}")
        adapter = load_json(source_path)
        selected = adapter["validation"]["selected"]
        adapter["validation"]["selected_threshold"] = selected["threshold"]
        target_path = V2_DIR / source_path.name
        target_path.write_text(
            json.dumps(adapter, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        reloaded = load_json(target_path)
        for key in ("feature_mean", "feature_scale", "weights", "bias"):
            if reloaded[key] != adapter[key]:
                raise AssertionError(f"numeric adapter field changed: {key}")
        repaired = copy.deepcopy(registered)
        repaired["path"] = str(target_path.relative_to(ROOT)).replace("\\", "/")
        repaired["sha256"] = sha256(target_path)
        repaired["schema_repair"] = (
            "copied validation.selected.threshold to the runner-required validation.selected_threshold field; "
            "all numeric adapter fields and the registered policy threshold are unchanged"
        )
        repaired_variants.append(repaired)

    protocol["schema"] = "physical-jepa-safety-gymnasium-risk-source-attribution-protocol-v2"
    protocol["protocol_id"] = "physical-jepa-safety-gymnasium-risk-source-attribution-v2"
    protocol["registered_date"] = "2026-09-05"
    protocol["amends"] = {
        "protocol": {"path": str(V1_PROTOCOL.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(V1_PROTOCOL), "registered_commit": "df58e72"},
        "failed_attempt": {"path": str(FAILED_ATTEMPT.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(FAILED_ATTEMPT)},
        "only_behavioral_change": "none",
        "only_schema_change": "add the frozen runner's required validation.selected_threshold alias to the three alternative adapter files",
        "old_final_range_status": "7000-7127 opened by the failed attempt and permanently excluded from attribution estimates",
    }
    protocol["risk_source_variants"] = repaired_variants
    protocol["prospective_boundary"]["final_seed_range_unopened_at_registration"] = {
        "start": 8000,
        "count": 128,
    }
    protocol["prospective_boundary"]["registration_search"] = (
        "repository text search found no 8000-8127 attribution result before v2 registration"
    )
    protocol["prospective_boundary"]["excluded_failed_range"] = {
        "start": 7000,
        "count": 128,
    }
    V2_PROTOCOL.write_text(
        json.dumps(protocol, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(V2_PROTOCOL.relative_to(ROOT).as_posix())
    for item in repaired_variants:
        print(f"{item['id']}: {item['sha256']}")


if __name__ == "__main__":
    main()
