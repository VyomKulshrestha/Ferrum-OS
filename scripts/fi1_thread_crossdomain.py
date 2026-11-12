#!/usr/bin/env python3
"""Cross-domain study: do the archived-inference recomputations hold at other thread counts?

Exploratory (fi1 B3). Runs ``verify_cross_domain_archived_inference_v1_2.verify`` unchanged (read-only;
it restores the base dataset into a temporary folder and compares every historical domain record,
common-episode record and attribution diagnostic by canonical JSON equality) with torch and BLAS
pinned to ``--threads``; the verifier's own ``torch.set_num_threads(16)`` is neutralised. Writes
target/fi1-pipeline3/crossdomain_t<threads>.json.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import repro_env  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threads", type=int, required=True)
    args = parser.parse_args()
    import torch

    repro_env.pin_threads(args.threads, torch_import=True)
    torch.set_num_threads = lambda n: None
    import verify_cross_domain_archived_inference_v1_2 as verifier

    start = time.time()
    try:
        report = verifier.verify()
        outcome = {
            "all_checks_pass": report["all_checks_pass"],
            "checks": report["checks"],
        }
    except AssertionError as error:
        outcome = {"all_checks_pass": False, "error": str(error)}
    outcome.update(
        {
            "threads": args.threads,
            "seconds": round(time.time() - start, 1),
            "environment": repro_env.environment_record(),
        }
    )
    out = ROOT / "target" / "fi1-pipeline3" / f"crossdomain_t{args.threads}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(outcome, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in outcome.items() if k != "environment"}))


if __name__ == "__main__":
    main()
