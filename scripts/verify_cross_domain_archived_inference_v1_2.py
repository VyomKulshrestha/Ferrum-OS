#!/usr/bin/env python3
"""Recompute historical tables from archived bytes, without changing old records.

--pack is a one-time release-maintenance operation. The default is read-only:
restore the original base input in a temporary directory, reconstruct the same
already-opened historical rows, and compare every original domain statistic.
No training, new test seed, threshold selection, or deployment occurs.
"""
from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

import torch

import evaluate_cross_domain_world_models as architecture
import evaluate_cross_domain_world_model_posthoc_sensitivity_v1 as sensitivity


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "docs/research/artifacts/cross-domain-inference-v1.2"
MANIFEST = ROOT / "docs/research/cross_domain_inference_archive_v1_2.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(record: object) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"))


def record(path: Path) -> dict:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)}


def metadata_matches(item: dict) -> bool:
    path = ROOT / item["path"]
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return item["sha256"] in {
        digest(path), hashlib.sha256(text.encode()).hexdigest(),
        hashlib.sha256(text.replace("\n", "\r\n").encode()).hexdigest(),
    }


def pack() -> None:
    if MANIFEST.exists() or ARCHIVE.exists():
        raise FileExistsError("retain the existing archive; do not overwrite it")
    protocol = architecture.load_json(architecture.PROTOCOL)
    selection = architecture.load_json(architecture.SELECTION)
    base = protocol["frozen_research_inputs"]["ferrumos_base_dataset"]
    if digest(ROOT / base["path"]) != base["sha256"]:
        raise AssertionError("original base dataset digest differs")
    items = []
    for domain, selected in selection["domains"].items():
        for method, runs in selected["methods"].items():
            for run in runs:
                original = run["checkpoint"]
                path = ROOT / original["path"]
                if digest(path) != original["sha256"]:
                    raise AssertionError(f"checkpoint differs: {path}")
                items.append((domain, method, run["seed"], path, original))
    # Validate all inputs before creating any archive file.
    ARCHIVE.mkdir(parents=True)
    checkpoints = []
    for domain, method, seed, path, original in items:
        destination = ARCHIVE / domain / path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        checkpoints.append({"domain": domain, "method": method, "seed": seed,
                            "original": original, "archived": record(destination)})
    compressed = ARCHIVE / "ferrumos-base.jsonl.gz"
    compressed.write_bytes(gzip.compress((ROOT / base["path"]).read_bytes(), mtime=0))
    manifest = {"schema": "cross-domain-inference-archive-v1.2", "checkpoints": checkpoints,
                "base_dataset": {"original": base, "archived": record(compressed)},
                "architecture_protocol": record(architecture.PROTOCOL),
                "architecture_selection": record(architecture.SELECTION),
                "architecture_result": record(architecture.RESULT),
                "posthoc_protocol": record(sensitivity.PROTOCOL),
                "posthoc_result": record(sensitivity.OUTPUT),
                "restoration": "All 18 checkpoint bytes match the original selection. Missing checkpoints were restored on development data with 16 Torch CPU threads, not reselected. Four-thread attempts were non-identical and are not used.",
                "promotion_eligible": False}
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def verify() -> dict:
    manifest = architecture.load_json(MANIFEST)
    for key in ("architecture_protocol", "architecture_selection", "architecture_result",
                "posthoc_protocol", "posthoc_result"):
        if not metadata_matches(manifest[key]):
            raise AssertionError(f"archive metadata drift: {key}")
    protocol = architecture.load_json(architecture.PROTOCOL)
    selection = copy.deepcopy(architecture.load_json(architecture.SELECTION))
    expected = architecture.load_json(architecture.RESULT)
    posthoc = architecture.load_json(sensitivity.OUTPUT)
    posthoc_protocol = architecture.load_json(sensitivity.PROTOCOL)
    for item in posthoc_protocol["inputs"].values():
        path = ROOT / item["path"]
        matches = (metadata_matches(item) if path.suffix == ".json" else digest(path) == item["sha256"])
        if not matches:
            raise AssertionError(f"post-hoc input drift: {path}")
    archived = {(item["domain"], item["method"], item["seed"]): item
                for item in manifest["checkpoints"]}
    count = 0
    for domain, selected in selection["domains"].items():
        for method, runs in selected["methods"].items():
            for run in runs:
                item = archived[(domain, method, run["seed"])]
                path = ROOT / item["archived"]["path"]
                if (item["original"] != run["checkpoint"]
                        or digest(path) != run["checkpoint"]["sha256"]
                        or digest(path) != item["archived"]["sha256"]):
                    raise AssertionError(f"archive checkpoint mismatch: {path}")
                run["checkpoint"]["path"] = item["archived"]["path"]
                count += 1
    if count != 18 or len(archived) != 18:
        raise AssertionError("exactly 18 original checkpoints are required")
    original = protocol["frozen_research_inputs"]["ferrumos_base_dataset"]
    base = manifest["base_dataset"]
    compressed = ROOT / base["archived"]["path"]
    if base["original"] != original or digest(compressed) != base["archived"]["sha256"]:
        raise AssertionError("base dataset archive binding differs")
    raw = gzip.decompress(compressed.read_bytes())
    if hashlib.sha256(raw).hexdigest() != original["sha256"]:
        raise AssertionError("uncompressed original dataset digest differs")
    protected = architecture.verify_digest_map(protocol["protected_deployed_artifacts"])
    if not all(protected.values()):
        raise AssertionError("protected deployed artifact drift")
    torch.set_num_threads(16)
    checks = {"all_18_original_checkpoint_bytes_match": True, "original_base_dataset_bytes_match": True}
    with tempfile.TemporaryDirectory(prefix="cross-domain-inference-") as temporary:
        base_path = Path(temporary) / "base.jsonl"
        base_path.write_bytes(raw)
        original["path"] = str(base_path)
        for index, (domain, loader) in enumerate((("ferrumos", architecture.os_final),
                                                 ("physical", architecture.physical_final))):
            print(f"recomputing historical {domain} tables", flush=True)
            spec, rows, provenance = loader(protocol)
            actual = {"provenance": provenance, **architecture.evaluate_domain(
                domain, spec, rows, selection["domains"][domain],
                protocol["architecture_controlled_comparison"]["shared_conditions"])}
            checks[f"{domain}_original_domain_record_exact"] = canonical(actual) == canonical(expected["domains"][domain])
            common = sensitivity.common_episode_domain(
                domain, spec, rows, selection["domains"][domain],
                posthoc_protocol["randomness"]["common_episode_bootstrap_seed"] + 100000 * index,
                posthoc_protocol["randomness"]["resamples"])
            checks[f"{domain}_common_episode_record_exact"] = canonical(common) == canonical(
                posthoc["common_episode_horizon_analysis"]["domains"][domain])
    checks["attribution_diagnostics_exact"] = canonical(sensitivity.attribution_analysis(posthoc_protocol)) == canonical(posthoc["attribution_diagnostics"])
    checks["protected_deployed_bytes_unchanged"] = protected == architecture.verify_digest_map(
        protocol["protected_deployed_artifacts"])
    report = {"all_checks_pass": all(checks.values()), "checks": checks,
              "archive_manifest": record(MANIFEST), "verifier": record(Path(__file__)),
              "scope": "Exact historical inference and sensitivity recomputation; same already-opened deterministic rows, no new final seed or result opening, no training, no simulator or QEMU execution.",
              "torch_cpu_threads": 16, "promotion_eligible": False}
    if not report["all_checks_pass"]:
        print(json.dumps(report, indent=2))
        raise AssertionError("historical recomputation differs; old evidence unchanged")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", action="store_true")
    parser.add_argument("--output", type=Path, help="optionally create a new audit record; never overwrite")
    args = parser.parse_args()
    if args.pack:
        if args.output:
            parser.error("--output cannot be combined with --pack")
        pack()
    else:
        report = verify()
        if args.output:
            with args.output.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(json.dumps(report, indent=2))
