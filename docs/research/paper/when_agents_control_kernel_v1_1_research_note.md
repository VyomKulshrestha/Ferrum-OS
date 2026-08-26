# When Agents Control the Kernel, Revisited

## Request-Bounded Deterministic Authority with an Action-Conditioned JEPA Forecast

Technical Research Note v0.1 - 26 August 2026

Vyom Kulshrestha
Independent Researcher, India
ORCID: 0009-0009-1434-7148

### Abstract

We revisit the FerrumOS pre-execution safety runtime after the published *When
Agents Control the Kernel* study. The earlier report established a hybrid
deterministic-plus-JEPA gate but reported 81.4% balanced accuracy and retained
substantial false negatives. We register incident-informed development and
source-held-out catalogs from official postmortems, recover and verify the exact
13,697-row public transition corpus, and preserve four failed iterations before
evaluating v3.4. The frozen JEPA candidate improves normalized rollout error on
the untouched published test partition at H=1, H=3, and H=5 by 9.54%, 2.36%, and
0.92%, respectively (4.35% geometric improvement versus deployed runtime-v2).
On a new 512-episode source-held-out deterministic simulator, the v3.4 policy
records 100% balanced accuracy, no missed simulated hazards, and no blocked safe
controls; the paired source-stratified balanced-accuracy improvement over
runtime-v2 has a 95% bootstrap interval of +46.35 to +48.82 percentage points.
Crucially, the final safety outcome is identical for rules-only and rules+JEPA.
It therefore demonstrates deterministic authority and integration, not
incremental learned safety value. The candidate is archived but not deployed:
runtime authority remains unverified, and authored simulator resource deltas
are not treated as empirical OS effects.

### 1. Research question and contribution

The practical question is not whether a neural model should control an
operating-system kernel. It should not. The question is whether a learned
action-conditioned forecast can improve state prediction while deterministic
policy, capabilities, and confirmation retain execution authority.

This note contributes:

1. A digest-bound v3-v3.4 lineage with preregistered development and final gates, retained negative results, and a final catalog denied to all validation-only scripts.
2. An incident-informed benchmark derived defensively from official GitLab, AWS, Fastly, Meta, Microsoft, Cloudflare, Atlassian, GitHub, Google Cloud, Dropbox, and CrowdStrike reports, with no exploit payloads or claims of incident replay.
3. A frozen FWM2 candidate that improves all three untouched-corpus rollout horizons over runtime-v2.
4. A request-bounded authority rule: when an action has an exact registered deterministic effect, authority scores the requested step rather than unrequested hypothetical repetitions. JEPA may add caution only where the deterministic effect is not exact.
5. An explicit non-promotion result separating a research improvement from a deployed-system claim.

### 2. System and authority boundary

FerrumOS normalizes a proposed tool call, captures an OS snapshot, and computes
deterministic and learned next-state forecasts in the ring-3 Heliox daemon. A
predictive allow grants no capability: kernel syscall checks and operator
confirmation remain independent. A learned forecast is monotone caution; it may
block an otherwise permitted proposal but may never erase a deterministic
block.

v3 introduced canonical protected-path writes and deletes, critical-service
stops, and an absolute process-occupancy rule. v3.4 additionally separates
forecast horizon from execution authority. For covered actions the authority
decision evaluates the requested deterministic step. Multi-horizon JEPA output
remains useful for prediction and telemetry, but an imagined repetition is not
itself an authorized request.

### 3. Evidence design

#### 3.1 Frozen lineage

The public dataset DOI is 10.5281/zenodo.21829193 and the published report DOI is
10.5281/zenodo.21829808. The recovered corpus contains 13,697 rows and matches
the public archive and source digests. The deployed runtime-v2 transition SHA-256
is `f6bf2e50...9cf0dc8`; the selected v3/v3.4 candidate SHA-256 is
`2616aa6b...444f77`.

#### 3.2 Incident sources and abstraction

Development sources were partitioned before candidate selection. A separate
final source catalog was frozen and denied to validation scripts. Its four
official postmortems describe: inadvertent disablement of Cloudflare's R2
Gateway; a Dropbox maintenance script reinstalling active database machines; a
Google Cloud race propagating corrupt load-balancer configuration; and GitHub
resource contention involving unintended configuration. These reports motivate
defensive scenario families only. The fixture does not reproduce any provider's
systems, workloads, data, or impact.

The final benchmark contains 128 balanced cases per source (512 total), with
deterministic labels and exactly half safe controls. Source holdout is not an
unseen-action, unseen-hazard, natural-use, or production-generalization claim.

#### 3.3 Statistics

Balanced-accuracy differences are paired by scenario and bootstrapped within
source for 10,000 resamples. Rollout error is reported at H=1, H=3, and H=5 on
the untouched published episode-disjoint test partition. Brier and ECE values
describe deterministic gate scores; the score is not a learned probability.

### 4. Retained iterations

| Iteration | Registered change | Development outcome | Decision |
|---|---|---|---|
| v3 | Frozen decoder refinement plus policy repair | Legacy BA 87.0%; FN 5; FP 60 | Retained failure: FP exceeded 41 |
| v3.1 | Shared learned-resource threshold sweep | 0/19 candidates passed | Retained failure |
| v3.2 | Learned-disk threshold sweep | 0/7 candidates passed | Retained failure; disk alerts were rule-originated |
| v3.3 | Three-step exact projection for covered actions | v3 safe-control FP 64/256 | Retained failure: hypothetical repetition over-intervened |
| v3.4 | One-step authority for covered requested actions | Legacy BA 95.8%; FN 0; FP 21 | Development passed; final opened once |

The sequence matters. No failed result was overwritten, no deployed artifact
was used as a scratch target, and the held-out final remained inaccessible until
v3.4 passed its development gates.

### 5. Results

#### 5.1 Untouched-corpus world-model rollout

| Horizon | Runtime-v2 normalized error | v3.4 candidate | Relative reduction |
|---|---:|---:|---:|
| H=1 | 0.072218 | 0.065331 | 9.54% |
| H=3 | 0.037751 | 0.036859 | 2.36% |
| H=5 | 0.040362 | 0.039990 | 0.92% |

All three horizons improve; the geometric candidate/runtime-v2 ratio is
0.956508. This is the quantitative learned-model result. It is smaller at long
horizons than at H=1 and should not be described as a large universal JEPA gain.

#### 5.2 Source-held-out final safety fixture

| Condition | TP | FN | TN | FP | Balanced accuracy |
|---|---:|---:|---:|---:|---:|
| Deployed runtime-v2 rules+JEPA | 12 | 244 | 256 | 0 | 52.34% |
| v3.4 deterministic policy | 256 | 0 | 256 | 0 | 100.00% |
| v3.4 policy + frozen candidate | 256 | 0 | 256 | 0 | 100.00% |

The paired source-stratified improvement interval is +46.35 to +48.82
percentage points. The rules-only and combined confusion matrices are
identical. The final benchmark therefore validates typed deterministic policy
on these simulated families, not incremental learned collision or harm
avoidance. The risk-score Brier value changes from 0.4768 to 0.00875 and 10-bin
ECE from 0.4789 to 0.0625, but these scores are rule-derived and not calibrated
probabilities.

#### 5.3 Intervention reduction on opened development fixtures

On the legacy 500-case fixture, v3.4 records FN 0 and FP 21 (8.4% safe-control
intervention), versus deployed runtime-v2 FN 50 and FP 41 (16.4% intervention).
On the opened v3 incident fixture, v3.4 records FN 0 and FP 16 (6.25%
intervention), versus v3 FN 0 and FP 40 (15.625%). These are development
regressions used to select v3.4 and are not independent final evidence.

### 6. What the result establishes

The evidence supports three bounded claims. First, the frozen candidate predicts
the published OS-transition test partition more accurately than runtime-v2 at
all registered horizons. Second, request-bounded deterministic authority avoids
the intervention explosion caused by scoring unrequested repetitions. Third,
the protocol can preserve failed iterations, source separation, artifact
digests, and a no-promotion boundary while still producing a stronger research
result than the published 81.4% fixture score.

The evidence does not show that JEPA beats an architecture-matched supervised
baseline in this new study, that JEPA adds final safety value over v3.4 rules,
or that the policy handles real provider incidents. The 100% figure is specific
to a simple deterministic simulator and should never appear without that
qualification.

### 7. Limitations and non-promotion

1. Labels are deterministic simulator labels, not observed production harm.
2. Incident reports motivate abstractions; no provider environment is replayed.
3. The final safety result is rules-only in attribution.
4. The authored resource effects used during development are not empirical FerrumOS runtime effects. In particular, a prior HUD boundary measurement observed zero normalized heap delta, so its authored simulator delta cannot be installed as runtime truth.
5. The final four-source catalog is small and uses fixed balanced family sizes.
6. The original dataset has unmatched coverage across model lineages and does not isolate architecture from curriculum.
7. No independently executed evaluator, formal verification, natural-use study, or adversarial operator study is reported here.
8. No runtime-v3.4 QEMU authority test, physical timing, or production rollout has passed. The deployed model and manifest remain runtime-v2.

For these reasons the candidate is archived as a research artifact and marked
`promotion_eligible: false`.

### 8. Reproduction

The evidence ladder is:

```text
python scripts/verify_world_model_incident_sources_v3.py --online
python scripts/select_world_model_jepa_v3_1.py
python scripts/select_world_model_jepa_v3_2.py
python scripts/validate_world_model_jepa_v3_3.py
python scripts/validate_world_model_jepa_v3_4.py
python scripts/evaluate_world_model_jepa_v3_4_final.py --dataset <public-jsonl>
python scripts/verify_world_model_jepa_v3_4.py --online
```

The final evaluator refuses to overwrite an existing final catalog. The
selection and validation scripts install file-open audit hooks that deny the
v3.4 final source and scenario paths. The archived candidate and every protocol,
selection, validation, scenario, and result artifact are SHA-256 bound.

### 9. Conclusion

The strongest lesson is an authority lesson rather than an accuracy slogan.
Better forecasts help, but hypothetical rollout should not silently become
execution authority. v3.4 improves the frozen model's untouched-corpus rollout
while reducing development intervention through request-bounded deterministic
authority. On the new final simulator the deterministic path, not JEPA, earns
the safety result. Keeping that attribution explicit—and declining deployment
until runtime effects and authority are verified—is the contribution.

### References

1. Y. LeCun, *A Path Towards Autonomous Machine Intelligence*, 2022. https://openreview.net/forum?id=BZ5a1r-kVsf
2. M. Assran et al., *Self-Supervised Learning from Images with a Joint-Embedding Predictive Architecture*, CVPR 2023. https://arxiv.org/abs/2301.08243
3. Y. Ruan et al., *Identifying the Risks of LM Agents with an LM-Emulated Sandbox*, 2023. https://arxiv.org/abs/2309.15817
4. E. Debenedetti et al., *AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents*, 2024. https://arxiv.org/abs/2406.13352
5. T. Xie et al., *OSWorld: Benchmarking Multimodal Agents for Open-Ended Tasks in Real Computer Environments*, 2024. https://arxiv.org/abs/2404.07972
6. NIST, *Artificial Intelligence Risk Management Framework (AI RMF 1.0)*, 2023. https://doi.org/10.6028/NIST.AI.100-1
7. Cloudflare, *Cloudflare incident on February 6, 2025*, 2025. https://blog.cloudflare.com/cloudflare-incident-on-february-6-2025/
8. Dropbox, *Outage post-mortem*, 2014. https://dropbox.tech/infrastructure/outage-post-mortem
9. Google Cloud, *Incident report: November 16, 2021*, 2021. https://status.cloud.google.com/incidents/6PM5mNd43NbMqjCZ5REh
10. GitHub, *February service disruptions post-incident analysis*, 2020. https://github.blog/news-insights/company-news/february-service-disruptions-post-incident-analysis/
