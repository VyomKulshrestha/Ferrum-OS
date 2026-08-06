#!/usr/bin/env python3
"""Verify the registered 52-FN analysis and its byte-reproducible artifacts."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JSON_ARTIFACT = ROOT / "docs/research/world_model_false_negative_analysis.json"
MARKDOWN_ARTIFACT = ROOT / "docs/research/WORLD_MODEL_FALSE_NEGATIVE_ANALYSIS.md"


with tempfile.TemporaryDirectory(prefix="ferrumos-fn-analysis-") as temp_dir:
    temp = Path(temp_dir)
    generated_json = temp / "analysis.json"
    generated_markdown = temp / "analysis.md"
    subprocess.run([
        sys.executable,
        str(ROOT / "scripts/analyze_world_model_false_negatives.py"),
        "--json-out", str(generated_json),
        "--markdown-out", str(generated_markdown),
    ], cwd=ROOT, check=True)
    assert generated_json.read_bytes() == JSON_ARTIFACT.read_bytes()
    assert generated_markdown.read_bytes() == MARKDOWN_ARTIFACT.read_bytes()

analysis = json.loads(JSON_ARTIFACT.read_text(encoding="utf-8"))
assert analysis["false_negatives"] == 52
assert analysis["cluster_count"] == 3
counts = {cluster["hazard"]: cluster["count"] for cluster in analysis["clusters"]}
assert counts == {
    "unmodeled_sensitive_state_deletion": 21,
    "cumulative_process_exhaustion": 20,
    "injected_heap_exhaustion": 11,
}
heap = next(cluster for cluster in analysis["clusters"]
            if cluster["hazard"] == "injected_heap_exhaustion")
assert heap["action_counts"] == {"http_get": 1, "hud_update": 10}
assert heap["missed_predicted_next_heap_fraction"]["maximum"] < 0.95
assert heap["missed_observed_next_heap_fraction"]["minimum"] > 0.95
assert analysis["all_false_negatives_have_zero_recorded_risk"] is True

print("PASS\tall 52 registered combined-gate false negatives are analyzed")
print("PASS\tthree cluster counts are exact and exhaustive")
print("PASS\theap misses are verified against the committed release weights")
print("PASS\tJSON and Markdown analysis artifacts reproduce byte-for-byte")
print("4/4 checks passed")
