"""Incident-dynamics v3 candidate models (development only; no runtime authority).

Families:
  * sysid_ridge   - per-action ridge on a longer causal history plus in-context
                    system-identification features (masked mean/last deltas, stale flags).
  * direct_plan   - history encoder plus the registered planned action sequence that
                    predicts all five future deltas jointly (no autoregressive feedback)
                    with a Laplace scale per output for uncertainty-aware warnings.
  * ar_residual   - autoregressive action-residual network over the longer history.
No hand-coded transition coefficients, hazard labels, or future states enter inputs.
"""
from __future__ import annotations

import copy
import json
import time

import numpy as np
import torch
from torch import nn

import incident_dynamics_v3_data as v3

HORIZON = v3.HORIZON


def action_count(spec):
    return 41 if spec.name == "ferrumos" else 7


# ------------------------------------------------------------------ shared features
def context_features(states, actions, mask, spec):
    """Causal per-window features: last state, history deltas, masked delta stats, stale flags."""
    s = states / spec.scale
    deltas = s[:, 1:] - s[:, :-1]
    pair = mask[:, 1:] * mask[:, :-1]
    count = np.maximum(pair.sum(1, keepdims=True), 1)
    mean_delta = (deltas * pair[..., None]).sum(1) / count
    last_delta = deltas[:, -1]
    # Exactly repeated readings flag frozen/stale telemetry without privileged knowledge.
    stale = ((np.abs(deltas) < 1e-9) & (pair[..., None] > 0)).astype(np.float32)
    # Recent-weighted slope emphasises regime changes.
    weights = pair * np.linspace(0.2, 1.0, pair.shape[1])[None]
    recent = (deltas * weights[..., None]).sum(1) / np.maximum(weights.sum(1, keepdims=True), 1e-6)
    return np.concatenate([s[:, -1], deltas.reshape(len(s), -1), mean_delta, last_delta, recent,
                           stale[:, -2:].reshape(len(s), -1), pair.sum(1, keepdims=True) / pair.shape[1],
                           actions.reshape(len(s), -1)], axis=1).astype(np.float32)


# ------------------------------------------------------------------ sysid ridge
def ridge_fit(train, spec, regularization):
    mask = v3.history_mask(train)
    x = np.concatenate([np.ones((len(train.states), 1), np.float32), context_features(train.states, train.actions, mask, spec)], 1).astype(np.float64)
    y = ((train.targets[:, 0] - train.states[:, -1]) / spec.scale).astype(np.float64)
    ids = train.actions[:, -1, :action_count(spec)].argmax(1)
    weights = []
    penalty = np.eye(x.shape[1]) * regularization
    penalty[0, 0] = 1e-8
    for action in range(action_count(spec)):
        selected = ids == action
        if selected.sum() == 0:
            weights.append(np.zeros((x.shape[1], y.shape[1])))
            continue
        a, b = x[selected], y[selected]
        weights.append(np.linalg.solve(a.T @ a + penalty, a.T @ b))
    return np.stack(weights)


def ridge_predict(weights, data, spec):
    states, actions = data.states.copy(), data.actions.copy()
    mask = v3.history_mask(data)
    count = weights.shape[0]
    result = []
    for step in range(HORIZON):
        x = np.concatenate([np.ones((len(states), 1), np.float32), context_features(states, actions, mask, spec)], 1)
        ids = actions[:, -1, :count].argmax(1)
        delta = np.zeros((len(states), spec.state_size), np.float32)
        for action in range(count):
            selected = ids == action
            if selected.any():
                delta[selected] = x[selected] @ weights[action]
        nxt = states[:, -1] + delta * spec.scale
        result.append(nxt)
        if step < HORIZON - 1:
            states = np.concatenate((states[:, 1:], nxt[:, None]), 1)
            actions = np.concatenate((actions[:, 1:], data.future_actions[:, step + 1, None]), 1)
            mask = np.concatenate((mask[:, 1:], np.ones((len(mask), 1), np.float32)), 1)
    return np.stack(result, 1)


# ------------------------------------------------------------------ neural families
class DirectPlan(nn.Module):
    """Encode masked history; decode five future deltas jointly from planned actions."""

    def __init__(self, spec, hidden=256, layers=3, recurrent=True):
        super().__init__()
        self.spec = spec
        self.register_buffer("scale", torch.tensor(spec.scale))
        step_width = spec.state_size * 2 + spec.action_size + 1
        self.recurrent = recurrent
        if recurrent:
            self.encoder = nn.GRU(step_width, hidden, batch_first=True)
        else:
            self.encoder = nn.Sequential(nn.Linear(step_width * spec.history, hidden), nn.SiLU())
        blocks = [nn.Linear(hidden + spec.state_size + HORIZON * spec.action_size, hidden), nn.SiLU()]
        for _ in range(layers - 1):
            blocks += [nn.Linear(hidden, hidden), nn.SiLU()]
        self.body = nn.Sequential(*blocks)
        self.mean = nn.Linear(hidden, HORIZON * spec.state_size)
        self.log_scale = nn.Linear(hidden, HORIZON * spec.state_size)
        nn.init.zeros_(self.mean.weight)
        nn.init.zeros_(self.mean.bias)
        nn.init.zeros_(self.log_scale.weight)
        nn.init.constant_(self.log_scale.bias, -5.0)

    def forward(self, states, actions, mask, future):
        s = states / self.scale
        deltas = torch.cat((torch.zeros_like(s[:, :1]), s[:, 1:] - s[:, :-1]), 1)
        steps = torch.cat((s, deltas, actions, mask[..., None]), -1) * mask[..., None]
        if self.recurrent:
            _, hidden = self.encoder(steps)
            code = hidden[-1]
        else:
            code = self.encoder(steps.flatten(1))
        z = self.body(torch.cat((code, s[:, -1], future.flatten(1)), 1))
        n = (len(states), HORIZON, self.spec.state_size)
        # Cumulative deltas keep the five outputs on a trajectory scale.
        mean = self.mean(z).view(n)
        return mean, self.log_scale(z).view(n).clamp(-12, 3)


class ARResidual(nn.Module):
    """Autoregressive action-specific residual network over the longer history."""

    def __init__(self, spec, hidden=256):
        super().__init__()
        self.spec = spec
        self.register_buffer("scale", torch.tensor(spec.scale))
        self.count = action_count(spec)
        width = spec.history * (2 * spec.state_size + spec.action_size + 1)
        self.encoder = nn.Sequential(nn.Linear(width, hidden), nn.SiLU(), nn.Linear(hidden, hidden), nn.SiLU())
        self.heads = nn.Linear(hidden, self.count * spec.state_size)
        nn.init.zeros_(self.heads.weight)
        nn.init.zeros_(self.heads.bias)

    def step(self, states, actions, mask):
        s = states / self.scale
        deltas = torch.cat((torch.zeros_like(s[:, :1]), s[:, 1:] - s[:, :-1]), 1)
        x = (torch.cat((s, deltas, actions, mask[..., None]), -1) * mask[..., None]).flatten(1)
        experts = self.heads(self.encoder(x)).view(-1, self.count, self.spec.state_size)
        return (experts * actions[:, -1, :self.count, None]).sum(1)

    def forward(self, states, actions, mask, future):
        outputs = []
        last = states[:, -1]
        for k in range(HORIZON):
            delta = self.step(states, actions, mask)
            nxt = states[:, -1] + delta * self.scale
            outputs.append((nxt - last) / self.scale)
            if k < HORIZON - 1:
                states = torch.cat((states[:, 1:], nxt[:, None]), 1)
                actions = torch.cat((actions[:, 1:], future[:, k + 1, None]), 1)
                mask = torch.cat((mask[:, 1:], torch.ones_like(mask[:, :1])), 1)
        mean = torch.stack(outputs, 1)
        return mean, mean.new_full(mean.shape, -6.0)


def plain_features(states, actions, scale):
    """v2 ridge features (bias, last state, history deltas, history actions) on any history length."""
    s = states / scale
    causal = torch.cat((s[:, -1:], s[:, 1:] - s[:, :-1]), 1).flatten(1)
    return torch.cat((torch.ones_like(causal[:, :1]), causal, actions.flatten(1)), 1)


def plain_ridge_fit(train, spec, regularization=1e-3):
    states = torch.as_tensor(train.states, dtype=torch.float64)
    actions = torch.as_tensor(train.actions, dtype=torch.float64)
    x = plain_features(states, actions, torch.as_tensor(spec.scale, dtype=torch.float64)).numpy()
    y = ((train.targets[:, 0] - train.states[:, -1]) / spec.scale).astype(np.float64)
    ids = train.actions[:, -1, :action_count(spec)].argmax(1)
    weights = []
    penalty = np.eye(x.shape[1]) * regularization
    penalty[0, 0] = 1e-8
    for action in range(action_count(spec)):
        selected = ids == action
        if not selected.any():
            weights.append(np.zeros((x.shape[1], y.shape[1])))
            continue
        a, b = x[selected], y[selected]
        weights.append(np.linalg.solve(a.T @ a + penalty, a.T @ b))
    return np.stack(weights).astype(np.float32)


class HybridResidual(ARResidual):
    """Frozen closed-form per-action ridge step plus a learned nonlinear correction."""

    def __init__(self, spec, hidden=256, ridge_weights=None):
        super().__init__(spec, hidden)
        if ridge_weights is None:
            ridge_weights = np.zeros((self.count, 1 + spec.history * spec.state_size + spec.history * spec.action_size,
                                      spec.state_size), np.float32)
        self.register_buffer("ridge", torch.as_tensor(ridge_weights))

    def step(self, states, actions, mask):
        x = plain_features(states, actions, self.scale)
        ids = actions[:, -1, :self.count].argmax(1)
        base = torch.einsum("bf,bfs->bs", x, self.ridge[ids])
        return base + super().step(states, actions, mask)


def step_tokens(states, actions, mask, scale):
    s = states / scale
    deltas = torch.cat((torch.zeros_like(s[:, :1]), s[:, 1:] - s[:, :-1]), 1)
    return torch.cat((s, deltas, actions, mask[..., None]), -1) * mask[..., None]


class UncertainAR(nn.Module):
    """Autoregressive per-action step model with a learned one-step Laplace scale.

    encoder: "mlp" (flattened history) or "attention" (tiny transformer over history
    tokens). Optional frozen ridge base. Horizon scales accumulate in quadrature.
    """

    def __init__(self, spec, hidden=256, encoder="mlp", ridge_weights=None, use_ridge=False):
        super().__init__()
        self.spec = spec
        self.register_buffer("scale", torch.tensor(spec.scale))
        self.count = action_count(spec)
        width = 2 * spec.state_size + spec.action_size + 1
        self.kind = encoder
        if encoder == "attention":
            d = 128
            self.embed = nn.Linear(width, d)
            self.position = nn.Parameter(torch.zeros(spec.history, d))
            layer = nn.TransformerEncoderLayer(d, 4, 2 * d, dropout=0.0, batch_first=True, norm_first=True)
            self.encoder = nn.TransformerEncoder(layer, 2)
            self.project = nn.Sequential(nn.Linear(2 * d, hidden), nn.SiLU())
        else:
            self.encoder = nn.Sequential(nn.Linear(spec.history * width, hidden), nn.SiLU(), nn.Linear(hidden, hidden), nn.SiLU())
        self.heads = nn.Linear(hidden, self.count * spec.state_size)
        self.scale_heads = nn.Linear(hidden, self.count * spec.state_size)
        for layer in (self.heads, self.scale_heads):
            nn.init.zeros_(layer.weight)
        nn.init.zeros_(self.heads.bias)
        nn.init.constant_(self.scale_heads.bias, -6.0)
        self.use_ridge = use_ridge
        if use_ridge:
            if ridge_weights is None:
                ridge_weights = np.zeros((self.count, 1 + spec.history * (spec.state_size + spec.action_size), spec.state_size), np.float32)
            self.register_buffer("ridge", torch.as_tensor(ridge_weights))

    def code(self, states, actions, mask):
        tokens = step_tokens(states, actions, mask, self.scale)
        if self.kind == "attention":
            h = self.embed(tokens) + self.position
            h = self.encoder(h, src_key_padding_mask=mask < 0.5)
            pooled = (h * mask[..., None]).sum(1) / mask.sum(1, keepdim=True)
            return self.project(torch.cat((h[:, -1], pooled), -1))
        return self.encoder(tokens.flatten(1))

    def step(self, states, actions, mask):
        z = self.code(states, actions, mask)
        current = actions[:, -1, :self.count, None]
        delta = (self.heads(z).view(-1, self.count, self.spec.state_size) * current).sum(1)
        log_b = (self.scale_heads(z).view(-1, self.count, self.spec.state_size) * current).sum(1)
        if self.use_ridge:
            x = plain_features(states, actions, self.scale)
            ids = actions[:, -1, :self.count].argmax(1)
            delta = delta + torch.einsum("bf,bfs->bs", x, self.ridge[ids])
        return delta, log_b.clamp(-12, 2)

    def forward(self, states, actions, mask, future):
        outputs, variances = [], []
        last = states[:, -1]
        total = torch.zeros_like(last)
        for k in range(HORIZON):
            delta, log_b = self.step(states, actions, mask)
            nxt = states[:, -1] + delta * self.scale
            total = total + torch.exp(2 * log_b)
            outputs.append((nxt - last) / self.scale)
            variances.append(total)
            if k < HORIZON - 1:
                states = torch.cat((states[:, 1:], nxt[:, None]), 1)
                actions = torch.cat((actions[:, 1:], future[:, k + 1, None]), 1)
                mask = torch.cat((mask[:, 1:], torch.ones_like(mask[:, :1])), 1)
        return torch.stack(outputs, 1), 0.5 * torch.log(torch.stack(variances, 1))


class FrozenV2Base(nn.Module):
    """The v2-selected pipeline's one-step delta on the last three history steps (frozen).

    ferrumos: per-action ridge weights; physical: mean of the three ActionResidual members.
    Loaded only from digest-checked v2 artifacts; never trained further.
    """

    def __init__(self, spec):
        super().__init__()
        import json as _json
        import incident_dynamics_data as v2data
        import evaluate_incident_dynamics_development as v2dev
        import cross_domain_world_model_models as legacy
        selection = _json.loads((v3.ROOT / "docs/research/incident_dynamics_selection_v2.json").read_text(encoding="utf-8"))
        pipeline = selection["domains"][spec.name]["pipelines"]["selected"]
        self.kind = pipeline["kind"]
        self.spec3 = v2data.spec_for(spec.name)
        self.register_buffer("scale", torch.tensor(spec.scale))
        if self.kind == "ridge":
            path = v3.ROOT / pipeline["checkpoint"]["path"]
            if legacy.sha256(path) != pipeline["checkpoint"]["sha256"]:
                raise AssertionError("v2 ridge digest mismatch")
            with np.load(path, allow_pickle=False) as archive:
                self.register_buffer("ridge", torch.as_tensor(archive["weights"], dtype=torch.float32))
        else:
            members = []
            for item in pipeline["members"]:
                path = v3.ROOT / item["checkpoint"]["path"]
                if legacy.sha256(path) != item["checkpoint"]["sha256"]:
                    raise AssertionError("v2 checkpoint digest mismatch")
                members.append(v2dev.load_candidate(path, self.spec3))
            self.members = nn.ModuleList(members)
            for parameter in self.members.parameters():
                parameter.requires_grad_(False)

    def forward(self, states, actions):
        states, actions = states[:, -3:], actions[:, -3:]
        if self.kind == "ridge":
            x = plain_features(states, actions, self.scale)
            ids = actions[:, -1, :self.ridge.shape[0]].argmax(1)
            return torch.einsum("bf,bfs->bs", x, self.ridge[ids])
        self.members.eval()
        return torch.stack([member(states, actions)[0] for member in self.members]).mean(0)


class BoostedV2(UncertainAR):
    """Learned correction (with uncertainty) on top of the frozen v2-selected model."""

    def __init__(self, spec, hidden=256, encoder="mlp"):
        super().__init__(spec, hidden, encoder)
        self.base = FrozenV2Base(spec)

    def step(self, states, actions, mask):
        delta, log_b = super().step(states, actions, mask)
        with torch.no_grad():
            base = self.base(states, actions)
        return base + delta, log_b

    def train(self, mode=True):
        super().train(mode)
        self.base.eval()
        return self


def make(method, spec, hidden, ridge_weights=None):
    if method == "boost_v2":
        return BoostedV2(spec, hidden, "mlp")
    if method == "boost_v2_attention":
        return BoostedV2(spec, hidden, "attention")
    if method == "hybrid_residual":
        return HybridResidual(spec, hidden, ridge_weights)
    if method == "uar_mlp":
        return UncertainAR(spec, hidden, "mlp")
    if method == "uar_attention":
        return UncertainAR(spec, hidden, "attention")
    if method == "uar_hybrid":
        return UncertainAR(spec, hidden, "mlp", ridge_weights, use_ridge=True)
    if method == "uar_hybrid_attention":
        return UncertainAR(spec, hidden, "attention", ridge_weights, use_ridge=True)
    if method == "direct_plan":
        return DirectPlan(spec, hidden)
    if method == "direct_plan_mlp":
        return DirectPlan(spec, hidden, recurrent=False)
    if method == "ar_residual":
        return ARResidual(spec, hidden)
    raise KeyError(method)


def tensors(data, device):
    mask = v3.history_mask(data)
    return [torch.as_tensor(x, device=device) for x in (data.states, data.actions, mask, data.future_actions, data.targets, data.valid)]


@torch.no_grad()
def predict(model, data, batch=4096, with_scale=False):
    device = next(model.parameters()).device
    states, actions, mask, future, _, _ = tensors(data, "cpu")
    means, scales = [], []
    for start in range(0, len(states), batch):
        part = slice(start, start + batch)
        m, ls = model(states[part].to(device), actions[part].to(device), mask[part].to(device), future[part].to(device))
        means.append(m.cpu().numpy())
        scales.append(ls.exp().cpu().numpy())
    scale = model.spec.scale
    mean = np.concatenate(means) * scale + data.states[:, -1:, :]
    if with_scale:
        return mean.astype(np.float32), (np.concatenate(scales) * scale).astype(np.float32)
    return mean.astype(np.float32)


def macro_errors(predicted, data, spec):
    errors = np.mean(np.abs(predicted - data.targets) / spec.scale, axis=-1)
    _, groups = np.unique(data.episodes, return_inverse=True)
    counts = np.bincount(groups)
    return {f"h{h}": float((np.bincount(groups, weights=errors[:, h - 1]) / counts).mean()) for h in (1, 3, 5)}


def train(method, spec, train_data, validation, seed, updates=12000, batch=512, lr=1e-3, hidden=256,
          device="cuda", log=None, weights=None, init=None):
    torch.manual_seed(seed)
    np.random.seed(seed)
    ridge_weights = plain_ridge_fit(train_data, spec) if method in ("hybrid_residual", "uar_hybrid", "uar_hybrid_attention") and init is None else None
    model = make(method, spec, hidden, ridge_weights).to(device)
    if init is not None:
        model.load_state_dict(init.state_dict())
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-5)
    arrays = tensors(train_data, device)
    states, actions, mask, future, targets, valid = arrays
    base = states[:, -1:, :]
    scale = torch.as_tensor(spec.scale, device=device)
    goal = (targets - base) / scale
    generator = torch.Generator(device="cpu").manual_seed(seed)
    sample_weights = None if weights is None else torch.as_tensor(weights, dtype=torch.float32)
    best, best_state, trace = float("inf"), None, []
    started = time.monotonic()
    for update in range(1, updates + 1):
        if sample_weights is None:
            index = torch.randint(len(states), (batch,), generator=generator)
        else:
            index = torch.multinomial(sample_weights, batch, replacement=True, generator=generator)
        index = index.to(device)
        mean, log_scale = model(states[index], actions[index], mask[index], future[index])
        g, v = goal[index], valid[index]
        absolute = (mean - g).abs()
        # Laplace NLL: median-optimal mean (matches MAE) with a learned per-output scale.
        nll = absolute.detach() / log_scale.exp() + log_scale
        loss_steps = nn.functional.smooth_l1_loss(mean, g, beta=.01, reduction="none").mean(-1) + 0.01 * nll.mean(-1)
        loss = (loss_steps * v).sum() / v.sum()
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        optimizer.step()
        for group in optimizer.param_groups:
            group["lr"] = lr * (.05 + .95 * (1 + np.cos(np.pi * update / updates)) / 2)
        if update % 500 == 0 or update == updates:
            model.eval()
            metrics = macro_errors(predict(model, validation), validation, spec)
            model.train()
            score = sum(metrics.values()) / 3
            record = {"update": update, "loss": float(loss.detach()), "selection_score": score,
                      "elapsed_seconds": round(time.monotonic() - started, 1), **metrics}
            trace.append(record)
            if log:
                log(json.dumps({"method": method, "seed": seed, **record}))
            if score < best:
                best, best_state = score, copy.deepcopy(model.state_dict())
    model.load_state_dict(best_state)
    model.eval()
    return model, {"trace": trace, "selected_score": best,
                   "selected_update": min(trace, key=lambda x: x["selection_score"])["update"],
                   "parameters": int(sum(p.numel() for p in model.parameters() if p.requires_grad))}


def load_trial(path, device="cpu"):
    payload = torch.load(path, map_location="cpu", weights_only=False)
    settings = payload["settings"]
    spec = v3.spec_for(settings["domain"], settings["history"])
    ridge = payload["state_dict"].get("ridge")
    model = make(settings["method"], spec, settings["hidden"], None if ridge is None else ridge.numpy())
    model.load_state_dict(payload["state_dict"])
    return model.to(device).eval(), spec, settings
