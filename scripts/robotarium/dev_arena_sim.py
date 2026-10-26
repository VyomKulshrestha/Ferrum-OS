#!/usr/bin/env python3
"""EXPLORATORY design check for study B (sim proxy re-rendered with the Robotarium's look):
which way of rendering the arena look lets a head trained ONLY in simulation transfer to
real frames? Scored on the SPENT real runs (every run of protocols v1/v2 that passes the
quality gate); the study's own sealed runs will be fresh seeds. Not evidence.

Variants (all from vision_runtime_domain_render.collect(look="arena"), 256 px):
  flat        the measured arena colours, flat lit
  randomized  flat + per-episode brightness/contrast/gamma jitter, a random linear lighting
              gradient, Gaussian sensor noise and occasional blur
  composite   simulated robots and obstacle disc pasted onto the real empty-arena background
              (median of real rectified frames, so tile seams, vignetting, the camera's dark
              border and the fence line are the real ones), plus the randomized jitter
Each variant: frozen DINOv2 head (vision_runtime_proxy_final.train_head, pooling 4/8 by sim
selection AUC-PR), then zero-shot on real frames. Reference: action-only trained on the
same sim decisions. Output docs/research/vision_caution_arena_sim_devcheck_v1.json.

Usage: CUDA_VISIBLE_DEVICES=-1 python scripts/robotarium/dev_arena_sim.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(HERE))

import evaluate_real as ER  # noqa: E402

OUT = ROOT / "docs/research/vision_caution_arena_sim_devcheck_v1.json"
RUNS = ROOT / "target/robotarium/runs"
SIZE, N_TRAIN, N_SEL = 256, 400, 150
REAL_KEYS = ("frames", "inspect", "kinds", "features", "hazards", "clearance", "margin", "contact", "robot_xy",
             "obstacle_xy")


def real_dev_runs():
    out = []
    for p in sorted(RUNS.glob("seed*")):
        if p.name == "seed101" or not ((p / "camera.json").exists() and (p / "frames.npz").exists()):
            continue
        ok, _ = ER.quality(p)
        if ok:
            out.append(p.name)
    return out


def real_background(names):
    """Median of real rectified frames: the empty arena with its real seams, light and border."""
    stack = np.concatenate([np.load(RUNS / n / "frames.npz")["inspect"][:, ::4].reshape(-1, SIZE, SIZE) for n in names])
    return (np.median(stack, 0) / 255.0).astype(np.float32)


def randomize(frames, rng):
    """Per-episode photometric jitter around the measured look (frames: (n, T, s, s) in [0,1])."""
    out = np.empty_like(frames)
    s = frames.shape[-1]
    yy, xx = np.mgrid[0:s, 0:s] / (s - 1) - 0.5
    for e in range(len(frames)):
        gain, bias, gamma = rng.uniform(0.85, 1.15), rng.uniform(-0.06, 0.06), rng.uniform(0.85, 1.2)
        gx, gy = rng.uniform(-0.12, 0.12, 2)
        f = np.clip(frames[e] * gain + bias + gx * xx + gy * yy, 0, 1) ** gamma
        f = f + rng.normal(0, rng.uniform(0.0, 0.03), f.shape)
        if rng.random() < 0.5:
            import cv2
            f = np.stack([cv2.GaussianBlur(x, (0, 0), rng.uniform(0.5, 1.5)) for x in f])
        out[e] = np.clip(f, 0, 1)
    return out.astype(np.float32)


def composite(frames, bg):
    """Paste everything that is not flat floor or fence (robots and disc) onto the real background."""
    import vision_runtime_domain_render as R
    floor, fence = R.ARENA["floor"], R.ARENA["fence"]
    keep = (np.abs(frames - floor) > 0.02) & (np.abs(frames - fence) > 0.02)
    return np.where(keep, frames, bg[None, None]).astype(np.float32)


def main():
    import torch
    from sklearn.linear_model import LogisticRegression

    import train_eval_real as TE
    import vision_runtime_domain_render as R
    import vision_runtime_proxy_final as RP
    import vision_wm_pretrained_encoders as PE
    import vision_wm_train as TR

    if os.environ.get("CUDA_VISIBLE_DEVICES") != "-1":
        raise SystemExit("CPU only; set CUDA_VISIBLE_DEVICES=-1")
    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "8")))
    t0 = time.time()
    names = real_dev_runs()
    real = {k: np.concatenate([np.load(RUNS / n / "frames.npz")[k] for n in names]) for k in REAL_KEYS}
    ireal = RP.decisions(real)
    bg = real_background(names)
    enc = PE.load_dino(True).cpu()
    Freal = RP.extract(enc, real["inspect"].astype(np.float32) / 255.0)
    print(f"real dev: {len(names)} runs, {len(ireal['y'])} decisions, prevalence {ireal['y'].mean():.3f} "
          f"({round(time.time() - t0)}s)", flush=True)

    sim_tr = R.collect(N_TRAIN, seed=950, size=SIZE, look="arena")
    sim_se = R.collect(N_SEL, seed=951, size=SIZE, look="arena")
    itr, ise = RP.decisions(sim_tr), RP.decisions(sim_se)
    print(f"sim arena renders: train {len(itr['y'])} / selection {len(ise['y'])} decisions ({round(time.time() - t0)}s)",
          flush=True)
    act = LogisticRegression(max_iter=1000, C=1.0, class_weight="balanced").fit(itr["a10"], itr["y"])
    res = {"action_only_sim_trained": TR.auc(ireal["y"], act.predict_proba(ireal["a10"])[:, 1])}
    rng = np.random.default_rng(0)
    for variant in ("flat", "randomized", "composite"):
        ftr, fse = sim_tr["frames"], sim_se["frames"]
        if variant == "randomized":
            ftr, fse = randomize(ftr, rng), randomize(fse, rng)
        elif variant == "composite":
            ftr, fse = randomize(composite(ftr, bg), rng), randomize(composite(fse, bg), rng)
        Ftr, Fse = RP.extract(enc, ftr), RP.extract(enc, fse)
        best = None
        for pool in (4, 8):
            head, sel_ap = TE.train_head(Ftr[pool], Fse[pool], itr, ise, itr["a10"], ise["a10"], pool, 60)
            if best is None or sel_ap > best[2]:
                best = (pool, head, sel_ap)
        pool, head, sel_ap = best
        s = RP.score_head(head, Freal[pool], ireal, ireal["a10"])
        res[variant] = {**TR.auc(ireal["y"], s), "pool": pool, "sim_selection_auc_pr": sel_ap}
        print(f"  {variant:10s} pool {pool}: sim sel AUC-PR {sel_ap:.3f} -> REAL zero-shot AUC-PR "
              f"{res[variant]['auc_pr']:.3f} ROC {res[variant]['auc_roc']:.3f} ({round(time.time() - t0)}s)", flush=True)
        del Ftr, Fse
    doc = {"schema_version": "vision-caution-arena-sim-devcheck-v1",
           "status": "EXPLORATORY design check on spent real runs; informs the study-B protocol; not evidence",
           "real_dev_runs": names, "real_decisions": int(len(ireal["y"])), "real_prevalence": float(ireal["y"].mean()),
           "sim": {"look": "arena", "size": SIZE, "train": [950, N_TRAIN], "selection": [951, N_SEL]},
           "results": res}
    OUT.write_text(json.dumps(doc, indent=1, default=float) + "\n", encoding="utf-8")
    print(f"\nbase rate {ireal['y'].mean():.3f}; action-only (sim-trained) AUC-PR {res['action_only_sim_trained']['auc_pr']:.3f}")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
