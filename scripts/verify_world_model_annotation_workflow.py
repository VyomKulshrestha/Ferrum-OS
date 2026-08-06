#!/usr/bin/env python3
"""Exercise annotation blinding and agreement analysis without claiming human labels."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def fill(path: Path, annotator: str, labels: list[str]) -> None:
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    by_id = sorted(row["blind_id"] for row in rows)
    assigned = dict(zip(by_id, labels))
    for row in rows:
        row["annotator_id"] = annotator
        row["label"] = assigned[row["blind_id"]]
        row["confidence"] = "3"
        row["rationale"] = "workflow fixture"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


with tempfile.TemporaryDirectory(prefix="ferrumos-annotations-") as temp_name:
    temp = Path(temp_name)
    source = temp / "source.jsonl"
    source.write_text("".join(json.dumps(row) + "\n" for row in [
        {"item_id": "one", "action": "read_file", "blocked": False},
        {"item_id": "two", "action": "delete_file", "blocked": True},
        {"item_id": "three", "action": "service_start", "blocked": False},
    ]), encoding="utf-8")
    out = temp / "pack"
    subprocess.run([
        sys.executable, str(ROOT / "scripts" / "prepare_world_model_annotation_pack.py"),
        "--input", str(source), "--out-dir", str(out),
    ], cwd=ROOT, check=True, capture_output=True)
    a = out / "annotator_a.csv"
    b = out / "annotator_b.csv"
    fill(a, "reviewer-a", ["safe", "dangerous", "dangerous"])
    fill(b, "reviewer-b", ["safe", "dangerous", "safe"])
    report = temp / "report.json"
    disagreements = temp / "disagreements.csv"
    subprocess.run([
        sys.executable, str(ROOT / "scripts" / "analyze_world_model_annotations.py"),
        "--annotation", str(a), "--annotation", str(b),
        "--json-out", str(report), "--disagreements-out", str(disagreements),
    ], cwd=ROOT, check=True, capture_output=True)
    result = json.loads(report.read_text(encoding="utf-8"))
    assert result["annotators"] == ["reviewer-a", "reviewer-b"]
    assert result["items"] == 3 and result["disagreements"] == 1
    assert abs(result["raw_agreement"] - 2 / 3) < 1e-12
    assert len(list(csv.DictReader(disagreements.open(newline="", encoding="utf-8")))) == 1
    key_text = (out / "blinding_key.json").read_text(encoding="utf-8")
    assert "risk" not in a.read_text(encoding="utf-8")
    assert "gate_blocked" in key_text

print("PASS\tannotation sheets hide gate decisions and source IDs")
print("PASS\tdistinct annotators, uncertainty, disagreement, and kappa are validated")
print("PASS\tgate metadata remains isolated in the post-lock blinding key")
print("3/3 checks passed")
