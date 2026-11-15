# ol1 paper: number trace

Every number the paper takes from the study is a LaTeX macro defined in `latex/values.tex`. This table
lists each macro, the value printed, and its source: a file and field, or the computation on the
episode records. `python scripts/verify_ol1_paper_numbers.py` recomputes every row and exits non-zero on
a mismatch. Paths are relative to `docs/research/` unless they name `scripts/`.

Status: rows from `operator_in_the_loop_ol1_result.json` are the registered analysis output (registered
where they are H1-H6 or the publication gate; the cell table is the analysis's own descriptive table).
Rows from `ol1_result/*/episodes.jsonl`, `ol1_open_weight/`, the run record and `ol1_quote_sample.json` are
descriptive or exploratory, and the paper labels them so. Rows from `ol1_core` are design constants of the
registered code.

| Macro | Value | Used in main.tex | Source |
|---|---|---|---|
| `\VCeilThr` | 1.10 | yes | ol1_core.CEIL_THRESHOLD |
| `\VCeilDelay` | 60 | yes | ol1_core.CEIL_DELAY_S |
| `\VCeilSup` | 0.5 | yes | ol1_core.CEIL_SUPPRESS_H |
| `\VAddedCeil` | 61.2 | yes | ol1_core.delay_steps(60) x STEP_SECONDS |
| `\VStep` | 3.6 | yes | ol1_core.STEP_SECONDS |
| `\VReviews` | 9 | no | ol1_core.N_REVIEWS |
| `\VMaxCalls` | 6 | yes | ol1_core.MAX_CALLS_PER_REVIEW |
| `\VLoudSteps` | 33 | yes | ol1_core.LOUD[1] |
| `\VSublSteps` | 12 | yes | ol1_core.SUBL[1] |
| `\VFrogFrac` | 0.97 | yes | ol1_core.FROG_FRAC |
| `\VGap` | 17 | yes | ol1_core.GAP |
| `\VLogRows` | 40 | yes | ol1_core.LOG_ROWS |
| `\VEpisodes` | 2,772 | yes | operator_in_the_loop_ol1_result.json: episodes |
| `\VEpHaiku` | 2,352 | yes | ol1_result/claude-haiku-5-5/episodes.jsonl: line count |
| `\VEpSonnet` | 280 | yes | ol1_result/claude-sonnet-5-5/episodes.jsonl: line count |
| `\VEpOpus` | 140 | yes | ol1_result/claude-opus-5-5/episodes.jsonl: line count |
| `\VCampEp` | 224 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H1.B_campaigns_P0.episodes |
| `\VGEp` | 784 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H5.G_episodes |
| `\VHoneB` | 0.821 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H1.B_campaigns_P0.estimate |
| `\VHoneBci` | [0.772, 0.866] | yes | operator_in_the_loop_ol1_result.json: hypotheses.H1.B_campaigns_P0.ci95 |
| `\VMSixty` | 0.817 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H1b.M_by_duration_campaigns_P0.60.estimate |
| `\VMSixtyci` | [0.768, 0.862] | yes | operator_in_the_loop_ol1_result.json: hypotheses.H1b.M_by_duration_campaigns_P0.60.ci95 |
| `\VMOneTwenty` | 0.371 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H1b.M_by_duration_campaigns_P0.120.estimate |
| `\VMOneTwentyci` | [0.299, 0.438] | yes | operator_in_the_loop_ol1_result.json: hypotheses.H1b.M_by_duration_campaigns_P0.120.ci95 |
| `\VMThreeHundred` | 0.085 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H1b.M_by_duration_campaigns_P0.300.estimate |
| `\VMThreeHundredci` | [0.058, 0.121] | yes | operator_in_the_loop_ol1_result.json: hypotheses.H1b.M_by_duration_campaigns_P0.300.ci95 |
| `\VMSixHundred` | 0.062 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H1b.M_by_duration_campaigns_P0.600.estimate |
| `\VMSixHundredci` | [0.031, 0.094] | yes | operator_in_the_loop_ol1_result.json: hypotheses.H1b.M_by_duration_campaigns_P0.600.ci95 |
| `\VMOhFive` | 0.268 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H1b.M105_campaigns_P0.estimate |
| `\VMOhFiveci` | [0.156, 0.384] | yes | operator_in_the_loop_ol1_result.json: hypotheses.H1b.M105_campaigns_P0.ci95 |
| `\VDelMed` | 61.2 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H1b.added_delay_campaigns_P0.median_s |
| `\VDelPninety` | 180.0 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H1b.added_delay_campaigns_P0.p90_s |
| `\VDelShare` | 0.455 | yes | operator_in_the_loop_ol1_result.json: ...added_delay_campaigns_P0.share_above_ceiling.estimate |
| `\VDelShareci` | [0.393, 0.509] | yes | operator_in_the_loop_ol1_result.json: ...added_delay_campaigns_P0.share_above_ceiling.ci95 |
| `\VHtwo` | 0.696 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H2.B_campaigns_minus_nuisance_P0.estimate |
| `\VHtwoci` | [0.625, 0.768] | yes | operator_in_the_loop_ol1_result.json: hypotheses.H2.B_campaigns_minus_nuisance_P0.ci95 |
| `\VHtwocininety` | [0.638, 0.759] | yes | operator_in_the_loop_ol1_result.json: hypotheses.H2.B_campaigns_minus_nuisance_P0.ci90 |
| `\VHtwoPos` | 7 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H2.B_campaigns_minus_nuisance_P0.modes_positive |
| `\VNuisB` | 0.125 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H2.nuisance_B_P0.estimate |
| `\VNuisBci` | [0.080, 0.179] | yes | operator_in_the_loop_ol1_result.json: hypotheses.H2.nuisance_B_P0.ci95 |
| `\VHthreeLoud` | 0.000 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H3.loud.B_campaign_minus_twin_P0.estimate |
| `\VHthreeLoudci` | [0.000, 0.000] | yes | operator_in_the_loop_ol1_result.json: hypotheses.H3.loud.B_campaign_minus_twin_P0.ci95 |
| `\VHthreeLoudPos` | 0 | no | operator_in_the_loop_ol1_result.json: hypotheses.H3.loud...modes_positive |
| `\VHthreeLoudNeg` | 0 | no | operator_in_the_loop_ol1_result.json: hypotheses.H3.loud...modes_negative |
| `\VHthreeLoudZero` | 7 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H3.loud...modes_zero |
| `\VHthreeSubl` | 0.018 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H3.subl.B_campaign_minus_twin_P0.estimate |
| `\VHthreeSublci` | [-0.152, 0.170] | yes | operator_in_the_loop_ol1_result.json: hypotheses.H3.subl.B_campaign_minus_twin_P0.ci95 |
| `\VHthreeSublPos` | 4 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H3.subl...modes_positive |
| `\VHthreeSublNeg` | 3 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H3.subl...modes_negative |
| `\VHthreeSublZero` | 0 | no | operator_in_the_loop_ol1_result.json: hypotheses.H3.subl...modes_zero |
| `\VHthreeFrog` | 0.009 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H3.frog.B_campaign_minus_twin_P0.estimate |
| `\VHthreeFrogci` | [0.000, 0.027] | yes | operator_in_the_loop_ol1_result.json: hypotheses.H3.frog.B_campaign_minus_twin_P0.ci95 |
| `\VHthreeFrogPos` | 1 | no | operator_in_the_loop_ol1_result.json: hypotheses.H3.frog...modes_positive |
| `\VHthreeFrogNeg` | 0 | no | operator_in_the_loop_ol1_result.json: hypotheses.H3.frog...modes_negative |
| `\VHthreeFrogZero` | 6 | no | operator_in_the_loop_ol1_result.json: hypotheses.H3.frog...modes_zero |
| `\VHfourM` | 0.062 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H4.M_P0_minus_P2_campaigns.estimate |
| `\VHfourMci` | [0.027, 0.098] | yes | operator_in_the_loop_ol1_result.json: hypotheses.H4.M_P0_minus_P2_campaigns.ci95 |
| `\VHfourMtwo` | 0.357 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H4.M120_P0_minus_P2_campaigns.estimate |
| `\VHfourMtwoci` | [0.304, 0.420] | yes | operator_in_the_loop_ol1_result.json: hypotheses.H4.M120_P0_minus_P2_campaigns.ci95 |
| `\VHfourB` | 0.839 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H4.B_P0_minus_P2_campaigns.estimate |
| `\VHfourBci` | [0.786, 0.884] | yes | operator_in_the_loop_ol1_result.json: hypotheses.H4.B_P0_minus_P2_campaigns.ci95 |
| `\VHfourMcininety` | [0.036, 0.089] | yes | operator_in_the_loop_ol1_result.json: hypotheses.H4.M_P0_minus_P2_campaigns.ci90 |
| `\VHfourMPos` | 5 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H4.M_P0_minus_P2_campaigns.modes_positive |
| `\VHfourMZero` | 2 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H4.M_P0_minus_P2_campaigns.modes_zero |
| `\VHfourPlace` | 56 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H4.M_P0_minus_P2_campaigns.placements |
| `\VGMisses` | 0 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H5.G_M600_misses |
| `\VGMSixty` | 0.674 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H5.G_M_by_duration_campaigns.60.estimate |
| `\VGMSixtyci` | [0.585, 0.750] | yes | operator_in_the_loop_ol1_result.json: hypotheses.H5.G_M_by_duration_campaigns.60.ci95 |
| `\VGMLonger` | 0.000 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H5.G_M_by_duration_campaigns.120/300/600.estimate (max) |
| `\VGDelPninety` | 61.2 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H5.G_added_delay_campaigns.p90_s |
| `\VGDelShare` | 0.000 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H5.G_added_delay_campaigns.share_above_ceiling.estimate |
| `\VFaDiff` | -0.196 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H5.fa_day3_nuisance_G_minus_P0.estimate |
| `\VFaDiffci` | [-0.473, 0.045] | yes | operator_in_the_loop_ol1_result.json: hypotheses.H5.fa_day3_nuisance_G_minus_P0.ci95 |
| `\VFaDiffPos` | 3 | yes | operator_in_the_loop_ol1_result.json: ...fa_day3_nuisance_G_minus_P0.modes_positive |
| `\VFaDiffNeg` | 3 | yes | operator_in_the_loop_ol1_result.json: ...fa_day3_nuisance_G_minus_P0.modes_negative |
| `\VFaDiffZero` | 1 | yes | operator_in_the_loop_ol1_result.json: ...fa_day3_nuisance_G_minus_P0.modes_zero |
| `\VFaPzero` | 0.96 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H5.fa_day3_nuisance.P0.estimate |
| `\VFaG` | 0.77 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H5.fa_day3_nuisance.G.estimate |
| `\VBlocked` | 1,385 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H5.blocked_calls_G |
| `\VAfterEsc` | 1,250 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H5.tools_after_block.escalate_to_engineer |
| `\VAfterClose` | 60 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H5.tools_after_block.close_review |
| `\VAfterDelay` | 48 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H5.tools_after_block.set_alarm_delay |
| `\VAfterThr` | 26 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H5.tools_after_block.set_threshold |
| `\VSixHaikuLT` | 0.000 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-haiku-5-5.B_loud_minus_twin_P0.estimate |
| `\VSixHaikuLTci` | [0.000, 0.000] | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-haiku-5-5.B_loud_minus_twin_P0.ci95 |
| `\VSixHaikuLTsigns` | 0/0/7 | no | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-haiku-5-5.B_loud_minus_twin_P0.modes_positive/negative/zero |
| `\VSixHaikuFa` | -0.196 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-haiku-5-5.fa_day3_nuisance_G_minus_P0.estimate |
| `\VSixHaikuFaci` | [-0.473, 0.045] | no | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-haiku-5-5.fa_day3_nuisance_G_minus_P0.ci95 |
| `\VSixHaikuB` | 1.000 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-haiku-5-5.B_loud_P0.estimate |
| `\VSixHaikuBci` | [1.000, 1.000] | no | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-haiku-5-5.B_loud_P0.ci95 |
| `\VSixHaikuMSixty` | 0.830 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-haiku-5-5.M_by_duration_loud_P0.60.estimate |
| `\VSixHaikuMOneTwenty` | 0.580 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-haiku-5-5.M_by_duration_loud_P0.120.estimate |
| `\VSixHaikuMThreeHundred` | 0.098 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-haiku-5-5.M_by_duration_loud_P0.300.estimate |
| `\VSixHaikuMSixHundred` | 0.054 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-haiku-5-5.M_by_duration_loud_P0.600.estimate |
| `\VSixHaikuDelMed` | 151.2 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-haiku-5-5.added_delay_loud_P0.median_s |
| `\VSixHaikuDelShare` | 0.607 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-haiku-5-5.added_delay_loud_P0.share_above_ceiling.estimate |
| `\VSixHaikuBG` | 0.000 | no | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-haiku-5-5.B_loud_G.estimate |
| `\VSixSonnetLT` | -0.018 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-sonnet-5-5.B_loud_minus_twin_P0.estimate |
| `\VSixSonnetLTci` | [-0.089, 0.054] | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-sonnet-5-5.B_loud_minus_twin_P0.ci95 |
| `\VSixSonnetLTsigns` | 2/3/2 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-sonnet-5-5.B_loud_minus_twin_P0.modes_positive/negative/zero |
| `\VSixSonnetFa` | 0.232 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-sonnet-5-5.fa_day3_nuisance_G_minus_P0.estimate |
| `\VSixSonnetFaci` | [-0.036, 0.464] | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-sonnet-5-5.fa_day3_nuisance_G_minus_P0.ci95 |
| `\VSixSonnetB` | 0.875 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-sonnet-5-5.B_loud_P0.estimate |
| `\VSixSonnetBci` | [0.804, 0.946] | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-sonnet-5-5.B_loud_P0.ci95 |
| `\VSixSonnetMSixty` | 0.589 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-sonnet-5-5.M_by_duration_loud_P0.60.estimate |
| `\VSixSonnetMOneTwenty` | 0.571 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-sonnet-5-5.M_by_duration_loud_P0.120.estimate |
| `\VSixSonnetMThreeHundred` | 0.018 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-sonnet-5-5.M_by_duration_loud_P0.300.estimate |
| `\VSixSonnetMSixHundred` | 0.018 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-sonnet-5-5.M_by_duration_loud_P0.600.estimate |
| `\VSixSonnetDelMed` | 126.0 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-sonnet-5-5.added_delay_loud_P0.median_s |
| `\VSixSonnetDelShare` | 0.589 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-sonnet-5-5.added_delay_loud_P0.share_above_ceiling.estimate |
| `\VSixSonnetBG` | 0.000 | no | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-sonnet-5-5.B_loud_G.estimate |
| `\VSixOpusLT` | 0.071 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-opus-5-5.B_loud_minus_twin_P0.estimate |
| `\VSixOpusLTci` | [-0.179, 0.286] | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-opus-5-5.B_loud_minus_twin_P0.ci95 |
| `\VSixOpusLTsigns` | 4/2/1 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-opus-5-5.B_loud_minus_twin_P0.modes_positive/negative/zero |
| `\VSixOpusFa` | 0.071 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-opus-5-5.fa_day3_nuisance_G_minus_P0.estimate |
| `\VSixOpusFaci` | [0.000, 0.179] | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-opus-5-5.fa_day3_nuisance_G_minus_P0.ci95 |
| `\VSixOpusB` | 0.679 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-opus-5-5.B_loud_P0.estimate |
| `\VSixOpusBci` | [0.500, 0.821] | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-opus-5-5.B_loud_P0.ci95 |
| `\VSixOpusMSixty` | 0.643 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-opus-5-5.M_by_duration_loud_P0.60.estimate |
| `\VSixOpusMOneTwenty` | 0.607 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-opus-5-5.M_by_duration_loud_P0.120.estimate |
| `\VSixOpusMThreeHundred` | 0.000 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-opus-5-5.M_by_duration_loud_P0.300.estimate |
| `\VSixOpusMSixHundred` | 0.000 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-opus-5-5.M_by_duration_loud_P0.600.estimate |
| `\VSixOpusDelMed` | 151.2 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-opus-5-5.added_delay_loud_P0.median_s |
| `\VSixOpusDelShare` | 0.643 | yes | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-opus-5-5.added_delay_loud_P0.share_above_ceiling.estimate |
| `\VSixOpusBG` | 0.000 | no | operator_in_the_loop_ol1_result.json: hypotheses.H6.claude-opus-5-5.B_loud_G.estimate |
| `\VGateDecision` | own short paper | yes | operator_in_the_loop_ol1_result.json: gate.decision |
| `\VGateBupper` | 0.866 | yes | operator_in_the_loop_ol1_result.json: gate.B_upper |
| `\VGateMupper` | 0.438 | yes | operator_in_the_loop_ol1_result.json: gate.M120_upper |
| `\VTabSublPtwoFa` | 47.43 | yes | operator_in_the_loop_ol1_result.json: tables[haiku, subl, P2].fa_day3_mean |
| `\VTabSublPzeroFa` | 13.15 | yes | operator_in_the_loop_ol1_result.json: tables[haiku, subl, P0].fa_day3_mean |
| `\VTabLoudPtwoFa` | 12.96 | yes | operator_in_the_loop_ol1_result.json: tables[haiku, loud, P2].fa_day3_mean |
| `\VTabLoudPzeroFa` | 6.88 | yes | operator_in_the_loop_ol1_result.json: tables[haiku, loud, P0].fa_day3_mean |
| `\VTabLoudGFa` | 12.27 | yes | operator_in_the_loop_ol1_result.json: tables[haiku, loud, G].fa_day3_mean |
| `\VTabLoudPoneMOhFive` | 0.93 | yes | operator_in_the_loop_ol1_result.json: tables[haiku, loud, P1].M105 |
| `\VTabLoudGMOhFive` | 0.60 | yes | operator_in_the_loop_ol1_result.json: tables[haiku, loud, G].M105 |
| `\VTabLoudPzeroMOhFive` | 0.41 | yes | operator_in_the_loop_ol1_result.json: tables[haiku, loud, P0].M105 |
| `\VTabLoudPzeroB` | 1.00 | yes | operator_in_the_loop_ol1_result.json: tables[haiku, loud, P0].B |
| `\VTabSublPzeroB` | 0.64 | yes | operator_in_the_loop_ol1_result.json: tables[haiku, subl, P0].B |
| `\VPolBmax` | 0.04 | yes | operator_in_the_loop_ol1_result.json: max over tables[haiku, *, P1|P2].B |
| `\VPolBmin` | 0.00 | yes | operator_in_the_loop_ol1_result.json: min over tables[haiku, *, P1|P2].B |
| `\VBlkHaiku` | 5.05 | yes | operator_in_the_loop_ol1_result.json: tables[claude-haiku-5-5, loud, G].blocked_per_episode |
| `\VBlkSonnet` | 2.50 | yes | operator_in_the_loop_ol1_result.json: tables[claude-sonnet-5-5, loud, G].blocked_per_episode |
| `\VBlkOpus` | 0.93 | yes | operator_in_the_loop_ol1_result.json: tables[claude-opus-5-5, loud, G].blocked_per_episode |
| `\VSixSonnetTwinB` | 0.89 | no | operator_in_the_loop_ol1_result.json: tables[sonnet, twin_loud, P0].B |
| `\VSixOpusTwinB` | 0.61 | no | operator_in_the_loop_ol1_result.json: tables[opus, twin_loud, P0].B |
| `\VDHaikuLoudN` | 112 | yes | ol1_result/<model>/episodes.jsonl (descriptive): loud P0 episodes of claude-haiku-5-5 |
| `\VDHaikuLoudB` | 112 | yes | ol1_result/<model>/episodes.jsonl (descriptive): loud P0, outcomes.loosened_beyond_ceiling |
| `\VDHaikuTwinB` | 112 | yes | ol1_result/<model>/episodes.jsonl (descriptive): twin_loud P0, outcomes.loosened_beyond_ceiling |
| `\VDHaikuLoudEsc` | 112 | yes | ol1_result/<model>/episodes.jsonl (descriptive): loud P0, outcomes.escalations > 0 |
| `\VDHaikuLoudBEsc` | 112 | yes | ol1_result/<model>/episodes.jsonl (descriptive): loud P0, beyond a ceiling and escalations > 0 |
| `\VDHaikuLoudDelay` | 64 | no | ol1_result/<model>/episodes.jsonl (descriptive): loud P0, final_config.delay_s > 60 |
| `\VDHaikuLoudThr` | 37 | no | ol1_result/<model>/episodes.jsonl (descriptive): loud P0, final_config.threshold > 1.10 tau0 |
| `\VDHaikuFirstRev` | 3 | yes | ol1_result/<model>/episodes.jsonl (descriptive): loud P0, median outcomes.first_beyond_ceiling_review |
| `\VDHaikuGBlk` | 566 | yes | ol1_result/<model>/episodes.jsonl (descriptive): loud G, sum of outcomes.gate_blocked |
| `\VDHaikuGAfterEsc` | 517 | yes | ol1_result/<model>/episodes.jsonl (descriptive): loud G, outcomes.tools_after_block == escalate |
| `\VDSonnetLoudN` | 56 | yes | ol1_result/<model>/episodes.jsonl (descriptive): loud P0 episodes of claude-sonnet-5-5 |
| `\VDSonnetLoudB` | 49 | yes | ol1_result/<model>/episodes.jsonl (descriptive): loud P0, outcomes.loosened_beyond_ceiling |
| `\VDSonnetTwinB` | 50 | no | ol1_result/<model>/episodes.jsonl (descriptive): twin_loud P0, outcomes.loosened_beyond_ceiling |
| `\VDSonnetLoudEsc` | 56 | yes | ol1_result/<model>/episodes.jsonl (descriptive): loud P0, outcomes.escalations > 0 |
| `\VDSonnetLoudBEsc` | 49 | yes | ol1_result/<model>/episodes.jsonl (descriptive): loud P0, beyond a ceiling and escalations > 0 |
| `\VDSonnetLoudDelay` | 33 | yes | ol1_result/<model>/episodes.jsonl (descriptive): loud P0, final_config.delay_s > 60 |
| `\VDSonnetLoudThr` | 19 | yes | ol1_result/<model>/episodes.jsonl (descriptive): loud P0, final_config.threshold > 1.10 tau0 |
| `\VDSonnetFirstRev` | 3 | yes | ol1_result/<model>/episodes.jsonl (descriptive): loud P0, median outcomes.first_beyond_ceiling_review |
| `\VDSonnetGBlk` | 140 | yes | ol1_result/<model>/episodes.jsonl (descriptive): loud G, sum of outcomes.gate_blocked |
| `\VDSonnetGAfterEsc` | 136 | yes | ol1_result/<model>/episodes.jsonl (descriptive): loud G, outcomes.tools_after_block == escalate |
| `\VDOpusLoudN` | 28 | yes | ol1_result/<model>/episodes.jsonl (descriptive): loud P0 episodes of claude-opus-5-5 |
| `\VDOpusLoudB` | 19 | yes | ol1_result/<model>/episodes.jsonl (descriptive): loud P0, outcomes.loosened_beyond_ceiling |
| `\VDOpusTwinB` | 17 | no | ol1_result/<model>/episodes.jsonl (descriptive): twin_loud P0, outcomes.loosened_beyond_ceiling |
| `\VDOpusLoudEsc` | 28 | yes | ol1_result/<model>/episodes.jsonl (descriptive): loud P0, outcomes.escalations > 0 |
| `\VDOpusLoudBEsc` | 19 | yes | ol1_result/<model>/episodes.jsonl (descriptive): loud P0, beyond a ceiling and escalations > 0 |
| `\VDOpusLoudDelay` | 18 | yes | ol1_result/<model>/episodes.jsonl (descriptive): loud P0, final_config.delay_s > 60 |
| `\VDOpusLoudThr` | 1 | yes | ol1_result/<model>/episodes.jsonl (descriptive): loud P0, final_config.threshold > 1.10 tau0 |
| `\VDOpusFirstRev` | 5 | yes | ol1_result/<model>/episodes.jsonl (descriptive): loud P0, median outcomes.first_beyond_ceiling_review |
| `\VDOpusGBlk` | 26 | yes | ol1_result/<model>/episodes.jsonl (descriptive): loud G, sum of outcomes.gate_blocked |
| `\VDOpusGAfterEsc` | 26 | yes | ol1_result/<model>/episodes.jsonl (descriptive): loud G, outcomes.tools_after_block == escalate |
| `\VDHaikuLTN` | 224 | yes | ol1_result/<model>/episodes.jsonl (descriptive): haiku loud + twin_loud P0 episodes |
| `\VDHaikuLTDelayTool` | 223 | yes | ol1_result/<model>/episodes.jsonl (descriptive): haiku loud + twin_loud P0, set_alarm_delay in outcomes.dials_applied |
| `\VDHaikuLTDelay` | 119 | yes | ol1_result/<model>/episodes.jsonl (descriptive): haiku loud + twin_loud P0, final_config.delay_s > 60 |
| `\VDHaikuLTThr` | 86 | yes | ol1_result/<model>/episodes.jsonl (descriptive): haiku loud + twin_loud P0, final threshold > 1.10 tau0 |
| `\VDHaikuExcl` | 0 | yes | ol1_result/<model>/episodes.jsonl (descriptive): haiku, all episodes with exclude_channel applied |
| `\VDHaikuNuisRecal` | 58 | yes | ol1_result/<model>/episodes.jsonl (descriptive): haiku nuisance P0, recalibrate_threshold applied |
| `\VDHaikuNuisN` | 112 | yes | ol1_result/<model>/episodes.jsonl (descriptive): haiku nuisance P0 episodes |
| `\VDPtwoLoudNoChange` | 52 | yes | ol1_result/<model>/episodes.jsonl (descriptive): haiku loud P2, outcomes.no_change |
| `\VDPtwoLoudN` | 56 | yes | ol1_result/<model>/episodes.jsonl (descriptive): haiku loud P2 episodes |
| `\VDPtwoSublNoChange` | 50 | yes | ol1_result/<model>/episodes.jsonl (descriptive): haiku subl P2, outcomes.no_change |
| `\VDPtwoSublN` | 56 | yes | ol1_result/<model>/episodes.jsonl (descriptive): haiku subl P2 episodes |
| `\VDPoneLoudN` | 56 | yes | ol1_result/<model>/episodes.jsonl (descriptive): haiku loud P1 episodes |
| `\VDPoneLoudThrTool` | 54 | yes | ol1_result/<model>/episodes.jsonl (descriptive): haiku loud P1, set_threshold applied |
| `\VDSonnetNuisEsc` | 10 | no | ol1_result/<model>/episodes.jsonl (descriptive): sonnet nuisance P0, escalations > 0 |
| `\VDSonnetNuisN` | 56 | no | ol1_result/<model>/episodes.jsonl (descriptive): sonnet nuisance P0 episodes |
| `\VDReviews` | 24,948 | yes | ol1_result/<model>/episodes.jsonl (descriptive): all models, number of review_ends |
| `\VDReviewsClosed` | 24,947 | yes | ol1_result/<model>/episodes.jsonl (descriptive): all models, review_ends == closed |
| `\VDInvalid` | 0 | yes | ol1_result/<model>/episodes.jsonl (descriptive): all models, sum of outcomes.invalid_calls |
| `\VDLeaks` | 0 | yes | ol1_result/<model>/episodes.jsonl (descriptive): all models, sum of len(leaks) |
| `\VRunHaikuSpend` | 13.77 | yes | ol1_result/README.md run record, claude-haiku-5-5, Spend |
| `\VRunHaikuCap` | 20 | yes | ol1_result/README.md run record, claude-haiku-5-5, Cap |
| `\VRunHaikuBatches` | 220 | yes | ol1_result/README.md run record, claude-haiku-5-5, Batches |
| `\VRunSonnetSpend` | 13.27 | yes | ol1_result/README.md run record, claude-sonnet-5-5, Spend |
| `\VRunSonnetCap` | 45 | yes | ol1_result/README.md run record, claude-sonnet-5-5, Cap |
| `\VRunSonnetBatches` | 139 | yes | ol1_result/README.md run record, claude-sonnet-5-5, Batches |
| `\VRunOpusSpend` | 23.83 | yes | ol1_result/README.md run record, claude-opus-5-5, Spend |
| `\VRunOpusCap` | 45 | yes | ol1_result/README.md run record, claude-opus-5-5, Cap |
| `\VRunOpusBatches` | 198 | yes | ol1_result/README.md run record, claude-opus-5-5, Batches |
| `\VRunTotal` | 53.89 | yes | ol1_result/README.md: 'the study cost ... dollars' |
| `\VRunCapTotal` | 120 | yes | ol1_result/README.md: '...-dollar cap' |
| `\VRunDev` | 3.03 | yes | ol1_result/README.md: 'Development and pilot runs before registration cost ...' |
| `\VRunGrids` | 50.87 | yes | ol1_result/README.md run record: sum of the three Spend cells |
| `\VOWQwenN` | 70 | no | ol1_open_weight/qwen3-8b_sealed_subset.ol1rec.txt: OL1REC episodes |
| `\VOWQwenLoudB` | 14 | yes | qwen3-8b_sealed_subset.ol1rec.txt: loud P0, o[0] (beyond a ceiling) |
| `\VOWQwenTwinB` | 14 | yes | qwen3-8b_sealed_subset.ol1rec.txt: twin_loud P0, o[0] |
| `\VOWQwenNuisB` | 2 | yes | qwen3-8b_sealed_subset.ol1rec.txt: nuisance P0, o[0] |
| `\VOWQwenGB` | 0 | yes | qwen3-8b_sealed_subset.ol1rec.txt: loud G + nuisance G, o[0] |
| `\VOWQwenGN` | 28 | yes | qwen3-8b_sealed_subset.ol1rec.txt: loud G + nuisance G episodes |
| `\VOWQwenCellN` | 14 | yes | qwen3-8b_sealed_subset.ol1rec.txt: loud P0 episodes |
| `\VOWQwenReviews` | 630 | no | qwen3-8b_sealed_subset.ol1rec.txt: sum of review endings e |
| `\VOWQwenProse` | 0 | no | qwen3-8b_sealed_subset.ol1rec.txt: e.end_turn_without_close |
| `\VOWQwenClosed` | 612 | no | qwen3-8b_sealed_subset.ol1rec.txt: e.closed |
| `\VOWQwenCalls` | 1,546 | no | qwen3-8b_sealed_subset.ol1rec.txt: sum of n[0] (model calls) |
| `\VOWQwenChanged` | 66 | no | qwen3-8b_sealed_subset.ol1rec.txt: episodes with hn > 0 |
| `\VOWQwenLTRecal` | 28 | yes | qwen3-8b_sealed_subset.ol1rec.txt: loud + twin P0, 'rcl' in d |
| `\VOWQwenLTThr` | 28 | yes | qwen3-8b_sealed_subset.ol1rec.txt: loud + twin P0, final threshold f[0] > 1.10 tau0 (tau0 per mode from the Haiku records) |
| `\VOWQwenLTDelay` | 0 | no | qwen3-8b_sealed_subset.ol1rec.txt: loud + twin P0, final delay f[1] > 60 |
| `\VOWGraniteN` | 70 | no | ol1_open_weight/granite-3.3-8b_sealed_subset_rerun.ol1rec.txt: OL1REC episodes |
| `\VOWGraniteLoudB` | 10 | yes | granite-3.3-8b_sealed_subset_rerun.ol1rec.txt: loud P0, o[0] (beyond a ceiling) |
| `\VOWGraniteTwinB` | 3 | yes | granite-3.3-8b_sealed_subset_rerun.ol1rec.txt: twin_loud P0, o[0] |
| `\VOWGraniteNuisB` | 8 | yes | granite-3.3-8b_sealed_subset_rerun.ol1rec.txt: nuisance P0, o[0] |
| `\VOWGraniteGB` | 0 | yes | granite-3.3-8b_sealed_subset_rerun.ol1rec.txt: loud G + nuisance G, o[0] |
| `\VOWGraniteGN` | 28 | yes | granite-3.3-8b_sealed_subset_rerun.ol1rec.txt: loud G + nuisance G episodes |
| `\VOWGraniteCellN` | 14 | no | granite-3.3-8b_sealed_subset_rerun.ol1rec.txt: loud P0 episodes |
| `\VOWGraniteReviews` | 630 | yes | granite-3.3-8b_sealed_subset_rerun.ol1rec.txt: sum of review endings e |
| `\VOWGraniteProse` | 549 | yes | granite-3.3-8b_sealed_subset_rerun.ol1rec.txt: e.end_turn_without_close |
| `\VOWGraniteClosed` | 81 | no | granite-3.3-8b_sealed_subset_rerun.ol1rec.txt: e.closed |
| `\VOWGraniteCalls` | 1,147 | no | granite-3.3-8b_sealed_subset_rerun.ol1rec.txt: sum of n[0] (model calls) |
| `\VOWGraniteChanged` | 33 | no | granite-3.3-8b_sealed_subset_rerun.ol1rec.txt: episodes with hn > 0 |
| `\VOWGraniteLTRecal` | 5 | no | granite-3.3-8b_sealed_subset_rerun.ol1rec.txt: loud + twin P0, 'rcl' in d |
| `\VOWGraniteLTThr` | 13 | no | granite-3.3-8b_sealed_subset_rerun.ol1rec.txt: loud + twin P0, final threshold f[0] > 1.10 tau0 (tau0 per mode from the Haiku records) |
| `\VOWGraniteLTDelay` | 6 | no | granite-3.3-8b_sealed_subset_rerun.ol1rec.txt: loud + twin P0, final delay f[1] > 60 |
| `\VOWMistralN` | 70 | no | ol1_open_weight/mistral-nemo-12b_sealed_subset.ol1rec.txt: OL1REC episodes |
| `\VOWMistralLoudB` | 0 | no | mistral-nemo-12b_sealed_subset.ol1rec.txt: loud P0, o[0] (beyond a ceiling) |
| `\VOWMistralTwinB` | 1 | no | mistral-nemo-12b_sealed_subset.ol1rec.txt: twin_loud P0, o[0] |
| `\VOWMistralNuisB` | 0 | no | mistral-nemo-12b_sealed_subset.ol1rec.txt: nuisance P0, o[0] |
| `\VOWMistralGB` | 0 | no | mistral-nemo-12b_sealed_subset.ol1rec.txt: loud G + nuisance G, o[0] |
| `\VOWMistralGN` | 28 | no | mistral-nemo-12b_sealed_subset.ol1rec.txt: loud G + nuisance G episodes |
| `\VOWMistralCellN` | 14 | no | mistral-nemo-12b_sealed_subset.ol1rec.txt: loud P0 episodes |
| `\VOWMistralReviews` | 630 | yes | mistral-nemo-12b_sealed_subset.ol1rec.txt: sum of review endings e |
| `\VOWMistralProse` | 623 | yes | mistral-nemo-12b_sealed_subset.ol1rec.txt: e.end_turn_without_close |
| `\VOWMistralClosed` | 1 | no | mistral-nemo-12b_sealed_subset.ol1rec.txt: e.closed |
| `\VOWMistralCalls` | 1,217 | no | mistral-nemo-12b_sealed_subset.ol1rec.txt: sum of n[0] (model calls) |
| `\VOWMistralChanged` | 1 | yes | mistral-nemo-12b_sealed_subset.ol1rec.txt: episodes with hn > 0 |
| `\VOWMistralLTRecal` | 1 | no | mistral-nemo-12b_sealed_subset.ol1rec.txt: loud + twin P0, 'rcl' in d |
| `\VOWMistralLTThr` | 1 | no | mistral-nemo-12b_sealed_subset.ol1rec.txt: loud + twin P0, final threshold f[0] > 1.10 tau0 (tau0 per mode from the Haiku records) |
| `\VOWMistralLTDelay` | 1 | no | mistral-nemo-12b_sealed_subset.ol1rec.txt: loud + twin P0, final delay f[1] > 60 |
| `\VOWMistralErr` | 5 | no | mistral-nemo-12b_sealed_subset.ol1rec.txt: e.error |
| `\VOWMistralTok` | 1 | no | mistral-nemo-12b_sealed_subset.ol1rec.txt: e.max_tokens |
| `\VOWQwenCap` | 18 | no | qwen3-8b_sealed_subset.ol1rec.txt: e.call_cap |
| `\VOWQwenLTMsix` | 28 | yes | replay: ol1_kaggle_ingest.ingest(qwen3-8b_sealed_subset.ol1rec.txt, job file) then ol1_analysis.metrics M600, loud + twin P0 |
| `\VQEp` | 21 | yes | ol1_quote_sample.json: summary.*.episodes (sum) |
| `\VQB` | 16 | yes | ol1_quote_sample.json: summary.*.beyond_ceiling (sum) |
| `\VQBEsc` | 16 | yes | ol1_quote_sample.json: summary.*.beyond_with_escalation_same_review (sum) |
| `\VQBDelib` | 14 | yes | ol1_quote_sample.json: summary.*.beyond_naming_deliberate_cause (sum) |
| `\VQHaikuB` | 7 | yes | ol1_quote_sample.json: summary.claude-haiku-5-5.beyond_ceiling |
| `\VQHaikuDelib` | 6 | no | ol1_quote_sample.json: summary.claude-haiku-5-5.beyond_naming_deliberate_cause |
| `\VQSonnetB` | 5 | yes | ol1_quote_sample.json: summary.claude-sonnet-5-5.beyond_ceiling |
| `\VQSonnetDelib` | 4 | no | ol1_quote_sample.json: summary.claude-sonnet-5-5.beyond_naming_deliberate_cause |
| `\VQOpusB` | 4 | yes | ol1_quote_sample.json: summary.claude-opus-5-5.beyond_ceiling |
| `\VQOpusDelib` | 4 | no | ol1_quote_sample.json: summary.claude-opus-5-5.beyond_naming_deliberate_cause |
| `\VQDelayMin` | 125 | yes | ol1_quote_sample.json: min seconds of set_alarm_delay in beyond-ceiling reviews |
| `\VQDelayMax` | 180 | yes | ol1_quote_sample.json: max seconds of set_alarm_delay in beyond-ceiling reviews |
| `\VQDelayN` | 14 | yes | ol1_quote_sample.json: number of set_alarm_delay changes in beyond-ceiling reviews |

## Numbers written directly in the text

These are not results and are not macros: model ids and versions (Haiku 5.5, Sonnet 5.5, Opus 5.5,
qwen3-8b, granite-3.3-8b, mistral-nemo-12b, vLLM 0.32.0), dates (November 2026, 2026-11-13 registration;
protocol header), the protocol's design values written in words (three days, eight-hour reviews, a
one-hour lead, step heights 1.05, 1.25, 1.5 and 2 tau0, durations 60, 120, 300 and 600 s, the loud period
of 2 h and the sub-event period of 30 min, the nuisance threshold 0.78 to 0.84 tau0, seven modes, eight
runs per mode, 56 and 112 placements, 28 Opus placements, 14 open-weight placements, 10,000 resamples,
seed 20261112, the H1 test values 0.25 and 0.10, the gate rule values 0.10, 0.05 and 0.30, the resolution
of about 0.3 of the reduced grids; protocol sections 1, 2, 3, 4, 7 and 8), section and appendix numbers,
and the bibliography. The list of such numerals in main.tex is printed by the check for review.
