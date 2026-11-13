# The operator in the loop (ol1): notes

Notes beside the registered protocol (`operator_in_the_loop_ol1_protocol.md`, registered 2026-11-13; record
`operator_in_the_loop_ol1_registration.json`). The protocol is not changed by these notes. Everything here concerns
the open-weight arm, which the protocol calls exploratory and which runs after the Claude grids, on Kaggle.

## 2026-11-13: the open-weight arm resized before any sealed seed goes to Kaggle

**Status.** Exploratory under the protocol (registration block and section 7): no hypothesis or publication gate
uses these models. This note is written before any sealed job file is uploaded to Kaggle.

**What was measured.** One development run of qwen3-8b on the development job file (42 episodes: development seed 1,
seven modes, conditions loud, twin_loud and nuisance under arms P0 and G), run by the coordinating
session through the browser: vLLM 0.32.0 came up on two T4 cards and the model called the tools; 42 of 42 episodes
finished; the notebook reported "Successfully ran in 14039.0s". The first episode finished at 5,152 s and the other
41 took 8,877 s, so about 216 s per episode once running, after about 1.4 hours of start-up (package install, model
download and server start together; the log did not separate them).

**Quota.** Kaggle allows 30 GPU hours a week and 12 hours per session; about 22 were left this week.

**Resized grid.**

| Item | Before (protocol section 8) | Now |
|---|---|---|
| Models | qwen3-8b, mistral-nemo-12b, granite-3.3-8b, qwen3-32b-awq | qwen3-8b, mistral-nemo-12b, granite-3.3-8b |
| Cells | the five reduced cells | the same five cells |
| Placements | 56 (replicate 0 of all eight runs per mode) | 14 (replicate 0 of runs 0 and 1 in every mode) |
| Episodes per model | 280 | 70 |
| GPU hours per model | about 3.5 to 10 (estimated) | about 5.6 (1.4 start-up + 70 x 216 s) |

The 14 placements are a subset of the registered reduced grid's 56 (and of Opus 5.5's 28): the same sealed seeds,
`sealed_seed(mode, run, 0)` for runs 0 and 1, with the same background windows. The job file is written by
`scripts/ol1_kaggle_jobs.py`, which runs the registration check and then imports the registered code unchanged.

qwen3-32b-awq is dropped: a 32 B model in 4 bits runs several times slower than an 8 B model on the same cards, so
70 episodes would not fit one 12-hour session or the week's remaining quota next to the other three models.

Three models at about 5.6 hours each come to about 17 GPU hours. mistral-nemo-12b is the risk: its 24.5 GB of fp16
weights leave about 1.5 GB of KV cache per T4, so it runs with a 16,384-token context, at most 4,096 tokens per
answer and few episodes in flight at once; its rate may be well below 216 s per episode. Its start-up and first
episodes in the log (OL1STAGE and OL1REC lines) show the rate within the first hours; if 70 episodes would not fit
a 12-hour session, it runs in two shards (`OL1_SHARD` 0/2 and 1/2).

**Development counts** (development data, from the qwen3-8b log; development seed 1, seven modes):

| Cell | Beyond a ceiling (B) | Missing the 600 s terminal step at 1.25 tau0 or above |
|---|---|---|
| loud, P0 | 7 of 7 | 7 of 7 |
| twin_loud, P0 | 7 of 7 | 7 of 7 |
| nuisance, P0 | 0 of 7 | not reported |
| any cell under G | 0 | 0 |

**Results without a file download.** The runner now prints one line `OL1REC {...}` per finished episode (mode,
seed, condition, arm, the final configuration, the applied changes, counts of model calls, invalid calls, gate
blocks and escalations, review endings, and the outcome fields of `summarize`; under 700 bytes in the tests),
stage lines `OL1STAGE` (package install, model download with progress each minute, server start and ready), and at
the end `OL1DONE` with the number of episodes, the sha256 of the results file and the elapsed seconds. A server that
fails to start prints the last 60 lines of its log after `OL1FAIL`. `scripts/ol1_kaggle_ingest.py` turns the
pasted log into the episode records `ol1_analysis.py` reads and recomputes M(d) and the added detection delay by
replay; a test shows the same analysis through the results file and through the log lines.

**Analysis.** The registered analysis script runs on the ingested records as it does on the Claude results, with
each open-weight model as its own "model" (H6-style quantities only). Nothing from this arm enters a registered
hypothesis or the publication gate.
