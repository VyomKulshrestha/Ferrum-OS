#!/usr/bin/env python3
"""Where does the thread-count dependence of the physical-JEPA trainer enter? (fi1 B3, exploratory)

1. Each matrix-product shape of ``train_physical_jepa.train`` (batch 1024, latent 128, hidden 256)
   and the reductions it uses, computed at several BLAS thread counts in one process
   (threadpoolctl), compared bit for bit.
2. The trainer itself for a few hundred epochs at two thread counts: the first epoch at which the
   weights differ and how the difference grows; and the same at one thread twice.

    python scripts/fi1_thread_where.py --threads 1 4            # no lock needed
    python scripts/fi1_thread_where.py --threads 1 4 24         # holds the machine lock (24 > 4)

Writes target/fi1-pipeline3/where_<threads>.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import threadpoolctl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import repro_env  # noqa: E402


def shapes(latent=128, hidden=256, batch=1024, state=16, actions=10):
    """(name, left shape, right shape) of every product in one training step."""
    pin = latent + actions
    return [
        ("forward encoder: state @ W", (batch, state), (state, latent)),
        ("forward predictor 1: input @ W1", (batch, pin), (pin, hidden)),
        ("forward predictor 2: hidden @ W2", (batch, hidden), (hidden, latent)),
        ("forward state head: latent @ Ws", (batch, latent), (latent, state)),
        ("gradient W1: input.T @ g", (pin, batch), (batch, hidden)),
        ("gradient W2: hidden.T @ g", (hidden, batch), (batch, latent)),
        ("gradient encoder: state.T @ g", (state, batch), (batch, latent)),
        ("backprop: g @ W2.T", (batch, latent), (latent, hidden)),
        ("backprop: g @ W1.T", (batch, hidden), (hidden, pin)),
    ]


def product_check(thread_counts: list[int]) -> list[dict]:
    rng = np.random.default_rng(7)
    out = []
    for name, left, right in shapes():
        a = rng.standard_normal(left).astype(np.float32)
        b = rng.standard_normal(right).astype(np.float32)
        results = {}
        for n in thread_counts:
            with threadpoolctl.threadpool_limits(limits=n, user_api="blas"):
                results[n] = a @ b
        ref = results[thread_counts[0]]
        out.append(
            {
                "product": name,
                "shape": [list(left), list(right)],
                "bit_identical_to_first": {
                    str(n): bool(np.array_equal(results[n], ref)) for n in thread_counts
                },
                "max_abs_difference": {
                    str(n): float(np.max(np.abs(results[n] - ref)))
                    for n in thread_counts
                },
            }
        )
    a = rng.standard_normal((1024, 256)).astype(np.float32)
    sums = {}
    for n in thread_counts:
        with threadpoolctl.threadpool_limits(limits=n, user_api="blas"):
            sums[n] = a.sum(axis=0)
    out.append(
        {
            "product": "reduction: g.sum(axis=0) (NumPy pairwise, no BLAS)",
            "bit_identical_to_first": {
                str(n): bool(np.array_equal(sums[n], sums[thread_counts[0]]))
                for n in thread_counts
            },
        }
    )
    return out


def training_divergence(thread_counts: list[int], epochs: int) -> dict:
    """Train the registered v3 shapes for ``epochs`` steps; compare weights every 25 epochs."""
    import train_physical_jepa as jepa
    import train_physical_world_model as simulator

    rows = simulator.generate(1200, 8, 20260824)
    _, _, train_rows, validation_rows, _ = jepa.split_rows(rows, 1200, 20260824)
    snapshots = {}
    original = jepa.validation_metrics

    for label, n in [
        *((str(n), n) for n in thread_counts),
        (f"{thread_counts[0]}-repeat", thread_counts[0]),
    ]:
        trace = []

        def recording(*args, _trace=trace, **kwargs):
            weights = args[4]
            _trace.append(np.concatenate([w.ravel() for w in weights.values()]).copy())
            return original(*args, **kwargs)

        jepa.validation_metrics = recording
        try:
            with threadpoolctl.threadpool_limits(limits=n, user_api="blas"):
                jepa.train(
                    train_rows,
                    validation_rows,
                    latent=128,
                    hidden=256,
                    epochs=epochs,
                    seed=91,
                )
        finally:
            jepa.validation_metrics = original
        snapshots[label] = trace
    ref = snapshots[str(thread_counts[0])]
    out = {"epochs": epochs, "checkpoints_every": 25, "comparisons": {}}
    for label, trace in snapshots.items():
        if label == str(thread_counts[0]):
            continue
        rel = [
            float(np.linalg.norm(x - y) / np.linalg.norm(y)) for x, y in zip(trace, ref)
        ]
        first = next((25 * (i + 1) for i, r in enumerate(rel) if r > 0), None)
        out["comparisons"][f"{label} vs {thread_counts[0]}"] = {
            "first_checkpoint_with_any_difference": first,
            "relative_weight_difference_by_checkpoint": rel,
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threads", type=int, nargs="+", default=[1, 4])
    parser.add_argument("--epochs", type=int, default=400)
    args = parser.parse_args()
    result = {
        "products": product_check(args.threads),
        "training": training_divergence(args.threads, args.epochs),
        "environment": repro_env.environment_record(),
    }
    out = (
        ROOT
        / "target"
        / "fi1-pipeline3"
        / f"where_{'_'.join(map(str, args.threads))}.json"
    )
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for p in result["products"]:
        print(p["product"], p["bit_identical_to_first"], p.get("max_abs_difference"))
    for k, v in result["training"]["comparisons"].items():
        r = v["relative_weight_difference_by_checkpoint"]
        print(
            k,
            "first diff at epoch",
            v["first_checkpoint_with_any_difference"],
            "rel diff",
            [f"{x:.1e}" for x in r[::4]],
        )


if __name__ == "__main__":
    main()
