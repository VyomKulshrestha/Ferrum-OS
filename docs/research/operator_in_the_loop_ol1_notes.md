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

## 2026-11-13: granite-3.3-8b, first sealed attempt excluded; rerun once with corrected serving

**What happened.** The first granite-3.3-8b run on the sealed subset finished in 3,401 s with 70 episodes (OL1DONE
results sha256 `61155e5da8c4d0d59da7cab694cec0b4513227938a9291e6b8ca6278e39982f8`). It made 630 model calls, one per
review, and every one of the 630 reviews ended `end_turn_without_close`: no tool call was parsed, no change was
applied, nothing was escalated and the gate blocked nothing. The model wrote its tool use as prose ("Action: 1. Use
set_threshold with a new threshold of 9.670 ..."). This is a serving failure. It carries no information about the
outcomes of interest, and its results are excluded.

**Cause.** The chat template of granite-3.3-8b-instruct at the pinned revision (`tokenizer_config.json`) adds the
model's tool-call instruction, "When a tool is required to answer the user's query, respond only with <|tool_call|>
followed by a JSON list of tools used", only on the branch where the request has no system message. Every ol1
request has a system message, so the model saw the tools but never the instruction to call them in its format. The
same template renders an assistant turn from its text alone, so after a tool call the model's own call would also
have vanished from the history. vLLM 0.32.0's `granite` parser itself is not at fault: it reads `<|tool_call|>`
(or `<tool_call>`) followed by a JSON array of `{"name", "arguments"}` and also recognises the special token by its
id, so it would have parsed a call in that format.

**What changed** (runner only; no registered file): granite-3.3-8b is served with `--chat-template` pointing to
a template derived from the model's own, with two changes:
1. the model's tool instruction is appended, word for word, to the system message whenever tools are given;
2. an assistant turn with tool calls is rendered as `<|tool_call|>` followed by the JSON list of calls.

The `granite` parser, the prompts, the tools and the request settings stay as they were. Every model run now
starts with a self-check: before the first episode it sends a request with a system message and one trivial tool,
up to three times. Unless one reply is parsed as a call of that tool with the requested argument, the run prints
`OL1FAIL tool_calling` with the raw replies and stops without running an episode.

**Plan.** A development-seed check of granite-3.3-8b first: 12 episodes on development seed 1, modes 0 and 3. It
must pass the self-check and show tool calls, applied changes and closed reviews in its OL1REC lines. Then one
rerun on the same 70 sealed episodes with the corrected serving. That rerun is granite's result in this arm; if it
fails again, the model is reported as not measurable under this harness and is not rerun a third time.

Sources (read 2026-11-13):
- https://huggingface.co/ibm-granite/granite-3.3-8b-instruct/raw/51dd4bc2ade4059a6bd87649d68aa11e4fb2529b/tokenizer_config.json
- https://huggingface.co/ibm-granite/granite-3.3-8b-instruct/raw/51dd4bc2ade4059a6bd87649d68aa11e4fb2529b/generation_config.json
- https://raw.githubusercontent.com/vllm-project/vllm/v0.32.0/docs/features/tool_calling.md (section "IBM Granite")
- https://raw.githubusercontent.com/vllm-project/vllm/v0.32.0/vllm/tool_parsers/__init__.py (`granite` maps to `granite_engine_tool_parser`)
- https://raw.githubusercontent.com/vllm-project/vllm/v0.32.0/vllm/parser/granite.py
- https://raw.githubusercontent.com/vllm-project/vllm/v0.32.0/tests/tool_parsers/test_granite_tool_parser.py
- https://raw.githubusercontent.com/vllm-project/vllm/v0.32.0/examples/tool_chat_template_granite.jinja
- https://raw.githubusercontent.com/vllm-project/vllm/v0.32.0/vllm/renderers/chat_utils.py (`_postprocess_messages`)

## 2026-11-14: granite-3.3-8b development check passed; the one sealed rerun started

Written when the sealed rerun was started and before any of its lines were read.

**Development check** (notebook version 5, corrected serving, development job file `ol1_jobs_dev_granite.npz`,
12 episodes on development seed 1, modes 0 and 3; 1,457 s; OL1DONE results sha256
`c91254d03365c08249918106816f2a00707be19df32d82c454fac7aa1653e748`):

- the self-check passed on the first try (`OL1STAGE tool_check_ok`);
- 12 of 12 episodes finished, with 206 model calls over 108 reviews, 13 applied changes, 7 calls blocked by the
  gate, 3 gate escalations, 1 escalation by the model and 20 invalid calls;
- 4 of 12 episodes ended beyond a ceiling;
- 8 reviews ended `closed` and 100 ended `end_turn_without_close`.

The plan's conditions (self-check, tool calls, applied changes, closed reviews) are met. The last count is a
property of the model under this harness and is reported with its result: it calls tools, about one round per
review, and then answers in prose without calling `close_review`. A change is applied when its tool is called, so
the outcomes do not depend on how the review ends.

**Sealed rerun**: notebook version 6, the same 70 sealed episodes, the script of the corrected runner. It is
granite's result in this arm.

## 2026-11-14: mistral-nemo-12b on the sealed subset

Notebook version 4 (the first script, before the self-check existed): 70 of 70 episodes in 4,827 s, OL1DONE
results sha256 `cefab259f360d0874953f4b7d3d41baf9c5431881ee9f75e3c837104209ab006`, ingested from the log (70
records, matching OL1DONE).

Of 630 reviews, 623 ended `end_turn_without_close`, 5 with an error, 1 at the token limit and 1 `closed`. The model
made 1,217 calls (about one tool round per review, a read tool in the reviews looked at) and 24 invalid calls. One
episode had applied changes (four, in twin_loud under P0) and the model escalated three times. In the replies
looked at, the prose after the read contained text shaped like a tool call that the parser did not read.

This run does not show how the model would act as an operator: it almost never reached a dial, and part of that is
its tool-call format after the first round. Its cells are listed with this caveat and are not compared with the
other models. It is not rerun; the week's GPU quota goes to the granite rerun and the qwen3-8b run.
