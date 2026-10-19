#!/usr/bin/env python3
"""Single registered final evaluation of the real-telemetry study (rt1).

Loads the frozen bundles named in docs/research/real_telemetry_selection_v1.json (refusing on any
digest mismatch), opens the recorded attacks and incidents once through the ledgered loaders,
scores every detector with its frozen smoothing window and threshold, and writes
docs/research/real_telemetry_result_v1.json with per-event outcomes and the registered gates.
"""
from __future__ import annotations

import hashlib
import json
import pickle
from pathlib import Path

import numpy as np

import real_telemetry_core as C
import real_telemetry_data as D
import real_telemetry_detect as R

ROOT = Path(__file__).resolve().parents[1]
SELECTION = ROOT / "docs/research/real_telemetry_selection_v1.json"
RESULT = ROOT / "docs/research/real_telemetry_result_v1.json"
DETECTORS = ["D0", "DR", "D1", "D2", "D3"]
COMPARISONS = [("D1", "D2"), ("D3", "D2"), ("DR", "D2"), ("D0", "D2"), ("D0", "D1"), ("DR", "D1")]
LEVEL = 0.975


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_bundle(entry):
    path = ROOT / entry["path"]
    if sha256(path) != entry["sha256"]:
        raise SystemExit(f"bundle digest mismatch: {path}")
    return R.load_bundle_bytes(path.read_bytes())


def evaluate_group(bundle, group, Z, V, y, out):
    scorer = bundle["scorers"][group]
    scores = R.scores_for(scorer, {k: bundle["classifiers"][k] for k in ("D2", "D3")}, Z, V)
    for d in DETECTORS:
        choice = bundle["choice"][d]
        s = R.smooth(scores[d], choice["window"])
        s[:R.WARMUP] = -np.inf
        alarm = s > choice["thresholds"][group]
        runs = C.events(y)
        for start, end in runs:
            hit = np.flatnonzero(alarm[start:end])
            out[d]["found"].append(bool(len(hit)))
            out[d]["delays"].append(int(hit[0]) if len(hit) else None)
            out[d]["events"].append({"group": group, "start": int(start), "end": int(end)})
        labelled = np.zeros(len(y), bool)
        for start, end in runs:
            labelled[start:end] = True
        false = [e for e in R.episodes(alarm, R.GAP[bundle["domain"]]) if not labelled[e[0]:e[1]].any()]
        out[d]["false_episodes"] += len(false)
        out[d]["normal_steps"] += int((~labelled).sum())
        out[d]["alarm_normal_steps"] += int(alarm[~labelled].sum())
        finite = np.isfinite(s)
        out[d]["scores"].append(s[finite])
        out[d]["labels"].append(y[finite])
    # World-model accuracy on normal periods only (forecast windows that touch no labelled step).
    wm = scorer.wm
    for h in (1, 5):
        t = C.valid_index(len(Z), wm.history, h)
        clean = np.array([not y[i - wm.history:i + h + 1].any() for i in t])
        t = t[clean]
        if len(t):
            err_model = np.abs(wm.predict(Z, V, t, h) - Z[t + h])
            err_persist = np.abs(Z[t] - Z[t + h])
            out["_wm"][h]["model"] += float(err_model.sum())
            out["_wm"][h]["persistence"] += float(err_persist.sum())
            out["_wm"][h]["count"] += err_model.size


def summarize(domain, out, steps_per_day):
    summary = {}
    for d in DETECTORS:
        o = out[d]
        delays = [x for x in o["delays"] if x is not None]
        scores, labels = np.concatenate(o["scores"]), np.concatenate(o["labels"])
        summary[d] = {
            "events": len(o["found"]), "detected": int(sum(o["found"])), "event_recall": float(np.mean(o["found"])),
            "false_episodes": o["false_episodes"], "normal_days": o["normal_steps"] / steps_per_day,
            "false_episodes_per_day": o["false_episodes"] / max(o["normal_steps"] / steps_per_day, 1e-9),
            "normal_step_alarm_rate": o["alarm_normal_steps"] / max(o["normal_steps"], 1),
            "median_delay_steps": float(np.median(delays)) if delays else None,
            **C.point_metrics(scores, labels),
        }
    comparisons = {}
    for a, b in COMPARISONS:
        comparisons[f"{b}_vs_{a}"] = C.paired_event_bootstrap(out[a]["found"], out[b]["found"], reps=10_000, level=LEVEL,
                                                             seed=R.SEEDS["bootstrap"])
    wm = {f"H{h}": {"model_mae": v["model"] / max(v["count"], 1), "persistence_mae": v["persistence"] / max(v["count"], 1),
                    "reduction": 1 - v["model"] / max(v["persistence"], 1e-12)} for h, v in out["_wm"].items()}
    budget = R.BUDGET_PER_DAY[domain]
    primary = comparisons["D2_vs_D1"]
    gate = {"miss_reduction": primary["miss_reduction"], "interval": primary["miss_reduction_interval"],
            "false_episodes_per_day": summary["D2"]["false_episodes_per_day"], "budget_per_day": budget,
            "passes": bool(primary["miss_reduction"] >= 0.20 and primary["miss_reduction_interval"][0] > 0
                           and summary["D2"]["false_episodes_per_day"] <= 2 * budget)}
    specificity = comparisons["D2_vs_D3"]
    return {"detectors": summary, "comparisons": comparisons, "world_model_normal_periods": wm, "primary_gate": gate,
            "specificity": {"miss_reduction": specificity["miss_reduction"], "interval": specificity["miss_reduction_interval"],
                            "excludes_zero": bool(specificity["miss_reduction_interval"][0] > 0 or specificity["miss_reduction_interval"][1] < 0)},
            "per_event": {d: [{**e, "detected": f, "delay": dl} for e, f, dl in zip(out[d]["events"], out[d]["found"], out[d]["delays"])]
                          for d in DETECTORS}}


def blank():
    out = {d: {"found": [], "delays": [], "events": [], "false_episodes": 0, "normal_steps": 0, "alarm_normal_steps": 0,
               "scores": [], "labels": []} for d in DETECTORS}
    out["_wm"] = {h: {"model": 0.0, "persistence": 0.0, "count": 0} for h in (1, 5)}
    return out


def main() -> None:
    if RESULT.exists():
        raise SystemExit("final result already exists; the registered evaluation runs once")
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    results = {}
    # HAI
    bundle = load_bundle(selection["bundles"]["hai"])
    xs, us = bundle["scalers"]["all"]
    test = D.hai_test("registered final evaluation rt1")
    out = blank()
    for seg in test["segments"]:
        evaluate_group(bundle, "all", xs(seg.X), us(seg.U), seg.y, out)
    results["hai-22.04"] = summarize("hai", out, R.STEPS_PER_DAY["hai"])
    # SMD
    bundle = load_bundle(selection["bundles"]["smd"])
    test = D.smd_test("registered final evaluation rt1")
    out = blank()
    for machine, seg in test.items():
        xs, _ = bundle["scalers"][machine]
        evaluate_group(bundle, machine, xs(seg.X), None, seg.y, out)
    results["smd"] = summarize("smd", out, R.STEPS_PER_DAY["smd"])
    passes = all(results[k]["primary_gate"]["passes"] for k in results)
    document = {"schema_version": "real-telemetry-result-v1", "study_id": "real-telemetry-rt1",
                "selection": str(SELECTION.relative_to(ROOT)), "selection_sha256": sha256(SELECTION),
                "primary_success_rule_passes": passes, "datasets": results}
    RESULT.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    for k, r in results.items():
        print(k, {d: (round(v["event_recall"], 3), round(v["false_episodes_per_day"], 2)) for d, v in r["detectors"].items()},
              "gate", r["primary_gate"]["passes"], "specificity", r["specificity"])
    print("primary success rule:", passes)


if __name__ == "__main__":
    main()
