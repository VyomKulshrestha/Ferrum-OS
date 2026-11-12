#!/usr/bin/env python3
"""tw1a: write the Tennessee Eastman setup that the score-level harness needs, from the tt1d result and the
tt1f score cache: constants of the study, the registered placements, the events of the recorded attack runs and
the frozen threshold's stored outcomes. Opens no dataset. Run with the repository's base Python (the harness
itself runs in the tw1 environment, which lacks the tt1 dependencies).

    python scripts/tw1a_export_setup.py    ->    target/tw1/tep_setup.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import repro_env
import tt1d_data as TD
import tt1d_final as M
import tt1f_tep_dev as F

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "target/tw1/tep_setup.json"
S = M.SETUPS["tep59"]


def main():
    out = {
        "source": "docs/research/threshold_transfer_tt1d_result_tep59.json and target/real-telemetry/tt1f/mode_<m>.npz",
        "constants": {
            "step": S.step,
            "spd": S.spd,
            "gap": S.gap,
            "budget": S.budget,
            "lead": S.lead,
            "campaign": S.campaign,
            "terminal": S.terminal,
            "loud": list(S.loud),
            "subl": list(S.subl),
            "mags": list(M.MAGS),
            "frog_frac": M.FROG_FRAC,
        },
        "modes": {},
    }
    for u in F.registered()["units"]:
        mode = int(u["unit"].split("_")[1])
        cfg, pooled, sealed, attack = F.load(mode)
        out["modes"][str(mode)] = {
            "tau0": cfg["tau0"],
            "calibration_steps": int(len(pooled)),
            "sealed": [
                {
                    "name": r["name"],
                    "steps": int(len(sealed[r["name"]])),
                    "terminal_start": int(r["campaigns"][0]["terminal_start"]),
                }
                for r in u["sealed_runs"]
            ],
            "attack": [
                {
                    "name": r["name"],
                    "type": r["type"],
                    "steps": int(len(attack[r["name"]][0])),
                    "events": [
                        [int(a), int(b), int(k)]
                        for a, b, k in TD.events(attack[r["name"]][1])
                    ],
                    "frozen": {
                        k: r["scores"]["D1"]["frozen"][k]
                        for k in ("found", "onset", "fa", "alarm_unlabelled")
                    },
                }
                for r in u["attack_runs"]
            ],
        }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out), encoding="utf-8")
    repro_env.stamp_json(OUT)
    n = out["modes"]
    print(
        "written",
        OUT,
        "| modes",
        len(n),
        "| sealed",
        sum(len(v["sealed"]) for v in n.values()),
        "| attack runs",
        sum(len(v["attack"]) for v in n.values()),
    )


if __name__ == "__main__":
    repro_env.pin_from_environment()
    main()
