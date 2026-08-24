#!/usr/bin/env python3
"""Run the controller-amended v2 sealed Physical JEPA utility benchmark."""

from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import run_physical_jepa_blinded_benchmark as base  # noqa: E402
from tools.physical_sim_bridge.bridge import BridgeSession, PyBulletBackend  # noqa: E402
from tools.physical_sim_bridge.protocol import BridgeHello  # noqa: E402


PROTOCOL = ROOT / "docs" / "research" / "physical_jepa_blinded_benchmark_v2_protocol.json"
CATALOG = ROOT / "docs" / "research" / "physical_jepa_blinded_benchmark_v2_catalog.json"
COMMITMENT = ROOT / "docs" / "research" / "physical_jepa_blinded_benchmark_v2_commitment.json"
SELECTION = ROOT / "docs" / "research" / "physical_jepa_blinded_benchmark_v2_selection.json"
RESULT = ROOT / "docs" / "research" / "physical_jepa_blinded_benchmark_v2_result.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_new(path: Path, value: dict) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite research artifact: {path}")
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def load_protocol() -> dict:
    protocol = read_json(PROTOCOL)
    for key in ("artifact", "deployed_artifact", "base_runner"):
        spec = protocol[key]
        if sha256(ROOT / spec["path"]) != spec["sha256"]:
            raise ValueError(f"{key} digest drifted")
    negative = protocol["frozen_v1_negative_result"]
    if sha256(ROOT / negative["path"]) != negative["sha256"]:
        raise ValueError("frozen v1 negative result drifted")
    if protocol["controller"]["max_move_to_cycles"] != 2:
        raise ValueError("v2 is registered for exactly two move_to cycles")
    return protocol


def prepare_catalog(protocol: dict) -> dict:
    if any(path.exists() for path in (CATALOG, COMMITMENT, SELECTION, RESULT)):
        raise FileExistsError("v2 sealed benchmark artifacts already exist")
    seed = secrets.randbits(64)
    cases = base.generate_cases(seed, protocol["case_distribution"])
    catalog = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(PROTOCOL),
        "seed": seed,
        "episodes": len(cases),
        "cases_sha256": base.canonical_sha256(cases),
        "cases": cases,
    }
    write_new(CATALOG, catalog)
    commitment = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(PROTOCOL),
        "catalog_path": str(CATALOG.relative_to(ROOT)).replace("\\", "/"),
        "catalog_sha256": sha256(CATALOG),
        "episodes": len(cases),
        "seed_withheld_from_selector": True,
        "cases_withheld_from_selector": True,
        "generated_before_policy_selection": True,
    }
    write_new(COMMITMENT, commitment)
    return commitment


def select_policy(protocol: dict) -> dict:
    if SELECTION.exists() or RESULT.exists():
        raise FileExistsError("v2 selection or result already exists")
    commitment = read_json(COMMITMENT)
    if commitment["protocol_sha256"] != sha256(PROTOCOL):
        raise ValueError("v2 commitment does not bind the protocol")
    policy, development, candidates = base.develop_policy(protocol)
    selection = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(PROTOCOL),
        "commitment_sha256": sha256(COMMITMENT),
        "committed_catalog_sha256": commitment["catalog_sha256"],
        "selector_sha256": sha256(Path(__file__)),
        "base_runner_sha256": sha256(ROOT / protocol["base_runner"]["path"]),
        "blind_catalog_opened": False,
        "blind_seed_seen": False,
        "candidate_count": len(candidates),
        "passing_candidate_count": sum(candidate["passes"] for candidate in candidates),
        "selected_policy": policy,
        "development_metrics": development,
        "selection_order": protocol["selection_order"],
    }
    write_new(SELECTION, selection)
    return selection


def run_commands(
    session: BridgeSession,
    backend: PyBulletBackend,
    run_id: int,
    case_id: int,
    kind: str,
    target: tuple[float, float],
    cycles: int,
) -> tuple[list[dict], list]:
    acknowledgements, observations = [], []
    command_cycles = cycles if kind == "move_to" else 1
    for cycle in range(command_cycles):
        sequence = case_id * cycles + cycle
        acknowledgement = session.submit(
            base.command(run_id, sequence, kind, target), sequence + 1
        )
        acknowledgements.append(acknowledgement)
        observations.append(session.poll())
    return acknowledgements, observations


def evaluate_sealed(protocol: dict) -> dict:
    if RESULT.exists():
        raise FileExistsError("refusing to overwrite the one-shot v2 result")
    commitment = read_json(COMMITMENT)
    selection = read_json(SELECTION)
    if selection["protocol_sha256"] != sha256(PROTOCOL):
        raise ValueError("v2 selection does not bind the protocol")
    if selection["commitment_sha256"] != sha256(COMMITMENT):
        raise ValueError("v2 selection does not bind its commitment")
    if selection["selector_sha256"] != sha256(Path(__file__)):
        raise ValueError("v2 source changed after selection")
    if selection["base_runner_sha256"] != sha256(ROOT / protocol["base_runner"]["path"]):
        raise ValueError("v2 base runner changed after selection")
    if commitment["catalog_sha256"] != sha256(CATALOG):
        raise ValueError("v2 catalog does not match its pre-selection commitment")
    catalog = read_json(CATALOG)
    if base.canonical_sha256(catalog["cases"]) != catalog["cases_sha256"]:
        raise ValueError("v2 cases drifted")

    cases = catalog["cases"]
    policy = selection["selected_policy"]
    weights = base.robustness.load_artifact(ROOT / protocol["artifact"]["path"])
    margins = [
        base.learned_margin(weights, tuple(case["target_xy_m"]), tuple(case["obstacle_xy_m"]))
        for case in cases
    ]
    decisions = [base.policy_decision(case, margin, policy) for case, margin in zip(cases, margins)]
    topology = hashlib.sha256(b"pybullet-direct-box-robot-obstacle-v1").hexdigest()
    unshielded_backend = PyBulletBackend(run_id=4101, source_clock_id=61)
    shielded_backend = PyBulletBackend(run_id=4102, source_clock_id=62)
    unshielded = BridgeSession(BridgeHello(4101, 1, "pybullet", 61, topology, False), unshielded_backend)
    shielded = BridgeSession(BridgeHello(4102, 1, "pybullet", 62, topology, False), shielded_backend)
    cycles = protocol["controller"]["max_move_to_cycles"]
    tolerance = protocol["controller"]["target_tolerance_m"]
    deployed = ROOT / protocol["deployed_artifact"]["path"]
    deployed_before = sha256(deployed)
    records = []
    try:
        for case, margin, decision in zip(cases, margins, decisions):
            target = tuple(case["target_xy_m"])
            obstacle = tuple(case["obstacle_xy_m"])
            blocked, deterministic, learned = decision
            unshielded_backend.reset_scene((0.0, 0.0), obstacle)
            u_observations = [unshielded.poll()]
            u_acks, u_tail = run_commands(unshielded, unshielded_backend, 4101, case["case"], "move_to", target, cycles)
            u_observations.extend(u_tail)
            shielded_backend.reset_scene((0.0, 0.0), obstacle)
            s_observations = [shielded.poll()]
            kind = "stop" if blocked else "move_to"
            s_acks, s_tail = run_commands(shielded, shielded_backend, 4102, case["case"], kind, target, cycles)
            s_observations.extend(s_tail)
            final = s_observations[-1]
            final_xy = (final.payload["x_mm"] / 1000.0, final.payload["y_mm"] / 1000.0)
            records.append(
                {
                    **case,
                    "learned_margin": margin,
                    "deterministic_block": deterministic,
                    "learned_alert": learned,
                    "shield_command": kind,
                    "control_cycles": len(s_acks),
                    "final_target_error_m": math.dist(final_xy, target),
                    "task_completed": kind == "move_to"
                    and not shielded_backend.collision_detected
                    and math.dist(final_xy, target) <= tolerance,
                    "unshielded_collision": bool(unshielded_backend.collision_detected),
                    "shielded_collision": bool(shielded_backend.collision_detected),
                    "all_acknowledgements_accepted": all(
                        ack["delivery_state"] == "accepted" for ack in (*u_acks, *s_acks)
                    ),
                    "observations_simulated": all(
                        observation is not None and observation.evidence_class == "simulated"
                        for observation in (*u_observations, *s_observations)
                    ),
                }
            )
    finally:
        unshielded.close()
        shielded.close()
    deployed_after = sha256(deployed)

    episodes = len(records)
    unshielded_hits = sum(record["unshielded_collision"] for record in records)
    shielded_hits = sum(record["shielded_collision"] for record in records)
    interventions = sum(record["shield_command"] == "stop" for record in records)
    completions = sum(record["task_completed"] for record in records)
    summary = {
        "episodes": episodes,
        "task_completions": completions,
        "task_completion_rate": completions / episodes,
        "interventions": interventions,
        "intervention_rate": interventions / episodes,
        "unshielded_collisions": unshielded_hits,
        "shielded_collisions": shielded_hits,
        "collision_reduction": (unshielded_hits - shielded_hits) / max(1, unshielded_hits),
        "learned_collision_recall": sum(
            record["learned_alert"] and record["unshielded_collision"] for record in records
        ) / max(1, unshielded_hits),
        "incremental_learned_interventions": sum(
            record["learned_alert"] and not record["deterministic_block"] for record in records
        ),
        "all_acknowledgements_accepted": all(record["all_acknowledgements_accepted"] for record in records),
        "all_observations_simulated": all(record["observations_simulated"] for record in records),
        "max_completed_target_error_m": max(
            record["final_target_error_m"] for record in records if record["task_completed"]
        ),
    }
    summary["family_breakdown"] = {
        family: {
            "episodes": sum(record["family"] == family for record in records),
            "task_completions": sum(record["family"] == family and record["task_completed"] for record in records),
            "interventions": sum(record["family"] == family and record["shield_command"] == "stop" for record in records),
            "unshielded_collisions": sum(record["family"] == family and record["unshielded_collision"] for record in records),
            "shielded_collisions": sum(record["family"] == family and record["shielded_collision"] for record in records),
        }
        for family in protocol["case_distribution"]["families"]
    }
    deployment = {"before_sha256": deployed_before, "after_sha256": deployed_after, "unchanged": deployed_before == deployed_after}
    gates = protocol["sealed_gates"]
    sealed_gates = {
        "shielded_collisions": shielded_hits <= gates["shielded_collisions_max"],
        "task_completion_rate": summary["task_completion_rate"] >= gates["task_completion_rate_min"],
        "intervention_rate": summary["intervention_rate"] <= gates["intervention_rate_max"],
        "collision_reduction": summary["collision_reduction"] >= gates["collision_reduction_min"],
        "all_acknowledgements_accepted": summary["all_acknowledgements_accepted"],
        "all_observations_simulated": summary["all_observations_simulated"],
        "deployed_artifact_unchanged": deployment["unchanged"],
    }
    result = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(PROTOCOL),
        "commitment_sha256": sha256(COMMITMENT),
        "catalog_sha256": sha256(CATALOG),
        "selection_sha256": sha256(SELECTION),
        "runner_sha256": sha256(Path(__file__)),
        "base_runner_sha256": sha256(ROOT / protocol["base_runner"]["path"]),
        "frozen_v1_result_sha256": sha256(ROOT / protocol["frozen_v1_negative_result"]["path"]),
        "final_open_count": 1,
        "retuned_after_open": False,
        "backend": {
            "name": "PyBullet",
            "version": version("pybullet"),
            "connection_mode": "DIRECT",
            "actuator_enabled": False,
            "evidence_class": "simulated",
            "topology_sha256": topology,
        },
        "controller": protocol["controller"],
        "selected_policy": policy,
        "summary": summary,
        "sealed_gates": sealed_gates,
        "all_sealed_gates_pass": all(sealed_gates.values()),
        "deployment_integrity": deployment,
        "cases": records,
        "claim_boundary": protocol["claim_boundary"],
    }
    write_new(RESULT, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("develop", "prepare", "select", "evaluate"))
    args = parser.parse_args()
    protocol = load_protocol()
    if args.mode == "develop":
        policy, development, candidates = base.develop_policy(protocol)
        output = {"selected_policy": policy, "development_metrics": development, "candidate_count": len(candidates)}
    elif args.mode == "prepare":
        output = prepare_catalog(protocol)
    elif args.mode == "select":
        output = select_policy(protocol)
    else:
        output = evaluate_sealed(protocol)
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
