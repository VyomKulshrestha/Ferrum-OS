"""Detector development for the real-telemetry study (normal data and synthetic injections only).

Implements the registered pipeline in docs/research/real_telemetry_protocol_v1.json: world model
fit, residual scales, D0/DR/D1 scores, D2/D3 classifiers trained on paired injected windows,
episode-budget calibration and smoothing selection. Writes a frozen bundle per dataset under
target/real-telemetry/frozen/ and appends every step to the development ledger.
"""
from __future__ import annotations

import json
import pickle
import sys
import time
import zlib
from pathlib import Path

import lightgbm as lgb
import numpy as np

import real_telemetry_core as C
import real_telemetry_data as D
import real_telemetry_dev as dev
import real_telemetry_injections as I

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = json.loads((ROOT / "docs/research/real_telemetry_protocol_v1.json").read_text(encoding="utf-8"))
FROZEN = dev.WORK / "frozen"
SEEDS = PROTOCOL["seeds"]
CLF = {k: v for k, v in PROTOCOL["detectors"]["classifier"].items() if k not in ("class_weight", "max_training_rows")}
MAX_ROWS = PROTOCOL["detectors"]["classifier"]["max_training_rows"]
GAP = {"hai": 60, "smd": 10}
BUDGET_PER_DAY = {"hai": 2.0, "smd": 1.0}
STEPS_PER_DAY = {"hai": 86400, "smd": 1440}
GRID = PROTOCOL["detectors"]["smoothing_grid"]
WARMUP = 10


# ------------------------------------------------------------------------------------------
# Scores and features
# ------------------------------------------------------------------------------------------

class Scorer:
    """Everything a detector needs from normal fitting data: world model, scales and bounds."""

    def __init__(self, wm, fit_pairs):
        self.wm = wm
        Z = np.concatenate([z for z, _ in fit_pairs])
        dZ = np.concatenate([np.diff(z, axis=0) for z, _ in fit_pairs])
        self.low, self.high = Z.min(0), Z.max(0)
        self.dsig = dZ.std(0) + 1e-3
        self.dmax = np.abs(dZ).max(0)
        V = [v for _, v in fit_pairs if v is not None]
        if V:
            V = np.concatenate(V)
            self.vlow, self.vhigh = V.min(0), V.max(0)
        self.sig1 = self.sig5 = None

    def residual_scales(self, pairs):
        r1 = np.concatenate([C.residuals(self.wm, z, v, 1)[WARMUP:] for z, v in pairs])
        r5 = np.concatenate([C.residuals(self.wm, z, v, 5)[WARMUP:] for z, v in pairs])
        self.sig1, self.sig5 = r1.std(0) + 1e-3, r5.std(0) + 1e-3

    def raw(self, Z, V):
        """Per-step raw scores (unsmoothed) and the classifier feature matrix."""
        S1 = np.abs(C.residuals(self.wm, Z, V, 1)) / self.sig1
        S5 = np.abs(C.residuals(self.wm, Z, V, 5)) / self.sig5
        S1[:WARMUP] = 0
        S5[:WARMUP] = 0
        dZ = np.vstack([np.zeros((1, Z.shape[1]), Z.dtype), np.diff(Z, axis=0)])
        G = np.abs(dZ) / self.dsig
        top = lambda A, k: -np.sort(-A, 1)[:, :k]
        d0 = top(G, 3).mean(1)
        exceed = np.maximum.reduce([np.maximum(0, Z - self.high), np.maximum(0, self.low - Z),
                                    np.maximum(0, np.abs(dZ) - self.dmax) / self.dsig])
        parts = [S1, C.rolling_mean(S1, 10), S5, G, top(S1, 5), S1.mean(1, keepdims=True), top(S5, 5)]
        if V is not None:
            dV = np.abs(np.vstack([np.zeros((1, V.shape[1]), V.dtype), np.diff(V, axis=0)]))
            vex = np.maximum(0, V - self.vhigh) + np.maximum(0, self.vlow - V)
            exceed = np.concatenate([exceed, vex], 1)
            parts += [dV, vex]
        dr = exceed.max(1)
        d1 = top(S1, 3).mean(1) + top(S5, 3).mean(1)
        return {"D0": d0, "DR": dr, "D1": d1}, np.concatenate(parts, 1).astype(np.float32)


class _BundleUnpickler(pickle.Unpickler):
    """Bundles were written while this module ran as __main__; resolve those names here."""

    def find_class(self, module, name):
        return super().find_class("real_telemetry_detect" if module == "__main__" else module, name)


def load_bundle_bytes(data: bytes):
    import io
    return _BundleUnpickler(io.BytesIO(data)).load()


def smooth(score, w):
    return C.rolling_mean(score.astype(np.float64), int(w))


def episodes(alarm, gap):
    """Alarm episodes (start, end) after merging runs separated by at most `gap` quiet steps."""
    idx = np.flatnonzero(alarm)
    if not len(idx):
        return []
    breaks = np.flatnonzero(np.diff(idx) > gap + 1)
    starts = np.concatenate([[idx[0]], idx[breaks + 1]])
    ends = np.concatenate([idx[breaks], [idx[-1]]]) + 1
    return list(zip(starts, ends))


def calibrate(clean_scores, gap, budget_per_day, steps_per_day):
    """Smallest threshold whose false-episode rate over all clean arrays is within the budget."""
    days = sum(len(s) for s in clean_scores) / steps_per_day
    allowed = budget_per_day * days
    pooled = np.concatenate(clean_scores)
    candidates = np.unique(np.quantile(pooled, 1 - np.logspace(-7, -0.7, 300)))
    best = float(pooled.max()) + 1e-9
    for thr in candidates[::-1]:
        count = sum(len(episodes(s > thr, gap)) for s in clean_scores)
        if count <= allowed:
            best = float(thr)
    return best


# ------------------------------------------------------------------------------------------
# Windows and classifiers
# ------------------------------------------------------------------------------------------

def sample_windows(pairs, length, count, rng):
    lengths = np.array([len(z) for z, _ in pairs])
    usable = np.maximum(lengths - length, 0)
    probs = usable / usable.sum()
    out = []
    for _ in range(count):
        k = int(rng.choice(len(pairs), p=probs))
        s = int(rng.integers(0, usable[k]))
        z, v = pairs[k]
        out.append((z[s:s + length], None if v is None else v[s:s + length]))
    return out


def classifier_rows(scorer, windows, injector, families, injected_fraction, rng, per_window):
    X, Y = [], []
    for z, v in windows:
        if rng.random() < injected_fraction:
            z, v, y = injector.apply(z, v, families[int(rng.integers(len(families)))])
        else:
            y = np.zeros(len(z), np.int8)
        _, F = scorer.raw(z, v)
        F, y = F[WARMUP:], y[WARMUP:]
        pos, neg = np.flatnonzero(y == 1), np.flatnonzero(y == 0)
        pos = rng.choice(pos, min(len(pos), per_window[0]), replace=False) if len(pos) else pos
        neg = rng.choice(neg, min(len(neg), per_window[1]), replace=False)
        keep = np.concatenate([pos, neg])
        X.append(F[keep])
        Y.append(y[keep])
    return np.concatenate(X), np.concatenate(Y)


def train_classifier(X, Y, seed):
    ratio = float((Y == 0).sum()) / max(float((Y == 1).sum()), 1.0)
    model = lgb.LGBMClassifier(random_state=seed, verbose=-1, n_jobs=4, scale_pos_weight=ratio, **CLF)
    return model.fit(X, Y)


def scores_for(scorer, classifiers, Z, V):
    base, F = scorer.raw(Z, V)
    for name, model in classifiers.items():
        base[name] = model.predict_proba(F)[:, 1]
    return base


# ------------------------------------------------------------------------------------------
# Development pipeline per dataset
# ------------------------------------------------------------------------------------------

def make_world_model(config, use_actions):
    if config == "persistence":
        return C.Persistence(dev.HORIZONS, dev.HISTORY)
    gbr = None
    if "gbr" in config:
        gbr = dict(n_estimators=60, num_leaves=31, learning_rate=0.1, min_child_samples=100, subsample=0.8, subsample_freq=1)
    return C.Forecaster(dev.HORIZONS, dev.HISTORY, use_actions=use_actions, gbr=gbr)


def selected_world_model(domain):
    rows = [json.loads(l) for l in dev.LEDGER.read_text(encoding="utf-8").splitlines()]
    rows = [r for r in rows if r.get("kind") == "world_model" and r["domain"] == domain and r["config"] != "persistence"]
    latest = {r["config"]: r for r in rows}
    best = min(latest.values(), key=lambda r: (r["validation_mae"]["H1"] + r["validation_mae"]["H5"]) / 2)
    return best["config"], {k: v["validation_mae"] for k, v in latest.items()}


def develop(domain):
    t0 = time.time()
    rng = np.random.default_rng(SEEDS["windows"])
    config, table = selected_world_model(domain)
    dev.log({"kind": "world_model_selection", "domain": domain, "selected": config, "candidates": table})
    print(domain, "world model", config, flush=True)
    win = PROTOCOL["detectors"]["windows"][domain]
    fam = I.HAI_FAMILIES if domain == "hai" else I.SMD_FAMILIES
    if domain == "hai":
        data = D.hai_train()
        seg = data["segments"]
        xs = C.Scaler().fit(np.concatenate([s.X for s in seg[:3]]))
        us = C.Scaler().fit(np.concatenate([s.U for s in seg[:3]]))
        pack = lambda group: [(xs(s.X), us(s.U)) for s in group]
        groups = {"all": {"fit": pack(seg[:3]), "train": pack(seg[3:5]), "cal": pack(seg[5:])}}
        scalers = {"all": (xs, us)}
    else:
        groups, scalers = {}, {}
        for name, s in D.smd_train().items():
            n = len(s.X)
            a, b = int(n * 0.5), int(n * 0.8)
            xs = C.Scaler().fit(s.X[:a])
            Z = xs(s.X)
            groups[name] = {"fit": [(Z[:a], None)], "train": [(Z[a:b], None)], "cal": [(Z[b:], None)]}
            scalers[name] = (xs, None)
    use_actions = domain == "hai" and "actions" in config
    scorers, injectors = {}, {}
    for g, parts in groups.items():
        wm = make_world_model(config, use_actions).fit(parts["fit"])
        sc = Scorer(wm, parts["fit"])
        sc.residual_scales(parts["train"])
        scorers[g] = sc
        fz = np.concatenate([z for z, _ in parts["fit"]])
        fv = np.concatenate([v for _, v in parts["fit"]]) if domain == "hai" else None
        injectors[g] = (fz, fv)
    print(domain, "world models fitted", round(time.time() - t0), "s", flush=True)

    # Paired classifier training windows: same positions and clean windows for D2 and D3.
    per_window = (250, 170) if domain == "hai" else (60, 40)
    rows = {"D2": ([], []), "D3": ([], [])}
    for g, parts in groups.items():
        count = win["count"] if domain == "hai" else win["count_per_machine"]
        windows = sample_windows(parts["train"], win["length"], count, rng)
        for name, families in (("D2", fam["development"]), ("D3", [I.GENERIC])):
            inj = I.Injector(domain, *injectors[g], seed=SEEDS["injection"] + zlib.crc32(g.encode()) % 1000)
            local = np.random.default_rng(SEEDS["windows"] + zlib.crc32(g.encode()) % 1000)
            X, Y = classifier_rows(scorers[g], windows, inj, families, win["injected_fraction"], local, per_window)
            rows[name][0].append(X)
            rows[name][1].append(Y)
    classifiers = {}
    for name, (Xs, Ys) in rows.items():
        X, Y = np.concatenate(Xs), np.concatenate(Ys)
        if len(X) > MAX_ROWS:
            keep = np.random.default_rng(SEEDS["classifier"]).choice(len(X), MAX_ROWS, replace=False)
            X, Y = X[keep], Y[keep]
        classifiers[name] = train_classifier(X, Y, SEEDS["classifier"])
        dev.log({"kind": "classifier", "domain": domain, "detector": name, "rows": int(len(X)), "positives": int(Y.sum())})
        print(domain, name, "trained on", len(X), "rows", int(Y.sum()), "positive", round(time.time() - t0), "s", flush=True)
    del rows

    # Calibration on clean data and smoothing selection on injected development windows.
    detectors = ["D0", "DR", "D1", "D2", "D3"]
    clean = {d: {g: [] for g in groups} for d in detectors}
    for g, parts in groups.items():
        for z, v in parts["cal"]:
            s = scores_for(scorers[g], {k: classifiers[k] for k in ("D2", "D3")}, z, v)
            for d in detectors:
                clean[d][g].append(s[d][WARMUP:])
    val_rng = np.random.default_rng(SEEDS["injection"] + 7)
    val_windows = {"development": [], "held_out": []}
    n_val = {"development": 200, "held_out": 150} if domain == "hai" else {"development": 8, "held_out": 6}
    for g, parts in groups.items():
        inj = I.Injector(domain, *injectors[g], seed=SEEDS["injection"] + 13 + zlib.crc32(g.encode()) % 1000)
        length = min(win["length"], min(len(z) for z, _ in parts["cal"]) - 1)
        for split in ("development", "held_out"):
            for i, (z, v) in enumerate(sample_windows(parts["cal"], length, n_val[split], val_rng)):
                family = fam[split][i % len(fam[split])]
                zi, vi, y = inj.apply(z, v, family)
                s = scores_for(scorers[g], {k: classifiers[k] for k in ("D2", "D3")}, zi, vi)
                val_windows[split].append((g, family, y, {d: s[d] for d in detectors}))
    choice = {}
    for d in detectors:
        best = None
        for w in GRID[domain]:
            thresholds = {g: calibrate([smooth(s, w) for s in clean[d][g]], GAP[domain], BUDGET_PER_DAY[domain], STEPS_PER_DAY[domain])
                          for g in groups}
            hits = [bool((smooth(s[d], w)[y == 1] > thresholds[g]).any()) for g, _, y, s in val_windows["development"]]
            recall = float(np.mean(hits))
            dev.log({"kind": "smoothing", "domain": domain, "detector": d, "window": w, "validation_recall": recall})
            if best is None or recall > best[0]:
                best = (recall, w, thresholds)
        held = {}
        for g, family, y, s in val_windows["held_out"]:
            held.setdefault(family, []).append(bool((smooth(s[d], best[1])[y == 1] > best[2][g]).any()))
        choice[d] = {"window": best[1], "validation_recall": best[0], "thresholds": best[2],
                     "held_out_recall": {k: float(np.mean(v)) for k, v in held.items()}}
        dev.log({"kind": "selection", "domain": domain, "detector": d, "window": best[1], "validation_recall": best[0],
                 "held_out_recall": choice[d]["held_out_recall"]})
        print(domain, d, "w", best[1], "dev recall", round(best[0], 3), "held-out", {k: round(v, 2) for k, v in choice[d]["held_out_recall"].items()}, flush=True)

    FROZEN.mkdir(parents=True, exist_ok=True)
    bundle = {"domain": domain, "world_model": config, "scorers": scorers, "classifiers": classifiers,
              "scalers": scalers, "choice": choice, "protocol": "real-telemetry-rt1"}
    path = FROZEN / f"{domain}-bundle.pkl"
    path.write_bytes(pickle.dumps(bundle))
    dev.log({"kind": "frozen_bundle", "domain": domain, "path": str(path.relative_to(ROOT)), "seconds": round(time.time() - t0)})
    print(domain, "frozen", path, round(time.time() - t0), "s", flush=True)


if __name__ == "__main__":
    develop(sys.argv[1])
