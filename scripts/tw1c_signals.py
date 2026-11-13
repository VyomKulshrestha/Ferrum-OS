"""tw1c (exploratory): the monitored signal and the campaigns of the signal-level round.

The metric fed to every product is the D1 monitor score of the spent Tennessee Eastman runs, read from the
tt1f score cache (`mode_<m>.npz`). No dataset is opened. One placement per mode: the first registered
sealed run of the mode, at its registered terminal start. Plan:
docs/research/thresholds_in_the_wild_tw1c_signal_plan.md.

The products expose no reading of their own threshold, so the campaigns are the open-loop translations
of the tw1a campaigns with the frozen threshold tau0 as the reference:

    control     the score as recorded
    frog        a floor that rises linearly from the median of the history to 0.97 tau0 over the campaign
    frog_hold   a floor held at 0.97 tau0 for the whole campaign (tw1a's frog against a static reading)
    loud        33 steps at 2 tau0 every 2,000 steps
    subl        12 steps at 2 tau0 every 500 steps

The injected value is max(score, floor). A terminal step max(score, mag * tau0) of `terminal` steps follows
directly after the campaign (lead 0) or after the registered lead of 1,000 steps. Magnitude "none" adds no
terminal step and measures what the product does without one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

CAMPAIGNS = ("control", "frog", "frog_hold", "loud", "subl")
MAGS = (1.05, 1.25, 1.5, 2.0)
LEADS = (0, 1000)
REG_LEAD = 1000  # the registered lead of tt1d
TERMINAL = 167
FROG_FRAC = 0.97
LOUD = (2000, 33, 2.0)
SUBL = (500, 12, 2.0)


@dataclass
class Placement:
    mode: int
    run: str
    tau0: float
    stream: (
        np.ndarray
    )  # calibration scores then the sealed run, non-finite steps dropped
    end: int  # registered terminal start, in stream coordinates
    dropped: int  # non-finite steps dropped from the sealed run
    meta: dict = field(default_factory=dict)


def load_placement(cache: Path, setup: dict, mode: int, which: int = 0) -> Placement:
    """The calibration scores followed by the mode's `which`-th sealed run; the terminal start is moved by
    the number of dropped non-finite steps that precede it."""
    m = setup["modes"][str(mode)]
    run = m["sealed"][which]
    z = np.load(cache / f"mode_{mode}.npz")
    pooled, sealed = (
        z["pooled"].astype(float),
        z["sealed::" + run["name"]].astype(float),
    )
    ok = np.isfinite(sealed)
    if not np.isfinite(pooled).all():
        raise ValueError("calibration scores hold non-finite values")
    dropped_before = int((~ok[: run["terminal_start"]]).sum())
    stream = np.concatenate([pooled, sealed[ok]])
    end = len(pooled) + run["terminal_start"] - dropped_before
    return Placement(mode, run["name"], float(m["tau0"]), stream, end, int((~ok).sum()))


def windows(end: int, campaign: int, history: int, tail: int):
    """Start of the series, start and end of the campaign, stop of the series (stream coordinates). The
    campaign ends the registered lead before the registered terminal start, as in tt1d."""
    c_end = end - REG_LEAD
    c_start = c_end - campaign
    return c_start - history, c_start, c_end, end + max(TERMINAL, 0) + tail


def floor(kind: str, campaign: int, tau0: float, base: float) -> np.ndarray:
    """The attacker's floor over the campaign; NaN where the attacker injects nothing."""
    k = np.arange(campaign)
    f = np.full(campaign, np.nan)
    if kind == "frog":
        f = base + (FROG_FRAC * tau0 - base) * k / max(campaign - 1, 1)
    elif kind == "frog_hold":
        f[:] = FROG_FRAC * tau0
    elif kind == "loud":
        f[k % LOUD[0] < LOUD[1]] = LOUD[2] * tau0
    elif kind == "subl":
        f[k % SUBL[0] < SUBL[1]] = SUBL[2] * tau0
    elif kind != "control":
        raise ValueError(kind)
    return f


def build(
    p: Placement,
    campaign: int = 24000,
    history: int = 24000,
    tail: int = 200,
    terminal: int = TERMINAL,
    campaigns=CAMPAIGNS,
    mags=MAGS,
    leads=LEADS,
):
    """All series of one placement as rows of one matrix, with a description of each row.

    Every row has the same length. Row coordinates: the campaign is [history, history + campaign); a
    terminal step at lead L covers [history + campaign + L, history + campaign + L + terminal)."""
    s0, c_start, c_end, stop = windows(p.end, campaign, history, tail)
    stop = max(stop, c_end + max(leads) + terminal + tail)
    if s0 < 0 or stop > len(p.stream):
        raise ValueError(f"placement {p.mode} does not fit: {s0}..{stop}")
    clean = p.stream[s0:stop].copy()
    base = float(np.median(clean[:history]))
    rows, info = [], []
    for kind in campaigns:
        f = floor(kind, campaign, p.tau0, base)
        attacked = clean.copy()
        seg = attacked[history : history + campaign]
        hit = np.isfinite(f) & (f > seg)
        seg[hit] = f[hit]
        for mag in (None, *mags):
            for lead in leads if mag is not None else (None,):
                x = attacked.copy()
                t0 = None
                if mag is not None:
                    t0 = history + campaign + lead
                    x[t0 : t0 + terminal] = np.maximum(
                        x[t0 : t0 + terminal], mag * p.tau0
                    )
                rows.append(x)
                info.append(
                    {
                        "mode": p.mode,
                        "campaign": kind,
                        "mag": mag,
                        "lead": lead,
                        "terminal_len": terminal if mag is not None else 0,
                        "terminal_start": t0,
                        "campaign_start": history,
                        "campaign_end": history + campaign,
                        "injected_steps": int(hit.sum()),
                    }
                )
    for i, r in enumerate(info):
        r["name"] = series_name(r)
        r["row"] = i
    return (
        np.vstack(rows),
        info,
        {
            "mode": p.mode,
            "run": p.run,
            "tau0": p.tau0,
            "history": history,
            "campaign": campaign,
            "terminal": terminal,
            "steps": int(stop - s0),
            "stream_start": int(s0),
            "history_median": base,
            "sealed_non_finite_dropped": p.dropped,
        },
    )


def series_name(r: dict) -> str:
    mag = "none" if r["mag"] is None else f"m{int(round(r['mag'] * 100)):03d}"
    lead = "" if r["lead"] is None else f"_l{r['lead']}"
    length = "" if r["terminal_len"] in (0, TERMINAL) else f"_t{r['terminal_len']}"
    return f"p{r['mode']}_{r['campaign']}_{mag}{lead}{length}"


def load_setup(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
