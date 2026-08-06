#!/usr/bin/env python3
"""One-command verification or full CPU reproduction of the paper artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(*arguments: str) -> None:
    subprocess.run([sys.executable, *arguments], cwd=ROOT, check=True)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def quick_verify() -> None:
    for script in (
        "scripts/verify_world_model_safety_evaluation.py",
        "scripts/verify_world_model_paper_evaluation.py",
        "scripts/verify_world_model_figures.py",
    ):
        run(script)


def full_reproduction(dataset: Path) -> None:
    if not dataset.is_file():
        raise SystemExit(f"dataset not found: {dataset}")
    config = json.loads((ROOT / "docs/research/world_model_training_config.json").read_text())
    with tempfile.TemporaryDirectory(prefix="ferrumos-paper-reproduce-") as directory:
        out = Path(directory)
        jepa_encoder = out / "jepa_encoder.bin"
        jepa_rows = out / "jepa_rows.jsonl"
        run(
            "scripts/train_world_model_jepa.py", "--dataset", str(dataset),
            "--out", str(jepa_encoder), "--encoded-dataset", str(jepa_rows),
            "--metrics-out", str(out / "jepa_metrics.json"), "--hidden", "256",
            "--epochs", "300", "--batch-size", "256", "--lr", "0.001",
            "--ema", "0.99", "--reconstruction-weight", "0.25",
            "--action-weight", "0.1", "--patience", "12", "--seed", "42",
            "--split-seed", "42",
        )
        assert digest(jepa_encoder) == config["representation_training"]["output_sha256"]

        seed_models = {}
        seed_metrics = {}
        for seed in (17, 42, 91):
            seed_models[seed] = out / f"transition_seed_{seed}.bin"
            seed_metrics[seed] = out / f"transition_seed_{seed}.json"
            run(
                "scripts/train_world_model.py", "--dataset", str(jepa_rows),
                "--out", str(seed_models[seed]), "--metrics-out", str(seed_metrics[seed]),
                "--hidden", "512", "--epochs", "2000", "--lr", "0.05",
                "--seed", str(seed), "--split-seed", "42",
                "--max-rollout-horizon", "5", "--min-train-per-tool", "32",
                "--require-covered-tools", "40",
            )
        assert digest(seed_models[17]) == config["transition_training"]["selected_output_sha256"]

        ae_encoder = out / "ae_encoder.bin"
        ae_rows = out / "ae_rows.jsonl"
        ae_transition = out / "ae_transition.bin"
        run(
            "scripts/train_world_model_encoder.py", "--dataset", str(dataset),
            "--out", str(ae_encoder), "--encoded-dataset", str(ae_rows),
            "--metrics-out", str(out / "ae_metrics.json"), "--hidden", "256",
            "--epochs", "3000", "--lr", "0.05", "--seed", "42",
            "--split-seed", "42",
        )
        run(
            "scripts/train_world_model.py", "--dataset", str(ae_rows),
            "--out", str(ae_transition), "--metrics-out", str(out / "ae_transition.json"),
            "--hidden", "256", "--epochs", "2000", "--lr", "0.05",
            "--seed", "17", "--split-seed", "42", "--max-rollout-horizon", "5",
            "--min-train-per-tool", "32", "--require-covered-tools", "40",
        )
        assert digest(ae_encoder) == config["autoencoder_baseline"]["encoder_sha256"]
        assert digest(ae_transition) == config["autoencoder_baseline"]["transition_sha256"]

        command = [
            "scripts/evaluate_world_model_paper.py", "--dataset", str(dataset),
            "--encoder", str(jepa_encoder), "--transition", str(seed_models[17]),
            "--ae-encoder", str(ae_encoder), "--ae-transition", str(ae_transition),
            "--json-out", str(out / "paper.json"), "--csv-out", str(out / "paper.csv"),
            "--markdown-out", str(out / "paper.md"),
        ]
        for seed in (17, 42, 91):
            command.extend(("--seed-transition", f"{seed}={seed_models[seed]}",
                            "--seed-metrics", f"{seed}={seed_metrics[seed]}"))
        run(*command)
        regenerated = json.loads((out / "paper.json").read_text())
        committed = json.loads((ROOT / "docs/research/world_model_paper_evaluation.json").read_text())
        for key in ("dataset_accounting", "baselines", "horizon_ablation",
                    "training_seed_sensitivity", "untouched_qemu_safe_replay"):
            assert regenerated[key] == committed[key], key
    quick_verify()
    print("PASS\tfull CPU training and paper evidence reproduced")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="retrain JEPA, all transition seeds, and autoencoder")
    parser.add_argument("--dataset", type=Path, default=ROOT / "target/world_model_dataset_release_repaired2.jsonl")
    args = parser.parse_args()
    if args.full:
        full_reproduction(args.dataset.resolve())
    else:
        quick_verify()


if __name__ == "__main__":
    main()
