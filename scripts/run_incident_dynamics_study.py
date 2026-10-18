#!/usr/bin/env python3
"""Freeze selection, open a fresh catalog once, or audit retained observations.

All outputs are research artifacts. No function has runtime delivery authority.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import numpy as np
import torch

import cross_domain_world_model_models as legacy
import evaluate_cross_domain_world_models as architecture
import evaluate_incident_dynamics_development as development
import fit_incident_dynamics_ridge as ridge
import incident_dynamics_data as data
import incident_dynamics_metrics as metrics
import train_incident_dynamics as training


ROOT = data.ROOT
PROTOCOL = ROOT / "docs/research/incident_dynamics_protocol_v1.json"
ARTIFACTS = ROOT / "docs/research/artifacts/incident-dynamics-v1"
SELECTION = ROOT / "docs/research/incident_dynamics_selection_v1.json"
RESULT = ROOT / "docs/research/incident_dynamics_result_v1.json"
VERIFICATION = ROOT / "docs/research/incident_dynamics_verification_v1.json"
VERSION = 1
CODE = ["scripts/incident_dynamics_data.py", "scripts/train_incident_dynamics.py",
        "scripts/fit_incident_dynamics_ridge.py", "scripts/evaluate_incident_dynamics_development.py",
        "scripts/incident_dynamics_metrics.py", "scripts/run_incident_dynamics_study.py",
        "scripts/cross_domain_world_model_models.py", "scripts/evaluate_cross_domain_world_models.py",
        "scripts/evaluate_cross_domain_learned_contribution.py", "scripts/train_physical_world_model.py",
        "scripts/physical_incident_scenarios.py", "scripts/physical_stress_scenarios.py",
        "scripts/train_world_model.py", "scripts/train_world_model_encoder.py",
        "docs/research/cross_domain_world_model_improvement_protocol_v1.json",
        "docs/research/world_model_jepa_v3_protocol.json", "docs/research/world_model_jepa_v3_4_protocol.json",
        "docs/research/physical_jepa_v5_protocol.json"]


def text_digest(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def json_write_once(path, value):
    if path.exists():
        if architecture.load_json(path) == value:
            return
        raise FileExistsError(f"write-once scientific output: {path}")
    architecture.write_json(path, value)


def record(path):
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": legacy.sha256(path)}


def record_matches(item):
    path = ROOT / item["path"]
    raw = path.read_bytes()
    candidates = {hashlib.sha256(raw).hexdigest()}
    if path.suffix == ".json":
        normalized = raw.replace(b"\r\n", b"\n")
        candidates.update(hashlib.sha256(value).hexdigest() for value in (normalized, normalized.replace(b"\n", b"\r\n")))
    return item["sha256"] in candidates


def read_protocol():
    protocol = architecture.load_json(PROTOCOL)
    if "inherits_protocol" in protocol:
        amendment = protocol
        protocol = architecture.load_json(ROOT / amendment["inherits_protocol"])
        protocol["study_id"] = amendment["study_id"]
        protocol["final_generation"]["seed"] = amendment["final_seed_override"]
        protocol["amendment"] = amendment
    return protocol


def copy_artifact(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if legacy.sha256(source) != legacy.sha256(destination):
            raise FileExistsError(destination)
    else:
        shutil.copyfile(source, destination)
    return record(destination)


def committed(path):
    relative = path.relative_to(ROOT).as_posix()
    blob = subprocess.check_output(["git", "show", f"HEAD:{relative}"], cwd=ROOT)
    if hashlib.sha256(blob.replace(b"\r\n", b"\n")).hexdigest() != text_digest(path):
        raise AssertionError(f"uncommitted registered input: {relative}")


def protected():
    old = architecture.load_json(architecture.PROTOCOL)
    values = architecture.verify_digest_map(old["protected_deployed_artifacts"])
    if not all(values.values()):
        raise AssertionError("protected deployed artifact drift")
    return values


def pipeline_predictions(pipeline, windows, spec):
    if pipeline["kind"] == "simple":
        return development.simple_predictions(windows, pipeline["method"])
    if pipeline["kind"] == "ridge":
        if legacy.sha256(ROOT / pipeline["checkpoint"]["path"]) != pipeline["checkpoint"]["sha256"]:
            raise AssertionError("ridge checkpoint digest mismatch")
        with np.load(ROOT / pipeline["checkpoint"]["path"], allow_pickle=False) as archive:
            return ridge.predict(archive["weights"], windows, spec)
    members = []
    for item in pipeline["members"]:
        path = ROOT / item["checkpoint"]["path"]
        if legacy.sha256(path) != item["checkpoint"]["sha256"]:
            raise AssertionError("checkpoint digest mismatch")
        if pipeline["kind"] == "paper":
            model = legacy.load_model(path, pipeline["method"], spec, item["hidden_size"], item["checkpoint"]["sha256"])
        else:
            model = development.load_candidate(path, spec)
        members.append(training.predictions(model, windows, spec))
    return np.mean(members, axis=0)


def candidate_pipelines(domain):
    groups = {}
    for path in sorted((data.WORK / domain).glob("*.pt")):
        metadata = architecture.load_json(path.with_suffix(".json"))
        settings = metadata["settings"]
        if metadata["checkpoint"]["sha256"] != legacy.sha256(path) or metadata["final_access_attempted"]:
            raise AssertionError("invalid development checkpoint lineage")
        if metadata["data_manifest_sha256"] != legacy.sha256(data.WORK / domain / "data_manifest.json"):
            raise AssertionError("training-data manifest drift")
        key = f"{settings['run_id']}-{settings['method']}-h{settings['hidden']}-u{settings['updates']}-lr{settings['lr']}-b{settings['batch_size']}"
        pipeline = groups.setdefault(key, {"kind": "neural", "method": settings["method"], "members": []})
        checkpoint = copy_artifact(path, ARTIFACTS / "development" / domain / path.name)
        # Retain full traces and failed/less successful configurations, not only winners.
        portable = json.loads(json.dumps(metadata).replace(str(ROOT).replace("\\", "/") + "/", ""))
        portable["checkpoint"] = checkpoint
        ledger = ARTIFACTS / "development" / domain / path.with_suffix(".json").name
        json_write_once(ledger, portable)
        pipeline["members"].append({"seed": settings["seed"], "checkpoint": checkpoint,
                                    "training_record": record(ledger), "parameters": metadata["trainable_parameters"],
                                    "updates": settings["updates"]})
    selected_ridge = architecture.load_json(data.WORK / domain / "ridge-selection.json")
    for trial in selected_ridge["trials"]:
        source = ROOT / trial["checkpoint"]["path"]
        copy_artifact(source, ARTIFACTS / "development" / domain / source.name)
    chosen = selected_ridge["selected"]
    source = ROOT / chosen["checkpoint"]["path"]
    groups["ridge"] = {"kind": "ridge", "method": "per_action_ridge",
                       "checkpoint": record(ARTIFACTS / "development" / domain / source.name),
                       "parameters": chosen["parameters"], "regularization": chosen["regularization"]}
    copy_artifact(data.WORK / domain / "ridge-selection.json", ARTIFACTS / "development" / domain / "ridge-selection.json")
    return groups


def paper_pipelines(domain):
    registered = architecture.load_json(architecture.SELECTION)["domains"][domain]["methods"]
    result = {}
    for method in ("action_conditioned_jepa", "gru_dynamics"):
        if domain == "physical" and method != "action_conditioned_jepa":
            continue
        members = []
        for item in registered[method]:
            source = ROOT / item["checkpoint"]["path"]
            if legacy.sha256(source) != item["checkpoint"]["sha256"]:
                raise AssertionError("paper checkpoint has not been restored byte-identically")
            checkpoint = copy_artifact(source, ARTIFACTS / "paper-checkpoints" / domain / source.name)
            members.append({"checkpoint": checkpoint, "seed": item["seed"], "hidden_size": item["hidden_size"],
                            "parameters": item["trainable_parameters"], "updates": item["optimizer_updates_completed"]})
        result[f"paper-{method}"] = {"kind": "paper", "method": method, "members": members}
    return result


def select():
    if SELECTION.exists() or (ARTIFACTS / "final").exists():
        raise FileExistsError("selection already frozen or final already opened")
    if VERSION == 2:
        return reuse_frozen_selection()
    protocol = read_protocol()
    for path in [PROTOCOL, data.PLAN, data.SOURCES, *[ROOT / name for name in CODE]]:
        committed(path)
    guard = architecture.install_final_guard(architecture.load_json(architecture.PROTOCOL))
    before = protected()
    old_protocol = architecture.load_json(architecture.PROTOCOL)
    if not all(architecture.verify_digest_map(old_protocol["frozen_research_inputs"]).values()):
        raise AssertionError("original research input drift")
    domains = {}
    for domain in ("ferrumos", "physical"):
        spec = data.spec_for(domain)
        validation = data.load_windows(data.WORK / domain / "validation.npz")
        manifest = architecture.load_json(data.WORK / domain / "data_manifest.json")
        if manifest["validation_sha256"] != legacy.sha256(data.WORK / domain / "validation.npz"):
            raise AssertionError("validation data drift")
        candidates = candidate_pipelines(domain)
        scores = {}
        for name, pipeline in candidates.items():
            values = training.macro_errors(pipeline_predictions(pipeline, validation, spec), validation, spec)
            scores[name] = {"horizons": values, "selection_score": sum(values.values()) / 3}
        chosen_name = min(scores, key=lambda key: (scores[key]["selection_score"], key))
        chosen = candidates[chosen_name]
        if chosen["kind"] == "neural" and len(chosen["members"]) < protocol["selection"]["neural_selected_minimum_seeds"]:
            raise AssertionError(f"best configuration {domain}/{chosen_name} needs all three seeds")
        pipelines = {"selected": chosen, **paper_pipelines(domain), "ridge": candidates["ridge"]}
        for method, label in (("action_conditioned_jepa", "retrained-jepa"), ("direct_mlp", "retrained-mlp")):
            eligible = [name for name, pipeline in candidates.items() if pipeline["method"] == method]
            best = min(eligible, key=lambda name: scores[name]["selection_score"])
            pipelines[label] = candidates[best]
        for method in ("persistence", "constant_velocity"):
            pipelines[method] = {"kind": "simple", "method": method}
        calibration = data.windows(data.incident_rows(domain, "calibration", protocol["calibration"]["episodes_per_domain"],
                                                     protocol["calibration"]["seed"]), spec, complete=True)
        calibration_path = ARTIFACTS / "calibration" / f"{domain}.npz"
        data.save_windows(calibration_path, calibration)
        labels = development.risk_score(calibration.targets, calibration, domain) >= 0
        for name, pipeline in pipelines.items():
            scores_cal = development.risk_score(pipeline_predictions(pipeline, calibration, spec), calibration, domain)
            threshold, coefficients = development.calibrate(scores_cal, labels)
            pipeline["warning"] = {"threshold": threshold, "logistic_coefficients": coefficients,
                                    "calibration_metrics": development.warning_metrics(scores_cal, labels, threshold, coefficients)}
        validation_path = ARTIFACTS / "development" / domain / "validation.npz"
        copy_artifact(data.WORK / domain / "validation.npz", validation_path)
        manifest_path = ARTIFACTS / "development" / domain / "data_manifest.json"
        copy_artifact(data.WORK / domain / "data_manifest.json", manifest_path)
        domains[domain] = {"selected_configuration": chosen_name, "candidate_scores": scores,
                           "candidates": candidates, "pipelines": pipelines, "calibration": record(calibration_path),
                           "validation": record(validation_path), "data_manifest": record(manifest_path)}
        print(json.dumps({"selected": domain, "configuration": chosen_name, "score": scores[chosen_name]}), flush=True)
    parent = ROOT / "docs/research/paper/Prediction_Is_Not_Permission_Technical_Report_v1.2.pdf"
    parent_record = copy_artifact(parent, ARTIFACTS / "historical-report" / parent.name)
    parent_source = ROOT / "docs/research/paper/prediction_is_not_permission_technical_report_v1_2.md"
    copy_artifact(parent_source, ARTIFACTS / "historical-report" / parent_source.name)
    for source in sorted((data.WORK / "replication").rglob("*.replication.json")):
        relative = source.relative_to(data.WORK / "replication")
        copy_artifact(source, ARTIFACTS / "development/replication" / relative)
    for domain in ("ferrumos", "physical"):
        for source in sorted((data.WORK / domain).glob("development*.json")):
            copy_artifact(source, ARTIFACTS / "development" / domain / source.name)
    frozen = {name: text_digest(ROOT / name) for name in CODE}
    frozen.update({path.relative_to(ROOT).as_posix(): text_digest(path) for path in (PROTOCOL, data.PLAN, data.SOURCES)})
    result = {"study_id": protocol["study_id"], "created_at": datetime.now(timezone.utc).isoformat(),
              "selection_commit_parent": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "domains": domains, "source_bindings": frozen, "historical_report": parent_record,
              "protected_before": before, "protected_after": protected(), "final_access_attempted": guard["attempted"],
              "promotion_eligible": False, "actuator_deliveries": 0}
    assert not guard["attempted"]
    json_write_once(SELECTION, result)


def reuse_frozen_selection():
    """V2 repairs input eligibility only; no model or threshold reselection."""
    original_path = ROOT / "docs/research/incident_dynamics_selection_v1.json"
    original = architecture.load_json(original_path)
    current_runner = "scripts/run_incident_dynamics_study.py"
    archived_runner = ROOT / "docs/research/artifacts/incident-dynamics-v1/historical-implementation/run_incident_dynamics_study.py"
    if text_digest(archived_runner) != original["source_bindings"][current_runner]:
        raise AssertionError("failed-v1 implementation archive drift")
    for name, digest in original["source_bindings"].items():
        if name != current_runner and text_digest(ROOT / name) != digest:
            raise AssertionError(f"v2 may not alter the selected model/data code: {name}")
    for path in (PROTOCOL, ROOT / current_runner):
        committed(path)
    original["study_id"] = read_protocol()["study_id"]
    original["created_at"] = datetime.now(timezone.utc).isoformat()
    original["selection_commit_parent"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    original["reused_selection"] = record(original_path)
    original["model_and_threshold_reselection"] = False
    original["source_bindings"][current_runner] = text_digest(ROOT / current_runner)
    original["source_bindings"][PROTOCOL.relative_to(ROOT).as_posix()] = text_digest(PROTOCOL)
    verify_bindings(original)
    json_write_once(SELECTION, original)
    print(json.dumps({"frozen_v2_selection": str(SELECTION), "models_and_thresholds_unchanged": True}))


def verify_bindings(selection):
    for name, digest in selection["source_bindings"].items():
        if text_digest(ROOT / name) != digest:
            raise AssertionError(f"frozen source drift: {name}")
    for path in ARTIFACTS.rglob("*.pt"):
        # Individual required checkpoint digests are also checked during inference.
        if path.stat().st_size == 0:
            raise AssertionError("empty checkpoint")
    if legacy.sha256(ROOT / selection["historical_report"]["path"]) != selection["historical_report"]["sha256"]:
        raise AssertionError("historical report drift")
    for domain in selection["domains"].values():
        for name in ("calibration", "validation", "data_manifest"):
            item = domain[name]
            if not record_matches(item):
                raise AssertionError(f"frozen {name} drift")
    protected()


def initially_observed_safe(windows, domain):
    initial = np.repeat(windows.states[:, -1:, :], 5, axis=1)
    # Repeated current observation under the known proposed sequence, not future truth.
    return development.risk_score(initial, windows, domain) < 0


def analyze_domain(domain, windows, historical, prediction_map, historical_map, selection, protocol):
    spec = data.spec_for(domain)
    pipelines = selection["domains"][domain]["pipelines"]
    labels = development.risk_score(windows.targets, windows, domain) >= 0
    currently_safe = initially_observed_safe(windows, domain)
    methods, errors, counts = {}, {}, {}
    for name, predicted in prediction_map.items():
        prediction, errors[name] = metrics.prediction_metrics(predicted, windows, spec)
        scores = development.risk_score(predicted, windows, domain)
        warning = pipelines[name]["warning"]
        summary, counts[name] = metrics.warning_summary(scores, labels, warning["threshold"], warning["logistic_coefficients"], windows.episodes)
        delayed, _ = metrics.warning_summary(scores[currently_safe], labels[currently_safe], warning["threshold"],
                                             warning["logistic_coefficients"], windows.episodes[currently_safe])
        sources = {}
        for source in np.unique(windows.sources):
            mask = windows.sources == source
            source_windows = data.subset(windows, mask)
            source_predictions, _ = metrics.prediction_metrics(predicted[mask], source_windows, spec)
            source_warnings, _ = metrics.warning_summary(scores[mask], labels[mask], warning["threshold"], warning["logistic_coefficients"], windows.episodes[mask])
            sources[source] = {"prediction": source_predictions, "warning": source_warnings}
        methods[name] = {"prediction": prediction, "warning": summary, "currently_observed_safe_warning": delayed, "sources": sources}
    baseline = protocol["comparison"]["primary_baseline"][domain]
    primary = {}
    for h in (3, 5):
        comparison = metrics.bootstrap_difference(errors["selected"][:, h - 1], errors[baseline][:, h - 1], windows.episodes,
                                                   protocol["statistics"]["seed"] + h, (.00625, .99375))
        old = methods[baseline]["prediction"][f"h{h}"]["episode_macro_mae"]
        new = methods["selected"]["prediction"][f"h{h}"]["episode_macro_mae"]
        comparison["relative_reduction"] = 1 - new / old
        comparison["pass"] = comparison["relative_reduction"] >= .2 and comparison["interval"][1] < 0
        primary[f"h{h}"] = comparison
    historical_results = {name: metrics.prediction_metrics(values, historical, spec)[0] for name, values in historical_map.items()}
    guards = {}
    for h in (1, 3, 5):
        key = f"h{h}"
        best_name = min((name for name in historical_results if name != "selected"), key=lambda name: historical_results[name][key]["episode_macro_mae"])
        baseline_value = historical_results[best_name][key]["episode_macro_mae"]
        new_value = historical_results["selected"][key]["episode_macro_mae"]
        guards[key] = {"best_paper_method": best_name, "relative_change": new_value / baseline_value - 1,
                       "pass": new_value <= 1.05 * baseline_value}
    paired_warning = metrics.paired_warning_difference(counts["selected"], counts[baseline], protocol["statistics"]["seed"])
    warning_pass = (paired_warning["recall"]["difference"] >= .20 and paired_warning["recall"]["interval_97_5_percent"][0] > 0
                    and methods["selected"]["warning"]["fpr"] <= .02)
    return {"methods": methods, "primary_prediction_comparisons": primary,
            "historical": historical_results, "historical_guards": guards,
            "paired_warning": paired_warning, "secondary_warning_objective_pass": warning_pass,
            "primary_prediction_objective_pass": all(x["pass"] for x in primary.values()) and all(x["pass"] for x in guards.values())}


def retained_analysis(selection, protocol, check_predictions=False):
    domains, checks = {}, {}
    for domain in ("ferrumos", "physical"):
        folder = ARTIFACTS / "final" / domain
        windows = data.load_windows(folder / "new_catalog.npz")
        historical = data.load_windows(folder / "historical_catalog.npz")
        with np.load(folder / "predictions.npz", allow_pickle=False) as archive:
            predicted = {key[4:]: archive[key] for key in archive.files if key.startswith("new_")}
            previous = {key[4:]: archive[key] for key in archive.files if key.startswith("old_")}
        if check_predictions:
            spec = data.spec_for(domain)
            for name, saved in predicted.items():
                inferred = pipeline_predictions(selection["domains"][domain]["pipelines"][name], windows, spec)
                checks[f"{domain}/new/{name}/inference"] = bool(np.allclose(saved, inferred, atol=1e-7, rtol=0))
            for name, saved in previous.items():
                inferred = pipeline_predictions(selection["domains"][domain]["pipelines"][name], historical, spec)
                checks[f"{domain}/historical/{name}/inference"] = bool(np.allclose(saved, inferred, atol=1e-7, rtol=0))
        domains[domain] = analyze_domain(domain, windows, historical, predicted, previous, selection, protocol)
        exclusions_path = folder / "historical_exclusions.json"
        if exclusions_path.exists():
            domains[domain]["historical_exclusions"] = architecture.load_json(exclusions_path)
    return domains, checks


def historical_inputs(domain, spec):
    old_protocol = architecture.load_json(architecture.PROTOCOL)
    _, rows, _ = (architecture.os_final if domain == "ferrumos" else architecture.physical_final)(old_protocol)
    grouped = {}
    for row in rows:
        grouped.setdefault(row["episode"], []).append(row["step"])
    ambiguous = {name: steps for name, steps in grouped.items() if len(steps) != len(set(steps))}
    if VERSION == 2:
        rows = [row for row in rows if row["episode"] not in ambiguous]
    common_ids = set(data.windows(rows, spec, complete=True).episodes)
    historical = data.windows([row for row in rows if row["episode"] in common_ids], spec)
    exclusions = {"rule": "Exclude duplicate-step episodes before model inference, then require five contiguous transitions.",
                  "ambiguous_episodes": ambiguous, "ambiguous_episode_count": len(ambiguous),
                  "all_ambiguous_episodes_shorter_than_five_rows": all(len(x) < 5 for x in ambiguous.values()),
                  "retained_common_episodes": len(common_ids), "applied_identically_to_all_methods": True}
    return historical, exclusions


def final():
    if RESULT.exists() or (ARTIFACTS / "final").exists():
        raise FileExistsError("final has already been opened; use verify on retained catalogs")
    committed(SELECTION)
    selection = architecture.load_json(SELECTION)
    protocol = read_protocol()
    verify_bindings(selection)
    # Historical-schema preflight cannot consume the new final RNG or predictions.
    historical_sets = {domain: historical_inputs(domain, data.spec_for(domain)) for domain in ("ferrumos", "physical")}
    root = ARTIFACTS / "final"
    root.mkdir(parents=True)
    event = {"opened_at": datetime.now(timezone.utc).isoformat(), "selection": record(SELECTION),
             "registration_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
             "new_seed": protocol["final_generation"]["seed"], "episodes_per_domain": protocol["final_generation"]["episodes_per_domain"]}
    json_write_once(root / "open_event.json", event)
    try:
        for domain in ("ferrumos", "physical"):
            spec = data.spec_for(domain)
            new = data.windows(data.incident_rows(domain, "final", protocol["final_generation"]["episodes_per_domain"],
                                                 protocol["final_generation"]["seed"]), spec, complete=True)
            historical, exclusions = historical_sets[domain]
            folder = root / domain
            data.save_windows(folder / "new_catalog.npz", new)
            data.save_windows(folder / "historical_catalog.npz", historical)
            json_write_once(folder / "historical_exclusions.json", exclusions)
            predictions = {}
            for name, pipeline in selection["domains"][domain]["pipelines"].items():
                predictions[f"new_{name}"] = pipeline_predictions(pipeline, new, spec)
                if name == "selected" or pipeline["kind"] == "paper":
                    predictions[f"old_{name}"] = pipeline_predictions(pipeline, historical, spec)
            np.savez_compressed(folder / "predictions.npz", **predictions)
            print(json.dumps({"final_catalog_completed": domain, "episodes": len(np.unique(new.episodes)), "windows": len(new.states)}), flush=True)
        domains, _ = retained_analysis(selection, protocol)
        verify_bindings(selection)
        result = {"study_id": protocol["study_id"], "evidence_class": "prospective locally designed software benchmark; shared-mechanism narrative-source holdout",
                  "domains": domains, "selection": record(SELECTION), "open_event": record(root / "open_event.json"),
                  "final_artifacts": [record(path) for path in sorted([*root.rglob("*.npz"), *root.rglob("historical_exclusions.json")])],
                  "primary_prediction_objective_pass": all(x["primary_prediction_objective_pass"] for x in domains.values()),
                  "secondary_warning_objective_pass": all(x["secondary_warning_objective_pass"] for x in domains.values()),
                  "protected_unchanged": protected(), "promotion_eligible": False, "actuator_attempts": 0, "actuator_deliveries": 0,
                  "limitations": ["Not independent execution, real incident telemetry, physical safety, or operational benefit.",
                                  "Curriculum, objective, model form and training budget change together; no architecture-only superiority claim.",
                                  "Prediction intervals condition on fixed trained models; seed variation is reported separately.",
                                  "Warning thresholds target calibration FPR only; shifted population FPR is not guaranteed.",
                                  "Historical comparisons are regression checks on already opened source families."]}
        json_write_once(RESULT, result)
        print(json.dumps({"result": str(RESULT), "primary_prediction_objective_pass": result["primary_prediction_objective_pass"],
                          "secondary_warning_objective_pass": result["secondary_warning_objective_pass"]}))
    except Exception as exc:
        json_write_once(root / "failed_attempt.json", {"error": type(exc).__name__, "message": str(exc), "prospective_result_eligible": False})
        raise


def verify():
    selection = architecture.load_json(SELECTION)
    protocol = read_protocol()
    original = architecture.load_json(RESULT)
    verify_bindings(selection)
    domains, checks = retained_analysis(selection, protocol, check_predictions=True)
    for domain, selected in selection["domains"].items():
        spec = data.spec_for(domain)
        validation = data.load_windows(ROOT / selected["validation"]["path"])
        recomputed_scores = {}
        for name, pipeline in selected["candidates"].items():
            values = training.macro_errors(pipeline_predictions(pipeline, validation, spec), validation, spec)
            recomputed_scores[name] = {"horizons": values, "selection_score": sum(values.values()) / 3}
        checks[f"{domain}/selection_scores"] = recomputed_scores == selected["candidate_scores"]
        checks[f"{domain}/selected_minimum"] = selected["selected_configuration"] == min(recomputed_scores, key=lambda name: (recomputed_scores[name]["selection_score"], name))
        calibration = data.load_windows(ROOT / selected["calibration"]["path"])
        labels = development.risk_score(calibration.targets, calibration, domain) >= 0
        for name, pipeline in selected["pipelines"].items():
            scores = development.risk_score(pipeline_predictions(pipeline, calibration, spec), calibration, domain)
            threshold, coefficients = development.calibrate(scores, labels)
            checks[f"{domain}/{name}/calibration"] = (threshold == pipeline["warning"]["threshold"] and
                                                      coefficients == pipeline["warning"]["logistic_coefficients"])
    checks["all_metrics_recompute_exactly"] = domains == original["domains"]
    checks["selection_digest"] = record_matches(original["selection"])
    checks["open_event_digest"] = record_matches(original["open_event"])
    checks["final_artifact_digests"] = all(record_matches(item) for item in original["final_artifacts"])
    if "reused_selection" in selection:
        parent = architecture.load_json(ROOT / selection["reused_selection"]["path"])
        checks["v1_models_and_thresholds_unchanged"] = (selection["domains"] == parent["domains"] and
                                                       not selection["model_and_threshold_reselection"])
        checks["v1_failed_attempt_retained"] = architecture.load_json(ROOT / protocol["amendment"]["failed_attempt"])["prospective_result_eligible"] is False
    checks["no_failed_final_attempt"] = not (ARTIFACTS / "final/failed_attempt.json").exists()
    checks["no_authority"] = not original["promotion_eligible"] and original["actuator_attempts"] == original["actuator_deliveries"] == 0
    checks["protected_unchanged"] = all(protected().values())
    report = {"study_id": protocol["study_id"], "result": record(RESULT), "checks": checks,
              "all_checks_pass": all(checks.values()), "verification_mode": "retained catalog inference and metric recomputation; no retraining or final generation",
              "promotion_eligible": False}
    if VERIFICATION.exists():
        if architecture.load_json(VERIFICATION) != report:
            raise AssertionError("verification changed")
    else:
        json_write_once(VERIFICATION, report)
    print(json.dumps(report, indent=2))
    if not report["all_checks_pass"]:
        raise AssertionError("retained-catalog audit failed")


def main():
    global VERSION, PROTOCOL, ARTIFACTS, SELECTION, RESULT, VERIFICATION
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["select", "final", "verify"])
    parser.add_argument("--version", type=int, choices=[1, 2], default=1)
    args = parser.parse_args()
    VERSION = args.version
    if VERSION == 2:
        PROTOCOL = ROOT / "docs/research/incident_dynamics_protocol_v2.json"
        ARTIFACTS = ROOT / "docs/research/artifacts/incident-dynamics-v2"
        SELECTION = ROOT / "docs/research/incident_dynamics_selection_v2.json"
        RESULT = ROOT / "docs/research/incident_dynamics_result_v2.json"
        VERIFICATION = ROOT / "docs/research/incident_dynamics_verification_v2.json"
    torch.set_num_threads(4)
    {"select": select, "final": final, "verify": verify}[args.stage]()


if __name__ == "__main__":
    main()
