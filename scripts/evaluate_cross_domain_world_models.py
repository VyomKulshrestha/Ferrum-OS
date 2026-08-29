#!/usr/bin/env python3
"""Run the registered matched-architecture cross-domain world-model study.

Selection fits only development and validation partitions while an audit hook
denies access to every final incident catalog. Final evaluation is a separate
command and never promotes or installs a checkpoint.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np
import torch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import cross_domain_world_model_models as models  # noqa: E402
import physical_incident_scenarios as physical_incidents  # noqa: E402
import physical_stress_scenarios as physical_stress  # noqa: E402
import train_physical_jepa as physical_jepa  # noqa: E402
import train_physical_world_model as physical_simulator  # noqa: E402
import train_world_model as os_trainer  # noqa: E402
import world_model_incident_scenarios as os_incidents  # noqa: E402
from evaluate_world_model_safety import Encoder  # noqa: E402
from train_world_model_encoder import extract_raw  # noqa: E402


PROTOCOL = (
    ROOT / "docs" / "research" / "cross_domain_world_model_improvement_protocol_v1.json"
)
OS_PROTOCOL = ROOT / "docs" / "research" / "world_model_jepa_v3_protocol.json"
OS_V34_PROTOCOL = ROOT / "docs" / "research" / "world_model_jepa_v3_4_protocol.json"
PHYSICAL_PROTOCOL = ROOT / "docs" / "research" / "physical_jepa_v5_protocol.json"
SELECTION = ROOT / "docs" / "research" / "cross_domain_world_model_selection_v1.json"
RESULT = (
    ROOT / "docs" / "research" / "cross_domain_world_model_architecture_result_v1.json"
)
WORK = ROOT / "target" / "cross-domain-world-model-v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repository_path(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT)).replace("\\", "/")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def verify_digest_map(items: dict) -> dict[str, bool]:
    checks = {}
    for name, item in items.items():
        path = ROOT / item["path"]
        checks[name] = path.is_file() and sha256(path) == item["sha256"]
    return checks


def final_paths(protocol: dict) -> set[Path]:
    paths = {
        ROOT / "docs/research/world_model_incident_final_sources_v3.json",
        ROOT / "docs/research/world_model_incident_final_sources_v3_1.json",
        ROOT / "docs/research/world_model_incident_v3_final_catalog.json",
        ROOT / "docs/research/world_model_incident_v3_4_final_catalog.json",
        ROOT / "docs/research/physical_incident_v5_test_sources.json",
    }
    paths.update(
        ROOT / value
        for value in protocol["learned_contribution_benchmarks"][
            "final_catalogs"
        ].values()
    )
    return {path.resolve() for path in paths}


def install_final_guard(protocol: dict) -> dict:
    protected = final_paths(protocol)
    state = {
        "attempted": False,
        "paths": sorted(repository_path(path) for path in protected),
    }

    def audit(event: str, arguments: tuple) -> None:
        if (
            event != "open"
            or not arguments
            or not isinstance(arguments[0], (str, bytes))
        ):
            return
        try:
            opened = Path(os.fsdecode(arguments[0])).resolve()
        except (OSError, TypeError, ValueError):
            return
        if opened in protected:
            state["attempted"] = True
            raise PermissionError(
                f"final catalog access forbidden during selection: {opened.name}"
            )

    sys.addaudithook(audit)
    return state


def os_spec(protocol: dict) -> models.DomainSpec:
    item = protocol["architecture_controlled_comparison"]["ferrumos"]
    return models.DomainSpec(
        name="ferrumos",
        state_size=item["state_dimensions"],
        action_size=item["action_dimensions"],
        history=protocol["architecture_controlled_comparison"]["shared_conditions"][
            "history_length"
        ],
        scale=np.ones(item["state_dimensions"], dtype=np.float32),
        latent_size=64,
    )


def physical_spec(protocol: dict) -> models.DomainSpec:
    item = protocol["architecture_controlled_comparison"]["physical"]
    return models.DomainSpec(
        name="physical",
        state_size=item["state_dimensions"],
        action_size=item["action_dimensions"],
        history=protocol["architecture_controlled_comparison"]["shared_conditions"][
            "history_length"
        ],
        scale=np.asarray(physical_simulator.STATE_RANGES, dtype=np.float32),
        latent_size=24,
    )


def standardize_os(rows: list[dict], spec: models.DomainSpec) -> list[dict]:
    output = []
    for row in rows:
        if not os_trainer.transition_eligible(row):
            continue
        action_id = int(row["action"])
        output.append(
            {
                "episode": str(row.get("episode_id", f"row-{len(output)}")),
                "step": int(row.get("step", 0)),
                "state": extract_raw(row["before"]).astype(np.float32),
                "action": models.standardize_action(
                    action_id,
                    row.get("action_features", [0.0] * os_trainer.ACTION_FEATURE_SIZE),
                    spec.action_size,
                    os_trainer.NUM_TOOLS,
                ),
                "next_state": extract_raw(row["after"]).astype(np.float32),
                "dangerous": bool(row.get("dangerous", False)),
                "source": str(row.get("source_id", row.get("source", "base"))),
                "hazard": str(row.get("hazard", "unlabelled_base_transition")),
            }
        )
    return output


def standardize_physical(
    rows: list[tuple], metadata: dict, spec: models.DomainSpec, fallback_source: str
) -> list[dict]:
    output = []
    for episode, step, state, action, features, next_state, dangerous in rows:
        item = metadata.get(episode, {})
        output.append(
            {
                "episode": str(episode),
                "step": int(step),
                "state": np.asarray(state, dtype=np.float32),
                "action": models.standardize_action(
                    int(action),
                    features,
                    spec.action_size,
                    physical_simulator.ACTION_COUNT,
                ),
                "next_state": np.asarray(next_state, dtype=np.float32),
                "dangerous": bool(dangerous),
                "source": str(item.get("source_id", item.get("case", fallback_source))),
                "hazard": ",".join(
                    item.get("hazard_tags", [item.get("case", fallback_source)])
                ),
            }
        )
    return output


def base_os_partitions(dataset_path: Path) -> tuple[list[dict], list[dict], list[dict]]:
    rows = os_trainer.load_dataset(dataset_path)
    eligible = [row for row in rows if os_trainer.transition_eligible(row)]
    train_idx, validation_idx, test_idx, split_mode = os_trainer.split_indices(
        eligible, 0.15, 0.15, 42
    )
    if split_mode != "episode":
        raise AssertionError(
            "registered OS comparison requires an episode-disjoint split"
        )
    return (
        [eligible[int(index)] for index in train_idx],
        [eligible[int(index)] for index in validation_idx],
        [eligible[int(index)] for index in test_idx],
    )


def os_development(protocol: dict, smoke: bool = False):
    spec = os_spec(protocol)
    frozen = protocol["frozen_research_inputs"]
    dataset = ROOT / frozen["ferrumos_base_dataset"]["path"]
    if sha256(dataset) != frozen["ferrumos_base_dataset"]["sha256"]:
        raise AssertionError("OS base dataset drifted")
    base_train, base_validation, _ = base_os_partitions(dataset)
    inherited = load_json(OS_PROTOCOL)
    encoder = Encoder(ROOT / "appliance/world-model/model_encoder.bin")
    source_catalog = (
        ROOT / "docs/research" / inherited["fit_partitions"]["incident"]["catalog"]
    )
    fit = inherited["fit_partitions"]["incident"]
    select = inherited["selection_partitions"]["incident"]
    train_cases, train_metadata = os_incidents.generate_partition(
        source_catalog,
        fit["partition"],
        8 if smoke else fit["episodes_per_source"],
        fit["maximum_steps"],
        fit["seed"],
    )
    validation_cases, validation_metadata = os_incidents.generate_partition(
        source_catalog,
        select["partition"],
        8 if smoke else select["episodes_per_source"],
        select["maximum_steps"],
        select["seed"],
    )
    train_rows = standardize_os(base_train[:512] if smoke else base_train, spec)
    train_rows += standardize_os(
        os_incidents.transition_rows(train_cases, encoder), spec
    )
    validation_rows = standardize_os(
        base_validation[:256] if smoke else base_validation, spec
    )
    validation_rows += standardize_os(
        os_incidents.transition_rows(validation_cases, encoder), spec
    )
    return (
        spec,
        train_rows,
        validation_rows,
        {
            "base_train_rows": min(512, len(base_train)) if smoke else len(base_train),
            "base_validation_rows": (
                min(256, len(base_validation)) if smoke else len(base_validation)
            ),
            "incident_train": train_metadata,
            "incident_validation": validation_metadata,
        },
    )


def physical_development(protocol: dict, smoke: bool = False):
    spec = physical_spec(protocol)
    inherited = load_json(PHYSICAL_PROTOCOL)
    fit = inherited["fit_partitions"]
    validation = inherited["selection_partitions"]
    base_episodes = 96 if smoke else fit["base"]["episodes"]
    base_rows = physical_simulator.generate(
        base_episodes, fit["base"]["steps"], fit["base"]["seed"]
    )
    _, _, base_train, base_validation, _ = physical_jepa.split_rows(
        base_rows, base_episodes, fit["base"]["seed"]
    )
    catalog = ROOT / "docs/research" / fit["incident_v2"]["catalog"]
    incident_train, incident_train_metadata = physical_incidents.generate_partition(
        fit["incident_v2"]["partition"],
        8 if smoke else fit["incident_v2"]["episodes_per_source"],
        fit["incident_v2"]["steps"],
        fit["incident_v2"]["seed"],
        catalog,
    )
    incident_validation, incident_validation_metadata = (
        physical_incidents.generate_partition(
            validation["incident_v2"]["partition"],
            8 if smoke else validation["incident_v2"]["episodes_per_source"],
            validation["incident_v2"]["steps"],
            validation["incident_v2"]["seed"],
            catalog,
        )
    )
    stress_train, stress_train_metadata = physical_stress.generate_partition(
        fit["stress"]["partition"],
        48 if smoke else fit["stress"]["episodes"],
        fit["stress"]["steps"],
        fit["stress"]["seed"],
    )
    stress_validation, stress_validation_metadata = physical_stress.generate_partition(
        validation["stress"]["partition"],
        32 if smoke else validation["stress"]["episodes"],
        validation["stress"]["steps"],
        validation["stress"]["seed"],
    )
    base_train_metadata = {row[0]: {"case": "base"} for row in base_train}
    base_validation_metadata = {row[0]: {"case": "base"} for row in base_validation}
    train_rows = standardize_physical(base_train, base_train_metadata, spec, "base")
    train_rows += standardize_physical(
        incident_train, incident_train_metadata, spec, "incident"
    )
    train_rows += standardize_physical(
        stress_train, stress_train_metadata, spec, "stress"
    )
    validation_rows = standardize_physical(
        base_validation, base_validation_metadata, spec, "base"
    )
    validation_rows += standardize_physical(
        incident_validation, incident_validation_metadata, spec, "incident"
    )
    validation_rows += standardize_physical(
        stress_validation, stress_validation_metadata, spec, "stress"
    )
    return (
        spec,
        train_rows,
        validation_rows,
        {
            "base_train_rows": len(base_train),
            "base_validation_rows": len(base_validation),
            "incident_train": physical_incidents.summarize(
                incident_train, incident_train_metadata
            ),
            "incident_validation": physical_incidents.summarize(
                incident_validation, incident_validation_metadata
            ),
            "stress_train": physical_stress.summarize(
                stress_train, stress_train_metadata
            ),
            "stress_validation": physical_stress.summarize(
                stress_validation, stress_validation_metadata
            ),
        },
    )


def os_final(protocol: dict):
    spec = os_spec(protocol)
    dataset = ROOT / protocol["frozen_research_inputs"]["ferrumos_base_dataset"]["path"]
    _, _, base_test = base_os_partitions(dataset)
    inherited = load_json(OS_V34_PROTOCOL)
    final = inherited["final_test"]
    source_catalog = ROOT / "docs/research" / inherited["final_source_catalog"]["path"]
    cases, metadata = os_incidents.generate_partition(
        source_catalog,
        final["partition"],
        final["episodes_per_source"],
        final["maximum_steps"],
        final["seed"],
    )
    encoder = Encoder(ROOT / "appliance/world-model/model_encoder.bin")
    rows = standardize_os(base_test, spec)
    rows += standardize_os(os_incidents.transition_rows(cases, encoder), spec)
    return spec, rows, {"base_test_rows": len(base_test), "incident_final": metadata}


def physical_final(protocol: dict):
    spec = physical_spec(protocol)
    inherited = load_json(PHYSICAL_PROTOCOL)
    final = inherited["final_test"]
    catalog = ROOT / "docs/research" / final["catalog"]
    rows, metadata = physical_incidents.generate_partition(
        "test", final["episodes_per_source"], final["steps"], final["seed"], catalog
    )
    return (
        spec,
        standardize_physical(rows, metadata, spec, "final"),
        {"final": physical_incidents.summarize(rows, metadata)},
    )


def relative_checkpoint_record(record: dict) -> dict:
    value = dict(record)
    value["path"] = repository_path(Path(record["path"]))
    return value


def selection_stage(args, protocol: dict) -> int:
    guard = install_final_guard(protocol)
    deployed_before = verify_digest_map(protocol["protected_deployed_artifacts"])
    frozen_inputs = verify_digest_map(protocol["frozen_research_inputs"])
    if not all(deployed_before.values()) or not all(frozen_inputs.values()):
        raise AssertionError("a protected artifact or frozen research input drifted")
    settings = copy.deepcopy(
        protocol["architecture_controlled_comparison"]["shared_conditions"]
    )
    seeds = list(settings["training_seeds"])
    work = WORK
    output = SELECTION
    if args.smoke:
        settings["optimizer_updates"] = 2
        settings["checkpoint_interval_updates"] = 1
        settings["batch_size"] = 32
        seeds = seeds[:1]
        work = ROOT / "target/cross-domain-world-model-smoke"
        output = work / "selection.json"
    domains = {
        "ferrumos": os_development(protocol, args.smoke),
        "physical": physical_development(protocol, args.smoke),
    }
    domain_results = {}
    for domain, (spec, train_rows, validation_rows, provenance) in domains.items():
        train_data = models.sequence_data(train_rows, spec)
        validation_data = models.sequence_data(validation_rows, spec)
        statistics = models.ood_statistics(train_data)
        method_results = {}
        for method in models.METHODS:
            runs = []
            for seed in seeds:
                print(f"training {domain} {method} seed={seed}", flush=True)
                model, metrics = models.fit_model(
                    method, spec, train_data, validation_data, seed, settings
                )
                checkpoint_path = models.model_record_path(work, domain, method, seed)
                checkpoint = models.save_model(checkpoint_path, model, metrics)
                metrics["checkpoint"] = relative_checkpoint_record(checkpoint)
                runs.append(metrics)
            method_results[method] = runs
        domain_results[domain] = {
            "provenance": provenance,
            "train_examples": len(train_data.states),
            "validation_examples": len(validation_data.states),
            "training_rows_sha256": models.canonical_sha256(
                [[row["episode"], row["step"], row["source"]] for row in train_rows]
            ),
            "validation_rows_sha256": models.canonical_sha256(
                [
                    [row["episode"], row["step"], row["source"]]
                    for row in validation_rows
                ]
            ),
            "ood_statistics": {
                "mean": statistics["mean"].tolist(),
                "std": statistics["std"].tolist(),
            },
            "methods": method_results,
        }
    deployed_after = verify_digest_map(protocol["protected_deployed_artifacts"])
    checks = {
        "protected_deployed_digests_valid_before": all(deployed_before.values()),
        "protected_deployed_digests_unchanged_after": deployed_before == deployed_after,
        "frozen_research_inputs_valid": all(frozen_inputs.values()),
        "final_catalog_access_not_attempted": not guard["attempted"],
        "all_predictions_finite": all(
            run["validation"]["all_predictions_finite"]
            for domain in domain_results.values()
            for runs in domain["methods"].values()
            for run in runs
        ),
        "fixed_update_budget_completed": all(
            run["optimizer_updates_completed"] == settings["optimizer_updates"]
            for domain in domain_results.values()
            for runs in domain["methods"].values()
            for run in runs
        ),
        "parameter_budget_respected": all(
            settings["trainable_parameter_budget"]
            * (1.0 - settings["parameter_budget_tolerance_fraction"])
            <= run["trainable_parameters"]
            <= settings["trainable_parameter_budget"]
            for domain in domain_results.values()
            for runs in domain["methods"].values()
            for run in runs
        ),
    }
    result = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "stage": "smoke-selection" if args.smoke else "validation-only-selection",
        "protocol_sha256": sha256(PROTOCOL),
        "torch_version": torch.__version__,
        "numpy_version": np.__version__,
        "settings": settings,
        "seeds": seeds,
        "final_catalog_guard": guard,
        "protected_digests_before": deployed_before,
        "protected_digests_after": deployed_after,
        "checks": checks,
        "selection_passed": all(checks.values()),
        "final_test_opened": False,
        "promotion_eligible": False,
        "domains": domain_results,
        "claim_boundary": protocol["claim_boundary"],
    }
    write_json(output, result)
    print(
        json.dumps(
            {
                "output": repository_path(output),
                "selection_passed": result["selection_passed"],
            },
            indent=2,
        )
    )
    return 0 if result["selection_passed"] else 1


def source_metrics(errors: np.ndarray, sources: list[str]) -> dict:
    values = np.asarray(sources)
    return {
        source: {
            "rows": int(np.sum(values == source)),
            "normalized_error": float(errors[values == source].mean()),
        }
        for source in sorted(set(sources))
    }


def evaluate_domain(
    domain: str,
    spec: models.DomainSpec,
    rows: list[dict],
    selection: dict,
    settings: dict,
) -> dict:
    data = models.sequence_data(rows, spec)
    statistics = {
        "mean": np.asarray(selection["ood_statistics"]["mean"], dtype=np.float32),
        "std": np.asarray(selection["ood_statistics"]["std"], dtype=np.float32),
    }
    ood = models.ood_scores(data, statistics)
    output = {"examples": len(data.states), "methods": {}}
    ensemble_errors = {}
    ensemble_rollout_errors = {}
    for method, runs in selection["methods"].items():
        predicted_members = []
        aleatoric_members = []
        run_results = []
        loaded = []
        for run in runs:
            checkpoint = ROOT / run["checkpoint"]["path"]
            model = models.load_model(
                checkpoint,
                method,
                spec,
                run["hidden_size"],
                run["checkpoint"]["sha256"],
            )
            loaded.append(model)
            predicted, variance = models.one_step_predictions(model, data, spec)
            predicted_members.append(predicted)
            aleatoric_members.append(variance)
            errors = models.normalized_errors(predicted, data.next_states, spec)
            run_results.append(
                {
                    "seed": run["seed"],
                    "one_step": models.episode_bootstrap(
                        errors, data.episodes, run["seed"]
                    ),
                    "per_source": source_metrics(errors, data.sources),
                }
            )
        member_array = np.stack(predicted_members)
        ensemble_prediction = member_array.mean(axis=0)
        errors = models.normalized_errors(ensemble_prediction, data.next_states, spec)
        ensemble_errors[method] = errors
        epistemic = np.mean(np.var(member_array / spec.scale, axis=0), axis=1)
        aleatoric = np.mean(np.stack(aleatoric_members), axis=(0, 2))
        normalized_ood = ood / max(float(np.median(ood)), 1e-8)
        total_uncertainty = (
            epistemic / max(float(np.median(epistemic)), 1e-8)
            + aleatoric / max(float(np.median(aleatoric)), 1e-8)
            + normalized_ood
        )
        rollouts = {}
        ensemble_rollout_errors[method] = {}
        for horizon in (1, 3, 5):
            predictions = []
            actual = episodes = sources = None
            per_seed = []
            for run, model in zip(runs, loaded):
                predicted, current_actual, current_episodes, current_sources = (
                    models.rollout_predictions(model, rows, spec, horizon)
                )
                predictions.append(predicted)
                current_errors = models.normalized_errors(
                    predicted, current_actual, spec
                )
                per_seed.append(
                    {
                        "seed": run["seed"],
                        **models.episode_bootstrap(
                            current_errors, current_episodes, run["seed"] + horizon
                        ),
                    }
                )
                actual, episodes, sources = (
                    current_actual,
                    current_episodes,
                    current_sources,
                )
            ensemble_prediction_h = np.stack(predictions).mean(axis=0)
            current_errors = models.normalized_errors(
                ensemble_prediction_h, actual, spec
            )
            ensemble_rollout_errors[method][horizon] = (current_errors, episodes)
            rollouts[f"h{horizon}"] = {
                "members": per_seed,
                "ensemble": models.episode_bootstrap(
                    current_errors, episodes, settings["split_seed"] + horizon
                ),
                "per_source": source_metrics(current_errors, sources),
            }
        output["methods"][method] = {
            "runs": run_results,
            "ensemble_one_step": models.episode_bootstrap(
                errors, data.episodes, settings["split_seed"]
            ),
            "uncertainty": {
                "mean_epistemic_variance": float(epistemic.mean()),
                "mean_aleatoric_variance": float(aleatoric.mean()),
                "mean_ood_score": float(ood.mean()),
                "risk_coverage": models.risk_coverage(errors, total_uncertainty),
            },
            "rollout": rollouts,
        }
    comparisons = {}
    for left_index, left in enumerate(models.METHODS):
        for right in models.METHODS[left_index + 1 :]:
            item = {}
            for horizon in (1, 3, 5):
                left_errors, episodes = ensemble_rollout_errors[left][horizon]
                right_errors, right_episodes = ensemble_rollout_errors[right][horizon]
                if not np.array_equal(episodes, right_episodes):
                    raise AssertionError(
                        "paired rollout episodes drifted between methods"
                    )
                item[f"h{horizon}"] = models.paired_bootstrap(
                    left_errors,
                    right_errors,
                    episodes,
                    settings["split_seed"] + 100 * left_index + horizon,
                )
            comparisons[f"{left}_minus_{right}"] = item
    output["paired_architecture_comparisons"] = comparisons
    return output


def final_stage(args, protocol: dict) -> int:
    if not SELECTION.is_file():
        raise FileNotFoundError("run validation-only selection before final evaluation")
    selection = load_json(SELECTION)
    if not selection["selection_passed"] or selection["final_test_opened"]:
        raise AssertionError("selection is not final-evaluation eligible")
    if RESULT.exists():
        raise FileExistsError(
            "final architecture result already exists; refusing a second opening"
        )
    deployed_before = verify_digest_map(protocol["protected_deployed_artifacts"])
    settings = protocol["architecture_controlled_comparison"]["shared_conditions"]
    os_current = os_final(protocol)
    physical_current = physical_final(protocol)
    domains = {
        "ferrumos": (os_current, selection["domains"]["ferrumos"]),
        "physical": (physical_current, selection["domains"]["physical"]),
    }
    evaluated = {}
    for domain, ((spec, rows, provenance), selected) in domains.items():
        print(f"evaluating final {domain}", flush=True)
        evaluated[domain] = {
            "provenance": provenance,
            **evaluate_domain(domain, spec, rows, selected, settings),
        }
    deployed_after = verify_digest_map(protocol["protected_deployed_artifacts"])
    checks = {
        "selection_passed": selection["selection_passed"],
        "selection_final_catalog_guard_passed": selection["checks"][
            "final_catalog_access_not_attempted"
        ],
        "protected_digests_valid_before": all(deployed_before.values()),
        "protected_digests_unchanged_after": deployed_before == deployed_after,
        "all_registered_methods_present": all(
            set(result["methods"]) == set(models.METHODS)
            for result in evaluated.values()
        ),
        "all_registered_horizons_present": all(
            all(
                tuple(method["rollout"].keys()) == ("h1", "h3", "h5")
                for method in result["methods"].values()
            )
            for result in evaluated.values()
        ),
    }
    result = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "stage": "architecture-controlled-final-evaluation",
        "protocol_sha256": sha256(PROTOCOL),
        "selection_sha256": sha256(SELECTION),
        "final_open_count": 1,
        "checks": checks,
        "evaluation_passed": all(checks.values()),
        "promotion_eligible": False,
        "deployed_digests_before": deployed_before,
        "deployed_digests_after": deployed_after,
        "domains": evaluated,
        "claim_boundary": [
            *protocol["claim_boundary"],
            "The existing final catalogs were already open in prior studies. This command is a registered post-publication architecture audit, not a fresh blind final test.",
            "Paired intervals measure this deterministic software distribution and do not establish production or physical safety.",
        ],
    }
    write_json(RESULT, result)
    print(
        json.dumps(
            {
                "output": repository_path(RESULT),
                "evaluation_passed": result["evaluation_passed"],
            },
            indent=2,
        )
    )
    return 0 if result["evaluation_passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("select", "final"))
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="run a two-update target-only selection smoke test",
    )
    args = parser.parse_args()
    if args.smoke and args.stage != "select":
        parser.error("--smoke is valid only for selection")
    protocol = load_json(PROTOCOL)
    if protocol["status"] != "prospective_registered":
        raise AssertionError("cross-domain study protocol is not registered")
    if args.stage == "select":
        return selection_stage(args, protocol)
    return final_stage(args, protocol)


if __name__ == "__main__":
    raise SystemExit(main())
