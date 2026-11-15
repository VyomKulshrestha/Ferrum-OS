# ol1 paper: references checked

Every entry of `latex/refs.bib` was checked on 2026-11-15, in the session that wrote the paper, against the
source's own page: the arXiv abstract page, the proceedings or publisher page, the DOI record through the
Crossref API (`api.crossref.org/works/<doi>`; the ACM Digital Library itself answered 403 to the fetch
tool), or the standards body's catalogue page. Nothing was cited from memory. Entries reused from the
"Thresholds That Travel" `refs.bib` were checked again the same way.

31 entries, 31 confirmed.

| Key | URL opened | Confirmed |
|---|---|---|
| kulshrestha2026tt1 | https://zenodo.org/records/24123217 | title, author (Vyom Kulshrestha, Independent Researcher), version 1.1, 11 Nov 2026, DOI 10.5281/zenodo.24123217 |
| isa182 | https://www.isa.org/products/ansi-isa-18-2-2016-management-of-alarm-systems-for ; https://www.exida.com/Blog/new-version-of-isa-18.2-alarm-management-standard-is-released-2016 | title and designation ISA-18.2-2016 (ISA page); the 2016 edition and alarm shelving as required functionality (exida page). The paper cites it only for the alarm-management lifecycle, not for specific clauses |
| iec62682 | https://webstore.iec.ch/en/publication/65543 (and /7363 for the 2014 edition) | title, IEC 62682:2022, edition 2.0, published 2022-12-08; abstract: general principles and processes for the management of alarm systems; the 2014 page states lifecycle management |
| eemua191 | https://eemua.org/getattachment/9d3f8071-55c3-49bf-a74a-3bf6ad4a2e0f/Contents-EEMUA-Publication-191-Edition4-November-2024.pdf (contents pages, text extracted) | title, Publication 191, fourth edition 2024, copyright 2024 EEMUA; contents include 5.7 Shelved and suppressed alarms, 6.1.3 Minimising unnecessary and nuisance alarms, 6.3 Alarm suppression, 6.5 Alarm shelving, 8 Management of change |
| rubinstein2009antidote | https://api.crossref.org/works/10.1145/1644893.1644895 | title, eight authors, Proceedings of the 9th ACM SIGCOMM Conference on Internet Measurement, 2009, pp. 1-14, DOI. (The ol1 prior-art notes give DOI 10.1145/1639562.1639592 from a search snippet; the Crossref record of 10.1145/1644893.1644895 is the one confirmed here.) |
| atarmla2026price | https://arxiv.org/abs/2609.23254 | title, sole author Abdou-Raouf Atarmla, v1 19 Sep 2026, no venue |
| kravchik2021poisoning | https://api.crossref.org/works/10.1145/3412841.3441892 | title, authors Kravchik, Biggio, Shabtai, SAC '21, pp. 116-125 |
| pasquini2026aiops | https://arxiv.org/abs/2508.06394 ; https://www.usenix.org/conference/usenixsecurity26/presentation/pasquini | title, six authors, 35th USENIX Security Symposium 2026, pp. 4841-4860; abstract: adversaries manipulate system telemetry to mislead AIOps agents |
| alahmadi2022falsepositives | https://www.usenix.org/conference/usenixsecurity22/presentation/alahmadi | title, authors Alahmadi, Axon, Martinovic, 31st USENIX Security Symposium 2022, pp. 2783-2800 |
| hassan2019nodoze | https://www.ndss-symposium.org/ndss-paper/nodoze-combatting-threat-alert-fatigue-with-automated-provenance-triage/ | title, seven authors, NDSS; year 2019 from the paper's file name on that page (no DOI given there, none cited) |
| greshake2023indirect | https://arxiv.org/abs/2302.12173 ; https://api.crossref.org/works/10.1145/3605764.3623985 | title, six authors, Proceedings of the 16th ACM Workshop on Artificial Intelligence and Security (AISec, at CCS '23), 2023, pp. 79-90 |
| zhan2024injecagent | https://arxiv.org/abs/2403.02691 | title, authors Zhan, Liang, Ying, Kang; comment "ACL 2024 Findings" |
| debenedetti2024agentdojo | https://arxiv.org/abs/2406.13352 ; https://proceedings.neurips.cc/paper_files/paper/2024/hash/97091a5177d8dc64b1da8bf3e1f6fb54-Abstract-Datasets_and_Benchmarks_Track.html | title, six authors, NeurIPS 2024 (vol. 37) Datasets and Benchmarks Track, DOI 10.52202/079017-2636 |
| zhang2025asb | https://arxiv.org/abs/2410.02644 | title, eight authors with full names, comment "Accepted by ICLR 2025" |
| debenedetti2025camel | https://arxiv.org/abs/2503.18813 | title, ten authors, 2025, no venue; abstract: control flow from the trusted query, untrusted data "can never impact the program flow" |
| shi2025progent | https://arxiv.org/abs/2504.11703 | title, seven authors, 2025, no venue; abstract: every tool call checked against a policy by a deterministic procedure, rules over tool names and arguments |
| wang2026agentspec | https://arxiv.org/abs/2503.18666 | title, authors Wang, Poskitt, Sun; ICSE 2026, Proc. pp. 2938-2950 |
| parasuraman1997humans | https://api.crossref.org/works/10.1518/001872097778543886 | title, authors Parasuraman and Riley, Human Factors 39(2), 1997, pp. 230-253 |
| parasuraman2010complacency | https://api.crossref.org/works/10.1177/0018720810376055 | title, authors Parasuraman and Manzey, Human Factors 52(3), 2010, pp. 381-410 |
| skitka1999automation | https://api.crossref.org/works/10.1006/ijhc.1999.0252 | title, authors Skitka, Mosier, Burdick, IJHCS 51(5), 1999, pp. 991-1006 |
| sharma2024sycophancy | https://arxiv.org/abs/2310.13548 ; https://proceedings.iclr.cc/paper_files/paper/2024/hash/0105f7972202c1d4fb817da9f21a9663-Abstract-Conference.html | title, 19 authors (arXiv), ICLR 2024 (proceedings page) |
| geng2025accumulating | https://arxiv.org/abs/2511.01805 | title, seven authors, Nov 2025, no venue; abstract: stated beliefs and tool-use behaviour shift with accumulated context |
| hu2026lying | https://arxiv.org/abs/2601.01685 | title, five authors, comment "Accepted to the ACL 2026 Main Conference (Oral Presentation)" |
| bisconti2026boiling | https://arxiv.org/abs/2605.22643 | title, first author Piercosma Bisconti, 14 authors (cited as "and others"), May 2026, no venue |
| dhananjeyan2026ratchet | https://arxiv.org/abs/2608.31062 | title, authors Dhananjeyan and U, 31 Aug 2026; summary: exclusions in the SigmaHQ corpus accumulate and persist |
| barnes2026opensec | https://arxiv.org/abs/2601.21083 | title, sole author Jarrod Barnes, Jan 2026, no venue |
| deason2025cybersoceval | https://arxiv.org/abs/2509.20166 | title, 23 authors (first three named, "and others"), Sep 2025, no venue |
| wu2026excytin | https://arxiv.org/abs/2507.14201 | title, twelve authors, comment "Accepted By ICML 2026" |
| bono2025rct | https://arxiv.org/abs/2511.13860 | title, sole author James Bono, 17 Nov 2025, no venue |
| filonov2017tep | https://arxiv.org/abs/1709.02232 | title, three authors, comment "ICML 2017 Time Series Workshop" |
| downs1993tep | https://api.crossref.org/works/10.1016/0098-1354(93)80018-I | title, authors J. J. Downs and E. F. Vogel (initials only in the record; the bib uses initials), Computers & Chemical Engineering 17(3), 1993, pp. 245-255 |

## Looked for and not used

- The ACM Digital Library pages for the ACM entries returned HTTP 403 to the fetch tool; the Crossref DOI
  records were used instead.
- The ISA-18.2 product page carries no description of the standard's content, so the paper does not cite
  ISA-18.2 for any specific clause (shelving, suppression, management of change); those topics are cited to
  the EEMUA 191 contents pages, which were read.
- The ACL 2026 proceedings number for hu2026lying ("64th Annual Meeting") was not confirmed and is not in
  the entry.
- Vendor product pages about alert-triage or detection-tuning agents were not cited.
