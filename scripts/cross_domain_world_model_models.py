#!/usr/bin/env python3
"""Shared models and metrics for the registered cross-domain study.

This module is research-only. It never writes a runtime artifact and exposes no
permit or execution path. All three model families consume the same temporal
examples and predict a normalized next-state delta plus aleatoric variance.
"""

from __future__ import annotations

from dataclasses import dataclass
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np
import torch
from torch import nn


METHODS = ("direct_mlp", "action_conditioned_jepa", "gru_dynamics")


@dataclass(frozen=True)
class DomainSpec:
    name: str
    state_size: int
    action_size: int
    history: int
    scale: np.ndarray
    latent_size: int


@dataclass
class SequenceData:
    states: np.ndarray
    actions: np.ndarray
    next_states: np.ndarray
    episodes: np.ndarray
    sources: list[str]
    dangerous: np.ndarray


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def standardize_action(
    action: int, features: Iterable[float], action_size: int, action_count: int
) -> np.ndarray:
    values = np.zeros(action_size, dtype=np.float32)
    if not 0 <= action < action_count:
        raise ValueError(f"action {action} is outside 0..{action_count - 1}")
    values[action] = 1.0
    feature_values = np.asarray(list(features), dtype=np.float32)
    if action_count + len(feature_values) != action_size:
        raise ValueError("action feature width does not match domain specification")
    values[action_count:] = feature_values
    return values


def sequence_data(rows: list[dict], spec: DomainSpec) -> SequenceData:
    """Build causal history windows without crossing episode boundaries."""
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(str(row["episode"]), []).append(row)
    state_windows: list[np.ndarray] = []
    action_windows: list[np.ndarray] = []
    next_states: list[np.ndarray] = []
    episodes: list[str] = []
    sources: list[str] = []
    dangerous: list[bool] = []
    for episode, episode_rows in grouped.items():
        episode_rows.sort(key=lambda item: int(item["step"]))
        for index, row in enumerate(episode_rows):
            start = max(0, index - spec.history + 1)
            window = episode_rows[start : index + 1]
            padding = spec.history - len(window)
            states = [np.asarray(window[0]["state"], dtype=np.float32)] * padding
            actions = [np.zeros(spec.action_size, dtype=np.float32)] * padding
            states.extend(
                np.asarray(item["state"], dtype=np.float32) for item in window
            )
            actions.extend(
                np.asarray(item["action"], dtype=np.float32) for item in window
            )
            state_windows.append(np.stack(states))
            action_windows.append(np.stack(actions))
            next_states.append(np.asarray(row["next_state"], dtype=np.float32))
            episodes.append(episode)
            sources.append(str(row.get("source", "unknown")))
            dangerous.append(bool(row.get("dangerous", False)))
    return SequenceData(
        states=np.stack(state_windows).astype(np.float32),
        actions=np.stack(action_windows).astype(np.float32),
        next_states=np.stack(next_states).astype(np.float32),
        episodes=np.asarray(episodes),
        sources=sources,
        dangerous=np.asarray(dangerous, dtype=bool),
    )


class DirectMLP(nn.Module):
    def __init__(self, spec: DomainSpec, hidden: int):
        super().__init__()
        width = spec.history * (spec.state_size + spec.action_size)
        self.network = nn.Sequential(
            nn.Linear(width, hidden),
            nn.GELU(),
            nn.Linear(hidden, 2 * spec.state_size),
        )
        self.state_size = spec.state_size

    def forward(self, states, actions, next_state=None):
        values = self.network(torch.cat((states, actions), dim=-1).flatten(1))
        mean, log_variance = values.split(self.state_size, dim=-1)
        return mean, log_variance.clamp(-8.0, 4.0), mean.new_zeros(())


class TemporalJEPA(nn.Module):
    def __init__(self, spec: DomainSpec, hidden: int):
        super().__init__()
        latent = spec.latent_size
        self.encoder = nn.Linear(spec.state_size, latent)
        self.target_encoder = copy.deepcopy(self.encoder)
        for parameter in self.target_encoder.parameters():
            parameter.requires_grad_(False)
        predictor_input = spec.history * (latent + spec.action_size)
        self.predictor = nn.Sequential(
            nn.Linear(predictor_input, hidden),
            nn.GELU(),
            nn.Linear(hidden, latent),
        )
        self.mean_head = nn.Linear(latent, spec.state_size)
        self.variance_head = nn.Linear(latent, spec.state_size)

    def forward(self, states, actions, next_state=None):
        latent_history = torch.tanh(self.encoder(states))
        context = torch.cat((latent_history, actions), dim=-1).flatten(1)
        predicted_latent = self.predictor(context)
        auxiliary = predicted_latent.new_zeros(())
        if next_state is not None:
            with torch.no_grad():
                target = torch.tanh(self.target_encoder(next_state))
            auxiliary = torch.mean((predicted_latent - target) ** 2)
        return (
            self.mean_head(predicted_latent),
            self.variance_head(predicted_latent).clamp(-8.0, 4.0),
            auxiliary,
        )

    @torch.no_grad()
    def update_target(self, coefficient: float = 0.99) -> None:
        for target, online in zip(
            self.target_encoder.parameters(), self.encoder.parameters()
        ):
            target.mul_(coefficient).add_(online, alpha=1.0 - coefficient)


class GRUDynamics(nn.Module):
    def __init__(self, spec: DomainSpec, hidden: int):
        super().__init__()
        self.gru = nn.GRU(spec.state_size + spec.action_size, hidden, batch_first=True)
        self.output = nn.Linear(hidden, 2 * spec.state_size)
        self.state_size = spec.state_size

    def forward(self, states, actions, next_state=None):
        sequence = torch.cat((states, actions), dim=-1)
        encoded, _ = self.gru(sequence)
        values = self.output(encoded[:, -1])
        mean, log_variance = values.split(self.state_size, dim=-1)
        return mean, log_variance.clamp(-8.0, 4.0), mean.new_zeros(())


def make_model(method: str, spec: DomainSpec, hidden: int) -> nn.Module:
    if method == "direct_mlp":
        return DirectMLP(spec, hidden)
    if method == "action_conditioned_jepa":
        return TemporalJEPA(spec, hidden)
    if method == "gru_dynamics":
        return GRUDynamics(spec, hidden)
    raise ValueError(f"unknown method: {method}")


def trainable_parameters(model: nn.Module) -> int:
    return sum(
        parameter.numel() for parameter in model.parameters() if parameter.requires_grad
    )


def budgeted_model(
    method: str, spec: DomainSpec, budget: int, tolerance: float
) -> tuple[nn.Module, int, int]:
    best = None
    for hidden in range(4, 4097):
        model = make_model(method, spec, hidden)
        count = trainable_parameters(model)
        if count > budget:
            break
        best = (model, hidden, count)
    if best is None or best[2] < math.floor(budget * (1.0 - tolerance)):
        raise ValueError(f"{method} cannot satisfy the registered parameter budget")
    return best


def tensors(data: SequenceData, spec: DomainSpec):
    states = torch.from_numpy(data.states)
    actions = torch.from_numpy(data.actions)
    next_states = torch.from_numpy(data.next_states)
    scale = torch.from_numpy(spec.scale.astype(np.float32))
    targets = (next_states - states[:, -1]) / scale
    return states, actions, next_states, targets


@torch.no_grad()
def validation_metrics(
    model: nn.Module, data: SequenceData, spec: DomainSpec, batch_size: int = 4096
) -> dict:
    states, actions, next_states, targets = tensors(data, spec)
    nll_sum = 0.0
    absolute_sum = 0.0
    count = 0
    finite = True
    for offset in range(0, len(states), batch_size):
        stop = offset + batch_size
        mean, log_variance, auxiliary = model(
            states[offset:stop], actions[offset:stop], next_states[offset:stop]
        )
        target = targets[offset:stop]
        nll = 0.5 * (torch.exp(-log_variance) * (mean - target) ** 2 + log_variance)
        nll_sum += float(nll.sum())
        absolute_sum += float(torch.abs(mean - target).sum())
        count += target.numel()
        finite = finite and bool(
            torch.isfinite(mean).all() and torch.isfinite(log_variance).all()
        )
    return {
        "gaussian_nll": nll_sum / count,
        "normalized_delta_mae": absolute_sum / count,
        "all_predictions_finite": finite,
    }


def fit_model(
    method: str,
    spec: DomainSpec,
    train: SequenceData,
    validation: SequenceData,
    seed: int,
    settings: dict,
) -> tuple[nn.Module, dict]:
    torch.manual_seed(seed)
    np.random.seed(seed)
    torch.use_deterministic_algorithms(bool(settings["deterministic_torch_algorithms"]))
    model, hidden, parameter_count = budgeted_model(
        method,
        spec,
        int(settings["trainable_parameter_budget"]),
        float(settings["parameter_budget_tolerance_fraction"]),
    )
    optimizer = torch.optim.AdamW(
        [parameter for parameter in model.parameters() if parameter.requires_grad],
        lr=float(settings["learning_rate"]),
        weight_decay=float(settings["weight_decay"]),
    )
    train_states, train_actions, train_next, train_targets = tensors(train, spec)
    generator = torch.Generator(device="cpu").manual_seed(seed)
    updates = int(settings["optimizer_updates"])
    batch_size = int(settings["batch_size"])
    check_every = int(settings["checkpoint_interval_updates"])
    best_state = None
    best_metrics = None
    trace = []
    for update in range(1, updates + 1):
        indices = torch.randint(len(train_states), (batch_size,), generator=generator)
        mean, log_variance, auxiliary = model(
            train_states[indices], train_actions[indices], train_next[indices]
        )
        target = train_targets[indices]
        nll = 0.5 * (torch.exp(-log_variance) * (mean - target) ** 2 + log_variance)
        loss = nll.mean() + (
            0.25 * auxiliary if method == "action_conditioned_jepa" else 0.0
        )
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        nn.utils.clip_grad_norm_(
            model.parameters(), float(settings["gradient_norm_clip"])
        )
        optimizer.step()
        if isinstance(model, TemporalJEPA):
            model.update_target()
        if update % check_every == 0 or update == updates:
            current = validation_metrics(model, validation, spec)
            current["update"] = update
            trace.append(current)
            if (
                best_metrics is None
                or current["gaussian_nll"] < best_metrics["gaussian_nll"]
            ):
                best_metrics = current
                best_state = copy.deepcopy(model.state_dict())
    if best_state is None or best_metrics is None:
        raise AssertionError("fixed-budget training produced no validation checkpoint")
    model.load_state_dict(best_state)
    return model, {
        "method": method,
        "seed": seed,
        "hidden_size": hidden,
        "latent_size": (
            spec.latent_size if method == "action_conditioned_jepa" else None
        ),
        "trainable_parameters": parameter_count,
        "optimizer_updates_completed": updates,
        "selected_checkpoint_update": best_metrics["update"],
        "validation": best_metrics,
        "validation_trace": trace,
    }


@torch.no_grad()
def predict(
    model: nn.Module,
    states: np.ndarray,
    actions: np.ndarray,
    spec: DomainSpec,
    batch_size: int = 4096,
) -> tuple[np.ndarray, np.ndarray]:
    state_tensor = torch.from_numpy(states.astype(np.float32))
    action_tensor = torch.from_numpy(actions.astype(np.float32))
    means = []
    variances = []
    for offset in range(0, len(state_tensor), batch_size):
        mean, log_variance, _ = model(
            state_tensor[offset : offset + batch_size],
            action_tensor[offset : offset + batch_size],
        )
        means.append(mean.numpy())
        variances.append(torch.exp(log_variance).numpy())
    return np.concatenate(means), np.concatenate(variances)


def one_step_predictions(
    model: nn.Module, data: SequenceData, spec: DomainSpec
) -> tuple[np.ndarray, np.ndarray]:
    mean, variance = predict(model, data.states, data.actions, spec)
    predicted = data.states[:, -1] + mean * spec.scale
    return predicted.astype(np.float32), variance.astype(np.float32)


def rollout_arrays(rows: list[dict], spec: DomainSpec, horizon: int):
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(str(row["episode"]), []).append(row)
    states = []
    actions = []
    future_actions = []
    actual = []
    episodes = []
    sources = []
    for episode, episode_rows in grouped.items():
        episode_rows.sort(key=lambda item: int(item["step"]))
        for start in range(0, len(episode_rows) - horizon + 1):
            current = episode_rows[start]
            prior_start = max(0, start - spec.history + 1)
            history_rows = episode_rows[prior_start : start + 1]
            padding = spec.history - len(history_rows)
            state_history = [
                np.asarray(history_rows[0]["state"], dtype=np.float32)
            ] * padding
            action_history = [np.zeros(spec.action_size, dtype=np.float32)] * padding
            state_history.extend(
                np.asarray(item["state"], dtype=np.float32) for item in history_rows
            )
            action_history.extend(
                np.asarray(item["action"], dtype=np.float32) for item in history_rows
            )
            states.append(np.stack(state_history))
            actions.append(np.stack(action_history))
            future_actions.append(
                np.stack(
                    [
                        np.asarray(item["action"], dtype=np.float32)
                        for item in episode_rows[start : start + horizon]
                    ]
                )
            )
            actual.append(
                np.asarray(
                    episode_rows[start + horizon - 1]["next_state"], dtype=np.float32
                )
            )
            episodes.append(episode)
            sources.append(str(current.get("source", "unknown")))
    return (
        np.stack(states).astype(np.float32),
        np.stack(actions).astype(np.float32),
        np.stack(future_actions).astype(np.float32),
        np.stack(actual).astype(np.float32),
        np.asarray(episodes),
        sources,
    )


def rollout_predictions(
    model: nn.Module, rows: list[dict], spec: DomainSpec, horizon: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    states, actions, future_actions, actual, episodes, sources = rollout_arrays(
        rows, spec, horizon
    )
    predicted_state = states[:, -1].copy()
    for offset in range(horizon):
        mean, _ = predict(model, states, actions, spec)
        predicted_state = predicted_state + mean * spec.scale
        if offset + 1 < horizon:
            states = np.concatenate(
                (states[:, 1:], predicted_state[:, None, :]), axis=1
            )
            actions = np.concatenate(
                (actions[:, 1:], future_actions[:, offset + 1, None, :]), axis=1
            )
    return predicted_state, actual, episodes, sources


def normalized_errors(
    predicted: np.ndarray, actual: np.ndarray, spec: DomainSpec
) -> np.ndarray:
    return np.mean(np.abs(predicted - actual) / spec.scale, axis=1)


def episode_bootstrap(
    errors: np.ndarray, episodes: np.ndarray, seed: int, resamples: int = 2000
) -> dict:
    unique = np.unique(episodes)
    per_episode = np.asarray([errors[episodes == episode].mean() for episode in unique])
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(per_episode), size=(resamples, len(per_episode)))
    values = per_episode[draws].mean(axis=1)
    return {
        "estimate": float(per_episode.mean()),
        "bootstrap_95_percent": [
            float(np.percentile(values, 2.5)),
            float(np.percentile(values, 97.5)),
        ],
        "episodes": len(unique),
        "resamples": resamples,
    }


def paired_bootstrap(
    left: np.ndarray,
    right: np.ndarray,
    episodes: np.ndarray,
    seed: int,
    resamples: int = 2000,
) -> dict:
    unique = np.unique(episodes)
    differences = np.asarray(
        [
            (left[episodes == episode] - right[episodes == episode]).mean()
            for episode in unique
        ]
    )
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(differences), size=(resamples, len(differences)))
    values = differences[draws].mean(axis=1)
    interval = [float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))]
    return {
        "estimate": float(differences.mean()),
        "bootstrap_95_percent": interval,
        "interval_excludes_zero": bool(interval[1] < 0.0 or interval[0] > 0.0),
        "episodes": len(unique),
        "resamples": resamples,
    }


def ood_statistics(data: SequenceData) -> dict:
    values = np.concatenate((data.states, data.actions), axis=-1).reshape(
        len(data.states), -1
    )
    return {
        "mean": values.mean(axis=0).astype(np.float32),
        "std": np.maximum(values.std(axis=0), 1e-4).astype(np.float32),
    }


def ood_scores(data: SequenceData, statistics: dict) -> np.ndarray:
    values = np.concatenate((data.states, data.actions), axis=-1).reshape(
        len(data.states), -1
    )
    standardized = (values - statistics["mean"]) / statistics["std"]
    return np.sqrt(np.mean(standardized**2, axis=1))


def risk_coverage(errors: np.ndarray, uncertainty: np.ndarray) -> list[dict]:
    order = np.argsort(uncertainty, kind="stable")
    result = []
    for coverage in (1.0, 0.9, 0.75, 0.5, 0.25):
        count = max(1, int(math.floor(len(order) * coverage)))
        kept = order[:count]
        result.append(
            {
                "coverage": coverage,
                "retained": count,
                "normalized_error": float(errors[kept].mean()),
                "maximum_uncertainty": float(uncertainty[kept].max()),
            }
        )
    return result


def model_record_path(root: Path, domain: str, method: str, seed: int) -> Path:
    return root / domain / f"{method}-seed-{seed}.pt"


def save_model(path: Path, model: nn.Module, metadata: dict) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": model.state_dict(), "metadata": metadata}, path)
    return {
        "path": str(path).replace("\\", "/"),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
    }


def load_model(
    path: Path, method: str, spec: DomainSpec, hidden: int, expected_sha256: str
) -> nn.Module:
    if sha256(path) != expected_sha256:
        raise AssertionError(f"research checkpoint drifted: {path}")
    payload = torch.load(path, map_location="cpu", weights_only=True)
    model = make_model(method, spec, hidden)
    model.load_state_dict(payload["state_dict"])
    model.eval()
    return model
