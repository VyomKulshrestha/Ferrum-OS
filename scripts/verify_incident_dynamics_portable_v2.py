#!/usr/bin/env python3
"""Recompute frozen v2 evidence without rewriting its registered verifier.

The original verifier compares its entire output record byte-digest field with
the retained report. Git can change JSON LF/CRLF encoding on checkout. This
wrapper applies the protocol's existing metadata equivalence rule only to that
field; every scientific check and every recomputed metric must remain exact.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile

import torch

import run_incident_dynamics_study as study


def verify():
    study.VERSION = 2
    study.PROTOCOL = study.ROOT / "docs/research/incident_dynamics_protocol_v2.json"
    study.ARTIFACTS = study.ROOT / "docs/research/artifacts/incident-dynamics-v2"
    study.SELECTION = study.ROOT / "docs/research/incident_dynamics_selection_v2.json"
    study.RESULT = study.ROOT / "docs/research/incident_dynamics_result_v2.json"
    retained_path = study.ROOT / "docs/research/incident_dynamics_verification_v2.json"
    retained = study.architecture.load_json(retained_path)
    torch.set_num_threads(4)
    with tempfile.TemporaryDirectory(prefix="incident-dynamics-verification-") as temporary:
        study.VERIFICATION = Path(temporary) / "recomputed.json"
        with redirect_stdout(io.StringIO()):
            study.verify()
        recomputed = study.architecture.load_json(study.VERIFICATION)
    if not study.record_matches(retained["result"]):
        raise AssertionError("retained result digest is not LF/CRLF-equivalent")
    if recomputed["result"]["path"] != retained["result"]["path"]:
        raise AssertionError("retained result path differs")
    recomputed_without_digest = dict(recomputed)
    retained_without_digest = dict(retained)
    recomputed_without_digest.pop("result")
    retained_without_digest.pop("result")
    if recomputed_without_digest != retained_without_digest:
        raise AssertionError("scientific verification differs from retained report")
    if not recomputed["all_checks_pass"]:
        raise AssertionError("scientific audit failed")
    return {
        "study_id": "incident-dynamics-v2",
        "all_checks_pass": True,
        "scientific_checks": len(recomputed["checks"]),
        "scientific_report_exact_match": True,
        "result_metadata_lf_crlf_equivalent": True,
        "retained_result_sha256": retained["result"]["sha256"],
        "checkout_result_sha256": recomputed["result"]["sha256"],
        "verification_mode": recomputed["verification_mode"],
        "promotion_eligible": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify()
    if args.output:
        study.json_write_once(args.output, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
