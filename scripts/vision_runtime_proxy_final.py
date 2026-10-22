#!/usr/bin/env python3
"""Registered single-open evaluation of the vision caution head on the runtime-scene proxy
(docs/research/vision_caution_runtime_proxy_protocol_v1.json). Branch work, not main.

Footage: scripts/vision_runtime_domain_render.py (the runtime's own PyBullet world filmed
from an overhead camera; simulation, not real footage). Action input: the runtime's own
10-dim PhysicalAction encoding (identity mapping), against the lossy 5-impulse projection.

Everything trains, selects and calibrates on seeds 200/201; the selected head is persisted
to docs/research/artifacts/vision-caution-v2/ and hashed; only then is the sealed seed
recorded in target/vision-wm/final_access.jsonl, rendered once and scored. CPU only.

Usage:
  CUDA_VISIBLE_DEVICES=-1 python scripts/vision_runtime_proxy_final.py --dry-run
  CUDA_VISIBLE_DEVICES=-1 python scripts/vision_runtime_proxy_final.py --smoke      # throwaway seed + temp ledger
  CUDA_VISIBLE_DEVICES=-1 python scripts/vision_runtime_proxy_final.py [--final-seed 790]   # 791 only per the crash rule
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import torch  # noqa: E402
import torch.nn as nn  # noqa: E402
import torch.nn.functional as F  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import average_precision_score  # noqa: E402

import train_physical_world_model as simulator  # noqa: E402
import vision_runtime_domain_render as R  # noqa: E402
import vision_wm_final_v2 as FV  # noqa: E402
import vision_wm_pretrained_encoders as PE  # noqa: E402
import vision_wm_train as TR  # noqa: E402

PROTOCOL = ROOT / "docs/research/vision_caution_runtime_proxy_protocol_v1.json"
OUT = ROOT / "docs/research/vision_caution_runtime_proxy_result_v1.json"
ARTIFACT = ROOT / "docs/research/artifacts/vision-caution-v2/selected_caution_head.npz"
V1_ARTIFACT = ROOT / "docs/research/artifacts/vision-caution-v1/selected_caution_head.npz"
V1_SHA = "800797e0701b70c5c471242a3310cb0c46f62335e9db49797945763e3a2f8a2a"
AUTHORITY = "advisory diagnostic only; no permit, block, approval, adapter or actuation authority"
K, H, STEPS, SIZE, PRIMARY_FPR, BUDGET = 2, 3, R.STEPS, R.SIZE, 0.05, 0.10
SPLITS = {"train": (200, 800), "sel": (201, 300)}
DEV = torch.device("cpu")


def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# --- data ----------------------------------------------------------------------------
def decisions(d):
    """Decision points t = 1..STEPS-1: indices, runtime/lossy actions, label and hazard types."""
    n = len(d["kinds"])
    e, t = np.meshgrid(np.arange(n), np.arange(K - 1, STEPS), indexing="ij")
    e, t = e.ravel(), t.ravel()
    kinds, feats, h = d["kinds"], d["features"], d["hazards"]
    a10 = np.stack([R.runtime_action_vector(kinds[i, j], feats[i, j]) for i, j in zip(e, t)])
    a5 = np.array([R.lossy_sim_action(kinds[i, j], feats[i, j]) for i, j in zip(e, t)], np.int64)
    window = lambda arr: np.array([int(arr[i, j + 1:min(j + 1 + H, STEPS + 1)].any()) for i, j in zip(e, t)], np.int8)
    moving = (kinds == simulator.MOVE) & (feats[:, :, 2] > 0.1)
    prox = np.zeros_like(h)
    prox[:, 1:] = moving & (d["clearance"][:, 1:] < R.CLEARANCE_HAZARD)
    geo = (d["margin"] < 0).astype(np.int8)
    geo[:, 0] = 0
    y = window(h)
    types = {"proximity": window(prox), "geofence": window(geo), "contact": window(d["contact"])}
    return {"e": e, "t": t, "a10": a10, "a5": a5, "y": y, "kind": kinds[e, t], "types": types}


def state_features(d, idx):
    """TRUE decision-time geometry + kinematic next state (state_reference only)."""
    e, t = idx["e"], idx["t"]
    r = d["robot_xy"][e, t]
    o = d["obstacle_xy"][e]
    a = idx["a10"]
    moving = ((idx["kind"] == simulator.MOVE) & (a[:, 9] > 0.1)).astype(np.float32)
    nxt = r + R.STEP_GAIN * a[:, 7:9] * moving[:, None]
    clr = lambda p: np.clip(np.hypot(*(p - o).T) - 0.16, 0, 1)
    mar = lambda p: 1.0 - np.abs(p).max(1)
    return np.column_stack([r, o, o - r, clr(r), mar(r), nxt, clr(nxt), mar(nxt), a]).astype(np.float32)


# --- frozen encoder ------------------------------------------------------------------
@torch.no_grad()
def extract(enc, frames, pools=(4, 8), bs=64):
    """frames (n, T, s, s) -> {P: (n, T, 384, P, P) fp16}; one encoder pass for every pooling."""
    n, T = frames.shape[:2]
    flat = torch.from_numpy(frames.reshape(n * T, 1, *frames.shape[2:]))
    out = {p: [] for p in pools}
    for i in range(0, len(flat), bs):
        x = flat[i:i + bs].float().repeat(1, 3, 1, 1)
        x = F.interpolate(x, size=(224, 224), mode="bilinear", align_corners=False)
        z = enc((x - PE.MEAN) / PE.STD)
        if not torch.isfinite(z).all():
            raise RuntimeError("non-finite encoder output")
        for p in pools:
            out[p].append(F.adaptive_avg_pool2d(z, p).half())
    return {p: torch.cat(v).view(n, T, 384, p, p) for p, v in out.items()}


# --- head (same architecture as PE.train_head, action input given as a matrix) --------
def make_head(pool, n_act):
    return nn.ModuleDict({"red": nn.Conv2d(768, 64, 1), "act": nn.Linear(n_act, 32),
                          "mlp": nn.Sequential(nn.Linear(64 * pool * pool + 32, 128), nn.GELU(), nn.Linear(128, 1))})


def head_forward(head, Fx, e, t, a):
    st = torch.cat([Fx[e, t - 1], Fx[e, t]], 1).float()
    z = F.gelu(head["red"](st)).flatten(1)
    return head["mlp"](torch.cat([z, F.gelu(head["act"](a))], 1)).squeeze(1)


def score_head(head, Fx, idx, A, bs=2048):
    e, t, a = torch.from_numpy(idx["e"]), torch.from_numpy(idx["t"]), torch.from_numpy(A.astype(np.float32))
    with torch.no_grad():
        return torch.cat([head_forward(head, Fx, e[i:i + bs], t[i:i + bs], a[i:i + bs])
                          for i in range(0, len(e), bs)]).numpy()


def train_head(Ftr, Fse, itr, ise, Atr, Ase, pool, epochs, seed=0):
    torch.manual_seed(seed)
    head = make_head(pool, Atr.shape[1])
    e, t = torch.from_numpy(itr["e"]), torch.from_numpy(itr["t"])
    a = torch.from_numpy(Atr.astype(np.float32))
    ytr = itr["y"]
    yt = torch.from_numpy(ytr.astype(np.float32))
    pw = torch.tensor([max(1.0, float((ytr == 0).sum()) / max(1.0, float(ytr.sum())))])
    opt = torch.optim.AdamW(head.parameters(), 1e-3, weight_decay=1e-4)
    gen = torch.Generator().manual_seed(seed)
    best, best_ap, pat = None, -1.0, 0
    for _ in range(epochs):
        head.train()
        for b in torch.randperm(len(ytr), generator=gen).split(256):
            opt.zero_grad(set_to_none=True)
            F.binary_cross_entropy_with_logits(head_forward(head, Ftr, e[b], t[b], a[b]), yt[b], pos_weight=pw).backward()
            opt.step()
        head.eval()
        ap = average_precision_score(ise["y"], score_head(head, Fse, ise, Ase))
        if ap > best_ap + 1e-5:
            best_ap, best, pat = ap, {k: v.detach().clone() for k, v in head.state_dict().items()}, 0
        else:
            pat += 1
            if pat >= 8:
                break
    head.load_state_dict(best)
    return head.eval(), float(best_ap)


def v1_head():
    sys.path.insert(0, str(ROOT / "tools" / "vision_caution"))
    from vision_caution import load_artifact
    art = load_artifact(V1_ARTIFACT, V1_SHA)
    head = make_head(4, 5)
    head.load_state_dict({k: torch.from_numpy(v) for k, v in art["weights"].items()}, strict=True)
    return head.eval(), art["thresholds"]["fpr_0.05"]


def onehot5(a5):
    return np.eye(5, dtype=np.float32)[a5]


# --- statistics ------------------------------------------------------------------------
def cluster_boot(hit_a, hit_b, y, ep, n_ep, reps=10000, seed=0):
    """Episode-cluster bootstrap of a recall difference (positives inside resampled episodes)."""
    pos = y == 1
    na = np.bincount(ep[pos], weights=hit_a[pos].astype(np.float64), minlength=n_ep)
    nb = np.bincount(ep[pos], weights=hit_b[pos].astype(np.float64), minlength=n_ep)
    npos = np.bincount(ep[pos], minlength=n_ep).astype(np.float64)
    rng = np.random.default_rng(seed)
    if npos.sum() == 0:
        return {"recall_difference": None, "ci95": [None, None], "episodes": int(n_ep), "positives": 0}
    idx = rng.integers(0, n_ep, (reps, n_ep))
    diff = (na[idx].sum(1) - nb[idx].sum(1)) / np.maximum(npos[idx].sum(1), 1.0)
    return {"recall_difference": float((na.sum() - nb.sum()) / npos.sum()),
            "ci95": [float(np.quantile(diff, 0.025)), float(np.quantile(diff, 0.975))],
            "episodes": int(n_ep), "positives": int(npos.sum())}


def guard_bridge_unmodified():
    head = subprocess.run(["git", "show", "HEAD:tools/physical_sim_bridge/bridge.py"], cwd=ROOT,
                          capture_output=True, check=True).stdout
    live = (ROOT / "tools/physical_sim_bridge/bridge.py").read_bytes()
    if head.replace(b"\r\n", b"\n") != live.replace(b"\r\n", b"\n"):
        raise SystemExit("REFUSE: tools/physical_sim_bridge/bridge.py differs from HEAD")
    return hashlib.sha256(live).hexdigest()


def main():
    global OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--final-seed", type=int, default=790)
    a = ap.parse_args()
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    splits, fseed, nf, epochs, art_path = dict(SPLITS), a.final_seed, 400, 60, ARTIFACT
    if a.dry_run:
        print(protocol["gates"]["primary_success"], "|", protocol["gates"]["G1_capability"])
        print(f"sealed seed {fseed}: " + ("ALREADY opened -> REFUSE" if FV.ledger_has(fseed) else "not yet opened -> eligible"))
        return
    if torch.cuda.is_available():
        raise SystemExit("REFUSE: the protocol requires CPU only; set CUDA_VISIBLE_DEVICES=-1")
    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "8")))
    if a.smoke:
        tmp = Path(tempfile.mkdtemp(prefix="vc_rt_smoke_"))
        FV.LEDGER = tmp / "ledger.jsonl"
        OUT, art_path = tmp / "result.json", tmp / "head.npz"
        splits, fseed, nf, epochs = {"train": (999990, 12), "sel": (999991, 8)}, 999996, 8, 2
        print("SMOKE: throwaway seeds/ledger/out ->", tmp)
    elif fseed not in (790, 791):
        raise SystemExit("REFUSE: only seed 790 (or 791 under the registered crash rule) is allowed")
    if FV.ledger_has(fseed):
        raise SystemExit(f"REFUSE: sealed seed {fseed} already in {FV.LEDGER}")
    bridge_sha = guard_bridge_unmodified()

    t0 = time.time()
    data = {k: R.collect(n, seed=s) for k, (s, n) in splits.items()}
    idx = {k: decisions(v) for k, v in data.items()}
    tr, se = idx["train"], idx["sel"]
    print(f"train {len(tr['y'])} / sel {len(se['y'])} decisions, prevalence {tr['y'].mean():.3f}/{se['y'].mean():.3f} "
          f"({round(time.time() - t0)}s)", flush=True)

    # --- everything below until the open uses seeds 200/201 only ---
    flat = lambda d, i: np.concatenate([np.stack([d["frames"][i["e"], i["t"] - 1], d["frames"][i["e"], i["t"]]], 1)
                                        .reshape(len(i["e"]), -1), i["a10"]], 1)
    probe = LogisticRegression(max_iter=400, C=0.5, class_weight="balanced").fit(flat(data["train"], tr), tr["y"])
    act_only = LogisticRegression(max_iter=1000, C=1.0, class_weight="balanced").fit(tr["a10"], tr["y"])
    state_ref = HistGradientBoostingClassifier(random_state=0).fit(state_features(data["train"], tr), tr["y"])
    print(f"baselines fitted ({round(time.time() - t0)}s)", flush=True)

    from huggingface_hub import hf_hub_download
    wsha = sha256_file(hf_hub_download("facebook/dinov2-small", "model.safetensors"))
    enc = PE.load_dino(True).to(DEV)
    feats = {k: extract(enc, v["frames"]) for k, v in data.items()}
    print(f"DINOv2 features extracted on CPU ({round(time.time() - t0)}s)", flush=True)

    cands = {}
    for pool in (4, 8):
        h, sel_ap = train_head(feats["train"][pool], feats["sel"][pool], tr, se, tr["a10"], se["a10"], pool, epochs)
        cands[pool] = (h, sel_ap)
        print(f"  dinov2_runtime pool {pool}: selection AUC-PR {sel_ap:.3f}", flush=True)
    pool = max(cands, key=lambda p: cands[p][1])
    head_rt, sel_ap_rt = cands[pool]
    head_l5, sel_ap_l5 = train_head(feats["train"][pool], feats["sel"][pool], tr, se,
                                    onehot5(tr["a5"]), onehot5(se["a5"]), pool, epochs)
    head_v1, thr_v1 = v1_head()

    def all_scores(split_data, i, Fx):
        return {"dinov2_runtime": score_head(head_rt, Fx[pool], i, i["a10"]),
                "dinov2_lossy5": score_head(head_l5, Fx[pool], i, onehot5(i["a5"])),
                "pixel_probe_runtime": probe.predict_proba(flat(split_data, i))[:, 1],
                "action_only": act_only.predict_proba(i["a10"])[:, 1],
                "v1_zero_shot": score_head(head_v1, Fx[4], i, onehot5(i["a5"])),
                "state_reference": state_ref.predict_proba(state_features(split_data, i))[:, 1]}

    sel_scores = all_scores(data["sel"], se, feats["sel"])
    thr = {m: {"p05": FV.calibrate(s, se["y"], PRIMARY_FPR), "p10": FV.calibrate(s, se["y"], BUDGET)}
           for m, s in sel_scores.items()}
    thr["v1_zero_shot"] = {"p05": float(thr_v1), "p10": None, "note": "v1's own registered fpr_0.05 threshold"}
    print(f"frozen before open: pool {pool}; selection AUC-PR runtime {sel_ap_rt:.3f} lossy5 {sel_ap_l5:.3f}", flush=True)
    del feats

    # --- persist the frozen candidate BEFORE the open ---
    platt = LogisticRegression(C=1e6).fit(sel_scores["dinov2_runtime"].reshape(-1, 1), se["y"])
    arrays = {f"head.{k}": v.detach().cpu().numpy().astype(np.float32) for k, v in head_rt.state_dict().items()}
    meta = {"schema": "FERRUM_VISION_CAUTION_V2", "authority": AUTHORITY,
            "protocol": [PROTOCOL.name],
            "encoder": {"name": "facebook/dinov2-small", "weights_sha256": wsha,
                        "source": "tools/vision_caution/dinov2_small.py (same module names as scripts/vision_wm_pretrained_encoders.py:DinoV2Small)",
                        "input": "grey frame replicated to RGB, bilinear to 224x224, ImageNet mean/std",
                        "pooling": f"patch-token map adaptive-avg-pooled to {pool}x{pool}, fp16"},
            "pool": pool, "frame_size": SIZE, "frame_stack": K, "horizon_steps": H,
            "head": f"2-frame stack (2x384,{pool},{pool}) -> Conv1x1(64)+GELU -> concat GELU(Linear(10->32)(runtime action)) "
                    f"-> Linear({64 * pool * pool + 32}->128)+GELU -> Linear(128->1) logit",
            "action_space": {"kind": "runtime PhysicalAction", "names": list(simulator.ACTION_NAMES),
                             "feature_size": simulator.ACTION_FEATURE_SIZE,
                             "encoding": "one-hot over the 7 kinds + the 3 raw features in [-1, 1] (identity mapping)"},
            "scene": "runtime-scene proxy: pybullet-direct-box-robot-obstacle-v1 filmed overhead (simulation)",
            "hazards": "camera-visible terms of is_dangerous: proximity (clearance < 0.16), geofence exit, contact",
            "thresholds_logit": {"fpr_0.05": thr["dinov2_runtime"]["p05"], "fpr_0.10": thr["dinov2_runtime"]["p10"]},
            "platt": {"coef": float(platt.coef_[0, 0]), "intercept": float(platt.intercept_[0]),
                      "fitted_on": "selection seed 201 logits, before the sealed open"},
            "selection_auc_pr": sel_ap_rt, "train_seed": splits["train"][0], "selection_seed": splits["sel"][0],
            "qualification": "decided by docs/research/vision_caution_runtime_proxy_result_v1.json and the integration protocol; never live use"}
    art_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(art_path, metadata=json.dumps(meta, sort_keys=True), **arrays)
    art_sha = sha256_file(art_path)
    print(f"persisted frozen head -> {art_path} sha256 {art_sha[:16]}...", flush=True)

    # --- SINGLE OPEN ---
    FV.record_final(fseed, "vision-caution runtime-scene proxy v1: identity runtime-action head (CPU)")
    dfi = R.collect(nf, seed=fseed)
    fi = decisions(dfi)
    y = fi["y"]
    final_scores = all_scores(dfi, fi, extract(enc, dfi["frames"], pools=tuple(sorted({4, pool}))))

    res = {}
    for m, s in final_scores.items():
        res[m] = TR.auc(y, s)
        for arm in ("p05", "p10"):
            if thr[m][arm] is not None:
                r, f = FV.recall_fpr(s, y, thr[m][arm])
                res[m][arm] = {"recall": r, "realized_fpr": f}
    hits = {m: final_scores[m] > thr[m]["p05"] for m in final_scores}
    n_ep = len(dfi["kinds"])
    boot = {f"dinov2_runtime_minus_{b}": cluster_boot(hits["dinov2_runtime"], hits[b], y, fi["e"], n_ep)
            for b in ("pixel_probe_runtime", "action_only", "dinov2_lossy5")}
    c = res["dinov2_runtime"]
    beats = lambda b: (c["auc_pr"] > res[b]["auc_pr"] and c["p05"]["recall"] > res[b]["p05"]["recall"]
                       and (boot[f"dinov2_runtime_minus_{b}"]["ci95"][0] or 0) > 0)
    g1 = beats("pixel_probe_runtime") and beats("action_only")
    g2 = c["p05"]["realized_fpr"] <= BUDGET
    s1 = beats("dinov2_lossy5")
    gates = {"G1_capability": bool(g1), "G2_budget": bool(g2), "primary_success": bool(g1 and g2),
             "S1_identity_mapping_beats_lossy5": bool(s1)}
    hit = hits["dinov2_runtime"]
    by_type = {k: {"positives": int(v.sum()), "recall": float(hit[v == 1].mean()) if v.sum() else None}
               for k, v in fi["types"].items()}
    by_kind = {simulator.ACTION_NAMES[k]: {"decisions": int((fi["kind"] == k).sum()),
                                           "positives": int(((fi["kind"] == k) & (y == 1)).sum()),
                                           "recall": float(hit[(fi["kind"] == k) & (y == 1)].mean())
                                           if ((fi["kind"] == k) & (y == 1)).any() else None,
                                           "benign_alarm_rate": float(hit[(fi["kind"] == k) & (y == 0)].mean())
                                           if ((fi["kind"] == k) & (y == 0)).any() else None}
               for k in range(simulator.ACTION_COUNT)}

    print(f"\nFINAL sealed seed {fseed}: {len(y)} decisions in {n_ep} episodes, prevalence {y.mean():.3f}")
    for m, r in res.items():
        p10 = f" | recall@10% {r['p10']['recall']:.3f} (realized {r['p10']['realized_fpr']:.3f})" if "p10" in r else ""
        print(f"  {m:20s} AUC-PR {r['auc_pr']:.3f} ROC {r['auc_roc']:.3f} | recall@5% {r['p05']['recall']:.3f} "
              f"(realized {r['p05']['realized_fpr']:.3f}){p10}")
    for k, b in boot.items():
        print(f"  {k}: {b['recall_difference']} CI95 {b['ci95']}")
    print(f"  by hazard type: {json.dumps(by_type)}")
    print(f"  G1 {'PASS' if g1 else 'FAIL'}  G2 {'PASS' if g2 else 'FAIL'}  => primary {'PASS' if g1 and g2 else 'FAIL'}"
          f"  | S1 mapping {'PASS' if s1 else 'FAIL'}")
    rel = lambda p: str(Path(p).relative_to(ROOT)).replace("\\", "/") if not a.smoke else str(p)
    doc = {"schema_version": "vision-caution-runtime-proxy-result-v1", "protocol": PROTOCOL.name,
           "status": "registered final, opened once; runtime-scene PROXY (simulation, not real footage); "
                     "branch work (not main); advisory only",
           "final_seed": fseed, "episodes": n_ep, "decisions": int(len(y)), "prevalence": float(y.mean()),
           "compute": "CPU only", "selected_pool": pool,
           "selection_auc_pr": {"dinov2_runtime_pool4": cands[4][1], "dinov2_runtime_pool8": cands[8][1],
                                "dinov2_lossy5": sel_ap_l5},
           "selected_artifact": rel(art_path), "selected_artifact_sha256": art_sha,
           "dinov2_weights_sha256": wsha, "bridge_py_sha256_unmodified": bridge_sha,
           "code_sha256": {p: sha256_file(ROOT / p) for p in ("scripts/vision_runtime_domain_render.py",
                                                               "scripts/vision_runtime_proxy_final.py",
                                                               "scripts/vision_wm_pretrained_encoders.py")},
           "thresholds": thr, "results": res, "bootstrap": boot, "gates": gates,
           "dinov2_runtime_recall_by_hazard_type": by_type, "dinov2_runtime_by_action_kind": by_kind}
    OUT.write_text(json.dumps(doc, indent=1, default=float) + "\n", encoding="utf-8")
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
