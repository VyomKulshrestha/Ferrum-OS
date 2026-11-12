#!/usr/bin/env python3
"""Post-hoc analysis of the retained rt1 HAI 22.04 result (not a registered endpoint).

Question: is D2's failure a ranking failure or a threshold-transfer failure? For each detector,
the threshold is set on the TEST normal periods (an oracle no deployed system has) so that every
detector has the same false-episode rate, and event recall is compared at that matched rate. The
calibrated thresholds actually used are also compared with the matched ones. The test data are
read through the ledgered loader with an explicit post-hoc reason.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

import real_telemetry_core as C
import real_telemetry_data as D
import real_telemetry_detect as R
import real_telemetry_final as F

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/research/real_telemetry_posthoc_rt1.json"
RATES = [0.5, 1.0, 2.0]


def false_episodes(scores, labels, thr):
    """Alarm episodes (gap-merged) that touch no labelled step, summed over the test files."""
    false = 0
    for s, y in zip(scores, labels):
        labelled = y.astype(bool)
        false += sum(1 for a, b in R.episodes(s > thr, R.GAP["hai"]) if not labelled[a:b].any())
    return false


def matched_threshold(scores, labels, allowed, rule="lowest"):
    """Threshold at which the false-episode count on the test normal periods is within `allowed`.

    rule "lowest" is the search that produced the stored Table 30 numbers: every candidate is visited
    and the smallest one within the budget is kept. False-episode counts are not monotone in the
    threshold (a low threshold merges alarms into a few long episodes), so it can return a threshold far
    below the first budget break. rule "first_break" stops at the first candidate, from the top, that
    exceeds the budget, as real_telemetry_detect_v2.calibrate does (fi1 pipeline round 2, finding R1).
    """
    pooled_normal = np.concatenate([s[(y == 0) & np.isfinite(s)] for s, y in zip(scores, labels)])
    candidates = np.unique(np.quantile(pooled_normal, 1 - np.logspace(-6, -1, 250)))
    best = float(pooled_normal.max()) + 1e-9
    for thr in candidates[::-1]:
        if false_episodes(scores, labels, thr) <= allowed:
            best = float(thr)
        elif rule == "first_break":
            break
    return best


def analyse(per, labels, bundle, rule="lowest", record=False):
    """Table 30 from smoothed test scores per detector (warm-up already blanked) and test labels."""
    normal_days = sum(int((y == 0).sum()) for y in labels) / 86400
    result = {"normal_days": normal_days, "matched_rate": {}, "calibrated_threshold_quantile_on_test_normal": {}}
    for d in F.DETECTORS:
        pooled_normal = np.concatenate([s[(y == 0) & np.isfinite(s)] for s, y in zip(per[d], labels)])
        result["calibrated_threshold_quantile_on_test_normal"][d] = float((pooled_normal <= bundle["choice"][d]["thresholds"]["all"]).mean())
        for rate in RATES:
            best = matched_threshold(per[d], labels, rate * normal_days, rule)
            if record:
                result.setdefault("thresholds", {}).setdefault(str(rate), {})[d] = {
                    "threshold": best,
                    "false_episodes": false_episodes(per[d], labels, best),
                    "test_normal_alarm_share": float((pooled_normal > best).mean()),
                }
            found = []
            for s, y in zip(per[d], labels):
                for a, b in C.events(y):
                    found.append(bool((s[a:b] > best).any()))
            result["matched_rate"].setdefault(str(rate), {})[d] = {"event_recall": float(np.mean(found)), "detected": int(sum(found)),
                                                                   "events": len(found)}
    return result


def main(rule: str = "lowest", out: Path = OUT, reason: str | None = None) -> None:
    """rule "lowest" with the default output reproduces the stored file; any other run writes elsewhere."""
    selection = json.loads(F.SELECTION.read_text(encoding="utf-8"))
    bundle = F.load_bundle(selection["bundles"]["hai"])
    xs, us = bundle["scalers"]["all"]
    test = D.hai_test(reason or "post-hoc analysis after the retained rt1 final (matched false-alarm rate)")
    per = {d: [] for d in F.DETECTORS}
    labels = []
    for seg in test["segments"]:
        scores = R.scores_for(bundle["scorers"]["all"], {k: bundle["classifiers"][k] for k in ("D2", "D3")}, xs(seg.X), us(seg.U))
        for d in F.DETECTORS:
            s = R.smooth(scores[d], bundle["choice"][d]["window"])
            s[:R.WARMUP] = -np.inf
            per[d].append(s)
        labels.append(seg.y)
    result = analyse(per, labels, bundle, rule, record=rule != "lowest")
    if rule != "lowest":
        result["threshold_search"] = rule
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"schema_version": "real-telemetry-posthoc-rt1", "status": "post-hoc, not registered",
                               "dataset": "hai-22.04", **result}, indent=1) + "\n", encoding="utf-8")
    for rate, row in result["matched_rate"].items():
        print(rate, {d: (v["detected"], round(v["event_recall"], 3)) for d, v in row.items()})
    print("calibrated threshold quantile on test normal:", {d: round(v, 5) for d, v in result["calibrated_threshold_quantile_on_test_normal"].items()})


if __name__ == "__main__":
    main()
