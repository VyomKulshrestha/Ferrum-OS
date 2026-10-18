#!/usr/bin/env python3
"""Incident-dynamics v4: a registered successor to the failed v3 primary rule.

Reuses the frozen v3 runner unchanged (so the v3 selection, result and verification remain
reproducible) and only redirects its protocol, output paths and source bindings. v4 opens fresh
populations A and B; the v3 final populations are already opened and are never used for selection.
"""
import argparse

import run_incident_dynamics_v3_study as study

ROOT = study.ROOT
study.PROTOCOL = ROOT / "docs/research/incident_dynamics_protocol_v4.json"
study.ARTIFACTS = ROOT / "docs/research/artifacts/incident-dynamics-v4"
study.SELECTION = ROOT / "docs/research/incident_dynamics_selection_v4.json"
study.RESULT = ROOT / "docs/research/incident_dynamics_result_v4.json"
study.VERIFICATION = ROOT / "docs/research/incident_dynamics_verification_v4.json"
study.CODE = [*study.CODE, "scripts/run_incident_dynamics_v4_study.py", "docs/research/incident_dynamics_protocol_v3.json",
              "docs/research/incident_dynamics_result_v3.json"]


_archive_checkpoint = study.archive_checkpoint


def archive_checkpoint(domain, checkpoint):
    """Reuse a v3 compact archive when the development checkpoint is byte-identical to one v3 archived."""
    import hashlib
    import json
    import numpy as np
    import incident_dynamics_v3_gbr as gbr
    if checkpoint.suffix == ".gbr":
        digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
        v3_selection = json.loads((ROOT / "docs/research/incident_dynamics_selection_v3.json").read_text(encoding="utf-8"))
        for item in v3_selection["domains"][domain]["pipelines"].values():
            for member in item.get("members", []):
                stored = member["checkpoint"]
                if stored.get("uncompressed_sha256") == digest and (ROOT / stored["path"]).exists():
                    probe = study.dev.load(domain, "mech_validation", gbr.load_any(checkpoint).history)
                    if not np.array_equal(gbr.load_any(checkpoint).predict(probe), gbr.load_path(ROOT / stored["path"]).predict(probe)):
                        raise AssertionError("v3 archive changed predictions")
                    if not study.record_matches(stored):
                        raise AssertionError("v3 archive drift")
                    return {**stored, "reused_from": "incident-dynamics-v3 selection archive"}
    return _archive_checkpoint(domain, checkpoint)


study.archive_checkpoint = archive_checkpoint


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["select", "final", "verify"])
    args = parser.parse_args()
    {"select": study.select, "final": study.final, "verify": study.verify}[args.stage]()


if __name__ == "__main__":
    main()
