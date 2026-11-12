#!/usr/bin/env python3
"""tt1g (exploratory): threshold rules from alarm practice, recalibration as a rule and a threshold watch,
on the Tennessee Eastman D1 score cache of the tt1f round (no dataset is opened).

Plan: docs/research/threshold_transfer_tt1g_dev_plan.md (committed before any run).

    python scripts/tt1g_baselines_dev.py natural      recorded attacks and attack-free cost   -> part file
    python scripts/tt1g_baselines_dev.py campaigns    the 56 registered placements            -> part file
    python scripts/tt1g_baselines_dev.py merge        docs/research/threshold_transfer_tt1g_tep_v1.json
"""
from __future__ import annotations

import copy
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_telemetry_detect_v2 as R2
import threshold_rules as T
import threshold_rules_tt1g as G
import tt1d_data as TD
import tt1d_final as M
import tt1f_tep_dev as F

ROOT = Path(__file__).resolve().parents[1]
PART = ROOT / "target/real-telemetry/tt1g"
OUT = ROOT / "docs/research/threshold_transfer_tt1g_tep_v1.json"
S = M.SETUPS["tep59"]
NEW = ["median_mad", "ewma", "ewma_excl", "on_delay", "recal_quiet", "recal_oracle"]
OLD = ["tracker", "daily", "daily_excl", "tracker_capped", "spot_gr"]
NEW2 = ["recal_pooled_quiet", "recal_pooled_oracle"]            # amendment 1 of the plan (post-hoc)
REFRESH, DELAY, WATCH = round(3600 / S.step), S.rules.event_l, 1.5


class Wrap:
    """A registered rule behind the tt1g interface."""

    def __init__(self, m):
        self.m = m

    def tau(self):
        return self.m.tau()

    def update(self, x, flag=False):
        self.m.update(x)


def calibrate(pooled):
    """k, L and the on-delay threshold of one mode from its four calibration runs (budget of the study)."""
    runs = np.split(pooled, 4)
    zs = []
    for run in runs:
        m = G.MedianMad(pooled, 0.0, S.spd, REFRESH)
        z = np.empty(len(run))
        for t, x in enumerate(run):
            z[t] = (x - m.m) / m.s
            m.update(x)
        zs.append(z)
    k = R2.calibrate(zs, S.gap, S.budget, S.spd)
    zs = []
    for run in runs:
        e = G.Ewma(pooled, 0.0, S.spd)
        z = np.empty(len(run))
        for t, x in enumerate(run):
            z[t] = (x - e.mu) / e.sigma()
            e.update(x)
        zs.append(z)
    L = R2.calibrate(zs, S.gap, S.budget, S.spd)
    thr = R2.calibrate([G.rolling_min(r, DELAY) for r in runs], S.gap, S.budget, S.spd)
    return {"k": float(k), "L": float(L), "on_delay_threshold": float(thr)}


def make(rule, cfg, pooled, cal):
    if rule == "median_mad":
        return G.MedianMad(pooled, cal["k"], S.spd, REFRESH)
    if rule in ("ewma", "ewma_excl"):
        return G.Ewma(pooled, cal["L"], S.spd, exclude=rule == "ewma_excl")
    if rule == "on_delay":
        return G.OnDelay(cal["on_delay_threshold"], DELAY)
    if rule in ("recal_quiet", "recal_oracle"):
        return G.Recal(cfg["tau0"], rule.split("_")[1], S.spd, S.gap, S.rules.event_l, S.budget)
    if rule in NEW2:
        return G.Recal(cfg["tau0"], rule.rsplit("_", 1)[1], S.spd, S.gap, S.rules.event_l, S.budget, pool=np.split(pooled, 4))
    return Wrap(S.rules.make(rule, cfg, pooled))


def path(model, s, flags=None):
    tau = np.empty(len(s))
    for i, x in enumerate(s):
        tau[i] = model.tau()
        model.update(x, bool(flags[i]) if flags is not None else False)
    return tau


def score(s, tau, events, lab, tau0):
    alarm = s > tau
    eps = T._episodes(alarm, S.gap)
    starts = np.zeros(len(s), bool)
    for a, _ in eps:
        starts[a] = True
    high = np.flatnonzero(np.isfinite(tau) & (tau > WATCH * tau0))
    fin = tau[np.isfinite(tau)]
    return {"found": [bool(alarm[e[0]:e[1]].any()) for e in events], "onset": [bool(starts[e[0]:e[1]].any()) for e in events],
            "fa": int(sum(1 for a, b in eps if not lab[a:b].any())), "alarm_unlabelled": int((alarm & ~lab).sum()),
            "tau_end": float(fin[-1] / tau0) if len(fin) else None, "watch_first": int(high[0]) if len(high) else None,
            "last_alarm": int(np.flatnonzero(alarm)[-1]) if alarm.any() else None}


# ---------------------------------------------------------------- recorded attacks and attack-free cost
def natural(new=NEW, old=OLD, name="natural"):
    reg = F.registered()
    out = {"calibration": {}, "attack_runs": [], "sealed_runs": []}
    for u in reg["units"]:
        mode = int(u["unit"].split("_")[1])
        cfg, pooled, sealed, attack = F.load(mode)
        cal = calibrate(pooled)
        out["calibration"][u["unit"]] = {**cal, "on_delay_over_tau0": cal["on_delay_threshold"] / cfg["tau0"]}
        print(u["unit"], out["calibration"][u["unit"]], flush=True)
        for run in u["attack_runs"]:
            t0 = time.time()
            s, key = attack[run["name"]]
            events, lab = TD.events(key), np.asarray(key) != 0
            row = {"name": run["name"], "type": run["type"], "events": [list(e) for e in events],
                   "unlabelled_steps": int((~lab).sum()), "rules": {}}
            for r in new + old:
                v = score(s, path(make(r, cfg, pooled, cal), s, lab), events, lab, cfg["tau0"])
                if r in OLD and v["found"] != run["scores"]["D1"][r]["found"]:
                    raise SystemExit(f"{run['name']} {r}: registered detections not reproduced")
                row["rules"][r] = v
            row["rules"]["frozen"] = {k: run["scores"]["D1"]["frozen"][k] for k in ("found", "onset", "fa", "alarm_unlabelled")}
            out["attack_runs"].append(row)
            print(run["name"], round(time.time() - t0), "s", flush=True)
        for run in u["sealed_runs"]:
            s = sealed[run["name"]]
            lab = np.zeros(len(s), bool)
            row = {"name": run["name"], "steps": int(len(s)), "rules": {}}
            for r in new + old:
                v = score(s, path(make(r, cfg, pooled, cal), s), [], lab, cfg["tau0"])
                row["rules"][r] = {"fa": v["fa"], "tau_end": v["tau_end"], "watch": v["watch_first"] is not None}
            out["sealed_runs"].append(row)
            print(run["name"], "sealed", flush=True)
    PART.mkdir(parents=True, exist_ok=True)
    (PART / f"{name}.json").write_text(json.dumps(out), encoding="utf-8")


# ---------------------------------------------------------------- campaigns on the registered placements
def play(rule, cfg, pooled, cal, s, end, mode):
    """tt1d_final.play for any rule; also the first campaign step on which the threshold watch would fire."""
    m = make(rule, cfg, pooled, cal)
    c_start, c_end = end - S.lead - S.campaign, end - S.lead
    tau0 = cfg["tau0"]
    alarms, episodes, last, watch = 0, 0, None, None
    for i in range(end):
        tau = m.tau()
        x, flag = s[i], False
        inside = c_start <= i < c_end
        if mode != "control" and inside and x != -np.inf:
            k = i - c_start
            base = tau if np.isfinite(tau) else getattr(m, "thr", tau0)
            if mode == "frog":
                x, flag = max(x, M.FROG_FRAC * base), True
            elif mode == "loud":
                if k % S.loud[0] < S.loud[1]:
                    x, flag = max(x, S.loud[2] * tau0), True
            elif k % S.subl[0] < S.subl[1]:
                x, flag = max(x, S.subl[2] * base), True
            if x > tau:
                alarms += 1
                if last is None or i - last > S.gap + 1:   # fi1: merge across up to gap quiet steps, as _episodes does
                    episodes += 1
                last = i
        if inside and watch is None and np.isfinite(tau) and tau > WATCH * tau0:
            watch = i - c_start
        m.update(x, flag)
    hits = []
    for mag in M.MAGS:
        mm, hit = copy.deepcopy(m), False
        for i in range(end, end + S.terminal):
            x = max(s[i], mag * tau0)
            hit |= bool(x > mm.tau())
            mm.update(x, True)
        hits.append(hit)
    t = m.tau()
    return {"hits": hits, "tau_end": float(t / tau0) if np.isfinite(t) else None, "alarm_steps": alarms, "alarm_episodes": episodes,
            "watch_step": watch}


def campaigns(new=NEW, old=OLD, name="campaigns"):
    reg = F.registered()
    out = []
    for u in reg["units"]:
        mode = int(u["unit"].split("_")[1])
        cfg, pooled, sealed, _ = F.load(mode)
        cal = calibrate(pooled)
        for run in u["sealed_runs"]:
            t0 = time.time()
            s = sealed[run["name"]]
            end = run["campaigns"][0]["terminal_start"]
            row = {"name": run["name"], "unit": u["unit"], "rules": {}}
            for r in new + old:
                row["rules"][r] = {c: play(r, cfg, pooled, cal, s, end, c) for c in ("control", "frog", "loud", "subl")}
            want = run["campaigns"][0]
            for c, r in (("frog", "spot_gr"), ("loud", "tracker"), ("subl", "daily_excl")) if old else ():
                if row["rules"][r][c]["hits"] != want[c][r]["after"] or row["rules"][r]["control"]["hits"] != want[c][r]["control"]:
                    raise SystemExit(f"{run['name']}: {r} under {c} does not reproduce the registered outcome")
            out.append(row)
            print(run["name"], round(time.time() - t0), "s", flush=True)
    PART.mkdir(parents=True, exist_ok=True)
    (PART / f"{name}.json").write_text(json.dumps(out), encoding="utf-8")


# ---------------------------------------------------------------- merge
def merge():
    nat = json.loads((PART / "natural.json").read_text(encoding="utf-8"))
    camp = json.loads((PART / "campaigns.json").read_text(encoding="utf-8"))
    extra = NEW2 if (PART / "natural2.json").exists() and (PART / "campaigns2.json").exists() else []
    if extra:
        nat2 = json.loads((PART / "natural2.json").read_text(encoding="utf-8"))
        camp2 = {x["name"]: x for x in json.loads((PART / "campaigns2.json").read_text(encoding="utf-8"))}
        for key in ("attack_runs", "sealed_runs"):
            more = {x["name"]: x for x in nat2[key]}
            for x in nat[key]:
                x["rules"].update({r: more[x["name"]]["rules"][r] for r in extra})
        for x in camp:
            x["rules"].update(camp2[x["name"]]["rules"])
    rules = ["frozen"] + NEW + extra + OLD
    meta, per = [], {r: {"found": [], "onset": []} for r in rules}
    fa, steps, unl = {r: 0 for r in rules}, {r: 0 for r in rules}, 0
    watch_runs, noise = {r: 0 for r in rules[1:]}, {r: [] for r in rules[1:]}
    for run in nat["attack_runs"]:
        unl += run["unlabelled_steps"]
        meta += [{"run": run["name"], "order": i} for i in range(len(run["events"]))]
        for r in rules:
            v = run["rules"][r]
            per[r]["found"] += v["found"]; per[r]["onset"] += v["onset"]
            fa[r] += v["fa"]; steps[r] += v["alarm_unlabelled"]
            if r == "frozen":
                continue
            watch_runs[r] += v["watch_first"] is not None
            if run["type"] == 24 and run["events"]:
                a = run["events"][0][0]
                noise[r].append({"watch_hours": None if v["watch_first"] is None else (v["watch_first"] - a) * S.step / 3600,
                                 "before_last_alarm": v["watch_first"] is not None and v["last_alarm"] is not None
                                 and v["watch_first"] <= v["last_alarm"]})
    groups = [e["run"] for e in meta]
    sel = {"first": [e["order"] == 0 for e in meta], "follower": [e["order"] > 0 for e in meta]}
    days = unl / S.spd
    sealed_days = sum(r["steps"] for r in nat["sealed_runs"]) / S.spd
    med = lambda xs: float(np.median(xs)) if len(xs) else None
    out = {"schema_version": "threshold-transfer-tt1g-tep-v1",
           "status": "exploratory: Tennessee Eastman D1 score cache of the tt1f round; no dataset opened",
           "plan": "docs/research/threshold_transfer_tt1g_dev_plan.md", "calibration": nat["calibration"],
           "settings": {"refresh_steps": REFRESH, "on_delay_steps": DELAY, "watch_multiple_of_tau0": WATCH,
                        "magnitudes_over_tau0": list(M.MAGS), "placements": len(camp), "sealed_days": sealed_days},
           "rules": {}}
    for r in rules:
        row = {"attack_runs_fa_ratio_to_budget": fa[r] / days / S.budget, "attack_runs_alarm_share": steps[r] / unl}
        for name, mask in sel.items():
            take = lambda xs, mask=mask: [x for x, k in zip(xs, mask) if k]
            row[name] = {"events": int(sum(mask)), "detected": int(sum(take(per[r]["found"]))), "onset_detected": int(sum(take(per[r]["onset"])))}
            if r != "frozen":
                row[name]["vs_frozen"] = M.cluster_bootstrap(take(groups), take(per["frozen"]["found"]), take(per[r]["found"]))["recall_difference_interval"]
                row[name]["vs_frozen_onset"] = M.cluster_bootstrap(take(groups), take(per["frozen"]["onset"]), take(per[r]["onset"]))["recall_difference_interval"]
        if r != "frozen":
            sr = [x["rules"][r] for x in nat["sealed_runs"]]
            row["sealed_fa_ratio_to_budget"] = sum(x["fa"] for x in sr) / sealed_days / S.budget
            row["sealed_median_tau_end"] = med([x["tau_end"] for x in sr if x["tau_end"] is not None])
            row["watch"] = {"sealed_runs_with_false_alert": int(sum(x["watch"] for x in sr)), "sealed_runs": len(sr),
                            "attack_runs_alerted": int(watch_runs[r]), "attack_runs": len(nat["attack_runs"]),
                            "noise_sequences_alerted": int(sum(x["watch_hours"] is not None for x in noise[r])),
                            "noise_sequences": len(noise[r]),
                            "noise_median_hours_to_alert": med([x["watch_hours"] for x in noise[r] if x["watch_hours"] is not None]),
                            "noise_alert_before_last_alarm": int(sum(x["before_last_alarm"] for x in noise[r]))}
            row["campaigns"] = {}
            for c in ("frog", "loud", "subl"):
                cells = [x["rules"][r][c] for x in camp]
                ctrl = [x["rules"][r]["control"] for x in camp]
                w = [x["watch_step"] for x in cells if x["watch_step"] is not None]
                row["campaigns"][c] = {
                    "caught_after": [int(sum(x["hits"][k] for x in cells)) for k in range(len(M.MAGS))],
                    "caught_control": [int(sum(x["hits"][k] for x in ctrl)) for k in range(len(M.MAGS))],
                    "silent_placements": int(sum(x["alarm_steps"] == 0 for x in cells)),
                    "median_alarm_episodes": med([x["alarm_episodes"] for x in cells]),
                    "median_tau_end": med([x["tau_end"] for x in cells if x["tau_end"] is not None]),
                    "watch_alerted": len(w), "watch_median_hours": med([x * S.step / 3600 for x in w]),
                    "watch_alerted_in_control": int(sum(x["watch_step"] is not None for x in ctrl))}
        out["rules"][r] = row
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for r in rules:
        v = out["rules"][r]
        line = f"{r:15s} first {v['first']['detected']:3d} foll {v['follower']['detected']:3d}/{v['follower']['onset_detected']:2d} FA att x{v['attack_runs_fa_ratio_to_budget']:.2f}"
        if r != "frozen":
            line += f" sealed x{v['sealed_fa_ratio_to_budget']:.2f} | " + " ".join(
                f"{c} {v['campaigns'][c]['caught_after']} (ctl {v['campaigns'][c]['caught_control'][0]}) w{v['campaigns'][c]['watch_alerted']}"
                for c in ("frog", "loud", "subl")) + f" | watch false {v['watch']['sealed_runs_with_false_alert']}/56"
        print(line)
    print("written", OUT)


if __name__ == "__main__":
    {"natural": natural, "campaigns": campaigns, "merge": merge, "natural2": lambda: natural(NEW2, [], "natural2"),
     "campaigns2": lambda: campaigns(NEW2, [], "campaigns2")}[sys.argv[1]]()
