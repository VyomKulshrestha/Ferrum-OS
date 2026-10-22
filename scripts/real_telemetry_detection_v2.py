#!/usr/bin/env python3
"""Fresh-attack detection test for WorldModelV2 (registered, run-once).

Implements docs/research/real_telemetry_detection_protocol_v2.json. It compares
the D1 normal-only world-model residual detector built on WorldModelV2
(feat_h12_w24) against the same detector built on the rt1/rt2 baseline forecaster,
on a FRESH, never-opened ICS attack recording. Everything (both forecasters, the
D1 detector, the residual scale, smoothing and calibration) is frozen by the
protocol; nothing is tuned on the attack data.

It is a readiness tool: with no fresh data it refuses to invent a result. It also
refuses to open a dataset whose id already appears in the final-access ledger, so
the HAI releases spent by rt1/rt2 cannot be reused here.

Input contract (--npz PATH): an .npz with
  train_X{i},  train_U{i}            normal segments (sensors, actions)
  attack_X{i}, attack_U{i}, attack_y{i}   attack segments (sensors, actions, per-step 0/1 label)
same column order across train and attack.

Usage:
  python scripts/real_telemetry_detection_v2.py <dataset_id> --dry-run
  python scripts/real_telemetry_detection_v2.py <dataset_id> --npz fresh.npz [--budget 2.0] [--steps-per-day 86400] [--window 10]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_telemetry_core as C
import real_telemetry_data as D
import real_telemetry_detect as DET
import real_telemetry_dev as dev
import real_telemetry_wm_v2 as V2

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs/research/real_telemetry_detection_protocol_v2.json"
GAP = 60
DEFAULT_WINDOW = 10
BASELINE_GBR = dict(n_estimators=60, num_leaves=31, learning_rate=0.1,
                    min_child_samples=100, subsample=0.8, subsample_freq=1)
CUTS = (0.45, 0.70, 0.90)   # fit / residual-scale / calibration / fa-holdout


def _git_commit(path: Path) -> str:
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%h", "--", str(path)],
                             cwd=ROOT, capture_output=True, text=True, timeout=15)
        return out.stdout.strip() or "uncommitted"
    except Exception:
        return "unknown"


def ledger_datasets() -> set[str]:
    if not D.FINAL_LEDGER.exists():
        return set()
    seen = set()
    for line in D.FINAL_LEDGER.read_text(encoding="utf-8").splitlines():
        try:
            seen.add(json.loads(line)["dataset"])
        except Exception:
            pass
    return seen


def load_npz(path: Path):
    data = np.load(path)
    keys = set(data.files)
    n_tr = len([k for k in keys if k.startswith("train_X")])
    n_at = len([k for k in keys if k.startswith("attack_X")])
    missing = []
    if n_tr == 0:
        missing.append("train_X{i}")
    if n_at == 0:
        missing.append("attack_X{i}/attack_y{i}")
    for i in range(n_at):
        if f"attack_y{i}" not in keys:
            missing.append(f"attack_y{i}")
    if missing:
        raise SystemExit(f"REFUSE: {path} missing required arrays: {sorted(set(missing))}. "
                         f"See the input_contract in {PROTOCOL.name}.")
    train = [(data[f"train_X{i}"].astype(np.float32),
              data[f"train_U{i}"].astype(np.float32) if f"train_U{i}" in keys else None)
             for i in range(n_tr)]
    attack = [(data[f"attack_X{i}"].astype(np.float32),
               data[f"attack_U{i}"].astype(np.float32) if f"attack_U{i}" in keys else None,
               data[f"attack_y{i}"].astype(np.int8)) for i in range(n_at)]
    return train, attack


def split_normal(train, xs, us):
    """Chronological fit / residual-scale / calibration / fa-holdout split."""
    pack = lambda x, u: (xs(x), None if u is None else (us(u) if us is not None else None))
    total = sum(len(x) for x, _ in train)
    b = [int(total * c) for c in CUTS]
    parts = {"fit": [], "scale": [], "cal": [], "fa": []}
    off = 0
    names = (("fit", 0, b[0]), ("scale", b[0], b[1]), ("cal", b[1], b[2]), ("fa", b[2], total))
    for x, u in train:
        a, z = off, off + len(x)
        for name, lo, hi in names:
            s, e = max(a, lo), min(z, hi)
            if e - s > 2 * V2.WINDOW + DET.WARMUP:
                xp, up = pack(x[s - a:e - a], None if u is None else u[s - a:e - a])
                parts[name].append((xp, up))
        off = z
    return parts


def d1_scores(scorer, segments_zv, window):
    """Smoothed D1 score per (Z,V) segment."""
    out = []
    for Z, V in segments_zv:
        base, _ = scorer.raw(Z, V)
        out.append(DET.smooth(base["D1"], window))
    return out


def evaluate(scorer, attack_scaled, window, threshold):
    """Event recall / delays over attack segments; per-event found booleans in order."""
    found, delays, detected, events_total = [], [], 0, 0
    for Z, V, y in attack_scaled:
        base, _ = scorer.raw(Z, V)
        score = DET.smooth(base["D1"], window)
        rep = C.event_report(score, y, threshold, tolerance=0)
        found.extend(rep["found"])
        delays.extend([d for d in rep["delays"] if d is not None])
        detected += rep["detected"]
        events_total += rep["events"]
    recall = detected / events_total if events_total else float("nan")
    return {"events": events_total, "detected": detected, "recall": recall,
            "found": found, "median_delay": float(np.median(delays)) if delays else None}


def fa_per_day(scorer, fa_scaled, window, threshold, steps_per_day):
    """False-alarm episodes/day on held-out normal (fa-holdout split)."""
    scores = d1_scores(scorer, fa_scaled, window)
    eps = sum(len(DET.episodes(s > threshold, GAP)) for s in scores)
    steps = sum(len(s) for s in scores)
    return eps / max(steps / steps_per_day, 1e-9), steps


def build_scorer(wm, parts):
    sc = DET.Scorer(wm.fit(parts["fit"]), parts["fit"])
    sc.residual_scales(parts["scale"])
    return sc


def run(dataset_id, npz, budget, steps_per_day, window):
    if dataset_id in ledger_datasets():
        raise SystemExit(f"REFUSE: dataset id '{dataset_id}' already appears in {D.FINAL_LEDGER}. "
                         f"The protocol allows a single final open; pick a genuinely unused dataset.")
    train, attack = load_npz(Path(npz))
    # Single final open: record the attack-data access before any label is touched.
    D._record_final_access(dataset_id, "real-telemetry-detection-v2 final evaluation")
    xs = C.Scaler().fit(np.concatenate([x for x, _ in train]))
    has_u = all(u is not None for _, u in train) and all(u is not None for _, u, _ in attack)
    us = C.Scaler().fit(np.concatenate([u for _, u in train])) if has_u else None
    parts = split_normal(train, xs, us)
    if not parts["fit"] or not parts["cal"] or not parts["fa"]:
        raise SystemExit("REFUSE: not enough normal data for fit/calibration/fa-holdout splits.")
    pack_at = [(xs(x), None if (u is None or us is None) else us(u), y) for x, u, y in attack]

    models = {
        "candidate_v2": V2.build(use_actions=has_u),
        "baseline_rt1": C.Forecaster(dev.HORIZONS, dev.HISTORY, use_actions=has_u, gbr=BASELINE_GBR),
    }
    out = {"dataset_id": dataset_id, "budget_per_day": budget, "steps_per_day": steps_per_day,
           "window": window, "use_actions": has_u,
           "commit": {"wm_v2": _git_commit(ROOT / "scripts/real_telemetry_wm_v2.py"),
                      "harness": _git_commit(ROOT / "scripts/real_telemetry_detection_v2.py")},
           "arms": {}}
    found = {}
    for name, wm in models.items():
        t0 = time.time()
        sc = build_scorer(wm, parts)
        cal_scores = d1_scores(sc, parts["cal"], window)
        thr = DET.calibrate(cal_scores, GAP, budget, steps_per_day)
        thr_margin = DET.calibrate(cal_scores, GAP, budget / 2, steps_per_day)
        ev = evaluate(sc, pack_at, window, thr)
        ev_margin = evaluate(sc, pack_at, window, thr_margin)
        fa, fa_steps = fa_per_day(sc, parts["fa"], window, thr, steps_per_day)
        fa_m, _ = fa_per_day(sc, parts["fa"], window, thr_margin, steps_per_day)
        found[name] = ev["found"]
        out["arms"][name] = {
            "primary": {"recall": ev["recall"], "detected": ev["detected"], "events": ev["events"],
                        "median_delay": ev["median_delay"], "fa_episodes_per_day": fa},
            "safety_margin": {"recall": ev_margin["recall"], "detected": ev_margin["detected"],
                              "fa_episodes_per_day": fa_m},
            "fa_holdout_steps": fa_steps, "seconds": round(time.time() - t0, 1),
        }
        print(f"{name}: recall {ev['recall']:.3f} ({ev['detected']}/{ev['events']}) "
              f"FA/day {fa:.2f} | margin recall {ev_margin['recall']:.3f} FA/day {fa_m:.2f}", flush=True)

    # G2: paired event bootstrap, candidate vs baseline (same event order across arms)
    boot = C.paired_event_bootstrap(found["baseline_rt1"], found["candidate_v2"], reps=10_000, level=0.95)
    cand, base = out["arms"]["candidate_v2"]["primary"], out["arms"]["baseline_rt1"]["primary"]
    g1 = cand["fa_episodes_per_day"] <= budget
    g1_slack = cand["fa_episodes_per_day"] <= 4.0
    g2 = boot["recall_difference_interval"][0] >= 0 and boot["miss_reduction"] > 0
    out["gates"] = {
        "G1_budget_holds": bool(g1), "G1_within_rt2_slack(4/day)": bool(g1_slack),
        "G2_noninferior_and_better": bool(g2),
        "paired_bootstrap_candidate_vs_baseline": boot,
        "primary_success": bool((g1 or g1_slack) and g2),
    }
    print(f"\nG1 budget {'PASS' if g1 else ('SLACK-PASS' if g1_slack else 'FAIL')}  "
          f"G2 {'PASS' if g2 else 'FAIL'}  "
          f"=> primary {'PASS' if out['gates']['primary_success'] else 'FAIL'}")
    print(f"recall diff (v2 - baseline) {boot['recall_difference']:+.3f} "
          f"CI95 [{boot['recall_difference_interval'][0]:+.3f}, {boot['recall_difference_interval'][1]:+.3f}]")

    res = ROOT / "docs/research" / f"real_telemetry_detection_v2_result_{dataset_id}.json"
    res.write_text(json.dumps({"schema_version": "real-telemetry-detection-result-v2",
                               "protocol": PROTOCOL.name, **out}, indent=1) + "\n", encoding="utf-8")
    print("wrote", res)


def dry_run(dataset_id):
    p = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    print(f"=== {p['study_id']} ({p['status']}) ===")
    print(p["status_note"])
    print("\nFrozen candidate:", p["frozen_components"]["world_model_candidate"]["name"])
    print("Baseline arm:    ", p["frozen_components"]["world_model_baseline"]["name"])
    print("Detector:        ", p["frozen_components"]["detector"]["name"])
    print("Primary gate:    ", p["gates"]["primary_success_rule"])
    already = dataset_id in ledger_datasets()
    print(f"\nDataset id '{dataset_id}': "
          f"{'ALREADY in final-access ledger -> would be REFUSED' if already else 'not yet opened -> eligible'}")
    print("\nWhen fresh, never-opened attack data is ready, run:")
    print(f"  python scripts/real_telemetry_detection_v2.py {dataset_id} --npz <fresh.npz> "
          f"--budget 2.0 --steps-per-day <rate>")
    print("Input contract:", p["data_requirements"]["input_contract"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset_id")
    ap.add_argument("--npz")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--budget", type=float, default=2.0)
    ap.add_argument("--steps-per-day", type=int, default=86400)
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    a = ap.parse_args()
    if a.dry_run:
        dry_run(a.dataset_id)
    elif a.npz:
        run(a.dataset_id, a.npz, a.budget, a.steps_per_day, a.window)
    else:
        raise SystemExit("Provide --npz <fresh.npz> to run, or --dry-run to print the frozen plan. "
                         "No fresh attack data => no result (by design).")


if __name__ == "__main__":
    main()
