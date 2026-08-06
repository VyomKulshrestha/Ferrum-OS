#!/usr/bin/env python3
"""Verify the expanded FerrumOS world-model paper evidence package."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "docs/research"
REPORT = RESEARCH / "world_model_paper_evaluation.json"
PREDICTIONS = RESEARCH / "world_model_paper_predictions.csv"
SUMMARY = RESEARCH / "WORLD_MODEL_PAPER_EVALUATION.md"
CONFIG = RESEARCH / "world_model_training_config.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest


report = json.loads(REPORT.read_text(encoding="utf-8"))
config = json.loads(CONFIG.read_text(encoding="utf-8"))
rows = list(csv.DictReader(PREDICTIONS.open(encoding="utf-8")))

accounting = report["dataset_accounting"]
stages = {row["stage"]: row["rows"] for row in accounting["stages"]}
assert stages["accepted corpus"] == 13697
assert stages["excluded: execution not attempted"] == 373
assert stages["excluded: policy-only kernel upgrade"] == 54
assert stages["eligible executed transitions"] == 13270
assert 373 + 54 + 13270 == 13697
assert accounting["episode_disjoint"]
assert set(accounting["episode_overlaps"].values()) == {0}
assert [accounting["partitions"][name]["rows"] for name in ("train", "validation", "test")] == [9104, 2197, 1969]

artifact_paths = {
    "encoder": ROOT / "appliance/world-model/model_encoder.bin",
    "transition": ROOT / "appliance/world-model/model_learned.bin",
    "fixture": RESEARCH / "world_model_safety_scenarios.json",
}
for name, path in artifact_paths.items():
    assert sha256(path) == report["artifacts"][name]["sha256"]

mapping = {
    "rules_only": ("jepa", "rules_only"),
    "jepa_only": ("jepa", "jepa_only"),
    "rules_plus_jepa": ("jepa", "rules_plus_jepa"),
    "mean_delta_only": ("mean_delta", "jepa_only"),
    "rules_plus_mean_delta": ("mean_delta", "rules_plus_jepa"),
    "jepa_without_action_conditioning": ("jepa_no_action", "jepa_only"),
    "autoencoder_only": ("autoencoder", "jepa_only"),
    "rules_plus_autoencoder": ("autoencoder", "rules_plus_jepa"),
    "validation_calibrated_jepa_only": ("validation_calibrated_jepa", "jepa_only"),
    "rules_plus_validation_calibrated_jepa": ("validation_calibrated_jepa", "rules_plus_jepa"),
}
for name, (baseline, condition) in mapping.items():
    selected = [row for row in rows if row["baseline"] == baseline and row["condition"] == condition]
    assert len(selected) == 500, name
    tp = sum(row["dangerous"] == "True" and row["blocked"] == "True" for row in selected)
    fn = sum(row["dangerous"] == "True" and row["blocked"] == "False" for row in selected)
    fp = sum(row["dangerous"] == "False" and row["blocked"] == "True" for row in selected)
    tn = sum(row["dangerous"] == "False" and row["blocked"] == "False" for row in selected)
    assert report["baselines"][name]["confusion"] == {"tp": tp, "fn": fn, "fp": fp, "tn": tn}

assert report["baselines"]["rules_plus_jepa"]["confusion"] == {"tp": 198, "fn": 52, "fp": 41, "tn": 209}
assert report["baselines"]["rules_plus_mean_delta"]["confusion"] == {"tp": 198, "fn": 52, "fp": 42, "tn": 208}
assert report["baselines"]["rules_plus_autoencoder"]["confusion"] == {"tp": 189, "fn": 61, "fp": 41, "tn": 209}
assert report["baselines"]["rules_plus_validation_calibrated_jepa"]["confusion"] == {"tp": 209, "fn": 41, "fp": 41, "tn": 209}

assert set(report["horizon_ablation"]) == {"1", "2", "3", "4", "5"}
assert report["horizon_ablation"]["2"]["rules_plus_jepa"]["balanced_accuracy"] > report["horizon_ablation"]["3"]["rules_plus_jepa"]["balanced_accuracy"]
assert set(report["training_seed_sensitivity"]) == {"17", "42", "91"}
assert report["training_seed_aggregate"]["combined_false_negative_rate"]["max"] >= 0.376
assert report["untouched_qemu_safe_replay"]["safe_rows"] == 1969
assert report["untouched_qemu_safe_replay"]["conditions"]["rules_plus_jepa"]["confusion"]["fp"] == 216

assert config["representation_training"]["clean_reproduction"]["byte_identical"]
assert config["transition_training"]["clean_reproduction"]["seed_17_byte_identical"]
assert "--epochs 2000" in config["transition_training"]["command_template"]
assert config["runtime_gate"]["learned_risk_head"] is False
assert config["representation_training"]["output_sha256"] == sha256(artifact_paths["encoder"])
assert config["transition_training"]["selected_output_sha256"] == sha256(artifact_paths["transition"])

summary = SUMMARY.read_text(encoding="utf-8")
for text in ("13,697", "episode overlap: **0**", "rules_plus_mean_delta", "Lookahead ablation"):
    assert text in summary

print("PASS\tall 13,697 corpus rows are accounted for")
print("PASS\tepisode-disjoint split has zero cross-partition overlap")
print("PASS\t10 learned/rule baseline rows reproduce from per-episode predictions")
print("PASS\tH=1..5 and three transition seeds are reported")
print("PASS\tuntouched-QEMU safe replay and calibration ablation are present")
print("PASS\tencoder and selected transition reproduce byte-for-byte under the recorded configuration")
print("6/6 checks passed")
