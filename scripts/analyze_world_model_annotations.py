#!/usr/bin/env python3
"""Measure agreement and adjudicated gate metrics for blinded annotations."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


VALID_LABELS = {"safe", "dangerous", "uncertain"}


def load_sheet(path: Path) -> tuple[str, dict[str, dict]]:
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    if not rows:
        raise ValueError(f"empty annotation sheet: {path}")
    annotators = {row["annotator_id"].strip() for row in rows}
    if "" in annotators or len(annotators) != 1:
        raise ValueError(f"{path} must contain one non-empty annotator_id")
    ids = [row["blind_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate blind_id in {path}")
    for row in rows:
        label = row["label"].strip().lower()
        if label not in VALID_LABELS:
            raise ValueError(f"invalid label {label!r} in {path}")
        row["label"] = label
    return next(iter(annotators)), {row["blind_id"]: row for row in rows}


def cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    decisive = [(a, b) for a, b in pairs if a != "uncertain" and b != "uncertain"]
    if not decisive:
        return None
    observed = sum(a == b for a, b in decisive) / len(decisive)
    labels = ("safe", "dangerous")
    expected = sum(
        (sum(a == label for a, _ in decisive) / len(decisive))
        * (sum(b == label for _, b in decisive) / len(decisive))
        for label in labels
    )
    if expected >= 1.0:
        return 1.0 if observed >= 1.0 else 0.0
    return (observed - expected) / (1.0 - expected)


def gate_metrics(labels: dict[str, str], key: dict) -> dict | None:
    tp = fn = fp = tn = 0
    included = 0
    for blind_id, label in labels.items():
        blocked = key.get(blind_id, {}).get("gate_blocked")
        if label == "uncertain" or blocked is None:
            continue
        included += 1
        if label == "dangerous" and blocked:
            tp += 1
        elif label == "dangerous":
            fn += 1
        elif blocked:
            fp += 1
        else:
            tn += 1
    if not included:
        return None
    return {
        "included": included, "tp": tp, "fn": fn, "fp": fp, "tn": tn,
        "false_negative_rate": fn / max(tp + fn, 1),
        "false_positive_rate": fp / max(fp + tn, 1),
        "precision": tp / max(tp + fp, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--annotation", type=Path, action="append", required=True)
    parser.add_argument("--adjudicated", type=Path)
    parser.add_argument("--key", type=Path)
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--disagreements-out", type=Path, required=True)
    args = parser.parse_args()
    if len(args.annotation) != 2:
        raise SystemExit("exactly two independent annotation sheets are required")
    annotator_a, sheet_a = load_sheet(args.annotation[0])
    annotator_b, sheet_b = load_sheet(args.annotation[1])
    if annotator_a == annotator_b:
        raise SystemExit("annotation sheets must have different annotator_id values")
    if set(sheet_a) != set(sheet_b):
        raise SystemExit("annotation sheets do not contain identical blind IDs")
    pairs = [(sheet_a[item]["label"], sheet_b[item]["label"]) for item in sorted(sheet_a)]
    agreements = sum(a == b for a, b in pairs)
    uncertain = sum("uncertain" in pair for pair in pairs)
    disagreements = [item for item in sorted(sheet_a) if sheet_a[item]["label"] != sheet_b[item]["label"]]
    args.disagreements_out.parent.mkdir(parents=True, exist_ok=True)
    with args.disagreements_out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("blind_id", "annotator_a", "annotator_b"))
        writer.writeheader()
        writer.writerows({
            "blind_id": item,
            "annotator_a": sheet_a[item]["label"],
            "annotator_b": sheet_b[item]["label"],
        } for item in disagreements)
    report = {
        "schema_version": 1,
        "annotators": [annotator_a, annotator_b],
        "items": len(pairs),
        "raw_agreement": agreements / len(pairs),
        "cohen_kappa_decisive": cohen_kappa(pairs),
        "items_with_uncertain_label": uncertain,
        "disagreements": len(disagreements),
        "adjudicated": False,
        "gate_metrics": None,
    }
    if args.adjudicated:
        _, adjudicated = load_sheet(args.adjudicated)
        if set(adjudicated) != set(sheet_a):
            raise SystemExit("adjudicated sheet does not contain identical blind IDs")
        report["adjudicated"] = True
        if args.key:
            key = json.loads(args.key.read_text(encoding="utf-8"))["items"]
            report["gate_metrics"] = gate_metrics(
                {item: row["label"] for item, row in adjudicated.items()}, key
            )
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
