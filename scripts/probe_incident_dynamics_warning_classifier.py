#!/usr/bin/env python3
"""Development-only probe: forecast-conditioned breach classifier versus margin-threshold warnings.

Uses the frozen v4-selected models. The classifier trains on FRESH development episodes (new seeds,
development generators and development mechanisms only), thresholds on the registered calibration
episodes with the unchanged 1% rule, and is compared on the development warning-validation windows.
"""
import json
import sys
import time

import numpy as np

sys.path.insert(0, r"C:\Users\marcu\Videos\cursor-os-base\scripts")
import lightgbm as lgb
import incident_dynamics_data as v2data
import incident_dynamics_v3_data as v3
import incident_dynamics_v3_dev as dev
import incident_dynamics_v3_eval as E
import incident_dynamics_v3_gbr as G
import incident_dynamics_v3_warning as W
import train_physical_world_model as P

ROOT = v3.ROOT
SEL = json.loads((ROOT / "docs/research/incident_dynamics_selection_v4.json").read_text(encoding="utf-8"))


def committee(domain):
    members = [G.load_path(ROOT / m["checkpoint"]["path"]) for m in SEL["domains"][domain]["pipelines"]["selected"]["members"]]

    def predict(data):
        return np.mean([m.predict(data) for m in members], 0)
    return predict


def margins(mean, data, domain):
    """Per-step constraint margins from a forecast (positive = breach) plus current-state margins."""
    if domain == "ferrumos":
        per = mean[:, :, [0, 1, 3]] - 0.95                       # (N,5,3)
        now = data.states[:, -1, [0, 1, 3]] - 0.95
        d = data.states[:, -1, [0, 1, 3]] - data.states[:, -2, [0, 1, 3]]
        return np.concatenate([per.reshape(len(mean), -1), per.max((1, 2))[:, None], now, d], 1)
    moving = data.future_actions[:, :, P.MOVE] > .5
    pos = np.abs(mean[:, :, :2]).max(-1) - 1
    bat = .08 - mean[:, :, P.BATTERY]
    link = .08 - mean[:, :, P.LINK]
    clr = np.where(moving, .16 - mean[:, :, P.CLEARANCE], -1)
    per = np.stack([pos, bat, link, clr], -1)                    # (N,5,4)
    s = data.states[:, -1]
    d = data.states[:, -1] - data.states[:, -2]
    now = np.stack([np.abs(s[:, :2]).max(-1) - 1, .08 - s[:, P.BATTERY], .08 - s[:, P.LINK], .16 - s[:, P.CLEARANCE]], -1)
    return np.concatenate([per.reshape(len(mean), -1), per.max((1, 2))[:, None], now,
                           d[:, [0, 1, P.CLEARANCE, P.BATTERY, P.LINK]], moving.astype(np.float32), s[:, [P.PAYLOAD]]], 1)


RECORD = ROOT / "docs/research/incident_dynamics_warning_probe_v4.json"
record = {"purpose": "Development-only probe after v4; never registered and never run on final populations.",
          "training_episodes": "incident_rows(warntrain, 1024, 391006) plus 150 episodes per development mechanism (warntrain, 391007)",
          "threshold_rule": "unchanged 1 percent empirical FPR on the registered calibration episodes",
          "evaluation": "development warning-validation windows", "domains": {}}
for domain in ("ferrumos", "physical"):
    t = time.time()
    spec = v3.spec_for(domain, 8)
    predict = committee(domain)
    rows = (v2data.incident_rows(domain, "warntrain", 1024, 391006)
            + v3.mechanism_rows(domain, "warntrain", v3.DEV_MECHANISMS[domain], 150 * 7, 391007))
    train = v3.windows(rows, spec, complete=True)
    cal = dev.load(domain, "calibration", 8)
    val = dev.warning_validation(domain, 8)
    mt, mc, mv = predict(train), predict(cal), predict(val)
    xt, xc, xv = margins(mt, train, domain), margins(mc, cal, domain), margins(mv, val, domain)
    yt = W.labels(train, domain)
    clf = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.05, num_leaves=31, min_child_samples=50,
                             subsample=0.8, subsample_freq=1, random_state=17, verbose=-1, n_jobs=8)
    clf.fit(xt, yt)
    score_c, score_v = clf.predict_proba(xc)[:, 1], clf.predict_proba(xv)[:, 1]
    yc, yv = W.labels(cal, domain), W.labels(val, domain)
    thr, coef = W.calibrate(score_c, yc)
    rep_clf = W.warning_metrics(score_v, yv, thr, coef)
    rep_margin, _, _ = E.warning_report(domain, cal, mc, None, val, mv, None, 0)
    cal3, val3 = dev.load(domain, "calibration", 3), dev.warning_validation(domain, 3)
    rep_v2, _, _ = E.warning_report(domain, cal3, E.v2_predict(domain, "selected", cal3), None, val3, E.v2_predict(domain, "selected", val3), None, 0)
    record["domains"][domain] = {}
    for name, r in (("v2 margin", rep_v2), ("v4 margin", rep_margin), ("v4 + breach classifier", rep_clf)):
        miss = 1 - (1 - r["recall"]) / (1 - rep_v2["recall"])
        record["domains"][domain][name] = {"recall": r["recall"], "fpr": r["fpr"], "miss_reduction_vs_v2": miss}
        print(f"{domain:9s} {name:24s} recall {100*r['recall']:.1f}%  FPR {100*r['fpr']:.2f}%  miss-reduction vs v2 {100*miss:.1f}%", flush=True)
    print(domain, "train windows", len(train.states), "prevalence", round(float(yt.mean()), 3), round(time.time() - t), "s", flush=True)

RECORD.write_text(json.dumps(record, indent=1), encoding="utf-8")
