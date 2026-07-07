#!/usr/bin/env python3
"""
Convert a llama2.c legacy (v0) fp32 checkpoint into the v2 int8-quantized
format userland/heliox-daemon/src/cognitive/inference.rs actually parses.

Pure numpy, no PyTorch - the legacy .bin format is just a flat sequence of
raw float32 arrays after a 7 x int32 header, so no model-loading framework
is needed to read it.

Legacy v0 layout (matches llama2.c's run.c reference implementation and
export.py's `legacy_export`):
  header: 7 x int32 = dim, hidden_dim, n_layers, n_heads, n_kv_heads,
          vocab_size (negative => classifier is NOT shared with the
          embedding table), seq_len
  then float32 arrays in order:
    token_embedding_table   [vocab_size, dim]
    rms_att_weight          [n_layers, dim]
    wq                      [n_layers, dim, n_heads*head_size]
    wk                      [n_layers, dim, n_kv_heads*head_size]
    wv                      [n_layers, dim, n_kv_heads*head_size]
    wo                      [n_layers, n_heads*head_size, dim]
    rms_ffn_weight          [n_layers, dim]
    w1                      [n_layers, dim, hidden_dim]
    w2                      [n_layers, hidden_dim, dim]
    w3                      [n_layers, dim, hidden_dim]
    rms_final_weight        [dim]
    (skip) freq_cis_real/imag - legacy RoPE tables, superseded by
    on-the-fly RoPE in this engine, not read on this side either
    wcls (only if not shared)  [vocab_size, dim]

v2 target layout (matches inference.rs's real parser exactly):
  256-byte header:
    u32 magic = 0x616b3432 ("ak42")
    i32 version = 2
    i32 dim, hidden_dim, n_layers, n_heads, n_kv_heads, vocab_size, seq_len
    u8  shared_classifier
    i32 group_size
    (padded with zeros to 256 bytes)
  then, unquantized:
    rms_att_weight [n_layers, dim] f32
    rms_ffn_weight [n_layers, dim] f32
    rms_final_weight [dim] f32
  then, quantized (each tensor as: i8 q[...], f32 scale[.../group_size]):
    q_tokens        [vocab_size, dim]
    wq (per layer)  [dim, dim]           (n_heads == n_kv_heads for stories15M)
    wk (per layer)  [dim, kv_dim]
    wv (per layer)  [dim, kv_dim]
    wo (per layer)  [dim, dim]
    w1 (per layer)  [dim, hidden_dim]
    w2 (per layer)  [hidden_dim, dim]
    w3 (per layer)  [dim, hidden_dim]
    wcls            [dim, vocab_size]   (only if not shared_classifier)
"""
import struct
import sys
import numpy as np


def quantize_q80(w: np.ndarray, group_size: int):
    """Symmetric per-group int8 quantization, matching llama2.c export.py's
    `quantize_q80`: each contiguous run of `group_size` fp32 values shares
    one fp32 scale = max(abs(group)) / 127."""
    assert w.size % group_size == 0, f"tensor size {w.size} not divisible by group_size {group_size}"
    w = w.reshape(-1, group_size)
    scale = np.abs(w).max(axis=1) / 127.0
    scale_safe = np.where(scale == 0, 1.0, scale)
    q = np.round(w / scale_safe[:, None]).astype(np.int8)
    return q.reshape(-1), scale.astype(np.float32)


def main():
    if len(sys.argv) != 4:
        print("usage: convert_v2.py <legacy.bin> <out_v2.bin> <group_size>")
        sys.exit(1)
    src_path, dst_path, gs = sys.argv[1], sys.argv[2], int(sys.argv[3])

    with open(src_path, "rb") as f:
        header = f.read(7 * 4)
        dim, hidden_dim, n_layers, n_heads, n_kv_heads, vocab_size_raw, seq_len = struct.unpack("<7i", header)
        shared_classifier = 1 if vocab_size_raw > 0 else 0
        vocab_size = abs(vocab_size_raw)
        head_size = dim // n_heads
        kv_dim = (dim * n_kv_heads) // n_heads

        print(f"legacy header: dim={dim} hidden_dim={hidden_dim} n_layers={n_layers} "
              f"n_heads={n_heads} n_kv_heads={n_kv_heads} vocab_size={vocab_size} "
              f"seq_len={seq_len} shared_classifier={shared_classifier}")

        # The inference engine quantizes activation vectors of length `dim`
        # and `hidden_dim` at runtime; if `gs` doesn't divide both evenly,
        # its integer-division group count silently drops the last partial
        # group on every matmul - no error, no size mismatch, just corrupted
        # output (this shipped once and produced "<unk><unk>" instead of
        # real text - see REPORT.md's Phase D4 section).
        if dim % gs != 0 or hidden_dim % gs != 0:
            print(f"error: group_size={gs} does not evenly divide dim={dim} "
                  f"and/or hidden_dim={hidden_dim} - this would silently "
                  f"corrupt quantization, not just misalign it.")
            import math
            print(f"gcd(dim, hidden_dim) = {math.gcd(dim, hidden_dim)} - "
                  f"pick a group_size that divides this.")
            sys.exit(1)

        def read_f32(n):
            buf = f.read(n * 4)
            assert len(buf) == n * 4, f"unexpected EOF reading {n} floats"
            return np.frombuffer(buf, dtype="<f4").astype(np.float32)

        token_embedding_table = read_f32(vocab_size * dim)
        rms_att_weight = read_f32(n_layers * dim)
        wq = read_f32(n_layers * dim * (n_heads * head_size))
        wk = read_f32(n_layers * dim * (n_kv_heads * head_size))
        wv = read_f32(n_layers * dim * (n_kv_heads * head_size))
        wo = read_f32(n_layers * (n_heads * head_size) * dim)
        rms_ffn_weight = read_f32(n_layers * dim)
        w1 = read_f32(n_layers * dim * hidden_dim)
        w2 = read_f32(n_layers * hidden_dim * dim)
        w3 = read_f32(n_layers * dim * hidden_dim)
        rms_final_weight = read_f32(dim)
        # Skip legacy RoPE freq_cis tables - this engine computes RoPE on
        # the fly and never reads them, matching export.py's own handling.
        f.read(seq_len * head_size // 2 * 4)
        f.read(seq_len * head_size // 2 * 4)
        wcls = None if shared_classifier else read_f32(vocab_size * dim)

    with open(dst_path, "wb") as out:
        header = struct.pack(
            "<IiiiiiiiiBi",
            0x616B3432, 2, dim, hidden_dim, n_layers, n_heads, n_kv_heads,
            vocab_size, seq_len, shared_classifier, gs,
        )
        header = header + b"\x00" * (256 - len(header))
        out.write(header)

        out.write(rms_att_weight.astype("<f4").tobytes())
        out.write(rms_ffn_weight.astype("<f4").tobytes())
        out.write(rms_final_weight.astype("<f4").tobytes())

        def write_quantized(w, label):
            q, s = quantize_q80(w, gs)
            out.write(q.tobytes())
            out.write(s.astype("<f4").tobytes())
            print(f"  wrote {label}: {w.size} values, {w.size // gs} groups")

        write_quantized(token_embedding_table, "q_tokens")

        per_layer = [
            (wq, dim * (n_heads * head_size), "wq"),
            (wk, dim * (n_kv_heads * head_size), "wk"),
            (wv, dim * (n_kv_heads * head_size), "wv"),
            (wo, (n_heads * head_size) * dim, "wo"),
            (w1, dim * hidden_dim, "w1"),
            (w2, hidden_dim * dim, "w2"),
            (w3, dim * hidden_dim, "w3"),
        ]
        for flat, stride, label in per_layer:
            for layer in range(n_layers):
                chunk = flat[layer * stride:(layer + 1) * stride]
                write_quantized(chunk, f"{label}[{layer}]")

        if wcls is not None:
            write_quantized(wcls, "wcls")

    import os
    print(f"done: {dst_path} ({os.path.getsize(dst_path)} bytes)")


if __name__ == "__main__":
    main()
