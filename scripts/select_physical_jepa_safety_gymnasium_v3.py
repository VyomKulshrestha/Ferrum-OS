#!/usr/bin/env python3
"""Recalibrate the Safety-Gymnasium rule threshold on the retained failed catalog."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs/research/physical_jepa_safety_gymnasium_protocol_v3.json"
OUTPUT = ROOT / "docs/research/physical_jepa_safety_gymnasium_selection_v3.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    if OUTPUT.exists():
        raise FileExistsError(f"selection output already exists: {OUTPUT}")
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    source = ROOT / protocol["development_selection"]["source_path"]
    if sha256(source) != protocol["development_selection"]["source_sha256"]:
        raise ValueError("retained development catalog hash mismatch")
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    candidates = []
    for candidate in protocol["candidate_policies"]:
        decisions = []
        for row in rows:
            moving = row["proposed_action"][0] > 0.0
            rule = moving and row["hazard_closeness"] >= candidate[
                "rule_hazard_closeness_threshold"
            ]
            learned = moving and row["predicted_clearance"] <= candidate[
                "learned_predicted_clearance_threshold"
            ]
            decisions.append((rule or learned, bool(row["dangerous_proposal"])))
        dangerous = sum(danger for _, danger in decisions)
        safe = len(decisions) - dangerous
        true_positive = sum(block and danger for block, danger in decisions)
        false_positive = sum(block and not danger for block, danger in decisions)
        interventions = true_positive + false_positive
        metrics = {
            "recorded_proposals": len(decisions),
            "recorded_dangerous_proposals": dangerous,
            "recorded_safe_proposals": safe,
            "counterfactual_interventions": interventions,
            "counterfactual_true_positive_interventions": true_positive,
            "counterfactual_false_positive_interventions": false_positive,
            "trajectory_conditional_intervention_rate": interventions / len(decisions),
            "trajectory_conditional_dangerous_recall": true_positive / max(1, dangerous),
            "trajectory_conditional_safe_false_positive_rate": false_positive / max(1, safe),
        }
        gates = {
            "strengthened_development_recall": metrics[
                "trajectory_conditional_dangerous_recall"
            ] >= protocol["development_selection"]["strengthened_dangerous_recall_minimum"],
            "final_intervention_limit": metrics["trajectory_conditional_intervention_rate"]
            <= protocol["frozen_gates"]["intervention_rate_maximum"],
            "final_safe_false_positive_limit": metrics[
                "trajectory_conditional_safe_false_positive_rate"
            ] <= protocol["frozen_gates"]["safe_proposal_false_positive_rate_maximum"],
        }
        candidates.append(
            {"candidate": candidate, "metrics": metrics, "gates": gates, "all_gates_pass": all(gates.values())}
        )
    passing = [item for item in candidates if item["all_gates_pass"]]
    passing.sort(
        key=lambda item: (
            item["metrics"]["trajectory_conditional_intervention_rate"],
            -item["metrics"]["trajectory_conditional_dangerous_recall"],
            item["candidate"]["candidate_id"],
        )
    )
    selected = passing[0] if passing else None
    report = {
        "schema": protocol["result_schemas"]["selection"],
        "protocol": {"path": PROTOCOL.relative_to(ROOT).as_posix(), "sha256": sha256(PROTOCOL)},
        "source": {"path": source.relative_to(ROOT).as_posix(), "sha256": sha256(source), "rows": len(rows)},
        "method": protocol["development_selection"]["method"],
        "trajectory_limitation": protocol["development_selection"]["trajectory_limitation"],
        "candidates": candidates,
        "selected_candidate": None if selected is None else selected["candidate"],
        "selection_passed": selected is not None,
        "final_seed_access_attempted": False,
        "final_seed_accessed": False,
        "promotion_eligible": False,
    }
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"selection_passed": report["selection_passed"], "selected": report["selected_candidate"]}))
    if selected is None:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
