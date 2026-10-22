#!/usr/bin/env python3
"""Post-hoc (after the registered tt1 finals): literature thresholds and a model-free score on the
three tt1 datasets. Exploratory; each access is ledgered as post-hoc.

Stream datasets (hai-20.07, hygrid-ics): the tt1 final pipeline (fit 60 / scale 20 / calibration 20 %),
scores D1 and D0 smoothed over 60 s, every rule in threshold_rules_ext.RULES, per-event detection,
delay, onset inflation and time since the previous event (tt1b_dev.evaluate).
voraus-ad: per-sample max of D1 and D0 smoothed over 10 steps, rules over the sample sequence (review
50 samples, DSPOT depth 50), TPR/FPR and paired bootstrap against frozen.
Writes target/real-telemetry/tt1b-posthoc/<dataset>.json; `merge` builds docs/research/threshold_transfer_tt1b_posthoc_v1.json.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_telemetry_core as C
import real_telemetry_detect as R
import threshold_rules_ext as E
import threshold_transfer_dev as X
import tt1_data as TD
import tt1_final as F
import tt1b_dev as B

ROOT = Path(__file__).resolve().parents[1]
PART = ROOT / "target/real-telemetry/tt1b-posthoc"
OUT = ROOT / "docs/research/threshold_transfer_tt1b_posthoc_v1.json"
REASON = "post-hoc analysis after the registered tt1 final: SPOT/DSPOT and the D0 score (exploratory)"


def stream(dataset):
    t0 = time.time()
    segs, cols = F.normal_data(dataset)
    kx, ku = F.varying_columns(segs)
    segs = [(x[:, kx], u[:, ku]) for x, u in segs]
    parts = F.split(segs, F.FINAL_CUTS, ("fit", "scale", "calib"), min_len=1000)
    scorer, pack, _, _, _ = F.fit_monitor(parts["fit"], parts["scale"])
    raw = (TD.hai2007_test if dataset == "hai-20.07" else TD.hygrid_test)(REASON)[0]
    packed = pack([(x[:, kx], u[:, ku]) for x, u, _ in raw])
    out = {"dataset": dataset, "scores": {}}
    for key in B.SCORES:
        cal = [s[np.isfinite(s)] for s in (B.smoothed(scorer, z, v, key) for z, v in pack(parts["calib"]))]
        tau0 = R.calibrate(cal, X.GAP, X.BUDGET, X.STEPS_PER_DAY)
        pooled = np.concatenate(cal)
        cfg = F.thresholds(pooled, tau0, F.ETA_MULT, 0.999)
        rules, days = B.evaluate([(B.smoothed(scorer, z, v, key), y) for (z, v), (_, _, y) in zip(packed, raw)], cfg, pooled)
        out["scores"][key] = {"thresholds": cfg, "normal_days": days, "rules": rules}
        print(dataset, key, "done", round(time.time() - t0), "s", flush=True)
    return out


def episodic(dataset):
    spec = F.EPISODIC[dataset]
    samples, cols = F.normal_data(dataset)
    kx, ku = F.varying_columns(samples)
    samples = [(x[:, kx], u[:, ku]) for x, u in samples]
    n = len(samples)
    c = [int(n * q) for q in F.FINAL_CUTS]
    scorer, pack, _, _, _ = F.fit_monitor(samples[:c[0]], samples[c[0]:c[1]])
    raw = TD.voraus_test(REASON)[0]
    test = pack([(x[:, kx], u[:, ku]) for x, u, _ in raw])
    flags = np.array([f for _, _, f in raw], np.int8)
    anom = flags.astype(bool)
    out = {"dataset": dataset, "scores": {}}
    for key in B.SCORES:
        def smax(z, v):
            s = R.smooth(scorer.raw(z, v)[0][key], spec["window"])
            s[:R.WARMUP] = np.nan
            return float(np.nanmax(s))
        cal = np.array([smax(z, v) for z, v in pack(samples[c[1]:])])
        cfg = F.thresholds(cal, float(np.quantile(cal, 1 - spec["alpha"])), spec["eta_mult"], 0.99)
        seq = np.array([smax(z, v) for z, v in test])
        rules, found = {}, {}
        for r in E.RULES:
            tau, _ = E.apply_rule(r, seq, cfg, cal, spec["review"], 0, spec["review"], labels=flags)
            alarm = seq > tau
            found[r] = alarm[anom].tolist()
            rules[r] = {"tpr": float(alarm[anom].mean()), "fpr": float(alarm[~anom].mean()),
                        "median_inflation_at_anomalies": float(np.median(tau[anom] / cfg["tau0"]))}
        for r in rules:
            if r != "frozen":
                rules[r]["vs_frozen"] = C.paired_event_bootstrap(found["frozen"], found[r], reps=10_000)
        out["scores"][key] = {"thresholds": cfg, "rules": rules}
        print(dataset, key, "done", flush=True)
    return out


def run(dataset):
    out = episodic(dataset) if dataset in F.EPISODIC else stream(dataset)
    PART.mkdir(parents=True, exist_ok=True)
    (PART / f"{dataset}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


def merge():
    rel = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(PART.glob("*.json"))}
    slim = {d: {"scores": {k: {a: (b if a != "rules" else {r: {x: y for x, y in m.items() if x != "per_event"}
                                                          for r, m in b.items()}) for a, b in s.items()}
                           for k, s in v["scores"].items()}} for d, v in rel.items()}
    OUT.write_text(json.dumps({"schema_version": "threshold-transfer-tt1b-posthoc-v1",
                               "status": "post-hoc on the tt1 datasets after their registered finals (exploratory)",
                               "datasets": slim}, indent=1) + "\n", encoding="utf-8")
    for d, v in rel.items():
        for key, s in v["scores"].items():
            print(f"\n== {d} {key}")
            for r, m in s["rules"].items():
                ci = m.get("vs_frozen", {}).get("recall_difference_interval")
                cis = "" if ci is None else f" [{ci[0]:+.2f},{ci[1]:+.2f}]"
                if "recall" in m:
                    cl = "-" if m["recall_close"] is None else f"{m['recall_close']:.2f}"
                    iso = "-" if m["recall_isolated"] is None else f"{m['recall_isolated']:.2f}"
                    print(f"   {r:15s} recall {m['recall']:.3f} [close {cl} n{m['n_close']} / isolated {iso} n{m['n_isolated']}] "
                          f"fa/day {m['fa_per_day']:.2f} infl {m['median_onset_inflation']:.2f}{cis}")
                else:
                    print(f"   {r:15s} tpr {m['tpr']:.3f} fpr {m['fpr']:.3f} infl {m['median_inflation_at_anomalies']:.2f}{cis}")


if __name__ == "__main__":
    run(sys.argv[2]) if sys.argv[1] == "run" else merge()
