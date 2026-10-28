#!/usr/bin/env python3
"""Registered study C: camera-tracked positions fed to a state model, tested on fresh real
Robotarium runs (docs/research/vision_caution_robotarium_protocol_v4.json). Branch work, not main.

Arms (identical sealed decisions):
  track_state        boosted trees on camera_track.state_features from camera-tracked positions,
                     trained on all spent runs (PRIMARY)
  action_only        logistic regression on the 10-dim action, all spent runs (control)
  finetune_head_v3   the frozen study-B fine-tuned DINOv2 head, not retrained (secondary comparison)
  state_true         boosted trees on true positions, all spent runs (descriptive reference)
Thresholds (track_state, action_only, state_true): the 0.95 quantile of hazard-free out-of-fold
scores, cross-fitted leave-one-batch-out over the spent runs (batch = hundreds digit of the seed);
each deployed model is then refit on all spent runs. finetune_head_v3 keeps its v3 threshold
(descriptive only). Models and thresholds are written and hashed before the sealed runs are
ledgered and scored once. CPU only.

Gates: G1 recall(track_state) - recall(action_only) CI95 lower bound > 0; G2 track_state realized
false-alarm rate <= 0.10; G3 track_state recall CI95 lower bound >= 0.30; primary = G1 and G2 and G3.
S1 (secondary): AUC-PR(track_state) - AUC-PR(finetune_head_v3) CI95 lower bound > 0. Episode-cluster
bootstrap, 10000 replicates, seed 0.

Usage:
  CUDA_VISIBLE_DEVICES=-1 python scripts/robotarium/study_c.py --dry-run
  CUDA_VISIBLE_DEVICES=-1 python scripts/robotarium/study_c.py --smoke    # spent runs 711/712 as 'sealed', temp ledger
  CUDA_VISIBLE_DEVICES=-1 python scripts/robotarium/study_c.py            # the registered final (opens once)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(HERE))

PROTOCOL = ROOT / "docs/research/vision_caution_robotarium_protocol_v4.json"
OUT = ROOT / "docs/research/vision_caution_robotarium_result_v4.json"
ART_DIR = ROOT / "docs/research/artifacts/vision-caution-tracking-v1"
RUNS = ROOT / "target/robotarium/runs"
HEAD = ROOT / "docs/research/artifacts/vision-caution-arena-v1/sim_finetune_head.npz"
HEAD_THR = ROOT / "docs/research/artifacts/vision-caution-arena-v1/thresholds.json"
HEAD_SHA = "d32cf20957f29e2fae477c7fa5860ee046b0206dc812e4fb1d9ae4f54785e86a"
LEDGER_KEY = "robotarium-sealed-v4"
AUTHORITY = "advisory diagnostic only; no permit, block, approval, adapter or actuation authority"
Q, BUDGET, FLOOR, REPS = 0.05, 0.10, 0.30, 10000
KEEP = ("kinds", "features", "hazards", "clearance", "margin", "contact", "robot_xy", "obstacle_xy")
CODE = ("scripts/robotarium/study_c.py", "scripts/robotarium/camera_track.py")
ARMS_FIT = ("track_state", "action_only", "state_true")


def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def sha256_text(p):
    """Line-ending independent (the checkout may convert LF to CRLF)."""
    return hashlib.sha256(Path(p).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def load_runs(names):
    """Quality-gated runs (protocol v2 amendment 1: no processed frames fails) with tracked positions."""
    import camera_track as CT
    import evaluate_real as ER
    runs, qual = {}, {}
    for n in names:
        p = RUNS / n
        if not ((p / "camera.json").exists() and (p / "frames.npz").exists()):
            qual[n] = {"passes": False, "reason": "no processed frames (video_frames.py failed)"}
            continue
        ok, q = ER.quality(p)
        qual[n] = {**q, "passes": bool(ok)}
        if not ok:
            continue
        d = np.load(p / "frames.npz")
        tr = CT.track(d["inspect"])
        runs[n] = {**{k: d[k] for k in KEEP}, **{f"trk_{k}": v for k, v in tr.items()}}
    return runs, qual


def concat(runs, names):
    parts = [runs[n] for n in names]
    return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}


def features(d, i):
    import camera_track as CT
    import vision_runtime_proxy_final as RP
    return {"track_state": CT.state_features(d["trk_robot"], d["trk_obstacle"], i),
            "action_only": i["a10"], "state_true": RP.state_features(d, i)}


def fit(d, i):
    from sklearn.ensemble import HistGradientBoostingClassifier as HGB
    from sklearn.linear_model import LogisticRegression
    X = features(d, i)
    return {"track_state": HGB(random_state=0).fit(X["track_state"], i["y"]),
            "action_only": LogisticRegression(max_iter=1000, C=1.0, class_weight="balanced").fit(X["action_only"], i["y"]),
            "state_true": HGB(random_state=0).fit(X["state_true"], i["y"])}


def score(models, d, i):
    X = features(d, i)
    return {k: models[k].predict_proba(X[k])[:, 1] for k in ARMS_FIT}


def recall_boot(hit, y, ep, n_ep, reps=REPS, seed=0):
    """Episode-cluster bootstrap of one arm's recall (positives inside resampled episodes)."""
    pos = y == 1
    nh = np.bincount(ep[pos], weights=hit[pos].astype(np.float64), minlength=n_ep)
    npos = np.bincount(ep[pos], minlength=n_ep).astype(np.float64)
    if npos.sum() == 0:
        return {"recall": None, "ci95": [None, None], "episodes": int(n_ep), "positives": 0}
    idx = np.random.default_rng(seed).integers(0, n_ep, (reps, n_ep))
    den = npos[idx].sum(1)
    r = nh[idx].sum(1) / np.maximum(den, 1.0)
    return {"recall": float(nh.sum() / npos.sum()), "ci95": [float(np.quantile(r, 0.025)), float(np.quantile(r, 0.975))],
            "episodes": int(n_ep), "positives": int(npos.sum()), "replicates_without_positives": int((den == 0).sum())}


def head_scores(names, d, i):
    """Frozen study-B fine-tuned head (logits) on the given runs' 256 px frames, in the same decision order."""
    import torch
    import vision_runtime_proxy_final as RP
    import vision_wm_pretrained_encoders as PE
    if sha256_file(HEAD) != HEAD_SHA:
        raise SystemExit("REFUSE: the frozen study-B head changed")
    pool = json.loads(HEAD_THR.read_text(encoding="utf-8"))["pool"]
    z = np.load(HEAD)
    head = RP.make_head(pool, 10)
    head.load_state_dict({k[5:]: torch.from_numpy(z[k]) for k in z.files if k.startswith("head.")})
    head.eval()
    enc = PE.load_dino(True).cpu()
    ins = np.concatenate([np.load(RUNS / n / "frames.npz")["inspect"] for n in names]).astype(np.float32) / 255.0
    Fx = RP.extract(enc, ins, pools=(pool,))
    return RP.score_head(head, Fx[pool], i, i["a10"])


def main():
    global OUT, ART_DIR
    import torch
    import study_b as SB
    import vision_runtime_proxy_final as RP
    import vision_wm_final_v2 as FV
    import vision_wm_train as TR

    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args()
    proto = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    runs_p = proto["runs"]
    spent = [f"seed{s}" for s in runs_p["spent_real_seeds"]]
    sealed = [f"seed{s}" for s in runs_p["sealed_seeds"]]
    registered = proto.get("registered_at") is not None and not proto["status"].startswith("DRAFT")
    code_ok = {c: sha256_text(ROOT / c) == proto.get("code_sha256", {}).get(c) for c in CODE}
    if a.dry_run:
        print("protocol:", "registered " + str(proto.get("registered_at")) if registered else "DRAFT (final refuses)")
        print("primary:", proto["gates"]["primary_success"])
        print("code sha256 matches protocol:", code_ok)
        print("spent present:", sum((RUNS / n / "frames.npz").exists() for n in spent), "of", len(spent))
        print("sealed present:", [n for n in sealed if (RUNS / n / "frames.npz").exists()])
        print("ledger:", "ALREADY opened -> REFUSE" if FV.ledger_has(LEDGER_KEY) else "not yet opened -> eligible")
        return
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "-1":
        raise SystemExit("REFUSE: CPU only; set CUDA_VISIBLE_DEVICES=-1")
    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "8")))
    if a.smoke:
        tmp = Path(tempfile.mkdtemp(prefix="vc_rbt4_smoke_"))
        FV.LEDGER, OUT, ART_DIR = tmp / "ledger.jsonl", tmp / "result.json", tmp / "artifact"
        sealed = ["seed711", "seed712"]
        spent = [n for n in spent if n not in sealed]
        print("SMOKE: spent runs 711/712 as 'sealed', temp ledger/artifact ->", tmp)
    else:
        if not registered:
            raise SystemExit("REFUSE: protocol v4 is not registered")
        if not all(code_ok.values()):
            raise SystemExit(f"REFUSE: code differs from the registered sha256: {code_ok}")
    if FV.ledger_has(LEDGER_KEY):
        raise SystemExit(f"REFUSE: {LEDGER_KEY} already in {FV.LEDGER}")
    t0 = time.time()

    # --- spent runs: tracking, cross-fitted thresholds, deployed models ---
    sp, sp_qual = load_runs(spent)
    batches = {}
    for n in sp:
        batches.setdefault(n[4], []).append(n)
    oof = {k: [] for k in ARMS_FIT}
    oof_y, oof_b = [], []
    for b in sorted(batches):
        train = [n for c in sorted(batches) if c != b for n in batches[c]]
        dtr, dte = concat(sp, train), concat(sp, batches[b])
        itr, ite = RP.decisions(dtr), RP.decisions(dte)
        s = score(fit(dtr, itr), dte, ite)
        for k in ARMS_FIT:
            oof[k].append(s[k])
        oof_y.append(ite["y"])
        oof_b.append(np.full(len(ite["y"]), int(b)))
    oof = {k: np.concatenate(v) for k, v in oof.items()}
    oof_y, oof_b = np.concatenate(oof_y), np.concatenate(oof_b)
    thr = {k: FV.calibrate(oof[k], oof_y, Q) for k in ARMS_FIT}
    oof_fpr = {k: {b: float((oof[k][(oof_b == int(b)) & (oof_y == 0)] > thr[k]).mean()) for b in sorted(batches)}
               for k in ARMS_FIT}
    oof_auc = {k: TR.auc(oof_y, oof[k]) for k in ARMS_FIT}
    dsp = concat(sp, list(sp))
    isp = RP.decisions(dsp)
    models = fit(dsp, isp)
    head_thr = json.loads(HEAD_THR.read_text(encoding="utf-8"))["thresholds"]["vision_sim_finetune"]
    print(f"spent: {len(sp)} runs, {len(oof_y)} decisions; out-of-fold AUC-PR "
          f"{json.dumps({k: round(v['auc_pr'], 3) for k, v in oof_auc.items()})}; thresholds {json.dumps(thr)} "
          f"({round(time.time() - t0)}s)", flush=True)

    # --- persist models and thresholds BEFORE the open ---
    ART_DIR.mkdir(parents=True, exist_ok=True)
    for k in ARMS_FIT:
        with open(ART_DIR / f"{k}.pkl", "wb") as h:
            pickle.dump(models[k], h, protocol=4)
    meta = {"schema": "FERRUM_VISION_CAUTION_TRACKING_V1", "authority": AUTHORITY, "protocol": PROTOCOL.name,
            "thresholds_prob": thr, "q": Q, "rule": "0.95 quantile of hazard-free out-of-fold scores, leave-one-batch-out",
            "out_of_fold_auc": oof_auc, "out_of_fold_fpr_by_batch": oof_fpr, "spent_runs": list(sp),
            "spent_quality": sp_qual, "head_v3": {"sha256": HEAD_SHA, "threshold_logit": head_thr},
            "code_sha256_lf": {c: sha256_text(ROOT / c) for c in CODE},
            "qualification": "decided by docs/research/vision_caution_robotarium_result_v4.json; never live use"}
    (ART_DIR / "thresholds.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    hashes = {n: sha256_file(ART_DIR / n) for n in [f"{k}.pkl" for k in ARMS_FIT] + ["thresholds.json"]}
    print(f"persisted {json.dumps({k: v[:12] for k, v in hashes.items()})} ({round(time.time() - t0)}s)", flush=True)

    # --- SINGLE OPEN ---
    FV.record_final(LEDGER_KEY, "vision-caution Robotarium v4 (study C): camera-tracked state model, sealed runs scored once (CPU)")
    sd, sd_qual = load_runs(sealed)
    if not sd:
        raise SystemExit("no sealed run passed the quality gate (recorded in the ledger; nothing scored)")
    names = list(sd)
    dsd = concat(sd, names)
    isd = RP.decisions(dsd)
    fin = score(models, dsd, isd)
    fin["finetune_head_v3"] = head_scores(names, dsd, isd)
    thr_all = {**thr, "finetune_head_v3": head_thr}
    y, ep, n_ep = isd["y"], isd["e"], len(dsd["kinds"])
    res, hits = {}, {}
    for m, s in fin.items():
        r, f = FV.recall_fpr(s, y, thr_all[m])
        hr, hf = FV.recall_fpr(s, y, FV.calibrate(s, y, BUDGET))
        res[m] = {**TR.auc(y, s), "threshold": thr_all[m], "recall": r, "realized_fpr": f,
                  "hindsight_recall_at_fpr_0.10": hr, "hindsight_fpr": hf}
        hits[m] = s > thr_all[m]
    g1b = RP.cluster_boot(hits["track_state"], hits["action_only"], y, ep, n_ep)
    g3b = recall_boot(hits["track_state"], y, ep, n_ep)
    s1b = SB.auc_pr_boot(fin["track_state"], fin["finetune_head_v3"], y, ep, n_ep)
    g1 = (g1b["ci95"][0] or 0) > 0
    g2 = res["track_state"]["realized_fpr"] <= BUDGET
    g3 = g3b["ci95"][0] is not None and g3b["ci95"][0] >= FLOOR
    gates = {"G1_track_beats_action_only": bool(g1), "G2_budget_holds": bool(g2), "G3_useful_recall": bool(g3),
             "primary_success": bool(g1 and g2 and g3), "S1_track_beats_finetune_head": bool((s1b["ci95"][0] or 0) > 0)}
    by_type = {m: {k: {"positives": int(v.sum()), "recall": float(hits[m][v == 1].mean()) if v.sum() else None}
                   for k, v in isd["types"].items()} for m in fin}
    er = np.hypot(*(dsd["trk_robot"] - dsd["robot_xy"]).reshape(-1, 2).T)          # after scoring, descriptive
    eo = np.hypot(*(dsd["trk_obstacle"] - dsd["obstacle_xy"][:, None, :]).reshape(-1, 2).T)
    tracking = {"robot_err_rt_median": float(np.median(er)), "robot_err_rt_p90": float(np.quantile(er, 0.9)),
                "obstacle_wrong_frac": float(np.mean(eo > 0.1)), "robot_seen_frac": float(dsd["trk_robot_seen"].mean())}
    print(f"\nFINAL Robotarium v4 sealed: {len(y)} decisions, {n_ep} episodes, prevalence {y.mean():.3f}; "
          f"runs passing the gate: {names}")
    for m, r in res.items():
        print(f"  {m:17s} AUC-PR {r['auc_pr']:.3f} ROC {r['auc_roc']:.3f} | recall {r['recall']:.3f} at realized FPR "
              f"{r['realized_fpr']:.3f} | hindsight recall at FPR 0.10: {r['hindsight_recall_at_fpr_0.10']:.3f}")
    print(f"  G1 recall difference {g1b['recall_difference']} CI95 {g1b['ci95']}")
    print(f"  G3 track_state recall {g3b['recall']} CI95 {g3b['ci95']} (floor {FLOOR})")
    print(f"  S1 AUC-PR difference {s1b['auc_pr_difference']} CI95 {s1b['ci95']}")
    print(f"  recall by hazard type: {json.dumps({m: {k: v['recall'] for k, v in t.items()} for m, t in by_type.items()})}")
    print(f"  tracking on sealed runs: {json.dumps(tracking)}")
    print("  gates:", json.dumps(gates))
    rel = lambda p: str(p if a.smoke else Path(p).relative_to(ROOT)).replace("\\", "/")
    doc = {"schema_version": "vision-caution-robotarium-result-v4", "protocol": PROTOCOL.name,
           "status": "registered final (study C) on real Robotarium robots and camera, opened once; camera-tracked "
                     "positions fed to a state model; branch work (not main); advisory only",
           "sealed_runs": sealed, "sealed_quality": sd_qual, "decisions": int(len(y)), "episodes": int(n_ep),
           "prevalence": float(y.mean()), "artifacts": {rel(ART_DIR / k): v for k, v in hashes.items()},
           "thresholds": thr_all, "out_of_fold_auc": oof_auc, "out_of_fold_fpr_by_batch": oof_fpr,
           "results": res, "G1_bootstrap": g1b, "G3_bootstrap": g3b, "S1_bootstrap": s1b, "gates": gates,
           "recall_by_hazard_type": by_type, "tracking_on_sealed": tracking,
           "code_sha256_lf": {q: sha256_text(ROOT / q) for q in CODE + ("scripts/robotarium/video_frames.py",
                                                                         "scripts/robotarium/label_robotarium_log.py",
                                                                         "scripts/robotarium/ferrum_experiment.py")}}
    OUT.write_text(json.dumps(doc, indent=1, default=float) + "\n", encoding="utf-8")
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
