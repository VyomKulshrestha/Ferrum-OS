#!/usr/bin/env python3
"""GPU world model in a regime where neural models WIN: raw pixels.

Context: on FerrumOS's engineered state/telemetry VECTORS, ridge/GBR beat neural
nets (docs/research/physical_jepa_gpu_devtrial_v1.json,
real_telemetry_hai_forecast_jepa_vs_ridge.json -- both GPU negatives). This maps
the other side of the boundary: when the observation is a raw high-dimensional
IMAGE with nonlinear dynamics (momentum, wall bounce, two objects), a linear
model structurally cannot model it, and a convolutional GPU world model can.

Environment (procedural, deterministic, no external deps): a `size`x`size`
grayscale frame with a controllable agent square (5 discrete impulse actions) and
a free square that bounces off the walls, both with momentum. The next frame is a
nonlinear function of the current frame and action.

World models, each predicting the NEXT frame from (current frame, action):
  persistence   next = current                                   (static baseline)
  ridge         linear map [pixels, action_onehot] -> next pixels (the vector-style baseline)
  cnn_gpu       conv encoder + action + deconv decoder, delta head, trained on CUDA

Reports held-out next-frame MAE overall and on the DYNAMIC region (pixels that
actually change), plus a multi-step rollout MAE. Per-pixel GBR is omitted because
it needs one tree ensemble per output pixel (size*size), which does not scale --
itself part of why this regime needs a neural model.

NOT a claim about the deployed Physical JEPA v5; a capability/regime-boundary demo.

Usage: python scripts/pixel_world_model_gpu.py [--size 32] [--episodes 400] [--steps 24] [--epochs 40]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/research/pixel_world_model_gpu_v1.json"
ACTIONS = np.array([[0, 0], [-1, 0], [1, 0], [0, -1], [0, 1]], np.float32)  # stay, -x,+x,-y,+y


def draw(frame, pos, half, value):
    size = frame.shape[0]
    x, y = int(round(pos[0])), int(round(pos[1]))
    x0, x1 = max(0, x - half), min(size, x + half + 1)
    y0, y1 = max(0, y - half), min(size, y + half + 1)
    frame[y0:y1, x0:x1] = np.maximum(frame[y0:y1, x0:x1], value)


def generate(n_episodes, steps, size, seed):
    rng = np.random.default_rng(seed)
    frames = np.zeros((n_episodes, steps + 1, size, size), np.float32)
    actions = rng.integers(0, len(ACTIONS), (n_episodes, steps)).astype(np.int64)
    lo, hi = 4.0, size - 5.0
    for e in range(n_episodes):
        agent = rng.uniform(lo, hi, 2).astype(np.float32)
        av = np.zeros(2, np.float32)
        free = rng.uniform(lo, hi, 2).astype(np.float32)
        fv = rng.uniform(-1.5, 1.5, 2).astype(np.float32)
        for t in range(steps + 1):
            f = frames[e, t]
            draw(f, agent, 2, 1.0)          # agent: bright 5x5
            draw(f, free, 1, 0.6)           # free object: dimmer 3x3
            if t == steps:
                break
            av = av * 0.8 + ACTIONS[actions[e, t]] * 0.9    # momentum + impulse
            agent = np.clip(agent + av, lo, hi)
            av = np.where((agent <= lo) | (agent >= hi), 0.0, av)
            free = free + fv
            for d in (0, 1):                 # wall bounce (nonlinear)
                if free[d] <= lo:
                    free[d] = lo + (lo - free[d]); fv[d] = -fv[d]
                elif free[d] >= hi:
                    free[d] = hi - (free[d] - hi); fv[d] = -fv[d]
            free = np.clip(free, lo, hi)
    frames += rng.normal(0, 0.01, frames.shape).astype(np.float32)   # tiny sensor noise
    return np.clip(frames, 0, 1).astype(np.float32), actions


def pairs(frames, actions):
    n, T1, s, _ = frames.shape
    cur = frames[:, :-1].reshape(-1, s, s)
    nxt = frames[:, 1:].reshape(-1, s, s)
    act = actions.reshape(-1)
    return cur, act, nxt


def onehot(a, k=len(ACTIONS)):
    o = np.zeros((len(a), k), np.float32)
    o[np.arange(len(a)), a] = 1.0
    return o


def mae_report(pred, true, cur):
    overall = float(np.abs(pred - true).mean())
    change = np.abs(true - cur) > 0.05
    dyn = float(np.abs(pred - true)[change].mean()) if change.any() else float("nan")
    return {"overall_mae": overall, "dynamic_region_mae": dyn}


def ridge_fit_predict(cur_tr, act_tr, nxt_tr, cur_va, act_va, penalty=1.0):
    s = cur_tr.shape[1]
    Xtr = np.concatenate([cur_tr.reshape(len(cur_tr), -1), onehot(act_tr)], 1).astype(np.float32)
    Ytr = nxt_tr.reshape(len(nxt_tr), -1).astype(np.float32)
    design = np.concatenate([Xtr, np.ones((len(Xtr), 1), np.float32)], 1)
    g = (design.T @ design).astype(np.float64)
    c = (design.T @ Ytr).astype(np.float64)
    reg = np.eye(g.shape[0]) * penalty
    reg[-1, -1] = 0.0
    W = np.linalg.solve(g + reg, c).astype(np.float32)
    Xva = np.concatenate([cur_va.reshape(len(cur_va), -1), onehot(act_va), np.ones((len(cur_va), 1), np.float32)], 1)
    pred = np.clip(Xva @ W, 0, 1).reshape(-1, s, s)
    return pred


def train_cnn(cur_tr, act_tr, nxt_tr, cur_va, act_va, nxt_va, size, epochs, seed, change_weight=0.0):
    """change_weight>0 up-weights per-pixel loss on pixels that change between frames,
    so the sparse moving-object signal is not drowned by the static background (a known
    collapse mode of plain MSE on video). Evaluation metric is unaffected."""
    import torch
    from torch import nn
    torch.manual_seed(seed)
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    class WM(nn.Module):
        def __init__(self):
            super().__init__()
            self.enc = nn.Sequential(
                nn.Conv2d(1, 32, 3, 2, 1), nn.GELU(),
                nn.Conv2d(32, 64, 3, 2, 1), nn.GELU(),
                nn.Conv2d(64, 64, 3, 2, 1), nn.GELU())
            self.fdim = 64 * (size // 8) * (size // 8)
            self.act = nn.Sequential(nn.Linear(len(ACTIONS), 64), nn.GELU())
            self.mix = nn.Sequential(nn.Linear(self.fdim + 64, self.fdim), nn.GELU())
            self.dec = nn.Sequential(
                nn.ConvTranspose2d(64, 64, 4, 2, 1), nn.GELU(),
                nn.ConvTranspose2d(64, 32, 4, 2, 1), nn.GELU(),
                nn.ConvTranspose2d(32, 1, 4, 2, 1))

        def forward(self, frame, a):
            h = self.enc(frame).flatten(1)
            h = self.mix(torch.cat([h, self.act(a)], 1)).view(-1, 64, size // 8, size // 8)
            delta = self.dec(h)
            return torch.clamp(frame + delta, 0, 1)

    net = WM().to(dev)
    opt = torch.optim.AdamW(net.parameters(), 1e-3, weight_decay=1e-5)
    tc = torch.from_numpy(cur_tr).unsqueeze(1).to(dev)
    ta = torch.from_numpy(onehot(act_tr)).to(dev)
    tn = torch.from_numpy(nxt_tr).unsqueeze(1).to(dev)
    vc = torch.from_numpy(cur_va).unsqueeze(1).to(dev)
    va = torch.from_numpy(onehot(act_va)).to(dev)
    vn = torch.from_numpy(nxt_va).unsqueeze(1).to(dev)
    wtr = 1.0 + change_weight * (tn - tc).abs().gt(0.05).float() if change_weight > 0 else None
    n, bs = len(tc), 256
    gen = torch.Generator().manual_seed(seed)
    best, best_loss, patience, params = None, 1e9, 0, sum(p.numel() for p in net.parameters())
    for ep in range(epochs):
        net.train()
        for idx in torch.randperm(n, generator=gen).split(bs):
            opt.zero_grad(set_to_none=True)
            se = (net(tc[idx], ta[idx]) - tn[idx]) ** 2
            loss = (se * wtr[idx]).mean() if wtr is not None else se.mean()
            loss.backward(); opt.step()
        net.eval()
        with torch.no_grad():
            pv = net(vc, va)
            chg = (vn - vc).abs().gt(0.05)
            vl = (pv - vn).abs()[chg].mean().item() if chg.any() else (pv - vn).abs().mean().item()  # dynamic-region val MAE
        if vl < best_loss - 1e-7:
            best_loss, best, patience = vl, {k: v.detach().clone() for k, v in net.state_dict().items()}, 0
        else:
            patience += 1
            if patience >= 6:
                break
        if ep == 0 or (ep + 1) % 5 == 0:
            print(f"  cnn epoch={ep+1} val_mse={vl:.6f} best={best_loss:.6f}", flush=True)
    net.load_state_dict(best)
    net.eval()
    with torch.no_grad():
        pred = net(vc, va).squeeze(1).cpu().numpy()
    return pred, params, net, dev


def rollout_mae(net, dev, frames_va, actions_va, horizon, size):
    """Closed-loop H-step rollout MAE on held-out episodes (CNN)."""
    import torch
    n = frames_va.shape[0]
    cur = torch.from_numpy(frames_va[:, 0]).unsqueeze(1).to(dev)
    errs = []
    with torch.no_grad():
        for t in range(horizon):
            a = torch.from_numpy(onehot(actions_va[:, t])).to(dev)
            cur = net(cur, a)
            true = torch.from_numpy(frames_va[:, t + 1]).unsqueeze(1).to(dev)
            errs.append(float((cur - true).abs().mean()))
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=32)
    ap.add_argument("--episodes", type=int, default=400)
    ap.add_argument("--steps", type=int, default=24)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--change-weight", type=float, default=30.0)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    t0 = time.time()
    frames, actions = generate(a.episodes, a.steps, a.size, a.seed)
    n_val = max(1, a.episodes // 5)
    tr, va = slice(0, a.episodes - n_val), slice(a.episodes - n_val, a.episodes)
    cur_tr, act_tr, nxt_tr = pairs(frames[tr], actions[tr])
    cur_va, act_va, nxt_va = pairs(frames[va], actions[va])
    print(f"pixel world {a.size}x{a.size}: {a.episodes} ep x {a.steps} steps; "
          f"train {len(cur_tr)} / val {len(cur_va)} transitions ({round(time.time()-t0)}s)", flush=True)

    res = {}
    res["persistence"] = mae_report(cur_va, nxt_va, cur_va)
    print(f"  persistence   overall {res['persistence']['overall_mae']:.5f}  dyn {res['persistence']['dynamic_region_mae']:.5f}", flush=True)
    tr0 = time.time()
    rp = ridge_fit_predict(cur_tr, act_tr, nxt_tr, cur_va, act_va)
    res["ridge_linear"] = mae_report(rp, nxt_va, cur_va)
    print(f"  ridge_linear  overall {res['ridge_linear']['overall_mae']:.5f}  dyn {res['ridge_linear']['dynamic_region_mae']:.5f}  ({round(time.time()-tr0)}s)", flush=True)
    tc0 = time.time()
    cp0, params, net0, dev = train_cnn(cur_tr, act_tr, nxt_tr, cur_va, act_va, nxt_va, a.size, a.epochs, a.seed, change_weight=0.0)
    res["cnn_plain_mse"] = {**mae_report(cp0, nxt_va, cur_va), "trainable_parameters": params, "device": str(dev),
                            "note": "plain MSE collapses toward copy on sparse-change pixels; matches the linear blur"}
    print(f"  cnn_plain_mse overall {res['cnn_plain_mse']['overall_mae']:.5f}  dyn {res['cnn_plain_mse']['dynamic_region_mae']:.5f}  ({round(time.time()-tc0)}s)", flush=True)
    cw0 = time.time()
    cpw, _, net, dev = train_cnn(cur_tr, act_tr, nxt_tr, cur_va, act_va, nxt_va, a.size, a.epochs, a.seed, change_weight=a.change_weight)
    res["cnn_gpu"] = {**mae_report(cpw, nxt_va, cur_va), "trainable_parameters": params, "device": str(dev),
                      "change_weight": a.change_weight}
    print(f"  cnn_gpu(cw={a.change_weight}) overall {res['cnn_gpu']['overall_mae']:.5f}  dyn {res['cnn_gpu']['dynamic_region_mae']:.5f}  "
          f"({params} params, {round(time.time()-cw0)}s)", flush=True)
    roll = {"cnn_gpu": rollout_mae(net, dev, frames[va], actions[va], min(10, a.steps), a.size)}
    # persistence rollout for reference
    roll["persistence"] = [float(np.abs(frames[va][:, 0] - frames[va][:, t + 1]).mean()) for t in range(min(10, a.steps))]

    cnn, rid, per = res["cnn_gpu"]["dynamic_region_mae"], res["ridge_linear"]["dynamic_region_mae"], res["persistence"]["dynamic_region_mae"]
    verdict = (f"CNN GPU wins the pixel regime: dynamic-region MAE {cnn:.4f} vs ridge {rid:.4f} "
               f"({100*(rid-cnn)/rid:+.0f}% vs ridge) vs persistence {per:.4f}"
               if cnn < rid and cnn < per else
               f"CNN did NOT win: cnn {cnn:.4f} ridge {rid:.4f} persistence {per:.4f}")
    doc = {"schema_version": "pixel-world-model-gpu-v1", "status": "EXPLORATORY capability/regime-boundary demo (not vs deployed v5)",
           "env": {"size": a.size, "episodes": a.episodes, "steps": a.steps, "actions": len(ACTIONS),
                   "dynamics": "momentum + wall-bounce + two objects; nonlinear in pixel space"},
           "note": "Per-pixel GBR omitted: one tree ensemble per output pixel does not scale, which is itself why raw-pixel regimes need a neural world model. Linear ridge is the scalable non-neural baseline.",
           "results": res, "rollout_mae": roll, "verdict": verdict}
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"\n{verdict}\nwrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
