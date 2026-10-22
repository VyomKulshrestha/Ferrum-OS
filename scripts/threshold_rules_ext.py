"""Streaming thresholds from the anomaly-detection literature, for the tt1 extension (tt1b).

SPOT and DSPOT (Siffer, Fouque, Termier and Largouet, KDD 2017, "Anomaly detection in streams with
extreme value theory"). SPOT fits a generalised Pareto tail to the peaks above an initial threshold t
(calibration quantile `level`) and alarms above z_q, the level exceeded with probability q. While
streaming, a value above z_q is an alarm and never enters the model; a value between t and z_q is
added as a peak and z_q is recomputed; any other value only increments the observation count.
DSPOT runs SPOT on the residual from the mean of the last `depth` non-alarm values, so a slow drift
in level moves the threshold with it. GPD parameters come from the method of moments (Hosking and
Wallis 1987) kept as running sums, so every refit is O(1); Siffer et al. use maximum likelihood.

threshold_rules.py (the registered tt1 library) is left unchanged; apply_rule here falls back to it.
"""
from __future__ import annotations

from collections import deque

import numpy as np

import threshold_rules as T

SPOT_LEVEL = 0.98


def _gpd(s1, s2, n):
    """Method-of-moments generalised Pareto shape and scale from the sums of y and y^2."""
    m = s1 / n
    v = s2 / n - m * m
    if v <= 1e-12:
        return 0.0, max(m, 1e-12)
    ratio = m * m / v
    return 0.5 * (1.0 - ratio), 0.5 * m * (ratio + 1.0)


def _zq(t, gamma, sigma, q, k, nt):
    r = q * k / nt
    if abs(gamma) < 1e-6:
        return t - sigma * np.log(r)
    try:
        return t + sigma / gamma * (r ** (-gamma) - 1.0)
    except OverflowError:                              # a runaway tail: the threshold has left the float range
        return float("inf")


def _init(values, q, level):
    t = float(np.quantile(values, level))
    peaks = values[values > t] - t
    s1, s2, nt, k = float(peaks.sum()), float((peaks ** 2).sum()), len(peaks), len(values)
    gamma, sigma = _gpd(s1, s2, nt)
    return t, s1, s2, nt, k, gamma, sigma


def spot_path(scores, calib, q, level=SPOT_LEVEL):
    calib = calib[np.isfinite(calib)]
    t, s1, s2, nt, k, gamma, sigma = _init(calib, q, level)
    z = _zq(t, gamma, sigma, q, k, nt)
    tau = np.empty(len(scores))
    for i, x in enumerate(scores):
        tau[i] = z
        if not np.isfinite(x) or x > z:               # warm-up, or an alarm: not learned
            continue
        k += 1
        if x > t:
            y = x - t
            s1, s2, nt = s1 + y, s2 + y * y, nt + 1
            gamma, sigma = _gpd(s1, s2, nt)
            z = _zq(t, gamma, sigma, q, k, nt)
    return tau


def dspot_path(scores, calib, q, depth, level=SPOT_LEVEL):
    calib = calib[np.isfinite(calib)]
    csum = np.concatenate([[0.0], np.cumsum(calib)])
    resid = calib[depth:] - (csum[depth:-1] - csum[:-depth - 1]) / depth
    t, s1, s2, nt, k, gamma, sigma = _init(resid, q, level)
    z = _zq(t, gamma, sigma, q, k, nt)
    window = deque(calib[-depth:].tolist())
    msum = float(sum(window))
    tau = np.empty(len(scores))
    for i, x in enumerate(scores):
        m = msum / depth
        tau[i] = m + z
        if not np.isfinite(x):
            continue
        r = x - m
        if r > z:                                      # alarm: neither the tail nor the mean learns it
            continue
        k += 1
        if r > t:
            y = r - t
            s1, s2, nt = s1 + y, s2 + y * y, nt + 1
            gamma, sigma = _gpd(s1, s2, nt)
            z = _zq(t, gamma, sigma, q, k, nt)
        msum += x - window.popleft()
        window.append(x)
    return tau


def _mle(peaks):
    """Maximum-likelihood GPD (scipy, location 0); method of moments below 10 peaks."""
    if len(peaks) < 10:
        return _gpd(float(np.sum(peaks)), float(np.sum(np.square(peaks))), len(peaks))
    from scipy.stats import genpareto
    gamma, _, sigma = genpareto.fit(np.asarray(peaks), floc=0)
    return float(gamma), float(sigma)


def spot_mle_path(scores, calib, q, refit=2048, level=SPOT_LEVEL):
    """SPOT as Siffer et al. specify it (maximum-likelihood tail), refit every `refit` new peaks; between
    refits z_q is recomputed from the last fit with the current counts."""
    calib = calib[np.isfinite(calib)]
    t = float(np.quantile(calib, level))
    peaks = list(calib[calib > t] - t)
    k = len(calib)
    gamma, sigma = _mle(peaks)
    fitted = len(peaks)
    z = _zq(t, gamma, sigma, q, k, len(peaks))
    tau = np.empty(len(scores))
    for i, x in enumerate(scores):
        tau[i] = z
        if not np.isfinite(x) or x > z:
            continue
        k += 1
        if x > t:
            peaks.append(x - t)
            if len(peaks) - fitted >= refit:
                gamma, sigma = _mle(peaks)
                fitted = len(peaks)
            z = _zq(t, gamma, sigma, q, k, len(peaks))
    return tau


def apply_rule(rule, scores, cfg, calib, steps_per_day, gap, depth, labels=None):
    """tt1 rules plus "spot", "spot_mle" and "dspot"; cfg carries tau0, tau_half, p, eta, m0 as in tt1_final.
    For sample sequences (steps_per_day = review window) spot_mle refits every 16 peaks instead of 2048."""
    if rule == "spot":
        return spot_path(scores, calib, cfg["p"]), {}
    if rule == "spot_mle":
        return spot_mle_path(scores, calib, cfg["p"], refit=2048 if steps_per_day > 1000 else 16), {}
    if rule == "dspot":
        return dspot_path(scores, calib, cfg["p"], depth), {}
    return T.apply_rule(rule, scores, cfg["tau0"], cfg["tau_half"], cfg["p"], cfg["eta"], steps_per_day, gap,
                        labels=labels, ref_median=cfg["m0"])


RULES = ["frozen", "margin", "daily", "tracker", "tracker_slow", "one_sided:none", "spot", "spot_mle", "dspot"]
