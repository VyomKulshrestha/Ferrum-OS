#!/usr/bin/env python3
"""tt1f part D (exploratory, post-hoc): the stronger rules on BATADAL, from the stored trace.

Plan: docs/research/threshold_transfer_tt1f_dev_plan.md (committed before any run). The trace
docs/research/paper/tt1_paper_pack/figure_data/threshold_trajectories.csv holds the 15-minute D1 score and the
attack labels of both BATADAL test files, written after the registered tt1b final, so the dataset is not
opened again. Durations are scaled as tt1b scaled them (60 s on HAI is 1 h here).

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
BOOT = 10_000
RULES = ["frozen", "tracker", "tracker_slow", "tracker_tau", "daily", "daily_excl", "tracker_hold", "tracker_capped",
         "static_1.1", "static_1.25", "tracker_ceil_1.1", "tracker_ceil_1.25", "daily_ceil_1.1", "daily_ceil_1.25"]


def rules():
    """The tt1d rule factory with BATADAL's durations (the factory itself converts from seconds at 60 s)."""
    r = object.__new__(RD.Rules)
    r.step, r.steps_per_day, r.gap, r.event_l, r.hold = 900.0, SPD, GAP, EVENT_L, HOLD
    r.N = RD._copy("threshold_rules_tt1c", "_tt1c_batadal", EVENT_L=EVENT_L, HOLD=HOLD, GAP=GAP, DECLUST=GAP)
    r.B = RD._copy("threshold_rules_tt1e", "_tt1e_batadal")
    r.B.N = r.N
    return r


def streams():
    out = {}
    with open(CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["dataset"] != "batadal":
                continue
            o = out.setdefault(row["stream"], {"s": [], "lab": [], "tracker": []})
            o["s"].append(float(row["score_max"]) if row["score_max"] not in ("", "nan") else np.nan)
            o["lab"].append(row["attack"] not in ("0", "", "0.0", "False"))
            o["tracker"].append(float(row["tau_tracker"]))
    return {k: {a: np.asarray(b) for a, b in v.items()} for k, v in out.items()}


def events(lab):
    edges = np.flatnonzero(np.diff(lab.astype(np.int8)) != 0) + 1
    starts, ends = np.concatenate([[0], edges]), np.concatenate([edges, [len(lab)]])
    return [(int(a), int(b)) for a, b in zip(starts, ends) if lab[a]]


def boot(base, other):
    base, other = np.asarray(base, float), np.asarray(other, float)
    pick = np.random.default_rng(0).integers(0, len(base), (BOOT, len(base)))
    d = other[pick].mean(1) - base[pick].mean(1)
    return [float(v) for v in np.quantile(d, [0.025, 0.975])]


def main():
    cfg = json.loads(REG.read_text(encoding="utf-8"))["scores"]["D1"]["thresholds"]
    R = rules()
    per = {r: {"found": [], "onset": [], "inflation": [], "fa": 0, "alarm_unlabelled": 0} for r in RULES}
    unlabelled = 0
    for name, d in sorted(streams().items()):
        s = np.where(np.isfinite(d["s"]), d["s"], -np.inf)
        lab, ev = d["lab"], events(d["lab"])
        unlabelled += int((~lab).sum())
        for r in RULES:
            m = R.make(r, cfg, None)
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
    if sum(per["frozen"]["found"]) != 14 or sum(per["tracker"]["found"]) != 6 or len(per["frozen"]["found"]) != 14:
        raise SystemExit(f"registered counts not reproduced: frozen {sum(per['frozen']['found'])}, tracker {sum(per['tracker']['found'])}")
    days = unlabelled / SPD
    out = {"schema_version": "threshold-transfer-tt1f-batadal-v1",
           "status": "exploratory, post-hoc: BATADAL from the stored trace of the registered tt1b final; no new access",
           "plan": "docs/research/threshold_transfer_tt1f_dev_plan.md",
           "settings": {"steps_per_day": SPD, "gap_steps": GAP, "event_steps": EVENT_L, "hold_steps": HOLD,
                        "budget_per_day": BUDGET, "thresholds": cfg, "eta_over_tau0": cfg["eta"] / cfg["tau0"]},
           "unlabelled_days": days, "events": 14, "rules": {}}
    for r in RULES:
        o = per[r]
        row = {"detected": int(sum(o["found"])), "onset_detected": int(sum(o["onset"])),
               "fa_ratio_to_budget": o["fa"] / days / BUDGET, "unlabelled_alarm_share": o["alarm_unlabelled"] / unlabelled,
               "median_onset_inflation": float(np.median(o["inflation"]))}
        if r != "frozen":
            row["vs_frozen_interval"] = boot(per["frozen"]["found"], o["found"])
            row["vs_frozen_onset_interval"] = boot(per["frozen"]["onset"], o["onset"])
        out["rules"][r] = row
        print(f"{r:20s} any {row['detected']:2d}/14 onset {row['onset_detected']:2d}/14 fa x{row['fa_ratio_to_budget']:.2f} "
              f"infl {row['median_onset_inflation']:.3g}")
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print("written", OUT)


if __name__ == "__main__":
    main()
