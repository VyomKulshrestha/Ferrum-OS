#!/usr/bin/env python3
"""Select a world-model representation from comparable held-out metrics.

JEPA is a candidate, not an automatic upgrade. This gate requires the baseline
and candidate transition models to use the same split and rejects a candidate
that regresses any critical one-step or rollout metric beyond tolerance. Since
AE and JEPA coordinates have different scale, every cross-representation error
is first normalized by the same held-out split's zero-delta baseline. It writes
an auditable decision; copying the selected weight pair remains explicit.
"""
import argparse
import json
import math
import sys


def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def metric_values(report):
    if int(report.get("schema_version", 0)) < 4:
        raise ValueError(
            "transition metrics predate scale-normalized representation comparison; retrain with schema v4"
        )
    rollout = report.get("rollout", {})
    return {
        # AE and JEPA latent coordinates have different variance.  Raw MSE
        # across those spaces is meaningless: a representation could appear
        # better merely by shrinking every coordinate.  Normalize each error
        # by the same split's zero-delta error before cross-representation
        # comparison.  Core features are normalized for one consistent rule.
        "one_step_relative_error": float(report["normalized_mse"]),
        "core_feature_relative_error": float(report["normalized_core_mse"]),
        "macro_tool_relative_error": float(report["normalized_macro_tool_mse"]),
        "rollout_h3_relative_error": float(rollout["3"]["normalized_mse"]),
        "rollout_h5_relative_error": float(rollout["5"]["normalized_mse"]),
    }


def representation_mismatches(candidate, representation):
    fields = ("rows", "test_rows", "split_mode", "split_seed", "dataset_fingerprint")
    return [
        key for key in fields
        if not candidate.get(key) or candidate.get(key) != representation.get(key)
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True, help="baseline transition metrics JSON")
    parser.add_argument("--candidate", required=True, help="candidate transition metrics JSON")
    parser.add_argument("--representation", required=True, help="candidate representation metrics JSON")
    parser.add_argument("--out", default="target/world_model_selection.json")
    parser.add_argument("--max-regression", type=float, default=0.02)
    parser.add_argument("--require-candidate", action="store_true")
    args = parser.parse_args()

    baseline = load(args.baseline)
    candidate = load(args.candidate)
    representation = load(args.representation)
    comparable = {
        key: (baseline.get(key), candidate.get(key))
        for key in (
            "rows", "train_rows", "validation_rows", "test_rows",
            "split_mode", "dataset_fingerprint",
        )
    }
    comparable["split_seed"] = (
        baseline.get("split_seed", baseline.get("seed")),
        candidate.get("split_seed", candidate.get("seed")),
    )
    mismatches = [key for key, pair in comparable.items() if pair[0] != pair[1]]
    if not all(comparable["dataset_fingerprint"]):
        mismatches.append("dataset_fingerprint")
    mismatches = list(dict.fromkeys(mismatches))
    if mismatches:
        sys.exit(f"candidate metrics are not comparable; mismatched: {', '.join(mismatches)}")
    if not representation.get("accepted", False):
        sys.exit("candidate representation failed its predictive or anti-collapse gates")
    representation_errors = representation_mismatches(candidate, representation)
    if representation_errors:
        sys.exit(
            "candidate representation report does not match its transition evaluation: "
            + ", ".join(representation_errors)
        )

    try:
        base = metric_values(baseline)
        trial = metric_values(candidate)
    except (KeyError, TypeError, ValueError) as error:
        sys.exit(f"candidate metrics are not scale-comparable: {error}")
    ratios = {name: trial[name] / max(base[name], 1e-12) for name in base}
    max_allowed = 1.0 + max(0.0, args.max_regression)
    regressions = [name for name, ratio in ratios.items() if ratio > max_allowed]
    geometric_ratio = math.exp(sum(math.log(max(ratio, 1e-12)) for ratio in ratios.values()) / len(ratios))
    selected = "candidate" if not regressions and geometric_ratio < 1.0 else "baseline"
    decision = {
        "schema_version": 2,
        "comparison_space": "error relative to held-out zero-delta baseline",
        "selected": selected,
        "comparable_split": comparable,
        "max_regression": args.max_regression,
        "geometric_error_ratio": geometric_ratio,
        "metric_ratios": ratios,
        "regressions_beyond_tolerance": regressions,
        "baseline": base,
        "candidate": trial,
        "representation_test": representation.get("test", {}),
    }
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(decision, handle, indent=2)
        handle.write("\n")
    print(json.dumps(decision, indent=2))
    print(
        "PASS: candidate improves comparable held-out accuracy and is eligible for promotion"
        if selected == "candidate"
        else "PASS: baseline retained; candidate did not clear the held-out promotion gate"
    )
    if args.require_candidate and selected != "candidate":
        sys.exit(1)


if __name__ == "__main__":
    main()
