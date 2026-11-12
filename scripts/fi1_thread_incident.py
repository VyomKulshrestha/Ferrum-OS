#!/usr/bin/env python3
"""Incident dynamics v3/v4: does recomputed inference, and every registered metric, depend on the
PyTorch thread count? (fi1 B3, exploratory; writes only under target/fi1-pipeline3/incident/)

The registered runner pins ``torch.set_num_threads(8)`` and LightGBM ``num_threads=8`` in its code.
This mirrors the runner's ``verify`` stage for one domain with torch pinned to ``--threads`` instead
(the runner's own calls to ``torch.set_num_threads`` are neutralised), and compares: the regenerated
catalogs, every pipeline's errors and scores against the stored evidence (max absolute difference,
and the verifier's atol 1e-7), and ``analyze`` recomputed from the recomputed evidence against the
stored result, gate by gate. The verifier itself recomputes ``analyze`` from the stored evidence.

    python scripts/fi1_thread_incident.py --version 3 --domain physical --threads 1
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import repro_env  # noqa: E402


def load_study(version: int):
    if version == 4:
        import run_incident_dynamics_v4_study as v4

        return v4.study
    import run_incident_dynamics_v3_study as study

    return study


def numeric_paths(a, b, path=""):
    if isinstance(a, dict):
        for k in a:
            yield from numeric_paths(
                a[k], b.get(k) if isinstance(b, dict) else None, f"{path}/{k}"
            )
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            yield from numeric_paths(x, y, f"{path}[{i}]")
    else:
        yield path, a, b


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", type=int, choices=[3, 4], default=3)
    parser.add_argument("--domain", choices=["ferrumos", "physical"], required=True)
    parser.add_argument("--threads", type=int, required=True)
    args = parser.parse_args()
    import torch

    repro_env.pin_threads(args.threads, torch_import=True)
    torch.set_num_threads = lambda n: None  # the runner's own pin to 8 is neutralised
    study = load_study(args.version)
    # Any cache the runner writes goes under this round's own folder.
    work = ROOT / "target" / "fi1-pipeline3" / "incident" / "work"
    study.v3.WORK = work / "incident-dynamics-v3"
    study.v2data.WORK = work / "incident-dynamics-v1"
    selection = study.architecture.load_json(study.SELECTION)
    protocol = study.architecture.load_json(study.PROTOCOL)
    original = study.architecture.load_json(study.RESULT)
    study.verify_bindings(selection)
    start = time.time()
    folder = study.ARTIFACTS / "final" / args.domain
    windows3 = {
        p: study.v3.load(folder / f"{p}_h3.npz") for p in ("A", "B", "historical")
    }
    windows, _ = study.build_populations(args.domain, protocol, selection)
    catalogs = {
        p: all(
            np.array_equal(getattr(windows3[p], k), getattr(windows[p][3], k))
            for k in study.v3.Windows.__dataclass_fields__
        )
        for p in windows3
    }
    evidence = study.collect(selection, protocol, args.domain, windows)
    inference = {}
    with np.load(folder / "evidence.npz", allow_pickle=False) as archive:
        for population, items in evidence.items():
            for name, (errors, scores) in items.items():
                se = archive[f"{population}__{name}__errors"]
                ss = archive[f"{population}__{name}__scores"]
                inference[f"{population}/{name}"] = {
                    "errors_bit_identical": bool(np.array_equal(se, errors)),
                    "scores_bit_identical": bool(np.array_equal(ss, scores)),
                    "max_abs_errors": float(np.max(np.abs(se - errors))),
                    "max_abs_scores": float(np.max(np.abs(ss - scores))),
                    "within_verifier_atol_1e-7": bool(
                        np.allclose(se, errors, atol=1e-7, rtol=0)
                        and np.allclose(ss, scores, atol=1e-7, rtol=0)
                    ),
                }
    recomputed = study.analyze(selection, protocol, evidence, windows3, args.domain)
    stored = original["domains"][args.domain]
    changed = []
    for path, a, b in numeric_paths(recomputed, stored):
        if a != b:
            changed.append({"path": path, "recomputed": a, "stored": b})
    result = {
        "version": args.version,
        "domain": args.domain,
        "threads": args.threads,
        "seconds": round(time.time() - start, 1),
        "catalogs_identical": catalogs,
        "inference": inference,
        "all_inference_bit_identical": all(
            v["errors_bit_identical"] and v["scores_bit_identical"]
            for v in inference.values()
        ),
        "all_within_verifier_tolerance": all(
            v["within_verifier_atol_1e-7"] for v in inference.values()
        ),
        "max_abs_difference": max(
            max(v["max_abs_errors"], v["max_abs_scores"]) for v in inference.values()
        ),
        "analysis_identical_to_stored": recomputed == stored,
        "analysis_leaves_changed": changed[:50],
        "analysis_leaves_changed_count": len(changed),
        "environment": repro_env.environment_record(),
    }
    out = ROOT / "target" / "fi1-pipeline3" / "incident"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"v{args.version}_{args.domain}_t{args.threads}.json"
    path.write_text(json.dumps(result, indent=1, default=str) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "seconds",
                    "all_inference_bit_identical",
                    "all_within_verifier_tolerance",
                    "max_abs_difference",
                    "analysis_identical_to_stored",
                    "analysis_leaves_changed_count",
                    "catalogs_identical",
                )
            }  # fmt: skip
        )
    )


if __name__ == "__main__":
    main()
