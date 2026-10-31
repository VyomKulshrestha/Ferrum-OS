#!/usr/bin/env python3
"""Post-hoc analysis after the registered tt1 and tt1b finals: time in alarm, onset recall, and what
inflates the adaptive thresholds.

Why: the recorded trajectories show that on HAI 20.07 the D1 score sits above tau0 for 23.8 h from the
start of test1 and for 17.2 h inside test2, with no attack label. The registered metrics count such a
run as one false-alarm episode, and count an attack inside it as detected. This script adds, for the
registered pipelines unchanged:

  alarm_time      share of unlabelled steps in alarm
  onset recall    an event counts only if an alarm episode (merged across the registered gap) starts
                  inside it, so an attack that falls inside an alarm already running is not credited
  learn variants  the adaptive rules rerun with their update fed only the attack-labelled samples
                  ("attacks_only") or only the unlabelled ones ("unlabelled_only"); the other samples
                  are replaced by the calibration median for the update, and alarms are still computed
                  on the real score. This separates inflation by attacks from inflation by unlabelled
                  exceedances.

The baseline must reproduce the registered event counts (and the post-hoc SPOT/DSPOT counts); the script
stops otherwise. Both datasets were opened once by their registered finals; this reopening is ledgered
as post-hoc. It supersedes threshold_transfer_tt1_posthoc_transient.json, whose "opening transient"
turned out to be the 23.8 h run, seven attacks included.

Output: docs/research/threshold_transfer_tt1_posthoc_alarm_time.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_telemetry_core as C
import real_telemetry_detect as R
import threshold_rules as T
import threshold_rules_ext as E
import threshold_transfer_dev as X
import tt1_data as TD
import tt1_final as F
import tt1b_final as B

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs/research"
OUT = DOCS / "threshold_transfer_tt1_posthoc_alarm_time.json"
RULES = ["frozen", "daily", "tracker", "tracker_slow", "one_sided:none", "spot", "spot_mle", "dspot"]
ADAPTIVE = [r for r in RULES if r != "frozen"]
REASON = ("post-hoc analysis after the registered {study} final: time in alarm, onset recall, and adaptive "
          "thresholds updated on attack-labelled or unlabelled samples only")


def metrics(s, y, taus, gap, steps_per_day, tau0):
    ev = C.events(y)
    lab = np.zeros(len(s), bool)
    for a, b in ev:
        lab[a:b] = True
    out = {}
    for r, tau in taus.items():
        alarm = s > tau
        eps = T._episodes(alarm, gap)
        starts = np.zeros(len(s), bool)
        for a, _ in eps:
            starts[a] = True
        out[r] = {"found": [bool(alarm[a:b].any()) for a, b in ev],
                  "onset_found": [bool(starts[a:b].any()) for a, b in ev],
                  "inflation": [float(tau[a] / tau0) for a, b in ev],
                  "unlabelled_steps": int((~lab).sum()), "unlabelled_alarm_steps": int((alarm & ~lab).sum()),
                  "fa_episodes": sum(1 for a, b in eps if not lab[a:b].any())}
    return out, len(s), int((~lab).sum())


def summarize(per_stream, steps_per_day):
    rules = {}
    for r in per_stream[0]:
        f = sum((m[r]["found"] for m in per_stream), [])
        o = sum((m[r]["onset_found"] for m in per_stream), [])
        inf = sum((m[r]["inflation"] for m in per_stream), [])
        un = sum(m[r]["unlabelled_steps"] for m in per_stream)
        ua = sum(m[r]["unlabelled_alarm_steps"] for m in per_stream)
        fa = sum(m[r]["fa_episodes"] for m in per_stream)
        rules[r] = {"events": len(f), "detected": int(sum(f)), "recall": float(np.mean(f)),
                    "onset_detected": int(sum(o)), "onset_recall": float(np.mean(o)),
                    "unlabelled_alarm_share": ua / un, "fa_episodes_per_day": fa / (un / steps_per_day),
                    "median_onset_inflation": float(np.median(inf)),
                    "per_stream_detected": [int(sum(m[r]["found"])) for m in per_stream],
                    "per_stream_onset_detected": [int(sum(m[r]["onset_found"])) for m in per_stream]}
        rules[r]["_found"], rules[r]["_onset"] = f, o
    paired = {}
    for r in rules:
        if r != "frozen" and "frozen" in rules:
            paired[f"{r}_vs_frozen"] = C.paired_event_bootstrap(rules["frozen"]["_found"], rules[r]["_found"], reps=F.BOOT)
            paired[f"{r}_vs_frozen_onset"] = C.paired_event_bootstrap(rules["frozen"]["_onset"], rules[r]["_onset"],
                                                                      reps=F.BOOT)
    for m in rules.values():
        del m["_found"], m["_onset"]
    return {"rules": rules, "paired": paired}


def run(streams, cfg, pooled, spd, gap, depth):
    """streams: list of (s, y). Returns baseline and the two learn variants."""
    m0 = cfg["m0"]
    res = {}
    for variant in ("baseline", "attacks_only", "unlabelled_only"):
        per = []
        for s, y in streams:
            lab = y.astype(bool)
            taus = {}
            for r in (RULES if variant == "baseline" else ["frozen"] + ADAPTIVE):
                if variant == "attacks_only" and r != "frozen":
                    s_upd = np.where(lab, s, m0)
                elif variant == "unlabelled_only" and r != "frozen":
                    s_upd = np.where(lab, m0, s)
                else:
                    s_upd = s
                taus[r] = E.apply_rule(r, s_upd, cfg, pooled, spd, gap, depth, labels=y)[0]
            per.append(metrics(s, y, taus, gap, spd, cfg["tau0"])[0])
        res[variant] = summarize(per, spd)
        print(variant, {r: f'{m["detected"]}/{m["events"]} onset {m["onset_detected"]} alarm '
                           f'{m["unlabelled_alarm_share"]:.3f}' for r, m in res[variant]["rules"].items()}, flush=True)
    return res


def stream_dataset(name):
    """HAI 20.07 or HyGrid-ICS through the registered tt1 stream pipeline."""
    t0 = time.time()
    segs, _ = F.normal_data(name)
    kx, ku = F.varying_columns(segs)
    segs = [(x[:, kx], u[:, ku]) for x, u in segs]
    parts = F.split(segs, F.FINAL_CUTS, ("fit", "scale", "calib"), min_len=1000)
    scorer, pack, _, _, _ = F.fit_monitor(parts["fit"], parts["scale"])
    cal = [s[np.isfinite(s)] for s in (X.d1(scorer, z, v) for z, v in pack(parts["calib"]))]
    tau0 = R.calibrate(cal, F.GAP, F.BUDGET, F.SPD)
    pooled = np.concatenate(cal)
    cfg = F.thresholds(pooled, tau0, F.ETA_MULT, 0.999)
    reg = json.loads((DOCS / f"threshold_transfer_tt1_result_{name}.json").read_text(encoding="utf-8"))
    assert cfg["tau0"] == reg["thresholds"]["tau0"]
    raw = F.final_data(name, REASON.format(study="tt1"))
    streams = []
    for x, u, y in raw:
        z, v = pack([(x[:, kx], u[:, ku])])[0]
        s = X.d1(scorer, z, v)
        streams.append((np.where(np.isfinite(s), s, -np.inf), y))
    print(name, "loaded", round(time.time() - t0), "s", flush=True)
    res = run(streams, cfg, pooled, F.SPD, F.GAP, 3600)
    want = {r: reg["real_events"]["rules"][r]["detected"] for r in ("frozen", "daily", "tracker", "tracker_slow",
                                                                    "one_sided:none")}
    # SPOT/DSPOT were not registered in tt1: their counts come from threshold_transfer_tt1b_posthoc_v1.json
    ph = json.loads((DOCS / "threshold_transfer_tt1b_posthoc_v1.json").read_text(encoding="utf-8"))
    for r in ("spot", "spot_mle", "dspot"):
        m = ph["datasets"][name]["scores"]["D1"]["rules"][r]
        want[r] = int(round(m["recall"] * m["events"]))
    for r, d in want.items():
        assert res["baseline"]["rules"][r]["detected"] == d, (r, res["baseline"]["rules"][r]["detected"], d)
    return {"tau0": cfg["tau0"], "steps_per_day": F.SPD, "gap": F.GAP,
            "baseline_reproduces": {r: d for r, d in want.items()}, **res}


def batadal():
    ds = B.DATASETS["batadal"]
    segs, _ = ds["train"]()
    kx, ku = F.varying_columns(segs)
    segs = [(x[:, kx], u[:, ku]) for x, u in segs]
    parts = F.split(segs, F.FINAL_CUTS, ("fit", "scale", "calib"), min_len=max(200, 4 * ds["window"]))
    scorer, pack, _, _, _ = F.fit_monitor(parts["fit"], parts["scale"])
    cal = [s[np.isfinite(s)] for s in (B.smoothed(scorer, z, v, "D1", ds["window"]) for z, v in pack(parts["calib"]))]
    tau0 = R.calibrate(cal, ds["gap"], ds["budget"], ds["steps_per_day"])
    pooled = np.concatenate(cal)
    cfg = F.thresholds(pooled, tau0, F.ETA_MULT, 0.999)
    reg = json.loads((DOCS / "threshold_transfer_tt1b_result_batadal.json").read_text(encoding="utf-8"))
    assert cfg["tau0"] == reg["scores"]["D1"]["thresholds"]["tau0"]
    raw, _ = ds["test"](REASON.format(study="tt1b"))
    streams = []
    for x, u, y in raw:
        z, v = pack([(x[:, kx], u[:, ku])])[0]
        s = B.smoothed(scorer, z, v, "D1", ds["window"])
        streams.append((np.where(np.isfinite(s), s, -np.inf), y))
    res = run(streams, cfg, pooled, ds["steps_per_day"], ds["gap"], ds["depth"])
    want = {r: reg["scores"]["D1"]["real_events"]["rules"][r]["detected"] for r in RULES
            if r in reg["scores"]["D1"]["real_events"]["rules"]}
    for r, d in want.items():
        assert res["baseline"]["rules"][r]["detected"] == d, (r, res["baseline"]["rules"][r]["detected"], d)
    return {"tau0": cfg["tau0"], "steps_per_day": ds["steps_per_day"], "gap": ds["gap"],
            "baseline_reproduces": want, **res}


def main():
    """No argument: HAI 20.07 and BATADAL (the first run). With dataset names: run those and merge them into
    the existing output (HyGrid-ICS was added in a second run, ledgered separately)."""
    if len(sys.argv) > 1:
        out = json.loads(OUT.read_text(encoding="utf-8"))
        for name in sys.argv[1:]:
            out[name] = batadal() if name == "batadal" else stream_dataset(name)
        OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
        print("merged", sys.argv[1:], "into", OUT)
        return
    t0 = time.time()
    out = {"status": "post-hoc analysis after the registered tt1 and tt1b finals (not registered)",
           "definitions": {"onset_recall": "an event counts only if an alarm episode, merged across the registered "
                                           "gap, starts inside it",
                           "unlabelled_alarm_share": "share of unlabelled steps in alarm",
                           "attacks_only / unlabelled_only": "adaptive rules updated on attack-labelled (or "
                                                             "unlabelled) samples only; other samples replaced by "
                                                             "the calibration median for the update; alarms on "
                                                             "the real score"},
           "supersedes": "threshold_transfer_tt1_posthoc_transient.json (its opening run was 23.8 h with 7 attacks)"}
    out["hai-20.07"] = stream_dataset("hai-20.07")
    out["batadal"] = batadal()
    out["seconds"] = round(time.time() - t0)
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print("written", OUT, out["seconds"], "s")


if __name__ == "__main__":
    main()
