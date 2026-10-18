#!/usr/bin/env python3
"""Development-only multi-step dynamics training; never loads a final catalog."""
from __future__ import annotations

import argparse
import copy
import json
import os
import time

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
import numpy as np
import torch
from torch import nn

import cross_domain_world_model_models as legacy
import evaluate_cross_domain_world_models as architecture
import incident_dynamics_data as data


class CausalResidual(nn.Module):
    """Learned linear skip plus nonlinear residual on state, deltas and actions.

    No hand-coded transition coefficients, hazard labels, or future states.
    Scaling is the pre-existing documented state range, not a test statistic.
    """
    def __init__(self, spec, hidden=192):
        super().__init__()
        self.register_buffer("scale", torch.tensor(spec.scale))
        width = spec.history * (spec.state_size + spec.action_size)
        self.linear = nn.Linear(width, spec.state_size)
        self.network = nn.Sequential(nn.Linear(width, hidden), nn.SiLU(),
                                     nn.Linear(hidden, hidden), nn.SiLU(),
                                     nn.Linear(hidden, spec.state_size))
        nn.init.zeros_(self.linear.weight)
        nn.init.zeros_(self.linear.bias)
        nn.init.zeros_(self.network[-1].weight)
        nn.init.zeros_(self.network[-1].bias)

    def forward(self, states, actions, next_state=None):
        normalized = states / self.scale
        causal = torch.cat((normalized[:, -1:], normalized[:, 1:] - normalized[:, :-1]), dim=1)
        inputs = torch.cat((causal.flatten(1), actions.flatten(1)), dim=1)
        mean = self.linear(inputs) + self.network(inputs)
        return mean, mean.new_full(mean.shape, -8), mean.new_zeros(())


class ActionResidual(nn.Module):
    """Shared history encoder with learned action-specific delta heads."""
    def __init__(self, spec, hidden=192):
        super().__init__()
        self.register_buffer("scale", torch.tensor(spec.scale))
        self.action_count = 41 if spec.name == "ferrumos" else 7
        self.state_size = spec.state_size
        width = spec.history * (spec.state_size + spec.action_size)
        self.encoder = nn.Sequential(nn.Linear(width, hidden), nn.SiLU(), nn.Linear(hidden, hidden), nn.SiLU())
        self.heads = nn.Linear(hidden, self.action_count * spec.state_size)
        nn.init.zeros_(self.heads.weight)
        nn.init.zeros_(self.heads.bias)

    def forward(self, states, actions, next_state=None):
        normalized = states / self.scale
        causal = torch.cat((normalized[:, -1:], normalized[:, 1:] - normalized[:, :-1]), dim=1)
        inputs = torch.cat((causal.flatten(1), actions.flatten(1)), dim=1)
        experts = self.heads(self.encoder(inputs)).view(-1, self.action_count, self.state_size)
        mean = (experts * actions[:, -1, :self.action_count, None]).sum(1)
        return mean, mean.new_full(mean.shape, -8), mean.new_zeros(())


def make_model(method, spec, hidden=192):
    if method == "causal_residual":
        return CausalResidual(spec, hidden)
    if method == "action_residual":
        return ActionResidual(spec, hidden)
    return legacy.make_model(method, spec, hidden)


def rollout(model, states, actions, future, spec, targets=None):
    scale = torch.as_tensor(spec.scale, device=states.device)
    result, auxiliary = [], states.new_zeros(())
    for step in range(future.shape[1]):
        target = None if targets is None else targets[:, step]
        delta, _, aux = model(states, actions, target)
        predicted = states[:, -1] + scale * delta
        result.append(predicted)
        auxiliary = auxiliary + aux
        if step + 1 < future.shape[1]:
            states = torch.cat((states[:, 1:], predicted[:, None]), dim=1)
            actions = torch.cat((actions[:, 1:], future[:, step + 1, None]), dim=1)
    return torch.stack(result, 1), auxiliary / future.shape[1]


@torch.no_grad()
def predictions(model, windows, spec, batch_size=2048):
    device = next(model.parameters()).device
    results = []
    for start in range(0, len(windows.states), batch_size):
        part = slice(start, start + batch_size)
        states, actions, future = [torch.as_tensor(x[part], device=device) for x in (windows.states, windows.actions, windows.future_actions)]
        predicted, _ = rollout(model, states, actions, future, spec)
        results.append(predicted.cpu().numpy())
    return np.concatenate(results)


def macro_errors(predicted, windows, spec):
    errors = np.mean(np.abs(predicted - windows.targets) / spec.scale, axis=-1)
    _, groups = np.unique(windows.episodes, return_inverse=True)
    counts = np.bincount(groups)
    values = [np.bincount(groups, weights=errors[:, h]) / counts for h in (0, 2, 4)]
    return {f"h{h}": float(value.mean()) for h, value in zip((1, 3, 5), values)}


def train(args):
    protocol = architecture.load_json(architecture.PROTOCOL)
    guard = architecture.install_final_guard(protocol)
    if not all(architecture.verify_digest_map(protocol["protected_deployed_artifacts"]).values()):
        raise AssertionError("protected deployment drift")
    output = data.WORK / args.domain / f"{args.run_id}-{args.method}-{args.seed}.pt"
    if output.exists():
        raise FileExistsError(f"retain the existing trial: {output}")
    spec = data.spec_for(args.domain)
    training = data.load_windows(data.WORK / args.domain / "train.npz")
    validation = data.load_windows(data.WORK / args.domain / "validation.npz")
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)
    device = torch.device(args.device)
    model = make_model(args.method, spec, args.hidden).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-5)
    scale = torch.as_tensor(spec.scale, device=device)
    arrays = [torch.as_tensor(x, device=device) for x in (training.states, training.actions, training.future_actions, training.targets, training.valid)]
    generator = torch.Generator().manual_seed(args.seed)
    trace, best, best_state = [], float("inf"), None
    started = time.monotonic()
    for update in range(1, args.updates + 1):
        indices = torch.randint(len(training.states), (args.batch_size,), generator=generator).to(device)
        states, actions, future, targets, valid = [x[indices] for x in arrays]
        predicted, auxiliary = rollout(model, states, actions, future, spec, targets)
        loss_values = nn.functional.smooth_l1_loss(predicted / scale, targets / scale, beta=.02, reduction="none").mean(-1)
        loss = (loss_values * valid).sum() / valid.sum()
        if args.method == "action_conditioned_jepa":
            loss = loss + .01 * auxiliary
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        optimizer.step()
        if isinstance(model, legacy.TemporalJEPA):
            model.update_target()
        # Deterministic decay, not triggered by results.
        for group in optimizer.param_groups:
            group["lr"] = args.lr * (.15 + .85 * (1 + np.cos(np.pi * update / args.updates)) / 2)
        if update % 250 == 0 or update == args.updates:
            metrics = macro_errors(predictions(model, validation, spec), validation, spec)
            score = sum(metrics.values()) / 3
            record = {"update": update, "loss": float(loss.detach()), "selection_score": score,
                      "elapsed_seconds": round(time.monotonic() - started, 3), **metrics}
            trace.append(record)
            print(json.dumps({"domain": args.domain, "method": args.method, "seed": args.seed, **record}), flush=True)
            if score < best:
                best, best_state = score, copy.deepcopy(model.state_dict())
    model.load_state_dict(best_state)
    checks = architecture.verify_digest_map(protocol["protected_deployed_artifacts"])
    if not all(checks.values()) or guard["attempted"]:
        raise AssertionError("integrity or selection boundary failed")
    metadata = {"settings": vars(args), "trainable_parameters": legacy.trainable_parameters(model),
                "trace": trace, "selected_score": best, "selected_update": min(trace, key=lambda x: x["selection_score"])["update"],
                "final_access_attempted": guard["attempted"], "protected_digests_unchanged": checks,
                "promotion_eligible": False, "torch": str(torch.__version__), "numpy": str(np.__version__),
                "data_manifest_sha256": legacy.sha256(data.WORK / args.domain / "data_manifest.json"),
                "script_sha256": legacy.sha256(data.ROOT / "scripts/train_incident_dynamics.py"),
                "data_script_sha256": legacy.sha256(data.ROOT / "scripts/incident_dynamics_data.py")}
    model.cpu()
    checkpoint = legacy.save_model(output, model, metadata)
    architecture.write_json(output.with_suffix(".json"), {**metadata, "checkpoint": checkpoint})
    print(json.dumps({"checkpoint": checkpoint, "best": best}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["prepare", "train"])
    parser.add_argument("--domain", choices=["ferrumos", "physical"], required=True)
    parser.add_argument("--method", default="causal_residual", choices=["causal_residual", "action_residual", "action_conditioned_jepa", "direct_mlp"])
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--run-id", default="trial01")
    parser.add_argument("--hidden", type=int, default=192)
    parser.add_argument("--updates", type=int, default=6000)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=.001)
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()
    if args.stage == "prepare":
        print(json.dumps(data.prepare(args.domain)))
    else:
        train(args)


if __name__ == "__main__":
    main()
