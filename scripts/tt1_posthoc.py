#!/usr/bin/env python3
"""Post-hoc checks promised by the tt1 protocol, run after the registered finals (ledgered as post-hoc).

hygrid-ics: attack contamination of the label-blind development portion (first 40% of rows), which
trained and calibrated the monitor. Writes docs/research/threshold_transfer_tt1_posthoc.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_telemetry_data as D
import tt1_data as TD

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/research/threshold_transfer_tt1_posthoc.json"


def hygrid_contamination():
    D._record_final_access("hygrid-ics", "post-hoc analysis after the registered tt1 final: attack contamination of the development portion")
    frame = TD._hygrid_frame(["Is_Attack"])
    cut = int(len(frame) * TD.HYGRID_DEV_FRACTION)
    dev, fin = frame["Is_Attack"].to_numpy()[:cut], frame["Is_Attack"].to_numpy()[cut:]
    runs = int(np.sum(np.diff(np.concatenate([[0], (dev > 0).astype(int)])) == 1))
    return {"development_rows": int(cut), "development_attack_fraction": float((dev > 0).mean()),
            "development_attack_runs": runs, "final_attack_fraction": float((fin > 0).mean())}


def main():
    out = {"schema_version": "threshold-transfer-tt1-posthoc", "status": "post-hoc, after the registered finals",
           "hygrid-ics": hygrid_contamination()}
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
