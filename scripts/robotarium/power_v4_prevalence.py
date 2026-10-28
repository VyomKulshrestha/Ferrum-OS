#!/usr/bin/env python3
"""EXPLORATORY power check for protocol v4 at the sealed seeds' simulated hazard rate. Branch work, not main.

The official simulator predicts each seed's hazard rate closely (study B: simulated 0.193, real
0.191; study v2: 0.177 vs 0.173). Seeds 801-816 simulate at 0.103 and 801-824 at 0.124, against
0.198 on the spent runs, so the dev check's power (drawn from all spent runs) is too high for them.
This re-draws sealed sets only from the k spent runs with the fewest hazards, so the pool's mean
hazard rate matches the sealed seeds, using the out-of-fold scores and per-batch thresholds saved
by dev_tracking_v4.py. Biased (selecting runs on their labels), so a rough guide only.
Output docs/research/vision_caution_v4_power_prevalence_v1.json. Not evidence.

Usage: python scripts/robotarium/power_v4_prevalence.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(HERE))

import dev_tracking_v4 as DT  # noqa: E402

OUT = ROOT / "docs/research/vision_caution_v4_power_prevalence_v1.json"
POOLS = (12, 15, 18, 20, 21, 22)
DT.N_SET = (6, 8, 10, 12, 14, 16, 17)


def main():
    z = np.load(DT.SCORES)
    D = {k: z[k] for k in z.files}
    runs = sorted(set(D["run"]))
    prev = {n: float(D["y"][D["run"] == n].mean()) for n in runs}
    order = sorted(runs, key=lambda n: prev[n])
    res = {}
    for k in POOLS:
        sub = order[:k]
        pw = DT.power(D, "trackB_plain", 0.05, sub)
        res[f"lowest_{k}"] = {"mean_prevalence": float(np.mean([prev[n] for n in sub])), "runs": sub,
                              "by_runs": {N: {"G1_and_G2": r["G1_and_G2"], "G1_G2_G3_floor_0.30": r["G1_G2_and_recall_lo_ge_0.30"],
                                              "median_recall": r["median_recall"], "median_fpr": r["median_fpr"]}
                                          for N, r in pw.items()}}
        print(f"lowest {k} runs (mean prevalence {res[f'lowest_{k}']['mean_prevalence']:.3f}): " + " ".join(
            f"N={N}: {v['G1_G2_G3_floor_0.30']:.2f}" for N, v in res[f"lowest_{k}"]["by_runs"].items()), flush=True)
    OUT.write_text(json.dumps({"schema_version": "vision-caution-v4-power-prevalence-v1",
                               "status": "EXPLORATORY, biased (pools chosen by their labels); rough guide to G3 power at the "
                                         "sealed seeds' simulated hazard rate; not evidence",
                               "simulated_prevalence": {"seeds_801_816": 0.103, "seeds_801_824": 0.124, "spent_runs_real": 0.198},
                               "arm": "trackB_plain", "q": 0.05, "draws": DT.DRAWS, "inner_bootstrap": DT.INNER,
                               "pools": res}, indent=1) + "\n", encoding="utf-8")
    print("wrote", OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
