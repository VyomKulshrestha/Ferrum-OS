#!/usr/bin/env python3
"""Incident-dynamics v3: freeze selection, open the registered final populations once, audit.

Populations
  A  fresh seed from the unchanged v2 final generator (the paper's Section 8.7 population)
  B  fresh seed; held-out mechanism families only (novel-mechanism holdout)
  historical  previously opened paper final families (regression guard only)

Retained evidence stores per-window errors and warning scores (not full prediction arrays);
verification reloads every checkpoint, recomputes inference and requires exact agreement.
All outputs are research artifacts with no runtime, permit or actuator authority.
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
import incident_dynamics_data as v2data
import incident_dynamics_metrics as metrics
import incident_dynamics_v3_data as v3
import incident_dynamics_v3_dev as dev
import incident_dynamics_v3_eval as evaluation
import incident_dynamics_v3_models as models
import incident_dynamics_v3_warning as warning
import run_incident_dynamics_study as v2run

ROOT = v3.ROOT
PROTOCOL = ROOT / "docs/research/incident_dynamics_protocol_v3.json"
PLAN = ROOT / "docs/research/incident_dynamics_v3_development_plan.json"
SOURCES = ROOT / "docs/research/incident_dynamics_sources_v3.json"
ARTIFACTS = ROOT / "docs/research/artifacts/incident-dynamics-v3"
SELECTION = ROOT / "docs/research/incident_dynamics_selection_v3.json"
RESULT = ROOT / "docs/research/incident_dynamics_result_v3.json"
VERIFICATION = ROOT / "docs/research/incident_dynamics_verification_v3.json"
CODE = ["scripts/incident_dynamics_v3_data.py", "scripts/incident_dynamics_v3_dev.py", "scripts/incident_dynamics_v3_models.py",
        "scripts/incident_dynamics_v3_trial.py", "scripts/incident_dynamics_v3_warning.py", "scripts/incident_dynamics_v3_eval.py",
        "scripts/run_incident_dynamics_v3_study.py", "scripts/incident_dynamics_v3_gbr.py", "scripts/incident_dynamics_v3_scale.py", "scripts/incident_dynamics_data.py", "scripts/incident_dynamics_metrics.py",
        "scripts/run_incident_dynamics_study.py", "scripts/evaluate_incident_dynamics_development.py",
        "scripts/train_incident_dynamics.py", "scripts/evaluate_cross_domain_learned_contribution.py",
        "scripts/train_physical_world_model.py", "scripts/cross_domain_world_model_models.py",
        "scripts/evaluate_cross_domain_world_models.py"]
DOMAINS = ("ferrumos", "physical")
text_digest = v2run.text_digest
record = v2run.record
record_matches = v2run.record_matches


def json_write_once(path, value):
    if path.exists():
        if architecture.load_json(path) == value:
            return
        raise FileExistsError(f"write-once scientific output: {path}")
    architecture.write_json(path, value)


def committed(path):
    relative = path.relative_to(ROOT).as_posix()
    blob = subprocess.check_output(["git", "show", f"HEAD:{relative}"], cwd=ROOT)
    if hashlib.sha256(blob.replace(b"\r\n", b"\n")).hexdigest() != text_digest(path):
        raise AssertionError(f"uncommitted registered input: {relative}")


def protected():
    return v2run.protected()


def copy_artifact(source, destination):
    if source.stat().st_size > 45 * 1024 * 1024:
        raise AssertionError(f"artifact exceeds the 45 MB repository limit: {source}")
    return v2run.copy_artifact(source, destination)


# ---------------------------------------------------------------- pipelines
class Pipeline:
    """Uniform prediction interface: returns (mean, scale_or_None) on windows of its own history.

    v3 pipelines are committees: members are grouped by trial configuration; the committee mean is
    the equal-weight mean of per-configuration seed means. The warning scale is the mean learned
    Laplace scale of members that provide one plus the disagreement between member forecasts.
    """

    def __init__(self, spec_record, domain):
        self.record, self.domain = spec_record, domain
        self.history = spec_record.get("history", 3)
        self.members = None

    def load(self):
        if self.members is not None:
            return
        import incident_dynamics_v3_gbr as gbr
        self.members = []
        for item in self.record["members"]:
            path = ROOT / item["checkpoint"]["path"]
            if legacy.sha256(path) != item["checkpoint"]["sha256"]:
                raise AssertionError(f"checkpoint digest mismatch: {path}")
            if path.suffix in (".gbr", ".xz"):
                self.members.append((item["group"], "gbr", gbr.load_path(path)))
            else:
                self.members.append((item["group"], "torch", models.load_trial(path, "cpu")[0]))

    def predict(self, windows):
        kind = self.record["kind"]
        if kind in ("v2", "simple"):
            spec = v3.spec_for(self.domain, 3)
            if kind == "simple":
                import evaluate_incident_dynamics_development as v2dev
                return v2dev.simple_predictions(windows, self.record["method"]), None
            return v2run.pipeline_predictions(self.record["v2_pipeline"], windows, spec), None
        self.load()
        groups, means, scales = {}, [], []
        for group, family, model in self.members:
            if family == "gbr" and hasattr(model, "predict_with_scale"):
                mean, scale = model.predict_with_scale(windows)
                scales.append(scale)
            elif family == "gbr":
                mean = model.predict(windows)
            else:
                mean, scale = models.predict(model, windows, with_scale=True)
                scales.append(scale)
            groups.setdefault(group, []).append(mean)
            means.append(mean)
        mean = np.mean([np.mean(values, axis=0) for values in groups.values()], axis=0)
        scale = np.std(means, axis=0)
        if scales:
            scale = scale + np.mean(scales, axis=0)
        return mean.astype(np.float32), scale.astype(np.float32)


def v2_records(domain):
    selection = json.loads(evaluation.V2_SELECTION.read_text(encoding="utf-8"))["domains"][domain]["pipelines"]
    names = ["selected", "ridge", "persistence", "constant_velocity", "paper-action_conditioned_jepa"]
    if domain == "ferrumos":
        names.append("paper-gru_dynamics")
    result = {}
    for name in names:
        if name in ("persistence", "constant_velocity"):
            result[name] = {"kind": "simple", "method": name, "history": 3}
        else:
            result[f"v2-{name}"] = {"kind": "v2", "v2_pipeline": selection[name], "history": 3}
    return result


def windows_for(rows, domain, history):
    return v3.windows(rows, v3.spec_for(domain, history), complete=True)


# ---------------------------------------------------------------- selection
def trial_configurations(domain):
    groups = {}
    for path in sorted((v3.WORK / "trials" / domain).glob("*.json")):
        info = architecture.load_json(path)
        if info.get("final_access_attempted"):
            raise AssertionError("trial attempted final access")
        settings = info["settings"]
        checkpoint = path.parent / info.get("checkpoint_file", path.with_suffix(".pt").name)
        if hashlib.sha256(checkpoint.read_bytes()).hexdigest() != info["checkpoint_sha256"]:
            raise AssertionError(f"trial checkpoint drift: {checkpoint}")
        groups.setdefault(settings["trial_id"], []).append((settings["seed"], path, checkpoint, info))
    return {name: sorted(members, key=lambda m: m[0]) for name, members in groups.items()}


def candidate_committees(domain, configurations, protocol):
    """Single configurations plus registered committees; every member configuration needs >=3 seeds."""
    minimum = protocol["selection"]["minimum_seeds"]
    eligible = {name for name, members in configurations.items() if len(members) >= minimum}
    # A scale-augmented configuration has the parent's mean forecast; it supersedes the parent when
    # it covers the same seeds, so the identical prediction score cannot drop the warning scale by tie.
    for name in list(eligible):
        parents = {m[3]["settings"].get("parent_trial", "").split("/")[-1].rsplit("-s", 1)[0] for m in configurations[name]}
        for parent in parents:
            if parent in eligible and {m[0] for m in configurations[parent]} <= {m[0] for m in configurations[name]}:
                eligible.discard(parent)
    candidates = {name: [name] for name in sorted(eligible)}
    for committee in protocol["selection"].get("committees", {}).get(domain, []):
        if all(name in eligible for name in committee):
            candidates["+".join(committee)] = list(committee)
    return candidates


def archive_checkpoint(domain, checkpoint):
    """Torch checkpoints are copied; boosted models are archived in the compact prediction-only xz form
    after asserting bit-identical predictions on the development-mechanism validation windows."""
    if checkpoint.suffix != ".gbr":
        return copy_artifact(checkpoint, ARTIFACTS / "checkpoints" / domain / checkpoint.name)
    import incident_dynamics_v3_gbr as gbr
    destination = ARTIFACTS / "checkpoints" / domain / (checkpoint.name + ".xz")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        gbr.export_compact(checkpoint, destination)
    original, compact = gbr.load_any(checkpoint), gbr.load_path(destination)
    probe = dev.load(domain, "mech_validation", original.history)
    if not np.array_equal(original.predict(probe), compact.predict(probe)):
        raise AssertionError(f"compact archive changed predictions: {checkpoint.name}")
    if destination.stat().st_size > 45 * 1024 * 1024:
        raise AssertionError(f"compact archive exceeds 45 MB: {destination}")
    return {**record(destination), "uncompressed_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            "encoding": "prediction-only LightGBM text in sorted JSON, xz preset 9e; predictions verified identical"}


def committee_record(domain, configurations, names):
    members = []
    for name in names:
        for seed, info_path, checkpoint, info in configurations[name]:
            stored = archive_checkpoint(domain, checkpoint)
            ledger = copy_artifact(info_path, ARTIFACTS / "checkpoints" / domain / info_path.name)
            members.append({"group": name, "seed": seed, "checkpoint": stored, "training_record": ledger,
                            "settings": info["settings"]})
    histories = {m["settings"]["history"] for m in members}
    return {"kind": "v3", "configuration": "+".join(names), "history": max(histories), "members": members}


def committee_score(domain, configurations, names):
    """Development selection score of a committee, computed without copying artifacts."""
    temporary = {"kind": "v3", "history": max(configurations[n][0][3]["settings"]["history"] for n in names),
                 "members": [{"group": n, "checkpoint": {"path": checkpoint.relative_to(ROOT).as_posix(),
                                                          "sha256": info["checkpoint_sha256"]}}
                             for n in names for _, _, checkpoint, info in configurations[n]]}
    pipeline = Pipeline(temporary, domain)
    return dev.selection_score(lambda data: pipeline.predict(data)[0], domain, temporary["history"])


def choose_k(domain, pipeline, protocol):
    """Registered warning-shift rule on development data only."""
    rule = protocol["warning"]
    calibration = dev.load(domain, "calibration", pipeline.history)
    validation = dev.warning_validation(domain, pipeline.history)
    cal_mean, cal_scale = pipeline.predict(calibration)
    val_mean, val_scale = pipeline.predict(validation)
    rows = []
    for k in rule["k_grid"]:
        if k and cal_scale is None:
            continue
        report, threshold, coefficients = evaluation.warning_report(domain, calibration, cal_mean, cal_scale,
                                                                    validation, val_mean, val_scale, k)
        rows.append({"k": k, "threshold": threshold, "coefficients": coefficients,
                     "validation": evaluation.summarize(report)})
    eligible = [row for row in rows if row["validation"]["fpr"] <= rule["validation_fpr_maximum"]] or rows[:1]
    chosen = max(eligible, key=lambda row: (row["validation"]["recall"], -row["k"]))
    return chosen, rows


def select():
    if SELECTION.exists() or (ARTIFACTS / "final").exists():
        raise FileExistsError("selection already frozen or final already opened")
    protocol = architecture.load_json(PROTOCOL)
    for path in [PROTOCOL, PLAN, SOURCES, *[ROOT / name for name in CODE]]:
        committed(path)
    guard = architecture.install_final_guard(architecture.load_json(architecture.PROTOCOL))
    before = protected()
    torch.set_num_threads(8)
    domains = {}
    for domain in DOMAINS:
        configurations = trial_configurations(domain)
        candidates = candidate_committees(domain, configurations, protocol)
        scores = {}
        for name, names in candidates.items():
            result = committee_score(domain, configurations, names)
            scores[name] = {"members": names, "seeds": {n: [m[0] for m in configurations[n]] for n in names},
                            "selection_score": result["selection_score"], "blocks": {b: result[b] for b in dev.BLOCKS}}
        chosen = min(scores, key=lambda name: (scores[name]["selection_score"], name))
        pipelines = {"selected": committee_record(domain, configurations, candidates[chosen])}
        for label, names in protocol["selection"]["registered_v3_comparators"].get(domain, {}).items():
            if all(n in configurations and len(configurations[n]) >= protocol["selection"]["minimum_seeds"] for n in names):
                pipelines[label] = committee_record(domain, configurations, names)
        pipelines.update(v2_records(domain))
        warnings = {}
        for name, item in pipelines.items():
            pipeline = Pipeline(item, domain)
            rule = protocol if item["kind"] == "v3" else {"warning": {**protocol["warning"], "k_grid": [0]}}
            chosen_k, grid = choose_k(domain, pipeline, rule)
            item["warning"] = {"k": chosen_k["k"], "threshold": chosen_k["threshold"], "logistic_coefficients": chosen_k["coefficients"],
                               "development_validation": chosen_k["validation"], "k_grid": grid}
            warnings[name] = item["warning"]["k"]
        for name in ("calibration", "base_validation", "mech_validation"):
            for history in sorted({3, *(p["history"] for p in pipelines.values())}):
                path = v3.WORK / "dev" / domain / f"{name}-h{history}.npz"
                copy_artifact(path, ARTIFACTS / "development" / domain / path.name)
        domains[domain] = {"selected_configuration": chosen, "candidate_scores": scores, "pipelines": pipelines,
                           "warning_k": warnings}
        print(json.dumps({"domain": domain, "selected": chosen, "score": scores[chosen]["selection_score"]}), flush=True)
    for path in [v3.WORK / "development_ledger.jsonl", v3.WORK / "infrastructure_failures.jsonl"]:
        if path.exists():
            copy_artifact(path, ARTIFACTS / "development" / path.name)
    for domain in DOMAINS:
        for path in (v3.WORK / "dev" / domain).glob("*.json"):
            copy_artifact(path, ARTIFACTS / "development" / domain / path.name)
    frozen = {name: text_digest(ROOT / name) for name in CODE}
    frozen.update({path.relative_to(ROOT).as_posix(): text_digest(path) for path in (PROTOCOL, PLAN, SOURCES)})
    result = {"study_id": protocol["study_id"], "created_at": datetime.now(timezone.utc).isoformat(),
              "selection_commit_parent": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "domains": domains, "source_bindings": frozen, "protected_before": before, "protected_after": protected(),
              "final_access_attempted": guard["attempted"], "promotion_eligible": False, "actuator_deliveries": 0}
    if guard["attempted"]:
        raise AssertionError("final access attempted during selection")
    json_write_once(SELECTION, result)


def verify_bindings(selection):
    for name, digest in selection["source_bindings"].items():
        if text_digest(ROOT / name) != digest:
            raise AssertionError(f"frozen source drift: {name}")
    for domain in selection["domains"].values():
        for item in domain["pipelines"].values():
            for member in item.get("members", []):
                if not record_matches(member["checkpoint"]):
                    raise AssertionError("checkpoint drift")
    protected()


# ---------------------------------------------------------------- final populations
def population_rows(domain, protocol):
    final = protocol["final"]
    a = v2data.incident_rows(domain, "final", final["episodes_per_domain"], final["seed_population_a"])
    b = v3.mechanism_rows(domain, "final", v3.HELD_OUT_MECHANISMS[domain], final["episodes_per_domain"], final["seed_population_b"])
    return {"A": a, "B": b}


def historical_rows(domain):
    old_protocol = architecture.load_json(architecture.PROTOCOL)
    _, rows, _ = (architecture.os_final if domain == "ferrumos" else architecture.physical_final)(old_protocol)
    grouped = {}
    for row in rows:
        grouped.setdefault(row["episode"], []).append(row["step"])
    ambiguous = {name for name, steps in grouped.items() if len(steps) != len(set(steps))}
    rows = [row for row in rows if row["episode"] not in ambiguous]
    common = set(v3.windows(rows, v3.spec_for(domain, 3), complete=True).episodes)
    return [row for row in rows if row["episode"] in common], sorted(ambiguous)


def evidence_for(pipeline, item, domain, windows):
    """Per-window normalized errors (N x 5) and warning scores for one pipeline on one population."""
    spec = v3.spec_for(domain, item["history"])
    mean, scale = pipeline.predict(windows)
    errors = np.mean(np.abs(mean - windows.targets) / spec.scale, axis=-1).astype(np.float64)
    k = item["warning"]["k"]
    score = warning.risk_score(mean, scale if k else None, windows, domain, k)
    return errors, score


def paired_warning_difference(left, right, seed, quantiles):
    """Episode-paired bootstrap of recall and FPR differences (left minus right) at the given quantiles."""
    rng = np.random.default_rng(seed)
    draws = rng.integers(len(left), size=(10000, len(left)))
    a, b = left[draws].sum(1), right[draws].sum(1)
    result = {}
    for name, numerator, denominator in (("recall", 0, (0, 3)), ("fpr", 1, (1, 2))):
        samples = a[:, numerator] / a[:, denominator].sum(1) - b[:, numerator] / b[:, denominator].sum(1)
        aa, bb = left.sum(0), right.sum(0)
        point = aa[numerator] / aa[list(denominator)].sum() - bb[numerator] / bb[list(denominator)].sum()
        result[name] = {"difference": float(point), "interval": np.quantile(samples, quantiles).tolist(),
                        "interval_level": 1 - 2 * quantiles[0]}
    return result


def analyze(selection, protocol, evidence, windows3, domain):
    pipelines = selection["domains"][domain]["pipelines"]
    stats = protocol["statistics"]
    result = {"populations": {}}
    for population in ("A", "B"):
        data = windows3[population]
        labels = warning.labels(data, domain)
        methods, counts = {}, {}
        for name, item in pipelines.items():
            errors, score = evidence[population][name]
            methods[name] = {"prediction": {}}
            for h in (1, 3, 5):
                ids, means = metrics.episode_means(errors[:, h - 1], data.episodes)
                methods[name]["prediction"][f"h{h}"] = {"episode_macro_mae": float(means.mean()), "episodes": len(ids)}
            report, counts[name] = metrics.warning_summary(score, labels, item["warning"]["threshold"],
                                                           item["warning"]["logistic_coefficients"], data.episodes)
            methods[name]["warning"] = report
        primary = {}
        for h in (3, 5):
            selected, base = evidence[population]["selected"][0][:, h - 1], evidence[population]["v2-selected"][0][:, h - 1]
            comparison = metrics.bootstrap_difference(selected, base, data.episodes, stats["seed"] + h + (0 if population == "A" else 50),
                                                      tuple(stats["prediction_quantiles"]))
            old = methods["v2-selected"]["prediction"][f"h{h}"]["episode_macro_mae"]
            new = methods["selected"]["prediction"][f"h{h}"]["episode_macro_mae"]
            comparison["relative_reduction"] = 1 - new / old
            comparison["pass"] = (comparison["relative_reduction"] >= protocol["gates"]["prediction_relative_reduction"]
                                  and comparison["interval"][1] < 0)
            primary[f"h{h}"] = comparison
        paired = paired_warning_difference(counts["selected"], counts["v2-selected"], stats["seed"] + (7 if population == "A" else 57),
                                           tuple(stats["warning_quantiles"]))
        miss_new = 1 - methods["selected"]["warning"]["recall"]
        miss_old = 1 - methods["v2-selected"]["warning"]["recall"]
        warning_gate = {"miss_rate_reduction": 1 - miss_new / miss_old if miss_old else None,
                        "recall_difference": paired["recall"], "fpr_difference": paired["fpr"],
                        "selected_fpr": methods["selected"]["warning"]["fpr"]}
        warning_gate["pass"] = (warning_gate["miss_rate_reduction"] is not None
                                and warning_gate["miss_rate_reduction"] >= protocol["gates"]["warning_miss_reduction"]
                                and paired["recall"]["interval"][0] > 0
                                and methods["selected"]["warning"]["fpr"] <= protocol["gates"]["warning_fpr_maximum"])
        ablation = {}
        if "uniform-counterpart" in pipelines and "rsi-counterpart" in pipelines:
            for h in (3, 5):
                comparison = metrics.bootstrap_difference(evidence[population]["rsi-counterpart"][0][:, h - 1],
                                                          evidence[population]["uniform-counterpart"][0][:, h - 1],
                                                          data.episodes, stats["seed"] + 90 + h, (.025, .975))
                old = methods["uniform-counterpart"]["prediction"][f"h{h}"]["episode_macro_mae"]
                new = methods["rsi-counterpart"]["prediction"][f"h{h}"]["episode_macro_mae"]
                comparison["relative_reduction"] = 1 - new / old
                ablation[f"h{h}"] = comparison
        result["populations"][population] = {"methods": methods, "primary_prediction": primary, "warning": warning_gate,
                                             "rsi_ablation": ablation, "windows": int(len(data.states)),
                                             "episodes": int(len(np.unique(data.episodes))), "prevalence": float(labels.mean())}
    guards = {}
    errors = evidence["historical"]
    data = windows3["historical"]
    for h in (1, 3, 5):
        valid = data.valid[:, h - 1] > 0  # historical windows keep v2's incomplete-tail masking
        values = {name: float(metrics.episode_means(err[0][valid, h - 1], data.episodes[valid])[1].mean()) for name, err in errors.items()}
        best_v2 = min(value for name, value in values.items() if name.startswith("v2-"))
        guards[f"h{h}"] = {"selected": values["selected"], "best_v2_or_paper": best_v2,
                           "relative_change": values["selected"] / best_v2 - 1,
                           "pass": values["selected"] <= (1 + protocol["gates"]["historical_maximum_regression"]) * best_v2}
    result["historical_guards"] = guards
    result["primary_prediction_pass"] = (all(x["pass"] for p in result["populations"].values() for x in p["primary_prediction"].values())
                                         and all(x["pass"] for x in guards.values()))
    result["warning_pass"] = all(p["warning"]["pass"] for p in result["populations"].values())
    return result


def build_populations(domain, protocol, selection):
    rows = population_rows(domain, protocol)
    historical, ambiguous = historical_rows(domain)
    rows["historical"] = historical
    histories = sorted({3, *(p["history"] for p in selection["domains"][domain]["pipelines"].values())})
    windows = {}
    for population, population_rows_ in rows.items():
        built = {h: (windows_for(population_rows_, domain, h) if population != "historical"
                     else v3.windows(population_rows_, v3.spec_for(domain, h), complete=False)) for h in histories}
        reference = built[3]
        for h, data in built.items():
            if not (np.array_equal(data.targets, reference.targets) and np.array_equal(data.episodes, reference.episodes)):
                raise AssertionError("history variants disagree on targets")
        windows[population] = built
    return windows, ambiguous


def collect(selection, protocol, domain, windows):
    pipelines = selection["domains"][domain]["pipelines"]
    evidence = {}
    for population in ("A", "B", "historical"):
        evidence[population] = {}
        for name, item in pipelines.items():
            if population == "historical" and name not in ("selected", "v2-selected", "v2-paper-action_conditioned_jepa", "v2-paper-gru_dynamics"):
                continue
            pipeline = Pipeline(item, domain)
            evidence[population][name] = evidence_for(pipeline, item, domain, windows[population][item["history"]])
    return evidence


def final():
    if RESULT.exists() or (ARTIFACTS / "final").exists():
        raise FileExistsError("final already opened; use verify")
    committed(SELECTION)
    selection = architecture.load_json(SELECTION)
    protocol = architecture.load_json(PROTOCOL)
    verify_bindings(selection)
    torch.set_num_threads(8)
    root = ARTIFACTS / "final"
    root.mkdir(parents=True)
    json_write_once(root / "open_event.json", {"opened_at": datetime.now(timezone.utc).isoformat(), "selection": record(SELECTION),
                                              "registration_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                                              "seeds": {"A": protocol["final"]["seed_population_a"], "B": protocol["final"]["seed_population_b"]}})
    try:
        domains = {}
        for domain in DOMAINS:
            windows, ambiguous = build_populations(domain, protocol, selection)
            folder = root / domain
            for population in ("A", "B", "historical"):
                v3.save(folder / f"{population}_h3.npz", windows[population][3])
            evidence = collect(selection, protocol, domain, windows)
            arrays = {f"{population}__{name}__{kind}": value
                      for population, items in evidence.items() for name, pair in items.items()
                      for kind, value in zip(("errors", "scores"), pair)}
            np.savez_compressed(folder / "evidence.npz", **arrays)
            json_write_once(folder / "historical_exclusions.json", {"ambiguous_episodes": ambiguous})
            domains[domain] = analyze(selection, protocol, evidence, {p: windows[p][3] for p in windows}, domain)
            print(json.dumps({"domain": domain, "primary_prediction_pass": domains[domain]["primary_prediction_pass"],
                              "warning_pass": domains[domain]["warning_pass"]}), flush=True)
        verify_bindings(selection)
        result = {"study_id": protocol["study_id"], "evidence_class": protocol["evidence_class"], "domains": domains,
                  "selection": record(SELECTION), "open_event": record(root / "open_event.json"),
                  "final_artifacts": [record(path) for path in sorted(root.rglob("*.npz"))] + [record(path) for path in sorted(root.rglob("historical_exclusions.json"))],
                  "primary_prediction_objective_pass": all(d["primary_prediction_pass"] for d in domains.values()),
                  "secondary_warning_objective_pass": all(d["warning_pass"] for d in domains.values()),
                  "protected_unchanged": protected(), "promotion_eligible": False, "actuator_attempts": 0, "actuator_deliveries": 0,
                  "limitations": protocol["claim_boundaries"]}
        json_write_once(RESULT, result)
        print(json.dumps({"result": str(RESULT), "primary": result["primary_prediction_objective_pass"],
                          "warning": result["secondary_warning_objective_pass"]}))
    except Exception as exc:
        json_write_once(root / "failed_attempt.json", {"error": type(exc).__name__, "message": str(exc), "prospective_result_eligible": False})
        raise


def verify():
    selection = architecture.load_json(SELECTION)
    protocol = architecture.load_json(PROTOCOL)
    original = architecture.load_json(RESULT)
    verify_bindings(selection)
    torch.set_num_threads(8)
    checks = {}
    domains = {}
    for domain in DOMAINS:
        folder = ARTIFACTS / "final" / domain
        windows3 = {p: v3.load(folder / f"{p}_h3.npz") for p in ("A", "B", "historical")}
        windows, _ = build_populations(domain, protocol, selection)
        for population in windows3:
            checks[f"{domain}/{population}/regenerated_catalog_identical"] = all(
                np.array_equal(getattr(windows3[population], k), getattr(windows[population][3], k)) for k in v3.Windows.__dataclass_fields__)
        evidence = collect(selection, protocol, domain, windows)
        with np.load(folder / "evidence.npz", allow_pickle=False) as archive:
            for population, items in evidence.items():
                for name, (errors, scores) in items.items():
                    checks[f"{domain}/{population}/{name}/inference"] = bool(
                        np.allclose(archive[f"{population}__{name}__errors"], errors, atol=1e-7, rtol=0)
                        and np.allclose(archive[f"{population}__{name}__scores"], scores, atol=1e-7, rtol=0))
            stored = {population: {name: (archive[f"{population}__{name}__errors"], archive[f"{population}__{name}__scores"])
                                   for name in items} for population, items in evidence.items()}
        domains[domain] = analyze(selection, protocol, stored, windows3, domain)
    checks["all_metrics_recompute_exactly"] = domains == original["domains"]
    checks["final_artifact_digests"] = all(record_matches(item) for item in original["final_artifacts"])
    checks["no_failed_final_attempt"] = not (ARTIFACTS / "final/failed_attempt.json").exists()
    checks["no_authority"] = not original["promotion_eligible"] and original["actuator_attempts"] == original["actuator_deliveries"] == 0
    checks["protected_unchanged"] = all(protected().values())
    report = {"study_id": protocol["study_id"], "result": record(RESULT), "checks": checks, "all_checks_pass": all(checks.values()),
              "verification_mode": "regenerate registered catalogs, recompute inference from retained checkpoints, recompute statistics",
              "promotion_eligible": False}
    if VERIFICATION.exists():
        if architecture.load_json(VERIFICATION) != report:
            raise AssertionError("verification changed")
    else:
        json_write_once(VERIFICATION, report)
    print(json.dumps({"checks": len(checks), "all_checks_pass": report["all_checks_pass"]}))
    if not report["all_checks_pass"]:
        raise AssertionError([k for k, v in checks.items() if not v])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["select", "final", "verify"])
    args = parser.parse_args()
    {"select": select, "final": final, "verify": verify}[args.stage]()


if __name__ == "__main__":
    main()
