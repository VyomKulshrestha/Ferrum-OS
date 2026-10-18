"""Gradient-boosted residual world model on top of the frozen v2-selected model (development only).

One-step delta = frozen v2-selected delta (ridge for FerrumOS, three-member ActionResidual mean
for Physical) + a LightGBM correction per corrected state dimension. Corrections use causal
features only: the full last observed state, recent history deltas, repeated-reading flags,
current/previous action identity, the current action vector, and the frozen base's own
predicted delta. Rollouts are autoregressive over the registered planned action sequence.
No simulator coefficient, hazard label, mechanism identity or future state is an input.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import torch

import incident_dynamics_v3_data as v3
import incident_dynamics_v3_models as models

HORIZON = v3.HORIZON


def corrected_dimensions(domain):
    return [0, 1, 2, 3] if domain == "ferrumos" else list(range(16))


def delta_dimensions(domain):
    return [0, 1, 2, 3] if domain == "ferrumos" else list(range(16))


class GBRModel:
    def __init__(self, domain, history, boosters=None, params=None):
        self.domain, self.history = domain, history
        self.spec = v3.spec_for(domain, history)
        self.count = models.action_count(self.spec)
        self.base = models.FrozenV2Base(self.spec).eval()
        self.boosters = boosters or []
        self.params = params or {}

    def base_delta(self, states, actions, batch=16384):
        with torch.no_grad():
            parts = [self.base(torch.as_tensor(states[i:i + batch]), torch.as_tensor(actions[i:i + batch])).numpy()
                     for i in range(0, len(states), batch)]
        return np.concatenate(parts) * self.spec.scale

    def features(self, states, actions, base_delta):
        scale = self.spec.scale
        s = states / scale
        deltas = s[:, 1:] - s[:, :-1]
        dims = delta_dimensions(self.domain)
        recent = deltas[:, -min(4, deltas.shape[1]):][:, :, dims]
        stale = (np.abs(deltas[:, -2:][:, :, dims]) < 1e-9).astype(np.float32)
        current = actions[:, -1, :self.count].argmax(1).astype(np.float32)
        previous = np.where(np.abs(actions[:, -2]).sum(1) > 0, actions[:, -2, :self.count].argmax(1), -1).astype(np.float32)
        return np.concatenate([s[:, -1], recent.reshape(len(s), -1), stale.reshape(len(s), -1),
                               current[:, None], previous[:, None], actions[:, -1], base_delta / scale], 1).astype(np.float32)

    def categorical(self):
        width = self.spec.state_size + min(4, self.history - 1) * len(delta_dimensions(self.domain)) + 2 * len(delta_dimensions(self.domain))
        return [width, width + 1]

    def step(self, states, actions):
        base = self.base_delta(states, actions)
        x = self.features(states, actions, base)
        delta = base.copy()
        for dim, booster in zip(corrected_dimensions(self.domain), self.boosters):
            delta[:, dim] += booster.predict(x, num_threads=8) * self.spec.scale[dim]
        return delta

    def predict(self, data):
        states, actions = data.states.copy(), data.actions.copy()
        out = []
        for k in range(HORIZON):
            nxt = states[:, -1] + self.step(states, actions)
            out.append(nxt)
            if k < HORIZON - 1:
                states = np.concatenate((states[:, 1:], nxt[:, None]), 1)
                actions = np.concatenate((actions[:, 1:], data.future_actions[:, k + 1, None]), 1)
        return np.stack(out, 1).astype(np.float32)

    def fit(self, train, weights, seed, n_estimators=600, learning_rate=0.05, num_leaves=63, objective="l1",
            bagging=0.8, log=print):
        base = self.base_delta(train.states, train.actions)
        x = self.features(train.states, train.actions, base)
        residual = (train.targets[:, 0] - train.states[:, -1]) - base
        self.params = {"n_estimators": n_estimators, "learning_rate": learning_rate, "num_leaves": num_leaves,
                       "objective": objective, "bagging_fraction": bagging, "seed": seed}
        self.boosters = []
        for dim in corrected_dimensions(self.domain):
            model = lgb.LGBMRegressor(n_estimators=n_estimators, learning_rate=learning_rate, num_leaves=num_leaves,
                                      min_child_samples=40, objective=objective, subsample=bagging, subsample_freq=1,
                                      colsample_bytree=0.9, random_state=seed + dim, deterministic=True,
                                      force_row_wise=True, n_jobs=8, verbose=-1)
            model.fit(x, residual[:, dim] / self.spec.scale[dim], sample_weight=weights,
                      categorical_feature=self.categorical())
            self.boosters.append(model.booster_)
            log(json.dumps({"fitted_dimension": dim}))
        return self

    def save(self, path: Path):
        payload = {"domain": self.domain, "history": self.history, "params": self.params,
                   "dimensions": corrected_dimensions(self.domain),
                   "boosters": [b.model_to_string() for b in self.boosters]}
        path.write_text(json.dumps(payload), encoding="utf-8")
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @classmethod
    def load(cls, path: Path):
        payload = json.loads(path.read_text(encoding="utf-8"))
        boosters = [lgb.Booster(model_str=text) for text in payload["boosters"]]
        return cls(payload["domain"], payload["history"], boosters, payload["params"])


class GBRDirect(GBRModel):
    """Direct multi-horizon correction of the frozen v2-selected rollout.

    For each horizon h and corrected dimension, a LightGBM model predicts the residual between the
    observed state at t+h and the frozen base rollout at h, from causal context features, the planned
    action identities for the whole window, and the base rollout's own displacement. Learning each
    horizon separately lets the model shrink drift extrapolation where development data show regime
    changes (a damped-trend effect) without anticipating any specific change.
    """

    kind = "direct"

    def base_rollout(self, data):
        states, actions = data.states.copy(), data.actions.copy()
        out = []
        for k in range(HORIZON):
            nxt = states[:, -1] + self.base_delta(states, actions)
            out.append(nxt)
            if k < HORIZON - 1:
                states = np.concatenate((states[:, 1:], nxt[:, None]), 1)
                actions = np.concatenate((actions[:, 1:], data.future_actions[:, k + 1, None]), 1)
        return np.stack(out, 1)

    def direct_features(self, data, base):
        context = self.features(data.states, data.actions, base[:, 0] - data.states[:, -1])
        plan = data.future_actions[:, :, :self.count].argmax(-1).astype(np.float32)
        dims = corrected_dimensions(self.domain)
        displacement = ((base - data.states[:, -1:, :]) / self.spec.scale)[:, :, dims].reshape(len(context), -1)
        return np.concatenate([context, plan, displacement], 1).astype(np.float32)

    def direct_categorical(self):
        width = self.spec.state_size + min(4, self.history - 1) * len(delta_dimensions(self.domain)) + 2 * len(delta_dimensions(self.domain))
        context_width = width + 2 + self.spec.action_size + self.spec.state_size
        return [width, width + 1, *range(context_width, context_width + HORIZON)]

    def predict(self, data):
        base = self.base_rollout(data)
        x = self.direct_features(data, base)
        out = base.copy()
        dims = corrected_dimensions(self.domain)
        for index, booster in enumerate(self.boosters):
            h, j = divmod(index, len(dims))
            out[:, h, dims[j]] += booster.predict(x, num_threads=8) * self.spec.scale[dims[j]]
        return out.astype(np.float32)

    def fit(self, train, weights, seed, n_estimators=600, learning_rate=0.05, num_leaves=63, objective="l1",
            bagging=0.8, log=print):
        base = self.base_rollout(train)
        x = self.direct_features(train, base)
        self.params = {"n_estimators": n_estimators, "learning_rate": learning_rate, "num_leaves": num_leaves,
                       "objective": objective, "bagging_fraction": bagging, "seed": seed, "kind": "direct"}
        self.boosters = []
        dims = corrected_dimensions(self.domain)
        for h in range(HORIZON):
            valid = train.valid[:, h] > 0
            for dim in dims:
                target = (train.targets[:, h, dim] - base[:, h, dim]) / self.spec.scale[dim]
                model = lgb.LGBMRegressor(n_estimators=n_estimators, learning_rate=learning_rate, num_leaves=num_leaves,
                                          min_child_samples=40, objective=objective, subsample=bagging, subsample_freq=1,
                                          colsample_bytree=0.9, random_state=seed + dim + 100 * h, deterministic=True,
                                          force_row_wise=True, n_jobs=8, verbose=-1)
                model.fit(x[valid], target[valid], sample_weight=weights[valid], categorical_feature=self.direct_categorical())
                self.boosters.append(model.booster_)
                log(json.dumps({"fitted": [h, dim]}))
        return self

    def save(self, path: Path):
        payload = {"domain": self.domain, "history": self.history, "params": self.params, "kind": "direct",
                   "dimensions": corrected_dimensions(self.domain),
                   "boosters": [b.model_to_string() for b in self.boosters]}
        path.write_text(json.dumps(payload), encoding="utf-8")
        return hashlib.sha256(path.read_bytes()).hexdigest()


def load_any(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    boosters = [lgb.Booster(model_str=text) for text in payload["boosters"]]
    cls = GBRDirect if payload.get("kind") == "direct" else GBRModel
    return cls(payload["domain"], payload["history"], boosters, payload["params"])


WARNING_DIMENSIONS = {"ferrumos": [0, 1, 3], "physical": [0, 1, 2, 4, 5]}


class ScaledGBR:
    """A trained GBR mean model plus learned per-horizon absolute-error models for warning dimensions.

    The mean forecast is unchanged. Scale boosters predict the expected absolute error of the mean
    forecast at each horizon on warning-relevant dimensions from the same causal features; they are
    fitted on training windows only and used solely for the uncertainty-shifted warning score.
    """

    def __init__(self, mean_model, scale_boosters=None, params=None):
        self.mean_model = mean_model
        self.domain, self.history, self.spec = mean_model.domain, mean_model.history, mean_model.spec
        self.scale_boosters = scale_boosters or []
        self.params = params or {}

    def _features(self, data, base_rollout):
        context = self.mean_model.features(data.states, data.actions, base_rollout[:, 0] - data.states[:, -1])
        plan = data.future_actions[:, :, :self.mean_model.count].argmax(-1).astype(np.float32)
        return np.concatenate([context, plan], 1)

    def fit_scale(self, train, weights, seed, n_estimators=300, num_leaves=31):
        mean = self.mean_model.predict(train)
        base = self.mean_model.base_rollout(train) if hasattr(self.mean_model, "base_rollout") else GBRDirect.base_rollout(self.mean_model, train)
        x = self._features(train, base)
        self.scale_boosters = []
        self.params = {"n_estimators": n_estimators, "num_leaves": num_leaves, "seed": seed, "objective": "l1 on |error|"}
        for h in range(HORIZON):
            valid = train.valid[:, h] > 0
            for dim in WARNING_DIMENSIONS[self.domain]:
                target = np.abs(train.targets[:, h, dim] - mean[:, h, dim]) / self.spec.scale[dim]
                model = lgb.LGBMRegressor(n_estimators=n_estimators, learning_rate=0.05, num_leaves=num_leaves,
                                          min_child_samples=80, objective="l1", subsample=0.8, subsample_freq=1,
                                          random_state=seed + 1000 + dim + 100 * h, deterministic=True,
                                          force_row_wise=True, n_jobs=8, verbose=-1)
                model.fit(x[valid], target[valid], sample_weight=weights[valid])
                self.scale_boosters.append(model.booster_)
        return self

    def predict(self, data):
        return self.mean_model.predict(data)

    def predict_with_scale(self, data):
        mean = self.mean_model.predict(data)
        base = GBRDirect.base_rollout(self.mean_model, data)
        x = self._features(data, base)
        scale = np.zeros_like(mean)
        dims = WARNING_DIMENSIONS[self.domain]
        for index, booster in enumerate(self.scale_boosters):
            h, j = divmod(index, len(dims))
            scale[:, h, dims[j]] = np.maximum(booster.predict(x, num_threads=8), 0) * self.spec.scale[dims[j]]
        return mean, scale.astype(np.float32)

    def save(self, path: Path):
        inner = json.loads(json.dumps({"boosters": [b.model_to_string() for b in self.mean_model.boosters]}))
        payload = {"domain": self.domain, "history": self.history, "kind": "scaled",
                   "mean_kind": "direct" if isinstance(self.mean_model, GBRDirect) else "autoregressive",
                   "mean_params": self.mean_model.params, "mean_boosters": inner["boosters"],
                   "scale_params": self.params, "scale_boosters": [b.model_to_string() for b in self.scale_boosters]}
        path.write_text(json.dumps(payload), encoding="utf-8")
        return hashlib.sha256(path.read_bytes()).hexdigest()


_plain_load_any = load_any


def load_any(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("kind") != "scaled":
        return _plain_load_any(path)
    cls = GBRDirect if payload["mean_kind"] == "direct" else GBRModel
    mean = cls(payload["domain"], payload["history"], [lgb.Booster(model_str=t) for t in payload["mean_boosters"]], payload["mean_params"])
    return ScaledGBR(mean, [lgb.Booster(model_str=t) for t in payload["scale_boosters"]], payload["scale_params"])


# ---------------------------------------------------------------- compact archive encoding
TRAINING_ONLY_FIELDS = ("leaf_weight=", "leaf_count=", "internal_value=", "internal_weight=", "internal_count=",
                        "split_gain=", "tree_sizes=")


def _prediction_only(model_text):
    """Drop training statistics and the byte-offset index; LightGBM then parses trees sequentially.
    Prediction uses only split features, thresholds, decision types, children and leaf values."""
    return "\n".join(line for line in model_text.split("\n") if not line.startswith(TRAINING_ONLY_FIELDS))


def export_compact(source: Path, destination: Path) -> str:
    import lzma
    payload = json.loads(source.read_text(encoding="utf-8"))
    for key in ("boosters", "mean_boosters", "scale_boosters"):
        if key in payload:
            payload[key] = [_prediction_only(text) for text in payload[key]]
    destination.write_bytes(lzma.compress(json.dumps(payload, sort_keys=True).encode("utf-8"), preset=9 | lzma.PRESET_EXTREME))
    return hashlib.sha256(destination.read_bytes()).hexdigest()


def load_path(path: Path):
    """Load a .gbr (JSON text) or compact .gbr.xz archive."""
    if path.suffix == ".xz":
        import lzma
        import tempfile
        text = lzma.decompress(path.read_bytes()).decode("utf-8")
        with tempfile.TemporaryDirectory() as folder:
            temporary = Path(folder) / "model.gbr"
            temporary.write_text(text, encoding="utf-8")
            return load_any(temporary)
    return load_any(path)
