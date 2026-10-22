#!/usr/bin/env python3
"""Step 3: real dashcam footage (Car Crash Dataset). Branch work, not main.

Implements docs/research/vision_world_model_ccd_protocol_v1.json. Same question as the
sim caution head, asked of real video: from frames t-1 and t, will the accident start
within the next 10 frames (1.0 s at 10 fps)? Crash-clip frames at or after onset are
excluded (anticipation, not detection); normal-clip frames are all negative.

Stages:
  prepare --split pool|test   decode + featurise in per-chunk checkpoints (grey 48x48,
                              frozen DINOv2 and MobileNetV2 4x4 maps). Retryable after a
                              GPU crash. Reads NO test labels. Logs 'ccd-test-featurise'.
  final                       CPU only: train all models on the train split, calibrate on
                              selection, persist frozen heads, record 'ccd-test', then read
                              test labels and compute metrics once.
  final --rescore             only per the registered crash rule: re-score from the
                              persisted frozen heads + cached features, no retraining.
  --smoke                     tiny run on pool videos only, temp cache/ledger/output.

Raw data lives in target/real-footage/ccd (gitignored); nothing from it is committed.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score

import vision_wm_final_v2 as FV
import vision_wm_pretrained_encoders as PE
import vision_wm_train as TR

ROOT = Path(__file__).resolve().parents[1]
CCD = ROOT / "target/real-footage/ccd"
RAW, VID = CCD / "raw", CCD / "videos"
CACHE = CCD / "cache"
FROZEN = ROOT / "target/vision-wm/ccd_frozen"
OUT = ROOT / "docs/research/vision_world_model_ccd_result_v1.json"
PROTOCOL = ROOT / "docs/research/vision_world_model_ccd_protocol_v1.json"
H_FR, G, PROBE_SIZE, IN_H, IN_W = 10, 48, 24, 224, 392
FPR, BUDGET, CHUNK, STRIDE = 0.05, 0.10, 25, 2


# ----------------------------------------------------------------------------- data
def split_lists():
    def read(name):
        rows = []
        for line in open(RAW / name, encoding="utf-8"):
            if line.strip():
                kind, f = line.split()[0].split("/")
                rows.append((kind, f[:-4]))
        return rows
    tr, te = read("train.txt"), read("test.txt")
    pos = sorted(i for k, i in tr if k == "positive")
    neg = sorted(i for k, i in tr if k == "negative")
    neg = sorted(np.random.default_rng(0).choice(neg, len(pos), replace=False).tolist())
    pool = [("positive", i) for i in pos] + [("negative", i) for i in neg]
    return pool, sorted(te)


def split_pool(pool):
    """80/20 by video, stratified, seed 0 -> (train, selection) index lists into pool."""
    rng = np.random.default_rng(0)
    tr, se = [], []
    for kind in ("positive", "negative"):
        ids = [j for j, (k, _) in enumerate(pool) if k == kind]
        ids = rng.permutation(ids).tolist()
        cut = int(round(0.8 * len(ids)))
        tr += ids[:cut]; se += ids[cut:]
    return sorted(tr), sorted(se)


def video_path(kind, vid):
    return VID / ("Crash-1500" if kind == "positive" else "Normal") / f"{vid}.mp4"


def decode(path):
    cap = cv2.VideoCapture(str(path))
    rgb, grey = [], []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        grey.append(cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (G, G), interpolation=cv2.INTER_AREA))
        rgb.append(cv2.cvtColor(cv2.resize(f, (IN_W, IN_H), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB))
    return np.stack(rgb), np.stack(grey)


@torch.no_grad()
def featurise(enc, rgb, bs=25, device=None):
    dev = PE.DEV if device is None else torch.device(device)
    x = torch.from_numpy(rgb).permute(0, 3, 1, 2).float() / 255.0
    out = []
    for i in range(0, len(x), bs):
        xb = ((x[i:i + bs].to(dev)) - PE.MEAN.to(dev)) / PE.STD.to(dev)
        out.append(F.adaptive_avg_pool2d(enc(xb), 4).half().cpu())
    return torch.cat(out).numpy()


_CPU = {}


def cpu_encoders():
    """CPU copies of both encoders, used to repair or cross-check GPU output (this laptop's GPU
    has crashed and also returned silently NaN frames)."""
    if not _CPU:
        import torchvision
        from huggingface_hub import hf_hub_download
        from safetensors.torch import load_file
        d = PE.DinoV2Small()
        d.load_state_dict(load_file(hf_hub_download("facebook/dinov2-small", "model.safetensors")), strict=True)
        m = torchvision.models.mobilenet_v2(weights=torchvision.models.MobileNet_V2_Weights.IMAGENET1K_V1).features[:-1]
        _CPU.update(dino=d.eval(), mbv2=m.eval())
    return _CPU


def guard(name, feats, rgb, rng, log):
    """Recompute non-finite frames on CPU; spot-check 2 random frames against CPU and
    recompute the whole clip on CPU if they disagree beyond fp16 precision."""
    enc = cpu_encoders()[name]
    bad = np.flatnonzero(~np.isfinite(feats.astype(np.float32)).reshape(len(feats), -1).all(1))
    for t in bad:
        feats[t] = featurise(enc, rgb[t:t + 1], device="cpu")[0]
        log.append(f"{name}: non-finite frame {int(t)} recomputed on CPU")
    probe = rng.choice(len(feats), 2, replace=False)
    ref = featurise(enc, rgb[probe], device="cpu").astype(np.float32)
    if np.abs(feats[probe].astype(np.float32) - ref).max() > 0.05:
        feats[:] = featurise(enc, rgb, device="cpu")
        log.append(f"{name}: GPU/CPU mismatch on spot check, clip recomputed on CPU")
    return feats


def annotations(ids):
    """Per-frame accident labels for the requested crash-clip ids only."""
    want, out = set(ids), {}
    for line in open(RAW / "Crash-1500.txt", encoding="utf-8"):
        vid, rest = line.split(",", 1)
        if vid in want:
            out[vid] = np.array(json.loads(rest[:rest.index("]") + 1]), np.int8)
    missing = want - set(out)
    assert not missing, f"missing annotations: {sorted(missing)[:5]}"
    return out


# ----------------------------------------------------------------------------- prepare
def prepare(split, videos, cache, ledger_note):
    cache.mkdir(parents=True, exist_ok=True)
    if ledger_note and not FV.ledger_has("ccd-test-featurise"):
        FV.record_final("ccd-test-featurise", "CCD official test videos decoded/featurised; no labels read, no metric computed")
    todo = [c for c in range(0, len(videos), CHUNK) if not (cache / f"chunk_{c // CHUNK:04d}.npz").exists()]
    print(f"prepare {split}: {len(videos)} videos, {len(todo)} chunks to do (device {PE.DEV})", flush=True)
    if not todo:
        return
    # TF32 off: with it on, GPU and CPU DINOv2 features differ by up to ~2% on some real clips;
    # with it off they agree to fp16 storage precision, so the spot check catches real corruption.
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    dino, mbv2 = PE.load_dino(True), PE.load_mobilenet(True)
    for n, c in enumerate(todo):
        t0 = time.time()
        grey, d, m, ids, notes = [], [], [], [], []
        rng = np.random.default_rng(c)
        for kind, vid in videos[c:c + CHUNK]:
            rgb, gr = decode(video_path(kind, vid))
            assert len(rgb) == 50, f"{kind}/{vid}: {len(rgb)} frames"
            fd = guard("dino", featurise(dino, rgb), rgb, rng, notes)
            fm = guard("mbv2", featurise(mbv2, rgb), rgb, rng, notes)
            grey.append(gr); d.append(fd); m.append(fm); ids.append(f"{kind}/{vid}")
        tmp = cache / f"chunk_{c // CHUNK:04d}.tmp.npz"
        np.savez(tmp, grey=np.stack(grey), dino=np.stack(d), mbv2=np.stack(m), ids=np.array(ids))
        tmp.replace(cache / f"chunk_{c // CHUNK:04d}.npz")
        if notes:
            with open(ROOT / "target/vision-wm/infrastructure_failures.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                     "script": f"scripts/vision_ccd.py prepare {split}", "chunk": c // CHUNK,
                                     "error": "GPU output repaired", "notes": notes}) + "\n")
            print(f"  chunk {c // CHUNK}: {len(notes)} GPU repair(s): {notes[:2]}", flush=True)
        if n % 10 == 0 or n == len(todo) - 1:
            print(f"  chunk {c // CHUNK:4d} ({n + 1}/{len(todo)}) {round(time.time() - t0, 1)}s", flush=True)


def audit(splits, n_clips=300, frames_per_clip=5, tol=0.05, seed=0):
    """Estimate silent GPU corruption in the cache: recompute random frames on CPU (TF32 is
    irrelevant on CPU), compare, and recompute + patch any clip with a mismatching frame.
    Reads no labels."""
    rng = np.random.default_rng(seed)
    enc = cpu_encoders()
    pool_list = [(name, videos, cache, i) for name, videos, cache in splits for i in range(len(videos))]
    pick = rng.choice(len(pool_list), min(n_clips, len(pool_list)), replace=False)
    checked = mismatched_frames = 0
    patched = []
    for j in pick:
        name, videos, cache, i = pool_list[j]
        chunk = cache / f"chunk_{i // CHUNK:04d}.npz"
        with np.load(chunk, allow_pickle=False) as z:
            arr = {k: z[k] for k in z.files}
        rgb, _ = decode(video_path(*videos[i]))
        ts = rng.choice(50, frames_per_clip, replace=False)
        bad = False
        for key in ("dino", "mbv2"):
            ref = featurise(enc[key], rgb[ts], device="cpu").astype(np.float32)
            d = np.abs(arr[key][i % CHUNK][ts].astype(np.float32) - ref).reshape(len(ts), -1).max(1)
            mismatched_frames += int((d > tol).sum()); checked += len(ts)
            bad |= bool((d > tol).any())
        if bad:
            for key in ("dino", "mbv2"):
                arr[key][i % CHUNK] = featurise(enc[key], rgb, device="cpu")
            tmp = chunk.with_name(chunk.stem + ".tmp.npz")
            np.savez(tmp, **arr); tmp.replace(chunk)
            patched.append(f"{name}:{videos[i][0]}/{videos[i][1]}")
    summary = {"clips_checked": len(pick), "frame_encoder_pairs_checked": checked,
               "mismatched": mismatched_frames, "mismatch_rate": mismatched_frames / max(checked, 1),
               "tolerance_abs": tol, "clips_recomputed_on_cpu": patched}
    (splits[0][2].parent / "audit.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "clips_recomputed_on_cpu"}), "| recomputed:", patched, flush=True)
    return summary


def load_cache(videos, cache, key):
    """One array (grey | dino | mbv2) for all videos, in split order (one key at a time to bound RAM)."""
    parts, ids = [], []
    for c in range(0, len(videos), CHUNK):
        with np.load(cache / f"chunk_{c // CHUNK:04d}.npz", allow_pickle=False) as p:
            parts.append(p[key]); ids.append(p["ids"])
    assert np.concatenate(ids).tolist() == [f"{k}/{v}" for k, v in videos], "cache order does not match the split"
    arr = np.concatenate(parts)
    if key != "grey":
        assert np.isfinite(arr.astype(np.float32)).all(), f"non-finite {key} features in cache"
    return arr


# ----------------------------------------------------------------------------- task
def transitions(videos, ann, stride=1):
    """(e, t, y, onset) for t in 1..48; crash frames at/after onset excluded."""
    e_, t_, y_, o_ = [], [], [], []
    for e, (kind, vid) in enumerate(videos):
        onset = int(np.argmax(ann[vid])) if kind == "positive" else None
        if kind == "positive" and not ann[vid].any():
            continue
        for t in range(1, 49):
            if stride > 1 and t % stride != 1:
                continue
            if onset is not None and t >= onset:
                continue
            e_.append(e); t_.append(t)
            y_.append(int(onset is not None and onset - t <= H_FR)); o_.append(-1 if onset is None else onset)
    return np.array(e_), np.array(t_), np.array(y_, np.int8), np.array(o_)


def stacks(grey, e, t):
    g = grey.astype(np.float32) / 255.0
    return np.stack([g[e, t - 1], g[e, t]], 1), g[e, t + 1]


def probe_x(grey, e, t):
    small = grey.reshape(grey.shape[0], grey.shape[1], PROBE_SIZE, 2, PROBE_SIZE, 2).mean((3, 5)) / 255.0
    return np.concatenate([small[e, t - 1].reshape(len(e), -1), small[e, t].reshape(len(e), -1)], 1)


def idx_of(e, t, y):
    return e, t, np.zeros(len(e), np.int64), y


def video_level(scores, e, t, y, onset, kinds, thr):
    crash_hit, tta, normal_alarm = [], [], []
    for v in np.unique(e):
        m = e == v
        alarm_t = t[m][scores[m] > thr]
        if kinds[v] == "positive":
            crash_hit.append(len(alarm_t) > 0)
            if len(alarm_t):
                tta.append((onset[m][0] - alarm_t.min()) / 10.0)
        else:
            normal_alarm.append(len(alarm_t) > 0)
    return {"crash_clips_alarmed_before_onset": float(np.mean(crash_hit)) if crash_hit else float("nan"),
            "mean_time_to_accident_s": float(np.mean(tta)) if tta else float("nan"),
            "normal_clips_with_any_alarm": float(np.mean(normal_alarm)) if normal_alarm else float("nan")}


def cluster_boot_ap_diff(s_a, s_b, y, e, reps=2000, seed=0):
    rng = np.random.default_rng(seed)
    vids = np.unique(e)
    rows = {v: np.flatnonzero(e == v) for v in vids}
    diffs = []
    for _ in range(reps):
        take = np.concatenate([rows[v] for v in rng.choice(vids, len(vids), replace=True)])
        if y[take].min() == y[take].max():
            continue
        diffs.append(average_precision_score(y[take], s_a[take]) - average_precision_score(y[take], s_b[take]))
    return {"auc_pr_difference": float(average_precision_score(y, s_a) - average_precision_score(y, s_b)),
            "ci95": [float(np.quantile(diffs, 0.025)), float(np.quantile(diffs, 0.975))], "resamples": len(diffs)}


# ----------------------------------------------------------------------------- final
def final(pool, test, pool_cache, test_cache, epochs, rescore, frozen_dir):
    import gc
    tr_i, se_i = (np.array(x) for x in split_pool(pool))
    ann_pool = annotations([v for k, v in pool if k == "positive"])
    etr, ttr, ytr, _ = transitions([pool[j] for j in tr_i], ann_pool, STRIDE)
    ese, tse, yse, _ = transitions([pool[j] for j in se_i], ann_pool, 1)
    etr, ese = tr_i[etr], se_i[ese]                     # pool-level video indices: index the shared array, no copies
    print(f"train {len(ytr)} transitions ({ytr.mean():.3f} pos) | selection {len(yse)} ({yse.mean():.3f} pos)", flush=True)
    frozen_dir.mkdir(parents=True, exist_ok=True)
    models, sel, z = {}, {}, (lambda n: np.zeros(n, np.int64))

    if not rescore:
        for name in ("dino", "mbv2"):
            Fp = torch.from_numpy(load_cache(pool, pool_cache, name))
            score, ap = PE.train_head(Fp, Fp, idx_of(etr, ttr, ytr), idx_of(ese, tse, yse), epochs)
            torch.save(score.head.state_dict(), frozen_dir / f"{name}_head.pt")
            models[name] = score; sel[name] = score(Fp, idx_of(ese, tse, yse))
            del Fp; gc.collect()
            print(f"  {name} head: selection AUC-PR {ap:.3f}", flush=True)
        grey = load_cache(pool, pool_cache, "grey")
        ctr, ntr = stacks(grey, etr, ttr); cse, nse = stacks(grey, ese, tse)
        cnn_scores, best_c, *_ = FV.train_vwm((ctr, z(len(ytr)), ntr, ytr), (cse, z(len(yse)), nse, yse), epochs=epochs)
        torch.save(best_c, frozen_dir / "cnn_best_caution.pt")
        models["cnn"] = cnn_scores; sel["cnn"] = cnn_scores(best_c, cse, z(len(yse)))[1]
        del ctr, ntr, cse, nse; gc.collect()
        lp = LogisticRegression(max_iter=500, C=0.5, class_weight="balanced").fit(probe_x(grey, etr, ttr), ytr)
        np.savez(frozen_dir / "probe.npz", coef=lp.coef_, intercept=lp.intercept_)
        models["probe"] = lp; sel["probe"] = lp.predict_proba(probe_x(grey, ese, tse))[:, 1]
        del grey; gc.collect()
        thr = {m: {"p05": FV.calibrate(s, yse, FPR), "p10": FV.calibrate(s, yse, BUDGET)} for m, s in sel.items()}
        (frozen_dir / "thresholds.json").write_text(json.dumps(thr, indent=1), encoding="utf-8")
        best_state = best_c
    else:
        thr = json.loads((frozen_dir / "thresholds.json").read_text(encoding="utf-8"))
        tiny = (np.zeros((4, 2, G, G), np.float32), np.zeros(4, np.int64), np.zeros((4, G, G), np.float32), np.array([0, 1, 0, 1], np.int8))
        models["cnn"], *_ = FV.train_vwm(tiny, tiny, epochs=0)
        best_state = torch.load(frozen_dir / "cnn_best_caution.pt")
        dummy = torch.zeros(2, 50, 1, 4, 4, dtype=torch.float16)
        for name, ch in (("dino", 384), ("mbv2", 320)):
            Fd = dummy.repeat(1, 1, ch, 1, 1)
            sidx = idx_of(np.array([0, 1]), np.array([1, 1]), np.array([0, 1], np.int8))
            score, _ = PE.train_head(Fd, Fd, sidx, sidx, 1)
            score.head.load_state_dict(torch.load(frozen_dir / f"{name}_head.pt"))
            models[name] = score
        with np.load(frozen_dir / "probe.npz") as pz:
            lp = LogisticRegression(); lp.coef_, lp.intercept_, lp.classes_ = pz["coef"], pz["intercept"], np.array([0, 1])
        models["probe"] = lp
    print("frozen thresholds:", json.dumps({m: {k: round(v, 4) for k, v in t.items()} for m, t in thr.items()}), flush=True)

    # ---------------- SINGLE OPEN: test labels are read only below this line ----------------
    if not rescore:
        FV.record_final("ccd-test", "vision-world-model CCD v1 final: test labels read, metrics computed once")
    ann_te = annotations([v for k, v in test if k == "positive"])
    ete, tte, yte, ote = transitions(test, ann_te, 1)
    kinds = [k for k, _ in test]
    scores = {}
    for name in ("dino", "mbv2"):
        scores[name] = models[name](torch.from_numpy(load_cache(test, test_cache, name)), idx_of(ete, tte, yte))
        gc.collect()
    tgrey = load_cache(test, test_cache, "grey")
    cte, _ = stacks(tgrey, ete, tte)
    scores["cnn"] = models["cnn"](best_state, cte, z(len(yte)))[1]
    scores["probe"] = models["probe"].predict_proba(probe_x(tgrey, ete, tte))[:, 1]
    crash = np.array([kinds[v] == "positive" for v in ete])
    res = {}
    for m, s in scores.items():
        res[m] = {**TR.auc(yte, s), "within_crash_clip": TR.auc(yte[crash], s[crash])}
        for arm in ("p05", "p10"):
            r, f = FV.recall_fpr(s, yte, thr[m][arm])
            res[m][arm] = {"recall": r, "realized_fpr": f}
        res[m]["video_level_p05"] = video_level(s, ete, tte, yte, ote, kinds, thr[m]["p05"])
    boot = cluster_boot_ap_diff(scores["dino"], scores["cnn"], yte, ete)
    g1 = (res["dino"]["auc_pr"] > res["cnn"]["auc_pr"] and res["dino"]["auc_pr"] > res["probe"]["auc_pr"]
          and boot["ci95"][0] > 0)
    g2 = res["dino"]["p05"]["realized_fpr"] <= BUDGET
    gates = {"G1_pretrained_beats_scratch": bool(g1), "G2_budget_holds": bool(g2),
             "auc_pr_diff_dino_minus_cnn_video_cluster_bootstrap": boot, "primary_success": bool(g1 and g2)}
    print(f"\nFINAL CCD test: {len(test)} clips, {len(yte)} frames, prevalence {yte.mean():.3f}")
    for m in ("dino", "mbv2", "cnn", "probe"):
        r = res[m]; v = r["video_level_p05"]
        print(f"  {m:6s} AUC-PR {r['auc_pr']:.3f} ROC {r['auc_roc']:.3f} | within-crash ROC {r['within_crash_clip']['auc_roc']:.3f} | "
              f"recall@5% {r['p05']['recall']:.3f} (fpr {r['p05']['realized_fpr']:.3f}) | crash clips alarmed {v['crash_clips_alarmed_before_onset']:.3f} "
              f"TTA {v['mean_time_to_accident_s']:.2f}s normal clips alarmed {v['normal_clips_with_any_alarm']:.3f}")
    print(f"  AUC-PR diff dino-cnn {boot['auc_pr_difference']:+.3f} CI95 {[round(x, 3) for x in boot['ci95']]}")
    print(f"  G1 {'PASS' if g1 else 'FAIL'}  G2 {'PASS' if g2 else 'FAIL'}  => primary {'PASS' if gates['primary_success'] else 'FAIL'}")
    return {"test_clips": len(test), "test_frames": int(len(yte)), "prevalence": float(yte.mean()),
            "thresholds": thr, "results": res, "gates": gates, "rescored": bool(rescore)}


def main():
    global OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["prepare", "audit", "final"])
    ap.add_argument("--split", choices=["pool", "test"], default="pool")
    ap.add_argument("--rescore", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args()
    pool, test = split_lists()
    pool_cache, test_cache, frozen, epochs = CACHE / "pool", CACHE / "test", FROZEN, 60
    if a.smoke:
        tmp = Path(tempfile.gettempdir()) / "vision_ccd_smoke"
        FV.LEDGER = tmp / "ledger.jsonl"; OUT = tmp / "result.json"; frozen = tmp / "frozen"
        # smoke never touches test videos: a fake "test" is carved out of the pool
        crash = [p for p in pool if p[0] == "positive"]; norm = [p for p in pool if p[0] == "negative"]
        pool = crash[:20] + norm[:20]; test = crash[20:26] + norm[20:26]
        pool_cache, test_cache, epochs = tmp / "pool", tmp / "test", 2
        print("SMOKE ->", tmp)
    if a.stage == "prepare":
        videos, cache = (pool, pool_cache) if a.split == "pool" else (test, test_cache)
        prepare(a.split, videos, cache, ledger_note=(a.split == "test" and not a.smoke))
        return
    if a.stage == "audit":
        audit([("pool", pool, pool_cache), ("test", test, test_cache)], n_clips=12 if a.smoke else 300)
        return
    if not a.rescore and FV.ledger_has("ccd-test"):
        raise SystemExit("REFUSE: 'ccd-test' already in the ledger; the final runs once (use --rescore only per the crash rule)")
    if a.rescore and not FV.ledger_has("ccd-test"):
        raise SystemExit("REFUSE: --rescore requires a recorded 'ccd-test' open")
    out = final(pool, test, pool_cache, test_cache, epochs, a.rescore, frozen)
    frozen_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(frozen.iterdir())}
    doc = {"schema_version": "vision-world-model-ccd-result-v1", "protocol": PROTOCOL.name,
           "status": "registered final on real footage, opened once; branch work (not main); advisory only",
           "horizon_frames": H_FR, "fps": 10, "frozen_state_sha256": frozen_hashes,
           "dinov2_weights": "facebook/dinov2-small", **out}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=1, default=float) + "\n", encoding="utf-8")
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
