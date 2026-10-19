"""Real-telemetry study core: forecasters, incident-informed injections, detectors and metrics.

Dataset-agnostic. A segment is a contiguous recording with sensors X (T, d), optional commands
U (T, m) used as world-model actions, and per-step labels y (T,) (1 = attack or incident). Only
normal training segments are used for fitting; injected anomalies are synthetic and applied to
copies of normal data; recorded attacks are read only by the registered final evaluation.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import lightgbm as lgb
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.metrics import average_precision_score, roc_auc_score

warnings.filterwarnings("ignore", message="X does not have valid feature names")


@dataclass
class Segment:
    name: str
    X: np.ndarray                      # (T, d) sensors
    U: np.ndarray | None = None        # (T, m) commands / setpoints (actions)
    y: np.ndarray | None = None        # (T,) labels, None for normal training data
    meta: dict = field(default_factory=dict)


class Scaler:
    """Per-variable robust centre and scale from normal training data."""

    def fit(self, X):
        self.center = np.median(X, 0)
        q75, q25 = np.percentile(X, [75, 25], 0)
        spread = np.maximum(q75 - q25, X.std(0))
        self.scale = np.where(spread > 1e-6, spread, 1.0)
        return self

    def __call__(self, X):
        return ((X - self.center) / self.scale).astype(np.float32)


def features(Z, V, t, history):
    """Causal features at index t (the newest observed step): last state, history deltas, commands."""
    last = Z[t]
    deltas = [Z[t - k] - Z[t - k - 1] for k in range(history - 1)]
    parts = [last, *deltas]
    if V is not None:
        parts += [V[t], V[t] - V[t - 1]]
    return np.concatenate(parts, 1).astype(np.float32)


def valid_index(T, history, horizon, stride=1, start=0):
    return np.arange(max(start, history), T - horizon, stride)


class Forecaster:
    """Direct per-horizon world model: ridge on causal features plus optional LightGBM corrections.

    Predicts Z[t+h] - Z[t] for each registered horizon h from features at t. When commands are
    given, the commands planned for t+1..t+h are appended (the action sequence, as in the paper).
    """

    def __init__(self, horizons, history=3, alpha=1.0, use_actions=True, gbr=None, seed=0):
        self.horizons, self.history, self.alpha = list(horizons), history, alpha
        self.use_actions, self.gbr, self.seed = use_actions, gbr, seed

    def _design(self, Z, V, t, h):
        base = features(Z, V if self.use_actions else None, t, self.history)
        if self.use_actions and V is not None:
            future = V[t + h] - V[t]
            base = np.concatenate([base, future], 1)
        return base

    def fit(self, segments, max_rows=200_000):
        """Fit on at most max_rows indices drawn uniformly (without replacement) across segments."""
        rng = np.random.default_rng(self.seed)
        self.ridge, self.boost = {}, {}
        for h in self.horizons:
            pools = [valid_index(len(Z), self.history, h) for Z, _ in segments]
            total = sum(len(p) for p in pools)
            keep = max_rows / total if total > max_rows else 1.0
            rows, targets = [], []
            for (Z, V), pool in zip(segments, pools):
                t = np.sort(rng.choice(pool, max(1, int(round(len(pool) * keep))), replace=False)) if keep < 1 else pool
                rows.append(self._design(Z, V, t, h))
                targets.append(Z[t + h] - Z[t])
            A, B = np.concatenate(rows), np.concatenate(targets)
            self.ridge[h] = Ridge(alpha=self.alpha).fit(A, B)
            if self.gbr:
                residual = B - self.ridge[h].predict(A)
                self.boost[h] = [lgb.LGBMRegressor(random_state=self.seed, verbose=-1, n_jobs=4, **self.gbr)
                                 .fit(A, residual[:, j]) for j in range(B.shape[1])]
        return self

    def predict(self, Z, V, t, h, chunk=50_000):
        out = np.empty((len(t), Z.shape[1]), np.float32)
        for i in range(0, len(t), chunk):
            part = t[i:i + chunk]
            A = self._design(Z, V, part, h)
            delta = self.ridge[h].predict(A)
            if self.gbr:
                delta = delta + np.stack([m.predict(A) for m in self.boost[h]], 1)
            out[i:i + chunk] = Z[part] + delta
        return out


class Persistence:
    def __init__(self, horizons, history=3):
        self.horizons, self.history = list(horizons), history

    def fit(self, segments, **_):
        return self

    def predict(self, Z, V, t, h):
        return Z[t]


def forecast_error(model, segments, h, stride=1):
    """Mean absolute error (in scaled units) of h-step forecasts over all valid indices."""
    total, count = 0.0, 0
    for Z, V in segments:
        t = valid_index(len(Z), model.history, h, stride)
        err = np.abs(model.predict(Z, V, t, h) - Z[t + h])
        total += float(err.sum())
        count += err.size
    return total / max(count, 1)


# ---------------------------------------------------------------------------------------------
# Residual detector (normal-only world-model warning)
# ---------------------------------------------------------------------------------------------

def residuals(model, Z, V, h):
    """Standardisable residual at each index s = t + h: observed minus the forecast made at t."""
    T = len(Z)
    R = np.zeros_like(Z)
    t = valid_index(T, model.history, h)
    R[t + h] = Z[t + h] - model.predict(Z, V, t, h)
    return R


def rolling_mean(a, w):
    if w <= 1:
        return a
    c = np.cumsum(np.concatenate([np.zeros((1,) + a.shape[1:], a.dtype), a]), 0)
    out = (c[w:] - c[:-w]) / w
    return np.concatenate([np.repeat(out[:1], w - 1, 0), out])


def residual_score(R, sigma, top_k=3, window=1):
    S = np.abs(R) / sigma
    top = -np.sort(-S, 1)[:, :top_k].mean(1)
    return rolling_mean(top, window)


def detector_features(R, sigma, Z, window):
    """Per-step features for a learned detector: scaled residuals, their rolling means, deltas."""
    S = np.abs(R) / sigma
    roll = rolling_mean(S, window)
    delta = np.vstack([np.zeros((1, Z.shape[1]), Z.dtype), np.diff(Z, axis=0)])
    top = -np.sort(-S, 1)[:, :5]
    return np.concatenate([S, roll, np.abs(delta), top, S.mean(1, keepdims=True)], 1).astype(np.float32)


# ---------------------------------------------------------------------------------------------
# Injections (applied to copies of normal data; never to recorded attack data)
# ---------------------------------------------------------------------------------------------

def inject(Z, V, family, start, length, columns, rng, magnitude, command_columns=None):
    """Return copies (Z', V') with one anomaly of the given shape on the selected columns."""
    Z, V = Z.copy(), None if V is None else V.copy()
    end = min(len(Z), start + length)
    span = np.arange(end - start)
    sign = rng.choice([-1.0, 1.0], len(columns))
    if family == "step":                      # abrupt offset (modified parameter, config push)
        Z[start:end, columns] += sign * magnitude
    elif family == "ramp":                    # slow drift (leak, stealthy bias)
        Z[start:end, columns] += np.outer(span / max(len(span), 1), sign * magnitude)
    elif family == "freeze":                  # stuck reading (frozen view, dead agent)
        Z[start:end, columns] = Z[start - 1, columns]
    elif family == "replay":                  # replay of earlier normal values (manipulated view)
        lag = int(rng.integers(len(span) + 1, max(len(span) + 2, start)))
        Z[start:end, columns] = Z[start - lag:end - lag, columns]
    elif family == "oscillation":             # periodic forcing (actuator chattering, retry storm)
        period = max(4, int(rng.integers(4, 20)))
        Z[start:end, columns] += np.outer(np.sin(2 * np.pi * span / period), sign * magnitude)
    elif family == "saturation":              # pinned at a bound (exhaustion, valve fully open)
        bound = np.where(sign > 0, Z[:, columns].max(0), Z[:, columns].min(0))
        Z[start:end, columns] = bound + sign * 0.1 * magnitude
    elif family == "spikes":                  # sparse spike train (bursty failure, packet storms)
        hits = rng.random(len(span)) < 0.2
        idx = start + np.flatnonzero(hits)
        Z[np.ix_(idx, columns)] += sign * magnitude
    elif family == "noise":                   # generic control: unstructured Gaussian corruption
        Z[start:end, columns] += rng.normal(0, magnitude, (len(span), len(columns)))
    elif family == "command_mismatch":        # command changes, sensors keep the old regime
        if V is not None and command_columns:
            V[start:end, command_columns] += rng.choice([-1.0, 1.0], len(command_columns)) * magnitude
        else:
            Z[start:end, columns] = Z[start - 1, columns]
    elif family == "decoupled":               # sensors move while commands are unchanged
        Z[start:end, columns] += np.outer(np.minimum(1.0, span / max(1, len(span) // 4)), sign * magnitude)
    else:
        raise ValueError(family)
    return Z, V


# ---------------------------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------------------------

def events(y):
    """Contiguous runs of label 1 as (start, end) half-open intervals."""
    y = np.asarray(y).astype(np.int8)
    edges = np.diff(np.concatenate([[0], y, [0]]))
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))


def threshold_at(normal_scores, fpr):
    return float(np.quantile(normal_scores, 1.0 - fpr))


def event_report(score, y, threshold, tolerance=0):
    """Event recall (any alarm in [start, end + tolerance)), normal-step alarm rate, delays."""
    alarm = score > threshold
    found, delays = [], []
    for s, e in events(y):
        hit = np.flatnonzero(alarm[s:min(len(y), e + tolerance)])
        found.append(bool(len(hit)))
        delays.append(int(hit[0]) if len(hit) else None)
    normal = np.asarray(y) == 0
    return {"events": len(found), "detected": int(sum(found)), "recall": float(np.mean(found)) if found else float("nan"),
            "fpr": float(alarm[normal].mean()) if normal.any() else float("nan"),
            "found": found, "delays": delays}


def point_metrics(score, y):
    y = np.asarray(y)
    if y.min() == y.max():
        return {"auc_pr": float("nan"), "auc_roc": float("nan")}
    return {"auc_pr": float(average_precision_score(y, score)), "auc_roc": float(roc_auc_score(y, score))}


def paired_event_bootstrap(found_a, found_b, reps=10_000, level=0.95, seed=0):
    """Bootstrap over events for recall(b) - recall(a) and relative miss reduction of b versus a."""
    a, b = np.asarray(found_a, float), np.asarray(found_b, float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(a), (reps, len(a)))
    diff = b[idx].mean(1) - a[idx].mean(1)
    miss_a = 1 - a[idx].mean(1)
    with np.errstate(divide="ignore", invalid="ignore"):
        reduction = np.where(miss_a > 0, 1 - (1 - b[idx].mean(1)) / miss_a, 0.0)
    q = [(1 - level) / 2, 1 - (1 - level) / 2]
    point_red = 1 - (1 - b.mean()) / (1 - a.mean()) if a.mean() < 1 else 0.0
    return {"recall_difference": float(b.mean() - a.mean()), "recall_difference_interval": [float(x) for x in np.quantile(diff, q)],
            "miss_reduction": float(point_red), "miss_reduction_interval": [float(x) for x in np.quantile(reduction, q)]}
