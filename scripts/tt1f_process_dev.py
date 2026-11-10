#!/usr/bin/env python3
"""tt1f part E (exploratory): process-level campaigns on normal data of the spent HAI releases.

Plan: docs/research/threshold_transfer_tt1f_dev_plan.md (committed before any run). The registered campaigns
write the score; here the attacker writes three sensor readings (the three most coupled to one setpoint
channel) and the real monitor scores the result.

    python scripts/tt1f_process_dev.py run <release> [placements]   target/real-telemetry/tt1f-process/<release>.json
    python scripts/tt1f_process_dev.py merge                        docs/research/threshold_transfer_tt1f_process_v1.json

Campaigns (each ends one quiet hour before the terminal setpoint step):
  frog     6 h; every 300 s the attacker reads tau_t and picks the largest noise scale whose score stays at
           or below 0.97 tau_t (bisection on the real monitor), as tt1b_physfrog_dev
  probe    6 h; the attacker sees only alarms: scale x1.25 after a 300 s block without one, x0.5 after one
  subl     24 h; every 30 min, 20 s of noise, the largest scale for which the exceedance of the rule's current
           threshold spans at most 45 s
  replay   no campaign; during the terminal step the three sensors show their clean values
"""
from __future__ import annotations

import copy
import json
import sys
import time
import zlib
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_telemetry_core as C
import real_telemetry_detect as R
import real_telemetry_detect_v2 as R2
import real_telemetry_injections as I
import threshold_transfer_dev as X
import tt1_final as F
import tt1b_physfrog_dev as P
import tt1e_defense_dev as E

ROOT = Path(__file__).resolve().parents[1]
PART = ROOT / "target/real-telemetry/tt1f-process"
OUT = ROOT / "docs/research/threshold_transfer_tt1f_process_v1.json"
MULTS = (1.0, 1.5, 2.0, 3.0)                      # terminal step over the just-detectable magnitude
FROG_S, SUBL_S, LEAD, BLOCK = 6 * 3600, 86400, 3600, 300
SUBL_EVERY, SUBL_NOISE, SUBL_SPAN, SUBL_WINDOW = 1800, 20, 45, 180
PROBE_START, PROBE_UP, PROBE_DOWN = 1e-3, 1.25, 0.5
RULES = {"frog": ["frozen", "spot_gr"], "probe": ["frozen", "spot_gr"], "subl": ["frozen", "daily_excl", "tracker_hold"]}
PLACEMENTS = 10


def bisect(fits):
    """Largest noise scale in [SIGMA_MIN, SIGMA_MAX] (log scale) that fits; 0 if the smallest does not."""
    if not fits(P.SIGMA_MIN):
        return 0.0
    if fits(P.SIGMA_MAX):
        return P.SIGMA_MAX
    lo, hi = np.log(P.SIGMA_MIN), np.log(P.SIGMA_MAX)
    for _ in range(P.BISECT):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if fits(np.exp(mid)) else (lo, mid)
    return float(np.exp(lo))


class Tally:
    """Alarm steps, episodes (merged across X.GAP) and the longest episode during a campaign."""

    def __init__(self):
        self.steps, self.episodes, self.longest, self.first, self.last = 0, 0, 0, None, None

    def add(self, i):
        self.steps += 1
        if self.last is None or i - self.last > X.GAP:
            self.episodes += 1
            self.first = i
        self.last = i
        self.longest = max(self.longest, i - self.first + 1)


def campaign(kind, rule, scorer, z, v, s, cfg, calib, end, sensors, noise):
    """Run one rule through one campaign; returns the model at the terminal step and what the campaign cost."""
    model = E.model(rule, cfg, calib)
    length = SUBL_S if kind == "subl" else FROG_S
    c0, c1 = end - LEAD - length, end - LEAD
    for i in range(c0):
        model.update(s[i])
    Z = z.copy()
    tally, sigmas, peaks = Tally(), [], []
    feed = lambda i, x: (tally.add(i) if x > model.tau() else None, model.update(x if np.isfinite(x) else -np.inf))
    if kind in ("frog", "probe"):
        sigma = PROBE_START
        for a in range(c0, c1, BLOCK):
            b = min(a + BLOCK, c1)
            base = Z[a:b, sensors].copy()
            put = lambda sg: Z.__setitem__((slice(a, b), sensors), base + sg * noise[a - c0:b - c0])
            if kind == "frog":
                cap = P.FRAC * model.tau()
                sigma = bisect(lambda sg: (put(sg), np.nanmax(P.scores_at(scorer, Z, v, a, b)) <= cap)[1])
            put(sigma)
            sigmas.append(sigma)
            before = tally.steps
            for k, x in enumerate(P.scores_at(scorer, Z, v, a, b)):
                feed(a + k, x)
            if kind == "probe":
                sigma = sigma * (PROBE_DOWN if tally.steps > before else PROBE_UP)
    else:
        i = c0
        for t in range(c0, c1, SUBL_EVERY):
            for j in range(i, t):
                feed(j, s[j])
            hi = min(t + SUBL_WINDOW, c1)
            base = Z[t:t + SUBL_NOISE, sensors].copy()
            put = lambda sg: Z.__setitem__((slice(t, t + SUBL_NOISE), sensors), base + sg * noise[t - c0:t - c0 + SUBL_NOISE])
            tau = model.tau()

            def fits(sg):
                put(sg)
                above = np.flatnonzero(P.scores_at(scorer, Z, v, t, hi) > tau)
                return len(above) == 0 or above[-1] - above[0] + 1 <= SUBL_SPAN

            sigma = bisect(fits)
            put(sigma)
            sigmas.append(sigma)
            seg = P.scores_at(scorer, Z, v, t, hi)
            peaks.append(float(np.nanmax(seg) / tau))
            for k, x in enumerate(seg):
                feed(t + k, x)
            i = hi
        for j in range(i, c1):
            feed(j, s[j])
    for i in range(c1, end):
        model.update(s[i])
    return model, {"alarm_steps": tally.steps, "alarm_episodes": tally.episodes, "longest_episode": tally.longest,
                   "median_sigma": float(np.median(sigmas)), "median_pulse_peak_over_tau": float(np.median(peaks)) if peaks else None}


def terminal_hits(model, terms):
    hits = []
    for seg in terms:
        m, hit = copy.deepcopy(model), False
        for x in seg:
            hit |= bool(x > m.tau())
            m.update(x)
        hits.append(hit)
    return hits


def run(release, placements=PLACEMENTS, seed=7):
    t0 = time.time()
    parts = X.split(X.normal_segments(release))
    xs = C.Scaler().fit(np.concatenate([x for x, _ in parts["fit"]]))
    us = C.Scaler().fit(np.concatenate([u for _, u in parts["fit"]]))
    pack = lambda g: [(xs(x), us(u)) for x, u in g]
    fit, scale, calib, deploy = (pack(parts[k]) for k in ("fit", "scale", "calib", "deploy"))
    wm = R.make_world_model("ridge_gbr_actions", True).fit(fit)
    scorer = R.Scorer(wm, fit)
    scorer.residual_scales(scale)
    cal = [s[np.isfinite(s)] for s in (X.d1(scorer, zz, vv) for zz, vv in calib)]
    tau0 = R.calibrate(cal, X.GAP, X.BUDGET, X.STEPS_PER_DAY)
    pooled = np.concatenate(cal)
    cfg = F.thresholds(pooled, tau0, F.ETA_MULT, 0.999)
    check = {"tau0_registered_calibrate": float(tau0),                 # plan amendment 2, K1
             "tau0_calibrate_v2": float(R2.calibrate(cal, X.GAP, X.BUDGET, X.STEPS_PER_DAY))}
    z, v = max(deploy, key=lambda item: len(item[0]))
    s_clean = X.d1(scorer, z, v)
    s = np.where(np.isfinite(s_clean), s_clean, -np.inf)
    fz, fv = np.concatenate([q for q, _ in fit]), np.concatenate([q for _, q in fit])
    inj = I.Injector("hai", fz, fv, seed=seed + zlib.crc32(release.encode()) % 1000)
    rng = np.random.default_rng(seed + 909)
    first = X.STEPS_PER_DAY // 2 + SUBL_S + LEAD
    last = len(z) - X.ATTACK - X.MARGIN
    print(release, "monitor ready", round(time.time() - t0), "s; stream", round(len(z) / 86400, 2), "days", flush=True)
    if last <= first:
        raise SystemExit(f"{release}: deployment stream too short for a 24 h campaign")
    rows = []
    for _ in range(placements * 3):
        if len(rows) == placements:
            break
        end = int(rng.integers(first, last))
        a_idx, sensors = inj._action_and_sensors(3)
        signs = rng.choice([-1, 1], len(sensors))
        m_att = X._just_detectable(scorer, z, v, s_clean, end, a_idx, sensors, signs, cfg["tau0"])
        if m_att is None:
            continue
        noise = rng.standard_normal((SUBL_S, len(sensors))).astype(np.float32)
        lo, hi = end - X.MARGIN, end + X.ATTACK + X.MARGIN
        window = lambda edit: X._splice(scorer, z, v, s_clean, lo, hi, edit)[end:end + X.ATTACK]
        terms = [window(lambda Zp, Vp, m=k * m_att: X._terminal(Zp, Vp, end - lo, a_idx, sensors, signs, m)) for k in MULTS]

        def replay(Zp, Vp, m):
            Vp[end - lo:end - lo + X.ATTACK, a_idx] += m           # the setpoint moves; the three sensors show clean values

        hidden = [window(lambda Zp, Vp, m=k * m_att: replay(Zp, Vp, m)) for k in MULTS]
        row = {"terminal_start": end, "action": int(a_idx), "sensors": [int(i) for i in sensors], "just_detectable": float(m_att),
               "replay": {"frozen_plain": [bool((seg > cfg["tau0"]).any()) for seg in terms],
                          "frozen_replayed": [bool((seg > cfg["tau0"]).any()) for seg in hidden]},
               "control": {}, "campaigns": {k: {} for k in RULES}}
        for rule in dict.fromkeys(sum(RULES.values(), [])):
            model = E.model(rule, cfg, pooled)
            for i in range(end):
                model.update(s[i])
            row["control"][rule] = terminal_hits(model, terms)
        for kind, rules in RULES.items():
            for rule in rules:
                model, cost = campaign(kind, rule, scorer, z, v, s, cfg, pooled, end, sensors, noise)
                row["campaigns"][kind][rule] = {"after": terminal_hits(model, terms), "tau_over_tau0": float(model.tau() / cfg["tau0"]), **cost}
                print(release, "placement", len(rows) + 1, kind, rule, row["campaigns"][kind][rule]["after"], "control",
                      row["control"][rule], "alarms", cost["alarm_steps"], round(time.time() - t0), "s", flush=True)
        rows.append(row)
    PART.mkdir(parents=True, exist_ok=True)
    (PART / f"{release}.json").write_text(json.dumps({"release": release, "thresholds": cfg, "calibration_check": check, "stream_days": len(z) / 86400,
                                                      "placements": rows}, indent=1), encoding="utf-8")
    print(release, "done", round(time.time() - t0), "s", flush=True)


def merge():
    rel = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(PART.glob("hai-*.json"))}
    rows = [r for v in rel.values() for r in v["placements"]]
    count = lambda hits: [int(sum(h[k] for h in hits)) for k in range(len(MULTS))]
    out = {"schema_version": "threshold-transfer-tt1f-process-v1",
           "status": "exploratory: normal data of the spent HAI releases; the attacker writes three sensor readings",
           "plan": "docs/research/threshold_transfer_tt1f_dev_plan.md", "placements": len(rows),
           "placements_per_release": {k: len(v["placements"]) for k, v in rel.items()},
           "calibration_check": {k: v.get("calibration_check") for k, v in rel.items()},
           "terminal_multiples_of_just_detectable": list(MULTS),
           "median_just_detectable_setpoint_step_scaled_units": float(np.median([r["just_detectable"] for r in rows])),
           "replay": {"frozen_plain": count([r["replay"]["frozen_plain"] for r in rows]),
                      "frozen_replayed": count([r["replay"]["frozen_replayed"] for r in rows])},
           "campaigns": {}}
    for kind, rules in RULES.items():
        out["campaigns"][kind] = {}
        for rule in rules:
            cells = [r["campaigns"][kind][rule] for r in rows]
            out["campaigns"][kind][rule] = {
                "caught_after": count([c["after"] for c in cells]), "caught_control": count([r["control"][rule] for r in rows]),
                "silent_placements": int(sum(c["alarm_steps"] == 0 for c in cells)),
                "median_alarm_steps": float(np.median([c["alarm_steps"] for c in cells])),
                "median_alarm_episodes": float(np.median([c["alarm_episodes"] for c in cells])),
                "longest_episode": int(max(c["longest_episode"] for c in cells)),
                "median_tau_over_tau0": float(np.median([c["tau_over_tau0"] for c in cells])),
                "median_noise_scale": float(np.median([c["median_sigma"] for c in cells])),
                "median_pulse_peak_over_tau": (float(np.median([c["median_pulse_peak_over_tau"] for c in cells]))
                                               if cells[0]["median_pulse_peak_over_tau"] is not None else None)}
            c = out["campaigns"][kind][rule]
            print(f"{kind:6s} {rule:13s} after {c['caught_after']} control {c['caught_control']} silent {c['silent_placements']}/{len(rows)} "
                  f"episodes {c['median_alarm_episodes']:.0f} tau x{c['median_tau_over_tau0']:.3g}")
    print("replay", out["replay"])
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print("written", OUT)


if __name__ == "__main__":
    if sys.argv[1] == "run":
        run(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else PLACEMENTS)
    else:
        merge()
