# Response to the Claude Science review (2026-10-23)

Each finding in `review_report.md` was checked against the result files before the draft was changed.
All were accepted; none changed a registered result.

| Finding | Check | Change in the draft |
|---|---|---|
| M1 budget per dataset | protocol budgets confirmed | Section 4 states 2/day (1 Hz), 0.05 per sample (voraus-AD), 1/week (BATADAL) |
| M2 tracker step on voraus-AD | eta / spread = 0.05 confirmed | Section 4 gives both steps and voraus-AD's spread and review window |
| M3, M4, M6 "runs" | result files count samples | "samples" throughout; 755 anomalous samples confirmed |
| M5 margin "held the budget" | 3.79/day on HAI 20.07 development | rewritten: cut false alarms without always reaching the budget |
| M7 fixed-level tracker | 16/30 against 20/30 confirmed | separate tracker row |
| M8 DSPOT denominator | 9/12 and 9/12 confirmed | column renamed "after campaign / in control (12 placements)" |
| M9 noise scale | DSPOT 0.05-0.12 confirmed | both ranges given |
| U1 synthetic light-tailed SPOT | the earlier run was unsaved | rerun with five seeds and saved: `results/threshold_transfer_tt1b_frog_synthetic_v1.json` (commit 1b398a5); sentence now cites its numbers |
| U2 "up to 7.6" | file stores medians only (0.78/1.42/1.03) | medians reported |
| U3 600 s bump | constant of the development campaigns | stated as the terminal length of every development campaign |
| R1 tt1b primary failure | gates.primary_success false | abstract and Section 7.6 say the primary rule failed |
| R2 SPOT/DSPOT not in tt1 registration | confirmed | Section 4 says so; "eleven rules" now consistent |
| R3 G1 caveat in abstract | confirmed | abstract and introduction qualify the pulse result |
| R4 reporting commitments | posthoc file confirmed | HyGrid contamination and the no-claim sentence added to Section 9 |
| C1 Erba et al. attribution | confirmed against the access log | concealment attributed to Taormina et al.; re-simulation to Erba et al.'s artifact |
| C2 ISA-18.2 wording | accepted | rewritten without the causal claim |
| C3 HAI citation scope | accepted | HAI 1.0 citation scoped to 20.07 |
| C4 HyGrid-ICS DOI and creator | Zenodo API: record 23250890 is v1.1.1, concept 23250468, creator Furkan Yolcu | reference rewritten with both DOIs and the creator |
| C5 Wu and Keogh year | accepted | TKDE 35(3), 2023 |
| L1 white-box physical attacker | accepted | Section 9 bullet rewritten |
| L2 margin recommended in Section 8 | BATADAL margin 3/14 confirmed | margin removed from the rules that held; caveat and limitation added |
| I1-I6 consistency | each confirmed | close-vs-control counts in 6.1 and 7.4, spread-permit rounds, false-alarm denominator, margin sentence in 6.3 |

Not yet done: anonymization for double-blind submission (author block, ORCID, "our earlier registered
studies", repository and Zenodo references), and the figures and LaTeX conversion (prompts 2 and 3).
