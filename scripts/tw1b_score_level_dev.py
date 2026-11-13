#!/usr/bin/env python3
"""tw1b (exploratory): configuration B and the frog closer to the reading, on the tw1a harness.
Plan: docs/research/thresholds_in_the_wild_tw1a_dev_plan.md, amendment 4. No dataset is opened; the
score cache of the tt1f round is replayed (TW1_CACHE, default the tt1 worktree's cache).

Run with the tw1 environment (river, PySAD, libspot), `python -I`:

    tw1b_score_level_dev.py harness <m> <full|young>        river ThresholdFilter(tau0) with the current code
    tw1b_score_level_dev.py calib <m> <key>                 configuration B parameter of one target
    tw1b_score_level_dev.py run <D|B> <m> <full|young> <key>  one target, one mode, one history
    tw1b_score_level_dev.py merge                           summary -> target/tw1/tw1b_summary_score.json

Every command writes its own part file under target/tw1/tw1b/ and skips work whose part already exists,
so a batch can be restarted. Result files are not committed (disclosure rule of the catalogue plan).
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import repro_env
import tw1_adapters as A
import tw1a_score_level_dev as T

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path(
    os.environ.get(
        "TW1_CACHE",
        r"C:\Users\marcu\Videos\cursor-os-base-tt1\target\real-telemetry\tt1f",
    )
)
OUT = ROOT / "target/tw1/tw1b"
T.CACHE = CACHE

# campaign name -> (tw1a campaign, frog fraction)
CAMPAIGNS = {
    "control": ("control", None),
    "loud": ("loud", None),
    "subl_cap": ("subl_cap", None),
    "frog_cap": ("frog_cap", 0.97),
    "frog_cap_98": ("frog_cap", 0.98),
    "frog_cap_99": ("frog_cap", 0.99),
    "frog_cap_995": ("frog_cap", 0.995),
}
FROGS = ("frog_cap", "frog_cap_98", "frog_cap_99", "frog_cap_995")
PLAN = {
    "D": {"campaigns": ("control",) + FROGS, "attacks": False},
    "B": {"campaigns": ("control", "loud", "subl_cap") + FROGS, "attacks": True},
}
BISECT_HALVINGS = 12


def _named(t, label):
    t.name = label
    return t


# key -> (documented parameter, parameter of u, u range, constructor of (tau0, parameter))
TARGETS = {
    "river_tf": (None, None, None, lambda tau0, p: A.RiverThreshold(tau0)),
    "river_q": (
        0.95,
        lambda u: 1 - 10.0**-u,
        (0.3, 7.0),
        lambda tau0, p: _named(A.RiverQuantile(p), f"river QuantileFilter(q={p!r})"),
    ),
    "pysad_q": (
        0.99,
        lambda u: 1 - 10.0**-u,
        (0.3, 7.0),
        lambda tau0, p: _named(A.PysadQuantile(p), f"PySAD QuantileFilter(q={p!r})"),
    ),
    "conformal": (
        0.99,
        lambda u: 1 - 10.0**-u,
        (0.3, 3.0),
        lambda tau0, p: _named(
            A.PysadConformal(1000, p),
            f"PySAD ConformalProbabilityCalibrator(window_size=1000) >= {p!r}",
        ),
    ),
    "gauss": (
        0.99,
        lambda u: 1 - 10.0**-u,
        (1.0, 15.0),
        lambda tau0, p: _named(
            A.PysadGaussian(1000, p),
            f"PySAD GaussianTailProbabilityCalibrator(window_size=1000) >= {p!r}",
        ),
    ),
    "likelihood": (
        1 - 1e-5,
        lambda u: 1 - 10.0**-u,
        (1.0, 15.0),
        lambda tau0, p: _named(
            A.PysadLikelihood(p),
            f"PySAD AnomalyLikelihoodProbabilityCalibrator() >= {p!r}",
        ),
    ),
    "pysad_spot": (
        1e-3,
        lambda u: 10.0**-u,
        (1.7, 10.0),
        lambda tau0, p: A.PysadSpot(p, 500),
    ),
    "libspot": (
        1e-4,
        lambda u: 10.0**-u,
        (2.7, 12.0),
        lambda tau0, p: A.LibSpot(p, 1000),
    ),
}
CALIBRATED = tuple(k for k, v in TARGETS.items() if v[1] is not None)


def setup():
    return T.SETUP or json.loads(
        (ROOT / "target/tw1/tep_setup.json").read_text(encoding="utf-8")
    )


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)
    repro_env.stamp_json(path)


def new_stats():
    return {
        "checked": 0,
        "in_band": 0,
        "largest_in_band": 0.0,
        "probes": 0,
        "skipped_not_finite": 0,
    }


# ------------------------------------------------------------------ harness check
def harness(mode, history):
    """tw1a's own run_mode, restricted to river ThresholdFilter, with the current code."""
    T.OUT = OUT / "harness"
    part = T.OUT / f"tw1a_mode{mode}_{history}.json"
    if part.exists():
        print("exists", part)
        return
    T.run_mode(mode, history, only="ThresholdFilter")


# ------------------------------------------------------------------ configuration B
def budget_episodes(make, pooled, K):
    """Alarm episodes over a second pass of the calibration runs, after one pass (amendment 1, item 8)."""
    t = make()
    xs = [float(x) for x in pooled if math.isfinite(x)]
    for x in xs:
        t.step(x)
    alarm = np.fromiter((t.step(x) for x in xs), bool, len(xs))
    return len(T.episodes(alarm, K["gap"])), len(xs)


def search(meets, lo, hi, halvings=BISECT_HALVINGS):
    """The most sensitive u in [lo, hi] (low u = sensitive) whose setting meets the budget, by bisection.
    Returns (u, reachable); when even `hi` exceeds the budget, (hi, False)."""
    if not meets(hi):
        return hi, False
    if meets(lo):
        return lo, True
    a, b = lo, hi  # a exceeds, b meets
    for _ in range(halvings):
        mid = round(0.5 * (a + b), 10)
        if meets(mid):
            b = mid
        else:
            a = mid
    return b, True


def calib(mode, key):
    path = OUT / "calib" / f"mode{mode}_{key}.json"
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if state.get("chosen") is not None:
        print("exists", path)
        return
    S = setup()
    K, M = S["constants"], S["modes"][str(mode)]
    pooled = np.load(CACHE / f"mode_{mode}.npz")["pooled"]
    _, param, (lo, hi), make = TARGETS[key]
    tau0 = M["tau0"]
    evals = {float(e["u"]): e for e in state.get("evaluations", [])}

    def evaluate(u):
        if u in evals:
            return evals[u]["meets"]
        t0, p = time.time(), param(u)
        try:
            n_ep, n = budget_episodes(lambda: make(tau0, p), pooled, K)
            limit = K["budget"] * n / K["spd"]
            e = {
                "u": u,
                "parameter": p,
                "episodes": n_ep,
                "limit": limit,
                "meets": n_ep <= limit,
            }
        except (
            Exception
        ) as exc:  # a setting the library refuses counts as over budget (amendment 4)
            e = {"u": u, "parameter": p, "refused": repr(exc)[:300], "meets": False}
        e["seconds"] = round(time.time() - t0)
        evals[u] = e
        state["evaluations"] = sorted(evals.values(), key=lambda d: d["u"])
        write(path, dict(state, mode=mode, target=key, tau0=tau0))
        print(
            f"mode {mode} {key}: u={u:.4f} p={p!r} {e.get('episodes', e.get('refused'))} meets={e['meets']} {e['seconds']} s",
            flush=True,
        )
        return e["meets"]

    chosen_u, reachable = search(evaluate, lo, hi)
    state.update(chosen_u=chosen_u, reachable=reachable)
    state["chosen"] = param(state["chosen_u"])
    state["chosen_episodes"] = evals[state["chosen_u"]].get("episodes")
    write(path, dict(state, mode=mode, target=key, tau0=tau0))
    print("chosen", key, mode, state["chosen"], flush=True)


def parameter(cfg, mode, key):
    doc = TARGETS[key][0]
    if cfg == "D" or TARGETS[key][1] is None:
        return doc
    path = OUT / "calib" / f"mode{mode}_{key}.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("chosen") is None:
        raise SystemExit(f"configuration B of {key} in mode {mode} not calibrated yet")
    return state["chosen"]


# ------------------------------------------------------------------ one part
def run(cfg, mode, history, key):
    part = OUT / "parts" / f"{cfg}_mode{mode}_{history}_{key}.json"
    if part.exists():
        print("exists", part)
        return
    S = setup()
    K, M = S["constants"], S["modes"][str(mode)]
    z = np.load(CACHE / f"mode_{mode}.npz")
    tau0, pooled = M["tau0"], z["pooled"]
    hist = pooled if history == "full" else pooled[-T.YOUNG :]
    p = parameter(cfg, mode, key)
    make = TARGETS[key][3]
    warm = make(tau0, p)
    plan = PLAN[cfg]
    t0, stats = time.time(), new_stats()
    row = {
        "config": cfg,
        "mode": mode,
        "history": history,
        "history_steps": int(len(hist)),
        "tau0": tau0,
        "key": key,
        "name": warm.name,
        "parameter": p,
        "doc": warm.doc,
        "closed_loop": warm.closed_loop,
        "versions": A.versions(),
        "sealed": [],
        "attack": [],
    }
    try:
        hist_alarm = T.feed(warm, hist, stats)
        row["history_alarm_share"] = float(hist_alarm.mean())
        row["reading_after_history"] = T.reading(warm, tau0)
        for run_ in M["sealed"]:
            s, end = z["sealed::" + run_["name"]], run_["terminal_start"]
            c_start = end - K["lead"] - K["campaign"]
            t = warm.clone()
            before = T.feed(t, s[:c_start], stats)
            cell = {"name": run_["name"], "campaigns": {}}
            for c in plan["campaigns"]:
                base, frac = CAMPAIGNS[c]
                if not warm.closed_loop and base not in ("control", "loud"):
                    continue
                Kc = dict(K, frog_frac=frac) if frac is not None else K
                u = t.clone()
                res, during, lead = T.campaign(u, s, end, base, Kc, tau0, stats)
                if c == "control":
                    after = T.feed(u, s[end:], stats, end)
                    whole = np.concatenate([before, during, lead, after])
                    cell["false_alarm_episodes"] = len(T.episodes(whole, K["gap"]))
                    cell["alarm_share"] = float(whole.mean())
                    cell["steps"] = int(len(whole))
                cell["campaigns"][c] = res
            row["sealed"].append(cell)
        if plan["attacks"]:
            for run_ in M["attack"]:
                s = z["attack::" + run_["name"]]
                alarm = T.feed(warm.clone(), s, stats)
                row["attack"].append(attack_row(alarm, run_, mode, warm.name, K))
        row["status"] = "run"
    except T.Disagreement as e:
        row["status"] = f"stopped: {e}"
    row["consistency"], row["seconds"] = stats, round(time.time() - t0)
    write(part, row)
    print(
        f"{cfg} mode {mode} {history} {key}: {row['status'][:80]} {row['seconds']} s",
        flush=True,
    )


def attack_row(alarm, run_, mode, name, K):
    s_len = len(alarm)
    lab = np.zeros(s_len, bool)
    for a, b, _ in run_["events"]:
        lab[a:b] = True
    eps = T.episodes(alarm, K["gap"])
    starts = np.zeros(s_len, bool)
    for a, _ in eps:
        starts[a] = True
    idx = np.flatnonzero(alarm)
    return {
        "name": run_["name"],
        "type": run_["type"],
        "found": [bool(alarm[a:b].any()) for a, b, _ in run_["events"]],
        "onset": [bool(starts[a:b].any()) for a, b, _ in run_["events"]],
        "chance_found": T.chance(
            alarm, run_["events"], T.chance_rng(mode, name, run_["name"])
        ),
        "fa": int(sum(1 for a, b in eps if not lab[a:b].any())),
        "alarm_unlabelled": int((alarm & ~lab).sum()),
        "unlabelled_steps": int((~lab).sum()),
        "alarm_in_events": int((alarm & lab).sum()),
        "event_steps": int(lab.sum()),
        "last_alarm": int(idx[-1]) if len(idx) else None,
    }


# ------------------------------------------------------------------ summary
def summarise(rows, K, campaigns):
    """Totals over the modes of one target, configuration and history (the fields of tw1a's merge)."""
    sealed = [c for r in rows for c in r["sealed"]]
    attack = [a for r in rows for a in r["attack"]]
    days = sum(c["steps"] for c in sealed) / K["spd"]
    entry = {
        "modes": len(rows),
        "placements": len(sealed),
        "parameter_per_mode": {str(r["mode"]): r["parameter"] for r in rows},
        "sealed_false_alarm_ratio_to_budget": sum(
            c["false_alarm_episodes"] for c in sealed
        )
        / days
        / K["budget"],
        "campaigns": {},
        "consistency": {
            k: sum(r["consistency"][k] for r in rows)
            for k in ("checked", "in_band", "probes", "skipped_not_finite")
        },
        "per_mode": {},
    }
    if attack:
        first = [(a["found"][0], a["onset"][0]) for a in attack if a["found"]]
        foll = [(f, o) for a in attack for f, o in zip(a["found"][1:], a["onset"][1:])]
        entry.update(
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
            events=sum(len(a["found"]) for a in attack),
            chance_detected=float(sum(a["chance_found"] for a in attack)),
            alarm_share_unlabelled=sum(a["alarm_unlabelled"] for a in attack)
            / max(1, sum(a["unlabelled_steps"] for a in attack)),
        )
    nm = len(K["mags"])
    for c in campaigns:
        cells = [x["campaigns"][c] for x in sealed if c in x["campaigns"]]
        if not cells:
            continue
        ends = [
            x["reading_at_campaign_end"]
            for x in cells
            if x["reading_at_campaign_end"] is not None
        ]
        entry["campaigns"][c] = {
            "caught_after_lead": [
                int(sum(x["hits"][k] for x in cells)) for k in range(nm)
            ],
            "caught_at_lead0": [
                int(sum(x["hits_lead0"][k] for x in cells)) for k in range(nm)
            ],
            "silent_placements": int(sum(x["alarm_steps"] == 0 for x in cells)),
            "median_alarm_steps": float(np.median([x["alarm_steps"] for x in cells])),
            "median_reading_at_campaign_end": float(np.median(ends)) if ends else None,
            "readings_above_2tau0": int(sum(e > 2 for e in ends)),
            "median_largest_injected_over_tau0": float(
                np.median([x["largest_injected_over_tau0"] for x in cells])
            ),
        }
    for r in rows:
        entry["per_mode"][str(r["mode"])] = {
            c: {
                "lead": [
                    int(sum(x["campaigns"][c]["hits"][k] for x in r["sealed"]))
                    for k in range(nm)
                ],
                "lead0": [
                    int(sum(x["campaigns"][c]["hits_lead0"][k] for x in r["sealed"]))
                    for k in range(nm)
                ],
                "median_reading_at_campaign_end": float(
                    np.median(
                        [
                            x["campaigns"][c]["reading_at_campaign_end"]
                            for x in r["sealed"]
                            if x["campaigns"][c]["reading_at_campaign_end"] is not None
                        ]
                        or [np.nan]
                    )
                ),
            }
            for c in campaigns
            if c in r["sealed"][0]["campaigns"]
        }
    return entry


def merge():
    K = setup()["constants"]
    out = {
        "status": "exploratory (tw1b); Tennessee Eastman score cache; no dataset opened",
        "plan": "docs/research/thresholds_in_the_wild_tw1a_dev_plan.md, amendment 4",
        "magnitudes_over_tau0": K["mags"],
        "harness": harness_summary(K),
        "calibration": {},
        "configs": {},
    }
    for f in sorted((OUT / "calib").glob("mode*_*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        out["calibration"].setdefault(d["target"], {})[str(d["mode"])] = {
            k: d.get(k)
            for k in ("chosen", "chosen_u", "reachable", "chosen_episodes", "tau0")
        } | {"evaluations": len(d.get("evaluations", []))}
    parts = [
        json.loads(f.read_text(encoding="utf-8"))
        for f in sorted((OUT / "parts").glob("*.json"))
    ]
    for cfg in PLAN:
        for history in ("full", "young"):
            for key in TARGETS:
                rows = sorted(
                    (
                        r
                        for r in parts
                        if r["config"] == cfg
                        and r["history"] == history
                        and r["key"] == key
                    ),
                    key=lambda r: r["mode"],
                )
                if not rows:
                    continue
                bad = [r for r in rows if r["status"] != "run"]
                slot = out["configs"].setdefault(cfg, {}).setdefault(history, {})
                if bad:
                    slot[key] = {
                        "status": bad[0]["status"],
                        "modes_run": len(rows) - len(bad),
                    }
                    continue
                slot[key] = summarise(rows, K, PLAN[cfg]["campaigns"])
                slot[key]["name"] = rows[0]["name"].split("(")[0]
                slot[key]["modes_present"] = [r["mode"] for r in rows]
    path = ROOT / "target/tw1/tw1b_summary_score.json"
    path.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    repro_env.stamp_json(path)
    print("written", path)


def harness_summary(K):
    docs = [
        json.loads(f.read_text(encoding="utf-8"))
        for f in sorted((OUT / "harness").glob("tw1a_mode*_*.json"))
    ]
    out = {}
    for history in ("full", "young"):
        rows = [
            dict(
                d["targets"]["river ThresholdFilter(tau0)"],
                mode=d["mode"],
                parameter=None,
            )
            for d in docs
            if d["history"] == history
        ]
        if rows and all(r["status"] == "run" for r in rows):
            out[history] = summarise(
                rows, K, ("control", "frog", "loud", "subl", "frog_cap", "subl_cap")
            )
    return out


if __name__ == "__main__":
    repro_env.pin_from_environment()
    cmd, args = (sys.argv[1] if len(sys.argv) > 1 else ""), sys.argv[2:]
    if cmd == "harness":
        harness(int(args[0]), args[1])
    elif cmd == "calib":
        calib(int(args[0]), args[1])
    elif cmd == "run":
        run(args[0], int(args[1]), args[2], args[3])
    elif cmd == "merge":
        merge()
    else:
        raise SystemExit(__doc__)
