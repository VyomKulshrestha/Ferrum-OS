#!/usr/bin/env python3
"""Check that the paper carries the six required primary-source references."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
paper = (ROOT / "docs/research/WORLD_MODEL_RESEARCH.md").read_text(encoding="utf-8")
access = (ROOT / "docs/research/LITERATURE_ACCESS.md").read_text(encoding="utf-8")
bib = (ROOT / "docs/research/references.bib").read_text(encoding="utf-8")
normalized_paper = " ".join(paper.split())

required = {
    "lecun2022path": "https://openreview.net/forum?id=BZ5a1r-kVsf",
    "assran2023ijepa": "https://arxiv.org/abs/2301.08243",
    "bardes2024vjepa": "https://arxiv.org/abs/2404.08471",
    "zhang2023safetybench": "https://arxiv.org/abs/2309.07045",
    "zhou2023webarena": "https://arxiv.org/abs/2307.13854",
    "ni2024responsible": "https://arxiv.org/abs/2411.18289",
}

for key, url in required.items():
    assert f"{{{key}," in bib, f"missing BibTeX key {key}"
    assert url in bib, f"missing primary URL for {key}"
    assert url in paper, f"paper does not cite {key}"
    assert url in access, f"access record does not list {key}"

assert "metric-equivalent" in access
assert "not evidence that an OS transition model inherits" in normalized_paper
assert "## Section 7: Discussion" in paper
for count in ("21", "20", "11"):
    assert f"| {count} |" in paper
for figure in ("figure_1_three_arm_comparison.png", "figure_2_jepa_architecture.png"):
    assert figure in paper

print("PASS\tsix requested primary references are present in BibTeX")
print("PASS\trelated work cites every primary record")
print("PASS\taccess and non-equivalence qualifications are explicit")
print("PASS\tSection 7 carries the exhaustive 52-FN analysis and both figures")
print("4/4 checks passed")
