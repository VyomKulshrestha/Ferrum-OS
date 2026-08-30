#!/usr/bin/env python3
"""Build a versioned Prediction Is Not Permission technical report."""

from __future__ import annotations

import argparse
from pathlib import Path

from build_world_model_technical_report_v1_2 import build


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "docs" / "research" / "paper" / "prediction_is_not_permission_technical_report_v1_0.md"
DEFAULT_OUTPUT = ROOT / "docs" / "research" / "paper" / "Prediction_Is_Not_Permission_Technical_Report_v1.0.pdf"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--version", default="1.0")
    parser.add_argument("--evidence-date", default="30 August 2026")
    args = parser.parse_args()
    build(
        args.source,
        args.output,
        pdf_title="Prediction Is Not Permission: Cross-Domain World Models Under Deterministic Runtime Authority",
        pdf_subject=f"Cross-domain world-model runtime authority Technical Report v{args.version}",
        pdf_keywords="world models, JEPA, GRU, FerrumOS, runtime assurance, cyber-physical systems, calibration",
        running_left="PREDICTION IS NOT PERMISSION",
        running_right=f"TECHNICAL REPORT v{args.version}",
        footer_note=f"Cross-domain world-model authority study - evidence frozen {args.evidence_date}",
        spacious_body=args.version == "1.0",
        compact_body=args.version != "1.0",
    )
    print(args.output)


if __name__ == "__main__":
    main()
