#!/usr/bin/env python3
"""Option (b): do pretrained visual encoders help the vision caution model? Branch work, not main.

EXPLORATORY dev comparison on the HARD (occluded) pybullet scene. Splits by seed:
train 0 (600 ep), selection 1 (200 ep), dev-eval 2 (200 ep). Seed 2 is a fresh
DEV seed, not a reserved sealed seed, so this is exploratory evidence, not a
registered final.

Caution = P(hazard within 3 steps) from a 2-frame stack + action. Compared:
  pixel_linear_probe      logistic regression on raw pixels (baseline)
  scratch_cnn             the registered VWM trained from scratch (vision_wm_final_v2.train_vwm)
  mobilenet_v2_pretrained frozen ImageNet MobileNetV2 (torchvision, locally cached) + head
  mobilenet_v2_random     same architecture, random init (control: is it pretraining or architecture?)
  dinov2_small_pretrained frozen DINOv2 ViT-S/14 (official facebook/dinov2-small weights) + head
  dinov2_small_random     same ViT, random init (control)

DINOv2 runs through a minimal pure-torch ViT that mirrors the HF Dinov2Model module
names, loaded with load_state_dict(strict=True). transformers itself segfaults on
import in this environment (transformers 5.2 + torch 2.6), so it is not used.

Heads are identical for every frozen encoder: per-frame 4x4-pooled feature maps,
2 frames stacked -> 1x1 conv -> MLP with the action -> caution logit. Calibrated on
the selection split's benign steps at FPR 0.05 (margin) and 0.10.

Usage: python scripts/vision_wm_pretrained_encoders.py [--smoke]
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score

import vision_wm_final_v2 as FV
import vision_wm_pybullet_data as D
import vision_wm_train as TR

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/research/vision_world_model_pretrained_encoders_v1.json"
K, H, SIZE, STEPS = 2, 3, 48, 20
NA = len(D.ACTIONS)
DEV = torch.device("cuda" if torch.cuda.is_available() else "cpu")
MEAN = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
STD = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)


# --- minimal DINOv2 ViT-S/14 mirroring HF Dinov2Model parameter names ------------
class _NS(nn.Module):
    pass


class _Layer(nn.Module):
    def __init__(self, d=384, heads=6, mlp=1536):
        super().__init__()
        self.heads = heads
        self.norm1 = nn.LayerNorm(d, eps=1e-6)
        self.attention = _NS(); self.attention.attention = _NS(); self.attention.output = _NS()
        self.attention.attention.query = nn.Linear(d, d)
        self.attention.attention.key = nn.Linear(d, d)
        self.attention.attention.value = nn.Linear(d, d)
        self.attention.output.dense = nn.Linear(d, d)
        self.layer_scale1 = _NS(); self.layer_scale1.lambda1 = nn.Parameter(torch.ones(d))
        self.norm2 = nn.LayerNorm(d, eps=1e-6)
        self.mlp = _NS(); self.mlp.fc1 = nn.Linear(d, mlp); self.mlp.fc2 = nn.Linear(mlp, d)
        self.layer_scale2 = _NS(); self.layer_scale2.lambda1 = nn.Parameter(torch.ones(d))

    def forward(self, x):
        B, N, d = x.shape
        a = self.attention.attention
        h = self.norm1(x)
        sp = lambda t: t.view(B, N, self.heads, d // self.heads).transpose(1, 2)
        o = F.scaled_dot_product_attention(sp(a.query(h)), sp(a.key(h)), sp(a.value(h)))
        o = self.attention.output.dense(o.transpose(1, 2).reshape(B, N, d))
        x = x + self.layer_scale1.lambda1 * o
        m = self.mlp.fc2(F.gelu(self.mlp.fc1(self.norm2(x))))
        return x + self.layer_scale2.lambda1 * m


class DinoV2Small(nn.Module):
    def __init__(self):
        super().__init__()
        d = 384
        self.embeddings = _NS()
        self.embeddings.cls_token = nn.Parameter(torch.zeros(1, 1, d))
        self.embeddings.mask_token = nn.Parameter(torch.zeros(1, d))
        self.embeddings.position_embeddings = nn.Parameter(torch.zeros(1, 1370, d))
        self.embeddings.patch_embeddings = _NS()
        self.embeddings.patch_embeddings.projection = nn.Conv2d(3, d, 14, 14)
        self.encoder = _NS(); self.encoder.layer = nn.ModuleList([_Layer() for _ in range(12)])
        self.layernorm = nn.LayerNorm(d, eps=1e-6)

    def forward(self, x):
        e = self.embeddings
        t = e.patch_embeddings.projection(x)                       # (B, d, h, w)
        B, d, h, w = t.shape
        t = t.flatten(2).transpose(1, 2)
        pos = e.position_embeddings
        pp = pos[:, 1:].reshape(1, 37, 37, d).permute(0, 3, 1, 2)
        pp = F.interpolate(pp, size=(h, w), mode="bicubic", align_corners=False).permute(0, 2, 3, 1).reshape(1, h * w, d)
        x = torch.cat([e.cls_token.expand(B, -1, -1) + pos[:, :1], t + pp], 1)
        for layer in self.encoder.layer:
            x = layer(x)
        x = self.layernorm(x)
        return x[:, 1:].transpose(1, 2).reshape(B, d, h, w)       # patch-token map


def load_dino(pretrained):
    m = DinoV2Small()
    if pretrained:
        from huggingface_hub import hf_hub_download
        from safetensors.torch import load_file
        missing = m.load_state_dict(load_file(hf_hub_download("facebook/dinov2-small", "model.safetensors")), strict=True)
        assert not missing.missing_keys and not missing.unexpected_keys
    else:
        torch.manual_seed(1)
        for mod in m.modules():
            if isinstance(mod, (nn.Linear, nn.Conv2d)):
                nn.init.trunc_normal_(mod.weight, std=0.02); nn.init.zeros_(mod.bias)
        nn.init.trunc_normal_(m.embeddings.position_embeddings, std=0.02)
        nn.init.trunc_normal_(m.embeddings.cls_token, std=0.02)
    return m.eval().to(DEV)


def load_mobilenet(pretrained):
    import torchvision
    torch.manual_seed(1)
    w = torchvision.models.MobileNet_V2_Weights.IMAGENET1K_V1 if pretrained else None
    return torchvision.models.mobilenet_v2(weights=w).features[:-1].eval().to(DEV)   # 320 ch


@torch.no_grad()
def extract(enc, frames, res=224, bs=128):
    """frames (n_ep, T, s, s) in [0,1] -> per-frame 4x4-pooled maps (n_ep, T, C, 4, 4) fp16 on GPU."""
    n, T = frames.shape[:2]
    flat = torch.from_numpy(frames.reshape(n * T, 1, SIZE, SIZE))
    out = []
    for i in range(0, len(flat), bs):
        x = flat[i:i + bs].to(DEV).repeat(1, 3, 1, 1)
        x = F.interpolate(x, size=(res, res), mode="bilinear", align_corners=False)
        x = (x - MEAN.to(DEV)) / STD.to(DEV)
        out.append(F.adaptive_avg_pool2d(enc(x), 4).half())
    f = torch.cat(out)
    return f.view(n, T, *f.shape[1:])


def _natural_images():
    import matplotlib.cbook as cb
    import skimage.data as sd
    from PIL import Image
    imgs = [getattr(sd, n)() for n in ("chelsea", "astronaut", "coffee", "rocket", "cat",
                                       "hubble_deep_field", "immunohistochemistry")]
    imgs.append(np.asarray(Image.open(cb.get_sample_data("grace_hopper.jpg", asfileobj=False)).convert("RGB")))
    return [torch.from_numpy(np.ascontiguousarray(i[..., :3])).permute(2, 0, 1).float() / 255.0 for i in imgs]


@torch.no_grad()
def natural_retrieval_check(enc):
    """Correctness check for the encoder forward pass, independent of the task: top-1
    retrieval of 8 natural photos from 4 augmented views each (crop, grayscale,
    brightness/contrast, flip+crop+grayscale). A working pretrained encoder matches
    views to their source; random weights (colour-statistics features) should not.
    (A PCA-vs-object-mask check on the renders was dropped: on these scenes brightness
    IS the object mask, so random features score higher on it -- confounded.)"""
    g = torch.Generator().manual_seed(0)
    prep = lambda x: (F.interpolate(x[None], size=(224, 224), mode="bilinear", align_corners=False) - MEAN) / STD

    def crop(x, lo=0.55, hi=0.8):
        _, Hh, Ww = x.shape
        s = float(torch.empty(1).uniform_(lo, hi, generator=g)) ** 0.5
        h, w = int(Hh * s), int(Ww * s)
        i = int(torch.randint(0, Hh - h + 1, (1,), generator=g)); j = int(torch.randint(0, Ww - w + 1, (1,), generator=g))
        return x[:, i:i + h, j:j + w]
    gray = lambda x: (0.299 * x[0] + 0.587 * x[1] + 0.114 * x[2]).expand(3, -1, -1)
    augs = [crop, gray, lambda x: ((x - 0.5) * 0.6 + 0.5) * 0.7, lambda x: gray(crop(x.flip(2)))]
    emb = lambda x: F.normalize(enc(prep(x).to(DEV)).mean((2, 3)), dim=1)
    imgs = _natural_images()
    gallery = torch.cat([emb(i) for i in imgs])
    hits = [int((emb(aug(img).clamp(0, 1)) @ gallery.T).argmax()) == k for k, img in enumerate(imgs) for aug in augs]
    return float(np.mean(hits))


def trans_index(n_ep):
    e, t = np.meshgrid(np.arange(n_ep), np.arange(K - 1, STEPS), indexing="ij")
    return e.ravel(), t.ravel()


def labels(actions, hazards):
    e, t = trans_index(len(actions))
    y = np.array([int(hazards[a, b + 1:min(b + 1 + H, STEPS + 1)].any()) for a, b in zip(e, t)], np.int8)
    return e, t, actions[e, t], y


def train_head(Ftr, Fse, idx_tr, idx_se, epochs, seed=0):
    """Identical head for every frozen encoder; early-stopped on selection AUC-PR."""
    torch.manual_seed(seed)
    C = Ftr.shape[2]
    head = nn.ModuleDict({"red": nn.Conv2d(2 * C, 64, 1), "act": nn.Linear(NA, 32),
                          "mlp": nn.Sequential(nn.Linear(64 * 16 + 32, 128), nn.GELU(), nn.Linear(128, 1))}).to(DEV)

    def fwd(Fx, e, t, a):
        st = torch.cat([Fx[e, t - 1], Fx[e, t]], 1).float()
        z = F.gelu(head["red"](st)).flatten(1)
        return head["mlp"](torch.cat([z, F.gelu(head["act"](a))], 1)).squeeze(1)

    def tens(idx):
        e, t, a, y = idx
        return (torch.from_numpy(e).to(DEV), torch.from_numpy(t).to(DEV),
                torch.from_numpy(TR.onehot(a)).to(DEV), y)

    etr, ttr, atr, ytr = tens(idx_tr)
    ese, tse, ase, yse = tens(idx_se)
    yt = torch.from_numpy(ytr.astype(np.float32)).to(DEV)
    pw = torch.tensor([max(1.0, float((ytr == 0).sum()) / max(1.0, float(ytr.sum())))], device=DEV)
    opt = torch.optim.AdamW(head.parameters(), 1e-3, weight_decay=1e-4)
    gen = torch.Generator().manual_seed(seed)
    best, best_ap, pat = None, -1.0, 0
    for ep in range(epochs):
        head.train()
        for b in torch.randperm(len(ytr), generator=gen).split(256):
            b = b.to(DEV)
            opt.zero_grad(set_to_none=True)
            F.binary_cross_entropy_with_logits(fwd(Ftr, etr[b], ttr[b], atr[b]), yt[b], pos_weight=pw).backward()
            opt.step()
        head.eval()
        with torch.no_grad():
            ap = average_precision_score(yse, fwd(Fse, ese, tse, ase).cpu().numpy())
        if ap > best_ap + 1e-5:
            best_ap, best, pat = ap, {k: v.detach().clone() for k, v in head.state_dict().items()}, 0
        else:
            pat += 1
            if pat >= 8:
                break
    head.load_state_dict(best); head.eval()

    def score(Fx, idx):
        e, t, a, _ = tens(idx)
        with torch.no_grad():
            return fwd(Fx, e, t, a).cpu().numpy()
    return score, best_ap


def evaluate(sel_scores, y_sel, dev_scores, y_dev):
    out = TR.auc(y_dev, dev_scores)
    for name, fpr in (("p05", 0.05), ("p10", 0.10)):
        thr = FV.calibrate(sel_scores, y_sel, fpr)
        r, f = FV.recall_fpr(dev_scores, y_dev, thr)
        out[name] = {"target_fpr": fpr, "recall": r, "realized_fpr": f}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args()
    global OUT
    nt, ns, nd, epochs = (600, 200, 200, 60) if not a.smoke else (20, 10, 10, 2)
    if a.smoke:
        import tempfile
        OUT = Path(tempfile.mkdtemp(prefix="vwm_enc_smoke_")) / "result.json"
    t0 = time.time()
    data = {name: D.collect(n, STEPS, SIZE, seed=s, scene="hard")
            for name, n, s in (("train", nt, 0), ("sel", ns, 1), ("dev", nd, 2))}
    idx = {k: labels(v[1], v[2]) for k, v in data.items()}
    print(f"hard scene: train {len(idx['train'][3])} / sel {len(idx['sel'][3])} / dev {len(idx['dev'][3])} "
          f"transitions; prevalence dev {idx['dev'][3].mean():.3f} ({round(time.time()-t0)}s)", flush=True)
    res, sanity = {}, {}

    def stack(split):
        fr, ac, _ = data[split]
        e, t, a_, y = idx[split]
        cur = np.stack([fr[e, t - 1], fr[e, t]], 1)
        return cur, a_, fr[e, t + 1], y

    # baselines: pixel linear probe and from-scratch CNN on identical splits
    ctr, atr_, ntr, ytr = stack("train"); cse, ase_, nse, yse = stack("sel"); cdv, adv, ndv, ydv = stack("dev")
    flat = lambda c, ac: np.concatenate([c.reshape(len(c), -1), TR.onehot(ac)], 1)
    lp = LogisticRegression(max_iter=400, C=0.5, class_weight="balanced").fit(flat(ctr, atr_), ytr)
    res["pixel_linear_probe"] = evaluate(lp.predict_proba(flat(cse, ase_))[:, 1], yse, lp.predict_proba(flat(cdv, adv))[:, 1], ydv)
    print(f"  pixel_linear_probe       dev AUC-PR {res['pixel_linear_probe']['auc_pr']:.3f}", flush=True)
    t1 = time.time()
    scores, best_c, _, params, _ = FV.train_vwm((ctr, atr_, ntr, ytr), (cse, ase_, nse, yse), epochs=epochs)
    res["scratch_cnn"] = {**evaluate(scores(best_c, cse, ase_)[1], yse, scores(best_c, cdv, adv)[1], ydv),
                          "params": params, "seconds": round(time.time() - t1)}
    print(f"  scratch_cnn              dev AUC-PR {res['scratch_cnn']['auc_pr']:.3f} ({res['scratch_cnn']['seconds']}s)", flush=True)

    encoders = (("mobilenet_v2_pretrained", lambda: load_mobilenet(True)), ("mobilenet_v2_random", lambda: load_mobilenet(False)),
                ("dinov2_small_pretrained", lambda: load_dino(True)), ("dinov2_small_random", lambda: load_dino(False)))
    for name, make in encoders:
        t1 = time.time()
        enc = make()
        sanity[name] = {"natural_image_aug_retrieval_top1": natural_retrieval_check(enc)}
        Fx = {k: extract(enc, v[0]) for k, v in data.items()}
        del enc; torch.cuda.empty_cache()
        score, sel_ap = train_head(Fx["train"], Fx["sel"], idx["train"], idx["sel"], epochs)
        res[name] = {**evaluate(score(Fx["sel"], idx["sel"]), yse, score(Fx["dev"], idx["dev"]), ydv),
                     "feature_channels": int(Fx["train"].shape[2]), "seconds": round(time.time() - t1)}
        del Fx; torch.cuda.empty_cache()
        extra = f"  natural-retrieval top1 {sanity[name]['natural_image_aug_retrieval_top1']:.2f}"
        print(f"  {name:24s} dev AUC-PR {res[name]['auc_pr']:.3f} recall@0.05 {res[name]['p05']['recall']:.3f}"
              f" (fpr {res[name]['p05']['realized_fpr']:.3f}) ({res[name]['seconds']}s){extra}", flush=True)

    best = max((k for k in res), key=lambda k: res[k]["auc_pr"])
    doc = {"schema_version": "vision-wm-pretrained-encoders-v1",
           "status": "EXPLORATORY dev comparison (seed 2 dev split, not sealed); branch work, not main; advisory only",
           "scene": "hard", "splits": {"train": [0, nt], "selection": [1, ns], "dev_eval": [2, nd]},
           "dev_prevalence": float(ydv.mean()), "results": res, "sanity": sanity, "best_by_dev_auc_pr": best,
           "note": "DINOv2 weights: official facebook/dinov2-small (HF), run through a strict-loaded pure-torch ViT "
                   "(transformers segfaults on import here). MobileNetV2: torchvision IMAGENET1K_V1, locally cached. "
                   "Random-init controls isolate pretraining from architecture."}
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"\nbest by dev AUC-PR: {best}\nwrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
