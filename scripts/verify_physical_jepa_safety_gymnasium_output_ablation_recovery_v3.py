#!/usr/bin/env python3
"""Verify the retained-catalog JEPA-output analysis portably and historically."""

from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import subprocess

import verify_physical_jepa_safety_gymnasium_output_ablation_recovery_v2 as v2


ROOT = Path(__file__).resolve().parents[1]
AMENDMENT_PATH = (
    ROOT
    / "docs/research/physical_jepa_safety_gymnasium_output_ablation_verification_amendment_v3.json"
)
PROTOCOL_PATH = v2.PROTOCOL_PATH
RECOVERY_RESULT_PATH = v2.RESULT_PATH
VERIFICATION_PATH = (
    ROOT
    / "docs/research/physical_jepa_safety_gymnasium_output_ablation_recovery_verification_v3.json"
)
REPORT_PDF = Path(
    "docs/research/paper/Prediction_Is_Not_Permission_Technical_Report_v1.1.pdf"
)
TEXT_SUFFIXES = {".json", ".md", ".py"}


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def portable_text_sha256(path: Path) -> str:
    normalized = (
        path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def text_digest_matches(path: Path, expected: str) -> bool:
    normalized = (
        path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    )
    candidates = {
        hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        hashlib.sha256(normalized.replace("\n", "\r\n").encode("utf-8")).hexdigest(),
    }
    return expected in candidates


def git_blob(commit: str, path: Path) -> bytes:
    relative = path.relative_to(ROOT).as_posix()
    return subprocess.check_output(["git", "show", f"{commit}:{relative}"], cwd=ROOT)


def main() -> None:
    amendment = v2.load_json(AMENDMENT_PATH)
    protocol = v2.load_json(PROTOCOL_PATH)
    recovery_result = v2.load_json(RECOVERY_RESULT_PATH)
    registered_commit = recovery_result["protocol"]["registered_commit"]

    historical_report_digest = hashlib.sha256(
        git_blob(registered_commit, ROOT / REPORT_PDF)
    ).hexdigest()
    expected_text_digests = {
        Path(record["path"]): record["sha256"]
        for group in ("registered_inputs", "toolchain")
        for record in protocol[group].values()
    }
    expected_text_digests.update(
        {
            Path(protocol["frozen_warning_pipeline"]["adapter"]["path"]): protocol[
                "frozen_warning_pipeline"
            ]["adapter"]["sha256"],
            PROTOCOL_PATH.relative_to(ROOT): recovery_result["protocol"]["sha256"],
            **{
                Path(record["path"]): record["sha256"]
                for record in protocol["protected_files"].values()
                if Path(record["path"]).suffix.lower() in TEXT_SUFFIXES
            },
        }
    )

    def registered_sha256(path: Path) -> str:
        relative = path.relative_to(ROOT)
        if relative == REPORT_PDF:
            return historical_report_digest
        if path.suffix.lower() in TEXT_SUFFIXES:
            expected = expected_text_digests.get(relative)
            if expected is not None and text_digest_matches(path, expected):
                return expected
            return portable_text_sha256(path)
        return raw_sha256(path)

    original_sha256 = v2.sha256
    original_verification_path = v2.VERIFICATION_PATH
    try:
        v2.sha256 = registered_sha256
        v2.VERIFICATION_PATH = VERIFICATION_PATH
        with redirect_stdout(io.StringIO()):
            v2.main()
    finally:
        v2.sha256 = original_sha256
        v2.VERIFICATION_PATH = original_verification_path

    base = v2.load_json(VERIFICATION_PATH)
    checks = dict(base["checks"])
    renamed = {
        "technical_report_v1_1_pdf_at_recovery_registration_matches_recovery_registration":
            "technical_report_v1_1_pdf_registered_blob_matches_recovery_registration",
        "technical_report_v1_1_pdf_at_recovery_registration_before_after_current_identical":
            "technical_report_v1_1_pdf_before_after_registered_blob_identical",
    }
    for old, new in renamed.items():
        checks[new] = checks.pop(old)

    checks["historical_report_snapshot_matches"] = historical_report_digest == protocol[
        "protected_files"
    ]["technical_report_v1_1_pdf_at_recovery_registration"]["sha256"]
    checks["portable_text_digest_policy_applied"] = amendment["digest_policy"][
        "text_compatibility"
    ] == "Compare semantic UTF-8 text after newline normalization against both LF and CRLF historical SHA-256 representations"
    checks["amendment_toolchain_digests_match"] = all(
        text_digest_matches(ROOT / record["path"], record["sha256"])
        for record in amendment["toolchain"].values()
    )
    checks["failed_v1_not_reclassified_as_success"] = (
        recovery_result["execution_evidence"]["source_failed_attempt"]
        == protocol["registered_inputs"]["failed_attempt"]
        and recovery_result["execution_evidence"]["simulator_rerun_during_recovery"]
        is False
        and amendment["interpretation"]["prospective_v1_execution_status"] == "failed"
    )

    current_protected = {}
    for name, record in protocol["protected_files"].items():
        path = ROOT / record["path"]
        current_digest = raw_sha256(path)
        current_protected[name] = {
            "current_sha256": current_digest,
            "registration_sha256": record["sha256"],
            "matches_registration": current_digest == record["sha256"],
            "text_content_matches_registration": (
                text_digest_matches(path, record["sha256"])
                if path.suffix.lower() in TEXT_SUFFIXES
                else None
            ),
        }

    all_checks_pass = all(checks.values())
    verification = {
        **base,
        "schema": "physical-jepa-safety-gymnasium-output-ablation-recovery-verification-v3",
        "verification_amendment": {
            "path": AMENDMENT_PATH.relative_to(ROOT).as_posix(),
            "sha256": portable_text_sha256(AMENDMENT_PATH),
        },
        "checks": checks,
        "all_checks_pass": all_checks_pass,
        "diagnostics": {
            "registered_commit": registered_commit,
            "historical_report_sha256": historical_report_digest,
            "current_protected_files": current_protected,
            "current_report_drift_is_non_failing": True,
        },
        "interpretation": amendment["interpretation"],
        "claim_boundary": amendment["claim_boundary"],
    }
    VERIFICATION_PATH.write_text(
        json.dumps(verification, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(verification, indent=2, sort_keys=True))
    if not all_checks_pass:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
