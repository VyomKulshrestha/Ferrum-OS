#!/usr/bin/env python3
"""tw1b (exploratory): the SPOT authors' script on whole series. Plan: thresholds_in_the_wild_tw1a_dev_plan.md,
amendment 4, section 3.

The script (`spot.py`, class SPOT) is loaded unchanged from a copy in an empty directory (TW1B_SPOT, default
target/tw1b_spot_src/spot.py) and is only ever used as its authors use it: one object per series,
`fit(init_data, data)`, `initialize()`, `run(with_alarm=True)`. The one exception is the frog planner, which
is the attacker's model: it steps an object of the script's class with the script's own `_grimshaw` and
`_quantile`, and the script's run on the planned series must return the same thresholds.

Run with the tw1 environment, `python -I`:

    tw1b_spot_authors.py campaigns <m> <full|young>   control and loud pulses on every placement of a mode
    tw1b_spot_authors.py attacks <m> <full|young>     the recorded attack runs of a mode
    tw1b_spot_authors.py frog <m>                     the planned 3% frog, first placement, young history

Parts go to target/tw1/tw1b/spot/ and are written after every placement or run, so a restart resumes.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import time
from pathlib import Path

os.environ.setdefault(
    "TQDM_DISABLE", "1"
)  # the script draws a progress bar on every run
os.environ.setdefault(
    "MPLBACKEND", "Agg"
)  # the script imports pyplot; nothing is plotted

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import repro_env
import tw1a_score_level_dev as T
import tw1b_score_level_dev as B

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(os.environ.get("TW1B_SPOT", ROOT / "target/tw1b_spot_src/spot.py"))
OUT = ROOT / "target/tw1/tw1b/spot"
Q = 1e-4  # README examples for SPOT and the constructor default
NAME = (
    "SPOT authors' spot.py SPOT(q=1e-4), initialize(level=0.98), run(with_alarm=True)"
)
_MOD = None


def module():
    global _MOD
    if _MOD is None:
        spec = importlib.util.spec_from_file_location("spot_authors", SCRIPT)
        _MOD = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_MOD)
    return _MOD


def finite(xs):
    xs = np.asarray(xs, dtype=float)
    keep = np.isfinite(xs)
    return xs[keep], np.flatnonzero(keep)


def run_script(init, data):
    """One whole-series run, as the authors run it. Returns (alarm mask, thresholds) over `data`; the
    threshold at i is the one after step i, so step i is judged against the threshold at i - 1."""
    init, _ = finite(init)
    xs, where = finite(data)
    s = module().SPOT(Q)
    s.fit(init, xs)
    s.initialize(verbose=False)
    r = s.run(with_alarm=True)
    alarm = np.zeros(len(data), bool)
    alarm[where[np.asarray(r["alarms"], dtype=int)]] = True
    th = np.full(len(data), np.nan)
    th[where] = r["thresholds"]
    # a dropped score leaves the threshold unchanged
    for i in range(1, len(th)):
        if not np.isfinite(th[i]):
            th[i] = th[i - 1]
    return alarm, th


def initial_threshold(init):
    """The script's threshold before the first step of a stream: after initialize(), before run()."""
    init, _ = finite(init)
    s = module().SPOT(Q)
    s.fit(init, np.zeros(1))
    s.initialize(verbose=False)
    return float(s.extreme_quantile), s


def history(mode, which, z):
    pooled = z["pooled"]
    return pooled if which == "full" else pooled[-T.YOUNG :]


def load(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def terminal_hits(init, prefix, terminal_raw, th_before, K, tau0):
    """Hits per magnitude: caught on the first terminal step by the script's comparison against the threshold
    it reports for the step before, otherwise by a whole-series run of prefix + raised terminal."""
    hits, how = [], []
    for mag in K["mags"]:
        raised = np.maximum(terminal_raw, mag * tau0)
        first = raised[0]
        if math.isfinite(first) and first > th_before:
            hits.append(True)
            how.append("first step")
            continue
        alarm, _ = run_script(init, np.concatenate([prefix, raised]))
        hits.append(bool(alarm[len(prefix) :].any()))
        how.append("run")
    return hits, how


def campaigns(mode, which):
    S = B.setup()
    K, M = S["constants"], S["modes"][str(mode)]
    z = np.load(B.CACHE / f"mode_{mode}.npz")
    tau0, init = M["tau0"], history(mode, which, z)
    path = OUT / f"campaigns_mode{mode}_{which}.json"
    out = load(path) or {
        "target": NAME,
        "script_sha256": sha(SCRIPT),
        "mode": mode,
        "history": which,
        "tau0": tau0,
        "sealed": [],
    }
    done = {c["name"] for c in out["sealed"]}
    th0, _ = initial_threshold(init)
    out["reading_after_history"] = th0 / tau0
    for run_ in M["sealed"]:
        if run_["name"] in done:
            continue
        t0 = time.time()
        s, end = z["sealed::" + run_["name"]], run_["terminal_start"]
        c_start, c_end = end - K["lead"] - K["campaign"], end - K["lead"]
        cell = {"name": run_["name"], "campaigns": {}}
        for c in ("control", "loud"):
            stream = np.array(s[c_start : end + K["terminal"]], dtype=float)
            injected = 0.0
            if c == "loud":
                for k in range(K["campaign"]):
                    if k % K["loud"][0] < K["loud"][1]:
                        lift = K["loud"][2] * tau0
                        if lift > stream[k]:
                            stream[k], injected = lift, max(injected, lift)
            alarm, th = run_script(init, stream)
            n_c, n_l = K["campaign"], K["lead"]
            during = alarm[:n_c]
            prev0 = th[
                n_c - 1
            ]  # threshold judged against at the first lead-0 terminal step
            prev = th[n_c + n_l - 1]
            hits0, how0 = terminal_hits(
                init,
                stream[:n_c],
                np.array(s[c_end : c_end + K["terminal"]], dtype=float),
                prev0,
                K,
                tau0,
            )
            hits, how = terminal_hits(
                init, stream[: n_c + n_l], stream[n_c + n_l :], prev, K, tau0
            )
            res = {
                "largest_injected_over_tau0": injected / tau0,
                "alarm_steps": int(during.sum()),
                "alarm_episodes": len(T.episodes(during, K["gap"])),
                "reading_at_campaign_end": float(prev0 / tau0),
                "reading_at_terminal": float(prev / tau0),
                "hits_lead0": hits0,
                "hits": hits,
                "how_lead0": how0,
                "how": how,
                "max_reading_over_tau0": float(np.nanmax(th[: n_c + n_l]) / tau0),
            }
            if c == "control":
                cell["false_alarm_episodes"] = len(T.episodes(alarm, K["gap"]))
                cell["alarm_share"] = float(alarm.mean())
                cell["steps"] = int(len(alarm))
            cell["campaigns"][c] = res
        cell["seconds"] = round(time.time() - t0)
        out["sealed"].append(cell)
        B.write(path, out)
        print(
            f"spot campaigns mode {mode} {which} {run_['name']}: {cell['seconds']} s",
            flush=True,
        )
    out["status"] = "run"
    B.write(path, out)


def attacks(mode, which):
    S = B.setup()
    K, M = S["constants"], S["modes"][str(mode)]
    z = np.load(B.CACHE / f"mode_{mode}.npz")
    tau0, init = M["tau0"], history(mode, which, z)
    path = OUT / f"attacks_mode{mode}_{which}.json"
    out = load(path) or {
        "target": NAME,
        "script_sha256": sha(SCRIPT),
        "mode": mode,
        "history": which,
        "tau0": tau0,
        "attack": [],
    }
    done = {a["name"] for a in out["attack"]}
    for run_ in M["attack"]:
        if run_["name"] in done:
            continue
        t0 = time.time()
        s = z["attack::" + run_["name"]]
        alarm, th = run_script(init, s)
        row = B.attack_row(alarm, run_, mode, NAME, K)
        row["max_reading_over_tau0"] = float(np.nanmax(th) / tau0)
        row["seconds"] = round(time.time() - t0)
        out["attack"].append(row)
        B.write(path, out)
        print(
            f"spot attacks mode {mode} {which} {run_['name']}: {row['seconds']} s",
            flush=True,
        )
    out["status"] = "run"
    B.write(path, out)


class Planner:
    """The attacker's model of the script: an object of the script's class, stepped with the body of its
    `run()` loop for with_alarm=True (alarm: nothing learned; peak: append, refit; otherwise n += 1)."""

    def __init__(self, init):
        _, self.s = initial_threshold(init)

    def step(self, x):
        s = self.s
        if x > s.extreme_quantile:
            return True
        if x > s.init_threshold:
            s.peaks = np.append(s.peaks, x - s.init_threshold)
            s.Nt += 1
            s.n += 1
            g, sg, _ = s._grimshaw()
            s.extreme_quantile = s._quantile(g, sg)
        else:
            s.n += 1
        return False


def frog(mode, frac=0.97):
    S = B.setup()
    K, M = S["constants"], S["modes"][str(mode)]
    z = np.load(B.CACHE / f"mode_{mode}.npz")
    tau0, init = M["tau0"], history(mode, "young", z)
    path = OUT / f"frog_mode{mode}_young.json"
    if path.exists():
        print("exists", path)
        return
    run_ = M["sealed"][0]
    s, end = z["sealed::" + run_["name"]], run_["terminal_start"]
    c_start = end - K["lead"] - K["campaign"]
    n_c, n_l, cap = K["campaign"], K["lead"], K["loud"][2] * tau0
    t0 = time.time()
    p = Planner(init)
    stream = np.array(s[c_start : end + K["terminal"]], dtype=float)
    planned_th, injected = [], 0.0
    for k in range(len(stream)):
        x = stream[k]
        if k < n_c and math.isfinite(x):
            lift = min(frac * p.s.extreme_quantile, cap)
            if lift > x:
                stream[k], injected = lift, max(injected, lift)
        if math.isfinite(stream[k]):
            p.step(float(stream[k]))
        planned_th.append(p.s.extreme_quantile)
        if k == n_c + n_l - 1:
            at_terminal = (p.s.peaks.copy(), p.s.Nt, p.s.n, p.s.extreme_quantile)
    plan_seconds = round(time.time() - t0)
    print(f"frog mode {mode}: planned in {plan_seconds} s", flush=True)
    # the attacker's terminal outcome per magnitude, from the planner state after the lead
    planner_hits = []
    for mag in K["mags"]:
        q = Planner(init)
        q.s.peaks, q.s.Nt, q.s.n, q.s.extreme_quantile = (
            at_terminal[0].copy(),
            at_terminal[1],
            at_terminal[2],
            at_terminal[3],
        )
        planner_hits.append(
            any(
                q.step(float(max(x, mag * tau0)))
                for x in s[end : end + K["terminal"]]
                if math.isfinite(x)
            )
        )
    t1 = time.time()
    alarm, th = run_script(init, stream)
    planned = np.array(planned_th)
    equal = bool(np.array_equal(planned, th))
    worst = float(np.nanmax(np.abs(planned - th) / np.abs(th)))
    # the script itself on the largest magnitude, after the lead
    prefix, term = (
        stream[: n_c + n_l],
        np.maximum(
            np.array(s[end : end + K["terminal"]], dtype=float), K["mags"][-1] * tau0
        ),
    )
    a2, _ = run_script(init, np.concatenate([prefix, term]))
    out = {
        "target": NAME,
        "script_sha256": sha(SCRIPT),
        "mode": mode,
        "history": "young",
        "placement": run_["name"],
        "frog_fraction": frac,
        "tau0": tau0,
        "trajectory_equal": equal,
        "largest_relative_difference": worst,
        "reading_after_history": planned_th[0] / tau0 if planned_th else None,
        "reading_at_campaign_end": float(th[n_c - 1] / tau0),
        "reading_at_terminal": float(th[n_c + n_l - 1] / tau0),
        "reading_quarter_days": [float(th[i] / tau0) for i in range(0, n_c, n_c // 4)],
        "largest_injected_over_tau0": injected / tau0,
        "alarm_steps": int(alarm[:n_c].sum()),
        "planner_hits_after_lead": planner_hits,
        "script_hit_after_lead_at_2tau0": bool(a2[len(prefix) :].any()),
        "plan_seconds": plan_seconds,
        "script_seconds": round(time.time() - t1),
        "status": "run"
        if equal
        else "stopped: script thresholds differ from the planned ones",
    }
    B.write(path, out)
    print(
        f"frog mode {mode}: {out['status']} end {out['reading_at_campaign_end']:.2f} tau0",
        flush=True,
    )


def merge():
    """Totals of the script's parts per history, and the round's combined summary target/tw1/tw1b_summary.json."""
    K = B.setup()["constants"]
    zero = {k: 0 for k in ("checked", "in_band", "probes", "skipped_not_finite")}
    out = {"target": NAME, "histories": {}, "frog": []}
    for which in ("full", "young"):
        camp = [load(OUT / f"campaigns_mode{m}_{which}.json") for m in range(7)]
        att = [load(OUT / f"attacks_mode{m}_{which}.json") for m in range(7)]
        rows = [
            dict(c, parameter=Q, consistency=zero, attack=[])
            for c in camp
            if c and c.get("status") == "run"
        ]
        entry = B.summarise(rows, K, ("control", "loud")) if rows else {}
        entry["campaign_modes"] = [c["mode"] for c in rows]
        done = [a for a in att if a and a.get("status") == "run"]
        attack = [r for a in done for r in a["attack"]]
        if attack:
            first = [(r["found"][0], r["onset"][0]) for r in attack if r["found"]]
            foll = [
                (f, o) for r in attack for f, o in zip(r["found"][1:], r["onset"][1:])
            ]
            entry.update(
                attack_modes=[a["mode"] for a in done],
                first={
                    "events": len(first),
                    "detected": sum(f for f, _ in first),
                    "onset": sum(o for _, o in first),
                },
                follower={
                    "events": len(foll),
                    "detected": sum(f for f, _ in foll),
                    "onset": sum(o for _, o in foll),
                },
                chance_detected=float(sum(r["chance_found"] for r in attack)),
                alarm_share_unlabelled=sum(r["alarm_unlabelled"] for r in attack)
                / max(1, sum(r["unlabelled_steps"] for r in attack)),
                median_max_reading_over_tau0=float(
                    np.median([r["max_reading_over_tau0"] for r in attack])
                ),
            )
        out["histories"][which] = entry
    for m in range(7):
        f = load(OUT / f"frog_mode{m}_young.json")
        if f:
            out["frog"].append(f)
    path = ROOT / "target/tw1/tw1b_summary_spot.json"
    path.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    repro_env.stamp_json(path)
    combined = {
        "status": "exploratory (tw1b); Tennessee Eastman score cache; no dataset opened",
        "plan": "docs/research/thresholds_in_the_wild_tw1a_dev_plan.md, amendment 4 and its note",
        "score_level": load(ROOT / "target/tw1/tw1b_summary_score.json"),
        "spot_authors_script": out,
    }
    path = ROOT / "target/tw1/tw1b_summary.json"
    path.write_text(json.dumps(combined, indent=1) + "\n", encoding="utf-8")
    repro_env.stamp_json(path)
    print("written", path)


def sha(path):
    import hashlib

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


if __name__ == "__main__":
    repro_env.pin_from_environment()
    cmd, args = (sys.argv[1] if len(sys.argv) > 1 else ""), sys.argv[2:]
    if cmd == "campaigns":
        campaigns(int(args[0]), args[1])
    elif cmd == "attacks":
        attacks(int(args[0]), args[1])
    elif cmd == "frog":
        frog(int(args[0]))
    elif cmd == "merge":
        merge()
    else:
        raise SystemExit(__doc__)
