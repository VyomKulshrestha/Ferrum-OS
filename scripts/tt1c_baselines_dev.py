#!/usr/bin/env python3
"""tt1c development (exploratory): stronger adaptive baselines and canonical SPOT on the spent HAI releases.

Plan, rules and parameters: docs/research/threshold_transfer_tt1c_dev_plan.md (committed before any run).
  natural <release>  D1 on the release's attack test files (tt1-final split, as tt1b_dev.py): every rule
  normal <release>   r4 split of normal data: E4 pulse campaign (as tt1b_attacks_dev.py) and the closed-loop
                     frog (as tt1b_frog_dev.py, same placements) with a burst variant
  merge              docs/research/threshold_transfer_tt1c_dev_v1.json
Parts are written to target/real-telemetry/tt1c-dev/.
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
import threshold_rules_ext as E
import threshold_rules_tt1c as N
import threshold_transfer_dev as X
import tt1_final as F
import tt1b_attacks_dev as A
import tt1b_frog_dev as G

ROOT = Path(__file__).resolve().parents[1]
PART = ROOT / "target/real-telemetry/tt1c-dev"
OUT = ROOT / "docs/research/threshold_transfer_tt1c_dev_v1.json"
REASON = "EXPLORATORY tt1c development: stronger adaptive baselines and canonical SPOT on already-opened attack data"
DEPTH = 3600
REF_RULES = ["frozen", "tracker", "daily", "spot", "spot_mle", "dspot"]
NATURAL_RULES = REF_RULES + N.NEW_RULES
PULSE_RULES = ["frozen", "tracker", "daily", "daily_excl", "tracker_hold", "tracker_capped", "ndt", "spot_gr",
               "spot_gr_declust"]
FROG_RULES = ["frozen", "spot_mle", "spot_gr", "spot_gr_bounded", "spot_gr_declust", "dspot_gr", "ndt",
              "daily_excl", "tracker_hold", "tracker_capped"]
FROG_VARIANTS = [("closed", 86400), ("closed", 3600), ("bursts", 86400)]
BURST_ON, BURST_OFF = 60, 120


def tau_path(rule, s, cfg, calib):
    if rule in N.NEW_RULES:
        return N.path(N.make(rule, cfg, calib, X.STEPS_PER_DAY, DEPTH), s)
    return E.apply_rule(rule, s, cfg, calib, X.STEPS_PER_DAY, X.GAP, DEPTH)[0]


# ---------------------------------------------------------------- natural poisoning on the attack files
def natural(release):
    t0 = time.time()
    segs = X.normal_segments(release)
    kx, ku = F.varying_columns(segs)
    segs = [(x[:, kx], u[:, ku]) for x, u in segs]
    parts = F.split(segs, F.FINAL_CUTS, ("fit", "scale", "calib"), min_len=1000)
    test = [(s.X, s.U, s.y) for s in D.hai_test(REASON)["segments"]] if release == "hai-22.04" \
        else RT2.test_segments(release, REASON)
    scorer, pack, _, _, _ = F.fit_monitor(parts["fit"], parts["scale"])
    cal = [s[np.isfinite(s)] for s in (X.d1(scorer, z, v) for z, v in pack(parts["calib"]))]
    tau0 = R.calibrate(cal, X.GAP, X.BUDGET, X.STEPS_PER_DAY)
    pooled = np.concatenate(cal)
    cfg = F.thresholds(pooled, tau0, F.ETA_MULT, 0.999)
    packed = pack([(x[:, kx], u[:, ku]) for x, u, _ in test])
    streams = [(np.where(np.isfinite(s), s, -np.inf), y)
               for s, y in ((X.d1(scorer, z, v), y) for (z, v), (_, _, y) in zip(packed, test))]
    print(release, "monitor and streams ready", round(time.time() - t0), "s", flush=True)
    rows = {r: {"found": [], "onset": [], "infl": [], "start": [], "fa": 0, "un": 0, "un_alarm": 0} for r in NATURAL_RULES}
    for s, y in streams:
        ev = C.events(y)
        lab = np.zeros(len(s), bool)
        for a, b in ev:
            lab[a:b] = True
        for r in NATURAL_RULES:
            tau = tau_path(r, s, cfg, pooled)
            alarm = s > tau
            eps = T._episodes(alarm, X.GAP)
            starts = np.zeros(len(s), bool)
            for a, _ in eps:
                starts[a] = True
            o = rows[r]
            o["found"] += [bool(alarm[a:b].any()) for a, b in ev]
            o["onset"] += [bool(starts[a:b].any()) for a, b in ev]
            o["infl"] += [float(tau[a] / tau0) for a, b in ev]
            o["start"].append(float(tau[0] / tau0))
            o["fa"] += sum(1 for a, b in eps if not lab[a:b].any())
            o["un"] += int((~lab).sum())
            o["un_alarm"] += int((alarm & ~lab).sum())
        print(release, "stream done", round(time.time() - t0), "s", flush=True)
    out = {"release": release, "thresholds": cfg, "rules": {}}
    for r, o in rows.items():
        out["rules"][r] = {"events": len(o["found"]), "detected": int(sum(o["found"])),
                           "onset_detected": int(sum(o["onset"])),
                           "fa_per_day": o["fa"] / (o["un"] / X.STEPS_PER_DAY),
                           "unlabelled_alarm_share": o["un_alarm"] / o["un"],
                           "median_onset_inflation": float(np.median(o["infl"])),
                           "start_over_tau0": o["start"], "found": o["found"], "onset": o["onset"]}
    PART.mkdir(parents=True, exist_ok=True)
    (PART / f"natural_{release}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(release, "natural done", round(time.time() - t0), "s", flush=True)


# ---------------------------------------------------------------- campaigns on normal data
def _score_rules(sp, sc, end, cfg, calib, out, starts=None, width=None):
    """Replacement for tt1b_attacks_dev.score_rules over PULSE_RULES."""
    for r in PULSE_RULES:
        tau_p = tau_path(r, sp, cfg, calib)
        tau_c = tau_path(r, sc, cfg, calib)
        o = out.setdefault(r, {"after": [], "control": [], "inflation": [], "campaign_alarmed": []})
        o["after"].append(bool((sp > tau_p)[end:end + X.ATTACK].any()))
        o["control"].append(bool((sc > tau_c)[end:end + X.ATTACK].any()))
        o["inflation"].append(float(tau_p[end] / cfg["tau0"]))
        if starts is not None:
            o["campaign_alarmed"].append(float(np.mean([(sp > tau_p)[t:t + width].any() for t in starts])))


def _model(rule, cfg, calib):
    if rule in N.NEW_RULES:
        return N.make(rule, cfg, calib, X.STEPS_PER_DAY, DEPTH)
    return G.make(rule, cfg, calib, calib)


def play(rule, cfg, calib, s, end, campaign, mode="closed", length=86400):
    """As tt1b_frog_dev.play; mode "bursts" holds 0.97 tau_t for BURST_ON s, then leaves BURST_OFF s clean."""
    model = _model(rule, cfg, calib)
    hit, alarms, tau_end = False, 0, None
    bump = G.BUMP * cfg["tau0"]
    c_start, c_end = end - G.LEAD - length, end - G.LEAD
    for i in range(len(s)):
        tau = model.tau()
        x = s[i] if np.isfinite(s[i]) else -np.inf
        if campaign and c_start <= i < c_end and np.isfinite(x):
            on = mode == "closed" or (i - c_start) % (BURST_ON + BURST_OFF) < BURST_ON
            if on:
                x = max(x, G.FRAC * tau)
            alarms += x > tau
        if end <= i < end + X.ATTACK:
            if i == end:
                tau_end = tau
            x = max(x, bump)
            hit |= x > tau
        model.update(x)
        if i >= end + X.ATTACK:
            break
    return bool(hit), float(tau_end / cfg["tau0"]), int(alarms)


def normal(release, seed=7):
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
    out = {"release": release, "thresholds": cfg, "stream_days": len(z) / X.STEPS_PER_DAY}
    print(release, "monitor ready", round(time.time() - t0), "s", flush=True)

    # E4, exactly as tt1b_attacks_dev.campaign, scored over PULSE_RULES
    fz, fv = np.concatenate([q for q, _ in fit]), np.concatenate([q for _, q in fit])
    inj = I.Injector("hai", fz, fv, seed=seed + zlib.crc32(release.encode()) % 1000)
    A.score_rules = _score_rules
    out["E4"] = A.campaign("E4", scorer, z, v, s_base, inj, cfg, pooled, seed)
    print(release, "E4 done", round(time.time() - t0), "s", flush=True)

    # closed-loop frog, same placements as tt1b_frog_dev.run
    s = s_base
    rng = np.random.default_rng(seed + 707)
    room = len(s) - G.CAMPAIGN - G.LEAD - X.ATTACK - X.STEPS_PER_DAY // 2
    keys = [f"{m}_{d // 3600}h" for m, d in FROG_VARIANTS]
    acc = {k: {r: {"after": [], "control": [], "inflation": [], "alarms": []} for r in FROG_RULES} for k in keys}
    for _ in range(G.PLACEMENTS):
        c0 = X.STEPS_PER_DAY // 2 + int(rng.integers(0, max(1, room)))
        end = c0 + G.CAMPAIGN + G.LEAD
        for r in FROG_RULES:
            hit_c, _, _ = play(r, cfg, pooled, s, end, False)
            for k, (mode, length) in zip(keys, FROG_VARIANTS):
                hit, infl, alarms = play(r, cfg, pooled, s, end, True, mode, length)
                o = acc[k][r]
                o["after"].append(hit); o["control"].append(hit_c); o["inflation"].append(infl); o["alarms"].append(alarms)
        print(release, "frog placement done", round(time.time() - t0), "s", flush=True)
    out["frog"] = {k: {r: {"terminal_after_campaign": float(np.mean(o["after"])),
                           "terminal_control": float(np.mean(o["control"])),
                           "median_inflation": float(np.median(o["inflation"])),
                           "max_inflation": float(np.max(o["inflation"])),
                           "median_campaign_alarm_steps": float(np.median(o["alarms"]))}
                       for r, o in acc[k].items()} for k in keys}
    PART.mkdir(parents=True, exist_ok=True)
    (PART / f"normal_{release}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(release, "normal done", round(time.time() - t0), "s", flush=True)


# ---------------------------------------------------------------- merge
def merge():
    nat = {f.stem[8:]: json.loads(f.read_text(encoding="utf-8")) for f in sorted(PART.glob("natural_*.json"))}
    nor = {f.stem[7:]: json.loads(f.read_text(encoding="utf-8")) for f in sorted(PART.glob("normal_*.json"))}
    natural_out = {}
    for rel, v in nat.items():
        base, base_on = v["rules"]["frozen"]["found"], v["rules"]["frozen"]["onset"]
        natural_out[rel] = {}
        for r, m in v["rules"].items():
            row = {k: x for k, x in m.items() if k not in ("found", "onset")}
            if r != "frozen":
                row["vs_frozen"] = C.paired_event_bootstrap(base, m["found"], reps=10_000)
                row["vs_frozen_onset"] = C.paired_event_bootstrap(base_on, m["onset"], reps=10_000)
                row["discordant_frozen_only"] = int(sum(b and not f for b, f in zip(base, m["found"])))
                row["discordant_rule_only"] = int(sum(f and not b for b, f in zip(base, m["found"])))
            natural_out[rel][r] = row
    pooled = {}
    if nat:
        base = sum((v["rules"]["frozen"]["found"] for v in nat.values()), [])
        base_on = sum((v["rules"]["frozen"]["onset"] for v in nat.values()), [])
        for r in NATURAL_RULES:
            f = sum((v["rules"][r]["found"] for v in nat.values()), [])
            o = sum((v["rules"][r]["onset"] for v in nat.values()), [])
            pooled[r] = {"events": len(f), "detected": int(sum(f)), "onset_detected": int(sum(o))}
            if r != "frozen":
                pooled[r]["vs_frozen"] = C.paired_event_bootstrap(base, f, reps=10_000)
                pooled[r]["vs_frozen_onset"] = C.paired_event_bootstrap(base_on, o, reps=10_000)
    OUT.write_text(json.dumps({
        "schema_version": "threshold-transfer-tt1c-dev-v1",
        "status": "exploratory development on the spent HAI releases (normal data and already-opened attack files); "
                  "plan docs/research/threshold_transfer_tt1c_dev_plan.md, committed before the runs",
        "natural": natural_out, "natural_pooled": pooled,
        "campaigns": {rel: {k: v[k] for k in ("thresholds", "stream_days", "E4", "frog")} for rel, v in nor.items()},
    }, indent=1) + "\n", encoding="utf-8")
    print("== natural poisoning (D1): detected / onset of events, fa/day, alarm share, start/tau0, median onset infl, vs frozen")
    for r in NATURAL_RULES:
        line = f"{r:16s}"
        for rel, v in natural_out.items():
            m = v[r]
            ci = m.get("vs_frozen", {}).get("recall_difference_interval")
            line += (f" | {m['detected']}/{m['events']} on{m['onset_detected']} fa{m['fa_per_day']:.1f} "
                     f"al{m['unlabelled_alarm_share']:.3f} st{np.median(m['start_over_tau0']):.2f} x{m['median_onset_inflation']:.1f}"
                     + ("" if ci is None else f" [{ci[0]:+.2f},{ci[1]:+.2f}]"))
        print(line)
    print("pooled", {r: (p["detected"], p["events"], p.get("vs_frozen", {}).get("recall_difference_interval"))
                     for r, p in pooled.items()})
    for rel, v in nor.items():
        print("\n==", rel, "E4: after/control/infl", {r: (m["terminal_after_campaign"], m["terminal_control"],
                                                          round(m["median_inflation"], 2)) for r, m in v["E4"]["rules"].items()})
        for k, rr in v["frog"].items():
            print("  frog", k, {r: (m["terminal_after_campaign"], m["terminal_control"], round(m["median_inflation"], 2),
                                    m["median_campaign_alarm_steps"]) for r, m in rr.items()})


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "natural":
        natural(sys.argv[2])
    elif cmd == "normal":
        normal(sys.argv[2])
    else:
        merge()
