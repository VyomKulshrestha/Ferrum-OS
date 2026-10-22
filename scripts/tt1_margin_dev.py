#!/usr/bin/env python3
"""tt1 development: choose the static safety-margin rule before registration.

The rehearsal on HAI 20.07 development data showed the half-rate margin (calibration quantile at
1 - p/2) sits only 1.7% above tau0 there and does not hold the budget on the pseudo-deployment. This
script compares margin families on the evidence development can use:
  spent HAI 21.03 / 22.04 / 23.05: monitor fitted exactly as in the tt1 final (fit 60 / scale 20 /
      calibration 20 % of all normal data), scored on the release's already-opened test streams
      (ledgered as an exploratory development access): false-alarm episodes/day on unlabelled time
      and event recall, per candidate threshold;
  HAI 20.07 development data: the rehearsal split (pseudo-deployment, normal only): false alarms.
Candidates: q<k> = max(tau0, calibration quantile at 1 - p/k); s<c> = tau0 + c x (q0.999 - median).
Writes target/real-telemetry/tt1-margin-dev/<release>.json; `merge` builds
docs/research/threshold_transfer_margin_dev_v1.json.
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
import real_telemetry_rt2 as RT2
import threshold_rules as T
import threshold_transfer_dev as X
import tt1_final as F

ROOT = Path(__file__).resolve().parents[1]
PART = ROOT / "target/real-telemetry/tt1-margin-dev"
OUT = ROOT / "docs/research/threshold_transfer_margin_dev_v1.json"
REASON = "EXPLORATORY tt1 development: static-margin and online-rule selection on already-opened attack data (not a registered final)"
QUANTILE_K = (1, 2, 4, 8, 16)
SPREAD_C = (0.1, 0.25, 0.5, 0.75, 1.0)


def candidates(pooled, tau0, p):
    m0, q999 = float(np.median(pooled)), float(np.quantile(pooled, 0.999))
    out = {f"q{k}": float(max(tau0, np.quantile(pooled, 1 - p / k))) for k in QUANTILE_K}
    out.update({f"s{c}": tau0 + c * (q999 - m0) for c in SPREAD_C})
    return out


def evaluate(scores, labels, thresholds):
    res = {}
    for name, tau in thresholds.items():
        found, fa, normal = [], 0, 0
        for s, y in zip(scores, labels):
            alarm = s > tau
            lab = np.zeros(len(s), bool)
            for a, b in C.events(y):
                lab[a:b] = True
                found.append(bool(alarm[a:b].any()))
            fa += sum(1 for a, b in T._episodes(alarm, X.GAP) if not lab[a:b].any())
            normal += int((~lab).sum())
        res[name] = {"tau": tau, "fa_per_day": fa / max(normal / X.STEPS_PER_DAY, 1e-9),
                     "recall": float(np.mean(found)) if found else None, "found": found}
    if res["q1"]["found"]:
        for name in res:
            res[name]["vs_frozen"] = C.paired_event_bootstrap(res["q1"]["found"], res[name]["found"], reps=10_000)
    for name in res:
        res[name].pop("found")
    return res


def run(release):
    t0 = time.time()
    if release == "hai-20.07":
        segs, _ = F.normal_data(release)
        kx, ku = F.varying_columns(segs)
        segs = [(x[:, kx], u[:, ku]) for x, u in segs]
        parts = F.split(segs, F.REHEARSAL_CUTS, ("fit", "scale", "calib", "deploy"), min_len=1000)
        streams = [(x, u, np.zeros(len(x), np.int8)) for x, u in parts["deploy"]]
        data = "rehearsal split of development data (pseudo-deployment, normal only)"
    else:
        segs = X.normal_segments(release)
        kx, ku = F.varying_columns(segs)
        segs = [(x[:, kx], u[:, ku]) for x, u in segs]
        parts = F.split(segs, F.FINAL_CUTS, ("fit", "scale", "calib"), min_len=1000)
        if release == "hai-22.04":
            test = [(s.X, s.U, s.y) for s in D.hai_test(REASON)["segments"]]
        else:
            test = RT2.test_segments(release, REASON)
        streams = [(x[:, kx], u[:, ku], y) for x, u, y in test]
        data = "final split of all normal data; already-opened test streams with labels"
    scorer, pack, _, _, _ = F.fit_monitor(parts["fit"], parts["scale"])
    cal = [s[np.isfinite(s)] for s in (X.d1(scorer, z, v) for z, v in pack(parts["calib"]))]
    tau0 = R.calibrate(cal, X.GAP, X.BUDGET, X.STEPS_PER_DAY)
    pooled = np.concatenate(cal)
    p = float(max((pooled > tau0).mean(), 1.0 / len(pooled)))
    thr = candidates(pooled, tau0, p)
    packed = pack([(x, u) for x, u, _ in streams])
    scores = [np.where(np.isfinite(s), s, -np.inf) for s in (X.d1(scorer, z, v) for z, v in packed)]
    cfg = F.thresholds(pooled, tau0, F.ETA_MULT, 0.999)
    out = {"release": release, "data": data, "tau0": tau0, "p": p, "calibration_seconds": int(len(pooled)),
           "deployment_days": sum(len(s) for s in scores) / X.STEPS_PER_DAY,
           "candidates": evaluate(scores, [y for _, _, y in streams], thr),
           "rules_on_streams": F.stream_rules(scorer, cfg, [(z, v, y) for (z, v), (_, _, y) in zip(packed, streams)]),
           "seconds": round(time.time() - t0)}
    PART.mkdir(parents=True, exist_ok=True)
    (PART / f"{release}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(release, "done", out["seconds"], "s", flush=True)


def merge():
    rel = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(PART.glob("*.json"))}
    OUT.write_text(json.dumps({"schema_version": "threshold-transfer-margin-dev-v1",
                               "status": "development evidence; spent attack data accessed as exploratory (ledgered)",
                               "releases": rel}, indent=1) + "\n", encoding="utf-8")
    names = list(next(iter(rel.values()))["candidates"])
    print(f"{'candidate':10s}" + "".join(f"{r:>34s}" for r in rel))
    for n in names:
        row = f"{n:10s}"
        for r, v in rel.items():
            m = v["candidates"][n]
            rec = f"rec {m['recall']:.2f} d{m['vs_frozen']['recall_difference_interval'][0]:+.2f}" if m.get("recall") is not None else ""
            row += f"{'fa ' + format(m['fa_per_day'], '.2f') + ' x' + format(m['tau'] / v['tau0'], '.2f') + ' ' + rec:>34s}"
        print(row)
    print("\nrules on the streams (recall [1st/2nd half], fa/day, onset inflation, CI low vs frozen)")
    for r in next(iter(rel.values()))["rules_on_streams"]["rules"]:
        row = f"{r:18s}"
        for v in rel.values():
            m = v["rules_on_streams"]["rules"][r]
            ci = v["rules_on_streams"]["paired"].get(f"{r}_vs_frozen", {}).get("recall_difference_interval", [None])[0]
            rec = f"{m['recall']:.2f}[{m['recall_first_half']:.2f}/{m['recall_second_half']:.2f}]" if m["recall"] is not None else "-"
            row += f"{rec + ' ' + format(m['fa_per_day'], '.2f') + ' x' + format(m['median_onset_inflation'] or 1, '.2f') + (' ' + format(ci, '+.2f') if ci is not None else ''):>40s}"
        print(row)


if __name__ == "__main__":
    run(sys.argv[2]) if sys.argv[1] == "run" else merge()
