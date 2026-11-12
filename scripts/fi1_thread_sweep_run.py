#!/usr/bin/env python3
"""Rerun the physical-JEPA v3 sweep and its baseline evaluator at a given BLAS thread count (fi1 B3).

Exploratory. Runs the registered commands of ``verify_physical_world_model.py`` (selector) and of
the v3 baseline evaluator in subprocesses whose BLAS pools are pinned to ``--threads``, and writes
everything under target/fi1-pipeline3/sweep/t<threads>_<run>/. Nothing in docs/ is touched.
A run at more than 4 threads must hold the machine's shared lock (the caller takes it).

    python scripts/fi1_thread_sweep_run.py --threads 4 --run run1
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import repro_env  # noqa: E402
import verify_physical_world_model as verifier  # noqa: E402


def child_environment(threads: int) -> dict:
    env = dict(os.environ)
    for name in repro_env.THREAD_ENVIRONMENT_VARIABLES:
        env[name] = str(threads)
    env["CUDA_VISIBLE_DEVICES"] = "-1"
    return env


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threads", type=int, required=True)
    parser.add_argument("--run", default="run1")
    parser.add_argument("--skip-baselines", action="store_true")
    args = parser.parse_args()
    out = ROOT / "target" / "fi1-pipeline3" / "sweep" / f"t{args.threads}_{args.run}"
    out.mkdir(parents=True, exist_ok=True)
    protocol = verifier.load(verifier.PROTOCOL)
    base = protocol["base_dataset"]
    incident = protocol["incident_dataset"]
    stress = protocol["stress_curriculum"]
    ood = protocol["registered_ood"]
    artifact = out / "model.bin"
    report = out / "selection.json"
    dataset = out / "dataset.jsonl"
    command = [
        sys.executable,
        str(verifier.SELECTOR),
        "--current-artifact",
        str(verifier.BASELINE_ARTIFACT),
        "--artifact",
        str(artifact),
        "--report",
        str(report),
        "--dataset",
        str(dataset),
        "--base-episodes",
        str(base["episodes"]),
        "--steps",
        str(base["steps"]),
        "--data-seed",
        str(base["seed"]),
        "--incident-validation-per-source",
        str(incident["validation_episodes_per_source"]),
        "--incident-test-per-source",
        str(incident["test_episodes_per_source"]),
        "--candidate-config",
        str(verifier.PROTOCOL),
        "--ood-count",
        str(ood["rows"]),
        "--ood-seed",
        str(ood["seed"]),
        "--ood-protocol",
        str(ood["protocol"]),
        "--stress-train-episodes",
        str(stress["train_episodes"]),
        "--stress-validation-episodes",
        str(stress["validation_episodes"]),
        "--stress-test-episodes",
        str(stress["test_episodes"]),
        "--stress-seed",
        str(stress["seed"]),
    ]
    env = child_environment(args.threads)
    timings = {}
    start = time.time()
    with (out / "selector.log").open("w", encoding="utf-8") as log:
        selector = subprocess.run(
            command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT
        )
    timings["selector_seconds"] = round(time.time() - start, 1)
    baselines_code = None
    if not args.skip_baselines and report.exists():
        start = time.time()
        with (out / "baselines.log").open("w", encoding="utf-8") as log:
            baselines_code = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "evaluate_physical_jepa_v3_baselines.py"),
                    "--selection-report",
                    str(report),
                    "--artifact",
                    str(artifact),
                    "--protocol",
                    str(verifier.PROTOCOL),
                    "--output",
                    str(out / "baselines.json"),
                ],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            ).returncode
        timings["baselines_seconds"] = round(time.time() - start, 1)
    # The record describes this (parent) process with the child's pinned environment applied.
    repro_env.pin_threads(args.threads)
    meta = {
        "threads": args.threads,
        "run": args.run,
        "selector_exit": selector.returncode,
        "baselines_exit": baselines_code,
        **timings,
        "environment": repro_env.environment_record(),
    }
    (out / "run.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", "utf-8"
    )
    print(json.dumps({k: v for k, v in meta.items() if k != "environment"}))


if __name__ == "__main__":
    main()
