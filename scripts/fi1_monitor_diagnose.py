#!/usr/bin/env python3
"""fi1 workstream A: why the registered D1 monitor sits in alarm outside labelled events (EXPLORATORY).

Runs on the selection set (HAI 21.03, HAI 22.04, Tennessee Eastman modes 0-3) and on attack-free data (the
calibration, residual-scale and sealed streams) from the residual cache of fi1_monitor_extract.py. Each
candidate cause is quantified:

  channels     which sensors make up the top-3 of the H1 / H5 standardised residuals at unlabelled alarm steps;
               share of unlabelled alarm steps that involve the five most frequent ones; alarm share after
               dropping them (recalibrated on attack-free data)
  scales       residual scale of every channel on each attack-free recording and on the unlabelled test time,
               over the scale fitted on the residual-scale split (ratio quantiles across channels)
  regime       share of unlabelled alarm steps (and of quiet unlabelled steps) with a sensor or an action
               outside its range in the world-model fit data
  combination  alarm share and onset recall of max / top-3 / mean of the standardised residuals
  smoothing    the same for half, double and four times the registered window
  calibration  leave-one-recording-out on attack-free recordings: threshold calibrated on one recording,
               false-alarm ratio to the budget on each other recording

    python scripts/fi1_monitor_diagnose.py [unit ...]       writes target/real-telemetry/fi1/monitor/diagnosis.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fi1_monitor_benchmark as B
import fi1_monitor_v3 as V
import real_telemetry_detect_v2 as R2
import threshold_rules as T

OUT = B.WORK / "diagnosis.json"
SEL_UNITS = ["hai-21.03", "hai-22.04", "tep-m0", "tep-m1", "tep-m2", "tep-m3"]


def std_res(unit, a):
    S1 = np.abs(np.asarray(a["R1"])) / unit.sig1
    S5 = np.abs(np.asarray(a["R5"])) / unit.sig5
    S1[:B.WARMUP] = 0
    S5[:B.WARMUP] = 0
    return S1, S5


class Agg:
    """D1-shaped score with a choice of channel subset, combination and window (diagnostic monitor)."""

    def __init__(self, how="top3", drop=(), window=None):
        self.how, self.drop, self.window = how, set(drop), window

    def fit(self, unit):
        return self

    def raw(self, unit, a):
        S1, S5 = std_res(unit, a)
        keep = [j for j in range(S1.shape[1]) if j not in self.drop]
        S1, S5 = S1[:, keep], S5[:, keep]
        f = {"top3": lambda A: V.topk_mean(A, 3), "max": lambda A: A.max(1), "mean": lambda A: A.mean(1)}[self.how]
        return f(S1) + f(S5)


def run_monitor(unit, mon, window=None):
    """Threshold, and per test stream (score, lab, valid, events)."""
    spec = dict(unit.spec)
    if window:
        unit.spec = dict(spec, window=window)
    try:
        tau, _ = B.calibrate_unit(unit, mon)
        streams = []
        for st in unit.streams("test"):
            lab, valid, events = B.labels_and_events(unit, st)
            streams.append((st, B.stream_score(unit, st, mon, valid), lab, valid, events))
    finally:
        unit.spec = spec
    return tau, streams


def share_and_onset(unit, tau, streams):
    al = un = on = n = 0
    for _, s, lab, valid, events in streams:
        alarm = s > tau
        unl = ~lab & valid
        al += int((alarm & unl).sum())
        un += int(unl.sum())
        starts = np.zeros(len(s), bool)
        for a, _ in T._episodes(alarm, unit.spec["gap"]):
            starts[a] = True
        on += sum(bool(starts[a:b].any()) for a, b, *_ in events)
        n += len(events)
    return {"unlabelled_alarm_share": al / max(un, 1), "onset_recall": on / max(n, 1), "events": n}


def channels(unit, tau, streams):
    d = len(unit.sig1)
    cnt1, cnt5 = np.zeros(d), np.zeros(d)
    alarm_steps = 0
    masks = []
    for st, s, lab, valid, _ in streams:
        idx = np.flatnonzero((s > tau) & ~lab & valid)
        if not len(idx):
            masks.append(None)
            continue
        S1, S5 = std_res(unit, st.arrays())
        t1 = np.argsort(-S1[idx], 1)[:, :3]
        t5 = np.argsort(-S5[idx], 1)[:, :3]
        cnt1 += np.bincount(t1.ravel(), minlength=d)
        cnt5 += np.bincount(t5.ravel(), minlength=d)
        alarm_steps += len(idx)
        masks.append((idx, t1, t5))
    total = cnt1 + cnt5
    top5 = [int(j) for j in np.argsort(-total)[:5]]
    involved = 0
    for m in masks:
        if m is None:
            continue
        _, t1, t5 = m
        involved += int((np.isin(t1, top5).any(1) | np.isin(t5, top5).any(1)).sum())
    return {"unlabelled_alarm_steps": alarm_steps, "top5_channels": top5,
            "top5_share_of_top3_slots": float(total[top5].sum() / max(total.sum(), 1)),
            "share_of_alarm_steps_involving_top5": involved / max(alarm_steps, 1),
            "channel_slot_counts_top10": {int(j): int(total[j]) for j in np.argsort(-total)[:10]}}


def ratio_stats(r):
    r = np.asarray(r, float)
    return {"median": float(np.median(r)), "q90": float(np.quantile(r, 0.9)), "max": float(r.max()),
            "argmax": int(r.argmax()), "channels_over_2": int((r > 2).sum()), "channels": int(len(r))}


def scales(unit):
    out = {"recordings": []}
    for group in ("scale", "calib", "sealed"):
        for st in unit.streams(group):
            r1 = np.asarray(st.load("R1"))[B.WARMUP:]
            out["recordings"].append({"group": group, "key": st.key, "steps": int(len(r1)),
                                      "std_ratio_h1": ratio_stats(r1.std(0) / unit.sig1)})
    rows, cnt = [], 0
    acc = np.zeros(len(unit.sig1))
    acc2 = np.zeros(len(unit.sig1))
    for st in unit.streams("test"):
        lab, valid, _ = B.labels_and_events(unit, st)
        r1 = np.asarray(st.load("R1"))[B.WARMUP:]
        m = (~lab & valid)[B.WARMUP:]
        acc += (r1[m].astype(np.float64) ** 2).sum(0)
        acc2 += r1[m].sum(0)
        cnt += int(m.sum())
    if cnt:
        var = acc / cnt - (acc2 / cnt) ** 2
        out["test_unlabelled_std_ratio_h1"] = ratio_stats(np.sqrt(np.maximum(var, 0)) / unit.sig1)
        out["test_unlabelled_mean_over_sig_h1"] = ratio_stats(np.abs(acc2 / cnt) / unit.sig1)
    return out


def regime(unit, tau, streams):
    if unit.name.startswith("tep-"):
        return None                                  # sensors not cached for Tennessee Eastman
    out = {"alarm": [0, 0], "quiet": [0, 0]}
    span = np.maximum(unit.fit_high - unit.fit_low, 1e-6)
    for st, s, lab, valid, _ in streams:
        Z = np.asarray(st.load("Z"))
        # only sensors are kept for the range test; actions are scaled separately and their range was not cached
        outside = ((Z < unit.fit_low - 0.05 * span) | (Z > unit.fit_high + 0.05 * span)).any(1)
        unl = ~lab & valid
        alarm = s > tau
        for k, m in (("alarm", alarm & unl), ("quiet", ~alarm & unl)):
            out[k][0] += int((outside & m).sum())
            out[k][1] += int(m.sum())
    return {k: v[0] / max(v[1], 1) for k, v in out.items()} | {"alarm_steps": out["alarm"][1]}


def loro(unit):
    """Each attack-free recording calibrates alone; false-alarm ratio on every other recording."""
    mon = V.D1().fit(unit)
    recs = []
    for group in ("scale", "calib", "sealed"):
        for st in unit.streams(group):
            _, valid, _ = B.labels_and_events(unit, st)
            s = B.stream_score(unit, st, mon, valid)
            recs.append((f"{group}:{st.key}", s))
    sp = unit.spec
    rows = []
    for i, (name, s) in enumerate(recs):
        tau = R2.calibrate([s[np.isfinite(s)]], sp["gap"], sp["budget"], sp["spd"])
        others = []
        for j, (n2, s2) in enumerate(recs):
            if i == j:
                continue
            days = np.isfinite(s2).sum() / sp["spd"]
            others.append(len(T._episodes(s2 > tau, sp["gap"])) / max(days, 1e-9) / sp["budget"])
        rows.append({"recording": name, "days": float(np.isfinite(s).sum() / sp["spd"]), "tau": float(tau),
                     "fa_ratio_on_others_median": float(np.median(others)) if others else None,
                     "fa_ratio_on_others_max": float(np.max(others)) if others else None})
    taus = [r["tau"] for r in rows]
    return {"recordings": rows, "tau_max_over_min": float(max(taus) / min(taus)) if taus else None}


def diagnose(name):
    unit = B.Unit(name)
    print(name, "...", flush=True)
    base = V.D1()
    tau, streams = run_monitor(unit, base)
    out = {"tau": tau, "baseline": share_and_onset(unit, tau, streams)}
    out["channels"] = ch = channels(unit, tau, streams)
    tau_d, st_d = run_monitor(unit, Agg(drop=ch["top5_channels"]))
    out["drop_top5"] = share_and_onset(unit, tau_d, st_d) | {"tau": tau_d}
    del st_d
    out["regime"] = regime(unit, tau, streams)
    del streams
    out["scales"] = scales(unit)
    out["combination"] = {}
    for how in ("max", "mean"):
        t, s = run_monitor(unit, Agg(how=how))
        out["combination"][how] = share_and_onset(unit, t, s)
    out["smoothing"] = {}
    w = unit.spec["window"]
    for mult in (0.5, 2, 4):
        ww = max(1, int(round(w * mult)))
        t, s = run_monitor(unit, Agg(), window=ww)
        out["smoothing"][str(ww)] = share_and_onset(unit, t, s)
    out["calibration_loro"] = loro(unit)
    print(json.dumps({k: out[k] for k in ("baseline", "drop_top5")}), flush=True)
    return out


def main():
    names = sys.argv[1:] or SEL_UNITS
    res = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    for n in names:
        res[n] = diagnose(n)
        OUT.write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
