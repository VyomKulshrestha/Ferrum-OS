#!/usr/bin/env python3
"""Reproduce missing research checkpoints without editing historical records.

This runs the original training recipe on original development rows only. A byte
digest match is restoration; a merely similar numerical result is a replication.
The distinction is recorded explicitly and must not be silently elided.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import torch

import cross_domain_world_model_models as models
import evaluate_cross_domain_world_models as study


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", choices=["physical", "ferrumos"], required=True)
    parser.add_argument("--method", choices=models.METHODS, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=[17, 43, 101])
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    torch.set_num_threads(args.threads)
    protocol = study.load_json(study.PROTOCOL)
    guard = study.install_final_guard(protocol)
    before = study.verify_digest_map(protocol["protected_deployed_artifacts"])
    assert all(before.values())
    spec, train, validation, _ = (study.os_development if args.domain == "ferrumos" else study.physical_development)(protocol)
    train, validation = models.sequence_data(train, spec), models.sequence_data(validation, spec)
    registered = study.load_json(study.SELECTION)["domains"][args.domain]["methods"][args.method]
    settings = protocol["architecture_controlled_comparison"]["shared_conditions"]
    for seed in args.seeds:
        expected = next(x for x in registered if x["seed"] == seed)
        destination = study.ROOT / expected["checkpoint"]["path"]
        if destination.exists():
            if models.sha256(destination) == expected["checkpoint"]["sha256"]:
                print(json.dumps({"already_restored": str(destination)}), flush=True)
                continue
            raise FileExistsError(destination)
        print(json.dumps({"reproducing": args.domain, "method": args.method, "seed": seed}), flush=True)
        model, metrics = models.fit_model(args.method, spec, train, validation, seed, settings)
        scratch = study.ROOT / "target/incident-dynamics-v1/replication" / args.domain / destination.name
        record = models.save_model(scratch, model, metrics)
        exact = record["sha256"] == expected["checkpoint"]["sha256"]
        expected_metrics = {key: value for key, value in expected.items() if key != "checkpoint"}
        metric_equal = metrics == expected_metrics
        trace_error = float(np.max(np.abs(np.asarray([x["gaussian_nll"] for x in metrics["validation_trace"]]) -
                                         np.asarray([x["gaussian_nll"] for x in expected["validation_trace"]]))))
        report = {"domain": args.domain, "method": args.method, "seed": seed, "threads": args.threads,
                  "byte_identical": exact, "metrics_identical": metric_equal, "max_trace_nll_difference": trace_error,
                  "checkpoint": record, "expected_checkpoint": expected["checkpoint"],
                  "final_access_attempted": guard["attempted"], "promotion_eligible": False}
        if exact:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(scratch.read_bytes())
        study.write_json(scratch.with_suffix(".replication.json"), report)
        print(json.dumps(report), flush=True)
    after = study.verify_digest_map(protocol["protected_deployed_artifacts"])
    assert all(after.values()) and before == after and not guard["attempted"]


if __name__ == "__main__":
    main()
