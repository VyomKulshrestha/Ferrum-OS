#!/usr/bin/env python3
"""Registered single-open final for the vision world model (increment 2). Branch work, not on main.

Implements docs/research/vision_world_model_protocol_v2.json: per-head checkpoint
selection (decouples the increment-1 frame/caution tradeoff), budget-calibrated
caution thresholds (TARGET_FPR 0.10 and a 0.05 conservative arm), and a SEALED
final scene set (seed 777) opened exactly once via a ledger. Caution = P(hazard
within H=3) from a 2-frame stack + action. Advisory only; rendered simulation.

Usage:
  python scripts/vision_wm_final_v2.py --dry-run     # print plan + ledger status
  python scripts/vision_wm_final_v2.py               # train, calibrate, open sealed final once
"""
from __future__ import annotations

import argparse
import datetime
import json
import time
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression

import vision_wm_pybullet_data as D
import vision_wm_train as TR

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/research/vision_world_model_result_v2.json"
LEDGER = ROOT / "target/vision-wm/final_access.jsonl"
PROTOCOL = ROOT / "docs/research/vision_world_model_protocol_v2.json"
TRAIN_SEED, CALIB_SEED, FINAL_SEED = 0, 1, 777
SIZE, STEPS, K, H = 48, 20, 2, 3
TARGET_FPR = 0.10
NA = len(D.ACTIONS)


def ledger_has(seed):
    if not LEDGER.exists():
        return False
    return any(json.loads(l).get("final_seed") == seed for l in LEDGER.read_text(encoding="utf-8").splitlines() if l.strip())


def record_final(seed, reason):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as h:
        h.write(json.dumps({"final_seed": seed, "reason": reason,
                            "at": datetime.datetime.now(datetime.timezone.utc).isoformat()}) + "\n")


def calibrate(scores, y, target_fpr):
    """Smallest threshold with benign (y==0) alarm rate <= target_fpr."""
    benign = scores[y == 0]
    if len(benign) == 0:
        return float(scores.max()) + 1.0
    return float(np.quantile(benign, 1.0 - target_fpr))


def recall_fpr(scores, y, thr):
    pos, neg = scores[y == 1], scores[y == 0]
    return (float((pos > thr).mean()) if len(pos) else float("nan"),
            float((neg > thr).mean()) if len(neg) else float("nan"))


def boot_recall_diff(sc_cnn, sc_probe, y, thr_cnn, thr_probe, reps=10000, seed=0):
    pos = np.flatnonzero(y == 1)
    if len(pos) == 0:
        return {"recall_difference": float("nan"), "ci95": [float("nan"), float("nan")]}
    rng = np.random.default_rng(seed)
    a = (sc_cnn[pos] > thr_cnn).astype(np.float64)
    b = (sc_probe[pos] > thr_probe).astype(np.float64)
    idx = rng.integers(0, len(pos), (reps, len(pos)))
    diff = a[idx].mean(1) - b[idx].mean(1)
    return {"recall_difference": float(a.mean() - b.mean()),
            "ci95": [float(np.quantile(diff, 0.025)), float(np.quantile(diff, 0.975))]}


def train_vwm(tr, ca, epochs=60, change_weight=30.0, lam=1.0, seed=0):
    """Train VWM; return best-caution and best-frame checkpoints (per-head selection)."""
    import torch
    from torch import nn
    cur_tr, act_tr, nxt_tr, y_tr = tr
    cur_ca, act_ca, nxt_ca, y_ca = ca
    torch.manual_seed(seed)
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    g = SIZE // 8

    class VWM(nn.Module):
        def __init__(s):
            super().__init__()
            s.enc = nn.Sequential(nn.Conv2d(K, 32, 3, 2, 1), nn.GELU(), nn.Conv2d(32, 64, 3, 2, 1), nn.GELU(),
                                  nn.Conv2d(64, 64, 3, 2, 1), nn.GELU())
            s.act = nn.Sequential(nn.Linear(NA, 64), nn.GELU())
            s.mix = nn.Sequential(nn.Linear(64 * g * g + 64, 64 * g * g), nn.GELU())
            s.dec = nn.Sequential(nn.ConvTranspose2d(64, 64, 4, 2, 1), nn.GELU(), nn.ConvTranspose2d(64, 32, 4, 2, 1),
                                  nn.GELU(), nn.ConvTranspose2d(32, 1, 4, 2, 1))
            s.haz = nn.Sequential(nn.Linear(64 * g * g, 128), nn.GELU(), nn.Linear(128, 1))

        def forward(s, st, a):
            h = s.enc(st).flatten(1); m = s.mix(torch.cat([h, s.act(a)], 1))
            return torch.clamp(st[:, -1:] + s.dec(m.view(-1, 64, g, g)), 0, 1), s.haz(m).squeeze(1)

    net = VWM().to(dev)
    opt = torch.optim.AdamW(net.parameters(), 1e-3, weight_decay=1e-5)
    T = lambda x: torch.from_numpy(x).to(dev)
    tc, ta, tn, ty = T(cur_tr), T(TR.onehot(act_tr)), T(nxt_tr).unsqueeze(1), T(y_tr.astype(np.float32))
    cc, cca = T(cur_ca), T(TR.onehot(act_ca))
    wtr = 1.0 + change_weight * (tn - tc[:, -1:]).abs().gt(0.05).float()
    pw = torch.tensor([max(1.0, float((y_tr == 0).sum()) / max(1.0, float((y_tr == 1).sum())))], device=dev)
    bce = nn.BCEWithLogitsLoss(pos_weight=pw)
    from sklearn.metrics import average_precision_score
    n, bs = len(tc), 256
    gen = torch.Generator().manual_seed(seed)
    best_c, best_ap, best_f, best_fm, pc, pf, params = None, -1, None, 1e9, 0, 0, sum(p.numel() for p in net.parameters())
    chg_ca = np.abs(nxt_ca - cur_ca[:, -1]) > 0.05
    for ep in range(epochs):
        net.train()
        for idx in torch.randperm(n, generator=gen).split(bs):
            opt.zero_grad(set_to_none=True)
            pfm, pl = net(tc[idx], ta[idx])
            (((pfm - tn[idx]) ** 2 * wtr[idx]).mean() + lam * bce(pl, ty[idx])).backward(); opt.step()
        net.eval()
        with torch.no_grad():
            pfr, pl = net(cc, cca)
            ap = average_precision_score(y_ca, pl.cpu().numpy()) if y_ca.min() != y_ca.max() else 0.0
            fm = float(np.abs(pfr.squeeze(1).cpu().numpy() - nxt_ca)[chg_ca].mean())
        imp = False
        if ap > best_ap + 1e-5:
            best_ap, best_c, pc, imp = ap, {k: v.detach().clone() for k, v in net.state_dict().items()}, 0, True
        if fm < best_fm - 1e-6:
            best_fm, best_f, pf, imp = fm, {k: v.detach().clone() for k, v in net.state_dict().items()}, 0, True
        pc += 0 if imp else 1; pf += 0 if imp else 1
        if ep == 0 or (ep + 1) % 10 == 0:
            print(f"  ep={ep+1} calib caution_AP={ap:.4f}(best {best_ap:.4f}) frame_dyn={fm:.4f}(best {best_fm:.4f})", flush=True)
        if min(pc, pf) >= 10:
            break

    def scores(state, cur, act):
        net.load_state_dict(state); net.eval()
        with torch.no_grad():
            pfr, pl = net(T(cur), T(TR.onehot(act)))
        return pfr.squeeze(1).cpu().numpy(), pl.cpu().numpy()

    return scores, best_c, best_f, params, str(dev)


def main():
    global LEDGER, OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--hard", action="store_true", help="oblique camera + tall occluding obstacles (increment 3)")
    ap.add_argument("--margin-primary", action="store_true",
                    help="amendment2: half-budget (0.05) calibration is PRIMARY; G2 = realized FPR <= 0.10")
    a = ap.parse_args()
    scene = "hard" if a.hard else "easy"
    arm = "p05" if a.margin_primary else "p10"
    g2_limit = TARGET_FPR if a.margin_primary else 1.25 * TARGET_FPR
    fseed = (779 if a.margin_primary else 778) if a.hard else FINAL_SEED
    nt, nc, nf, epochs = 600, 200, 300, 60
    if a.hard:
        OUT = ROOT / ("docs/research/vision_world_model_result_v3b_hard_margin.json" if a.margin_primary
                      else "docs/research/vision_world_model_result_v3_hard.json")
    if a.smoke:
        import tempfile
        nt, nc, nf, fseed, epochs = 24, 10, 12, 999998 if a.hard else 999999, 3
        tmp = Path(tempfile.mkdtemp(prefix="vwm_smoke_"))
        LEDGER = tmp / "ledger.jsonl"; OUT = tmp / "result.json"
        print(f"SMOKE scene={scene}: tiny config, throwaway seed/ledger/out ->", tmp)
    if a.dry_run:
        p = json.loads(PROTOCOL.read_text(encoding="utf-8"))
        print(f"=== {p['study_id']} ({p['status']}) === branch: {p['branch']}")
        print("primary:", p["gates"]["primary_success"])
        print(f"scene={scene} sealed final seed {fseed}: " + ("ALREADY opened -> would REFUSE" if ledger_has(fseed) else "not yet opened -> eligible"))
        print(f"primary arm {arm}, G2 limit {g2_limit}")
        print(f"run: python scripts/vision_wm_final_v2.py{' --hard' if a.hard else ''}{' --margin-primary' if a.margin_primary else ''}")
        return
    if ledger_has(fseed):
        raise SystemExit(f"REFUSE: sealed final seed {fseed} already in {LEDGER}; the final runs once.")

    t0 = time.time()
    ftr, atr, htr = D.collect(nt, STEPS, SIZE, seed=TRAIN_SEED, scene=scene)
    fca, aca, hca = D.collect(nc, STEPS, SIZE, seed=CALIB_SEED, scene=scene)
    tr = TR.build(ftr, atr, htr, H, K)
    ca = TR.build(fca, aca, hca, H, K)
    cur_tr, act_tr, nxt_tr, y_tr = tr
    cur_ca, act_ca, nxt_ca, y_ca = ca
    print(f"train {len(cur_tr)} / calib {len(cur_ca)} transitions; prevalence tr {y_tr.mean():.3f} ca {y_ca.mean():.3f} ({round(time.time()-t0)}s)", flush=True)

    scores, best_c, best_f, params, dev = train_vwm(tr, ca, epochs=epochs)

    # linear probe + ridge baselines
    flat = lambda c, ac: np.concatenate([c.reshape(len(c), -1), TR.onehot(ac)], 1)
    probe = LogisticRegression(max_iter=400, C=0.5, class_weight="balanced").fit(flat(cur_tr, act_tr), y_tr)

    # calibrate on calibration split
    _, cnn_ca = scores(best_c, cur_ca, act_ca)
    probe_ca = probe.predict_proba(flat(cur_ca, act_ca))[:, 1]
    thr = {m: {f: calibrate(sc, y_ca, fpr) for f, fpr in (("p10", TARGET_FPR), ("p05", TARGET_FPR / 2))}
           for m, sc in (("cnn", cnn_ca), ("probe", probe_ca))}

    # SINGLE FINAL OPEN
    record_final(fseed, f"vision-world-model-v2 registered final (scene={scene})")
    ffi, afi, hfi = D.collect(nf, STEPS, SIZE, seed=fseed, scene=scene)
    cur_fi, act_fi, nxt_fi, y_fi = TR.build(ffi, afi, hfi, H, K)
    frame_fi_bestf, _ = scores(best_f, cur_fi, act_fi)
    _, cnn_fi = scores(best_c, cur_fi, act_fi)
    probe_fi = probe.predict_proba(flat(cur_fi, act_fi))[:, 1]

    res = {"caution": {}, "frame": {}}
    for m, sc in (("cnn", cnn_fi), ("probe", probe_fi)):
        per_arm = {}
        for f in ("p10", "p05"):
            r, fp = recall_fpr(sc, y_fi, thr[m][f])
            per_arm[f] = {"target_fpr": TARGET_FPR if f == "p10" else TARGET_FPR / 2, "recall": r, "realized_fpr": fp}
        res["caution"][m] = {**per_arm, **TR.auc(y_fi, sc)}
    res["caution"]["base_rate"] = {"auc_pr": float(y_fi.mean()), "prevalence": float(y_fi.mean())}
    res["frame"]["persistence"] = TR.mae_report(cur_fi[:, -1], nxt_fi, cur_fi[:, -1])
    res["frame"]["ridge"] = TR.mae_report(TR.ridge_frame(cur_tr, act_tr, nxt_tr, cur_fi, act_fi), nxt_fi, cur_fi[:, -1])
    res["frame"]["cnn_best_frame"] = TR.mae_report(frame_fi_bestf, nxt_fi, cur_fi[:, -1])

    boot = boot_recall_diff(cnn_fi, probe_fi, y_fi, thr["cnn"][arm], thr["probe"][arm])
    g1 = (res["caution"]["cnn"][arm]["recall"] > res["caution"]["probe"][arm]["recall"]
          and res["caution"]["cnn"]["auc_pr"] > res["caution"]["probe"]["auc_pr"] and boot["ci95"][0] > 0)
    g2 = res["caution"]["cnn"][arm]["realized_fpr"] <= g2_limit
    gates = {"primary_arm": arm, "G2_limit": g2_limit,
             "G1_caution_beats_linear": bool(g1), "G2_budget_holds": bool(g2),
             "recall_diff_bootstrap": boot, "primary_success": bool(g1 and g2)}

    print(f"\nFINAL (sealed seed {fseed}, {len(cur_fi)} transitions, prevalence {y_fi.mean():.3f}):")
    for m in ("cnn", "probe", "base_rate"):
        c = res["caution"][m]
        if m == "base_rate":
            print(f"  {m:6s} AUC-PR {c['auc_pr']:.3f}")
        else:
            print(f"  {m:6s} AUC-PR {c['auc_pr']:.3f} ROC {c['auc_roc']:.3f} | recall@fpr0.10 {c['p10']['recall']:.3f} (realized fpr {c['p10']['realized_fpr']:.3f}) | @fpr0.05 {c['p05']['recall']:.3f}")
    print(f"  frame dyn-MAE: persistence {res['frame']['persistence']['dynamic_region_mae']:.3f} ridge {res['frame']['ridge']['dynamic_region_mae']:.3f} cnn(best-frame) {res['frame']['cnn_best_frame']['dynamic_region_mae']:.3f}")
    print(f"  recall diff (cnn-probe) {boot['recall_difference']:+.3f} CI95 {boot['ci95']}")
    print(f"  G1 {'PASS' if g1 else 'FAIL'}  G2 {'PASS' if g2 else 'FAIL'}  => primary {'PASS' if gates['primary_success'] else 'FAIL'}")

    doc = {"schema_version": "vision-world-model-result-v2", "protocol": PROTOCOL.name,
           "status": "registered final, opened once; branch work (not main); advisory only",
           "scene": scene, "final_seed": fseed, "trainable_parameters": params, "device": dev,
           "thresholds": thr, "results": res, "gates": gates}
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
