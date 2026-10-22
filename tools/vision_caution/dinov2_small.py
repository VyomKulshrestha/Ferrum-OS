"""DINOv2 ViT-S/14 forward pass (official facebook/dinov2-small weights), pure torch.

Standalone copy of scripts/vision_wm_pretrained_encoders.DinoV2Small so the advisory
package does not import research scripts. Parameter names mirror the Hugging Face
Dinov2Model so the official safetensors load with strict=True. test_vision_caution.py
checks numerical equivalence with the research implementation.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class _NS(nn.Module):
    pass


class _Layer(nn.Module):
    def __init__(self, d=384, heads=6, mlp=1536):
        super().__init__()
        self.heads = heads
        self.norm1 = nn.LayerNorm(d, eps=1e-6)
        self.attention = _NS()
        self.attention.attention = _NS()
        self.attention.output = _NS()
        self.attention.attention.query = nn.Linear(d, d)
        self.attention.attention.key = nn.Linear(d, d)
        self.attention.attention.value = nn.Linear(d, d)
        self.attention.output.dense = nn.Linear(d, d)
        self.layer_scale1 = _NS()
        self.layer_scale1.lambda1 = nn.Parameter(torch.ones(d))
        self.norm2 = nn.LayerNorm(d, eps=1e-6)
        self.mlp = _NS()
        self.mlp.fc1 = nn.Linear(d, mlp)
        self.mlp.fc2 = nn.Linear(mlp, d)
        self.layer_scale2 = _NS()
        self.layer_scale2.lambda1 = nn.Parameter(torch.ones(d))

    def forward(self, x):
        B, N, d = x.shape
        a = self.attention.attention
        h = self.norm1(x)
        split = lambda t: t.view(B, N, self.heads, d // self.heads).transpose(1, 2)
        o = F.scaled_dot_product_attention(split(a.query(h)), split(a.key(h)), split(a.value(h)))
        o = self.attention.output.dense(o.transpose(1, 2).reshape(B, N, d))
        x = x + self.layer_scale1.lambda1 * o
        return x + self.layer_scale2.lambda1 * self.mlp.fc2(F.gelu(self.mlp.fc1(self.norm2(x))))


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
        self.encoder = _NS()
        self.encoder.layer = nn.ModuleList([_Layer() for _ in range(12)])
        self.layernorm = nn.LayerNorm(d, eps=1e-6)

    def forward(self, x):
        e = self.embeddings
        t = e.patch_embeddings.projection(x)
        B, d, h, w = t.shape
        t = t.flatten(2).transpose(1, 2)
        pos = e.position_embeddings
        pp = pos[:, 1:].reshape(1, 37, 37, d).permute(0, 3, 1, 2)
        pp = F.interpolate(pp, size=(h, w), mode="bicubic", align_corners=False).permute(0, 2, 3, 1).reshape(1, h * w, d)
        x = torch.cat([e.cls_token.expand(B, -1, -1) + pos[:, :1], t + pp], 1)
        for layer in self.encoder.layer:
            x = layer(x)
        x = self.layernorm(x)
        return x[:, 1:].transpose(1, 2).reshape(B, d, h, w)
