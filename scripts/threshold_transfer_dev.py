#!/usr/bin/env python3
"""Development experiments for threshold-transfer study tt1 (normal HAI data only; no attack files).

For each spent HAI release, normal training data are split in time: world-model fit (50%),
residual scale (50-65%), threshold calibration (65-75%) and a deployment proxy (75-100%). The
monitor is the registered rt1/rt2 D1 (ridge + 60-tree GBR world model, history 3, residual
top-3 at H1 + H5, smoothing window 60, budget 2 false-alarm episodes per day).

E1  budget adherence: false-alarm episodes per day of each threshold rule on the deployment proxy.
E2  poisoning: a slow drift (geometric bias, Cardenas 2011 family) on coupled sensors for 12 h,
    ending in a 10-minute setpoint step (T0836 family), injected at random places in the
    deployment proxy. Reports event detection, terminal-attack detection and threshold inflation.
E3  stealthy poisoning: the drift is kept below tau0 and the terminal step is just detectable.
E4  nuisance-pulse campaign: a day of short supra-threshold setpoint pulses on the loop the
    attacker will later hit (alarms an operator learns to dismiss), then the just-detectable
    terminal step. Online thresholds that learn from exceedances are the target.
E5  noise campaign: sub-threshold sensor noise for a day (largest that never trips tau0),
    continued through the just-detectable terminal step. The adaptive attack on the "shift" permit.
Round r2 ran E1-E3 (docs/research/threshold_transfer_dev_v1.json, code at f657b6d); round r3
runs E1, E4, E5 with the per-step margin and the shift permit (threshold_transfer_dev_v2.json);
round r4 reruns E1 and E4 with the slow tracker added (threshold_transfer_dev_v3.json).
Everything here is development evidence for choosing registered settings, not a result.
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
import real_telemetry_data as D
import real_telemetry_detect as R
import real_telemetry_injections as I
import real_telemetry_rt2 as RT2
import threshold_rules as T

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/research/threshold_transfer_dev_v1.json"
STEPS_PER_DAY = 86400
GAP = 60
WINDOW = 60
BUDGET = 2.0
CUTS = (0.50, 0.65, 0.75)
ETA_MULTS = (0.001, 0.01, 0.05)
RAMP = 12 * 3600
ATTACK = 600
PLACEMENTS = 20


def normal_segments(release):
    if release == "hai-22.04":
        return [(s.X, s.U) for s in D.hai_train()["segments"]]
    segs, _ = RT2.train_segments(release)
    return segs


def split(segs):
    total = sum(len(x) for x, _ in segs)
    b = [int(total * c) for c in CUTS] + [total]
    names, out, off = ("fit", "scale", "calib", "deploy"), {n: [] for n in ("fit", "scale", "calib", "deploy")}, 0
    for x, u in segs:
        a, z = off, off + len(x)
        lo = 0
        for name, hi in zip(names, b):
            s, e = max(a, lo), min(z, hi)
            if e - s > 2000:
                out[name].append((x[s - a:e - a], u[s - a:e - a]))
            lo = hi
        off = z
    return out


def d1(scorer, Z, V):
    s = R.smooth(R.scores_for(scorer, {}, Z, V)["D1"], WINDOW)
    s[:R.WARMUP] = np.nan
    return s


def fa_per_day(alarm, n):
    return len(T._episodes(alarm, GAP)) / max(n / STEPS_PER_DAY, 1e-9)


def run_release(release, experiments=("E1", "E2", "E3"), seed=7):
    t0 = time.time()
    parts = split(normal_segments(release))
    xs = C.Scaler().fit(np.concatenate([x for x, _ in parts["fit"]]))
    us = C.Scaler().fit(np.concatenate([u for _, u in parts["fit"]]))
    pack = lambda g: [(xs(x), us(u)) for x, u in g]
    fit, scale, calib, deploy = (pack(parts[k]) for k in ("fit", "scale", "calib", "deploy"))
    wm = R.make_world_model("ridge_gbr_actions", True).fit(fit)
    scorer = R.Scorer(wm, fit)
    scorer.residual_scales(scale)
    cal_scores = [d1(scorer, z, v) for z, v in calib]
    cal_clean = [s[np.isfinite(s)] for s in cal_scores]
    tau0 = R.calibrate(cal_clean, GAP, BUDGET, STEPS_PER_DAY)
    pooled = np.concatenate(cal_clean)
    p = float(max((pooled > tau0).mean(), 1.0 / len(pooled)))
    if "E4" in experiments:
        # r3/r4 margin: half the per-step exceedance rate (episode counting over ~1 calibration day
        # is too coarse; in r2 it returned tau0 itself on 23.05)
        tau_half = float(max(tau0, np.quantile(pooled, 1 - p / 2)))
    else:
        tau_half = R.calibrate(cal_clean, GAP, BUDGET / 2, STEPS_PER_DAY)
    m0 = float(np.median(pooled))
    spread = float(np.quantile(pooled, 0.999) - m0)
    print(release, "calibrated", round(time.time() - t0), "s; tau0", round(tau0, 3), "p", round(p, 6), flush=True)
    cfg = {"tau0": tau0, "tau_half": tau_half, "p": p, "eta": ETA_MULTS[1] * spread, "m0": m0}

    # E1 budget adherence on the deployment proxy (one stream per deploy segment).
    dep = [(z, v, d1(scorer, z, v)) for z, v in deploy]
    n_dep = sum(len(s) for _, _, s in dep)
    e1 = {}
    for eta_mult in ETA_MULTS:
        for rule in T.RULES:
            if rule == "one_sided:oracle":
                continue
            if eta_mult != ETA_MULTS[1] and rule in ("frozen", "margin", "daily"):
                continue
            alarms, permits = 0, 0
            for z, v, s in dep:
                s2 = np.where(np.isfinite(s), s, -np.inf)
                tau, meta = T.apply_rule(rule, s2, tau0, tau_half, p, eta_mult * spread, STEPS_PER_DAY, GAP, ref_median=m0)
                alarms += len(T._episodes(s2 > tau, GAP))
                permits += meta.get("permits", 0)
            key = rule if rule in ("frozen", "margin", "daily") else f"{rule}@eta{eta_mult}"
            e1[key] = {"fa_per_day": alarms / max(n_dep / STEPS_PER_DAY, 1e-9), "ratio_to_budget": alarms / max(n_dep / STEPS_PER_DAY, 1e-9) / BUDGET,
                       "permits": permits}
    print(release, "E1 done", round(time.time() - t0), "s", flush=True)
    result = {"release": release, "deploy_days": n_dep / STEPS_PER_DAY, "tau0": tau0, "tau_half": tau_half, "p": p,
              "calib_median": m0, "E1_budget_adherence": e1}

    z, v, s_base = max(dep, key=lambda item: len(item[0]))
    fz = np.concatenate([q for q, _ in fit])
    fv = np.concatenate([q for _, q in fit])
    inj = I.Injector("hai", fz, fv, seed=seed + zlib.crc32(release.encode()) % 1000)
    result["attack_segment_days"] = len(z) / STEPS_PER_DAY
    if "E4" in experiments:
        result["E4_pulse_campaign"] = pulse_campaign(scorer, z, v, s_base, inj, cfg, seed)
        print(release, "E4 done", round(time.time() - t0), "s", flush=True)
    if "E5" in experiments:
        result["E5_noise_campaign"] = noise_campaign(scorer, z, v, s_base, inj, cfg, seed)
        print(release, "E5 done", round(time.time() - t0), "s", flush=True)
    if "E2" not in experiments:
        return result

    # E2 poisoning: slow drift then a setpoint step, spliced into the longest deployment segment.
    rng = np.random.default_rng(seed)
    rules = [r for r in T.RULES if r != "one_sided:oracle"] + ["one_sided:oracle"]
    e2 = {r: {"event": [], "terminal": [], "inflation": []} for r in rules}
    ctrl = {r: [] for r in rules}
    margin = 300
    for k in range(PLACEMENTS):
        end = int(rng.integers(RAMP + 2 * margin + STEPS_PER_DAY // 2, len(z) - ATTACK - margin))
        start = end - RAMP
        a_idx, sensors = inj._action_and_sensors(3)
        mag = float(rng.uniform(1.0, 3.0))
        Zp, Vp = z.copy(), v.copy()
        ramp = (np.arange(RAMP) / RAMP) ** 2.0
        Zp[start:end, sensors] += np.outer(ramp, rng.choice([-1, 1], len(sensors)) * 0.8 * mag)
        Vp[end:end + ATTACK, a_idx] += mag
        Zp[end:end + ATTACK, sensors] += np.outer(I._lag_response(ATTACK, 60.0), rng.choice([-1, 1], len(sensors)) * mag)
        lo, hi = start - margin, end + ATTACK + margin
        seg = d1(scorer, Zp[lo:hi], Vp[lo:hi])
        s_pois = s_base.copy()
        s_pois[lo + R.WARMUP:hi] = seg[R.WARMUP:]
        labels = np.zeros(len(z), np.int8)
        labels[start:end + ATTACK] = 1
        # control: the same terminal attack without the ramp
        Zc, Vc = z.copy(), v.copy()
        Vc[end:end + ATTACK, a_idx] += mag
        Zc[end:end + ATTACK, sensors] += np.outer(I._lag_response(ATTACK, 60.0), rng.choice([-1, 1], len(sensors)) * mag)
        segc = d1(scorer, Zc[lo:hi], Vc[lo:hi])
        s_ctrl = s_base.copy()
        s_ctrl[lo + R.WARMUP:hi] = segc[R.WARMUP:]
        lab_c = np.zeros(len(z), np.int8)
        lab_c[end:end + ATTACK] = 1
        for rule in rules:
            sp = np.where(np.isfinite(s_pois), s_pois, -np.inf)
            tau, _ = T.apply_rule(rule, sp, tau0, tau_half, p, ETA_MULTS[1] * spread, STEPS_PER_DAY, GAP, labels=labels, ref_median=m0)
            alarm = sp > tau
            e2[rule]["event"].append(bool(alarm[start:end + ATTACK].any()))
            e2[rule]["terminal"].append(bool(alarm[end:end + ATTACK].any()))
            e2[rule]["inflation"].append(float(tau[end] / tau0))
            sc = np.where(np.isfinite(s_ctrl), s_ctrl, -np.inf)
            tau_c, _ = T.apply_rule(rule, sc, tau0, tau_half, p, ETA_MULTS[1] * spread, STEPS_PER_DAY, GAP, labels=lab_c, ref_median=m0)
            ctrl[rule].append(bool((sc > tau_c)[end:end + ATTACK].any()))
    e2_summary = {r: {"event_detected": float(np.mean(v["event"])), "terminal_detected": float(np.mean(v["terminal"])),
                      "median_threshold_inflation": float(np.median(v["inflation"])),
                      "control_terminal_detected": float(np.mean(ctrl[r]))} for r, v in e2.items()}
    print(release, "E2 done", round(time.time() - t0), "s", flush=True)
    e3 = stealthy_poisoning(scorer, z, v, s_base, inj, tau0, tau_half, p, spread, seed, m0)
    print(release, "E3 done", round(time.time() - t0), "s", flush=True)
    return result | {"E2_poisoning": e2_summary, "E3_stealthy_poisoning": e3, "placements": PLACEMENTS}


STEALTHY_PLACEMENTS = 12


def stealthy_poisoning(scorer, z, v, s_base, inj, tau0, tau_half, p, spread, seed, m0=None):
    """E3: boiling-frog drift kept below the registered threshold, then a just-detectable attack.

    Per placement, the drift magnitude is the largest (bisection) for which the frozen threshold
    never fires during the 12 h drift, and the terminal setpoint-step magnitude is the smallest
    (bisection) that the frozen threshold detects WITHOUT the drift. Each rule is then asked to
    detect the terminal attack after the drift (poisoned) and without it (control).
    """
    rng = np.random.default_rng(seed + 101)
    margin = 300
    rules = [r for r in T.RULES]
    out = {r: {"poisoned": [], "control": [], "inflation": []} for r in rules}
    used = 0
    for _ in range(STEALTHY_PLACEMENTS * 3):
        if used == STEALTHY_PLACEMENTS:
            break
        end = int(rng.integers(RAMP + 2 * margin + STEPS_PER_DAY // 2, len(z) - ATTACK - margin))
        start, lo, hi = end - RAMP, end - RAMP - margin, end + ATTACK + margin
        a_idx, sensors = inj._action_and_sensors(3)
        signs = rng.choice([-1, 1], len(sensors))
        ramp = (np.arange(RAMP) / RAMP) ** 2.0
        resp = I._lag_response(ATTACK, 60.0)

        def scores(m_ramp, m_att):
            Zp, Vp = z[lo:hi].copy(), v[lo:hi].copy()
            Zp[start - lo:end - lo, sensors] += np.outer(ramp, signs * m_ramp)
            Zp[end - lo:end - lo + ATTACK, sensors] += np.outer(ramp[-1] * np.ones(ATTACK), signs * m_ramp)
            Vp[end - lo:end - lo + ATTACK, a_idx] += m_att
            Zp[end - lo:end - lo + ATTACK, sensors] += np.outer(resp, signs * m_att)
            seg = d1(scorer, Zp, Vp)
            s = s_base.copy()
            s[lo + R.WARMUP:hi] = seg[R.WARMUP:]
            return np.where(np.isfinite(s), s, -np.inf)

        # largest sub-threshold drift (frozen tau0 never fires during the drift, no terminal attack)
        a, b = 0.0, 4.0
        for _ in range(7):
            mid = (a + b) / 2
            a, b = (mid, b) if not (scores(mid, 0.0)[start:end] > tau0).any() else (a, mid)
        m_ramp = a
        # smallest terminal attack the frozen threshold detects without the drift
        a, b = 0.0, 6.0
        if not (scores(0.0, b)[end:end + ATTACK] > tau0).any():
            continue
        for _ in range(7):
            mid = (a + b) / 2
            a, b = (a, mid) if (scores(0.0, mid)[end:end + ATTACK] > tau0).any() else (mid, b)
        m_att = b
        if m_ramp < 0.05:
            continue
        used += 1
        sp, sc = scores(m_ramp, m_att), scores(0.0, m_att)
        lab_p = np.zeros(len(z), np.int8)
        lab_p[start:end + ATTACK] = 1
        lab_c = np.zeros(len(z), np.int8)
        lab_c[end:end + ATTACK] = 1
        for rule in rules:
            tau_p, _ = T.apply_rule(rule, sp, tau0, tau_half, p, ETA_MULTS[1] * spread, STEPS_PER_DAY, GAP, labels=lab_p, ref_median=m0)
            tau_c, _ = T.apply_rule(rule, sc, tau0, tau_half, p, ETA_MULTS[1] * spread, STEPS_PER_DAY, GAP, labels=lab_c, ref_median=m0)
            out[rule]["poisoned"].append(bool((sp > tau_p)[end:end + ATTACK].any()))
            out[rule]["control"].append(bool((sc > tau_c)[end:end + ATTACK].any()))
            out[rule]["inflation"].append(float(tau_p[end] / tau0))
    return {"placements_used": used,
            "rules": {r: {"terminal_detected_after_drift": float(np.mean(v["poisoned"])) if v["poisoned"] else None,
                          "terminal_detected_control": float(np.mean(v["control"])) if v["control"] else None,
                          "median_threshold_inflation": float(np.median(v["inflation"])) if v["inflation"] else None}
                      for r, v in out.items()}}


CAMPAIGN = STEPS_PER_DAY
PULSES_PER_DAY = 12
PULSE = 120
PULSE_MULT = 2.0
LEAD = 3600                  # quiet hour between the end of a campaign and the terminal step
CAMPAIGN_PLACEMENTS = 10
NOISE_PLACEMENTS = 8
MARGIN = 300


def _splice(scorer, z, v, s_base, lo, hi, edit):
    """Score an edited copy of z[lo:hi], v[lo:hi] and splice it into the clean score stream."""
    Zp, Vp = z[lo:hi].copy(), v[lo:hi].copy()
    edit(Zp, Vp)
    seg = d1(scorer, Zp, Vp)
    s = s_base.copy()
    s[lo + R.WARMUP:hi] = seg[R.WARMUP:]
    return np.where(np.isfinite(s), s, -np.inf)


def _terminal(Zp, Vp, at, a_idx, sensors, signs, m):
    resp = I._lag_response(ATTACK, 60.0)
    Vp[at:at + ATTACK, a_idx] += m
    Zp[at:at + ATTACK, sensors] += np.outer(resp, signs * m)


def _just_detectable(scorer, z, v, s_base, end, a_idx, sensors, signs, tau0):
    """Smallest setpoint-step magnitude the frozen tau0 detects on clean background (bisection)."""
    lo, hi = end - MARGIN, end + ATTACK + MARGIN
    hit = lambda m: (_splice(scorer, z, v, s_base, lo, hi, lambda Zp, Vp: _terminal(
        Zp, Vp, end - lo, a_idx, sensors, signs, m))[end:end + ATTACK] > tau0).any()
    a, b = 0.0, 6.0
    if not hit(b):
        return None
    for _ in range(7):
        mid = (a + b) / 2
        a, b = (a, mid) if hit(mid) else (mid, b)
    return b


def _campaign_slots(z):
    # at most a day, and at most half the room after the half-day warm-up, so placements can vary
    campaign = int(min(CAMPAIGN, (len(z) - STEPS_PER_DAY // 2 - LEAD - ATTACK - 2 * MARGIN) // 2))
    return campaign, max(1, round(PULSES_PER_DAY * campaign / STEPS_PER_DAY))


def _score_rules(sp, sc, end, lab_p, lab_c, cfg, out, extra=None):
    for rule in T.RULES:
        tau_p, meta = T.apply_rule(rule, sp, cfg["tau0"], cfg["tau_half"], cfg["p"], cfg["eta"], STEPS_PER_DAY, GAP,
                                   labels=lab_p, ref_median=cfg["m0"])
        tau_c, _ = T.apply_rule(rule, sc, cfg["tau0"], cfg["tau_half"], cfg["p"], cfg["eta"], STEPS_PER_DAY, GAP,
                                labels=lab_c, ref_median=cfg["m0"])
        o = out.setdefault(rule, {"poisoned": [], "control": [], "inflation": [], "permits": []})
        o["poisoned"].append(bool((sp > tau_p)[end:end + ATTACK].any()))
        o["control"].append(bool((sc > tau_c)[end:end + ATTACK].any()))
        o["inflation"].append(float(tau_p[end] / cfg["tau0"]))
        o["permits"].append(int(meta.get("permits", 0)))
        if extra:
            extra(rule, sp > tau_p, o)


def _summarise(out, used, **info):
    rules = {}
    for r, o in out.items():
        rules[r] = {"terminal_detected_after_campaign": float(np.mean(o["poisoned"])),
                    "terminal_detected_control": float(np.mean(o["control"])),
                    "median_threshold_inflation": float(np.median(o["inflation"])),
                    "mean_permits": float(np.mean(o["permits"]))}
        for k in ("pulse_alarm_frac", "late_pulse_alarm_frac"):
            if k in o:
                rules[r][k] = float(np.mean(o[k]))
    return {"placements_used": used, **info, "rules": rules}


def pulse_campaign(scorer, z, v, s_base, inj, cfg, seed, avoid=None):
    """E4: PULSES_PER_DAY short supra-threshold pulses for a day, then the just-detectable step."""
    rng = np.random.default_rng(seed + 202)
    campaign, n_pulses = _campaign_slots(z)
    if campaign < 6 * 3600:
        return {"skipped": f"attack segment too short ({len(z) / STEPS_PER_DAY:.2f} days)"}
    slot = campaign // n_pulses
    out, used, mags = {}, 0, []
    for _ in range(CAMPAIGN_PLACEMENTS * 3):
        if used == CAMPAIGN_PLACEMENTS:
            break
        c0 = int(rng.integers(STEPS_PER_DAY // 2, len(z) - campaign - LEAD - ATTACK - MARGIN))
        end = c0 + campaign + LEAD
        a_idx, sensors = inj._action_and_sensors(3)
        signs = rng.choice([-1, 1], len(sensors))
        if avoid is not None and avoid[end - MARGIN:end + ATTACK + MARGIN].any():
            continue                                   # final data: keep the terminal step clear of labelled events
        m_att = _just_detectable(scorer, z, v, s_base, end, a_idx, sensors, signs, cfg["tau0"])
        if m_att is None:
            continue
        used += 1
        mags.append(m_att)
        m_pulse = PULSE_MULT * m_att
        starts = [c0 + k * slot + int(rng.integers(0, slot - PULSE - WINDOW)) for k in range(n_pulses)]
        presp = I._lag_response(PULSE, 60.0)
        lo, hi = c0 - MARGIN, end + ATTACK + MARGIN

        def edit(Zp, Vp):
            for t in starts:
                Vp[t - lo:t - lo + PULSE, a_idx] += m_pulse
                Zp[t - lo:t - lo + PULSE, sensors] += np.outer(presp, signs * m_pulse)
            _terminal(Zp, Vp, end - lo, a_idx, sensors, signs, m_att)

        sp = _splice(scorer, z, v, s_base, lo, hi, edit)
        sc = _splice(scorer, z, v, s_base, end - MARGIN, end + ATTACK + MARGIN,
                     lambda Zp, Vp: _terminal(Zp, Vp, MARGIN, a_idx, sensors, signs, m_att))
        lab_p = np.zeros(len(z), np.int8)
        for t in starts:
            lab_p[t:t + PULSE] = 1
        lab_p[end:end + ATTACK] = 1
        lab_c = np.zeros(len(z), np.int8)
        lab_c[end:end + ATTACK] = 1

        def pulses(rule, alarm, o):
            hits = [bool(alarm[t:t + PULSE + WINDOW].any()) for t in starts]
            o.setdefault("pulse_alarm_frac", []).append(float(np.mean(hits)))
            o.setdefault("late_pulse_alarm_frac", []).append(float(np.mean(hits[-max(1, n_pulses // 4):])))

        _score_rules(sp, sc, end, lab_p, lab_c, cfg, out, pulses)
    return _summarise(out, used, campaign_hours=campaign / 3600, pulses=n_pulses, pulse_s=PULSE,
                      pulse_mult=PULSE_MULT, median_terminal_magnitude=float(np.median(mags)) if mags else None)


def noise_campaign(scorer, z, v, s_base, inj, cfg, seed, avoid=None):
    """E5: largest sensor noise that adds no tau0 alarm episode over a day, kept on through the terminal step."""
    rng = np.random.default_rng(seed + 303)
    campaign, _ = _campaign_slots(z)
    if campaign < 6 * 3600:
        return {"skipped": f"attack segment too short ({len(z) / STEPS_PER_DAY:.2f} days)"}
    out, used, sigmas, shifts, loud = {}, 0, [], [], 0
    for _ in range(NOISE_PLACEMENTS * 2):
        if used == NOISE_PLACEMENTS:
            break
        c0 = int(rng.integers(STEPS_PER_DAY // 2, len(z) - campaign - LEAD - ATTACK - MARGIN))
        end = c0 + campaign + LEAD
        a_idx, sensors = inj._action_and_sensors(3)
        signs = rng.choice([-1, 1], len(sensors))
        if avoid is not None and avoid[end - MARGIN:end + ATTACK + MARGIN].any():
            continue                                   # final data: keep the terminal step clear of labelled events
        m_att = _just_detectable(scorer, z, v, s_base, end, a_idx, sensors, signs, cfg["tau0"])
        if m_att is None:
            continue
        noise = rng.standard_normal((end + ATTACK - c0, len(sensors)))
        lo, hi = c0 - MARGIN, end + ATTACK + MARGIN

        def scores(sigma, m):
            def edit(Zp, Vp):
                Zp[c0 - lo:end + ATTACK - lo, sensors] += sigma * noise
                if m:
                    _terminal(Zp, Vp, end - lo, a_idx, sensors, signs, m)
            return _splice(scorer, z, v, s_base, lo, hi, edit)

        # stealth = no more frozen alarm episodes AND no more seconds above tau0 during the campaign
        # than the clean stream has there (episode count alone lets one day-long alarm pass)
        load = lambda s: (len(T._episodes(s[c0:end] > cfg["tau0"], GAP)), int((s[c0:end] > cfg["tau0"]).sum()))
        base = load(np.where(np.isfinite(s_base), s_base, -np.inf))
        quiet = lambda s: all(x <= y for x, y in zip(load(s), base))
        a, b = 0.0, 4.0
        for _ in range(8):
            mid = (a + b) / 2
            a, b = (mid, b) if quiet(scores(mid, 0.0)) else (a, mid)
        if a == 0.0:
            loud += 1                                  # even sigma = 1/64 adds alarms: no stealthy level
            continue
        used += 1
        sigmas.append(a)
        sp = scores(a, m_att)
        clean = s_base[c0:end]
        shifts.append(float(np.median(sp[c0:end]) - np.median(clean[np.isfinite(clean)])))   # noise effect only
        sc = _splice(scorer, z, v, s_base, end - MARGIN, end + ATTACK + MARGIN,
                     lambda Zp, Vp: _terminal(Zp, Vp, MARGIN, a_idx, sensors, signs, m_att))
        lab_p = np.zeros(len(z), np.int8)
        lab_p[c0:end + ATTACK] = 1
        lab_c = np.zeros(len(z), np.int8)
        lab_c[end:end + ATTACK] = 1
        _score_rules(sp, sc, end, lab_p, lab_c, cfg, out)
    return _summarise(out, used, campaign_hours=campaign / 3600, placements_without_stealthy_level=loud,
                      median_noise_sigma=float(np.median(sigmas)) if sigmas else None,
                      median_score_median_shift_vs_clean=float(np.median(shifts)) if shifts else None)


ROUNDS = {"r2": (("E1", "E2", "E3"), "tt1-dev", "threshold_transfer_dev_v1.json"),
          "r3": (("E1", "E4", "E5"), "tt1-dev-r3", "threshold_transfer_dev_v2.json"),
          "r4": (("E1", "E4"), "tt1-dev-r4", "threshold_transfer_dev_v3.json")}


def main():
    """`run <release> [round]` writes one part file per release (safe in parallel); `merge [round]` builds the JSON."""
    rnd = sys.argv[3] if sys.argv[1] == "run" and len(sys.argv) > 3 else (sys.argv[2] if sys.argv[1] == "merge" and len(sys.argv) > 2 else "r2")
    experiments, part_dir, out_name = ROUNDS[rnd]
    part = ROOT / "target/real-telemetry" / part_dir
    if sys.argv[1] == "run":
        part.mkdir(parents=True, exist_ok=True)
        (part / f"{sys.argv[2]}.json").write_text(json.dumps(run_release(sys.argv[2], experiments), indent=1), encoding="utf-8")
        return
    out = {"schema_version": "threshold-transfer-dev-v1" if rnd == "r2" else "threshold-transfer-dev-v2",
           "round": rnd, "experiments": list(experiments),
           "status": "development evidence on normal data of spent HAI releases; not a result",
           "monitor": "rt1/rt2 D1 (ridge_gbr_actions, history 3, window 60, 2 false-alarm episodes per day)",
           "releases": {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(part.glob("*.json"))}}
    (ROOT / "docs/research" / out_name).write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for r, v in out["releases"].items():
        print("==", r, "deploy days", round(v["deploy_days"], 2), "tau0", round(v["tau0"], 3), "tau_half", round(v["tau_half"], 3))
        for k, m in v["E1_budget_adherence"].items():
            print(f"   E1 {k:28s} fa/day {m['fa_per_day']:6.2f} (x{m['ratio_to_budget']:.2f}) permits {m['permits']}")
        for k, m in v.get("E2_poisoning", {}).items():
            print(f"   E2 {k:28s} event {m['event_detected']:.2f} terminal {m['terminal_detected']:.2f} ctrl {m['control_terminal_detected']:.2f} infl {m['median_threshold_inflation']:.2f}")
        for exp in ("E4_pulse_campaign", "E5_noise_campaign"):
            if exp not in v:
                continue
            e = v[exp]
            print("  ", exp, {k: (round(x, 3) if isinstance(x, float) else x) for k, x in e.items() if k != "rules"})
            for k, m in e["rules"].items():
                extra = f" pulses alarmed {m['pulse_alarm_frac']:.2f} late {m['late_pulse_alarm_frac']:.2f}" if "pulse_alarm_frac" in m else ""
                print(f"     {k:20s} terminal {m['terminal_detected_after_campaign']:.2f} ctrl {m['terminal_detected_control']:.2f} "
                      f"infl {m['median_threshold_inflation']:.2f} permits {m['mean_permits']:.1f}{extra}")


if __name__ == "__main__":
    main()
