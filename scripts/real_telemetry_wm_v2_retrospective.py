#!/usr/bin/env python3
"""EXPLORATORY / RETROSPECTIVE look at WorldModelV2 on real HAI data.

This is NOT the registered final (docs/research/real_telemetry_detection_protocol_v2.json),
which waits for a never-opened dataset. The HAI 22.04/21.03/23.05 attacks were
already opened in rt1/rt2 (target/real-telemetry/final_access.jsonl), so the
detection numbers here are INDICATIVE, carry selection optimism, and are reported
in the same spirit as docs/research/real_telemetry_posthoc_rt1.json -- a post-hoc
comparison, not a clean prospective claim.

Per release it refits BOTH forecasters on identical chronological splits (so the
only difference is the world model) and reports:
  (1) normal-period forecast MAE (H1,H5) on test windows touching no labelled step
      -- the clean "is the forecaster better" answer, no attack data in the metric;
  (2) D1 event recall + false-alarm episodes/day on the recorded attacks, with a
      paired event bootstrap of candidate vs baseline -- the indicative detection answer.

Usage: python scripts/real_telemetry_wm_v2_retrospective.py [release ...]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_telemetry_core as C
import real_telemetry_data as D
import real_telemetry_detect as R
import real_telemetry_dev as dev
import real_telemetry_rt2 as RT2
import real_telemetry_wm_v2 as V2

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/research/real_telemetry_detection_v2_retrospective.json"
MAX_ROWS = int(__import__("os").environ.get("MAX_ROWS", "15000"))
BASELINE_GBR = dict(n_estimators=60, num_leaves=31, learning_rate=0.1,
                    min_child_samples=100, subsample=0.8, subsample_freq=1)
CUTS = (0.5, 0.8)   # fit / residual-scale / calibration
REASON = "EXPLORATORY retrospective (v2 vs baseline D1) on already-opened data; not a registered final"


def normal_segments(release):
    if release == "hai-22.04":
        return [(s.X, s.U) for s in D.hai_train()["segments"]]
    return [(x, u) for x, u in RT2.train_segments(release)[0]]


def attack_segments(release):
    if release == "hai-22.04":
        return [(s.X, s.U, s.y) for s in D.hai_test(REASON)["segments"]]
    return RT2.test_segments(release, REASON)


def frozen_window(release):
    path = (ROOT / "target/real-telemetry/frozen/hai-bundle.pkl" if release == "hai-22.04"
            else ROOT / f"target/real-telemetry/rt2/{release}-bundle.pkl")
    try:
        return R.load_bundle_bytes(path.read_bytes())["choice"]["D1"]["window"]
    except Exception:
        return 10


def split(segs):
    total = sum(len(x) for x, _ in segs)
    b = [int(total * c) for c in CUTS]
    parts, off = {"fit": [], "scale": [], "cal": []}, 0
    for x, u in segs:
        a, z = off, off + len(x)
        for name, lo, hi in (("fit", 0, b[0]), ("scale", b[0], b[1]), ("cal", b[1], total)):
            s, e = max(a, lo), min(z, hi)
            if e - s > 2000:
                parts[name].append((x[s - a:e - a], u[s - a:e - a]))
        off = z
    return parts


def d1_clean(scorer, pairs, window):
    out = []
    for Z, Vv in pairs:
        base, _ = scorer.raw(Z, Vv)
        s = R.smooth(base["D1"], window)
        out.append(s[R.WARMUP:])
    return out


def evaluate(scorer, attack, window, thr, steps_per_day):
    found, delays = [], []
    false_eps, normal_steps = 0, 0
    wm_err = {h: [0.0, 0.0, 0] for h in (1, 5)}   # model_sum, persist_sum, count
    for Z, Vv, y in attack:
        base, _ = scorer.raw(Z, Vv)
        s = R.smooth(base["D1"], window)
        s[:R.WARMUP] = -np.inf
        alarm = s > thr
        runs = C.events(y)
        labelled = np.zeros(len(y), bool)
        for a, b in runs:
            labelled[a:b] = True
            hit = np.flatnonzero(alarm[a:b])
            found.append(bool(len(hit)))
            if len(hit):
                delays.append(int(hit[0]))
        false_eps += sum(1 for e in R.episodes(alarm, R.GAP["hai"]) if not labelled[e[0]:e[1]].any())
        normal_steps += int((~labelled).sum())
        wm = scorer.wm
        for h in (1, 5):
            t = C.valid_index(len(Z), wm.history, h)
            clean = np.array([not y[max(0, i - wm.history):i + h + 1].any() for i in t])
            t = t[clean]
            if len(t):
                em = np.abs(wm.predict(Z, Vv, t, h) - Z[t + h]).sum()
                ep = np.abs(Z[t] - Z[t + h]).sum()
                wm_err[h][0] += float(em); wm_err[h][1] += float(ep); wm_err[h][2] += t.size
    recall = float(np.mean(found)) if found else float("nan")
    days = max(normal_steps / steps_per_day, 1e-9)
    mae = {f"H{h}": {"model_mae": v[0] / max(v[2], 1), "persistence_mae": v[1] / max(v[2], 1),
                     "reduction_vs_persistence": 1 - v[0] / max(v[1], 1e-12)} for h, v in wm_err.items()}
    return {"events": len(found), "detected": int(sum(found)), "recall": recall,
            "false_episodes": false_eps, "false_episodes_per_day": false_eps / days,
            "median_delay_steps": float(np.median(delays)) if delays else None,
            "normal_period_forecast_mae": mae, "found": found}


def run_release(release):
    t0 = time.time()
    segs = normal_segments(release)
    parts = split(segs)
    xs = C.Scaler().fit(np.concatenate([x for x, _ in parts["fit"]]))
    us = C.Scaler().fit(np.concatenate([u for _, u in parts["fit"]]))
    pack = lambda g: [(xs(x), us(u)) for x, u in g]
    fit, scale, cal = pack(parts["fit"]), pack(parts["scale"]), pack(parts["cal"])
    window = frozen_window(release)
    budget = R.BUDGET_PER_DAY["hai"]
    spd = R.STEPS_PER_DAY["hai"]

    attack = [(xs(x), us(u), y) for x, u, y in attack_segments(release)]

    models = {"candidate_v2": V2.build(use_actions=True),
              "baseline_rt1": C.Forecaster(dev.HORIZONS, dev.HISTORY, use_actions=True, gbr=BASELINE_GBR)}
    res, found = {}, {}
    for name, wm in models.items():
        sc = R.Scorer(wm.fit(fit, max_rows=MAX_ROWS), fit)
        sc.residual_scales(scale)
        thr = R.calibrate(d1_clean(sc, cal, window), R.GAP["hai"], budget, spd)
        ev = evaluate(sc, attack, window, thr, spd)
        found[name] = ev.pop("found")
        res[name] = ev
        m = ev["normal_period_forecast_mae"]
        print(f"  {name:13s} recall {ev['recall']:.3f} ({ev['detected']}/{ev['events']})  "
              f"FA/day {ev['false_episodes_per_day']:.2f}  "
              f"normalMAE H1 {m['H1']['model_mae']:.4f} H5 {m['H5']['model_mae']:.4f}", flush=True)
    boot = C.paired_event_bootstrap(found["baseline_rt1"], found["candidate_v2"], reps=10_000, level=0.95)
    h5c = res["candidate_v2"]["normal_period_forecast_mae"]["H5"]["model_mae"]
    h5b = res["baseline_rt1"]["normal_period_forecast_mae"]["H5"]["model_mae"]
    print(f"  => recall diff (v2 - baseline) {boot['recall_difference']:+.3f} "
          f"CI95 [{boot['recall_difference_interval'][0]:+.3f},{boot['recall_difference_interval'][1]:+.3f}]  "
          f"| normal H5 MAE {h5b:.4f} -> {h5c:.4f} ({100*(h5b-h5c)/h5b:+.1f}%)  ({round(time.time()-t0)}s)", flush=True)
    return {"window": window, "budget_per_day": budget, "arms": res,
            "paired_bootstrap_candidate_vs_baseline": boot,
            "normal_H5_mae_pct_improvement": 100 * (h5b - h5c) / h5b if h5b else None}


def main():
    releases = sys.argv[1:] or ["hai-22.04", "hai-21.03", "hai-23.05"]
    results = {}
    for rel in releases:
        print(f"== {rel} ==", flush=True)
        results[rel] = run_release(rel)
    doc = {"schema_version": "real-telemetry-detection-v2-retrospective",
           "status": "EXPLORATORY-retrospective-on-already-opened-data",
           "disclaimer": "NOT the registered final. HAI attacks were opened in rt1/rt2; these numbers are "
                         "indicative and optimistic. The clean prospective claim awaits a never-opened dataset "
                         "(docs/research/real_telemetry_detection_protocol_v2.json).",
           "max_fit_rows": MAX_ROWS, "releases": results}
    prev = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"releases": {}}
    prev_rel = prev.get("releases", {}) if isinstance(prev, dict) else {}
    prev_rel.update(results)
    doc["releases"] = prev_rel
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
