"""Corrections to tt1d_final.py (a frozen file; fi1 pipeline audit, docs/research/fi1_reports/pipeline_round1.md).

play() counts the campaign's own alarm episodes with `i - last > gap`, so two alarm runs separated by exactly
`gap` quiet steps count as two episodes. Every other episode count of the study (threshold_rules._episodes,
DailyExcl, tracker_hold after the first audit, the false-alarm counts) merges runs separated by up to `gap`
quiet steps (`i - last > gap + 1` starts a new episode). The error touches only the campaign diagnostics
alarm_episodes and longest_episode (median_alarm_episodes and longest_alarm_episode in the result tables);
the terminal detections, inflation, alarm steps and every gate are unaffected.

play_v2() is play() with the corrected merge; placement_v2() uses it. Nothing else is overridden.
"""

from __future__ import annotations

import copy

import numpy as np

import tt1d_final as M


def play_v2(S, rule, cfg, calib, s, end, mode):
    """tt1d_final.play with episodes merged across up to S.gap quiet steps."""
    m = S.rules.make(rule, cfg, calib)
    c_start, c_end = end - S.lead - S.campaign, end - S.lead
    tau0 = cfg["tau0"]
    alarms, episodes, longest, first, last = 0, 0, 0, None, None
    for i in range(end):
        tau = m.tau()
        x = s[i]
        if mode != "control" and c_start <= i < c_end and x != -np.inf:
            k = i - c_start
            if mode == "frog":
                x = max(x, M.FROG_FRAC * tau)
            elif mode == "loud":
                if k % S.loud[0] < S.loud[1]:
                    x = max(x, S.loud[2] * tau0)
            elif k % S.subl[0] < S.subl[1]:
                x = max(x, S.subl[2] * tau)
            if x > tau:
                alarms += 1
                if last is None or i - last > S.gap + 1:
                    episodes += 1
                    first = i
                last = i
                longest = max(longest, i - first + 1)
        m.update(x)
    tau_end = m.tau()
    hits = {}
    for mag in M.MAGS:
        mm, hit = copy.deepcopy(m), False
        bump = mag * tau0
        for i in range(end, end + S.terminal):
            x = max(s[i], bump)
            hit |= bool(x > mm.tau())
            mm.update(x)
        hits[mag] = hit
    return hits, float(tau_end / tau0), alarms, episodes, longest


def placement_v2(S, s, cfg, calib, c0):
    end = c0 + S.campaign + S.lead
    out = {"campaign_start": int(c0), "terminal_start": int(end)}
    rules = dict.fromkeys(sum(M.CAMPAIGNS.values(), []))
    control = {r: play_v2(S, r, cfg, calib, s, end, "control")[0] for r in rules}
    for attack, names in M.CAMPAIGNS.items():
        out[attack] = {}
        for r in names:
            hits, infl, alarms, episodes, longest = play_v2(
                S, r, cfg, calib, s, end, attack
            )
            out[attack][r] = {
                "after": [bool(hits[m]) for m in M.MAGS],
                "control": [bool(control[r][m]) for m in M.MAGS],
                "inflation": infl,
                "alarm_steps": alarms,
                "alarm_episodes": episodes,
                "longest_episode": longest,
            }
    return out
