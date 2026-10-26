#!/usr/bin/env python3
"""Registered study B: a vision caution head trained in SIMULATION with the Robotarium's look,
tested on fresh real Robotarium runs (docs/research/vision_caution_robotarium_protocol_v3.json).
Branch work, not main.

Simulated training frames: the runtime-scene proxy rendered with look="arena" (256 px), its
robots and obstacle disc pasted onto the real empty-arena background (median of the spent
real runs' rectified frames), then photometric randomization (dev_arena_sim.composite and
.randomize). Rendered, composited and encoded in chunks, so only DINOv2 features are kept.

Arms (identical sealed decisions):
  vision_sim_arena       head trained only on the composite sim frames (PRIMARY)
  vision_sim_finetune    that head fine-tuned on the real training runs (secondary)
  action_only            logistic regression on the 10-dim action, trained on the real training runs (control)
  state_reference        boosted trees on true geometry, real training runs (descriptive)
Every arm's threshold: 0.95 quantile of its scores on the calibration runs' hazard-free
decisions. Head, thresholds and background are written and hashed before the sealed runs
are ledgered and scored once. CPU only.

Usage:
  CUDA_VISIBLE_DEVICES=-1 python scripts/robotarium/study_b.py --dry-run
  CUDA_VISIBLE_DEVICES=-1 python scripts/robotarium/study_b.py --smoke    # tiny sim, spent runs as 'sealed', temp ledger
  CUDA_VISIBLE_DEVICES=-1 python scripts/robotarium/study_b.py            # the registered final (opens once)
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
sys.path.insert(0, str(HERE))

PROTOCOL = ROOT / "docs/research/vision_caution_robotarium_protocol_v3.json"
OUT = ROOT / "docs/research/vision_caution_robotarium_result_v3.json"
ART_DIR = ROOT / "docs/research/artifacts/vision-caution-arena-v1"
BG_PATH = ROOT / "target/robotarium/arena_background_v1.npy"
LEDGER_KEY = "robotarium-sealed-v3"
AUTHORITY = "advisory diagnostic only; no permit, block, approval, adapter or actuation authority"
SIZE, CHUNK, EPOCHS, PRIMARY_FPR, BUDGET = 256, 100, 60, 0.05, 0.10
SIM_KEYS = ("kinds", "features", "hazards", "clearance", "margin", "contact", "robot_xy", "obstacle_xy")


def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def sim_features(enc, n, seed, bg, rng_seed, pools=(4, 8)):
    """Render n arena episodes in chunks, composite + randomize, keep only DINOv2 features."""
    import torch

    import dev_arena_sim as DA
    import vision_runtime_domain_render as R
    import vision_runtime_proxy_final as RP
    rng = np.random.default_rng(rng_seed)
    feats, meta = {p: [] for p in pools}, {k: [] for k in SIM_KEYS}
    for start in range(0, n, CHUNK):
        d = R.collect(min(CHUNK, n - start), seed=seed * 1000 + start, size=SIZE, look="arena")
        frames = DA.randomize(DA.composite(d["frames"], bg), rng)
        F = RP.extract(enc, frames, pools=pools)
        for p in pools:
            feats[p].append(F[p])
        for k in SIM_KEYS:
            meta[k].append(d[k])
    return {p: torch.cat(v) for p, v in feats.items()}, {k: np.concatenate(v) for k, v in meta.items()}


def main():
    global OUT, ART_DIR, BG_PATH
    import torch
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression

    import dev_arena_sim as DA
    import train_eval_real as TE
    import vision_runtime_proxy_final as RP
    import vision_wm_final_v2 as FV
    import vision_wm_pretrained_encoders as PE
    import vision_wm_train as TR

    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args()
    proto = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    runs = proto["runs"]
    spent = [f"seed{s}" for s in runs["spent_real_seeds"]]
    cal = [f"seed{s}" for s in runs["calibration_seeds"]]
    sealed = [f"seed{s}" for s in runs["sealed_seeds"]]
    sim = proto["simulation"]
    n_tr, n_se, epochs = sim["train_episodes"], sim["selection_episodes"], EPOCHS
    if a.dry_run:
        print("primary:", proto["gates"]["primary_success"])
        print("spent present:", sum((TE.RUNS / n / "frames.npz").exists() for n in spent), "of", len(spent))
        print("sealed present:", [n for n in sealed if (TE.RUNS / n / "frames.npz").exists()])
        print("ledger:", "ALREADY opened -> REFUSE" if FV.ledger_has(LEDGER_KEY) else "not yet opened -> eligible")
        return
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "-1":
        raise SystemExit("REFUSE: CPU only; set CUDA_VISIBLE_DEVICES=-1")
    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "8")))
    if a.smoke:
        tmp = Path(tempfile.mkdtemp(prefix="vc_rbt3_smoke_"))
        FV.LEDGER, OUT, ART_DIR, BG_PATH = tmp / "ledger.jsonl", tmp / "result.json", tmp / "artifact", tmp / "bg.npy"
        n_tr, n_se, epochs = 20, 10, 2
        sealed = ["seed601", "seed602"]
        spent = [n for n in spent if n not in sealed]
        print("SMOKE: tiny sim, spent runs 601/602 as 'sealed', temp ledger/artifact ->", tmp)
    if FV.ledger_has(LEDGER_KEY):
        raise SystemExit(f"REFUSE: {LEDGER_KEY} already in {FV.LEDGER}")
    t0 = time.time()

    # --- real spent runs: background, calibration and real-training splits ---
    sp, sp_qual, _ = TE.load_split(spent, gate=True)
    kept = [n for n in spent if sp_qual[n]["passes"]]
    bg = DA.real_background(kept)
    BG_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.save(BG_PATH, bg)
    rtr, _, _ = TE.load_split([n for n in kept if n not in cal], gate=True)
    rca, cal_qual, _ = TE.load_split(cal, gate=True)
    irtr, ica = RP.decisions(rtr), RP.decisions(rca)
    enc = PE.load_dino(True).cpu()
    inspect = lambda d: d["inspect"].astype(np.float32) / 255.0
    Frtr, Fca = RP.extract(enc, inspect(rtr)), RP.extract(enc, inspect(rca))
    print(f"real: train {len(irtr['y'])} decisions, calibration {len(ica['y'])} ({round(time.time() - t0)}s)", flush=True)

    # --- simulation (arena look on the real background) ---
    Fstr, dstr = sim_features(enc, n_tr, sim["train_seed"], bg, 0)
    Fsse, dsse = sim_features(enc, n_se, sim["selection_seed"], bg, 1)
    istr, isse = RP.decisions(dstr), RP.decisions(dsse)
    print(f"sim: train {len(istr['y'])} / selection {len(isse['y'])} decisions ({round(time.time() - t0)}s)", flush=True)
    cands = {pool: TE.train_head(Fstr[pool], Fsse[pool], istr, isse, istr["a10"], isse["a10"], pool, epochs)
             for pool in (4, 8)}
    pool = max(cands, key=lambda p: cands[p][1])
    head_sim, sel_ap_sim = cands[pool]
    init = {k: v.detach().clone() for k, v in head_sim.state_dict().items()}
    head_ft, sel_ap_ft = TE.train_head(Frtr[pool], Fca[pool], irtr, ica, irtr["a10"], ica["a10"], pool, epochs,
                                       init=init, lr=1e-4)
    act = LogisticRegression(max_iter=1000, C=1.0, class_weight="balanced").fit(irtr["a10"], irtr["y"])
    state = HistGradientBoostingClassifier(random_state=0).fit(RP.state_features(rtr, irtr), irtr["y"])

    def scores(d, i, Fx):
        return {"vision_sim_arena": RP.score_head(head_sim, Fx[pool], i, i["a10"]),
                "vision_sim_finetune": RP.score_head(head_ft, Fx[pool], i, i["a10"]),
                "action_only": act.predict_proba(i["a10"])[:, 1],
                "state_reference": state.predict_proba(RP.state_features(d, i))[:, 1]}

    cs = scores(rca, ica, Fca)
    thr = {m: FV.calibrate(s, ica["y"], PRIMARY_FPR) for m, s in cs.items()}
    cal_ap = {m: TR.auc(ica["y"], s)["auc_pr"] for m, s in cs.items()}
    print(f"frozen before open: pool {pool}, sim selection AUC-PR {sel_ap_sim:.3f}; calibration-run AUC-PR "
          f"{json.dumps({m: round(v, 3) for m, v in cal_ap.items()})}", flush=True)

    # --- persist heads, thresholds, background hash BEFORE the open ---
    ART_DIR.mkdir(parents=True, exist_ok=True)
    platt = LogisticRegression(C=1e6).fit(cs["vision_sim_arena"].reshape(-1, 1), ica["y"])
    meta = {"schema": "FERRUM_VISION_CAUTION_V2", "authority": AUTHORITY, "protocol": [PROTOCOL.name],
            "pool": pool, "frame_size": SIZE, "frame_stack": 2, "horizon_steps": 3,
            "action_space": {"kind": "runtime PhysicalAction", "names": ["move", "inspect", "diagnose", "approve",
                                                                           "repair", "verify", "stop"],
                             "feature_size": 3, "encoding": "one-hot over the 7 kinds + the 3 raw features"},
            "trained_on": "simulation only: arena-look proxy renders composited on the real empty-arena background",
            "background_sha256": sha256_file(BG_PATH),
            "thresholds_logit": {"fpr_0.05": thr["vision_sim_arena"]},
            "platt": {"coef": float(platt.coef_[0, 0]), "intercept": float(platt.intercept_[0])},
            "qualification": "decided by docs/research/vision_caution_robotarium_result_v3.json; never live use"}
    for name, head in (("sim_arena_head.npz", head_sim), ("sim_finetune_head.npz", head_ft)):
        arrays = {f"head.{k}": v.detach().cpu().numpy().astype(np.float32) for k, v in head.state_dict().items()}
        np.savez_compressed(ART_DIR / name, metadata=json.dumps({**meta, "arm": name}, sort_keys=True), **arrays)
    (ART_DIR / "thresholds.json").write_text(json.dumps({"thresholds": thr, "calibration_auc_pr": cal_ap, "pool": pool,
                                                         "sim_selection_auc_pr": sel_ap_sim, "finetune_selection_auc_pr": sel_ap_ft,
                                                         "calibration_runs": cal, "calibration_quality": cal_qual,
                                                         "background_sha256": meta["background_sha256"]}, indent=1) + "\n",
                                             encoding="utf-8")
    hashes = {n: sha256_file(ART_DIR / n) for n in ("sim_arena_head.npz", "sim_finetune_head.npz", "thresholds.json")}
    print(f"persisted {json.dumps({k: v[:12] for k, v in hashes.items()})} ({round(time.time() - t0)}s)", flush=True)

    # --- SINGLE OPEN ---
    FV.record_final(LEDGER_KEY, "vision-caution Robotarium v3 (study B): sim arena-look head, sealed runs scored once (CPU)")
    sd, sd_qual, _ = TE.load_split(sealed, gate=True)
    if sd is None:
        raise SystemExit("no sealed run passed the quality gate (recorded in the ledger; nothing scored)")
    isd = RP.decisions(sd)
    fin = scores(sd, isd, RP.extract(enc, inspect(sd), pools=(pool,)))
    y, ep, n_ep = isd["y"], isd["e"], len(sd["kinds"])
    res = {}
    for m, s in fin.items():
        r, f = FV.recall_fpr(s, y, thr[m])
        res[m] = {**TR.auc(y, s), "recall": r, "realized_fpr": f}
    hits = {m: fin[m] > thr[m] for m in fin}
    boot = {"sim_arena_minus_action_only": RP.cluster_boot(hits["vision_sim_arena"], hits["action_only"], y, ep, n_ep),
            "finetune_minus_action_only": RP.cluster_boot(hits["vision_sim_finetune"], hits["action_only"], y, ep, n_ep),
            "finetune_minus_sim_arena": RP.cluster_boot(hits["vision_sim_finetune"], hits["vision_sim_arena"], y, ep, n_ep)}
    beats = lambda a_, b_, key: (res[a_]["auc_pr"] > res[b_]["auc_pr"] and res[a_]["recall"] > res[b_]["recall"]
                                 and (boot[key]["ci95"][0] or 0) > 0)
    g1 = beats("vision_sim_arena", "action_only", "sim_arena_minus_action_only")
    g2 = res["vision_sim_arena"]["realized_fpr"] <= BUDGET
    gates = {"G1_sim_arena_beats_action_only": bool(g1), "G2_budget_holds": bool(g2), "primary_success": bool(g1 and g2),
             "S1_finetune_beats_action_only": bool(beats("vision_sim_finetune", "action_only", "finetune_minus_action_only")
                                                  and res["vision_sim_finetune"]["realized_fpr"] <= BUDGET),
             "S2_finetune_beats_sim_arena": bool(beats("vision_sim_finetune", "vision_sim_arena", "finetune_minus_sim_arena"))}
    by_type = {arm: {k: {"positives": int(v.sum()), "recall": float(hits[arm][v == 1].mean()) if v.sum() else None}
                     for k, v in isd["types"].items()} for arm in ("vision_sim_arena", "vision_sim_finetune")}
    print(f"\nFINAL Robotarium v3 sealed: {len(y)} decisions, {n_ep} episodes, prevalence {y.mean():.3f}; "
          f"runs passing the gate: {[n for n in sealed if sd_qual[n]['passes']]}")
    for m, r in res.items():
        print(f"  {m:20s} AUC-PR {r['auc_pr']:.3f} ROC {r['auc_roc']:.3f} | recall {r['recall']:.3f} at realized FPR {r['realized_fpr']:.3f}")
    for k, b in boot.items():
        print(f"  {k}: {b['recall_difference']} CI95 {b['ci95']}")
    print("  gates:", json.dumps(gates))
    rel = lambda p: str(p if a.smoke else Path(p).relative_to(ROOT)).replace("\\", "/")
    doc = {"schema_version": "vision-caution-robotarium-result-v3", "protocol": PROTOCOL.name,
           "status": "registered final (study B) on real Robotarium robots and camera, opened once; head trained in "
                     "simulation only; branch work (not main); advisory only",
           "sealed_runs": sealed, "sealed_quality": sd_qual, "decisions": int(len(y)), "episodes": int(n_ep),
           "prevalence": float(y.mean()), "pool": pool, "artifacts": {rel(ART_DIR / k): v for k, v in hashes.items()},
           "background_sha256": meta["background_sha256"], "thresholds": thr, "calibration_auc_pr": cal_ap,
           "results": res, "bootstrap": boot, "gates": gates, "recall_by_hazard_type": by_type,
           "code_sha256": {q: sha256_file(ROOT / q) for q in ("scripts/robotarium/study_b.py", "scripts/robotarium/dev_arena_sim.py",
                                                              "scripts/vision_runtime_domain_render.py",
                                                              "scripts/robotarium/video_frames.py",
                                                              "scripts/robotarium/label_robotarium_log.py",
                                                              "scripts/robotarium/ferrum_experiment.py")}}
    OUT.write_text(json.dumps(doc, indent=1, default=float) + "\n", encoding="utf-8")
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
