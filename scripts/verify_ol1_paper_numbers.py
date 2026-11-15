#!/usr/bin/env python3
"""Check every number macro of the ol1 paper against its source.

    python scripts/verify_ol1_paper_numbers.py            # check; exit 1 on any mismatch
    python scripts/verify_ol1_paper_numbers.py --write    # (re)write values.tex, table_cells.tex, NUMBER_TRACE.md
    ... [--jobs PATH]   # optional: the Kaggle job file, to replay the open-weight M(600) by the registered code

The paper (docs/research/paper/ol1_paper_pack/latex/main.tex) writes no result as a literal: every number from
the study is a macro defined in latex/values.tex, and the full cell table is latex/table_cells.tex. This script
recomputes each value from

- docs/research/operator_in_the_loop_ol1_result.json (registered analysis output),
- docs/research/ol1_result/<model>/episodes.jsonl (episode records; descriptive counts),
- docs/research/ol1_result/README.md (run record),
- docs/research/ol1_open_weight/*.ol1rec.txt (exploratory open-weight arm, OL1REC lines),
- docs/research/paper/ol1_paper_pack/ol1_quote_sample.json (systematic transcript sample),
- scripts/ol1_core.py (design constants of the registered code),

formats it as the paper prints it, and compares it with the macro's definition in values.tex. It also checks
that every macro main.tex uses is defined, that table_cells.tex equals the table rebuilt from the result JSON,
and lists numerals written directly in main.tex for review (not an error: section numbers, model names,
dates and the like).
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import ol1_core as C  # noqa: E402

DOCS = ROOT / "docs/research"
PACK = DOCS / "paper/ol1_paper_pack"
LATEX = PACK / "latex"
RESULT = DOCS / "operator_in_the_loop_ol1_result.json"
EPIS = DOCS / "ol1_result"
OPEN = DOCS / "ol1_open_weight"
QUOTES = PACK / "ol1_quote_sample.json"
HAIKU, SONNET, OPUS = "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"
MODELS = (HAIKU, SONNET, OPUS)
SRC_R = "operator_in_the_loop_ol1_result.json"
SRC_E = "ol1_result/<model>/episodes.jsonl (descriptive)"
OW_FILES = {
    "qwen": "qwen3-8b_sealed_subset.ol1rec.txt",
    "granite": "granite-3.3-8b_sealed_subset_rerun.ol1rec.txt",
    "mistral": "mistral-nemo-12b_sealed_subset.ol1rec.txt",
}


# ---------------------------------------------------------------- formatting
def f3(x):
    s = f"{x:.3f}"
    if s.startswith("-"):
        return "$-$" + s[1:]
    return s


def f2(x):
    s = f"{x:.2f}"
    return "$-$" + s[1:] if s.startswith("-") else s


def f1(x):
    return f"{x:.1f}"


def ci(v):
    return f"[{f3(v[0])}, {f3(v[1])}]"


def n(x):
    return f"{int(x):,}"


# ---------------------------------------------------------------- sources
def load():
    res = json.loads(RESULT.read_text(encoding="utf-8"))
    eps = {}
    for m in MODELS:
        p = EPIS / m / "episodes.jsonl"
        eps[m] = [
            json.loads(line)
            for line in p.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    ow = {}
    for k, f in OW_FILES.items():
        recs = {}
        for line in (OPEN / f).read_text(encoding="utf-8").splitlines():
            if "OL1REC " in line:
                r = json.loads(line[line.index("OL1REC ") + 7 :])
                recs.setdefault((r["m"], r["s"], r["c"], r["a"]), r)
        ow[k] = list(recs.values())
    quotes = json.loads(QUOTES.read_text(encoding="utf-8"))
    readme = (EPIS / "README.md").read_text(encoding="utf-8")
    return res, eps, ow, quotes, readme


def cell(eps, m, cond, arm):
    return [r for r in eps[m] if r["condition"] == cond and r["arm"] == arm]


def count(rows, fn):
    return sum(1 for r in rows if fn(r))


def tbl(res, m, cond, arm):
    for r in res["tables"]:
        if (r["model"], r["condition"], r["arm"]) == (m, cond, arm):
            return r
    raise KeyError((m, cond, arm))


def beyond(r):
    return r["outcomes"]["loosened_beyond_ceiling"]


def thr_above(r):
    return r["final_config"]["threshold"] > C.CEIL_THRESHOLD * r["tau0"] * (1 + 1e-12)


def readme_row(readme, model):
    for line in readme.splitlines():
        if line.startswith(f"| {model} |"):
            return [c.strip() for c in line.strip("|").split("|")]
    raise KeyError(model)


# ---------------------------------------------------------------- the values
def values(res, eps, ow, quotes, readme, jobs=None):
    """List of (macro, value as printed, source)."""
    H = res["hypotheses"]
    V = []

    def add(name, val, src):
        V.append((name, val, src))

    # design constants (registered code)
    add("VCeilThr", f"{C.CEIL_THRESHOLD:.2f}", "ol1_core.CEIL_THRESHOLD")
    add("VCeilDelay", f"{C.CEIL_DELAY_S:.0f}", "ol1_core.CEIL_DELAY_S")
    add("VCeilSup", f"{C.CEIL_SUPPRESS_H:g}", "ol1_core.CEIL_SUPPRESS_H")
    add(
        "VAddedCeil",
        f1(C.delay_steps(C.CEIL_DELAY_S) * C.STEP_SECONDS),
        "ol1_core.delay_steps(60) x STEP_SECONDS",
    )
    add("VStep", f"{C.STEP_SECONDS:g}", "ol1_core.STEP_SECONDS")
    add("VReviews", str(C.N_REVIEWS), "ol1_core.N_REVIEWS")
    add("VMaxCalls", str(C.MAX_CALLS_PER_REVIEW), "ol1_core.MAX_CALLS_PER_REVIEW")
    add("VLoudSteps", str(C.LOUD[1]), "ol1_core.LOUD[1]")
    add("VSublSteps", str(C.SUBL[1]), "ol1_core.SUBL[1]")
    add("VFrogFrac", f"{C.FROG_FRAC:.2f}", "ol1_core.FROG_FRAC")
    add("VGap", str(C.GAP), "ol1_core.GAP")
    add("VLogRows", str(C.LOG_ROWS), "ol1_core.LOG_ROWS")

    # sizes
    add("VEpisodes", n(res["episodes"]), f"{SRC_R}: episodes")
    for k, m in (("Haiku", HAIKU), ("Sonnet", SONNET), ("Opus", OPUS)):
        add(f"VEp{k}", n(len(eps[m])), f"ol1_result/{m}/episodes.jsonl: line count")
    add(
        "VCampEp",
        n(H["H1"]["B_campaigns_P0"]["episodes"]),
        f"{SRC_R}: hypotheses.H1.B_campaigns_P0.episodes",
    )
    add("VGEp", n(H["H5"]["G_episodes"]), f"{SRC_R}: hypotheses.H5.G_episodes")

    # H1, H1b
    b = H["H1"]["B_campaigns_P0"]
    add("VHoneB", f3(b["estimate"]), f"{SRC_R}: hypotheses.H1.B_campaigns_P0.estimate")
    add("VHoneBci", ci(b["ci95"]), f"{SRC_R}: hypotheses.H1.B_campaigns_P0.ci95")
    for d in ("60", "120", "300", "600"):
        x = H["H1b"]["M_by_duration_campaigns_P0"][d]
        w = {
            "60": "Sixty",
            "120": "OneTwenty",
            "300": "ThreeHundred",
            "600": "SixHundred",
        }[d]
        add(
            f"VM{w}",
            f3(x["estimate"]),
            f"{SRC_R}: hypotheses.H1b.M_by_duration_campaigns_P0.{d}.estimate",
        )
        add(
            f"VM{w}ci",
            ci(x["ci95"]),
            f"{SRC_R}: hypotheses.H1b.M_by_duration_campaigns_P0.{d}.ci95",
        )
    x = H["H1b"]["M105_campaigns_P0"]
    add(
        "VMOhFive",
        f3(x["estimate"]),
        f"{SRC_R}: hypotheses.H1b.M105_campaigns_P0.estimate",
    )
    add("VMOhFiveci", ci(x["ci95"]), f"{SRC_R}: hypotheses.H1b.M105_campaigns_P0.ci95")
    x = H["H1b"]["added_delay_campaigns_P0"]
    add(
        "VDelMed",
        f1(x["median_s"]),
        f"{SRC_R}: hypotheses.H1b.added_delay_campaigns_P0.median_s",
    )
    add(
        "VDelPninety",
        f1(x["p90_s"]),
        f"{SRC_R}: hypotheses.H1b.added_delay_campaigns_P0.p90_s",
    )
    add(
        "VDelShare",
        f3(x["share_above_ceiling"]["estimate"]),
        f"{SRC_R}: ...added_delay_campaigns_P0.share_above_ceiling.estimate",
    )
    add(
        "VDelShareci",
        ci(x["share_above_ceiling"]["ci95"]),
        f"{SRC_R}: ...added_delay_campaigns_P0.share_above_ceiling.ci95",
    )

    # H2
    x = H["H2"]["B_campaigns_minus_nuisance_P0"]
    add(
        "VHtwo",
        f3(x["estimate"]),
        f"{SRC_R}: hypotheses.H2.B_campaigns_minus_nuisance_P0.estimate",
    )
    add(
        "VHtwoci",
        ci(x["ci95"]),
        f"{SRC_R}: hypotheses.H2.B_campaigns_minus_nuisance_P0.ci95",
    )
    add(
        "VHtwocininety",
        ci(x["ci90"]),
        f"{SRC_R}: hypotheses.H2.B_campaigns_minus_nuisance_P0.ci90",
    )
    add(
        "VHtwoPos",
        str(x["modes_positive"]),
        f"{SRC_R}: hypotheses.H2.B_campaigns_minus_nuisance_P0.modes_positive",
    )
    x = H["H2"]["nuisance_B_P0"]
    add("VNuisB", f3(x["estimate"]), f"{SRC_R}: hypotheses.H2.nuisance_B_P0.estimate")
    add("VNuisBci", ci(x["ci95"]), f"{SRC_R}: hypotheses.H2.nuisance_B_P0.ci95")

    # H3
    for k, w in (("loud", "Loud"), ("subl", "Subl"), ("frog", "Frog")):
        x = H["H3"][k]["B_campaign_minus_twin_P0"]
        add(
            f"VHthree{w}",
            f3(x["estimate"]),
            f"{SRC_R}: hypotheses.H3.{k}.B_campaign_minus_twin_P0.estimate",
        )
        add(
            f"VHthree{w}ci",
            ci(x["ci95"]),
            f"{SRC_R}: hypotheses.H3.{k}.B_campaign_minus_twin_P0.ci95",
        )
        add(
            f"VHthree{w}Pos",
            str(x["modes_positive"]),
            f"{SRC_R}: hypotheses.H3.{k}...modes_positive",
        )
        add(
            f"VHthree{w}Neg",
            str(x["modes_negative"]),
            f"{SRC_R}: hypotheses.H3.{k}...modes_negative",
        )
        add(
            f"VHthree{w}Zero",
            str(x["modes_zero"]),
            f"{SRC_R}: hypotheses.H3.{k}...modes_zero",
        )

    # H4
    for k, w in (
        ("M_P0_minus_P2_campaigns", "M"),
        ("M120_P0_minus_P2_campaigns", "Mtwo"),
        ("B_P0_minus_P2_campaigns", "B"),
    ):
        x = H["H4"][k]
        add(f"VHfour{w}", f3(x["estimate"]), f"{SRC_R}: hypotheses.H4.{k}.estimate")
        add(f"VHfour{w}ci", ci(x["ci95"]), f"{SRC_R}: hypotheses.H4.{k}.ci95")
    x = H["H4"]["M_P0_minus_P2_campaigns"]
    add(
        "VHfourMcininety",
        ci(x["ci90"]),
        f"{SRC_R}: hypotheses.H4.M_P0_minus_P2_campaigns.ci90",
    )
    add(
        "VHfourMPos",
        str(x["modes_positive"]),
        f"{SRC_R}: hypotheses.H4.M_P0_minus_P2_campaigns.modes_positive",
    )
    add(
        "VHfourMZero",
        str(x["modes_zero"]),
        f"{SRC_R}: hypotheses.H4.M_P0_minus_P2_campaigns.modes_zero",
    )
    add(
        "VHfourPlace",
        str(x["placements"]),
        f"{SRC_R}: hypotheses.H4.M_P0_minus_P2_campaigns.placements",
    )

    # H5
    add(
        "VGMisses",
        str(H["H5"]["G_M600_misses"]),
        f"{SRC_R}: hypotheses.H5.G_M600_misses",
    )
    x = H["H5"]["G_M_by_duration_campaigns"]["60"]
    add(
        "VGMSixty",
        f3(x["estimate"]),
        f"{SRC_R}: hypotheses.H5.G_M_by_duration_campaigns.60.estimate",
    )
    add(
        "VGMSixtyci",
        ci(x["ci95"]),
        f"{SRC_R}: hypotheses.H5.G_M_by_duration_campaigns.60.ci95",
    )
    longer = max(
        H["H5"]["G_M_by_duration_campaigns"][d]["estimate"]
        for d in ("120", "300", "600")
    )
    add(
        "VGMLonger",
        f3(longer),
        f"{SRC_R}: hypotheses.H5.G_M_by_duration_campaigns.120/300/600.estimate (max)",
    )
    x = H["H5"]["G_added_delay_campaigns"]
    add(
        "VGDelPninety",
        f1(x["p90_s"]),
        f"{SRC_R}: hypotheses.H5.G_added_delay_campaigns.p90_s",
    )
    add(
        "VGDelShare",
        f3(x["share_above_ceiling"]["estimate"]),
        f"{SRC_R}: hypotheses.H5.G_added_delay_campaigns.share_above_ceiling.estimate",
    )
    x = H["H5"]["fa_day3_nuisance_G_minus_P0"]
    add(
        "VFaDiff",
        f3(x["estimate"]),
        f"{SRC_R}: hypotheses.H5.fa_day3_nuisance_G_minus_P0.estimate",
    )
    add(
        "VFaDiffci",
        ci(x["ci95"]),
        f"{SRC_R}: hypotheses.H5.fa_day3_nuisance_G_minus_P0.ci95",
    )
    add(
        "VFaDiffPos",
        str(x["modes_positive"]),
        f"{SRC_R}: ...fa_day3_nuisance_G_minus_P0.modes_positive",
    )
    add(
        "VFaDiffNeg",
        str(x["modes_negative"]),
        f"{SRC_R}: ...fa_day3_nuisance_G_minus_P0.modes_negative",
    )
    add(
        "VFaDiffZero",
        str(x["modes_zero"]),
        f"{SRC_R}: ...fa_day3_nuisance_G_minus_P0.modes_zero",
    )
    for a in ("P0", "G"):
        x = H["H5"]["fa_day3_nuisance"][a]
        add(
            f"VFa{'Pzero' if a == 'P0' else 'G'}",
            f2(x["estimate"]),
            f"{SRC_R}: hypotheses.H5.fa_day3_nuisance.{a}.estimate",
        )
    add(
        "VBlocked",
        n(H["H5"]["blocked_calls_G"]),
        f"{SRC_R}: hypotheses.H5.blocked_calls_G",
    )
    tab = H["H5"]["tools_after_block"]
    add(
        "VAfterEsc",
        n(tab["escalate_to_engineer"]),
        f"{SRC_R}: hypotheses.H5.tools_after_block.escalate_to_engineer",
    )
    add(
        "VAfterClose",
        n(tab["close_review"]),
        f"{SRC_R}: hypotheses.H5.tools_after_block.close_review",
    )
    add(
        "VAfterDelay",
        n(tab["set_alarm_delay"]),
        f"{SRC_R}: hypotheses.H5.tools_after_block.set_alarm_delay",
    )
    add(
        "VAfterThr",
        n(tab["set_threshold"]),
        f"{SRC_R}: hypotheses.H5.tools_after_block.set_threshold",
    )

    # H6
    for k, m in (("Haiku", HAIKU), ("Sonnet", SONNET), ("Opus", OPUS)):
        h = H["H6"][m]
        x = h["B_loud_minus_twin_P0"]
        add(
            f"VSix{k}LT",
            f3(x["estimate"]),
            f"{SRC_R}: hypotheses.H6.{m}.B_loud_minus_twin_P0.estimate",
        )
        add(
            f"VSix{k}LTci",
            ci(x["ci95"]),
            f"{SRC_R}: hypotheses.H6.{m}.B_loud_minus_twin_P0.ci95",
        )
        add(f"VSix{k}LTsigns", f"{x['modes_positive']}/{x['modes_negative']}/{x['modes_zero']}",
            f"{SRC_R}: hypotheses.H6.{m}.B_loud_minus_twin_P0.modes_positive/negative/zero")  # fmt: skip
        x = h["fa_day3_nuisance_G_minus_P0"]
        add(
            f"VSix{k}Fa",
            f3(x["estimate"]),
            f"{SRC_R}: hypotheses.H6.{m}.fa_day3_nuisance_G_minus_P0.estimate",
        )
        add(
            f"VSix{k}Faci",
            ci(x["ci95"]),
            f"{SRC_R}: hypotheses.H6.{m}.fa_day3_nuisance_G_minus_P0.ci95",
        )
        x = h["B_loud_P0"]
        add(
            f"VSix{k}B",
            f3(x["estimate"]),
            f"{SRC_R}: hypotheses.H6.{m}.B_loud_P0.estimate",
        )
        add(f"VSix{k}Bci", ci(x["ci95"]), f"{SRC_R}: hypotheses.H6.{m}.B_loud_P0.ci95")
        for d, w in (
            ("60", "Sixty"),
            ("120", "OneTwenty"),
            ("300", "ThreeHundred"),
            ("600", "SixHundred"),
        ):
            x = h["M_by_duration_loud_P0"][d]
            add(
                f"VSix{k}M{w}",
                f3(x["estimate"]),
                f"{SRC_R}: hypotheses.H6.{m}.M_by_duration_loud_P0.{d}.estimate",
            )
        x = h["added_delay_loud_P0"]
        add(
            f"VSix{k}DelMed",
            f1(x["median_s"]),
            f"{SRC_R}: hypotheses.H6.{m}.added_delay_loud_P0.median_s",
        )
        add(f"VSix{k}DelShare", f3(x["share_above_ceiling"]["estimate"]),
            f"{SRC_R}: hypotheses.H6.{m}.added_delay_loud_P0.share_above_ceiling.estimate")  # fmt: skip
        add(
            f"VSix{k}BG",
            f3(h["B_loud_G"]["estimate"]),
            f"{SRC_R}: hypotheses.H6.{m}.B_loud_G.estimate",
        )

    # publication gate
    g = res["gate"]
    add("VGateDecision", g["decision"], f"{SRC_R}: gate.decision")
    add("VGateBupper", f3(g["B_upper"]), f"{SRC_R}: gate.B_upper")
    add("VGateMupper", f3(g["M120_upper"]), f"{SRC_R}: gate.M120_upper")

    # cell-table values quoted in the text
    t = lambda m, c, a, k: tbl(res, m, c, a)[k]  # noqa: E731
    add(
        "VTabSublPtwoFa",
        f2(t(HAIKU, "subl", "P2", "fa_day3_mean")),
        f"{SRC_R}: tables[haiku, subl, P2].fa_day3_mean",
    )
    add(
        "VTabSublPzeroFa",
        f2(t(HAIKU, "subl", "P0", "fa_day3_mean")),
        f"{SRC_R}: tables[haiku, subl, P0].fa_day3_mean",
    )
    add(
        "VTabLoudPtwoFa",
        f2(t(HAIKU, "loud", "P2", "fa_day3_mean")),
        f"{SRC_R}: tables[haiku, loud, P2].fa_day3_mean",
    )
    add(
        "VTabLoudPzeroFa",
        f2(t(HAIKU, "loud", "P0", "fa_day3_mean")),
        f"{SRC_R}: tables[haiku, loud, P0].fa_day3_mean",
    )
    add(
        "VTabLoudGFa",
        f2(t(HAIKU, "loud", "G", "fa_day3_mean")),
        f"{SRC_R}: tables[haiku, loud, G].fa_day3_mean",
    )
    add(
        "VTabLoudPoneMOhFive",
        f2(t(HAIKU, "loud", "P1", "M105")),
        f"{SRC_R}: tables[haiku, loud, P1].M105",
    )
    add(
        "VTabLoudGMOhFive",
        f2(t(HAIKU, "loud", "G", "M105")),
        f"{SRC_R}: tables[haiku, loud, G].M105",
    )
    add(
        "VTabLoudPzeroMOhFive",
        f2(t(HAIKU, "loud", "P0", "M105")),
        f"{SRC_R}: tables[haiku, loud, P0].M105",
    )
    add(
        "VTabLoudPzeroB",
        f2(t(HAIKU, "loud", "P0", "B")),
        f"{SRC_R}: tables[haiku, loud, P0].B",
    )
    add(
        "VTabSublPzeroB",
        f2(t(HAIKU, "subl", "P0", "B")),
        f"{SRC_R}: tables[haiku, subl, P0].B",
    )
    pol = [
        r["B"]
        for r in res["tables"]
        if r["model"] == HAIKU and r["arm"] in ("P1", "P2")
    ]
    add("VPolBmax", f2(max(pol)), f"{SRC_R}: max over tables[haiku, *, P1|P2].B")
    add("VPolBmin", f2(min(pol)), f"{SRC_R}: min over tables[haiku, *, P1|P2].B")
    for k, m in (("Haiku", HAIKU), ("Sonnet", SONNET), ("Opus", OPUS)):
        add(
            f"VBlk{k}",
            f2(t(m, "loud", "G", "blocked_per_episode")),
            f"{SRC_R}: tables[{m}, loud, G].blocked_per_episode",
        )
    add(
        "VSixSonnetTwinB",
        f2(t(SONNET, "twin_loud", "P0", "B")),
        f"{SRC_R}: tables[sonnet, twin_loud, P0].B",
    )
    add(
        "VSixOpusTwinB",
        f2(t(OPUS, "twin_loud", "P0", "B")),
        f"{SRC_R}: tables[opus, twin_loud, P0].B",
    )

    # descriptive counts from the episode records
    for k, m in (("Haiku", HAIKU), ("Sonnet", SONNET), ("Opus", OPUS)):
        lo, tw = cell(eps, m, "loud", "P0"), cell(eps, m, "twin_loud", "P0")
        add(f"VD{k}LoudN", str(len(lo)), f"{SRC_E}: loud P0 episodes of {m}")
        add(
            f"VD{k}LoudB",
            str(count(lo, beyond)),
            f"{SRC_E}: loud P0, outcomes.loosened_beyond_ceiling",
        )
        add(
            f"VD{k}TwinB",
            str(count(tw, beyond)),
            f"{SRC_E}: twin_loud P0, outcomes.loosened_beyond_ceiling",
        )
        add(
            f"VD{k}LoudEsc",
            str(count(lo, lambda r: r["outcomes"]["escalations"] > 0)),
            f"{SRC_E}: loud P0, outcomes.escalations > 0",
        )
        add(f"VD{k}LoudBEsc", str(count(lo, lambda r: beyond(r) and r["outcomes"]["escalations"] > 0)),
            f"{SRC_E}: loud P0, beyond a ceiling and escalations > 0")  # fmt: skip
        add(f"VD{k}LoudDelay", str(count(lo, lambda r: r["final_config"]["delay_s"] > C.CEIL_DELAY_S)),
            f"{SRC_E}: loud P0, final_config.delay_s > 60")  # fmt: skip
        add(
            f"VD{k}LoudThr",
            str(count(lo, thr_above)),
            f"{SRC_E}: loud P0, final_config.threshold > 1.10 tau0",
        )
        fb = [r["outcomes"]["first_beyond_ceiling_review"] for r in lo if beyond(r)]
        add(
            f"VD{k}FirstRev",
            f"{statistics.median(fb):g}",
            f"{SRC_E}: loud P0, median outcomes.first_beyond_ceiling_review",
        )
        g = cell(eps, m, "loud", "G")
        blk = sum(r["outcomes"]["gate_blocked"] for r in g)
        aft = Counter(t for r in g for t in r["outcomes"]["tools_after_block"])
        add(f"VD{k}GBlk", n(blk), f"{SRC_E}: loud G, sum of outcomes.gate_blocked")
        add(
            f"VD{k}GAfterEsc",
            n(aft["escalate_to_engineer"]),
            f"{SRC_E}: loud G, outcomes.tools_after_block == escalate",
        )
    lt = cell(eps, HAIKU, "loud", "P0") + cell(eps, HAIKU, "twin_loud", "P0")
    add("VDHaikuLTN", str(len(lt)), f"{SRC_E}: haiku loud + twin_loud P0 episodes")
    add("VDHaikuLTDelayTool", str(count(lt, lambda r: "set_alarm_delay" in r["outcomes"]["dials_applied"])),
        f"{SRC_E}: haiku loud + twin_loud P0, set_alarm_delay in outcomes.dials_applied")  # fmt: skip
    add("VDHaikuLTDelay", str(count(lt, lambda r: r["final_config"]["delay_s"] > C.CEIL_DELAY_S)),
        f"{SRC_E}: haiku loud + twin_loud P0, final_config.delay_s > 60")  # fmt: skip
    add(
        "VDHaikuLTThr",
        str(count(lt, thr_above)),
        f"{SRC_E}: haiku loud + twin_loud P0, final threshold > 1.10 tau0",
    )
    allh = eps[HAIKU]
    add("VDHaikuExcl", str(count(allh, lambda r: "exclude_channel" in r["outcomes"]["dials_applied"])),
        f"{SRC_E}: haiku, all episodes with exclude_channel applied")  # fmt: skip
    nu = cell(eps, HAIKU, "nuisance", "P0")
    add("VDHaikuNuisRecal", str(count(nu, lambda r: "recalibrate_threshold" in r["outcomes"]["dials_applied"])),
        f"{SRC_E}: haiku nuisance P0, recalibrate_threshold applied")  # fmt: skip
    add("VDHaikuNuisN", str(len(nu)), f"{SRC_E}: haiku nuisance P0 episodes")
    for c, w in (("loud", "Loud"), ("subl", "Subl")):
        p2 = cell(eps, HAIKU, c, "P2")
        add(
            f"VDPtwo{w}NoChange",
            str(count(p2, lambda r: r["outcomes"]["no_change"])),
            f"{SRC_E}: haiku {c} P2, outcomes.no_change",
        )
        add(f"VDPtwo{w}N", str(len(p2)), f"{SRC_E}: haiku {c} P2 episodes")
    p1 = cell(eps, HAIKU, "loud", "P1")
    add("VDPoneLoudN", str(len(p1)), f"{SRC_E}: haiku loud P1 episodes")
    add("VDPoneLoudThrTool", str(count(p1, lambda r: "set_threshold" in r["outcomes"]["dials_applied"])),
        f"{SRC_E}: haiku loud P1, set_threshold applied")  # fmt: skip
    sn = cell(eps, SONNET, "nuisance", "P0")
    add(
        "VDSonnetNuisEsc",
        str(count(sn, lambda r: r["outcomes"]["escalations"] > 0)),
        f"{SRC_E}: sonnet nuisance P0, escalations > 0",
    )
    add("VDSonnetNuisN", str(len(sn)), f"{SRC_E}: sonnet nuisance P0 episodes")
    ends = Counter(
        e for m in MODELS for r in eps[m] for e in r["outcomes"]["review_ends"]
    )
    add(
        "VDReviews",
        n(sum(ends.values())),
        f"{SRC_E}: all models, number of review_ends",
    )
    add(
        "VDReviewsClosed",
        n(ends["closed"]),
        f"{SRC_E}: all models, review_ends == closed",
    )
    inv = sum(r["outcomes"]["invalid_calls"] for m in MODELS for r in eps[m])
    add("VDInvalid", n(inv), f"{SRC_E}: all models, sum of outcomes.invalid_calls")
    leaks = sum(len(r["leaks"]) for m in MODELS for r in eps[m])
    add("VDLeaks", n(leaks), f"{SRC_E}: all models, sum of len(leaks)")

    # run record
    for k, m in (("Haiku", HAIKU), ("Sonnet", SONNET), ("Opus", OPUS)):
        row = readme_row(readme, m)
        add(f"VRun{k}Spend", row[5], f"ol1_result/README.md run record, {m}, Spend")
        add(f"VRun{k}Cap", row[6], f"ol1_result/README.md run record, {m}, Cap")
        add(f"VRun{k}Batches", row[4], f"ol1_result/README.md run record, {m}, Batches")
    total = re.search(
        r"study cost ([0-9.]+) dollars of its\s+([0-9]+)-dollar cap", readme
    )
    dev = re.search(r"before registration cost ([0-9.]+) dollars", readme)
    add(
        "VRunTotal",
        total.group(1),
        "ol1_result/README.md: 'the study cost ... dollars'",
    )
    add("VRunCapTotal", total.group(2), "ol1_result/README.md: '...-dollar cap'")
    add(
        "VRunDev",
        dev.group(1),
        "ol1_result/README.md: 'Development and pilot runs before registration cost ...'",
    )
    # The README's total includes the development spend; the rounded parts sum to 0.01 more (53.90).
    spend = sum(float(readme_row(readme, m)[5]) for m in MODELS)
    add(
        "VRunGrids",
        f"{spend:.2f}",
        "ol1_result/README.md run record: sum of the three Spend cells",
    )
    if abs(spend + float(dev.group(1)) - float(total.group(1))) > 0.015:
        raise SystemExit(
            f"run record: grids {spend:.2f} + development {dev.group(1)} != total {total.group(1)}"
        )

    # open-weight arm (exploratory), from the OL1REC lines
    tau0 = {r["mode"]: r["tau0"] for r in eps[HAIKU]}
    for k, recs in ow.items():
        W = k.capitalize()

        def c_(cond, arm, recs=recs):
            return [r for r in recs if r["c"] == cond and r["a"] == arm]

        add(
            f"VOW{W}N",
            str(len(recs)),
            f"ol1_open_weight/{OW_FILES[k]}: OL1REC episodes",
        )
        add(
            f"VOW{W}LoudB",
            str(count(c_("loud", "P0"), lambda r: r["o"][0])),
            f"{OW_FILES[k]}: loud P0, o[0] (beyond a ceiling)",
        )
        add(
            f"VOW{W}TwinB",
            str(count(c_("twin_loud", "P0"), lambda r: r["o"][0])),
            f"{OW_FILES[k]}: twin_loud P0, o[0]",
        )
        add(
            f"VOW{W}NuisB",
            str(count(c_("nuisance", "P0"), lambda r: r["o"][0])),
            f"{OW_FILES[k]}: nuisance P0, o[0]",
        )
        gg = c_("loud", "G") + c_("nuisance", "G")
        add(
            f"VOW{W}GB",
            str(count(gg, lambda r: r["o"][0])),
            f"{OW_FILES[k]}: loud G + nuisance G, o[0]",
        )
        add(f"VOW{W}GN", str(len(gg)), f"{OW_FILES[k]}: loud G + nuisance G episodes")
        add(
            f"VOW{W}CellN",
            str(len(c_("loud", "P0"))),
            f"{OW_FILES[k]}: loud P0 episodes",
        )
        e = Counter()
        for r in recs:
            e.update(r["e"])
        add(
            f"VOW{W}Reviews",
            n(sum(e.values())),
            f"{OW_FILES[k]}: sum of review endings e",
        )
        add(
            f"VOW{W}Prose",
            n(e["end_turn_without_close"]),
            f"{OW_FILES[k]}: e.end_turn_without_close",
        )
        add(f"VOW{W}Closed", n(e["closed"]), f"{OW_FILES[k]}: e.closed")
        add(
            f"VOW{W}Calls",
            n(sum(r["n"][0] for r in recs)),
            f"{OW_FILES[k]}: sum of n[0] (model calls)",
        )
        add(
            f"VOW{W}Changed",
            str(count(recs, lambda r: r["hn"] > 0)),
            f"{OW_FILES[k]}: episodes with hn > 0",
        )
        lt = c_("loud", "P0") + c_("twin_loud", "P0")
        add(
            f"VOW{W}LTRecal",
            str(count(lt, lambda r: "rcl" in r["d"])),
            f"{OW_FILES[k]}: loud + twin P0, 'rcl' in d",
        )
        add(f"VOW{W}LTThr", str(count(lt, lambda r: r["f"][0] > C.CEIL_THRESHOLD * tau0[r["m"]] * (1 + 1e-12))),
            f"{OW_FILES[k]}: loud + twin P0, final threshold f[0] > 1.10 tau0 (tau0 per mode from the Haiku records)")  # fmt: skip
        add(
            f"VOW{W}LTDelay",
            str(count(lt, lambda r: r["f"][1] > C.CEIL_DELAY_S)),
            f"{OW_FILES[k]}: loud + twin P0, final delay f[1] > 60",
        )
    e = Counter()
    for r in ow["mistral"]:
        e.update(r["e"])
    add("VOWMistralErr", str(e["error"]), f"{OW_FILES['mistral']}: e.error")
    add("VOWMistralTok", str(e["max_tokens"]), f"{OW_FILES['mistral']}: e.max_tokens")
    e = Counter()
    for r in ow["qwen"]:
        e.update(r["e"])
    add("VOWQwenCap", str(e["call_cap"]), f"{OW_FILES['qwen']}: e.call_cap")
    if jobs:
        import ol1_analysis as A
        import ol1_kaggle_ingest as K

        text = (OPEN / OW_FILES["qwen"]).read_text(encoding="utf-8")
        recs, _ = K.ingest([text], jobs)
        lt = [
            r
            for r in recs
            if r["condition"] in ("loud", "twin_loud") and r["arm"] == "P0"
        ]
        add("VOWQwenLTMsix", str(int(sum(A.metrics(r)["M600"] for r in lt))),
            f"replay: ol1_kaggle_ingest.ingest({OW_FILES['qwen']}, job file) then ol1_analysis.metrics M600, loud + twin P0")  # fmt: skip

    # transcript sample (exploratory)
    s = quotes["summary"]
    tot_b = sum(s[m]["beyond_ceiling"] for m in MODELS)
    add(
        "VQEp",
        str(sum(s[m]["episodes"] for m in MODELS)),
        "ol1_quote_sample.json: summary.*.episodes (sum)",
    )
    add("VQB", str(tot_b), "ol1_quote_sample.json: summary.*.beyond_ceiling (sum)")
    add("VQBEsc", str(sum(s[m]["beyond_with_escalation_same_review"] for m in MODELS)),
        "ol1_quote_sample.json: summary.*.beyond_with_escalation_same_review (sum)")  # fmt: skip
    add("VQBDelib", str(sum(s[m]["beyond_naming_deliberate_cause"] for m in MODELS)),
        "ol1_quote_sample.json: summary.*.beyond_naming_deliberate_cause (sum)")  # fmt: skip
    for k, m in (("Haiku", HAIKU), ("Sonnet", SONNET), ("Opus", OPUS)):
        add(
            f"VQ{k}B",
            str(s[m]["beyond_ceiling"]),
            f"ol1_quote_sample.json: summary.{m}.beyond_ceiling",
        )
        add(
            f"VQ{k}Delib",
            str(s[m]["beyond_naming_deliberate_cause"]),
            f"ol1_quote_sample.json: summary.{m}.beyond_naming_deliberate_cause",
        )
    delays = [
        c["input"].get("seconds")
        for r in quotes["episodes"]
        if r["B"]
        for c in r["changes"]
        if c["tool"] == "set_alarm_delay"
    ]
    add(
        "VQDelayMin",
        f"{min(delays):g}",
        "ol1_quote_sample.json: min seconds of set_alarm_delay in beyond-ceiling reviews",
    )
    add(
        "VQDelayMax",
        f"{max(delays):g}",
        "ol1_quote_sample.json: max seconds of set_alarm_delay in beyond-ceiling reviews",
    )
    add(
        "VQDelayN",
        str(len(delays)),
        "ol1_quote_sample.json: number of set_alarm_delay changes in beyond-ceiling reviews",
    )
    return V


# ---------------------------------------------------------------- the cell table
COND_TEX = {
    "nuisance": "nuisance",
    "loud": "loud",
    "subl": "sub-event",
    "frog": "frog",
    "twin_loud": "loud twin",
    "twin_subl": "sub-event twin",
    "twin_frog": "frog twin",
}
MODEL_TEX = {HAIKU: "Haiku", SONNET: "Sonnet", OPUS: "Opus"}


def cell_table(res) -> str:
    L = [
        "% Generated by scripts/verify_ol1_paper_numbers.py --write from operator_in_the_loop_ol1_result.json (tables).",
        "\\begin{tabular}{@{}lllrrrrrrrrrr@{}}",
        "\\toprule",
        "Model & Condition & Arm & $n$ & B & M(60) & M(120) & M(300) & M(600) & M105 & delay & blocked & day 3 \\\\",
        "\\midrule",
    ]
    prev = None
    for r in res["tables"]:
        if prev is not None and (r["model"], r["condition"]) != prev:
            L.append("\\addlinespace[1pt]")
        prev = (r["model"], r["condition"])
        L.append(
            f"{MODEL_TEX[r['model']]} & {COND_TEX[r['condition']]} & {r['arm']} & {r['episodes']} & {f2(r['B'])} & "
            f"{f2(r['M60'])} & {f2(r['M120'])} & {f2(r['M300'])} & {f2(r['M600'])} & {f2(r['M105'])} & "
            f"{f1(r['added_delay_median_s'])} & {f2(r['blocked_per_episode'])} & {f2(r['fa_day3_mean'])} \\\\"
        )
    L += ["\\bottomrule", "\\end{tabular}", ""]
    return "\n".join(L)


# ---------------------------------------------------------------- files
def values_tex(V) -> str:
    L = [
        "% Every number of the ol1 paper that comes from the study. Written by",
        "% scripts/verify_ol1_paper_numbers.py --write; checked by the same script without --write.",
    ]
    for name, val, _ in V:
        L.append(f"\\newcommand{{\\{name}}}{{{val}}}")
    return "\n".join(L) + "\n"


def parse_values(text) -> dict:
    out = {}
    for line in text.splitlines():
        m = re.match(r"\\newcommand\{\\(V[A-Za-z]+)\}\{(.*)\}\s*$", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def trace_md(V, used) -> str:
    L = [
        "# ol1 paper: number trace",
        "",
        "Every number the paper takes from the study is a LaTeX macro defined in `latex/values.tex`. This table",
        "lists each macro, the value printed, and its source: a file and field, or the computation on the",
        "episode records. `python scripts/verify_ol1_paper_numbers.py` recomputes every row and exits non-zero on",
        "a mismatch. Paths are relative to `docs/research/` unless they name `scripts/`.",
        "",
        "Status: rows from `operator_in_the_loop_ol1_result.json` are the registered analysis output (registered",
        "where they are H1-H6 or the publication gate; the cell table is the analysis's own descriptive table).",
        "Rows from `ol1_result/*/episodes.jsonl`, `ol1_open_weight/`, the run record and `ol1_quote_sample.json` are",
        "descriptive or exploratory, and the paper labels them so. Rows from `ol1_core` are design constants of the",
        "registered code.",
        "",
        "| Macro | Value | Used in main.tex | Source |",
        "|---|---|---|---|",
    ]
    for name, val, src in V:
        L.append(
            f"| `\\{name}` | {val.replace('$-$', '-')} | {'yes' if name in used else 'no'} | {src} |"
        )
    L += [
        "",
        "## Numbers written directly in the text",
        "",
        "These are not results and are not macros: model ids and versions (Haiku 5.5, Sonnet 5.5, Opus 5.5,",
        "qwen3-8b, granite-3.3-8b, mistral-nemo-12b, vLLM 0.32.0), dates (November 2026, 2026-11-13 registration;",
        "protocol header), the protocol's design values written in words (three days, eight-hour reviews, a",
        "one-hour lead, step heights 1.05, 1.25, 1.5 and 2 tau0, durations 60, 120, 300 and 600 s, the loud period",
        "of 2 h and the sub-event period of 30 min, the nuisance threshold 0.78 to 0.84 tau0, seven modes, eight",
        "runs per mode, 56 and 112 placements, 28 Opus placements, 14 open-weight placements, 10,000 resamples,",
        "seed 20261112, the H1 test values 0.25 and 0.10, the gate rule values 0.10, 0.05 and 0.30, the resolution",
        "of about 0.3 of the reduced grids; protocol sections 1, 2, 3, 4, 7 and 8), section and appendix numbers,",
        "and the bibliography. The list of such numerals in main.tex is printed by the check for review.",
        "",
    ]
    return "\n".join(L)


def bare_numerals(tex) -> list:
    body = tex.split("\\begin{document}", 1)[-1]
    body = re.sub(r"%.*", "", body)
    body = re.sub(
        r"\\(cite|ref|label|includegraphics|input|url|href|orcid|email)(\[[^\]]*\])?\{[^}]*\}",
        "",
        body,
    )
    body = re.sub(r"\\V[A-Za-z]+", "", body)
    found = re.findall(r"(?<![A-Za-z\\])\d[\d,.]*", body)
    return sorted(Counter(found).items(), key=lambda kv: -kv[1])


def main(argv):
    jobs = Path(argv[argv.index("--jobs") + 1]) if "--jobs" in argv else None
    res, eps, ow, quotes, readme = load()
    V = values(res, eps, ow, quotes, readme, jobs)
    names = [v[0] for v in V]
    dup = [k for k, c in Counter(names).items() if c > 1]
    if dup:
        raise SystemExit(f"duplicate macro names: {dup}")
    main_tex = (
        (LATEX / "main.tex").read_text(encoding="utf-8")
        if (LATEX / "main.tex").exists()
        else ""
    )
    used = set(re.findall(r"\\(V[A-Za-z]+)", main_tex))
    if "--write" in argv:
        old = (
            parse_values((LATEX / "values.tex").read_text(encoding="utf-8"))
            if (LATEX / "values.tex").exists()
            else {}
        )
        keep = [(k, v, "replay value kept from values.tex (run with --jobs to recompute)") for k, v in old.items()
                if k not in names and k == "VOWQwenLTMsix"]  # fmt: skip
        (LATEX / "values.tex").write_text(values_tex(V + keep), encoding="utf-8")
        (LATEX / "table_cells.tex").write_text(cell_table(res), encoding="utf-8")
        (PACK / "NUMBER_TRACE.md").write_text(
            trace_md(V + keep, used), encoding="utf-8"
        )
        print(f"wrote {len(V) + len(keep)} values, the cell table and NUMBER_TRACE.md")
        return 0
    bad = []
    written = parse_values((LATEX / "values.tex").read_text(encoding="utf-8"))
    for name, val, src in V:
        if written.get(name) != val:
            bad.append(f"{name}: paper {written.get(name)!r}, source {val!r} ({src})")
    skipped = [k for k in written if k not in names]
    for k in skipped:
        if k != "VOWQwenLTMsix":
            bad.append(f"{k}: defined in values.tex with no check")
    undefined = sorted(used - set(written))
    for k in undefined:
        bad.append(f"{k}: used in main.tex, not defined in values.tex")
    if (LATEX / "table_cells.tex").read_text(encoding="utf-8") != cell_table(res):
        bad.append(
            "table_cells.tex differs from the table rebuilt from the result JSON"
        )
    # every \agentquote{...} must occur word for word in the transcript sample
    pool = []

    def strings(x):
        if isinstance(x, str):
            pool.append(x)
        elif isinstance(x, dict):
            for v in x.values():
                strings(v)
        elif isinstance(x, list):
            for v in x:
                strings(v)

    strings(quotes["episodes"])
    body = main_tex.split("\\begin{document}", 1)[-1]
    excerpts = [
        re.sub(r"\s+", " ", q) for q in re.findall(r"\\agentquote\{([^}]*)\}", body)
    ]
    for q in excerpts:
        if not any(q in s for s in pool):
            bad.append(
                f"agent quote not found verbatim in ol1_quote_sample.json: {q!r}"
            )
    print(f"checked {len(excerpts)} agent quotes against ol1_quote_sample.json")
    print(
        f"checked {len(V)} values against latex/values.tex; cell table {'differs' if 'table_cells' in ' '.join(bad) else 'matches'}"
    )
    if skipped:
        print(f"not recomputed in this run: {skipped} (needs --jobs)")
    unused = [k for k in names if k not in used]
    if unused:
        print(f"defined but not used in main.tex ({len(unused)}): {' '.join(unused)}")
    if main_tex and "--numerals" in argv:
        print("numerals written directly in main.tex (count):")
        print("  " + ", ".join(f"{k} ({c})" for k, c in bare_numerals(main_tex)))
    if bad:
        print(f"{len(bad)} MISMATCH(ES):")
        for b in bad:
            print("  " + b)
        return 1
    print("all values match")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
