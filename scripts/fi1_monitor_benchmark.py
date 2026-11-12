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

SELECTION = {
    "hai-21.03": ["hai-21.03"],
    "hai-22.04": ["hai-22.04"],
    "tep-0-3": [f"tep-m{m}" for m in range(4)],
}
CHECK = {
    "hai-20.07": ["hai-20.07"],
    "hai-23.05": ["hai-23.05"],
    "batadal": ["batadal"],
    "hygrid-ics": ["hygrid-ics"],
    "voraus-ad": ["voraus-ad"],
    "tep-4-6": [f"tep-m{m}" for m in range(4, 7)],
    "provics": ["provics"],
}
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
        if (self.d / "fit_vlow.npy").exists():
            self.fit_vlow = np.load(self.d / "fit_vlow.npy")
            self.fit_vhigh = np.load(self.d / "fit_vhigh.npy")

    def streams(self, group):
        return [
            Stream(self.d, row["key"], self.spec, row)
            for row in self.meta["groups"].get(group, [])
        ]

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
        return (
            key != 0,
            valid,
            [(a, b, stream.row.get("type", 0), i) for i, (a, b, _) in enumerate(ev)],
        )
    if unit.name == "provics":
        import tt1d_data_v2 as TD2

        v = stream.load("valid", mmap=False)
        if (
            v is not None
        ):  # development segments carry no mask: they are cut at gaps, every step is valid
            valid = TD2.provics_valid_v2(
                v, unit.spec["window"]
            )  # the audit's extended mask
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
        raw = monitor.raw(
            unit, {k: (None if v is None else np.asarray(v[sl])) for k, v in a.items()}
        )
        out.append(float(np.nanmax(smooth(raw, unit.spec["window"]))))
        at += n
    return np.array(out)


def stream_score(unit, stream, monitor, valid=None):
    """Smoothed score as the rules see it: warm-up and invalid steps are -inf and cannot alarm."""
    a = stream.arrays()
    s = smooth(
        monitor.raw(
            unit, {k: (None if v is None else np.asarray(v)) for k, v in a.items()}
        ),
        unit.spec["window"],
    )
    ok = np.isfinite(s) if valid is None else np.isfinite(s) & valid
    return np.where(ok, s, -np.inf)


def calibrate_unit(unit, monitor):
    """Fit the monitor's normal-data statistics, then the threshold on the calibration split."""
    monitor.fit(unit)
    if unit.episodic:
        cal = episodic_scores(unit, unit.streams("calib")[0], monitor)
        return monitor.threshold_episodic(unit, cal) if hasattr(
            monitor, "threshold_episodic"
        ) else float(np.quantile(cal, 1 - unit.spec["alpha"])), cal
    cal = []
    for st in unit.streams("calib"):
        s = stream_score(unit, st, monitor)
        cal.append(s[np.isfinite(s)])
    if hasattr(monitor, "threshold"):
        return float(monitor.threshold(unit, cal)), cal
    return float(
        R2.calibrate(cal, unit.spec["gap"], unit.spec["budget"], unit.spec["spd"])
    ), cal


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


RANGE_MARGIN = 0.05  # round 1's descriptive definition (fi1_monitor_diagnose.regime)


def outside_range(unit, stream, sl=None):
    """Rule 5 of the plan's note (descriptive, the same for every monitor): a step is outside the fitted range
    when a scaled sensor lies more than 5 % of its fit span beyond the range of the world-model fit data."""
    Z = stream.load("Z")
    if Z is None:
        return None
    Z = np.asarray(Z if sl is None else Z[sl])
    span = np.maximum(unit.fit_high - unit.fit_low, 1e-6)
    return (
        (Z < unit.fit_low - RANGE_MARGIN * span)
        | (Z > unit.fit_high + RANGE_MARGIN * span)
    ).any(1)


def stream_rows(unit, stream, s, tau, lab, valid, events, rng, states=None):
    """Per-stream metrics. Single-score monitors: alarm = s > tau. Multi-state monitors (`states`, a list of
    normalised scores, state on where > 1): alarm time is the union; episodes are taken per state, an episode of
    any state starting inside an event is an onset, and every state's episodes outside events are false alarms
    (rule 4 of the plan's note)."""
    gap = unit.spec["gap"]
    if states is None:
        on = [s > tau]
    else:
        xs = [np.where(np.isnan(x), -np.inf, x) for x in states]
        on = [x > 1 for x in xs]
        s = np.max(np.stack(xs), 0)
        tau = 1.0
    alarm = np.logical_or.reduce(on)
    eps = [e for a in on for e in T._episodes(a, gap)]
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
    any_c, on_c = (
        _shift_counts(alarm, starts, events, rng)
        if events
        else (np.zeros(SHIFTS, int), np.zeros(SHIFTS, int))
    )
    ok = np.isfinite(s) & valid
    out = outside_range(unit, stream) if hasattr(stream, "load") else None
    if out is None:
        out = np.zeros(len(s), bool)
    desc = {
        "unlabelled_outside": int((out & unl).sum()),
        "unlabelled_inside_alarm": int((alarm & unl & ~out).sum()),
        "event_inside": [bool(not out[a]) for a, *_ in events],
    }
    return desc | {
        "found": found,
        "onset": onset,
        "delay": delay,
        "types": [e[2] for e in events],
        "order": [e[3] for e in events],
        "fa": int(sum(1 for a, b in eps if not lab[a:b].any())),
        "event_episodes": int(sum(1 for a, b in eps if lab[a:b].any())),
        "episode_seconds": [float(b - a) * unit.spec["step"] for a, b in eps],
        "labelled": int((lab & valid).sum()),
        "unlabelled": int(unl.sum()),
        "unlabelled_alarm": int((alarm & unl).sum()),
        "chance_any": any_c,
        "chance_onset": on_c,
        "ap_score": (s[ok] / tau).astype(np.float32),
        "ap_label": lab[ok],
    }


def _ci(x):
    return [float(np.quantile(x, 0.025)), float(np.quantile(x, 0.975))]


def pool(unit_rows, spec_budget, spd_of):
    """Pool stream rows of one dataset. unit_rows: [(unit, rows)]."""
    found = sum((r["found"] for _, rows in unit_rows for r in rows), [])
    onset = sum((r["onset"] for _, rows in unit_rows for r in rows), [])
    delay = [
        d for _, rows in unit_rows for r in rows for d in r["delay"] if d is not None
    ]
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
    out = {
        "events": n,
        "detected": int(sum(found)),
        "onset_detected": int(sum(onset)),
        "any_recall": float(np.mean(found)) if n else None,
        "onset_recall": float(np.mean(onset)) if n else None,
        "chance_any": {"mean": float(np.mean(ca)), "ci95": _ci(ca)} if n else None,
        "chance_onset": {"mean": float(np.mean(co)), "ci95": _ci(co)} if n else None,
        "unlabelled_alarm_share": unl_alarm / max(unl, 1),
        "fa_per_day": fa / max(unl_days, 1e-9),
        "fa_ratio_to_budget": fa / max(unl_days, 1e-9) / spec_budget,
        "average_precision": float(average_precision_score(y, sc))
        if 0 < y.sum() < len(y)
        else None,
        "median_seconds_to_first_alarm": float(np.median(delay)) if delay else None,
        "unlabelled_days": unl_days,
    }
    # added before the check run (coordinator request): onset net of chance and the episode structure
    lab_days = sum(r["labelled"] / spd_of[u] for u, rows in unit_rows for r in rows)
    ev_eps = sum(r["event_episodes"] for _, rows in unit_rows for r in rows)
    lengths = [x for _, rows in unit_rows for r in rows for x in r["episode_seconds"]]
    out |= {
        "chance_onset_recall": float(np.mean(co)) / n if n else None,
        "onset_recall_net_of_chance": (sum(onset) - float(np.mean(co))) / n
        if n
        else None,
        "episodes_per_unlabelled_day": fa / max(unl_days, 1e-9),
        "episodes_touching_events_per_labelled_day": ev_eps / max(lab_days, 1e-9),
        "episodes_touching_events": int(ev_eps),
        "labelled_days": lab_days,
        "median_episode_seconds": float(np.median(lengths)) if lengths else None,
        "alarm_episodes": len(lengths),
    }
    # rule 5 of the plan's note (descriptive): outside / inside the fitted range
    unl_out = sum(r.get("unlabelled_outside", 0) for _, rows in unit_rows for r in rows)
    unl_in_alarm = sum(
        r.get("unlabelled_inside_alarm", 0) for _, rows in unit_rows for r in rows
    )
    ev_in = sum((r.get("event_inside", []) for _, rows in unit_rows for r in rows), [])
    if len(ev_in) == n:
        n_in = int(sum(ev_in))
        out |= {
            "unlabelled_share_outside_range": unl_out / max(unl, 1),
            "alarm_share_inside_range": unl_in_alarm / max(unl - unl_out, 1),
            "events_starting_inside_range": n_in,
            "onset_recall_inside_range": float(
                sum(o for o, i in zip(onset, ev_in) if i) / n_in
            )
            if n_in
            else None,
        }
    if any(o > 0 for o in order):
        for name, keep in (
            ("first", [o == 0 for o in order]),
            ("follower", [o > 0 for o in order]),
        ):
            out[name] = {
                "events": int(sum(keep)),
                "detected": int(sum(f for f, k in zip(found, keep) if k)),
                "onset_detected": int(sum(f for f, k in zip(onset, keep) if k)),
                "onset_recall": float(np.mean([f for f, k in zip(onset, keep) if k]))
                if any(keep)
                else None,
            }
    return out


def _arrs(st, sl=None):
    return {
        k: (None if v is None else np.asarray(v if sl is None else v[sl]))
        for k, v in st.arrays().items()
    }


def _samples_of(st):
    lens = st.load("lengths", mmap=False)
    at = 0
    for n in lens:
        yield slice(at, at + n)
        at += n


def episodic_outside(unit, st):
    """Rule 5 for an episodic unit: a sample is outside the fitted range when any of its steps is."""
    out = []
    for sl in _samples_of(st):
        o = outside_range(unit, st, sl)
        out.append(bool(o.any()) if o is not None else False)
    return np.array(out)


def _episodic_row(unit, st, seq, tau, outside):
    flags = st.load("flags", mmap=False).astype(bool)
    alarm = seq > tau
    inn = ~outside
    return {
        "anomalous": int(flags.sum()),
        "detected": int(alarm[flags].sum()),
        "fpr": float(alarm[~flags].mean()),
        "fpr_ratio_to_target": float(alarm[~flags].mean() / unit.spec["alpha"]),
        "average_precision": float(
            average_precision_score(flags, np.maximum(seq, -1e300))
        ),
        "unlabelled_share_outside_range": float(outside[~flags].mean()),
        "alarm_share_inside_range": float(alarm[~flags & inn].mean())
        if (~flags & inn).any()
        else None,
        "events_starting_inside_range": int((flags & inn).sum()),
        "onset_recall_inside_range": float(alarm[flags & inn].mean())
        if (flags & inn).any()
        else None,
    }


def _states(unit, st, monitor, valid):
    xs = monitor.states(unit, _arrs(st), ~valid)
    return [np.where(np.isfinite(x) & valid, x, -np.inf) for x in xs]


def evaluate_unit_multi(unit, monitor):
    """A multi-state monitor (fi1_monitor_v4) calibrates itself on attack-free data in fit(); states are on > 1."""
    monitor.fit(unit)
    out = {"tau": 1.0}
    if unit.episodic:
        st = unit.streams("test")[0]
        seq = []
        for sl in _samples_of(st):
            xs = monitor.states(unit, _arrs(st, sl))
            seq.append(
                max(
                    float(np.nanmax(x)) if np.isfinite(x).any() else -np.inf for x in xs
                )
            )
        out["episodic"] = _episodic_row(
            unit, st, np.array(seq), 1.0, episodic_outside(unit, st)
        )
        return out, None, None
    rng = np.random.default_rng(SHIFT_SEED)
    rows = []
    for st in unit.streams("test"):
        lab, valid, events = labels_and_events(unit, st)
        xs = _states(unit, st, monitor, valid)
        rows.append(stream_rows(unit, st, None, None, lab, valid, events, rng, xs))
    sealed = []
    for st in unit.streams("sealed"):
        lab, valid, _ = labels_and_events(unit, st)
        on = [x > 1 for x in _states(unit, st, monitor, valid)]
        sealed.append(
            {
                "fa": sum(len(T._episodes(a, unit.spec["gap"])) for a in on),
                "steps": int(valid.sum()),
                "alarm": int(np.logical_or.reduce(on).sum()),
            }
        )
    return out, rows, sealed


def evaluate_unit(unit, monitor):
    """Calibrate on attack-free data, then score every test (and sealed) stream of the unit."""
    if getattr(monitor, "multistate", False):
        return evaluate_unit_multi(unit, monitor)
    tau, cal = calibrate_unit(unit, monitor)
    out = {"tau": tau}
    if unit.episodic:
        st = unit.streams("test")[0]
        seq = episodic_scores(unit, st, monitor)
        out["episodic"] = _episodic_row(unit, st, seq, tau, episodic_outside(unit, st))
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
        sealed.append(
            {
                "fa": len(T._episodes(alarm, unit.spec["gap"])),
                "steps": int(valid.sum()),
                "alarm": int(alarm.sum()),
            }
        )
    return out, rows, sealed


def evaluate_set(monitor_name, set_name, units_filter=None):
    import fi1_monitor_v4 as V  # plain round-1 names resolve to the same fi1_monitor_v3 objects

    datasets = SETS[set_name]
    result = {}
    for ds, units in datasets.items():
        if units_filter and ds not in units_filter:
            continue
        absent = [u for u in units if not (RESID / u / "meta.json").exists()]
        if absent:
            result[ds] = {"missing": True, "absent_units": absent}
            print(
                f"{monitor_name:24s} {ds:11s} MISSING (no complete residual cache for {absent})",
                flush=True,
            )
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
            row = {
                "events": e["anomalous"],
                "detected": e["detected"],
                "onset_detected": e["detected"],
                "any_recall": e["detected"] / e["anomalous"],
                "onset_recall": e["detected"] / e["anomalous"],
                "chance_any": None,
                "unlabelled_alarm_share": e["fpr"],
                "fa_per_day": None,
                "fa_ratio_to_budget": e["fpr_ratio_to_target"],
                "average_precision": e["average_precision"],
                "median_seconds_to_first_alarm": None,
                **{
                    k: e[k]
                    for k in (
                        "unlabelled_share_outside_range",
                        "alarm_share_inside_range",
                        "events_starting_inside_range",
                        "onset_recall_inside_range",
                    )
                },
                "note": "episodic: an event is an anomalous sample; onset = any-alarm = sample alarm; "
                "alarm share = false-positive rate of normal samples; budget = the 5 % sample target",
            }
        else:
            row = pool(unit_rows, budget, spd_of)
            if sealed_all:
                days = sum(r["steps"] / spd_of[u] for u, r in sealed_all)
                row["sealed_fa_ratio_to_budget"] = (
                    sum(r["fa"] for _, r in sealed_all) / days / budget
                )
                row["sealed_alarm_share"] = sum(
                    r["alarm"] for _, r in sealed_all
                ) / sum(r["steps"] for _, r in sealed_all)
        row["tau"] = taus
        row["seconds"] = round(time.time() - t0)
        result[ds] = row
        print(
            f"{monitor_name:24s} {ds:11s} onset {row['onset_detected']}/{row['events']} any {row['detected']}"
            f" share {row['unlabelled_alarm_share']:.4f} fa x{row['fa_ratio_to_budget']:.2f}"
            f" ap {row['average_precision'] if row['average_precision'] is None else round(row['average_precision'], 3)}"
            f" ({row['seconds']} s)",
            flush=True,
        )
    return result


def summary(result):
    result = {k: v for k, v in result.items() if not v.get("missing")}
    on = [
        v["onset_recall"] for v in result.values() if v.get("onset_recall") is not None
    ]
    sh = [v["unlabelled_alarm_share"] for v in result.values()]
    return {
        "mean_onset_recall": float(np.mean(on)),
        "mean_unlabelled_alarm_share": float(np.mean(sh)),
    }


def verdict(base, cand):
    """The plan's definition of improved, on the check set (datasets that ran; a missing one makes it partial)."""
    base = {k: v for k, v in base.items() if not v.get("missing")}
    cand = {k: v for k, v in cand.items() if k in base}
    sb, sc = summary(base), summary(cand)
    drops = {k: cand[k]["onset_recall"] - base[k]["onset_recall"] for k in base}
    ok = (
        sc["mean_onset_recall"] - sb["mean_onset_recall"] >= 0.05
        and sc["mean_unlabelled_alarm_share"] <= sb["mean_unlabelled_alarm_share"]
        and all(d >= -0.05 for d in drops.values())
    )
    pick = lambda d, k, f: d[k][f] if k in d else None
    return {
        "improved": bool(ok),
        "datasets": sorted(base),
        "mean_onset_recall_gain": sc["mean_onset_recall"] - sb["mean_onset_recall"],
        "mean_alarm_share_change": sc["mean_unlabelled_alarm_share"]
        - sb["mean_unlabelled_alarm_share"],
        "onset_recall_change_per_dataset": drops,
        "onset_net_of_chance_per_dataset": {
            k: [
                base[k].get("onset_recall_net_of_chance"),
                cand[k].get("onset_recall_net_of_chance"),
            ]
            for k in base
        },
        "alarm_share_hai_20_07": [
            pick(base, "hai-20.07", "unlabelled_alarm_share"),
            pick(cand, "hai-20.07", "unlabelled_alarm_share"),
        ],
        "alarm_share_provics": [
            pick(base, "provics", "unlabelled_alarm_share"),
            pick(cand, "provics", "unlabelled_alarm_share"),
        ],
    }


def survives_selection(base, cand):
    """The selection rule of docs/research/fi1_reports/monitor_round1.md (fixed before the full selection results)."""
    sb, sc = summary(base), summary(cand)
    drops = {k: cand[k]["onset_recall"] - base[k]["onset_recall"] for k in base}
    sealed = cand["tep-0-3"].get("sealed_fa_ratio_to_budget", 0.0)
    checks = {
        "mean_onset_gain_ge_0.02": sc["mean_onset_recall"] - sb["mean_onset_recall"]
        >= 0.02,
        "mean_share_not_higher": sc["mean_unlabelled_alarm_share"]
        <= sb["mean_unlabelled_alarm_share"],
        "no_dataset_loses_more_than_0.05": all(d >= -0.05 for d in drops.values()),
        "tep_sealed_fa_below_1.5_budget": sealed < 1.5,
    }
    return {
        "survives": all(checks.values()),
        "checks": checks,
        "mean_onset_recall": sc["mean_onset_recall"],
        "mean_unlabelled_alarm_share": sc["mean_unlabelled_alarm_share"],
        "mean_onset_gain": sc["mean_onset_recall"] - sb["mean_onset_recall"],
        "onset_change": drops,
        "tep_sealed_fa_ratio": sealed,
    }


def select(names):
    path = WORK / "results" / "selection_table.json"
    table = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for n in ["d1"] + [n for n in names if n != "d1"]:
        if n not in table:
            table[n] = evaluate_set(n, "selection")
            save(path, table)
    rows = {
        n: survives_selection(table["d1"], r) for n, r in table.items() if n != "d1"
    }
    rows = dict(sorted(rows.items(), key=lambda kv: -kv[1]["mean_onset_recall"]))
    sb = summary(table["d1"])
    print(
        f"baseline d1: mean onset {sb['mean_onset_recall']:.3f} mean share {sb['mean_unlabelled_alarm_share']:.4f}"
    )
    for n, r in rows.items():
        print(
            f"{n:22s} {'SURVIVES' if r['survives'] else 'out     '} mean onset {r['mean_onset_recall']:.3f} "
            f"({r['mean_onset_gain']:+.3f}) share {r['mean_unlabelled_alarm_share']:.4f} sealed x{r['tep_sealed_fa_ratio']:.2f} "
            + " ".join(f"{k} {v:+.3f}" for k, v in r["onset_change"].items())
        )
    save(
        WORK / "results" / "selection_verdicts.json",
        {"baseline": sb, "candidates": rows},
    )
    return rows


def _mean_net(result):
    v = [
        r["onset_recall_net_of_chance"]
        for r in result.values()
        if not r.get("missing") and r.get("onset_recall_net_of_chance") is not None
    ]
    return float(np.mean(v)) if v else None


def survives_selection_r2(base, cand):
    """The round-2 selection rule (docs/research/fi1_reports/monitor_round2.md, commit 60d8f91): round 1's four
    conditions and mean onset recall net of chance not below the baseline's."""
    r = survives_selection(base, cand)
    nb, nc = _mean_net(base), _mean_net(cand)
    r["checks"]["mean_net_of_chance_not_lower"] = nc >= nb
    r["survives"] = all(r["checks"].values())
    r["mean_onset_net_of_chance"] = nc
    r["mean_onset_net_gain"] = nc - nb
    return r


def select_r2(names):
    path = WORK / "results" / "selection_table_r2.json"
    table = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for n in ["d1"] + [n for n in names if n != "d1"]:
        if n not in table:
            table[n] = evaluate_set(n, "selection")
            save(path, table)
    rows = {
        n: survives_selection_r2(table["d1"], r) for n, r in table.items() if n != "d1"
    }
    rows = dict(
        sorted(
            rows.items(),
            key=lambda kv: (
                -kv[1]["mean_onset_net_of_chance"],
                kv[1]["mean_unlabelled_alarm_share"],
            ),
        )
    )
    sb = summary(table["d1"])
    print(
        f"baseline d1: mean onset {sb['mean_onset_recall']:.3f} net {_mean_net(table['d1']):.3f} "
        f"mean share {sb['mean_unlabelled_alarm_share']:.4f}"
    )
    for n, r in rows.items():
        tep = table[n]["tep-0-3"]
        print(
            f"{n:28s} {'SURVIVES' if r['survives'] else 'out     '} onset {r['mean_onset_recall']:.3f} "
            f"({r['mean_onset_gain']:+.3f}) net {r['mean_onset_net_of_chance']:.3f} ({r['mean_onset_net_gain']:+.3f}) "
            f"share {r['mean_unlabelled_alarm_share']:.4f} sealed x{r['tep_sealed_fa_ratio']:.2f} "
            f"tep first {tep['first']['onset_detected']}/{tep['first']['events']} "
            f"fol {tep['follower']['onset_detected']}/{tep['follower']['events']} "
            + " ".join(f"{k} {v:+.3f}" for k, v in r["onset_change"].items())
            + " | failed: "
            + ",".join(k for k, ok in r["checks"].items() if not ok)
        )
    save(
        WORK / "results" / "selection_verdicts_r2.json",
        {
            "baseline": sb | {"mean_onset_net_of_chance": _mean_net(table["d1"])},
            "candidates": rows,
        },
    )
    return rows


VERDICT_KEYS = ("onset_detected", "events", "onset_recall", "unlabelled_alarm_share")


def check_r2(names):
    """Round 2 on the check set: a second use (plan's note). Each candidate once (the ledger refuses a name it
    holds). The baseline d1 is not rerun as a candidate: its verdict numbers are round 1's stored ones; it is
    re-scored once under the ledger label 'd1 (round-2 re-score)' only to add the rule-5 descriptive numbers,
    and the run stops if its verdict numbers differ from round 1's."""
    done = set()
    if CHECK_LEDGER.exists():
        done = {
            json.loads(line)["monitor"]
            for line in CHECK_LEDGER.read_text(encoding="utf-8").splitlines()
            if line
        }
    again = [n for n in names if n in done or n == "d1"]
    if again:
        raise SystemExit(f"REFUSE: already run on the check set: {again}")
    if len(names) > 3:
        raise SystemExit("REFUSE: at most three round-2 candidates")
    r1 = json.loads((WORK / "results" / "check_table.json").read_text(encoding="utf-8"))
    base = r1["d1"]
    out_path = WORK / "results" / "check_table_r2.json"
    out = {}
    label = "d1 (round-2 re-score)"

    def ledger(n):
        with CHECK_LEDGER.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "monitor": n,
                        "round": 2,
                        "use": "second use of the check set",
                        "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "datasets": list(CHECK),
                    }
                )
                + "\n"
            )

    if label not in done:
        ledger(label)
        out["d1"] = evaluate_set("d1", "check")
        for ds, row in out["d1"].items():
            for k in VERDICT_KEYS:
                if not np.isclose(row[k], base[ds][k]):
                    raise SystemExit(
                        f"STOP: baseline re-score differs from round 1 on {ds} {k}: {row[k]} vs {base[ds][k]}"
                    )
        save(out_path, out)
    for n in names:
        ledger(n)
        out[n] = evaluate_set(n, "check")
        save(out_path, out)
    verdicts = {n: verdict(base, out[n]) for n in names}
    for n, v in verdicts.items():
        print(
            n,
            "IMPROVED" if v["improved"] else "not improved",
            json.dumps(v, default=float),
        )
    save(
        WORK / "results" / "check_verdicts_r2.json",
        {"baseline": summary(base), "verdicts": verdicts},
    )


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
                rows.append(
                    stream_rows(
                        unit,
                        _CachedStream(len(s), {}),
                        s,
                        cfg["tau0"],
                        key != 0,
                        np.ones(len(s), bool),
                        events,
                        rng,
                    )
                )
            elif k.startswith("sealed::"):
                s = z[k]
                sealed.append(
                    (unit.name, len(T._episodes(s > cfg["tau0"], spec["gap"])), len(s))
                )
        unit_rows.append((unit.name, rows))
        spd_of[unit.name] = spec["spd"]
    row = pool(unit_rows, spec["budget"], spd_of)
    days = sum(n / spec["spd"] for _, _, n in sealed)
    row["sealed_fa_ratio_to_budget"] = (
        sum(f for _, f, _ in sealed) / days / spec["budget"]
    )
    return row


# Registered (or registered-pipeline exploratory) numbers of the frozen D1 rule, with their source files.
REGISTERED = {
    "hai-21.03": {
        "src": "threshold_transfer_tt1c_dev_v1.json natural (exploratory, tt1-final split)",
        "events": 50,
        "detected": 50,
        "onset_detected": 49,
        "unlabelled_alarm_share": 0.007571,
        "fa_per_day": 0.6594,
    },
    "hai-22.04": {
        "src": "threshold_transfer_tt1c_dev_v1.json natural (exploratory, tt1-final split)",
        "events": 58,
        "detected": 44,
        "onset_detected": 44,
        "unlabelled_alarm_share": 0.002744,
        "fa_per_day": 1.4847,
    },
    "hai-23.05": {
        "src": "threshold_transfer_tt1c_dev_v1.json natural (exploratory, tt1-final split)",
        "events": 52,
        "detected": 31,
        "onset_detected": 31,
        "unlabelled_alarm_share": 0.007113,
        "fa_per_day": 1.2659,
    },
    "hai-20.07": {
        "src": "threshold_transfer_tt1_result_hai-20.07.json (registered) + tt1_posthoc_alarm_time.json",
        "tau": 17.25877,
        "events": 38,
        "detected": 36,
        "onset_detected": 26,
        "unlabelled_alarm_share": 0.39096,
        "fa_per_day": 2.2254,
    },
    "hygrid-ics": {
        "src": "threshold_transfer_tt1_result_hygrid-ics.json (registered) + tt1_posthoc_alarm_time.json",
        "tau": 4.75370,
        "events": 91,
        "detected": 27,
        "onset_detected": 3,
        "unlabelled_alarm_share": 0.04067,
        "fa_per_day": 19.202,
    },
    "batadal": {
        "src": "threshold_transfer_tt1b_result_batadal.json (registered) + tt1_posthoc_alarm_time.json",
        "tau": 9.39328,
        "events": 14,
        "detected": 14,
        "onset_detected": 14,
        "unlabelled_alarm_share": 0.013685,
        "fa_ratio_to_budget": 0.7012,
    },
    "voraus-ad": {
        "src": "threshold_transfer_tt1_result_voraus-ad.json (registered)",
        "tau": 9.77571,
        "events": 755,
        "detected": 252,
        "unlabelled_alarm_share": 0.081146,
    },
    "provics": {
        "src": "threshold_transfer_tt1f_provics_mask_v1.json, extended mask (registered mask: 25 / onset 4 / 0.4411)",
        "tau": 3.95370,
        "events": 32,
        "detected": 23,
        "onset_detected": 3,
        "unlabelled_alarm_share": 0.43989,
        "fa_ratio_to_budget": 33.705,
    },
    "tep-0-3": {
        "src": "threshold_transfer_tt1d_result_tep59.json units mode_0..3 (registered)"
    },
    "tep-4-6": {
        "src": "threshold_transfer_tt1d_result_tep59.json units mode_4..6 (registered)"
    },
}


def registered_tep(modes):
    """Registered frozen-rule counts for a subset of Tennessee Eastman modes, from the per-unit records."""
    d = json.loads(
        (ROOT / "docs/research/threshold_transfer_tt1d_result_tep59.json").read_text(
            encoding="utf-8"
        )
    )
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
            found += sum(v["found"])
            onset += sum(v["onset"])
            n += len(v["found"])
            first[0] += int(v["found"][0]) if v["found"] else 0
            first[1] += 1 if v["found"] else 0
            fa += v["fa"]
            alarm += v["alarm_unlabelled"]
            unl += run["unlabelled_steps"]
        for run in u["sealed_runs"]:
            sealed_fa += run["false_alarms"]["frozen"]["fa"]
            sealed_steps += run["steps"]
    return {
        "tau": taus,
        "events": n,
        "detected": found,
        "onset_detected": onset,
        "first_detected": first[0],
        "first_events": first[1],
        "unlabelled_alarm_share": alarm / unl,
        "fa_ratio_to_budget": fa / (unl / 24000) / 2,
        "sealed_fa_ratio_to_budget": sealed_fa / (sealed_steps / 24000) / 2,
    }


def main():
    cmd = sys.argv[1]
    if cmd == "registered":
        REGISTERED["tep-0-3"] |= registered_tep(range(4))
        REGISTERED["tep-4-6"] |= registered_tep(range(4, 7))
        print(json.dumps(REGISTERED, indent=1))
        save(WORK / "results" / "registered.json", REGISTERED)
    elif cmd == "select":
        select(sys.argv[2:])
    elif cmd == "select2":
        select_r2(sys.argv[2:])
    elif cmd == "check2":
        check_r2(sys.argv[2:])
    elif cmd == "check":
        # baseline and the survivors of selection, once each on the check set; a monitor already in the
        # check ledger is refused (no second look)
        done = set()
        if CHECK_LEDGER.exists():
            done = {
                json.loads(line)["monitor"]
                for line in CHECK_LEDGER.read_text(encoding="utf-8").splitlines()
                if line
            }
        names = ["d1"] + [n for n in sys.argv[2:] if n != "d1"]
        again = [n for n in names if n in done]
        if again:
            raise SystemExit(f"REFUSE: already run on the check set: {again}")
        out = {}
        for n in names:
            with CHECK_LEDGER.open("a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "monitor": n,
                            "at": datetime.datetime.now(
                                datetime.timezone.utc
                            ).isoformat(),
                            "datasets": list(CHECK),
                        }
                    )
                    + "\n"
                )
            out[n] = evaluate_set(n, "check")
            save(WORK / "results" / "check_table.json", out)
        verdicts = {n: verdict(out["d1"], r) for n, r in out.items() if n != "d1"}
        for n, v in verdicts.items():
            print(
                n,
                "IMPROVED" if v["improved"] else "not improved",
                json.dumps(v, default=float),
            )
        save(
            WORK / "results" / "check_verdicts.json",
            {"baseline": summary(out["d1"]), "verdicts": verdicts},
        )
    elif cmd == "tep-cache":
        row = reproduce_tep_cache()
        print(
            json.dumps(
                {k: v for k, v in row.items() if k not in ("chance_onset",)},
                indent=1,
                default=float,
            )
        )
        save(WORK / "results" / "reproduce_tep_cache.json", row)
    elif cmd == "run":
        name, set_name = sys.argv[2], sys.argv[3]
        only = sys.argv[4:] or None
        if set_name == "check":
            with CHECK_LEDGER.open("a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "monitor": name,
                            "at": datetime.datetime.now(
                                datetime.timezone.utc
                            ).isoformat(),
                            "datasets": only or list(CHECK),
                        }
                    )
                    + "\n"
                )
        res = evaluate_set(name, set_name, only)
        tag = "_".join(only) if only else "all"
        save(
            WORK / "results" / f"{set_name}_{name}_{tag}.json",
            {"monitor": name, "set": set_name, "datasets": res},
        )
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
