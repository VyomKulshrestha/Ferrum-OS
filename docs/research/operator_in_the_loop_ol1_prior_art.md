# The operator in the loop: prior art, Kaggle limits, candidate models

Compiled 2026-11-11. Web research only (WebSearch, WebFetch, Scrapling `fetch` for JS-rendered Kaggle docs and Hugging Face API listings). Every claim below carries the URL it came from. "Opened" means I fetched that URL and read the content myself. "Search snippet only" means I saw it in a search result but did not open the primary page. "Not confirmed" means I could not verify the item from a primary page and I say what I tried.

---

## Task 1: Prior art

### 1.1 Search queries run (46)

1. `"AI Oops" AIOpsDoom USENIX Security 2026 Pasquini`
2. `LLM agent attack without prompt injection manipulated telemetry true observations SOC agent 2026 arXiv`
3. `alert fatigue attack LLM SOC agent alert flooding induce false positive closure`
4. `arxiv 2026 LLM agent manipulated by adversarial observations no instructions "environment" attack benign-looking evidence` (extended)
5. `LLM sycophancy persistent pressure multi-turn evidence persuasion changes answer arXiv`
6. `multi-turn erosion of safety policy LLM agent gradual pressure policy compliance degrades long horizon`
7. `LLM agent tuning detection rules threshold suppression rule evaluation false negatives SOC automation paper`
8. `Patton Yurcik Doss "squealing" false positives IDS RAID 2001`
9. `Stick Snot IDS alert flooding attack Snort false alarms overwhelm analyst`
10. `EEMUA 191 ISA-18.2 alarm flood definition 10 alarms per 10 minutes nuisance alarm shelving management of change`
11. `CaMeL "Defeating Prompt Injections by Design" arXiv 2503.18813`
12. `AIOpsLab holistic framework evaluate AI agents autonomous clouds arXiv`
13. `ITBench evaluating AI agents IT automation SRE CISO FinOps arXiv`
14. `CyberSOCEval benchmark LLM SOC malware analysis threat intelligence Meta CrowdStrike arXiv`
15. `ExCyTIn-Bench cyber threat investigation LLM agents benchmark arXiv`
16. `"alert fatigue" LLM agent adversarial induce agent to suppress alerts benign noise study 2026` (extended)
17. `LLM anomaly detection threshold tuning agent adversarial poisoning recalibration industrial control system`
18. `attacks on LLM-based SOC agents arXiv 2026 triage agent security evaluation adversarial alerts`
19. `LLM agent physical sensor readings manipulation spoofed sensor data mislead LLM controller decision attack paper`
20. `"boiling frog" gradual drift attack LLM agent incremental changes accepted`
21. `reward hacking via environment state LLM agent misleading but true observations "observation" manipulation without prompt injection`
22. `"misleading" truthful tool outputs LLM agent deception selective true information attack arXiv 2025 2026`
23. `Microsoft Security Copilot agent alert triage phishing triage agent false positive closure accuracy`
24. `Google Security Operations Gemini alert triage agent closes alerts autonomously`
25. `CrowdStrike Charlotte AI agentic triage detection triage autonomously closes false positives accuracy`
26. `Red Canary agentic tuning suppression rules plain language Splunk AI assistant detection tuning Elastic AI Assistant rule exceptions`
27. `Datadog Bits AI SRE monitor threshold tuning agent noisy monitor recommendations`
28. `Dropzone AI autonomous SOC analyst benchmark false negative rate Prophet Security AI SOC analyst evaluation`
29. `open source SOC agent LLM github triage alerts tune detection rules autonomous`
30. `LLM operator assistant process control alarm management large language model plant operator alarm flood study`
31. `follow-up AIOpsDoom 2026 attack LLM SRE agent remediation manipulation metrics only no logs`
32. `adversarial attack LLM time series anomaly detection perturbation fool LLM-based detector arXiv`
33. `AgentSpec runtime enforcement customizable rules LLM agents arXiv`
34. `deterministic policy enforcement tool calls LLM agent guardrail outside model allowlist argument constraints 2026 arXiv`
35. `LLM belief update accumulated in-context evidence adversarially selected examples persuasion susceptibility agents 2025`
36. `LLM detection engineering agent generates Sigma rules exclusions evaluation false negatives adversarial arXiv`
37. `poisoning adaptive threshold anomaly detection attacker-induced drift frog-boiling attack network anomaly detector`
38. `ANTIDOTE understanding and defending against poisoning of anomaly detectors Rubinstein IMC 2009`
39. `benchmark adversarial robustness LLM SOC triage agent 2026 "alert" manipulation benchmark arXiv`
40. `Elastic AI Assistant Attack Discovery create rule exception false positive; Splunk AI Assistant SecOps tuning detections`
41. `LLM agent persuaded to disable or weaken security control by legitimate looking evidence without prompt injection "configuration weakening"`
42. `"truthful" OR "benign-only" data poisoning LLM agent decision manipulation no malicious instructions operations agent 2026` (extended)
43. `LLM agent noisy alerts recommends raising threshold false positive rate study SRE agent alert tuning evaluation`
44. `kaggle_secrets UserSecretsClient get_secret Hugging Face token Kaggle notebook Add-ons Secrets official` (Task 2)
45. `Kaggle phone verification required internet access GPU notebooks site:kaggle.com` and `kaggle.com discussion product announcement phone verification required GPU internet notebooks Kaggle team` (Task 2)
46. `huggingface new open-weight instruct model tool calling 2026 Qwen3.5 OR Gemma 4 OR Llama 4.X OR Granite 4 small dense 8B 14B` (Task 3)

Closeness labels: **same question** (an LLM ops agent loosened by true, text-free signal), **neighbouring** (one of the two key properties holds), **background**.

### 1.2 Attacks on LLM-driven SOC / AIOps / log-analysis agents

**[A1] Pasquini, Kornaropoulos, Ateniese, Akgul, Theocharis, Efstathopoulos. "When AIOps Become 'AI Oops': Subverting LLM-driven IT Operations via Telemetry Manipulation." 35th USENIX Security Symposium (USENIX Security '26), pp. 4841-4860. arXiv:2508.06394 (v1 8 Aug 2025, v2 27 Aug 2025).**
- Opened: https://arxiv.org/abs/2508.06394 , https://www.usenix.org/conference/usenixsecurity26/presentation/pasquini , https://arxiv.org/html/2508.06394v2 (both halves).
- Attack: AIOpsDoom. The attacker sends ordinary HTTP requests that cause error logs; attacker strings land in logged fields (Referer, User-Agent, parameters, URL paths). **Injected text: yes.** Each payload is natural language with a plausible "lead" explaining the error and a "body" recommending a remediation, sometimes with decorators such as "[SOLUTION]". Target remediations: malicious PPA addition, service downgrade, configuration weakening.
- Result: about 90% average attack success over 36 configurations x 5 runs (AIOpsLab ReAct and Flash agents; GPT-4o, GPT-4.1; SocialNet, AstronomyShop, HotelReservation). Plain prompt injection got 0% under the same conditions. Defence AIOpsShield replaces attacker-reachable telemetry fields with abstract tokens and blocked all tested attacks.
- Limits stated by the authors: AIOpsShield "can not defend against stronger attackers" who poison other input sources; they cannot exclude other vectors. The paper does not evaluate a purely numeric or text-free manipulation. The attacker-induced errors do raise metric alerts, but the decision is steered by the text in log entries.
- Closeness: **neighbouring, the closest in setting.** Same agent class and the same harmful outcome class ("configuration weakening"), but the steering comes from injected text. Its sanitiser defence leaves untouched exactly the channel the planned study uses: true numeric telemetry.

**[A2] Pandey, Bhujang. "Poisoning the Watchtower: Prompt Injection Attacks Against LLM-Augmented Security Operations Through Adversarial Log Content." arXiv:2605.24421 (23 May 2026).**
- Opened: https://arxiv.org/abs/2605.24421
- Attack: instructions placed in attacker-controlled log fields (user agents, URLs, DNS queries, usernames). Four strategies: direct override, persona hijack, context manipulation, obfuscated payloads. **Injected text: yes.**
- Result: 48 strategy x defence x task cells with gpt-4o-mini as analyst. Direct override reached 0% suppression on classification. Persona hijack suppressed 68% of malicious logs under a naive classifier. Context manipulation reached 96% on summarisation (38% with constrained output). Mean injection success fell from 26.6% to 11.8% under the strongest defence.
- Closeness: **neighbouring** (SOC agent suppressing true positives, via text).

**[A3] Karanjai, Lu, Hegadehalli Madhavarao, Xu, Shi. "Context Contamination in LLM Analysis of Network Security Logs: Poison with Passive Prompt Injection and Mitigation Evaluation." arXiv:2607.14493 (16 Jul 2026).**
- Opened: https://arxiv.org/abs/2607.14493
- Attack: payloads in fields that log-producing services write, which persist and fire when an analyst queries the LLM. Benchmark LogInject-1.0 has 12,847 entries, 2,569 adversarial. Goals: activity concealment, false-positive generation, exfiltration, output hijacking. "Context Stitching" splits a payload across entries. **Injected text: yes.**
- Result: up to 88.2% success (mean 83.4%) across three production LLMs; Context Stitching 76.4%; layered defences cut success by 90.4%, leaving 8.4%.
- Closeness: **neighbouring.** The "false positive generation" goal is the textual cousin of a nuisance campaign.

**[A4] Piñero-Jacome, Coffey, Nguyen, Rastogi. "Evaluating the Robustness of LLM Cybersecurity Agents to Adversarial Telemetry in Security Logs." Poster, Third Workshop on Agents in the Wild, NeurIPS 2026.**
- Opened: https://neurips.cc/virtual/2026/168153
- Attack: indirect prompt injection, i.e. natural-language text in security telemetry. **Injected text: yes.** More than 1,100 payloads in four framings, five model configurations.
- Result: verdict downgrades in every configuration. Larger and thinking models were not consistently more robust. Letting the agent fetch extra read-only telemetry did not reliably neutralise the attack.
- Closeness: **neighbouring.** No arXiv ID found; I did not open a full text.

**[A5] Barnes. "OpenSec: Measuring Incident Response Agent Calibration Under Adversarial Evidence." arXiv:2601.21083 (v1 28 Jan 2026, v3 6 Feb 2026).**
- Opened: https://arxiv.org/abs/2601.21083
- Setting: dual-control RL environment; an attacker policy advances a kill chain while the defender agent acts. The abstract ties "adversarial evidence" to prompt-injection scenarios. Whether true-but-misleading evidence is included is **not confirmed** from the abstract.
- Result: GPT-5.2 contained in 100% of episodes with an 82.5% false-positive rate; Claude Sonnet 4.5 62.5% containment, 45% FP. The author's conclusion is that the gap is restraint, not detection. This is the over-reaction failure, the mirror image of loosening.
- Closeness: **neighbouring/background.**

**[A6] Tsegai, Gao. "Benchmarking LLM Agents for SOC Alert Triage: Performance and Failure Modes" (Alert-Bench). Poster, Agents in the Wild workshop, NeurIPS 2026.**
- Opened: https://neurips.cc/virtual/2026/168137
- Not an attack. 6,235 investigations over 1,247 alerts from a four-day multi-stage scenario. Every configuration missed at least 40.4% of attack-related alerts. Attack alerts were dismissed more often when queries returned no records. A revision stage overturned more correct decisions than it fixed.
- Closeness: **background, but directly useful.** It measures without any adversary the bias the planned study would exploit: an empty or quiet result reads as benign. This matches the "quiet log, so approve" failure in Thresholds That Travel.

**[A7] Golinelli, Drago, Boffa, Bergadano, Crispo. "AgentLSD: Evaluating AI Security Agents Under Adversarial Task Contamination." arXiv:2609.19140 (16 Sep 2026); listed for the 19th ACM AISec Workshop at CCS 2026.**
- Opened: https://arxiv.org/abs/2609.19140
- Attack: planted, **fabricated** artifacts (fake flags, decoy endpoints, misleading hints) in web CTF tasks. They are described as "non-instructional evidence" and contrasted with prompt injection. Whether every trap is free of instructional text is **not confirmed** from the abstract.
- Result: six models, 11 challenges; 41% clean solve rate; traps added about 20 turns and 2k reasoning tokens; some model-challenge pairs followed decoys.
- Closeness: **neighbouring.** The attack is text-free in spirit, but the evidence is false, the target is an offensive agent, and the outcome is not a loosening action.

**[A8] Zhan, Zhou, Li, Jing, Li, Haddadi. "How Adversarial Environments Mislead Agentic AI?" arXiv:2604.18874 (20 Apr 2026); Findings of ACL 2026.**
- Opened: https://arxiv.org/abs/2604.18874
- Attack: Adversarial Environmental Injection, i.e. compromised tool outputs that build a "fake world": poisoned retrieval ("Illusion") and structural traps ("Maze"). **The evidence is fabricated, not true.**
- Result: more than 11,000 trials on five frontier agents. Resistance to one attack often increased vulnerability to the other.
- Closeness: **neighbouring** (observation-space attack without instructions, but with false observations).

**[A9] Hu, Huang, Sun, Dong, Huang. "Lying with Truths: Open-Channel Multi-Agent Collusion for Belief Manipulation via Generative Montage." arXiv:2601.01685 (v1 4 Jan 2026, v2 18 May 2026); ACL 2026 main conference (oral).**
- Opened: https://arxiv.org/abs/2601.01685
- Attack: colluding agents release **only truthful evidence fragments** through public channels, with no falsified documents and no backdoors, and arrange them to induce a false belief. Dataset CoPHEME is built from real rumour events.
- Result: up to 74.4% success on proprietary and 70.6% on open-weight models across 14 families; downstream judges deceived above 60%; stronger reasoning correlated with higher susceptibility.
- Closeness: **neighbouring, the closest on mechanism.** It shows that true, selectively arranged evidence moves LLM beliefs. The domain is belief and rumour, not an operations agent taking a loosening action.

**[A10] Dorzhiev. "RIPA: Sensory-Vector Prompt Injection Attacks on LLM-Controlled ROS 2 Robots." arXiv:2606.28649 (26 Jun 2026).**
- Opened: https://arxiv.org/abs/2606.28649
- Attack: injected instructions via camera (OCR) and microphone; Channel 3 injects **fabricated** LiDAR obstacle data into the state representation.
- Result: Llama-3.3-70B 100% ASR across variants; Channel 3 on DeepSeek-V4-Flash 100%; hybrid firewall bypassed in 10.2% of obfuscated trials.
- Closeness: **background** (spoofed, i.e. false, sensor values plus text).

**[A11] Bisconti et al. (14 authors). "Boiling the Frog: A Multi-Turn Benchmark for Agentic Safety." arXiv:2605.22643 (v1 21 May 2026, v2 22 May 2026).**
- Opened: https://arxiv.org/abs/2605.22643
- Setting: chains of benign workspace edits followed by a risk-bearing request; a failure counts only if the agent puts a file into an unsafe state. The abstract does not state who issues the requests (presumably the user turn). **Not confirmed.**
- Result: aggregate strict ASR 44.4% over nine models (Claude Haiku 4.5 20.5%, Gemini 3.1 Flash Lite 92.9%); loss-of-control scenarios 93.3%.
- Closeness: **neighbouring** on dose-response and multi-turn erosion; the pressure is requests, not signal.

### 1.3 Persuasion, sycophancy and context drift (background)

- **Geng, Chen, Liu, Horta Ribeiro, Willer, Neubig, Griffiths. "Accumulating Context Changes the Beliefs of Language Models." arXiv:2511.01805 (Nov 2025).** Opened: https://arxiv.org/abs/2511.01805. GPT-5 shifted stated beliefs 54.7% after 10 rounds of discussion; Grok 4 shifted 27.2% after reading opposing texts; in tool-use tasks, behaviour shifts matched the stated-belief shifts. This supports the dose-response hypothesis (more campaign context leads to more drift). **Background.**
- Sycophancy under repeated pushback: SYCON Bench (arXiv:2505.23840), TRUTH DECAY (arXiv:2503.11656), "Consistency of Large Reasoning Models Under Multi-Turn Attacks" (arXiv:2602.13093). **Search snippet only**: https://arxiv.org/html/2505.23840v4 , https://arxiv.org/html/2503.11656v1 , https://arxiv.org/html/2602.13093v2 . **Background.** All three apply pressure through user text, not data.
- "Learning to Persuade Exposes How Easily LLMs Abandon Correct Beliefs" (arXiv:2608.11624). **Search snippet only** (https://tldr.takara.ai/p/2608.11624); not opened, details not confirmed.
- Multi-turn jailbreak erosion (Siege, arXiv:2503.10619). **Search snippet only.** Background.

### 1.4 Agents and products that tune, suppress or close (the action surface)

All are vendor or project pages; none publishes a true-positive suppression rate under adversarial conditions.

- **LimaCharlie.** Opened: https://limacharlie.io/blog/automated-false-positive-suppression-with-agentic-ai-security. The agent "creates and applies false positive suppression rules automatically, then tests to confirm"; it applies rules "directly to the tenant environment". The page describes no approval gate; the only condition is "high-confidence benign". **This is exactly the action the planned attack targets.**
- **Red Canary (Zscaler) Agentic Tuning.** Opened: https://www.zscaler.com/blogs/product-insights/ai-agentic-tuning (S. Straka, 26 Jan 2026; redirected from redcanary.com). Customers write plain-language suppression guidance; a Threat Review Agent "recommend[s] whether a threat should be suppressed or published"; matching threats are suppressed. Who reviews the customisations is not stated.
- **Datadog Bits Detection.** Opened: https://docs.datadoghq.com/bits_ai/bits_detection/. Bits "sets detection logic from observed production behavior" and "creates and tunes managed monitors", with monitors "tuned to production behavior, not static thresholds", and keeps reassessing "as your services evolve". The page mentions no approval step for threshold changes. **An autonomous agent that sets thresholds from observed behaviour, i.e. directly exposed to a truthful nuisance campaign.**
- **AiSOC (open source, MIT).** Opened: https://beenuar.github.io/AiSOC/docs/intro. "High-confidence false positives are auto-closed"; "closed-loop dashboard driven by analyst TP/FP verdicts, with auto-tune toggles per rule". No bound on how far auto-tuning may move a threshold is stated.
- **Splunk Enterprise Security 8.6+.** Search snippet only: https://help.splunk.com/en/splunk-enterprise-security-8/administer/8.6/ai-assistant-in-security-and-agentic-capabilities/ai-analysis-in-splunk-enterprise-security. Detection Builder agent can "create, tune, validate, and troubleshoot detections"; the triage agent can help close findings judged false or benign. Not opened, so **not confirmed** beyond the snippet.
- **CrowdStrike Charlotte AI Detection Triage (GA 13 Feb 2025).** Opened: https://www.crowdstrike.com/en-us/press-releases/crowdstrike-delivers-next-breakthrough-in-ai-powered-agentic-cybersecurity-with-charlotte-ai-detection-triage/. "Filtering out false positives and closing low-risk alerts"; "over 98% accuracy", defined as agreement with Falcon Complete analysts; "bounded autonomy".
- **Google SecOps Triage and Investigation Agent.** Opened: https://docs.cloud.google.com/chronicle/docs/secops/triage-agent. Determines "if the alerts are true or false positives"; "If an alert is classified as low risk, the agent concludes the investigation". No rule tuning or suppression is documented.
- **Microsoft Security Copilot Phishing Triage Agent.** RCT by J. Bono, "Randomized Controlled Trials for Phishing Triage Agent", arXiv:2511.13860 (17 Nov 2025). Opened: https://arxiv.org/abs/2511.13860. Up to 6.5x true positives per analyst minute; 77% better verdict accuracy. No adversarial evaluation.
- **Elastic, Dropzone, Prophet.** No documentation of autonomous rule or threshold tuning found in searches 26 and 28. **Not confirmed.**

### 1.5 Classical precedent: alert fatigue against humans and detectors

- **Patton, Yurcik, Doss. "An Achilles' Heel in Signature-Based IDS: Squealing False Positives in SNORT." RAID 2001.** Opened the slides: https://www.sambuz.com/doc/an-achilles-heel-in-signature-based-ids-squealing-false-ppt-presentation-754193. Squealing is "the generation of network/host data with the intent of creating false positives in IDSs" against Snort 1.6.3/1.8.1; the stated aims are to mask real attacks, misdirect analysts and poison statistics. Tools named: Stick, Snot, CASL, idswakeup and others. The paper PDF (https://homeostasis.scs.carleton.ca/~soma/id-2007w/readings/patton_yurcik_doss_raid2001.pdf) could not be text-extracted, and the Springer chapter redirected to a login, so the LNCS volume and pages are **not confirmed**.
- **Tedesco, Aickelin. "Strategic Alert Throttling for Intrusion Detection Systems." WSEAS Int. Conf. on Information Security 2005; arXiv:0801.4119.** Opened: https://arxiv.org/abs/0801.4119. Alert floods hide real attacks; defence is a token-bucket throttle with attack-graph-guided correlation.
- **Rubinstein, Nelson, Huang, Joseph, Lau, Rao, Taft, Tygar. "ANTIDOTE: Understanding and Defending against Poisoning of Anomaly Detectors." IMC 2009, DOI 10.1145/1639562.1639592.** The PDF (https://ptolemy.berkeley.edu/projects/truststc/pubs/725/IMC.2009.pdf) did not text-extract. Bibliographic details and the "Boiling Frog" gradual poisoning of PCA detectors (search snippet: 5% weekly increase over 3 weeks matches an 18% one-shot increase in raising FNR from 4% to 50%) are **from search snippets only**. **Background:** the original boiling-frog campaign, against a statistical detector rather than an LLM.
- **Kravchik, Shabtai. "Can't Boil This Frog: Robustness of Online-Trained Autoencoder-Based Anomaly Detectors to Adversarial Poisoning Attacks." arXiv:2002.02741 (Feb 2020).** Opened: https://arxiv.org/abs/2002.02741. ICS autoencoder; poisoning works only for a small set of attack types and magnitudes; SWaT detector resisted all ten relevant attacks. Background.
- **Process alarm management.** Opened: https://www.chemengonline.com/alarm-management-numbers/. EEMUA 191: a flood starts at more than 10 new alarms in 10 minutes and continues until a 10-minute interval has fewer than 5. Nuisance alarms are flagged when the top ten sources produce over 20% of alarms. Chattering is commonly 3 or more activations in one minute, fixed with on/off-delay and hysteresis (the "lengthen alarm delay" lever in the planned study). ISA-18.2 flood numbers were not on this page; **not confirmed** from a primary source (the standards themselves are paywalled).
- **LLM alarm assistants in process control.** Honeywell Experion Operations Assistant and Emerson Ovation AI found only via search snippets (https://hydrocarbonprocessing.com/news/2026/03/honeywell-s-commercial-launch-of-ai-powered-control-room-assistant-follows-successful-pilot/ , https://www.emerson.com/en/automation-systems/ovation/ovation-ai/what-is-ai-assisted-operation-in-power-plants). Not opened. **No security evaluation found.**

### 1.6 Defences with a deterministic policy outside the model

- **CaMeL.** Debenedetti, Shumailov, Fan, Hayes, Carlini, Fabian, Kern, Shi, Terzis, Tramèr. "Defeating Prompt Injections by Design." arXiv:2503.18813 (v1 24 Mar 2025, v2 24 Jun 2025). Opened: https://arxiv.org/abs/2503.18813. Control and data flow come from the trusted query; a custom interpreter tracks provenance and enforces capability policies. 77% of AgentDojo tasks solved with provable security vs 84% undefended. **Limit for this study:** CaMeL stops untrusted data from changing program flow. If the trusted task itself is "tune the noisy detector", true data legitimately decides the argument (the new threshold), so CaMeL alone would not stop a truthful campaign. An argument-level policy is needed.
- **Progent.** Shi, He, Wang, Li, Wu, Guo, Song. "Progent: Securing AI Agents with Privilege Control." arXiv:2504.11703 (v1 16 Apr 2025, v3 14 May 2026). Opened: https://arxiv.org/abs/2504.11703. Symbolic rules over tool names and **arguments**, checked deterministically on each call; policy updates verified by an SMT solver; **"narrowing updates apply automatically, while expansions require explicit approval."** Evaluated on AgentDojo and ASB. This is the closest existing design to "tighten freely, loosen only to a fixed ceiling", applied to the agent's own privileges rather than to a detector threshold.
- **AgentSpec.** Wang, Poskitt, Sun. "AgentSpec: Customizable Runtime Enforcement for Safe and Reliable LLM Agents." ICSE 2026 (Proc. pp. 2938-2950); arXiv:2503.18666. Opened: https://arxiv.org/abs/2503.18666. Trigger/predicate/enforcement DSL; prevents unsafe executions in over 90% of code-agent cases; millisecond overhead.
- **Sigdel, Baral. "Guardrails as Infrastructure: Policy-First Control for Tool-Orchestrated Workflows."** arXiv:2603.18059 (18 Mar 2026). Opened: https://arxiv.org/abs/2603.18059. Model-agnostic permission layer; 225 controlled runs; stricter packs raised violation prevention from 0.000 to 0.681 while task success fell from 0.356 to 0.067. Simulation only, no live LLM.
- **Approval fatigue as an agent-governance attack.** WorkOS blog (5 Aug 2026), opened: https://workos.com/blog/approval-fatigue-agent-governance. It cites rule ATR-2026-00118 "Human Approval Fatigue Exploitation" (Agent Threat Rules catalogue, Mar 2026); that rule was **not opened**. Relevant because a ceiling-plus-human-approval gate can be attacked by flooding the human with approval requests.

### 1.7 Benchmarks

| Benchmark | Citation (opened URL) | Adversarial? | Relevance |
|---|---|---|---|
| AgentDojo | Debenedetti, Zhang, Balunović, Beurer-Kellner, Fischer, Tramèr, arXiv:2406.13352 (https://arxiv.org/abs/2406.13352); 97 tasks, 629 security cases. NeurIPS 2024 D&B venue is not stated on the abs page: **not confirmed** | Prompt injection via tool output | Defence-evaluation baseline |
| InjecAgent | Zhan, Liang, Ying, Kang, ACL 2024 Findings, arXiv:2403.02691 (https://arxiv.org/abs/2403.02691); 1,054 cases; ReAct GPT-4 attacked 24% | Indirect prompt injection | Background |
| ASB | Zhang et al., ICLR 2025, arXiv:2410.02644 (https://arxiv.org/abs/2410.02644); max average ASR 84.30% | Injection, memory poisoning, backdoor | Background |
| AgentHarm | Andriushchenko et al., ICLR 2025, arXiv:2410.09024 (https://arxiv.org/abs/2410.09024); 110 malicious tasks | Harmful user requests | Background |
| AIOpsLab | Chen et al., arXiv:2501.06706 (https://arxiv.org/abs/2501.06706) | No (fault injection for RCA) | Possible host environment; AIOpsDoom used its agents |
| ITBench | Jha et al. (44 authors), arXiv:2502.05352 (https://arxiv.org/abs/2502.05352); v1: SRE 13.8%, CISO 25.2%, FinOps 0%. ICML 2025 version via search snippet only | No | Possible host environment |
| CyberSOCEval | Deason, Bali et al., arXiv:2509.20166 (https://arxiv.org/abs/2509.20166) | No | Background |
| ExCyTIn-Bench | Wu et al., arXiv:2507.14201, accepted ICML 2026 (https://arxiv.org/abs/2507.14201); 57 Sentinel tables, 7,542 questions, best reward 0.606 | No | Background |
| Alert-Bench | see A6 | No | Shows the "no records means benign" bias |
| OpenSec | see A5 | Yes (injection) | Calibration metrics worth borrowing |
| SecBench | Not searched separately; **not confirmed** | | |

No benchmark found tests numeric, text-free alarm streams against a tuning or suppression agent.

### 1.8 Verdict

No one has shown an LLM operations agent being led to loosen a detector by true, text-free signal manipulation. I searched 43 queries on this topic and opened every candidate. Every attack on SOC, AIOps or log agents I found (AIOpsDoom [A1], Poisoning the Watchtower [A2], LogInject/Context Contamination [A3], the NeurIPS 2026 adversarial-telemetry poster [A4]) steers the agent with injected natural-language text. AIOpsDoom's own baseline shows the steering lives in that text. Text-free attacks on agents (AEI [A8], AgentLSD [A7], RIPA channel 3 [A10]) use fabricated evidence and do not target detector tuning. The one study that uses only true evidence (Lying with Truths [A9]) manipulates beliefs about rumours, not an operations agent's actions. Meanwhile, shipping products already let agents create suppression rules (LimaCharlie), set thresholds from observed behaviour (Datadog Bits Detection) and auto-tune rule noise (AiSOC), with no published loosening bound.

**Three closest works:**
1. Pasquini et al., AIOpsDoom (USENIX Security 2026). It has the same agent class and "configuration weakening" as a target. It differs on two counts: the attack is injected text, and the text-sanitising defence leaves true numeric telemetry unaddressed.
2. Hu et al., "Lying with Truths" (ACL 2026). It uses the same mechanism, only true evidence arranged adversarially. It differs because it targets beliefs about rumours and involves no tools or thresholds.
3. Golinelli et al., AgentLSD (AISec 2026). Its attack is non-instructional environmental evidence against security agents. It differs because the evidence is fabricated and the agents are CTF solvers. Runner-up: Progent, the closest defence, whose rule is narrowing automatic and expansion approved.

**What the planned study would add:**
- the first attacker model limited to the physical or process signal, with every alarm a true record;
- loosening actions (threshold raise, suppression, delay, recalibration) as the measured outcome, against a benign nuisance-alarm control;
- dose-response with campaign length, linked to the context-drift result of Geng et al.;
- a test of whether a written policy holds under sustained truthful pressure;
- an argument-level asymmetric gate (tighten free, loosen to a fixed ceiling). This applies Progent's narrowing-versus-expansion idea to detector parameters, and it closes the gap that text sanitisation (AIOpsShield) and control-flow isolation (CaMeL) cannot.

---

## Task 2: Kaggle as the GPU

Official pages opened (rendered with Scrapling because they are JavaScript-only):
- K1: https://www.kaggle.com/docs/notebooks
- K2: https://www.kaggle.com/docs/efficient-gpu-usage
- K3: https://www.kaggle.com/docs/models
- K4: https://github.com/Kaggle/kaggle-api/blob/main/docs/kernels_metadata.md (official Kaggle API repository)
- K5: https://github.com/Kaggle/kaggle-api/blob/main/docs/kernels.md
- N1: https://www.nvidia.com/en-us/data-center/tesla-t4/ (T4 memory)

| Item | Value | Source |
|---|---|---|
| GPU types | "1 Nvidia Tesla P100 GPU" and "2 Nvidia Tesla T4 GPUs" (T4 x2); TPU v3-8 / "TPU 1VM" | K1 |
| Other accelerators via API | `machine_shape` / `--accelerator` examples: `NvidiaTeslaT4` (default GPU), `NvidiaL4`, `TpuV5E8`, `TpuV6E8`; "some accelerators are limited to specific competition participants" or admins. Whether L4 is available to ordinary users: **not confirmed** | K4, K5 |
| GPU memory | Not stated on Kaggle pages. T4 = "16 GB GDDR6" (N1). P100 memory: **not confirmed** (no official page opened) | N1 |
| Weekly GPU quota | "The quota resets weekly and is 30 hours or sometimes higher depending on demand and resources" | K2 |
| Colab Pro bonus | "Colab Pro and Pro+ users will get 15 and 30 hours of extra GPU hours per week" (experimental promotion) | K1 |
| Session length | "12 hours execution time for CPU and GPU notebook sessions and 9 hours for TPU notebook sessions" | K1 |
| Committed run ("Save & Run All") | "the entire Notebook must execute within 12 hours (9 hours for TPU notebooks)" | K1 |
| Interactive idle timeout | K1: "20 minutes of idle time for your interactive session". K2: "Interactive sessions remain active until they reach the 60 minute idle timeout limit". **The two official pages disagree.** | K1, K2 |
| CPU / RAM | CPU-only: 4 cores, 30 GB RAM. P100: 4 cores, 29 GB RAM. T4 x2: 4 cores, 29 GB RAM. TPU 1VM: 96 cores, 330 GB RAM | K1 |
| Disk | "20 Gigabytes of auto-saved disk space (/kaggle/working)" plus unsaved scratch space (size not stated) | K1 |
| Internet | Toggle in Session options; "make sure 'Internet' is enabled in the Settings pane (it will be by default if it's a new notebook)" | K1 |
| Phone verification for GPU/internet | **Not confirmed on an official page.** Third-party guides agree it is required (e.g. https://course.fast.ai/Resources/kaggle.html , https://hsf-training.github.io/hsf-training-ml-gpu-webpage/setup.html ; search snippets). The only official hit is a product-announcement title "Phone verification is required for public Models" (https://kaggle.com/product-announcements, not opened) | — |
| CLI run | `kaggle kernels push` "Pushes new code/notebook and metadata to a kernel, then runs the kernel"; flags `--accelerator <ID>`, `-t/--timeout <SECONDS>`, `--no-run`. `kaggle kernels status` reports running/complete/failed. `kaggle kernels output` downloads output files (`--file-pattern`). `kaggle kernels init` creates the metadata template. K2 recommends the API to avoid interactive sessions | K5, K2 |
| kernel-metadata.json | `is_private` (default true), `enable_gpu` (default false), `enable_internet` (default false), `machine_shape`, `dataset_sources` ("username/dataset-slug"), `model_sources` ("owner/model/framework/variation/version"), `kernel_sources`, `competition_sources` | K4 |
| Private dataset via API | Listed in `dataset_sources`; whether a private dataset owned by the same user attaches without extra steps is not stated explicitly. **Not confirmed** (expected to work for the owner) | K4 |
| Model weights | Kaggle Models attach via "Add Input"; gated models need licence acceptance first. "If you are downloading a Hugging Face model in your notebook, e.g., by using the Transformers library, you don't have to do anything special." Download outside Kaggle via kagglehub, CLI or API with `KAGGLE_USERNAME`/`KAGGLE_KEY` | K3 |
| HF token as Kaggle secret | `kaggle_secrets.UserSecretsClient().get_secret("HF_TOKEN")` via Add-ons > Secrets is the usual pattern, but **not confirmed on an official Kaggle page** (only community code, e.g. https://huggingface.co/Anthonyg5005/hf-scripts/blob/main/HF%20Login%20Snippet%20Kaggle.py). One community report says secret bindings may not survive a CLI push (https://huggingface.co/spaces/cuilabs/bee/blob/main/scripts/bootstrap_kaggle_secrets.py). **Unverified; test before relying on it.** For gated Llama/Gemma weights, attaching the Kaggle Models copy avoids the token entirely | — |

Practical notes (my inference, not from the pages):
- The T4 is Turing (compute capability 7.5, **not confirmed** from N1). It has no bf16, so use fp16 or 4-bit (bitsandbytes NF4, AWQ or GPTQ).
- gpt-oss MXFP4 kernels target newer GPUs, so gpt-oss-20b on T4 may fall back to bf16 dequantisation and not fit. Test it before committing.
- 30 h a week at 12 h per run is roughly 2.5 full committed runs per week. Plan sweeps in sub-12 h shards with resumable outputs in `/kaggle/working`.

---

## Task 3: Open-weight models that fit

Fit rule: 4-bit weights are about 0.5 to 0.6 bytes per parameter, plus KV cache and overhead. "Approx 4-bit" below is **my arithmetic, not from the model cards**, unless stated. One T4 is 16 GB; T4 x2 is 32 GB split across two cards.

| HF repo id (card opened) | Params | Licence | Tool calling on card | Approx 4-bit weights | Gated |
|---|---|---|---|---|---|
| `Qwen/Qwen3-8B` | 8.2B | Apache-2.0 | Yes ("excels in tool calling", Qwen-Agent) | ~5-6 GB, one T4 | No notice shown |
| `Qwen/Qwen3-14B` | 14.8B | Apache-2.0 | Yes | ~9-10 GB, one T4 | No notice shown |
| `Qwen/Qwen3.5-9B` (Feb 2026; vision encoder; thinking by default) | 9B (10B incl. vision) | Apache-2.0 | Yes (tool-call parser flags, Qwen-Agent) | ~6-7 GB, one T4 | No notice shown |
| `Qwen/Qwen3.5-27B` (official `Qwen/Qwen3.5-27B-GPTQ-Int4` exists per HF API listing) | 27B (28B incl. vision) | Apache-2.0 | Yes (`qwen3_coder` parser) | ~15-17 GB, T4 x2 | No notice shown |
| `Qwen/Qwen3-30B-A3B-Instruct-2507` (MoE) | 30.5B total / 3.3B active | Apache-2.0 | Yes | ~17-19 GB, T4 x2 | Not stated |
| `meta-llama/Llama-3.1-8B-Instruct` (standard baseline) | 8B | Llama 3.1 Community | Yes ("Tool use with transformers") | ~5-6 GB, one T4 | **Yes (gated)** |
| `mistralai/Mistral-Nemo-Instruct-2407` | 12B | Apache-2.0 | Yes (mistral_inference and transformers; 9-char tool-call IDs) | ~7-8 GB, one T4 | No notice shown |
| `mistralai/Mistral-Small-3.2-24B-Instruct-2506` | 24B | Apache-2.0 | Yes (via vLLM); card: "~55 GB of GPU RAM in bf16" | ~14-15 GB, T4 x2 | No notice shown |
| `mistralai/Ministral-3-14B-Instruct-2512` | 14B (13.5B LM + 0.4B vision) | Apache-2.0 | Yes (`--tool-call-parser mistral`); card: "24GB of VRAM in FP8" | ~9 GB, one T4 | Not stated |
| `google/gemma-4-12B-it` (official QAT q4_0 and w4a16 variants listed) | 11.95B | Card tag apache-2.0 but links to Gemma 4 licence: **unclear** | Yes ("native function-calling support"; no example) | ~7-8 GB, one T4 | Not stated |
| `ibm-granite/granite-4.2-8b` (released 25 Aug 2026; post-trained for tool use) | 8B | Apache-2.0 | Yes ("Tool Calling" section, vLLM/SGLang) | ~5-6 GB, one T4 | Not stated |
| `ibm-granite/granite-3.3-8b-instruct` | 8B | Apache-2.0 | Listed ("Function-calling tasks"), no example | ~5-6 GB | No notice shown |
| `microsoft/Phi-4-mini-instruct` | 3.8B | MIT | Yes (`<|tool|>` format) | ~2.5 GB | No notice shown |
| `NousResearch/Hermes-3-Llama-3.1-8B` | 8B | llama3 | Yes (`<tools>` / `<tool_call>` format) | ~5-6 GB | Not stated |
| `openai/gpt-oss-20b` | 21B total / 3.6B active | Apache-2.0 | Yes (function calling, harmony format required) | Card: MXFP4 "run within 16GB of memory"; T4 support **not confirmed** | Not stated |

Cards opened: https://huggingface.co/Qwen/Qwen3-8B , https://huggingface.co/Qwen/Qwen3-14B , https://huggingface.co/Qwen/Qwen3.5-9B , https://huggingface.co/Qwen/Qwen3.5-27B , https://huggingface.co/Qwen/Qwen3-30B-A3B-Instruct-2507 , https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct , https://huggingface.co/mistralai/Mistral-Nemo-Instruct-2407 , https://huggingface.co/mistralai/Mistral-Small-3.2-24B-Instruct-2506 , https://huggingface.co/mistralai/Ministral-3-14B-Instruct-2512 , https://huggingface.co/google/gemma-4-12B-it , https://huggingface.co/ibm-granite/granite-4.2-8b , https://huggingface.co/ibm-granite/granite-3.3-8b-instruct , https://huggingface.co/microsoft/Phi-4-mini-instruct , https://huggingface.co/NousResearch/Hermes-3-Llama-3.1-8B , https://huggingface.co/openai/gpt-oss-20b , https://huggingface.co/Qwen/Qwen2.5-7B-Instruct , https://huggingface.co/google/gemma-3-12b-it .
Listings opened: https://huggingface.co/api/models?author=google&search=gemma-4 , https://huggingface.co/api/models?author=Qwen&search=Qwen3.5 , https://huggingface.co/api/models?author=ibm-granite&search=granite-4 , https://huggingface.co/api/models?author=meta-llama&sort=lastModified .

Excluded or caveated:
- `Qwen/Qwen2.5-7B-Instruct` (7.61B, Apache-2.0, not gated). The card **does not mention tool calling**; the chat template's tool support is not confirmed from the card. It is usable as a legacy baseline only if the template is checked.
- `google/gemma-3-12b-it` (12B, Gemma licence, gated). The card **does not document tool calling**.
- Llama 4 Scout/Maverick (17B active, 109B+ total) do not fit. Meta's HF listing shows no new small Llama after Llama 4.
- DeepSeek-R1 distills: card not opened; native tool calling **not confirmed**.

Suggested panel of eight (my choice): Qwen3-8B, Qwen3.5-9B, Llama-3.1-8B-Instruct, Mistral-Nemo-Instruct-2407, Granite-4.2-8B, Gemma-4-12B-it (one T4 each); Mistral-Small-3.2-24B and Qwen3.5-27B (T4 x2). This covers five vendors, dense and thinking-by-default variants, and two sizes.
