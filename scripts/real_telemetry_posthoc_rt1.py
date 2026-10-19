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


def main() -> None:
    selection = json.loads(F.SELECTION.read_text(encoding="utf-8"))
    bundle = F.load_bundle(selection["bundles"]["hai"])
    xs, us = bundle["scalers"]["all"]
    test = D.hai_test("post-hoc analysis after the retained rt1 final (matched false-alarm rate)")
    per = {d: [] for d in F.DETECTORS}
    labels = []
    for seg in test["segments"]:
        scores = R.scores_for(bundle["scorers"]["all"], {k: bundle["classifiers"][k] for k in ("D2", "D3")}, xs(seg.X), us(seg.U))
        for d in F.DETECTORS:
            s = R.smooth(scores[d], bundle["choice"][d]["window"])
            s[:R.WARMUP] = -np.inf
            per[d].append(s)
        labels.append(seg.y)
    normal_days = sum(int((y == 0).sum()) for y in labels) / 86400
    result = {"normal_days": normal_days, "matched_rate": {}, "calibrated_threshold_quantile_on_test_normal": {}}
    for d in F.DETECTORS:
        pooled_normal = np.concatenate([s[(y == 0) & np.isfinite(s)] for s, y in zip(per[d], labels)])
        result["calibrated_threshold_quantile_on_test_normal"][d] = float((pooled_normal <= bundle["choice"][d]["thresholds"]["all"]).mean())
        for rate in RATES:
            candidates = np.unique(np.quantile(pooled_normal, 1 - np.logspace(-6, -1, 250)))
            best = float(pooled_normal.max()) + 1e-9
            for thr in candidates[::-1]:
                false = 0
                for s, y in zip(per[d], labels):
                    labelled = y.astype(bool)
                    false += sum(1 for a, b in R.episodes(s > thr, R.GAP["hai"]) if not labelled[a:b].any())
                if false <= rate * normal_days:
                    best = float(thr)
            found = []
            for s, y in zip(per[d], labels):
                for a, b in C.events(y):
                    found.append(bool((s[a:b] > best).any()))
            result["matched_rate"].setdefault(str(rate), {})[d] = {"event_recall": float(np.mean(found)), "detected": int(sum(found)),
                                                                   "events": len(found)}
    OUT.write_text(json.dumps({"schema_version": "real-telemetry-posthoc-rt1", "status": "post-hoc, not registered",
                               "dataset": "hai-22.04", **result}, indent=1) + "\n", encoding="utf-8")
    for rate, row in result["matched_rate"].items():
        print(rate, {d: (v["detected"], round(v["event_recall"], 3)) for d, v in row.items()})
    print("calibrated threshold quantile on test normal:", {d: round(v, 5) for d, v in result["calibrated_threshold_quantile_on_test_normal"].items()})


if __name__ == "__main__":
    main()
