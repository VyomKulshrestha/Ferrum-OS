#!/usr/bin/env python3
"""tt1f (exploratory, post-hoc): matched operating points, one trace and SPOT under the frog on the
Tennessee Eastman data of the registered tt1d study.

Plan: docs/research/threshold_transfer_tt1f_dev_plan.md (committed before any run). Nothing here is
registered and no registered outcome changes.

    python scripts/tt1f_tep_dev.py scores     refit each mode's monitor with the registered code and cache the D1
                                              score of every sealed attack-free run and every attack run (a second,
                                              ledgered access to both)
    python scripts/tt1f_tep_dev.py analyse    parts A, B and C of the plan from the cache; writes
                                              docs/research/threshold_transfer_tt1f_tep_v1.json
"""
from __future__ import annotations

import copy
import csv
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_telemetry_detect as R
import real_telemetry_detect_v2 as R2
import threshold_rules as T
import tt1d_data as TD
import tt1d_final as M

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "target/real-telemetry/tt1f"
OUT = ROOT / "docs/research/threshold_transfer_tt1f_tep_v1.json"
TRACE = CACHE / "tep_noise_run_trace.csv"
REASON = ("EXPLORATORY tt1f (post-hoc after the registered tt1d final): D1 scores for matched operating points, "
          "one trace and SPOT under the frog")
S = M.SETUPS["tep59"]
TARGETS = ["tracker", "tracker_ceil_1.25", "daily_excl", "tighten_only", "tracker_capped"]
GRID = np.round(np.arange(0.50, 1.5001, 0.001), 3)
SPOTS = ["spot_gr", "spot_gr_bounded", "spot_gr_declust"]
TRACE_STRIDE = 10


def registered():
    return json.loads(M.result_path("tep59").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- scores
def scores():
    CACHE.mkdir(parents=True, exist_ok=True)
    todo = [m for m in TD.MODES if not (CACHE / f"mode_{m}.npz").exists()]
    if not todo:
        print("every mode is cached")
        return
    reg = {u["unit"]: u for u in registered()["units"]}
    TD.open_final(REASON)
    for mode in todo:
        t0 = time.time()
        dev = {role: TD.dev_runs(mode, role) for role in ("fit", "scale", "calib")}
        score, cfgs, pooled, _ = M.fit_scores(S, dev["fit"], dev["scale"], dev["calib"])
        del dev
        cfg = cfgs["D1"]
        want = reg[f"mode_{mode}"]["thresholds"]["D1"]
        if any(abs(cfg[k] - want[k]) > 1e-9 * max(1.0, abs(want[k])) for k in want):
            raise SystemExit(f"mode {mode}: refitted thresholds differ from the registered ones: {cfg} vs {want}")
        data = {"cfg": np.array(json.dumps(cfg)), "pooled": np.asarray(pooled["D1"], np.float64)}
        for name, x, u in TD.sealed_runs(mode):
            data["sealed::" + name] = M.clean(score(x, u)["D1"])
        for name, kind, x, u, key in TD.attack_runs(mode):
            data["attack::" + name] = M.clean(score(x, u)["D1"])
            data["key::" + name] = np.asarray(key, np.int8)
        np.savez_compressed(CACHE / f"mode_{mode}.npz", **data)
        print("mode", mode, "cached", len(data) - 2, "arrays", round(time.time() - t0), "s", flush=True)


def load(mode):
    z = np.load(CACHE / f"mode_{mode}.npz")
    cfg = json.loads(str(z["cfg"]))
    sealed = {k.split("::", 1)[1]: z[k] for k in z.files if k.startswith("sealed::")}
    attack = {k.split("::", 1)[1]: (z[k], z["key::" + k.split("::", 1)[1]]) for k in z.files if k.startswith("attack::")}
    return cfg, z["pooled"], sealed, attack


# ---------------------------------------------------------------- A. matched operating points
def n_episodes(idx):
    return 0 if not len(idx) else 1 + int((np.diff(idx) > S.gap + 1).sum())


def static_rows(s, thr, events, lab):
    """A static threshold over one stream, scored as tt1d_final.stream_rows scores a rule."""
    alarm = s > thr
    eps = T._episodes(alarm, S.gap)
    starts = np.zeros(len(s), bool)
    for a, _ in eps:
        starts[a] = True
    return {"found": [bool(alarm[e[0]:e[1]].any()) for e in events],
            "onset": [bool(starts[e[0]:e[1]].any()) for e in events],
            "fa": int(sum(1 for a, b in eps if not lab[a:b].any())),
            "alarm_unlabelled": int((alarm & ~lab).sum())}


def matched(reg, modes):
    # registered false-alarm episodes of every rule on the 56 sealed runs
    reg_fa, days = {}, 0.0
    for u in reg["units"]:
        for run in u["sealed_runs"]:
            days += run["steps"] / S.spd
            for r, v in run["false_alarms"].items():
                reg_fa[r] = reg_fa.get(r, 0) + v["fa"]
    counts = np.zeros(len(GRID), int)
    for cfg, _, sealed, _ in modes.values():
        for s in sealed.values():
            keep = np.flatnonzero(s > GRID[0] * cfg["tau0"])
            v = s[keep]
            for j, c in enumerate(GRID):
                counts[j] += n_episodes(keep[v > c * cfg["tau0"]])
    at_one = int(counts[int(np.flatnonzero(GRID == 1.0)[0])])
    if at_one != reg_fa["frozen"]:
        raise SystemExit(f"cache check failed: static 1.0 tau0 gives {at_one} sealed episodes, registered frozen {reg_fa['frozen']}")
    choice = {}
    for r in TARGETS:
        gap = np.abs(counts - reg_fa[r])
        j = int(np.flatnonzero(gap == gap.min())[-1])           # ties go to the larger multiplier
        choice[r] = {"multiplier": float(GRID[j]), "sealed_episodes": int(counts[j]), "target_episodes": int(reg_fa[r]),
                     "sealed_ratio_to_budget": float(counts[j] / days / S.budget),
                     "target_ratio_to_budget": float(reg_fa[r] / days / S.budget)}
    # attack runs: registered per-event outcomes and the static thresholds
    meta, per = [], {}
    put = lambda name, key, values: per.setdefault(name, {"found": [], "onset": []})[key].extend(values)
    fa, steps, unlabelled = {}, {}, 0
    names = ["static_1.0"] + [f"static@{r}" for r in TARGETS]
    mult = {"static_1.0": 1.0, **{f"static@{r}": choice[r]["multiplier"] for r in TARGETS}}
    for u in reg["units"]:
        mode = int(u["unit"].split("_")[1])
        cfg, _, _, attack = modes[mode]
        for run in u["attack_runs"]:
            s, key = attack[run["name"]]
            events, lab = TD.events(key), np.asarray(key) != 0
            if [list(e) for e in events] != run["events"]:
                raise SystemExit(f"{run['name']}: events differ from the registered record")
            unlabelled += int((~lab).sum())
            meta += [{"run": run["name"], "order": i} for i in range(len(events))]
            for r in ["frozen"] + TARGETS:
                v = run["scores"]["D1"][r]
                put(r, "found", v["found"]); put(r, "onset", v["onset"])
                fa[r] = fa.get(r, 0) + v["fa"]; steps[r] = steps.get(r, 0) + v["alarm_unlabelled"]
            for n in names:
                v = static_rows(s, mult[n] * cfg["tau0"], events, lab)
                if n == "static_1.0" and (v["found"], v["onset"], v["fa"]) != tuple(run["scores"]["D1"]["frozen"][k] for k in ("found", "onset", "fa")):
                    raise SystemExit(f"{run['name']}: the cached score does not reproduce the registered frozen row")
                put(n, "found", v["found"]); put(n, "onset", v["onset"])
                fa[n] = fa.get(n, 0) + v["fa"]; steps[n] = steps.get(n, 0) + v["alarm_unlabelled"]
    groups = [e["run"] for e in meta]
    sel = {"all": [True] * len(meta), "first": [e["order"] == 0 for e in meta], "follower": [e["order"] > 0 for e in meta]}
    rows = {}
    for n in ["frozen"] + TARGETS + names[1:]:
        row = {"fa_ratio_to_budget_attack_runs": fa[n] / (unlabelled / S.spd) / S.budget,
               "unlabelled_alarm_share": steps[n] / unlabelled}
        for name, mask in sel.items():
            take = lambda xs, mask=mask: [x for x, k in zip(xs, mask) if k]
            row[name] = {"events": int(sum(mask)), "detected": int(sum(take(per[n]["found"]))),
                         "onset_detected": int(sum(take(per[n]["onset"])))}
            pairs = {"vs_frozen": "frozen"}
            if n.startswith("static@"):
                pairs["vs_matched_rule"] = n.split("@", 1)[1]            # recall(static) - recall(rule)
            for label, base in pairs.items():
                if base == n:
                    continue
                row[name][label] = M.cluster_bootstrap(take(groups), take(per[base]["found"]), take(per[n]["found"]))
                row[name][label + "_onset"] = M.cluster_bootstrap(take(groups), take(per[base]["onset"]), take(per[n]["onset"]))
        rows[n] = row
    return {"sealed_days": days, "grid": [float(GRID[0]), float(GRID[-1]), 0.001], "match": choice, "attack_runs": rows,
            "note": "static@R is the static threshold c tau0 whose sealed-run episode count is closest to rule R's; "
                    "vs_matched_rule is recall(static@R) - recall(R); the match is in-sample on the sealed runs"}


# ---------------------------------------------------------------- B. one trace
def trace(modes):
    name = min((n for n, kind in TD.attack_names()[0] if kind == 24), key=lambda n: int(re.search(r"_id_(\d+)", n).group(1)))
    cfg, _, _, attack = modes[0]
    s, key = attack[name]
    tau = M.path(S, "tracker", cfg, None, s)
    with open(TRACE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["hours", "score_max", "tau0", "tau_tracker", "attack_key"])
        for a in range(0, len(s), TRACE_STRIDE):
            b = min(a + TRACE_STRIDE, len(s))
            seg = s[a:b]
            top = float(np.max(seg)) if np.isfinite(seg).any() else ""
            w.writerow([round(a * S.step / 3600, 4), top, cfg["tau0"], float(tau[b - 1]), int(np.max(key[a:b]))])
    events = TD.events(key)
    return {"run": name, "file": str(TRACE.relative_to(ROOT)).replace("\\", "/"), "stride_steps": TRACE_STRIDE,
            "tau0": cfg["tau0"], "events": [list(e) for e in events],
            "tracker_over_tau0_at_event_starts": [float(tau[e[0]] / cfg["tau0"]) for e in events],
            "frozen_alarm_share_in_events": [float((s[e[0]:e[1]] > cfg["tau0"]).mean()) for e in events],
            "tracker_alarm_share_in_events": [float((s[e[0]:e[1]] > tau[e[0]:e[1]]).mean()) for e in events]}


# ---------------------------------------------------------------- C. SPOT under the frog
def snapshot(m, tau0):
    return {"xi": float(m.g), "sigma": float(m.sg), "peaks": int(len(m.peaks)), "tau_over_tau0": float(m.tau() / tau0)}


def frog_play(rule, cfg, calib, s, end, frog):
    """tt1d_final.play for the frog, with the fitted tail read at the end of the campaign and a fixed tau0
    monitor watching the same score (part H)."""
    m = S.rules.N.make(rule, cfg, calib, S.spd, S.rules.hold)
    c_start, c_end = end - S.lead - S.campaign, end - S.lead
    alarms, at_end, watch, watch_first = 0, None, 0, None
    for i in range(end):
        if i == c_end:
            at_end = snapshot(m, cfg["tau0"])
            at_end.update(tau0_monitor_steps=watch, tau0_monitor_first_hours=None if watch_first is None else
                          (watch_first - c_start) * S.step / 3600)
        tau = m.tau()
        x = s[i]
        if c_start <= i < c_end and x != -np.inf:
            if frog:
                x = max(x, M.FROG_FRAC * tau)
                alarms += bool(x > tau)
            if x > cfg["tau0"]:
                watch += 1
                watch_first = i if watch_first is None else watch_first
        m.update(x)
    hits = []
    for mag in M.MAGS:
        mm, hit = copy.deepcopy(m), False
        for i in range(end, end + S.terminal):
            x = max(s[i], mag * cfg["tau0"])
            hit |= bool(x > mm.tau())
            mm.update(x)
        hits.append(hit)
    return hits, at_end, alarms


def spot_frog(reg, modes):
    rows = {r: {"after": [], "control": [], "end": [], "end_control": [], "alarm_steps": []} for r in SPOTS}
    for u in reg["units"]:
        mode = int(u["unit"].split("_")[1])
        cfg, pooled, sealed, _ = modes[mode]
        for run in u["sealed_runs"]:
            t0 = time.time()
            s = sealed[run["name"]]
            end = run["campaigns"][0]["terminal_start"]
            for r in SPOTS:
                hits, diag, alarms = frog_play(r, cfg, pooled, s, end, True)
                hits_c, diag_c, _ = frog_play(r, cfg, pooled, s, end, False)
                if r == "spot_gr":
                    want = run["campaigns"][0]["frog"]["spot_gr"]
                    if hits != want["after"] or hits_c != want["control"]:
                        raise SystemExit(f"{run['name']}: spot_gr does not reproduce the registered frog row")
                o = rows[r]
                o["after"].append(hits); o["control"].append(hits_c); o["end"].append(diag); o["end_control"].append(diag_c)
                o["alarm_steps"].append(alarms)
            print("mode", mode, run["name"], round(time.time() - t0), "s", flush=True)
    out = {}
    q = lambda xs: [float(v) for v in np.quantile(xs, [0.0, 0.25, 0.5, 0.75, 1.0])]
    for r, o in rows.items():
        infl = np.array([d["tau_over_tau0"] for d in o["end"]])
        xi = np.array([d["xi"] for d in o["end"]])
        out[r] = {"placements": len(o["after"]),
                  "caught_after": [int(np.sum([h[k] for h in o["after"]])) for k in range(len(M.MAGS))],
                  "caught_control": [int(np.sum([h[k] for h in o["control"]])) for k in range(len(M.MAGS))],
                  "silent_placements": int(np.sum(np.array(o["alarm_steps"]) == 0)),
                  "tau_over_tau0_quartiles": q(infl), "tau_over_tau0_control_quartiles": q([d["tau_over_tau0"] for d in o["end_control"]]),
                  "placements_above_2_tau0": int((infl > 2).sum()), "placements_above_10_tau0": int((infl > 10).sum()),
                  "xi_quartiles": q(xi), "xi_control_quartiles": q([d["xi"] for d in o["end_control"]]),
                  "placements_xi_above_half": int((xi > 0.5).sum()), "placements_xi_above_one": int((xi > 1.0).sum()),
                  "sigma_quartiles": q([d["sigma"] for d in o["end"]]),
                  "peaks_quartiles": q([d["peaks"] for d in o["end"]]),
                  "peaks_control_quartiles": q([d["peaks"] for d in o["end_control"]]),
                  "tau0_monitor": {
                      "placements_alarming_during_frog": int(sum(d["tau0_monitor_steps"] > 0 for d in o["end"])),
                      "placements_alarming_without_frog": int(sum(d["tau0_monitor_steps"] > 0 for d in o["end_control"])),
                      "share_of_campaign_steps_above_tau0_quartiles": q([d["tau0_monitor_steps"] / S.campaign for d in o["end"]]),
                      "share_without_frog_quartiles": q([d["tau0_monitor_steps"] / S.campaign for d in o["end_control"]]),
                      "hours_to_first_alarm_quartiles": q([d["tau0_monitor_first_hours"] for d in o["end"]
                                                           if d["tau0_monitor_first_hours"] is not None] or [np.nan])},
                  "per_placement": [{"after": h, "control": c, **d} for h, c, d in zip(o["after"], o["control"], o["end"])]}
    return {"magnitudes_over_tau0": list(M.MAGS), "rules": out}


# ---------------------------------------------------------------- F, G, I (amendment 1 of the plan)
CHANCE_RULES = ["frozen", "tracker", "daily", "daily_excl", "tracker_capped", "tighten_only"]
CLEAR_RULES = ["frozen", "tracker", "tracker_slow", "tracker_tau", "daily"]
SHIFTS = 200


def chance_clear_peaks(reg, modes):
    rng = np.random.default_rng(7)
    groups = {}                                           # (rule, type, role) -> observed and shifted counts
    cell = lambda key: groups.setdefault(key, {"events": 0, "any": 0, "onset": 0, "any_shift": np.zeros(SHIFTS), "onset_shift": np.zeros(SHIFTS)})
    clear = {r: [] for r in CLEAR_RULES}
    peaks = []
    for u in reg["units"]:
        mode = int(u["unit"].split("_")[1])
        cfg, pooled, _, attack = modes[mode]
        for run in u["attack_runs"]:
            t0 = time.time()
            s, key = attack[run["name"]]
            events = TD.events(key)
            n = len(s)
            offs = rng.integers(1, n, SHIFTS)
            for i, e in enumerate(events):
                seg = s[e[0]:e[1]]
                peaks.append({"type": run["type"], "role": "first" if i == 0 else "follower",
                              "peak_over_tau0": float(np.max(seg) / cfg["tau0"]) if np.isfinite(seg).any() else None})
            for r in dict.fromkeys(CHANCE_RULES + CLEAR_RULES):
                alarm = s > M.path(S, r, cfg, pooled, s)
                eps = T._episodes(alarm, S.gap)
                starts = np.zeros(n, bool)
                for a, _ in eps:
                    starts[a] = True
                found = [bool(alarm[e[0]:e[1]].any()) for e in events]
                if found != run["scores"]["D1"][r]["found"]:
                    raise SystemExit(f"{run['name']} {r}: the recomputed rule does not reproduce the registered detections")
                if r in CLEAR_RULES and run["type"] == 24 and events:
                    a, b = events[0][0], events[-1][1]
                    idx = np.flatnonzero(alarm[a:b])
                    clear[r].append({"hours": (b - a) * S.step / 3600, "alarm_share": float(len(idx) / (b - a)),
                                     "first_alarm_hours": float(idx[0] * S.step / 3600) if len(idx) else None,
                                     "last_alarm_hours": float(idx[-1] * S.step / 3600) if len(idx) else None})
                if r not in CHANCE_RULES:
                    continue
                ca, cs = np.concatenate([[0], np.cumsum(alarm)]), np.concatenate([[0], np.cumsum(starts)])
                for i, e in enumerate(events):
                    c = cell((r, run["type"], "first" if i == 0 else "follower"))
                    c["events"] += 1
                    c["any"] += found[i]
                    c["onset"] += bool(starts[e[0]:e[1]].any())
                    lo, hi = (e[0] - offs) % n, (e[1] - offs) % n          # the event seen from a sequence rolled by offs
                    wrap = hi <= lo
                    for cum, name in ((ca, "any_shift"), (cs, "onset_shift")):
                        inside = np.where(wrap, cum[n] - cum[lo] + cum[hi], cum[hi] - cum[lo])
                        c[name] += inside > 0
            print("chance", run["name"], round(time.time() - t0), "s", flush=True)
    rows = {}
    for (r, kind, role), c in sorted(groups.items()):
        rng_of = lambda x: [float(np.mean(x)), float(np.quantile(x, 0.025)), float(np.quantile(x, 0.975))]
        rows.setdefault(r, {})[f"type_{kind}_{role}"] = {"events": c["events"], "detected": int(c["any"]), "onset_detected": int(c["onset"]),
                                                          "shifted_detected_mean_lo_hi": rng_of(c["any_shift"]),
                                                          "shifted_onset_mean_lo_hi": rng_of(c["onset_shift"])}
    for r in rows:
        for role in ("first", "follower"):
            parts = [c for (rr, _, ro), c in groups.items() if rr == r and ro == role]
            tot = lambda k: sum(c[k] for c in parts)
            rows[r][role] = {"events": int(tot("events")), "detected": int(tot("any")), "onset_detected": int(tot("onset")),
                             "shifted_detected_mean_lo_hi": [float(np.mean(tot("any_shift"))), float(np.quantile(tot("any_shift"), 0.025)),
                                                             float(np.quantile(tot("any_shift"), 0.975))],
                             "shifted_onset_mean_lo_hi": [float(np.mean(tot("onset_shift"))), float(np.quantile(tot("onset_shift"), 0.025)),
                                                          float(np.quantile(tot("onset_shift"), 0.975))]}
    med = lambda xs: float(np.median(xs)) if len(xs) else None
    clear_out = {r: {"sequences": len(v), "never_alarmed": int(sum(x["first_alarm_hours"] is None for x in v)),
                     "median_sequence_hours": med([x["hours"] for x in v]),
                     "median_alarm_share": med([x["alarm_share"] for x in v]),
                     "median_first_alarm_hours": med([x["first_alarm_hours"] for x in v if x["first_alarm_hours"] is not None]),
                     "median_last_alarm_hours": med([x["last_alarm_hours"] for x in v if x["last_alarm_hours"] is not None]),
                     "median_last_alarm_share_of_sequence": med([x["last_alarm_hours"] / x["hours"] for x in v if x["last_alarm_hours"] is not None])}
                 for r, v in clear.items()}
    pk = np.array([p["peak_over_tau0"] for p in peaks if p["peak_over_tau0"] is not None])
    first = np.array([p["peak_over_tau0"] for p in peaks if p["peak_over_tau0"] is not None and p["role"] == "first"])
    below = lambda a: {str(k): int((a < k).sum()) for k in (1.0, 1.1, 1.25, 1.5, 2.0)}
    return ({"shifts_per_run": SHIFTS, "rules": rows,
             "note": "each rule's alarm sequence is shifted circularly within its run by a random offset; counts are pooled over runs per shift"},
            clear_out,
            {"events": int(len(pk)), "quantiles_0_25_50_75_100": [float(v) for v in np.quantile(pk, [0, 0.25, 0.5, 0.75, 1])],
             "events_with_peak_below": below(pk), "first_events": int(len(first)), "first_events_with_peak_below": below(first)})


# ---------------------------------------------------------------- K1 (amendment 2 of the plan)
def calibration_check(modes):
    """The D1 threshold of each mode under the registered calibrate and under calibrate_v2 (first budget break)."""
    out = {}
    for mode, (cfg, pooled, _, _) in modes.items():
        if len(pooled) % 4:
            raise SystemExit(f"mode {mode}: the pooled calibration scores do not split into four runs")
        runs = np.split(pooled, 4)
        old, new = R.calibrate(runs, S.gap, S.budget, S.spd), R2.calibrate(runs, S.gap, S.budget, S.spd)
        if abs(old - cfg["tau0"]) > 1e-9 * max(1.0, abs(old)):
            raise SystemExit(f"mode {mode}: the registered tau0 is not reproduced from the cached calibration scores")
        allowed = S.budget * len(pooled) / S.spd
        cand = np.unique(np.quantile(pooled, 1 - np.logspace(-7, -0.7, 300)))
        breaks = [float(c) for c in cand if c > old and sum(len(R.episodes(r > c, S.gap)) for r in runs) > allowed]
        out[f"mode_{mode}"] = {"tau0_registered": float(old), "tau0_calibrate_v2": float(new), "ratio_v2_over_registered": float(new / old),
                               "candidates_above_tau0_that_break_the_budget": len(breaks),
                               "exceedance_rate_at_tau0": float((pooled > old).mean())}
        print("mode", mode, out[f"mode_{mode}"], flush=True)
    return out


def analyse(parts):
    reg = registered()
    modes = {m: load(m) for m in TD.MODES}
    out = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {
        "schema_version": "threshold-transfer-tt1f-tep-v1",
        "status": "exploratory, post-hoc: Tennessee Eastman data of tt1d, opened a second time (ledgered)",
        "plan": "docs/research/threshold_transfer_tt1f_dev_plan.md"}
    if "A" in parts:
        out["matched_operating_points"] = matched(reg, modes)
    if "B" in parts:
        out["trace"] = trace(modes)
    if "C" in parts:
        out["spot_under_frog"] = spot_frog(reg, modes)
    if "K" in parts:
        out["calibration_check"] = calibration_check(modes)
    if "F" in parts:
        out["chance_reference"], out["time_to_clear_noise_sequences"], out["peak_scores"] = chance_clear_peaks(reg, modes)
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print("written", OUT)


if __name__ == "__main__":
    if sys.argv[1] == "scores":
        scores()
    else:
        analyse(sys.argv[2] if len(sys.argv) > 2 else "KABCF")
