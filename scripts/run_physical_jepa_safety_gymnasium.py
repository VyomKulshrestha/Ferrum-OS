#!/usr/bin/env python3
"""Select and evaluate a useful Physical JEPA operating point on Safety-Gymnasium."""

from __future__ import annotations

import argparse
import copy
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import sys
import warnings

import mujoco
import numpy as np
import safety_gymnasium


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_physical_jepa_robustness as robustness  # noqa: E402
import select_physical_jepa_v5 as v5  # noqa: E402
import train_physical_world_model as physical  # noqa: E402


PROTOCOL = ROOT / "docs" / "research" / "physical_jepa_safety_gymnasium_protocol_v1.json"
SELECTION = ROOT / "docs" / "research" / "physical_jepa_safety_gymnasium_selection_v1.json"
FINAL_RESULT = ROOT / "docs" / "research" / "physical_jepa_safety_gymnasium_result_v1.json"
FINAL_CASES = ROOT / "docs" / "research" / "physical_jepa_safety_gymnasium_cases_v1.jsonl"
SYNC_ARRAYS = (
    "qpos",
    "qvel",
    "act",
    "qacc_warmstart",
    "ctrl",
    "mocap_pos",
    "mocap_quat",
    "userdata",
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_tree_digest() -> tuple[int, str]:
    package_root = Path(safety_gymnasium.__file__).resolve().parent
    files = sorted(
        (
            path
            for path in package_root.rglob("*")
            if path.is_file() and path.suffix in {".py", ".xml"}
        ),
        key=lambda path: path.relative_to(package_root).as_posix(),
    )
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(package_root).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "little"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "little"))
        digest.update(payload)
    return len(files), digest.hexdigest()


def wilson(successes: int, total: int, z: float = 1.959963984540054) -> list[float]:
    if total == 0:
        return [0.0, 1.0]
    proportion = successes / total
    denominator = 1.0 + z * z / total
    center = (proportion + z * z / (2.0 * total)) / denominator
    half = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / total
            + z * z / (4.0 * total * total)
        )
        / denominator
    )
    return [max(0.0, center - half), min(1.0, center + half)]


def proposal(observation: np.ndarray, episode: dict) -> tuple[np.ndarray, float]:
    start, end = episode["proposal_controller"]["goal_lidar_slice"]
    goal_lidar = observation[start:end]
    index = int(np.argmax(goal_lidar))
    angle = index * 2.0 * math.pi / episode["proposal_controller"]["lidar_bins"]
    if angle > math.pi:
        angle -= 2.0 * math.pi
    aligned = abs(angle) < episode["proposal_controller"]["alignment_radians"]
    forward = (
        episode["proposal_controller"]["forward_when_aligned"]
        if aligned
        else episode["proposal_controller"]["forward_when_unaligned"]
    )
    turn = float(
        np.clip(episode["proposal_controller"]["turn_gain"] * angle, -1.0, 1.0)
    )
    return np.asarray([forward, turn], dtype=np.float64), angle


def physical_state(observation: np.ndarray, episode: dict) -> np.ndarray:
    hazard_start, hazard_end = episode["proposal_controller"]["hazards_lidar_slice"]
    goal_start, goal_end = episode["proposal_controller"]["goal_lidar_slice"]
    state = np.zeros(physical.STATE_SIZE, dtype=np.float32)
    state[physical.CLEARANCE] = 1.0 - float(np.max(observation[hazard_start:hazard_end]))
    state[physical.BATTERY] = 0.8
    state[physical.LINK] = 0.9
    state[physical.HEALTH] = 0.8
    state[physical.PROGRESS] = float(np.max(observation[goal_start:goal_end]))
    state[physical.ONLINE] = 1.0
    state[physical.VELOCITY] = float(np.clip(np.linalg.norm(observation[3:6]), 0.0, 1.0))
    state[physical.MARGIN] = 1.0
    state[physical.APPROVAL] = 1.0
    return state


def decision_inputs(
    observation: np.ndarray,
    proposed: np.ndarray,
    goal_angle: float,
    weights: dict,
    episode: dict,
) -> tuple[float, float]:
    hazard_start, hazard_end = episode["proposal_controller"]["hazards_lidar_slice"]
    hazard_closeness = float(np.max(observation[hazard_start:hazard_end]))
    state = physical_state(observation, episode)
    forward = float(abs(proposed[0]))
    features = np.asarray(
        [math.cos(goal_angle) * forward, math.sin(goal_angle) * forward, forward],
        dtype=np.float32,
    )
    predicted = v5.batch_prediction(
        weights,
        state[None, :],
        np.asarray([physical.MOVE], dtype=np.int64),
        features[None, :],
    )[0]
    return hazard_closeness, float(predicted[physical.CLEARANCE])


def synchronize(main_env, oracle_env) -> None:
    main_task = main_env.unwrapped.task
    oracle_task = oracle_env.unwrapped.task
    for name in SYNC_ARRAYS:
        source = getattr(main_task.data, name)
        target = getattr(oracle_task.data, name)
        if source.size:
            np.copyto(target, source)
    oracle_task.data.time = main_task.data.time
    oracle_task.last_dist_goal = copy.deepcopy(main_task.last_dist_goal)
    oracle_env.unwrapped.steps = main_env.unwrapped.steps
    mujoco.mj_forward(oracle_task.model, oracle_task.data)


def fallback_action(
    observation: np.ndarray,
    episode: dict,
    seed: int,
    recovery_sign: float | None,
    forward: float = 0.0,
) -> tuple[np.ndarray, float]:
    start, end = episode["proposal_controller"]["hazards_lidar_slice"]
    hazards = observation[start:end]
    index = int(np.argmax(hazards))
    angle = index * 2.0 * math.pi / episode["proposal_controller"]["lidar_bins"]
    if angle > math.pi:
        angle -= 2.0 * math.pi
    if recovery_sign is None:
        if abs(angle) < math.pi / episode["proposal_controller"]["lidar_bins"]:
            recovery_sign = 1.0 if seed % 2 == 0 else -1.0
        else:
            recovery_sign = -1.0 if angle > 0.0 else 1.0
    return np.asarray([forward, recovery_sign], dtype=np.float64), recovery_sign


def run_episode(
    seed: int,
    arm: str,
    policy: dict,
    protocol: dict,
    weights: dict,
    capture_cases: bool,
) -> tuple[dict, list[dict]]:
    environment = protocol["external_benchmark"]["environment"]
    main_env = safety_gymnasium.make(environment)
    oracle_env = safety_gymnasium.make(environment)
    observation, _ = main_env.reset(seed=seed)
    oracle_observation, _ = oracle_env.reset(seed=seed)
    if not np.allclose(observation, oracle_observation, atol=1e-12, rtol=0.0):
        raise ValueError(f"mirrored reset mismatch for seed {seed}")

    counts = {
        "seed": seed,
        "proposals": 0,
        "dangerous_proposals": 0,
        "safe_proposals": 0,
        "interventions": 0,
        "true_positive_interventions": 0,
        "false_positive_interventions": 0,
        "false_negative_proposals": 0,
        "true_negative_proposals": 0,
        "actual_hazard_cost_events": 0,
        "learned_only_interventions": 0,
        "learned_only_dangerous_interventions": 0,
        "task_completed": False,
        "steps": 0,
    }
    cases: list[dict] = []
    recovery_sign: float | None = None
    recovery_turn_remaining = 0
    recovery_bypass_remaining = 0
    try:
        for step in range(protocol["episode"]["maximum_steps"]):
            proposed, goal_angle = proposal(observation, protocol["episode"])
            hazard_closeness, predicted_clearance = decision_inputs(
                observation,
                proposed,
                goal_angle,
                weights,
                protocol["episode"],
            )
            moving = bool(proposed[0] > 0.0)
            rule_block = moving and hazard_closeness >= policy["rule_hazard_closeness_threshold"]
            learned_block = (
                moving
                and predicted_clearance
                <= policy["learned_predicted_clearance_threshold"]
            )
            base_block = {
                "unshielded": False,
                "rules_only": rule_block,
                "learned_only": learned_block,
                "rules_plus_learned": rule_block or learned_block,
            }[arm]
            state_machine_active = (
                recovery_turn_remaining > 0 or recovery_bypass_remaining > 0
            )
            block = base_block or state_machine_active

            synchronize(main_env, oracle_env)
            _, oracle_reward, oracle_cost, _, _, oracle_info = oracle_env.step(proposed)
            dangerous = bool(oracle_cost > 0.0 or oracle_info.get("cost_hazards", 0.0) > 0.0)

            recovery_phase = "none"
            if state_machine_active:
                if recovery_turn_remaining > 0:
                    actual = np.asarray([0.0, recovery_sign], dtype=np.float64)
                    recovery_turn_remaining -= 1
                    recovery_phase = "turn"
                else:
                    actual = np.asarray(
                        [
                            policy["recovery_bypass_forward"],
                            recovery_sign * policy["recovery_bypass_turn"],
                        ],
                        dtype=np.float64,
                    )
                    recovery_bypass_remaining -= 1
                    recovery_phase = "bypass"
                    if recovery_bypass_remaining == 0:
                        recovery_sign = None
            elif base_block and "recovery_turn_steps" in policy:
                _, recovery_sign = fallback_action(
                    observation,
                    protocol["episode"],
                    seed,
                    recovery_sign,
                )
                recovery_turn_remaining = max(0, policy["recovery_turn_steps"] - 1)
                recovery_bypass_remaining = policy["recovery_bypass_steps"]
                actual = np.asarray([0.0, recovery_sign], dtype=np.float64)
                recovery_phase = "turn"
            elif block:
                actual, recovery_sign = fallback_action(
                    observation,
                    protocol["episode"],
                    seed,
                    recovery_sign,
                    policy.get("fallback_forward", 0.0),
                )
            else:
                actual = proposed
                recovery_sign = None

            next_observation, reward, cost, terminated, truncated, info = main_env.step(actual)
            actual_cost = bool(cost > 0.0 or info.get("cost_hazards", 0.0) > 0.0)
            completed = bool(reward > 0.5)

            counts["proposals"] += 1
            counts["dangerous_proposals"] += int(dangerous)
            counts["safe_proposals"] += int(not dangerous)
            counts["interventions"] += int(block)
            counts["true_positive_interventions"] += int(block and dangerous)
            counts["false_positive_interventions"] += int(block and not dangerous)
            counts["false_negative_proposals"] += int(not block and dangerous)
            counts["true_negative_proposals"] += int(not block and not dangerous)
            counts["actual_hazard_cost_events"] += int(actual_cost)
            counts["learned_only_interventions"] += int(learned_block and not rule_block)
            counts["learned_only_dangerous_interventions"] += int(
                learned_block and not rule_block and dangerous
            )
            counts["steps"] = step + 1
            counts["task_completed"] = completed

            if capture_cases:
                cases.append(
                    {
                        "arm": arm,
                        "seed": seed,
                        "step": step,
                        "hazard_closeness": hazard_closeness,
                        "predicted_clearance": predicted_clearance,
                        "rule_block": rule_block,
                        "learned_block": learned_block,
                        "intervention": block,
                        "base_intervention": base_block,
                        "recovery_phase": recovery_phase,
                        "dangerous_proposal": dangerous,
                        "actual_hazard_cost": actual_cost,
                        "proposed_action": proposed.tolist(),
                        "applied_action": actual.tolist(),
                        "goal_reached": completed,
                        "oracle_goal_reached": bool(oracle_reward > 0.5),
                    }
                )

            observation = next_observation
            if completed or terminated or truncated:
                break
    finally:
        main_env.close()
        oracle_env.close()
    return counts, cases


def aggregate(episodes: list[dict]) -> dict:
    total = {key: sum(int(item[key]) for item in episodes) for key in (
        "proposals",
        "dangerous_proposals",
        "safe_proposals",
        "interventions",
        "true_positive_interventions",
        "false_positive_interventions",
        "false_negative_proposals",
        "true_negative_proposals",
        "actual_hazard_cost_events",
        "learned_only_interventions",
        "learned_only_dangerous_interventions",
        "steps",
    )}
    total["episodes"] = len(episodes)
    total["task_completions"] = sum(bool(item["task_completed"]) for item in episodes)
    total["task_completion_rate"] = total["task_completions"] / max(1, total["episodes"])
    total["intervention_rate"] = total["interventions"] / max(1, total["proposals"])
    total["dangerous_proposal_recall"] = total["true_positive_interventions"] / max(
        1, total["dangerous_proposals"]
    )
    total["safe_proposal_false_positive_rate"] = total["false_positive_interventions"] / max(
        1, total["safe_proposals"]
    )
    total["actual_hazard_cost_rate"] = total["actual_hazard_cost_events"] / max(
        1, total["proposals"]
    )
    total["episodes_with_actual_hazard_cost"] = sum(
        item["actual_hazard_cost_events"] > 0 for item in episodes
    )
    total["task_completion_wilson_95"] = wilson(total["task_completions"], total["episodes"])
    total["intervention_wilson_95"] = wilson(total["interventions"], total["proposals"])
    total["dangerous_recall_wilson_95"] = wilson(
        total["true_positive_interventions"], total["dangerous_proposals"]
    )
    total["safe_false_positive_wilson_95"] = wilson(
        total["false_positive_interventions"], total["safe_proposals"]
    )
    return total


def bootstrap(episodes: list[dict], seed: int, resamples: int = 5000) -> dict:
    rng = np.random.default_rng(seed)
    values = {
        "task_completion_rate": [],
        "intervention_rate": [],
        "dangerous_proposal_recall": [],
        "safe_proposal_false_positive_rate": [],
        "actual_hazard_cost_rate": [],
    }
    for _ in range(resamples):
        sample = [episodes[index] for index in rng.integers(0, len(episodes), len(episodes))]
        metrics = aggregate(sample)
        for name in values:
            values[name].append(metrics[name])
    return {
        name: [float(np.quantile(items, 0.025)), float(np.quantile(items, 0.975))]
        for name, items in values.items()
    }


def gate_status(metrics: dict, gates: dict, unshielded: dict | None = None) -> dict:
    status = {
        "task_completion_rate": metrics["task_completion_rate"]
        >= gates["task_completion_rate_minimum"],
        "intervention_rate": metrics["intervention_rate"]
        <= gates["intervention_rate_maximum"],
        "dangerous_proposal_recall": metrics["dangerous_proposal_recall"]
        >= gates["dangerous_proposal_recall_minimum"],
        "safe_proposal_false_positive_rate": metrics["safe_proposal_false_positive_rate"]
        <= gates["safe_proposal_false_positive_rate_maximum"],
        "physical_actuator_attempts": gates["physical_actuator_attempts"] == 0,
        "physical_actuator_deliveries": gates["physical_actuator_deliveries"] == 0,
    }
    if "actual_hazard_cost_reduction_fraction_minimum" in gates:
        status["actual_hazard_cost_reduction_fraction"] = (
            unshielded is not None
            and (
                unshielded["actual_hazard_cost_events"]
                - metrics["actual_hazard_cost_events"]
            )
            / max(1, unshielded["actual_hazard_cost_events"])
            >= gates["actual_hazard_cost_reduction_fraction_minimum"]
        )
    return status


def runtime_evidence(protocol: dict) -> dict:
    source_count, source_digest = source_tree_digest()
    expected = protocol["runtime_lock"]
    observed = {
        "python": ".".join(str(value) for value in sys.version_info[:3]),
        "safety_gymnasium": version("safety-gymnasium"),
        "gymnasium": version("gymnasium"),
        "gymnasium_robotics": version("gymnasium-robotics"),
        "mujoco": version("mujoco"),
        "numpy": version("numpy"),
        "pygame": version("pygame"),
    }
    required_keys = (
        "python",
        "safety_gymnasium",
        "gymnasium",
        "gymnasium_robotics",
        "mujoco",
        "numpy",
        "pygame",
    )
    return {
        "observed": observed,
        "versions_match": all(observed[key] == expected[key] for key in required_keys),
        "source_file_count": source_count,
        "source_tree_sha256": source_digest,
        "source_matches": source_count
        == protocol["external_benchmark"]["source_file_count"]
        and source_digest == protocol["external_benchmark"]["source_tree_sha256"],
    }


def run_policy(
    seeds: list[int],
    arm: str,
    policy: dict,
    protocol: dict,
    weights: dict,
    capture_cases: bool,
) -> tuple[list[dict], list[dict]]:
    episodes = []
    cases = []
    for position, seed in enumerate(seeds, 1):
        episode, episode_cases = run_episode(
            seed,
            arm,
            policy,
            protocol,
            weights,
            capture_cases,
        )
        episodes.append(episode)
        cases.extend(episode_cases)
        if position % 16 == 0 or position == len(seeds):
            print(f"{arm}: {position}/{len(seeds)} episodes", flush=True)
    return episodes, cases


def selection(protocol: dict, protocol_path: Path, output: Path) -> None:
    if output.exists():
        raise FileExistsError(f"selection output already exists: {output}")
    runtime = runtime_evidence(protocol)
    if not runtime["versions_match"] or not runtime["source_matches"]:
        raise ValueError(f"external benchmark runtime mismatch: {runtime}")
    artifact = ROOT / protocol["artifact"]["path"]
    if sha256(artifact) != protocol["artifact"]["sha256"]:
        raise ValueError("frozen Physical JEPA v5 artifact mismatch")
    weights = robustness.load_artifact(artifact)
    development = protocol["prospective_boundary"]["pilot_and_development_seeds_already_observed"]
    seeds = list(range(development["start"], development["start"] + development["count"]))
    baseline_metrics = None
    if "actual_hazard_cost_reduction_fraction_minimum" in protocol["frozen_gates"]:
        baseline_episodes, _ = run_policy(
            seeds,
            "unshielded",
            protocol["candidate_policies"][0],
            protocol,
            weights,
            False,
        )
        baseline_metrics = aggregate(baseline_episodes)
    candidates = []
    for candidate in protocol["candidate_policies"]:
        episodes, _ = run_policy(
            seeds,
            "rules_plus_learned",
            candidate,
            protocol,
            weights,
            False,
        )
        metrics = aggregate(episodes)
        if baseline_metrics is not None:
            metrics["actual_hazard_cost_reduction_fraction"] = (
                baseline_metrics["actual_hazard_cost_events"]
                - metrics["actual_hazard_cost_events"]
            ) / max(1, baseline_metrics["actual_hazard_cost_events"])
        gates = gate_status(metrics, protocol["frozen_gates"], baseline_metrics)
        candidates.append(
            {
                "candidate": candidate,
                "metrics": metrics,
                "gates": gates,
                "all_gates_pass": all(gates.values()),
                "episode_summaries": episodes,
            }
        )
    passing = [item for item in candidates if item["all_gates_pass"]]
    passing.sort(
        key=lambda item: (
            -item["metrics"].get("actual_hazard_cost_reduction_fraction", 0.0),
            item["metrics"]["intervention_rate"],
            -item["metrics"]["dangerous_proposal_recall"],
            -item["metrics"]["task_completion_rate"],
            item["metrics"]["safe_proposal_false_positive_rate"],
            item["candidate"]["candidate_id"],
        )
    )
    selected = passing[0] if passing else None
    report = {
        "schema": protocol.get("result_schemas", {}).get(
            "selection", "physical-jepa-safety-gymnasium-selection-v1"
        ),
        "protocol": {"path": str(protocol_path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(protocol_path)},
        "runtime": runtime,
        "development_seeds": seeds,
        "final_seed_access_attempted": False,
        "final_seed_accessed": False,
        "candidates": candidates,
        "unshielded_development_metrics": baseline_metrics,
        "selected_candidate": None if selected is None else selected["candidate"],
        "selection_passed": selected is not None,
        "promotion_eligible": False,
    }
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if selected is None:
        raise SystemExit("no useful-operating-region candidate passed development gates")


def final(
    protocol: dict,
    protocol_path: Path,
    selection_path: Path,
    recovery_path: Path | None,
    output: Path,
    cases_output: Path,
) -> None:
    if output.exists() or cases_output.exists():
        raise FileExistsError("final result or case catalog already exists")
    if not selection_path.is_file():
        raise FileNotFoundError("selection result is required before final execution")
    selected_report = load_json(selection_path)
    if not selected_report.get("selection_passed"):
        raise ValueError("selection did not pass")
    if selected_report["protocol"]["sha256"] != sha256(protocol_path):
        raise ValueError("protocol changed after selection")
    recovery = None
    if recovery_path is not None:
        recovery = load_json(recovery_path)
        if recovery["protocol_sha256"] != sha256(protocol_path):
            raise ValueError("recovery protocol hash mismatch")
        if recovery["selection_sha256"] != sha256(selection_path):
            raise ValueError("recovery selection hash mismatch")
        failed = ROOT / recovery["failed_attempt"]["path"]
        if sha256(failed) != recovery["failed_attempt"]["sha256"]:
            raise ValueError("retained failed-attempt record mismatch")
        failed_cases = ROOT / recovery["failed_catalog"]["path"]
        if sha256(failed_cases) != recovery["failed_catalog"]["sha256"]:
            raise ValueError("retained failed catalog mismatch")
    runtime = runtime_evidence(protocol)
    if not runtime["versions_match"] or not runtime["source_matches"]:
        raise ValueError("external benchmark runtime changed after selection")
    artifact = ROOT / protocol["artifact"]["path"]
    deployment = ROOT / protocol["artifact"]["deployment_target"]
    artifact_before = sha256(artifact)
    deployment_before = sha256(deployment)
    if artifact_before != protocol["artifact"]["sha256"]:
        raise ValueError("frozen artifact changed before final")
    weights = robustness.load_artifact(artifact)
    final_range = protocol["prospective_boundary"]["final_seed_range_unopened_at_registration"]
    seeds = list(range(final_range["start"], final_range["start"] + final_range["count"]))
    selected = selected_report["selected_candidate"]
    arms = {}
    final_cases = []
    for arm in protocol["final_arms"]:
        episodes, cases = run_policy(
            seeds,
            arm,
            selected,
            protocol,
            weights,
            arm == "rules_plus_learned",
        )
        metrics = aggregate(episodes)
        metrics["episode_bootstrap_95"] = bootstrap(
            episodes,
            seed=20260830 + protocol["final_arms"].index(arm),
        )
        arms[arm] = {"metrics": metrics, "episode_summaries": episodes}
        final_cases.extend(cases)

    union = arms["rules_plus_learned"]["metrics"]
    unshielded = arms["unshielded"]["metrics"]
    gates = gate_status(union, protocol["frozen_gates"], unshielded)
    artifact_after = sha256(artifact)
    deployment_after = sha256(deployment)
    gates["protected_deployed_artifact_unchanged"] = (
        artifact_before == artifact_after
        and deployment_before == deployment_after
        and protocol["frozen_gates"]["protected_deployed_artifact_unchanged"]
    )
    avoided = unshielded["actual_hazard_cost_events"] - union["actual_hazard_cost_events"]
    result = {
        "schema": (
            recovery["result_schema"]
            if recovery is not None
            else protocol.get("result_schemas", {}).get(
                "final", "physical-jepa-safety-gymnasium-result-v1"
            )
        ),
        "protocol": {"path": str(protocol_path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(protocol_path)},
        "selection": {"path": str(selection_path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(selection_path)},
        "runtime": runtime,
        "final_seed_range": final_range,
        "final_seed_access_count": (
            recovery["authorized_final_seed_access_count"]
            if recovery is not None
            else 1
        ),
        "recovery": (
            None
            if recovery is None
            else {
                "path": str(recovery_path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256(recovery_path),
                "reason": recovery["reason"],
                "only_code_change": recovery["only_code_change"],
            }
        ),
        "selected_candidate": selected,
        "arms": arms,
        "headline": {
            "task_completion_rate": union["task_completion_rate"],
            "intervention_rate": union["intervention_rate"],
            "dangerous_proposal_recall": union["dangerous_proposal_recall"],
            "safe_proposal_false_positive_rate": union["safe_proposal_false_positive_rate"],
            "unshielded_actual_hazard_cost_events": unshielded["actual_hazard_cost_events"],
            "union_actual_hazard_cost_events": union["actual_hazard_cost_events"],
            "actual_hazard_cost_events_avoided": avoided,
            "actual_hazard_cost_reduction_fraction": avoided
            / max(1, unshielded["actual_hazard_cost_events"]),
            "learned_only_interventions": union["learned_only_interventions"],
            "learned_only_dangerous_interventions": union[
                "learned_only_dangerous_interventions"
            ],
        },
        "frozen_gates": gates,
        "all_frozen_gates_pass": all(gates.values()),
        "physical_actuator_attempts": 0,
        "physical_actuator_deliveries": 0,
        "independent_execution": False,
        "externally_authored_benchmark": True,
        "promotion_eligible": False,
        "protected_artifact": {
            "research_artifact_sha256_before": artifact_before,
            "research_artifact_sha256_after": artifact_after,
            "deployment_sha256_before": deployment_before,
            "deployment_sha256_after": deployment_after,
            "unchanged": artifact_before == artifact_after
            and deployment_before == deployment_after,
        },
        "claim_boundary": [
            "Safety-Gymnasium supplies the task definition, seeded layouts, observations, and hazard costs; the adapter, controller, shield, execution, and analysis are researcher-authored.",
            "The result is an externally designed, locally executed software benchmark, not independent replication or assessment.",
            "The adapter covers the navigation subset only and does not validate maintenance actions, humans, absolute-position prediction, hardware timing, physical contact, or actuator transfer.",
            "Physical actuator authority remained disabled and no deployment artifact was promoted or replaced."
        ],
    }
    with cases_output.open("x", encoding="utf-8", newline="\n") as handle:
        for item in final_cases:
            handle.write(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n")
    result["case_catalog"] = {
        "path": str(cases_output.relative_to(ROOT)).replace("\\", "/"),
        "sha256": sha256(cases_output),
        "rows": len(final_cases),
        "arm": "rules_plus_learned",
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not result["all_frozen_gates_pass"]:
        raise SystemExit("final useful-operating-region gates did not all pass")


def main() -> None:
    warnings.filterwarnings("ignore")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("selection", "final"), required=True)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    parser.add_argument("--selection", type=Path, default=SELECTION)
    parser.add_argument("--recovery", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cases-output", type=Path, default=FINAL_CASES)
    args = parser.parse_args()
    protocol_path = args.protocol.resolve()
    selection_path = args.selection.resolve()
    recovery_path = None if args.recovery is None else args.recovery.resolve()
    protocol = load_json(protocol_path)
    if args.mode == "selection":
        selection(protocol, protocol_path, args.output or selection_path)
    else:
        final(
            protocol,
            protocol_path,
            selection_path,
            recovery_path,
            (args.output or FINAL_RESULT).resolve(),
            args.cases_output.resolve(),
        )


if __name__ == "__main__":
    main()
