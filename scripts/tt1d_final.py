#!/usr/bin/env python3
"""tt1d registered study: adaptive alarm thresholds on two never-opened datasets.

Protocol: docs/research/threshold_transfer_tt1d_protocol.json. Datasets:
  tep59    Kaspersky Tennessee Eastman attack dataset: 142 attack runs in 7 operating modes, 8 sealed
           attack-free runs of 120 h per mode. One monitor per mode.
  provics  ProvICS: one attack recording with 32 ground-truth events, and the sealed last quarter of the
           attack-free recording.
Commands:
  dry-run  <dataset>            frozen-file digests and ledger eligibility; reads no data
  rehearse <dataset> [unit]     the whole pipeline on development data with stand-in events
  final    <dataset> [--resume] refuses if the dataset is in the ledger or a frozen file changed; one
                                access. --resume (tep59 only) continues an interrupted final from its
                                per-mode parts and records that in the ledger.
Per unit (a TEP mode, or ProvICS): the D1 monitor, the model-free D0 score and the PCA reconstruction score
D2 are fitted and calibrated on attack-free development data. Final data: the attack recordings (every
rule over every stream; per-event detection under the any-alarm and the onset count) and the sealed
attack-free streams (false alarms of every rule, and campaign placements: closed-loop frog, loud pulses,
sub-event pulses, each ending in terminal bumps of several magnitudes, with a no-campaign control).
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
REHEARSAL = ROOT / "target/real-telemetry/tt1d-rehearsal"
PARTS = ROOT / "target/real-telemetry/tt1d-final"
MAGS = (1.05, 1.25, 1.5, 2.0)
FROG_FRAC = 0.97
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


class Setup:
    """Every duration of the study in steps of one dataset."""

    def __init__(self, name, step, campaign_seconds, settle_seconds, ledger_ids, cluster):
        self.name, self.step, self.ledger_ids, self.cluster = name, step, ledger_ids, cluster
        self.rules = RD.Rules(step)
        self.spd, self.gap, self.window, self.budget = self.rules.steps_per_day, self.rules.gap, self.rules.gap, 2.0
        n = lambda seconds: round(seconds / step)
        self.terminal, self.lead, self.campaign, self.settle = n(600), n(3600), n(campaign_seconds), n(settle_seconds)
        self.loud = (n(7200), n(120), 2.0)        # a 2 tau0 pulse of 120 s every 2 h: each one is an event
        self.subl = (n(1800), n(45), 2.0)         # a 2 tau_t pulse of 45 s every 30 min: shorter than an event
        assert self.subl[1] < self.rules.event_l <= self.loud[1]

    def settings(self):
        return {"step_seconds": self.step, "steps_per_day": self.spd, "smoothing_steps": self.window,
                "gap_steps": self.gap, "event_steps": self.rules.event_l, "hold_steps": self.rules.hold,
                "budget_per_day": self.budget, "terminal_steps": self.terminal, "lead_steps": self.lead,
                "campaign_steps": self.campaign, "settle_steps": self.settle, "frog_fraction": FROG_FRAC,
                "loud_every_width_height": list(self.loud), "sub_event_every_width_height": list(self.subl),
                "terminal_magnitudes_over_tau0": list(MAGS)}


SETUPS = {"tep59": Setup("tep59", TD.STEP_SECONDS, 86400, 43200, TD.LEDGER_IDS, cluster=True),
          "provics": Setup("provics", TD.P_STEP_SECONDS, 21600, 1800, TD.P_LEDGER_IDS, cluster=False)}
PROVICS_PLACEMENTS = 6


def result_path(name):
    return ROOT / "docs/research" / f"threshold_transfer_tt1d_result_{name}.json"


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


def fit_scores(S, fit, scale, calib):
    """Fit and calibrate the three scores on attack-free development runs, each a list of (X, U)."""
    kx, ku = F.varying_columns(fit + scale + calib)
    cut = lambda runs: [(x[:, kx], u[:, ku]) for x, u in runs]
    scorer, pack, packed_fit, _, _ = F.fit_monitor(cut(fit), cut(scale))
    pca = PCAScore([z for z, _ in packed_fit])
    pca.scales([z for z, _ in pack(cut(scale))])

    def score(x, u):
        z, v = pack([(x[:, kx], u[:, ku])])[0]
        raw = scorer.raw(z, v)[0]
        out = {}
        for key, a in (("D1", raw["D1"]), ("D0", raw["D0"]), ("D2", pca.raw(z))):
            s = R.smooth(a, S.window)
            s[:R.WARMUP] = np.nan
            out[key] = s
        return out

    cal = [score(x, u) for x, u in calib]
    cfgs, pooled = {}, {}
    for key in SCORES:
        arrs = [c[key][np.isfinite(c[key])] for c in cal]
        pooled[key] = np.concatenate(arrs)
        cfgs[key] = F.thresholds(pooled[key], R.calibrate(arrs, S.gap, S.budget, S.spd), F.ETA_MULT, 0.999)
    n_x, n_u = fit[0][0].shape[1], fit[0][1].shape[1]
    info = {"sensors": int(len(kx)), "actions": int(len(ku)), "pca_components": pca.k,
            "calibration_steps": int(len(pooled["D1"])),
            "dropped_constant_sensors": [int(i) for i in range(n_x) if i not in set(kx)],
            "dropped_constant_actions": [int(i) for i in range(n_u) if i not in set(ku)]}
    return score, cfgs, pooled, info


def clean(s, valid=None):
    """Scores as the rules see them: warm-up and invalid steps are -inf and cannot alarm."""
    ok = np.isfinite(s) if valid is None else np.isfinite(s) & valid
    return np.where(ok, s, -np.inf)


# ---------------------------------------------------------------- rules over a stream
def path(S, rule, cfg, calib, s):
    m = S.rules.make(rule, cfg, calib)
    tau = np.empty(len(s))
    for i, x in enumerate(s):
        tau[i] = m.tau()
        m.update(x)
    return tau


def stream_rows(S, s, events, lab, cfg, calib, rules):
    """Every rule over one stream. events: (start, end, ...) with end exclusive; lab: labelled steps.
    Per event: any alarm inside; an alarm episode starting inside; the threshold at its start."""
    out = {}
    for r in rules:
        tau = path(S, r, cfg, calib, s)
        alarm = s > tau
        eps = T._episodes(alarm, S.gap)
        starts = np.zeros(len(s), bool)
        for a, _ in eps:
            starts[a] = True
        out[r] = {"found": [bool(alarm[e[0]:e[1]].any()) for e in events],
                  "onset": [bool(starts[e[0]:e[1]].any()) for e in events],
                  "inflation": [float(tau[e[0]] / cfg["tau0"]) for e in events],
                  "fa": int(sum(1 for a, b in eps if not lab[a:b].any())),
                  "alarm_unlabelled": int((alarm & ~lab).sum()),
                  "tau_end": float(tau[-1] / cfg["tau0"])}
    return out


# ---------------------------------------------------------------- campaigns on attack-free streams
def play(S, rule, cfg, calib, s, end, mode):
    """Run the rule online to the terminal window, then try every terminal magnitude on a copy of its state.
    mode: control | frog (0.97 x the deployed threshold) | loud (2 tau0 pulses that are events) | subl
    (2 tau_t pulses shorter than an event)."""
    m = S.rules.make(rule, cfg, calib)
    c_start, c_end = end - S.lead - S.campaign, end - S.lead
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
                if k % S.loud[0] < S.loud[1]:
                    x = max(x, S.loud[2] * tau0)
            elif k % S.subl[0] < S.subl[1]:
                x = max(x, S.subl[2] * tau)
            if x > tau:
                alarms += 1
                if last is None or i - last > S.gap:
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
        for i in range(end, end + S.terminal):
            x = max(s[i], bump)
            hit |= bool(x > mm.tau())
            mm.update(x)
        hits[mag] = hit
    return hits, float(tau_end / tau0), alarms, episodes, longest


def placement(S, s, cfg, calib, c0):
    end = c0 + S.campaign + S.lead
    out = {"campaign_start": int(c0), "terminal_start": int(end)}
    control = {r: play(S, r, cfg, calib, s, end, "control")[0] for r in dict.fromkeys(sum(CAMPAIGNS.values(), []))}
    for attack, rules in CAMPAIGNS.items():
        out[attack] = {}
        for r in rules:
            hits, infl, alarms, episodes, longest = play(S, r, cfg, calib, s, end, attack)
            out[attack][r] = {"after": [bool(hits[m]) for m in MAGS], "control": [bool(control[r][m]) for m in MAGS],
                              "inflation": infl, "alarm_steps": alarms, "alarm_episodes": episodes,
                              "longest_episode": longest}
    return out


def room(S, s):
    """Last admissible campaign start on a stream (exclusive)."""
    return len(s) - S.campaign - S.lead - S.terminal


def clean_false_alarms(S, s, cfg, calib, rules):
    rows = stream_rows(S, s, [], np.zeros(len(s), bool), cfg, calib, rules)
    return {r: {"fa": v["fa"], "alarm_steps": v["alarm_unlabelled"], "tau_end": v["tau_end"]} for r, v in rows.items()}


def score_attack_run(S, name, kind, sc, events, lab, cfgs, pooled, valid=None):
    row = {"name": name, "type": kind, "steps": int(len(lab)), "events": [list(e) for e in events],
           "unlabelled_steps": int((~lab).sum() if valid is None else (~lab & valid).sum()), "scores": {}}
    for sk in SCORES:
        row["scores"][sk] = stream_rows(S, clean(sc[sk], valid), events, lab, cfgs[sk], pooled[sk],
                                        D1_RULES if sk == "D1" else SIDE_RULES)
    return row


def stand_in(S, sc, count):
    """Rehearsal only: score bumps (1.5 x the stream's 99.9th percentile, one terminal length) as events."""
    n = len(sc["D1"])
    sc = {k: v.copy() for k, v in sc.items()}
    events = []
    for j in range(count):
        t = int((0.25 + 0.5 * j / max(count - 1, 1)) * n)
        events.append((t, t + S.terminal, 1 + j % 2))
        for k in sc:
            sc[k][t:t + S.terminal] = np.maximum(sc[k][t:t + S.terminal], 1.5 * np.nanquantile(sc[k], 0.999))
    lab = np.zeros(n, bool)
    for a, b, _ in events:
        lab[a:b] = True
    return sc, events, lab


# ---------------------------------------------------------------- units
def tep_unit(S, mode, final):
    t0 = time.time()
    dev = {role: TD.dev_runs(mode, role) for role in ("fit", "scale", "calib")}
    score, cfgs, pooled, info = fit_scores(S, dev["fit"], dev["scale"], dev["calib"])
    del dev
    print("mode", mode, "monitor ready", round(time.time() - t0), "s", flush=True)
    out = {"unit": f"mode_{mode}", "monitor": info, "thresholds": cfgs, "attack_runs": [], "sealed_runs": []}
    if final:
        attacks = ((name, kind, score(x, u), key) for name, kind, x, u, key in TD.attack_runs(mode))
        normal = [(name, score(x, u)) for name, x, u in TD.sealed_runs(mode)]
    else:
        normal = [(name, score(x, u)) for name, (x, u) in
                  zip(TD.clean_roles()[mode]["deploy"], TD.dev_runs(mode, "deploy"))]
        attacks = ((name, 0, sc, None) for name, sc in normal)
    for name, kind, sc, key in attacks:
        if key is None:
            sc, events, lab = stand_in(S, sc, 3)
        else:
            events, lab = TD.events(key), np.asarray(key) != 0
        out["attack_runs"].append(score_attack_run(S, name, kind, sc, events, lab, cfgs, pooled))
        print("mode", mode, "attack run", name, len(events), "events", round(time.time() - t0), "s", flush=True)
    for name, sc in normal:
        s = clean(sc["D1"])
        ident = int(re.search(r"_id_(\d+)", name).group(1))
        c0 = int(np.random.default_rng(SEED + 707 + ident).integers(S.settle, room(S, s)))
        out["sealed_runs"].append({"name": name, "steps": int(len(s)),
                                   "false_alarms": clean_false_alarms(S, s, cfgs["D1"], pooled["D1"], D1_RULES),
                                   "campaigns": [placement(S, s, cfgs["D1"], pooled["D1"], c0)]})
        print("mode", mode, "attack-free run", name, round(time.time() - t0), "s", flush=True)
    out["seconds"] = round(time.time() - t0)
    return out


def provics_unit(S, final):
    t0 = time.time()
    segs, cols = TD.provics_dev()
    names = ("fit", "scale", "calib") + (() if final else ("deploy",))
    parts = F.split(segs, F.FINAL_CUTS if final else F.REHEARSAL_CUTS, names, min_len=500)
    score, cfgs, pooled, info = fit_scores(S, parts["fit"], parts["scale"], parts["calib"])
    info["columns"] = cols
    print("provics monitor ready", round(time.time() - t0), "s", flush=True)
    out = {"unit": "provics", "monitor": info, "thresholds": cfgs, "attack_runs": [], "sealed_runs": []}
    if final:
        x, u, valid, events, unobserved = TD.provics_attack()
        sc = score(x, u)
        lab = np.zeros(len(x), bool)
        for e in events:
            lab[e[0]:e[1]] = True
        row = score_attack_run(S, "attack22h", 0, sc, events, lab, cfgs, pooled, valid)
        row["unobserved_events"] = int(unobserved)
        row["invalid_steps"] = int((~valid).sum())
        xs, us, vs = TD.provics_sealed()
        s = clean(score(xs, us)["D1"], vs)
    else:
        xd, ud = max(parts["deploy"], key=lambda p: len(p[0]))
        sc0 = score(xd, ud)
        sc, events, lab = stand_in(S, sc0, 6)
        row = score_attack_run(S, "rehearsal-deployment", 0, sc, events, lab, cfgs, pooled)
        s = clean(sc0["D1"])
    out["attack_runs"].append(row)
    print("provics attack stream", len(row["events"]), "events", round(time.time() - t0), "s", flush=True)
    starts = np.linspace(S.settle, room(S, s) - 1, PROVICS_PLACEMENTS).astype(int)
    out["sealed_runs"].append({"name": "sealed-normal" if final else "rehearsal-deployment", "steps": int(len(s)),
                               "false_alarms": clean_false_alarms(S, s, cfgs["D1"], pooled["D1"], D1_RULES),
                               "campaigns": [placement(S, s, cfgs["D1"], pooled["D1"], int(c0)) for c0 in starts]})
    out["seconds"] = round(time.time() - t0)
    print("provics campaigns done", out["seconds"], "s", flush=True)
    return out


# ---------------------------------------------------------------- pooling and gates
def cluster_bootstrap(groups, base, other):
    """recall(other) - recall(base); whole groups are resampled (a group is a run, or a single event)."""
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
    return {"events": int(n.sum()), "groups": len(ids), "base_detected": int(a.sum()), "rule_detected": int(b.sum()),
            "discordant_base_only": int(sum(1 for x, y in zip(base, other) if x and not y)),
            "discordant_rule_only": int(sum(1 for x, y in zip(base, other) if y and not x)),
            "recall_difference": float((b.sum() - a.sum()) / n.sum()),
            "recall_difference_interval": [float(v) for v in np.quantile(diff, [0.025, 0.975])]}


def summarise(S, units, score, rules):
    meta, per = [], {r: {"found": [], "onset": [], "inflation": []} for r in rules}
    fa, alarm_steps, unlabelled = {r: 0 for r in rules}, {r: 0 for r in rules}, 0
    for unit in units:
        for run in unit["attack_runs"]:
            unlabelled += run["unlabelled_steps"]
            meta += [{"run": run["name"], "type": run["type"] if S.cluster else e[2], "order": i}
                     for i, e in enumerate(run["events"])]
            for r in rules:
                v = run["scores"][score][r]
                for k in ("found", "onset", "inflation"):
                    per[r][k] += v[k]
                fa[r] += v["fa"]
                alarm_steps[r] += v["alarm_unlabelled"]
    groups = [e["run"] for e in meta] if S.cluster else list(range(len(meta)))
    sel = {"all": [True] * len(meta), "first": [e["order"] == 0 for e in meta],
           "follower": [e["order"] > 0 for e in meta]}
    out = {"events": len(meta), "first_events": int(sum(sel["first"])), "follower_events": int(sum(sel["follower"])),
           "runs": len({e["run"] for e in meta}), "unlabelled_days": unlabelled / S.spd,
           "resampling_unit": "run" if S.cluster else "event", "rules": {}}
    for r in rules:
        row = {"fa_per_day": fa[r] / max(unlabelled / S.spd, 1e-9),
               "fa_ratio_to_budget": fa[r] / max(unlabelled / S.spd, 1e-9) / S.budget,
               "unlabelled_alarm_share": alarm_steps[r] / max(unlabelled, 1),
               "median_onset_inflation": float(np.median(per[r]["inflation"])) if meta else None}
        for name, mask in sel.items():
            take = lambda xs, mask=mask: [x for x, k in zip(xs, mask) if k]
            n = int(sum(mask))
            row[name] = {"events": n, "detected": int(sum(take(per[r]["found"]))),
                         "onset_detected": int(sum(take(per[r]["onset"])))}
            if r != "frozen" and n:
                g = take(groups)
                row[name]["vs_frozen"] = cluster_bootstrap(g, take(per["frozen"]["found"]), take(per[r]["found"]))
                row[name]["vs_frozen_onset"] = cluster_bootstrap(g, take(per["frozen"]["onset"]), take(per[r]["onset"]))
        row["by_type"] = {}
        for kind in sorted({e["type"] for e in meta}):
            mask = [e["type"] == kind for e in meta]
            row["by_type"][str(kind)] = {"events": int(sum(mask)),
                                         "detected": int(sum(x for x, k in zip(per[r]["found"], mask) if k)),
                                         "onset_detected": int(sum(x for x, k in zip(per[r]["onset"], mask) if k))}
        out["rules"][r] = row
    return out


def summarise_campaigns(S, units):
    runs = [run for unit in units for run in unit["sealed_runs"]]
    places = [p for run in runs for p in run["campaigns"]]
    out = {"placements": len(places), "streams": len(runs), "magnitudes_over_tau0": list(MAGS), "attacks": {}}
    pick = np.random.default_rng(0).integers(0, len(places), (BOOT, len(places)))
    for attack, rules in CAMPAIGNS.items():
        out["attacks"][attack] = {}
        for r in rules:
            rows = [p[attack][r] for p in places]
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
    days = sum(run["steps"] for run in runs) / S.spd
    total = lambda r, k: sum(run["false_alarms"][r][k] for run in runs)
    out["attack_free"] = {"days": days, "rules": {
        r: {"fa_per_day": total(r, "fa") / max(days, 1e-9), "fa_ratio_to_budget": total(r, "fa") / max(days, 1e-9) / S.budget,
            "alarm_share": total(r, "alarm_steps") / max(days * S.spd, 1),
            "median_tau_end": float(np.median([run["false_alarms"][r]["tau_end"] for run in runs]))}
        for r in D1_RULES}}
    return out


NONINF, DROP, HOLD, EVALUABLE = 0.10, 0.5, 0.1, 0.6


def _campaign_tests(camp):
    at = {m: i for i, m in enumerate(MAGS)}

    def blinded(attack, rule, mag=1.05):
        v, i = camp["attacks"][attack][rule], at[mag]
        if v["control"][i] < EVALUABLE:
            return None
        return bool(v["after"][i] <= v["control"][i] - DROP and v["difference_interval"][i][1] < 0)

    def holds(attack, rule, mag=1.05):
        v, i = camp["attacks"][attack][rule], at[mag]
        return bool(v["after"][i] >= v["control"][i] - HOLD)

    def verdict(targets, keepers):
        if any(t is None for t in targets):
            return "not evaluable"
        return bool(all(targets) and all(keepers))

    return blinded, holds, verdict


def _upper(row):
    return row is not None and row["recall_difference_interval"][1] < 0


def _lower(row, tol=NONINF):
    return row is not None and row["recall_difference_interval"][0] >= -tol


def _ceiling(rr):
    return bool(all(rr[f"tracker_ceil_{k}"]["all"]["detected"] >= rr[f"static_{k}"]["all"]["detected"]
                    for k in ("1.1", "1.25", "1.5")))


def gates_tep(real, camp):
    rr = real["D1"]["rules"]
    blinded, holds, verdict = _campaign_tests(camp)
    f = rr["tracker"]["follower"]
    g = {"H1a_tracker_loses_followers_any_alarm": bool(_upper(f.get("vs_frozen"))),
         "H1b_tracker_loses_followers_onset": bool(_upper(f.get("vs_frozen_onset"))),
         "H1c_tracker_holds_first_events": bool(_lower(rr["tracker"]["first"].get("vs_frozen"))),
         "H2_stronger_rules_hold_followers": bool(all(_lower(rr[r]["follower"].get("vs_frozen"))
                                                      for r in ("daily_excl", "tracker_capped"))),
         "H3_ceiling_bounds_loss": _ceiling(rr),
         "H4_frog_blinds_spot": verdict([blinded("frog", "spot_gr")],
                                        [holds("frog", "frozen"), holds("frog", "spot_gr_ceil_1.25", 1.5)]),
         "H5_loud_pulses_blind_tracker": verdict([blinded("loud", "tracker")],
                                                 [holds("loud", "frozen"), holds("loud", "daily_excl")]),
         "H6_sub_event_pulses_blind_excluding_rules": verdict(
             [blinded("subl", "daily_excl"), blinded("subl", "tracker_hold")],
             [holds("subl", "frozen"), holds("subl", "tracker_ceil_1.25", 1.5), holds("subl", "daily_ceil_1.25", 1.5)])}
    g["primary_success"] = bool(g["H1a_tracker_loses_followers_any_alarm"] and g["H1b_tracker_loses_followers_onset"])
    return g


def gates_provics(real, camp):
    rr = real["D1"]["rules"]
    blinded, holds, verdict = _campaign_tests(camp)
    tol = max(NONINF, 2.0 / max(real["D1"]["events"], 1))
    a = rr["tracker"]["all"]
    g = {"P1a_tracker_loses_any_alarm": bool(_upper(a.get("vs_frozen"))),
         "P1b_tracker_loses_onset": bool(_upper(a.get("vs_frozen_onset"))),
         "P2_capped_tracker_holds": bool(_lower(rr["tracker_capped"]["all"].get("vs_frozen"), tol)),
         "P2_tolerance": tol,
         "P3_ceiling_bounds_loss": _ceiling(rr),
         "P4_frog_blinds_spot": verdict([blinded("frog", "spot_gr")],
                                        [holds("frog", "frozen"), holds("frog", "spot_gr_ceil_1.25", 1.5)]),
         "P5_loud_pulses_blind_tracker": verdict([blinded("loud", "tracker")], [holds("loud", "frozen")]),
         "P6_sub_event_pulses_blind_tracker_hold": verdict(
             [blinded("subl", "tracker_hold")], [holds("subl", "frozen"), holds("subl", "tracker_ceil_1.25", 1.5)])}
    g["primary_success"] = bool(g["P1a_tracker_loses_any_alarm"] and g["P1b_tracker_loses_onset"])
    return g


GATES = {"tep59": gates_tep, "provics": gates_provics}


def assemble(S, units, mode_name):
    real = {"D1": summarise(S, units, "D1", D1_RULES), "D0": summarise(S, units, "D0", SIDE_RULES),
            "D2": summarise(S, units, "D2", SIDE_RULES)}
    camp = summarise_campaigns(S, units)
    return {"dataset": S.name, "mode": mode_name, "settings": S.settings(), "real_events": real, "campaigns": camp,
            "gates": GATES[S.name](real, camp), "units": units}


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
    print(out["dataset"], out["mode"], "events", r["events"], "first", r["first_events"], "followers",
          r["follower_events"], "runs", r["runs"], "unlabelled days", round(r["unlabelled_days"], 2))
    for name, v in r["rules"].items():
        fo = v["follower"]
        ci = (fo.get("vs_frozen") or {}).get("recall_difference_interval")
        co = (fo.get("vs_frozen_onset") or {}).get("recall_difference_interval")
        fmt = lambda c: "" if c is None else "[%+.2f,%+.2f]" % tuple(c)
        print(f"  {name:18s} all {v['all']['detected']}/{v['all']['events']} on {v['all']['onset_detected']}"
              f" | first {v['first']['detected']}/{v['first']['events']}"
              f" | followers {fo['detected']}/{fo['events']} on {fo['onset_detected']} {fmt(ci)} onset {fmt(co)}"
              f" | fa x{v['fa_ratio_to_budget']:.2f} share {v['unlabelled_alarm_share']:.3f} infl {v['median_onset_inflation']}")
    for sk in ("D0", "D2"):
        print(" ", sk, {k: (v["all"]["detected"], v["all"]["onset_detected"]) for k, v in out["real_events"][sk]["rules"].items()})
    c = out["campaigns"]
    print("placements", c["placements"], "on", c["streams"], "streams; terminal magnitudes", c["magnitudes_over_tau0"])
    for attack, rules in c["attacks"].items():
        for name, v in rules.items():
            print(f"  {attack:5s}{name:18s} after {[round(x, 2) for x in v['after']]} control {[round(x, 2) for x in v['control']]}"
                  f" infl med {v['median_inflation']:.3g} max {v['max_inflation']:.3g}"
                  f" episodes {v['median_alarm_episodes']:.0f} longest {v['longest_alarm_episode']}")
    print("attack-free days", round(c["attack_free"]["days"], 1), "fa / budget",
          {k: round(v["fa_ratio_to_budget"], 2) for k, v in c["attack_free"]["rules"].items()})
    print("gates", out["gates"])


def run_units(S, final, only=None, resume=False):
    if S.name == "provics":
        return [provics_unit(S, final)]
    units = []
    for m in (TD.MODES if only is None else [only]):
        part = PARTS / f"mode_{m}.json"
        if final and resume and part.exists():
            units.append(json.loads(part.read_text(encoding="utf-8")))
            continue
        units.append(tep_unit(S, m, final))
        if final:
            part.write_text(json.dumps(units[-1]), encoding="utf-8")
    return units


def main():
    cmd, name = sys.argv[1], sys.argv[2]
    S = SETUPS[name]
    resume = "--resume" in sys.argv
    extra = [a for a in sys.argv[3:] if not a.startswith("--")]
    if cmd == "dry-run":
        seen = ledger()
        print("ledger:", {d: ("ALREADY OPENED" if d in seen else "not opened") for d in S.ledger_ids})
        bad = check_frozen()
        print("frozen files:", "all match the registration" if not bad else f"MISMATCH {bad}")
        return
    if cmd == "rehearse":
        out = assemble(S, run_units(S, False, int(extra[0]) if extra else None), "rehearsal")
        REHEARSAL.mkdir(parents=True, exist_ok=True)
        (REHEARSAL / f"{name}{'_' + extra[0] if extra else ''}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
        show(out)
        return
    bad = check_frozen()
    if bad:
        raise SystemExit(f"REFUSE: frozen files changed or protocol missing: {bad}")
    opened = set(S.ledger_ids) & ledger()
    if opened and not resume:
        raise SystemExit(f"REFUSE: {sorted(opened)} already in {D.FINAL_LEDGER}")
    if resume and not (name == "tep59" and opened and any(PARTS.glob("mode_*.json"))):
        raise SystemExit("REFUSE: nothing to resume")
    PARTS.mkdir(parents=True, exist_ok=True)
    reason = "tt1d final: registered study (threshold-transfer-tt1d)" + \
        (" -- RESUME of an interrupted run from its per-mode parts" if resume else "")
    (TD.provics_open_final if name == "provics" else TD.open_final)(reason)
    out = assemble(S, run_units(S, True, resume=resume), "final")
    out["frozen_file_sha256"] = digests()
    out["resumed"] = resume
    path_out = result_path(name)
    path_out.write_text(json.dumps({"schema_version": "threshold-transfer-tt1d-result", "protocol": PROTOCOL.name, **out},
                                   indent=1) + "\n", encoding="utf-8")
    show(out)
    print("wrote", path_out)


if __name__ == "__main__":
    main()
