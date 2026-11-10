#!/usr/bin/env python3
"""tt1f parts D and J, with the trace-based parts of F and I (exploratory, post-hoc): the stronger rules on
BATADAL, and chance references and peak scores for BATADAL and HAI 20.07, from the stored traces.

Plan: docs/research/threshold_transfer_tt1f_dev_plan.md with amendment 1 (committed before the runs they
cover). docs/research/paper/tt1_paper_pack/figure_data/threshold_trajectories.csv holds the D1 score, the
attack labels and the registered threshold paths of the BATADAL test files (15-minute steps) and of the
HAI 20.07 test files (one row a minute: the minute's largest score), written after the registered finals,
so neither dataset is opened again. BATADAL durations are scaled as tt1b scaled them (60 s on HAI is 1 h).

    python scripts/tt1f_batadal_trace.py      writes docs/research/threshold_transfer_tt1f_batadal_v1.json
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import threshold_rules as T
import threshold_rules_tt1d as RD

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "docs/research/paper/tt1_paper_pack/figure_data/threshold_trajectories.csv"
REG = ROOT / "docs/research/threshold_transfer_tt1b_result_batadal.json"
OUT = ROOT / "docs/research/threshold_transfer_tt1f_batadal_v1.json"
SPD, GAP, EVENT_L, HOLD = 96, 4, 4, 240
BUDGET = 1 / 7                                    # one false-alarm episode a week, as registered
BOOT, SHIFTS = 10_000, 1000
RULES = ["frozen", "tracker", "tracker_slow", "tracker_tau", "daily", "daily_excl", "tracker_hold", "tracker_capped",
         "static_1.1", "static_1.25", "tracker_ceil_1.1", "tracker_ceil_1.25", "daily_ceil_1.1", "daily_ceil_1.25",
         "tracker_tau_ceil_1.1", "tracker_tau_ceil_1.25"]                    # the last two: amendment 1, part J


def rules():
    """The tt1d rule factory with BATADAL's durations (the factory itself converts from seconds at 60 s)."""
    r = object.__new__(RD.Rules)
    r.step, r.steps_per_day, r.gap, r.event_l, r.hold = 900.0, SPD, GAP, EVENT_L, HOLD
    r.N = RD._copy("threshold_rules_tt1c", "_tt1c_batadal", EVENT_L=EVENT_L, HOLD=HOLD, GAP=GAP, DECLUST=GAP)
    r.B = RD._copy("threshold_rules_tt1e", "_tt1e_batadal")
    r.B.N = r.N
    return r


def make(R, rule, cfg):
    if rule.startswith("tracker_tau_ceil_"):
        return R.B.TrackerCeil({**cfg, "eta": 0.01 * cfg["tau0"]}, float(rule.rsplit("_", 1)[1]))
    return R.make(rule, cfg, None)


def streams(dataset):
    out = {}
    with open(CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["dataset"] != dataset:
                continue
            o = out.setdefault(row["stream"], {"s": [], "lab": [], "tracker": [], "frozen": []})
            o["s"].append(float(row["score_max"]) if row["score_max"] not in ("", "nan") else np.nan)
            o["lab"].append(row["attack"] not in ("0", "", "0.0", "False"))
            o["tracker"].append(float(row["tau_tracker"]))
            o["frozen"].append(float(row["tau_frozen"]))
    return {k: {a: np.asarray(b) for a, b in v.items()} for k, v in sorted(out.items())}


def events(lab):
    edges = np.flatnonzero(np.diff(lab.astype(np.int8)) != 0) + 1
    starts, ends = np.concatenate([[0], edges]), np.concatenate([edges, [len(lab)]])
    return [(int(a), int(b)) for a, b in zip(starts, ends) if lab[a]]


def boot(base, other):
    base, other = np.asarray(base, float), np.asarray(other, float)
    pick = np.random.default_rng(0).integers(0, len(base), (BOOT, len(base)))
    d = other[pick].mean(1) - base[pick].mean(1)
    return [float(v) for v in np.quantile(d, [0.025, 0.975])]


def chance(alarms, gap):
    """alarms: [(alarm array, events)] per stream. Detections when each stream's alarm sequence is shifted
    circularly by a random offset: mean and central 95 % range over SHIFTS shifts, both counts."""
    rng = np.random.default_rng(7)
    any_s, on_s, any_o, on_o = np.zeros(SHIFTS), np.zeros(SHIFTS), 0, 0
    for alarm, ev in alarms:
        n = len(alarm)
        starts = np.zeros(n, bool)
        for a, _ in T._episodes(alarm, gap):
            starts[a] = True
        ca, cs = np.concatenate([[0], np.cumsum(alarm)]), np.concatenate([[0], np.cumsum(starts)])
        offs = rng.integers(1, n, SHIFTS)
        for a, b in ev:
            any_o += bool(alarm[a:b].any()); on_o += bool(starts[a:b].any())
            lo, hi = (a - offs) % n, (b - offs) % n
            wrap = hi <= lo
            any_s += np.where(wrap, ca[n] - ca[lo] + ca[hi], ca[hi] - ca[lo]) > 0
            on_s += np.where(wrap, cs[n] - cs[lo] + cs[hi], cs[hi] - cs[lo]) > 0
    r3 = lambda x: [float(np.mean(x)), float(np.quantile(x, 0.025)), float(np.quantile(x, 0.975))]
    return {"detected": int(any_o), "onset_detected": int(on_o), "shifted_detected_mean_lo_hi": r3(any_s),
            "shifted_onset_mean_lo_hi": r3(on_s)}


def peak_summary(peaks):
    pk = np.asarray(peaks)
    return {"events": int(len(pk)), "quantiles_0_25_50_75_100": [float(v) for v in np.quantile(pk, [0, 0.25, 0.5, 0.75, 1])],
            "events_with_peak_below": {str(k): int((pk < k).sum()) for k in (1.0, 1.1, 1.25, 1.5, 2.0)}}


def main():
    cfg = json.loads(REG.read_text(encoding="utf-8"))["scores"]["D1"]["thresholds"]
    R = rules()
    per = {r: {"found": [], "onset": [], "inflation": [], "fa": 0, "alarm_unlabelled": 0, "alarms": []} for r in RULES}
    unlabelled, peaks = 0, []
    for name, d in streams("batadal").items():
        s = np.where(np.isfinite(d["s"]), d["s"], -np.inf)
        lab, ev = d["lab"], events(d["lab"])
        unlabelled += int((~lab).sum())
        peaks += [float(np.max(s[a:b]) / cfg["tau0"]) for a, b in ev]
        for r in RULES:
            m = make(R, r, cfg)
            tau = np.empty(len(s))
            for i, x in enumerate(s):
                tau[i] = m.tau()
                m.update(x)
            if r == "tracker" and not np.allclose(tau, d["tracker"], rtol=0, atol=1e-6):   # the trace has 6 decimals
                raise SystemExit(f"{name}: the tracker path differs from the stored registered trajectory")
            alarm = s > tau
            eps = T._episodes(alarm, GAP)
            starts = np.zeros(len(s), bool)
            for a, _ in eps:
                starts[a] = True
            o = per[r]
            o["found"] += [bool(alarm[a:b].any()) for a, b in ev]
            o["onset"] += [bool(starts[a:b].any()) for a, b in ev]
            o["inflation"] += [float(tau[a] / cfg["tau0"]) for a, _ in ev]
            o["fa"] += int(sum(1 for a, b in eps if not lab[a:b].any()))
            o["alarm_unlabelled"] += int((alarm & ~lab).sum())
            o["alarms"].append((alarm, ev))
    if sum(per["frozen"]["found"]) != 14 or sum(per["tracker"]["found"]) != 6 or len(per["frozen"]["found"]) != 14:
        raise SystemExit(f"registered counts not reproduced: frozen {sum(per['frozen']['found'])}, tracker {sum(per['tracker']['found'])}")
    days = unlabelled / SPD
    out = {"schema_version": "threshold-transfer-tt1f-batadal-v1",
           "status": "exploratory, post-hoc: BATADAL and HAI 20.07 from the stored traces of the registered finals; no new access",
           "plan": "docs/research/threshold_transfer_tt1f_dev_plan.md (parts D and J; trace-based parts of F and I)",
           "settings": {"steps_per_day": SPD, "gap_steps": GAP, "event_steps": EVENT_L, "hold_steps": HOLD,
                        "budget_per_day": BUDGET, "thresholds": cfg, "eta_over_tau0": cfg["eta"] / cfg["tau0"]},
           "unlabelled_days": days, "events": 14, "rules": {}, "peak_scores_over_tau0": peak_summary(peaks)}
    for r in RULES:
        o = per[r]
        row = {"detected": int(sum(o["found"])), "onset_detected": int(sum(o["onset"])),
               "fa_ratio_to_budget": o["fa"] / days / BUDGET, "unlabelled_alarm_share": o["alarm_unlabelled"] / unlabelled,
               "median_onset_inflation": float(np.median(o["inflation"]))}
        if r != "frozen":
            row["vs_frozen_interval"] = boot(per["frozen"]["found"], o["found"])
            row["vs_frozen_onset_interval"] = boot(per["frozen"]["onset"], o["onset"])
        if r in ("frozen", "tracker", "tracker_tau", "daily"):
            row["chance_reference"] = chance(o["alarms"], GAP)
        out["rules"][r] = row
        print(f"{r:22s} any {row['detected']:2d}/14 onset {row['onset_detected']:2d}/14 fa x{row['fa_ratio_to_budget']:.2f} "
              f"infl {row['median_onset_inflation']:.3g}" + (f" chance {row['chance_reference']['shifted_detected_mean_lo_hi']}" if "chance_reference" in row else ""))
    # HAI 20.07, one row a minute: the minute's largest score against the registered threshold paths
    hai, hpeaks, alarms = streams("hai-20.07"), [], {"frozen": [], "tracker": []}
    for name, d in hai.items():
        s = np.where(np.isfinite(d["s"]), d["s"], -np.inf)
        ev = events(d["lab"])
        hpeaks += [float(np.max(s[a:b]) / d["frozen"][0]) for a, b in ev]
        for r in alarms:
            alarms[r].append((s > d[r], ev))
    out["hai_20_07_minute_trace"] = {"note": "one row a minute (largest score of the minute); episode gap one minute; approximate",
                                     "events": int(sum(len(ev) for _, ev in alarms["frozen"])),
                                     "peak_scores_over_tau0": peak_summary(hpeaks),
                                     "chance_reference": {r: chance(v, 1) for r, v in alarms.items()}}
    for r, v in out["hai_20_07_minute_trace"]["chance_reference"].items():
        print("hai-20.07", r, v)
    print("peaks batadal", out["peak_scores_over_tau0"], "hai-20.07", out["hai_20_07_minute_trace"]["peak_scores_over_tau0"])
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print("written", OUT)


if __name__ == "__main__":
    main()
