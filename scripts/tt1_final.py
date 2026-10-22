#!/usr/bin/env python3
"""Shared final harness: threshold-transfer study tt1 plus the pre-registered detection-v2 test.

Each fresh dataset (hai-20.07, hygrid-ics, voraus-ad) is opened once. Modes:
  dry-run  <dataset>  print the frozen plan, the frozen-file digest check and ledger eligibility; reads no data
  rehearse <dataset>  the identical pipeline on development data only: normal data split into fit /
                      residual scale / calibration / pseudo-deployment, injected events instead of real
                      ones. Writes target/real-telemetry/tt1-rehearsal/<dataset>.json
  final    <dataset>  refuses if the dataset is already in the final-access ledger or a frozen file has
                      changed since registration; otherwise records ONE access and runs tt1 (and, for
                      the stream datasets, detection-v2 under its amendment 2) on the same arrays.

Stream datasets (1 Hz): the rt1/rt2 D1 monitor, every rule in threshold_rules.RULES applied online to
each test stream, real labelled events scored per rule, and the E4/E5 campaigns of the development
study injected into the longest test stream (terminal step kept clear of labelled events).
Episodic dataset (voraus-AD, 10 Hz samples): one score per sample (max of smoothed D1), the same rules
applied to the sample sequence with a per-sample false-alarm target.
"""
from __future__ import annotations

import hashlib
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
import threshold_rules as T
import threshold_transfer_dev as X
import tt1_data as TD

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs/research/threshold_transfer_tt1_protocol.json"
REHEARSAL = ROOT / "target/real-telemetry/tt1-rehearsal"
GAP, WINDOW, BUDGET, SPD = X.GAP, X.WINDOW, X.BUDGET, X.STEPS_PER_DAY
FINAL_CUTS = (0.60, 0.80)                  # fit / residual scale / calibration (the most recent normal data)
REHEARSAL_CUTS = (0.50, 0.65, 0.75)        # fit / residual scale / calibration / pseudo-deployment
ETA_MULT = 0.01
SEED = 7
BOOT = 10_000

STREAMS = {"hai-20.07": {"detection_v2": "primary (same-testbed fresh release)",
                          "detection_v2_window": 60},     # inherited: rt1 (HAI) and rt2 both selected D1 window 60
           "hygrid-ics": {"detection_v2": "exploratory (cross-testbed; 9.6 h of normal training data)",
                          "detection_v2_window": 10}}     # no selection exists for this testbed: registered default
EPISODIC = {"voraus-ad": {"window": 10, "alpha": 0.05, "review": 50, "eta_mult": 0.05}}
DATASETS = list(STREAMS) + list(EPISODIC)

FROZEN_FILES = ["scripts/tt1_final.py", "scripts/tt1_data.py", "scripts/threshold_rules.py",
                "scripts/threshold_transfer_dev.py", "scripts/real_telemetry_core.py", "scripts/real_telemetry_data.py",
                "scripts/real_telemetry_detect.py", "scripts/real_telemetry_dev.py", "scripts/real_telemetry_injections.py",
                "scripts/real_telemetry_detection_v2.py", "scripts/real_telemetry_wm_v2.py"]


def digests():
    return {f: hashlib.sha256((ROOT / f).read_bytes().replace(b"\r\n", b"\n")).hexdigest() for f in FROZEN_FILES}


def ledger():
    if not D.FINAL_LEDGER.exists():
        return set()
    return {json.loads(line)["dataset"] for line in D.FINAL_LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()}


# ---------------------------------------------------------------- data
def normal_data(dataset):
    if dataset == "hai-20.07":
        return TD.hai2007_train()
    if dataset == "hygrid-ics":
        return TD.hygrid_dev()
    return TD.voraus_train()


def final_data(dataset, reason):
    if dataset == "hai-20.07":
        return TD.hai2007_test(reason)[0]
    if dataset == "hygrid-ics":
        return TD.hygrid_test(reason)[0]
    return TD.voraus_test(reason)[0]


def varying_columns(segs):
    """Columns that vary in development data; constant ones (e.g. a never-raised plant alarm flag) are
    dropped from development and final arrays alike, so a column the monitor never saw move cannot act
    as a label proxy through a near-zero residual scale."""
    X_all = np.concatenate([x for x, _ in segs])
    U_all = np.concatenate([u for _, u in segs])
    return np.flatnonzero(X_all.std(0) > 1e-9), np.flatnonzero(U_all.std(0) > 1e-9)


def split(segs, cuts, names, min_len=2000):
    total = sum(len(x) for x, _ in segs)
    bounds = [int(total * c) for c in cuts] + [total]
    out, off = {n: [] for n in names}, 0
    for x, u in segs:
        a, z = off, off + len(x)
        lo = 0
        for name, hi in zip(names, bounds):
            s, e = max(a, lo), min(z, hi)
            if e - s > min_len:
                out[name].append((x[s - a:e - a], u[s - a:e - a]))
            lo = hi
        off = z
    return out


# ---------------------------------------------------------------- monitor
def fit_monitor(fit_raw, scale_raw):
    xs = C.Scaler().fit(np.concatenate([x for x, _ in fit_raw]))
    us = C.Scaler().fit(np.concatenate([u for _, u in fit_raw]))
    pack = lambda g: [(xs(x), us(u)) for x, u in g]
    fit = pack(fit_raw)
    wm = R.make_world_model("ridge_gbr_actions", True).fit(fit)
    scorer = R.Scorer(wm, fit)
    scorer.residual_scales(pack(scale_raw))
    return scorer, pack, fit


def thresholds(pooled, tau0, eta_mult, spread_q):
    p = float(max((pooled > tau0).mean(), 1.0 / len(pooled)))
    m0 = float(np.median(pooled))
    spread = float(np.quantile(pooled, spread_q) - m0)
    return {"tau0": float(tau0), "tau_half": float(max(tau0, np.quantile(pooled, 1 - p / 2))), "p": p,
            "m0": m0, "spread": spread, "eta": eta_mult * spread}


def apply(rule, s, cfg, steps_per_day, gap, labels):
    return T.apply_rule(rule, s, cfg["tau0"], cfg["tau_half"], cfg["p"], cfg["eta"], steps_per_day, gap,
                        labels=labels, ref_median=cfg["m0"])


def paired(found, base_rules=("frozen", "tracker")):
    out = {}
    for base in base_rules:
        for r in found:
            if r != base and len(found[base]):
                out[f"{r}_vs_{base}"] = C.paired_event_bootstrap(found[base], found[r], reps=BOOT)
    return out


# ---------------------------------------------------------------- stream datasets
def stream_rules(scorer, cfg, streams):
    """Every rule online on every stream; labelled events (zeros in rehearsal) scored per rule."""
    acc = {r: {"found": [], "infl": [], "fa": 0, "permits": 0} for r in T.RULES}
    normal_steps = total_steps = 0
    for z, v, y in streams:
        s = X.d1(scorer, z, v)
        s = np.where(np.isfinite(s), s, -np.inf)
        ev = C.events(y)
        lab = np.zeros(len(s), bool)
        for a, b in ev:
            lab[a:b] = True
        normal_steps += int((~lab).sum())
        total_steps += len(s)
        for r in T.RULES:
            tau, meta = apply(r, s, cfg, SPD, GAP, y)
            alarm = s > tau
            for a, b in ev:
                acc[r]["found"].append(bool(alarm[a:b].any()))
                acc[r]["infl"].append(float(tau[a] / cfg["tau0"]))
            acc[r]["fa"] += sum(1 for a, b in T._episodes(alarm, GAP) if not lab[a:b].any())
            acc[r]["permits"] += meta.get("permits", 0)
    days, weeks = normal_steps / SPD, total_steps / SPD / 7
    rules = {}
    for r, a in acc.items():
        f = np.asarray(a["found"], bool)
        h = len(f) // 2
        rules[r] = {"events": int(len(f)), "detected": int(f.sum()), "recall": float(f.mean()) if len(f) else None,
                    "recall_first_half": float(f[:h].mean()) if h else None,
                    "recall_second_half": float(f[h:].mean()) if len(f) - h else None,
                    "fa_per_day": a["fa"] / max(days, 1e-9), "ratio_to_budget": a["fa"] / max(days, 1e-9) / BUDGET,
                    "permits": int(a["permits"]), "permits_per_week": a["permits"] / max(weeks, 1e-9),
                    "median_onset_inflation": float(np.median(a["infl"])) if a["infl"] else None}
    return {"normal_days": days, "total_days": total_steps / SPD, "rules": rules,
            "paired": paired({r: a["found"] for r, a in acc.items()}) if acc["frozen"]["found"] else {}}


def run_stream(dataset, final):
    t0 = time.time()
    segs, cols = normal_data(dataset)
    kx, ku = varying_columns(segs)
    segs = [(x[:, kx], u[:, ku]) for x, u in segs]
    info = {"sensors": [cols["sensors"][i] for i in kx], "actions": [cols["actions"][i] for i in ku],
            "dropped_constant_in_development": [c for i, c in enumerate(cols["sensors"]) if i not in set(kx)] +
                                               [c for i, c in enumerate(cols["actions"]) if i not in set(ku)]}
    names = ("fit", "scale", "calib") + (() if final else ("deploy",))
    parts = split(segs, FINAL_CUTS if final else REHEARSAL_CUTS, names, min_len=1000)
    scorer, pack, fit = fit_monitor(parts["fit"], parts["scale"])
    cal = [s[np.isfinite(s)] for s in (X.d1(scorer, z, v) for z, v in pack(parts["calib"]))]
    tau0 = R.calibrate(cal, GAP, BUDGET, SPD)
    cfg = thresholds(np.concatenate(cal), tau0, ETA_MULT, 0.999)
    print(dataset, "monitor fitted", round(time.time() - t0), "s", {k: round(v, 4) for k, v in cfg.items()}, flush=True)

    if final:
        reason = "tt1 shared final: threshold-transfer-tt1 + real-telemetry-detection-v2 (amendment 2)"
        raw = final_data(dataset, reason)                      # records the single final access
        raw = [(x[:, kx], u[:, ku], y) for x, u, y in raw]
        packed = pack([(x, u) for x, u, _ in raw])
        streams = [(z, v, y) for (z, v), (_, _, y) in zip(packed, raw)]
    else:
        raw = None
        streams = [(z, v, np.zeros(len(z), np.int8)) for z, v in pack(parts["deploy"])]
    out = {"dataset": dataset, "mode": "final" if final else "rehearsal", "columns": info, "thresholds": cfg,
           "normal_training_seconds": {k: int(sum(len(x) for x, _ in g)) for k, g in parts.items()},
           "real_events": stream_rules(scorer, cfg, streams)}
    print(dataset, "rules done", round(time.time() - t0), "s", flush=True)

    z, v, y = max(streams, key=lambda item: len(item[0]))
    s_base = X.d1(scorer, z, v)
    fz, fv = np.concatenate([q for q, _ in fit]), np.concatenate([q for _, q in fit])
    inj = I.Injector("hai", fz, fv, seed=SEED + zlib.crc32(dataset.encode()) % 1000)
    avoid = y.astype(bool) if final else None
    out["injection_stream_days"] = len(z) / SPD
    out["E4_pulse_campaign"] = X.pulse_campaign(scorer, z, v, s_base, inj, cfg, SEED, avoid=avoid)
    print(dataset, "E4 done", round(time.time() - t0), "s", flush=True)
    out["E5_noise_campaign"] = X.noise_campaign(scorer, z, v, s_base, inj, cfg, SEED, avoid=avoid)
    print(dataset, "E5 done", round(time.time() - t0), "s", flush=True)
    out["seconds"] = round(time.time() - t0)
    return out, segs, raw


# ---------------------------------------------------------------- episodic dataset
def run_episodic(dataset, final):
    spec = EPISODIC[dataset]
    t0 = time.time()
    samples, cols = normal_data(dataset)
    kx, ku = varying_columns(samples)
    samples = [(x[:, kx], u[:, ku]) for x, u in samples]
    n = len(samples)
    cuts = [int(n * c) for c in (FINAL_CUTS if final else REHEARSAL_CUTS)]
    fit_raw, scale_raw = samples[:cuts[0]], samples[cuts[0]:cuts[1]]
    calib_raw = samples[cuts[1]:] if final else samples[cuts[1]:cuts[2]]
    scorer, pack, fit = fit_monitor(fit_raw, scale_raw)

    def smax(z, v):
        s = R.smooth(R.scores_for(scorer, {}, z, v)["D1"], spec["window"])
        s[:R.WARMUP] = np.nan
        return float(np.nanmax(s))

    cal = np.array([smax(z, v) for z, v in pack(calib_raw)])
    cfg = thresholds(cal, float(np.quantile(cal, 1 - spec["alpha"])), spec["eta_mult"], 0.99)
    if final:
        reason = "tt1 shared final: threshold-transfer-tt1 (voraus-ad is not part of detection-v2)"
        raw = [(x[:, kx], u[:, ku], flag) for x, u, flag in final_data(dataset, reason)]
        test = [(z, v) for z, v in pack([(x, u) for x, u, _ in raw])]
        flags = np.array([f for _, _, f in raw], np.int8)
    else:
        rng = np.random.default_rng(SEED)
        fz, fv = np.concatenate([q for q, _ in fit]), np.concatenate([q for _, q in fit])
        inj = I.Injector("voraus", fz, fv, seed=SEED)
        test, flags = [], []
        for k, (z, v) in enumerate(pack(samples[cuts[2]:])):
            if k % 2:                                  # rehearsal anomaly: lagged bias on 3 coupled sensors
                _, sensors = inj._action_and_sensors(3)
                z = z.copy()
                start = len(z) // 3
                z[start:, sensors] += np.outer(I._lag_response(len(z) - start, 5.0), rng.choice([-1, 1], 3) * 1.0)
            test.append((z, v))
            flags.append(k % 2)
        flags = np.array(flags, np.int8)
    seq = np.array([smax(z, v) for z, v in test])
    found, rules = {}, {}
    anom = flags.astype(bool)
    h = int(anom.sum()) // 2
    for r in T.RULES:
        tau, meta = apply(r, seq, cfg, spec["review"], 0, flags)
        alarm = seq > tau
        found[r] = alarm[anom].tolist()
        f = np.asarray(found[r], bool)
        rules[r] = {"anomalous": int(anom.sum()), "detected": int(f.sum()), "tpr": float(f.mean()) if len(f) else None,
                    "tpr_first_half": float(f[:h].mean()) if h else None,
                    "tpr_second_half": float(f[h:].mean()) if len(f) - h else None,
                    "fpr": float(alarm[~anom].mean()) if (~anom).any() else None,
                    "fpr_ratio_to_target": float(alarm[~anom].mean() / spec["alpha"]) if (~anom).any() else None,
                    "permits": int(meta.get("permits", 0)),
                    "median_inflation_at_anomalies": float(np.median(tau[anom] / cfg["tau0"])) if anom.any() else None}
    from sklearn.metrics import roc_auc_score
    auroc = float(roc_auc_score(flags, seq)) if 0 < anom.sum() < len(flags) else None
    return {"dataset": dataset, "mode": "final" if final else "rehearsal", "spec": spec, "thresholds": cfg,
            "samples": {"fit": len(fit_raw), "scale": len(scale_raw), "calib": len(calib_raw), "test": len(test)},
            "dropped_constant_in_development": [c for i, c in enumerate(cols["sensors"]) if i not in set(kx)] +
                                               [c for i, c in enumerate(cols["actions"]) if i not in set(ku)],
            "sample_score_auroc": auroc, "rules": rules, "paired": paired(found),
            "seconds": round(time.time() - t0)}


# ---------------------------------------------------------------- modes
def dry_run(dataset):
    print(f"tt1 shared final harness; dataset {dataset}")
    print("ledger:", "ALREADY OPENED -> final would be refused" if dataset in ledger() else "not opened -> eligible")
    if not PROTOCOL.exists():
        print("protocol not registered yet:", PROTOCOL.relative_to(ROOT))
        return
    frozen = json.loads(PROTOCOL.read_text(encoding="utf-8"))["frozen_file_sha256"]
    now = digests()
    bad = [f for f in FROZEN_FILES if frozen.get(f) != now[f]]
    print("frozen files:", "all match the registration" if not bad else f"CHANGED since registration: {bad}")


def final(dataset):
    if dataset in ledger():
        raise SystemExit(f"REFUSE: {dataset} already appears in {D.FINAL_LEDGER}; a single final open is allowed.")
    if not PROTOCOL.exists():
        raise SystemExit("REFUSE: the tt1 protocol is not registered.")
    frozen = json.loads(PROTOCOL.read_text(encoding="utf-8"))["frozen_file_sha256"]
    now = digests()
    bad = [f for f in FROZEN_FILES if frozen.get(f) != now[f]]
    if bad:
        raise SystemExit(f"REFUSE: frozen files changed since registration: {bad}")
    if dataset in EPISODIC:
        out = run_episodic(dataset, final=True)
    else:
        out, segs, raw = run_stream(dataset, final=True)
        import real_telemetry_detection_v2 as DV2
        out["detection_v2"] = {"role": STREAMS[dataset]["detection_v2"], "window": STREAMS[dataset]["detection_v2_window"],
                               "result_file": f"docs/research/real_telemetry_detection_v2_result_{dataset}.json"}
        DV2.evaluate_arrays(dataset, segs, raw, BUDGET, SPD, STREAMS[dataset]["detection_v2_window"],
                            shared_final="tt1 shared final harness (detection-v2 amendment 2)")
    out["frozen_file_sha256"] = now
    path = ROOT / "docs/research" / f"threshold_transfer_tt1_result_{dataset}.json"
    path.write_text(json.dumps({"schema_version": "threshold-transfer-tt1-result", "protocol": PROTOCOL.name, **out},
                               indent=1) + "\n", encoding="utf-8")
    print("wrote", path)


def rehearse(dataset):
    out = run_episodic(dataset, final=False) if dataset in EPISODIC else run_stream(dataset, final=False)[0]
    REHEARSAL.mkdir(parents=True, exist_ok=True)
    (REHEARSAL / f"{dataset}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("wrote", REHEARSAL / f"{dataset}.json")


def main():
    mode, dataset = sys.argv[1], sys.argv[2]
    if dataset not in DATASETS:
        raise SystemExit(f"unknown dataset {dataset}; choose from {DATASETS}")
    {"dry-run": dry_run, "rehearse": rehearse, "final": final}[mode](dataset)


if __name__ == "__main__":
    main()
