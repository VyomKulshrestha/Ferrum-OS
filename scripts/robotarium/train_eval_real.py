#!/usr/bin/env python3
"""Registered real-footage study: a vision caution head TRAINED on real Robotarium frames
(docs/research/vision_caution_robotarium_protocol_v2.json). Branch work, not main.

Everything is trained, selected and calibrated on the train and selection runs; the
selected head and every arm's threshold are written to disk and hashed; only then are the
sealed runs recorded in the access ledger and scored, once. CPU only.

Arms (identical decisions):
  vision_real          head trained on real frames over frozen DINOv2 (PRIMARY); pooling 4 or 8
                       chosen by selection AUC-PR
  vision_sim_finetune  the sim-trained v2 head fine-tuned on the same real frames (secondary)
  pixel_probe          logistic regression on the raw 2x64x64 frame stack + action (secondary)
  action_only          logistic regression on the 10-dim runtime action (control)
  state_reference      boosted trees on true geometry + action (descriptive)
All trained on the real train runs only.

Usage:
  CUDA_VISIBLE_DEVICES=-1 python scripts/robotarium/train_eval_real.py --dry-run
  CUDA_VISIBLE_DEVICES=-1 python scripts/robotarium/train_eval_real.py --smoke   # existing runs only, temp ledger
  CUDA_VISIBLE_DEVICES=-1 python scripts/robotarium/train_eval_real.py           # the registered final (opens once)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tools" / "vision_caution"))
sys.path.insert(0, str(HERE))

PROTOCOL = ROOT / "docs/research/vision_caution_robotarium_protocol_v2.json"
OUT = ROOT / "docs/research/vision_caution_robotarium_result_v2.json"
ART_DIR = ROOT / "docs/research/artifacts/vision-caution-robotarium-v1"
SIM_ARTIFACT = ROOT / "docs/research/artifacts/vision-caution-v2/selected_caution_head.npz"
SIM_ARTIFACT_SHA = "77e3ea1ed04421818e1efd6aa4b216b92b75b224c1f13e18e307345fc040042f"
RUNS = ROOT / "target/robotarium/runs"
LEDGER_KEY = "robotarium-sealed-v2"
AUTHORITY = "advisory diagnostic only; no permit, block, approval, adapter or actuation authority"
PRIMARY_FPR, BUDGET, EPOCHS = 0.05, 0.10, 60
KEYS = ("frames", "inspect", "kinds", "features", "hazards", "clearance", "margin", "contact", "robot_xy", "obstacle_xy")
# encoder input for the real-trained heads, pinned by the protocol: "frames" = the 64x64 model frames
# (the proxy's format), "inspect" = the 256x256 rectified frames video_frames.py also writes
ENCODER_FRAMES = "inspect"


def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load_split(names, gate):
    """Concatenate the runs' episodes into one dataset (episode ids stay unique)."""
    import evaluate_real as ER
    parts, qual, run_of_ep = [], {}, []
    for name in names:
        if not ((RUNS / name / "camera.json").exists() and (RUNS / name / "frames.npz").exists()):
            # amendment 1: no processed frames (e.g. the testbed's video was truncated) fails the gate
            qual[name] = {"passes": False, "reason": "no processed frames (video_frames.py failed)"}
            continue
        ok, q = ER.quality(RUNS / name)
        qual[name] = {**q, "passes": ok}
        if gate and not ok:
            continue
        d = np.load(RUNS / name / "frames.npz")
        parts.append({k: d[k] for k in KEYS})
        run_of_ep += [name] * len(d["kinds"])
    if not parts:
        return None, qual, []
    return {k: np.concatenate([p[k] for p in parts]) for k in KEYS}, qual, run_of_ep


def train_head(Ftr, Fse, itr, ise, Atr, Ase, pool, epochs, init=None, lr=1e-3, seed=0):
    """vision_runtime_proxy_final.train_head with an optional initial state and learning rate."""
    import torch
    import torch.nn.functional as F
    from sklearn.metrics import average_precision_score

    import vision_runtime_proxy_final as RP
    torch.manual_seed(seed)
    head = RP.make_head(pool, Atr.shape[1])
    if init is not None:
        head.load_state_dict(init, strict=True)
    e, t = torch.from_numpy(itr["e"]), torch.from_numpy(itr["t"])
    a = torch.from_numpy(Atr.astype(np.float32))
    ytr = itr["y"]
    yt = torch.from_numpy(ytr.astype(np.float32))
    pw = torch.tensor([max(1.0, float((ytr == 0).sum()) / max(1.0, float(ytr.sum())))])
    opt = torch.optim.AdamW(head.parameters(), lr, weight_decay=1e-4)
    gen = torch.Generator().manual_seed(seed)
    head.eval()
    best_ap = average_precision_score(ise["y"], RP.score_head(head, Fse, ise, Ase)) if init is not None else -1.0
    best = {k: v.detach().clone() for k, v in head.state_dict().items()} if init is not None else None
    pat = 0
    for _ in range(epochs):
        head.train()
        for b in torch.randperm(len(ytr), generator=gen).split(256):
            opt.zero_grad(set_to_none=True)
            F.binary_cross_entropy_with_logits(RP.head_forward(head, Ftr, e[b], t[b], a[b]), yt[b], pos_weight=pw).backward()
            opt.step()
        head.eval()
        ap = average_precision_score(ise["y"], RP.score_head(head, Fse, ise, Ase))
        if ap > best_ap + 1e-5:
            best_ap, best, pat = ap, {k: v.detach().clone() for k, v in head.state_dict().items()}, 0
        else:
            pat += 1
            if pat >= 8:
                break
    head.load_state_dict(best)
    return head.eval(), float(best_ap)


def main():
    global OUT, ART_DIR
    import torch
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression

    import vision_runtime_proxy_final as RP
    import vision_wm_final_v2 as FV
    import vision_wm_pretrained_encoders as PE
    import vision_wm_train as TR
    from vision_caution import load_artifact

    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args()
    proto = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    names = {k: [f"seed{s}" for s in proto["runs"][k]] for k in ("train_seeds", "selection_seeds", "sealed_seeds")}
    if a.dry_run:
        print("primary:", proto["gates"]["primary_success"])
        for k, v in names.items():
            print(f"{k}: present {[n for n in v if (RUNS / n / 'frames.npz').exists()]} of {len(v)}")
        print("ledger:", "ALREADY opened -> REFUSE" if FV.ledger_has(LEDGER_KEY) else "not yet opened -> eligible")
        return
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "-1":
        raise SystemExit("REFUSE: CPU only; set CUDA_VISIBLE_DEVICES=-1")
    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "8")))
    epochs = EPOCHS
    if a.smoke:
        tmp = Path(tempfile.mkdtemp(prefix="vc_rbt2_smoke_"))
        FV.LEDGER, OUT, ART_DIR = tmp / "ledger.jsonl", tmp / "result.json", tmp / "artifact"
        names = {"train_seeds": ["seed201", "seed202", "seed203", "seed301", "seed302", "seed303"],
                 "selection_seeds": ["seed204", "seed304"], "sealed_seeds": ["seed305", "seed306"]}
        epochs = 3
        print("SMOKE: existing runs only, temp ledger/artifact/out ->", tmp)
    if FV.ledger_has(LEDGER_KEY):
        raise SystemExit(f"REFUSE: {LEDGER_KEY} already in {FV.LEDGER}")
    t0 = time.time()

    # --- train + selection runs only ---
    tr, tr_qual, _ = load_split(names["train_seeds"], gate=True)
    se, se_qual, _ = load_split(names["selection_seeds"], gate=True)
    itr, ise = RP.decisions(tr), RP.decisions(se)
    print(f"train {len(itr['y'])} decisions ({len(tr['kinds'])} episodes), selection {len(ise['y'])} "
          f"({len(se['kinds'])} episodes); prevalence {itr['y'].mean():.3f} / {ise['y'].mean():.3f}", flush=True)
    from huggingface_hub import hf_hub_download
    wsha = sha256_file(hf_hub_download("facebook/dinov2-small", "model.safetensors"))
    sim = load_artifact(SIM_ARTIFACT, SIM_ARTIFACT_SHA)
    if wsha != sim["encoder_sha256"]:
        raise SystemExit("REFUSE: DINOv2 weights differ from the recorded encoder digest")
    enc = PE.load_dino(True).cpu()
    enc_in = lambda d: d[ENCODER_FRAMES].astype(np.float32) / (255.0 if ENCODER_FRAMES == "inspect" else 1.0)
    Ftr, Fse = RP.extract(enc, enc_in(tr)), RP.extract(enc, enc_in(se))
    Fsim_tr, Fsim_se = RP.extract(enc, tr["frames"], pools=(4,)), RP.extract(enc, se["frames"], pools=(4,))
    print(f"DINOv2 features ({round(time.time() - t0)}s)", flush=True)

    cands = {pool: train_head(Ftr[pool], Fse[pool], itr, ise, itr["a10"], ise["a10"], pool, epochs) for pool in (4, 8)}
    for pool, (_, apv) in cands.items():
        print(f"  vision_real pool {pool}: selection AUC-PR {apv:.3f}", flush=True)
    pool = max(cands, key=lambda p: cands[p][1])
    head_real, sel_ap_real = cands[pool]
    init = {k: torch.from_numpy(v) for k, v in sim["weights"].items()}
    # the sim head was trained on 64 px frames, so it is fine-tuned on 64 px features whatever ENCODER_FRAMES is
    head_ft, sel_ap_ft = train_head(Fsim_tr[4], Fsim_se[4], itr, ise, itr["a10"], ise["a10"], 4, epochs, init=init, lr=1e-4)
    flat = lambda d, i: np.concatenate([np.stack([d["frames"][i["e"], i["t"] - 1], d["frames"][i["e"], i["t"]]], 1)
                                        .reshape(len(i["e"]), -1), i["a10"]], 1)
    probe = LogisticRegression(max_iter=400, C=0.5, class_weight="balanced").fit(flat(tr, itr), itr["y"])
    act = LogisticRegression(max_iter=1000, C=1.0, class_weight="balanced").fit(itr["a10"], itr["y"])
    state = HistGradientBoostingClassifier(random_state=0).fit(RP.state_features(tr, itr), itr["y"])

    def scores(d, i, Fx, Fsim):
        return {"vision_real": RP.score_head(head_real, Fx[pool], i, i["a10"]),
                "vision_sim_finetune": RP.score_head(head_ft, Fsim[4], i, i["a10"]),
                "pixel_probe": probe.predict_proba(flat(d, i))[:, 1],
                "action_only": act.predict_proba(i["a10"])[:, 1],
                "state_reference": state.predict_proba(RP.state_features(d, i))[:, 1]}

    sel = scores(se, ise, Fse, Fsim_se)
    thr = {m: FV.calibrate(s, ise["y"], PRIMARY_FPR) for m, s in sel.items()}
    sel_ap = {m: TR.auc(ise["y"], s)["auc_pr"] for m, s in sel.items()}
    print(f"frozen before open: pool {pool}; selection AUC-PR {json.dumps({m: round(v, 3) for m, v in sel_ap.items()})}", flush=True)

    # --- persist the selected head and all thresholds BEFORE the open ---
    platt = LogisticRegression(C=1e6).fit(sel["vision_real"].reshape(-1, 1), ise["y"])
    ART_DIR.mkdir(parents=True, exist_ok=True)
    art_path = ART_DIR / "selected_caution_head.npz"
    meta = {"schema": "FERRUM_VISION_CAUTION_V2", "authority": AUTHORITY, "protocol": [PROTOCOL.name],
            "encoder": {"name": "facebook/dinov2-small", "weights_sha256": wsha,
                        "input": "grey frame replicated to RGB, bilinear to 224x224, ImageNet mean/std",
                        "pooling": f"patch-token map adaptive-avg-pooled to {pool}x{pool}, fp16"},
            "pool": pool, "frame_size": 256 if ENCODER_FRAMES == "inspect" else 64, "frame_stack": 2, "horizon_steps": 3,
            "action_space": {"kind": "runtime PhysicalAction", "names": ["move", "inspect", "diagnose", "approve",
                                                                           "repair", "verify", "stop"],
                             "feature_size": 3, "encoding": "one-hot over the 7 kinds + the 3 raw features"},
            "scene": "Georgia Tech Robotarium overhead camera, rectified to runtime |x|,|y| <= 1.5 (scripts/robotarium/video_frames.py)",
            "trained_on": names["train_seeds"], "selected_on": names["selection_seeds"],
            "thresholds_logit": {"fpr_0.05": thr["vision_real"], "fpr_0.10": FV.calibrate(sel["vision_real"], ise["y"], BUDGET)},
            "platt": {"coef": float(platt.coef_[0, 0]), "intercept": float(platt.intercept_[0]),
                      "fitted_on": "selection-run logits, before the sealed open"},
            "selection_auc_pr": sel_ap_real,
            "qualification": "decided by docs/research/vision_caution_robotarium_result_v2.json; never live use"}
    arrays = {f"head.{k}": v.detach().cpu().numpy().astype(np.float32) for k, v in head_real.state_dict().items()}
    np.savez_compressed(art_path, metadata=json.dumps(meta, sort_keys=True), **arrays)
    thr_path = ART_DIR / "thresholds.json"
    thr_path.write_text(json.dumps({"thresholds": thr, "selection_auc_pr": sel_ap, "pool": pool,
                                    "train_quality": tr_qual, "selection_quality": se_qual}, indent=1) + "\n", encoding="utf-8")
    art_sha, thr_sha = sha256_file(art_path), sha256_file(thr_path)
    print(f"persisted head {art_sha[:16]}... and thresholds {thr_sha[:16]}... ({round(time.time() - t0)}s)", flush=True)

    # --- SINGLE OPEN ---
    FV.record_final(LEDGER_KEY, "vision-caution Robotarium v2: real-trained head, sealed runs scored once (CPU)")
    sd, sd_qual, run_of_ep = load_split(names["sealed_seeds"], gate=True)
    if sd is None:
        raise SystemExit("no sealed run passed the quality gate (recorded in the ledger; nothing scored)")
    isd = RP.decisions(sd)
    fin = scores(sd, isd, RP.extract(enc, enc_in(sd), pools=(pool,)), RP.extract(enc, sd["frames"], pools=(4,)))
    y, ep = isd["y"], isd["e"]
    n_ep = len(sd["kinds"])
    res = {}
    for m, s in fin.items():
        r, f = FV.recall_fpr(s, y, thr[m])
        res[m] = {**TR.auc(y, s), "recall": r, "realized_fpr": f}
    hits = {m: fin[m] > thr[m] for m in fin}
    boot = {f"vision_real_minus_{b}": RP.cluster_boot(hits["vision_real"], hits[b], y, ep, n_ep)
            for b in ("action_only", "pixel_probe", "vision_sim_finetune")}
    beats = lambda b: (res["vision_real"]["auc_pr"] > res[b]["auc_pr"] and res["vision_real"]["recall"] > res[b]["recall"]
                       and (boot[f"vision_real_minus_{b}"]["ci95"][0] or 0) > 0)
    g1, g2 = beats("action_only"), res["vision_real"]["realized_fpr"] <= BUDGET
    gates = {"G1_camera_beats_action_only": bool(g1), "G2_budget_holds": bool(g2), "primary_success": bool(g1 and g2),
             "S1_beats_pixel_probe": bool(beats("pixel_probe")),
             "S2_real_from_scratch_beats_sim_finetune": bool(beats("vision_sim_finetune"))}
    hit = hits["vision_real"]
    by_type = {k: {"positives": int(v.sum()), "recall": float(hit[v == 1].mean()) if v.sum() else None}
               for k, v in isd["types"].items()}
    print(f"\nFINAL Robotarium v2 sealed runs {names['sealed_seeds']}: {len(y)} decisions, {n_ep} episodes, prevalence {y.mean():.3f}")
    for m, r in res.items():
        print(f"  {m:20s} AUC-PR {r['auc_pr']:.3f} ROC {r['auc_roc']:.3f} | recall {r['recall']:.3f} at realized FPR {r['realized_fpr']:.3f}")
    for k, b in boot.items():
        print(f"  {k}: {b['recall_difference']} CI95 {b['ci95']}")
    print(f"  G1 {'PASS' if g1 else 'FAIL'}  G2 {'PASS' if g2 else 'FAIL'}  => primary {'PASS' if g1 and g2 else 'FAIL'} | "
          f"S1 {'PASS' if gates['S1_beats_pixel_probe'] else 'FAIL'}  S2 {'PASS' if gates['S2_real_from_scratch_beats_sim_finetune'] else 'FAIL'}")
    rel = lambda p: str(p if a.smoke else Path(p).relative_to(ROOT)).replace("\\", "/")
    doc = {"schema_version": "vision-caution-robotarium-result-v2", "protocol": PROTOCOL.name,
           "status": "registered final on real Robotarium robots and camera, opened once; head trained on real "
                     "footage; branch work (not main); advisory only",
           "splits": names, "sealed_quality": sd_qual, "decisions": int(len(y)), "episodes": int(n_ep),
           "prevalence": float(y.mean()), "selected_pool": pool, "selection_auc_pr": sel_ap,
           "selected_artifact": rel(art_path), "selected_artifact_sha256": art_sha,
           "thresholds_file": rel(thr_path), "thresholds_sha256": thr_sha, "thresholds": thr,
           "dinov2_weights_sha256": wsha, "results": res, "bootstrap": boot, "gates": gates,
           "vision_real_recall_by_hazard_type": by_type,
           "code_sha256": {q: sha256_file(ROOT / q) for q in ("scripts/robotarium/train_eval_real.py",
                                                              "scripts/robotarium/video_frames.py",
                                                              "scripts/robotarium/label_robotarium_log.py",
                                                              "scripts/robotarium/ferrum_experiment.py")}}
    OUT.write_text(json.dumps(doc, indent=1, default=float) + "\n", encoding="utf-8")
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
