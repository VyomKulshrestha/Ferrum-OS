#!/usr/bin/env python3
"""tt1b registered replication: adaptive alarm thresholds on never-opened ICS attack data.

Datasets: batadal now; swat and wadi when their loaders exist (their settings are registered here; the
loaders must be added by an amendment before the first access). One ledgered open per dataset. Modes:
  dry-run  <dataset>  frozen-file digest check and ledger eligibility; reads no data
  rehearse <dataset>  the same pipeline on development (normal training) data with stand-in events
  final    <dataset>  refuses if the dataset is in the ledger or a frozen file changed; one access
Per dataset: the D1 monitor (rt1/rt2 world model) and the model-free D0 score, each smoothed and
calibrated once on the most recent 20% of normal training data; every rule in threshold_rules_ext.RULES
over each test stream; real events scored per rule; and the score-level closed-loop frog
(threshold_online) placed in attack-free stretches of the longest test stream.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_telemetry_core as C
import real_telemetry_data as D
import real_telemetry_detect as R
import threshold_online as O
import threshold_rules as T
import threshold_rules_ext as E
import tt1_final as F
import tt1b_data as TB

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs/research/threshold_transfer_tt1b_protocol.json"
REHEARSAL = ROOT / "target/real-telemetry/tt1b-rehearsal"
SCORES = ("D1", "D0")
FRAC, BUMP, PLACEMENTS, SEED = 0.97, 1.05, 10, 7

# Settings in physical time: smoothing 1 min at 1 Hz but 1 h at 15 min (one step would be no smoothing),
# episodes merged across 1 min / 1 h, budget 2 per day at 1 Hz but 1 per week at 15 min, DSPOT mean over
# 1 h / 1 day, frog campaigns 24 h, 6 h and 1 h, terminal bump 10 min / 1 h, lead 1 h.
DATASETS = {
    "batadal": dict(steps_per_day=96, gap=4, window=4, budget=1 / 7, depth=96, terminal=4, lead=4,
                    campaigns=(96, 24, 4), close=24, train=TB.batadal_train, test=TB.batadal_test, event=96),
    "swat": dict(steps_per_day=86400, gap=60, window=60, budget=2.0, depth=3600, terminal=600, lead=3600,
                 campaigns=(86400, 21600, 3600), close=21600, train=None, test=None, event=600),
    "wadi": dict(steps_per_day=86400, gap=60, window=60, budget=2.0, depth=3600, terminal=600, lead=3600,
                 campaigns=(86400, 21600, 3600), close=21600, train=None, test=None, event=600),
}
FROZEN_FILES = ["scripts/tt1b_final.py", "scripts/tt1b_data.py", "scripts/threshold_online.py",
                "scripts/threshold_rules_ext.py", "scripts/threshold_rules.py", "scripts/tt1_final.py",
                "scripts/threshold_transfer_dev.py", "scripts/real_telemetry_core.py", "scripts/real_telemetry_data.py",
                "scripts/real_telemetry_detect.py", "scripts/real_telemetry_dev.py", "scripts/real_telemetry_injections.py"]


def digests():
    return {f: hashlib.sha256((ROOT / f).read_bytes().replace(b"\r\n", b"\n")).hexdigest() for f in FROZEN_FILES}


def refit(ds):
    return 2048 if ds["steps_per_day"] > 1000 else 16


def smoothed(scorer, z, v, key, window):
    s = R.smooth(scorer.raw(z, v)[0][key], window)
    s[:R.WARMUP] = np.nan
    return s


# ---------------------------------------------------------------- real events
def evaluate(streams, cfg, calib, ds):
    """Every rule over every labelled stream: detection, delay, onset inflation, false alarms."""
    rows = {r: {"events": [], "fa": 0} for r in E.RULES}
    normal = 0
    for s, y in streams:
        s = np.where(np.isfinite(s), s, -np.inf)
        ev = C.events(y)
        lab = np.zeros(len(s), bool)
        for a, b in ev:
            lab[a:b] = True
        normal += int((~lab).sum())
        prev = [None] + [b for _, b in ev[:-1]]
        for r in E.RULES:
            tau, _ = E.apply_rule(r, s, cfg, calib, ds["steps_per_day"], ds["gap"], ds["depth"], labels=y)
            alarm = s > tau
            for (a, b), pe in zip(ev, prev):
                hit = np.flatnonzero(alarm[a:b])
                rows[r]["events"].append({"found": bool(len(hit)), "delay": int(hit[0]) if len(hit) else None,
                                          "onset_inflation": float(tau[a] / cfg["tau0"]),
                                          "since_previous": None if pe is None else int(a - pe)})
            rows[r]["fa"] += sum(1 for a, b in T._episodes(alarm, ds["gap"]) if not lab[a:b].any())
    days = normal / ds["steps_per_day"]
    out = {}
    for r, v in rows.items():
        ev = v["events"]
        found = [e["found"] for e in ev]
        close = [e["found"] for e in ev if e["since_previous"] is not None and e["since_previous"] <= ds["close"]]
        far = [e["found"] for e in ev if e["since_previous"] is None or e["since_previous"] > ds["close"]]
        delays = [e["delay"] for e in ev if e["delay"] is not None]
        out[r] = {"events": len(found), "detected": int(sum(found)), "recall": float(np.mean(found)) if found else None,
                  "recall_close": float(np.mean(close)) if close else None, "n_close": len(close),
                  "recall_isolated": float(np.mean(far)) if far else None, "n_isolated": len(far),
                  "fa_per_day": v["fa"] / max(days, 1e-9), "fa_ratio_to_budget": v["fa"] / max(days, 1e-9) / ds["budget"],
                  "median_delay_steps": float(np.median(delays)) if delays else None,
                  "median_onset_inflation": float(np.median([e["onset_inflation"] for e in ev])) if ev else None,
                  "per_event": ev}
    paired = {}
    if rows["frozen"]["events"]:
        found = {r: [e["found"] for e in v["events"]] for r, v in rows.items()}
        paired = F.paired(found)
    return {"normal_days": days, "rules": out, "paired": paired}


# ---------------------------------------------------------------- closed-loop frog (score level)
def play(rule, cfg, calib, s, ds, start_attack, end, length, campaign):
    model = O.make(rule, cfg, calib, ds["steps_per_day"], ds["depth"], refit(ds))
    hit, alarms, tau_end = False, 0, None
    bump = BUMP * cfg["tau0"]
    for i in range(end + ds["terminal"]):
        tau = model.tau()
        x = s[i] if np.isfinite(s[i]) else -np.inf
        if campaign and start_attack <= i < start_attack + length and np.isfinite(x):
            x = max(x, FRAC * tau)
            alarms += x > tau
        if i >= end:
            if i == end:
                tau_end = tau
            x = max(x, bump)
            hit |= x > tau
        model.update(x)
    return bool(hit), float(tau_end / cfg["tau0"]), int(alarms)


def frog(s, y, cfg, calib, ds, seed=SEED):
    """Placements in the longest stream whose campaign, lead and terminal windows touch no labelled step."""
    rng = np.random.default_rng(seed + 909)
    longest = max(ds["campaigns"])
    span = longest + ds["lead"] + ds["terminal"]
    margin = ds["lead"]
    lab = y.astype(bool) if y is not None else np.zeros(len(s), bool)
    out = {f"closed_{c // HOUR_OF(ds)}h": {r: {"after": [], "control": [], "inflation": [], "alarms": []}
                                         for r in E.RULES} for c in ds["campaigns"]}
    used = 0
    lo = ds["steps_per_day"] // 2
    for _ in range(PLACEMENTS * 5):
        if used == PLACEMENTS or len(s) - span - margin <= lo:
            break
        c0 = int(rng.integers(lo, len(s) - span - margin))
        end = c0 + longest + ds["lead"]
        if lab[c0 - margin:end + ds["terminal"] + margin].any():
            continue
        used += 1
        for r in E.RULES:
            hit_c, _, _ = play(r, cfg, calib, s, ds, 0, end, 0, False)
            for c in ds["campaigns"]:
                hit, infl, alarms = play(r, cfg, calib, s, ds, end - ds["lead"] - c, end, c, True)
                o = out[f"closed_{c // HOUR_OF(ds)}h"][r]
                o["after"].append(hit); o["control"].append(hit_c); o["inflation"].append(infl); o["alarms"].append(alarms)
    return {"placements_used": used,
            "variants": {k: {r: {"terminal_after_campaign": float(np.mean(o["after"])) if o["after"] else None,
                                 "terminal_control": float(np.mean(o["control"])) if o["control"] else None,
                                 "median_inflation": float(np.median(o["inflation"])) if o["inflation"] else None,
                                 "median_campaign_alarm_steps": float(np.median(o["alarms"])) if o["alarms"] else None}
                             for r, o in v.items()} for k, v in out.items()}}


def HOUR_OF(ds):
    return ds["steps_per_day"] // 24


# ---------------------------------------------------------------- gates
H2_FLOOR, H3_DROP, H3_HOLD, H3_MIN = 0.10, 0.5, 0.1, 6     # H2 margin: max(0.10, two events' worth of recall)


def gates(out):
    """H1-H3 of docs/research/threshold_transfer_tt1b_protocol.json, computed from the result."""
    d1 = out["scores"]["D1"]
    b1 = d1["real_events"]["paired"].get("tracker_vs_frozen")
    b2 = d1["real_events"]["paired"].get("spot_mle_vs_frozen")
    h1 = b1 is not None and b1["recall_difference_interval"][1] < 0
    n_events = d1["real_events"]["rules"]["frozen"]["events"]
    tol = -max(H2_FLOOR, 2.0 / max(n_events, 1))
    h2 = b2 is not None and b2["recall_difference_interval"][0] >= tol
    fr = d1["frog"]
    v = fr["variants"]["closed_24h"]
    h3 = False
    if fr["placements_used"] >= H3_MIN:
        after = {r: v[r]["terminal_after_campaign"] for r in v}
        ctrl = {r: v[r]["terminal_control"] for r in v}
        h3 = after["dspot"] <= ctrl["dspot"] - H3_DROP and \
            all(after[r] >= ctrl[r] - H3_HOLD for r in ("frozen", "one_sided:none"))
    return {"H1_real_attacks_poison_tracker": bool(h1), "H1_tracker_vs_frozen": b1,
            "H2_spot_mle_noninferior_to_frozen": bool(h2), "H2_spot_mle_vs_frozen": b2, "H2_tolerance": tol,
            "H3_frog_blinds_dspot_not_frozen_or_tighten_only": bool(h3), "H3_placements": fr["placements_used"],
            "primary_success": bool(h1 and h2 and h3)}


# ---------------------------------------------------------------- pipeline
def stand_in_events(streams, ds, seed=SEED):
    """Rehearsal only: score-level stand-in events (a bump to 1.5 x the 99.9th percentile of the stream for
    `event` steps) so every event path runs on development data."""
    rng = np.random.default_rng(seed + 404)
    out = []
    for s in streams:
        y = np.zeros(len(s), np.int8)
        s = s.copy()
        n = max(1, min(6, (len(s) - 2 * ds["event"]) // (4 * ds["event"])))
        level = 1.5 * np.nanquantile(s, 0.999)
        for t in np.sort(rng.choice(np.arange(ds["event"], len(s) - 2 * ds["event"], ds["event"]), n, replace=False)):
            s[t:t + ds["event"]] = np.maximum(s[t:t + ds["event"]], level)
            y[t:t + ds["event"]] = 1
        out.append((s, y))
    return out


def run(name, final):
    ds = DATASETS[name]
    t0 = time.time()
    segs, cols = ds["train"]()
    kx, ku = F.varying_columns(segs)
    segs = [(x[:, kx], u[:, ku]) for x, u in segs]
    names = ("fit", "scale", "calib") + (() if final else ("deploy",))
    parts = F.split(segs, F.FINAL_CUTS if final else F.REHEARSAL_CUTS, names, min_len=max(200, 4 * ds["window"]))
    scorer, pack, _, _, _ = F.fit_monitor(parts["fit"], parts["scale"])
    print(name, "monitor fitted", round(time.time() - t0), "s", flush=True)
    if final:
        raw, _ = ds["test"]("tt1b final: registered replication (threshold-transfer-tt1b)")
        raw = [(x[:, kx], u[:, ku], y) for x, u, y in raw]
    else:
        raw = [(x, u, None) for x, u in parts["deploy"]]
    packed = pack([(x, u) for x, u, _ in raw])
    out = {"dataset": name, "mode": "final" if final else "rehearsal", "settings": {k: v for k, v in ds.items() if not callable(v)},
           "dropped_constant_in_development": [c for i, c in enumerate(cols["sensors"]) if i not in set(kx)] +
                                              [c for i, c in enumerate(cols["actions"]) if i not in set(ku)],
           "scores": {}}
    for key in SCORES:
        cal = [s[np.isfinite(s)] for s in (smoothed(scorer, z, v, key, ds["window"]) for z, v in pack(parts["calib"]))]
        tau0 = R.calibrate(cal, ds["gap"], ds["budget"], ds["steps_per_day"])
        pooled = np.concatenate(cal)
        cfg = F.thresholds(pooled, tau0, F.ETA_MULT, 0.999)
        streams = [smoothed(scorer, z, v, key, ds["window"]) for z, v in packed]
        labelled = [(s, y) for s, (_, _, y) in zip(streams, raw)] if final else stand_in_events(streams, ds)
        k = int(np.argmax([len(s) for s, _ in labelled]))
        s_k, y_k = labelled[k]                             # the frog runs on the stream as recorded, events included
        out["scores"][key] = {"thresholds": cfg, "real_events": evaluate(labelled, cfg, pooled, ds),
                              "frog": frog(np.where(np.isfinite(s_k), s_k, -np.inf), y_k, cfg, pooled, ds)}
        print(name, key, "done", round(time.time() - t0), "s", flush=True)
    out["gates"] = gates(out)
    out["seconds"] = round(time.time() - t0)
    print(name, "gates", {k: v for k, v in out["gates"].items() if not isinstance(v, dict)}, flush=True)
    return out


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


def main():
    mode, name = sys.argv[1], sys.argv[2]
    if name not in DATASETS:
        raise SystemExit(f"unknown dataset {name}; choose from {list(DATASETS)}")
    if mode == "dry-run":
        print("ledger:", "ALREADY OPENED" if name in ledger() else "not opened -> eligible")
        bad = check_frozen()
        print("frozen files:", "all match the registration" if not bad else f"MISMATCH {bad}")
        print("loader:", "present" if DATASETS[name]["train"] else "missing (needs an amendment before access)")
        return
    if mode == "rehearse":
        out = run(name, final=False)
        REHEARSAL.mkdir(parents=True, exist_ok=True)
        (REHEARSAL / f"{name}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
        return
    if name in ledger():
        raise SystemExit(f"REFUSE: {name} already in {D.FINAL_LEDGER}")
    bad = check_frozen()
    if bad:
        raise SystemExit(f"REFUSE: frozen files changed or protocol missing: {bad}")
    if DATASETS[name]["test"] is None:
        raise SystemExit(f"REFUSE: no registered loader for {name}")
    out = run(name, final=True)
    out["frozen_file_sha256"] = digests()
    path = ROOT / "docs/research" / f"threshold_transfer_tt1b_result_{name}.json"
    path.write_text(json.dumps({"schema_version": "threshold-transfer-tt1b-result", "protocol": PROTOCOL.name, **out},
                               indent=1) + "\n", encoding="utf-8")
    print("wrote", path)


if __name__ == "__main__":
    main()
