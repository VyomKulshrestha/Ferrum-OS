#!/usr/bin/env python3
"""Registered single-open confirmation: frozen pretrained DINOv2 vs from-scratch CNN on the
hard scene (docs/research/vision_world_model_protocol_v2_amendment3.json). Branch work.

Everything trains, selects and calibrates on seeds 0/1 BEFORE the sealed seed is opened.
Then the sealed seed is recorded in target/vision-wm/final_access.jsonl, rendered once,
and scored. Margin-primary calibration (FPR 0.05 on seed-1 benign steps).

Usage:
  python scripts/vision_wm_final_dinov2.py --dry-run
  python scripts/vision_wm_final_dinov2.py --smoke              # throwaway seed + temp ledger
  python scripts/vision_wm_final_dinov2.py [--final-seed 780]   # 781 only per the crash rule
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression

import vision_wm_final_v2 as FV
import vision_wm_pretrained_encoders as PE
import vision_wm_pybullet_data as D
import vision_wm_train as TR

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/research/vision_world_model_result_v4_dinov2.json"
PROTOCOL = ROOT / "docs/research/vision_world_model_protocol_v2_amendment3.json"
ARTIFACT = ROOT / "docs/research/artifacts/vision-caution-v1/selected_caution_head.npz"   # amendment4
AUTHORITY = "advisory diagnostic only; no permit, block, approval, adapter or actuation authority"


def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()
K, H, SIZE, STEPS, PRIMARY_FPR, BUDGET = 2, 3, 48, 20, 0.05, 0.10


def render(n, seed):
    f, a, h = D.collect(n, STEPS, SIZE, seed=seed, scene="hard")
    return f, a, h


def main():
    global OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--final-seed", type=int, default=780)
    a = ap.parse_args()
    fseed = a.final_seed
    nt, ns, nf, epochs = 600, 200, 300, 60
    art_path = ARTIFACT
    if a.smoke:
        tmp = Path(tempfile.mkdtemp(prefix="vwm_v4_smoke_"))
        FV.LEDGER = tmp / "ledger.jsonl"; OUT = tmp / "result.json"; art_path = tmp / "head.npz"
        nt, ns, nf, epochs, fseed = 20, 10, 12, 2, 999997
        print("SMOKE: throwaway seed/ledger/out ->", tmp)
    if a.dry_run:
        print(json.loads(PROTOCOL.read_text(encoding="utf-8"))["gates"]["primary_success"])
        print(f"sealed seed {fseed}: " + ("ALREADY opened -> REFUSE" if FV.ledger_has(fseed) else "not yet opened -> eligible"))
        return
    if fseed not in (780, 781) and not a.smoke:
        raise SystemExit("REFUSE: only seed 780 (or 781 under the registered crash rule) is allowed")
    if FV.ledger_has(fseed):
        raise SystemExit(f"REFUSE: sealed seed {fseed} already in {FV.LEDGER}")

    t0 = time.time()
    ftr, atr, htr = render(nt, 0)
    fse, ase, hse = render(ns, 1)
    tr, se = TR.build(ftr, atr, htr, H, K), TR.build(fse, ase, hse, H, K)
    itr, ise = PE.labels(atr, htr), PE.labels(ase, hse)
    assert np.array_equal(tr[3], itr[3]) and np.array_equal(se[3], ise[3]), "label paths must agree"
    print(f"train {len(tr[3])} / sel {len(se[3])} transitions ({round(time.time()-t0)}s)", flush=True)

    # --- everything below until the open uses seeds 0/1 only ---
    scores, best_c, _, cnn_params, _ = FV.train_vwm(tr, se, epochs=epochs)
    cnn = lambda d: scores(best_c, d[0], d[1])[1]
    flat = lambda c, ac: np.concatenate([c.reshape(len(c), -1), TR.onehot(ac)], 1)
    lp = LogisticRegression(max_iter=400, C=0.5, class_weight="balanced").fit(flat(tr[0], tr[1]), tr[3])
    probe = lambda d: lp.predict_proba(flat(d[0], d[1]))[:, 1]

    from huggingface_hub import hf_hub_download
    wpath = hf_hub_download("facebook/dinov2-small", "model.safetensors")
    wsha = hashlib.sha256(Path(wpath).read_bytes()).hexdigest()
    enc = PE.load_dino(True)
    Ftr, Fse = PE.extract(enc, ftr), PE.extract(enc, fse)
    head, sel_ap = PE.train_head(Ftr, Fse, itr, ise, epochs)
    dino = lambda Fx, idx: head(Fx, idx)
    del Ftr

    sel_scores = {"dinov2": dino(Fse, ise), "cnn": cnn(se), "probe": probe(se)}
    thr = {m: {"p05": FV.calibrate(s, se[3], PRIMARY_FPR), "p10": FV.calibrate(s, se[3], BUDGET)}
           for m, s in sel_scores.items()}
    print(f"frozen before open: dinov2 sel AP {sel_ap:.3f}; thresholds {json.dumps({m: {k: round(v, 4) for k, v in t.items()} for m, t in thr.items()})}", flush=True)

    # --- amendment4: persist the frozen candidate BEFORE the open (no gate/model change) ---
    platt = LogisticRegression(C=1e6).fit(sel_scores["dinov2"].reshape(-1, 1), se[3])
    arrays = {f"head.{k}": v.detach().cpu().numpy().astype(np.float32) for k, v in head.head.state_dict().items()}
    meta = {"schema": "FERRUM_VISION_CAUTION_V1", "authority": AUTHORITY,
            "protocol": ["vision_world_model_protocol_v2_amendment3.json", "vision_world_model_protocol_v2_amendment4.json"],
            "encoder": {"name": "facebook/dinov2-small", "weights_sha256": wsha,
                        "source": "scripts/vision_wm_pretrained_encoders.py:DinoV2Small",
                        "source_sha256": sha256_file(ROOT / "scripts/vision_wm_pretrained_encoders.py"),
                        "input": "grey frame replicated to RGB, bilinear to 224x224, ImageNet mean/std",
                        "pooling": "patch-token map adaptive-avg-pooled to 4x4"},
            "head": "2-frame stack (2x384,4,4) -> Conv1x1(64)+GELU -> concat GELU(Linear(5->32)(action one-hot)) -> Linear(1056->128)+GELU -> Linear(128->1) logit",
            "frame_stack": K, "horizon_steps": H, "render_size": SIZE, "scene": "hard", "look": "clean",
            "action_space": {"kind": "sim discrete", "actions": D.ACTIONS.tolist(), "names": ["stay", "-x", "+x", "-y", "+y"]},
            "thresholds_logit": {"fpr_0.05": thr["dinov2"]["p05"], "fpr_0.10": thr["dinov2"]["p10"]},
            "platt": {"coef": float(platt.coef_[0, 0]), "intercept": float(platt.intercept_[0]),
                      "fitted_on": "selection seed 1 logits, before the sealed open"},
            "selection_auc_pr": float(sel_ap), "train_seed": 0, "selection_seed": 1,
            "qualified_for": "rendered pybullet hard scene, clean look, advisory logging only; NOT qualified for live use"}
    art_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(art_path, metadata=json.dumps(meta, sort_keys=True), **arrays)
    art_sha = sha256_file(art_path)
    print(f"persisted frozen head -> {art_path} sha256 {art_sha[:16]}...", flush=True)

    # --- SINGLE OPEN ---
    FV.record_final(fseed, "vision-world-model amendment3: frozen DINOv2 vs scratch CNN (hard, margin-primary)")
    ffi, afi, hfi = render(nf, fseed)
    fi, ifi = TR.build(ffi, afi, hfi, H, K), PE.labels(afi, hfi)
    y = fi[3]
    final_scores = {"dinov2": dino(PE.extract(enc, ffi), ifi), "cnn": cnn(fi), "probe": probe(fi)}

    res = {}
    for m, s in final_scores.items():
        res[m] = {**TR.auc(y, s)}
        for arm in ("p05", "p10"):
            r, f = FV.recall_fpr(s, y, thr[m][arm])
            res[m][arm] = {"recall": r, "realized_fpr": f}
    boot = FV.boot_recall_diff(final_scores["dinov2"], final_scores["cnn"], y, thr["dinov2"]["p05"], thr["cnn"]["p05"])
    g1 = (res["dinov2"]["p05"]["recall"] > res["cnn"]["p05"]["recall"]
          and res["dinov2"]["auc_pr"] > res["cnn"]["auc_pr"] and boot["ci95"][0] > 0)
    g2 = res["dinov2"]["p05"]["realized_fpr"] <= BUDGET
    gates = {"G1_pretrained_beats_scratch": bool(g1), "G2_budget_holds": bool(g2),
             "recall_diff_dinov2_minus_cnn": boot, "primary_success": bool(g1 and g2)}

    print(f"\nFINAL sealed seed {fseed}: {len(y)} transitions, prevalence {y.mean():.3f}")
    for m in ("dinov2", "cnn", "probe"):
        r = res[m]
        print(f"  {m:7s} AUC-PR {r['auc_pr']:.3f} ROC {r['auc_roc']:.3f} | recall@5% {r['p05']['recall']:.3f} "
              f"(realized {r['p05']['realized_fpr']:.3f}) | recall@10% {r['p10']['recall']:.3f} (realized {r['p10']['realized_fpr']:.3f})")
    print(f"  recall diff dinov2-cnn {boot['recall_difference']:+.3f} CI95 {[round(x, 3) for x in boot['ci95']]}")
    print(f"  G1 {'PASS' if g1 else 'FAIL'}  G2 {'PASS' if g2 else 'FAIL'}  => primary {'PASS' if gates['primary_success'] else 'FAIL'}")
    doc = {"schema_version": "vision-world-model-result-v4-dinov2", "protocol": PROTOCOL.name,
           "status": "registered final, opened once; branch work (not main); advisory only",
           "scene": "hard", "final_seed": fseed, "dinov2_weights_sha256": wsha, "cnn_params": cnn_params,
           "selected_artifact": str(art_path.relative_to(ROOT)).replace("\\", "/") if not a.smoke else str(art_path),
           "selected_artifact_sha256": art_sha,
           "thresholds": thr, "prevalence": float(y.mean()), "results": res, "gates": gates}
    OUT.write_text(json.dumps(doc, indent=1, default=float) + "\n", encoding="utf-8")
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
