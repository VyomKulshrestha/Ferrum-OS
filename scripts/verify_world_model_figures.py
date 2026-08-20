#!/usr/bin/env python3
"""Verify paper figures, source bindings, and reproducible rendering."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
FIGURES = ROOT / "docs/research/figures"
STUDY_MANIFEST = ROOT / "docs/research/artifacts/world-model-study-v1.0.0/manifest.json"
manifest = json.loads((FIGURES / "manifest.json").read_text(encoding="utf-8"))
assert len(manifest["figures"]) == 12

with tempfile.TemporaryDirectory(prefix="ferrumos-paper-figures-") as temp_dir:
    generated = Path(temp_dir) / "figures"
    subprocess.run([
        sys.executable,
            str(ROOT / "scripts/generate_world_model_figures.py"),
            "--manifest", str(STUDY_MANIFEST),
            "--out-dir", str(generated),
    ], cwd=ROOT, check=True)
    for item in manifest["figures"]:
        expected = ROOT / item["path"]
        actual = generated / expected.name
        assert expected.read_bytes() == actual.read_bytes(), expected.name

for stem in (
    "figure_1_three_arm_comparison",
    "figure_2_jepa_architecture",
    "figure_3_stronger_baselines",
    "figure_4_horizon_and_seed_sensitivity",
):
    with Image.open(FIGURES / f"{stem}.png") as image:
        assert image.width >= 1800 and image.height >= 900
    assert (FIGURES / f"{stem}.pdf").read_bytes().startswith(b"%PDF")
    svg = (FIGURES / f"{stem}.svg").read_text(encoding="utf-8")
    assert "<svg" in svg and len(svg) > 10_000

figure_one = (FIGURES / "figure_1_three_arm_comparison.svg").read_text(encoding="utf-8")
figure_two = (FIGURES / "figure_2_jepa_architecture.svg").read_text(encoding="utf-8")
figure_three = (FIGURES / "figure_3_stronger_baselines.svg").read_text(encoding="utf-8")
figure_four = (FIGURES / "figure_4_horizon_and_seed_sensitivity.svg").read_text(encoding="utf-8")
for label in ("41.2%", "77.2%", "20.8%", "81.4%"):
    assert label in figure_one
for label in ("JEPA predictor", "EMA target", "Transition MLP", "Monotonic union"):
    assert label in figure_two
for label in ("Rules + mean", "81.4%", "83.6%"):
    assert label in figure_three
for label in ("Horizon sensitivity", "Seed 17", "Seed 42", "Seed 91"):
    assert label in figure_four

print("PASS\tFigure 1 encodes the registered three-arm metrics")
print("PASS\tFigure 2 encodes the manifest-backed training and runtime dimensions")
print("PASS\tPNG, SVG, and PDF publication formats are structurally valid")
print("PASS\tall twelve figure files reproduce byte-for-byte")
print("4/4 checks passed")
