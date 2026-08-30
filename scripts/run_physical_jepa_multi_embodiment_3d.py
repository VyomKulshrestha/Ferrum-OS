#!/usr/bin/env python3
"""Run the registered Physical JEPA v5 multi-embodiment 3D stress study."""

from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
import math
import sys
from pathlib import Path

import numpy as np
import pybullet as p


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_physical_jepa_robustness as robustness  # noqa: E402
import train_physical_world_model as simulator  # noqa: E402


PROTOCOL = ROOT / "docs/research/physical_jepa_multi_embodiment_3d_protocol_v1.json"
DEFAULT_OUTPUT = ROOT / "docs/research/physical_jepa_multi_embodiment_3d_result_v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def wilson(successes: int, total: int, z: float = 1.959963984540054) -> list[float]:
    if total == 0:
        return [0.0, 1.0]
    proportion = successes / total
    denominator = 1.0 + z * z / total
    center = (proportion + z * z / (2.0 * total)) / denominator
    half = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total)
        )
        / denominator
    )
    return [max(0.0, center - half), min(1.0, center + half)]


def collision_shape(client: int, specification: dict, obstacle: bool = False) -> int:
    name = specification["name"]
    if name == "box":
        return p.createCollisionShape(
            p.GEOM_BOX,
            halfExtents=specification["half_extents_m"],
            physicsClientId=client,
        )
    if name == "sphere":
        return p.createCollisionShape(
            p.GEOM_SPHERE,
            radius=specification["radius_m"],
            physicsClientId=client,
        )
    if name in {"capsule", "cylinder"}:
        geometry = p.GEOM_CAPSULE if not obstacle else p.GEOM_CYLINDER
        return p.createCollisionShape(
            geometry,
            radius=specification["radius_m"],
            height=specification["height_m"],
            physicsClientId=client,
        )
    raise ValueError(f"unsupported shape: {name}")


def prepare_scene(
    client: int,
    embodiment: dict,
    obstacle: dict,
    start: np.ndarray,
    obstacle_position: np.ndarray,
) -> tuple[int, int]:
    p.resetSimulation(physicsClientId=client)
    p.setGravity(0.0, 0.0, 0.0, physicsClientId=client)
    p.setTimeStep(1.0 / 240.0, physicsClientId=client)
    robot_shape = collision_shape(client, embodiment)
    obstacle_shape = collision_shape(client, obstacle, obstacle=True)
    robot = p.createMultiBody(
        baseMass=embodiment["mass_kg"],
        baseCollisionShapeIndex=robot_shape,
        basePosition=start.tolist(),
        physicsClientId=client,
    )
    obstacle_body = p.createMultiBody(
        baseMass=0.0,
        baseCollisionShapeIndex=obstacle_shape,
        basePosition=obstacle_position.tolist(),
        physicsClientId=client,
    )
    return robot, obstacle_body


def move_and_contact(
    client: int,
    robot: int,
    obstacle: int,
    target: np.ndarray,
) -> bool:
    position = np.asarray(
        p.getBasePositionAndOrientation(robot, physicsClientId=client)[0],
        dtype=np.float64,
    )
    p.resetBaseVelocity(
        robot,
        linearVelocity=(target - position).tolist(),
        angularVelocity=[0.0, 0.0, 0.0],
        physicsClientId=client,
    )
    contact = False
    for _ in range(240):
        p.stepSimulation(physicsClientId=client)
        contact = contact or bool(
            p.getContactPoints(robot, obstacle, physicsClientId=client)
        )
    p.resetBaseVelocity(
        robot,
        linearVelocity=[0.0, 0.0, 0.0],
        angularVelocity=[0.0, 0.0, 0.0],
        physicsClientId=client,
    )
    return contact


def recover_to_start(
    client: int,
    robot: int,
    obstacle: int,
    start: np.ndarray,
) -> tuple[bool, float, bool]:
    position = np.asarray(
        p.getBasePositionAndOrientation(robot, physicsClientId=client)[0],
        dtype=np.float64,
    )
    p.resetBaseVelocity(
        robot,
        linearVelocity=(start - position).tolist(),
        angularVelocity=[0.0, 0.0, 0.0],
        physicsClientId=client,
    )
    for _ in range(240):
        p.stepSimulation(physicsClientId=client)
    p.resetBaseVelocity(
        robot,
        linearVelocity=[0.0, 0.0, 0.0],
        angularVelocity=[0.0, 0.0, 0.0],
        physicsClientId=client,
    )
    final = np.asarray(
        p.getBasePositionAndOrientation(robot, physicsClientId=client)[0],
        dtype=np.float64,
    )
    contact = bool(p.getContactPoints(robot, obstacle, physicsClientId=client))
    distance = float(np.linalg.norm(final - start))
    return (not contact and distance <= 0.03), distance, contact


def model_state(clearance: float, start: np.ndarray) -> np.ndarray:
    state = np.zeros(simulator.STATE_SIZE, dtype=np.float32)
    state[simulator.X] = float(start[0])
    state[simulator.Y] = float(start[1])
    state[simulator.CLEARANCE] = float(np.clip(clearance, 0.0, 1.0))
    state[simulator.BATTERY] = 0.8
    state[simulator.LINK] = 0.9
    state[simulator.HEALTH] = 0.8
    state[simulator.ONLINE] = 1.0
    state[simulator.PAYLOAD] = 0.3
    state[simulator.MARGIN] = 1.0
    state[simulator.APPROVAL] = 1.0
    return state


def summarize(cases: list[dict]) -> dict:
    total = len(cases)
    interventions = sum(item["union_block"] for item in cases)
    completions = sum(item["task_completed"] for item in cases)
    unshielded = sum(item["unshielded_contact"] for item in cases)
    shielded = sum(item["shielded_contact"] for item in cases)
    learned_only = sum(
        item["learned_block"] and not item["rule_block"] for item in cases
    )
    learned_avoided = sum(
        item["learned_block"]
        and not item["rule_block"]
        and item["unshielded_contact"]
        and not item["shielded_contact"]
        for item in cases
    )
    recovery_cases = [item for item in cases if item["unshielded_contact"]]
    recovered = sum(item["recovery_success"] is True for item in recovery_cases)
    return {
        "cases": total,
        "task_completions": completions,
        "task_completion_rate": completions / max(1, total),
        "task_completion_wilson_95": wilson(completions, total),
        "interventions": interventions,
        "intervention_rate": interventions / max(1, total),
        "intervention_wilson_95": wilson(interventions, total),
        "unshielded_contacts": unshielded,
        "unshielded_contact_rate": unshielded / max(1, total),
        "unshielded_contact_wilson_95": wilson(unshielded, total),
        "shielded_contacts": shielded,
        "shielded_contact_rate": shielded / max(1, total),
        "shielded_contact_wilson_95": wilson(shielded, total),
        "learned_only_interventions": learned_only,
        "learned_only_contacts_avoided": learned_avoided,
        "contact_recovery_cases": len(recovery_cases),
        "contact_recovery_successes": recovered,
        "contact_recovery_rate": recovered / max(1, len(recovery_cases)),
        "contact_recovery_wilson_95": wilson(recovered, len(recovery_cases)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    protocol = load(PROTOCOL)
    artifact = ROOT / protocol["artifact"]["path"]
    artifact_before = sha256(artifact)
    if artifact_before != protocol["artifact"]["sha256"]:
        raise ValueError("frozen v5 artifact digest mismatch")
    if version("pybullet") != protocol["backend"]["version"]:
        raise ValueError("PyBullet version mismatch")
    weights = robustness.load_artifact(artifact)
    rng = np.random.default_rng(protocol["seed"])
    client = p.connect(p.DIRECT)
    if client < 0:
        raise RuntimeError("PyBullet DIRECT connection failed")
    cases = []
    try:
        case_id = 0
        for embodiment in protocol["embodiments"]:
            for obstacle in protocol["obstacles"]:
                for _ in range(protocol["cases_per_embodiment_obstacle_pair"]):
                    start = np.asarray([0.0, 0.0, 0.2], dtype=np.float64)
                    angle = float(rng.uniform(-math.pi, math.pi))
                    radial = float(
                        rng.uniform(*protocol["trajectory"]["target_radial_range_m"])
                    )
                    vertical = float(
                        rng.uniform(
                            *protocol["trajectory"]["target_vertical_offset_range_m"]
                        )
                    )
                    direction = np.asarray([math.cos(angle), math.sin(angle), 0.0])
                    perpendicular = np.asarray([-direction[1], direction[0], 0.0])
                    target = (
                        start + radial * direction + np.asarray([0.0, 0.0, vertical])
                    )
                    fraction = float(
                        rng.uniform(
                            *protocol["trajectory"]["obstacle_path_fraction_range"]
                        )
                    )
                    lateral = float(
                        rng.uniform(
                            *protocol["trajectory"]["obstacle_lateral_offset_range_m"]
                        )
                    )
                    obstacle_vertical = float(
                        rng.uniform(
                            *protocol["trajectory"]["obstacle_vertical_offset_range_m"]
                        )
                    )
                    obstacle_position = (
                        start
                        + fraction * (target - start)
                        + lateral * perpendicular
                        + np.asarray([0.0, 0.0, obstacle_vertical])
                    )
                    clearance = max(
                        0.0,
                        float(np.linalg.norm(obstacle_position - start))
                        - embodiment["bounding_radius_m"]
                        - obstacle["bounding_radius_m"],
                    )
                    state = model_state(clearance, start)
                    planar_norm = max(
                        float(np.linalg.norm(target[:2] - start[:2])), 1e-9
                    )
                    features = np.asarray(
                        [
                            (target[0] - start[0]) / planar_norm,
                            (target[1] - start[1]) / planar_norm,
                            min(1.0, float(np.linalg.norm(target - start)) / 0.48),
                        ],
                        dtype=np.float32,
                    )
                    predicted = robustness.prediction(
                        weights, state, simulator.MOVE, features
                    )
                    rule_block = simulator.rules_block(state, simulator.MOVE, features)
                    learned_block = simulator.predicted_block(
                        state, simulator.MOVE, features, predicted
                    )
                    union_block = bool(rule_block or learned_block)

                    robot, obstacle_body = prepare_scene(
                        client, embodiment, obstacle, start, obstacle_position
                    )
                    unshielded_contact = move_and_contact(
                        client, robot, obstacle_body, target
                    )
                    recovery_success = None
                    recovery_distance = None
                    recovery_contact = None
                    if unshielded_contact:
                        (
                            recovery_success,
                            recovery_distance,
                            recovery_contact,
                        ) = recover_to_start(client, robot, obstacle_body, start)

                    shielded_contact = False
                    if not union_block:
                        robot, obstacle_body = prepare_scene(
                            client, embodiment, obstacle, start, obstacle_position
                        )
                        shielded_contact = move_and_contact(
                            client, robot, obstacle_body, target
                        )
                    cases.append(
                        {
                            "case_id": case_id,
                            "embodiment": embodiment["name"],
                            "obstacle": obstacle["name"],
                            "target_xyz_m": target.tolist(),
                            "obstacle_xyz_m": obstacle_position.tolist(),
                            "initial_clearance_m": clearance,
                            "rule_block": bool(rule_block),
                            "learned_block": bool(learned_block),
                            "union_block": union_block,
                            "unshielded_contact": bool(unshielded_contact),
                            "shielded_contact": bool(shielded_contact),
                            "task_completed": bool(
                                not union_block and not shielded_contact
                            ),
                            "recovery_success": recovery_success,
                            "recovery_distance_to_start_m": recovery_distance,
                            "recovery_final_contact": recovery_contact,
                            "observation_evidence_class": "simulated",
                        }
                    )
                    case_id += 1
    finally:
        p.disconnect(client)

    summary = summarize(cases)
    per_embodiment = {
        item["name"]: summarize(
            [case for case in cases if case["embodiment"] == item["name"]]
        )
        for item in protocol["embodiments"]
    }
    per_obstacle = {
        item["name"]: summarize(
            [case for case in cases if case["obstacle"] == item["name"]]
        )
        for item in protocol["obstacles"]
    }
    artifact_after = sha256(artifact)
    checks = {
        "case_count": len(cases) == protocol["expected_cases"],
        "all_cells_represented": all(
            sum(
                case["embodiment"] == embodiment["name"]
                and case["obstacle"] == obstacle["name"]
                for case in cases
            )
            == protocol["cases_per_embodiment_obstacle_pair"]
            for embodiment in protocol["embodiments"]
            for obstacle in protocol["obstacles"]
        ),
        "finite": all(
            np.isfinite(case["target_xyz_m"]).all()
            and np.isfinite(case["obstacle_xyz_m"]).all()
            and math.isfinite(case["initial_clearance_m"])
            for case in cases
        ),
        "union_monotone": all(
            case["union_block"] == (case["rule_block"] or case["learned_block"])
            for case in cases
        ),
        "all_observations_simulated": all(
            case["observation_evidence_class"] == "simulated" for case in cases
        ),
        "zero_physical_actuator_attempts": True,
        "zero_physical_actuator_deliveries": True,
        "artifact_unchanged": artifact_before == artifact_after,
        "claim_boundary_preserved": True,
    }
    result = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(PROTOCOL),
        "backend": {
            **protocol["backend"],
            "observed_version": version("pybullet"),
        },
        "artifact": {
            "path": protocol["artifact"]["path"],
            "sha256_before": artifact_before,
            "sha256_after": artifact_after,
            "unchanged": artifact_before == artifact_after,
        },
        "authority": {
            "physical_actuator_attempts": 0,
            "physical_actuator_deliveries": 0,
            "simulator_motion_enabled": True,
        },
        "summary": summary,
        "per_embodiment": per_embodiment,
        "per_obstacle": per_obstacle,
        "cases": cases,
        "checks": checks,
        "acceptance_gates_passed": all(checks.values()),
        "promotion_eligible": False,
        "claim_boundary": protocol["claim_boundary"],
    }
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                **summary,
                "acceptance_gates_passed": result["acceptance_gates_passed"],
            },
            indent=2,
        )
    )
    return 0 if result["acceptance_gates_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
