# Response to the mock PC review (2026-11-01)

The review (`mock_pc_review.md`, Claude Science, Opus 5.5 with a Sonnet 5.5 background reviewer) scored
the paper 2/2/2 (weak reject) and recommended major revision. Every weakness below was re-checked against
`results/` and `figure_data/` before the draft was changed; the numbers it cites all reproduced.

| Rank | Change asked for | Done | Where |
|---|---|---|---|
| 0 | Working anonymized artifact link | No: still a placeholder; needs the anonymized repository uploaded first | contribution 5, Open science |
| 1 | BATADAL SPOT/DSPOT were blind from calibration, not poisoned by attacks | Yes. Moments SPOT 49.0 tau_0, DSPOT 45.8 tau_0 at t = 0 of both files; MLE SPOT 1.22. Abstract, 7.6, Figure 3 caption and conclusion rewritten | Abstract, 7.6, Fig. 3, 10 |
| 2 | Re-weight the headline around registered, metric-robust evidence | Yes. Abstract leads with both registered tracker losses, says the HAI 20.07 gap is not robust to onset counting and the BATADAL gap is, marks the campaigns exploratory; "seven datasets" removed; G1 marked uninformative; G3 qualified with the 39% alarm share | Abstract, 1, 6.1, 10 |
| 3 | Report every registered outcome | Yes. New 6.4: the four automatic permits (all lose recall on HAI 20.07), oracle permit, first/second half recall, E5; BATADAL frog variants for every rule and both scores in 7.6; superseded transient analysis in 6.2 | 6.2, 6.4, 7.6 |
| 4 | Scope the design rule | Yes. Proposition 3 restricted to tighten-only without a permit and to the any-alarm count; operator-gated loosening no longer credited with the guarantee; oracle control 1/10 reported | 1, 3.1, 8 |
| 5 | Stronger adaptive baselines and canonical EVT rules on the spent development data | No. Listed as a limitation; needs new exploratory runs (alarm-excluding recalibration, capped tracker, Telemanom, Grimshaw MLE SPOT with declustering) | 9 |
| 6 | Frog dose-response, matched refit cadence, direct-concealment baseline | Partly: the threat model now says what poisoning buys over concealment and that we did not compare them; no new runs | 3 |
| 7 | Inference repairs | Partly: exact McNemar tests on the discordant pairs (HAI 20.07 tracker 16/0, p = 3.1e-5; BATADAL 8/0, p = 0.0078) and the exact H2 bound (-0.23 against the -0.14 tolerance). Matched operating points not done | 6.2, 7.6 |
| 8 | Related work | Yes, from `review/literature_report.md`: Section 2 replaced by its proposed text (verified citations; Crossref/arXiv metadata); A2 introduced as the standard stealthy attacker (Cardenas 2011, Urbina 2016); Atarmla 2026 cited as the theory of tracker absorption; ISA-18.2/EEMUA management of change, Kravchik 2021 and Kloft-Laskov 2012 as precedent in Section 8; the exclusion-ratchet preprint as a limit on operator gating; HAI 1.0 citation fixed (its arXiv ID belonged to an unrelated paper); Kravchik-Shabtai sentence corrected. Still to read before submission: Seo, Lee and Seo 2026 (ICUFN), whose title overlaps contribution 2 and whose abstract was not accessible | 2, 3, 3.1, 8, 9 |
| 9 | Presentation fixes | Yes: Figure 2 caption (only 2.7 h unlabelled, 7 attacks inside the run), episode-count wording, physical-frog table header, light-tail MLE SPOT miss, 7.2 status tags, 7.3 lead sentence, recommendation 3 ("0.66 to 1.48 ... and 2.23 against a budget of 2"), "exceedance-free" | 3.1, 6.2, 7.2, 7.3, 7.5, 8 |
| 10 | Registered SWaT/WADI outcomes, ideally a new registration (tt1c) | No: data not available yet | - |

Two errors that the 2026-11-01 revision itself had introduced were caught by the review and fixed: the
Figure 2 caption said the 23.8 h opening run had no attack label, and the draft said each long run counts
as one false-alarm episode (an episode that overlaps an attack is not counted as a false alarm at all).
