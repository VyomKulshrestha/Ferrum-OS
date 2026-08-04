#!/usr/bin/env python3
"""Validation-only capacity/seed sweep for the runtime transition MLP."""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def csv_ints(value):
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--out", default="target/world_model_learned.bin")
    parser.add_argument("--metrics-out", default="target/world_model_tuning_metrics.json")
    parser.add_argument("--hidden", default="128,256,384")
    parser.add_argument("--seeds", default="17,42,91")
    parser.add_argument("--epochs", type=int, default=800)
    parser.add_argument("--lr", type=float, default=0.05)
    parser.add_argument("--patience", type=int, default=8)
    parser.add_argument("--min-train-per-tool", type=int, default=24)
    parser.add_argument("--require-covered-tools", type=int, default=41)
    args = parser.parse_args()
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    candidates = []
    trainer = Path(__file__).with_name("train_world_model.py")
    for hidden in csv_ints(args.hidden):
        for seed in csv_ints(args.seeds):
            stem = output.parent / f"world_model_candidate_h{hidden}_s{seed}"
            weights = stem.with_suffix(".bin")
            metrics_path = stem.with_suffix(".json")
            command = [
                sys.executable, str(trainer), "--dataset", args.dataset,
                "--out", str(weights), "--metrics-out", str(metrics_path),
                "--hidden", str(hidden), "--seed", str(seed),
                "--epochs", str(args.epochs), "--lr", str(args.lr),
                "--patience", str(args.patience), "--max-rollout-horizon", "5",
                "--min-train-per-tool", str(args.min_train_per_tool),
                "--require-covered-tools", str(args.require_covered_tools),
            ]
            print(f"[tune] hidden={hidden} seed={seed}")
            result = subprocess.run(command, check=False)
            if result.returncode != 0:
                candidates.append({"hidden": hidden, "seed": seed, "accepted": False})
                continue
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            validation = metrics["validation"]
            h3 = metrics["validation_rollout"].get("3", {}).get("mse")
            score = validation["macro_tool_mse"] + validation["core_mse"] + (h3 or 1.0)
            candidates.append({
                "hidden": hidden, "seed": seed, "accepted": True, "score": score,
                "weights": str(weights), "metrics": metrics,
            })
    accepted = [candidate for candidate in candidates if candidate["accepted"]]
    if not accepted:
        sys.exit("no capacity candidate passed training acceptance")
    best = min(accepted, key=lambda candidate: candidate["score"])
    shutil.copyfile(best["weights"], output)
    report = {
        "schema_version": 1,
        "selection_rule": "validation macro_tool_mse + core_mse + H3 rollout_mse",
        "selected": {key: best[key] for key in ("hidden", "seed", "score", "metrics")},
        "candidates": [
            {key: value for key, value in candidate.items() if key != "metrics"}
            for candidate in candidates
        ],
    }
    Path(args.metrics_out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"[tune] selected hidden={best['hidden']} seed={best['seed']} score={best['score']:.8f}")
    print(f"[tune] wrote {output} and {args.metrics_out}")


if __name__ == "__main__":
    main()
