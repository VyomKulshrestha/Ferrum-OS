# Paper pack: Thresholds That Travel

Everything needed to review, illustrate and typeset the paper without touching raw data. Built on
2026-10-23 by `scripts/tt1_paper_pack.py` from committed results; `MANIFEST.json` lists every file with
its SHA-256 and the canonical file it was copied from.

## What is here

| Folder | Contents |
|---|---|
| `manuscript/` | the draft (`thresholds_that_travel_draft_v0_1.md`) and the findings record it summarises |
| `results/` | every result file the draft cites: the registered tt1 and tt1b results, their verifier reports, and the exploratory development and post-hoc files |
| `protocols/` | the two registrations, the detection-v2 amendment that shared tt1's data access, and the data-access logs |
| `figure_data/` | plot-ready CSVs (below) |
| `prompts/` | three prompts for Claude Science: review, figures, LaTeX |

`figure_data/`:

- `recall_and_false_alarms_by_rule.csv`: one row per dataset, score and rule. Recall, the paired
  difference against the frozen threshold with its 95% interval, false alarms, onset inflation, recall on
  close and isolated events, and the source file. The `status` column separates registered results from
  exploratory and post-hoc ones.
- `attack_campaigns.csv`: pulse campaigns, score-level frog variants, the BATADAL frog and the physical
  frog: terminal attacks caught after the campaign and in the control, per rule.
- `threshold_trajectories.csv`: the threshold of each rule over time on the HAI 20.07 test streams (one
  row per minute) and the BATADAL test streams (one row per 15-minute step), with the score and the
  attack label. Computed after the registered finals and ledgered as post-hoc. The recomputed calibration
  thresholds equal the registered ones exactly (`trajectory_consistency.json`), and the traces reproduce
  the event counts of the result files: HAI 20.07 frozen 36/38 and tracker 20/38 (registered tt1), MLE
  SPOT 35/38 and DSPOT 36/38 (post-hoc: SPOT and DSPOT were not part of the tt1 registration); BATADAL
  frozen 14/14, tracker 6/14, MLE SPOT 14/14, DSPOT 6/14 (all registered tt1b).

## Where the numbers come from

| Study | Registered | Result | Verifier |
|---|---|---|---|
| tt1 (HAI 20.07 primary; HyGrid-ICS, voraus-AD secondary) | add86f1 | 0971009 | 27/27 checks |
| tt1b (BATADAL) | 3d4467d | 41912ca | 8/8 checks; SWaT and WADI pending |

Development used the normal data and the already-opened attack files of HAI 21.03, 22.04 and 23.05.
Everything in `results/*_dev_*` and `results/*posthoc*` is exploratory. Commits refer to
github.com/VyomKulshrestha/Ferrum-OS (anonymize before submission).

## Rules for using the pack

- Do not recompute any result from raw data. The raw datasets are not in the pack, and each registered
  study allowed one access per dataset, already used.
- Figures come from `figure_data/` only.
- Edits to the draft are proposals until checked against the result files; the numbers in `results/`
  are the record.

## Using it in Claude Science

Claude Science is installed on this machine and runs a local daemon (check with
`claude-science status`; open the UI with `claude-science open`).

1. In the Claude Science web UI, start a project whose folder is this pack folder:
   `C:\Users\marcu\Videos\cursor-os-base-tt1\docs\research\paper\tt1_paper_pack`. Approve read access
   when the approval card asks; write access is needed only for `review/`, `figures/` and `latex/`.
2. Paste `prompts/1_review_numbers_and_citations.md` and keep the background reviewer on. Read
   `review/review_report.md` and bring the proposed fixes back to the draft in the repository.
3. Paste `prompts/2_figures.md`. Each figure keeps its code, environment and conversation.
4. After the draft is fixed, paste `prompts/3_latex_submission.md` for the anonymous ACM version.
5. Copy `review/`, `figures/` and `latex/` back into the repository and commit them, so the paper and its
   provenance live with the code.

## Compiling the LaTeX versions

`latex/main.pdf` (ACM sigconf, anonymous review mode, 10 pages with references from page 9) and
`latex_usenix/main.pdf` (11 pages, references from page 10) were built with tectonic 0.17.0, which
fetches the TeX packages it needs on first use:

```
cd latex && tectonic main.tex
cd latex_usenix && tectonic main.tex
```

Both compile with no overfull lines and no undefined references. The USENIX copy uses fallback page
metrics; with the official `usenix-2020-09.sty` next to `main.tex`, compile it with pdflatex instead.
Before submission, replace the anonymous.4open.science placeholder with the real anonymized link.

What the pack sends to Anthropic: whatever Claude Science reads from these files goes to the Claude API
as context, as in any Claude session. The files hold results and text, no raw telemetry.
