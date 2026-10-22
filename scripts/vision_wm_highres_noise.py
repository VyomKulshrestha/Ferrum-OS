#!/usr/bin/env python3
"""Step 2: does frozen pretrained DINOv2 recover under sensor noise at a higher native
camera resolution? Branch work, not main. EXPLORATORY (dev seeds, nothing sealed).

The shift ablation (vision_world_model_shift_ablation_v1.json) found DINOv2 robust to
viewpoint and lighting but hurt by sensor degradation (noise 0.06, gamma 1.5, 3x3 blur)
on 48 px renders, where the agent is ~4 px wide. Hypothesis: with the same per-pixel
sensor model at a higher native resolution the agent spans more pixels, noise averages
out inside each 14 px DINOv2 patch, and the sensor penalty shrinks.

Hard scene. Same seeds at every resolution, so geometry, actions and hazards are paired
across resolutions; only the render size changes. Per resolution: train seed 0 (600 ep,
clean), selection seed 1 (200, clean), test seed 3 under clean / sensor-only / full SHIFT,
target-calibration seed 4 (full SHIFT, benign steps). DINOv2 input is resized to 224 at
every resolution. Frames are stored as float16 to fit host RAM.

Usage: python scripts/vision_wm_highres_noise.py [--sizes 48 112] [--smoke]
"""
from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

import numpy as np
import torch

import vision_wm_final_v2 as FV
import vision_wm_pretrained_encoders as PE
import vision_wm_pybullet_data as D
import vision_wm_shift_ablation as SA
import vision_wm_train as TR

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/research/vision_world_model_highres_noise_v1.json"
STEPS, FPR = 20, 0.05
LOOKS = {"clean": None, "sensor": SA.VARIANTS["sensor"], "full": D.SHIFT}


def render(n, seed, size, look):
    f, a, h = D.collect(n, STEPS, size, seed=seed, scene="hard", appearance=look)
    return f.astype(np.float16), a, h


_CPU_ENC = None


def repair_nonfinite(feat, path, n, seed, size, look, act, haz):
    """This laptop GPU occasionally returns NaN for a frame without raising. Recompute any
    non-finite frames on the CPU from a deterministic re-render, patch the cache, log it."""
    global _CPU_ENC
    bad = np.argwhere(~np.isfinite(feat.astype(np.float32)).reshape(feat.shape[0], feat.shape[1], -1).all(-1))
    if not len(bad):
        return feat
    import datetime
    from huggingface_hub import hf_hub_download
    from safetensors.torch import load_file
    if _CPU_ENC is None:
        _CPU_ENC = PE.DinoV2Small()
        _CPU_ENC.load_state_dict(load_file(hf_hub_download("facebook/dinov2-small", "model.safetensors")), strict=True)
        _CPU_ENC.eval()
    fr, a2, h2 = render(n, seed, size, look)
    assert np.array_equal(a2, act) and np.array_equal(h2, haz), "re-render must reproduce the cached episodes"
    feat = feat.copy()
    with torch.no_grad():
        for e, t in bad:
            x = torch.from_numpy(fr[e, t].astype(np.float32))[None, None].repeat(1, 3, 1, 1)
            x = (torch.nn.functional.interpolate(x, size=(224, 224), mode="bilinear", align_corners=False) - PE.MEAN) / PE.STD
            feat[e, t] = torch.nn.functional.adaptive_avg_pool2d(_CPU_ENC(x), 4)[0].half().numpy()
    assert np.isfinite(feat.astype(np.float32)).all()
    tmp = path.with_name(path.stem + ".tmp.npz")
    np.savez(tmp, feat=feat, a=act, h=haz)
    tmp.replace(path)
    with open(ROOT / "target/vision-wm/infrastructure_failures.jsonl", "a", encoding="utf-8") as log:
        log.write(json.dumps({"at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                              "script": "scripts/vision_wm_highres_noise.py", "error": "silent GPU NaN output (no exception)",
                              "frames": bad.tolist(), "file": path.name, "action": "recomputed those frames on CPU and patched the cache"}) + "\n")
    print(f"  repaired {len(bad)} non-finite frame(s) in {path.name} on CPU", flush=True)
    return feat


def main():
    global OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", type=int, nargs="+", default=[48, 112])
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args()
    nt, ns, nd, epochs = (600, 200, 200, 60) if not a.smoke else (16, 8, 8, 2)
    if a.smoke:
        import tempfile
        OUT = Path(tempfile.mkdtemp(prefix="vwm_hires_smoke_")) / "result.json"
    # Per-(size, split) feature cache: this laptop GPU faults intermittently, so a crash
    # loses one split and a rerun resumes. Renders are deterministic per seed.
    cache = Path(tempfile.mkdtemp(prefix="vwm_hires_cache_")) if a.smoke else ROOT / "target/vision-wm/highres_cache"
    cache.mkdir(parents=True, exist_ok=True)
    splits = {"train": (nt, 0, None), "sel": (ns, 1, None), "tcal": (ns, 4, D.SHIFT)}
    splits.update({f"test_{k}": (nd, 3, look) for k, look in LOOKS.items()})
    enc = None
    res, labels_ref = {}, None
    for size in a.sizes:
        t0 = time.time()
        feats, idx = {}, {}
        for key, (n, seed, look) in splits.items():
            f = cache / f"s{size}_{key}_n{n}.npz"
            if not f.exists():
                if enc is None:
                    enc = PE.load_dino(True)
                fr, act, haz = render(n, seed, size, look)
                feat = PE.extract(enc, fr).cpu().numpy()
                tmp = f.with_name(f.stem + ".tmp.npz")
                np.savez(tmp, feat=feat, a=act, h=haz)
                tmp.replace(f)
                del fr
            with np.load(f, allow_pickle=False) as z:   # close the handle before any repair rewrite (Windows)
                feat, act, haz = z["feat"], z["a"], z["h"]
            feat = repair_nonfinite(feat, f, n, seed, size, look, act, haz)
            feats[key] = torch.from_numpy(feat).to(PE.DEV)
            idx[key] = PE.labels(act, haz)
        y = idx["test_clean"][3]
        if labels_ref is None:
            labels_ref = y
        assert np.array_equal(y, labels_ref), "labels must be identical across resolutions (paired)"
        score, sel_ap = PE.train_head(feats["train"], feats["sel"], idx["train"], idx["sel"], epochs)
        thr = FV.calibrate(score(feats["tcal"], idx["tcal"]), idx["tcal"][3], FPR)
        res[size] = {"selection_auc_pr": sel_ap}
        for k in LOOKS:
            sc = score(feats[f"test_{k}"], idx[f"test_{k}"])
            r, f = FV.recall_fpr(sc, y, thr)
            res[size][k] = {**TR.auc(y, sc), "target_cal_recall": r, "target_cal_fpr": f}
        del feats; torch.cuda.empty_cache()
        print(f"  size {size:3d}: AUC-PR clean {res[size]['clean']['auc_pr']:.3f}  sensor {res[size]['sensor']['auc_pr']:.3f}  "
              f"full {res[size]['full']['auc_pr']:.3f} | full recall@5% (target-cal) {res[size]['full']['target_cal_recall']:.3f} "
              f"fpr {res[size]['full']['target_cal_fpr']:.3f} ({round(time.time()-t0)}s)", flush=True)
    doc = {"schema_version": "vision-wm-highres-noise-v1",
           "status": "EXPLORATORY (dev seeds 0/1/3/4, nothing sealed); branch work, not main; advisory only",
           "scene": "hard", "sizes": a.sizes, "test_prevalence": float(labels_ref.mean()),
           "sensor_model": {k: D.SHIFT[k] for k in ("noise", "gamma", "blur")}, "results": res}
    OUT.write_text(json.dumps(doc, indent=1, default=float) + "\n", encoding="utf-8")
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
