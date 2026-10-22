#!/usr/bin/env python3
"""tt1b development: attacks matched to each threshold's learning region (normal HAI data only).

Every adaptive threshold learns from part of its input. The tracker and daily recalibration learn from
exceedances; SPOT and DSPOT (threshold_rules_ext) refuse alarms but learn from the band between their
base level t and the alarm level. Two campaigns, each ending in the just-detectable setpoint step of
threshold_transfer_dev (smallest step the frozen tau0 detects on the clean stream):
  E4  supra-threshold pulses: 12 x 120 s a day at twice the terminal magnitude (as in tt1)
  E6  sub-alarm pulses ("frog pulses"): 24 x 300 s a day at the largest magnitude that adds no frozen
      alarm episode and no second above tau0 over the campaign, i.e. invisible to the frozen threshold
Setup as development round r4 (fit 50 / scale 15 / calibration 10 / pseudo-deployment 25 %), D1 score,
10 placements on the longest pseudo-deployment segment. Writes target/real-telemetry/tt1b-attacks/<release>.json;
`merge` builds docs/research/threshold_transfer_tt1b_attacks_dev_v1.json.
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
import threshold_rules as T
import threshold_rules_ext as E
import threshold_transfer_dev as X
import tt1_final as F

ROOT = Path(__file__).resolve().parents[1]
PART = ROOT / "target/real-telemetry/tt1b-attacks"
OUT = ROOT / "docs/research/threshold_transfer_tt1b_attacks_dev_v1.json"
DEPTH = 3600
PLACEMENTS = 10
FROG_PER_DAY, FROG_S = 24, 300


def score_rules(sp, sc, end, cfg, calib, out, starts=None, width=None):
    for r in E.RULES:
        tau_p, _ = E.apply_rule(r, sp, cfg, calib, X.STEPS_PER_DAY, X.GAP, DEPTH)
        tau_c, _ = E.apply_rule(r, sc, cfg, calib, X.STEPS_PER_DAY, X.GAP, DEPTH)
        o = out.setdefault(r, {"after": [], "control": [], "inflation": [], "campaign_alarmed": []})
        o["after"].append(bool((sp > tau_p)[end:end + X.ATTACK].any()))
        o["control"].append(bool((sc > tau_c)[end:end + X.ATTACK].any()))
        o["inflation"].append(float(tau_p[end] / cfg["tau0"]))
        if starts is not None:
            o["campaign_alarmed"].append(float(np.mean([(sp > tau_p)[t:t + width].any() for t in starts])))


def summary(out, used, **info):
    return {"placements_used": used, **info,
            "rules": {r: {"terminal_after_campaign": float(np.mean(o["after"])),
                          "terminal_control": float(np.mean(o["control"])),
                          "median_inflation": float(np.median(o["inflation"])),
                          "campaign_pulses_alarmed": float(np.mean(o["campaign_alarmed"])) if o["campaign_alarmed"] else None}
                      for r, o in out.items()}}


def campaign(kind, scorer, z, v, s_base, inj, cfg, calib, seed):
    rng = np.random.default_rng(seed + (202 if kind == "E4" else 606))
    length, _ = X._campaign_slots(z)
    per_day, width = (X.PULSES_PER_DAY, X.PULSE) if kind == "E4" else (FROG_PER_DAY, FROG_S)
    n = max(1, round(per_day * length / X.STEPS_PER_DAY))
    slot = length // n
    out, used, mags = {}, 0, []
    for _ in range(PLACEMENTS * 3):
        if used == PLACEMENTS:
            break
        c0 = int(rng.integers(X.STEPS_PER_DAY // 2, len(z) - length - X.LEAD - X.ATTACK - X.MARGIN))
        end = c0 + length + X.LEAD
        a_idx, sensors = inj._action_and_sensors(3)
        signs = rng.choice([-1, 1], len(sensors))
        m_att = X._just_detectable(scorer, z, v, s_base, end, a_idx, sensors, signs, cfg["tau0"])
        if m_att is None:
            continue
        starts = [c0 + k * slot + int(rng.integers(0, slot - width - X.WINDOW)) for k in range(n)]
        resp = I._lag_response(width, 60.0)
        lo, hi = c0 - X.MARGIN, end + X.ATTACK + X.MARGIN

        def scores(m_pulse, m_term):
            def edit(Zp, Vp):
                for t in starts:
                    Vp[t - lo:t - lo + width, a_idx] += m_pulse
                    Zp[t - lo:t - lo + width, sensors] += np.outer(resp, signs * m_pulse)
                if m_term:
                    X._terminal(Zp, Vp, end - lo, a_idx, sensors, signs, m_term)
            return X._splice(scorer, z, v, s_base, lo, hi, edit)

        if kind == "E4":
            m_pulse = X.PULSE_MULT * m_att
        else:                                   # largest pulse the frozen threshold cannot see
            clean = np.where(np.isfinite(s_base), s_base, -np.inf)
            load = lambda s: (len(T._episodes(s[c0:end] > cfg["tau0"], X.GAP)), int((s[c0:end] > cfg["tau0"]).sum()))
            base = load(clean)
            a, b = 0.0, 2.0 * m_att
            for _ in range(8):
                mid = (a + b) / 2
                a, b = (mid, b) if all(x <= y for x, y in zip(load(scores(mid, 0.0)), base)) else (a, mid)
            if a == 0.0:
                continue
            m_pulse = a
        used += 1
        mags.append((m_att, m_pulse))
        sp = scores(m_pulse, m_att)
        sc = X._splice(scorer, z, v, s_base, end - X.MARGIN, end + X.ATTACK + X.MARGIN,
                       lambda Zp, Vp: X._terminal(Zp, Vp, X.MARGIN, a_idx, sensors, signs, m_att))
        score_rules(sp, sc, end, cfg, calib, out, starts, width + X.WINDOW)
    return summary(out, used, campaign_hours=length / 3600, pulses=n, pulse_s=width,
                   median_pulse_over_terminal=float(np.median([p / t for t, p in mags])) if mags else None)


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
    cal = [s[np.isfinite(s)] for s in (X.d1(scorer, z, v) for z, v in calib)]
    tau0 = R.calibrate(cal, X.GAP, X.BUDGET, X.STEPS_PER_DAY)
    pooled = np.concatenate(cal)
    cfg = F.thresholds(pooled, tau0, F.ETA_MULT, 0.999)
    z, v = max(deploy, key=lambda item: len(item[0]))
    s_base = X.d1(scorer, z, v)
    fz, fv = np.concatenate([q for q, _ in fit]), np.concatenate([q for _, q in fit])
    inj = I.Injector("hai", fz, fv, seed=seed + zlib.crc32(release.encode()) % 1000)
    out = {"release": release, "thresholds": cfg, "stream_days": len(z) / X.STEPS_PER_DAY}
    for kind in ("E4", "E6"):
        out[kind] = campaign(kind, scorer, z, v, s_base, inj, cfg, pooled, seed)
        print(release, kind, "done", round(time.time() - t0), "s", flush=True)
    PART.mkdir(parents=True, exist_ok=True)
    (PART / f"{release}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


def merge():
    rel = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(PART.glob("*.json"))}
    OUT.write_text(json.dumps({"schema_version": "threshold-transfer-tt1b-attacks-dev-v1",
                               "status": "development evidence on normal data of spent HAI releases; not a result",
                               "releases": rel}, indent=1) + "\n", encoding="utf-8")
    for kind in ("E4", "E6"):
        print(f"\n== {kind}: terminal caught after campaign / control, median inflation, pulses alarmed")
        for name, v in rel.items():
            print("  ", name, {k: (round(x, 2) if isinstance(x, float) else x) for k, x in v[kind].items() if k != "rules"})
        for r in E.RULES:
            row = f"{r:15s}"
            for v in rel.values():
                m = v[kind]["rules"].get(r)
                if m:
                    row += f"   {m['terminal_after_campaign']:.1f}/{m['terminal_control']:.1f} x{m['median_inflation']:.2f} p{m['campaign_pulses_alarmed']:.2f}"
            print(row)


if __name__ == "__main__":
    run(sys.argv[2]) if sys.argv[1] == "run" else merge()
