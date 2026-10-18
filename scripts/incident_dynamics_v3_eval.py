"""Shared v3 evaluation helpers for development diagnostics and the registered final audit."""
from __future__ import annotations

import json

import numpy as np

import incident_dynamics_v3_data as v3
import incident_dynamics_v3_warning as warning
import run_incident_dynamics_study as v2run

V2_SELECTION = v3.ROOT / "docs/research/incident_dynamics_selection_v2.json"


def v2_pipeline(domain, name="selected"):
    return json.loads(V2_SELECTION.read_text(encoding="utf-8"))["domains"][domain]["pipelines"][name]


def v2_predict(domain, name, data):
    spec = v3.spec_for(domain, 3)
    return v2run.pipeline_predictions(v2_pipeline(domain, name), data, spec)


def warning_report(domain, calibration, cal_mean, cal_scale, evaluation, eval_mean, eval_scale, k):
    cal_labels = warning.labels(calibration, domain)
    cal_score = warning.risk_score(cal_mean, cal_scale, calibration, domain, k)
    threshold, coefficients = warning.calibrate(cal_score, cal_labels)
    labels = warning.labels(evaluation, domain)
    score = warning.risk_score(eval_mean, eval_scale, evaluation, domain, k)
    return warning.warning_metrics(score, labels, threshold, coefficients), threshold, coefficients


def summarize(metrics):
    return {key: (round(value, 5) if isinstance(value, float) else value) for key, value in metrics.items()
            if key in ("tp", "fp", "tn", "fn", "recall", "fpr", "brier", "prevalence")}
