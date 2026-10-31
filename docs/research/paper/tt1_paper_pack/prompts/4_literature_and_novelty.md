# Prompt 4: literature search and novelty check

Paste the text below into Claude Science with this pack's folder open as the project. Model Opus 5.5,
background reviewer Sonnet 5.5.

---

You are checking whether a security paper's contributions are new, and what prior work it is missing.
The paper is `manuscript/thresholds_that_travel_draft_v0_1.md` (the compiled version is
`latex/main.pdf`). Read the abstract, Sections 1 to 3 and Section 8 first. Do not edit the manuscript.
Write the report to `review/literature_report.md`.

The paper's claims, in short: adaptive alarm thresholds in ICS anomaly detection (daily recalibration,
online quantile tracking as in adaptive conformal inference, SPOT/DSPOT extreme-value thresholds) can be
pushed upward by what they learn from; real attacks do this to exceedance learners with no adversarial
effort; a closed-loop "frog-boiling" attacker does it to SPOT/DSPOT without raising an alarm; a
threshold that only tightens itself and loosens only with operator approval avoids all of it.

1. **Search.** Find published work (2005 to 2026: journals, conferences, arXiv) on:
   - poisoning, evasion or manipulation of anomaly-detection *thresholds* (not only of the model):
     dynamic thresholds, adaptive thresholds, peaks-over-threshold / SPOT / DSPOT, extreme-value
     thresholds, Telemanom's nonparametric dynamic threshold;
   - frog-boiling or gradual-drift poisoning of online or self-updating anomaly detectors, in any domain
     (network intrusion detection, ICS, spacecraft telemetry, fraud, cloud monitoring, AIOps);
   - adaptive conformal inference or online quantile tracking under adversarial (not only benign)
     distribution shift;
   - threshold selection and recalibration in ICS / CPS anomaly detection (SWaT, WADI, HAI, BATADAL
     detectors), including how published detectors set and update their thresholds;
   - alarm management and alarm-threshold practice in process control (ISA-18.2, EEMUA 191) as it bears
     on nuisance alarms and operator acknowledgement.
   Use every literature connector you have. Record the query and the source for each hit.
2. **Verify each candidate.** For every paper you cite in the report, confirm that it exists: authors,
   title, venue, year, and a DOI or arXiv ID. Do not list a paper you could not confirm; put it in a
   separate "could not verify" list with what you searched. Never fill in an identifier from memory.
3. **Closest prior work per contribution.** For each of the five contributions in Section 1, name the
   closest prior work, say what it already showed, and say plainly whether the paper's contribution is
   new, partly new, or already known. Quote the prior paper's own claim (one short quote) where you rely
   on it.
4. **Missing citations.** List the papers the related-work section should cite and is not citing, ranked
   by how likely a reviewer is to name them. For each, one sentence on what it adds and where in the
   paper it belongs.
5. **Proposed related-work text.** Draft a replacement for Section 2 (same length, plus at most 150
   words) that positions the paper against what you found. Mark every new citation. Keep the paper's
   claims as they are; do not strengthen them.

Keep the report factual. If the search finds a paper that already demonstrates one of the claims, say so
at the top of the report.
