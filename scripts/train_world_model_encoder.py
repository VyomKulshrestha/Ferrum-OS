#!/usr/bin/env python3
"""
Trains the world model's Layer 3.2 learned encoder: an autoencoder that
fills the state embedding's currently-unused slots (51-127, 77 floats -
everything past the 7 hand-crafted scalars and the 41-wide one-hot last-
action block) with genuinely learned latent features, reconstructed from
the same raw scalars the hand-crafted encoder already computes.

Deliberately does NOT touch slots 0-6 (proc_count, heap_fraction,
fs_file_count, disk_usage_fraction, screen_hash, last_error,
ticks_since_action) or the one-hot action block at 10-50 - those stay
exactly as cognitive/world_model/encoder.rs already computes them,
because safety.rs's risk rules and the already-verified Layer 4.2
transition model both read those exact indices. Growing the embedding to
a fresh 256-dim space (model.md's literal Layer 3.2 spec) would need an
entirely new data-collection pass to get real (before, after) pairs in
that space; reusing the 77 dims already sitting unused inside the
existing 128-float embedding avoids that cost while still being a
genuinely learned (not hand-coded) representation for the majority of
what the transition model gets to see.

Pure numpy, no PyTorch/candle - same pragmatic scoping as
scripts/convert_model_v2.py and scripts/train_world_model.py.

After training the encoder, this script *also* re-encodes the existing
dataset (target/world_model_dataset.jsonl) with the trained encoder -
copying slots 0-50 verbatim from the original hand-crafted embedding,
filling 51-127 with the encoder's output - and writes the result to
target/world_model_dataset_encoded.jsonl for
scripts/train_world_model.py to retrain the transition model on.

Usage:
    python scripts/train_world_model_encoder.py [--dataset PATH] [--out PATH] [--encoded-dataset PATH]
"""
import argparse
import json
import struct
import sys

import numpy as np

EMBEDDING_SIZE = 128
NUM_TOOLS = 41
RAW_SCALARS = 7         # slots 0-6: proc_count, heap_fraction, fs_file_count,
                        # disk_usage, screen_hash, last_error, ticks_since_action
RAW_INPUT_SIZE = RAW_SCALARS + NUM_TOOLS  # + one-hot action at slots 10-50 = 48
LATENT_START = 51       # first currently-unused slot
LATENT_SIZE = EMBEDDING_SIZE - LATENT_START  # 77


def load_dataset(path):
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def extract_raw(embedding):
    """Pulls the 48 raw-feature dims (7 scalars + 41-wide one-hot action)
    out of a full 128-float embedding - exactly what encoder.rs already
    computes into those fixed slots, so no new observation data is needed."""
    e = np.asarray(embedding, dtype=np.float32)
    raw = np.zeros(RAW_INPUT_SIZE, dtype=np.float32)
    raw[:RAW_SCALARS] = e[:RAW_SCALARS]
    raw[RAW_SCALARS:] = e[10:10 + NUM_TOOLS]
    return raw


def build_raw_matrix(rows):
    raws = []
    for row in rows:
        raws.append(extract_raw(row["before"]))
        raws.append(extract_raw(row["after"]))
    return np.stack(raws)


def train_autoencoder(X, hidden_size, latent_size, epochs, lr, seed=0):
    rng = np.random.default_rng(seed)
    n_in = X.shape[1]

    enc_w1 = rng.normal(0, 1.0 / np.sqrt(n_in), size=(n_in, hidden_size)).astype(np.float32)
    enc_b1 = np.zeros(hidden_size, dtype=np.float32)
    enc_w2 = rng.normal(0, 1.0 / np.sqrt(hidden_size), size=(hidden_size, latent_size)).astype(np.float32)
    enc_b2 = np.zeros(latent_size, dtype=np.float32)

    dec_w1 = rng.normal(0, 1.0 / np.sqrt(latent_size), size=(latent_size, hidden_size)).astype(np.float32)
    dec_b1 = np.zeros(hidden_size, dtype=np.float32)
    dec_w2 = rng.normal(0, 1.0 / np.sqrt(hidden_size), size=(hidden_size, n_in)).astype(np.float32)
    dec_b2 = np.zeros(n_in, dtype=np.float32)

    n = X.shape[0]
    for epoch in range(epochs):
        h1_pre = X @ enc_w1 + enc_b1
        h1 = np.maximum(h1_pre, 0.0)
        latent = h1 @ enc_w2 + enc_b2  # no activation on the latent code itself

        h2_pre = latent @ dec_w1 + dec_b1
        h2 = np.maximum(h2_pre, 0.0)
        recon = h2 @ dec_w2 + dec_b2

        err = recon - X
        loss = float(np.mean(err ** 2))

        d_recon = (2.0 / n) * err
        grad_dec_w2 = h2.T @ d_recon
        grad_dec_b2 = d_recon.sum(axis=0)
        d_h2 = d_recon @ dec_w2.T
        d_h2[h2_pre <= 0] = 0.0
        grad_dec_w1 = latent.T @ d_h2
        grad_dec_b1 = d_h2.sum(axis=0)

        d_latent = d_h2 @ dec_w1.T
        grad_enc_w2 = h1.T @ d_latent
        grad_enc_b2 = d_latent.sum(axis=0)
        d_h1 = d_latent @ enc_w2.T
        d_h1[h1_pre <= 0] = 0.0
        grad_enc_w1 = X.T @ d_h1
        grad_enc_b1 = d_h1.sum(axis=0)

        for w, g in [
            (dec_w2, grad_dec_w2), (dec_b2, grad_dec_b2),
            (dec_w1, grad_dec_w1), (dec_b1, grad_dec_b1),
            (enc_w2, grad_enc_w2), (enc_b2, grad_enc_b2),
            (enc_w1, grad_enc_w1), (enc_b1, grad_enc_b1),
        ]:
            w -= lr * g

        if epoch % max(1, epochs // 10) == 0 or epoch == epochs - 1:
            print(f"  epoch {epoch:5d}  reconstruction MSE={loss:.6f}")

    return (enc_w1, enc_b1, enc_w2, enc_b2), (dec_w1, dec_b1, dec_w2, dec_b2)


def encode(X, enc_w1, enc_b1, enc_w2, enc_b2):
    h1 = np.maximum(X @ enc_w1 + enc_b1, 0.0)
    return h1 @ enc_w2 + enc_b2


def write_encoder_weights(path, w1, b1, w2, b2):
    """Same flat-binary shape as train_world_model.py's write_weights -
    cognitive/world_model/encoder_learned.rs parses it the same way
    cognitive/world_model/learned.rs parses the transition weights."""
    input_size, hidden_size = w1.shape
    output_size = w2.shape[1]
    with open(path, "wb") as f:
        f.write(struct.pack("<III", input_size, hidden_size, output_size))
        f.write(w1.astype("<f4").tobytes())
        f.write(b1.astype("<f4").tobytes())
        f.write(w2.astype("<f4").tobytes())
        f.write(b2.astype("<f4").tobytes())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="target/world_model_dataset.jsonl")
    parser.add_argument("--out", default="target/world_model_encoder.bin")
    parser.add_argument("--encoded-dataset", default="target/world_model_dataset_encoded.jsonl")
    parser.add_argument("--hidden", type=int, default=64)
    parser.add_argument("--epochs", type=int, default=3000)
    parser.add_argument("--lr", type=float, default=0.05)
    parser.add_argument("--holdout", type=float, default=0.15)
    args = parser.parse_args()

    rows = load_dataset(args.dataset)
    if len(rows) < 20:
        print(f"error: only {len(rows)} examples in {args.dataset}", file=sys.stderr)
        sys.exit(1)
    print(f"loaded {len(rows)} examples ({len(rows) * 2} before/after snapshots) from {args.dataset}")

    X = build_raw_matrix(rows)

    rng = np.random.default_rng(42)
    idx = rng.permutation(len(X))
    n_holdout = max(1, int(len(X) * args.holdout))
    holdout_idx, train_idx = idx[:n_holdout], idx[n_holdout:]
    X_train, X_holdout = X[train_idx], X[holdout_idx]

    print(f"train/holdout split: {len(train_idx)}/{len(holdout_idx)}")
    zero_mse = float(np.mean(X_holdout ** 2))
    print(f"trivial (always predict zero) holdout MSE: {zero_mse:.6f}")

    print(f"training autoencoder (input={RAW_INPUT_SIZE}, hidden={args.hidden}, latent={LATENT_SIZE}, epochs={args.epochs})...")
    (enc_w1, enc_b1, enc_w2, enc_b2), _decoder = train_autoencoder(
        X_train, args.hidden, LATENT_SIZE, args.epochs, args.lr
    )

    latent_holdout = encode(X_holdout, enc_w1, enc_b1, enc_w2, enc_b2)
    print(f"holdout latent code stats: mean={latent_holdout.mean():.4f} std={latent_holdout.std():.4f}")
    if latent_holdout.std() < 1e-4:
        print("FAIL: learned latent code collapsed to a near-constant output", file=sys.stderr)
        sys.exit(1)
    print("PASS: learned encoder produces a non-degenerate latent code")

    write_encoder_weights(args.out, enc_w1, enc_b1, enc_w2, enc_b2)
    print(f"wrote encoder weights to {args.out}")

    # Re-encode the full dataset for scripts/train_world_model.py to
    # retrain the transition model on - slots 0-50 copied verbatim,
    # 51-127 filled with this encoder's output.
    encoded_rows = []
    for row in rows:
        before_raw = extract_raw(row["before"]).reshape(1, -1)
        after_raw = extract_raw(row["after"]).reshape(1, -1)
        before_latent = encode(before_raw, enc_w1, enc_b1, enc_w2, enc_b2)[0]
        after_latent = encode(after_raw, enc_w1, enc_b1, enc_w2, enc_b2)[0]

        before = list(row["before"])
        after = list(row["after"])
        before[LATENT_START:EMBEDDING_SIZE] = before_latent.tolist()
        after[LATENT_START:EMBEDDING_SIZE] = after_latent.tolist()

        encoded_rows.append({
            "tick": row["tick"], "action": row["action"], "reward": row["reward"],
            "before": before, "after": after,
        })

    with open(args.encoded_dataset, "w") as f:
        f.write("\n".join(json.dumps(r) for r in encoded_rows) + "\n")
    print(f"wrote {len(encoded_rows)} re-encoded examples to {args.encoded_dataset}")


if __name__ == "__main__":
    main()
