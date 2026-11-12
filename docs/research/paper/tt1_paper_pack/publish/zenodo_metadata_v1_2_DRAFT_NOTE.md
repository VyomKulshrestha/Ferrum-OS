# DRAFT: Zenodo metadata for preprint version 1.2

`zenodo_metadata_v1_2.json` is a draft prepared on 2026-11-12. Nothing has been uploaded or published, and
no DOI has been reserved. It follows `zenodo_metadata_v1_1.json` field for field. The changes are the
version (1.2), the file block (name, size, MD5 and SHA-256 of `Thresholds_That_Travel_preprint_v1.2.pdf`),
the record it becomes a new version of (24123217, the published v1.1), the last paragraph of the
description, and the removal of the `published` block, which is filled in after publication.

The first three paragraphs of the description are v1.1's, unchanged, because the paper's abstract did not
change between v1.1 and v1.2. The last paragraph names the three differences from v1.1:

1. the exploratory tt1g round (rules from alarm practice, recalibration as a rule, related work on how a
   detection is counted), from commit 3d4ec15, `protocols/threshold_transfer_tt1g_dev_plan.md` and Section
   "Rules from alarm practice (exploratory)" of the paper;
2. the appendix headings named as the ASIA CCS 2027 call names them, from commit 7217f5f;
3. the exploratory post-hoc paragraph on alarm time outside the fitted range, from the fi2 papers commit
   7dd0c17 and `docs/research/fi1_monitor_round1.json`, `fi1_monitor_round2.json`.

As for v1.1, neither the preprint nor this metadata carries a generative-AI statement; the conference copies
keep theirs.

Before publishing: on Zenodo, open record 24123217, choose "New version", upload the PDF, check its MD5
against the `file` block, paste the fields, publish, then add a `published` block as in v1.1 and update ORCID.
