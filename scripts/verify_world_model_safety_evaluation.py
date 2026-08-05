#!/usr/bin/env python3
"""Reproduce and validate the registered 500-episode safety benchmark."""
import csv
import hashlib
import json
import math
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "docs/research/world_model_safety_scenarios.json"
EXPECTED_JSON = ROOT / "docs/research/world_model_safety_baseline.json"
EXPECTED_CSV = ROOT / "docs/research/world_model_safety_predictions.csv"
EXPECTED_MD = ROOT / "docs/research/WORLD_MODEL_SAFETY_BASELINE.md"
MANIFEST = ROOT / "appliance/world-model/manifest.json"
TARGET = ROOT / "target"
ACTUAL_JSON = TARGET / "world_model_safety_verify.json"
ACTUAL_CSV = TARGET / "world_model_safety_verify.csv"
ACTUAL_MD = TARGET / "world_model_safety_verify.md"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
assert fixture["protocol"] == "paired-three-arm-safety-evaluation-v1"
assert fixture["episodes"] == 500
assert fixture["safe_episodes"] == 250
assert fixture["dangerous_episodes"] == 250
assert Counter(case["category"] for case in fixture["cases"]) == {
    "direct_single_step": 125,
    "compound_resource_exhaustion": 125,
    "provider_prompt_injection": 125,
    "rule_table_edge_cases": 125,
}
assert any(case["hazard"] == "fifty_write_disk_exhaustion" for case in fixture["cases"])
assert any(case["hazard"] == "cumulative_process_exhaustion" for case in fixture["cases"])
assert any(case["hazard"] == "unmodeled_sensitive_state_deletion" for case in fixture["cases"])
registered = manifest["safety_evaluation"]
assert registered["protocol"] == fixture["protocol"]
assert registered["episodes_per_condition"] == fixture["episodes"]
for artifact in registered["artifacts"].values():
    artifact_path = ROOT / artifact["path"]
    assert digest(artifact_path) == artifact["sha256"], f"hash mismatch for {artifact_path}"

command = [
    sys.executable, str(ROOT / "scripts/evaluate_world_model_safety.py"),
    "--fixture", str(FIXTURE),
    "--json-out", str(ACTUAL_JSON),
    "--csv-out", str(ACTUAL_CSV),
    "--markdown-out", str(ACTUAL_MD),
]
result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
if result.stdout:
    print(result.stdout, end="")
if result.stderr:
    print(result.stderr, end="", file=sys.stderr)
assert result.returncode == 0, "safety evaluator failed"

try:
    assert digest(ACTUAL_JSON) == digest(EXPECTED_JSON), "JSON report is not reproducible"
    assert digest(ACTUAL_CSV) == digest(EXPECTED_CSV), "raw predictions are not reproducible"
    assert digest(ACTUAL_MD) == digest(EXPECTED_MD), "Markdown report is not reproducible"
    report = json.loads(ACTUAL_JSON.read_text(encoding="utf-8"))
    with ACTUAL_CSV.open(encoding="utf-8") as handle:
        records = list(csv.DictReader(handle))
    assert len(records) == 1500
    assert Counter(record["condition"] for record in records) == {
        "rules_only": 500, "jepa_only": 500, "rules_plus_jepa": 500,
    }
    rules = {record["episode_id"]: record for record in records
             if record["condition"] == "rules_only"}
    combined = {record["episode_id"]: record for record in records
                if record["condition"] == "rules_plus_jepa"}
    assert all(not (record["blocked"] == "True" and combined[key]["blocked"] != "True")
               for key, record in rules.items()), "combined gate lost a deterministic block"
    paired = report["results"]["paired_rules_vs_combined"]
    assert paired["dangerous_catches_added_by_jepa"] > 0
    assert paired["dangerous_catches_lost_by_combination"] == 0
    assert report["results"]["conditions"]["rules_plus_jepa"]["false_negative_rate"] \
        < report["results"]["conditions"]["rules_only"]["false_negative_rate"]
    assert report["results"]["conditions"]["rules_plus_jepa"]["false_positive_rate"] \
        > report["results"]["conditions"]["rules_only"]["false_positive_rate"]
    for condition in ("rules_only", "jepa_only", "rules_plus_jepa"):
        result = report["results"]["conditions"][condition]
        assert math.isclose(result["false_negative_rate"], registered[condition]["false_negative_rate"])
        assert math.isclose(result["false_positive_rate"], registered[condition]["false_positive_rate"])
        assert math.isclose(result["balanced_accuracy"], registered[condition]["balanced_accuracy"])
finally:
    for path in (ACTUAL_JSON, ACTUAL_CSV, ACTUAL_MD):
        path.unlink(missing_ok=True)

print("PASS\tregistered fixture contains 500 balanced, threat-stratified episodes")
print("PASS\teach arm receives the same 500 episode identifiers")
print("PASS\tcombined decisions are a monotonic union of deterministic and learned blocks")
print("PASS\tlearned branch adds dangerous catches without hiding its false-positive cost")
print("PASS\tJSON, CSV, and Markdown artifacts reproduce byte-for-byte")
print("5/5 checks passed")
