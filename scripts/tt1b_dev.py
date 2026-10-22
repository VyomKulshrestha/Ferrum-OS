#!/usr/bin/env python3
"""tt1b development: do literature streaming thresholds and a model-free score show the same loss?

Spent HAI 21.03 / 22.04 / 23.05 only (their test files were opened by rt1/rt2; this access is ledgered
as exploratory). Per release: the D1 monitor fitted as in the tt1 final (fit 60 / scale 20 / calibration
20 % of normal data), two score families on the recorded test streams -- D1 (world-model residual) and
D0 (top-3 standardised first differences, no model) -- each smoothed over 60 s and calibrated to 2
false-alarm episodes per day, and every rule in threshold_rules_ext.RULES (tt1 rules + SPOT + DSPOT).
Per event it records detection, delay, threshold over tau0 at onset and the time since the previous
event ends, so recall can be split into events that follow another within 6 h and isolated ones.
Writes target/real-telemetry/tt1b-dev/<release>.json; `merge` builds docs/research/threshold_transfer_tt1b_dev_v1.json.
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
import threshold_rules_ext as E
import threshold_transfer_dev as X
import tt1_final as F

ROOT = Path(__file__).resolve().parents[1]
PART = ROOT / "target/real-telemetry/tt1b-dev"
OUT = ROOT / "docs/research/threshold_transfer_tt1b_dev_v1.json"
REASON = "EXPLORATORY tt1b development: literature thresholds (SPOT/DSPOT) and a model-free score on already-opened attack data"
SCORES = ("D1", "D0")
DEPTH = 3600            # DSPOT moving-average depth at 1 Hz
NEAR = 6 * 3600         # an event is "close" if it starts within 6 h of the previous event's end


def smoothed(scorer, z, v, key):
    s = R.smooth(scorer.raw(z, v)[0][key], X.WINDOW)
    s[:R.WARMUP] = np.nan
    return s


def evaluate(streams, cfg, calib):
    rows = {r: {"events": [], "fa": 0} for r in E.RULES}
    normal = 0
    for s, y in streams:
        s = np.where(np.isfinite(s), s, -np.inf)
        ev = C.events(y)
        lab = np.zeros(len(s), bool)
        for a, b in ev:
            lab[a:b] = True
        normal += int((~lab).sum())
        prev_end = [None] + [b for _, b in ev[:-1]]
        for r in E.RULES:
            tau, _ = E.apply_rule(r, s, cfg, calib, X.STEPS_PER_DAY, X.GAP, DEPTH, labels=y)
            alarm = s > tau
            for (a, b), pe in zip(ev, prev_end):
                hit = np.flatnonzero(alarm[a:b])
                rows[r]["events"].append({"found": bool(len(hit)), "delay": int(hit[0]) if len(hit) else None,
                                          "onset_inflation": float(tau[a] / cfg["tau0"]),
                                          "since_previous": None if pe is None else int(a - pe)})
            rows[r]["fa"] += sum(1 for a, b in T._episodes(alarm, X.GAP) if not lab[a:b].any())
    out = {}
    for r, v in rows.items():
        ev = v["events"]
        found = [e["found"] for e in ev]
        close = [e["found"] for e in ev if e["since_previous"] is not None and e["since_previous"] <= NEAR]
        far = [e["found"] for e in ev if e["since_previous"] is None or e["since_previous"] > NEAR]
        delays = [e["delay"] for e in ev if e["delay"] is not None]
        out[r] = {"recall": float(np.mean(found)), "events": len(found),
                  "fa_per_day": v["fa"] / max(normal / X.STEPS_PER_DAY, 1e-9),
                  "recall_close": float(np.mean(close)) if close else None, "n_close": len(close),
                  "recall_isolated": float(np.mean(far)) if far else None, "n_isolated": len(far),
                  "median_delay_s": float(np.median(delays)) if delays else None,
                  "median_onset_inflation": float(np.median([e["onset_inflation"] for e in ev])),
                  "per_event": ev}
    base = [e["found"] for e in rows["frozen"]["events"]]
    for r in out:
        if r != "frozen":
            out[r]["vs_frozen"] = C.paired_event_bootstrap(base, [e["found"] for e in rows[r]["events"]], reps=10_000)
    return out, normal / X.STEPS_PER_DAY


def run(release):
    t0 = time.time()
    segs = X.normal_segments(release)
    kx, ku = F.varying_columns(segs)
    segs = [(x[:, kx], u[:, ku]) for x, u in segs]
    parts = F.split(segs, F.FINAL_CUTS, ("fit", "scale", "calib"), min_len=1000)
    test = [(s.X, s.U, s.y) for s in D.hai_test(REASON)["segments"]] if release == "hai-22.04" \
        else RT2.test_segments(release, REASON)
    scorer, pack, _, _, _ = F.fit_monitor(parts["fit"], parts["scale"])
    packed = pack([(x[:, kx], u[:, ku]) for x, u, _ in test])
    labels = [y for _, _, y in test]
    out = {"release": release, "scores": {}}
    for key in SCORES:
        cal = [s[np.isfinite(s)] for s in (smoothed(scorer, z, v, key) for z, v in pack(parts["calib"]))]
        tau0 = R.calibrate(cal, X.GAP, X.BUDGET, X.STEPS_PER_DAY)
        pooled = np.concatenate(cal)
        cfg = F.thresholds(pooled, tau0, F.ETA_MULT, 0.999)
        streams = [(smoothed(scorer, z, v, key), y) for (z, v), y in zip(packed, labels)]
        rules, days = evaluate(streams, cfg, pooled)
        out["scores"][key] = {"thresholds": cfg, "normal_days": days, "rules": rules}
        print(release, key, "done", round(time.time() - t0), "s", flush=True)
    PART.mkdir(parents=True, exist_ok=True)
    (PART / f"{release}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


def merge():
    rel = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(PART.glob("*.json"))}
    slim = {r: {"scores": {k: {"thresholds": s["thresholds"], "normal_days": s["normal_days"],
                                "rules": {n: {a: b for a, b in m.items() if a != "per_event"} for n, m in s["rules"].items()}}
                           for k, s in v["scores"].items()}} for r, v in rel.items()}
    OUT.write_text(json.dumps({"schema_version": "threshold-transfer-tt1b-dev-v1",
                               "status": "development evidence on already-opened HAI attacks (exploratory, ledgered)",
                               "releases": slim}, indent=1) + "\n", encoding="utf-8")
    for key in SCORES:
        print(f"\n== score {key}: recall [close/isolated] fa/day infl delay  CI vs frozen")
        for r in E.RULES:
            row = f"{r:15s}"
            for name, v in rel.items():
                m = v["scores"][key]["rules"][r]
                ci = m.get("vs_frozen", {}).get("recall_difference_interval")
                cl = "-" if m["recall_close"] is None else f"{m['recall_close']:.2f}"
                iso = "-" if m["recall_isolated"] is None else f"{m['recall_isolated']:.2f}"
                cis = "" if ci is None else f" [{ci[0]:+.2f},{ci[1]:+.2f}]"
                row += f"  {m['recall']:.2f}[{cl}/{iso}] {m['fa_per_day']:.1f} x{m['median_onset_inflation']:.1f}{cis}"
            print(row)


if __name__ == "__main__":
    run(sys.argv[2]) if sys.argv[1] == "run" else merge()
