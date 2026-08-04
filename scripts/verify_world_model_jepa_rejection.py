#!/usr/bin/env python3
"""A rejected JEPA trial must leave metrics, but no promotable artifacts."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path


script_dir = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix="ferrumos-jepa-reject-") as temp:
    root = Path(temp)
    dataset = root / "dataset.jsonl"
    metrics = root / "metrics.json"
    weights = root / "encoder.bin"
    encoded = root / "encoded.jsonl"
    rows = []
    for episode in range(40):
        for step in range(3):
            rows.append({
                "episode_id": f"constant-{episode:02d}",
                "step": step,
                "action": episode % 41,
                "action_features": [0.0] * 16,
                "executed": True,
                "before": [0.0] * 128,
                "after": [0.0] * 128,
            })
    dataset.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    result = subprocess.run([
        sys.executable, str(script_dir / "train_world_model_jepa.py"),
        "--dataset", str(dataset), "--out", str(weights),
        "--encoded-dataset", str(encoded), "--metrics-out", str(metrics),
        "--hidden", "8", "--epochs", "1", "--batch-size", "32",
        "--patience", "1", "--seed", "7", "--split-seed", "7",
    ], check=False, capture_output=True, text=True)
    assert result.returncode != 0, "constant representation should be rejected"
    report = json.loads(metrics.read_text(encoding="utf-8"))
    assert report["accepted"] is False
    assert report["dataset_fingerprint"].startswith("sha256:")
    assert not weights.exists() and not encoded.exists()

print("PASS\trejected JEPA trial persists its held-out metrics")
print("PASS\trejection report remains bound to the source dataset")
print("PASS\trejected JEPA trial emits no encoder or encoded corpus")
print("3/3 checks passed")
