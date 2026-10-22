#!/usr/bin/env python3
"""tt1b development: silent inflation by a closed-loop, score-level attacker (frog boiling).

Worst case for each threshold rule: during a 24 h campaign the attacker sees the rule's current
threshold tau_t and holds the score at max(clean_t, 0.97 tau_t), so the campaign itself raises no alarm
the clean stream would not raise (Chan-Tin et al.'s frog-boiling attack on outlier rejection). One hour
later a 600 s terminal bump puts the score at 1.05 tau0, which the frozen threshold detects. The control
is the same bump without the campaign. This attacker acts on the score directly, an upper bound on a
physical attacker; it measures how far each rule can be moved without a single alarm.
Online rules mirror threshold_rules / threshold_rules_ext (frozen, margin, daily, tracker, tracker_slow,
one_sided:none, spot, dspot). Normal HAI data only (development split of round r4).
Writes target/real-telemetry/tt1b-frog/<release>.json; `merge` builds docs/research/threshold_transfer_tt1b_frog_dev_v1.json.
"""
from __future__ import annotations

import json
import sys
import time
from collections import deque
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_telemetry_core as C
import real_telemetry_detect as R
import threshold_rules_ext as E
import threshold_transfer_dev as X
import tt1_final as F

ROOT = Path(__file__).resolve().parents[1]
PART = ROOT / "target/real-telemetry/tt1b-frog"
OUT = ROOT / "docs/research/threshold_transfer_tt1b_frog_dev_v1.json"
FRAC, BUMP, CAMPAIGN, LEAD, PLACEMENTS, DEPTH = 0.97, 1.05, 86400, 3600, 10, 3600
# (mode, campaign seconds): closed loop follows tau_t; fixed holds 0.97 x the rule's starting threshold
VARIANTS = [("closed", 86400), ("closed", 21600), ("closed", 3600), ("fixed", 86400)]


class Static:
    def __init__(self, tau): self.t = tau
    def tau(self): return self.t
    def update(self, x): pass


class Tracker:
    def __init__(self, cfg, eta): self.q, self.eta, self.p = cfg["tau0"], eta, cfg["p"]
    def tau(self): return self.q
    def update(self, x): self.q += self.eta * ((1.0 if x > self.q else 0.0) - self.p)


class OneSided(Tracker):
    def __init__(self, cfg, eta): super().__init__(cfg, eta); self.ceiling = cfg["tau0"]
    def tau(self): return min(self.ceiling, self.q)


class Daily:
    def __init__(self, cfg, history):
        self.t, self.p, self.buf, self.n = cfg["tau0"], cfg["p"], deque(maxlen=X.STEPS_PER_DAY), 0
    def tau(self): return self.t
    def update(self, x):                       # day boundaries counted from the stream start, as in daily_path
        self.n += 1
        if np.isfinite(x):
            self.buf.append(x)
        if self.n % X.STEPS_PER_DAY == 0:
            self.t = float(np.quantile(np.fromiter(self.buf, float), 1 - self.p))


class Spot:
    def __init__(self, cfg, calib):
        self.q = cfg["p"]
        self.t, self.s1, self.s2, self.nt, self.k, g, sg = E._init(calib, self.q, E.SPOT_LEVEL)
        self.z = E._zq(self.t, g, sg, self.q, self.k, self.nt)
    def tau(self): return self.z
    def update(self, x):
        if not np.isfinite(x) or x > self.z:
            return
        self.k += 1
        if x > self.t:
            y = x - self.t
            self.s1, self.s2, self.nt = self.s1 + y, self.s2 + y * y, self.nt + 1
            g, sg = E._gpd(self.s1, self.s2, self.nt)
            self.z = E._zq(self.t, g, sg, self.q, self.k, self.nt)


class DSpot(Spot):
    def __init__(self, cfg, calib):
        csum = np.concatenate([[0.0], np.cumsum(calib)])
        resid = calib[DEPTH:] - (csum[DEPTH:-1] - csum[:-DEPTH - 1]) / DEPTH
        super().__init__(cfg, resid)
        self.win = deque(calib[-DEPTH:].tolist())
        self.msum = float(sum(self.win))
    def tau(self): return self.msum / DEPTH + self.z
    def update(self, x):
        if not np.isfinite(x):
            return
        m = self.msum / DEPTH
        if x - m > self.z:
            return
        Spot.update(self, x - m)
        self.msum += x - self.win.popleft()
        self.win.append(x)


class SpotMLE(Spot):
    """SPOT with maximum-likelihood GPD fits (scipy), refit every REFIT new peaks: checks that a
    runaway is not an artefact of the method-of-moments estimator."""
    REFIT = 2048

    def __init__(self, cfg, calib):
        super().__init__(cfg, calib)
        self.peaks = list(calib[calib > self.t] - self.t)
        self.fitted = 0
        self._fit()

    def _fit(self):
        from scipy.stats import genpareto
        g, _, sg = genpareto.fit(np.asarray(self.peaks), floc=0)
        self.g, self.sg, self.fitted = float(g), float(sg), len(self.peaks)
        self.z = E._zq(self.t, self.g, self.sg, self.q, self.k, len(self.peaks))

    def update(self, x):
        if not np.isfinite(x) or x > self.z:
            return
        self.k += 1
        if x > self.t:
            self.peaks.append(x - self.t)
            if len(self.peaks) - self.fitted >= self.REFIT:
                self._fit()
            else:
                self.z = E._zq(self.t, self.g, self.sg, self.q, self.k, len(self.peaks))


def make(rule, cfg, calib, history):
    return {"frozen": lambda: Static(cfg["tau0"]), "margin": lambda: Static(cfg["tau_half"]),
            "daily": lambda: Daily(cfg, history), "tracker": lambda: Tracker(cfg, cfg["eta"]),
            "tracker_slow": lambda: Tracker(cfg, cfg["eta"] / 10), "one_sided:none": lambda: OneSided(cfg, cfg["eta"]),
            "spot": lambda: Spot(cfg, calib), "dspot": lambda: DSpot(cfg, calib),
            "spot_mle": lambda: SpotMLE(cfg, calib)}[rule]()


RULES = E.RULES + ["spot_mle"]


def play(rule, cfg, calib, s, c0, end, campaign, mode="closed", length=CAMPAIGN):
    """Run the rule online from the stream start; returns (detected at terminal, tau at terminal, campaign alarms)."""
    model = make(rule, cfg, calib, calib)
    hit, alarms, tau_end = False, 0, None
    level = FRAC * model.tau()
    bump = BUMP * cfg["tau0"]
    for i in range(len(s)):
        tau = model.tau()
        x = s[i] if np.isfinite(s[i]) else -np.inf      # warm-up steps reach the rules as -inf, as in tt1
        if campaign and end - LEAD - length <= i < end - LEAD and np.isfinite(x):
            x = max(x, FRAC * tau if mode == "closed" else level)
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
    s = X.d1(scorer, z, v)
    rng = np.random.default_rng(seed + 707)
    room = len(s) - CAMPAIGN - LEAD - X.ATTACK - X.STEPS_PER_DAY // 2
    keys = [f"{m}_{d // 3600}h" for m, d in VARIANTS]
    out = {k: {r: {"after": [], "control": [], "inflation": [], "campaign_alarms": []} for r in RULES} for k in keys}
    for _ in range(PLACEMENTS):
        c0 = X.STEPS_PER_DAY // 2 + int(rng.integers(0, max(1, room)))
        end = c0 + CAMPAIGN + LEAD
        for r in RULES:
            hit_c, _, _ = play(r, cfg, pooled, s, c0, end, False)
            for k, (mode, length) in zip(keys, VARIANTS):
                hit, infl, alarms = play(r, cfg, pooled, s, c0, end, True, mode, length)
                o = out[k][r]
                o["after"].append(hit); o["control"].append(hit_c); o["inflation"].append(infl); o["campaign_alarms"].append(alarms)
        print(release, "placement done", round(time.time() - t0), "s", flush=True)
    res = {"release": release, "stream_days": len(s) / X.STEPS_PER_DAY, "thresholds": cfg, "variants": {
        k: {r: {"terminal_after_campaign": float(np.mean(o["after"])), "terminal_control": float(np.mean(o["control"])),
                "median_inflation": float(np.median(o["inflation"])), "max_inflation": float(np.max(o["inflation"])),
                "median_campaign_alarm_steps": float(np.median(o["campaign_alarms"]))} for r, o in out[k].items()}
        for k in keys}}
    PART.mkdir(parents=True, exist_ok=True)
    (PART / f"{release}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")


def merge():
    rel = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(PART.glob("*.json"))}
    OUT.write_text(json.dumps({"schema_version": "threshold-transfer-tt1b-frog-dev-v1",
                               "status": "development evidence on normal data of spent HAI releases; score-level attacker (upper bound)",
                               "releases": rel}, indent=1) + "\n", encoding="utf-8")
    for k in next(iter(rel.values()))["variants"]:
        print()
        print(f"== {k}: terminal caught after / control, median inflation, campaign alarm steps")
        for r in RULES:
            row = f"{r:15s}"
            for v in rel.values():
                m = v["variants"][k][r]
                row += f"{m['terminal_after_campaign']:.1f}/{m['terminal_control']:.1f} x{m['median_inflation']:.3g} a{m['median_campaign_alarm_steps']:.0f}".rjust(30)
            print(row)


if __name__ == "__main__":
    run(sys.argv[2]) if sys.argv[1] == "run" else merge()
