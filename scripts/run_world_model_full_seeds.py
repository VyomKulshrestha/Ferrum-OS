#!/usr/bin/env python3
"""Train complete FerrumOS JEPA + transition pipelines for multiple seeds."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_logged(command: list[str], log: Path) -> float:
    started = time.perf_counter()
    with log.open("w", encoding="utf-8") as handle:
        handle.write("COMMAND " + subprocess.list2cmdline(command) + "\n")
        handle.flush()
        result = subprocess.run(command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}); inspect {log}")
    return time.perf_counter() - started


def train_seed(seed: int, dataset: Path, out_dir: Path, resume: bool) -> dict:
    seed_dir = out_dir / f"seed_{seed}"
    seed_dir.mkdir(parents=True, exist_ok=True)
    encoder = seed_dir / "encoder.bin"
    encoded_dataset = seed_dir / "encoded_dataset.jsonl"
    encoder_metrics = seed_dir / "encoder_metrics.json"
    transition = seed_dir / "transition.bin"
    transition_metrics = seed_dir / "transition_metrics.json"
    encoder_command = [
        sys.executable, str(ROOT / "scripts" / "train_world_model_jepa.py"),
        "--dataset", str(dataset), "--out", str(encoder),
        "--encoded-dataset", str(encoded_dataset), "--metrics-out", str(encoder_metrics),
        "--hidden", "256", "--epochs", "300", "--batch-size", "256", "--lr", "0.001",
        "--ema", "0.99", "--reconstruction-weight", "0.25", "--action-weight", "0.1",
        "--patience", "12", "--seed", str(seed), "--split-seed", "42",
    ]
    transition_command = [
        sys.executable, str(ROOT / "scripts" / "train_world_model.py"),
        "--dataset", str(encoded_dataset), "--out", str(transition),
        "--metrics-out", str(transition_metrics), "--hidden", "512", "--epochs", "2000",
        "--lr", "0.05", "--seed", str(seed), "--split-seed", "42",
        "--max-rollout-horizon", "5", "--min-train-per-tool", "32",
        "--require-covered-tools", "40",
    ]
    encoder_elapsed = 0.0
    transition_elapsed = 0.0
    if not (resume and encoder.is_file() and encoded_dataset.is_file() and encoder_metrics.is_file()):
        encoder_elapsed = run_logged(encoder_command, seed_dir / "encoder.log")
    if not (resume and transition.is_file() and transition_metrics.is_file()):
        transition_elapsed = run_logged(transition_command, seed_dir / "transition.log")
    return {
        "seed": seed,
        "encoder_elapsed_seconds": encoder_elapsed,
        "transition_elapsed_seconds": transition_elapsed,
        "encoder_sha256": sha256(encoder),
        "transition_sha256": sha256(transition),
        "encoder_command": encoder_command,
        "transition_command": transition_command,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=ROOT / "target" / "world_model_dataset_release_repaired2.jsonl")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "target" / "world_model_full_seeds")
    parser.add_argument("--seeds", default="17,42,91,123,2026")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--json-out", type=Path, default=ROOT / "docs" / "research" / "world_model_full_seed_evaluation.json")
    parser.add_argument("--markdown-out", type=Path, default=ROOT / "docs" / "research" / "WORLD_MODEL_FULL_SEED_EVALUATION.md")
    args = parser.parse_args()
    dataset = args.dataset.resolve()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    seeds = [int(value) for value in args.seeds.split(",") if value.strip()]
    if len(seeds) < 5:
        raise SystemExit("full-pipeline paper evaluation requires at least five seeds")
    started = time.perf_counter()
    runs = []
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as executor:
        futures = {
            executor.submit(train_seed, seed, dataset, out_dir, args.resume): seed
            for seed in seeds
        }
        for future in as_completed(futures):
            seed = futures[future]
            result = future.result()
            runs.append(result)
            print(f"completed full pipeline seed {seed}", flush=True)
    runs.sort(key=lambda row: row["seed"])
    manifest = {
        "schema_version": 1,
        "dataset": {"path": str(dataset), "sha256": sha256(dataset)},
        "seeds": seeds,
        "jobs": max(1, args.jobs),
        "elapsed_seconds": time.perf_counter() - started,
        "runs": runs,
    }
    (out_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    evaluate_command = [
        sys.executable, str(ROOT / "scripts" / "evaluate_world_model_full_seeds.py"),
        "--run-dir", str(out_dir), "--seeds", ",".join(str(seed) for seed in seeds),
        "--json-out", str(args.json_out), "--markdown-out", str(args.markdown_out),
    ]
    subprocess.run(evaluate_command, cwd=ROOT, check=True)
    print(json.dumps({
        "seeds": seeds,
        "elapsed_seconds": manifest["elapsed_seconds"],
        "run_dir": str(out_dir),
        "evaluation": str(args.json_out),
    }, indent=2))


if __name__ == "__main__":
    main()
