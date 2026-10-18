#!/usr/bin/env python3
"""Attach learned warning-scale models to a finished GBR trial as a new development configuration.

The parent's mean forecast is reused unchanged (so its selection score is unchanged); only the
uncertainty used by the warning score is added. Training windows only; no final access.
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone

import numpy as np

import evaluate_cross_domain_world_models as architecture
import incident_dynamics_v3_data as v3
import incident_dynamics_v3_dev as dev
import incident_dynamics_v3_gbr as gbr
import incident_dynamics_v3_trial as trial


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent", required=True, help="trial JSON path relative to the trials folder")
    parser.add_argument("--trial-id", required=True)
    args = parser.parse_args()
    guard = architecture.install_final_guard(architecture.load_json(architecture.PROTOCOL))
    parent_path = v3.WORK / "trials" / args.parent
    parent = architecture.load_json(parent_path)
    settings = dict(parent["settings"])
    domain, seed = settings["domain"], settings["seed"]
    checkpoint = parent_path.parent / parent["checkpoint_file"]
    if hashlib.sha256(checkpoint.read_bytes()).hexdigest() != parent["checkpoint_sha256"]:
        raise AssertionError("parent checkpoint drift")
    stem = parent_path.parent / f"{args.trial_id}-s{seed}"
    if stem.with_suffix(".json").exists():
        raise FileExistsError(stem)
    train = dev.training_set(domain, settings["history"], include_mechanisms=bool(settings.get("mechanisms", 1)))
    weights = trial.incident_weights(train, settings.get("incident_weight", 1.0))
    model = gbr.ScaledGBR(gbr.load_any(checkpoint)).fit_scale(train, weights / weights.mean(), seed)
    path = stem.with_suffix(".gbr")
    digest = model.save(path)
    scores = dev.selection_score(model.predict, domain, settings["history"])
    settings.update({"trial_id": args.trial_id, "parent_trial": args.parent, "scale_model": True})
    record = {"trial": args.trial_id, "seed": seed, "settings": settings, "created_at": datetime.now(timezone.utc).isoformat(),
              "checkpoint_file": path.name, "checkpoint_sha256": digest, "scores": scores, "scale_params": model.params,
              "parent_checkpoint_sha256": parent["checkpoint_sha256"], "code_sha256": trial.code_digests(),
              "final_access_attempted": guard["attempted"]}
    architecture.write_json(stem.with_suffix(".json"), record)
    with trial.LEDGER.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"domain": domain, "trial": args.trial_id, "seed": seed, "selection_score": scores["selection_score"],
                                 **{name: scores[name]["relative"] for name in dev.BLOCKS}, "settings": settings}) + "\n")
    if guard["attempted"]:
        raise AssertionError("final access attempted")
    print(json.dumps({"trial": args.trial_id, "seed": seed, "selection_score": scores["selection_score"]}))


if __name__ == "__main__":
    main()
