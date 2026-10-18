#!/usr/bin/env python3
"""Build the cross-domain v1.2 report with its own metadata, layout and numbered table captions."""
from pathlib import Path

from build_prediction_report_layout_v1_2 import build


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    build(
        root / "docs/research/paper/prediction_is_not_permission_technical_report_v1_2.md",
        root / "docs/research/paper/Prediction_Is_Not_Permission_Technical_Report_v1.2.pdf",
        pdf_title="Prediction Is Not Permission: Cross-Domain World Models Under Deterministic Runtime Authority",
        pdf_subject="Cross-domain world-model runtime authority Technical Report v1.2",
        pdf_keywords="FerrumOS, Physical JEPA, world models, runtime authority, incident-motivated dynamics, gradient-boosted residuals, calibration",
        running_left="PREDICTION IS NOT PERMISSION",
        running_right="TECHNICAL REPORT v1.2",
        footer_note="Cross-domain world-model evidence - frozen 19 October 2026",
        spacious_body=True,
        editorial_layout=True,
    )
