#!/usr/bin/env python3
"""Validate FerrumOS repository discovery metadata and local documentation links."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS  {message}")


def local_markdown_links(text: str) -> list[str]:
    links = []
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
        target = target.split("#", 1)[0]
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        links.append(target)
    return links


def main() -> int:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    llms = (ROOT / "llms.txt").read_text(encoding="utf-8")
    llms_full = (ROOT / "llms-full.txt").read_text(encoding="utf-8")
    proof = (ROOT / "proof.md").read_text(encoding="utf-8")
    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    citation_guide = (ROOT / "docs" / "CITATION.md").read_text(encoding="utf-8")
    codemeta = json.loads((ROOT / "codemeta.json").read_text(encoding="utf-8"))
    capabilities = json.loads((ROOT / "capabilities.json").read_text(encoding="utf-8"))
    benchmarks = json.loads((ROOT / "benchmarks.json").read_text(encoding="utf-8"))
    cargo = (ROOT / "Cargo.toml").read_text(encoding="utf-8")
    funding = (ROOT / ".github" / "FUNDING.yml").read_text(encoding="utf-8")

    opening = readme[:7000].lower()
    for phrase in (
        "rust ai-native os",
        "jepa safety gate",
        "proof center",
        "evidence snapshot",
        "what makes ferrumos different",
        "research and development use cases",
        "qemu/bochs",
        "synthetic eeg",
    ):
        require(phrase in opening, f"README opening contains {phrase!r}")
    for target in (
        "proof.md",
        "docs/BENCHMARKS.md",
        "benchmarks.json",
        "capabilities.json",
    ):
        require(target in readme, f"README links {target}")

    require(
        "full hardware control" not in opening,
        "README opening avoids unbounded hardware claim",
    )
    require("10.5281/zenodo.21829808" in readme, "README exposes technical-report DOI")
    require("10.5281/zenodo.21829193" in readme, "README exposes dataset DOI")

    require(llms.startswith("# FerrumOS\n"), "llms.txt has canonical project heading")
    require(
        "raw.githubusercontent.com" in llms,
        "llms.txt links raw machine-readable evidence",
    )
    require("llms-full.txt" in llms, "llms.txt links full agent-readable context")
    require("no live EEG" in llms, "llms.txt preserves neural claim boundary")
    require("formal safety proof" in llms, "llms.txt preserves safety claim boundary")
    require(
        "41" in llms_full and "Canonical actions" in llms_full,
        "llms-full catalogs canonical actions",
    )
    require(
        "v0.1.1" in llms_full and "no prebuilt OS image" in llms_full,
        "llms-full states distribution scope",
    )
    require(
        "not directly comparable" in llms_full, "llms-full preserves protocol boundary"
    )

    require(
        codemeta["@type"] == "SoftwareSourceCode", "CodeMeta type is SoftwareSourceCode"
    )
    require(codemeta["version"] == "0.1.1", "CodeMeta version matches release")
    require(
        codemeta["codeRepository"].endswith("/Ferrum-OS"),
        "CodeMeta repository is canonical",
    )
    require("JEPA" in codemeta["keywords"], "CodeMeta exposes JEPA keyword")
    require('version = "0.1.1"' in cargo, "Cargo version matches CodeMeta")
    require(
        'repository = "https://github.com/VyomKulshrestha/Ferrum-OS"' in cargo,
        "Cargo repository metadata is canonical",
    )
    require("VyomKulshrestha" in funding, "GitHub Sponsors button is configured")
    require(
        "type: software" in citation,
        "CITATION.cff identifies the repository as software",
    )
    preferred_citation = citation.index("preferred-citation:")
    software_citation = citation[:preferred_citation]
    report_citation = citation[preferred_citation:]
    require(
        not re.search(r"^doi:\s*", software_citation, re.MULTILINE),
        "software citation does not claim an unrelated DOI",
    )
    require(
        "10.5281/zenodo.21829193" not in citation,
        "dataset DOI is not assigned to the software citation",
    )
    require(
        "doi: 10.5281/zenodo.21829808" in report_citation,
        "preferred report citation retains the technical-report DOI",
    )
    require(
        "10.5281/zenodo.21829808" in citation_guide
        and "10.5281/zenodo.21829193" in citation_guide,
        "citation guide keeps report and dataset identifiers separate",
    )
    require(
        "docs/CITATION.md" in llms, "llms.txt links artifact-specific citation guidance"
    )

    require(
        capabilities["canonical_action_count"] == 41,
        "capability catalog contains 41 source-derived actions",
    )
    require(
        len(capabilities["actions"]) == 41, "capability action count matches catalog"
    )
    require(
        capabilities["schema_version"] == "2.0.0",
        "capability catalog uses versioned schema",
    )
    require(
        benchmarks["schema_version"] == "2.0.0",
        "benchmark summary uses versioned schema",
    )
    require(
        "current main" in capabilities["catalog_scope"]["source_channel"],
        "capability catalog states source scope",
    )
    require(
        benchmarks["paper_release"]["rules_plus_jepa_balanced_accuracy"]
        == 0.8140000000000001,
        "paper metric is source-derived",
    )
    require(
        benchmarks["physical_simulator_jepa"]["validated_for_gating"] is False,
        "physical model remains shadow-only",
    )
    require(
        benchmarks["neural_synthetic"]["emitted_intents"] == 0,
        "neural no-control count remains zero",
    )
    require(
        "formal safety certificate" in proof,
        "proof center disclaims formal certification",
    )

    for document in (
        ROOT / "README.md",
        ROOT / "proof.md",
        ROOT / "docs" / "BENCHMARKS.md",
    ):
        for target in local_markdown_links(document.read_text(encoding="utf-8")):
            resolved = (document.parent / target).resolve()
            require(
                resolved.exists(),
                f"{document.relative_to(ROOT)} local link exists: {target}",
            )

    print("\nRepository discovery verification passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, json.JSONDecodeError) as error:
        print(f"FAIL  {error}", file=sys.stderr)
        raise SystemExit(1)
