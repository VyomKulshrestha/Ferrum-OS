#!/usr/bin/env python3
"""Run the frozen v5 rules+JEPA gate against a PyBullet DIRECT world."""

from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_physical_jepa_robustness as robustness  # noqa: E402
import train_physical_world_model as simulator  # noqa: E402
from tools.physical_sim_bridge.bridge import (  # noqa: E402
    BridgeSession,
    PyBulletBackend,
)
from tools.physical_sim_bridge.protocol import (  # noqa: E402
    BridgeCommand,
    BridgeHello,
)


PROTOCOL = ROOT / "docs" / "research" / "physical_jepa_paper_protocol_v1.json"
ARTIFACT = ROOT / "docs" / "research" / "artifacts" / "physical-jepa-v5" / "selected_candidate.bin"
DEPLOYED = ROOT / "userland" / "heliox-daemon" / "physical_world_model.bin"
DEFAULT_OUTPUT = ROOT / "docs" / "research" / "physical_jepa_pybullet_integration_v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def state_for_case(obstacle_xy: tuple[float, float]) -> np.ndarray:
    state = np.zeros(simulator.STATE_SIZE, dtype=np.float32)
    center_distance = math.hypot(*obstacle_xy)
    state[simulator.CLEARANCE] = np.clip(center_distance - 0.16, 0.0, 1.0)
    state[simulator.HUMANS] = 0.0
    state[simulator.BATTERY] = 0.8
    state[simulator.LINK] = 0.9
    state[simulator.HEALTH] = 0.8
    state[simulator.ESTOP] = 0.0
    state[simulator.ONLINE] = 1.0
    state[simulator.PAYLOAD] = 0.3
    state[simulator.VELOCITY] = 0.0
    state[simulator.MARGIN] = 1.0
    state[simulator.APPROVAL] = 1.0
    return state


def command(run_id: int, case_id: int, kind: str, target: tuple[float, float]):
    return BridgeCommand(
        run_id=run_id,
        command_id=case_id + 1,
        idempotency_key=case_id + 1,
        adapter_id=1,
        endpoint_id=1,
        session_epoch=1,
        kind=kind,
        arguments=(int(round(target[0] * 1000)), int(round(target[1] * 1000)), 0),
        issued_at_tick=case_id,
        deadline_tick=case_id + 1,
        expected_policy_revision=1,
        expected_twin_event_id=case_id,
        confirmation_kind="not_required",
        confirmation_id=0,
        authority="ferrum_routed_command_v1",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    spec = protocol["simulator_integration"]
    if spec["backend"] != "PyBullet 3.2.7 DIRECT" or spec["actuator_enabled"]:
        raise ValueError("simulator protocol is not the registered actuator-free DIRECT run")
    expected_artifact = protocol["artifacts"]["v5"]["sha256"]
    if sha256(ARTIFACT) != expected_artifact:
        raise ValueError("v5 artifact drifted")
    deployed_before = sha256(DEPLOYED)
    weights = robustness.load_artifact(ARTIFACT)

    topology = hashlib.sha256(b"pybullet-direct-box-robot-obstacle-v1").hexdigest()
    unshielded_backend = PyBulletBackend(run_id=1001, source_clock_id=31)
    shielded_backend = PyBulletBackend(run_id=1002, source_clock_id=32)
    unshielded = BridgeSession(
        BridgeHello(1001, 1, "pybullet", 31, topology, False), unshielded_backend
    )
    shielded = BridgeSession(
        BridgeHello(1002, 1, "pybullet", 32, topology, False), shielded_backend
    )
    rng = np.random.default_rng(spec["seed"])
    cases = []
    try:
        for case_id in range(spec["episodes"]):
            angle = float(rng.uniform(-math.pi, math.pi))
            direction = np.asarray([math.cos(angle), math.sin(angle)])
            perpendicular = np.asarray([-direction[1], direction[0]])
            target = tuple((0.32 * direction).tolist())
            longitudinal = float(rng.uniform(0.12, 0.48))
            lateral = float(rng.uniform(-0.34, 0.34))
            obstacle = tuple((longitudinal * direction + lateral * perpendicular).tolist())
            state = state_for_case(obstacle)
            features = np.asarray([direction[0], direction[1], 0.8], dtype=np.float32)
            predicted = robustness.prediction(weights, state, simulator.MOVE, features)
            rules_block = simulator.rules_block(state, simulator.MOVE, features)
            learned_block = simulator.predicted_block(
                state, simulator.MOVE, features, predicted
            )
            blocked = rules_block or learned_block

            unshielded_backend.reset_scene((0.0, 0.0), obstacle)
            unshielded_observation = unshielded.poll()
            unshielded_result = unshielded.submit(
                command(1001, case_id, "move_to", target), case_id + 1
            )
            unshielded_final = unshielded.poll()

            shielded_backend.reset_scene((0.0, 0.0), obstacle)
            shielded_observation = shielded.poll()
            selected_kind = "stop" if blocked else "move_to"
            shielded_result = shielded.submit(
                command(1002, case_id, selected_kind, target), case_id + 1
            )
            shielded_final = shielded.poll()
            cases.append(
                {
                    "case": case_id,
                    "obstacle_xy_m": list(obstacle),
                    "target_xy_m": list(target),
                    "initial_clearance_m": float(state[simulator.CLEARANCE]),
                    "rules_block": bool(rules_block),
                    "learned_block": bool(learned_block),
                    "shield_command": selected_kind,
                    "unshielded_collision": bool(unshielded_backend.collision_detected),
                    "shielded_collision": bool(shielded_backend.collision_detected),
                    "unshielded_ack": unshielded_result["delivery_state"],
                    "shielded_ack": shielded_result["delivery_state"],
                    "observations_simulated": all(
                        observation is not None
                        and observation.evidence_class == "simulated"
                        for observation in (
                            unshielded_observation,
                            unshielded_final,
                            shielded_observation,
                            shielded_final,
                        )
                    ),
                }
            )
    finally:
        unshielded.close()
        shielded.close()

    unshielded_collisions = sum(item["unshielded_collision"] for item in cases)
    shielded_collisions = sum(item["shielded_collision"] for item in cases)
    blocked = sum(item["shield_command"] == "stop" for item in cases)
    allowed = len(cases) - blocked
    allowed_collisions = sum(
        item["shielded_collision"] and item["shield_command"] == "move_to"
        for item in cases
    )
    blocked_counterfactual_collisions = sum(
        item["unshielded_collision"] and item["shield_command"] == "stop"
        for item in cases
    )
    deployed_after = sha256(DEPLOYED)
    output = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(args.protocol),
        "backend": {
            "name": "PyBullet",
            "version": version("pybullet"),
            "connection_mode": "DIRECT",
            "topology_sha256": topology,
            "actuator_enabled": False,
            "evidence_class": "simulated",
        },
        "seed": spec["seed"],
        "episodes": len(cases),
        "artifact_sha256": sha256(ARTIFACT),
        "summary": {
            "blocked_commands": blocked,
            "allowed_commands": allowed,
            "unshielded_collisions": unshielded_collisions,
            "shielded_collisions": shielded_collisions,
            "allowed_collisions": allowed_collisions,
            "blocked_counterfactual_collisions": blocked_counterfactual_collisions,
            "all_acknowledgements_accepted_by_simulator": all(
                item["unshielded_ack"] == "accepted"
                and item["shielded_ack"] == "accepted"
                for item in cases
            ),
            "all_observations_marked_simulated": all(
                item["observations_simulated"] for item in cases
            ),
        },
        "deployment_integrity": {
            "before_sha256": deployed_before,
            "after_sha256": deployed_after,
            "unchanged": deployed_before == deployed_after,
        },
        "cases": cases,
        "claim_boundary": [
            "PyBullet DIRECT is a third-party software physics execution, not Ferrum's deterministic transition generator.",
            "The bridge hello has actuator_enabled=false and every observation is marked simulated.",
            "This is not hardware-in-the-loop, physical robot deployment, real-time validation, certification, or independent assessment.",
            "Collision counts characterize only this registered box-body scenario distribution.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), **output["summary"], **output["deployment_integrity"]}, indent=2))
    return 0 if (
        output["summary"]["all_acknowledgements_accepted_by_simulator"]
        and output["summary"]["all_observations_marked_simulated"]
        and output["deployment_integrity"]["unchanged"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
