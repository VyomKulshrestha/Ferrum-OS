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
    import fi1_thread_compare as compare
    import verify_cross_domain_archived_inference_v1_2 as verifier

    # The verifier compares records as canonical JSON, recomputed first, stored second; keep both.
    seen = []
    original_canonical = verifier.canonical

    def capturing(record):
        seen.append(record)
        return original_canonical(record)

    verifier.canonical = capturing
    start = time.time()
    try:
        report = verifier.verify()
        outcome = {
            "all_checks_pass": report["all_checks_pass"],
            "checks": report["checks"],
        }
    except AssertionError as error:
        outcome = {"all_checks_pass": False, "error": str(error)}
    labels = [
        "ferrumos_original_domain_record",
        "ferrumos_common_episode_record",
        "physical_original_domain_record",
        "physical_common_episode_record",
        "attribution_diagnostics",
    ]
    outcome["differences"] = {
        label: compare.diff_summary(seen[2 * i], seen[2 * i + 1])
        for i, label in enumerate(labels)
        if 2 * i + 1 < len(seen)
    }
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
