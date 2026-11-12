#!/usr/bin/env python3
"""Compare results regenerated at different BLAS thread counts with the committed ones (fi1 B3).

Exploratory. Reads committed result files and regenerated copies under target/fi1-pipeline3/;
writes nothing in docs/. Each ``study_*`` function returns, per thread count and run, the largest
relative change of any numeric leaf against the committed file, every gate or selection with its
value, threshold and margin, and whether it flips.

    python scripts/fi1_thread_compare.py robustness
    python scripts/fi1_thread_compare.py sweep
    python scripts/fi1_thread_compare.py os-world-model
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "docs" / "research"
WORK = ROOT / "target" / "fi1-pipeline3"


def load(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def numeric_leaves(a, b, path=""):
    """Yield (path, a, b) for every leaf where both sides are numbers or where they differ."""
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            yield from numeric_leaves(a.get(key), b.get(key), f"{path}/{key}")
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for index, (left, right) in enumerate(zip(a, b)):
            yield from numeric_leaves(left, right, f"{path}[{index}]")
    else:
        yield path, a, b


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def relative(a: float, b: float) -> float:
    if a == b:
        return 0.0
    scale = max(abs(a), abs(b))
    return abs(a - b) / scale if scale else 0.0


def diff_summary(produced, committed, ignore=()) -> dict:
    """Largest relative change of a numeric leaf, and counts of differing leaves."""
    changed, other, largest = 0, [], (0.0, None, None, None)
    total = 0
    for path, a, b in numeric_leaves(produced, committed):
        if any(token in path for token in ignore):
            continue
        if is_number(a) and is_number(b):
            total += 1
            if a != b:
                changed += 1
                r = relative(a, b)
                if r > largest[0]:
                    largest = (r, path, a, b)
        elif a != b:
            other.append({"path": path, "produced": a, "committed": b})
    return {
        "numeric_leaves": total,
        "numeric_leaves_changed": changed,
        "largest_relative_change": largest[0],
        "largest_at": largest[1],
        "largest_produced": largest[2],
        "largest_committed": largest[3],
        "non_numeric_differences": other[:20],
        "non_numeric_differences_count": len(other),
    }


def gate(name, value, threshold, op, kind="gate") -> dict:
    """A comparison ``value op threshold`` with its margin (positive = passes)."""
    if op == "<":
        passed, margin = value < threshold, threshold - value
    elif op == "<=":
        passed, margin = value <= threshold, threshold - value
    elif op == ">":
        passed, margin = value > threshold, value - threshold
    elif op == ">=":
        passed, margin = value >= threshold, value - threshold
    elif op == "==":
        passed, margin = value == threshold, None
    else:
        raise ValueError(op)
    relative_margin = None
    if margin is not None and is_number(threshold) and threshold not in (0, 0.0):
        relative_margin = margin / abs(threshold)
    return {
        "name": name,
        "kind": kind,
        "value": value,
        "op": op,
        "threshold": threshold,
        "passed": bool(passed),
        "margin": margin,
        "relative_margin": relative_margin,
    }


def runs(folder: Path, pattern: str):
    """{label: path} for files t<threads>_<run>.json, sorted by thread count."""
    found = {}
    for path in sorted(folder.glob(pattern)):
        label = path.stem
        found[label] = path
    return dict(
        sorted(
            found.items(), key=lambda item: (int(item[0][1:].split("_")[0]), item[0])
        )
    )


def flips(table: dict, committed_label: str = "committed") -> list:
    """Gates whose pass/fail differs from the committed run."""
    reference = {g["name"]: g["passed"] for g in table[committed_label]["gates"]}
    out = []
    for label, row in table.items():
        if label == committed_label:
            continue
        for g in row["gates"]:
            if g["name"] in reference and g["passed"] != reference[g["name"]]:
                out.append(
                    {"run": label, **g, "committed_passed": reference[g["name"]]}
                )
    return out


def closest(table: dict) -> dict:
    """Per gate, the smallest relative margin over all runs (including the committed one)."""
    best = {}
    for label, row in table.items():
        for g in row["gates"]:
            m = g["relative_margin"]
            if m is None:
                continue
            if g["name"] not in best or m < best[g["name"]]["relative_margin"]:
                best[g["name"]] = {"run": label, **g}
    return best


# --------------------------------------------------------------------------------------------
# Physical-JEPA robustness evaluator


def robustness_gates(report: dict, rules_only_rare_fn: int) -> list:
    points = report["data_scaling"]["points"]
    return [
        gate(
            "counterfactual_directional_accuracy_at_least_95_percent",
            report["context_counterfactuals"]["directional_accuracy"],
            0.95,
            ">=",
        ),
        gate(
            "rare_hazard_false_negatives_below_rules_only",
            report["rare_hazards"]["rules_plus_jepa"]["fn"],
            rules_only_rare_fn,
            "<",
        ),
        gate(
            "data_scaling_final_h3_below_smallest_data_h3",
            points[-1]["validation_h3"],
            points[0]["validation_h3"],
            "<",
        ),
        gate(
            "all_held_out_predictions_finite",
            report["held_out"]["all_predictions_finite"],
            True,
            "==",
        ),
        # Checks of verify_physical_jepa_robustness.py that read values a rerun can change.
        gate(
            "verifier: OOD rules_plus_jepa fn > 0",
            report["out_of_distribution"]["rules_plus_jepa"]["fn"],
            0,
            ">",
            kind="verifier",
        ),
        # Claims the reports make from this file (comparisons, not registered gates).
        gate(
            "claim: matched autoencoder test h3 above deployed JEPA held-out h3",
            report["matched_autoencoder"]["test_rollout"]["h3"],
            report["held_out"].get("rollout_h3", float("nan")),
            ">",
            kind="claim",
        )
        if "rollout_h3" in report["held_out"]
        else None,
        *[
            gate(
                f"claim: data scaling h3 decreases from {points[i]['episodes']} to "
                f"{points[i + 1]['episodes']} episodes",
                points[i + 1]["validation_h3"],
                points[i]["validation_h3"],
                "<",
                kind="claim",
            )
            for i in range(len(points) - 1)
        ],
    ]


def rules_only_rare_false_negatives() -> int:
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    import train_physical_jepa as jepa
    import train_physical_world_model as simulator

    rows = simulator.generate(2500, 6, 42)
    _, _, _, _, test_rows = jepa.split_rows(rows, 2500, 42)
    rare = [row for row in test_rows if row[6]]
    return simulator.confusion(
        rare, lambda row: simulator.rules_block(row[2], row[3], row[4])
    )["fn"]


def study_robustness() -> dict:
    committed_path = RESEARCH / "physical_jepa_robustness.json"
    committed = load(committed_path)
    rules_fn = rules_only_rare_false_negatives()
    table = {
        "committed": {
            "gates": [g for g in robustness_gates(committed, rules_fn) if g],
            "passed": committed["passed"],
        }
    }
    folder = WORK / "robustness"
    bit_identical = {}
    for label, path in runs(folder, "t*_run*.json").items():
        report = load(path)
        row = {
            "file": path.relative_to(ROOT).as_posix(),
            "passed": report["passed"],
            "stored_gates": report["gates"],
            "gates": [g for g in robustness_gates(report, rules_fn) if g],
            "identical_to_committed": json.dumps(report, sort_keys=True)
            == json.dumps(committed, sort_keys=True),
            "diff": diff_summary(report, committed),
        }
        table[label] = row
    for label in table:
        if label.endswith("_run2"):
            first = label.replace("_run2", "_run1")
            if first in table:
                bit_identical[label.split("_")[0]] = sha256(
                    WORK / "robustness" / f"{first}.json"
                ) == sha256(WORK / "robustness" / f"{label}.json")
    return {
        "study": "physical_jepa_robustness",
        "committed_file": "docs/research/physical_jepa_robustness.json",
        "rules_only_rare_false_negatives": rules_fn,
        "runs": table,
        "repeat_runs_bit_identical": bit_identical,
        "flips": flips(table),
        "closest": closest(table),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", choices=["robustness", "sweep", "os-world-model"])
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.study == "robustness":
        result = study_robustness()
    elif args.study == "sweep":
        import fi1_thread_sweep_compare as sweep  # noqa: PLC0415

        result = sweep.study_sweep()
    else:
        import fi1_thread_os_world_model as oswm  # noqa: PLC0415

        result = oswm.study_os_world_model()
    text = json.dumps(result, indent=2, sort_keys=True, default=_default) + "\n"
    out = args.out or WORK / f"compare_{args.study}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    print(text if len(text) < 20000 else f"wrote {out}")


def _default(value):
    if isinstance(value, float) and math.isnan(value):
        return None
    raise TypeError(type(value))


if __name__ == "__main__":
    main()
