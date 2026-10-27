#!/usr/bin/env python3
"""EXPLORATORY power check for study B (protocol v3) BEFORE any of its sealed runs return.

How likely is the registered G1 gate (camera arm beats action-only: higher AUC-PR, higher
recall, episode-cluster CI95 lower bound > 0) to pass with N usable sealed runs, if the
composite sim head behaves on fresh runs as it does on the spent ones?

Method: a composite-recipe sim head (dev_arena_sim settings, 400/150 sim episodes) and an
action-only model are scored on the 20 spent non-calibration runs (action-only cross-fitted
across two halves so no run is scored in-sample); thresholds come from the protocol's four
calibration runs, as registered. Then, for each N, sealed sets of N runs are drawn with
replacement from the 20 runs, and G1 + G2 are evaluated exactly as study_b.py does
(1000-replicate episode bootstrap inside each draw). Optimistic: the spent runs also chose the
recipe. Output docs/research/vision_caution_study_b_power_v1.json. Not evidence.

Usage: CUDA_VISIBLE_DEVICES=-1 python scripts/robotarium/power_study_b.py
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

OUT = ROOT / "docs/research/vision_caution_study_b_power_v1.json"
OUT_V2 = ROOT / "docs/research/vision_caution_study_b_power_v2.json"
SCORES = ROOT / "target/robotarium/power_study_b_scores.npz"
N_SET = (4, 6, 8, 10, 12, 16)
DRAWS, INNER = 400, 1000
AP_DRAWS, AP_INNER = 200, 200


def auc_pr_diff_lower(sv, sa, y, ep, rng):
    """Episode-cluster bootstrap CI95 lower bound of AUC-PR(vision) - AUC-PR(action)."""
    from sklearn.metrics import average_precision_score
    _, epd = np.unique(ep, return_inverse=True)
    rows = [np.flatnonzero(epd == k) for k in range(epd.max() + 1)]
    diffs = []
    for _ in range(AP_INNER):
        idx = np.concatenate([rows[k] for k in rng.integers(0, len(rows), len(rows))])
        if y[idx].min() == y[idx].max():
            continue
        diffs.append(average_precision_score(y[idx], sv[idx]) - average_precision_score(y[idx], sa[idx]))
    return float(np.quantile(diffs, 0.025)) if diffs else float("nan")


def gate_variants():
    """EXPLORATORY: power of the registered gate and two pre-result alternatives, from saved scores."""
    import vision_wm_final_v2 as FV
    z = np.load(SCORES, allow_pickle=True)
    per_run = z["per_run"].item()
    cal = z["cal"].item()
    rest = sorted(per_run)
    th = {b: (FV.calibrate(cal["sv"], cal["y"], b), FV.calibrate(cal["sa"], cal["y"], b)) for b in (0.05, 0.10)}
    pooled = {}
    ally = np.concatenate([per_run[n]["y"] for n in rest])
    allv = np.concatenate([per_run[n]["sv"] for n in rest]); alla = np.concatenate([per_run[n]["sa"] for n in rest])
    for b, (tv, ta) in th.items():
        pooled[f"calibrated_fpr_{b}"] = {"recall_sim_arena": float((allv[ally == 1] > tv).mean()),
                                         "recall_action_only": float((alla[ally == 1] > ta).mean()),
                                         "fpr_sim_arena": float((allv[ally == 0] > tv).mean())}
    rng = np.random.default_rng(1)
    power = {}
    for N in N_SET:
        counts = {"registered_half_budget": 0, "full_budget_thresholds": 0, "auc_pr_ci_gate": 0}
        for d in range(AP_DRAWS):
            pick = rng.choice(rest, size=N, replace=True)
            y = np.concatenate([per_run[n]["y"] for n in pick])
            ep = np.concatenate([per_run[n]["ep"] + 1000 * j for j, n in enumerate(pick)])
            sv = np.concatenate([per_run[n]["sv"] for n in pick]); sa = np.concatenate([per_run[n]["sa"] for n in pick])
            g1, g2 = g1_g2(sv, sa, *th[0.05], y, ep, rng)
            counts["registered_half_budget"] += g1 and g2
            g1f, g2f = g1_g2(sv, sa, *th[0.10], y, ep, rng)
            counts["full_budget_thresholds"] += g1f and g2f
            if g2 and y.min() != y.max():
                counts["auc_pr_ci_gate"] += auc_pr_diff_lower(sv, sa, y, ep, rng) > 0
        power[N] = {k: v / AP_DRAWS for k, v in counts.items()}
        print(f"  N={N:2d}: " + ", ".join(f"{k} {v:.2f}" for k, v in power[N].items()), flush=True)
    doc = {"schema_version": "vision-caution-study-b-power-v2",
           "status": "EXPLORATORY gate comparison on spent runs before any study-B sealed result; optimistic (the same runs chose the recipe); not evidence; no gate is changed by this file",
           "variants": {"registered_half_budget": "protocol v3 as registered: thresholds at calibration FPR 0.05; recall higher, recall-difference CI95 > 0, AUC-PR higher; G2 <= 0.10",
                        "full_budget_thresholds": "same, thresholds at calibration FPR 0.10 (G2 still <= 0.10 on sealed)",
                        "auc_pr_ci_gate": "G1 replaced by: episode-cluster CI95 lower bound of AUC-PR difference > 0; G2 as registered"},
           "pooled_on_spent": pooled, "draws": AP_DRAWS, "inner_bootstrap": {"recall": INNER, "auc_pr": AP_INNER},
           "power_by_usable_sealed_runs": power}
    OUT_V2.write_text(json.dumps(doc, indent=1, default=float) + "\n", encoding="utf-8")
    print("wrote", OUT_V2)


def g1_g2(sv, sa, tv, ta, y, ep, rng):
    """study_b.py's G1/G2 on one drawn sealed set (inner episode bootstrap of the recall difference)."""
    import vision_wm_train as TR
    from sklearn.metrics import average_precision_score
    pos = y == 1
    if pos.sum() == 0 or (~pos).sum() == 0:
        return False, False
    hv, ha = sv > tv, sa > ta
    _, epd = np.unique(ep, return_inverse=True)
    n_ep = epd.max() + 1
    nv = np.bincount(epd[pos], weights=hv[pos].astype(float), minlength=n_ep)
    na = np.bincount(epd[pos], weights=ha[pos].astype(float), minlength=n_ep)
    npos = np.bincount(epd[pos], minlength=n_ep).astype(float)
    idx = rng.integers(0, n_ep, (INNER, n_ep))
    diff = (nv[idx].sum(1) - na[idx].sum(1)) / np.maximum(npos[idx].sum(1), 1.0)
    g1 = (average_precision_score(y, sv) > average_precision_score(y, sa) and hv[pos].mean() > ha[pos].mean()
          and np.quantile(diff, 0.025) > 0)
    g2 = hv[~pos].mean() <= 0.10
    return bool(g1), bool(g2)


def main():
    import torch
    from sklearn.linear_model import LogisticRegression

    import dev_arena_sim as DA
    import study_b as SB
    import train_eval_real as TE
    import vision_runtime_proxy_final as RP
    import vision_wm_final_v2 as FV
    import vision_wm_pretrained_encoders as PE
    import vision_wm_train as TR

    if os.environ.get("CUDA_VISIBLE_DEVICES") != "-1":
        raise SystemExit("CPU only; set CUDA_VISIBLE_DEVICES=-1")
    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "8")))
    t0 = time.time()
    proto = json.loads((ROOT / "docs/research/vision_caution_robotarium_protocol_v3.json").read_text(encoding="utf-8"))
    spent = [f"seed{s}" for s in proto["runs"]["spent_real_seeds"]]
    cal = [f"seed{s}" for s in proto["runs"]["calibration_seeds"]]
    rest = [n for n in spent if n not in cal]
    bg = DA.real_background(spent)
    enc = PE.load_dino(True).cpu()
    Fs, Ds = SB.sim_features(enc, 400, 950, bg, 0, pools=(4,))
    Fse, Dse = SB.sim_features(enc, 150, 951, bg, 1, pools=(4,))
    istr, isse = RP.decisions(Ds), RP.decisions(Dse)
    head, sel_ap = TE.train_head(Fs[4], Fse[4], istr, isse, istr["a10"], isse["a10"], 4, 60)
    print(f"sim head ready, sim selection AUC-PR {sel_ap:.3f} ({round(time.time() - t0)}s)", flush=True)

    def run_scores(names):
        d, _, _ = TE.load_split(names, gate=True)
        i = RP.decisions(d)
        F = RP.extract(enc, d["inspect"].astype(np.float32) / 255.0, pools=(4,))[4]
        return d, i, RP.score_head(head, F, i, i["a10"])

    dc, ic, sc = run_scores(cal)
    per_run = {}
    halves = (rest[::2], rest[1::2])
    for k, half in enumerate(halves):
        other = halves[1 - k]
        d_other, _, _ = TE.load_split(other, gate=True)
        i_other = RP.decisions(d_other)
        act = LogisticRegression(max_iter=1000, C=1.0, class_weight="balanced").fit(i_other["a10"], i_other["y"])
        for n in half:
            d, i, s = run_scores([n])
            per_run[n] = {"y": i["y"], "ep": i["e"], "sv": s, "sa": act.predict_proba(i["a10"])[:, 1]}
        if k == 0:
            act_cal = act
    sa_cal = act_cal.predict_proba(ic["a10"])[:, 1]
    np.savez(SCORES, per_run=np.array(per_run, dtype=object), cal=np.array({"sv": sc, "sa": sa_cal, "y": ic["y"]}, dtype=object))
    tv = FV.calibrate(sc, ic["y"], 0.05)
    ta = FV.calibrate(sa_cal, ic["y"], 0.05)
    allv = np.concatenate([per_run[n]["sv"] for n in rest]); alla = np.concatenate([per_run[n]["sa"] for n in rest])
    ally = np.concatenate([per_run[n]["y"] for n in rest])
    pooled = {"sim_arena": TR.auc(ally, allv), "action_only": TR.auc(ally, alla),
              "recall_sim_arena": float((allv[ally == 1] > tv).mean()), "recall_action_only": float((alla[ally == 1] > ta).mean()),
              "fpr_sim_arena": float((allv[ally == 0] > tv).mean())}
    print(f"pooled on 20 spent runs: sim AUC-PR {pooled['sim_arena']['auc_pr']:.3f} vs action {pooled['action_only']['auc_pr']:.3f}; "
          f"recall {pooled['recall_sim_arena']:.3f} vs {pooled['recall_action_only']:.3f}; sim FPR {pooled['fpr_sim_arena']:.3f} "
          f"({round(time.time() - t0)}s)", flush=True)
    rng = np.random.default_rng(0)
    power = {}
    for N in N_SET:
        passes = g2s = 0
        for _ in range(DRAWS):
            pick = rng.choice(rest, size=N, replace=True)
            y = np.concatenate([per_run[n]["y"] for n in pick])
            ep = np.concatenate([per_run[n]["ep"] + 1000 * j for j, n in enumerate(pick)])
            sv = np.concatenate([per_run[n]["sv"] for n in pick]); sa = np.concatenate([per_run[n]["sa"] for n in pick])
            g1, g2 = g1_g2(sv, sa, tv, ta, y, ep, rng)
            passes += g1 and g2
            g2s += g2
        power[N] = {"p_primary_pass": passes / DRAWS, "p_G2": g2s / DRAWS}
        print(f"  N={N:2d} usable sealed runs: P(primary pass) {passes / DRAWS:.2f}, P(G2) {g2s / DRAWS:.2f}", flush=True)
    doc = {"schema_version": "vision-caution-study-b-power-v1",
           "status": "EXPLORATORY power check on spent runs, before any study-B sealed run returned; optimistic (the same runs chose the recipe); not evidence",
           "thresholds": {"sim_arena": tv, "action_only": ta}, "pooled_on_spent": pooled, "sim_selection_auc_pr": sel_ap,
           "draws": DRAWS, "inner_bootstrap": INNER, "power_by_usable_sealed_runs": power}
    OUT.write_text(json.dumps(doc, indent=1, default=float) + "\n", encoding="utf-8")
    print("wrote", OUT)
    gate_variants()


if __name__ == "__main__":
    if "--gates-only" in sys.argv:
        gate_variants()
    else:
        main()
