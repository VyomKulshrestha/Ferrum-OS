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


def run_release(release, seed=7):
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
    tau_half = R.calibrate(cal_clean, GAP, BUDGET / 2, STEPS_PER_DAY)
    pooled = np.concatenate(cal_clean)
    p = float(max((pooled > tau0).mean(), 1.0 / len(pooled)))
    spread = float(np.quantile(pooled, 0.999) - np.median(pooled))
    print(release, "calibrated", round(time.time() - t0), "s; tau0", round(tau0, 3), "p", round(p, 6), flush=True)

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
                tau, meta = T.apply_rule(rule, s2, tau0, tau_half, p, eta_mult * spread, STEPS_PER_DAY, GAP)
                alarms += len(T._episodes(s2 > tau, GAP))
                permits += meta.get("permits", 0)
            key = rule if rule in ("frozen", "margin", "daily") else f"{rule}@eta{eta_mult}"
            e1[key] = {"fa_per_day": alarms / max(n_dep / STEPS_PER_DAY, 1e-9), "ratio_to_budget": alarms / max(n_dep / STEPS_PER_DAY, 1e-9) / BUDGET,
                       "permits": permits}
    print(release, "E1 done", round(time.time() - t0), "s", flush=True)

    # E2 poisoning: slow drift then a setpoint step, spliced into the longest deployment segment.
    z, v, s_base = max(dep, key=lambda item: len(item[0]))
    fz = np.concatenate([q for q, _ in fit])
    fv = np.concatenate([q for _, q in fit])
    inj = I.Injector("hai", fz, fv, seed=seed + zlib.crc32(release.encode()) % 1000)
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
            tau, _ = T.apply_rule(rule, sp, tau0, tau_half, p, ETA_MULTS[1] * spread, STEPS_PER_DAY, GAP, labels=labels)
            alarm = sp > tau
            e2[rule]["event"].append(bool(alarm[start:end + ATTACK].any()))
            e2[rule]["terminal"].append(bool(alarm[end:end + ATTACK].any()))
            e2[rule]["inflation"].append(float(tau[end] / tau0))
            sc = np.where(np.isfinite(s_ctrl), s_ctrl, -np.inf)
            tau_c, _ = T.apply_rule(rule, sc, tau0, tau_half, p, ETA_MULTS[1] * spread, STEPS_PER_DAY, GAP, labels=lab_c)
            ctrl[rule].append(bool((sc > tau_c)[end:end + ATTACK].any()))
    e2_summary = {r: {"event_detected": float(np.mean(v["event"])), "terminal_detected": float(np.mean(v["terminal"])),
                      "median_threshold_inflation": float(np.median(v["inflation"])),
                      "control_terminal_detected": float(np.mean(ctrl[r]))} for r, v in e2.items()}
    print(release, "E2 done", round(time.time() - t0), "s", flush=True)
    e3 = stealthy_poisoning(scorer, z, v, s_base, inj, tau0, tau_half, p, spread, seed)
    print(release, "E3 done", round(time.time() - t0), "s", flush=True)
    return {"release": release, "deploy_days": n_dep / STEPS_PER_DAY, "tau0": tau0, "tau_half": tau_half, "p": p,
            "E1_budget_adherence": e1, "E2_poisoning": e2_summary, "E3_stealthy_poisoning": e3, "placements": PLACEMENTS}


STEALTHY_PLACEMENTS = 12


def stealthy_poisoning(scorer, z, v, s_base, inj, tau0, tau_half, p, spread, seed):
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
            tau_p, _ = T.apply_rule(rule, sp, tau0, tau_half, p, ETA_MULTS[1] * spread, STEPS_PER_DAY, GAP, labels=lab_p)
            tau_c, _ = T.apply_rule(rule, sc, tau0, tau_half, p, ETA_MULTS[1] * spread, STEPS_PER_DAY, GAP, labels=lab_c)
            out[rule]["poisoned"].append(bool((sp > tau_p)[end:end + ATTACK].any()))
            out[rule]["control"].append(bool((sc > tau_c)[end:end + ATTACK].any()))
            out[rule]["inflation"].append(float(tau_p[end] / tau0))
    return {"placements_used": used,
            "rules": {r: {"terminal_detected_after_drift": float(np.mean(v["poisoned"])) if v["poisoned"] else None,
                          "terminal_detected_control": float(np.mean(v["control"])) if v["control"] else None,
                          "median_threshold_inflation": float(np.median(v["inflation"])) if v["inflation"] else None}
                      for r, v in out.items()}}


PART = ROOT / "target/real-telemetry/tt1-dev"


def main():
    """`run <release>` writes one part file per release (safe in parallel); `merge` builds OUT."""
    if sys.argv[1] == "run":
        PART.mkdir(parents=True, exist_ok=True)
        (PART / f"{sys.argv[2]}.json").write_text(json.dumps(run_release(sys.argv[2]), indent=1), encoding="utf-8")
        return
    out = {"schema_version": "threshold-transfer-dev-v1",
           "status": "development evidence on normal data of spent HAI releases; not a result",
           "monitor": "rt1/rt2 D1 (ridge_gbr_actions, history 3, window 60, 2 false-alarm episodes per day)",
           "releases": {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(PART.glob("*.json"))}}
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for r, v in out["releases"].items():
        print("==", r, "deploy days", round(v["deploy_days"], 2))
        for k, m in v["E1_budget_adherence"].items():
            print(f"   E1 {k:28s} fa/day {m['fa_per_day']:6.2f} (x{m['ratio_to_budget']:.2f}) permits {m['permits']}")
        for k, m in v["E2_poisoning"].items():
            print(f"   E2 {k:28s} event {m['event_detected']:.2f} terminal {m['terminal_detected']:.2f} ctrl {m['control_terminal_detected']:.2f} infl {m['median_threshold_inflation']:.2f}")


if __name__ == "__main__":
    main()
