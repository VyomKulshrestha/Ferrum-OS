#!/usr/bin/env python3
"""Follow-up to options (b)+(c): does a frozen pretrained DINOv2 survive the appearance
shift that takes the from-scratch CNN to chance, and which shift component does the
damage? Branch work, not main. EXPLORATORY (dev seeds, nothing sealed).

Hard scene. Models are trained on CLEAN renders (train seed 0, selection seed 1), plus a
DINOv2 head trained on domain-randomized renders. Each model is tested on paired
renders of the same seed-3 episodes under five looks:
  clean   the training look
  view    only the SHIFT camera offset
  photo   only the SHIFT surface tones + light direction
  sensor  only the SHIFT noise + gamma + blur
  full    the full SHIFT look
Metric: caution AUC-PR / ROC (chance AUC-PR = prevalence), plus recall at a 5% budget
target-calibrated on benign full-SHIFT seed-4 renders.

Usage: python scripts/vision_wm_shift_ablation.py [--smoke]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch

import vision_wm_final_v2 as FV
import vision_wm_pretrained_encoders as PE
import vision_wm_pybullet_data as D
import vision_wm_train as TR

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/research/vision_world_model_shift_ablation_v1.json"
K, H, SIZE, STEPS, FPR = 2, 3, 48, 20, 0.05
LOOK_CLEAN = {"floor": 0.10, "obst": 0.55, "agent": 1.0, "eye_offset": [0, 0, 0],
              "light": [0.2, 0.2, 1.0], "noise": 0.0, "gamma": 1.0, "blur": False}
VARIANTS = {
    "clean": None,
    "view": {**LOOK_CLEAN, "eye_offset": D.SHIFT["eye_offset"]},
    "photo": {**LOOK_CLEAN, **{k: D.SHIFT[k] for k in ("floor", "obst", "agent", "light")}},
    "sensor": {**LOOK_CLEAN, **{k: D.SHIFT[k] for k in ("noise", "gamma", "blur")}},
    "full": D.SHIFT,
}


def render(n, seed, look):
    return D.collect(n, STEPS, SIZE, seed=seed, scene="hard", appearance=look)


def main():
    global OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args()
    nt, ns, nd, epochs = (600, 200, 200, 60) if not a.smoke else (20, 10, 10, 2)
    if a.smoke:
        import tempfile
        OUT = Path(tempfile.mkdtemp(prefix="vwm_ablate_smoke_")) / "result.json"
    t0 = time.time()
    # the explicit clean look must reproduce the default renders, else the ablation is not paired
    f0 = render(2, 3, None)[0]; f1 = render(2, 3, LOOK_CLEAN)[0]
    assert np.allclose(f0, f1, atol=1e-6), "LOOK_CLEAN must equal the default look"

    raw = {"train_clean": render(nt, 0, None), "sel_clean": render(ns, 1, None),
           "train_dr": render(nt, 0, "randomize"), "sel_dr": render(ns, 1, "randomize"),
           "tcal_full": render(ns, 4, D.SHIFT)}
    raw.update({f"test_{v}": render(nd, 3, look) for v, look in VARIANTS.items()})
    idx = {k: PE.labels(v[1], v[2]) for k, v in raw.items()}
    yte = idx["test_clean"][3]
    assert all(np.array_equal(yte, idx[f"test_{v}"][3]) for v in VARIANTS), "test looks must be paired"
    print(f"rendered {sum(len(v[0]) for v in raw.values())} episodes; test prevalence {yte.mean():.3f} "
          f"({round(time.time()-t0)}s)", flush=True)
    res = {}

    def report(name, score_fn, sel_key):
        tcal = score_fn("tcal_full")
        thr = FV.calibrate(tcal, idx["tcal_full"][3], FPR)
        res[name] = {}
        for v in VARIANTS:
            sc = score_fn(f"test_{v}")
            r, f = FV.recall_fpr(sc, yte, thr)
            res[name][v] = {**TR.auc(yte, sc), "target_cal_recall": r, "target_cal_fpr": f}
        print(f"  {name:22s} " + "  ".join(f"{v} {res[name][v]['auc_pr']:.3f}" for v in VARIANTS)
              + f" | full recall@5%(target-cal) {res[name]['full']['target_cal_recall']:.3f}", flush=True)

    # from-scratch CNN, trained clean
    built = {k: TR.build(*raw[k], H, K) for k in raw}
    scores, best_c, *_ = FV.train_vwm(built["train_clean"], built["sel_clean"], epochs=epochs)
    report("scratch_cnn_clean", lambda k: scores(best_c, built[k][0], built[k][1])[1], "sel_clean")

    # frozen pretrained DINOv2 + head, trained clean and trained on randomized renders
    enc = PE.load_dino(True)
    feats = {k: PE.extract(enc, v[0]) for k, v in raw.items()}
    del enc; torch.cuda.empty_cache()
    for regime in ("clean", "dr"):
        score, _ = PE.train_head(feats[f"train_{regime}"], feats[f"sel_{regime}"],
                                 idx[f"train_{regime}"], idx[f"sel_{regime}"], epochs)
        report(f"dinov2_frozen_{regime}", lambda k, s=score: s(feats[k], idx[k]), f"sel_{regime}")

    doc = {"schema_version": "vision-wm-shift-ablation-v1",
           "status": "EXPLORATORY (dev seeds 0/1/3/4, nothing sealed); branch work, not main; advisory only",
           "scene": "hard", "variants": {k: v for k, v in VARIANTS.items() if v is not None},
           "test_prevalence": float(yte.mean()), "results": res}
    OUT.write_text(json.dumps(doc, indent=1, default=float) + "\n", encoding="utf-8")
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
