# tw1 catalogue, group C (reference code of widely re-used methods)

Read 2026-11-11. Sources cloned under `C:\Users\marcu\Videos\tw1-sources\` (depth 1, read only; nothing built, installed, imported or run). Line numbers are at the commits below. "Read" means seen in the code at the cited lines; "inferred" means a consequence I worked out from that code without running it.

| Clone | Repo | Commit | Date / version |
|---|---|---|---|
| `NAB` | github.com/numenta/NAB | ea702d75cc2258d9d7dd35ca8e5e2539d71f3140 | 2024-12-03 (no tag) |
| `nupic` | github.com/numenta/nupic (now redirects to numenta/nupic-legacy) | 7281482def2a96fbda663e6c39e8351a1886dec7 | 2024-12-03, VERSION 1.0.6.dev0; tag 1.0.5 (what NAB pins) also fetched |
| `htm.core` | github.com/htm-community/htm.core | 0cab77fa638925e0c84a1b2aa6c7cc1258cb66f1 | 2026-10-22, VERSION 2.2.0 (sparse: src/htm/algorithms, src/htm/utils, py/htm, bindings/py/cpp_src) |
| `telemanom` | github.com/khundman/telemanom | 2e6c5b6c3558e7835601519b7bdef37c649bdbdc | 2025-01-17 (no tag) |
| `SPOT` | github.com/Amossys-team/SPOT, **deleted from GitHub**; recovered from Software Heritage | revision a7a499c4ec151c1a314b440cfd64526553a275a5 (snapshot 360fcff0c686eb5cabe45cb862770490de06ecd1, last archive visit 2021-01-23) | 2017-08-16 commit "typos"; `spot.py` git blob 4f8453989689e65f0dba56ea7272849027ecf4ba (hash re-checked locally) |
| `libspot` | github.com/asiffer/libspot | d57e921a08930b960d07adcbec3a839bd228fe94 | tag v3.1.0, 2026-09-06; PyPI `libspot` 3.1.0 |
| `libspot-v1` | same repo, tag v1.3.1-171 | babb6a4ec9dfbd04e2e71c46356d57533cae777f | 2022-06-09 (the C++ library behind the archived Python binding; has DSpot) |
| `python3-libspot` | github.com/asiffer/python3-libspot (archived) | 8373057a9a5cbbc1760bf98cd9e9ea92dadb6727 | 2024-02-22 |
| `egads` | github.com/yahoo/egads | 40d3db6e27fea649b2aa23c26d0f14991e6adaae | 2023-10-04 (no tag) |
| `Kitsune-py` | github.com/ymirsky/Kitsune-py | 7c8ea51e89268d9a20399dca4bf32d663e638eb4 | 2026-03-24 (no tag) |

Adoption figures are GitHub stars/forks read through the GitHub API on 2026-11-11, plus PyPI where noted.

---

## C1. Numenta anomaly likelihood as used by NAB's `numenta` detector (NuPIC 1.0.5)

1. **Identity.** NAB `nab/detectors/numenta/numenta_detector.py` plus NuPIC `src/nupic/algorithms/anomaly_likelihood.py`. NAB MIT; NuPIC 1.0.5 (the pinned version, `nab/detectors/numenta/requirements.txt`: `nupic==1.0.5`) carries an AGPL-3.0 header; NuPIC HEAD re-licensed the same file MIT. The tag-to-HEAD diff of `anomaly_likelihood.py` changes only the licence header (HEAD lines = 1.0.5 lines minus 12). Line numbers below are at NuPIC HEAD 7281482. Adoption: NAB 2,116 stars / 869 forks; nupic-legacy 6,349 stars (2026-11-11). Reference code.
2. **Default path.** `NumentaDetector.initialize` builds an OPF HTM model and `AnomalyLikelihood(learningPeriod=floor(P/2), estimationSamples=P-floor(P/2), reestimationPeriod=100)` with default `historicWindowSize=8640` (numenta_detector.py 120-127; anomaly_likelihood.py 138-143). P = probationary period = min(floor(0.15·len), 0.15·5000 = 750) (NAB `nab/util.py` 25-29). Per record: raw HTM anomaly score -> `anomalyProbability` -> `computeLogLikelihood` -> final score (numenta_detector.py 87-94). The alarm is final score >= a fixed per-profile threshold optimised offline over the corpus: `"standard": {"threshold": 0.5421876907348634}` (config/thresholds.json 123-126), applied by `alerts = anomalyScores[anomalyScores >= threshold].index` (nab/util.py 134).
3. **Adaptive quantities.** (a) A Gaussian (mean, variance) of the 10-point moving average of raw scores, re-estimated every 100 records from the last 8640 records; (b) the HTM model itself, which learns online (OPF `Model.__init__`: `self.__learningEnabled = True`, nupic `src/nupic/frameworks/opf/model.py` 52); (c) the running min/max used for the "spatial anomaly" override (numenta_detector.py 82-85). The 0.5422 threshold is static.
4. **Learning region.** All records. Every data point is appended to the history before returning, with no condition on its likelihood:
   `anomaly_likelihood.py` 385-387:
   ```
   # Before we exit update historical scores and iteration
   self._historicalScores.append(dataPoint)
   self._iteration += 1
   ```
   Re-estimation uses the whole deque, skipping only the learning period (367-377): `_, _, self._distribution = estimateAnomalyLikelihoods(self._historicalScores, skipRecords=numSkipRecords)`, which fits `estimateNormal(dataValues[skipRecords:])` (459). Spatial range (numenta_detector.py 82-85): `if self.maxVal is None or value > self.maxVal: self.maxVal = value`.
5. **Learns from its own alarms.** Yes (read). Flagged records enter `_historicalScores` (386) and therefore the next re-estimated mean and variance; the HTM model learns every record; a value that triggers the spatial override immediately widens min/max.
6. **Memory.** Box window of 8640 records (`collections.deque(maxlen=historicWindowSize)`, 179); re-estimation every 100 records (368); 10-record moving average of raw scores (`averagingWindow=10`, 394; `MovingAverage.compute`, 566-568). Output fixed at 0.5 for the first learningPeriod+estimationSamples records (362-364).
7. **Direction and bounds.** Symmetric re-estimation. Floors: mean >= 0.03, variance >= 0.0003 (`estimateNormal`, 695-700). Flat-metric guard: metric variance < 1.5e-5 gives a null distribution (473-474). No ceiling.
8. **Alarm logic.** `_filterLikelihoods` (602-632): when a tail probability is <= 1e-5 ("red") and the previous raw value was also red, it is replaced by 1e-3 ("yellow"):
   ```
   if v <= redThreshold:
     # Value is in the redzone
     if likelihoods[i] > redThreshold:
       # Previous value is not in redzone, so leave as-is
       filteredLikelihoods.append(v)
     else:
       filteredLikelihoods.append(yellowThreshold)
   ```
   Inferred arithmetic: a yellow value maps to log score log(1e-3)/log(1e-10) = 0.30 < 0.5422, so a run of consecutive red records alarms on its first record only. The spatial override sets the final score to 1.0 for a value more than 5% of the seen range outside min/max (numenta_detector.py 27, 76-81, 96-97).
9. **Operator controls.** `useLikelihood` flag (numenta_detector.py 51); no exclusion window, freeze switch or feedback labels in the likelihood; OPF has `disableLearning()` (model.py 165-168) but NAB never calls it.
10. **Documentation.** Docstring of `learningPeriod` (151-156): "The downside if this is too large is that real anomalies might get ignored and not flagged." Nothing on anomalies entering the rolling distribution: silent.
11. **Closest tt1 rule.** ewma (mean + deviation band learned from all scores), with a 8640-record box window refit every 100 records instead of exponential weights, a fixed threshold on a Gaussian tail probability of a 10-point average, and onset-only alarming from the red-zone filter. Not daily_excl or ewma_excl: nothing is left out.
12. **Predictions (hypotheses, not results).** Sustained: absorb (the filter silences the run after its first record by construction; the attack then enters the 8640 window and the HTM model). Loud pulses: absorb (each pulse onset alarms once, but pulses inflate the variance of the window, and HTM's time-of-day encoder may learn a 2 h period). Frog: absorb (scores held under the threshold enter the mean/variance with nothing left out). Sub-event pulses: absorb (no exclusion logic to bypass; bursts shorter than 10 records are also diluted by the 10-point average).
13. **Runnable here.** Docker: NAB documents `docker pull numenta/nab:py2.7` (Python 2.7, nupic 1.0.5). HTM on one NAB-length series is CPU-only, well under 2 GB RAM; corpus runs take hours. The likelihood class alone is pure Python and could be lifted, but NAB's default includes the HTM model.

## C2. htm.core (maintained port): Python `AnomalyLikelihood`

1. **Identity.** `py/htm/algorithms/anomaly_likelihood.py` (106 lines, "2021, David McDougall" in header); AGPL-3.0 (README 351). Adoption: 175 stars / 83 forks. Library (PyPI `htm.core`), catalogued with the reference code as asked.
2. **Default path.** The shipped example `py/htm/examples/hotgym.py`: `'anomaly': {'period': 1000}` (44), `anomaly_history = AnomalyLikelihood(parameters["anomaly"]["period"])` (110), `tm.compute(activeColumns, learn=True)` (145), `anomalyProb.append( anomaly_history.compute(tm.anomaly) )` (157). The class docstring's alarm example: `if anomaly_probability > 0.25: print("Anomaly Detected!")` (35-36). The example itself sets no threshold. This is a different algorithm from the NuPIC/NAB one: no window, no 100-step re-estimation, no red/yellow filter.
3. **Adaptive quantity.** EWMA mean and variance of raw TM anomaly scores, alpha = 1 - exp(-1/period) (44); the TM learns online in the example (145).
4. **Learning region.** Every score, updated after its own likelihood is computed (58-59: `likelihood = self.get_likelihood(anomaly)` then `self.add_record(anomaly)`). Update (71-74):
   ```
   diff      = anomaly - self.mean
   incr      = self.alpha * diff
   self.mean = self.mean + incr
   self.var  = (1.0 - self.alpha) * (self.var + diff * incr)
   ```
5. **Learns from its own alarms.** Yes (read, 58-59 and 71-74: no condition on the likelihood).
6. **Memory.** Exponential, time constant 1000 samples by default (`period = 1000`, 38 and 44). Returns 0.0 until `n_records >= period` (62-63).
7. **Direction and bounds.** Symmetric. Floors `self.mean = max(self.mean, 0.03)`, `self.var = max(self.var, 0.0003)` (79, 81). No ceiling.
8. **Alarm logic.** `combined = 1 - (1 - likelihood) * (1 - self.prev)` (60) combines the current and previous point; log scale (97-106). Threshold left to the user. No on-delay or suppression.
9. **Operator controls.** None in the class. TM `learn=False` is available to the caller.
10. **Documentation.** Docstring (54-56): "Calculates the log-likelihood of the probability that the given anomaly score is greater than a historical distribution of anomaly scores. Then updates the historical distribution to include the given anomaly score." Nothing about anomalies specifically.
11. **Closest tt1 rule.** ewma (no exclusion), exactly: EWMA mean and variance of all scores, with floors.
12. **Predictions.** Sustained: absorb (mean moves toward the attack level with time constant 1000 samples; TM learns the new pattern). Loud: absorb (each pulse raises the variance). Frog: absorb. Sub-event: absorb (no exclusion to bypass).
13. **Runnable here.** In-process. The class is 106 lines of pure Python with only `math`; the full example needs the `htm.core` wheel (C++ extension). Laptop-scale.

**Variant, opt-in: C++ `htm::AnomalyLikelihood` through `TemporalMemory(anomalyMode=ANMode::LIKELIHOOD)`.** Default `anomalyMode = ANMode::RAW` (TemporalMemory.hpp 132-133, 152), so not on the default path. Read: every score is appended before any likelihood is computed (AnomalyLikelihood.cpp 51-53: `this->runningRawAnomalyScores_.append(anomalyScore);` ... `this->runningAverageAnomalies_.append(newAvg);`), the distribution is re-fit over the whole window (65-67), and the returned value is `likelihood = 1.0f - likelihoods[0];` (74) where `likelihoods` is built by iterating `runningAverageAnomalies_[i]` from i = 0, and `operator[]` indexes from the oldest element (SlidingWindow.hpp 130-147). Inferred: the C++ path returns the likelihood of the oldest averaged score in its window, not of the current one, and line 68 resets `initialTimestamp_` after each re-estimation, which sends the next call back into the probationary branch (57-59). The code warns `"C++ AnomalyLikelihood may still need some testing."` (30). Learns from own alarms: yes (51-53), but what it alarms on is unclear without running it.

## C3. Telemanom (nonparametric dynamic threshold)

1. **Identity.** `telemanom/errors.py`; Caltech BSD-style licence with a no-endorsement clause (LICENSE.txt), no restriction on running or publishing found. Adoption: 1,205 stars / 271 forks. Reference code (KDD 2018).
2. **Default path.** `example.py` -> `Detector.run` -> for each channel `Errors(channel, config, id)` then `errors.process_batches(channel)` (detector.py 209-210). `config.yaml`: `train: False` (3), `batch_size: 70` (8), `window_size: 30` (11), `smoothing_perc: 0.05` (19), `error_buffer: 100` (22), `l_s: 250` (44), `p: 0.13` (53). The LSTM is trained on the training split only (modeling.py 97-98 `self.model.fit(channel.X_train, channel.y_train, ...)`) and is not retrained on test data; by default saved models and predictions are reused.
3. **Adaptive quantity.** The threshold epsilon per window = mean + z·sd of smoothed errors e_s over the trailing 2100 points (30 batches × 70), with z chosen from 2.5..11.5 to maximise the drop in mean and sd when points above epsilon are removed, penalised by the number of flagged points and sequences.
4. **Learning region.** All smoothed errors in the trailing window, flagged or not (errors.py 245-248):
   ```
   self.e_s = errors.e_s[start_idx:end_idx]

   self.mean_e_s = np.mean(self.e_s)
   self.sd_e_s = np.std(self.e_s)
   ```
   with `start_idx = i*batch_size`, `end_idx = window_size*batch_size + i*batch_size` (123-128). The window includes the current batch of 70 that is about to be judged. The only place flagged indices are left out is the pruning reference `non_anom_max` (363-371: `window_indices = np.setdiff1d(window_indices, np.append(errors_all.i_anom, adj_i_anom))`), which affects pruning, not epsilon.
5. **Learns from its own alarms.** Yes (read, 245-248 and 285-286: `epsilon = self.mean_e_s + (self.sd_e_s * z)`; nothing filters `self.e_s`). Partial mitigation: the z search scores each candidate by how much mean and sd drop when points above it are removed (306-311), so a few outliers do not set the threshold, but mean_e_s and sd_e_s themselves include them.
6. **Memory.** Box window of 2100 smoothed errors, step 70. e_s is an EWMA of absolute prediction error with span int(70·30·0.05) = 105 (51-59).
7. **Direction and bounds.** Symmetric. z in {2.5, ..., 11.5}; fallback epsilon = mean + 12·sd when no candidate passes the guardrails (241-243, 252). Guardrails (314-315): `len(E_seq) <= 5 and len(i_anom) < (len(e_s) * 0.5)`; inferred: once more than half the window (after ±99-point buffering) would be flagged, every z fails and the 12-sd fallback applies.
8. **Alarm logic.** `i_anom = np.argwhere((e_s >= epsilon) & (e_s > 0.05 * self.inter_range))` (342-343), skipped entirely when errors are small relative to the channel's spread (338-340). Each exceedance is widened by ±100 points (347-353), then restricted to the last batch (358-359) or past the first 2·l_s = 500 points in window 0 (356-357). Pruning (403-418): sequences whose maximum is within p = 13% of the next lower maximum (down to non_anom_max) are removed. Drops are detected on errors mirrored about the mean (249-250). Final output drops single-index sequences (159-160: `if not g[0] == g[-1]`).
9. **Operator controls.** config.yaml parameters only; labels are used for scoring, not feedback.
10. **Documentation.** README: "Telemanom then uses a novel nonparametric, unsupervised approach for thresholding these errors and identifying anomalous sequences of errors." Silent on anomalies entering the window.
11. **Closest tt1 rule.** daily (threshold recomputed on a trailing window of all scores), here every 70 points over 2100 points with a mean + z·sd form; tt1c's `ndt` is the direct re-implementation (differences below).
12. **Predictions.** Sustained: absorb (as the attack fills the 2100-point window it raises mean and sd; past half the window the guardrail forces the 12-sd fallback). Loud pulses: absorb (each pulse inflates sd of the next 30 windows; the z search may still isolate the pulses themselves, so smaller events nearby are the ones lost). Frog: absorb (sub-threshold errors enter mean and sd unfiltered). Sub-event: absorb (nothing is excluded, and the span-105 EWMA also flattens short bursts).
13. **Runnable here.** In-process for the threshold: errors.py needs numpy, pandas, more_itertools and can take any score series in place of LSTM errors. Full pipeline needs TensorFlow/Keras (Dockerfile provided); predictions for SMAP/MSL ship with the data download. Laptop-scale.

## C4. SPOT and biSPOT, authors' Python (`spot.py`)

1. **Identity.** `spot.py` from the deleted repo Amossys-team/SPOT, recovered byte-exact from Software Heritage (provenance in `SPOT/_PROVENANCE.txt`). GPL-3.0. Adoption: the original repo is gone; GitHub code search finds copies of the file in other projects (e.g. dawnvince/EasyTSAD, kplabs-pl/ESA-ADB, limjcst/ads-evt), which is how most users now get it. Reference code (KDD 2017).
2. **Default path.** README examples: `s = SPOT(q); s.fit(init_data, data); s.initialize(); results = s.run()`. Defaults: `q = 1e-4` (58), `initialize(level = 0.98)` (171), `run(with_alarm = True)` (395). biSPOT fixes level 0.98 / 0.02 (677-678).
3. **Adaptive quantity.** z_q, the GPD extreme quantile above a fixed excess threshold t; refit by Grimshaw maximum likelihood on every new peak.
4. **Learning region.** Values between t and z_q. Alarms are not added (427-450):
   ```
   if self.data[i]>self.extreme_quantile:
       # if we want to alarm, we put it in the alarm list
       if with_alarm:
           alarm.append(i)
   ```
   The peak update applies only on the `elif` branch (442-450): `elif self.data[i]>self.init_threshold:` ... `self.peaks = np.append(self.peaks,self.data[i]-self.init_threshold)`. Alarms also do not increment n (n += 1 appears only in the peak and normal branches, 435, 446, 452).
5. **Learns from its own alarms.** Configurable, default no (read, 427-439: with `with_alarm=False` the value above z_q is appended to the peaks and z_q is refit). t is fixed after calibration (187: "t is fixed for the whole algorithm").
6. **Memory.** Unbounded: every peak since calibration stays in `self.peaks` (np.append, no cap); n counts all non-alarm values since calibration. The effective learning rate of z_q decays as the peak set grows.
7. **Direction and bounds.** Symmetric in principle (a new peak can move z_q either way); no floor, ceiling or clamp on z_q. Grimshaw candidates include gamma = 0 with sigma = mean (353-356).
8. **Alarm logic.** Per sample, strict `>` (427). No on-delay or hold-off.
9. **Operator controls.** `with_alarm` flag only.
10. **Documentation.** `run` docstring (401-403): "(default = True) If False, SPOT will adapt the threshold assuming there is no abnormal values". README silent.
11. **Closest tt1 rule.** SPOT (same exclusion of alarms; differences listed below).
12. **Predictions.** Sustained: resist (values above z_q never enter; t and z_q frozen while the attack stays above z_q). Loud pulses: resist (pulse tops excluded; only edges that fall between t and z_q are learned). Frog: absorb (every held-under value above t is a peak that thickens the tail; no cap). Sub-event: resist (exclusion is per sample, so no duration logic to slip under).
13. **Runnable here.** In-process: pure Python (numpy, scipy, pandas, tqdm, matplotlib). Each peak triggers a Grimshaw refit over all peaks (O(peaks) per peak), so long streams with many peaks are slow but fit in memory.

## C5. DSPOT and biDSPOT, authors' Python (`spot.py`)

1. **Identity.** As C4. `dSPOT` (class at 1063), `bidSPOT` (1554).
2. **Default path.** README: `s = dSPOT(q, d); s.fit(init_data, data); s.initialize(); results = s.run()` with examples d = 450 and d = 10; no default depth (`__init__(self, q, depth)`, 1096).
3. **Adaptive quantities.** z_q (as SPOT) on residuals x - M_i, and the local mean M_i = mean of the window W of the last d values.
4. **Learning region.** Peaks and W both skip alarms (1455-1485):
   ```
   Mi = W.mean()
   # If the observed value exceeds the current threshold (alarm case)
   if (self.data[i]-Mi)>self.extreme_quantile:
       # if we want to alarm, we put it in the alarm list
       if with_alarm:
           alarm.append(i)
   ```
   W is updated only in the non-alarm branches: `W = np.append(W[1:],self.data[i])` (1482, 1485). Calibration residuals use the mean of the previous d values (`backMean`, 1052-1059; 1210-1211).
5. **Learns from its own alarms.** Configurable, default no (read, 1457-1470; with `with_alarm=False` the alarm value goes into both peaks and W). bidSPOT behaves the same on both sides (1979-2030).
6. **Memory.** W: last d non-alarm values (box). Peaks: unbounded.
7. **Direction and bounds.** No clamp on z_q or on M_i. M_i follows any slow drift that stays below M_i + z_q.
8. **Alarm logic.** Per sample on the residual; the recorded threshold is `self.extreme_quantile+Mi` (1488).
9. **Operator controls.** `with_alarm`, `depth`.
10. **Documentation.** Same docstring as SPOT (copied, it says "biSPOT"); README silent on alarms and the window.
11. **Closest tt1 rule.** SPOT (tt1's dspot / dspot_gr).
12. **Predictions.** Sustained step above z_q: resist (W frozen, alarm persists). Sustained ramp slower than z_q per d samples: absorb (inferred: each non-alarm value enters W, so M_i walks up with it). Loud pulses: resist. Frog: absorb (both M_i and the tail learn the held-under values). Sub-event: resist.
13. **Runnable here.** In-process, as C4.

## C6. libspot v3.1.0 (C library, Python binding in the same repo, PyPI `libspot`)

1. **Identity.** `src/spot.c`, `src/tail.c`, `src/ubend.c`, `python/libspotmodule.c`. LGPL-3.0-or-later. Adoption: 30 stars / 5 forks; PyPI `libspot` 3.1.0, 264 downloads in the last month (pypistats, 2026-11-11). Library by the SPOT author; listed here as the maintained reference implementation.
2. **Default path.** Python `Spot(q, *, low=0, discard_anomalies=1, level=0.98, max_excess=500)` (libspotmodule.c 10-13, 108-120); `spot.fit(data)`; `status = spot.step(x)`; alarm when `status == ANOMALY` (docs/guides/drifting.md). Only SPOT; v3 has no DSPOT (docs/guides/drifting.md suggests differencing or a moving average outside the library).
3. **Adaptive quantity.** `anomaly_threshold` = excess_threshold + GPD quantile; GPD refit (method of moments and Grimshaw, the higher likelihood wins: tail.c 14, 47-65) on every excess.
4. **Learning region.** Non-alarm values above the excess threshold (spot.c 123-139):
   ```
   if ((spot->discard_anomalies) &&
       (spot->__up_down * (x - spot->anomaly_threshold) > 0)) {
       return ANOMALY;
   }
   ```
   then `spot->n++;` and, if `ex >= 0.0`, `tail_push(&(spot->tail), ex); tail_fit(&(spot->tail)); spot->anomaly_threshold = spot_quantile(spot, spot->q);`.
5. **Learns from its own alarms.** No at the default (read, 123-126; `SPOT_INIT_DISCARD_ANOMALIES 1`, libspotmodule.c 11). Inferred from 123-142: with `discard_anomalies=0` the function never returns ANOMALY, so there are no alarms to learn from in that mode either; the flag switches between "flag and exclude" and "do not flag".
6. **Memory.** Peaks kept in a ring buffer of `max_excess` = 500 (Python default; ubend.c 28-48 overwrites the oldest). Nt and n are never decremented, so the exceedance rate s = Nt/n (spot.c 146) covers all history while the GPD shape covers only the last 500 excesses. Docs (parameters.md 47): "the model will keep only the last `max_excess` tail data to perform the fit."
7. **Direction and bounds.** Symmetric; no clamp. Excess threshold fixed after `fit` (P² quantile estimate, spot.c 83-93).
8. **Alarm logic.** Per sample; no on-delay.
9. **Operator controls.** `discard_anomalies`, `max_excess`, `level`, `q`, `low`; `spot_reset`.
10. **Documentation.** docs/api.md 263: "`discard_anomalies` | Do not include anomalies in the model (default: 1, 0 otherwise)". docs/get_started.md 53: "`discard_anomalies` says that we want to reject anomalies."
11. **Closest tt1 rule.** SPOT, with a 500-peak FIFO cap that tt1's SPOT does not have.
12. **Predictions.** Sustained: resist. Loud: resist. Frog: absorb, and faster than the authors' Python once 500 frog peaks have replaced the calibration peaks (inferred from the FIFO). Sub-event: resist.
13. **Runnable here.** In-process (`pip install libspot`, C extension, abi3 wheels). Negligible resources.

**Variant: archived `python3-libspot` (pyspot.py) over libspot v1.3.1 C++.** Defaults `Spot(q=1e-4, n_init=2000, level=0.99, up=True, down=True, alert=True, bounded=True, max_excess=200)` (pyspot.py 313-314) and `DSpot(d=10, ..., alert=True, bounded=True, max_excess=200)` (488-498). Spot::step (libspot-v1 src/spot.cpp 347-352): `if (this->alert && v > this->z_up) { this->n--; this->al_up++; return (SPOTEVENT::ALERT_UP); }`, i.e. alerts are not learned and not counted; with `alert=false` the value falls to the excess branch and is learned. DSpot::step (src/dspot.cpp 195-201): the drift window is updated only `if ((res != SPOTEVENT::ALERT_UP) && (res != SPOTEVENT::ALERT_DOWN))`. Learns from own alarms: configurable, default no. Peak cap 200 FIFO (ubend.cpp 98-103). Runnable: needs the v1 shared library built (Debian packaging in the repo); Docker/WSL.

## C7. Yahoo EGADS

1. **Identity.** Java; GPL-3.0 (LICENSE). Adoption: 1,191 stars / 324 forks; last push 2023-11-14. Library, catalogued as reference code.
2. **Default path.** README and `src/test/resources/sample_config.ini`: `OP_TYPE DETECT_ANOMALY`, `TS_MODEL OlympicModel`, `AD_MODEL ExtremeLowDensityModel`, THRESHOLD commented out ("Comment out to auto-detect all thresholds"). `DetectAnomalyProcessable.process` (control/DetectAnomalyProcessable.java 36-57): `ma.reset(); ma.train();` ("Training the model with the whole metric", 41-42), forecast, then per forecast `ad.reset(); ad.tune(ds); anomalyList = ad.detect(ad.metric, ds);`. It is a batch tool: each invocation reads a whole series, tunes on it and scores the same series. No online update; `UpdateModelProcessable` only retrains (27-28) and `OlympicModel.update` is empty (146-148).
3. **Adaptive quantity.** Per-error-metric thresholds auto-tuned on the errors of the very series being scored (ExtremeLowDensity: low-density cluster; KSigma: mean + 3 sd; SimpleThreshold: adaptive k-sigma or max/min; DBScan: eps and minPoints from the same data). The Olympic baseline is the mean of the values 1..NUM_WEEKS periods back (OlympicModel.java 162-199), recomputed in each run from the input series.
4. **Learning region.** The whole input series, including the points that end up flagged. ExtremeLowDensityModel.tune (75-87):
   ```
   HashMap<String, ArrayList<Float>> allErrors = aes.initAnomalyErrors(observedSeries, expectedSeries);
   ...
   threshold.put(aes.getIndexToError().get(i), AutoSensitivity.getLowDensitySensitivity(fArray, sDAutoSensitivity, amntAutoSensitivity));
   ```
   KSigmaModel.tune (76-84) the same with `AutoSensitivity.getKSigmaSensitivity(fArray, sDAutoSensitivity)` = `mean + (sd * sDAutoSensitivity)` (AutoSensitivity.java 74-78).
5. **Learns from its own alarms.** Yes, in-sample batch (read, ExtremeLowDensityModel.java 78-85; KSigmaModel.java 76-84): the samples a run flags are part of the data its thresholds are tuned on. Inferred for ExtremeLowDensity: the threshold is defined as the smallest member of the top error cluster (`toReturn = fData.get(fData.size() - 1);`, AutoSensitivity.java 65), so flagged samples set it by construction. Not online: nothing carries over between runs except what the caller feeds back as input.
6. **Memory.** Whatever series the caller passes; Olympic uses NUM_WEEKS (3 in the sample config) periods of BASE_WINDOWS (168) points, with NUM_TO_DROP 0 (no trimming).
7. **Direction and bounds.** ExtremeLowDensity: if the top cluster is larger than `amntAutoSensitivity` of the rest, the threshold is +infinity (AutoSensitivity.java 59-62: `// Cannot do anomaly detection.` ... `return toReturn;` with `toReturn = Float.POSITIVE_INFINITY`, 25). Code default `amntAutoSensitivity = 0.05`, `sDAutoSensitivity = 3` (AnomalyDetectionAbstractModel.java 24-25); README sample sets `AUTO_SENSITIVITY_ANOMALY_PCNT 0.01`, `AUTO_SENSITIVITY_SD 3.0`.
8. **Alarm logic.** `Math.abs(errors[...]) >= Math.abs(entry.getValue())` on any error metric (ExtremeLowDensityModel.java 96-98), only within the detection window (`MAX_ANOMALY_TIME_AGO`, 129-130).
9. **Operator controls.** `THRESHOLD` (fixed per-metric thresholds replace auto-tuning: `if (!threshold.containsKey(...))`, 83), `AUTO_SENSITIVITY_*`, detection window.
10. **Documentation.** README: "EGADS automatically determines thresholds on *E* and outputs the most probable anomalies." Sample config: "Denotes the expected % of anomalies in your data." Code comment AutoSensitivity.java 23: "Assumes that anomalies constitute at most 5% of the data."
11. **Closest tt1 rule.** daily with the window equal to the whole input series and no exclusion; ExtremeLowDensity adds a "too many anomalies -> no threshold" clamp that tt1 has no analogue for.
12. **Predictions.** Sustained: absorb (an attack longer than 1-5% of the series makes the top cluster too large and the threshold +inf; for KSigma it inflates mean and sd). Loud pulses: absorb (pulses form the top cluster; enough of them push it past the percentage). Frog: unclear (batch, not closed-loop; within one run held-under values raise KSigma's mean/sd, but there is no state across runs). Sub-event: absorb (no duration logic).
13. **Runnable here.** In-process JVM (Java + Maven build of the jar); small memory. The `AdaptiveKernelDensityChangePointDetector` variant (below) needs PRE_WINDOW_SIZE/POST_WINDOW_SIZE set.

**Variant: AdaptiveKernelDensityChangePointDetector.** Opt-in. `tune` is empty (134-137); in `computeKLScore` every residual enters the sliding pre/post windows (24 and 48 by default fields, 67-69; `buffer.addLast(residual); buffer.removeFirst();`, 308-309). Learns from own alarms: yes (all residuals pass through the windows; it is a change-point detector, so a level shift is reported once and then becomes the new pre-window by design).

## C8. Kitsune / KitNET (Python reference)

1. **Identity.** `KitNET/KitNET.py`, `KitNET/dA.py`; MIT. Adoption: 400 stars / 120 forks. Reference code (NDSS 2018).
2. **Default path.** `example.py`: `Kitsune(path, packet_limit, maxAE=10, FMgrace=5000, ADgrace=50000)`; `K.proc_next_packet()` returns an RMSE per packet (Kitsune.py 34-41). No alarm decision in the library.
3. **Adaptive quantity.** None after the grace periods. `process` (KitNET.py 51-56): train while `n_trained <= FM_grace_period + AD_grace_period`, then `return self.execute(x)`. `execute` (83-95) and `dA.execute` (dA.py 114-122) do not update weights or the 0-1 normalisation min/max (those update only in `dA.train`, 83-84). The feature extractor keeps damped per-stream statistics with decay factors [5, 3, 1, 0.1, 0.01] over every packet (netStat.py 41-42); that is feature computation, not an alarm baseline.
4. **Learning region.** Grace period only (first FMgrace + ADgrace packets).
5. **Learns from its own alarms.** not_adaptive (read, KitNET.py 52-53: `if self.n_trained > self.FM_grace_period + self.AD_grace_period: return self.execute(x)`).
6. **Memory.** Frozen model after 55,000 packets in the example.
7. **Direction and bounds.** n/a.
8. **Alarm logic.** Left to the user. The example fits a log-normal to `RMSEs[FMgrace+ADgrace+1:100000]` (example.py 56-57) for colouring a plot; that fit uses execute-phase scores up to packet 100,000 while the comment says "The first 70,000 observations are clean..." (17), so the example's fit window extends past the stated clean part (read; whether those packets are attack traffic rests on the comment).
9. **Operator controls.** Grace-period lengths; `train(x)` can be called to force training.
10. **Documentation.** README: "trained to mimic (reconstruct) network traffic patterns, and whose performance incrementally improves overtime", while the code stops training after the grace period. README 65: "Kitsune returns the RMSE value of the packet (zero during the FM featuremapping and AD grace periods)."
11. **Closest tt1 rule.** static (no threshold shipped; model frozen).
12. **Predictions.** Sustained: resist. Loud: resist. Frog: resist (nothing to ratchet, unless the user fits the threshold on live scores as the example does). Sub-event: resist.
13. **Runnable here.** In-process (numpy, scipy; Cython optional; needs tshark or scapy to parse pcaps). Pure Python is slow, roughly minutes per 100k packets (README says the C++ version is about 100x faster); memory small.
14. **Scope.** Out of scope under criterion 3 (no quantity that decides an alarm changes at run time); kept as a static control.

---

## Reference code against the tt1 re-implementations

tt1 files read: `C:\Users\marcu\Videos\cursor-os-base-tt1\scripts\threshold_rules_ext.py` (`spot_path`, `spot_mle_path`, `dspot_path`) and `threshold_rules_tt1c.py` (`NDT`, `SpotGR`, `DSpotGR`, `gpd_mle`). Last commit touching them: 28b4ed15 (2026-11-01).

### SPOT (`spot`, `spot_mle`, `spot_gr`) vs authors' `spot.py` and libspot

Same: alarms (x > z_q, strict) neither enter the peaks nor increment the count n/k; values in (t, z_q] are peaks; values <= t only increment the count; t is fixed after calibration at the 0.98 quantile; no peak cap; no clamp on z_q. The quantile formula `t + sigma/gamma*(r**-gamma - 1)` with r = q·k/Nt matches `_quantile` (spot.py 388-392).

Differences that can change what is learned or when it alarms:
1. **GPD fit.** Reference: Grimshaw MLE by root finding (`_rootsFinder` with scipy minimize, 10 candidate points per side, gamma = 0 always a candidate), refit on every new peak. tt1 `spot`: method of moments from running sums, every peak. tt1 `spot_mle`: `scipy.stats.genpareto.fit(..., floc=0)`, refit only every 2048 new peaks (16 for sample sequences), method of moments below 10 peaks, z recomputed on every peak with stale (gamma, sigma). tt1 `spot_gr`: Grimshaw profile likelihood by grid plus golden-section search, warm-started from the previous theta once there are 100 peaks, refit on every peak below 100 peaks and then only on 1% growth of the peak set. libspot v3: best of MoM and Grimshaw each excess. Different fits give different z_q, so the boundary between "learned peak" and "alarm" differs.
2. **When z is recomputed.** Reference and libspot recompute z_q only when a peak arrives; between peaks z_q stays put while n grows. tt1 `spot_gr` calls `self._z()` on every non-alarm sample (threshold_rules_tt1c.py 289-290), so its z drifts down between peaks as k grows. tt1 `spot` and `dspot` recompute only on peaks, as the reference.
3. **Initial t.** Reference: `S[int(level*n_init)]` on the sorted calibration set (order statistic). tt1: `np.quantile(calib, 0.98)` (linear interpolation). libspot v3: P² streaming estimate. libspot v1: order statistic with excesses taken from rank+1 (src/spot.cpp 461-469, so values tied with t are counted as zero-size peaks). Small effect on t and on the initial peak count.
4. **Peak cap.** Reference and tt1: none. libspot v3 default 500 FIFO; pyspot/libspot v1 default 200 FIFO (bounded=True). With a cap, frog peaks replace calibration peaks in the GPD fit while Nt/n still count all history.
5. **Overflow.** tt1 `_zq` returns +inf on OverflowError (threshold_rules_ext.py 39-42). While z is +inf nothing alarms and every finite value is learned, until a later refit gives a finite z. The reference has no guard (Python `pow` on floats raises OverflowError, which would stop `run`). Only matters for runaway tails.
6. **Comparison at t.** Stream: reference `> init_threshold` (442); libspot v3 `ex >= 0.0` (spot.c 132) includes x == t; tt1 `x > t`. Negligible on continuous scores.
7. **Variants with no reference counterpart.** `spot_gr_bounded` (|xi| <= 0.5), `spot_gr_declust` (runs declustering with 60-step gap, cluster-rate q). The reference has neither.
8. **q.** Reference README examples use q = 1e-3 to 1e-5; tt1 sets q = cfg["p"] (the calibrated alarm rate). A parameter choice, not a code difference, but it moves z_q.

### DSPOT (`dspot`, `dspot_gr`) vs authors' `dSPOT` and libspot v1 `DSpot`

Same: residual from the mean of the previous `depth` values in calibration (tt1 `csum` construction equals `backMean` alignment); n_init = len(calib) - depth; the window W starts as the last `depth` calibration values; on an alarm neither the tail nor W is updated; non-alarm values (normal or peak) enter W.

Differences: items 1-8 above apply. In addition, libspot v1 `DSpot` does not run SPOT until its own drift window is filled from the stream (dspot.cpp 203-206) and then calibrates on drift-removed values, whereas the authors' Python and tt1 build W from the calibration set; this changes which early samples the tail is calibrated on, not the exclusion rule.

### Telemanom (`ndt`) vs `telemanom/errors.py`

Same: window 2100 = 30 × 70, recomputed every 70 samples; z grid 2.5..11.5 step 0.5; fallback mean + 12 sd; tie-breaking `>=` so the larger z wins ties; guardrails "at most 5 sequences" and "fewer than half the window flagged"; mean and sd taken over all scores in the window, flagged or not (both learn from their own alarms).

Differences that can change what is learned or when it alarms:
1. **What enters the window.** Reference: EWMA-smoothed absolute LSTM errors (span 105). tt1: the raw detector score. Smoothing dilutes short bursts and delays onsets.
2. **Is the batch being judged inside its own threshold?** Reference: yes, epsilon is computed on a window that ends with the current 70-point batch, and only that batch is flagged (errors.py 123-128, 358-359). tt1 `NDT`: epsilon from the trailing buffer is applied to the next 70 samples (`tau()` before `update(x)`). A burst in the reference raises the very epsilon that judges it; in tt1 it does not until the next recompute.
3. **Score denominator and guardrail counts.** Reference: `len(E_seq)**2 + len(i_anom)` where i_anom is first widened by ±99 points (`np.arange(1, error_buffer)`, 291-298) and E_seq counts only multi-point groups (304). tt1: `len(idx) + n_seq**2` on unwidened exceedances, singletons counted as sequences. The same applies to the guardrails `n_seq <= 5` and `len(idx) < len(e)/2`. These pick different z.
4. **Extra alarm gates in the reference, absent in tt1.** `e_s > 0.05 * inter_range` with inter_range from the raw telemetry values (342-343); the whole window skipped if errors are small relative to the channel (338-340); ±100-point widening of each exceedance (347-353); first 500 points of window 0 ignored (356-357); final single-index sequences dropped (159-160).
5. **Pruning.** Reference prunes sequences whose peak is within p = 0.13 of the next lower peak, using `non_anom_max`, which excludes previously flagged indices (363-371, 403-418). tt1: no pruning (stated in the NDT docstring). This is the one place the reference leaves past alarms out, and it affects only which candidate sequences survive, not epsilon.
6. **Inverse errors.** Reference also thresholds errors mirrored about the mean (drops); tt1 is upper-only.
7. **Initialisation.** tt1 seeds the buffer with the last 2100 calibration scores; the reference starts on the test series itself (window 0 is the first 2100 test points).
8. **Small-value guards.** tt1 returns mu + 12 sd when sd <= 0 or mu == 0 and skips z with fewer than 2 values below; the reference has no such guard (division by mean_e_s could fail at zero).

### Numenta likelihood

tt1 has no re-implementation. The NAB detector's onset-only filter (C1 item 8) is behaviour no tt1 rule has.

## Additions

None. Considered and not added: Twitter AnomalyDetection (S-H-ESD; batch over the whole input like EGADS, already wrapped in NAB as `twitter`) and NAB's `earthgecko_skyline` (belongs with Skyline in group D). Instead, two variants were added as separate rows because their defaults differ from the main target: the archived python3-libspot / libspot v1.3.1 (has DSPOT, peak cap 200) and the opt-in htm.core C++ likelihood. The NuPIC library itself (numenta/nupic, now nupic-legacy) was cloned because NAB's `numenta` detector imports its `anomaly_likelihood` module.

## Could not establish

- The current GitHub home of the authors' SPOT code: Amossys-team/SPOT returns 404 and the organisation is gone. The code read is the 2017 revision archived by Software Heritage; I could not check whether a newer revision existed before deletion (the last archive visit, 2021-01-23, has the same snapshot as 2020).
- htm.core C++ `AnomalyLikelihood` behaviour: the code returns the oldest window element's likelihood and re-enters probation after each re-estimation (inferred from the code). Whether that is what users see needs a run. Not on the default path.
- Whether NAB results files for `numenta` were produced with exactly NuPIC 1.0.5 (the pin) or another version; the likelihood file is identical apart from the licence header between 1.0.5 and HEAD.
- Kitsune example: whether packets 70,000-100,000 of the Mirai capture are attack traffic; I have only the comment in example.py line 17.
- EGADS: whether any downstream deployment runs EGADS incrementally (feeding back a sliding series); the library itself has no online path.
- PyPI download counts for htm.core (pypistats rate-limited).
