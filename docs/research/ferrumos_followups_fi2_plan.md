# FerrumOS follow-ups (fi2): plan

Written 2026-11-12, before any change. It carries out the owner's answers to the decisions listed in
section 7 of `ferrumos_improvement_fi1_report.md`. Rules of fi1 that stay in force: files frozen by a
registration are never modified; everything measured on recorded attacks is exploratory and no
registered or published number is recomputed; kernel and userland Rust reaches main only through pull
requests that CI builds and the owner merges; QEMU harnesses run one at a time under the lock directory;
no attack result against a named project is committed before its maintainers are told.

## The owner's answers (2026-11-12)

| Decision | Answer |
|---|---|
| Papers' next versions | Write them |
| Two-channel monitor in future studies | Yes |
| Kernel open items | Do them, one by one |
| Policy questions of the gate rounds | Add whatever strengthens FerrumOS |
| Paper-2 follow-ups, the Docker round, htm.core | Go ahead; Docker is running |
| Kaggle | Through the signed-in browser, not the API token |
| Agent study | An Anthropic API key is available; OpenRouter has no balance |

## Workstreams

Each Rust workstream is a branch on top of pull request 6's head (1efd7a6), in its own worktree, with
its own draft pull request so that CI builds it.

### K1. Kernel protections (branch `improve/fi2-kernel-cpu`)

In this order, each finished before the next starts:

1. SMEP (CR4 bit 20) wherever the CPU reports it.
2. SMAP (CR4 bit 21) wherever the CPU reports it, with every intended kernel access to user memory
   bracketed explicitly.
3. The `[SECURITY]` prompt cannot be imitated by a process writing to the console.
4. A ledger that caps one process's total kernel heap, charged at allocation and released at reap.
5. ext2 on disks made with a real `mke2fs` (in a container): backup superblocks and reserved descriptor
   blocks treated as metadata, cross-linked blocks, indirect blocks freed on remove and overwrite,
   directories longer than 12 blocks.
6. CR0.NE set, with the x87 error delivered to the process.
7. Page-table isolation between kernel and user. Done only if it can be finished and tested inside the
   workstream; otherwise the report gives the design and says plainly that it is not done.

### K2. Kernel areas no round examined (branch `improve/fi2-kernel-audit`, starts after K1 or P)

An audit with fixes, as in fi1: the compositor and desktop input paths, the xHCI, HDA, VirtIO-GPU and
VBE drivers, ACPI AML, the package manager's signature verification, `src/agent`, `src/heliox` and
`src/accounts`, the audit log's flush to disk, and the bootloader configuration.

### P. Gate policy (branch `improve/fi2-policy`)

The option taken for each question is the one that strengthens the gate and keeps a way for the operator
to widen it in `config.json`.

| Question | Change |
|---|---|
| Q1 read, then send | network calls to hosts outside an allowlist (the provider and speech hosts, plus `network_allowlist` in the config) need approval; `poll_input` needs approval; the rate limit the source comment promises exists |
| Q2 approval by id | an approval counts only for the request printed last, otherwise the request is printed again and a second confirmation is needed; the shell gets `heliox pending` and `heliox deny <id>` |
| Q3 config fallback | a config file that exists and does not parse gives tier 0 and a console message; zero intervals cannot crash the daemon |
| Q4 test hooks | in the default build no file under a path the agent can write triggers ungated network access or unbounded synthetic actions at startup; the harnesses and the collection tooling keep working |
| Q5 | `service_stop` shows the service's name; autosave cannot write model text that the approval for `save_memory` would have covered; an auto-approve tier of 4 or more is clamped to 3; the setup wizard escapes strings |
| Q6 | one process cannot push other processes' unflushed entries out of the audit ring |
| Q-J2a | the panel's sender flag authorises only GOAL and CONFIG_UPDATED |
| Q-J2b | the boot-time setup panel gets no more authority than first-run setup needs; changed only if first-run setup still completes |
| Q-J2c | an approved `keyboard_type` is bound to the window that had focus when it was approved |
| Q-J2d | a delete of any ancestor of the daemon's configuration is refused |
| O1 | a missing or stale occupancy record blocks motion when humans are not allowed |
| O5 | a per-command step bound (named as on the `vision-world-model` branch, which is read and not touched) and the payload and battery limits checked on the command path |

### Yardstick for K1, K2 and P

An item is done when: a run-time or host test fails on a negative control (the same tree with that fix
held back, or a runtime switch) and passes with the fix; the twenty-one harnesses of fi1 still pass
(315 checks) on the final image, run by the main session on the image CI built; host tests pass; both
workflows are green under the strict rule. An item that cannot be tested is reported as not tested,
with the reason. Behaviour changes are listed for the owner.

### D. Papers (branch `docs/fi2-papers`, from main)

- "Prediction Is Not Permission" v1.4: the sentences fi1 found missing (dependence of the physical
  model's selection and promotion, and of the OS world-model numbers, on the BLAS thread count; the
  Table 13 tie; the unreachable threshold of Table 7; the search rule of Table 30 and Tables 28 and 29;
  the control rows of Table 19; the 0/0 bootstrap convention; the discontinuity in Tables 4, 5 and D1;
  binning and weighting in Section 6.2; the discordant-pair wording of Section 8.5). No number is
  recomputed. Every added statement cites the stored file it comes from.
- "Thresholds That Travel": a post-hoc paragraph on HAI 20.07 (share of unlabelled time and of alarm
  time with a sensor outside the fitted range), marked exploratory. The two-channel monitor is not
  added: it rests on a second use of the check set.
- Nothing is uploaded to Zenodo or HotCRP by this workstream. Publication is the owner's step.

### T1. Paper 2, score level (branch `research/tw1b`, from main)

An amendment to `thresholds_in_the_wild_tw1a_dev_plan.md` is committed before any run. Then, on the same
nine targets and the same spent score cache: settings matched to the false-alarm budget; the frog held
at 2%, 1% and 0.5% below each target's reading; the SPOT authors' script on whole series. Results stay
local under `target/tw1/`.

### T2. Paper 2, signal level (branch `research/tw1c`, from main)

A plan is committed before any run. Products in containers, one at a time, within the 4 GB the Docker
machine has: OpenSearch anomaly detection, Netdata, Zabbix; then StreamAD and htm.core, each inside a
container with no host mounts beyond its own input and output directories. Results stay local.

### O. The operator in the loop (ol1), after T1

Open choices of the draft, settled: models are Claude models through the owner's Anthropic key and
open-weight models on Kaggle GPUs through the browser; the study is registered on sealed scenario seeds;
whether it is its own short paper or a section of paper 2 follows the rule already in the draft. The
harness, the deterministic gate arm, scripted reference policies and a mock model are built and tested
first. No model is queried on a sealed seed before the protocol is committed. The key is read from the
environment or from a file the owner names; it is never printed, logged or committed. Spending on the
API has a cap the owner sets; a pilot on development seeds stays under 5 US dollars.

### Disclosure

Notes to the maintainers of river, PySAD and libspot are drafted by the main session and sent only when
the owner has read them and said so.

## Two-channel monitor in future studies

A new study that uses it registers it before any of its data is opened, with the budget split fixed, and
counts alarm episodes as well as alarm time. Published and registered results keep the monitor they
were registered with.

## Notes after the plan was committed

- 2026-11-12, 14:45 UTC: the owner merged pull request 6 with a merge commit (main c80f7dd); pull
  requests 2 to 5 show as merged with it. The Rust workstreams' branches start from a commit that main
  now contains, so their pull requests show only their own changes.
- 2026-11-12: the owner set the cost rule for workstream O. The API balance is about 180 US dollars and
  the Claude arm uses `claude-haiku-5-5` only. The pilot stays under 5 dollars. The registered run has
  a cap of 30 dollars including retries and is designed so that its estimate, with the Batches API and
  prompt caching, stays under 20. No request goes to a larger Claude model; adding one later is a
  separate, costed extension that the owner decides on.

## Stopping

Each workstream runs once through its list. A second round on a workstream starts only if its own
report names a defect it introduced or left open and can test.
