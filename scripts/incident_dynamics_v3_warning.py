"""Uncertainty-aware constraint-margin warnings for incident-dynamics v3.

A warning score is still a function of the forecast trajectory only: the maximum
signed constraint margin over the five forecast states, where each forecast
coordinate is shifted toward the constraint by `k` times its predicted Laplace
scale. k=0 reproduces the v2 score exactly. Thresholds are fitted only on
calibration episodes with the unchanged v2 1-percent empirical-FPR rule.
These are simulator constraints, not real incident probabilities, and a warning
never grants or removes execution authority.
"""
from __future__ import annotations

import numpy as np

import evaluate_incident_dynamics_development as v2dev
import train_physical_world_model as physical

calibrate = v2dev.calibrate
warning_metrics = v2dev.warning_metrics


def risk_score(mean, scale, windows, domain, k=0.0):
    if mean.shape != windows.targets.shape or not np.isfinite(mean).all():
        raise ValueError("invalid forecast: evaluation fails closed, never returns a permit")
    if scale is None or k == 0:
        return v2dev.risk_score(mean, windows, domain)
    if not np.isfinite(scale).all() or (scale < 0).any():
        raise ValueError("invalid forecast scale")
    if domain == "ferrumos":
        upper = mean[:, :, [0, 1, 3]] + k * scale[:, :, [0, 1, 3]]
        return (upper.max((1, 2)) - .95).astype(np.float64)
    moving = windows.future_actions[:, :, physical.MOVE] > .5
    clearance_low = mean[:, :, physical.CLEARANCE] - k * scale[:, :, physical.CLEARANCE]
    clearance = np.where(moving, .16 - clearance_low, -1)
    position = np.abs(mean[:, :, :2]) + k * scale[:, :, :2]
    margins = np.stack((position.max(-1) - 1,
                        .08 - (mean[:, :, physical.BATTERY] - k * scale[:, :, physical.BATTERY]),
                        .08 - (mean[:, :, physical.LINK] - k * scale[:, :, physical.LINK]), clearance), -1)
    return margins.max((1, 2)).astype(np.float64)


def labels(windows, domain):
    return v2dev.risk_score(windows.targets, windows, domain) >= 0
