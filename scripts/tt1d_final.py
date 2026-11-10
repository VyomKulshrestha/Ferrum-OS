#!/usr/bin/env python3
"""tt1d registered study: adaptive alarm thresholds on the Kaspersky Tennessee Eastman attack dataset.

Protocol: docs/research/threshold_transfer_tt1d_protocol.json. Modes:
  dry-run   frozen-file digests and ledger eligibility; reads no data
  rehearse  the whole pipeline on development data (rehearsal deployment runs, stand-in events)
  final     refuses if the dataset is in the ledger or a frozen file changed; one access
  final --resume   continues an interrupted final from its per-mode parts (recorded in the ledger)
Per operating mode: the D1 monitor, the model-free D0 score and the PCA reconstruction score D2 are fitted
and calibrated on that mode's attack-free development runs. Final data: every attack run (real events,
every rule) and the sealed attack-free runs (false alarms of every rule; one campaign placement per run:
closed-loop frog, loud pulses, sub-event pulses, each ending in terminal bumps of several magnitudes).
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_telemetry_core as C
import real_telemetry_data as D
import real_telemetry_detect as R
import threshold_rules as T
import threshold_rules_tt1d as RD
import tt1_final as F
import tt1d_data as TD

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs/research/threshold_transfer_tt1d_protocol.json"
RESULT = ROOT / "docs/research/threshold_transfer_tt1d_result_tep59.json"
REHEARSAL = ROOT / "target/real-telemetry/tt1d-rehearsal"
PARTS = ROOT / "target/real-telemetry/tt1d-final"
DATASET = "tep59"

RULES = RD.Rules(TD.STEP_SECONDS)
SPD, GAP, WINDOW, BUDGET = RULES.steps_per_day, RULES.gap, RULES.gap, 2.0
steps = lambda seconds: round(seconds / TD.STEP_SECONDS)
TERMINAL, LEAD, CAMPAIGN = steps(600), steps(3600), RULES.steps_per_day
MAGS = (1.05, 1.25, 1.5, 2.0)
FROG_FRAC = 0.97
LOUD_EVERY, LOUD_W, LOUD_H = steps(7200), steps(120), 2.0     # 12 pulses a day of 2 tau0, each an event
SUBL_EVERY, SUBL_W, SUBL_H = steps(1800), steps(45), 2.0      # 48 pulses a day of 2 tau_t, each below an event
SEED, BOOT = 7, 10_000
SCORES = ("D1", "D0", "D2")
PCA_VARIANCE = 0.95

D1_RULES = ["frozen", "tracker", "tracker_slow", "tracker_tau", "daily", "tighten_only", "daily_excl",
            "tracker_hold", "tracker_capped", "spot_gr", "static_1.1", "static_1.25", "static_1.5",
            "tracker_ceil_1.1", "tracker_ceil_1.25", "tracker_ceil_1.5", "daily_ceil_1.25", "spot_gr_ceil_1.25",
            "spot_gate6", "spot_gate24"]
SIDE_RULES = ["frozen", "tracker", "daily", "daily_excl", "tracker_capped", "spot_gr", "tracker_ceil_1.25"]
CAMPAIGNS = {
    "frog": ["frozen", "spot_gr", "spot_gr_ceil_1.25", "spot_gate6", "spot_gate24", "daily_excl",
             "tracker_capped", "tracker_ceil_1.25"],
    "loud": ["frozen", "tracker", "daily", "daily_excl", "tracker_hold", "tracker_capped", "tracker_ceil_1.25",
             "daily_ceil_1.25", "spot_gr"],
    "subl": ["frozen", "tracker", "daily", "daily_excl", "tracker_hold", "tracker_capped", "tracker_ceil_1.25",
             "daily_ceil_1.25", "spot_gr"],
}
FROZEN_FILES = ["scripts/tt1d_final.py", "scripts/tt1d_data.py", "scripts/threshold_rules_tt1d.py",
                "scripts/threshold_rules_tt1e.py", "scripts/threshold_rules_tt1c.py", "scripts/threshold_rules_ext.py",
                "scripts/threshold_online.py", "scripts/threshold_rules.py", "scripts/tt1_final.py",
                "scripts/threshold_transfer_dev.py", "scripts/real_telemetry_core.py", "scripts/real_telemetry_data.py",
                "scripts/real_telemetry_detect.py", "scripts/real_telemetry_dev.py", "scripts/real_telemetry_injections.py"]
assert SUBL_W < RULES.event_l <= LOUD_W


def digests():
    return {f: hashlib.sha256((ROOT / f).read_bytes().replace(b"\r\n", b"\n")).hexdigest() for f in FROZEN_FILES}


# ---------------------------------------------------------------- scores
class PCAScore:
    """D2: residual of the scaled sensors after projection on the leading principal components."""

    def __init__(self, fit_z):
        n = sum(len(z) for z in fit_z)
        self.mu = sum(z.sum(0, dtype=np.float64) for z in fit_z) / n
        cov = np.zeros((len(self.mu), len(self.mu)))
        for z in fit_z:
            for a in range(0, len(z), 100_000):
                c = z[a:a + 100_000].astype(np.float64) - self.mu
                cov += c.T @ c
        w, v = np.linalg.eigh(cov / (n - 1))
        order = np.argsort(w)[::-1]
        w, v = np.maximum(w[order], 0), v[:, order]
        self.k = int(np.searchsorted(np.cumsum(w) / w.sum(), PCA_VARIANCE) + 1)
        self.P = v[:, :self.k]
        self.sig = None

    def _resid(self, z):
        c = z.astype(np.float64) - self.mu
        return c - (c @ self.P) @ self.P.T

    def scales(self, scale_z):
        self.sig = np.concatenate([self._resid(z) for z in scale_z]).std(0) + 1e-3

    def raw(self, z):
        a = np.abs(self._resid(z)) / self.sig
        return (-np.sort(-a, 1)[:, :3]).mean(1)


def monitor(mode):
    """Fit and calibrate the three scores on one mode's development runs."""
    dev = {role: TD.dev_runs(mode, role) for role in ("fit", "scale", "calib")}
    kx, ku = F.varying_columns(dev["fit"] + dev["scale"] + dev["calib"])
    cut = lambda runs: [(x[:, kx], u[:, ku]) for x, u in runs]
    scorer, pack, fit, _, _ = F.fit_monitor(cut(dev["fit"]), cut(dev["scale"]))
    pca = PCAScore([z for z, _ in fit])
    pca.scales([z for z, _ in pack(cut(dev["scale"]))])

    def score(x, u):
        z, v = pack([(x[:, kx], u[:, ku])])[0]
        raw = scorer.raw(z, v)[0]
        out = {}
        for key, a in (("D1", raw["D1"]), ("D0", raw["D0"]), ("D2", pca.raw(z))):
            s = R.smooth(a, WINDOW)
            s[:R.WARMUP] = np.nan
            out[key] = s
        return out

    cal = [score(x, u) for x, u in dev["calib"]]
    cfgs, pooled = {}, {}
    for key in SCORES:
        arrs = [c[key][np.isfinite(c[key])] for c in cal]
        pooled[key] = np.concatenate(arrs)
        cfgs[key] = F.thresholds(pooled[key], R.calibrate(arrs, GAP, BUDGET, SPD), F.ETA_MULT, 0.999)
    info = {"sensors": int(len(kx)), "actions": int(len(ku)), "pca_components": pca.k,
            "dropped_constant_sensors": [int(i) for i in range(41) if i not in set(kx)],
            "dropped_constant_actions": [int(i) for i in range(12) if i not in set(ku)]}
    return score, cfgs, pooled, info


def clean(s):
    return np.where(np.isfinite(s), s, -np.inf)


# ---------------------------------------------------------------- rules over a stream
def path(rule, cfg, calib, s):
    m = RULES.make(rule, cfg, calib)
    tau = np.empty(len(s))
    for i, x in enumerate(s):
        tau[i] = m.tau()
        m.update(x)
    return tau


def stream_rows(s, key, cfg, calib, rules):
    """Every rule over one stream: per-event detection (any alarm; alarm episode starting inside), the
    threshold at event onset, false-alarm episodes, alarm steps outside labels."""
    ev = TD.events(key)
    lab = np.asarray(key) != 0
    out = {}
    for r in rules:
        tau = path(r, cfg, calib, s)
        alarm = s > tau
        eps = T._episodes(alarm, GAP)
        starts = np.zeros(len(s), bool)
        for a, _ in eps:
            starts[a] = True
        out[r] = {"found": [bool(alarm[a:b].any()) for a, b, _ in ev],
                  "onset": [bool(starts[a:b].any()) for a, b, _ in ev],
                  "inflation": [float(tau[a] / cfg["tau0"]) for a, b, _ in ev],
                  "fa": int(sum(1 for a, b in eps if not lab[a:b].any())),
                  "alarm_unlabelled": int((alarm & ~lab).sum()),
                  "tau_end": float(tau[-1] / cfg["tau0"])}
    return ev, int((~lab).sum()), out


# ---------------------------------------------------------------- campaigns on attack-free streams
def play(rule, cfg, calib, s, end, mode):
    """Run the rule online to the terminal window, then try every terminal magnitude on a copy of its state.
    mode: control | frog (0.97 x the deployed threshold) | loud (2 tau0 pulses that are events) | subl
    (2 tau_t pulses shorter than an event)."""
    m = RULES.make(rule, cfg, calib)
    c_start, c_end = end - LEAD - CAMPAIGN, end - LEAD
    tau0 = cfg["tau0"]
    alarms, episodes, longest, first, last = 0, 0, 0, None, None
    for i in range(end):
        tau = m.tau()
        x = s[i]
        if mode != "control" and c_start <= i < c_end and x != -np.inf:
            k = i - c_start
            if mode == "frog":
                x = max(x, FROG_FRAC * tau)
            elif mode == "loud":
                if k % LOUD_EVERY < LOUD_W:
                    x = max(x, LOUD_H * tau0)
            elif k % SUBL_EVERY < SUBL_W:
                x = max(x, SUBL_H * tau)
            if x > tau:
                alarms += 1
                if last is None or i - last > GAP:
                    episodes += 1
                    first = i
                last = i
                longest = max(longest, i - first + 1)
        m.update(x)
    tau_end = m.tau()
    hits = {}
    for mag in MAGS:
        mm, hit = copy.deepcopy(m), False
        bump = mag * tau0
        for i in range(end, end + TERMINAL):
            x = max(s[i], bump)
            hit |= bool(x > mm.tau())
            mm.update(x)
        hits[mag] = hit
    return hits, float(tau_end / tau0), alarms, episodes, longest


def campaigns(name, s, cfg, calib):
    """One placement on one attack-free stream, seeded by the run id."""
    ident = int(re.search(r"_id_(\d+)", name).group(1))
    rng = np.random.default_rng(SEED + 707 + ident)
    c0 = int(rng.integers(SPD // 2, len(s) - CAMPAIGN - LEAD - TERMINAL))
    end = c0 + CAMPAIGN + LEAD
    out = {"campaign_start": c0, "terminal_start": end}
    control = {r: play(r, cfg, calib, s, end, "control")[0] for r in dict.fromkeys(sum(CAMPAIGNS.values(), []))}
    for attack, rules in CAMPAIGNS.items():
        out[attack] = {}
        for r in rules:
            hits, infl, alarms, episodes, longest = play(r, cfg, calib, s, end, attack)
            out[attack][r] = {"after": [bool(hits[m]) for m in MAGS], "control": [bool(control[r][m]) for m in MAGS],
                              "inflation": infl, "alarm_steps": alarms, "alarm_episodes": episodes,
                              "longest_episode": longest}
    return out


def clean_false_alarms(s, cfg, calib, rules):
    zero = np.zeros(len(s), np.int8)
    _, n, rows = stream_rows(s, zero, cfg, calib, rules)
    return {r: {"fa": v["fa"], "alarm_steps": v["alarm_unlabelled"], "tau_end": v["tau_end"]} for r, v in rows.items()}, n


# ---------------------------------------------------------------- one mode
def stand_in(streams):
    """Rehearsal only: three score bumps per stream (1.5 x its 99.9th percentile, 600 s) as labelled events."""
    out = []
    for name, sc in streams:
        n = len(sc["D1"])
        key = np.zeros(n, np.int8)
        sc = {k: v.copy() for k, v in sc.items()}
        for j, frac in enumerate((0.3, 0.5, 0.7)):
            t = int(frac * n)
            key[t:t + TERMINAL] = 1 + j % 2
            for k in sc:
                sc[k][t:t + TERMINAL] = np.maximum(sc[k][t:t + TERMINAL], 1.5 * np.nanquantile(sc[k], 0.999))
        out.append((name, 0, sc, key))
    return out


def run_mode(mode, final):
    t0 = time.time()
    score, cfgs, pooled, info = monitor(mode)
    print("mode", mode, "monitor ready", round(time.time() - t0), "s", flush=True)
    out = {"mode": mode, "monitor": info, "thresholds": cfgs, "attack_runs": [], "sealed_runs": []}
    if final:
        attack_iter = ((name, kind, score(x, u), key) for name, kind, x, u, key in TD.attack_runs(mode))
        normal = [(name, score(x, u)) for name, x, u in TD.sealed_runs(mode)]
    else:
        normal = [(name, score(x, u)) for name, (x, u) in
                  zip(TD.clean_roles()[mode]["deploy"], TD.dev_runs(mode, "deploy"))]
        attack_iter = iter(stand_in(normal))
    for name, kind, sc, key in attack_iter:
        row = {"name": name, "type": kind, "steps": int(len(key)), "scores": {}}
        for sk in SCORES:
            ev, unlabelled, rows = stream_rows(clean(sc[sk]), key, cfgs[sk], pooled[sk],
                                               D1_RULES if sk == "D1" else SIDE_RULES)
            row["events"], row["unlabelled_steps"] = ev, unlabelled
            row["scores"][sk] = rows
        out["attack_runs"].append(row)
        print("mode", mode, "attack run", name, len(row["events"]), "events", round(time.time() - t0), "s", flush=True)
    for name, sc in normal:
        s = clean(sc["D1"])
        fa, n = clean_false_alarms(s, cfgs["D1"], pooled["D1"], D1_RULES)
        out["sealed_runs"].append({"name": name, "steps": n, "false_alarms": fa,
                                   "campaigns": campaigns(name, s, cfgs["D1"], pooled["D1"])})
        print("mode", mode, "attack-free run", name, round(time.time() - t0), "s", flush=True)
    out["seconds"] = round(time.time() - t0)
    return out


# ---------------------------------------------------------------- pooling and gates
def cluster_bootstrap(groups, base, other):
    """recall(other) - recall(base) with whole runs resampled (events of a run are not independent)."""
    ids = sorted(set(groups))
    if not ids:
        return None
    idx = {g: i for i, g in enumerate(ids)}
    n, a, b = np.zeros(len(ids)), np.zeros(len(ids)), np.zeros(len(ids))
    for g, x, y in zip(groups, base, other):
        n[idx[g]] += 1; a[idx[g]] += x; b[idx[g]] += y
    rng = np.random.default_rng(0)
    pick = rng.integers(0, len(ids), (BOOT, len(ids)))
    diff = (b[pick].sum(1) - a[pick].sum(1)) / n[pick].sum(1)
    return {"events": int(n.sum()), "runs": len(ids), "base_detected": int(a.sum()), "rule_detected": int(b.sum()),
            "recall_difference": float((b.sum() - a.sum()) / n.sum()),
            "recall_difference_interval": [float(v) for v in np.quantile(diff, [0.025, 0.975])]}


def pooled_events(modes, score, rules):
    """Per rule: detection lists over every event with its run, order in the run and attack type."""
    meta, per = [], {r: {"found": [], "onset": [], "inflation": []} for r in rules}
    fa = {r: 0 for r in rules}
    alarm_steps = {r: 0 for r in rules}
    unlabelled = 0
    for m in modes:
        for run in m["attack_runs"]:
            unlabelled += run["unlabelled_steps"]
            meta += [{"run": run["name"], "type": run["type"], "order": i, "steps": b - a}
                     for i, (a, b, _) in enumerate(run["events"])]
            for r in rules:
                v = run["scores"][score][r]
                for k in ("found", "onset", "inflation"):
                    per[r][k] += v[k]
                fa[r] += v["fa"]
                alarm_steps[r] += v["alarm_unlabelled"]
    return meta, per, fa, alarm_steps, unlabelled


def summarise(modes, score, rules):
    meta, per, fa, alarm_steps, unlabelled = pooled_events(modes, score, rules)
    runs = [e["run"] for e in meta]
    sel = {"all": [True] * len(meta), "first": [e["order"] == 0 for e in meta],
           "follower": [e["order"] > 0 for e in meta]}
    out = {"events": len(meta), "first_events": int(sum(sel["first"])), "follower_events": int(sum(sel["follower"])),
           "runs": len(set(runs)), "unlabelled_days": unlabelled / SPD, "rules": {}}
    for r in rules:
        row = {"fa_per_day": fa[r] / max(unlabelled / SPD, 1e-9), "unlabelled_alarm_share": alarm_steps[r] / max(unlabelled, 1),
               "median_onset_inflation": float(np.median(per[r]["inflation"])) if meta else None}
        for name, mask in sel.items():
            pick = lambda xs: [x for x, k in zip(xs, mask) if k]
            n = int(sum(mask))
            row[name] = {"events": n, "detected": int(sum(pick(per[r]["found"]))),
                         "onset_detected": int(sum(pick(per[r]["onset"])))}
            if r != "frozen" and n:
                g = pick(runs)
                row[name]["vs_frozen"] = cluster_bootstrap(g, pick(per["frozen"]["found"]), pick(per[r]["found"]))
                row[name]["vs_frozen_onset"] = cluster_bootstrap(g, pick(per["frozen"]["onset"]), pick(per[r]["onset"]))
        row["by_type"] = {}
        for kind in sorted({e["type"] for e in meta}):
            mask = [e["type"] == kind for e in meta]
            row["by_type"][str(kind)] = {"events": int(sum(mask)),
                                         "detected": int(sum(x for x, k in zip(per[r]["found"], mask) if k)),
                                         "onset_detected": int(sum(x for x, k in zip(per[r]["onset"], mask) if k))}
        out["rules"][r] = row
    return out


def summarise_campaigns(modes):
    runs = [run for m in modes for run in m["sealed_runs"]]
    out = {"placements": len(runs), "magnitudes_over_tau0": list(MAGS), "attacks": {}}
    rng = np.random.default_rng(0)
    pick = rng.integers(0, max(len(runs), 1), (BOOT, max(len(runs), 1)))
    for attack, rules in CAMPAIGNS.items():
        out["attacks"][attack] = {}
        for r in rules:
            rows = [run["campaigns"][attack][r] for run in runs]
            after = np.array([v["after"] for v in rows], float)
            control = np.array([v["control"] for v in rows], float)
            diff = (after - control)[pick].mean(1)
            infl = [v["inflation"] for v in rows]
            out["attacks"][attack][r] = {
                "after": [float(x) for x in after.mean(0)], "control": [float(x) for x in control.mean(0)],
                "difference_interval": [[float(x) for x in np.quantile(diff[:, j], [0.025, 0.975])] for j in range(len(MAGS))],
                "median_inflation": float(np.median(infl)), "max_inflation": float(np.max(infl)),
                "median_alarm_steps": float(np.median([v["alarm_steps"] for v in rows])),
                "median_alarm_episodes": float(np.median([v["alarm_episodes"] for v in rows])),
                "longest_alarm_episode": int(np.max([v["longest_episode"] for v in rows]))}
    days = sum(run["steps"] for run in runs) / SPD
    out["attack_free"] = {"days": days, "rules": {
        r: {"fa_per_day": sum(run["false_alarms"][r]["fa"] for run in runs) / max(days, 1e-9),
            "fa_ratio_to_budget": sum(run["false_alarms"][r]["fa"] for run in runs) / max(days, 1e-9) / BUDGET,
            "alarm_share": sum(run["false_alarms"][r]["alarm_steps"] for run in runs) / max(days * SPD, 1),
            "median_tau_end": float(np.median([run["false_alarms"][r]["tau_end"] for run in runs]))}
        for r in D1_RULES}}
    return out


NONINF, DROP, HOLD, EVALUABLE = 0.10, 0.5, 0.1, 0.6


def gates(real, camp):
    """Hypotheses of docs/research/threshold_transfer_tt1d_protocol.json, computed from the pooled result."""
    rr = real["D1"]["rules"]
    upper = lambda row: row is not None and row["recall_difference_interval"][1] < 0
    lower = lambda row: row is not None and row["recall_difference_interval"][0] >= -NONINF
    g = {}
    f = rr["tracker"]["follower"]
    g["H1a_tracker_loses_followers_any_alarm"] = bool(upper(f.get("vs_frozen")))
    g["H1b_tracker_loses_followers_onset"] = bool(upper(f.get("vs_frozen_onset")))
    g["H1c_tracker_holds_first_events"] = bool(lower(rr["tracker"]["first"].get("vs_frozen")))
    g["H2_stronger_rules_hold_followers"] = bool(all(lower(rr[r]["follower"].get("vs_frozen"))
                                                     for r in ("daily_excl", "tracker_capped")))
    g["H3_ceiling_bounds_loss"] = bool(all(
        rr[f"tracker_ceil_{k}"]["all"]["detected"] >= rr[f"static_{k}"]["all"]["detected"] for k in ("1.1", "1.25", "1.5")))
    at = {m: i for i, m in enumerate(MAGS)}

    def blinded(attack, rule, mag=1.05):
        v = camp["attacks"][attack][rule]
        i = at[mag]
        if v["control"][i] < EVALUABLE:
            return None
        return bool(v["after"][i] <= v["control"][i] - DROP and v["difference_interval"][i][1] < 0)

    def holds(attack, rule, mag=1.05):
        v = camp["attacks"][attack][rule]
        i = at[mag]
        return bool(v["after"][i] >= v["control"][i] - HOLD)

    def verdict(targets, keepers):
        if any(t is None for t in targets):
            return "not evaluable"
        return bool(all(targets) and all(keepers))

    g["H4_frog_blinds_spot"] = verdict([blinded("frog", "spot_gr")],
                                       [holds("frog", "frozen"), holds("frog", "spot_gr_ceil_1.25", 1.5)])
    g["H5_loud_pulses_blind_tracker"] = verdict([blinded("loud", "tracker")],
                                                [holds("loud", "frozen"), holds("loud", "daily_excl")])
    g["H6_sub_event_pulses_blind_excluding_rules"] = verdict(
        [blinded("subl", "daily_excl"), blinded("subl", "tracker_hold")],
        [holds("subl", "frozen"), holds("subl", "tracker_ceil_1.25", 1.5), holds("subl", "daily_ceil_1.25", 1.5)])
    g["primary_success"] = bool(g["H1a_tracker_loses_followers_any_alarm"] and g["H1b_tracker_loses_followers_onset"])
    return g


def assemble(modes, mode_name):
    real = {"D1": summarise(modes, "D1", D1_RULES), "D0": summarise(modes, "D0", SIDE_RULES),
            "D2": summarise(modes, "D2", SIDE_RULES)}
    camp = summarise_campaigns(modes)
    settings = {"step_seconds": TD.STEP_SECONDS, "steps_per_day": SPD, "smoothing_steps": WINDOW, "gap_steps": GAP,
                "event_steps": RULES.event_l, "hold_steps": RULES.hold, "budget_per_day": BUDGET,
                "terminal_steps": TERMINAL, "lead_steps": LEAD, "campaign_steps": CAMPAIGN, "frog_fraction": FROG_FRAC,
                "loud": [LOUD_EVERY, LOUD_W, LOUD_H], "sub_event": [SUBL_EVERY, SUBL_W, SUBL_H]}
    return {"dataset": DATASET, "mode": mode_name, "settings": settings, "real_events": real, "campaigns": camp,
            "gates": gates(real, camp), "modes": modes}


# ---------------------------------------------------------------- entry points
def ledger():
    if not D.FINAL_LEDGER.exists():
        return set()
    return {json.loads(line)["dataset"] for line in D.FINAL_LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()}


def check_frozen():
    if not PROTOCOL.exists():
        return ["protocol not registered"]
    frozen = json.loads(PROTOCOL.read_text(encoding="utf-8"))["frozen_file_sha256"]
    now = digests()
    return [f for f in FROZEN_FILES if frozen.get(f) != now[f]]


def show(out):
    r = out["real_events"]["D1"]
    print("events", r["events"], "first", r["first_events"], "followers", r["follower_events"], "runs", r["runs"])
    for name, v in r["rules"].items():
        fo = v["follower"]
        ci = fo.get("vs_frozen", {}) or {}
        co = fo.get("vs_frozen_onset", {}) or {}
        print(f"  {name:18s} all {v['all']['detected']}/{v['all']['events']} on {v['all']['onset_detected']}"
              f" | first {v['first']['detected']} | followers {fo['detected']}/{fo['events']} on {fo['onset_detected']}"
              f" {ci.get('recall_difference_interval')} onset {co.get('recall_difference_interval')}"
              f" | fa/day {v['fa_per_day']:.2f} share {v['unlabelled_alarm_share']:.3f}")
    c = out["campaigns"]
    print("placements", c["placements"], "terminal magnitudes", c["magnitudes_over_tau0"])
    for attack, rules in c["attacks"].items():
        for name, v in rules.items():
            print(f"  {attack:5s}{name:18s} after {v['after']} control {v['control']} infl med {v['median_inflation']:.3g}"
                  f" max {v['max_inflation']:.3g} longest episode {v['longest_alarm_episode']}")
    print("attack-free days", round(c["attack_free"]["days"], 1),
          {k: round(v["fa_ratio_to_budget"], 2) for k, v in c["attack_free"]["rules"].items()})
    print("gates", out["gates"])


def main():
    mode = sys.argv[1]
    resume = "--resume" in sys.argv
    if mode == "dry-run":
        seen = ledger()
        print("ledger:", {d: ("ALREADY OPENED" if d in seen else "not opened") for d in TD.LEDGER_IDS})
        bad = check_frozen()
        print("frozen files:", "all match the registration" if not bad else f"MISMATCH {bad}")
        return
    if mode == "rehearse":
        modes = [run_mode(m, final=False) for m in (TD.MODES if len(sys.argv) < 3 else [int(sys.argv[2])])]
        out = assemble(modes, "rehearsal")
        REHEARSAL.mkdir(parents=True, exist_ok=True)
        (REHEARSAL / f"{DATASET}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
        show(out)
        return
    bad = check_frozen()
    if bad:
        raise SystemExit(f"REFUSE: frozen files changed or protocol missing: {bad}")
    opened = set(TD.LEDGER_IDS) & ledger()
    if opened and not resume:
        raise SystemExit(f"REFUSE: {sorted(opened)} already in {D.FINAL_LEDGER}")
    if resume and not (opened and any(PARTS.glob("mode_*.json"))):
        raise SystemExit("REFUSE: nothing to resume")
    PARTS.mkdir(parents=True, exist_ok=True)
    TD.open_final("tt1d final: registered study (threshold-transfer-tt1d)" +
                  (" -- RESUME of an interrupted run from its per-mode parts" if resume else ""))
    modes = []
    for m in TD.MODES:
        part = PARTS / f"mode_{m}.json"
        if resume and part.exists():
            modes.append(json.loads(part.read_text(encoding="utf-8")))
            continue
        modes.append(run_mode(m, final=True))
        part.write_text(json.dumps(modes[-1]), encoding="utf-8")
    out = assemble(modes, "final")
    out["frozen_file_sha256"] = digests()
    out["resumed"] = resume
    RESULT.write_text(json.dumps({"schema_version": "threshold-transfer-tt1d-result", "protocol": PROTOCOL.name, **out},
                                 indent=1) + "\n", encoding="utf-8")
    show(out)
    print("wrote", RESULT)


if __name__ == "__main__":
    main()
