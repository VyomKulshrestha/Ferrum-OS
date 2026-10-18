#!/usr/bin/env python3
"""Run and retain one incident-dynamics v3 development trial (no final access).

Every trial writes a checkpoint plus a JSON record (settings, trace, validation
scores) under target/incident-dynamics-v3/trials/<domain>/ and appends a line to
the development ledger. Existing trial ids are never overwritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone

import numpy as np
import torch

import evaluate_cross_domain_world_models as architecture
import incident_dynamics_v3_data as v3
import incident_dynamics_v3_dev as dev
import incident_dynamics_v3_models as models

TRIALS = v3.WORK / "trials"
LEDGER = v3.WORK / "development_ledger.jsonl"


def incident_weights(data, factor):
    incident = np.array([e.startswith(("new:", "v3:")) for e in data.episodes])
    weights = np.where(incident, factor, 1.0).astype(np.float64)
    return weights / weights.sum()


def block_weights(data, domain):
    """Sample each training block in inverse proportion to its v2-selected validation error scale,
    so that the loss is aligned with the relative three-block selection metric."""
    reference = dev.reference_scores(domain)
    kinds = np.where([e.startswith("new:") for e in data.episodes], "incident_validation",
                     np.where([e.startswith("v3:") for e in data.episodes], "mech_validation", "legacy_validation"))
    weights = np.asarray([1.0 / reference[k] for k in kinds], np.float64)
    # Equal total mass per block, then inverse error scale within the per-window loss.
    for k in set(kinds):
        weights[kinds == k] /= (kinds == k).sum()
    return weights / weights.sum()


def code_digests():
    names = ["incident_dynamics_v3_data.py", "incident_dynamics_v3_dev.py", "incident_dynamics_v3_models.py",
             "incident_dynamics_v3_trial.py", "incident_dynamics_v3_warning.py", "incident_dynamics_v3_gbr.py",
             "incident_dynamics_v3_scale.py"]
    return {name: hashlib.sha256((v3.ROOT / "scripts" / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest() for name in names}


def run(args):
    guard = architecture.install_final_guard(architecture.load_json(architecture.PROTOCOL))
    folder = TRIALS / args.domain
    folder.mkdir(parents=True, exist_ok=True)
    stem = folder / f"{args.trial_id}-s{args.seed}"
    if stem.with_suffix(".json").exists():
        raise FileExistsError(f"retain existing trial {stem}")
    spec = v3.spec_for(args.domain, args.history)
    train = dev.training_set(args.domain, args.history, include_mechanisms=args.mechanisms)
    validation = dev.combined_validation(args.domain, args.history)
    if args.block_balance:
        weights = block_weights(train, args.domain)
    else:
        weights = None if args.incident_weight == 1 else incident_weights(train, args.incident_weight)
    select_fn = lambda m: dev.selection_score(lambda data: models.predict(m, data), args.domain, args.history)["selection_score"]
    torch.set_num_threads(4)
    trace_lines = []
    if args.curriculum == "rsi" and args.method in ("gbr", "gbr_direct"):
        family = dev.gbr_family(args.trees, args.leaves, args.gbr_lr, direct=args.method == "gbr_direct")
        model, info = dev.rsi_curriculum(args.domain, family, args.seed, rounds=args.rounds,
                                         incident_weight=args.incident_weight, log=lambda line: print(line, flush=True))
        checkpoint = stem.with_suffix(".gbr")
        digest = model.save(checkpoint)
        scores = dev.selection_score(model.predict, args.domain, args.history)
        record = {"trial": args.trial_id, "seed": args.seed, "settings": vars(args), "created_at": datetime.now(timezone.utc).isoformat(),
                  "checkpoint_file": checkpoint.name, "checkpoint_sha256": digest, "scores": scores, "rsi": info,
                  "code_sha256": code_digests(), "final_access_attempted": guard["attempted"]}
        architecture.write_json(stem.with_suffix(".json"), record)
        with LEDGER.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"domain": args.domain, "trial": args.trial_id, "seed": args.seed,
                                     "selection_score": scores["selection_score"],
                                     **{name: scores[name]["relative"] for name in dev.BLOCKS}, "settings": vars(args)}) + chr(10))
        print(json.dumps({"trial": args.trial_id, "seed": args.seed, "selection_score": scores["selection_score"],
                          **{name: scores[name] for name in dev.BLOCKS}}), flush=True)
        return
    if args.method in ("gbr", "gbr_direct"):
        import incident_dynamics_v3_gbr as gbr
        if weights is None:
            weights = np.ones(len(train.states))
        family = gbr.GBRDirect if args.method == "gbr_direct" else gbr.GBRModel
        model = family(args.domain, args.history).fit(train, weights / weights.mean(), args.seed,
                                                              n_estimators=args.trees, learning_rate=args.gbr_lr,
                                                              num_leaves=args.leaves, log=lambda line: None)
        checkpoint = stem.with_suffix(".gbr")
        digest = model.save(checkpoint)
        scores = dev.selection_score(model.predict, args.domain, args.history)
        record = {"trial": args.trial_id, "seed": args.seed, "settings": vars(args), "created_at": datetime.now(timezone.utc).isoformat(),
                  "checkpoint_file": checkpoint.name, "checkpoint_sha256": digest, "scores": scores, "params": model.params,
                  "code_sha256": code_digests(), "final_access_attempted": guard["attempted"]}
        architecture.write_json(stem.with_suffix(".json"), record)
        with LEDGER.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"domain": args.domain, "trial": args.trial_id, "seed": args.seed,
                                     "selection_score": scores["selection_score"],
                                     **{name: scores[name]["relative"] for name in dev.BLOCKS}, "settings": vars(args)}) + "\n")
        if guard["attempted"]:
            raise AssertionError("final access attempted")
        print(json.dumps({"trial": args.trial_id, "seed": args.seed, "selection_score": scores["selection_score"],
                          **{name: scores[name] for name in dev.BLOCKS}}), flush=True)
        return
    if args.curriculum == "rsi":
        family = dev.neural_family(args.method, args.hidden, args.device, args.updates, args.round_updates)
        model, info = dev.rsi_curriculum(args.domain, family, args.seed, rounds=args.rounds,
                                         incident_weight=args.incident_weight, log=lambda line: print(line, flush=True))
    else:
        model, info = models.train(args.method, spec, train, validation, args.seed, updates=args.updates,
                                   batch=args.batch, lr=args.lr, hidden=args.hidden, device=args.device,
                                   weights=weights, log=trace_lines.append, select_fn=select_fn)
    torch.save({"state_dict": model.cpu().state_dict(), "settings": vars(args)}, stem.with_suffix(".pt"))
    model.to(args.device)
    scores = dev.selection_score(lambda data: models.predict(model, data), args.domain, args.history)
    record = {"trial": args.trial_id, "seed": args.seed, "settings": vars(args), "created_at": datetime.now(timezone.utc).isoformat(),
              "checkpoint_sha256": hashlib.sha256(stem.with_suffix(".pt").read_bytes()).hexdigest(),
              "scores": scores, **info, "code_sha256": code_digests(), "final_access_attempted": guard["attempted"]}
    architecture.write_json(stem.with_suffix(".json"), record)
    with LEDGER.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"domain": args.domain, "trial": args.trial_id, "seed": args.seed,
                                 "selection_score": scores["selection_score"],
                                 **{name: scores[name]["relative"] for name in dev.BLOCKS},
                                 "settings": vars(args)}) + "\n")
    if guard["attempted"]:
        raise AssertionError("final access attempted")
    print(json.dumps({"trial": args.trial_id, "seed": args.seed, "selection_score": scores["selection_score"],
                      **{name: scores[name] for name in dev.BLOCKS}}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", choices=["ferrumos", "physical"], required=True)
    parser.add_argument("--trial-id", required=True)
    parser.add_argument("--method", default="ar_residual")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--history", type=int, default=dev.HISTORY)
    parser.add_argument("--hidden", type=int, default=256)
    parser.add_argument("--updates", type=int, default=12000)
    parser.add_argument("--batch", type=int, default=512)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--incident-weight", type=float, default=1.0)
    parser.add_argument("--mechanisms", type=int, default=1)
    parser.add_argument("--block-balance", type=int, default=0)
    parser.add_argument("--trees", type=int, default=600)
    parser.add_argument("--leaves", type=int, default=63)
    parser.add_argument("--gbr-lr", type=float, default=0.05)
    parser.add_argument("--curriculum", choices=["uniform", "rsi"], default="uniform")
    parser.add_argument("--rounds", type=int, default=4)
    parser.add_argument("--round-updates", type=int, default=4000)
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
