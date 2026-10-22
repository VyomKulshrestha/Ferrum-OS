#!/usr/bin/env python3
"""Option (c): a concrete step toward real data -- domain randomization vs a held-out
appearance shift. Branch work, not main. EXPLORATORY (dev seeds, nothing sealed).

Real cameras differ from the clean renders in appearance (lighting, surface tones,
viewpoint, noise, blur). Before any real footage, two things can be measured in sim:
  1. ranking robustness: does the caution model still rank hazards when the look shifts?
  2. calibration transfer: does a false-alarm budget calibrated in sim hold under the shift,
     and does re-calibrating on benign target-domain footage restore it?

Hard (occluded) scene. Appearance (scripts/vision_wm_pybullet_data.py):
  clean      = the fixed look of increments 1-3
  randomize  = per-episode colours, camera jitter, light, noise, gamma, blur
  SHIFT      = a fixed look OUTSIDE the randomization ranges on several axes (pseudo-real)
Seeds: train 0, selection 1, test 3 (clean and SHIFT renders of the SAME episodes, so the
shift effect is paired), target-domain benign calibration 4 (SHIFT). Not sealed seeds.

Models: from-scratch CNN (vision_wm_final_v2.train_vwm) and the pixel linear probe, each
trained on clean vs randomized data. Thresholds at FPR 0.05: sim-calibrated (own selection
split) vs target-calibrated (benign steps of seed-4 SHIFT renders).

Usage: python scripts/vision_wm_domain_shift.py [--smoke]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression

import vision_wm_final_v2 as FV
import vision_wm_pybullet_data as D
import vision_wm_train as TR

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/research/vision_world_model_domain_shift_v1.json"
K, H, SIZE, STEPS, FPR = 2, 3, 48, 20, 0.05


def load(n, seed, appearance):
    f, a, h = D.collect(n, STEPS, SIZE, seed=seed, scene="hard", appearance=appearance)
    return TR.build(f, a, h, H, K)


def at(scores, y, thr):
    r, f = FV.recall_fpr(scores, y, thr)
    return {"recall": r, "realized_fpr": f}


def main():
    global OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args()
    nt, ns, nd, epochs = (600, 200, 200, 60) if not a.smoke else (20, 10, 10, 2)
    if a.smoke:
        import tempfile
        OUT = Path(tempfile.mkdtemp(prefix="vwm_shift_smoke_")) / "result.json"
    t0 = time.time()
    data = {("train", "clean"): load(nt, 0, None), ("train", "dr"): load(nt, 0, "randomize"),
            ("sel", "clean"): load(ns, 1, None), ("sel", "dr"): load(ns, 1, "randomize"),
            ("test", "clean"): load(nd, 3, None), ("test", "shift"): load(nd, 3, D.SHIFT),
            ("tcal", "shift"): load(ns, 4, D.SHIFT)}
    yte = data[("test", "clean")][3]
    assert np.array_equal(yte, data[("test", "shift")][3]), "clean/shift test must be paired"
    tcal = data[("tcal", "shift")]
    print(f"hard scene: train {len(data[('train','clean')][3])} x2 looks, test {len(yte)} (paired clean/shift), "
          f"prevalence test {yte.mean():.3f} ({round(time.time()-t0)}s)", flush=True)

    flat = lambda c, ac: np.concatenate([c.reshape(len(c), -1), TR.onehot(ac)], 1)
    res, test_scores = {}, {}
    for regime in ("clean", "dr"):
        tr, se = data[("train", regime)], data[("sel", regime)]
        t1 = time.time()
        scores, best_c, _, params, _ = FV.train_vwm(tr, se, epochs=epochs)
        cnn = lambda d, s=scores, b=best_c: s(b, d[0], d[1])[1]
        lp = LogisticRegression(max_iter=400, C=0.5, class_weight="balanced").fit(flat(tr[0], tr[1]), tr[3])
        probe = lambda d, m=lp: m.predict_proba(flat(d[0], d[1]))[:, 1]
        for kind, fn in (("cnn", cnn), ("probe", probe)):
            name = f"{kind}_trained_{regime}"
            thr_sim = FV.calibrate(fn(se), se[3], FPR)
            thr_tgt = FV.calibrate(fn(tcal), tcal[3], FPR)
            res[name] = {}
            for dom in ("clean", "shift"):
                sc = fn(data[("test", dom)])
                test_scores[(name, dom)] = (sc, thr_tgt)
                res[name][dom] = {**TR.auc(yte, sc), "sim_calibrated": at(sc, yte, thr_sim),
                                  "target_calibrated": at(sc, yte, thr_tgt)}
            c, s = res[name]["clean"], res[name]["shift"]
            print(f"  {name:20s} AUC-PR clean {c['auc_pr']:.3f} -> shift {s['auc_pr']:.3f} | shift FPR "
                  f"sim-cal {s['sim_calibrated']['realized_fpr']:.3f} vs target-cal {s['target_calibrated']['realized_fpr']:.3f} "
                  f"| shift recall (target-cal) {s['target_calibrated']['recall']:.3f}", flush=True)
        res[f"cnn_trained_{regime}"]["seconds"] = round(time.time() - t1)

    # Does domain randomization buy recall under the shift at a held budget? Paired over hazard steps.
    (sd, td), (sc_, tc) = test_scores[("cnn_trained_dr", "shift")], test_scores[("cnn_trained_clean", "shift")]
    boot = FV.boot_recall_diff(sd, sc_, yte, td, tc)
    res["dr_vs_clean_cnn_shift_recall_targetcal"] = boot
    print(f"  CNN shift recall, DR - clean (target-calibrated): {boot['recall_difference']:+.3f} CI95 {boot['ci95']}", flush=True)

    doc = {"schema_version": "vision-wm-domain-shift-v1",
           "status": "EXPLORATORY (dev seeds 0/1/3/4, nothing sealed); branch work, not main; advisory only",
           "scene": "hard", "calibration_fpr": FPR, "dr_ranges": D.DR_RANGES, "shift": D.SHIFT,
           "test_prevalence": float(yte.mean()), "results": res,
           "note": "SHIFT is a synthetic pseudo-real look outside the randomization ranges, not real footage. "
                   "Target-calibration uses benign steps of a separate SHIFT seed, mirroring 'calibrate on real benign footage'."}
    OUT.write_text(json.dumps(doc, indent=1, default=float) + "\n", encoding="utf-8")
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
