# Paper pack: The Operator in the Loop (ol1)

The short paper that the ol1 publication gate called for ("own short paper"), as a named preprint in
ACM sigconf. Nothing here is published, uploaded or submitted.

## Files

| Path | Content |
|---|---|
| `latex/main.tex` | the paper; the title is set once, in `\papertitle` near the top |
| `latex/values.tex` | every number the paper takes from the study, as macros (`\V...`) |
| `latex/table_cells.tex` | the full cell table (Appendix C), rebuilt from the result JSON |
| `latex/refs.bib` | references; each checked online, see `REFERENCES_CHECKED.md` |
| `latex/figures/*.pdf` | the three figures (vector, grey scale) |
| `latex/acmart.cls`, `latex/ACM-Reference-Format.bst` | vendored from the tt1 pack (acmart v2.21) |
| `latex/main.pdf` | the built paper |
| `NUMBER_TRACE.md` | every macro with its value and its source file and field |
| `REFERENCES_CHECKED.md` | the URL opened for each reference and what was confirmed |
| `ol1_quote_sample.json` | the systematic transcript sample behind Section 5.2 |

## Building

From `latex/`, with tectonic 0.17.0 (XeTeX):

```
tectonic main.tex
```

The build of 2026-11-15 has no undefined reference or citation and no overfull box on its final pass;
10 pages: body on pages 1 to 7 (the references begin on page 7), appendices on pages 8 to 10.

## Regenerating and checking

From the repository root:

```
python scripts/ol1_paper_figures.py                       # the three figures, from the result JSON
python scripts/ol1_paper_quotes.py <stage2 transcripts dir> --out docs/research/paper/ol1_paper_pack/ol1_quote_sample.json
python scripts/verify_ol1_paper_numbers.py                # check: exit 1 on any mismatch
python scripts/verify_ol1_paper_numbers.py --write --jobs <ol1_jobs_kaggle_sealed.npz>   # rewrite values, table, trace
```

The check recomputes every value in `values.tex` from the sources listed below, compares the cell table
with one rebuilt from the result JSON, checks that every `\agentquote{...}` occurs word for word in
`ol1_quote_sample.json`, and fails if `main.tex` uses an undefined macro. One value, the open-weight
qwen3-8b replay of M(600) (`\VOWQwenLTMsix`), needs the Kaggle job file (D1 score windows, not in git;
it was at `cursor-os-base-ol1k/target/ol1/kaggle/ol1_jobs_kaggle_sealed.npz`) and is recomputed only with
`--jobs`. The transcripts (about 600 MB) are outside the repository; the quote sample was drawn from
`cursor-os-base-ol1/target/ol1/stage2/<model>/wave_mode<m>/episodes.jsonl`, read only.

## Where the numbers come from

| Source | Status in the paper |
|---|---|
| `docs/research/operator_in_the_loop_ol1_result.json`, `hypotheses` and `gate` | registered (H1 to H5 on Haiku, H6 estimates, publication gate) |
| the same file, `tables` | the registered analysis's cell table; quoted as such |
| `docs/research/ol1_result/<model>/episodes.jsonl` | descriptive counts beyond the analysis output, labelled "from the episode records" |
| `docs/research/ol1_result/README.md` | run record (spend, batches, the interruption, the interim analyses) |
| `docs/research/ol1_open_weight/*.ol1rec.txt` | exploratory open-weight arm |
| `ol1_quote_sample.json` | exploratory transcript sample |
| `scripts/ol1_core.py` | design constants of the registered code |

What is registered: the protocol `docs/research/operator_in_the_loop_ol1_protocol.md` and the record
`operator_in_the_loop_ol1_registration.json` (both frozen, registered 2026-11-13). Section 4 of the paper
reports the registered quantities (cell-table values there are marked); Section 5 is descriptive and exploratory, and says so.
