#!/usr/bin/env python3
"""EXPLORATORY design check before registering the real-trained study: leave-runs-out
cross-validation on the ten SPENT black-fence runs (201-204, 301-306, already opened by
protocol v1). Compares frame resolution (64 px model frames vs the 256 px inspection
frames video_frames.py also writes) and pooling for a head trained on real frames,
against the action-only control and the true-geometry reference. No future sealed seed
is touched. Output: docs/research/vision_caution_robotarium_devcv_v1.json.

Usage: CUDA_VISIBLE_DEVICES=-1 python scripts/robotarium/dev_cv_real.py
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

import train_eval_real as TE  # noqa: E402

OUT = ROOT / "docs/research/vision_caution_robotarium_devcv_v1.json"
FOLDS = [(["seed201", "seed301"], "seed202"), (["seed202", "seed302"], "seed203"), (["seed203", "seed303"], "seed204"),
         (["seed204", "seed304"], "seed305"), (["seed305", "seed306"], "seed201")]
RUNS = [f"seed{s}" for s in (201, 202, 203, 204, 301, 302, 303, 304, 305, 306)]


def main():
    import torch
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression

    import vision_runtime_proxy_final as RP
    import vision_wm_pretrained_encoders as PE
    import vision_wm_train as TR

    if os.environ.get("CUDA_VISIBLE_DEVICES") != "-1":
        raise SystemExit("CPU only; set CUDA_VISIBLE_DEVICES=-1")
    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "8")))
    t0 = time.time()
    enc = PE.load_dino(True).cpu()
    data, feats = {}, {}
    for r in RUNS:
        d = dict(np.load(TE.RUNS / r / "frames.npz"))
        data[r] = d
        feats[(r, 64)] = RP.extract(enc, d["frames"])
        feats[(r, 256)] = RP.extract(enc, d["inspect"].astype(np.float32) / 255.0)
    print(f"features for {len(RUNS)} runs at 64 and 256 px ({round(time.time() - t0)}s)", flush=True)

    def cat(rs, res=None, pool=None):
        d = {k: np.concatenate([data[r][k] for r in rs]) for k in TE.KEYS}
        if res is None:
            return d
        return d, torch.cat([feats[(r, res)][pool] for r in rs])

    pooled = {}
    for test, sel in FOLDS:
        train = [r for r in RUNS if r not in test and r != sel]
        dtr, dse, dte = cat(train), cat([sel]), cat(test)
        itr, ise, ite = RP.decisions(dtr), RP.decisions(dse), RP.decisions(dte)
        add = lambda name, s: pooled.setdefault(name, []).append((ite["y"], s))
        for res in (64, 256):
            for pool in (4, 8):
                Ftr = cat(train, res, pool)[1]
                Fse = cat([sel], res, pool)[1]
                Fte = cat(test, res, pool)[1]
                head, _ = TE.train_head(Ftr, Fse, itr, ise, itr["a10"], ise["a10"], pool, TE.EPOCHS)
                add(f"vision_real_{res}px_pool{pool}", RP.score_head(head, Fte, ite, ite["a10"]))
        act = LogisticRegression(max_iter=1000, C=1.0, class_weight="balanced").fit(itr["a10"], itr["y"])
        add("action_only", act.predict_proba(ite["a10"])[:, 1])
        st = HistGradientBoostingClassifier(random_state=0).fit(RP.state_features(dtr, itr), itr["y"])
        add("state_reference", st.predict_proba(RP.state_features(dte, ite))[:, 1])
        print(f"fold test={test} done ({round(time.time() - t0)}s)", flush=True)

    res = {}
    for name, parts in pooled.items():
        y = np.concatenate([p[0] for p in parts])
        # AUC-PR within each fold (scores are not calibrated across folds), averaged; plus per-fold list
        per_fold = [TR.auc(p[0], p[1])["auc_pr"] for p in parts]
        res[name] = {"auc_pr_mean_over_folds": float(np.mean(per_fold)), "auc_pr_per_fold": per_fold,
                     "prevalence": float(y.mean())}
    base = float(np.mean([p[0].mean() for p in pooled["action_only"]]))
    doc = {"schema_version": "vision-caution-robotarium-devcv-v1",
           "status": "EXPLORATORY design check on spent runs (201-204, 301-306); informs the v2 protocol; not evidence",
           "folds": [{"test": t, "selection": s} for t, s in FOLDS], "mean_base_rate": base, "results": res}
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"\nmean fold base rate {base:.3f}")
    for name, r in sorted(res.items(), key=lambda kv: -kv[1]["auc_pr_mean_over_folds"]):
        print(f"  {name:26s} AUC-PR {r['auc_pr_mean_over_folds']:.3f}  per fold {[round(v, 2) for v in r['auc_pr_per_fold']]}")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
