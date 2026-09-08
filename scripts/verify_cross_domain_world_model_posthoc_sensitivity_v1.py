#!/usr/bin/env python3
"""Independently recompute the registered post-hoc sensitivity result."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_cross_domain_world_model_posthoc_sensitivity_v1 as analysis  # noqa: E402


PROTOCOL = analysis.PROTOCOL
RESULT = analysis.OUTPUT
VERIFICATION = ROOT / "docs/research/cross_domain_world_model_posthoc_sensitivity_verification_v1.json"


def canonical(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, default=RESULT)
    parser.add_argument("--output", type=Path, default=VERIFICATION)
    args = parser.parse_args()
    if not args.result.is_file():
        raise FileNotFoundError(args.result)
    protocol = analysis.load_json(PROTOCOL)
    recorded = analysis.load_json(args.result)
    recomputed = analysis.compute(protocol, recorded["protocol"]["registered_commit"])
    checks = {
        "protocol_digest_matches": recorded["protocol"]["sha256"] == analysis.sha256(PROTOCOL),
        "result_recomputes_exactly": canonical(recorded) == canonical(recomputed),
        "original_registered_result_retained": recorded["common_episode_horizon_analysis"][
            "original_registered_result_retained"
        ],
        "selection_or_training_unchanged": not recorded["common_episode_horizon_analysis"][
            "selection_or_training_changed"
        ],
        "common_proposal_full_arm_reproduced": all(
            recorded["attribution_diagnostics"]["common_proposal_warning_analysis"][
                "full_adapter_source_arm_reproduced"
            ].values()
        ),
        "simulator_not_executed": not recorded["authority"]["simulator_executed"],
        "no_retraining": not recorded["authority"]["models_or_adapters_retrained"],
        "no_promotion": not recorded["authority"]["promotion_eligible"],
        "zero_physical_actuation": recorded["authority"]["physical_actuator_attempts"]
        == recorded["authority"]["physical_actuator_deliveries"]
        == 0,
    }
    verification = {
        "schema": "cross-domain-world-model-posthoc-sensitivity-verification-v1",
        "result": {
            "path": args.result.relative_to(ROOT).as_posix(),
            "sha256": analysis.sha256(args.result),
        },
        "checks": checks,
        "all_checks_pass": all(checks.values()),
        "promotion_eligible": False,
    }
    if args.output.exists():
        existing = analysis.load_json(args.output)
        if existing != verification:
            raise FileExistsError(f"refusing to overwrite differing {args.output}")
    else:
        args.output.write_text(
            json.dumps(verification, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(verification, indent=2, sort_keys=True))
    return 0 if verification["all_checks_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
