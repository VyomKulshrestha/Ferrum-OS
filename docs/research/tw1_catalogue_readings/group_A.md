# tw1 catalogue, group A: Python streaming / time-series anomaly libraries

Read 2026-11-11 from shallow clones in `C:\Users\marcu\Videos\tw1-sources\<repo>`. Nothing was installed, imported or run. Every quote below was checked line by line against the file at the recorded commit by a script (0 mismatches). Statements marked "inferred" were reasoned from the code, not read directly. Predictions (item 12) are hypotheses written before any run.

## Summary

| Target | In scope | Learns from own alarms | Update evidence | Closest tt1 rule |
|---|---|---|---|---|
| river anomaly.QuantileFilter (threshold) | yes | yes | `river/anomaly/filter.py`:180-184 | tracker |
| river anomaly.ThresholdFilter + wrapped self-normalising scorer (GaussianScorer, StandardAbsoluteDeviation, HalfSpaceTrees) | yes | no | `river/base/anomaly_detector.py`:155-156 | ewma_excl |
| river anomaly.PredictiveAnomalyDetection (internal dynamic threshold) | yes | yes | `river/anomaly/pad.py`:147-148 | ewma |
| river anomaly.HalfSpaceTrees standalone (scorer, no alarm) | no | not_adaptive | `river/anomaly/hst.py`:223-227 | none |
| PySAD transform.postprocessing.QuantileFilter | yes | yes | `pysad/transform/postprocessing/postprocessors.py`:157 | tracker |
| PySAD ConformalProbabilityCalibrator (+ fixed ThresholdFilter) | yes | yes | `pysad/transform/probability_calibration/conformal_prediction.py`:36 | daily |
| PySAD GaussianTailProbabilityCalibrator | yes | yes | `pysad/transform/probability_calibration/gaussian_tail.py`:67-68 | ewma |
| PySAD SPOTProbabilityCalibrator | yes | no | `pysad/transform/probability_calibration/spot.py`:91-95 | SPOT |
| PySAD AnomalyLikelihoodProbabilityCalibrator (NuPIC anomaly likelihood port) | yes | yes | `pysad/transform/probability_calibration/anomaly_likelihood.py`:67-69 | ewma |
| PySAD NonparametricDynamicThresholdPostprocessor (Telemanom threshold, streaming) | yes | yes | `pysad/transform/postprocessing/running_postprocessors.py`:120-122 | ewma |
| PySAD models.PEWMA (probabilistic EWMA normaliser) | yes | partial | `pysad/models/pewma.py`:81-85 | ewma |
| StreamAD model.SpotDetector | yes | yes | `streamad/model/spot_Detector.py`:345-349 | SPOT |
| StreamAD process.ZScoreCalibrator | yes | yes | `streamad/process/zscore_calibrator.py`:34 | ewma |
| StreamAD process.TDigestCalibrator | yes | yes | `streamad/process/tdigest_calibrator.py`:41-44 | tracker |
| Merlion post-rules (AnomScoreCalibrator + AggregateAlarms threshold) | no | no | `merlion/models/anomaly/base.py`:286-287 | on_delay |
| Merlion DefaultDetector: RandomCutForest member with online_updates=True | yes | yes | `merlion/models/anomaly/random_cut_forest.py`:159-163 | none |
| Orion find_anomalies (window threshold in verified pipelines) | yes | yes | `orion/primitives/timeseries_anomalies.py`:158-161 | daily |
| ADTK fitted detectors (quickstart SeasonalAD; IQR / quantile bounds) | no | configurable | `src/adtk/_detector_base.py`:247-251 | static |
| ADTK PersistAD / LevelShiftAD reference window | yes | yes | `src/adtk/transformer/_transformer_1d.py`:505-509 | none |
| Luminol AnomalyDetector (default bitmap_detector, percent-of-max threshold) | yes | yes | `src/luminol/anomaly_detector.py`:111-115 | none |
| alibi-detect od.Mahalanobis (online outlier detector) | yes | yes | `alibi_detect/od/mahalanobis.py`:254-255 | ewma |
| alibi-detect outlier detectors with infer_threshold (IForest, AE, VAE, SR, new-style sklearn/pytorch backends) | no | no | `alibi_detect/od/isolationforest.py`:97-98 | static |
| PyOD BaseDetector contamination threshold (static control) | no | no | `pyod/models/base.py`:570-573 | static |
| Darts darts.ad detectors (QuantileDetector, IQRDetector, ThresholdDetector) [addition] | no | no | `darts/ad/detectors/quantile_detector.py`:104-107 | static |

## river

Repository https://github.com/online-ml/river, commit `9fab7f7b041390c8549820111947e6f61dc61f57`, version 0.26.1 (pyproject; PyPI latest 0.26.1, 2026-08-21). Licence: BSD-3-Clause. No restriction on running, benchmarking or publishing. Adoption: 159,209 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).

### river anomaly.QuantileFilter (threshold)

Scope: in scope. Library on PyPI; the alarm threshold is a running quantile of the scores that moves at run time.

1. **Identity.** river anomaly.QuantileFilter (threshold); https://github.com/online-ml/river @ `9fab7f7b0413`; 0.26.1 (pyproject; PyPI latest 0.26.1, 2026-08-21); BSD-3-Clause; 159,209 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).
2. **Default path.** Docstring example in river/anomaly/filter.py (lines 136-150): compose.Pipeline(preprocessing.MinMaxScaler(), anomaly.QuantileFilter(anomaly.HalfSpaceTrees(seed=42), q=0.95)); per sample: score_one -> model['QuantileFilter'].classify(score) -> model.learn_one(x). Alarm decided by QuantileFilter.classify.
3. **Adaptive quantity.** Threshold: running q-quantile (P2 estimator) of all anomaly scores since start. Update rule: quantile.update(score) on every learn_one call, flagged or not; P2 marker update (rank-based, whole history).
4. **Learning region.** All scores. The protect_anomaly_detector switch (default True) gates only the wrapped detector, not the quantile. Evidence (read in the code):
   - `river/anomaly/filter.py` lines 180-184:
     ```python
         def learn_one(self, *args, **learn_kwargs):
             score = self.score_one(*args)
             if not self.protect_anomaly_detector or not self.classify(score):
                 self.anomaly_detector.learn_one(*args, **learn_kwargs)
             self.quantile.update(score)
     ```
   - `river/anomaly/filter.py` lines 177-178:
     ```python
         def classify(self, score):
             return score >= (self.quantile.get() or math.inf)
     ```
   - `river/anomaly/filter.py` lines 171:
     ```python
             self.quantile = stats.Quantile(q=q)
     ```
   - `river/stats/quantile.py` lines 60:
     ```python
             self._quantile = _rust_stats.RsQuantile(q)
     ```
5. **Learns from its own alarms.** yes.
6. **Memory.** Whole history; P2 estimator, no window and no decay. Influence of one score shrinks roughly as 1/n (inferred from the P2 algorithm, not read in the Rust source).
7. **Direction and bounds.** Symmetric (moves up or down with ranks). No clamp, floor or ceiling. classify returns False until the first update (quantile None -> inf).
8. **Alarm logic.** Per-sample comparison score >= quantile. No on-delay, no hysteresis, no suppression.
9. **Operator controls.** protect_anomaly_detector (default True) shields the wrapped detector only. No freeze switch for the quantile, no exclusion windows, no feedback labels. stats.RollingQuantile exists but is not used by QuantileFilter.
10. **Documentation.** Silent on the quantile. The parameter doc talks about the detector only: 'if it learns the anomaly score, then it will slowly start to consider anomalous anomaly scores as normal. This might be desirable, for instance in the case of drift.' (river/anomaly/filter.py 120-125)
11. **Closest tt1 rule.** tracker. Differs: Learns from all scores like the tt1 tracker, but it is a rank-based whole-history quantile (step size shrinks ~1/n, no window), not a fixed-step tracker. The wrapped detector is protected (per-sample exclusion), so the scores of a sustained attack stay high while the quantile climbs.
12. **Predictions (hypotheses, not results).** Sustained: absorb, slowly: once attack scores make up more than (1-q) of all scores seen, the q-quantile moves into the attack range; time to silence grows with history length. Loud pulses: resist: rank-based, so pulse height does not matter and short pulses are a small fraction of samples. Frog: resist: mass placed just under a rank quantile cannot raise it; the quantile drifts down toward the frog values, which then alarm. Sub-event pulses: resist: no alarm-exclusion logic to evade; sub-event pulses act like small loud pulses on a rank statistic.
13. **Runnable here.** In-process (pip install, CPU only); seconds to minutes for 1e5-1e6 samples; well under 1 GB RAM.

Notes: Upstream preprocessing.MinMaxScaler in the docstring pipeline learns from every x (Pipeline.learn_one runs unsupervised transformers before the anomaly filter, river/compose/pipeline.py 536-540), so feature scaling also absorbs attack values. The detector is shielded per sample only (no episode logic).

Unresolved: P2 implementation is in Rust (_rust_stats.RsQuantile), not read; 1/n behaviour inferred from the algorithm.

### river anomaly.ThresholdFilter + wrapped self-normalising scorer (GaussianScorer, StandardAbsoluteDeviation, HalfSpaceTrees)

Scope: in scope. The threshold is fixed, but the scorer that the threshold is applied to (a Gaussian fit, mean/variance normaliser or tree mass profile) updates at run time.

1. **Identity.** river anomaly.ThresholdFilter + wrapped self-normalising scorer (GaussianScorer, StandardAbsoluteDeviation, HalfSpaceTrees); https://github.com/online-ml/river @ `9fab7f7b0413`; 0.26.1 (pyproject; PyPI latest 0.26.1, 2026-08-21); BSD-3-Clause; 159,209 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).
2. **Default path.** Docstring example in river/anomaly/filter.py (lines 43-63): anomaly.ThresholdFilter(anomaly.GaussianScorer(window_size=24*7, grace_period=30), threshold=0.995) | time_series.HoltWinters(...); evaluate.evaluate calls Pipeline.learn_one. Alarm decided by ThresholdFilter.classify (score >= threshold). protect_anomaly_detector defaults to True.
3. **Adaptive quantity.** Score normaliser inside the wrapped detector: GaussianScorer's (rolling) Gaussian of y; SAD's running mean and variance; HST's windowed mass profiles. The threshold itself is fixed. Update rule: AnomalyFilter.learn_one calls the detector's learn_one only when the pre-update score is not classified anomalous.
4. **Learning region.** All except flagged samples (per-sample exclusion, decided with the score before the update). Evidence (read in the code):
   - `river/base/anomaly_detector.py` lines 155-156:
     ```python
             if self.protect_anomaly_detector and not self.classify(self.score_one(*args)):
                 self.anomaly_detector.learn_one(*args, **learn_kwargs)
     ```
   - `river/base/anomaly_detector.py` lines 103-104:
     ```python
         def __init__(
             self, anomaly_detector: AnomalyDetector, protect_anomaly_detector: bool = True
     ```
   - `river/anomaly/filter.py` lines 98-99:
     ```python
         def classify(self, score):
             return score >= self.threshold
     ```
   - `river/anomaly/gaussian.py` lines 60-61:
     ```python
         def learn_one(self, x, y):
             self.gaussian.update(y)
     ```
   - `river/compose/pipeline.py` lines 571-572:
     ```python
                     if step.classify(score):
                         break
     ```
5. **Learns from its own alarms.** no. Default / switch: protect_anomaly_detector=True (default) excludes flagged samples. Setting it to False does NOT make the detector learn from all samples: the condition at base/anomaly_detector.py 155 is 'protect and not anomalous', so with protect=False the wrapped detector is never updated at all (read in the code; looks like a bug, QuantileFilter overrides learn_one with the intended 'not protect or not anomalous').
6. **Memory.** GaussianScorer: window_size samples (example 168) or whole history (default window_size=None); SAD: whole history, count-based; HST: tumbling window_size=250.
7. **Direction and bounds.** Threshold fixed. Normaliser symmetric, no clamps. grace_period: GaussianScorer returns 0 for the first grace_period samples (default 100).
8. **Alarm logic.** Per-sample score >= threshold. In a Pipeline, a flagged sample also stops downstream steps from learning (pipeline.py 571-572).
9. **Operator controls.** protect_anomaly_detector, but see default_when_configurable: False freezes the detector instead of un-protecting it. No exclusion windows or labels.
10. **Documentation.** 'If the data contains sporadic anomalies, then the anomaly detector should likely not be updated. Indeed, if it learns the anomaly score, then it will slowly start to consider anomalous anomaly scores as normal. This might be desirable, for instance in the case of drift.' (river/anomaly/filter.py 17-22)
11. **Closest tt1 rule.** ewma_excl. Differs: Mean/variance (GaussianScorer, SAD) or tree masses (HST) fitted with flagged samples left out per sample; no hold-off after an alarm and no episode-level exclusion; GaussianScorer in the example uses a sliding 7-day window rather than an EWMA.
12. **Predictions (hypotheses, not results).** Sustained: resist: every attack sample is flagged and withheld, so the baseline never moves and the alarm persists (and a genuine level change is never learned). Loud pulses: resist: pulses above the threshold are withheld. Frog: absorb: values kept just under the threshold are learned and widen the Gaussian, raising the effective cut on the raw value. Sub-event pulses: resist: exclusion is per sample, so even one-sample pulses above the threshold are withheld.
13. **Runnable here.** In-process (pip install, CPU only); seconds to minutes for 1e5-1e6 samples; well under 1 GB RAM.

Notes: StandardAbsoluteDeviation (river/anomaly/sad.py 68-70) and GaussianScorer learn from every sample when used standalone with learn_one on each sample; the exclusion comes only from the filter. HalfSpaceTrees standalone (docstring loop in hst.py learns every sample) has no alarm of its own; see the separate out-of-scope row.

Unresolved: Whether the protect=False behaviour (detector frozen) is intended was not established; no issue tracker read.

### river anomaly.PredictiveAnomalyDetection (internal dynamic threshold)

Scope: in scope. The scorer carries its own dynamic threshold (mean + n_std * std of squared errors) that updates at run time and saturates the score at 1.0.

1. **Identity.** river anomaly.PredictiveAnomalyDetection (internal dynamic threshold); https://github.com/online-ml/river @ `9fab7f7b0413`; 0.26.1 (pyproject; PyPI latest 0.26.1, 2026-08-21); BSD-3-Clause; 159,209 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).
2. **Default path.** Docstring example in river/anomaly/pad.py (lines 60-84): PAD = anomaly.PredictiveAnomalyDetection(SNARIMAX(...), horizon=1, n_std=3.5, warmup_period=15); loop: score = PAD.score_one(None, y); PAD.learn_one(None, y). Score 1.0 means the squared error is at or above the internal threshold.
3. **Adaptive quantity.** Threshold on squared prediction error: running mean + n_std * running std of squared errors; also the forecaster itself. Update rule: score_one computes the threshold from current stats, then updates stats.Mean and stats.Var with the current squared error, before comparing; learn_one updates the forecaster with every y.
4. **Learning region.** All scored samples, including those returned as 1.0. The update sits in score_one, so an AnomalyFilter's protection (which only gates learn_one) cannot withhold it. Evidence (read in the code):
   - `river/anomaly/pad.py` lines 147-148:
     ```python
             threshold = self.dynamic_mae.get() + (
                 self.n_std * math.sqrt(self.dynamic_se_variance.get())
     ```
   - `river/anomaly/pad.py` lines 157-158:
     ```python
             self.dynamic_mae.update(squared_error)
             self.dynamic_se_variance.update(squared_error)
     ```
   - `river/anomaly/pad.py` lines 162-163:
     ```python
             if squared_error >= threshold:
                 return 1.0
     ```
   - `river/anomaly/pad.py` lines 121-122:
     ```python
         def learn_one(self, x: dict | None, y: base.typing.Target | float):
             self.iter += 1
     ```
5. **Learns from its own alarms.** yes.
6. **Memory.** Whole history, count-based (stats.Mean / stats.Var, weight 1/n). Forecaster memory depends on the model.
7. **Direction and bounds.** Symmetric; no clamp. Returns 0.0 during warmup_period (default 0).
8. **Alarm logic.** No alarm logic inside; score 1.0 at or above the threshold, linear below. User thresholds the score.
9. **Operator controls.** n_std (default 3.0), warmup_period. No freeze or exclusion.
10. **Documentation.** Silent on anomalies entering the threshold. Attribute doc: 'The running mean of the (squared) errors from the predictions of the model to update the dynamic threshold.' (pad.py 40-41)
11. **Closest tt1 rule.** ewma. Differs: Mean + k*std like the tt1 EWMA limit, but on squared errors and with count-based (1/n) weights over the whole history instead of exponential forgetting; the forecaster also learns the attacked signal, shrinking errors.
12. **Predictions (hypotheses, not results).** Sustained: absorb: the forecaster learns the new level so errors fall, and attack errors also inflate the threshold stats. Loud pulses: absorb: squared errors of loud pulses inflate the variance of squared errors strongly, raising the threshold for later anomalies; 1/n weighting slows this on long histories. Frog: absorb, slowly: errors kept just under mean + k*std raise both terms; speed limited by 1/n. Sub-event pulses: absorb: there is no exclusion to evade; pulses enter the stats like any sample.
13. **Runnable here.** In-process (pip install, CPU only); seconds to minutes for 1e5-1e6 samples; well under 1 GB RAM.

Notes: Because the stats update inside score_one, every extra score_one call on the same sample (for example QuantileFilter.learn_one calls score_one, and Pipeline.learn_one calls it again) updates the stats again (inferred from the call sites; not run).

Unresolved: Whether PAD is commonly used without a wrapping filter was not established.

### river anomaly.HalfSpaceTrees standalone (scorer, no alarm)

Scope: out of scope / static control. Scorer only; it makes no alarm decision. The library's alarm path wraps it in QuantileFilter or ThresholdFilter (rows above), where it is protected by default.

1. **Identity.** river anomaly.HalfSpaceTrees standalone (scorer, no alarm); https://github.com/online-ml/river @ `9fab7f7b0413`; 0.26.1 (pyproject; PyPI latest 0.26.1, 2026-08-21); BSD-3-Clause; 159,209 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).
2. **Default path.** Docstring in river/anomaly/hst.py (lines 117-130): Pipeline(MinMaxScaler(), HalfSpaceTrees(seed=42)); score = model.score_one(x); model.learn_one(x) on every sample.
3. **Adaptive quantity.** Model: per-node mass profiles over tumbling windows. Update rule: Every learn_one increments l_mass along the path; every window_size samples r_mass <- l_mass.
4. **Learning region.** All samples passed to learn_one (in the standalone docstring loop, all samples). Evidence (read in the code):
   - `river/anomaly/hst.py` lines 223-227:
     ```python
             self.counter += 1
             if self.counter == self.window_size:
                 for nodes in self._tree_nodes:
                     for node in nodes:
                         node.r_mass = node.l_mass
     ```
5. **Learns from its own alarms.** not_adaptive.
6. **Memory.** Tumbling reference window of window_size=250 samples (default).
7. **Direction and bounds.** n/a
8. **Alarm logic.** None in the library.
9. **Operator controls.** None.
10. **Documentation.** Silent.
11. **Closest tt1 rule.** none. Differs: No threshold; listed so the catalogue records that the standalone docs loop retrains on every sample while the alarm-making filters protect it.
12. **Predictions (hypotheses, not results).** Sustained: unclear: depends on the user's threshold. Loud pulses: unclear. Frog: unclear. Sub-event pulses: unclear.
13. **Runnable here.** In-process (pip install, CPU only); seconds to minutes for 1e5-1e6 samples; well under 1 GB RAM.

Notes: learns_from_own_alarms is 'not_adaptive' only in the sense that this component makes no alarm, so it has no 'own alarms'; the model itself adapts to all samples.

## pysad

Repository https://github.com/selimfirat/pysad, commit `4f5da8ca2c87d725637343d0f9a644464587da17`, version 0.8.0 (pysad/version.py; PyPI 0.8.0 uploaded 2026-11-08; HEAD commit is 2026-11-11, so HEAD may differ from the release). Licence: BSD-3-Clause. No restriction. Adoption: 921 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).

### PySAD transform.postprocessing.QuantileFilter

Scope: in scope. Running quantile threshold over the score stream.

1. **Identity.** PySAD transform.postprocessing.QuantileFilter; https://github.com/selimfirat/pysad @ `4f5da8ca2c87`; 0.8.0 (pysad/version.py; PyPI 0.8.0 uploaded 2026-11-08; HEAD commit is 2026-11-11, so HEAD may differ from the release); BSD-3-Clause; 921 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).
2. **Default path.** examples/example_quantile_filter.py: model = LODA(); quantile_filter = QuantileFilter(q=0.9); predicted = quantile_filter.fit_transform_partial(model.fit_score_partial(x)). Default q=0.95.
3. **Adaptive quantity.** Threshold: P2 running q-quantile of all previous scores. Update rule: fit_transform_partial labels with the quantile of previous scores, then meter.update(score) unconditionally.
4. **Learning region.** All scores. Evidence (read in the code):
   - `pysad/transform/postprocessing/postprocessors.py` lines 157:
     ```python
             self.meter.update(score)
     ```
   - `pysad/transform/postprocessing/postprocessors.py` lines 181-183:
     ```python
             label = self.transform_partial(score)
             self.fit_partial(score)
             return label
     ```
   - `pysad/transform/postprocessing/postprocessors.py` lines 170:
     ```python
             return float(self.meter.num_items > 0 and score >= self.meter.get())
     ```
5. **Learns from its own alarms.** yes.
6. **Memory.** Whole history (P2, constant memory).
7. **Direction and bounds.** Symmetric, no clamps.
8. **Alarm logic.** Per-sample label; no delay or suppression.
9. **Operator controls.** None on the filter. Docs show a loop that withholds alerting points from the model (not from the filter).
10. **Documentation.** 'It keeps an estimate of the quantile in constant memory, so it uses every score since the start of the stream.' and 'the filter does not forget old scores. Thus it follows a change in the scores slowly.' (docs/guides/alerts.rst 138, 151)
11. **Closest tt1 rule.** tracker. Differs: Rank-based whole-history quantile with ~1/n influence, not a fixed-step tracker. Unlike river's QuantileFilter it does not wrap or protect the detector: the example model learns from every point too.
12. **Predictions (hypotheses, not results).** Sustained: absorb, slowly: after attack scores exceed (1-q) of the history the quantile reaches them; the model also learns the attack (fit_score_partial). Loud pulses: resist: rank-based. Frog: resist: rank quantile cannot be raised from below. Sub-event pulses: resist: no exclusion logic; behaves like small loud pulses.
13. **Runnable here.** In-process (pip install, CPU only); seconds to minutes for 1e5-1e6 samples; well under 1 GB RAM.

Notes: Examples in examples/*.py and docs/guides/alerts.rst call model.fit_score_partial(x) (model learns every point) and then calibrator.fit_transform_partial(score). The docstring states it is a port of river's QuantileFilter (postprocessors.py 132).

Unresolved: QuantileMeter (pysad/statistics/quantile_meter.py) not read line by line.

### PySAD ConformalProbabilityCalibrator (+ fixed ThresholdFilter)

Scope: in scope. Calibrated value = rank of the score in a sliding window of recent scores; the alarm is calibrated >= fixed cut, so the effective threshold is a sliding-window quantile.

1. **Identity.** PySAD ConformalProbabilityCalibrator (+ fixed ThresholdFilter); https://github.com/selimfirat/pysad @ `4f5da8ca2c87`; 0.8.0 (pysad/version.py; PyPI 0.8.0 uploaded 2026-11-08; HEAD commit is 2026-11-11, so HEAD may differ from the release); BSD-3-Clause; 921 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).
2. **Default path.** examples/example_probability_calibration.py and docs/guides/alerts.rst: model = LODA(); calibrator = ConformalProbabilityCalibrator(window_size=300 or 1000); calibrated = calibrator.fit_transform_partial(model.fit_score_partial(x)); alert if t >= warm-up and calibrated >= 0.95/0.99. Constructor default window_size=300.
3. **Adaptive quantity.** Threshold (implicit): the (cut)-quantile of the last window_size scores. Update rule: window.update(score) on every fit_partial (FIFO deque); fit_transform_partial fits first, then transforms.
4. **Learning region.** All scores, including the scored one and alerting ones; in the docs' 'Keep anomalies out of the model' loop the calibrator still fits every score. Evidence (read in the code):
   - `pysad/transform/probability_calibration/conformal_prediction.py` lines 36:
     ```python
             self.window.update(score)
     ```
   - `pysad/transform/probability_calibration/conformal_prediction.py` lines 52:
     ```python
             return sum(1 for s in scores if s < score) / len(scores)
     ```
   - `examples/example_probability_calibration.py` lines 16-19:
     ```python
             calibrated = calibrator.fit_transform_partial(score)
             # 0.95 means that the score is higher than 95% of the last 300 scores.
             # Skip the first 100 points, while the model and the calibrator warm up.
             if t >= 100 and calibrated >= 0.95:
     ```
   - `docs/guides/alerts.rst` lines 190-193:
     ```python
            if calibrator.fit_transform_partial(score) >= 0.99:
                alerts.append(t)  # alert, and keep the point out of the model
            else:
                model.fit_partial(x)
     ```
5. **Learns from its own alarms.** yes.
6. **Memory.** Sliding window of window_size scores (default 300).
7. **Direction and bounds.** Symmetric; no clamp. Output 0.0 before the first fit.
8. **Alarm logic.** Per-sample; user-side warm-up skip (t >= 100 in example).
9. **Operator controls.** window_size. The docs' protective loop withholds alerting points from the model only; the calibrator keeps fitting them.
10. **Documentation.** 'With fit_score_partial, the model learns from every point, and also from anomalies. As a result, a long anomaly can become normal for the model.' (docs/guides/alerts.rst 176). Silent on the calibrator window absorbing anomalies.
11. **Closest tt1 rule.** daily. Differs: Quantile of a short sliding window (300 samples) recomputed every sample, rather than a once-a-day quantile of the previous day; no episode exclusion.
12. **Predictions (hypotheses, not results).** Sustained: absorb, fast: with a constant attack score, after about (1-cut)*window_size samples (16 of 300 at 0.95) the score is no longer above 95% of the window and the alarm stops. Loud pulses: resist: rank-based; one pulse is one sample in the window. Frog: resist: mass just under the cut cannot raise a rank quantile. Sub-event pulses: resist: no exclusion logic.
13. **Runnable here.** In-process (pip install, CPU only); seconds to minutes for 1e5-1e6 samples; well under 1 GB RAM.

Notes: Examples in examples/*.py and docs/guides/alerts.rst call model.fit_score_partial(x) (model learns every point) and then calibrator.fit_transform_partial(score). ThresholdFilter (postprocessors.py 186-218) is fixed: 'Does nothing, because the threshold is fixed.' (line 199).

### PySAD GaussianTailProbabilityCalibrator

Scope: in scope. Gaussian normaliser (mean, variance over a window) of the scores; alarm is a fixed cut on the calibrated value.

1. **Identity.** PySAD GaussianTailProbabilityCalibrator; https://github.com/selimfirat/pysad @ `4f5da8ca2c87`; 0.8.0 (pysad/version.py; PyPI 0.8.0 uploaded 2026-11-08; HEAD commit is 2026-11-11, so HEAD may differ from the release); BSD-3-Clause; 921 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).
2. **Default path.** docs/guides/alerts.rst 71-77: calibrator = GaussianTailProbabilityCalibrator(window_size=1000); same loop as the conformal calibrator. Defaults running_statistics=True, window_size=8000, short_window_size=10.
3. **Adaptive quantity.** Score normaliser: running mean and variance of the last window_size scores. Update rule: avg_meter.update(score); var_meter.update(score) on every fit_partial.
4. **Learning region.** All scores. Evidence (read in the code):
   - `pysad/transform/probability_calibration/gaussian_tail.py` lines 67-68:
     ```python
             self.avg_meter.update(score)
             self.var_meter.update(score)
     ```
   - `pysad/transform/probability_calibration/gaussian_tail.py` lines 125:
     ```python
             return 1 - self._qfunction(short_mean, mean, std)
     ```
5. **Learns from its own alarms.** yes.
6. **Memory.** Sliding window of window_size scores (default 8000); running_statistics=False gives whole history.
7. **Direction and bounds.** Symmetric; no floor on variance (zero variance returns 1.0/0.5/0.0).
8. **Alarm logic.** Short-term average of the last 10 scores is compared, which smooths single spikes. No suppression.
9. **Operator controls.** window_size, short_window_size, running_statistics.
10. **Documentation.** 'keeps the mean and the variance of the scores in a window, and updates them with each score' (docs/guides/alerts.rst 71). Silent on anomalies entering.
11. **Closest tt1 rule.** ewma. Differs: Sliding-window mean + variance instead of an EWMA; alarm on a 10-sample short average.
12. **Predictions (hypotheses, not results).** Sustained: absorb: the window fills with attack scores and the mean rises to them. Loud pulses: absorb: loud pulses inflate the window variance and lower the calibrated value of later anomalies. Frog: absorb: just-under scores raise mean and variance. Sub-event pulses: absorb: no exclusion; but the 10-sample short average may keep very short pulses from alarming at all.
13. **Runnable here.** In-process (pip install, CPU only); seconds to minutes for 1e5-1e6 samples; well under 1 GB RAM.

Notes: Examples in examples/*.py and docs/guides/alerts.rst call model.fit_score_partial(x) (model learns every point) and then calibrator.fit_transform_partial(score).

### PySAD SPOTProbabilityCalibrator

Scope: in scope. SPOT/DSPOT: GPD tail threshold z_q refitted at run time on peaks.

1. **Identity.** PySAD SPOTProbabilityCalibrator; https://github.com/selimfirat/pysad @ `4f5da8ca2c87`; 0.8.0 (pysad/version.py; PyPI 0.8.0 uploaded 2026-11-08; HEAD commit is 2026-11-11, so HEAD may differ from the release); BSD-3-Clause; 921 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).
2. **Default path.** examples/example_spot_calibration.py and docs/guides/alerts.rst 84-95: calibrator = SPOTProbabilityCalibrator(q=1e-3, num_init=500); alert if calibrator.fit_transform_partial(model.fit_score_partial(x)) > 1 - q. Defaults q=1e-4, num_init=1000, level=0.98, depth=0, max_peaks=1000.
3. **Adaptive quantity.** Threshold z_q = t + sigma/gamma((q n/N_t)^-gamma - 1); t fixed at init, GPD refitted on peaks. Update rule: Scores above z_q return before any update; scores between t and z_q are added as peaks and the GPD is refitted; all scores below z_q increment n.
4. **Learning region.** All except flagged samples (x > z_q); the first num_init scores are all used to initialise t and the peaks. Evidence (read in the code):
   - `pysad/transform/probability_calibration/spot.py` lines 91-95:
     ```python
             elif x > self.z_q_:
                 return self  # An anomaly does not update the calibrator.
             else:
                 self.num_scores_ += 1
                 if x > self.t_:
     ```
   - `pysad/transform/probability_calibration/spot.py` lines 135-137:
     ```python
             calibrated = self.transform_partial(score)
             self.fit_partial(score)
             return calibrated
     ```
5. **Learns from its own alarms.** no.
6. **Memory.** Last max_peaks=1000 peaks for the GPD fit; n and N_t count everything since init (count-based ratio). DSPOT window of depth (default 0, off).
7. **Direction and bounds.** t fixed after init; z_q can move up or down; no clamp. z_q is inf until the first peak if no initial score exceeds t.
8. **Alarm logic.** Per-sample > 1-q. No delay or suppression.
9. **Operator controls.** q, num_init, level, depth, max_peaks.
10. **Documentation.** 'A score gets a calibrated value above 1 - q when the score is above calibrator.threshold_. The calibrator does not learn from these scores.' (docs/guides/alerts.rst 97)
11. **Closest tt1 rule.** SPOT. Differs: Matches the tt1 SPOT rule (alarms left out, sub-alarm peaks update the tail). Fits on a bounded deque of 1000 peaks; DSPOT baseline window (if depth > 0) also skips anomalies (spot.py 92 returns before line 100 appends).
12. **Predictions (hypotheses, not results).** Sustained: resist: attack scores above z_q are withheld, the alarm persists. Loud pulses: resist: pulses above z_q are withheld. Frog: absorb: scores kept between t and z_q are peaks and refit the GPD upward. Sub-event pulses: resist: exclusion is per sample, so short pulses above z_q are withheld too.
13. **Runnable here.** In-process (pip install, CPU only); seconds to minutes for 1e5-1e6 samples; well under 1 GB RAM.

Notes: Examples in examples/*.py and docs/guides/alerts.rst call model.fit_score_partial(x) (model learns every point) and then calibrator.fit_transform_partial(score). Initialisation uses every one of the first num_init scores, so an attack present during initialisation is learned.

### PySAD AnomalyLikelihoodProbabilityCalibrator (NuPIC anomaly likelihood port)

Scope: in scope. Gaussian of short-term score averages over a long window, re-estimated every 100 scores.

1. **Identity.** PySAD AnomalyLikelihoodProbabilityCalibrator (NuPIC anomaly likelihood port); https://github.com/selimfirat/pysad @ `4f5da8ca2c87`; 0.8.0 (pysad/version.py; PyPI 0.8.0 uploaded 2026-11-08; HEAD commit is 2026-11-11, so HEAD may differ from the release); BSD-3-Clause; 921 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).
2. **Default path.** examples/example_anomaly_likelihood.py and docs/guides/alerts.rst 104-115: calibrator = AnomalyLikelihoodProbabilityCalibrator(); alert if fit_transform_partial(score) >= 1 - 1e-5. Defaults learning_period=288, num_estimation_samples=100, window_size=8640, reestimation_period=100, short_window_size=10.
3. **Adaptive quantity.** Score normaliser: mean and std of 10-sample averages over the last 8640 scores. Update rule: Every score is stored in the ring buffer; the Gaussian is refitted every reestimation_period scores from all stored scores.
4. **Learning region.** All scores (after the learning_period skip). Evidence (read in the code):
   - `pysad/transform/probability_calibration/anomaly_likelihood.py` lines 67-69:
     ```python
             self.scores_[self.num_scores_ % self.window_size] = score
             self.short_window_.append(score)
             self.num_scores_ += 1
     ```
   - `pysad/transform/probability_calibration/anomaly_likelihood.py` lines 72-75:
     ```python
             if self.num_scores_ == num_init or (
                 self.num_scores_ > num_init and self.num_scores_ % self.reestimation_period == 0
             ):
                 self._fit_gaussian()
     ```
   - `pysad/transform/probability_calibration/anomaly_likelihood.py` lines 134-135:
     ```python
             self.mean_ = max(float(averages.mean()), 0.03)
             self.std_ = math.sqrt(max(float(averages.var()), 0.0003))
     ```
   - `pysad/transform/probability_calibration/anomaly_likelihood.py` lines 99-100:
     ```python
             if tail <= 1e-5 and prev_tail <= 1e-5:
                 tail = 1e-3
     ```
5. **Learns from its own alarms.** yes.
6. **Memory.** Window of 8640 scores; refit every 100 scores.
7. **Direction and bounds.** Floors: mean >= 0.03, variance >= 0.0003 (assume scores in [0,1]). Two-sided tail.
8. **Alarm logic.** Only the first score of a run reaches 1 - 1e-5; later scores of the run are capped at 1 - 1e-3, so with the paper threshold a sustained run alarms once.
9. **Operator controls.** Window, periods. No freeze.
10. **Documentation.** 'During a run of anomalous scores, only the first score reaches 1 - 1e-5. The next scores of the run get 0.999.' (docs/guides/alerts.rst 117). Silent on anomalies entering the fit.
11. **Closest tt1 rule.** ewma. Differs: Windowed Gaussian on 10-sample averages, refitted every 100 samples, with variance floor and a one-alert-per-run cap; no exclusion.
12. **Predictions (hypotheses, not results).** Sustained: absorb: the alarm stops after the first sample by design (cap), and the Gaussian also absorbs the run within the 8640 window. Loud pulses: absorb: pulse averages inflate the fitted variance; partly limited because a pulse moves a 10-sample average only a little. Frog: absorb: averages kept just under the cut raise the fitted mean/std at each refit. Sub-event pulses: resist (inferred): short pulses barely move the 10-sample average, so they neither alarm nor shift the fit much.
13. **Runnable here.** In-process (pip install, CPU only); seconds to minutes for 1e5-1e6 samples; well under 1 GB RAM.

Notes: Port of NuPIC AnomalyLikelihood; group C covers the reference code.

### PySAD NonparametricDynamicThresholdPostprocessor (Telemanom threshold, streaming)

Scope: in scope. Threshold mean + z*std chosen per sample over a window of EWMA-smoothed scores.

1. **Identity.** PySAD NonparametricDynamicThresholdPostprocessor (Telemanom threshold, streaming); https://github.com/selimfirat/pysad @ `4f5da8ca2c87`; 0.8.0 (pysad/version.py; PyPI 0.8.0 uploaded 2026-11-08; HEAD commit is 2026-11-11, so HEAD may differ from the release); BSD-3-Clause; 921 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).
2. **Default path.** examples/example_dynamic_threshold.py: model = MedianAbsoluteDeviation(window_size=250); postprocessor = NonparametricDynamicThresholdPostprocessor(); anomaly_score = postprocessor.fit_transform_partial(model.fit_score_partial(x[:1])); alarm if > 0. Defaults window_size=2100, span=105, p=0.13, z in 2.5..10.
3. **Adaptive quantity.** Threshold: mean + z*std of the last 2100 smoothed scores, z chosen by the Telemanom objective. Update rule: Every score is smoothed and written to the ring buffer; thresholds are recomputed from the whole window on each transform.
4. **Learning region.** All scores; the objective scores candidates by removing points above each candidate, but the candidate thresholds themselves are mean + z*std of the full window including flagged points. Evidence (read in the code):
   - `pysad/transform/postprocessing/running_postprocessors.py` lines 120-122:
     ```python
             self._ewma_sum = score + decay * self._ewma_sum
             self._ewma_weight = 1.0 + decay * self._ewma_weight
             self.smoothed_[self.num_seen_ % self.window_size] = self._ewma_sum / self._ewma_weight
     ```
   - `pysad/transform/postprocessing/running_postprocessors.py` lines 144-146:
     ```python
             mean = window.mean()
             std = window.std()
             thresholds = mean + self._z * std  # (num_z,)
     ```
5. **Learns from its own alarms.** yes.
6. **Memory.** Window of 2100 smoothed scores; EWMA span 105.
7. **Direction and bounds.** z between 2.5 and 10; no clamp on the level.
8. **Alarm logic.** Pruning keeps only sequences whose maxima separate by more than p=13%; output 0 otherwise.
9. **Operator controls.** window_size, span, p, z_values.
10. **Documentation.** Silent on anomalies entering the window (docs/guides/alerts.rst 122 describes the method only).
11. **Closest tt1 rule.** ewma. Differs: EWMA smoothing then a sliding-window mean + z*std with z picked per sample and sequence pruning (Telemanom); no exclusion of flagged scores from the window.
12. **Predictions (hypotheses, not results).** Sustained: absorb: the window mean and std rise as attack scores fill it. Loud pulses: absorb: pulses inflate std and raise every candidate threshold; pruning against the largest maxima can also drop smaller anomalies. Frog: absorb: just-under smoothed scores raise mean and std. Sub-event pulses: absorb: no exclusion; EWMA smoothing (span 105) also damps short pulses.
13. **Runnable here.** In-process (pip install, CPU only); seconds to minutes for 1e5-1e6 samples; well under 1 GB RAM.

Notes: Examples in examples/*.py and docs/guides/alerts.rst call model.fit_score_partial(x) (model learns every point) and then calibrator.fit_transform_partial(score).

### PySAD models.PEWMA (probabilistic EWMA normaliser)

Scope: in scope. Score normaliser (|Z| against EWMA mean/std) that weights each new value by its likelihood.

1. **Identity.** PySAD models.PEWMA (probabilistic EWMA normaliser); https://github.com/selimfirat/pysad @ `4f5da8ca2c87`; 0.8.0 (pysad/version.py; PyPI 0.8.0 uploaded 2026-11-08; HEAD commit is 2026-11-11, so HEAD may differ from the release); BSD-3-Clause; 921 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).
2. **Default path.** Constructor defaults alpha=0.99, beta=1.0, training_period=14; fit_score_partial per value. No alarm in the class; the paper's alarm is a threshold on P_t (docstring).
3. **Adaptive quantity.** Normaliser: EWMA mean s1 and second moment s2. Update rule: weight = (1 - beta*P_t)*alpha after training; s1 <- weight*s1 + (1-weight)*x.
4. **Learning region.** All values, unlikely ones at reduced weight: new-value weight is 1-alpha = 0.01 for very improbable values and about 0.4 for the most likely ones (P_t <= 0.399). Evidence (read in the code):
   - `pysad/models/pewma.py` lines 81-85:
     ```python
                 p = math.exp(-(self._z(x) ** 2) / 2.0) / math.sqrt(2.0 * math.pi)
                 weight = (1.0 - self.beta * p) * self.alpha
     
             self.s1_ = weight * self.s1_ + (1.0 - weight) * x
             self.s2_ = weight * self.s2_ + (1.0 - weight) * x**2
     ```
5. **Learns from its own alarms.** partial.
6. **Memory.** Exponential; floor on the new-value weight of 1-alpha = 0.01, so an improbable value still moves the mean by 1%.
7. **Direction and bounds.** Symmetric; no clamp.
8. **Alarm logic.** None in the class.
9. **Operator controls.** alpha, beta, training_period.
10. **Documentation.** 'After training, a likely value gets a small weight alpha_t. It moves the estimates more than an unlikely value.' (pewma.py 27-28)
11. **Closest tt1 rule.** ewma. Differs: EWMA with likelihood-dependent weight: flagged-looking values get weight 0.01 instead of being excluded.
12. **Predictions (hypotheses, not results).** Sustained: absorb: at 1% per step the mean reaches the attack within a few hundred samples, then the weight grows as Z falls. Loud pulses: absorb, partly: each pulse moves s1 by 1% but s2 by 1% of a large square, inflating std. Frog: absorb: just-under values have moderate likelihood and higher weight. Sub-event pulses: absorb: no exclusion, reduced weight only.
13. **Runnable here.** In-process (pip install, CPU only); seconds to minutes for 1e5-1e6 samples; well under 1 GB RAM.

Notes: Not on the default calibration path of the alerts guide; included because it is the one PySAD component with flagged-at-reduced-weight learning.

Unresolved: Alarm threshold is left to the user; impact depends on it.

## StreamAD

Repository https://github.com/Fengrui-Liu/StreamAD, commit `d2e38f4c35349b05c9bbd3ac753efc9a96e0ab05`, version 0.3.1 (streamad/version.py; PyPI 0.3.1, 2023-05-11). Licence: Apache-2.0. No restriction. Adoption: 65 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).

### StreamAD model.SpotDetector

Scope: in scope. README quickstart detector; DSPOT-style threshold that updates at run time.

1. **Identity.** StreamAD model.SpotDetector; https://github.com/Fengrui-Liu/StreamAD @ `d2e38f4c3534`; 0.3.1 (streamad/version.py; PyPI 0.3.1, 2023-05-11); Apache-2.0; 65 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).
2. **Default path.** README Quick Start: model = SpotDetector(); score = model.fit_score(x). Defaults prob=1e-4, back_mean_len=20, num_threshold_up/down=20, deviance_ratio=0.01, global_memory=True; BaseDetector window_len=50, score_first=False. Score 1.0 = beyond the extreme quantile.
3. **Adaptive quantity.** Threshold: extreme quantile from a GPD fitted to the top-20 (bottom-20) values of detrended X; init_threshold = 20th largest; DSPOT baseline = mean of the last 20 raw X. Update rule: fit() appends every X to the back-mean window; if detrended X > init_threshold it recomputes the top-20 peaks (from the 50-sample window plus all previous top-20 with global_memory) and refits the GPD. No check against the extreme quantile, and fit runs before score.
4. **Learning region.** All samples, including those scored 1.0 (no exclusion of alarms). Evidence (read in the code):
   - `streamad/model/spot_Detector.py` lines 345-349:
     ```python
                 if self.normal_X > self.init_threshold["up"]:
                     self._update_one_side("up")
     
                 elif self.normal_X < self.init_threshold["down"]:
                     self._update_one_side("down")
     ```
   - `streamad/model/spot_Detector.py` lines 319:
     ```python
             self.back_mean_window.append(X)
     ```
   - `streamad/model/spot_Detector.py` lines 276-280:
     ```python
                 self.history_peaks[side] = heapq.nlargest(
                     self.num_threshold[side],
                     candidates,
                 )
                 self.init_threshold[side] = self.history_peaks[side][-1]
     ```
   - `streamad/model/spot_Detector.py` lines 371-375:
     ```python
             elif (
                 self.normal_X > self.extreme_quantile["up"]
                 or self.normal_X < self.extreme_quantile["down"]
             ):
                 score = 1.0
     ```
   - `streamad/base/detector.py` lines 96:
     ```python
                 score = self.fit(X, timestamp).score(X, timestamp)
     ```
5. **Learns from its own alarms.** yes.
6. **Memory.** Peaks: top 20 ever seen (global_memory=True keeps them forever); detrending mean: last 20 raw values.
7. **Direction and bounds.** Two-sided (up and down tails). No clamp. Early return with score 0 and no update when |X - back_mean|/back_mean < 0.01.
8. **Alarm logic.** Score in [0,1]; 1.0 beyond the extreme quantile. No delay or suppression.
9. **Operator controls.** global_memory, back_mean_len, num_threshold_*, prob, deviance_ratio, score_first.
10. **Documentation.** Silent (README and docstring describe parameters only).
11. **Closest tt1 rule.** SPOT. Differs: Unlike SPOT/DSPOT in the paper and the tt1 SPOT rule, alarms are not left out: any value beyond init_threshold, including one beyond the extreme quantile, enters the top-20 peaks, and the DSPOT mean window takes every raw value. The current sample updates the model before it is scored. Peaks are only the top 20 values (count, not a quantile level).
12. **Predictions (hypotheses, not results).** Sustained: absorb: the 20-sample back mean catches up with a level shift within about 20 samples, after which |X - back_mean| is small (and below 1% of back_mean returns score 0). Loud pulses: absorb: each loud pulse enters the permanent top-20 list, raising init_threshold and the extreme quantile for later anomalies. Frog: absorb: values between init_threshold and the extreme quantile refit the GPD upward. Sub-event pulses: absorb: no exclusion to evade; short pulses enter the peaks.
13. **Runnable here.** In-process (pip install, CPU only); seconds to minutes for 1e5-1e6 samples; well under 1 GB RAM. Depends on scipy; tdigest only for the calibrator.

Notes: Docstring says window_len 'Defaults to 200' but the class passes **kwargs and BaseDetector defaults window_len=50 (read in the code). zspot_Detector.py has a related ZSpot variant that also updates peaks without an alarm check (lines 150-153), not on the quickstart path.

Unresolved: The effect of the down-side tail and the deviance early-return on real streams was not worked out.

### StreamAD process.ZScoreCalibrator

Scope: in scope. Calibrator that maps scores to [0,1] with 1.0 meaning anomaly, from running mean/std of the scores.

1. **Identity.** StreamAD process.ZScoreCalibrator; https://github.com/Fengrui-Liu/StreamAD @ `d2e38f4c3534`; 0.3.1 (streamad/version.py; PyPI 0.3.1, 2023-05-11); Apache-2.0; 65 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).
2. **Default path.** docs/source/example/calibrator_usage.ipynb: detector = KNNDetector(); calibrator = ZScoreCalibrator(sigma=3, extreme_sigma=5); normalized_score = calibrator.normalize(detector.fit_score(x)). Default is_global=True.
3. **Adaptive quantity.** Normaliser: running mean, std, min, max of all scores (global) or last window_len (rolling). Update rule: score_stats.update(score) on every normalize call, before the z-score is computed.
4. **Learning region.** All scores, including the current one. Evidence (read in the code):
   - `streamad/process/zscore_calibrator.py` lines 34:
     ```python
             self.score_stats.update(score)
     ```
   - `streamad/process/zscore_calibrator.py` lines 53-54:
     ```python
             if sigma > self.extreme_sigma:
                 return 1.0
     ```
   - `streamad/process/zscore_calibrator.py` lines 10:
     ```python
             is_global: bool = True,
     ```
5. **Learns from its own alarms.** yes.
6. **Memory.** Whole history by default (is_global=True); window_len=100 if rolling.
7. **Direction and bounds.** Symmetric (absolute z). No clamp.
8. **Alarm logic.** 1.0 above extreme_sigma; min-max scaled between sigma and extreme_sigma; 0 below sigma.
9. **Operator controls.** sigma, extreme_sigma, is_global, window_len.
10. **Documentation.** 'Global way ... It can "remember" the distribution of all history scores with little memory usage.' (calibrator_usage.ipynb, first markdown cell). Silent on anomalies.
11. **Closest tt1 rule.** ewma. Differs: Whole-history mean/std (count-based) by default instead of an EWMA; includes the scored value itself.
12. **Predictions (hypotheses, not results).** Sustained: absorb, slowly with long history (1/n). Loud pulses: absorb: pulses inflate std. Frog: absorb. Sub-event pulses: absorb: no exclusion.
13. **Runnable here.** In-process (pip install, CPU only); seconds to minutes for 1e5-1e6 samples; well under 1 GB RAM.

Unresolved: StreamStatistic rolling branch not read in detail.

### StreamAD process.TDigestCalibrator

Scope: in scope. Calibrator: 1.0 when the score is above a running percentile of all scores.

1. **Identity.** StreamAD process.TDigestCalibrator; https://github.com/Fengrui-Liu/StreamAD @ `d2e38f4c3534`; 0.3.1 (streamad/version.py; PyPI 0.3.1, 2023-05-11); Apache-2.0; 65 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).
2. **Default path.** calibrator_usage.ipynb: TDigestCalibrator(percentile_up=99, percentile_down=0); defaults percentile_up=95, is_global=True.
3. **Adaptive quantity.** Threshold: t-digest percentile of all scores. Update rule: score_stats.update(score) on every call before the comparison.
4. **Learning region.** All non-zero scores (a score of 0 or None returns None and is not added). Evidence (read in the code):
   - `streamad/process/tdigest_calibrator.py` lines 41-44:
     ```python
             self.score_deque.append(score)
     
             if self.is_global:
                 self.score_stats.update(score)
     ```
   - `streamad/process/tdigest_calibrator.py` lines 54:
     ```python
             if score > percentile_up or score < percentile_down:
     ```
5. **Learns from its own alarms.** yes.
6. **Memory.** Whole history (global); last 100 if rolling.
7. **Direction and bounds.** Symmetric; no clamp.
8. **Alarm logic.** Per sample, binary output.
9. **Operator controls.** percentiles, is_global, window_len.
10. **Documentation.** Silent.
11. **Closest tt1 rule.** tracker. Differs: Rank-based whole-history percentile (t-digest), not a fixed-step tracker.
12. **Predictions (hypotheses, not results).** Sustained: absorb, slowly. Loud pulses: resist: rank-based. Frog: resist: rank-based. Sub-event pulses: resist: no exclusion logic.
13. **Runnable here.** In-process (pip install, CPU only); seconds to minutes for 1e5-1e6 samples; well under 1 GB RAM. Requires the third-party tdigest package.

Unresolved: tdigest package internals not read.

## Merlion

Repository https://github.com/salesforce/Merlion, commit `39507642dc3d7b8d04232e34e9f36b372cf4912d`, version setup.py says 2.0.2; PyPI latest salesforce-merlion 2.0.4 (2024-06-20). HEAD is a bulk 'Add files via upload' commit of 2026-03-11 and the repo carries CONTRIBUTING-ARCHIVED.md. Licence: BSD-3-Clause. No restriction. Bundles Amazon randomcutforest-core-1.0.jar (Apache-2.0). Adoption: 10,063 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).

### Merlion post-rules (AnomScoreCalibrator + AggregateAlarms threshold)

Scope: out of scope / static control. Static control: calibrator and threshold are fitted in train() and not touched by get_anomaly_label.

1. **Identity.** Merlion post-rules (AnomScoreCalibrator + AggregateAlarms threshold); https://github.com/salesforce/Merlion @ `39507642dc3d`; setup.py says 2.0.2; PyPI latest salesforce-merlion 2.0.4 (2024-06-20). HEAD is a bulk 'Add files via upload' commit of 2026-03-11 and the repo carries CONTRIBUTING-ARCHIVED.md; BSD-3-Clause; 10,063 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).
2. **Default path.** README: model = DefaultDetector(DefaultDetectorConfig()); model.train(train_data=train_data); test_pred = model.get_anomaly_label(time_series=test_data). post_rule = calibrator (enable_calibrator=True) then AggregateAlarms(alm_threshold=3.0).
3. **Adaptive quantity.** None at inference. Calibrator anchors (quantiles of training scores) and alm_threshold are set in train(). Update rule: get_anomaly_label applies post_rule(scores) only; calibrator.train returns early once trained unless retrain_calibrator=True; TSADEvaluator retrains with no_train post-rule config.
4. **Learning region.** Training batch only (which may contain anomalies; no exclusion). Evidence (read in the code):
   - `merlion/models/anomaly/base.py` lines 286-287:
     ```python
             scores = self.get_anomaly_score(time_series, time_series_prev)
             return self.post_rule(scores) if self.post_rule is not None else scores
     ```
   - `merlion/post_process/calibrate.py` lines 68-69:
     ```python
             if self.interpolator is not None and not retrain_calibrator:
                 return self(anomaly_scores)
     ```
   - `merlion/evaluate/anomaly.py` lines 404:
     ```python
             no_train = dict(metric=None, unsup_quantile=None, retrain_calibrator=False)
     ```
   - `merlion/post_process/threshold.py` lines 48:
     ```python
                 scores = np.where(np.abs(scores) >= self.alm_threshold, scores, 0.0)
     ```
5. **Learns from its own alarms.** no.
6. **Memory.** Fixed after training.
7. **Direction and bounds.** Fixed.
8. **Alarm logic.** AggregateAlarms: alarm only when min_alm_in_window=2 points exceed the threshold within alm_window_minutes=60, then suppress for alm_suppress_minutes=120 (threshold.py 161-167, 206-215).
9. **Operator controls.** enable_calibrator, enable_threshold, threshold object, retrain_calibrator flag at train time.
10. **Documentation.** 'retrain_calibrator: Whether to re-train the calibrator on a new sequence of anomaly scores, if it has already been trained once. In practice, we find better results if this is False.' (calibrate.py 64-66). Silent on anomalies.
11. **Closest tt1 rule.** on_delay. Differs: Static threshold with a 2-in-60-minutes count rule and a 120-minute suppression after each alarm, instead of a 60 s duration on-delay.
12. **Predictions (hypotheses, not results).** Sustained: resist (post-rule level): threshold never moves; the underlying model may absorb, see the RRCF row. Loud pulses: resist. Frog: resist. Sub-event pulses: resist (single-point pulses fail the 2-in-60-min count only if isolated).
13. **Runnable here.** In-process (pip install salesforce-merlion); the DefaultDetector's RRCF needs a Java JDK via JPype. CPU, under 2 GB RAM for NAB-sized series.

Notes: Code read is HEAD (setup.py 2.0.2), PyPI ships 2.0.4.

Unresolved: Diff between HEAD and the 2.0.4 wheel not checked.

### Merlion DefaultDetector: RandomCutForest member with online_updates=True

Scope: in scope. In the quickstart DefaultDetector the RRCF forest is updated with every test point at inference, while calibrator and threshold stay fixed.

1. **Identity.** Merlion DefaultDetector: RandomCutForest member with online_updates=True; https://github.com/salesforce/Merlion @ `39507642dc3d`; setup.py says 2.0.2; PyPI latest salesforce-merlion 2.0.4 (2024-06-20). HEAD is a bulk 'Add files via upload' commit of 2026-03-11 and the repo carries CONTRIBUTING-ARCHIVED.md; BSD-3-Clause; 10,063 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).
2. **Default path.** README DefaultDetector; merlion/models/defaults.py builds DetectorEnsemble(AutoETS, RandomCutForest(online_updates=True, n_estimators=100, max_n_samples=512), ZMS) for univariate data; ensemble combiner Mean of calibrated scores, AggregateAlarms(3.0).
3. **Adaptive quantity.** Model: RRCF tree samples (sample size 512 per tree). Update rule: For each new point: score with getAnomalyScore, then forest.update(point) when online_updates is true.
4. **Learning region.** All points after the last training time, flagged or not. Evidence (read in the code):
   - `merlion/models/anomaly/random_cut_forest.py` lines 159-163:
     ```python
             for i in range(n):
                 jpoint = data_jarray[d * i : d * (i + 1)]
                 scores.append(self.forest.getAnomalyScore(jpoint))
                 if online_updates:
                     self.forest.update(jpoint)
     ```
   - `merlion/models/anomaly/random_cut_forest.py` lines 187:
     ```python
                 new = self._forest_predict(time_series.values[t0:], self.online_updates)
     ```
   - `merlion/models/defaults.py` lines 88-90:
     ```python
                         ModelFactory.create(
                             "RandomCutForest",
                             online_updates=True,
     ```
5. **Learns from its own alarms.** yes.
6. **Memory.** RCF reservoir of 512 points per tree; time decay of the Java 1.0 sampler not set by Merlion (java_params lines 96-104) and not read in the jar.
7. **Direction and bounds.** Model only; calibrator and threshold fixed.
8. **Alarm logic.** Ensemble mean of calibrated z-scores, AggregateAlarms (2 in 60 min, 120 min suppression).
9. **Operator controls.** online_updates flag on the RRCF config (default False in RandomCutForestConfig, True in DefaultDetector).
10. **Documentation.** 'online_updates: Whether to update the model while running using it to evaluate new data.' (random_cut_forest.py 77-78). Silent on anomalies.
11. **Closest tt1 rule.** none. Differs: Model-level absorption (the forest samples attack points) under a fixed threshold; the other two ensemble members (AutoETS without time_series_prev, ZMS) are static at inference, which may keep the ensemble mean high.
12. **Predictions (hypotheses, not results).** Sustained: unclear: RRCF scores fall as attack points fill the reservoir, but the ensemble also averages static ETS and ZMS scores. Loud pulses: unclear: pulses enter the reservoir; effect on the ensemble mean not estimated. Frog: unclear: frog requires a moving threshold; here only the model moves. Sub-event pulses: unclear.
13. **Runnable here.** In-process with a Java JDK (JPype + bundled RCF 1.0 jar); CPU, under 2 GB.

Notes: MSESDetector (merlion/models/anomaly/forecast_based/mses.py 26, 45-51) also defaults to online_updates=True and calls self.update(full_ts) inside get_anomaly_score; not on the quickstart path. AutoETS with time_series_prev and refit=True (ets.py 48, 173) refits on time_series_prev, which includes earlier flagged data, in streaming use.

Unresolved: RCF 1.0 default time decay (lambda) not read; whether repeated get_anomaly_label calls in a streaming loop are the documented usage (README calls it once on the whole test split).

## Orion

Repository https://github.com/sintel-dev/Orion, commit `10b76ac4830af1750c67c85e002a0f36f4395807`, version 0.7.2.dev0 (setup.py); PyPI orion-ml 0.7.1 (2025-03-17). Licence: MIT. No restriction. Adoption: 291 PyPI downloads of orion-ml in the last month (pypistats.org last_month downloads, queried 2026-11-11).

### Orion find_anomalies (window threshold in verified pipelines)

Scope: in scope. The threshold is recomputed at detect() time from the errors of the data being scored.

1. **Identity.** Orion find_anomalies (window threshold in verified pipelines); https://github.com/sintel-dev/Orion @ `10b76ac4830a`; 0.7.2.dev0 (setup.py); PyPI orion-ml 0.7.1 (2025-03-17); MIT; 291 PyPI downloads of orion-ml in the last month (pypistats.org last_month downloads, queried 2026-11-11).
2. **Default path.** README: orion = Orion(pipeline='aer'); orion.fit(train_data); anomalies = orion.detect(new_data). DEFAULT_PIPELINE = 'lstm_dynamic_threshold' (orion/core.py 46). Both aer.json and lstm_dynamic_threshold.json set find_anomalies window_size_portion=0.33, window_step_size_portion=0.1, fixed_threshold=true.
3. **Adaptive quantity.** Threshold per window: mean + 4*std of the window's errors (fixed_threshold=true); with fixed_threshold=false, mean + z*std with z from the Telemanom cost. Update rule: For each window (33% of the series, step 10% of window): threshold = errors.mean() + k*errors.std() over all errors in the window.
4. **Learning region.** All errors in each window, including the ones it flags; batch and non-causal (later errors in the window also count). Evidence (read in the code):
   - `orion/primitives/timeseries_anomalies.py` lines 158-161:
     ```python
         mean = errors.mean()
         std = errors.std()
     
         return mean + k * std
     ```
   - `orion/primitives/timeseries_anomalies.py` lines 394-398:
     ```python
         if fixed_threshold:
             threshold = _fixed_threshold(window)
     
         else:
             threshold = _find_threshold(window, z_range)
     ```
   - `orion/primitives/timeseries_anomalies.py` lines 476-478:
     ```python
             window_end = window_start + window_size
             window = errors[window_start:window_end]
             window_sequences = _find_window_sequences(window, z_range, anomaly_padding, min_percent,
     ```
   - `orion/pipelines/verified/aer/aer.json` lines 42-46:
     ```python
             "orion.primitives.timeseries_anomalies.find_anomalies#1": {
                 "window_size_portion": 0.33,
                 "window_step_size_portion": 0.1,
                 "fixed_threshold": true
             }
     ```
5. **Learns from its own alarms.** yes.
6. **Memory.** Window = 33% of the series passed to detect(); step 10% of the window.
7. **Direction and bounds.** Symmetric; k=4 fixed; no clamp.
8. **Alarm logic.** anomaly_padding=50 points added around each exceedance; pruning drops sequences whose max is within min_percent of the next lower max (default 0.1 in the function, 0.13 in the primitive JSON); overlapping sequences merged.
9. **Operator controls.** Hyperparameters only; no exclusion or freeze.
10. **Documentation.** Silent (README and primitive docstrings describe the method only).
11. **Closest tt1 rule.** daily. Differs: Batch: threshold from the same window it is applied to (non-causal), mean + 4*std rather than a quantile; the 'dynamic' Telemanom search is off in both verified pipelines read.
12. **Predictions (hypotheses, not results).** Sustained: absorb: a level shift covering more than about 1/17 (~6%) of a window pushes mean + 4*std above it (inferred from the formula). Loud pulses: absorb: pulses inflate the window std and raise the threshold for everything else in the window. Frog: unclear: a closed-loop frog is not defined for a batch, non-causal threshold. Sub-event pulses: absorb: no exclusion; padding of 50 merges short pulses.
13. **Runnable here.** In-process; AER and LSTM pipelines need TensorFlow (CPU, a few GB RAM, minutes per signal).

Notes: MLBazaar/MLPrimitives (commit eb1c36da9992d015118b2ef0fe51e7174c3b45af) carries an older copy in mlprimitives/custom/timeseries_anomalies.py without _fixed_threshold, and its _find_threshold lacks the 'best_cost = cost' line, so best_z is the last start point whose cost is finite (read by diff; not run). Orion's model (AER/LSTM) is fixed after fit.

Unresolved: Not checked how many users call detect on streaming chunks versus whole signals.

## adtk

Repository https://github.com/arundo/adtk, commit `6041f5b9a41a57263d8988bdc26a2dfc7ad675c2`, version 0.6.2 (setup.cfg; PyPI 0.6.2, 2020-04-17; repo inactive since 2020). Licence: MPL-2.0. File-level copyleft on modifications; no restriction on running or publishing results. Adoption: 217,187 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).

### ADTK fitted detectors (quickstart SeasonalAD; IQR / quantile bounds)

Scope: out of scope / static control. Bounds are fitted in fit() and fixed in detect(); nothing changes at run time unless the user calls fit again. Static control. The quickstart uses fit_detect on one series, a batch fit on the data being flagged.

1. **Identity.** ADTK fitted detectors (quickstart SeasonalAD; IQR / quantile bounds); https://github.com/arundo/adtk @ `6041f5b9a41a`; 0.6.2 (setup.cfg; PyPI 0.6.2, 2020-04-17; repo inactive since 2020); MPL-2.0; 217,187 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).
2. **Default path.** docs/quickstart.rst: seasonal_ad = SeasonalAD(); anomalies = seasonal_ad.fit_detect(s_train).
3. **Adaptive quantity.** Bounds (IQR: q1 - c*iqr, q3 + c*iqr; quantiles) set at fit time. Update rule: fit_detect = fit(ts) then detect(ts); detect = predict, no refit.
4. **Learning region.** Training batch (in fit_detect, the same series that is flagged; quartiles are robust to a minority of outliers). Evidence (read in the code):
   - `src/adtk/_detector_base.py` lines 247-251:
     ```python
             self.fit(ts)
             return self.detect(ts, return_list=return_list)
     
         detect = predict
         fit_detect = fit_predict
     ```
   - `src/adtk/detector/_detector_1d.py` lines 240-244:
     ```python
         def _fit_core(self, s: pd.Series) -> None:
             if s.count() == 0:
                 raise RuntimeError("Valid values are not enough for training.")
             q1 = s.quantile(0.25)
             q3 = s.quantile(0.75)
     ```
   - `src/adtk/detector/_detector_1d.py` lines 268-269:
     ```python
         def _predict_core(self, s: pd.Series) -> pd.Series:
             predicted = (s > self.abs_high_) | (s < self.abs_low_)
     ```
5. **Learns from its own alarms.** configurable. Default / switch: Quickstart: fit_detect, so the bounds are fitted on the same series they flag (batch, robust quartiles). fit() then detect(new): fixed, no learning.
6. **Memory.** Whatever batch is passed to fit.
7. **Direction and bounds.** Fixed after fit.
8. **Alarm logic.** Per point; aggregators (AndAggregator, OrAggregator) in pipenets.
9. **Operator controls.** Explicit fit/detect split.
10. **Documentation.** Silent.
11. **Closest tt1 rule.** static. Differs: Static after fit; batch refit only when the user calls fit or fit_detect.
12. **Predictions (hypotheses, not results).** Sustained: resist after a separate fit. Loud pulses: resist. Frog: resist. Sub-event pulses: resist.
13. **Runnable here.** In-process (pip install, CPU only); seconds to minutes for 1e5-1e6 samples; well under 1 GB RAM. Last release 2020; may need an older pandas.

Notes: See the PersistAD/LevelShiftAD row for the rolling reference window.

Unresolved: Whether ADTK 0.6.2 imports on current pandas not checked (not installed).

### ADTK PersistAD / LevelShiftAD reference window

Scope: in scope. The reference (baseline) for each point is the median/mean of the preceding raw values, which move with the signal at detect time; the IQR bound on the difference is fixed after fit.

1. **Identity.** ADTK PersistAD / LevelShiftAD reference window; https://github.com/arundo/adtk @ `6041f5b9a41a`; 0.6.2 (setup.cfg; PyPI 0.6.2, 2020-04-17; repo inactive since 2020); MPL-2.0; 217,187 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).
2. **Default path.** PersistAD(window=1, c=3.0, agg='median'); LevelShiftAD(window=<required>, c=6.0). Pipenet: DoubleRollingAggregate(diff='l1') -> InterQuartileRangeAD(c=(None, c)).
3. **Adaptive quantity.** Baseline: rolling median of the preceding window of raw values. Update rule: Left window = RollingAggregate over s.shift(1); difference |right - left| compared with fitted IQR bound.
4. **Learning region.** All preceding raw values, including flagged ones (by construction; these are change detectors). Evidence (read in the code):
   - `src/adtk/transformer/_transformer_1d.py` lines 505-509:
     ```python
                     s_rolling_left = RollingAggregate(
                         agg=agg[0],
                         agg_params=agg_params[0],
                         window=window[0],
                         min_periods=min_periods[0],
     ```
   - `src/adtk/transformer/_transformer_1d.py` lines 511:
     ```python
                     ).transform(s.shift(1))
     ```
   - `src/adtk/transformer/_transformer_1d.py` lines 601-602:
     ```python
                 if diff in ["l1", "l2"]:
                     return abs(s_rolling_right - s_rolling_left)
     ```
5. **Learns from its own alarms.** yes.
6. **Memory.** window points (PersistAD default 1).
7. **Direction and bounds.** Fixed IQR bound on the difference; baseline unbounded.
8. **Alarm logic.** Per point; sign check for side.
9. **Operator controls.** window, c, side, agg.
10. **Documentation.** 'compares time series values with the values of their preceding time windows, and identifies a time point as anomalous if the change of value from its preceding average or median is anomalously large.' (_detector_1d.py 372-374)
11. **Closest tt1 rule.** none. Differs: A differencing change detector: absorption of a sustained shift after `window` points is its stated purpose, not a learned threshold.
12. **Predictions (hypotheses, not results).** Sustained: absorb: by design, only the transition is flagged. Loud pulses: resist: the bound is fixed; pulses are flagged. Frog: unclear: a ramp below the per-step bound is never flagged (slow drift), which is the change-detector analogue of the frog. Sub-event pulses: resist: short pulses are flagged at their edges.
13. **Runnable here.** In-process (pip install, CPU only); seconds to minutes for 1e5-1e6 samples; well under 1 GB RAM.

Notes: Included so the parent can decide whether change detectors count; I would not count this row as threshold absorption.

## luminol

Repository https://github.com/linkedin/luminol, commit `b0dc7df586394578d29389d306223523dc99c827`, version 0.4 (VERSION file; PyPI 0.4, 2017-12-11). Licence: Apache-2.0. No restriction (NOTICE file present). Adoption: 1,149 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).

### Luminol AnomalyDetector (default bitmap_detector, percent-of-max threshold)

Scope: in scope. The alarm threshold is computed from the scores of the series being analysed (20% of the maximum score) on every call.

1. **Identity.** Luminol AnomalyDetector (default bitmap_detector, percent-of-max threshold); https://github.com/linkedin/luminol @ `b0dc7df58639`; 0.4 (VERSION file; PyPI 0.4, 2017-12-11); Apache-2.0; 1,149 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).
2. **Default path.** README Quick Start: detector = luminol.anomaly_detector.AnomalyDetector(ts); anomalies = detector.get_anomalies(). Default algorithm bitmap_detector, refine exp_avg_detector, score_percent_threshold 0.2, no score_threshold for bitmap.
3. **Adaptive quantity.** Threshold = 0.2 * max anomaly score of the same series (batch). Update rule: threshold = self.threshold or max_anom_score * self.score_percent_threshold, computed in _detect_anomalies.
4. **Learning region.** All scores of the series, dominated by the largest (most anomalous) one. Evidence (read in the code):
   - `src/luminol/anomaly_detector.py` lines 111-115:
     ```python
             max_anom_score = anom_scores.max()
             anomalies = []
     
             if max_anom_score:
                 threshold = self.threshold or max_anom_score * self.score_percent_threshold
     ```
   - `src/luminol/anomaly_detector.py` lines 120:
     ```python
                     if value > threshold:
     ```
   - `src/luminol/anomaly_detector.py` lines 53:
     ```python
             self.threshold = score_threshold or ANOMALY_THRESHOLD.get(algorithm_name)
     ```
   - `src/luminol/constants.py` lines 52-55:
     ```python
     ANOMALY_THRESHOLD = {
         'exp_avg_detector': 3,
         'default_detector': 3
     }
     ```
5. **Learns from its own alarms.** yes.
6. **Memory.** The series passed in (batch).
7. **Direction and bounds.** Relative to the maximum; no floor except that a zero max gives no anomalies. Scores under 0.1% of the max are zeroed (algorithms/anomaly_detector_algorithms/__init__.py 53-58).
8. **Alarm logic.** Consecutive points above threshold form intervals; refine algorithm picks the peak timestamp.
9. **Operator controls.** score_threshold (absolute, overrides), score_percent_threshold, algorithm_name.
10. **Documentation.** 'the library does not rely on any predefined threshold on the values of a time series. Instead, it assigns each data point an anomaly score and identifies anomalies using the scores.' (README.md 11). README calls the parameter a 'percentile' (line 115) but the code multiplies the max score (read in the code).
11. **Closest tt1 rule.** none. Differs: Batch threshold proportional to the series maximum; the strongest anomaly sets the bar for all others. Bitmap scores compare lagging and future SAX windows (each capped at 200 points), so a plateau only scores at its edges.
12. **Predictions (hypotheses, not results).** Sustained: absorb: bitmap scores are high only at the edges of a plateau; the middle of a sustained attack is not scored high. Loud pulses: absorb: one loud pulse sets the max and lifts the threshold for every other anomaly in the series. Frog: unclear: batch, and the series max is always above 20% of itself, so something is always flagged when max > 0. Sub-event pulses: absorb: no exclusion; masked by any larger pulse.
13. **Runnable here.** In-process (pip install, CPU only); seconds to minutes for 1e5-1e6 samples; well under 1 GB RAM. Python 2/3 era code (uses pandas-free own TimeSeries; iteritems on its own class).

Notes: Unmaintained (last release 2017).

Unresolved: bitmap_detector scoring details beyond window sizes not traced.

## alibi-detect

Repository https://github.com/SeldonIO/alibi-detect, commit `c2fd0e05c648d353467bdb15fd6149a103b3a981`, version 0.13.0.dev0 (alibi_detect/version.py); PyPI 0.13.0 (2025-12-11). Licence: Business Source License 1.1 (converts to Apache-2.0 four years after each release). Not an open-source licence. The Additional Use Grant allows production use only for non-profit educational institutions; non-production use (reading, research runs) is permitted by BSL. Publishing benchmark results is not prohibited by the text read, but production use by others is restricted. Versions before the BSL change were Apache-2.0 (not checked which). Adoption: 45,308 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).

### alibi-detect od.Mahalanobis (online outlier detector)

Scope: in scope. Documented as online: mean and covariance update with every instance passed to predict; threshold fixed.

1. **Identity.** alibi-detect od.Mahalanobis (online outlier detector); https://github.com/SeldonIO/alibi-detect @ `c2fd0e05c648`; 0.13.0.dev0 (alibi_detect/version.py); PyPI 0.13.0 (2025-12-11); Business Source License 1.1 (converts to Apache-2.0 four years after each release); 45,308 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).
2. **Default path.** doc/source/od/methods/mahalanobis.ipynb: od = Mahalanobis(threshold=10., n_components=2, std_clip=3, start_clip=100); preds = od.predict(X). Defaults threshold=None (must set or infer), n_components=3, std_clip=3, start_clip=100, max_n=None.
3. **Adaptive quantity.** Model / normaliser: running mean and covariance (and the clip bounds) used for the Mahalanobis distance in PCA space. Update rule: score() (called by predict and infer_threshold) updates mean and covariance with the clipped batch, count-weighted 1/(n+i+1), then sets self.mean, self.C, self.n and new clip bounds.
4. **Learning region.** All instances, clipped feature-wise to mean +/- 3 std after the first 100 observations; flagged instances are not excluded. Evidence (read in the code):
   - `alibi_detect/od/mahalanobis.py` lines 254-255:
     ```python
             if self.n > self.start_clip:
                 X_clip = np.clip(X, self.clip[0], self.clip[1])
     ```
   - `alibi_detect/od/mahalanobis.py` lines 305-309:
     ```python
             self.mean = new_means[-1]
             self.C = cov_batch
             stdev = np.sqrt(np.diag(cov_batch))
             self.n += n_batch
             if self.n > self.start_clip:
     ```
   - `alibi_detect/od/mahalanobis.py` lines 341-344:
     ```python
             iscore = self.score(X)
     
             # values above threshold are outliers
             outlier_pred = (iscore > self.threshold).astype(int)
     ```
5. **Learns from its own alarms.** yes.
6. **Memory.** Whole history with count-based weights (1/n) unless max_n is set (default None).
7. **Direction and bounds.** Per-sample influence bounded by clipping at mean +/- std_clip*std (3) after start_clip (100) observations; threshold fixed.
8. **Alarm logic.** Per instance > threshold.
9. **Operator controls.** std_clip, start_clip, max_n; no freeze switch (predict always updates).
10. **Documentation.** 'The algorithm is online, which means that it starts without knowledge about the distribution of the features and learns as requests arrive.' (mahalanobis.ipynb Overview). Silent on outliers entering the statistics; the std_clip parameter is described as clipping 'before updating the mean and cov'.
11. **Closest tt1 rule.** ewma. Differs: Count-based (1/n) mean and covariance with per-sample winsorising at 3 std, rather than an EWMA; nothing is excluded, and infer_threshold also feeds its batch into the statistics.
12. **Predictions (hypotheses, not results).** Sustained: absorb on short histories, resist on long ones: 1/n weights and 3-std clipping slow the shift; with max_n set the shift is bounded-time. Loud pulses: absorb, limited: each pulse enters clipped at 3 std but still inflates the covariance. Frog: absorb, slowly: just-under instances are not clipped and move mean/covariance with weight 1/n. Sub-event pulses: absorb, limited: no exclusion; clipping caps each sample.
13. **Runnable here.** In-process (pip install, CPU only); seconds to minutes for 1e5-1e6 samples; well under 1 GB RAM. BSL-1.1: non-production use only.

Notes: Other alibi-detect outlier detectors and online drift detectors are static (separate rows).

### alibi-detect outlier detectors with infer_threshold (IForest, AE, VAE, SR, new-style sklearn/pytorch backends)

Scope: out of scope / static control. Static control: threshold set once by infer_threshold (percentile of a user batch) and compared at predict; no update at predict.

1. **Identity.** alibi-detect outlier detectors with infer_threshold (IForest, AE, VAE, SR, new-style sklearn/pytorch backends); https://github.com/SeldonIO/alibi-detect @ `c2fd0e05c648`; 0.13.0.dev0 (alibi_detect/version.py); PyPI 0.13.0 (2025-12-11); Business Source License 1.1 (converts to Apache-2.0 four years after each release); 45,308 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).
2. **Default path.** Typical: od = IForest(); od.fit(X_train); od.infer_threshold(X, threshold_perc=95); od.predict(X_test).
3. **Adaptive quantity.** None at predict. Update rule: threshold = percentile(scores of the infer_threshold batch).
4. **Learning region.** The batch passed to infer_threshold only. Evidence (read in the code):
   - `alibi_detect/od/isolationforest.py` lines 97-98:
     ```python
             # update threshold
             self.threshold = np.percentile(iscore, threshold_perc)
     ```
   - `alibi_detect/od/isolationforest.py` lines 138-139:
     ```python
             # values above threshold are outliers
             outlier_pred = (iscore > self.threshold).astype(int)
     ```
   - `alibi_detect/od/sklearn/base.py` lines 172-173:
     ```python
             self.val_scores = self.score(x)
             self.threshold = np.quantile(self.val_scores, 1-fpr, interpolation='higher')  # type: ignore[call-overload]
     ```
5. **Learns from its own alarms.** no.
6. **Memory.** Fixed.
7. **Direction and bounds.** Fixed.
8. **Alarm logic.** Per instance.
9. **Operator controls.** infer_threshold call.
10. **Documentation.** Silent.
11. **Closest tt1 rule.** static. Differs: Static.
12. **Predictions (hypotheses, not results).** Sustained: resist. Loud pulses: resist. Frog: resist. Sub-event pulses: resist.
13. **Runnable here.** In-process (pip install, CPU only); seconds to minutes for 1e5-1e6 samples; well under 1 GB RAM. BSL-1.1.

Notes: Online drift detectors (cd/*_online.py) precompute thresholds from x_ref at init (base_online.py 101, 131-144); the test window slides over all incoming data but the reference and thresholds are fixed; they are drift tests, not alarm thresholds that learn.

Unresolved: Every od module was not opened; grep for 'self.threshold =' found assignments only in __init__ and infer_threshold (od/*.py, od/pytorch/base.py 226, od/sklearn/base.py 173).

## pyod

Repository https://github.com/yzhao062/pyod, commit `7e1330e10ac5c56ed402fbbaa41b225efb4bbc5c`, version 3.6.7 (pyod/version.py; PyPI 3.6.7, 2026-10-12). Licence: BSD-2-Clause. No restriction. Adoption: 2,714,709 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).

### PyOD BaseDetector contamination threshold (static control)

Scope: out of scope / static control. Static control: threshold_ set in fit from the training scores; predict compares and never refits.

1. **Identity.** PyOD BaseDetector contamination threshold (static control); https://github.com/yzhao062/pyod @ `7e1330e10ac5`; 3.6.7 (pyod/version.py; PyPI 3.6.7, 2026-10-12); BSD-2-Clause; 2,714,709 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).
2. **Default path.** clf = IForest() (contamination=0.1); clf.fit(X_train); clf.predict(X_test).
3. **Adaptive quantity.** None at predict. Update rule: threshold_ = percentile(decision_scores_, 100*(1-contamination)) in fit.
4. **Learning region.** Training batch (fit labels its own training data with the same threshold). Evidence (read in the code):
   - `pyod/models/base.py` lines 570-573:
     ```python
             if isinstance(self.contamination, (float, int)):
                 self.threshold_ = percentile(self.decision_scores_,
                                              100 * (1 - self.contamination))
                 self.labels_ = (self.decision_scores_ > self.threshold_).astype(
     ```
   - `pyod/models/base.py` lines 165-166:
     ```python
             if isinstance(self.contamination, (float, int)):
                 prediction = (pred_score > self.threshold_).astype('int').ravel()
     ```
5. **Learns from its own alarms.** no.
6. **Memory.** Fixed.
7. **Direction and bounds.** Fixed.
8. **Alarm logic.** Per sample.
9. **Operator controls.** contamination; PyThresh object instead of a float.
10. **Documentation.** Silent.
11. **Closest tt1 rule.** static. Differs: Static.
12. **Predictions (hypotheses, not results).** Sustained: resist. Loud pulses: resist. Frog: resist. Sub-event pulses: resist.
13. **Runnable here.** In-process (pip install, CPU only); seconds to minutes for 1e5-1e6 samples; well under 1 GB RAM.

Notes: Exception path: when contamination is a PyThresh object, predict calls self.contamination.predict(pred_score) (base.py 169-170); whether PyThresh thresholders refit on the test scores was not read (external package). MAD (pyod/models/mad.py 141-145) keeps the training median and median deviation at predict.

Unresolved: PyThresh predict behaviour.

## darts

Repository https://github.com/unit8co/darts, commit `ca413d65a7563ab5945df543714289e40be345e5`, version 0.48.1 (pyproject; PyPI 0.48.1, 2026-10-16). Licence: Apache-2.0. No restriction. Adoption: 154,525 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).

### Darts darts.ad detectors (QuantileDetector, IQRDetector, ThresholdDetector) [addition]

Scope: out of scope / static control. Addition (2026-11-11): widely installed Python time-series library with an anomaly-detection module; checked as a further static control. Bounds fitted in fit(), fixed in detect().

1. **Identity.** Darts darts.ad detectors (QuantileDetector, IQRDetector, ThresholdDetector) [addition]; https://github.com/unit8co/darts @ `ca413d65a756`; 0.48.1 (pyproject; PyPI 0.48.1, 2026-10-16); Apache-2.0; 154,525 PyPI downloads in the last month (pypistats.org last_month downloads, queried 2026-11-11).
2. **Default path.** QuantileDetector(high_quantile=...).fit(train_scores); detect(scores); or fit_detect on one series.
3. **Adaptive quantity.** None at detect. Update rule: fit computes nanquantile of the training series and builds a ThresholdDetector.
4. **Learning region.** Training batch. Evidence (read in the code):
   - `darts/ad/detectors/quantile_detector.py` lines 104-107:
     ```python
             high_threshold = [
                 np.nanquantile(np_series[:, i], q=hi, axis=0) if hi is not None else None
                 for i, hi in enumerate(self.high_quantile)
             ]
     ```
   - `darts/ad/detectors/quantile_detector.py` lines 109:
     ```python
             self.detector = ThresholdDetector(
     ```
   - `darts/ad/detectors/detectors.py` lines 159-160:
     ```python
             self.fit(series)
             return self.detect(series, name="series")
     ```
5. **Learns from its own alarms.** no.
6. **Memory.** Fixed.
7. **Direction and bounds.** Fixed.
8. **Alarm logic.** Per point.
9. **Operator controls.** fit/detect split.
10. **Documentation.** Silent.
11. **Closest tt1 rule.** static. Differs: Static.
12. **Predictions (hypotheses, not results).** Sustained: resist. Loud pulses: resist. Frog: resist. Sub-event pulses: resist.
13. **Runnable here.** In-process (pip install, CPU only); seconds to minutes for 1e5-1e6 samples; well under 1 GB RAM.

Notes: ForecastingAnomalyModel scores with historical_forecasts(retrain=False) (darts/ad/anomaly_model/forecasting_am.py 301-307). Sparse clone of darts/ad only.

Unresolved: Scorers (darts/ad/scorers) fit at fit time; not every scorer read.

## Additions

- 2026-11-11, **Darts** (`unit8co/darts`, `darts/ad`, sparse clone at `ca413d65a756`, 0.48.1, Apache-2.0, 154,525 PyPI downloads last month). Reason: widely installed Python time-series library with an anomaly-detection module in the same category; checked whether any detector adapts at detect time. Result: static after `fit` (one more static control).
- No other additions. Candidates considered and not read: PyThresh (batch thresholders for PyOD; would resolve PyOD's one open exception), Kats (batch detectors), scikit-multiflow (superseded by river), CapyMOA (scorers only).
- Components added inside listed libraries because they turned out to adapt: river `PredictiveAnomalyDetection` (own dynamic threshold), PySAD `NonparametricDynamicThresholdPostprocessor`, `AnomalyLikelihoodProbabilityCalibrator` and `PEWMA`, StreamAD `ZScoreCalibrator` and `TDigestCalibrator`, Merlion `RandomCutForest(online_updates=True)` inside `DefaultDetector`, alibi-detect `Mahalanobis` (online).

## Could not establish

- **river:** the P2 quantile is implemented in Rust (`_rust_stats.RsQuantile`) and was not read; the claim that one score's influence shrinks about as 1/n comes from the algorithm. Whether `protect_anomaly_detector=False` freezing the wrapped detector in `ThresholdFilter` (base class line 155) is intended was not checked against the issue tracker.
- **PySAD:** HEAD (2026-11-11) is three days newer than the 0.8.0 wheel (2026-11-08). The code read may differ from the release. `QuantileMeter` internals not read.
- **StreamAD:** effect of the two-sided tail and of the `deviance_ratio` early return on real streams not worked out; `tdigest` package internals not read.
- **Merlion:** HEAD is a bulk re-upload (setup.py 2.0.2) while PyPI ships 2.0.4; the diff was not checked. The default time decay of the bundled Java RCF 1.0 sampler was not read, so the memory of the online RRCF is unknown. Whether users call `get_anomaly_label` repeatedly on streaming chunks (which makes RRCF and, with `time_series_prev`, AutoETS absorb) or once per test split (README) was not established.
- **Orion:** whether users run `detect` on streaming chunks or whole signals was not established. The behaviour of the MLPrimitives copy of `_find_threshold` (missing `best_cost = cost`) was read by diff only.
- **ADTK:** whether 0.6.2 still imports on current pandas (not installed).
- **Luminol:** bitmap scoring was traced only to window sizes and normalisation, not line by line.
- **alibi-detect:** not every `od` module was opened; the search for `self.threshold =` found assignments only in constructors and `infer_threshold`. Which pre-BSL versions were Apache-2.0 was not checked.
- **PyOD:** when `contamination` is a PyThresh object, `predict` delegates to `contamination.predict(pred_score)`; whether PyThresh refits on test scores was not read.
- **All rows:** item 12 predictions are hypotheses only. No detector was run.

