#!/usr/bin/env python3
"""Verify the current runtime checkpoint without mutating study-v1 evidence."""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "docs/research"
APPLIANCE = ROOT / "appliance/world-model"
ARCHIVE = RESEARCH / "artifacts/world-model-study-v1.0.0"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


manifest = load(APPLIANCE / "manifest.json")
metrics = load(RESEARCH / "world_model_runtime_v2_metrics.json")
selection = load(RESEARCH / "world_model_runtime_v2_selection.json")
sweep = load(RESEARCH / "world_model_runtime_v2_sweep.json")
safety = load(RESEARCH / "world_model_runtime_v2_safety.json")
benchmark = load(RESEARCH / "world_model_runtime_v2_benchmark.json")
study_manifest = load(ARCHIVE / "manifest.json")

assert manifest["runtime_revision"] == 2
assert sha256(APPLIANCE / "model_encoder.bin") == manifest["files"]["encoder"]["sha256"]
assert sha256(APPLIANCE / "model_learned.bin") == manifest["files"]["transition"]["sha256"]

assert selection["selected"] == "candidate"
assert not selection["regressions_beyond_tolerance"]
assert selection["candidate"]["one_step_relative_error"] == metrics["normalized_mse"]
assert selection["candidate"]["rollout_h3_relative_error"] == metrics["rollout"]["3"]["normalized_mse"]
assert sweep["selected_transition_sha256"] == manifest["files"]["transition"]["sha256"]
assert next(
    row for row in sweep["boundary_candidates"] if row.get("selected")
)["core_loss_weight"] == manifest["transition"]["refinement"]["core_loss_weight"]

combined = safety["results"]["conditions"]["rules_plus_jepa"]
assert combined["confusion"] == {
    "false_negative": 50,
    "false_positive": 41,
    "true_negative": 209,
    "true_positive": 200,
}
assert combined["balanced_accuracy"] == 0.8180000000000001
assert sha256(RESEARCH / "world_model_runtime_v2_safety.json") == (
    manifest["safety_evaluation"]["artifacts"]["aggregate"]["sha256"]
)
assert sha256(RESEARCH / "world_model_runtime_v2_safety_predictions.csv") == (
    manifest["safety_evaluation"]["artifacts"]["predictions"]["sha256"]
)
assert benchmark["memory"]["heap_growth_bytes"] == 0
assert [row["horizon"] for row in benchmark["horizons"]] == [1, 2, 3, 4, 5]
assert sha256(RESEARCH / "world_model_runtime_v2_benchmark.json") == (
    manifest["runtime_benchmark"]["artifact"]["sha256"]
)

assert sha256(ARCHIVE / "model_encoder.bin") == study_manifest["files"]["encoder"]["sha256"]
assert sha256(ARCHIVE / "model_learned.bin") == study_manifest["files"]["transition"]["sha256"]
assert study_manifest["held_out_normalized_error"]["rollout_h3"] == 0.03867185344696794

print("PASS\truntime-v2 encoder and transition hashes match the appliance manifest")
print("PASS\tvalidation-selected checkpoint passed the held-out promotion gate")
print("PASS\tselected boundary weight matches the immutable sweep report")
print("PASS\ttracked metrics match the selected checkpoint")
print("PASS\tpost-selection 500-episode safety result is internally consistent")
print("PASS\tsafety aggregate and predictions match manifest hashes")
print("PASS\tfresh H=1..5 appliance benchmark reports zero heap growth")
print("PASS\tstudy-v1 encoder and transition remain byte-for-byte archived")
print("PASS\tstudy-v1 published H=3 result remains unchanged")
print("9/9 runtime-v2 checks passed")
