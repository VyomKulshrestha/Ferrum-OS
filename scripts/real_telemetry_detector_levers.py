#!/usr/bin/env python3
"""EXPLORATORY detector levers on real HAI data (already-opened => indicative).

The retrospective (docs/research/real_telemetry_detection_v2_retrospective.json)
showed the better-forecasting WorldModelV2 does NOT improve the D1 residual
detector: a stronger world model absorbs attacks too, shrinking the residual
spike. This probes detector-side levers that might recover detection WITHOUT
needing a better normal forecast:

  base_short_std  rt1/rt2 baseline: short (history-3) residual, std scale  [reference]
  v2_std          v2 residual, std scale                                   [from retrospective]
  v2_mad          v2 residual, robust MAD scale (cycle-2b transfer fix)
  short_mad       short residual, MAD scale
  disagree_mad    |R_v2 - R_short| (model-vs-model divergence), MAD scale
  union           alarm if base_short_std OR disagree_mad fires (each at its own budget)

Each detector is the registered D1 shape: mean(top-3 standardised |.|) at H1 +
at H5, smoothed with the frozen window, calibrated to the budget on held-out
normal, evaluated on the recorded attacks. Paired event bootstrap vs the
baseline. NOT a registered final; indicative only.

Usage: python scripts/real_telemetry_detector_levers.py [release ...]
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
import real_telemetry_dev as dev
import real_telemetry_wm_v2 as V2
import real_telemetry_wm_v2_retrospective as RETRO

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/research/real_telemetry_detector_levers.json"
MAX_ROWS = RETRO.MAX_ROWS
BASELINE_GBR = RETRO.BASELINE_GBR
WARMUP = R.WARMUP
HOR = (1, 5)


def topk(A, k=3):
    return -np.sort(-A, 1)[:, :k].mean(1)


def resid(model, Z, V, h):
    """Signed residual array (T,d): obs - forecast at each index, 0 outside valid."""
    return C.residuals(model, Z, V, h)


def scale_of(stack, kind):
    if kind == "std":
        return stack.std(0) + 1e-3
    med = np.median(stack, 0)
    return 1.4826 * np.median(np.abs(stack - med), 0) + 1e-3


def fit_scales(residual_lists, kind):
    """Per-variable scale for H1 and H5 from a list of (R1,R5) normal arrays."""
    r1 = np.concatenate([a[WARMUP:] for a, _ in residual_lists])
    r5 = np.concatenate([b[WARMUP:] for _, b in residual_lists])
    return scale_of(r1, kind), scale_of(r5, kind)


def score(R1, R5, s1, s5, window):
    S1, S5 = np.abs(R1) / s1, np.abs(R5) / s5
    S1[:WARMUP] = 0.0
    S5[:WARMUP] = 0.0
    return R.smooth(topk(S1) + topk(S5), window)


def precompute(model, pairs):
    """[(R1,R5)] residual arrays per segment for a fitted model."""
    return [(resid(model, Z, V, 1), resid(model, Z, V, 5)) for Z, V in pairs]


def calibrate(resid_lists, scales, window, budget, spd):
    s1, s5 = scales
    clean = [score(R1, R5, s1, s5, window)[WARMUP:] for R1, R5 in resid_lists]
    return R.calibrate(clean, R.GAP["hai"], budget, spd)


def eval_detector(attack_resid, attack_y, scales, window, thr, spd):
    s1, s5 = scales
    found, delays, false_eps, normal_steps = [], [], 0, 0
    alarms = []
    for (R1, R5), y in zip(attack_resid, attack_y):
        s = score(R1, R5, s1, s5, window)
        s[:WARMUP] = -np.inf
        alarm = s > thr
        alarms.append(alarm)
        labelled = np.zeros(len(y), bool)
        for a, b in C.events(y):
            labelled[a:b] = True
            hit = np.flatnonzero(alarm[a:b])
            found.append(bool(len(hit)))
            if len(hit):
                delays.append(int(hit[0]))
        false_eps += sum(1 for e in R.episodes(alarm, R.GAP["hai"]) if not labelled[e[0]:e[1]].any())
        normal_steps += int((~labelled).sum())
    days = max(normal_steps / spd, 1e-9)
    return {"events": len(found), "detected": int(sum(found)),
            "recall": float(np.mean(found)) if found else float("nan"),
            "false_episodes_per_day": false_eps / days,
            "median_delay": float(np.median(delays)) if delays else None,
            "found": found, "alarms": alarms}


def union_eval(ev_a, ev_b, attack_y, spd):
    """Alarm if either detector fires (each already at its own budget)."""
    found, delays, false_eps, normal_steps = [], [], 0, 0
    for aa, ab, y in zip(ev_a["alarms"], ev_b["alarms"], attack_y):
        alarm = aa | ab
        labelled = np.zeros(len(y), bool)
        for a, b in C.events(y):
            labelled[a:b] = True
            hit = np.flatnonzero(alarm[a:b])
            found.append(bool(len(hit)))
            if len(hit):
                delays.append(int(hit[0]))
        false_eps += sum(1 for e in R.episodes(alarm, R.GAP["hai"]) if not labelled[e[0]:e[1]].any())
        normal_steps += int((~labelled).sum())
    days = max(normal_steps / spd, 1e-9)
    return {"events": len(found), "detected": int(sum(found)),
            "recall": float(np.mean(found)) if found else float("nan"),
            "false_episodes_per_day": false_eps / days,
            "median_delay": float(np.median(delays)) if delays else None, "found": found}


def run_release(release):
    t0 = time.time()
    segs = RETRO.normal_segments(release)
    parts = RETRO.split(segs)
    xs = C.Scaler().fit(np.concatenate([x for x, _ in parts["fit"]]))
    us = C.Scaler().fit(np.concatenate([u for _, u in parts["fit"]]))
    pack = lambda g: [(xs(x), us(u)) for x, u in g]
    fit, scale, cal = pack(parts["fit"]), pack(parts["scale"]), pack(parts["cal"])
    window = RETRO.frozen_window(release)
    budget, spd = R.BUDGET_PER_DAY["hai"], R.STEPS_PER_DAY["hai"]
    attack_raw = RETRO.attack_segments(release)
    attack = [(xs(x), us(u)) for x, u, _ in attack_raw]
    attack_y = [y for _, _, y in attack_raw]

    v2 = V2.build(use_actions=True).fit(fit, max_rows=MAX_ROWS)
    short = C.Forecaster(dev.HORIZONS, dev.HISTORY, use_actions=True, gbr=BASELINE_GBR).fit(fit, max_rows=MAX_ROWS)
    print(f"  fitted v2+short ({round(time.time()-t0)}s)", flush=True)

    # residual arrays on scale (for scales), cal (for thresholds), attack (for eval)
    def packs(model):
        return {"scale": precompute(model, scale), "cal": precompute(model, cal), "attack": precompute(model, attack)}
    rv2, rsh = packs(v2), packs(short)
    # disagreement residual arrays = R_v2 - R_short, per split
    def diff(split):
        return [(a1 - b1, a5 - b5) for (a1, a5), (b1, b5) in zip(rv2[split], rsh[split])]
    rdi = {s: diff(s) for s in ("scale", "cal", "attack")}

    detectors = {
        "base_short_std": (rsh, "std"),
        "v2_std": (rv2, "std"),
        "v2_mad": (rv2, "mad"),
        "short_mad": (rsh, "mad"),
        "disagree_mad": (rdi, "mad"),
    }
    res, evs = {}, {}
    for name, (rp, kind) in detectors.items():
        scales = fit_scales(rp["scale"], kind)
        thr = calibrate(rp["cal"], scales, window, budget, spd)
        ev = eval_detector(rp["attack"], attack_y, scales, window, thr, spd)
        evs[name] = ev
        res[name] = {k: ev[k] for k in ("events", "detected", "recall", "false_episodes_per_day", "median_delay")}
        print(f"  {name:16s} recall {ev['recall']:.3f} ({ev['detected']}/{ev['events']})  FA/day {ev['false_episodes_per_day']:.2f}", flush=True)
    # union of baseline-short and disagreement
    u = union_eval(evs["base_short_std"], evs["disagree_mad"], attack_y, spd)
    evs["union"] = u
    res["union"] = {k: u[k] for k in ("events", "detected", "recall", "false_episodes_per_day", "median_delay")}
    print(f"  {'union':16s} recall {u['recall']:.3f} ({u['detected']}/{u['events']})  FA/day {u['false_episodes_per_day']:.2f}", flush=True)

    base = evs["base_short_std"]["found"]
    boots = {name: C.paired_event_bootstrap(base, evs[name]["found"], reps=10_000, level=0.95)
             for name in res if name != "base_short_std"}
    for name, b in boots.items():
        res[name]["recall_diff_vs_base"] = b["recall_difference"]
        res[name]["recall_diff_ci95"] = b["recall_difference_interval"]
    print(f"  => vs base_short_std: " + "  ".join(
        f"{n} {res[n]['recall_diff_vs_base']:+.3f}{res[n]['recall_diff_ci95']}" for n in boots), flush=True)
    return {"window": window, "budget_per_day": budget, "detectors": res, "seconds": round(time.time() - t0)}


def main():
    releases = sys.argv[1:] or ["hai-23.05", "hai-22.04"]
    results = {}
    for rel in releases:
        print(f"== {rel} ==", flush=True)
        results[rel] = run_release(rel)
    doc = {"schema_version": "real-telemetry-detector-levers",
           "status": "EXPLORATORY-retrospective-on-already-opened-data",
           "disclaimer": "NOT a registered final; indicative only. Detector-side levers probed because a "
                         "better normal forecaster did not improve detection (see real_telemetry_detection_v2_retrospective.json).",
           "max_fit_rows": MAX_ROWS, "releases": results}
    prev = json.loads(OUT.read_text(encoding="utf-8")).get("releases", {}) if OUT.exists() else {}
    prev.update(results)
    doc["releases"] = prev
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
