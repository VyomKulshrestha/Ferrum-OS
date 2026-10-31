#!/usr/bin/env python3
"""Post-hoc sensitivity analysis after the registered tt1 final: the opening transient of HAI 20.07 test1.

HAI 20.07 test1 opens with about ten unlabelled minutes in which the D1 score sits near 5 tau0. The
registered tracker and daily rules learn from those minutes, so the tracker stood at 5.25 tau0 when the
first attack arrived. This script asks how much of the registered recall loss depends on that transient:
it reruns the registered pipeline unchanged and, for the adaptive rules only, hides each stream's opening
run of scores above tau0 from the threshold update (the samples count as non-exceedances for the trackers
and are left out of the daily quantile). Alarms are still computed on the real score.

The baseline run (no hiding) must reproduce the registered event counts; the script stops otherwise.
HAI 20.07 was opened once by the registered final; this reopening is ledgered as post-hoc.

Output: docs/research/threshold_transfer_tt1_posthoc_transient.json
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
import threshold_transfer_dev as X
import tt1_data as TD
import tt1_final as F

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/research/threshold_transfer_tt1_posthoc_transient.json"
REGISTERED = ROOT / "docs/research/threshold_transfer_tt1_result_hai-20.07.json"
RULES = ["frozen", "daily", "tracker", "tracker_slow", "one_sided:none"]
ADAPTIVE = {"daily", "tracker", "tracker_slow", "one_sided:none"}
REASON = ("post-hoc sensitivity analysis after the registered tt1 final: adaptive thresholds with the opening "
          "transient of each test stream hidden from the threshold update")


def opening_run(s, tau0):
    """Length of the stream's opening run of scores above tau0 (0 if the stream opens below tau0)."""
    below = np.flatnonzero(np.isfinite(s) & (s <= tau0))
    return int(below[0]) if len(below) else len(s)


def evaluate(streams, cfg, hide):
    found = {r: [] for r in RULES}
    per_stream, infl = [], {r: [] for r in RULES}
    for k, (s, y) in enumerate(streams):
        ev = C.events(y)
        n0 = opening_run(s, cfg["tau0"]) if hide else 0
        s_upd = s.copy()
        s_upd[:n0] = -np.inf                       # invisible to the update, still alarmed on below
        row = {"stream": f"test{k + 1}", "opening_run_seconds": n0, "events": len(ev)}
        for r in RULES:
            tau, _ = F.apply(r, s_upd if r in ADAPTIVE else s, cfg, F.SPD, F.GAP, y)
            alarm = s > tau
            f = [bool(alarm[a:b].any()) for a, b in ev]
            found[r] += f
            infl[r] += [float(tau[a] / cfg["tau0"]) for a, b in ev]
            row[r] = int(sum(f))
        per_stream.append(row)
    rules = {r: {"detected": int(sum(found[r])), "events": len(found[r]), "recall": float(np.mean(found[r])),
                 "median_onset_inflation": float(np.median(infl[r]))} for r in RULES}
    paired = {f"{r}_vs_frozen": C.paired_event_bootstrap(found["frozen"], found[r], reps=F.BOOT)
              for r in RULES if r != "frozen"}
    return {"per_stream": per_stream, "rules": rules, "paired": paired}


def main():
    t0 = time.time()
    segs, cols = F.normal_data("hai-20.07")
    kx, ku = F.varying_columns(segs)
    segs = [(x[:, kx], u[:, ku]) for x, u in segs]
    parts = F.split(segs, F.FINAL_CUTS, ("fit", "scale", "calib"), min_len=1000)
    scorer, pack, _, _, _ = F.fit_monitor(parts["fit"], parts["scale"])
    cal = [s[np.isfinite(s)] for s in (X.d1(scorer, z, v) for z, v in pack(parts["calib"]))]
    tau0 = R.calibrate(cal, F.GAP, F.BUDGET, F.SPD)
    cfg = F.thresholds(np.concatenate(cal), tau0, F.ETA_MULT, 0.999)
    reg = json.loads(REGISTERED.read_text(encoding="utf-8"))
    assert cfg["tau0"] == reg["thresholds"]["tau0"], (cfg["tau0"], reg["thresholds"]["tau0"])
    print("monitor fitted", round(time.time() - t0), "s; tau0 equals the registered value", flush=True)

    raw = TD.hai2007_test(REASON)[0]
    streams = []
    for x, u, y in raw:
        z, v = pack([(x[:, kx], u[:, ku])])[0]
        s = X.d1(scorer, z, v)
        streams.append((np.where(np.isfinite(s), s, -np.inf), y))

    base = evaluate(streams, cfg, hide=False)
    for r in RULES:
        want = reg["real_events"]["rules"][r]["detected"]
        assert base["rules"][r]["detected"] == want, (r, base["rules"][r]["detected"], want)
    print("baseline reproduces the registered counts", flush=True)
    hidden = evaluate(streams, cfg, hide=True)

    out = {"status": "post-hoc analysis after the registered tt1 final (not registered)",
           "reason": REASON, "dataset": "hai-20.07", "tau0": cfg["tau0"], "p": cfg["p"], "eta": cfg["eta"],
           "registered_pipeline_unchanged": True, "baseline_reproduces_registered_counts": True,
           "baseline": base, "opening_transient_hidden": hidden, "seconds": round(time.time() - t0)}
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for name, res in (("baseline", base), ("hidden", hidden)):
        print(name, {r: f'{m["detected"]}/{m["events"]} infl {m["median_onset_inflation"]:.1f}' for r, m in res["rules"].items()})
        print("  ", res["per_stream"])
        print("  ", {k: (round(v["recall_difference"], 3), [round(x, 2) for x in v["recall_difference_interval"]])
                     for k, v in res["paired"].items()})


if __name__ == "__main__":
    main()
