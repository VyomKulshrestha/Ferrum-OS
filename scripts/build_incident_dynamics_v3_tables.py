#!/usr/bin/env python3
"""Generate the manuscript tables for incident-dynamics v3 directly from registered JSON records.

Prints Markdown so that every number in Section 8.8 is traceable to a retained artifact.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "docs/research/incident_dynamics_sources_v3.json"
RESULT = ROOT / "docs/research/incident_dynamics_result_v3.json"
SELECTION = ROOT / "docs/research/incident_dynamics_selection_v3.json"

SHORT = {
    "crowdstrike-channel-file-291-2024": "CrowdStrike RCA 2024", "meta-backbone-bgp-withdrawal-2021": "Meta 2021",
    "gitlab-database-outage-2017": "GitLab 2017", "aws-s3-us-east-1-2017": "AWS S3 2017", "knight-capital-2012": "SEC Knight Capital",
    "cloudflare-waf-regex-cpu-2019": "Cloudflare 2019", "aws-us-east-1-retry-storm-2021": "AWS 2021",
    "log4shell-cve-2021-44228-2021": "CISA Log4Shell", "xz-utils-backdoor-cve-2024-3094-2024": "xz-utils disclosure",
    "mirai-dyn-ddos-2016": "Mirai (USENIX)", "aws-ebs-agent-memory-leak-2012": "AWS 2012", "instapaper-rds-filesize-limit-2017": "Instapaper 2017",
    "stuxnet-centrifuge-sabotage": "Stuxnet dossier", "ukraine-power-grid-2015": "CISA Ukraine 2015", "oldsmar-water-treatment-2021": "CISA Oldsmar",
    "maroochy-sewage-2000": "MITRE Maroochy", "triton-trisis-safety-system-2017": "TRITON", "jeep-cherokee-remote-2015": "Jeep Cherokee paper",
    "boeing-737max-mcas-2019": "NTSB 737 MAX", "uber-atg-tempe-2018": "NTSB Uber ATG", "jal-787-apu-battery-fire-2013": "NTSB JAL 787",
    "mars-climate-orbiter-1999": "NASA MCO", "ariane5-flight501-1996": "ESA Ariane 501", "gnss-jamming-spoofing-aviation-easa-2022": "EASA GNSS AD",
}
LABEL = {"ferrumos": "OS", "physical": "Physical"}


def table_sources():
    import incident_dynamics_v3_data as v3
    catalog = json.loads(SOURCES.read_text(encoding="utf-8"))
    rows = ["| Domain | Mechanism family | Partition | Motivating sources | Abstract perturbation |", "|---|---|---|---|---|"]
    for domain, library in (("ferrumos", v3.OS_MECHANISMS), ("physical", v3.PHYSICAL_MECHANISMS)):
        for mechanism, description in library.items():
            held = mechanism in v3.HELD_OUT_MECHANISMS[domain]
            names = [SHORT[s["id"]] for s in catalog["sources"] if s["domain"] == domain and s["motivates_mechanism"] == mechanism]
            if mechanism == "constant_pressure":
                names = ["v1/v2 sources"] + names
            if not names:
                names = ["generic wear (no incident claimed)"]
            rows.append(f"| {LABEL[domain]} | {mechanism.replace('_', ' ')} | {'held out' if held else 'development'} | "
                        f"{'; '.join(names)} | {description} |")
    return "\n".join(rows)


def pct(x):
    return f"{100 * x:.1f}%"


def table_primary(result, label="v3"):
    rows = [f"| Population | Domain | Horizon | v2-selected MAE | {label}-selected MAE | Reduction | {label} minus v2, 99.375% CI | Gate |",
            "|---|---|---|---|---|---|---|---|"]
    for population in ("A", "B"):
        for domain in ("ferrumos", "physical"):
            data = result["domains"][domain]["populations"][population]
            for h in ("h3", "h5"):
                old = data["methods"]["v2-selected"]["prediction"][h]["episode_macro_mae"]
                new = data["methods"]["selected"]["prediction"][h]["episode_macro_mae"]
                cmp = data["primary_prediction"][h]
                lo, hi = cmp["interval"]
                rows.append(f"| {population} | {LABEL[domain]} | H={h[1]} | {old:.6f} | {new:.6f} | {pct(cmp['relative_reduction'])} | "
                            f"[{lo:.6f}, {hi:.6f}] | {'pass' if cmp['pass'] else 'fail'} |")
    return "\n".join(rows)


def table_controls(result):
    order = ["persistence", "constant_velocity", "v2-paper-gru_dynamics", "v2-paper-action_conditioned_jepa", "v2-ridge",
             "v2-selected", "uniform-counterpart", "rsi-counterpart", "selected"]
    names = {"persistence": "State persistence", "constant_velocity": "Causal constant velocity", "v2-paper-gru_dynamics": "Paper GRU ensemble",
             "v2-paper-action_conditioned_jepa": "Paper JEPA ensemble", "v2-ridge": "v2 per-action ridge", "v2-selected": "v2-selected (Section 8.7)",
             "uniform-counterpart": "v3 uniform curriculum", "rsi-counterpart": "v3 evolving-world curriculum", "selected": "v3-selected"}
    rows = ["| Method | OS A | OS B | Physical A | Physical B |", "|---|---|---|---|---|"]
    for name in order:
        cells = []
        for domain in ("ferrumos", "physical"):
            for population in ("A", "B"):
                methods = result["domains"][domain]["populations"][population]["methods"]
                cells.append(f"{methods[name]['prediction']['h5']['episode_macro_mae']:.6f}" if name in methods else "not run")
        label = f"**{names[name]}**" if name == "selected" else names[name]
        rows.append(f"| {label} | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} |")
    return "\n".join(rows)


def table_warnings(result, label="v3"):
    rows = ["| Population | Domain | Pipeline | TP / FP / TN / FN | Recall | FPR | Brier | Miss reduction | Gate |",
            "|---|---|---|---|---|---|---|---|---|"]
    for population in ("A", "B"):
        for domain in ("ferrumos", "physical"):
            data = result["domains"][domain]["populations"][population]
            for name, pipeline_label in (("v2-selected", "v2-selected, recalibrated"), ("selected", f"{label}-selected")):
                w = data["methods"][name]["warning"]
                tail = (f"{pct(data['warning']['miss_rate_reduction'])} | {'pass' if data['warning']['pass'] else 'fail'}"
                        if name == "selected" else "- | -")
                rows.append(f"| {population} | {LABEL[domain]} | {pipeline_label} | {w['tp']} / {w['fp']} / {w['tn']} / {w['fn']} | "
                            f"{pct(w['recall'])} | {100 * w['fpr']:.2f}% | {w['brier']:.4f} | {tail} |")
    return "\n".join(rows)


def table_rsi(result):
    rows = ["| Population | Horizon | Uniform MAE | Evolving-world MAE | Reduction | Paired 95% CI (RSI minus uniform) |", "|---|---|---|---|---|---|"]
    for population in ("A", "B"):
        data = result["domains"]["ferrumos"]["populations"][population]
        for h in ("h3", "h5"):
            ab = data["rsi_ablation"][h]
            old = data["methods"]["uniform-counterpart"]["prediction"][h]["episode_macro_mae"]
            new = data["methods"]["rsi-counterpart"]["prediction"][h]["episode_macro_mae"]
            lo, hi = ab["interval"]
            rows.append(f"| {population} | H={h[1]} | {old:.6f} | {new:.6f} | {pct(ab['relative_reduction'])} | [{lo:.6f}, {hi:.6f}] |")
    return "\n".join(rows)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    print(table_sources())
    if RESULT.exists():
        result = json.loads(RESULT.read_text(encoding="utf-8"))
        for builder in (table_primary, table_controls, table_warnings, table_rsi):
            print()
            print(builder(result))


def table_development_trials():
    """Every retained v3 development trial: configuration, family, seeds and validation scores."""
    import glob
    from collections import defaultdict
    groups = defaultdict(list)
    for path in sorted(glob.glob(str(ROOT / "target/incident-dynamics-v3/trials/*/*.json"))):
        record = json.loads(Path(path).read_text(encoding="utf-8"))
        settings = record["settings"]
        groups[(settings["domain"], settings["trial_id"])].append(record)
    family = {"ar_residual": "AR net", "boost_v2": "net on v2", "boost_v2_attention": "net on v2 (attn)",
              "edd": "effect-drift net", "edd_attention": "effect-drift net (attn)", "uar_hybrid": "ridge + net",
              "gbr": "trees on v2, one-step", "gbr_direct": "trees on v2, direct"}
    rows = ["| Domain | Configuration | Family | H | Weighting | Seeds | Score | Legacy | Incident | Mechanism |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for (domain, name), records in sorted(groups.items()):
        s = records[0]["settings"]
        weighting = "balanced" if s.get("block_balance") else (f"incident x{s.get('incident_weight', 1):g}" if s.get("incident_weight", 1) != 1 else "uniform")
        if s.get("curriculum") == "rsi":
            weighting += ", RSI"
        if not s.get("mechanisms", 1):
            weighting += ", no mech."
        if s.get("scale_model"):
            weighting += ", + scale"
        rescored = json.loads((ROOT / "target/incident-dynamics-v3/trial_rescores.json").read_text())
        scores = [rescored[f"{name}-s{r['seed']}.json"] for r in records]
        mean = lambda key: sum(x[key] for x in scores) / len(scores)
        rows.append(f"| {LABEL[domain]} | {name} | {family.get(s['method'], s['method'])} | {s['history']} | {weighting} | "
                    f"{', '.join(str(r['seed']) for r in sorted(records, key=lambda r: r['seed']))} | "
                    f"{sum(x['selection_score'] for x in scores) / len(scores):.3f} | {mean('legacy_validation'):.3f} | "
                    f"{mean('incident_validation'):.3f} | {mean('mech_validation'):.3f} |")
    return "\n".join(rows)


def table_v4_physical_lineage(result):
    """Physical v4 against v3-selected and v2-selected on the fresh v4 populations and the historical guard."""
    rows = ["| Evidence | Horizon | v2-selected | v3-selected (one-step) | v4-selected (direct) | v4 vs v2 | v4 vs v3 |", "|---|---|---|---|---|---|---|"]
    domain = result["domains"]["physical"]
    for population in ("A", "B"):
        methods = domain["populations"][population]["methods"]
        for h in ("h3", "h5"):
            v2, v3s, v4 = (methods[n]["prediction"][h]["episode_macro_mae"] for n in ("v2-selected", "v3-selected", "selected"))
            rows.append(f"| Population {population} | H={h[1]} | {v2:.6f} | {v3s:.6f} | {v4:.6f} | {pct(1 - v4 / v2)} | {pct(1 - v4 / v3s)} |")
    for h, guard in domain["historical_guards"].items():
        rows.append(f"| Historical guard | H={h[1]} | {guard['best_v2_or_paper']:.6f} | - | {guard['selected']:.6f} | {pct(-guard['relative_change'])} | - |")
    return "\n".join(rows)
