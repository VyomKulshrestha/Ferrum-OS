# The operator in the loop (ol1): registered result, files

Protocol: `../operator_in_the_loop_ol1_protocol.md` (registered 2026-11-13, record
`../operator_in_the_loop_ol1_registration.json`). The open-weight arm is separate and exploratory:
`../operator_in_the_loop_ol1_notes.md` and `../ol1_open_weight/`.

## Files

| File | Content | sha256 (LF line endings) |
|---|---|---|
| `../operator_in_the_loop_ol1_result.md` | output of `scripts/ol1_analysis.py` on the registered results directory, unchanged | `0ff1b01af0e46100bfaef92d0536cf1f4a7da17fde139c54ad9d26e44e1b2d49` |
| `../operator_in_the_loop_ol1_result.json` | the same analysis as data, with the environment record | `baa9236f855690218c69a1b052e9bbc05dc90f93797d1971a98b610ebe38007c` |
| `claude-haiku-5-5/episodes.jsonl` | 2,352 episode records | `4f5193b3ae46e5a8d050d5ef265be445d1d2d21bb9239b51d75296a0d917d017` |
| `claude-sonnet-5-5/episodes.jsonl` | 280 episode records | `1caf8108a1deab424b80003cdc509f4de07e30317757bfa75a705c52ed767f57` |
| `claude-opus-5-5/episodes.jsonl` | 140 episode records | `8ae60c276b79282ac1e99099e030f9eec596a11b36a2b8850ad32e8e92ce6d02` |

An episode record here is the runner's record with one field removed: `reviews`, the message transcripts of
the nine reviews. Nothing else is changed; the records are sorted by mode, seed, condition and arm. The
transcripts (about 600 MB, with the per-turn responses another 220 MB) are kept outside the repository.

## Reproducing the analysis

```
python scripts/ol1_analysis.py docs/research/ol1_result --out <directory>
```

writes `ol1_analysis.md` with the same content as `operator_in_the_loop_ol1_result.md`, and
`ol1_analysis.json` equal to the result JSON apart from the environment record (both checked on
2026-11-15).

## Run record

| Model | Grid | Episodes | Run (IST) | Batches | Spend (USD) | Cap (USD) |
|---|---|---|---|---|---|---|
| claude-haiku-5-5 | full | 2,352 | 2026-11-13 00:25 to 2026-11-14 00:01 | 220 | 13.77 | 20 |
| claude-sonnet-5-5 | reduced | 280 | 2026-11-14 00:03 to 21:10 | 139 | 13.27 | 45 |
| claude-opus-5-5 | reduced | 140 | 2026-11-14 21:11 to 2026-11-15 09:29 | 198 | 23.83 | 45 |

By the cost ledgers the three grids cost 50.86 dollars (13.7669, 13.2661 and 23.8266; the rounded cells
above sum to 50.87). Development and pilot runs before registration cost 3.03 dollars; the study cost 53.89
dollars of its 120-dollar cap. Every grid ran to completion, so no mode is dropped.

Order: Haiku, then Sonnet, then Opus, each started after the previous runner had exited and its spend was
read from the ledger. The registration check passed before each start.

One interruption: on 2026-11-14 at 02:48 a Windows Update restart of the machine stopped the Sonnet runner in
its second wave. It was resumed at 09:35 with the same command, after the lock file of the stopped process
had been removed (no runner was alive). The runner replays the recorded responses, collected the batch that
had been submitted before the restart, and settled it in the ledger; no request was sent twice.

Two analyses were run before the last grid ended, each into its own directory: on the Haiku grid alone
(2026-11-14 00:05) and on Haiku and Sonnet (2026-11-14 21:12). Grids, prompts, settings and code of the later
models are bound by the registration record and were not changed. The hypotheses and the publication gate
are defined on the Haiku grid, and their values are the same in all three analyses.

## Transcripts archive (prepared 2026-11-21, not published)

The protocol (section 10) lists the transcripts among what is released with the result. An archive was
built from the registered results directory for upload as a Zenodo dataset by the author:

| File | Bytes | sha256 |
|---|---|---|
| `ol1_transcripts_claude_v1.0.tar.xz` | 207,046,452 | `69a28e80cd7951cafdf753f5439085468aa66f3f3ba82d033ffa70dbd77f3638` |
| `ol1_jobs_sealed.npz` (the derived job file) | 73,929,234 | `0b3c9d49c15473e12cadf3d2f74944932208197b47190e2c2cee633dfe20b8b2` |

The archive holds `episodes.jsonl` and `turns.jsonl` of every wave of the three grids (42 files,
861,387,774 bytes, unchanged), a README and `SHA256SUMS`. Checked after building: every file unpacks to its
listed digest, and the registered analysis on the unpacked archive gives the registered result byte for
byte.

Scan before the build, over all 42 files: the stored API key itself, the key prefix, request headers,
e-mail addresses, user names and local paths. None found. Three short name patterns matched only inside
strings the API generates at random (thinking signatures, message ids, tool-use ids). The protocol's own
check, `scripts/test_ol1_secrets.py`, passes for the results directory; its second test, on the git index,
reports the dummy string `sk-ant-SECRET` in the gate test `userland/heliox-gate-tests/tests/round3.rs`,
which is a test fixture and not a key.
