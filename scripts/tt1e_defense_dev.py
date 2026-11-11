#!/usr/bin/env python3
"""tt1e development (exploratory): bounded loosening, attacks on the exclusion rules, an approval gate and
a reconstruction score, on the spent HAI releases.

Plan, rules and parameters: docs/research/threshold_transfer_tt1e_dev_plan.md (committed before any run).
  natural <release>  D1 on the release's attack files (tt1-final split, as tt1c): ceiling and gate rules
  d2 <release>       the same streams scored by the PCA reconstruction score D2
  normal <release>   r4 split of normal data: E4 pulse campaign, closed-loop frog and sub-event pulses, the
                     last two with terminal bumps of several magnitudes (same placements as tt1c)
  merge              docs/research/threshold_transfer_tt1e_dev_v1.json
Parts are written to target/real-telemetry/tt1e-dev/.
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
import real_telemetry_data as D
import real_telemetry_detect as R
import real_telemetry_injections as I
import real_telemetry_rt2 as RT2
import threshold_rules as T
import threshold_rules_tt1c as N
import threshold_rules_tt1e as B
import threshold_transfer_dev as X
import tt1_final as F
import tt1b_attacks_dev as A
import tt1b_frog_dev as G
import tt1c_baselines_dev as TC

ROOT = Path(__file__).resolve().parents[1]
PART = ROOT / "target/real-telemetry/tt1e-dev"
OUT = ROOT / "docs/research/threshold_transfer_tt1e_dev_v1.json"
REASON = ("EXPLORATORY tt1e development: bounded loosening, an approval gate and a reconstruction score on "
          "already-opened attack data")
MAGS = (1.05, 1.1, 1.25, 1.5, 2.0, 3.0, 5.0, 10.0)
SUBL_EVERY, SUBL_W, SUBL_H = 1800, 45, 2.0
CEIL = lambda kind: [f"{kind}_{k}" for k in B.KAPPAS]
NATURAL_RULES = ["frozen", "tracker", "daily", "spot_gr"] + B.NEW_RULES
FROG_RULES = ["frozen", "spot_gr"] + CEIL("spot_gr_ceil") + ["spot_gate24", "spot_gate6", "spot_gr_declust",
                                                             "daily_excl", "tracker_capped"]
SUBL_RULES = ["frozen", "daily", "daily_excl", "tracker", "tracker_hold", "tracker_capped"] + \
    CEIL("tracker_ceil") + CEIL("daily_ceil") + ["spot_gr"]
D2_RULES = ["frozen", "tracker", "daily", "daily_excl", "tracker_capped", "spot_gr", "tracker_ceil_1.25"]
PCA_VARIANCE = 0.95


def model(rule, cfg, calib):
    if rule in B.NEW_RULES:
        return B.make(rule, cfg, calib, X.STEPS_PER_DAY)
    return TC._model(rule, cfg, calib)


def tau_path(rule, s, cfg, calib):
    if rule in B.NEW_RULES:
        return N.path(B.make(rule, cfg, calib, X.STEPS_PER_DAY), s)
    return TC.tau_path(rule, s, cfg, calib)


# ---------------------------------------------------------------- reconstruction score D2
class PCAScore:
    """Residual of the scaled sensors after projection on the leading principal components."""

    def __init__(self, fit_z):
        n = sum(len(z) for z in fit_z)
        self.mu = sum(z.sum(0, dtype=np.float64) for z in fit_z) / n
        cov = np.zeros((len(self.mu), len(self.mu)))
        for z in fit_z:                                   # accumulated in blocks to keep memory flat
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

    def score(self, z):
        a = np.abs(self._resid(z)) / self.sig
        s = R.smooth((-np.sort(-a, 1)[:, :3]).mean(1), X.WINDOW)
        s[:R.WARMUP] = np.nan
        return s


# ---------------------------------------------------------------- natural poisoning on the attack files
def natural(release, score="D1"):
    t0 = time.time()
    rules = NATURAL_RULES if score == "D1" else D2_RULES
    segs = X.normal_segments(release)
    kx, ku = F.varying_columns(segs)
    segs = [(x[:, kx], u[:, ku]) for x, u in segs]
    parts = F.split(segs, F.FINAL_CUTS, ("fit", "scale", "calib"), min_len=1000)
    test = [(s.X, s.U, s.y) for s in D.hai_test(REASON)["segments"]] if release == "hai-22.04" \
        else RT2.test_segments(release, REASON)
    info = {}
    if score == "D1":
        scorer, pack, _, _, _ = F.fit_monitor(parts["fit"], parts["scale"])
        fn = lambda z, v: X.d1(scorer, z, v)
    else:
        xs = C.Scaler().fit(np.concatenate([x for x, _ in parts["fit"]]))
        us = C.Scaler().fit(np.concatenate([u for _, u in parts["fit"]]))
        pack = lambda g: [(xs(x), us(u)) for x, u in g]
        pca = PCAScore([z for z, _ in pack(parts["fit"])])
        pca.scales([z for z, _ in pack(parts["scale"])])
        fn = lambda z, v: pca.score(z)
        info = {"components": pca.k, "sensors": int(len(pca.mu))}
    cal = [s[np.isfinite(s)] for s in (fn(z, v) for z, v in pack(parts["calib"]))]
    tau0 = R.calibrate(cal, X.GAP, X.BUDGET, X.STEPS_PER_DAY)
    pooled = np.concatenate(cal)
    cfg = F.thresholds(pooled, tau0, F.ETA_MULT, 0.999)
    packed = pack([(x[:, kx], u[:, ku]) for x, u, _ in test])
    streams = [(np.where(np.isfinite(s), s, -np.inf), y)
               for s, y in ((fn(z, v), y) for (z, v), (_, _, y) in zip(packed, test))]
    print(release, score, "monitor and streams ready", round(time.time() - t0), "s", flush=True)
    rows = {r: {"found": [], "onset": [], "infl": [], "fa": 0, "un": 0, "un_alarm": 0, "extra": []} for r in rules}
    for s, y in streams:
        ev = C.events(y)
        lab = np.zeros(len(s), bool)
        for a, b in ev:
            lab[a:b] = True
        for r in rules:
            m = model(r, cfg, pooled) if r in B.NEW_RULES else None
            tau = N.path(m, s) if m is not None else TC.tau_path(r, s, cfg, pooled)
            if hasattr(m, "approvals"):
                rows[r]["extra"].append(m.approvals)
            alarm = s > tau
            eps = T._episodes(alarm, X.GAP)
            starts = np.zeros(len(s), bool)
            for a, _ in eps:
                starts[a] = True
            o = rows[r]
            o["found"] += [bool(alarm[a:b].any()) for a, b in ev]
            o["onset"] += [bool(starts[a:b].any()) for a, b in ev]
            o["infl"] += [float(tau[a] / tau0) for a, b in ev]
            o["fa"] += sum(1 for a, b in eps if not lab[a:b].any())
            o["un"] += int((~lab).sum())
            o["un_alarm"] += int((alarm & ~lab).sum())
        print(release, score, "stream done", round(time.time() - t0), "s", flush=True)
    out = {"release": release, "score": score, "thresholds": cfg, **info, "rules": {}}
    for r, o in rows.items():
        out["rules"][r] = {"events": len(o["found"]), "detected": int(sum(o["found"])),
                           "onset_detected": int(sum(o["onset"])),
                           "fa_per_day": o["fa"] / (o["un"] / X.STEPS_PER_DAY),
                           "unlabelled_alarm_share": o["un_alarm"] / o["un"],
                           "median_onset_inflation": float(np.median(o["infl"])),
                           "approvals_per_stream": o["extra"] or None,
                           "found": o["found"], "onset": o["onset"]}
    PART.mkdir(parents=True, exist_ok=True)
    name = "natural" if score == "D1" else "d2"
    (PART / f"{name}_{release}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(release, score, "natural done", round(time.time() - t0), "s", flush=True)


# ---------------------------------------------------------------- campaigns on normal data
def _score_rules(sp, sc, end, cfg, calib, out, starts=None, width=None):
    """Replacement for tt1b_attacks_dev.score_rules over NATURAL_RULES."""
    for r in NATURAL_RULES:
        tau_p = tau_path(r, sp, cfg, calib)
        tau_c = tau_path(r, sc, cfg, calib)
        o = out.setdefault(r, {"after": [], "control": [], "inflation": [], "campaign_alarmed": []})
        o["after"].append(bool((sp > tau_p)[end:end + X.ATTACK].any()))
        o["control"].append(bool((sc > tau_c)[end:end + X.ATTACK].any()))
        o["inflation"].append(float(tau_p[end] / cfg["tau0"]))
        if starts is not None:
            o["campaign_alarmed"].append(float(np.mean([(sp > tau_p)[t:t + width].any() for t in starts])))


def play(rule, cfg, calib, s, end, mode):
    """Run the rule online to the terminal window, then try every terminal magnitude on a copy of its state.
    mode: "control" (no campaign), "closed" (frog at FRAC x the deployed threshold), "subl" (sub-event pulses)."""
    m = model(rule, cfg, calib)
    c_start, c_end = end - G.LEAD - G.CAMPAIGN, end - G.LEAD
    alarms, episodes, longest, first, last = 0, 0, 0, None, None
    for i in range(end):
        tau = m.tau()
        x = s[i] if np.isfinite(s[i]) else -np.inf
        if mode != "control" and c_start <= i < c_end and np.isfinite(x):
            if mode == "closed":
                x = max(x, G.FRAC * tau)
            elif (i - c_start) % SUBL_EVERY < SUBL_W:
                x = max(x, SUBL_H * tau)
            if x > tau:
                alarms += 1
                if last is None or i - last > X.GAP + 1:   # fi1: merge across up to GAP quiet steps, as _episodes does
                    episodes += 1
                    first = i
                last = i
                longest = max(longest, i - first + 1)
        m.update(x)
    tau_end = m.tau()
    hits = {}
    for mag in MAGS:
        mm, hit = copy.deepcopy(m), False
        bump = mag * cfg["tau0"]
        for i in range(end, end + X.ATTACK):
            x = max(s[i] if np.isfinite(s[i]) else -np.inf, bump)
            hit |= bool(x > mm.tau())
            mm.update(x)
        hits[mag] = hit
    return hits, float(tau_end / cfg["tau0"]), alarms, episodes, longest


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

    fz, fv = np.concatenate([q for q, _ in fit]), np.concatenate([q for _, q in fit])
    inj = I.Injector("hai", fz, fv, seed=seed + zlib.crc32(release.encode()) % 1000)
    A.score_rules = _score_rules
    out["E4"] = A.campaign("E4", scorer, z, v, s_base, inj, cfg, pooled, seed)
    print(release, "E4 done", round(time.time() - t0), "s", flush=True)

    s = s_base
    rng = np.random.default_rng(seed + 707)                     # the placements of tt1b_frog_dev and tt1c
    room = len(s) - G.CAMPAIGN - G.LEAD - X.ATTACK - X.STEPS_PER_DAY // 2
    attacks = {"closed": FROG_RULES, "subl": SUBL_RULES}
    acc = {a: {r: {"after": {m: [] for m in MAGS}, "control": {m: [] for m in MAGS}, "inflation": [],
                   "alarms": [], "episodes": [], "longest": []} for r in rr} for a, rr in attacks.items()}
    for _ in range(G.PLACEMENTS):
        c0 = X.STEPS_PER_DAY // 2 + int(rng.integers(0, max(1, room)))
        end = c0 + G.CAMPAIGN + G.LEAD
        control = {r: play(r, cfg, pooled, s, end, "control")[0] for r in dict.fromkeys(FROG_RULES + SUBL_RULES)}
        for a, rr in attacks.items():
            for r in rr:
                hits, infl, alarms, episodes, longest = play(r, cfg, pooled, s, end, a)
                o = acc[a][r]
                for m in MAGS:
                    o["after"][m].append(hits[m])
                    o["control"][m].append(control[r][m])
                o["inflation"].append(infl); o["alarms"].append(alarms)
                o["episodes"].append(episodes); o["longest"].append(longest)
        print(release, "placement done", round(time.time() - t0), "s", flush=True)
    for a in attacks:
        out[a] = {r: {"terminal_after_campaign": {str(m): float(np.mean(o["after"][m])) for m in MAGS},
                      "terminal_control": {str(m): float(np.mean(o["control"][m])) for m in MAGS},
                      "median_inflation": float(np.median(o["inflation"])),
                      "max_inflation": float(np.max(o["inflation"])),
                      "median_campaign_alarm_steps": float(np.median(o["alarms"])),
                      "median_campaign_alarm_episodes": float(np.median(o["episodes"])),
                      "longest_campaign_alarm_episode_steps": int(np.max(o["longest"]))}
                  for r, o in acc[a].items()}
    PART.mkdir(parents=True, exist_ok=True)
    (PART / f"normal_{release}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(release, "normal done", round(time.time() - t0), "s", flush=True)


# ---------------------------------------------------------------- merge
def _vs_frozen(parts):
    """Per release and pooled: every rule against frozen under both counts."""
    per, pooled = {}, {}
    for rel, v in parts.items():
        base, base_on = v["rules"]["frozen"]["found"], v["rules"]["frozen"]["onset"]
        per[rel] = {"thresholds": v["thresholds"], **{k: v[k] for k in ("components", "sensors") if k in v}, "rules": {}}
        for r, m in v["rules"].items():
            row = {k: x for k, x in m.items() if k not in ("found", "onset")}
            if r != "frozen":
                row["vs_frozen"] = C.paired_event_bootstrap(base, m["found"], reps=10_000)
                row["vs_frozen_onset"] = C.paired_event_bootstrap(base_on, m["onset"], reps=10_000)
            per[rel]["rules"][r] = row
    if parts:
        rules = list(next(iter(parts.values()))["rules"])
        base = sum((v["rules"]["frozen"]["found"] for v in parts.values()), [])
        base_on = sum((v["rules"]["frozen"]["onset"] for v in parts.values()), [])
        for r in rules:
            f = sum((v["rules"][r]["found"] for v in parts.values()), [])
            o = sum((v["rules"][r]["onset"] for v in parts.values()), [])
            pooled[r] = {"events": len(f), "detected": int(sum(f)), "onset_detected": int(sum(o))}
            if r != "frozen":
                pooled[r]["vs_frozen"] = C.paired_event_bootstrap(base, f, reps=10_000)
                pooled[r]["vs_frozen_onset"] = C.paired_event_bootstrap(base_on, o, reps=10_000)
    return per, pooled


def merge():
    load = lambda prefix: {f.stem[len(prefix) + 1:]: json.loads(f.read_text(encoding="utf-8"))
                           for f in sorted(PART.glob(f"{prefix}_*.json"))}
    nat, pooled = _vs_frozen(load("natural"))
    d2, d2_pooled = _vs_frozen(load("d2"))
    nor = load("normal")
    OUT.write_text(json.dumps({
        "schema_version": "threshold-transfer-tt1e-dev-v1",
        "status": "exploratory development on the spent HAI releases (normal data and already-opened attack files); "
                  "plan docs/research/threshold_transfer_tt1e_dev_plan.md, committed before the runs",
        "terminal_magnitudes_over_tau0": list(MAGS),
        "natural": nat, "natural_pooled": pooled, "d2_natural": d2, "d2_natural_pooled": d2_pooled,
        "campaigns": nor,
    }, indent=1) + "\n", encoding="utf-8")
    fmt = lambda p: f"{p['detected']}/{p['events']} on{p['onset_detected']}" + (
        "" if "vs_frozen" not in p else " [%+.2f,%+.2f]" % tuple(p["vs_frozen"]["recall_difference_interval"]))
    print("== natural poisoning, D1, pooled")
    for r, p in pooled.items():
        print(f"  {r:20s} {fmt(p)}   fa/day " + " ".join(f"{v['rules'][r]['fa_per_day']:.2f}" for v in nat.values()))
    print("== natural poisoning, D2, pooled")
    for r, p in d2_pooled.items():
        print(f"  {r:20s} {fmt(p)}   fa/day " + " ".join(f"{v['rules'][r]['fa_per_day']:.2f}" for v in d2.values()))
    for rel, v in nor.items():
        print("\n==", rel, "E4 after/control/infl", {r: (m["terminal_after_campaign"], m["terminal_control"],
                                                         round(m["median_inflation"], 2)) for r, m in v["E4"]["rules"].items()})
        for a in ("closed", "subl"):
            print("  ", a, "detected after campaign at", list(MAGS), "(control at 1.05 in brackets)")
            for r, m in v[a].items():
                print(f"     {r:18s}", " ".join(f"{m['terminal_after_campaign'][str(g)]:.1f}" for g in MAGS),
                      f"({m['terminal_control']['1.05']:.1f})  infl med {m['median_inflation']:.3g} max {m['max_inflation']:.3g}"
                      f"  alarm steps {m['median_campaign_alarm_steps']:.0f} longest episode {m['longest_campaign_alarm_episode_steps']}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "natural":
        natural(sys.argv[2])
    elif cmd == "d2":
        natural(sys.argv[2], score="D2")
    elif cmd == "normal":
        normal(sys.argv[2])
    else:
        merge()
