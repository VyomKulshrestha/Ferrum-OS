"""Exact version of the attribution threshold rule (fi1 pipeline round 2, finding P1).

`prepare_physical_jepa_safety_gymnasium_attribution_v1.choose_threshold` registers the rule "match the full
adapter's validation FPR, then fewer false negatives, then the higher threshold". It sorts on the float
`abs(fpr - target)`. When two candidates sit the same number of false positives above and below the target
(13/3471 and 15/3471 against 14/3471), float rounding makes the lower one look closer by about 4e-17, so
the false-negative tie-break never runs. This module applies the same rule with exact fractions. The
registered thresholds (protocol v1/v2 of the attribution study) stay as they are; seeds 8000-8127 are spent.
"""

from __future__ import annotations

from fractions import Fraction

import numpy as np

GRID = np.linspace(0.001, 0.999, 999)


def counts(labels: np.ndarray, values: np.ndarray, threshold: float) -> dict:
    predicted = values >= threshold
    positive = labels.astype(bool)
    return {
        "threshold": float(threshold),
        "tp": int(np.sum(predicted & positive)),
        "fp": int(np.sum(predicted & ~positive)),
        "fn": int(np.sum(~predicted & positive)),
        "tn": int(np.sum(~predicted & ~positive)),
    }


def choose_threshold_exact(
    labels: np.ndarray, values: np.ndarray, target_fp: int, target_negatives: int
) -> dict:
    """Registered rule with the FPR distance computed as an exact fraction."""
    target = Fraction(target_fp, target_negatives)
    rows = [counts(labels, values, float(t)) for t in GRID]
    rows.sort(
        key=lambda r: (
            abs(Fraction(r["fp"], max(1, r["fp"] + r["tn"])) - target),
            r["fn"],
            -r["threshold"],
        )
    )
    return rows[0]


def choose_threshold_float(
    labels: np.ndarray, values: np.ndarray, target_fpr: float
) -> dict:
    """The registered v1 sort key, kept for comparison (same candidates, float distance)."""
    rows = [counts(labels, values, float(t)) for t in GRID]
    for r in rows:
        r["false_positive_rate"] = r["fp"] / max(1, r["fp"] + r["tn"])
    rows.sort(
        key=lambda r: (
            abs(r["false_positive_rate"] - target_fpr),
            r["fn"],
            -r["threshold"],
        )
    )
    return rows[0]
