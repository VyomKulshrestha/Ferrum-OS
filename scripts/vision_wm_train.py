#!/usr/bin/env python3
"""FerrumOS vision world model + caution head (increment 1). Branch work, not on main.

Trains a GPU CNN world model on rendered pybullet scenes
(scripts/vision_wm_pybullet_data.py) that, from a short stack of the last K frames
plus the action, (a) predicts the next frame and (b) emits a caution score =
P(hazard within the next H steps). The K-frame stack makes velocity (momentum)
observable, so the task is well-posed -- a single frame hides velocity.

Compared against non-neural baselines on held-out scenes:
  frame:   persistence, ridge-on-pixels            (dynamic-region MAE)
  caution: base rate, linear logistic pixel probe   (AUC-PR, AUC-ROC)

Caution is the deployable-relevant output (advisory only). Key test: does the
neural model beat a linear pixel probe at anticipating hazards -- the raw-pixel,
nonlinear-approach regime where neural should earn its place.

Usage: python scripts/vision_wm_train.py [--size 48] [--train-ep 500] [--val-ep 150]
                                         [--steps 20] [--epochs 50] [--horizon 3] [--frames 2]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score

import vision_wm_pybullet_data as D

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/research/vision_world_model_result_v1.json"
NA = len(D.ACTIONS)


def onehot(a, k=NA):
    o = np.zeros((len(a), k), np.float32); o[np.arange(len(a)), a] = 1.0; return o


def build(frames, actions, hazards, horizon, K):
    """cur (N,K,s,s) = frames t-K+1..t ; action t ; next (N,s,s)=t+1 ; y=any hazard in t+1..t+H."""
    n, T1, s, _ = frames.shape
    steps = T1 - 1
    cur, nxt, act, y = [], [], [], []
    for e in range(n):
        for t in range(K - 1, steps):
            cur.append(frames[e, t - K + 1:t + 1]); nxt.append(frames[e, t + 1]); act.append(actions[e, t])
            y.append(int(hazards[e, t + 1:min(t + 1 + horizon, T1)].any()))
    return np.stack(cur), np.array(act, np.int64), np.stack(nxt), np.array(y, np.int8)


def mae_report(pred, true, cur_last):
    overall = float(np.abs(pred - true).mean())
    chg = np.abs(true - cur_last) > 0.05
    dyn = float(np.abs(pred - true)[chg].mean()) if chg.any() else float("nan")
    return {"overall_mae": overall, "dynamic_region_mae": dyn}


def ridge_frame(cur_tr, act_tr, nxt_tr, cur_va, act_va, pen=1.0):
    s = cur_tr.shape[-1]
    flat = lambda c, a: np.concatenate([c.reshape(len(c), -1), onehot(a), np.ones((len(c), 1), np.float32)], 1)
    X, Y = flat(cur_tr, act_tr), nxt_tr.reshape(len(nxt_tr), -1).astype(np.float32)
    g = (X.T @ X).astype(np.float64); c = (X.T @ Y).astype(np.float64)
    reg = np.eye(g.shape[0]) * pen; reg[-1, -1] = 0
    W = np.linalg.solve(g + reg, c).astype(np.float32)
    return np.clip(flat(cur_va, act_va) @ W, 0, 1).reshape(-1, s, s)


def auc(y, score):
    if y.min() == y.max():
        return {"auc_pr": float("nan"), "auc_roc": float("nan"), "prevalence": float(y.mean())}
    return {"auc_pr": float(average_precision_score(y, score)), "auc_roc": float(roc_auc_score(y, score)),
            "prevalence": float(y.mean())}


def train_cnn(data, size, K, epochs, change_weight, lam, seed):
    import torch
    from torch import nn
    cur_tr, act_tr, nxt_tr, y_tr, cur_va, act_va, nxt_va, y_va = data
    torch.manual_seed(seed)
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    class VWM(nn.Module):
        def __init__(self):
            super().__init__()
            self.enc = nn.Sequential(nn.Conv2d(K, 32, 3, 2, 1), nn.GELU(),
                                     nn.Conv2d(32, 64, 3, 2, 1), nn.GELU(),
                                     nn.Conv2d(64, 64, 3, 2, 1), nn.GELU())
            self.g = size // 8
            self.act = nn.Sequential(nn.Linear(NA, 64), nn.GELU())
            self.mix = nn.Sequential(nn.Linear(64 * self.g * self.g + 64, 64 * self.g * self.g), nn.GELU())
            self.dec = nn.Sequential(nn.ConvTranspose2d(64, 64, 4, 2, 1), nn.GELU(),
                                     nn.ConvTranspose2d(64, 32, 4, 2, 1), nn.GELU(),
                                     nn.ConvTranspose2d(32, 1, 4, 2, 1))
            self.haz = nn.Sequential(nn.Linear(64 * self.g * self.g, 128), nn.GELU(), nn.Linear(128, 1))

        def forward(self, stack, a):
            h = self.enc(stack).flatten(1)
            m = self.mix(torch.cat([h, self.act(a)], 1))
            nxt = torch.clamp(stack[:, -1:] + self.dec(m.view(-1, 64, self.g, self.g)), 0, 1)
            return nxt, self.haz(m).squeeze(1)

    net = VWM().to(dev)
    opt = torch.optim.AdamW(net.parameters(), 1e-3, weight_decay=1e-5)
    T = lambda x: torch.from_numpy(x).to(dev)
    tc, ta, tn, ty = T(cur_tr), T(onehot(act_tr)), T(nxt_tr).unsqueeze(1), T(y_tr.astype(np.float32))
    vc, van = T(cur_va), T(onehot(act_va))
    wtr = 1.0 + change_weight * (tn - tc[:, -1:]).abs().gt(0.05).float()
    pos_w = torch.tensor([max(1.0, float((y_tr == 0).sum()) / max(1.0, float((y_tr == 1).sum())))], device=dev)
    bce = nn.BCEWithLogitsLoss(pos_weight=pos_w)
    n, bs = len(tc), 256
    gen = torch.Generator().manual_seed(seed)
    best, best_ap, patience, params = None, -1.0, 0, sum(p.numel() for p in net.parameters())
    for ep in range(epochs):
        net.train()
        for idx in torch.randperm(n, generator=gen).split(bs):
            opt.zero_grad(set_to_none=True)
            pf, pl = net(tc[idx], ta[idx])
            loss = ((pf - tn[idx]) ** 2 * wtr[idx]).mean() + lam * bce(pl, ty[idx])
            loss.backward(); opt.step()
        net.eval()
        with torch.no_grad():
            _, vl = net(vc, van)
            ap = average_precision_score(y_va, vl.cpu().numpy()) if y_va.min() != y_va.max() else 0.0
        if ap > best_ap + 1e-5:
            best_ap, best, patience = ap, {k: v.detach().clone() for k, v in net.state_dict().items()}, 0
        else:
            patience += 1
            if patience >= 8:
                break
        if ep == 0 or (ep + 1) % 5 == 0:
            print(f"  cnn epoch={ep+1} val_caution_AP={ap:.4f} best={best_ap:.4f}", flush=True)
    net.load_state_dict(best); net.eval()
    with torch.no_grad():
        pf, pl = net(vc, van)
    return pf.squeeze(1).cpu().numpy(), pl.cpu().numpy(), params, str(dev)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=48)
    ap.add_argument("--train-ep", type=int, default=500)
    ap.add_argument("--val-ep", type=int, default=150)
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--horizon", type=int, default=3)
    ap.add_argument("--frames", type=int, default=2)
    ap.add_argument("--change-weight", type=float, default=30.0)
    ap.add_argument("--haz-lambda", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    K = a.frames
    t0 = time.time()
    ftr, atr, htr = D.collect(a.train_ep, a.steps, a.size, seed=0)
    fva, ava, hva = D.collect(a.val_ep, a.steps, a.size, seed=1)
    cur_tr, act_tr, nxt_tr, y_tr = build(ftr, atr, htr, a.horizon, K)
    cur_va, act_va, nxt_va, y_va = build(fva, ava, hva, a.horizon, K)
    print(f"vision-wm {a.size}x{a.size} K={K}: train {len(cur_tr)} / val {len(cur_va)} transitions; "
          f"caution prevalence train {y_tr.mean():.3f} val {y_va.mean():.3f} ({round(time.time()-t0)}s)", flush=True)

    res = {"frame": {}, "caution": {}}
    res["frame"]["persistence"] = mae_report(cur_va[:, -1], nxt_va, cur_va[:, -1])
    res["frame"]["ridge"] = mae_report(ridge_frame(cur_tr, act_tr, nxt_tr, cur_va, act_va), nxt_va, cur_va[:, -1])
    print(f"  frame persistence dyn {res['frame']['persistence']['dynamic_region_mae']:.4f} | "
          f"ridge dyn {res['frame']['ridge']['dynamic_region_mae']:.4f}", flush=True)

    res["caution"]["base_rate"] = {"auc_pr": float(y_va.mean()), "auc_roc": 0.5, "prevalence": float(y_va.mean())}
    Xtr = np.concatenate([cur_tr.reshape(len(cur_tr), -1), onehot(act_tr)], 1)
    Xva = np.concatenate([cur_va.reshape(len(cur_va), -1), onehot(act_va)], 1)
    lp = LogisticRegression(max_iter=400, C=0.5, class_weight="balanced").fit(Xtr, y_tr)
    res["caution"]["linear_probe"] = auc(y_va, lp.predict_proba(Xva)[:, 1])
    print(f"  caution base AP {res['caution']['base_rate']['auc_pr']:.4f} | "
          f"linear_probe AP {res['caution']['linear_probe']['auc_pr']:.4f} ROC {res['caution']['linear_probe']['auc_roc']:.4f}", flush=True)

    tc0 = time.time()
    pf, pl, params, dev = train_cnn((cur_tr, act_tr, nxt_tr, y_tr, cur_va, act_va, nxt_va, y_va),
                                    a.size, K, a.epochs, a.change_weight, a.haz_lambda, a.seed)
    res["frame"]["cnn_gpu"] = mae_report(pf, nxt_va, cur_va[:, -1])
    res["caution"]["cnn_gpu"] = {**auc(y_va, pl), "trainable_parameters": params, "device": dev}
    print(f"  cnn_gpu frame dyn {res['frame']['cnn_gpu']['dynamic_region_mae']:.4f} | "
          f"caution AP {res['caution']['cnn_gpu']['auc_pr']:.4f} ROC {res['caution']['cnn_gpu']['auc_roc']:.4f}  "
          f"({params} params, {round(time.time()-tc0)}s)", flush=True)

    cnn_ap = res["caution"]["cnn_gpu"]["auc_pr"]; lin_ap = res["caution"]["linear_probe"]["auc_pr"]; base_ap = res["caution"]["base_rate"]["auc_pr"]
    verdict = (f"Vision CNN caution beats the linear pixel probe: AUC-PR {cnn_ap:.3f} vs {lin_ap:.3f} (base {base_ap:.3f})"
               if cnn_ap > lin_ap else f"CNN did NOT beat the linear probe: AUC-PR {cnn_ap:.3f} vs {lin_ap:.3f} (base {base_ap:.3f})")
    doc = {"schema_version": "vision-world-model-result-v1", "status": "EXPLORATORY increment-1, branch work (not on main); advisory only",
           "env": {"size": a.size, "frame_stack": K, "train_ep": a.train_ep, "val_ep": a.val_ep, "steps": a.steps,
                   "caution_horizon": a.horizon, "renderer": "pybullet DIRECT TinyRenderer"},
           "results": res, "verdict": verdict,
           "note": "Rendered pybullet scenes, numpy kinematics, advisory caution only, not a real-hardware claim. "
                   "K-frame stack makes velocity observable. Caution = P(hazard within H); neural vs linear pixel probe is the key test."}
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"\n{verdict}\nwrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
