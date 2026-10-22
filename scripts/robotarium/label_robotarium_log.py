#!/usr/bin/env python3
"""Label a Robotarium FerrumOS run (ferrum_steps.npy + ferrum_meta.txt) with the runtime's rules.

Poses are converted to runtime metres (divide by the run's scale) and each step gets the
camera-visible terms of train_physical_world_model.is_dangerous, as in the runtime-scene
proxy (scripts/vision_runtime_domain_render.py):
  moving and clearance_next < 0.16   clearance = centre distance - 0.16 (runtime metres)
  or geofence margin_next < 0        margin = 1 - max(|x|, |y|)
Contact cannot occur on the Robotarium (the testbed rejects close approaches and the
experiment keeps robot 0 at least d_min away), so it is never a label here.

Decision points t = 1..steps-1 per episode; caution target = any hazard in steps t..t+2.

Usage: python scripts/robotarium/label_robotarium_log.py <run_dir> [--out labels.npz]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

H = 3


def label(run_dir):
    run_dir = Path(run_dir)
    meta = json.loads((run_dir / "ferrum_meta.txt").read_text(encoding="utf-8"))
    rows = np.load(run_dir / "ferrum_steps.npy")
    col = {c: i for i, c in enumerate(meta["step_columns"])}
    n_ep, steps, scale = meta["episodes"], meta["steps"], meta["scale"]
    if len(rows) != n_ep * steps:
        raise ValueError(f"expected {n_ep * steps} step rows, found {len(rows)} (run incomplete?)")
    rows = rows.reshape(n_ep, steps, -1)
    kind = rows[:, :, col["kind"]].astype(int)
    feats = rows[:, :, [col["f0"], col["f1"], col["f2"]]]
    end = rows[:, :, [col["r0x_end"], col["r0y_end"]]] / scale
    obs = rows[:, :, [col["obs_x"], col["obs_y"]]] / scale
    clearance = np.clip(np.hypot(*(end - obs).transpose(2, 0, 1)) - 0.16, 0, 1)
    margin = 1.0 - np.abs(end).max(2)
    moving = (kind == 0) & (feats[:, :, 2] > 0.1)
    prox = moving & (clearance < 0.16)
    geo = margin < 0
    hazards = np.zeros((n_ep, steps + 1), np.int8)
    hazards[:, 1:] = prox | geo
    e, t = np.meshgrid(np.arange(n_ep), np.arange(1, steps), indexing="ij")
    e, t = e.ravel(), t.ravel()
    window = lambda a: np.array([int(a[i, j + 1:j + 1 + H].any()) for i, j in zip(e, t)], np.int8)
    pad = lambda a: np.concatenate([np.zeros((n_ep, 1), a.dtype), a], 1)
    return {"e": e, "t": t, "y": window(hazards), "kind": kind[e, t], "features": feats[e, t],
            "hazards": hazards, "proximity": window(pad(prox)), "geofence": window(pad(geo)),
            "clearance": clearance, "margin": margin, "min_centre_dist_m": rows[:, :, col["min_centre_dist"]],
            "it_end": rows[:, :, col["it_end"]].astype(int), "meta": meta}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--out")
    a = ap.parse_args()
    lab = label(a.run_dir)
    y = lab["y"]
    print(f"{len(y)} decisions, caution prevalence {y.mean():.3f}; proximity {lab['proximity'].mean():.3f}, "
          f"geofence {lab['geofence'].mean():.3f}; per-step hazard rate {lab['hazards'][:, 1:].mean():.3f}; "
          f"closest approach {lab['min_centre_dist_m'].min():.3f} m")
    if a.out:
        np.savez_compressed(a.out, **{k: v for k, v in lab.items() if k != "meta"}, meta=json.dumps(lab["meta"]))
        print("wrote", a.out)


if __name__ == "__main__":
    main()
