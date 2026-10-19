#!/usr/bin/env python3
"""Registered successor rt2: replication on unopened HAI releases 21.03 and 23.05.

Reuses the frozen rt1 implementation (core, injections, Scorer, calibration) unchanged and adds:
loaders for the two releases, time-based partitions (world-model fit 50%, detector training 30%,
calibration 20% of the normal training time), the fixed world-model class selected in rt1 for HAI
(ridge_gbr_actions), and the registered D2c calibration (D2 scores thresholded at D1's calibrated
clean alarm fraction). Usage: develop <release> | final.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import pickle
import sys
import time
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

import real_telemetry_core as C
import real_telemetry_data as D
import real_telemetry_detect as R
import real_telemetry_injections as I

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "target" / "real-telemetry" / "rt2"
LEDGER = WORK / "development_ledger.jsonl"
PROTOCOL = json.loads((ROOT / "docs/research/real_telemetry_protocol_rt2.json").read_text(encoding="utf-8"))
RELEASES = ("hai-21.03", "hai-23.05")
EXTRA_ACTIONS = ["P2_ASD", "P2_MSD", "P2_CO_rpm", "P3_LH", "P3_LL", "P1_PP04D"]
DETECTORS = ["D0", "DR", "D1", "D2", "D3", "D2c"]
SELECTION = ROOT / "docs/research/real_telemetry_selection_rt2.json"
RESULT = ROOT / "docs/research/real_telemetry_result_rt2.json"


def log(entry):
    WORK.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), **entry}) + chr(10))


def is_action(tag: str) -> bool:
    return tag in D.HAI_ACTIONS or tag in EXTRA_ACTIONS or tag.startswith("x10") and tag.endswith(("_SETPOINT_OUT", "_ASSIGN_OUT", "_SUM_OUT"))


def _files(release, split):
    if release == "hai-21.03":
        names = [f"train{i}.csv.gz" for i in range(1, 4)] if split == "train" else [f"test{i}.csv.gz" for i in range(1, 6)]
    else:
        names = [f"hai-train{i}.csv" for i in range(1, 5)] if split == "train" else ["hai-test1.csv", "hai-test2.csv"]
    return [D.RAW / release / n for n in names]


def _read(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, compression="gzip" if path.suffix == ".gz" else None)
    frame.columns = [c.strip() for c in frame.columns]
    return frame


LABELS = ("attack", "attack_P1", "attack_P2", "attack_P3", "Attack", "label")


def columns(release):
    path = D.CACHE / f"{release}-columns.json"
    if not path.exists():
        low = high = tags = None
        for f in _files(release, "train"):
            frame = _read(f)
            tags = tags or [c for c in frame.columns if c not in ("time", "timestamp") + LABELS]
            v = frame[tags].to_numpy(np.float64)
            low = v.min(0) if low is None else np.minimum(low, v.min(0))
            high = v.max(0) if high is None else np.maximum(high, v.max(0))
            if "attack" in frame:
                assert int(frame["attack"].sum()) == 0, f"{f.name} has attack labels"
        varying = [t for t, a, b in zip(tags, low, high) if b - a > 1e-9]
        meta = {"sensors": [t for t in varying if not is_action(t)], "actions": [t for t in varying if is_action(t)],
                "dropped_constant": [t for t in tags if t not in varying]}
        D.CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


def train_segments(release):
    cols = columns(release)
    path = D.CACHE / f"{release}-train.npz"
    if not path.exists():
        arrays = {}
        for i, f in enumerate(_files(release, "train")):
            frame = _read(f)
            arrays[f"X{i}"] = frame[cols["sensors"]].to_numpy(np.float32)
            arrays[f"U{i}"] = frame[cols["actions"]].to_numpy(np.float32)
        np.savez_compressed(path, **arrays)
    data = np.load(path)
    n = len([k for k in data.files if k.startswith("X")])
    return [(data[f"X{i}"], data[f"U{i}"]) for i in range(n)], cols


def test_segments(release, reason):
    D._record_final_access(release, reason)
    cols = columns(release)
    out = []
    for f in _files(release, "test"):
        frame = _read(f)
        if release == "hai-21.03":
            y = frame["attack"].to_numpy(np.int8)
        else:
            label = _read(D.RAW / release / f.name.replace("hai-test", "label-test"))
            # Amendment 2: row order with minute-resolution timestamp equality, the rule registered by the earlier
            # HAI 23.05 evaluator (label-test2.csv repeats minute timestamps on its per-second rows).
            label_minute = pd.to_datetime(label["timestamp"], errors="raise").to_numpy(dtype="datetime64[m]")
            data_minute = pd.to_datetime(frame["timestamp"], errors="raise").to_numpy(dtype="datetime64[m]")
            assert len(label) == len(frame) and np.array_equal(label_minute, data_minute), f"{f.name}: label alignment failed"
            y = label["label"].to_numpy(np.int8)
        out.append((frame[cols["sensors"]].to_numpy(np.float32), frame[cols["actions"]].to_numpy(np.float32), y))
    return out


def split_by_time(segments, cuts=(0.5, 0.8)):
    """Cut the chronologically ordered training files at cumulative-time fractions."""
    total = sum(len(x) for x, _ in segments)
    bounds = [int(total * c) for c in cuts]
    parts, offset = {"fit": [], "train": [], "cal": []}, 0
    for x, u in segments:
        a, b = offset, offset + len(x)
        for name, lo, hi in (("fit", 0, bounds[0]), ("train", bounds[0], bounds[1]), ("cal", bounds[1], total)):
            s, e = max(a, lo), min(b, hi)
            if e - s > 2000:
                parts[name].append((x[s - a:e - a], u[s - a:e - a]))
        offset = b
    return parts


def develop(release):
    t0 = time.time()
    segments, cols = train_segments(release)
    parts = split_by_time(segments)
    xs = C.Scaler().fit(np.concatenate([x for x, _ in parts["fit"]]))
    us = C.Scaler().fit(np.concatenate([u for _, u in parts["fit"]]))
    pack = lambda group: [(xs(x), us(u)) for x, u in group]
    fit, train, cal = pack(parts["fit"]), pack(parts["train"]), pack(parts["cal"])
    log({"kind": "partitions", "release": release, "sensors": len(cols["sensors"]), "actions": len(cols["actions"]),
         "steps": {k: int(sum(len(x) for x, _ in v)) for k, v in parts.items()}})
    print(release, len(cols["sensors"]), "sensors", len(cols["actions"]), "actions",
          {k: sum(len(x) for x, _ in v) for k, v in parts.items()}, flush=True)
    wm = R.make_world_model("ridge_gbr_actions", True).fit(fit)
    scorer = R.Scorer(wm, fit)
    scorer.residual_scales(train)
    print(release, "world model fitted", round(time.time() - t0), "s", flush=True)
    fz, fv = np.concatenate([z for z, _ in fit]), np.concatenate([v for _, v in fit])
    win = PROTOCOL["windows"]
    rng = np.random.default_rng(R.SEEDS["windows"])
    windows = R.sample_windows(train, win["length"], win["count"], rng)
    classifiers = {}
    for name, families in (("D2", I.HAI_FAMILIES["development"]), ("D3", [I.GENERIC])):
        inj = I.Injector("hai", fz, fv, seed=R.SEEDS["injection"] + zlib.crc32(release.encode()) % 1000)
        local = np.random.default_rng(R.SEEDS["windows"] + zlib.crc32(release.encode()) % 1000)
        X, Y = R.classifier_rows(scorer, windows, inj, families, win["injected_fraction"], local, (250, 170))
        if len(X) > R.MAX_ROWS:
            keep = np.random.default_rng(R.SEEDS["classifier"]).choice(len(X), R.MAX_ROWS, replace=False)
            X, Y = X[keep], Y[keep]
        classifiers[name] = R.train_classifier(X, Y, R.SEEDS["classifier"])
        log({"kind": "classifier", "release": release, "detector": name, "rows": int(len(X)), "positives": int(Y.sum())})
        print(release, name, len(X), "rows", round(time.time() - t0), "s", flush=True)
    base = ["D0", "DR", "D1", "D2", "D3"]
    clean = {d: [] for d in base}
    for z, v in cal:
        s = R.scores_for(scorer, classifiers, z, v)
        for d in base:
            clean[d].append(s[d][R.WARMUP:])
    val_rng = np.random.default_rng(R.SEEDS["injection"] + 7)
    inj = I.Injector("hai", fz, fv, seed=R.SEEDS["injection"] + 13)
    length = min(win["length"], min(len(z) for z, _ in cal) - 1)
    val = {"development": [], "held_out": []}
    for split, count in (("development", 200), ("held_out", 150)):
        fams = I.HAI_FAMILIES[split]
        for i, (z, v) in enumerate(R.sample_windows(cal, length, count, val_rng)):
            zi, vi, y = inj.apply(z, v, fams[i % len(fams)])
            val[split].append((fams[i % len(fams)], y, R.scores_for(scorer, classifiers, zi, vi)))
    choice = {}
    for d in base:
        best = None
        for w in R.GRID["hai"]:
            thr = R.calibrate([R.smooth(s, w) for s in clean[d]], R.GAP["hai"], R.BUDGET_PER_DAY["hai"], R.STEPS_PER_DAY["hai"])
            recall = float(np.mean([bool((R.smooth(s[d], w)[y == 1] > thr).any()) for _, y, s in val["development"]]))
            log({"kind": "smoothing", "release": release, "detector": d, "window": w, "validation_recall": recall})
            if best is None or recall > best[0]:
                best = (recall, w, thr)
        choice[d] = {"window": best[1], "threshold": best[2], "validation_recall": best[0]}
    # Registered D2c: D2 scores at D1's calibrated clean alarm fraction.
    d1 = choice["D1"]
    fraction = float(np.mean(np.concatenate([R.smooth(s, d1["window"]) for s in clean["D1"]]) > d1["threshold"]))
    w2 = choice["D2"]["window"]
    pooled = np.concatenate([R.smooth(s, w2) for s in clean["D2"]])
    thr2c = float(np.quantile(pooled, 1 - fraction)) if fraction > 0 else float(pooled.max()) + 1e-9
    recall2c = float(np.mean([bool((R.smooth(s["D2"], w2)[y == 1] > thr2c).any()) for _, y, s in val["development"]]))
    choice["D2c"] = {"window": w2, "threshold": thr2c, "validation_recall": recall2c, "matched_clean_alarm_fraction": fraction}
    for d, c in choice.items():
        src = "D2" if d == "D2c" else d
        held = {}
        for fam, y, s in val["held_out"]:
            held.setdefault(fam, []).append(bool((R.smooth(s[src], c["window"])[y == 1] > c["threshold"]).any()))
        c["held_out_recall"] = {k: float(np.mean(v)) for k, v in held.items()}
        log({"kind": "selection", "release": release, "detector": d, **{k: v for k, v in c.items()}})
        print(release, d, "w", c["window"], "dev recall", round(c["validation_recall"], 3), flush=True)
    bundle = {"release": release, "scorer": scorer, "classifiers": classifiers, "scalers": (xs, us), "choice": choice,
              "columns": cols}
    path = WORK / f"{release}-bundle.pkl"
    path.write_bytes(pickle.dumps(bundle))
    log({"kind": "frozen_bundle", "release": release, "path": path.relative_to(ROOT).as_posix(),
         "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "seconds": round(time.time() - t0)})
    print(release, "frozen", round(time.time() - t0), "s", flush=True)


def final():
    if RESULT.exists():
        raise SystemExit("rt2 final result already exists")
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    results = {}
    for release in RELEASES:
        entry = selection["bundles"][release]
        path = ROOT / entry["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise SystemExit(f"bundle digest mismatch for {release}")
        bundle = pickle.loads(path.read_bytes())
        xs, us = bundle["scalers"]
        out = {d: {"found": [], "delays": [], "events": [], "false_episodes": 0, "normal_steps": 0, "alarm_normal_steps": 0,
                   "scores": [], "labels": []} for d in DETECTORS}
        out["_wm"] = {h: {"model": 0.0, "persistence": 0.0, "count": 0} for h in (1, 5)}
        for k, (x, u, y) in enumerate(test_segments(release, "registered final evaluation rt2 attempt 2 (amendment 2)")):
            Z, V = xs(x), us(u)
            scores = R.scores_for(bundle["scorer"], bundle["classifiers"], Z, V)
            scores["D2c"] = scores["D2"]
            labelled = y.astype(bool)
            runs = C.events(y)
            for d in DETECTORS:
                c = bundle["choice"][d]
                s = R.smooth(scores[d], c["window"])
                s[:R.WARMUP] = -np.inf
                alarm = s > c["threshold"]
                for a, b in runs:
                    hit = np.flatnonzero(alarm[a:b])
                    out[d]["found"].append(bool(len(hit)))
                    out[d]["delays"].append(int(hit[0]) if len(hit) else None)
                    out[d]["events"].append({"segment": k, "start": int(a), "end": int(b)})
                out[d]["false_episodes"] += sum(1 for a, b in R.episodes(alarm, R.GAP["hai"]) if not labelled[a:b].any())
                out[d]["normal_steps"] += int((~labelled).sum())
                out[d]["alarm_normal_steps"] += int(alarm[~labelled].sum())
                finite = np.isfinite(s)
                out[d]["scores"].append(s[finite])
                out[d]["labels"].append(y[finite])
            wm = bundle["scorer"].wm
            for h in (1, 5):
                t = C.valid_index(len(Z), wm.history, h)
                csum = np.concatenate([[0], np.cumsum(y)])
                t = t[(csum[t + h + 1] - csum[t - wm.history]) == 0]
                if len(t):
                    out["_wm"][h]["model"] += float(np.abs(wm.predict(Z, V, t, h) - Z[t + h]).sum())
                    out["_wm"][h]["persistence"] += float(np.abs(Z[t] - Z[t + h]).sum())
                    out["_wm"][h]["count"] += int(len(t) * Z.shape[1])
        results[release] = summarize(out)
    gates = PROTOCOL["gates"]
    primary = all(results[r]["primary_gate"]["passes"] for r in RELEASES)
    doc = {"schema_version": "real-telemetry-result-rt2", "study_id": "real-telemetry-rt2",
           "selection_sha256": hashlib.sha256(SELECTION.read_bytes()).hexdigest(),
           "primary_success_rule_passes": primary, "gates": gates, "releases": results}
    RESULT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    for r, v in results.items():
        print(r, {d: (v["detectors"][d]["detected"], v["detectors"][d]["events"], round(v["detectors"][d]["false_episodes_per_day"], 2))
                  for d in DETECTORS}, "primary", v["primary_gate"]["passes"], "D2c", v["secondary"]["D2c_vs_D1"]["miss_reduction"])
    print("primary success rule:", primary)


def summarize(out):
    summary = {}
    for d in DETECTORS:
        o = out[d]
        delays = [x for x in o["delays"] if x is not None]
        days = o["normal_steps"] / R.STEPS_PER_DAY["hai"]
        summary[d] = {"events": len(o["found"]), "detected": int(sum(o["found"])), "event_recall": float(np.mean(o["found"])),
                      "false_episodes": o["false_episodes"], "normal_days": days,
                      "false_episodes_per_day": o["false_episodes"] / max(days, 1e-9),
                      "normal_step_alarm_rate": o["alarm_normal_steps"] / max(o["normal_steps"], 1),
                      "median_delay_steps": float(np.median(delays)) if delays else None,
                      **C.point_metrics(np.concatenate(o["scores"]), np.concatenate(o["labels"]))}
    level = PROTOCOL["gates"]["primary_interval_level"]
    boot = lambda a, b, lv: C.paired_event_bootstrap(out[a]["found"], out[b]["found"], reps=10_000, level=lv, seed=R.SEEDS["bootstrap"])
    primary = {f"D1_vs_{b}": boot(b, "D1", level) for b in ("D0", "DR")}
    budget = R.BUDGET_PER_DAY["hai"]
    passes = all(p["miss_reduction"] >= 0.20 and p["miss_reduction_interval"][0] > 0 for p in primary.values()) \
        and summary["D1"]["false_episodes_per_day"] <= 2 * budget
    secondary = {"D2c_vs_D1": boot("D1", "D2c", 0.95), "D2_vs_D1": boot("D1", "D2", 0.95), "D3_vs_D1": boot("D1", "D3", 0.95),
                 "D2c_vs_D3": boot("D3", "D2c", 0.95)}
    wm = {f"H{h}": {"model_mae": v["model"] / max(v["count"], 1), "persistence_mae": v["persistence"] / max(v["count"], 1),
                    "reduction": 1 - v["model"] / max(v["persistence"], 1e-12)} for h, v in out["_wm"].items()}
    return {"detectors": summary, "primary_comparisons": primary,
            "primary_gate": {"passes": bool(passes), "budget_per_day": budget},
            "secondary": secondary, "world_model_normal_periods": wm,
            "per_event": {d: [{**e, "detected": f, "delay": dl} for e, f, dl in zip(out[d]["events"], out[d]["found"], out[d]["delays"])]
                          for d in DETECTORS}}


if __name__ == "__main__":
    if sys.argv[1] == "develop":
        develop(sys.argv[2])
    elif sys.argv[1] == "final":
        final()
