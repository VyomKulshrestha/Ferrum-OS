#!/usr/bin/env python3
"""fi1 workstream B, round 2: did the frozen non-monotone `calibrate` decide any rt1/rt2 threshold?

`real_telemetry_detect.calibrate` (frozen) keeps the smallest candidate whose false-episode count is within
the budget, scanning every candidate. Episode counts are not monotone in the threshold, so it can return a
threshold far below the first budget break (monitor audit 2026-11-10, finding 1). That audit checked only the
D1 calibrations, by their alarm share. This script rebuilds the clean calibration scores of every rt1 HAI and
rt2 detector from NORMAL training data only (no test file, no ledger row), checks that the frozen routine
reproduces the threshold stored in each frozen bundle, and reports what `real_telemetry_detect_v2.calibrate`
(stop at the first budget break) returns on the same scores.

Memory: the classifier feature matrix is built in row chunks; every per-step quantity that depends on the
past (residuals, the 10-step rolling mean of S1) is computed on the whole array first, so the scores are the
same numbers the registered pipeline computed.

Usage (from scripts/): python fi1_rt_calibration_check.py [rt1-hai] [hai-21.03] [hai-23.05]
Output: target/real-telemetry/fi1/pipeline2/rt_calibration_check.json
"""

from __future__ import annotations

import hashlib
import json
import pickle
import sys
from pathlib import Path

import numpy as np

import real_telemetry_core as C
import real_telemetry_data as D
import real_telemetry_detect as R
import real_telemetry_detect_v2 as R2
import repro_env

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "target/real-telemetry/fi1/pipeline2/rt_calibration_check.json"
DETECTORS = ["D0", "DR", "D1", "D2", "D3"]


def raw_scores(scorer, classifiers, Z, V, chunk=20_000):
    """`real_telemetry_detect.scores_for` with the feature matrix built in row chunks (same values)."""
    top = lambda A, k: -np.sort(-A, 1)[:, :k]  # noqa: E731
    S1 = np.abs(C.residuals(scorer.wm, Z, V, 1)) / scorer.sig1
    S5 = np.abs(C.residuals(scorer.wm, Z, V, 5)) / scorer.sig5
    S1[: R.WARMUP] = 0
    S5[: R.WARMUP] = 0
    roll = C.rolling_mean(S1, 10)
    dZ = np.vstack([np.zeros((1, Z.shape[1]), Z.dtype), np.diff(Z, axis=0)])
    dV = (
        np.abs(np.vstack([np.zeros((1, V.shape[1]), V.dtype), np.diff(V, axis=0)]))
        if V is not None
        else None
    )
    out = {d: np.empty(len(Z)) for d in DETECTORS}
    for a in range(0, len(Z), chunk):
        b = min(a + chunk, len(Z))
        s1, s5, z, dz = S1[a:b], S5[a:b], Z[a:b], dZ[a:b]
        G = np.abs(dz) / scorer.dsig
        exceed = np.maximum.reduce(
            [
                np.maximum(0, z - scorer.high),
                np.maximum(0, scorer.low - z),
                np.maximum(0, np.abs(dz) - scorer.dmax) / scorer.dsig,
            ]
        )
        parts = [
            s1,
            roll[a:b],
            s5,
            G,
            top(s1, 5),
            s1.mean(1, keepdims=True),
            top(s5, 5),
        ]
        if V is not None:
            v = V[a:b]
            vex = np.maximum(0, v - scorer.vhigh) + np.maximum(0, scorer.vlow - v)
            exceed = np.concatenate([exceed, vex], 1)
            parts += [dV[a:b], vex]
        out["D0"][a:b] = top(G, 3).mean(1)
        out["DR"][a:b] = exceed.max(1)
        out["D1"][a:b] = top(s1, 3).mean(1) + top(s5, 3).mean(1)
        F = np.concatenate(parts, 1).astype(np.float32)
        for name, model in classifiers.items():
            out[name][a:b] = model.predict_proba(F)[:, 1]
    return out


def episode_count(clean, thr, gap):
    return sum(len(R.episodes(s > thr, gap)) for s in clean)


def describe(clean, thr, gap):
    pooled = np.concatenate(clean)
    return {
        "threshold": float(thr),
        "episodes": episode_count(clean, thr, gap),
        "alarm_share": float(np.mean(pooled > thr)),
    }


def compare(name, clean_by_detector, choice, gap, budget, steps_per_day, stored_key):
    rows = {}
    days = sum(len(s) for s in clean_by_detector["D1"]) / steps_per_day
    for d in DETECTORS:
        w = choice[d]["window"]
        clean = [R.smooth(s, w) for s in clean_by_detector[d]]
        stored = (
            choice[d][stored_key]
            if stored_key == "threshold"
            else choice[d]["thresholds"]["all"]
        )
        frozen = R.calibrate(clean, gap, budget, steps_per_day)
        fixed = R2.calibrate(clean, gap, budget, steps_per_day)
        rows[d] = {
            "window": w,
            "stored": float(stored),
            "frozen_reproduces_stored": bool(frozen == stored),
            "frozen": describe(clean, frozen, gap),
            "first_break_v2": describe(clean, fixed, gap),
            "differs": bool(frozen != fixed),
        }
    print(
        name,
        json.dumps(
            {d: (r["frozen_reproduces_stored"], r["differs"]) for d, r in rows.items()}
        ),
        flush=True,
    )
    return {
        "calibration_days": days,
        "allowed_episodes": budget * days,
        "detectors": rows,
    }


def bundle(path):
    with open(path, "rb") as handle:
        return R.load_bundle_bytes(handle.read())


def rt1_hai():
    selection = json.loads(
        (ROOT / "docs/research/real_telemetry_selection_v1.json").read_text(
            encoding="utf-8"
        )
    )
    entry = selection["bundles"]["hai"]
    path = ROOT / entry["path"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"], (
        "rt1 bundle digest"
    )
    b = bundle(path)
    xs, us = b["scalers"]["all"]
    clfs = {k: b["classifiers"][k] for k in ("D2", "D3")}
    clean = {d: [] for d in DETECTORS}
    for seg in D.hai_train()["segments"][5:]:
        s = raw_scores(b["scorers"]["all"], clfs, xs(seg.X), us(seg.U))
        for d in DETECTORS:
            clean[d].append(s[d][R.WARMUP :])
    return compare(
        "rt1-hai",
        clean,
        b["choice"],
        R.GAP["hai"],
        R.BUDGET_PER_DAY["hai"],
        R.STEPS_PER_DAY["hai"],
        "thresholds",
    )


def rt2(release):
    import real_telemetry_rt2 as RT2

    selection = json.loads(
        (ROOT / "docs/research/real_telemetry_selection_rt2.json").read_text(
            encoding="utf-8"
        )
    )
    entry = selection["bundles"][release]
    path = ROOT / entry["path"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"], (
        f"{release} bundle digest"
    )
    b = pickle.loads(path.read_bytes())
    xs, us = b["scalers"]
    segments, _ = RT2.train_segments(release)
    cal = RT2.split_by_time(segments)["cal"]
    del segments
    clean = {d: [] for d in DETECTORS}
    for x, u in cal:
        s = raw_scores(b["scorer"], b["classifiers"], xs(x), us(u))
        for d in DETECTORS:
            clean[d].append(s[d][R.WARMUP :])
    result = compare(
        release,
        clean,
        b["choice"],
        R.GAP["hai"],
        R.BUDGET_PER_DAY["hai"],
        R.STEPS_PER_DAY["hai"],
        "threshold",
    )
    d1 = b["choice"]["D1"]
    fraction = float(
        np.mean(
            np.concatenate([R.smooth(s, d1["window"]) for s in clean["D1"]])
            > d1["threshold"]
        )
    )
    result["D2c_matched_fraction"] = {
        "stored": b["choice"]["D2c"]["matched_clean_alarm_fraction"],
        "recomputed": fraction,
    }
    return result


def rt1_posthoc():
    """Table 30 under both threshold searches from one ledgered read of the HAI 22.04 test files."""
    import real_telemetry_final as F
    import real_telemetry_posthoc_rt1 as P

    selection = json.loads(F.SELECTION.read_text(encoding="utf-8"))
    b = F.load_bundle(selection["bundles"]["hai"])
    xs, us = b["scalers"]["all"]
    clfs = {k: b["classifiers"][k] for k in ("D2", "D3")}
    test = D.hai_test(
        "EXPLORATORY fi1 pipeline2 (workstream B round 2): Table 30 post-hoc matched-rate search, "
        "lowest-within-budget versus first budget break; no registered number is replaced"
    )
    per, labels = {d: [] for d in DETECTORS}, []
    for seg in test["segments"]:
        scores = raw_scores(b["scorers"]["all"], clfs, xs(seg.X), us(seg.U))
        for d in DETECTORS:
            s = R.smooth(scores[d], b["choice"][d]["window"])
            s[: R.WARMUP] = -np.inf
            per[d].append(s)
        labels.append(seg.y)
    del test
    stored = json.loads(P.OUT.read_text(encoding="utf-8"))
    lowest = P.analyse(per, labels, b, "lowest", record=True)
    first = P.analyse(per, labels, b, "first_break", record=True)
    # Registered thresholds (Table 28) against the first-break calibration of the same clean scores.
    calibrated = (
        json.loads(OUT.read_text(encoding="utf-8"))
        .get("rt1-hai", {})
        .get("detectors", {})
    )
    registered = json.loads(F.RESULT.read_text(encoding="utf-8"))["datasets"][
        "hai-22.04"
    ]["detectors"]
    normal_days = sum(int((y == 0).sum()) for y in labels) / R.STEPS_PER_DAY["hai"]
    table28 = {}
    for d in DETECTORS:
        row = {}
        for label, thr in (
            ("registered", b["choice"][d]["thresholds"]["all"]),
            (
                "first_break_v2",
                calibrated.get(d, {}).get("first_break_v2", {}).get("threshold"),
            ),
        ):
            if thr is None:
                continue
            found = [
                bool((s[a:e] > thr).any())
                for s, y in zip(per[d], labels)
                for a, e in C.events(y)
            ]
            row[label] = {
                "threshold": thr,
                "detected": int(sum(found)),
                "events": len(found),
                "false_episodes_per_day": P.false_episodes(per[d], labels, thr)
                / normal_days,
            }
        row["registered_reproduces_table_28"] = (
            row["registered"]["detected"] == registered[d]["detected"]
        )
        table28[d] = row
    return {
        "lowest_reproduces_stored": lowest["matched_rate"] == stored["matched_rate"],
        "stored_rule": {
            "matched_rate": lowest["matched_rate"],
            "thresholds": lowest["thresholds"],
        },
        "first_break": {
            "matched_rate": first["matched_rate"],
            "thresholds": first["thresholds"],
        },
        "table28_thresholds": table28,
    }


def main():
    targets = sys.argv[1:] or ["rt1-hai", "hai-21.03", "hai-23.05"]
    report = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    for t in targets:
        report[t] = (
            rt1_hai()
            if t == "rt1-hai"
            else rt1_posthoc()
            if t == "rt1-posthoc"
            else rt2(t)
        )
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
        repro_env.stamp_json(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    repro_env.pin_from_environment()
    main()
