#!/usr/bin/env python3
"""tt1d, amendment 1 (2026-11-10): the ProvICS final with missing register values filled.

    python scripts/tt1d_provics_amendment1.py

The registered final (scripts/tt1d_final.py final provics) stopped with an error while scoring the sealed
attack-free rows, before any result was printed or written: one sealed row has no value for the nine
setpoint registers, and the monitor does not accept missing values. docs/research/
threshold_transfer_tt1d_amendment_1.md records the failure and this change.

The change: a register with no value in a row repeats its previous value (leading gaps take the next
value). This is the registered loader's rule for an empty grid step, applied to an empty cell. Nothing
else changes: this script imports the frozen harness and loader unmodified, wraps the loader's file reader
with the fill, and runs the registered pipeline once. It refuses if a frozen file differs from the
registration or if a result file already exists.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tt1d_data as TD
import tt1d_final as M

FILLED = {}
_read = TD._p_read


def read_filled(path, first=None, skip=0):
    seconds, values, names = _read(path, first=first, skip=skip)
    frame = pd.DataFrame(values)
    missing = int(frame.isna().to_numpy().sum())
    if missing:
        values = frame.ffill().bfill().to_numpy(np.float32)
        FILLED[f"{Path(path).parent.name}/{Path(path).name} (rows after {skip})"] = missing
    return seconds, values, names


def main():
    name = "provics"
    S = M.SETUPS[name]
    bad = M.check_frozen()
    if bad:
        raise SystemExit(f"REFUSE: frozen files changed or protocol missing: {bad}")
    out_path = M.result_path(name)
    if out_path.exists():
        raise SystemExit(f"REFUSE: {out_path} exists")
    TD._p_read = read_filled
    TD.provics_open_final("tt1d final attempt 2 under amendment 1 (a missing register value repeats the previous row); "
                          "attempt 1 stopped with an error before any result was printed or written")
    out = M.assemble(S, [M.provics_unit(S, True)], "final")
    out["frozen_file_sha256"] = M.digests()
    out["resumed"] = False
    here = Path(__file__).resolve()
    out["amendment"] = {"id": 1, "document": "docs/research/threshold_transfer_tt1d_amendment_1.md",
                        "script": "scripts/tt1d_provics_amendment1.py",
                        "script_sha256": hashlib.sha256(here.read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
                        "filled_cells": FILLED}
    out_path.write_text(json.dumps({"schema_version": "threshold-transfer-tt1d-result", "protocol": M.PROTOCOL.name, **out},
                                   indent=1) + "\n", encoding="utf-8")
    M.show(out)
    print("filled cells", FILLED)
    print("wrote", out_path)


if __name__ == "__main__":
    main()
