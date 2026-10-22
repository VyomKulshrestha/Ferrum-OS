"""Online alarm-threshold rules for world-model monitors (threshold-transfer study tt1).

Every rule consumes a score stream s_t (one score per step, higher = more anomalous) and returns
the per-step threshold tau_t used to decide alarm_t = s_t > tau_t. All rules start from the
registered calibrated threshold tau0 and the per-step exceedance target p measured on clean
calibration data (the rate at which tau0 is exceeded there). Rules never see labels, except the
explicitly named oracle-operator permit, which is an upper-bound arm and is reported as such.

Rules
  frozen        tau_t = tau0
  margin        tau_t = tau_half, a static threshold above tau0 supplied by the caller (tt1: tau0 + 0.25 x spread)
  daily         tau re-set once per day to the trailing-day (1 - p) quantile of scores
  tracker       symmetric online quantile tracking (ACI-style): tau moves up and down
  one_sided     tighten-only: tau_t = min(tau0_t, q_t) where q_t is the same tracker;
                tau0_t (the ceiling) only rises through a permit:
                  permit="none"     never rises
                  permit="spread"   rises to the trailing-day quantile if, over the trailing
                                    day, tau0 was exceeded at > 2x the target rate AND no single
                                    alarm episode holds more than half of the exceedances
                  permit="oracle"   rises like "spread" but only if the trailing day held no
                                    labelled event (simulated operator; upper bound)
                  permit="shift"    location-shift test on the body of the score distribution:
                                    at each review the ceiling is set to tau0 + max(0, median of
                                    the trailing window - calibration median). Lowering is a
                                    tightening and needs no permit. Short supra-threshold events
                                    cannot move a median unless they fill half the window.
                A digit suffix (e.g. "spread6", "shift6") reviews every that many hours instead of daily.
"""
from __future__ import annotations

import numpy as np


def _episodes(alarm: np.ndarray, gap: int):
    idx = np.flatnonzero(alarm)
    if not len(idx):
        return []
    breaks = np.flatnonzero(np.diff(idx) > gap + 1)
    starts = np.concatenate([[idx[0]], idx[breaks + 1]])
    ends = np.concatenate([idx[breaks], [idx[-1]]]) + 1
    return list(zip(starts, ends))


def tracker_path(scores: np.ndarray, tau0: float, p: float, eta: float) -> np.ndarray:
    """Symmetric online quantile tracker: q_{t+1} = q_t + eta * (1[s_t > q_t] - p)."""
    q = np.empty(len(scores))
    cur = tau0
    for t, s in enumerate(scores):
        q[t] = cur
        cur += eta * ((1.0 if s > cur else 0.0) - p)
    return q


def daily_path(scores: np.ndarray, tau0: float, p: float, steps_per_day: int) -> np.ndarray:
    tau = np.full(len(scores), tau0, dtype=float)
    for start in range(steps_per_day, len(scores), steps_per_day):
        window = scores[start - steps_per_day:start]
        tau[start:start + steps_per_day] = np.quantile(window[np.isfinite(window)], 1 - p)
    return tau


def one_sided_path(scores: np.ndarray, tau0: float, p: float, eta: float, steps_per_day: int, gap: int,
                   permit: str = "none", labels: np.ndarray | None = None, review_every: int | None = None,
                   ref_median: float | None = None):
    """Tighten-only threshold. Returns (tau, permits) where permits lists (step, old, new)."""
    review = review_every or steps_per_day
    q = tracker_path(scores, tau0, p, eta)
    ceiling = np.full(len(scores), tau0, dtype=float)
    permits = []
    cur = tau0
    for start in range(review, len(scores) + 1, review):
        ceiling[start - review:start] = cur
        if permit == "none" or start >= len(scores):
            continue
        window = scores[start - review:start]
        if permit == "shift":
            finite = window[np.isfinite(window)]
            if len(finite):
                new = tau0 + max(0.0, float(np.median(finite)) - ref_median)
                if new > cur:
                    permits.append((int(start), float(cur), new))
                cur = new
            continue
        exceed = window > cur
        rate = exceed.mean()
        if rate <= 2 * p or not exceed.any():
            continue
        eps = _episodes(exceed, gap)
        biggest = max(int(exceed[a:b].sum()) for a, b in eps)
        if biggest > 0.5 * exceed.sum():
            continue                                   # concentrated: looks like an event, keep caution
        if permit == "oracle" and labels is not None and labels[start - review:start].any():
            continue
        new = float(np.quantile(window[np.isfinite(window)], 1 - p))
        if new > cur:
            permits.append((int(start), float(cur), new))
            cur = new
    if len(scores) % review:
        ceiling[(len(scores) // review) * review:] = cur
    return np.minimum(ceiling, q), permits


def apply_rule(rule: str, scores: np.ndarray, tau0: float, tau_half: float, p: float, eta: float,
               steps_per_day: int, gap: int, labels: np.ndarray | None = None, ref_median: float | None = None):
    """Return (tau path, metadata) for a named rule. ref_median (calibration median) is needed by "shift"."""
    if rule == "frozen":
        return np.full(len(scores), tau0), {}
    if rule == "margin":
        return np.full(len(scores), tau_half), {}
    if rule == "daily":
        return daily_path(scores, tau0, p, steps_per_day), {}
    if rule == "tracker":
        return tracker_path(scores, tau0, p, eta), {}
    if rule == "tracker_slow":                         # one tenth of the step: the best budget in development
        return tracker_path(scores, tau0, p, eta / 10), {}
    if rule.startswith("one_sided"):
        permit = rule.split(":", 1)[1] if ":" in rule else "none"
        review = None
        if permit[-1].isdigit():                      # e.g. "spread6": review every 6 hours
            hours = int("".join(ch for ch in permit if ch.isdigit()))
            permit = permit.rstrip("0123456789")
            review = steps_per_day * hours // 24
        tau, permits = one_sided_path(scores, tau0, p, eta, steps_per_day, gap, permit=permit, labels=labels,
                                      review_every=review, ref_median=ref_median)
        return tau, {"permits": len(permits), "permit_log": permits[:50]}
    raise ValueError(rule)


RULES = ["frozen", "margin", "daily", "tracker", "tracker_slow", "one_sided:none", "one_sided:spread",
         "one_sided:spread6", "one_sided:shift", "one_sided:shift6", "one_sided:oracle"]
