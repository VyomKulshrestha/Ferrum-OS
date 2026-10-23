#!/usr/bin/env python3
"""tt1b development: a physically realizable closed-loop frog (sensor-noise spoofing) on normal HAI data.

The score-level frog (tt1b_frog_dev) sets the score directly. Here the attacker can only spoof readings:
zero-mean noise on the 3 sensors most coupled to one setpoint channel. Every BLOCK steps it reads the
rule's threshold tau_b and picks, by bisection, the largest noise scale whose smoothed D1 score over the
block stays at or below 0.97 tau_b, scored by the real world model with the spoofed history (white-box:
the attacker can run the monitor). After a 6 h campaign the noise stops; 1 h later comes the just-
detectable setpoint step of threshold_transfer_dev (the smallest step the frozen tau0 detects on the
clean stream). Control: the same step without the campaign. Rules run online (threshold_online).
Writes target/real-telemetry/tt1b-physfrog/<release>.json; `merge` builds docs/research/threshold_transfer_tt1b_physfrog_dev_v1.json.
"""
from __future__ import annotations

import json
import sys
import time
import zlib
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_telemetry_core as C
import real_telemetry_detect as R
import real_telemetry_injections as I
import threshold_online as O
import threshold_transfer_dev as X
import tt1_final as F

ROOT = Path(__file__).resolve().parents[1]
PART = ROOT / "target/real-telemetry/tt1b-physfrog"
OUT = ROOT / "docs/research/threshold_transfer_tt1b_physfrog_dev_v1.json"
FRAC, BLOCK, CAMPAIGN, LEAD, CTX, PLACEMENTS = 0.97, 300, 6 * 3600, 3600, 120, 4
RULES = ["frozen", "spot", "spot_mle", "dspot"]      # the rules the closed-loop question is about
SIGMA_MIN, SIGMA_MAX, BISECT = 1e-4, 4.0, 7      # log-scale search: the residual reacts to noise of ~0.01


def scores_at(scorer, Z, V, lo, hi):
    """Smoothed D1 on [lo, hi) of the (possibly spoofed) arrays, with CTX steps of context before lo."""
    a = max(0, lo - CTX)
    s = X.d1(scorer, Z[a:hi], V[a:hi])
    return s[lo - a:]


def attack(rule, scorer, z, v, s_clean, cfg, calib, c0, end, sensors, noise, a_idx, signs, m_att, campaign):
    model = O.make(rule, cfg, calib, X.STEPS_PER_DAY, 3600, 2048)
    Z, V = z.copy(), v.copy()
    resp = I._lag_response(X.ATTACK, 60.0)
    V[end:end + X.ATTACK, a_idx] += m_att
    Z[end:end + X.ATTACK, sensors] += np.outer(resp, signs * m_att)
    s = np.where(np.isfinite(s_clean), s_clean, -np.inf).copy()
    for i in range(c0):                                    # clean history up to the campaign
        model.update(s[i])
    sigmas, alarms = [], 0
    i = c0
    while i < end + X.ATTACK:
        if campaign and i < c0 + CAMPAIGN:
            hi = min(i + BLOCK, c0 + CAMPAIGN)
            cap = FRAC * model.tau()
            base = Z[i:hi, sensors].copy()
            fits = lambda sg: (Z.__setitem__((slice(i, hi), sensors), base + sg * noise[i - c0:hi - c0]),
                               np.nanmax(scores_at(scorer, Z, V, i, hi)) <= cap)[1]
            best = 0.0
            if fits(SIGMA_MIN):
                lo_l, hi_l = np.log(SIGMA_MIN), np.log(SIGMA_MAX)
                for _ in range(BISECT):
                    mid = (lo_l + hi_l) / 2
                    lo_l, hi_l = (mid, hi_l) if fits(np.exp(mid)) else (lo_l, mid)
                best = float(np.exp(lo_l))
            Z[i:hi, sensors] = base + best * noise[i - c0:hi - c0]
            sigmas.append(best)
            block = scores_at(scorer, Z, V, i, hi)
        else:
            hi = min(i + BLOCK, end + X.ATTACK)
            block = scores_at(scorer, Z, V, i, hi)
        for k, x in enumerate(block):
            t = i + k
            tau = model.tau()
            if t == end:
                tau_end = tau
            if campaign and t < c0 + CAMPAIGN:
                alarms += x > tau
            if end <= t < end + X.ATTACK and x > tau:
                return True, float(tau_end / cfg["tau0"]), alarms, sigmas
            model.update(x if np.isfinite(x) else -np.inf)
        i = hi
    return False, float(tau_end / cfg["tau0"]), alarms, sigmas


def run(release, seed=7):
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
    z, v = max(deploy, key=lambda item: len(item[0]))
    s_clean = X.d1(scorer, z, v)
    fz, fv = np.concatenate([q for q, _ in fit]), np.concatenate([q for _, q in fit])
    inj = I.Injector("hai", fz, fv, seed=seed + zlib.crc32(release.encode()) % 1000)
    rng = np.random.default_rng(seed + 808)
    out = {r: {"after": [], "control": [], "inflation": [], "alarms": [], "median_sigma": []} for r in RULES}
    used = 0
    for _ in range(PLACEMENTS * 3):
        if used == PLACEMENTS:
            break
        c0 = int(rng.integers(X.STEPS_PER_DAY // 2, len(z) - CAMPAIGN - LEAD - X.ATTACK - X.MARGIN))
        end = c0 + CAMPAIGN + LEAD
        a_idx, sensors = inj._action_and_sensors(3)
        signs = rng.choice([-1, 1], len(sensors))
        m_att = X._just_detectable(scorer, z, v, s_clean, end, a_idx, sensors, signs, cfg["tau0"])
        if m_att is None:
            continue
        used += 1
        noise = rng.standard_normal((CAMPAIGN, len(sensors))).astype(np.float32)
        for r in RULES:
            hit, infl, alarms, sig = attack(r, scorer, z, v, s_clean, cfg, pooled, c0, end, sensors, noise, a_idx, signs, m_att, True)
            hit_c, _, _, _ = attack(r, scorer, z, v, s_clean, cfg, pooled, c0, end, sensors, noise, a_idx, signs, m_att, False)
            o = out[r]
            o["after"].append(hit); o["control"].append(hit_c); o["inflation"].append(infl); o["alarms"].append(alarms)
            o["median_sigma"].append(float(np.median(sig)) if sig else 0.0)
            print(release, "placement", used, r, "after", hit, "control", hit_c, "infl", round(infl, 3), round(time.time() - t0), "s", flush=True)
        print(release, "placement", used, "done", round(time.time() - t0), "s", flush=True)
    res = {"release": release, "placements_used": used, "campaign_hours": CAMPAIGN / 3600, "thresholds": cfg,
           "rules": {r: {"terminal_after_campaign": float(np.mean(o["after"])), "terminal_control": float(np.mean(o["control"])),
                         "median_inflation": float(np.median(o["inflation"])), "median_campaign_alarm_steps": float(np.median(o["alarms"])),
                         "median_noise_sigma": float(np.median(o["median_sigma"]))} for r, o in out.items()}}
    PART.mkdir(parents=True, exist_ok=True)
    (PART / f"{release}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")


def merge():
    rel = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(PART.glob("*.json"))}
    OUT.write_text(json.dumps({"schema_version": "threshold-transfer-tt1b-physfrog-dev-v1",
                               "status": "development evidence on normal data of spent HAI releases; sensor-noise spoofing attacker",
                               "releases": rel}, indent=1) + "\n", encoding="utf-8")
    for r in RULES:
        row = f"{r:15s}"
        for v in rel.values():
            m = v["rules"][r]
            row += f"   {m['terminal_after_campaign']:.2f}/{m['terminal_control']:.2f} x{m['median_inflation']:.3g} a{m['median_campaign_alarm_steps']:.0f} s{m['median_noise_sigma']:.3f}"
        print(row)


if __name__ == "__main__":
    run(sys.argv[2]) if sys.argv[1] == "run" else merge()
