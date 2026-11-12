#!/usr/bin/env python3
"""fi1 workstream A: the monitor benchmark (EXPLORATORY; every dataset is spent).

Plan: docs/research/ferrumos_improvement_fi1_plan.md ("Monitor benchmark"). Reads the residual cache written by
fi1_monitor_extract.py and scores a monitor (the registered D1 baseline or a candidate of fi1_monitor_v3) on the
selection set or the check set:

    python scripts/fi1_monitor_benchmark.py reproduce              baseline vs the registered numbers (all units)
    python scripts/fi1_monitor_benchmark.py run <monitor> selection
    python scripts/fi1_monitor_benchmark.py run <monitor> check     appends to the check ledger (fi1/monitor/check_ledger.jsonl)

Calibration: real_telemetry_detect_v2.calibrate on the registered calibration split of attack-free data, to the
episode budget of the study that used the dataset (voraus-AD: the registered per-sample quantile). Smoothing:
the registered trailing mean with the warm-up blanked. Metrics per dataset (events pooled over its units):
onset recall (an alarm episode, merged across the gap, starts inside the event), any-alarm recall with a
circular-shift chance reference (200 shifts per stream, seed 7), share of unlabelled time in alarm, false-alarm
episodes per day on unlabelled time and their ratio to the budget, step-level average precision of score/tau,
and the median time from event start to the first alarm.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_k, "2")

import datetime
import json
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.metrics import average_precision_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_telemetry_detect as R
import real_telemetry_detect_v2 as R2
import threshold_rules as T

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "target/real-telemetry/fi1/monitor"
RESID = WORK / "resid"
CHECK_LEDGER = WORK / "check_ledger.jsonl"
SHIFTS, SHIFT_SEED = 200, 7
WARMUP = R.WARMUP

SELECTION = {"hai-21.03": ["hai-21.03"], "hai-22.04": ["hai-22.04"], "tep-0-3": [f"tep-m{m}" for m in range(4)]}
CHECK = {"hai-20.07": ["hai-20.07"], "hai-23.05": ["hai-23.05"], "batadal": ["batadal"],
         "hygrid-ics": ["hygrid-ics"], "voraus-ad": ["voraus-ad"], "tep-4-6": [f"tep-m{m}" for m in range(4, 7)],
         "provics": ["provics"]}
SETS = {"selection": SELECTION, "check": CHECK}


# ---------------------------------------------------------------- cache access
class Stream:
    """One cached stream: residuals (memory-mapped), actions, labels, events and validity."""

    def __init__(self, d, key, spec, row=None):
        self.d, self.key, self.spec, self.row = d, key, spec, row or {}
        self.steps = int(self.row.get("steps", 0)) or len(self.load("R1"))

    def load(self, name, mmap=True):
        p = self.d / f"{self.key}_{name}.npy"
        return np.load(p, mmap_mode="r" if mmap else None) if p.exists() else None

    def arrays(self):
        return {k: self.load(k) for k in ("R1", "R5", "U", "Z")}


class Unit:
    def __init__(self, name):
        self.name = name
        self.d = RESID / name
        self.meta = json.loads((self.d / "meta.json").read_text(encoding="utf-8"))
        self.spec = self.meta["spec"]
        self.sig1 = np.load(self.d / "sig1.npy")
        self.sig5 = np.load(self.d / "sig5.npy")
        self.fit_low = np.load(self.d / "fit_low.npy")
        self.fit_high = np.load(self.d / "fit_high.npy")

    def streams(self, group):
        return [Stream(self.d, row["key"], self.spec, row) for row in self.meta["groups"].get(group, [])]

    @property
    def episodic(self):
        return self.spec["kind"] == "episodic"


def labels_and_events(unit, stream):
    """(lab, valid, events) for a test or sealed stream; events = [(a, b, type, order)] with end exclusive."""
    n = stream.steps
    valid = np.ones(n, bool)
    if unit.name.startswith("tep-"):
        import tt1d_data as TD

        key = stream.load("key", mmap=False)
        if key is None:
            return np.zeros(n, bool), valid, []
        ev = TD.events(key)
        return key != 0, valid, [(a, b, stream.row.get("type", 0), i) for i, (a, b, _) in enumerate(ev)]
    if unit.name == "provics":
        import tt1d_data_v2 as TD2

        v = stream.load("valid", mmap=False)
        valid = TD2.provics_valid_v2(v, unit.spec["window"])           # the audit's extended mask
        ev = stream.load("events", mmap=False)
        lab = np.zeros(n, bool)
        events = []
        if ev is not None:
            for i, (a, b, k) in enumerate(ev):
                lab[a:b] = True
                events.append((int(a), int(b), int(k), i))
        return lab, valid, events
    y = stream.load("y", mmap=False)
    if y is None:
        return np.zeros(n, bool), valid, []
    import real_telemetry_core as C

    ev = C.events(y)
    lab = np.zeros(n, bool)
    for a, b in ev:
        lab[a:b] = True
    return lab, valid, [(int(a), int(b), 0, i) for i, (a, b) in enumerate(ev)]


# ---------------------------------------------------------------- monitors
def smooth(raw, window):
    s = R.smooth(np.asarray(raw), window)
    s[:WARMUP] = np.nan
    return s


def episodic_scores(unit, stream, monitor):
    """voraus-AD: one score per sample, the maximum of the smoothed per-step score (registered tt1 rule)."""
    lens = stream.load("lengths", mmap=False)
    a = stream.arrays()
    out, at = [], 0
    for n in lens:
        sl = slice(at, at + n)
        raw = monitor.raw(unit, {k: (None if v is None else np.asarray(v[sl])) for k, v in a.items()})
        out.append(float(np.nanmax(smooth(raw, unit.spec["window"]))))
        at += n
    return np.array(out)


def stream_score(unit, stream, monitor, valid=None):
    """Smoothed score as the rules see it: warm-up and invalid steps are -inf and cannot alarm."""
    a = stream.arrays()
    s = smooth(monitor.raw(unit, {k: (None if v is None else np.asarray(v)) for k, v in a.items()}), unit.spec["window"])
    ok = np.isfinite(s) if valid is None else np.isfinite(s) & valid
    return np.where(ok, s, -np.inf)


def calibrate_unit(unit, monitor):
    """Fit the monitor's normal-data statistics, then the threshold on the calibration split."""
    monitor.fit(unit)
    if unit.episodic:
        cal = episodic_scores(unit, unit.streams("calib")[0], monitor)
        return monitor.threshold_episodic(unit, cal) if hasattr(monitor, "threshold_episodic") else \
            float(np.quantile(cal, 1 - unit.spec["alpha"])), cal
    cal = []
    for st in unit.streams("calib"):
        s = stream_score(unit, st, monitor)
        cal.append(s[np.isfinite(s)])
    if hasattr(monitor, "threshold"):
        return float(monitor.threshold(unit, cal)), cal
    return float(R2.calibrate(cal, unit.spec["gap"], unit.spec["budget"], unit.spec["spd"])), cal


# ---------------------------------------------------------------- metrics
def _shift_counts(alarm, starts, events, rng):
    """Detections under SHIFTS circular shifts of one stream's alarm and episode-start sequences."""
    n = len(alarm)
    ks = rng.integers(0, n, SHIFTS)
    ca = np.concatenate([[0], np.cumsum(alarm)])
    cs = np.concatenate([[0], np.cumsum(starts)])
    any_c, on_c = np.zeros(SHIFTS, int), np.zeros(SHIFTS, int)
    for a, b, *_ in events:
        # shifted sequence x'[t] = x[(t - k) mod n]; window [a, b) reads x over [(a - k) mod n, (b - k) mod n)
        lo = (a - ks) % n
        hi = lo + (b - a)
        wrap = hi > n

        def total(c):
            inner = c[np.minimum(hi, n)] - c[lo]
            extra = np.where(wrap, c[np.clip(hi - n, 0, n)], 0)
            return inner + extra

        any_c += total(ca) > 0
        on_c += total(cs) > 0
    return any_c, on_c


def stream_rows(unit, stream, s, tau, lab, valid, events, rng):
    gap = unit.spec["gap"]
    alarm = s > tau
    eps = T._episodes(alarm, gap)
    starts = np.zeros(len(s), bool)
    for a, _ in eps:
        starts[a] = True
    found, onset, delay = [], [], []
    for a, b, *_ in events:
        hit = np.flatnonzero(alarm[a:b])
        found.append(bool(len(hit)))
        onset.append(bool(starts[a:b].any()))
        delay.append(float(hit[0]) * unit.spec["step"] if len(hit) else None)
    unl = ~lab & valid
    any_c, on_c = _shift_counts(alarm, starts, events, rng) if events else (np.zeros(SHIFTS, int), np.zeros(SHIFTS, int))
    ok = np.isfinite(s) & valid
    return {"found": found, "onset": onset, "delay": delay,
            "types": [e[2] for e in events], "order": [e[3] for e in events],
            "fa": int(sum(1 for a, b in eps if not lab[a:b].any())),
            "unlabelled": int(unl.sum()), "unlabelled_alarm": int((alarm & unl).sum()),
            "chance_any": any_c, "chance_onset": on_c,
            "ap_score": (s[ok] / tau).astype(np.float32), "ap_label": lab[ok]}


def _ci(x):
    return [float(np.quantile(x, 0.025)), float(np.quantile(x, 0.975))]


def pool(unit_rows, spec_budget, spd_of):
    """Pool stream rows of one dataset. unit_rows: [(unit, rows)]."""
    found = sum((r["found"] for _, rows in unit_rows for r in rows), [])
    onset = sum((r["onset"] for _, rows in unit_rows for r in rows), [])
    delay = [d for _, rows in unit_rows for r in rows for d in r["delay"] if d is not None]
    order = sum((r["order"] for _, rows in unit_rows for r in rows), [])
    unl_days = sum(r["unlabelled"] / spd_of[u] for u, rows in unit_rows for r in rows)
    fa = sum(r["fa"] for _, rows in unit_rows for r in rows)
    unl = sum(r["unlabelled"] for _, rows in unit_rows for r in rows)
    unl_alarm = sum(r["unlabelled_alarm"] for _, rows in unit_rows for r in rows)
    ca = sum(r["chance_any"] for _, rows in unit_rows for r in rows)
    co = sum(r["chance_onset"] for _, rows in unit_rows for r in rows)
    y = np.concatenate([r["ap_label"] for _, rows in unit_rows for r in rows])
    sc = np.concatenate([r["ap_score"] for _, rows in unit_rows for r in rows])
    n = len(found)
    out = {"events": n, "detected": int(sum(found)), "onset_detected": int(sum(onset)),
           "any_recall": float(np.mean(found)) if n else None, "onset_recall": float(np.mean(onset)) if n else None,
           "chance_any": {"mean": float(np.mean(ca)), "ci95": _ci(ca)} if n else None,
           "chance_onset": {"mean": float(np.mean(co)), "ci95": _ci(co)} if n else None,
           "unlabelled_alarm_share": unl_alarm / max(unl, 1), "fa_per_day": fa / max(unl_days, 1e-9),
           "fa_ratio_to_budget": fa / max(unl_days, 1e-9) / spec_budget,
           "average_precision": float(average_precision_score(y, sc)) if 0 < y.sum() < len(y) else None,
           "median_seconds_to_first_alarm": float(np.median(delay)) if delay else None,
           "unlabelled_days": unl_days}
    if any(o > 0 for o in order):
        for name, keep in (("first", [o == 0 for o in order]), ("follower", [o > 0 for o in order])):
            out[name] = {"events": int(sum(keep)), "detected": int(sum(f for f, k in zip(found, keep) if k)),
                         "onset_detected": int(sum(f for f, k in zip(onset, keep) if k))}
    return out


def evaluate_unit(unit, monitor):
    """Calibrate on attack-free data, then score every test (and sealed) stream of the unit."""
    tau, cal = calibrate_unit(unit, monitor)
    out = {"tau": tau}
    if unit.episodic:
        st = unit.streams("test")[0]
        seq = episodic_scores(unit, st, monitor)
        flags = st.load("flags", mmap=False).astype(bool)
        alarm = seq > tau
        out["episodic"] = {"anomalous": int(flags.sum()), "detected": int(alarm[flags].sum()),
                           "fpr": float(alarm[~flags].mean()), "fpr_ratio_to_target": float(alarm[~flags].mean() / unit.spec["alpha"]),
                           "average_precision": float(average_precision_score(flags, seq))}
        return out, None, None
    rng = np.random.default_rng(SHIFT_SEED)
    rows = []
    for st in unit.streams("test"):
        lab, valid, events = labels_and_events(unit, st)
        s = stream_score(unit, st, monitor, valid)
        rows.append(stream_rows(unit, st, s, tau, lab, valid, events, rng))
    sealed = []
    for st in unit.streams("sealed"):
        lab, valid, _ = labels_and_events(unit, st)
        s = stream_score(unit, st, monitor, valid)
        alarm = s > tau
        sealed.append({"fa": len(T._episodes(alarm, unit.spec["gap"])), "steps": int(valid.sum()),
                       "alarm": int(alarm.sum())})
    return out, rows, sealed


def evaluate_set(monitor_name, set_name, units_filter=None):
    import fi1_monitor_v3 as V

    datasets = SETS[set_name]
    result = {}
    for ds, units in datasets.items():
        if units_filter and ds not in units_filter:
            continue
        t0 = time.time()
        unit_rows, sealed_all, taus, spd_of = [], [], {}, {}
        episodic = None
        budget = None
        for name in units:
            unit = Unit(name)
            monitor = V.make(monitor_name)
            info, rows, sealed = evaluate_unit(unit, monitor)
            taus[name] = info["tau"]
            if unit.episodic:
                episodic = info["episodic"]
                continue
            spd_of[name] = unit.spec["spd"]
            budget = unit.spec["budget"]
            unit_rows.append((name, rows))
            sealed_all += [(name, r) for r in sealed]
        if episodic is not None:
            e = episodic
            row = {"events": e["anomalous"], "detected": e["detected"], "onset_detected": e["detected"],
                   "any_recall": e["detected"] / e["anomalous"], "onset_recall": e["detected"] / e["anomalous"],
                   "chance_any": None, "unlabelled_alarm_share": e["fpr"], "fa_per_day": None,
                   "fa_ratio_to_budget": e["fpr_ratio_to_target"], "average_precision": e["average_precision"],
                   "median_seconds_to_first_alarm": None,
                   "note": "episodic: an event is an anomalous sample; onset = any-alarm = sample alarm; "
                           "alarm share = false-positive rate of normal samples; budget = the 5 % sample target"}
        else:
            row = pool(unit_rows, budget, spd_of)
            if sealed_all:
                days = sum(r["steps"] / spd_of[u] for u, r in sealed_all)
                row["sealed_fa_ratio_to_budget"] = sum(r["fa"] for _, r in sealed_all) / days / budget
                row["sealed_alarm_share"] = sum(r["alarm"] for _, r in sealed_all) / sum(r["steps"] for _, r in sealed_all)
        row["tau"] = taus
        row["seconds"] = round(time.time() - t0)
        result[ds] = row
        print(f"{monitor_name:24s} {ds:11s} onset {row['onset_detected']}/{row['events']} any {row['detected']}"
              f" share {row['unlabelled_alarm_share']:.4f} fa x{row['fa_ratio_to_budget']:.2f}"
              f" ap {row['average_precision'] if row['average_precision'] is None else round(row['average_precision'], 3)}"
              f" ({row['seconds']} s)", flush=True)
    return result


def summary(result):
    on = [v["onset_recall"] for v in result.values() if v.get("onset_recall") is not None]
    sh = [v["unlabelled_alarm_share"] for v in result.values()]
    return {"mean_onset_recall": float(np.mean(on)), "mean_unlabelled_alarm_share": float(np.mean(sh))}


def verdict(base, cand):
    """The plan's definition of improved, on the check set."""
    sb, sc = summary(base), summary(cand)
    drops = {k: cand[k]["onset_recall"] - base[k]["onset_recall"] for k in base}
    ok = (sc["mean_onset_recall"] - sb["mean_onset_recall"] >= 0.05 and
          sc["mean_unlabelled_alarm_share"] <= sb["mean_unlabelled_alarm_share"] and
          all(d >= -0.05 for d in drops.values()))
    return {"improved": bool(ok), "mean_onset_recall_gain": sc["mean_onset_recall"] - sb["mean_onset_recall"],
            "mean_alarm_share_change": sc["mean_unlabelled_alarm_share"] - sb["mean_unlabelled_alarm_share"],
            "onset_recall_change_per_dataset": drops,
            "alarm_share_hai_20_07": [base["hai-20.07"]["unlabelled_alarm_share"], cand["hai-20.07"]["unlabelled_alarm_share"]],
            "alarm_share_provics": [base["provics"]["unlabelled_alarm_share"], cand["provics"]["unlabelled_alarm_share"]]}


def survives_selection(base, cand):
    """The selection rule of docs/research/fi1_reports/monitor_round1.md (fixed before the full selection results)."""
    sb, sc = summary(base), summary(cand)
    drops = {k: cand[k]["onset_recall"] - base[k]["onset_recall"] for k in base}
    sealed = cand["tep-0-3"].get("sealed_fa_ratio_to_budget", 0.0)
    checks = {"mean_onset_gain_ge_0.02": sc["mean_onset_recall"] - sb["mean_onset_recall"] >= 0.02,
              "mean_share_not_higher": sc["mean_unlabelled_alarm_share"] <= sb["mean_unlabelled_alarm_share"],
              "no_dataset_loses_more_than_0.05": all(d >= -0.05 for d in drops.values()),
              "tep_sealed_fa_below_1.5_budget": sealed < 1.5}
    return {"survives": all(checks.values()), "checks": checks,
            "mean_onset_recall": sc["mean_onset_recall"], "mean_unlabelled_alarm_share": sc["mean_unlabelled_alarm_share"],
            "mean_onset_gain": sc["mean_onset_recall"] - sb["mean_onset_recall"], "onset_change": drops,
            "tep_sealed_fa_ratio": sealed}


def select(names):
    path = WORK / "results" / "selection_table.json"
    table = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for n in ["d1"] + [n for n in names if n != "d1"]:
        if n not in table:
            table[n] = evaluate_set(n, "selection")
            save(path, table)
    rows = {n: survives_selection(table["d1"], r) for n, r in table.items() if n != "d1"}
    rows = dict(sorted(rows.items(), key=lambda kv: -kv[1]["mean_onset_recall"]))
    sb = summary(table["d1"])
    print(f"baseline d1: mean onset {sb['mean_onset_recall']:.3f} mean share {sb['mean_unlabelled_alarm_share']:.4f}")
    for n, r in rows.items():
        print(f"{n:22s} {'SURVIVES' if r['survives'] else 'out     '} mean onset {r['mean_onset_recall']:.3f} "
              f"({r['mean_onset_gain']:+.3f}) share {r['mean_unlabelled_alarm_share']:.4f} sealed x{r['tep_sealed_fa_ratio']:.2f} "
              + " ".join(f"{k} {v:+.3f}" for k, v in r["onset_change"].items()))
    save(WORK / "results" / "selection_verdicts.json", {"baseline": sb, "candidates": rows})
    return rows


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=float), encoding="utf-8")


class _CachedStream:
    def __init__(self, n, row):
        self.steps, self.row = n, row


class _CachedUnit:
    def __init__(self, name, spec):
        self.name, self.spec = name, spec


def reproduce_tep_cache(modes=range(7)):
    """Metric code against the registered tt1d Tennessee Eastman record: the registered D1 scores cached by
    tt1f (target/real-telemetry/tt1f/mode_<m>.npz, registered thresholds) through this harness's metrics."""
    import tt1d_data as TD

    cache = ROOT / "target/real-telemetry/tt1f"
    spec = {"gap": 17, "window": 17, "budget": 2.0, "spd": 24000, "step": 3.6}
    rng = np.random.default_rng(SHIFT_SEED)
    unit_rows, sealed, spd_of = [], [], {}
    for m in modes:
        z = np.load(cache / f"mode_{m}.npz")
        cfg = json.loads(str(z["cfg"]))
        unit = _CachedUnit(f"tep-m{m}", spec)
        rows = []
        for k in z.files:
            if k.startswith("attack::"):
                s, key = z[k], z["key::" + k.split("::", 1)[1]]
                ev = TD.events(key)
                events = [(a, b, 0, i) for i, (a, b, _) in enumerate(ev)]
                rows.append(stream_rows(unit, _CachedStream(len(s), {}), s, cfg["tau0"], key != 0,
                                        np.ones(len(s), bool), events, rng))
            elif k.startswith("sealed::"):
                s = z[k]
                sealed.append((unit.name, len(T._episodes(s > cfg["tau0"], spec["gap"])), len(s)))
        unit_rows.append((unit.name, rows))
        spd_of[unit.name] = spec["spd"]
    row = pool(unit_rows, spec["budget"], spd_of)
    days = sum(n / spec["spd"] for _, _, n in sealed)
    row["sealed_fa_ratio_to_budget"] = sum(f for _, f, _ in sealed) / days / spec["budget"]
    return row


# Registered (or registered-pipeline exploratory) numbers of the frozen D1 rule, with their source files.
REGISTERED = {
    "hai-21.03": {"src": "threshold_transfer_tt1c_dev_v1.json natural (exploratory, tt1-final split)",
                  "events": 50, "detected": 50, "onset_detected": 49, "unlabelled_alarm_share": 0.007571, "fa_per_day": 0.6594},
    "hai-22.04": {"src": "threshold_transfer_tt1c_dev_v1.json natural (exploratory, tt1-final split)",
                  "events": 58, "detected": 44, "onset_detected": 44, "unlabelled_alarm_share": 0.002744, "fa_per_day": 1.4847},
    "hai-23.05": {"src": "threshold_transfer_tt1c_dev_v1.json natural (exploratory, tt1-final split)",
                  "events": 52, "detected": 31, "onset_detected": 31, "unlabelled_alarm_share": 0.007113, "fa_per_day": 1.2659},
    "hai-20.07": {"src": "threshold_transfer_tt1_result_hai-20.07.json (registered) + tt1_posthoc_alarm_time.json",
                  "tau": 17.25877, "events": 38, "detected": 36, "onset_detected": 26, "unlabelled_alarm_share": 0.39096,
                  "fa_per_day": 2.2254},
    "hygrid-ics": {"src": "threshold_transfer_tt1_result_hygrid-ics.json (registered) + tt1_posthoc_alarm_time.json",
                   "tau": 4.75370, "events": 91, "detected": 27, "onset_detected": 3, "unlabelled_alarm_share": 0.04067,
                   "fa_per_day": 19.202},
    "batadal": {"src": "threshold_transfer_tt1b_result_batadal.json (registered) + tt1_posthoc_alarm_time.json",
                "tau": 9.39328, "events": 14, "detected": 14, "onset_detected": 14, "unlabelled_alarm_share": 0.013685,
                "fa_ratio_to_budget": 0.7012},
    "voraus-ad": {"src": "threshold_transfer_tt1_result_voraus-ad.json (registered)", "tau": 9.77571,
                  "events": 755, "detected": 252, "unlabelled_alarm_share": 0.081146},
    "provics": {"src": "threshold_transfer_tt1f_provics_mask_v1.json, extended mask (registered mask: 25 / onset 4 / 0.4411)",
                "tau": 3.95370, "events": 32, "detected": 23, "onset_detected": 3, "unlabelled_alarm_share": 0.43989,
                "fa_ratio_to_budget": 33.705},
    "tep-0-3": {"src": "threshold_transfer_tt1d_result_tep59.json units mode_0..3 (registered)"},
    "tep-4-6": {"src": "threshold_transfer_tt1d_result_tep59.json units mode_4..6 (registered)"},
}


def registered_tep(modes):
    """Registered frozen-rule counts for a subset of Tennessee Eastman modes, from the per-unit records."""
    d = json.loads((ROOT / "docs/research/threshold_transfer_tt1d_result_tep59.json").read_text(encoding="utf-8"))
    found = onset = n = fa = alarm = unl = 0
    sealed_fa = sealed_steps = 0
    first = [0, 0]
    taus = {}
    for u in d["units"]:
        if int(u["unit"].split("_")[1]) not in modes:
            continue
        taus[u["unit"]] = u["thresholds"]["D1"]["tau0"]
        for run in u["attack_runs"]:
            v = run["scores"]["D1"]["frozen"]
            found += sum(v["found"]); onset += sum(v["onset"]); n += len(v["found"])
            first[0] += int(v["found"][0]) if v["found"] else 0
            first[1] += 1 if v["found"] else 0
            fa += v["fa"]; alarm += v["alarm_unlabelled"]; unl += run["unlabelled_steps"]
        for run in u["sealed_runs"]:
            sealed_fa += run["false_alarms"]["frozen"]["fa"]; sealed_steps += run["steps"]
    return {"tau": taus, "events": n, "detected": found, "onset_detected": onset, "first_detected": first[0],
            "first_events": first[1], "unlabelled_alarm_share": alarm / unl, "fa_ratio_to_budget": fa / (unl / 24000) / 2,
            "sealed_fa_ratio_to_budget": sealed_fa / (sealed_steps / 24000) / 2}


def main():
    cmd = sys.argv[1]
    if cmd == "registered":
        REGISTERED["tep-0-3"] |= registered_tep(range(4))
        REGISTERED["tep-4-6"] |= registered_tep(range(4, 7))
        print(json.dumps(REGISTERED, indent=1))
        save(WORK / "results" / "registered.json", REGISTERED)
    elif cmd == "select":
        select(sys.argv[2:])
    elif cmd == "check":
        # baseline and the survivors of selection, once each on the check set; a monitor already in the
        # check ledger is refused (no second look)
        done = set()
        if CHECK_LEDGER.exists():
            done = {json.loads(line)["monitor"] for line in CHECK_LEDGER.read_text(encoding="utf-8").splitlines() if line}
        names = ["d1"] + [n for n in sys.argv[2:] if n != "d1"]
        again = [n for n in names if n in done]
        if again:
            raise SystemExit(f"REFUSE: already run on the check set: {again}")
        out = {}
        for n in names:
            with CHECK_LEDGER.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"monitor": n, "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                    "datasets": list(CHECK)}) + "\n")
            out[n] = evaluate_set(n, "check")
            save(WORK / "results" / "check_table.json", out)
        verdicts = {n: verdict(out["d1"], r) for n, r in out.items() if n != "d1"}
        for n, v in verdicts.items():
            print(n, "IMPROVED" if v["improved"] else "not improved", json.dumps(v, default=float))
        save(WORK / "results" / "check_verdicts.json", {"baseline": summary(out["d1"]), "verdicts": verdicts})
    elif cmd == "tep-cache":
        row = reproduce_tep_cache()
        print(json.dumps({k: v for k, v in row.items() if k not in ("chance_onset",)}, indent=1, default=float))
        save(WORK / "results" / "reproduce_tep_cache.json", row)
    elif cmd == "run":
        name, set_name = sys.argv[2], sys.argv[3]
        only = sys.argv[4:] or None
        if set_name == "check":
            with CHECK_LEDGER.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"monitor": name, "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                    "datasets": only or list(CHECK)}) + "\n")
        res = evaluate_set(name, set_name, only)
        tag = "_".join(only) if only else "all"
        save(WORK / "results" / f"{set_name}_{name}_{tag}.json", {"monitor": name, "set": set_name, "datasets": res})
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
