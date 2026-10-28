#!/usr/bin/env python3
"""EXPLORATORY dev check for protocol v4 (draft), on SPENT Robotarium runs only. Branch work, not main.

Three questions, answered before any v4 run exists:
  1. Model: which camera-tracked state model (camera_track.py positions) to make primary -- boosted
     trees trained on TRUE positions and fed tracked ones (A), or trained on tracked positions (B);
     each either on the tracked reading only ('plain') or the max over both robot/obstacle readings
     while identity is unresolved before the first move ('max').
  2. Threshold rule: does a threshold travel to runs it never saw? Every Robotarium batch (2xx..7xx)
     is held out in turn. Models are fitted on the other batches; the cross-fitted rule takes the
     (1 - q) quantile of the hazard-free decisions' out-of-fold scores, pooled over an inner
     leave-one-batch-out on the training batches, for q in 0.10 / 0.08 / 0.06 / 0.05. The study-B-style
     rule (q = 0.05 on four random held-out calibration runs) is run alongside for comparison.
  3. Power: sealed sets of N runs are drawn (with replacement) from the 35 spent runs' out-of-fold
     scores and per-batch thresholds, and the draft v4 gates are evaluated on each.
  With --with-head: the frozen study-B fine-tuned DINOv2 head (secondary comparison of the draft) is
  scored on runs 701-712, its only out-of-sample runs, and S1's power is estimated from them.

Optimistic: the same spent runs shaped the tracker (camera_track.py was fixed on them) and choose
the model, the rule and the gate. Output docs/research/vision_caution_tracking_devcheck_v1.json.
Not evidence.

Usage: CUDA_VISIBLE_DEVICES=-1 python scripts/robotarium/dev_tracking_v4.py [--with-head]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(HERE))

OUT = ROOT / "docs/research/vision_caution_tracking_devcheck_v1.json"
SCORES = ROOT / "target/robotarium/tracking_devcheck_scores.npz"
V3 = ROOT / "docs/research/vision_caution_robotarium_protocol_v3.json"
HEAD = ROOT / "docs/research/artifacts/vision-caution-arena-v1/sim_finetune_head.npz"
HEAD_THR = ROOT / "docs/research/artifacts/vision-caution-arena-v1/thresholds.json"
STUDY_B_USABLE = [701, 703, 704, 705, 706, 707, 708, 709, 710, 711, 712]   # 702: no processed frames
KEEP = ("kinds", "features", "hazards", "clearance", "margin", "contact", "robot_xy", "obstacle_xy")
QS, BUDGET = (0.10, 0.08, 0.06, 0.05), 0.10
TRACKED = ("trackA_plain", "trackA_max", "trackB_plain", "trackB_max")
N_SET, DRAWS, INNER = (6, 8, 10, 12, 16), 400, 500
FLOORS = (0.25, 0.30, 0.35, 0.40)
AP_DRAWS, AP_INNER = 200, 200


def load_runs(names):
    """Quality-gated runs with the tracker's output attached (frames dropped to save memory)."""
    import camera_track as CT
    import evaluate_real as ER
    import train_eval_real as TE
    runs, skipped = {}, {}
    for n in names:
        p = TE.RUNS / n
        if not ((p / "camera.json").exists() and (p / "frames.npz").exists()):
            skipped[n] = "no processed frames"
            continue
        ok, _ = ER.quality(p)
        if not ok:
            skipped[n] = "quality gate"
            continue
        d = np.load(p / "frames.npz")
        tr = CT.track(d["inspect"])
        runs[n] = {**{k: d[k] for k in KEEP}, **{f"trk_{k}": v for k, v in tr.items()}}
    return runs, skipped


def concat(runs, names):
    parts = [runs[n] for n in names]
    d = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
    return d, np.concatenate([[n] * len(runs[n]["kinds"]) for n in names])


def feats(d, i):
    import camera_track as CT
    import vision_runtime_proxy_final as RP
    return (RP.state_features(d, i), CT.state_features(d["trk_robot"], d["trk_obstacle"], i),
            CT.state_features(d["trk_alt_robot"], d["trk_alt_obstacle"], i))


def fit(d, i):
    from sklearn.ensemble import HistGradientBoostingClassifier as HGB
    from sklearn.linear_model import LogisticRegression
    true, trk, _ = feats(d, i)
    return {"act": LogisticRegression(max_iter=1000, C=1.0, class_weight="balanced").fit(i["a10"], i["y"]),
            "true": HGB(random_state=0).fit(true, i["y"]), "trk": HGB(random_state=0).fit(trk, i["y"])}


def score(m, d, i):
    true, trk, alt = feats(d, i)
    p = lambda mdl, X: mdl.predict_proba(X)[:, 1]
    return {"action_only": p(m["act"], i["a10"]), "state_true": p(m["true"], true),
            "trackA_plain": p(m["true"], trk), "trackA_max": np.maximum(p(m["true"], trk), p(m["true"], alt)),
            "trackB_plain": p(m["trk"], trk), "trackB_max": np.maximum(p(m["trk"], trk), p(m["trk"], alt))}


def fit_score(runs, train, test):
    import vision_runtime_proxy_final as RP
    dtr, _ = concat(runs, train)
    dte, rte = concat(runs, test)
    itr, ite = RP.decisions(dtr), RP.decisions(dte)
    return score(fit(dtr, itr), dte, ite), ite, rte


def cluster_counts(hit, y, ep, n_ep):
    pos = y == 1
    return (np.bincount(ep[pos], weights=hit[pos].astype(np.float64), minlength=n_ep),
            np.bincount(ep[pos], minlength=n_ep).astype(np.float64))


def gates_on(sel, D, arm, q, rng):
    """Draft v4 gates on one drawn sealed set (decision indices `sel`, episode ids already re-labelled)."""
    y, ep = D["y"][sel], D["ep_draw"]
    n_ep = int(ep.max()) + 1
    ht = D[arm][sel] > D[f"thr_{arm}_{q}"][sel]
    ha = D["action_only"][sel] > D[f"thr_action_only_{q}"][sel]
    nt, npos = cluster_counts(ht, y, ep, n_ep)
    na, _ = cluster_counts(ha, y, ep, n_ep)
    idx = rng.integers(0, n_ep, (INNER, n_ep))
    den = np.maximum(npos[idx].sum(1), 1.0)
    rec_t = nt[idx].sum(1) / den
    diff = (nt[idx].sum(1) - na[idx].sum(1)) / den
    fpr = float(ht[y == 0].mean())
    return {"G1": np.quantile(diff, 0.025) > 0, "G2": fpr <= BUDGET, "recall_lo": float(np.quantile(rec_t, 0.025)),
            "recall": float(nt.sum() / max(npos.sum(), 1)), "fpr": fpr}


def power(D, arm, q, run_names, seed=0):
    rng = np.random.default_rng(seed)
    rows = {n: np.flatnonzero(D["run"] == n) for n in run_names}
    out = {}
    for N in N_SET:
        res = []
        for _ in range(DRAWS):
            pick = rng.choice(run_names, N, replace=True)
            sel = np.concatenate([rows[n] for n in pick])
            # episodes re-labelled per drawn slot, so a run drawn twice counts as separate clusters
            ep, off = [], 0
            for n in pick:
                e_local = D["ep_local"][rows[n]]
                ep.append(e_local + off)
                off += int(e_local.max()) + 1
            D["ep_draw"] = np.concatenate(ep)
            res.append(gates_on(sel, D, arm, q, rng))
        g1 = np.array([r["G1"] for r in res])
        g2 = np.array([r["G2"] for r in res])
        lo = np.array([r["recall_lo"] for r in res])
        out[str(N)] = {"G1": float(g1.mean()), "G2": float(g2.mean()), "G1_and_G2": float((g1 & g2).mean()),
                       **{f"G1_G2_and_recall_lo_ge_{f:.2f}": float((g1 & g2 & (lo >= f)).mean()) for f in FLOORS},
                       "median_recall": float(np.median([r["recall"] for r in res])),
                       "median_fpr": float(np.median([r["fpr"] for r in res]))}
    return out


def head_part(runs, D, arm):
    """Frozen study-B fine-tuned head on runs 701-712 (its out-of-sample runs) against the tracked arm."""
    import torch
    import study_b as SB
    import vision_runtime_proxy_final as RP
    import vision_wm_pretrained_encoders as PE
    import vision_wm_train as TR
    names = [f"seed{s}" for s in STUDY_B_USABLE if f"seed{s}" in runs]
    pool = json.loads(HEAD_THR.read_text(encoding="utf-8"))["pool"]
    z = np.load(HEAD)
    head = RP.make_head(pool, 10)
    head.load_state_dict({k[5:]: torch.from_numpy(z[k]) for k in z.files if k.startswith("head.")})
    head.eval()
    enc = PE.load_dino(True).cpu()
    ins = np.concatenate([np.load(ROOT / "target/robotarium/runs" / n / "frames.npz")["inspect"] for n in names])
    d7, r7 = concat(runs, names)
    i7 = RP.decisions(d7)
    Fx = RP.extract(enc, ins.astype(np.float32) / 255.0, pools=(pool,))
    s_head = RP.score_head(head, Fx[pool], i7, i7["a10"])
    del Fx, ins
    sel = np.concatenate([np.flatnonzero(D["run"] == n) for n in names])     # same run order, same decision order
    assert np.array_equal(D["y"][sel], i7["y"])
    s_trk, y = D[arm][sel], i7["y"]
    ep = i7["e"]
    n_ep = len(d7["kinds"])
    res = {"runs": names, "decisions": int(len(y)), "head_auc": TR.auc(y, s_head), f"{arm}_auc": TR.auc(y, s_trk),
           "S1_auc_pr_boot": SB.auc_pr_boot(s_trk, s_head, y, ep, n_ep)}
    rng = np.random.default_rng(1)
    ep_rows = {n: [np.flatnonzero(ep == e) for e in np.flatnonzero(r7 == n)] for n in names}
    from sklearn.metrics import average_precision_score as ap
    pw = {}
    for N in N_SET:
        hits = 0
        for _ in range(AP_DRAWS):
            pick = rng.choice(names, N, replace=True)
            blocks = [b for n in pick for b in ep_rows[n]]                    # episode clusters, as the gate
            diffs = []
            for _ in range(AP_INNER):
                idx = np.concatenate([blocks[k] for k in rng.integers(0, len(blocks), len(blocks))])
                if y[idx].min() != y[idx].max():
                    diffs.append(ap(y[idx], s_trk[idx]) - ap(y[idx], s_head[idx]))
            hits += bool(diffs) and np.quantile(diffs, 0.025) > 0
        pw[str(N)] = hits / AP_DRAWS
    res["S1_power_by_runs"] = pw
    return res, s_head


def main():
    import vision_wm_train as TR
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("--with-head", action="store_true")
    a = ap_.parse_args()
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "-1":
        raise SystemExit("REFUSE: CPU only; set CUDA_VISIBLE_DEVICES=-1")
    t0 = time.time()
    v3 = json.loads(V3.read_text(encoding="utf-8"))["runs"]
    names = [f"seed{s}" for s in v3["spent_real_seeds"] + STUDY_B_USABLE]
    runs, skipped = load_runs(names)
    batches = {}
    for n in runs:
        batches.setdefault(n[4], []).append(n)
    print(f"{len(runs)} spent runs usable ({json.dumps({b: len(v) for b, v in sorted(batches.items())})}); "
          f"skipped {skipped} ({round(time.time() - t0)}s)", flush=True)

    rng = np.random.default_rng(0)
    cols = {k: [] for k in ("y", "run", "ep_local", "batch", "prox", "geo")}
    arms_all = ("action_only", "state_true") + TRACKED
    for k in arms_all:
        cols[k] = []
        for q in QS:
            cols[f"thr_{k}_{q}"] = []
        cols[f"thr_{k}_cal4"] = []
    per_batch = {}
    for b in sorted(batches):
        test = batches[b]
        train = [n for c in sorted(batches) if c != b for n in batches[c]]
        s_out, ite, rte = fit_score(runs, train, test)
        inner = {k: [] for k in arms_all}
        inner_y = []
        for c in sorted(batches):
            if c == b:
                continue
            s_c, i_c, _ = fit_score(runs, [n for n in train if n not in batches[c]], batches[c])
            for k in arms_all:
                inner[k].append(s_c[k])
            inner_y.append(i_c["y"])
        inner_y = np.concatenate(inner_y)
        thr = {k: {q: float(np.quantile(np.concatenate(inner[k])[inner_y == 0], 1 - q)) for q in QS} for k in arms_all}
        cal = list(rng.choice(train, 4, replace=False))                           # study-B-style rule
        s_cal, i_cal, _ = fit_score(runs, [n for n in train if n not in cal], cal)
        thr_cal4 = {k: float(np.quantile(s_cal[k][i_cal["y"] == 0], 0.95)) for k in arms_all}
        y = ite["y"]
        nd = len(y)
        cols["y"].append(y)
        cols["run"].append(rte[ite["e"]])
        cols["ep_local"].append(np.array([int(np.sum(rte[:e] == rte[e])) for e in ite["e"]]))
        cols["batch"].append(np.full(nd, int(b)))
        cols["prox"].append(ite["types"]["proximity"])
        cols["geo"].append(ite["types"]["geofence"])
        pb = {"runs": test, "decisions": nd, "prevalence": float(y.mean())}
        for k in arms_all:
            cols[k].append(s_out[k])
            for q in QS:
                cols[f"thr_{k}_{q}"].append(np.full(nd, thr[k][q]))
            cols[f"thr_{k}_cal4"].append(np.full(nd, thr_cal4[k]))
            r = {"auc": TR.auc(y, s_out[k])}
            for q in QS:
                h = s_out[k] > thr[k][q]
                r[f"q{q}"] = {"recall": float(h[y == 1].mean()), "fpr": float(h[y == 0].mean())}
            h = s_out[k] > thr_cal4[k]
            r["cal4_q0.05"] = {"recall": float(h[y == 1].mean()), "fpr": float(h[y == 0].mean()), "calibration_runs": cal}
            pb[k] = r
        per_batch[b] = pb
        print(f"held-out batch {b}xx ({len(test)} runs, {nd} decisions): " + " | ".join(
            f"{k} AP {pb[k]['auc']['auc_pr']:.3f} fpr@q.08 {pb[k]['q0.08']['fpr']:.3f} cal4 {pb[k]['cal4_q0.05']['fpr']:.3f}"
            for k in ("action_only", "state_true", "trackA_max", "trackB_max")) + f" ({round(time.time() - t0)}s)", flush=True)

    D = {k: np.concatenate(v) for k, v in cols.items()}
    y = D["y"]
    pooled = {}
    for k in arms_all:
        r = {"auc": TR.auc(y, D[k])}
        for q in list(QS) + ["cal4"]:
            h = D[k] > D[f"thr_{k}_{q}"]
            fprs = [float(h[(D["batch"] == int(b)) & (y == 0)].mean()) for b in sorted(batches)]
            r[f"q{q}" if q != "cal4" else "cal4_q0.05"] = {
                "recall": float(h[y == 1].mean()), "fpr": float(h[y == 0].mean()),
                "fpr_by_batch": fprs, "max_batch_fpr": max(fprs), "min_batch_fpr": min(fprs),
                "recall_proximity": float(h[D["prox"] == 1].mean()), "recall_geofence": float(h[D["geo"] == 1].mean())}
        pooled[k] = r
    primary = max(TRACKED, key=lambda k: pooled[k]["auc"]["auc_pr"])
    ok_q = [q for q in QS if pooled[primary][f"q{q}"]["max_batch_fpr"] <= BUDGET
            and pooled["action_only"][f"q{q}"]["max_batch_fpr"] <= BUDGET]
    q_star = max(ok_q) if ok_q else min(QS)
    print("\npooled out-of-fold over", len(runs), "runs,", len(y), "decisions, prevalence", round(float(y.mean()), 3))
    for k in arms_all:
        r = pooled[k]
        print(f"  {k:13s} AUC-PR {r['auc']['auc_pr']:.3f} ROC {r['auc']['auc_roc']:.3f} | " + " | ".join(
            f"q{q}: rec {r[f'q{q}']['recall']:.3f} fpr {r[f'q{q}']['fpr']:.3f} (max batch {r[f'q{q}']['max_batch_fpr']:.3f})"
            for q in QS) + f" | cal4: rec {r['cal4_q0.05']['recall']:.3f} fpr {r['cal4_q0.05']['fpr']:.3f} "
            f"(batches {min(r['cal4_q0.05']['fpr_by_batch']):.3f}-{r['cal4_q0.05']['max_batch_fpr']:.3f})")
    print(f"selected by the script's rule: primary {primary} (highest pooled AUC-PR among tracked variants); "
          f"q* = {q_star} (largest q whose max held-out-batch FPR <= {BUDGET} for the primary and action-only)")

    pw = power(D, primary, q_star, sorted(runs))
    print("power (draft v4 gates, primary at q*):")
    for N, r in pw.items():
        print(f"  N={N:>2}: G1 {r['G1']:.2f} G2 {r['G2']:.2f} G1&G2 {r['G1_and_G2']:.2f} | " + " ".join(
            f"floor{f:.2f} {r[f'G1_G2_and_recall_lo_ge_{f:.2f}']:.2f}" for f in FLOORS)
            + f" | median recall {r['median_recall']:.3f} fpr {r['median_fpr']:.3f}")

    head = None
    if a.with_head:
        head, s_head = head_part(runs, D, primary)
        print(f"head (frozen study-B fine-tuned) on {len(head['runs'])} runs: AUC-PR {head['head_auc']['auc_pr']:.3f} vs "
              f"{primary} {head[f'{primary}_auc']['auc_pr']:.3f}; S1 diff CI95 {head['S1_auc_pr_boot']['ci95']}; "
              f"S1 power by runs {head['S1_power_by_runs']}", flush=True)

    SCORES.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(SCORES, **{k: v for k, v in D.items() if k != "ep_draw"})
    OUT.write_text(json.dumps({
        "schema_version": "vision-caution-tracking-devcheck-v1",
        "status": "EXPLORATORY dev check on spent runs for the draft protocol v4; not evidence (optimistic: these runs "
                  "shaped the tracker and choose the model, rule and gates)",
        "runs": sorted(runs), "skipped": skipped, "batches": {b: v for b, v in sorted(batches.items())},
        "decisions": int(len(y)), "prevalence": float(y.mean()),
        "design": {"outer": "leave-one-batch-out (Robotarium batches 2xx..7xx)",
                   "rule_cross_fitted": "threshold = (1 - q) quantile of hazard-free out-of-fold scores pooled over an inner "
                                        "leave-one-batch-out on the training batches; model refit on all training batches",
                   "rule_cal4": "study-B style: 0.95 quantile on four random held-out training runs (rng seed 0)",
                   "arms": {"trackA": "boosted trees trained on TRUE positions, scored on camera-tracked positions",
                            "trackB": "boosted trees trained and scored on camera-tracked positions",
                            "_max": "max over both robot/obstacle readings while identity is unresolved (before the first move)",
                            "state_true": "true positions (reference)", "action_only": "logistic regression on the action"}},
        "pooled_out_of_fold": pooled, "per_batch": per_batch,
        "selected": {"primary": primary, "q_star": q_star,
                     "rule": "primary = highest pooled out-of-fold AUC-PR among tracked variants; q* = largest q whose "
                             "maximum held-out-batch false-alarm rate is <= 0.10 for both the primary and action-only"},
        "power": {"arm": primary, "q": q_star, "draws": DRAWS, "inner_bootstrap": INNER, "by_runs": pw},
        "head_comparison": head,
        "elapsed_s": round(time.time() - t0)}, indent=1) + "\n", encoding="utf-8")
    print("wrote", OUT.relative_to(ROOT), f"({round(time.time() - t0)}s)")


if __name__ == "__main__":
    main()
