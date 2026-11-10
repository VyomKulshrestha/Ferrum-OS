# Next research directions after "Thresholds That Travel"

Written 2026-11-10. Basis: a literature triage of three candidate directions run the same day (web
search only; its citations are listed at the end and must be re-verified before any of them is cited in a
paper), plus two source-code probes I read myself. Status of every claim is marked.

## Recommendation

**Paper 2: audit the adaptive thresholds that people already run.** Replay recorded attacks and the tt1
attack library (loud pulses, the closed-loop frog, sub-event pulses) through shipped, open-source anomaly
detectors at their default settings, and report whether each one absorbs attacks: recall by attack order,
threshold trajectory, and what an attacker must spend to blind it. Working title: *Thresholds in the Wild*.

Why this one:

- **It answers the strongest objection to paper 1.** Paper 1 tests rules we implemented. A reviewer can
  say real products are smarter. An audit tests the products.
- **The gap looks open.** The triage found no paper that tests shipped implementations for absorption of
  attacks into the threshold (status: a few searches, not exhaustive).
- **Two probes already point the same way** (status: read by me on 2026-11-10, main branches):
  - `river` (Python online-learning library), `river/anomaly/filter.py`: `QuantileFilter.learn_one`
    calls `self.quantile.update(score)` for every sample, including samples it classifies as anomalous.
    Its `protect_anomaly_detector=True` default protects only the wrapped detector, not the threshold.
    That is the symmetric quantile tracker of paper 1 with a model-protection switch that does not cover it.
  - AWS `random-cut-forest-by-aws`, `BasicThresholder.java` (the thresholder behind OpenSearch Anomaly
    Detection): the running mean and deviation that set the threshold are updated with every score passed
    in; the file has no exclusion of flagged points (scores are only clamped at 2.0). Whether the caller
    withholds flagged points is not yet read.
- **It reuses what exists.** The harness, the registration discipline, the access ledger, the attack
  library and seven opened datasets carry over. Deliberate attacks need no fresh attack data; only a
  registered natural-poisoning test does.
- **It fits one laptop.** Libraries run in-process; OpenSearch runs in Docker in 2 to 4 GB.

### Candidate targets (to be confirmed by reading each one's default code path)

| Target | Adaptive part | Licence | Notes |
|---|---|---|---|
| river `QuantileFilter` / `ThresholdFilter` | running quantile of scores | BSD-3 | probe done |
| OpenSearch Anomaly Detection (RCF + thresholder) | decayed mean / deviation of scores | Apache-2.0 | thresholder read; caller not yet |
| Numenta anomaly likelihood (NAB) | rolling Gaussian tail of scores | AGPL / MIT ports | by design suppresses repeats |
| Telemanom dynamic threshold | trailing-window error statistics | Apache-2.0 | already implemented in tt1c |
| SPOT / DSPOT reference code | streaming extreme-value tail | GPL-3 | compare with our implementations |
| Netdata ML | models retrained on recent data | GPL-3 | model, not threshold, adapts |
| Zabbix baseline and anomaly triggers | seasonal baselines | AGPL | configuration-driven |
| Elastic ML | score renormalization | Elastic licence | check benchmark and publication terms first |

### Design sketch (pre-registered, as in tt1)

1. **Catalogue** (no data): for each target, read the default code path and record its learning region
   in the paper-1 vocabulary: what it learns from, whether it learns from its own alarms, its memory.
2. **Deliberate attacks** on attack-free data (development: the spent HAI normal data; registered: the
   reserve of never-opened Tennessee Eastman attack-free runs, see below): loud pulses, frog, sub-event
   pulses, with terminal steps of several sizes. Outcome: fraction of terminal steps caught after the
   campaign against a control, per target.
3. **Natural poisoning** on recorded attacks: per-target recall against the same target with its
   threshold frozen at calibration, by attack order within a stream. Registered on data no analysis has
   opened (SWaT / WADI if iTrust grants access; ProvICS if its terms are accepted; LANL as a cross-domain
   test, see risks).
4. **Disclosure.** Findings about a named project go to its maintainers before publication.

### Data position after tt1d

- Never opened: 53 attack-free Tennessee Eastman runs of 120 h. The Kaspersky dataset has 200; tt1d
  gives 147 a role (91 development, 56 sealed for its final) and does not read the other 53. They are a
  reserve for registered campaign tests in paper 2.
- Requested, not granted: SWaT, WADI (iTrust).
- Needs the author's agreement to terms: ProvICS (CC BY-NC, no redistribution, name and affiliation
  form), LANL 2015 (email and intended-use form, then CC0).

## The other candidates

**Robust loosening with a "price of poisoning" (defense).** A threshold may rise only with a quorum:
the median of the last k daily quantiles, agreement of two independent scores, a hard ceiling. Goal: a
proved minimum number of days or alarms an attacker must spend, plus the measured false-alarm benefit.
Triage rating: partly done. The guarantee is close to textbook breakdown-point arguments and to three
existing results (Atarmla 2026; Wang and Feizi, NeurIPS 2023, temporal aggregation; Kloft and Laskov
2012), so it does not carry a paper alone. Best use: the defense half of paper 2, scored on the same
targets ("here is the patch, and what it costs"). The ceiling rule tested in tt1e is its first piece.

**The same effect in enterprise monitoring (UEBA / NDR baselines).** Triage rating: open as a
measurement; the mechanism is known. Tuor et al. 2018 retrain through the LANL red-team period and report
only aggregate AUC. Main risk is statistical power: LANL's 749 red-team events reportedly originate from
four source hosts, so a pre-registered per-host test could be an n = 4 result. Use LANL as a secondary
natural-poisoning test inside paper 2 after counting, from `redteam.txt` alone, how many events each
baseline scope sees per day.

**LLM agents as the alarm operator.** Paper 1 says loosening needs a human; triage is being handed to
LLM agents. Triage rating: partly done. Prompt injection through log content is covered by two 2026
papers; the open part is a truthful nuisance campaign (no injected text) that talks an agent into
approving a loosening. Risks: results age with model versions, paid APIs carry the study, and a
deterministic gate "works by construction", which reads as no finding. Fit: a short workshop paper that
reuses the tt1 alarm streams, and the natural bridge to FerrumOS's authority gate.

## Order of work

1. Finish the paper-1 revision and submit to ASIA CCS (11 December 2026).
2. Catalogue step of paper 2 (two weeks, no data access): read the default code path of each target.
   Decide go / no-go on the audit from how many targets learn from their own alarms.
3. Development runs on the spent HAI data; then register and run the campaign tests on the reserve
   Tennessee Eastman runs.
4. Venue: RAID or ACSAC 2027 are realistic (2026 deadlines were mid-April and late May; 2027 dates not
   yet published). USENIX Security 2027 cycle 2 (26 January 2027) is too close.

## What would change this recommendation

- If the catalogue shows that most shipped detectors already withhold flagged points from the threshold
  update, the audit shrinks to a short negative result and the defense paper moves up.
- If iTrust grants SWaT / WADI, the registered natural-poisoning test in paper 2 becomes much stronger.

## Sources from the triage (re-verify before citing)

Atarmla 2026, arXiv:2609.23254; Wang and Feizi, NeurIPS 2023, arXiv:2302.03684; Wang, Zecchin and Simeone
2026, arXiv:2605.20515; Bashari, Sesia and Romano, ICML 2025, arXiv:2502.04807; Bhattacharjee et al.,
CPSS 2022, doi:10.1145/3494107.3522778; Korycki and Krawczyk 2023, doi:10.1007/s10994-022-06177-w; Kloft
and Laskov, JMLR 2012; Tuor et al. 2018, arXiv:1712.00557; Han et al. (OWAD), NDSS 2023; Nkashama et al.
2024, arXiv:2407.08838; Lovisotto et al., EuroS&P 2020, doi:10.1109/EuroSP48549.2020.00020; Kent, LANL
2015, doi:10.17021/1179829; Pandey and Bhujang 2026, arXiv:2605.24421; Karanjai et al. 2026,
arXiv:2607.14493; Tong et al., AAAI 2020, doi:10.1609/aaai.v34i01.5442; Patton, Yurcik and Doss, RAID
2001; Progent, arXiv:2504.11703; CaMeL, arXiv:2503.18813. Code read directly: `river/anomaly/filter.py`
and `BasicThresholder.java`, both main branch on 2026-11-10.
