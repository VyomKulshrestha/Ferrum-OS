#!/usr/bin/env python3
"""Rerun the OS world-model paper pipeline at a given BLAS thread count and compare (fi1 B3).

Exploratory. ``run`` executes the commands of ``reproduce_world_model_paper.py --full`` (JEPA
encoder, transition seeds 17, 42 and 91, autoencoder baseline, paper evaluation) in subprocesses
whose BLAS pools are pinned, writing under target/fi1-pipeline3/os-wm/t<threads>_<run>/ instead of a
temporary folder. ``study_os_world_model`` compares every run with the committed evidence: digests
against world_model_training_config.json, every numeric leaf of the evaluation, and the data-derived
assertions of verify_world_model_paper_evaluation.py and of the paper's comparisons, with margins.

    python scripts/fi1_thread_os_world_model.py run --threads 4 --run run1 --dataset <path>
    python scripts/fi1_thread_compare.py os-world-model
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

import fi1_thread_compare as compare  # noqa: E402
import repro_env  # noqa: E402

WORK = ROOT / "target" / "fi1-pipeline3" / "os-wm"
CONFIG = ROOT / "docs" / "research" / "world_model_training_config.json"
COMMITTED = ROOT / "docs" / "research" / "world_model_paper_evaluation.json"
MANIFEST = (
    ROOT
    / "docs"
    / "research"
    / "artifacts"
    / "world-model-study-v1.0.0"
    / "manifest.json"
)
SHARED_DATASET = Path(
    "C:/Users/marcu/Videos/cursor-os-base/target/world-model-v3-work/"
    "world_model_dataset_release_repaired2.jsonl"
)
COMPARED_KEYS = (
    "dataset_accounting",
    "baselines",
    "horizon_ablation",
    "training_seed_sensitivity",
    "untouched_qemu_safe_replay",
    "untouched_qemu_safe_replay_calibrated",
    "paired_rules_vs_combined",
    "training_seed_aggregate",
    "validation_resource_calibration",
)


def run(threads: int, label: str, dataset: Path, only=None) -> None:
    out = WORK / f"t{threads}_{label}"
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    for name in repro_env.THREAD_ENVIRONMENT_VARIABLES:
        env[name] = str(threads)
    env["CUDA_VISIBLE_DEVICES"] = "-1"
    steps = [
        (
            "jepa_encoder",
            [
                "scripts/train_world_model_jepa.py",
                "--dataset", str(dataset),
                "--out", str(out / "jepa_encoder.bin"),
                "--encoded-dataset", str(out / "jepa_rows.jsonl"),
                "--metrics-out", str(out / "jepa_metrics.json"),
                "--hidden", "256", "--epochs", "300", "--batch-size", "256", "--lr", "0.001",
                "--ema", "0.99", "--reconstruction-weight", "0.25", "--action-weight", "0.1",
                "--patience", "12", "--seed", "42", "--split-seed", "42",
            ],
        )
    ]  # fmt: skip
    for seed in (17, 42, 91):
        steps.append(
            (
                f"transition_{seed}",
                [
                    "scripts/train_world_model.py",
                    "--dataset", str(out / "jepa_rows.jsonl"),
                    "--out", str(out / f"transition_seed_{seed}.bin"),
                    "--metrics-out", str(out / f"transition_seed_{seed}.json"),
                    "--hidden", "512", "--epochs", "2000", "--lr", "0.05",
                    "--seed", str(seed), "--split-seed", "42", "--max-rollout-horizon", "5",
                    "--min-train-per-tool", "32", "--require-covered-tools", "40",
                ],
            )
        )  # fmt: skip
    steps += [
        (
            "ae_encoder",
            [
                "scripts/train_world_model_encoder.py",
                "--dataset", str(dataset),
                "--out", str(out / "ae_encoder.bin"),
                "--encoded-dataset", str(out / "ae_rows.jsonl"),
                "--metrics-out", str(out / "ae_metrics.json"),
                "--hidden", "256", "--epochs", "3000", "--lr", "0.05", "--seed", "42",
                "--split-seed", "42",
            ],
        ),
        (
            "ae_transition",
            [
                "scripts/train_world_model.py",
                "--dataset", str(out / "ae_rows.jsonl"),
                "--out", str(out / "ae_transition.bin"),
                "--metrics-out", str(out / "ae_transition.json"),
                "--hidden", "256", "--epochs", "2000", "--lr", "0.05", "--seed", "17",
                "--split-seed", "42", "--max-rollout-horizon", "5", "--min-train-per-tool", "32",
                "--require-covered-tools", "40",
            ],
        ),
    ]  # fmt: skip
    evaluate = [
        "scripts/evaluate_world_model_paper.py",
        "--manifest", str(MANIFEST),
        "--dataset", str(dataset),
        "--encoder", str(out / "jepa_encoder.bin"),
        "--transition", str(out / "transition_seed_17.bin"),
        "--ae-encoder", str(out / "ae_encoder.bin"),
        "--ae-transition", str(out / "ae_transition.bin"),
        "--json-out", str(out / "paper.json"),
        "--csv-out", str(out / "paper.csv"),
        "--markdown-out", str(out / "paper.md"),
    ]  # fmt: skip
    for seed in (17, 42, 91):
        evaluate += [
            "--seed-transition",
            f"{seed}={out / f'transition_seed_{seed}.bin'}",
            "--seed-metrics",
            f"{seed}={out / f'transition_seed_{seed}.json'}",
        ]
    steps.append(("evaluate", evaluate))
    timings = {}
    if only:
        steps = [step for step in steps if step[0] in only]
    for name, arguments in steps:
        start = time.time()
        with (out / f"{name}.log").open("w", encoding="utf-8") as log:
            subprocess.run(
                [sys.executable, *arguments],
                cwd=ROOT,
                env=env,
                check=True,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        timings[name] = round(time.time() - start, 1)
        print(name, timings[name], flush=True)
    repro_env.pin_threads(threads)
    meta = {
        "threads": threads,
        "run": label,
        "seconds": timings,
        "environment": repro_env.environment_record(),
    }
    (out / "run.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", "utf-8"
    )


def gates(report: dict) -> list:
    b = report["baselines"]

    def ba(name):
        return b[name]["balanced_accuracy"]

    agg = report["training_seed_aggregate"]["combined_false_negative_rate"]["max"]
    hz = report["horizon_ablation"]
    out = [
        compare.gate(
            "verifier: rules_plus_jepa confusion is 198/52/41/209",
            json.dumps(b["rules_plus_jepa"]["confusion"], sort_keys=True),
            json.dumps({"tp": 198, "fn": 52, "fp": 41, "tn": 209}, sort_keys=True),
            "==",
            kind="verifier",
        ),
        compare.gate(
            "verifier: rules_plus_mean_delta confusion is 198/52/42/208",
            json.dumps(b["rules_plus_mean_delta"]["confusion"], sort_keys=True),
            json.dumps({"tp": 198, "fn": 52, "fp": 42, "tn": 208}, sort_keys=True),
            "==",
            kind="verifier",
        ),
        compare.gate(
            "verifier: rules_plus_autoencoder confusion is 189/61/41/209",
            json.dumps(b["rules_plus_autoencoder"]["confusion"], sort_keys=True),
            json.dumps({"tp": 189, "fn": 61, "fp": 41, "tn": 209}, sort_keys=True),
            "==",
            kind="verifier",
        ),
        compare.gate(
            "verifier: rules_plus_validation_calibrated_jepa confusion is 209/41/41/209",
            json.dumps(
                b["rules_plus_validation_calibrated_jepa"]["confusion"], sort_keys=True
            ),
            json.dumps({"tp": 209, "fn": 41, "fp": 41, "tn": 209}, sort_keys=True),
            "==",
            kind="verifier",
        ),
        compare.gate(
            "verifier: horizon H=2 rules_plus_jepa balanced accuracy above H=3",
            hz["2"]["rules_plus_jepa"]["balanced_accuracy"],
            hz["3"]["rules_plus_jepa"]["balanced_accuracy"],
            ">",
            kind="verifier",
        ),
        compare.gate(
            "verifier: seed aggregate combined FNR max at least 0.376",
            agg,
            0.376,
            ">=",
            kind="verifier",
        ),
        compare.gate(
            "verifier: untouched QEMU safe replay rules_plus_jepa fp is 216",
            report["untouched_qemu_safe_replay"]["conditions"]["rules_plus_jepa"][
                "confusion"
            ]["fp"],
            216,
            "==",
            kind="verifier",
        ),
        compare.gate(
            "claim: rules_plus_jepa balanced accuracy above rules_only",
            ba("rules_plus_jepa"),
            ba("rules_only"),
            ">",
            kind="claim",
        ),
        compare.gate(
            "claim: rules_plus_jepa balanced accuracy at least rules_plus_mean_delta",
            ba("rules_plus_jepa"),
            ba("rules_plus_mean_delta"),
            ">=",
            kind="claim",
        ),
        compare.gate(
            "claim: rules_plus_jepa balanced accuracy above rules_plus_autoencoder",
            ba("rules_plus_jepa"),
            ba("rules_plus_autoencoder"),
            ">",
            kind="claim",
        ),
        compare.gate(
            "claim: JEPA H=3 rollout error below matched autoencoder's (seed 17)",
            report["training_seed_sensitivity"]["17"]["rollout_h3_normalized_error"],
            report.get("autoencoder_rollout_h3", float("inf")),
            "<",
            kind="claim",
        )
        if "autoencoder_rollout_h3" in report
        else None,
    ]
    return [g for g in out if g]


def study_os_world_model() -> dict:
    committed = compare.load(COMMITTED)
    config = compare.load(CONFIG)
    expected = {
        "jepa_encoder.bin": config["representation_training"]["output_sha256"],
        "transition_seed_17.bin": config["transition_training"][
            "selected_output_sha256"
        ],
        "ae_encoder.bin": config["autoencoder_baseline"]["encoder_sha256"],
        "ae_transition.bin": config["autoencoder_baseline"]["transition_sha256"],
    }
    seeds = committed["training_seed_sensitivity"]
    for seed in ("42", "91"):
        expected[f"transition_seed_{seed}.bin"] = seeds[seed]["transition_sha256"]
    table = {"committed": {"gates": gates(committed)}}
    for folder in sorted(WORK.glob("t*_run*")):
        paper = folder / "paper.json"
        digests = {
            name: (folder / name).exists() and compare.sha256(folder / name) == digest
            for name, digest in expected.items()
            if (folder / name).exists()
        }
        metrics = folder / "transition_seed_17.json"
        if not paper.exists():
            # A truncated run (--steps): digests and the selected seed's transition metrics only.
            table[folder.name] = {
                "truncated": True,
                "digests_match": digests,
                "transition_seed_17_metrics": compare.load(metrics)
                if metrics.exists()
                else None,
                "gates": [],
            }
            continue
        report = compare.load(paper)
        table[folder.name] = {
            "digests_match": {
                name: (folder / name).exists()
                and compare.sha256(folder / name) == digest
                for name, digest in expected.items()
            },
            "diff": compare.diff_summary(
                {k: report.get(k) for k in COMPARED_KEYS},
                {k: committed.get(k) for k in COMPARED_KEYS},
                ignore=("transition_sha256",),
            ),
            "gates": gates(report),
            "seconds": compare.load(folder / "run.json")["seconds"]
            if (folder / "run.json").exists()
            else None,
        }
    return {
        "study": "os_world_model_paper",
        "committed_file": "docs/research/world_model_paper_evaluation.json",
        "runs": table,
        "flips": compare.flips(table),
        "closest": compare.closest(table),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("--threads", type=int, required=True)
    r.add_argument("--run", default="run1")
    r.add_argument("--dataset", type=Path, default=SHARED_DATASET)
    r.add_argument(
        "--steps",
        nargs="+",
        help="run only these steps (a truncated run), e.g. jepa_encoder transition_17",
    )
    args = parser.parse_args()
    run(args.threads, args.run, args.dataset, args.steps)


if __name__ == "__main__":
    main()
