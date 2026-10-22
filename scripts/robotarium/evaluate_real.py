#!/usr/bin/env python3
"""Registered real-robot evaluation of the vision caution head on Robotarium footage
(docs/research/vision_caution_robotarium_protocol_v1.json). Branch work, not main.

No model is trained on real data. The frozen vision-caution-v2 head (trained only on the
simulated runtime-scene proxy) scores rectified real frames (scripts/robotarium/
video_frames.py). Thresholds come from the calibration runs' hazard-free decisions only,
are written to disk and hashed, and only then are the sealed runs recorded in the access
ledger and scored, once. CPU only.

Arms (all on identical decisions):
  vision_real_cal   frozen v2 head, threshold from real calibration runs (PRIMARY)
  vision_sim_thr    frozen v2 head, its own frozen simulation threshold (sim-to-real transfer)
  action_only       proxy-trained logistic model on the 10-dim runtime action, threshold
                    from the same real calibration runs (control: no camera)
  state_reference   proxy-trained boosted trees on TRUE geometry (descriptive upper reference)

Usage:
  python scripts/robotarium/evaluate_real.py --dry-run
  python scripts/robotarium/evaluate_real.py --smoke          # pilot run 101 as both sets, temp ledger
  python scripts/robotarium/evaluate_real.py                  # the registered final (opens once)
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

PROTOCOL = ROOT / "docs/research/vision_caution_robotarium_protocol_v1.json"
OUT = ROOT / "docs/research/vision_caution_robotarium_result_v1.json"
THRESHOLDS = ROOT / "docs/research/artifacts/vision-caution-v2/robotarium_thresholds_v1.json"
ARTIFACT = ROOT / "docs/research/artifacts/vision-caution-v2/selected_caution_head.npz"
ARTIFACT_SHA = "77e3ea1ed04421818e1efd6aa4b216b92b75b224c1f13e18e307345fc040042f"
RUNS = ROOT / "target/robotarium/runs"
LEDGER_KEY = "robotarium-sealed-v1"
PRIMARY_FPR, BUDGET = 0.05, 0.10
QUALITY = {"window_corr_median_min": 0.30, "hold_pairing_min": 0.80, "median_err_px_max": 5.0}


def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def quality(run):
    cam = json.loads((run / "camera.json").read_text(encoding="utf-8"))
    c, s = cam["camera"], cam["sync"]
    pairing = c["hold_frames_paired"] / max(1, c["hold_frames_with_two_blobs"])
    ok = (s["knot_corr_median"] >= QUALITY["window_corr_median_min"] and pairing >= QUALITY["hold_pairing_min"]
          and c["median_err_px"] <= QUALITY["median_err_px_max"])
    return ok, {"window_corr_median": s["knot_corr_median"], "hold_pairing": pairing, "median_err_px": c["median_err_px"]}


def load_runs(names):
    import vision_runtime_proxy_final as RP
    data, idx, qual = [], [], {}
    for k, name in enumerate(names):
        run = RUNS / name
        ok, q = quality(run)
        qual[name] = {**q, "passes": ok}
        if not ok:
            continue
        d = dict(np.load(run / "frames.npz"))
        i = RP.decisions(d)
        i["episode_id"] = k * 1000 + i["e"]
        i["run"] = np.full(len(i["y"]), name)
        data.append(d)
        idx.append(i)
    return data, idx, qual


def score_all(data, idx, models):
    import vision_runtime_proxy_final as RP
    out = {m: [] for m in ("vision", "action_only", "state_reference")}
    for d, i in zip(data, idx):
        Fx = RP.extract(models["encoder"], d["frames"], pools=(models["pool"],))[models["pool"]]
        out["vision"].append(RP.score_head(models["head"], Fx, i, i["a10"]))
        out["action_only"].append(models["action_only"].predict_proba(i["a10"])[:, 1])
        out["state_reference"].append(models["state_reference"].predict_proba(RP.state_features(d, i))[:, 1])
    cat = lambda key: np.concatenate([i[key] for i in idx])
    return {m: np.concatenate(v) for m, v in out.items()}, {k: cat(k) for k in ("y", "episode_id", "kind")}, \
        {k: np.concatenate([i["types"][k] for i in idx]) for k in idx[0]["types"]}


def build_models():
    import torch
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression

    import vision_runtime_domain_render as R
    import vision_runtime_proxy_final as RP
    import vision_wm_pretrained_encoders as PE
    from vision_caution import load_artifact

    art = load_artifact(ARTIFACT, ARTIFACT_SHA)
    head = RP.make_head(art["pool"], 10)
    head.load_state_dict({k: torch.from_numpy(v) for k, v in art["weights"].items()}, strict=True)
    from huggingface_hub import hf_hub_download
    wsha = sha256_file(hf_hub_download("facebook/dinov2-small", "model.safetensors"))
    if wsha != art["encoder_sha256"]:
        raise SystemExit("REFUSE: DINOv2 weights differ from the artifact's encoder digest")
    proxy = R.collect(800, seed=200)                         # the proxy study's training split, deterministic
    ip = RP.decisions(proxy)
    action_only = LogisticRegression(max_iter=1000, C=1.0, class_weight="balanced").fit(ip["a10"], ip["y"])
    state_ref = HistGradientBoostingClassifier(random_state=0).fit(RP.state_features(proxy, ip), ip["y"])
    return {"encoder": PE.load_dino(True).cpu(), "head": head.eval(), "pool": art["pool"], "artifact": art,
            "action_only": action_only, "state_reference": state_ref, "dinov2_sha256": wsha}


def main():
    global OUT, THRESHOLDS
    import vision_wm_final_v2 as FV
    import vision_wm_train as TR
    import vision_runtime_proxy_final as RP

    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args()
    proto = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    cal_names = [f"seed{s}" for s in proto["runs"]["calibration_seeds"]]
    sealed_names = [f"seed{s}" for s in proto["runs"]["sealed_seeds"]]
    if a.dry_run:
        print("primary:", proto["gates"]["primary_success"])
        print("calibration runs present:", [n for n in cal_names if (RUNS / n / "frames.npz").exists()])
        print("sealed runs present:", [n for n in sealed_names if (RUNS / n / "frames.npz").exists()])
        print("ledger:", "ALREADY opened -> REFUSE" if FV.ledger_has(LEDGER_KEY) else "not yet opened -> eligible")
        return
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "-1":
        raise SystemExit("REFUSE: CPU only; set CUDA_VISIBLE_DEVICES=-1")
    if a.smoke:
        tmp = Path(tempfile.mkdtemp(prefix="vc_rbt_smoke_"))
        FV.LEDGER, OUT, THRESHOLDS = tmp / "ledger.jsonl", tmp / "result.json", tmp / "thresholds.json"
        cal_names, sealed_names = ["seed101"], ["seed101"]
        print("SMOKE: pilot run 101 as both sets; temp ledger/out ->", tmp)
    if FV.ledger_has(LEDGER_KEY):
        raise SystemExit(f"REFUSE: {LEDGER_KEY} already in {FV.LEDGER}")

    t0 = time.time()
    models = build_models()
    print(f"models ready ({round(time.time() - t0)}s): v2 head pool {models['pool']}, proxy-trained controls", flush=True)

    # --- calibration runs only ---
    cdata, cidx, cqual = load_runs(cal_names)
    if not cdata:
        raise SystemExit("no calibration run passed the quality gate")
    cs, cy, _ = score_all(cdata, cidx, models)
    thr = {"vision_real_cal": FV.calibrate(cs["vision"], cy["y"], PRIMARY_FPR),
           "vision_sim_thr": float(models["artifact"]["thresholds"]["fpr_0.05"]),
           "action_only": FV.calibrate(cs["action_only"], cy["y"], PRIMARY_FPR),
           "state_reference": FV.calibrate(cs["state_reference"], cy["y"], PRIMARY_FPR)}
    frozen = {"thresholds": thr, "calibration_runs": cal_names, "calibration_quality": cqual,
              "calibration_decisions": int(len(cy["y"])), "calibration_benign": int((cy["y"] == 0).sum()),
              "artifact_sha256": ARTIFACT_SHA, "dinov2_sha256": models["dinov2_sha256"],
              "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    THRESHOLDS.parent.mkdir(parents=True, exist_ok=True)
    THRESHOLDS.write_text(json.dumps(frozen, indent=1) + "\n", encoding="utf-8")
    thr_sha = sha256_file(THRESHOLDS)
    print(f"thresholds frozen from {len(cy['y'])} calibration decisions -> {THRESHOLDS} sha256 {thr_sha[:16]}...", flush=True)

    # --- SINGLE OPEN ---
    FV.record_final(LEDGER_KEY, "vision-caution Robotarium v1: sealed real-robot runs scored once (CPU)")
    sdata, sidx, squal = load_runs(sealed_names)
    if not sdata:
        raise SystemExit("no sealed run passed the quality gate (recorded in the ledger; nothing scored)")
    ss, sy, types = score_all(sdata, sidx, models)
    y, ep = sy["y"], sy["episode_id"]
    _, ep_dense = np.unique(ep, return_inverse=True)
    arm_scores = {"vision_real_cal": ss["vision"], "vision_sim_thr": ss["vision"],
                  "action_only": ss["action_only"], "state_reference": ss["state_reference"]}
    res = {}
    for arm, s in arm_scores.items():
        r, f = FV.recall_fpr(s, y, thr[arm])
        res[arm] = {**TR.auc(y, s), "recall": r, "realized_fpr": f}
    hits = {arm: arm_scores[arm] > thr[arm] for arm in arm_scores}
    boot = RP.cluster_boot(hits["vision_real_cal"], hits["action_only"], y, ep_dense, int(ep_dense.max()) + 1)
    p, c = res["vision_real_cal"], res["action_only"]
    g1 = p["auc_pr"] > c["auc_pr"] and p["recall"] > c["recall"] and (boot["ci95"][0] or 0) > 0
    g2 = p["realized_fpr"] <= BUDGET
    s1 = res["vision_sim_thr"]["realized_fpr"] <= BUDGET
    gates = {"G1_camera_beats_action_only": bool(g1), "G2_budget_holds": bool(g2), "primary_success": bool(g1 and g2),
             "S1_sim_threshold_budget_holds": bool(s1)}
    hit = hits["vision_real_cal"]
    by_type = {k: {"positives": int(v.sum()), "recall": float(hit[v == 1].mean()) if v.sum() else None}
               for k, v in types.items()}
    names = ("move", "inspect", "diagnose", "approve", "repair", "verify", "stop")
    by_kind = {names[k]: {"positives": int(((sy["kind"] == k) & (y == 1)).sum()),
                          "recall": float(hit[(sy["kind"] == k) & (y == 1)].mean()) if ((sy["kind"] == k) & (y == 1)).any() else None}
               for k in range(7)}
    print(f"\nFINAL Robotarium sealed runs {sealed_names}: {len(y)} decisions, {ep_dense.max() + 1} episodes, prevalence {y.mean():.3f}")
    for arm, r in res.items():
        print(f"  {arm:16s} AUC-PR {r['auc_pr']:.3f} ROC {r['auc_roc']:.3f} | recall {r['recall']:.3f} at realized FPR {r['realized_fpr']:.3f}")
    print(f"  recall diff vision_real_cal - action_only {boot['recall_difference']} CI95 {boot['ci95']}")
    print(f"  G1 {'PASS' if g1 else 'FAIL'}  G2 {'PASS' if g2 else 'FAIL'}  => primary {'PASS' if g1 and g2 else 'FAIL'} | "
          f"S1 sim threshold budget {'PASS' if s1 else 'FAIL'}")
    doc = {"schema_version": "vision-caution-robotarium-result-v1", "protocol": PROTOCOL.name,
           "status": "registered final on real Robotarium robots and camera, opened once; branch work (not main); "
                     "advisory only; no model trained on real data",
           "sealed_runs": sealed_names, "sealed_quality": squal, "decisions": int(len(y)),
           "episodes": int(ep_dense.max() + 1), "prevalence": float(y.mean()),
           "thresholds_file": str(THRESHOLDS if a.smoke else THRESHOLDS.relative_to(ROOT)).replace("\\", "/"),
           "thresholds_sha256": thr_sha, "thresholds": thr, "results": res, "bootstrap": boot, "gates": gates,
           "vision_real_cal_recall_by_hazard_type": by_type, "vision_real_cal_by_action_kind": by_kind,
           "code_sha256": {q: sha256_file(ROOT / q) for q in ("scripts/robotarium/evaluate_real.py",
                                                              "scripts/robotarium/video_frames.py",
                                                              "scripts/robotarium/label_robotarium_log.py",
                                                              "scripts/robotarium/ferrum_experiment.py")}}
    OUT.write_text(json.dumps(doc, indent=1, default=float) + "\n", encoding="utf-8")
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
