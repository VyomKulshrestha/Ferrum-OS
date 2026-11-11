"""tw1 (Thresholds in the Wild): build the catalogue from the group readings and the verification file.

The group files (group_*.json) are written by the reading agents into a directory outside the repository.
The verification file is written by hand after items 4 and 5 of every row were re-read at the cited lines.
Only rows whose status is "verified" or "corrected" count in the decision rule of
docs/research/thresholds_in_the_wild_tw1_catalogue_plan.md.

Usage: tw1_catalogue_build.py <dir with group_*.json> <repo root> [--check]
"""

import json
import sys
from pathlib import Path

KEYS = [
    "target", "group", "kind", "repo", "commit", "version", "licence", "licence_notes", "adoption", "in_scope",
    "scope_reason", "default_path", "adaptive_quantity", "update_rule", "learning_region", "evidence",
    "learns_from_own_alarms", "default_when_configurable", "memory", "direction_bounds", "alarm_logic",
    "operator_controls", "documentation_quote", "closest_tt1_rule", "differs", "predictions", "runnable", "notes",
    "unresolved",
]  # fmt: skip
LEARNS = {"yes", "no", "partial", "configurable", "unclear", "not_adaptive"}
COUNTED = {"verified", "corrected"}
PLAN = "docs/research/thresholds_in_the_wild_tw1_catalogue_plan.md"
VERIFICATION = "docs/research/thresholds_in_the_wild_tw1_verification.json"
OUT_JSON = "docs/research/thresholds_in_the_wild_tw1_catalogue.json"
OUT_MD = "docs/research/thresholds_in_the_wild_tw1_catalogue.md"
PREFACE = "docs/research/thresholds_in_the_wild_tw1_catalogue_preface.md"


def load_rows(src):
    rows, problems = [], []
    for path in sorted(Path(src).glob("group_*.json")):
        for row in json.loads(path.read_text(encoding="utf-8")):
            missing = [k for k in KEYS if k not in row]
            if missing:
                problems.append(
                    f"{path.name}: {row.get('target', '?')}: missing {missing}"
                )
            if row.get("learns_from_own_alarms") not in LEARNS:
                problems.append(
                    f"{path.name}: {row.get('target', '?')}: learns_from_own_alarms = {row.get('learns_from_own_alarms')!r}"
                )
            rows.append(row)
    names = [r.get("target") for r in rows]
    problems += [
        f"duplicate target name: {n}"
        for n in sorted({n for n in names if names.count(n) > 1})
    ]
    return rows, problems


def decide(rows, ver):
    """Apply the decision rule of the plan to families of rows. A family absorbs when one of its in-scope rows,
    verified or corrected, updates the alarm-deciding quantity with flagged samples on the default path."""
    fam = {}
    for r in rows:
        v = ver.get(r["target"])
        if not v:
            continue
        f = fam.setdefault(v["family"], {"absorbs": False, "partial_only": True, "product": False, "runnable": False, "rows": [],
                                         "set_aside": False})  # fmt: skip
        f["rows"].append(r["target"])
        if not (r["in_scope"] and v["status"] in COUNTED and v.get("default_absorbs")):
            continue
        if v.get("counted") is False:
            # absorbs, but set aside by the reading (batch-only threshold, or a change detector by design)
            f["set_aside"] = True
            continue
        f["absorbs"] = True
        f["partial_only"] = (
            f["partial_only"] and v["learns_from_own_alarms"] == "partial"
        )
        f["product"] = f["product"] or bool(v.get("product"))
        f["runnable"] = f["runnable"] or bool(v.get("runnable_here"))
    absorbing = {k: f for k, f in fam.items() if f["absorbs"]}
    n = len(absorbing)
    products = sorted(k for k, f in absorbing.items() if f["product"])
    runnable = sorted(k for k, f in absorbing.items() if f["runnable"])
    strict = sorted(k for k, f in absorbing.items() if not f["partial_only"])
    if n >= 5 and len(products) >= 2 and len(runnable) >= 3:
        outcome = "go"
    elif n <= 2:
        outcome = "shrink"
    else:
        outcome = "between"
    return {
        "families_read": len(fam),
        "set_aside": sorted(
            k for k, f in fam.items() if f["set_aside"] and not f["absorbs"]
        ),
        "absorbing": sorted(absorbing),
        "absorbing_without_partial_only": strict,
        "absorbing_products": products,
        "absorbing_runnable_here": runnable,
        "outcome": outcome,
        "between_condition_met": bool(set(products) & set(runnable))
        if outcome == "between"
        else None,
        "rule": "go: >= 5 absorbing families, >= 2 of them products or plugins, >= 3 runnable here; shrink: <= 2; otherwise between",
    }


def cell(text, limit=None):
    text = " ".join(str(text if text is not None else "").split()).replace("|", "\\|")
    return text if not limit or len(text) <= limit else text[: limit - 1].rstrip() + "…"


def markdown(rows, ver, decision, preface):
    out = (
        [preface.rstrip(), ""]
        if preface
        else ["# Thresholds in the Wild (tw1): catalogue", ""]
    )
    out += ["## Decision", ""]
    out += [f"- Families read: {decision['families_read']}."]
    out += [
        f"- Absorbing on the default path, verified: {len(decision['absorbing'])} ({', '.join(decision['absorbing']) or 'none'})."
    ]
    out += [f"- Of these, absorbing at full weight (not only down-weighted): {len(decision['absorbing_without_partial_only'])} "
            f"({', '.join(decision['absorbing_without_partial_only']) or 'none'})."]  # fmt: skip
    out += [
        f"- Products or plugins among them: {len(decision['absorbing_products'])} ({', '.join(decision['absorbing_products']) or 'none'})."
    ]
    out += [
        f"- Runnable on this laptop: {len(decision['absorbing_runnable_here'])} ({', '.join(decision['absorbing_runnable_here']) or 'none'})."
    ]
    out += [f"- Absorbing but set aside and not counted (batch-only thresholds, change detectors by design): "
            f"{', '.join(decision['set_aside']) or 'none'}."]  # fmt: skip
    out += [f"- Rule ({decision['rule']}): **{decision['outcome']}**.", ""]

    def table(title, selected):
        if not selected:
            return
        out.extend([f"## {title}", ""])
        out.append(
            "| Target | Kind | Adaptive quantity | Learns from its own alarms | Evidence | Closest tt1 rule | Runnable here | Check |"
        )
        out.append("|---|---|---|---|---|---|---|---|")
        for r in selected:
            v = ver.get(r["target"], {})
            learns = v.get("learns_from_own_alarms", r["learns_from_own_alarms"])
            if learns == "configurable":
                learns += f" (default: {cell(r['default_when_configurable'], 40)})"
            ev = v.get("lines_checked") or "; ".join(
                f"{e['file']}:{e['lines']}" for e in r["evidence"][:2]
            )
            out.append(
                f"| {cell(r['target'])} | {cell(r['kind'])} | {cell(r['adaptive_quantity'], 90)} | {cell(learns)} | "
                f"{cell(ev, 110)} | {cell(r['closest_tt1_rule'], 50)} | {cell(r['runnable'], 40)} | {cell(v.get('status', 'agent only'))} |"
            )
        out.append("")

    by_group = {}
    for r in rows:
        by_group.setdefault(r["group"], []).append(r)
    titles = {"A": "Group A: Python streaming libraries", "B": "Group B: search and observability engines",
              "C": "Group C: reference code", "D": "Group D: monitoring platforms"}  # fmt: skip
    for g in sorted(by_group):
        table(titles.get(g, f"Group {g}"), [r for r in by_group[g] if r["in_scope"]])
    table("Out of scope or static controls", [r for r in rows if not r["in_scope"]])

    out += [
        "## Predictions for the development round (hypotheses, written before any run)",
        "",
    ]
    out += [
        "| Target | Sustained attack | Loud pulses | Frog | Sub-event pulses |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        if r["in_scope"]:
            p = r["predictions"] or {}
            out.append(
                f"| {cell(r['target'])} | "
                + " | ".join(
                    cell(p.get(k), 120) for k in ("sustained", "loud", "frog", "subl")
                )
                + " |"
            )
    out.append("")

    out += ["## Notes per target", ""]
    for r in rows:
        v = ver.get(r["target"], {})
        out += [f"### {r['target']}", ""]
        out += [
            f"- Repository: {r['repo']} at `{r['commit']}` (version {r['version']}); licence {r['licence']}. {cell(r['licence_notes'])}"
        ]
        out += [f"- Adoption: {cell(r['adoption'])}"]
        out += [
            f"- Scope: {'in' if r['in_scope'] else 'out'}. {cell(r['scope_reason'])}"
        ]
        out += [f"- Default path: {cell(r['default_path'])}"]
        out += [f"- Update rule: {cell(r['update_rule'])}"]
        out += [f"- Learning region: {cell(r['learning_region'])}"]
        for e in r["evidence"]:
            out += [
                f"  - `{e['file']}:{e['lines']}`",
                "",
                "    ```",
                *("    " + ln for ln in str(e["quote"]).splitlines()),
                "    ```",
                "",
            ]
        out += [f"- Memory: {cell(r['memory'])}"]
        out += [f"- Direction and bounds: {cell(r['direction_bounds'])}"]
        out += [f"- Alarm logic: {cell(r['alarm_logic'])}"]
        out += [f"- Operator controls: {cell(r['operator_controls'])}"]
        out += [f"- Documentation: {cell(r['documentation_quote'])}"]
        out += [
            f"- Closest tt1 rule: {cell(r['closest_tt1_rule'])}. Differs: {cell(r['differs'])}"
        ]
        out += [f"- Runnable here: {cell(r['runnable'])}"]
        if r["notes"]:
            out += [f"- Notes: {cell(r['notes'])}"]
        if r["unresolved"]:
            out += [f"- Unresolved: {cell(r['unresolved'])}"]
        if v:
            out += [f"- Check ({v['status']}): {cell(v.get('note'))}"]
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def main():
    src, root = Path(sys.argv[1]), Path(sys.argv[2])
    rows, problems = load_rows(src)
    for p in problems:
        print("PROBLEM", p)
    if "--check" in sys.argv:
        print(len(rows), "rows;", len(problems), "problems")
        for r in rows:
            print(
                f"{r.get('group')} | {r.get('target')} | {r.get('kind')} | in_scope={r.get('in_scope')} | {r.get('learns_from_own_alarms')}"
            )
        return 1 if problems else 0
    if problems:
        return 1
    vdoc = json.loads((root / VERIFICATION).read_text(encoding="utf-8"))
    ver = vdoc["rows"]
    unknown = sorted(set(ver) - {r["target"] for r in rows})
    unchecked = sorted({r["target"] for r in rows} - set(ver))
    if unknown:
        raise SystemExit(f"verification names rows that do not exist: {unknown}")
    decision = decide(rows, ver)
    # The full rows stay in the group files beside the readings; this file is the index and the decision.
    index = [
        {
            "target": r["target"],
            "group": r["group"],
            "kind": r["kind"],
            "repo": r["repo"],
            "commit": r["commit"],
            "in_scope": r["in_scope"],
            "family": ver.get(r["target"], {}).get("family"),
            "learns_from_own_alarms": ver.get(r["target"], {}).get(
                "learns_from_own_alarms", r["learns_from_own_alarms"]
            ),
            "status": ver.get(r["target"], {}).get("status", "agent only"),
            "lines_checked": ver.get(r["target"], {}).get("lines_checked", ""),
        }
        for r in rows
    ]
    doc = {"schema": "tw1-catalogue-v1", "plan": PLAN, "verified_on": vdoc["verified_on"], "decision": decision,
           "rows_without_a_check": unchecked, "additions": vdoc.get("additions", []), "left_out": vdoc.get("left_out", []),
           "full_rows": "docs/research/tw1_catalogue_readings/group_*.json", "rows": index}  # fmt: skip
    (root / OUT_JSON).write_text(
        json.dumps(doc, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    preface = (
        (root / PREFACE).read_text(encoding="utf-8")
        if (root / PREFACE).exists()
        else ""
    )
    (root / OUT_MD).write_text(
        markdown(rows, ver, decision, preface), encoding="utf-8", newline="\n"
    )
    print(len(rows), "rows;", len(ver), "checked;", "outcome:", decision["outcome"])
    print(json.dumps({k: v for k, v in decision.items() if k != "rule"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
