# tw1 catalogue, group B: search and observability engines

Read 2026-11-11. Read only: nothing was built, installed or executed from any clone. Line numbers are at the
commits below. "Read" means I opened the cited lines; "inferred" means I reasoned from code I read but did not
trace every branch; "unclear" means I could not establish it.

| Clone | Path | Commit | Version at commit |
|---|---|---|---|
| aws/random-cut-forest-by-aws | `tw1-sources/rcf` | `2486241c914d41155aabe229ab12665e3f5af75d` (2025-10-21) | Java pom 4.4.0; Rust crate 4.0.0. `git diff --stat 4.4.0-java HEAD -- Java/core/src/main Java/parkservices/src/main` is empty, so the Java sources read equal the 4.4.0 release |
| opensearch-project/anomaly-detection | `tw1-sources/opensearch-ad` | `9886b340705cb9abd241e12722724b112a7fb943` (2026-11-09) | main, `3.10.0-SNAPSHOT` (build.gradle:40); newest release notes in tree 3.9.0.0; depends on `randomcutforest-parkservices:4.4.0` (build.gradle:164) |
| opensearch-project/alerting-dashboards-plugin | `tw1-sources/alerting-dashboards-plugin` | `2fab006adc71cb4ff0fd9cfd989dadeeba2e8b2f` | package.json 3.10.0.0 |
| elastic/ml-cpp | `tw1-sources/elastic-ml-cpp` | `a2943bfdaff7edbb537f7dcfcab8420655ffa398` (2026-11-10) | main, `elasticsearchVersion=9.7.0` (gradle.properties) |
| elastic/elasticsearch (sparse: licences, x-pack ml normalizer, ml job config, licence code) | `tw1-sources/elasticsearch` | `bac8c977eeb8e790714e96ff44509209dfe3da6b` (2026-11-11) | main, 9.7.0 (build-tools-internal/version.properties); latest GitHub release v9.5.6 |

Adoption (GitHub API, 2026-11-11): RCF 242 stars / 36 forks; OpenSearch AD 95 stars / 89 forks, shipped
inside the default OpenSearch distribution; ml-cpp 158 stars / 68 forks, shipped inside the default
Elasticsearch distribution. Stars understate use of the two plugins, which reach users through the
OpenSearch and Elasticsearch distributions; I have no download figure for them.

---

## 1. AWS Random Cut Forest, `ThresholdedRandomCutForest` (TRCF)

Two separately adaptive parts: the thresholder (`BasicThresholder`, owned by `PredictorCorrector`) and the
forest (time-decayed reservoir sample per tree). A third, the input normaliser in `Preprocessor`, is only
active when `transformMethod != NONE`; the library default is `NONE`, OpenSearch sets `NORMALIZE`.

1. **Identity.** Apache-2.0 (LICENSE; per-file headers). No restriction on running, benchmarking or
   publishing. Library on Maven Central (`software.amazon.randomcutforest:randomcutforest-parkservices`) and
   crates.io (`rcf`). Embedded by OpenSearch AD (below).
2. **Default path.** `ThresholdedRandomCutForest.builder()...build()` then `process(point, timestamp)`.
   Builder defaults (`ThresholdedRandomCutForest.java:676-711`): sampleSize 256, 50 trees, shingleSize 1,
   anomalyRate 0.01, transformMethod NONE, autoAdjust false, zFactor 3.0, alertOnceInDrift false, timeDecay
   unset, so the forest uses `1.0 / (10 * sampleSize)` = 1/2560 (`RandomCutForest.java:356`). Alarm =
   `AnomalyDescriptor.getAnomalyGrade() > 0`, set in `PredictorCorrector.detect` (`PredictorCorrector.java:950`).
   `process` -> `augment` (`ThresholdedRandomCutForest.java:216-224`) -> `predictorCorrector.detect(...)` then
   `postProcess(...)`.
3. **Adaptive quantities.**
   - Thresholder: discounted running mean and deviation of the RCF score; threshold = max(absolute floor,
     mean + scaledDeviation), with z = 3 (`BasicThresholder.java:258-271`).
   - Forest: each tree keeps a 256-point sample; new points enter by time-decayed weighted reservoir sampling
     (`CompactSampler.java:143-155`, `AbstractStreamSampler.java:147-153`).
4. **Learning region (read).**
   - Thresholder: every scored point, flagged or not. `detect` ends with an unconditional call
     (`PredictorCorrector.java:975-977`):
     ```java
     lastDescriptor = result.copyOf();
     saveScores(strategy, choice, scoreVector, correctedScore, result.getTransformMethod(), shingleSize);
     return result;
     ```
     `saveScores` passes the raw score (`PredictorCorrector.java:701-706`):
     ```java
     if (scoreVector[EXPECTED_INVERSE_DEPTH_INDEX] > 0) {
         double temp = (choice == EXPECTED_INVERSE_DEPTH_INDEX) ? correctedScore
                 : scoreVector[EXPECTED_INVERSE_DEPTH_INDEX];
         double last = (strategy == lastStrategy) ? lastScore[EXPECTED_INVERSE_DEPTH_INDEX] : 0;
         thresholders[EXPECTED_INVERSE_DEPTH_INDEX].update(scoreVector[EXPECTED_INVERSE_DEPTH_INDEX], temp, last,
     ```
     and the thresholder update clamps it at 2.0 (`BasicThresholder.java:321-330`):
     ```java
     public void update(double primary, double secondary) {
         updateThreshold(primary);
         primaryDeviation.update(primary);
         secondaryDeviation.update(secondary);
         ++count;
     ...
     public void update(double score, double secondScore, double lastScore, TransformMethod method) {
         update(min(score, 2.0), secondScore - lastScore);
     ```
     The only early returns before `saveScores` are a null RCF point (warm-up) and `score == 0`
     (`PredictorCorrector.java:732-753`). Neither depends on the grade.
   - Forest: every point. `postProcess` calls the preprocessor, which updates the forest, after the grade is
     set and regardless of it (`ThresholdedRandomCutForest.java:650-652`; `Preprocessor.java:437-451`):
     ```java
     // will update the forest
     preprocessor.update(result.getCurrentInput(), point, result.getInputTimestamp(), result.getMissingValues(),
             forest);
     ```
     The sampler gives every point the same weight 1.0 (`AbstractStreamSampler.java:110-111`:
     `return acceptPoint(sequenceIndex, 1.0f);`). Acceptance depends on a random number and arrival time only.
5. **Learns from its own alarms.** Thresholder: **yes**. Forest: **yes**. Both at full weight. The thresholder
   input is clamped at 2.0, which bounds the pull of a single high score but does not withhold it.
6. **Memory.** Thresholder primary Deviation discount = forest timeDecay = 1/2560 per score
   (`PredictorCorrector.java:122` -> `BasicThresholder.java:75-80`), an exponential window of about 2560
   scores (inferred from `Deviation.update`: `weight = weight * (1 - discount) + 1`). Secondary deviation
   discount = anomalyRate = 0.01 (library default), about 100 scores. `thresholdDeviation` discount =
   timeDecay/2. Forest: time decay 1/2560 in the sampler weight.
7. **Direction and bounds.** Symmetric: the mean and deviation follow scores up and down. Score clamp
   `min(score, 2.0)` on the primary statistic only. Absolute floor: the library constructor calls
   `setAbsoluteThreshold(builder.lowerThreshold.orElse(0.8))` when autoAdjust is false
   (`ThresholdedRandomCutForest.java:142-145`), so the threshold never goes below 0.8. The factor is floored at
   `MINIMUM_Z_FACTOR = 2.0` (`BasicThresholder.java:218`). For shingleSize 1 and no differencing the
   deviation term is `min(sqrt(2) * thresholdDeviation, primaryDeviation)`, where `thresholdDeviation` only
   learns gaps *below* the mean (`BasicThresholder.java:237-243, 308-313`); the code comment reads "control
   the effect of large values above a threshold from raising the threshold". This limits how fast the
   deviation part grows under high scores; the mean part is not limited beyond the 2.0 clamp.
8. **Alarm logic.** No on-delay and no consecutive-count rule. Grade is zeroed by correction filters
   (noise vs. smoothed deviations, `ANOMALY_IN_SHINGLE`, `FORECAST` when the value lies within the
   `ignoreNearExpected*` box) (`PredictorCorrector.java:831-899`). With autoAdjust (off by default), a run of
   more than 2 flagged points that stays within 2 deviations of the run's own mean is relabelled `DATA_DRIFT`
   and its grade set to 0 (`PredictorCorrector.java:906-940`). With alertOnce (off by default), later points
   of a run within a shingle of the last anomaly get grade 0 (`PredictorCorrector.java:942-947`).
   Initial threshold 1.5 for the first 10 scores, blended to the adaptive threshold by 20
   (`BasicThresholder.java:140-148, 269-271`).
9. **Operator controls.** `ignoreNearExpectedFromAbove/Below[ByRatio]`, `lowerThreshold` (absolute floor),
   `zFactor`, `autoAdjust`, `alertOnce`, `scoreDifferencing`, `initialThreshold`. No freeze switch, no
   feedback-label input, no exclusion window: I found no API that withholds a point from `saveScores` or
   `forest.update` in the TRCF path.
10. **Documentation.** Silent on anomalies entering the threshold or the forest. `Java/README.md:90-97`
    explains `timeDecay` as the lifetime of points in the sample ("By default, we set `timeDecay` equal to
    `1 / (10 * sampleSize)`"). A code comment notes masking after runs (`PredictorCorrector.java:779-780`):
    "a consequence of this can be masking -- anomalies just after a run/drift would be difficult to
    determine".
11. **Closest tt1 rule.** Thresholder: `ewma` (mean + k deviations, alarms included), with three
    differences: a 2.0 clamp on the input, a 0.8 absolute floor, and a deviation term that learns only from
    scores below the mean. Forest: no tt1 analogue; it is a model retrained on a decaying sample that includes
    flagged points.
12. **Predictions (hypotheses, not results).**
    - Sustained: absorb. Attack points enter the forest sample at weight 1, so their RCF score should fall as
      the sample fills, and the thresholder mean rises with them.
    - Loud pulses: resist, weakly. The 2.0 clamp and the 1/2560 discount bound each pulse's pull on the mean;
      a few pulse points in a 256-point sample should change the forest little.
    - Frog: absorb. Sub-threshold points update forest and thresholder at full weight with no hold-out.
    - Sub-event pulses: unclear. There is no minimum alarm duration and no exclusion of alarms, so the
      campaign's premise (evading exclusion logic) does not apply; short pulses would alarm and be absorbed
      like loud pulses.
13. **Runnable here.** In-process: Java jar from Maven (JVM, well under 1 GB for one series) or the Rust
    crate. Feasible on the laptop.

**Rust port** (`Rust/src/trcf`). Same structure: `update_score` is called on every exit of
`detect_and_modify`, including after a positive grade (`predictorcorrector.rs:417-420`), and
`BasicTRCF::process` updates the forest for every point (`basictrcf.rs:183`). The clamp is the same
(`basicthresholder.rs:217-219`, `self.update_both(minf32(2.0,primary),secondary - last_score);`). One
difference: Rust `update_threshold` learns gaps *above* the mean (`basicthresholder.rs:195-199`,
`let gap : f32 = score - self.primary_deviation.mean() as f32;`), Java learns gaps below it
(`BasicThresholder.java:309`, `double gap = primaryDeviation.getMean() - score;`). The Rust default forest time
decay is `0.1/capacity` (`basictrcf.rs:307`), ten times faster than Java's 1/(10*256). **Python** wrapper
(`python_rcf_wrapper/trcf_model.py`) calls the Java TRCF through JPype; no separate logic.

---

## 2. OpenSearch Anomaly Detection plugin

1. **Identity.** Apache-2.0 (LICENSE.txt). No restriction on running, benchmarking or publishing. Ships in
   the default OpenSearch distribution and Docker image (inferred from general knowledge of the distribution,
   not read in this repo).
2. **Default path.** A detector created through API/UI with defaults: interval set by the user; shingle size
   8 (`TimeSeriesSettings.java:18`, returned by `AnomalyDetector.java:89-98` when no custom shingle and no
   season); recency emphasis `10 * 256 = 2560` (`TimeSeriesSettings.java:199`, `Config.java:445`), time
   decay `1.0 / recencyEmphasis` (`Config.java:1000-1002`). Real-time model built in
   `ADColdStart.java:184-208`:
   ```java
   .timeDecay(config.getTimeDecay())
   .transformDecay(config.getTimeDecay())
   ...
   .anomalyRate(1 - this.thresholdMinPvalue)
   .transformMethod(TransformMethod.NORMALIZE)
   .alertOnce(true)
   .autoAdjust(true);
   ```
   with sampleSize 256, 50 trees, outputAfter max(shingle, 32), `THRESHOLD_MIN_PVALUE = 0.995` so anomalyRate
   0.005 (`TimeSeriesSettings.java:195-220`), `ForestMode.STREAMING_IMPUTE` when shingle > 1
   (`ADColdStart.java:210-216`). Default suppression rule added when the user gives none
   (`AnomalyDetector.java:265`, `856-870`): ignore anomalies whose actual differs from expected by at most 20%
   in either direction (`ACTUAL_OVER_EXPECTED_RATIO LTE 0.2`, `EXPECTED_OVER_ACTUAL_RATIO LTE 0.2`), passed
   to RCF as `ignoreNearExpected*ByRatio` (`ADColdStart.java:304-323`). Real-time inference:
   `RealTimeInferencer.java:267`,
   `List<AnomalyDescriptor> results = model.processSequentially(points, timestamps, x -> true);`, i.e. every
   sample goes through TRCF `augment` (`ThresholdedRandomCutForest.java:379`). The reported grade and
   confidence are the TRCF values unchanged (`ModelUtil.java:105-107`). The plugin flags a result when
   grade > 0 (`AnomalyResult.java:948`, used to prioritise saving).
3. **Adaptive quantities.** The RCF 4.4.0 thresholder, forest and NORMALIZE input normaliser, with the settings
   above. Thresholder discounts: primary 1/2560, secondary 0.005 (from anomalyRate), thresholdDeviation
   1/5120 (`PredictorCorrector.java:122`, `BasicThresholder.java:75-80`). autoAdjust true means the
   absolute floor is not fixed: `setAbsoluteThreshold` is skipped (`ThresholdedRandomCutForest.java:142-145`)
   and the floor scales with the mean when the mean is below 0.9 (`BasicThresholder.java:265-268`).
4. **Learning region (read).** Same code as section 1 (RCF 4.4.0, identical to the clone): thresholder via
   `PredictorCorrector.java:976`, forest via `ThresholdedRandomCutForest.java:651` ->
   `ImputePreprocessor.update`. The normaliser (`WeightedTransformer.updateDeviation`, called from
   `Preprocessor.updateState`, `Preprocessor.java:760`) updates with every non-missing input
   (`WeightedTransformer.java:124-127`). The only forest gate in STREAMING_IMPUTE is the imputed fraction
   (`ImputePreprocessor.java:91-114`, `fraction < useImputedFraction`), unrelated to the grade. I found no
   plugin code that withholds flagged samples; no periodic retraining, only re-cold-start on a large time gap
   or an error (`RealTimeInferencer.java:207, 306`).
5. **Learns from its own alarms.** Thresholder **yes**, forest **yes**, input normaliser **yes**.
6. **Memory.** As section 1 with timeDecay = transformDecay = 1/2560 per interval; secondary deviation about
   200 intervals (1/0.005).
7. **Direction and bounds.** Symmetric; 2.0 clamp on the thresholder input; adaptive absolute floor
   (0.8, or mean*0.8/0.9 when mean < 0.9); normalised inputs clipped to [-100, 100]
   (`Preprocessor.java:72`, `WeightedTransformer.java:149-157`).
8. **Alarm logic (default).** autoAdjust: `DATA_DRIFT` zeroes the grade after more than 2 flagged points in a
   run that stay within 2 deviations of the run mean; also `CONDITIONAL_FORECAST` (zero grade if enough
   near neighbours in the sample fall inside the uncertainty box) (`PredictorCorrector.java:870-873,
   906-940`). alertOnce: `ALERT_ONCE` zeroes later points of a run (`PredictorCorrector.java:942-947`).
   Default 20% suppression rule zeroes anomalies near the forecast (`FORECAST` mode). These suppress the
   alarm only; all of these points still reach `saveScores` and `forest.update`.
   **Alerting monitor default** (alerting-dashboards-plugin): an AD trigger created in the UI defaults to
   `anomalyGradeThresholdValue: 0.7`, `ABOVE`, and `anomalyConfidenceThresholdValue: 0.7`, `ABOVE`
   (`public/pages/CreateTrigger/containers/CreateTrigger/utils/constants.js:29-35`), compiled to
   `grade > 0.7 && confidence > 0.7` (`formikToTrigger.js:353`). Confidence is the RCF data confidence,
   which depends on values seen, outputAfter and data quality (`AnomalyDescriptor.java:92-105`), not on alarms.
9. **Operator controls.** Suppression rules (absolute or ratio, above/below), shingle size, recency emphasis
   (time decay), imputation method, history. No freeze switch, no exclusion window, no feedback labels in the
   plugin code read.
10. **Documentation.** Silent in the repo (README.md, docs/). The external documentation site was not read.
11. **Closest tt1 rule.** `ewma` (thresholder), plus a forest and an input normaliser that both learn from
    flagged points. Differs by the 2.0 clamp, the adaptive floor, and run-level alarm suppression
    (DATA_DRIFT, ALERT_ONCE) that resembles a hold rule for the alarm but not for learning.
12. **Predictions (hypotheses).**
    - Sustained: absorb. Learning is the same as section 1; in addition DATA_DRIFT and ALERT_ONCE are built
      to stop repeated alarms within a stable run, so the alarm should go quiet early whatever the threshold
      does.
    - Loud pulses: resist, weakly (2.0 clamp, 1/2560 discount). Pulses more than 20% above the forecast pass
      the default suppression rule.
    - Frog: absorb (no hold-out anywhere; forest and normaliser drift with the attacker).
    - Sub-event pulses: unclear. No minimum alarm duration; with shingle 8 a short pulse stays in eight
      consecutive shingles, and `ANOMALY_IN_SHINGLE` may suppress repeat alarms for it.
13. **Runnable here.** Docker: `opensearchproject/opensearch` single node with a 2-4 GB heap, plus
    Dashboards for the UI (optional; the REST API suffices). Feasible on 16 GB. Detectors run on a schedule
    of at least 1 minute per interval, so a long campaign needs either real time or the historical-analysis
    (batch) path, which builds its TRCF separately in `ADBatchTaskCache.java:66-75` (not traced in full).

---

## 3. Elastic ML (`ml-cpp`, plus `x-pack/plugin/ml` normaliser glue)

**Licence position (recorded first).**
- `ml-cpp/LICENSE.txt:1-8`: all files outside `3rd_party` and `build-setup` are under the Elastic License 2.0
  "and the following additional limitation. Functionality enabled by the files subject to the Elastic
  License 2.0 may only be used in production when invoked by an Elasticsearch process with a license key
  installed that permits use of machine learning features." The same text is in each file header
  (`copyright_code_header.txt`).
- ELv2 (full text in that file) grants a licence to "use, copy, distribute, make available, and prepare
  derivative works", with three limitations: no hosted or managed service, no circumventing licence keys, no
  removing notices. It says nothing about reading the source, benchmarking, or publishing results. Reading
  is not restricted by the text.
- `elasticsearch/LICENSE.txt`: code is under a triple licence (AGPL-3.0-only, SSPL-1.0, ELv2) by default,
  "Code that is licensed solely under the "Elastic License 2.0" is found only in the x-pack folder." The ML
  Java files read carry an ELv2-only header (e.g. `x-pack/plugin/core/.../ml/job/config/Job.java:1-6`).
- Running: anomaly detection jobs require a Platinum licence:
  `MachineLearning.java:517-521`, `ML_ANOMALY_JOBS_FEATURE = LicensedFeature.persistent(..., "anomaly-detection-job",
  License.OperationMode.PLATINUM)`. A self-generated trial lasts 30 days
  (`LicenseSettings.java:41`, `NON_BASIC_SELF_GENERATED_LICENSE_DURATION = TimeValue.timeValueHours(30 * 24)`).
- Benchmarking and publishing results: ELv2 and the repo files are silent. The terms that govern the trial
  and the binary distribution (Elastic's licence agreement / EULA) are not in these repos and were not read.
  Status: **unclear**; check those terms before any run is published.

Two adaptive components: the per-series time-series model (priors, trend decomposition, change-point
handling) and the score normaliser (q-digest of raw scores, plus Java-side renormalisation of past results).

1. **Identity.** ELv2 + ML-in-production limitation (above). Shipped in every default Elasticsearch
   distribution; usable under trial or Platinum/Enterprise licence.
2. **Default path.** A job with a single metric detector (e.g. `mean(x)`) and default `bucket_span`
   (default value not read here; unclear). Per bucket: `CMetricModel::sample` adds the bucket value to the
   series model; `CMetricModel::computeProbability` gives a probability; raw score =
   `anomalyScore(probability)` if probability <= 0.035, else 0 (`CHierarchicalResultsNormalizer.cc:132-134`,
   `CAnomalyDetectorModelConfig.cc:89`); the normaliser maps it to 0-100 (`record_score`/`anomaly_score`).
   The C++ side raises no alarm; the alarm is a Kibana alerting rule or watch comparing the normalised score
   to a severity threshold. The default threshold of that rule was not read (Kibana not cloned): unclear.
3. **Adaptive quantities.**
   - Model: Bayesian priors and time-series decomposition updated each bucket with per-sample weights.
     Default decay 0.0005 per standard 30-minute bucket, learn rate 1.0 (`CAnomalyDetectorModelConfig.cc:63-66`).
   - Normaliser: q-digest (201 nodes) of discretised raw scores; normalised score from knot points
     (0,0),(70,1),(85,1.2),(90,1.5),(95,3),(97,20),(99,50),(99.9,90),(100,100)
     (`CAnomalyDetectorModelConfig.cc:92-101`), percentile -> score.
4. **Learning region (read).**
   - Model: all buckets, with an outlier weight that shrinks for improbable values. `outliers::weight`
     (`lib/maths/time_series/CTimeSeriesModel.cc:199-224`):
     ```cpp
     double pValue{computePValue(prior, weights, value)};
     if (pValue >= MAXIMUM_P_VALUE) {
         return 1.0;
     }
     double minimumWeight{deratedMinimumWeight(derate)};
     ```
     with `MINIMUM_WEIGHT{0.01}`, `MAXIMUM_P_VALUE{1e-3}`, `MINIMUM_P_VALUE{1e-5}` (lines 166-168): weight 1
     for p >= 1e-3, log-interpolated down to the minimum at p <= 1e-5. The weight enters the update as a count
     multiplier (`MathsTypes.cc:53-55`, `return weights[E_SampleCountWeight] * weights[E_SampleOutlierWeight];`).
     It is set on both the trend and the residual model (`CTimeSeriesModel.cc:1238-1253`). The minimum is
     derated: `MINIMUM_WEIGHT + (0.5 - MINIMUM_WEIGHT) * derate` (lines 175-178), with derate falling from 1 to
     0 over the first 3 weeks of a series (`CIndividualModel.cc:611-615`) and over 3 days after a detected
     change point (`CTimeSeriesDecompositionDetail.cc:686-692`). So outliers enter at 0.5 weight early on and
     at 0.01 later, never at 0.
     The p-value here is the model's own tail probability of the detrended value, which is related to but not
     the same as the job's record probability or the alerting threshold (inferred).
   - Change points: a level shift (or, with seasonality, other change types) that lasts at least
     `max(30 h, 5 window buckets)` (doubled for sparse data) and is "large enough" is applied to the
     decomposition (`CTimeSeriesDecompositionDetail.cc:851-866, 923-936`). The code comment: "By waiting 30
     hours we give ourselves a margin to see the revert before we commit to making a change." Changes can be
     undone if the series reverts (`testUndoLastChange`, lines 874-902).
   - Normaliser: every bucket's raw score, sampled as the max over `m_CountPerSample` buckets
     (`HOUR / clamp(2 * bucketLength, 5 min, 1 h)`, `CAnomalyScore.cc:257-260`), is added
     (`CAnomalyScore.cc:587-593`):
     ```cpp
     m_RawScoreQuantileSummary.add(discreteScore);
     if (discreteScore <= m_HighPercentileScore) {
         ++m_HighPercentileCount;
     } else {
         m_RawScoreHighQuantileSummary.add(discreteScore);
     ```
     The caller skips the update only when `s_ShouldUpdateQuantiles == false`
     (`CHierarchicalResultsNormalizer.cc:147-155`), which is set when a detection rule with
     `skip_model_update` or a scheduled event applies (`CMetricModel.cc:394-396`;
     `CAnomalyDetectorModel.cc:485-507`). By default neither exists, so high scores enter the quantiles.
   - Renormalisation (Java): when quantiles change, past bucket, record and influencer scores are rewritten over
     a window of max(30 days, 100 buckets) by default (`ScoresUpdater.java:39-41, 75-80`).
5. **Learns from its own alarms.** Model: **partial** (flagged-like values at weight 0.01-0.5; sustained level
   shifts accepted as change points after about 30 h). Normaliser: **yes** (all raw scores, unless an operator
   rule or calendar event applies).
6. **Memory.** Model decay 0.0005 per 30-min bucket equivalent (`bucketNormalizationFactor`), trend decay
   `min(48 * decay / ..., 0.1)` (`CAnomalyDetectorModelConfig.cc:155-160`); exact half-life in hours not
   derived (unclear units in places). Normaliser: q-digest decays at the model decay rate but only every
   `QUANTILE_DECAY_TIME = 20` sample periods (`CAnomalyScore.h:236`, `CAnomalyScore.cc:681-705`): "Quantiles
   age at a much slower rate than everything else". Renormalisation window 30 days.
7. **Direction and bounds.** Model: down-weighting, floor 0.01 on the weight; symmetric otherwise. Normaliser:
   quantile-based, normalised score capped at 100; raw scores above probability 0.035 count as 0.
8. **Alarm logic.** None in ml-cpp. Kibana/alerting side not read.
9. **Operator controls.** Custom rules with actions `skip_result` and `skip_model_update`, calendars
   (scheduled events: weight 0 for the model update, `CAnomalyDetectorModel.cc:489-493`), job
   `renormalization_window_days`, model snapshots and revert (not read).
10. **Documentation.** Silent in ml-cpp (docs/ holds only changelogs; `CHANGELOG.asciidoc:283` "Better
    handling of outliers in update immediately after detecting changes in time series"). The Elastic
    documentation site was not read.
11. **Closest tt1 rule.** Model: closest to `ewma_excl` with soft exclusion (weights 0.01, never 0) plus a
    change detector that adopts shifts lasting 30 h or more. Normaliser: closest to `daily` (a quantile of
    past scores including alarms), with very slow decay and retroactive rescoring.
12. **Predictions (hypotheses).**
    - Model, sustained: absorb, after about 30 h via the change-point test; before that the 0.01 weight slows it.
    - Model, loud pulses: resist (each pulse at weight about 0.01 once the series is 3 weeks old).
    - Model, frog: absorb. Values with p >= 1e-3 get full weight, so a slow ramp that stays below the
      improbable region is learned in full.
    - Model, sub-event pulses: unclear. Bucket aggregation (mean, max, etc. per bucket) shapes what the model
      sees; depends on the bucket function and span.
    - Normaliser, sustained: absorb. The attack's raw scores fill the upper quantiles; later and past
      (renormalised) scores of the same size fall.
    - Normaliser, loud pulses: absorb. Each pulse adds a high raw score; with slow decay they accumulate.
    - Normaliser, frog: unclear. Depends on whether the frog lives in raw-score space below the 0.035
      probability cut, where raw score is 0.
    - Normaliser, sub-event pulses: unclear.
13. **Runnable here.** Docker `docker.elastic.co/elasticsearch/elasticsearch` single node on x86_64 with a
    30-day trial licence; about 4-6 GB including the native ML process for one job (estimate). Feasible on
    16 GB. Data can be fed through the `_ml/anomaly_detectors/<job>/_data` API with historical timestamps, so
    weeks of data run in minutes (inferred from the post-data API; not checked here). Licence terms for
    publishing results: unclear (above).

---

## Additions

None added. Candidates considered:
- Wazuh and Graylog anomaly detection: they embed or front the OpenSearch AD plugin, so they share its code
  path and would not be independent rows.
- `rrcf` (Python robust random cut forest): a library with no thresholder; it belongs to group A if anywhere.
- Amazon Kinesis Data Analytics `RANDOM_CUT_FOREST` and Elastic's hosted services are closed and belong to the
  documentation-only table.

## Could not establish

- Elastic: the default severity threshold of the Kibana anomaly-detection alert rule, the default
  `bucket_span` from the job wizard, and the licence terms (EULA/trial agreement) on benchmarking and
  publishing results. These live in Kibana and Elastic's commercial terms, which I did not read.
- Elastic: the exact half-life of the model priors in hours, and how `CTimeSeriesAnomalyModel` (which tracks
  anomalous sections) changes probabilities during a long anomaly.
- Elastic: whether the outlier-weight p-value threshold (1e-3) lines up with the scores at which users alarm,
  i.e. which flagged buckets are actually down-weighted. The two quantities are related but I did not trace
  the mapping.
- OpenSearch: the documentation site's description of model updating (not read); the default detector
  interval in the Dashboards UI (Dashboards AD plugin not cloned); the historical-analysis (batch) path in
  detail.
- RCF: whether `DATA_DRIFT` / `ALERT_ONCE` together with the `candidate` logic silence a sustained run after
  exactly 3 points or later. The control flow involves `lastDescriptor`, `runLength` and
  `lastSignificantDescriptor`, and I read it but did not simulate it.
- RCF: why `PredictorCorrector` passes `anomalyRate` as the secondary deviation's discount
  (`new BasicThresholder(timeDecay, anomalyRate, adjust)` -> `BasicThresholder(double primaryDiscount, double
  secondaryDiscount, boolean adjust)`). Read in the code; the intent is unclear.
