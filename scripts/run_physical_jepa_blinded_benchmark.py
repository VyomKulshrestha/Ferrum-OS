#!/usr/bin/env python3
"""Seal, select, and evaluate the prospective Physical JEPA PyBullet benchmark."""

from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import secrets
import sys

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
from tools.physical_sim_bridge.protocol import BridgeCommand, BridgeHello  # noqa: E402


PROTOCOL = ROOT / "docs" / "research" / "physical_jepa_blinded_benchmark_v1_protocol.json"
CATALOG = ROOT / "docs" / "research" / "physical_jepa_blinded_benchmark_v1_catalog.json"
COMMITMENT = ROOT / "docs" / "research" / "physical_jepa_blinded_benchmark_v1_commitment.json"
SELECTION = ROOT / "docs" / "research" / "physical_jepa_blinded_benchmark_v1_selection.json"
RESULT = ROOT / "docs" / "research" / "physical_jepa_blinded_benchmark_v1_result.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_new(path: Path, value: dict) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite research artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def load_protocol() -> dict:
    protocol = read_json(PROTOCOL)
    backend = protocol["backend"]
    if (
        backend["name"] != "PyBullet"
        or backend["version"] != "3.2.7"
        or backend["connection_mode"] != "DIRECT"
        or backend["actuator_enabled"]
    ):
        raise ValueError("protocol is not the registered actuator-free PyBullet run")
    for key in ("artifact", "deployed_artifact"):
        spec = protocol[key]
        if sha256(ROOT / spec["path"]) != spec["sha256"]:
            raise ValueError(f"{key} digest drifted")
    return protocol


def segment_intersects_box(
    target: tuple[float, float],
    obstacle: tuple[float, float],
    half_extent: float,
) -> bool:
    """Return whether the origin-to-target segment intersects an axis-aligned box."""
    lower = (obstacle[0] - half_extent, obstacle[1] - half_extent)
    upper = (obstacle[0] + half_extent, obstacle[1] + half_extent)
    enter, leave = 0.0, 1.0
    for delta, low, high in zip(target, lower, upper):
        if abs(delta) < 1e-12:
            if not low <= 0.0 <= high:
                return False
            continue
        first, second = low / delta, high / delta
        if first > second:
            first, second = second, first
        enter = max(enter, first)
        leave = min(leave, second)
        if enter > leave:
            return False
    return leave >= 0.0 and enter <= 1.0


def classify_case(target: tuple[float, float], obstacle: tuple[float, float], spec: dict) -> str:
    limits = spec["classification"]
    if segment_intersects_box(target, obstacle, limits["collision_half_extent_m"]):
        return "collision_course"
    if segment_intersects_box(target, obstacle, limits["boundary_half_extent_m"]):
        return "boundary_safe"
    if segment_intersects_box(target, obstacle, limits["near_half_extent_m"]):
        return "near_safe"
    return "clear_safe"


def generate_cases(seed: int, distribution: dict, scale: float = 1.0) -> list[dict]:
    rng = np.random.default_rng(seed)
    requested = {
        family: int(round(count * scale))
        for family, count in distribution["families"].items()
    }
    cases: list[dict] = []
    attempts = 0
    while any(sum(case["family"] == family for case in cases) < count for family, count in requested.items()):
        attempts += 1
        if attempts > 2_000_000:
            raise RuntimeError("case generator exhausted its rejection budget")
        angle = float(rng.uniform(-math.pi, math.pi))
        distance = float(rng.uniform(*distribution["target_distance_m"]))
        target = (distance * math.cos(angle), distance * math.sin(angle))
        obstacle = (float(rng.uniform(-0.62, 0.62)), float(rng.uniform(-0.62, 0.62)))
        family = classify_case(target, obstacle, distribution)
        if sum(case["family"] == family for case in cases) >= requested[family]:
            continue
        cases.append(
            {
                "case": len(cases),
                "family": family,
                "target_xy_m": [target[0], target[1]],
                "obstacle_xy_m": [obstacle[0], obstacle[1]],
            }
        )
    rng.shuffle(cases)
    for case_id, case in enumerate(cases):
        case["case"] = case_id
    return cases


def state_for_case(obstacle: tuple[float, float]) -> np.ndarray:
    state = np.zeros(simulator.STATE_SIZE, dtype=np.float32)
    state[simulator.CLEARANCE] = np.clip(math.hypot(*obstacle) - 0.16, 0.0, 1.0)
    state[simulator.BATTERY] = 0.8
    state[simulator.LINK] = 0.9
    state[simulator.HEALTH] = 0.8
    state[simulator.ONLINE] = 1.0
    state[simulator.PAYLOAD] = 0.3
    state[simulator.MARGIN] = 1.0
    state[simulator.APPROVAL] = 1.0
    return state


def features_for_target(target: tuple[float, float]) -> np.ndarray:
    distance = math.hypot(*target)
    return np.asarray([target[0] / distance, target[1] / distance, 0.8], dtype=np.float32)


def learned_margin(weights: dict, target: tuple[float, float], obstacle: tuple[float, float]) -> float:
    state = state_for_case(obstacle)
    features = features_for_target(target)
    nxt = robustness.prediction(weights, state, simulator.MOVE, features)
    margins = [
        (0.18 - float(nxt[simulator.CLEARANCE])) / 0.18,
        (0.08 - float(nxt[simulator.BATTERY])) / 0.08,
        (0.08 - float(nxt[simulator.LINK])) / 0.08,
        (0.01 - float(nxt[simulator.MARGIN])) / 0.25,
    ]
    return max(margins)


def command(run_id: int, case_id: int, kind: str, target: tuple[float, float]) -> BridgeCommand:
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


def pybullet_truth(cases: list[dict], run_id: int) -> list[bool]:
    topology = hashlib.sha256(b"pybullet-direct-box-robot-obstacle-v1").hexdigest()
    backend = PyBulletBackend(run_id=run_id, source_clock_id=41)
    session = BridgeSession(BridgeHello(run_id, 1, "pybullet", 41, topology, False), backend)
    collisions = []
    try:
        for case in cases:
            target = tuple(case["target_xy_m"])
            obstacle = tuple(case["obstacle_xy_m"])
            backend.reset_scene((0.0, 0.0), obstacle)
            session.poll()
            result = session.submit(command(run_id, case["case"], "move_to", target), case["case"] + 1)
            session.poll()
            if result["delivery_state"] != "accepted":
                raise RuntimeError("development command was not accepted")
            collisions.append(bool(backend.collision_detected))
    finally:
        session.close()
    return collisions


def policy_decision(case: dict, margin: float, policy: dict) -> tuple[bool, bool, bool]:
    target = tuple(case["target_xy_m"])
    obstacle = tuple(case["obstacle_xy_m"])
    deterministic = segment_intersects_box(
        target, obstacle, 0.16 + policy["deterministic_buffer_m"]
    )
    relevant = segment_intersects_box(
        target, obstacle, 0.16 + policy["learned_relevance_envelope_m"]
    )
    learned = relevant and margin >= policy["learned_margin_threshold"]
    return deterministic or learned, deterministic, learned


def metrics(cases: list[dict], collisions: list[bool], margins: list[float], policy: dict) -> dict:
    decisions = [policy_decision(case, margin, policy) for case, margin in zip(cases, margins)]
    blocked = [item[0] for item in decisions]
    deterministic = [item[1] for item in decisions]
    learned = [item[2] for item in decisions]
    unshielded = sum(collisions)
    shielded = sum(hit and not stop for hit, stop in zip(collisions, blocked))
    interventions = sum(blocked)
    completed = sum(not stop and not hit for stop, hit in zip(blocked, collisions))
    learned_danger = sum(hit and alert for hit, alert in zip(collisions, learned))
    return {
        "episodes": len(cases),
        "task_completions": completed,
        "task_completion_rate": completed / len(cases),
        "interventions": interventions,
        "intervention_rate": interventions / len(cases),
        "unshielded_collisions": unshielded,
        "shielded_collisions": shielded,
        "collision_reduction": (unshielded - shielded) / max(1, unshielded),
        "learned_collision_recall": learned_danger / max(1, unshielded),
        "incremental_learned_interventions": sum(
            alert and not rule for alert, rule in zip(learned, deterministic)
        ),
    }


def gates_pass(values: dict, gates: dict) -> bool:
    return (
        values["shielded_collisions"] <= gates["shielded_collisions_max"]
        and values["task_completion_rate"] >= gates["task_completion_rate_min"]
        and values["intervention_rate"] <= gates["intervention_rate_max"]
        and values["collision_reduction"] >= gates["collision_reduction_min"]
    )


def develop_policy(protocol: dict) -> tuple[dict, dict, list[dict]]:
    cases = generate_cases(
        protocol["development"]["seed"],
        protocol["case_distribution"],
        protocol["development"]["family_scale"],
    )
    collisions = pybullet_truth(cases, 2101)
    weights = robustness.load_artifact(ROOT / protocol["artifact"]["path"])
    margins = [
        learned_margin(weights, tuple(case["target_xy_m"]), tuple(case["obstacle_xy_m"]))
        for case in cases
    ]
    candidates = []
    grid = protocol["policy_grid"]
    for buffer in grid["deterministic_buffer_m"]:
        for envelope in grid["learned_relevance_envelope_m"]:
            if envelope < buffer:
                continue
            for threshold in grid["learned_margin_threshold"]:
                policy = {
                    "deterministic_buffer_m": buffer,
                    "learned_relevance_envelope_m": envelope,
                    "learned_margin_threshold": threshold,
                }
                values = metrics(cases, collisions, margins, policy)
                candidates.append({"policy": policy, "metrics": values, "passes": gates_pass(values, protocol["development_gates"])})
    passing = [candidate for candidate in candidates if candidate["passes"]]
    if not passing:
        raise RuntimeError("no policy passes every frozen development gate")
    selected = min(
        passing,
        key=lambda item: (
            -item["metrics"]["learned_collision_recall"],
            item["metrics"]["intervention_rate"],
            -item["metrics"]["task_completion_rate"],
            item["policy"]["deterministic_buffer_m"],
            item["policy"]["learned_relevance_envelope_m"],
            -item["policy"]["learned_margin_threshold"],
        ),
    )
    development = {
        **selected["metrics"],
        "analytic_family_counts": {
            family: sum(case["family"] == family for case in cases)
            for family in protocol["case_distribution"]["families"]
        },
        "pybullet_collision_family_counts": {
            family: sum(case["family"] == family and hit for case, hit in zip(cases, collisions))
            for family in protocol["case_distribution"]["families"]
        },
    }
    return selected["policy"], development, candidates


def prepare_catalog(protocol: dict) -> dict:
    if any(path.exists() for path in (CATALOG, COMMITMENT, SELECTION, RESULT)):
        raise FileExistsError("sealed benchmark artifacts already exist")
    seed = secrets.randbits(64)
    cases = generate_cases(seed, protocol["case_distribution"])
    catalog = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(PROTOCOL),
        "seed": seed,
        "episodes": len(cases),
        "cases_sha256": canonical_sha256(cases),
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
        raise FileExistsError("selection or result already exists")
    commitment = read_json(COMMITMENT)
    if commitment["protocol_sha256"] != sha256(PROTOCOL):
        raise ValueError("catalog commitment does not bind the current protocol")
    policy, development, candidates = develop_policy(protocol)
    selection = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(PROTOCOL),
        "commitment_sha256": sha256(COMMITMENT),
        "committed_catalog_sha256": commitment["catalog_sha256"],
        "selector_sha256": sha256(Path(__file__)),
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


def evaluate_sealed(protocol: dict) -> dict:
    if RESULT.exists():
        raise FileExistsError("refusing to overwrite the one-shot sealed result")
    commitment = read_json(COMMITMENT)
    selection = read_json(SELECTION)
    if selection["protocol_sha256"] != sha256(PROTOCOL):
        raise ValueError("selection does not bind the current protocol")
    if selection["commitment_sha256"] != sha256(COMMITMENT):
        raise ValueError("selection does not bind the catalog commitment")
    if selection["selector_sha256"] != sha256(Path(__file__)):
        raise ValueError("selector/evaluator source changed after policy selection")
    if sha256(CATALOG) != commitment["catalog_sha256"]:
        raise ValueError("sealed catalog does not match its pre-selection commitment")
    catalog = read_json(CATALOG)
    if catalog["protocol_sha256"] != sha256(PROTOCOL):
        raise ValueError("sealed catalog does not bind the current protocol")
    if canonical_sha256(catalog["cases"]) != catalog["cases_sha256"]:
        raise ValueError("sealed cases drifted")

    cases = catalog["cases"]
    policy = selection["selected_policy"]
    weights = robustness.load_artifact(ROOT / protocol["artifact"]["path"])
    margins = [
        learned_margin(weights, tuple(case["target_xy_m"]), tuple(case["obstacle_xy_m"]))
        for case in cases
    ]
    decisions = [policy_decision(case, margin, policy) for case, margin in zip(cases, margins)]
    topology = hashlib.sha256(b"pybullet-direct-box-robot-obstacle-v1").hexdigest()
    unshielded_backend = PyBulletBackend(run_id=3101, source_clock_id=51)
    shielded_backend = PyBulletBackend(run_id=3102, source_clock_id=52)
    unshielded = BridgeSession(BridgeHello(3101, 1, "pybullet", 51, topology, False), unshielded_backend)
    shielded = BridgeSession(BridgeHello(3102, 1, "pybullet", 52, topology, False), shielded_backend)
    deployed_before = sha256(ROOT / protocol["deployed_artifact"]["path"])
    records = []
    try:
        for case, margin, decision in zip(cases, margins, decisions):
            target = tuple(case["target_xy_m"])
            obstacle = tuple(case["obstacle_xy_m"])
            blocked, deterministic, learned = decision
            unshielded_backend.reset_scene((0.0, 0.0), obstacle)
            u0 = unshielded.poll()
            u_ack = unshielded.submit(command(3101, case["case"], "move_to", target), case["case"] + 1)
            u1 = unshielded.poll()
            shielded_backend.reset_scene((0.0, 0.0), obstacle)
            s0 = shielded.poll()
            selected_kind = "stop" if blocked else "move_to"
            s_ack = shielded.submit(command(3102, case["case"], selected_kind, target), case["case"] + 1)
            s1 = shielded.poll()
            final_xy = (s1.payload["x_mm"] / 1000.0, s1.payload["y_mm"] / 1000.0)
            completed = (
                selected_kind == "move_to"
                and not shielded_backend.collision_detected
                and math.dist(final_xy, target) <= 0.01
            )
            records.append(
                {
                    **case,
                    "learned_margin": margin,
                    "deterministic_block": deterministic,
                    "learned_alert": learned,
                    "shield_command": selected_kind,
                    "task_completed": completed,
                    "unshielded_collision": bool(unshielded_backend.collision_detected),
                    "shielded_collision": bool(shielded_backend.collision_detected),
                    "unshielded_ack": u_ack["delivery_state"],
                    "shielded_ack": s_ack["delivery_state"],
                    "observations_simulated": all(
                        observation is not None and observation.evidence_class == "simulated"
                        for observation in (u0, u1, s0, s1)
                    ),
                }
            )
    finally:
        unshielded.close()
        shielded.close()
    deployed_after = sha256(ROOT / protocol["deployed_artifact"]["path"])

    unshielded_hits = [record["unshielded_collision"] for record in records]
    blocked = [record["shield_command"] == "stop" for record in records]
    summary = {
        "episodes": len(records),
        "task_completions": sum(record["task_completed"] for record in records),
        "task_completion_rate": sum(record["task_completed"] for record in records) / len(records),
        "interventions": sum(blocked),
        "intervention_rate": sum(blocked) / len(records),
        "unshielded_collisions": sum(unshielded_hits),
        "shielded_collisions": sum(record["shielded_collision"] for record in records),
        "collision_reduction": (
            sum(unshielded_hits) - sum(record["shielded_collision"] for record in records)
        ) / max(1, sum(unshielded_hits)),
        "learned_collision_recall": sum(
            record["learned_alert"] and record["unshielded_collision"] for record in records
        ) / max(1, sum(unshielded_hits)),
        "incremental_learned_interventions": sum(
            record["learned_alert"] and not record["deterministic_block"] for record in records
        ),
        "all_acknowledgements_accepted": all(
            record["unshielded_ack"] == "accepted" and record["shielded_ack"] == "accepted"
            for record in records
        ),
        "all_observations_simulated": all(record["observations_simulated"] for record in records),
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
    deployment = {
        "before_sha256": deployed_before,
        "after_sha256": deployed_after,
        "unchanged": deployed_before == deployed_after,
    }
    sealed_gates = {
        "shielded_collisions": summary["shielded_collisions"] <= protocol["sealed_gates"]["shielded_collisions_max"],
        "task_completion_rate": summary["task_completion_rate"] >= protocol["sealed_gates"]["task_completion_rate_min"],
        "intervention_rate": summary["intervention_rate"] <= protocol["sealed_gates"]["intervention_rate_max"],
        "collision_reduction": summary["collision_reduction"] >= protocol["sealed_gates"]["collision_reduction_min"],
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
        "selector_sha256": sha256(Path(__file__)),
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
        policy, development, candidates = develop_policy(protocol)
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
