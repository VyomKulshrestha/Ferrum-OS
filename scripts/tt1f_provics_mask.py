#!/usr/bin/env python3
"""tt1f K2 (exploratory, post-hoc): the ProvICS validity mask.

Plan: docs/research/threshold_transfer_tt1f_dev_plan.md, amendment 2 (committed before this run). The code
audit (docs/research/monitor_audit_2026-11-10.md) found that the registered loader marks only the grid steps
inside a recording gap as invalid, while the score still depends on forward-filled values for 36 steps
after the gap. This script refits the monitor with the registered code and amendment 1 of tt1d, then scores
the attack recording and the sealed rows twice: with the registered mask and with the extended one. It is a
third, ledgered access to both. The registered ProvICS outcome is not replaced.

    python scripts/tt1f_provics_mask.py      writes docs/research/threshold_transfer_tt1f_provics_mask_v1.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tt1_final as F
import tt1d_data as TD
import tt1d_data_v2 as TD2
import tt1d_final as M
import tt1d_provics_amendment1 as A1

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/research/threshold_transfer_tt1f_provics_mask_v1.json"
REASON = ("EXPLORATORY tt1f K2 (post-hoc after the registered tt1d final): ProvICS scored with the registered and "
          "the extended validity mask")
RULES = ["frozen", "tracker", "tighten_only", "tracker_capped", "tracker_ceil_1.25", "daily"]
S = M.SETUPS["provics"]


def gaps(valid):
    v = np.asarray(valid, bool)
    return int((v[:-1] & ~v[1:]).sum() + (not v[0]))


def main():
    reg = json.loads(M.result_path("provics").read_text(encoding="utf-8"))
    unit = reg["units"][0]
    TD._p_read = A1.read_filled                              # amendment 1 of tt1d: an empty cell repeats the previous row
    TD.provics_open_final(REASON)
    segs, _ = TD.provics_dev()
    parts = F.split(segs, F.FINAL_CUTS, ("fit", "scale", "calib"), min_len=500)
    score, cfgs, pooled, _ = M.fit_scores(S, parts["fit"], parts["scale"], parts["calib"])
    cfg = cfgs["D1"]
    want = unit["thresholds"]["D1"]
    if any(abs(cfg[k] - want[k]) > 1e-9 * max(1.0, abs(want[k])) for k in want):
        raise SystemExit(f"refitted thresholds differ from the registered ones: {cfg} vs {want}")
    x, u, valid, events, unobserved = TD.provics_attack()
    raw = score(x, u)["D1"]
    lab = np.zeros(len(x), bool)
    for e in events:
        lab[e[0]:e[1]] = True
    xs, us, vs = TD.provics_sealed()
    raw_s = score(xs, us)["D1"]
    lookback = TD2.score_lookback(S.window)
    out = {"schema_version": "threshold-transfer-tt1f-provics-mask-v1",
           "status": "exploratory, post-hoc: third, ledgered access to the ProvICS attack recording and sealed rows",
           "plan": "docs/research/threshold_transfer_tt1f_dev_plan.md (amendment 2, K2)",
           "lookback_steps": lookback, "events": len(events), "unobserved_events": int(unobserved), "masks": {}}
    for name, mask, mask_s in (("registered", valid, vs),
                               ("extended", TD2.extend_invalid(valid, lookback), TD2.extend_invalid(vs, lookback))):
        rows = M.stream_rows(S, M.clean(raw, mask), events, lab, cfg, pooled["D1"], RULES)
        if name == "registered":
            got, ref = rows["frozen"], unit["attack_runs"][0]["scores"]["D1"]["frozen"]
            if (got["found"], got["onset"], got["fa"]) != (ref["found"], ref["onset"], ref["fa"]):
                raise SystemExit("the registered frozen row is not reproduced")
        unl = int((~lab & mask).sum())
        clean_rows = M.clean_false_alarms(S, M.clean(raw_s, mask_s), cfg, pooled["D1"], RULES)
        days_s = int(np.asarray(mask_s, bool).sum()) / S.spd
        out["masks"][name] = {
            "attack_recording": {"invalid_steps": int((~np.asarray(mask, bool)).sum()), "gaps": gaps(mask),
                                 "unlabelled_valid_steps": unl,
                                 "rules": {r: {"detected": int(sum(v["found"])), "onset_detected": int(sum(v["onset"])),
                                               "fa_ratio_to_budget": v["fa"] / (unl / S.spd) / S.budget,
                                               "unlabelled_alarm_share": v["alarm_unlabelled"] / unl} for r, v in rows.items()}},
            "sealed_rows": {"invalid_steps": int((~np.asarray(mask_s, bool)).sum()), "gaps": gaps(mask_s),
                            "rules": {r: {"fa_ratio_to_budget": v["fa"] / days_s / S.budget, "alarm_steps": v["alarm_steps"]}
                                      for r, v in clean_rows.items()}}}
        for r in RULES:
            v = out["masks"][name]["attack_recording"]["rules"][r]
            print(f"{name:10s} {r:18s} any {v['detected']:2d} onset {v['onset_detected']:2d} fa x{v['fa_ratio_to_budget']:.1f} "
                  f"in alarm {100 * v['unlabelled_alarm_share']:.1f}%")
        print(name, "gaps", out["masks"][name]["attack_recording"]["gaps"], "invalid", out["masks"][name]["attack_recording"]["invalid_steps"],
              "| sealed gaps", out["masks"][name]["sealed_rows"]["gaps"], "frozen fa x",
              round(out["masks"][name]["sealed_rows"]["rules"]["frozen"]["fa_ratio_to_budget"], 2))
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print("written", OUT)


if __name__ == "__main__":
    main()
