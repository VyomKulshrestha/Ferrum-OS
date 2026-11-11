# tw1 catalogue, group D: monitoring platforms

Read 2026-11-11. Source only; nothing built, installed or run. Clones under `C:\Users\marcu\Videos\tw1-sources\`.
Line numbers are at the commit given per target. "Read" means I read it in the code at that commit;
"inferred" means I reasoned from code I read but did not see the behaviour stated or exercised.
Item 12 entries are **predictions** (hypotheses written before any run), never results.

| Target | Commit | Clone dir |
|---|---|---|
| Netdata ML | `034d079edaa468da6b8f259653afb7e013e66702` | `netdata` (sparse) |
| Zabbix | `1de5cf68d989e20f308cb00c8e5f4ce518ec4714` | `zabbix` (sparse) |
| RRDtool | `cef7e1a9579f4175df52f6ff88c73ee9082d79fa` | `rrdtool-1.x` |
| Graphite-web | `b23b548b24a2300f55d2fb676e37ed9f4bff9c31` | `graphite-web` |
| Checkmk | `d1602e8a93e7bc40334eb323951f06705615d7db` | `checkmk` (sparse) |
| Grafana promql-anomaly-detection | `b22d38956c19fb5540ad24b6d6a7ca5179aa015b` | `promql-anomaly-detection` |
| Skyline | `0f7419f78bd982c1980556229340b81e1677733a` | `skyline` (checkout fails on Windows: a docs file name contains `:`; files read with `git show HEAD:<path>` into `skyline-read`) |
| SkyPredictor (addition) | `c010133531f6a03ee060de61e67865ec4baf9a8a` | `skypredictor` |

Adoption figures are GitHub stargazer counts from `gh api repos/<repo>` on 2026-11-11.

---

## 1. Netdata ML (per-dimension k-means, anomaly bit)

1. **Identity.** github.com/netdata/netdata, commit `034d079`, `packaging/version` = `v2.12.0-497-nightly`; latest release v2.12.3. Licence GPL-3.0 (agent; the Netdata Cloud UI is separate and not covered). Adoption: 81,367 stars (gh api, 2026-11-11).
2. **Default path.** ML is on by default when the database mode is dbengine (the default). Read: `src/daemon/config/netdata-conf-profile.c:129,145,161` set `nd_profile.ml_enabled = CONFIG_BOOLEAN_AUTO` for parent, child and standalone (IoT profile sets NO, line 110); `src/ml/ml_config.cc:137` reads `"enabled"` with that default; `ml_config.cc:292-296` turns AUTO off only when the memory mode is not dbengine. Documentation agrees: `src/ml/ml-configuration.md:3` "enabled by default if your Database mode is set to `db = dbengine`". The anomaly bit is decided in `ml_dimension_predict` (`src/ml/ml.cc:1133-1272`). The shipped health alert `ml_1min_node_ar` (`src/health/health.d/ml.conf:11-23`) warns when the 1-minute average node anomaly rate exceeds 1 %, routed `to: silent`.
3. **Adaptive quantity.** Per dimension, up to 18 k-means models (k=2). Each model's alarm threshold is its own training range: score = 100·(mean distance to centres − min_dist)/(max_dist − min_dist), capped at 100 (`ml_kmeans.cc:122-123`); a model flags when score ≥ 99 (`ml_config.cc:114`, `ml.cc:1252`), i.e. roughly when the distance exceeds 99 % of the way from the smallest to the largest training distance. The update rule: every `train every` (3 h), a new model is fitted on the trailing `training window` (6 h) and installed; the oldest is dropped once 18 exist.
4. **Learning region.** All samples in the trailing window, flagged or not. Read: the training query walks every stored point between `query_after_t = before − training_window` and `before` (`ml.cc:242-246`, `261-263`) and copies each value (`ml.cc:273-283`: `calculated_number_t value = sp.sum / sp.count;` … `worker->training_cns[idx] = value;`). No anomaly-bit test exists on this path. `max_dist` is the maximum over all training vectors (`ml_kmeans.cc:82-86`: `if (mean_dist > kmeans->max_dist) kmeans->max_dist = mean_dist;`). Training vectors are randomly subsampled to about 1,440 (`ml_config.cc:145`; ratio set at `ml.cc:1083-1089`), so at 1 s collection about 6.7 % of feature vectors in a 6 h window are used (inferred from 1440/21600).
5. **Learns from own alarms.** **Yes** (read). Nothing withholds flagged samples from the next training window. `charts_to_skip` always excludes the `anomaly_detection.*` charts (`ml_config.cc:277-279`), which are the ML output charts, not flagged samples of the input.
6. **Memory.** Window 6 h (clamped 1-24 h, `ml_config.cc:183`); retrain every 3 h (clamped 1-6 h, line 185); 18 models (clamped 1-168, line 187), so the oldest model covers data up to about 57 h old (18×3 h + 6 h, inferred). Models older than 7 days are deleted (line 150). Rotation: `ml.cc:963-989`; when the second-newest model's window overlaps both neighbours, the newest is replaced instead of the oldest being dropped (lines 973-985).
7. **Direction and bounds.** Symmetric: each model's range is recomputed from scratch, so it can widen or narrow. The configured score threshold is clamped to 0.01-1.00 (`ml_config.cc:121-126`). No floor or ceiling on max_dist. Features are first-differenced (`num samples to diff` = 1), smoothed over 3 and lagged 5 (`ml_config.cc:146,152-153`), so a constant level shift is anomalous only around its onset (inferred from the differencing).
8. **Alarm logic.** A dimension is anomalous only if **every** model that does not abstain scores ≥ 99: the loop returns false at the first model below threshold (`ml.cc:1243-1258`). With unanimity, the newest model alone can veto (inferred), so absorption into one fresh model is enough to clear the bit. Self-silencing: `dim->suppression_anomaly_counter += sum ? 1 : 0;` and once ≥ 450 anomalous samples and ≥ 900 samples have accumulated, `dim->ts = TRAINING_STATUS_SILENCED` (`ml.cc:1261-1266`); a silenced dimension returns not-anomalous (`ml.cc:1229-1232`). The counters and status reset only when a model is installed or training fails (`ml.cc:908-913`, `992`, `1052-1054`), so they count since the last retrain, not over a sliding window (inferred from where the resets are). Node rate: fraction of anomalous dimensions (`ml.cc:1450-1452`). Shipped alert: `lookup: average -1m of anomaly_rate`, `warn: $this > 1`, `to: silent` (`ml.conf:16,20,23`); no `delay` or hysteresis in that alert.
9. **Operator controls.** `enabled`, `charts to skip from training`, `hosts to skip from training`, all window/model settings, the suppression window/threshold, the score threshold (`ml_config.cc:137-177`, `274-279`). No freeze switch, exclusion window or feedback label found in `src/ml`.
10. **Documentation.** `docs/ml-ai/ml-anomaly-detection/ml-anomaly-detection.md:184`: "When an anomaly occurs, the newest model will learn it as "normal" within 3 hours. The system gradually "forgets" this pattern as older models are replaced." Line 188: "recent anomalies become "normal" quickly (within 3 hours for the newest model)". The docs (lines 112, 116) describe the per-model threshold as "the 99th percentile of training data"; the code instead normalises by min and max training distance and compares to 99 of 100 (`ml_kmeans.cc:122`), which is a 99 % point of the range, not a percentile (read; a doc/code mismatch). Suppression is documented only as two config keys (`ml-configuration.md:72-73`).
11. **Closest tt1 rule.** daily (batch recompute on a trailing window that includes alarms). Differs: recompute every 3 h on 6 h; threshold is the window maximum (100th percentile of training distances), not a quantile; unanimity over 18 models of different ages, so the newest model decides once it has seen the attack; per-cycle self-silencing; differenced features.
12. **Predictions.**
    - Sustained: **absorb**. The newest model retrains within 3 h on a window that contains the attack and vetoes; separately, 450 anomalous seconds silence the dimension until the next retrain. Differencing also makes a flat shifted level look normal after onset.
    - Loud pulses: **absorb**. A 2 h pulse cadence puts about three pulses in every 6 h window; if any pulse vector is sampled, max_dist covers it and the newest model stops flagging similar pulses.
    - Frog: **absorb**. Each retrain sets the threshold at the largest distance in the window, so sub-threshold points push it up every 3 h.
    - Sub-event pulses: **absorb**. No exclusion exists, so duration does not matter for learning; whether the shipped node alert (1-min average > 1 % of all dimensions) ever fires on one dimension is unclear.
13. **Runnable.** Docker (`netdata/netdata` image), well under 1 GB RAM for a single node (estimate). Inject a synthetic metric through a collector or statsd.

---

## 2. Zabbix baseline and anomaly functions

1. **Identity.** github.com/zabbix/zabbix (mirror), commit `1de5cf6`, `include/version.h` = 8.2.0 alpha1 (master). Licence AGPL-3.0 (gh api); runs and benchmarks are not restricted by the licence (publishing results is not addressed by AGPL). Adoption: 6,557 stars on the mirror (gh api, 2026-11-11).
2. **Default path.** Opt-in per trigger expression. No shipped template uses them: `grep -rlE 'baselinewma|baselinedev|trendstl' templates` returned nothing. Templates use only `timeleft(...,1h,100)<1d` (285 matches in 114 files under `templates/net`, YAML and README), always in an `and` with a fixed utilisation threshold, e.g. `templates/net/arista_snmp/README.md:217`. The functions are evaluated in `src/libs/zbxcalc/func_eval.c`: `evaluate_BASELINE` (lines 3868-3984) and `evaluate_TREND` → `trends_eval_stl` (lines 2606-2676, 2775-2840).
3. **Adaptive quantity.**
   - `baselinewma(item, period:time_shift, season_unit, num_seasons)`: weighted mean of the same `period` in each of the previous `num_seasons` seasons, weight `season_num − index` (newest season heaviest). Recomputed at every trigger evaluation from the trends table.
   - `baselinedev(...)`: |current period average − mean| / population stddev, over the current period plus the same period in `num_seasons` past seasons.
   - `trendstl(item, eval_period, detect_period, season, deviations=3, devalg="mad", s_window)`: STL decomposition of hourly trend averages over `eval_period`; returns the fraction of remainder points in `detect_period` beyond `deviations × devalg(remainder over the whole eval period)`.
4. **Learning region.**
   - Baseline functions: every past season's period average, whatever the trigger state. `baseline.c:65` `state = zbx_trends_get_avg(table, itemid, start, end, &value_dbl);` then `baseline.c:77` `zbx_vector_dbl_append(values, value_dbl);`. No problem/trigger state is consulted (read: the only filter is trend availability, lines 67-74). `baselinewma` skips the current period (`func_eval.c:3919-3920`, skip argument `1`); `baselinedev` includes it (`func_eval.c:3948-3949`, skip `0`), and values[0] is the current period (line 3969).
   - `trendstl`: all hourly averages in the eval window, gaps forward/back-filled (`func_eval.c:2621-2655`); the deviation unit is computed over the whole remainder, including the detection window under test (`anomalystl.c:88-94`).
5. **Learns from own alarms.** baselinewma: **yes**, from the next season on. baselinedev: **yes**, including the period under test. trendstl: **yes**, including the points under test. All read; no exclusion code exists on these paths.
6. **Memory.** User-set: `num_seasons` seasons (baseline functions), `eval_period` (trendstl). Trend data are hourly averages, so a one-hour period is the finest unit (`baseline.c`, `func_eval.c:2621` steps 3600 s).
7. **Direction and bounds.** Symmetric; no clamp. `baselinedev` returns 0 when stddev is below epsilon (`func_eval.c:3963-3972`). `trendstl` default deviations 3 and devalg `mad` (`func_eval.c:2816-2822`, `anomalystl.h:22`); STL `robust` flag off by default (`anomalystl.h:32` `ROBUST_DEF 0`, passed at `func_eval.c:2657`), so the trend and seasonal fits are least-squares-like LOESS (inferred from the flag name; robust iterations not read).
8. **Alarm logic.** Whatever the user writes in the trigger (e.g. `last(...) > baselinewma(...) * 1.2`, or `trendstl(...) > 0.1`). Trigger-level hysteresis is possible through a recovery expression; nothing is applied by default (not read in this sparse checkout; standard Zabbix trigger feature, inferred from documentation knowledge, unverified here).
9. **Operator controls.** Function parameters; time shift `period:now-1d/d` style to move the window. No exclusion list of anomalous periods found in `baseline.c` or `func_eval.c`.
10. **Documentation.** Silent on anomalous periods entering the baseline. zabbix.com 7.0 manual, trend functions page (fetched 2026-11-11): baselinewma "Calculates the baseline by averaging data from the same timeframe in multiple equal time periods ('seasons')"; trendstl "Returns the rate of anomalies during the detection period". No exclusion statement.
11. **Closest tt1 rule.** baselinewma: daily (seasonal batch recompute, alarms included), lag of one season. baselinedev: daily with a mean+k·sd test, current period included. trendstl: median_mad (MAD of the STL remainder over the window, current points included). Differs: seasonal indexing, hourly averaging, user-written trigger.
12. **Predictions.**
    - baselinewma. Sustained: **absorb** after one season (attack periods become past-season values with the largest weight); the first season resists because the current period is skipped. Loud: **resist** mostly; hourly averaging dilutes short pulses (degree unclear). Frog: **absorb**, one season per step. Sub-event: **absorb** (no exclusion; duration irrelevant).
    - baselinedev. Sustained: **absorb** over seasons; inside one season the current period inflates its own stddev only once among num_seasons+1 values (partial). Loud: **resist** (hourly averaging). Frog: **absorb**. Sub-event: **absorb**.
    - trendstl. Sustained: **absorb**; a non-robust STL trend follows a level shift, so the remainder returns near zero away from the edges. Loud: **resist**; MAD ignores sparse outliers. Frog: **unclear**. Sub-event: **unclear** (hourly averaging dilutes them).
13. **Runnable.** Docker (official server + PostgreSQL/MySQL + web images), about 1-2 GB RAM (estimate). Trends need hourly aggregation, so seasonal tests need simulated history inserted into the trends table or days of wall time.

### Zabbix `timeleft` / `forecast` (checked, out of scope)

`timeleft(/T/I,1h,100)<1d` in shipped network templates extrapolates the last hour of the monitored value to a fixed 100 % limit with a fixed 1-day horizon. There is no learned model of normal behaviour and the thresholds (100, 1d) are constants, so "flagged samples entering a baseline" does not apply. `forecast` is not used in any shipped template (0 files).

---

## 3. RRDtool aberrant behaviour detection (Holt-Winters, Brutlag)

1. **Identity.** github.com/oetiker/rrdtool-1.x, commit `cef7e1a`, `VERSION` = 1.11.0 (= latest release v1.11.0). Licence GPL-2.0. Adoption: 1,121 stars (gh api, 2026-11-11); RRDtool is a storage backend for other tools, which this count does not capture.
2. **Default path.** Opt-in at `rrdtool create` by declaring `RRA:HWPREDICT:rows:alpha:beta:period` (the other four RRAs are created implicitly, `doc/rrdcreate.pod:400-412`). Per primary data point, `update_aberrant_CF` (`src/rrd_hw.c:437-526`) calls `update_hwpredict`, `update_seasonal`, `update_devseasonal`, `update_devpredict`, `update_failures` (`src/rrd_hw_update.c`). Which RRD-based products create HWPREDICT RRAs by default: unclear (not established).
3. **Adaptive quantity.** Holt-Winters level (intercept), trend (slope), per-slot seasonal coefficient, per-slot deviation (EWMA of |prediction − observed|). Band = prediction ± delta·deviation; FAILURES = 1 when at least `threshold` of the last `window` points violated the band.
4. **Learning region.** Every non-NaN observation updates all terms, inside or outside the band. Intercept (`rrd_hw_update.c:93-97`): `coefs[CDP_hw_intercept].u_val = functions->intercept(current_rra->par[RRA_hw_alpha].u_val, coefs[CDP_scratch_idx].u_val, seasonal_coef, coefs);`. Deviation (`rrd_hw_update.c:352-362`, rule at `rrd_hw_math.c:128-136`): `return hw_gamma * fabs(prediction - observed) + (1 - hw_gamma) * last;`. Seasonal (`rrd_hw_update.c:170-177`). The only skip is for NaN inputs (lines 88-91, 143-148, 333-337). The violation test (`rrd_hw_update.c:444-454`) writes only to the FAILURES RRA and is never read by the update functions (read).
5. **Learns from own alarms.** **Yes** (read).
6. **Memory.** EWMA: intercept α (user-required argument), slope β (user-required), seasonal and deviation γ = α when implicitly created (`rrd_create.c:1152-1153`, `1167-1168`). Seasonal and deviation terms are per slot, so each slot updates once per season. Seasonal smoothing window 0.05 of the season (`rrd_create.c:480`).
7. **Direction and bounds.** Symmetric; no clamp. Deviation is non-negative by construction. Band asymmetry via delta_pos / delta_neg (default 2, `rrd_create.c:1189-1190`).
8. **Alarm logic.** FAILURES with implicit defaults threshold 7 of window 9 (`rrd_create.c:1191-1192`); explicit `RRA:FAILURES` parsing starts from 2 of 3 before tokens override (`rrd_create.c:490-493`). NaN observations count as violations (`rrd_hw_update.c:453`). The test uses the deviation from before this step's update (lines 395-404), so the point under test does not widen its own band (read).
9. **Operator controls.** `rrdtune` `--deltapos`, `--deltaneg`, `--failure-threshold`, `--window-length`, `--alpha`, `--beta`, `--gamma`, smoothing windows, and `--aberrant-reset` ("forget all it has learnt so far", `doc/rrdtune.pod:157-165`). No freeze or exclusion.
10. **Documentation.** Silent on anomalies entering the model. `doc/rrdcreate.pod:328-391` describes the RRAs and FAILURES; nothing about excluding violations.
11. **Closest tt1 rule.** ewma (EWMA level plus k EWMA-deviations, alarms included). Differs: seasonal per-slot deviation, Holt-Winters trend, k-of-n violation window (7 of 9) acting like an on-delay.
12. **Predictions.** Sustained: **absorb** (intercept follows the shift at rate α; per-slot deviations grow; the 7-of-9 count falls). Loud: **absorb** (each pulse raises its slot's deviation for the next season and nudges the intercept). Frog: **absorb**. Sub-event: **absorb** (pulses shorter than 7 points never fail but still update every term).
13. **Runnable.** In-process CLI (`rrdtool create/update/fetch`), negligible resources; Windows binaries or a small Linux container.

---

## 4. Graphite-web Holt-Winters functions

1. **Identity.** github.com/graphite-project/graphite-web, commit `b23b548`, `setup.py:82` version 1.2.0 (master, unreleased); latest release 1.1.10 (the functions were not compared against the 1.1.10 tag). Licence Apache-2.0. Adoption: 6,137 stars (gh api, 2026-11-11).
2. **Default path.** Opt-in render functions: `holtWintersConfidenceBands`, `holtWintersAberration` (`webapp/graphite/render/functions.py:4141-4247`), both calling `holtWintersAnalysis` (lines 4008-4103). Graphite has no alerting; an alarm needs an external evaluator (e.g. a Grafana alert on a Graphite query). Defaults: delta 3, bootstrapInterval 7d, seasonality 1d (lines 4203-4208, 4242-4247); α = γ = 0.1, β = 0.0035 hard-coded (lines 4009-4010).
3. **Adaptive quantity.** Same Holt-Winters terms as RRDtool, recomputed from scratch at every render over [from − 7d, until].
4. **Learning region.** All non-None points in the render window plus the bootstrap. Loop `functions.py:4069-4074`: `intercept = holtWintersIntercept(alpha,actual,last_seasonal ,last_intercept,last_slope)` … `deviation = holtWintersDeviation(gamma,actual,prediction,last_seasonal_dev)`. The band at point i uses `deviations[i]`, which already includes |actual_i − prediction_i| (lines 4074, 4080, 4162-4181), so the point under test widens its own band (read). With γ = 0.1, delta = 3, a point violates only if |e| > 3.86 × the previous same-slot deviation (inferred arithmetic: |e| > 3(0.1|e| + 0.9d)).
5. **Learns from own alarms.** **Yes** (read), including the current point.
6. **Memory.** EWMA with α = γ = 0.1 per step (slot deviation per season); recomputed from a 7-day bootstrap on every render, so memory is also cut at 7 days plus the view range.
7. **Direction and bounds.** Symmetric; none.
8. **Alarm logic.** None in Graphite; `holtWintersAberration` returns the distance outside the band (lines 4224-4232).
9. **Operator controls.** delta, bootstrapInterval, seasonality per query.
10. **Documentation.** Silent. Docstrings only describe the forecast and bands (lines 4142-4145, 4212-4215).
11. **Closest tt1 rule.** ewma. Differs: the current point is included in its own deviation; whole-history recompute at each query.
12. **Predictions.** Sustained: **absorb**. Loud: **absorb** (slot deviation inflated for the next season). Frog: **absorb**. Sub-event: **absorb** (no exclusion; any duration logic lives in the external alert rule).
13. **Runnable.** In-process (pure Python function over a list) or Docker `graphiteapp/graphite-statsd`, < 1 GB (estimate).

---

## 5. Checkmk predictive levels

1. **Identity.** github.com/Checkmk/checkmk, commit `d1602e8`, `defines.make` VERSION 3.0.0b1 (master; GitHub has no release objects). Licence GPL-2.0 for this repository. **Licence note:** the Checkmk documentation (docs.checkmk.com, "Predictive monitoring", fetched 2026-11-11) presents predictive levels as a feature of "the commercial editions", and the GUI form title reads "Predictive levels (only on CMC)" (`cmk/gui/form_specs/visitors/recomposers/levels.py:345`). Whether the GPL edition can execute them is unclear. Adoption: 2,640 stars (gh api, 2026-11-11).
2. **Default path.** Opt-in per check parameter rule (levels type "predictive"). Defaults when chosen: period `wday`, horizon 90 days (`levels.py:361`, `373`), levels type prefilled `absolute` (`levels.py:288`) with plugin-specific offsets; stdev prefill (2, 4) (`packages/cmk-plugin-apis/cmk/rulesets/v1/form_specs/_levels.py:53`). Reference built in `cmk/utils/prediction/_prediction.py:113-190`, levels in `_plugin_interface.py:72-121`, injected at `cmk/base/checkers.py:768-786`.
3. **Adaptive quantity.** Reference = average of the metric at the same time of day over every matching past slice (every Monday for `wday`) within the horizon; levels = reference ± warn/crit × (1 | reference/100 | stdev).
4. **Learning region.** All recorded values of the matching slices, consolidated with RRD `max` (`_prediction.py:21`, `125`). `_prediction.py:186`: `DataStat.from_values(point_line) if (point_line := [x for x in time_column if x is not None])`. The only filter drops missing values. No check state is consulted (read).
5. **Learns from own alarms.** **Yes** (read): slices in which the service was WARN/CRIT are averaged like any other.
6. **Memory.** Horizon 90 days (≈ 13 matching weekdays for `wday`). Recomputed at most once per day: `PredictionInfo.make` sets `valid_interval=(start_of_day, start_of_day + _ONE_DAY)` (`prediction_backend.py:47-53`), a stored prediction is reused while valid (`_prediction.py:100`, `_plugin_interface.py:34-36`). The slice list starts at the current day (`_grouping.py:108-112`); at the first check after midnight the current slice is almost empty (inferred).
7. **Direction and bounds.** Symmetric reference. Optional `bound` ("Fixed limits"): for upper levels `max(estimated, bound)` (`_plugin_interface.py:82-86`), a floor under the threshold that prevents it falling too low but does not stop it rising. No ceiling.
8. **Alarm logic.** Standard check levels (WARN/CRIT per check). Notification delays and max check attempts are general Checkmk features, not read here.
9. **Operator controls.** period, horizon, levels type and values, fixed limits. No exclusion of past periods found.
10. **Documentation.** Silent on excluding problem periods (docs.checkmk.com predictive monitoring page, fetched 2026-11-11). It states the standard deviation is computed from "all measured values of the reference period" and that "Checkmk learns continuously".
11. **Closest tt1 rule.** daily (seasonal recompute once per day, alarms included). Differs: averaged over ~13 weeks, so one week has weight ≈ 1/13; RRD `max` consolidation of older data.
12. **Predictions.** Sustained: **resist** for days, **absorb** over weeks (reference moves by about 1/13 of the shift per week of attack). Loud: **resist** with absolute/relative levels; with stdev levels, the stdev of the affected time slots inflates (partial). Frog: **absorb** slowly (closed loop at about 1/13 per week). Sub-event: **absorb** in the sense that nothing is excluded; RRD max consolidation may amplify short pulses in older data (unclear).
13. **Runnable.** Unclear: the documentation ties the feature to the commercial CMC core. A Docker image of the free edition exists (from general knowledge, unverified here); whether it computes predictive levels was not established. The algorithm itself is pure Python and could be exercised in-process with synthetic slices.

---

## 6. Grafana promql-anomaly-detection (recording/alerting rules)

1. **Identity.** github.com/grafana/promql-anomaly-detection, commit `b22d389`, latest release v0.3.0. Licence Apache-2.0. Adoption: 433 stars (gh api, 2026-11-11).
2. **Default path.** Opt-in: copy `rules/*.yml` into Prometheus and tag metrics with `anomaly_name` (`README.md:38-50`). Default strategy `adaptive` (`README.md:55`; selector `anomaly_strategy=~"^$|adaptive"`, `rules/adaptive.yml:41`). Alert `AnomalyDetected`, `for: 5m`, level outside the band (`adaptive.yml:181-189`; `robust.yml:164-172`).
3. **Adaptive quantity.** adaptive: upper band = max(avg_1h + 2·stddev_st, avg_1h·1.5, long-term band from the same hour 1 day and 1 week ago); stddev_st = 26 h average of the 1 h stddev, kept only where the 1 h coefficient of variation exceeds 0.5. robust: median of 24 h ± 2·MAD of 24 h, a margin of 0.5·median, and seasonal bands from 1 d / 1 w ago; the level is a 1 h median.
4. **Learning region.** All samples of the selected series. adaptive.yml:51 `avg_over_time(anomaly:adaptive:select[1h])`; :61 `stddev_over_time(anomaly:adaptive:select[1h]) > anomaly:adaptive:avg_1h * on() group_left anomaly:adaptive:threshold_by_covar`; :67 `avg_over_time(anomaly:adaptive:stddev_1h:filtered[26h])`; long-term :136-138 (`offset 167h30m`) and :144-146 (`offset 23h30m`). robust.yml:37 `quantile_over_time(0.5, anomaly:robust:select[1d])`, :45 `quantile_over_time(0.5, anomaly:robust:abs_dev_lt[1d])`. The "high pass filter" (adaptive.yml:53-61) keeps **high**-variability hours and drops low ones, so it admits outlier-heavy hours rather than excluding them (read). No rule references `ALERTS` or the alert state (read, both files).
5. **Learns from own alarms.** adaptive: **yes**. robust: **yes** (median/MAD bound the influence until a sustained shift covers half the window). Read.
6. **Memory.** adaptive: 1 h mean, 26 h smoothing of stddev, 1 d and 1 w look-backs. robust: 24 h median and MAD, 1 h level median, 1 d / 1 w look-backs.
7. **Direction and bounds.** Upper band is the max of three candidates and the lower band the min (wider wins); lower band `clamp_min(..., 0)` and pinned to 0 for errors/latency (adaptive.yml:99-121). Margin band gives a floor width of 0.5·avg_1h (adaptive) or 0.5·median (robust).
8. **Alarm logic.** `for: 5m` on-delay; `last_over_time(...[2m])` on both sides. No hysteresis.
9. **Operator controls.** Edit the constants (multipliers, CoV threshold, sparse threshold); choose strategy per metric by label.
10. **Documentation.** README:55 says adaptive is "minimizing false positives for recurring events" and robust "is robust to outliers". adaptive.yml:63-64: the smoothing gives "bands that expand gently in the presence of extreme outliers". No statement about excluding anomalous samples (silent on exclusion).
11. **Closest tt1 rule.** adaptive: ewma-like (moving mean plus k smoothed deviations, alarms included) with a 5 min on-delay. robust: median_mad (24 h) with a 1 h median level.
12. **Predictions.** adaptive. Sustained: **absorb** within about an hour (avg_1h includes the shifted level; alerting stops once the level is below avg_1h + max(2σ, 0.5·avg_1h); the next day the 1 d look-back also carries it). Loud: **absorb** (pulse hours pass the CoV filter and widen stddev_st for 26 h). Frog: **absorb**. Sub-event: pulses under 5 min never alert (`for: 5m`) and still enter every window: **absorb**.
    robust. Sustained: **resist** for about 12 h, then **absorb** when the shifted level is the 24 h median. Loud: **resist** (median, MAD and the 1 h median level ignore sparse pulses). Frog: **absorb** slowly. Sub-event: **resist** for alerting (a 1 h median level ignores them); they still enter the windows.
13. **Runnable.** Docker (Prometheus alone, < 1 GB) or `promtool test rules` with synthetic series (in-process, the repo ships `tests/*_test.yml`).

---

## 7. Skyline (Analyzer three-sigma ensemble; Ionosphere)

1. **Identity.** github.com/earthgecko/skyline, commit `0f7419f`, `skyline/skyline_version.py:40` = 5.0.0 on branch `v5.0.0-alpha`; latest release v4.0.0. Licence MIT (`LICENSE`; gh reports NOASSERTION). Adoption: 596 stars (gh api, 2026-11-11).
2. **Default path.** Analyzer enabled (`settings.py:428`); `ALGORITHMS` = 9 algorithms (`settings.py:820-830`); `CONSENSUS = 6` (`settings.py:838`); `FULL_DURATION = 86400` (`settings.py:102`); Mirage off (`settings.py:1115`), second-order off (`settings.py:1100`); Ionosphere enabled and `IONOSPHERE_LEARN = True` (`settings.py:2976`, `3230`). Decision in `run_selected_algorithm` (`skyline/analyzer/algorithms.py:1168-2045`): anomalous when `ensemble.count(False) <= threshold` with `threshold = len(ensemble) - CONSENSUS` (lines 2006, 2025).
3. **Adaptive quantity.** Each algorithm recomputes its statistics from the metric's last 24 h in Redis at every run (mean/std, EWMA mean/std with com=50, median/MAD, histogram, Grubbs, least squares, KS test).
4. **Learning region.** All points in the 24 h window, including the points under test. `algorithms.py:374-378` (stddev_from_average): `mean = series.mean()` / `stdDev = series.std()` / `t = tail_avg(timeseries, series)` / `return abs(t - mean) > 3 * stdDev`. `algorithms.py:400-410` (stddev_from_moving_average) EWMA over the full series including the last point. `algorithms.py:243-276` (median_absolute_deviation) median and MAD over the full series. Exceptions: `mean_subtraction_cumulation` excludes only the last point (lines 428-430, 444-445); `first_hour_average` uses the hour 24 h ago (lines 338-346). The timeseries is read from Redis without any anomaly filter (`analyzer.py:2252-2281`, read in outline).
5. **Learns from own alarms.** Analyzer: **yes** (read). Ionosphere feedback loop: **unclear**; Ionosphere code was not read. Its documented design is operator-labelled "not anomalous" features profiles plus automatic "learning" from them (`docs/ionosphere.rst:93-114`).
6. **Memory.** 24 h rolling window (`FULL_DURATION`); EWMA com=50 points; Ionosphere learn defaults: 30 days, 16 generations (`settings.py:3257`, `3289`).
7. **Direction and bounds.** Symmetric; none. MAD test returns False when MAD = 0 (`algorithms.py:254-255`; numba path 209-210).
8. **Alarm logic.** 6 of 9 algorithms; `tail_avg` of the last 3 points for several tests (`algorithms.py:180-193`); alert re-send expiry per ALERTS tuple (e.g. 1800 s for `skyline`, `settings.py:1150`).
9. **Operator controls.** Ionosphere training (operator marks an anomaly as not anomalous; layers rules), ALGORITHMS, CONSENSUS, per-namespace learn config.
10. **Documentation.** For Analyzer, silent on anomalies entering the window. Ionosphere: "Ionosphere's goal is to allow us to train Skyline on what is not anomalous" (`docs/ionosphere.rst:31`).
11. **Closest tt1 rule.** Ensemble of median_mad / ewma / mean+3σ over the last day, with alarms included; consensus 6 of 9.
12. **Predictions.** Sustained: **absorb** (24 h mean and std inflate; median-based tests last about 12 h). Loud: **absorb** for mean/std tests, **resist** for MAD and histogram; consensus outcome unclear. Frog: **absorb**. Sub-event: **absorb** (no exclusion); `tail_avg` over 3 points dilutes 1-point pulses.
13. **Runnable.** Unclear. Needs Redis, MySQL, a Graphite-like feed and several daemons; no official Docker setup was found in this reading. Probably feasible in containers at 2-4 GB (estimate, unverified).

---

## Additions

Logged 2026-11-11.

### A1. SkyPredictor (default baseline service for Apache SkyWalking alarms)

Reason for adding: Apache SkyWalking's alarm engine can alarm on a predicted baseline, and its documentation names SkyAPM/SkyPredictor as "a default implementation" (`apache/skywalking` `docs/en/setup/ai-pipeline/metrics-baseline-integration.md`, master `b0a3065`, read via gh api). It is the adaptive-baseline feature of a widely used open-source APM.

1. **Identity.** github.com/SkyAPM/SkyPredictor, commit `c010133`, no release tag read. Licence Apache-2.0. Adoption: 7 stars (gh api, 2026-11-11), low; its adoption runs through SkyWalking.
2. **Default path.** Opt-in: deploy SkyPredictor, connect the SkyWalking OAP, write an alarm rule that uses the baseline (SkyWalking docs). Fit every `*/8 * * * *` (`baseline/config/config.yaml:27`), metrics `service_cpm,service_percentile` (line 35), hourly down-sampling (line 33), min 2 days (line 38), forecast period 24 (line 40).
3. **Adaptive quantity.** Prophet forecast `yhat` with `yhat_upper` / `yhat_lower` served as the baseline (`baseline/predict.py:142`, `154-156`).
4. **Learning region.** All fetched hourly points over the OAP metrics TTL (`baseline/fetcher.py:269-277`, `279-287`). `predict.py:208-209`: `m = Prophet(daily_seasonality=True, weekly_seasonality=False, yearly_seasonality=False)` / `m.fit(meter.single_df)`. Only NaN rows are dropped (`predict.py:243`, `260`).
5. **Learns from own alarms.** **Yes** (read: no alarm state is fetched or used).
6. **Memory.** The OAP metrics TTL in days (read via `/status/config/ttl`); value unclear (OAP default not read).
7. **Direction and bounds.** Negative predictions zeroed (`ignore_nagative_value`, `predict.py:154-156`). Prophet's default interval width applies (not read).
8. **Alarm logic.** In SkyWalking alarm rules (period, silence period); not read.
9. **Operator controls.** Env-var config; no exclusion.
10. **Documentation.** Silent (SkyWalking integration page and config).
11. **Closest tt1 rule.** daily (periodic refit on a long window including alarms).
12. **Predictions.** Sustained: **absorb** (Prophet's trend follows a level shift after refits). Loud: **unclear** (hourly averaging dilutes; Prophet is not outlier-robust). Frog: **absorb**. Sub-event: **unclear** (hourly averaging).
13. **Runnable.** Docker: SkyWalking OAP + storage (BanyanDB or Elasticsearch) + SkyPredictor, roughly 4-6 GB (estimate). Not attempted.

Only one addition was made; the remaining two slots were not used.

## Checked and left out

- **SigNoz anomaly alerts.** The anomaly code sits under `ee/` (`ee/anomaly/*.go`, `ee/query-service/rules/anomaly.go`, listed via gh api tree), covered by "The SigNoz Enterprise license" (`ee/LICENSE` head), not an open-source licence. Left out of the open-source table; could get a documentation-only row.
- **Prometheus core.** Not cloned. Left out because Prometheus ships no anomaly or baseline alerting of its own (alert thresholds are user PromQL); the Grafana rule pack above is the adaptive layer. Unverified at a commit.
- **Icinga, LibreNMS, OpenNMS thresholding.** Not cloned. Left out because, as far as I know, their thresholds are static or relative-change rules without a learned baseline. Unverified; a quick read of OpenNMS `relativeChange` would settle it.
- **VictoriaMetrics anomaly detection (vmanomaly).** Left out: vmanomaly is an enterprise component, not part of the open-source VictoriaMetrics (from product knowledge, unverified here).
- **Wazuh.** Left out: its anomaly detection is the OpenSearch Anomaly Detection plugin, which group B covers.
- **Apache SkyWalking OAP itself.** Covered through A1. The OAP alarm rule mechanics were not read.

## Could not establish

- Netdata: whether the shipped node-rate alert fires for a single-dimension attack; how often a short pulse's feature vector survives the 6.7 % training subsample. The doc text ("99th percentile") disagrees with the code (99 % of the min-max range).
- Zabbix: trigger recovery and hysteresis semantics were not read in this sparse checkout. Exact STL robustness behaviour with `ROBUST_DEF 0` was inferred from the flag name, not from the STL code.
- RRDtool: which downstream products (Cacti, Munin, Smokeping, collectd) create HWPREDICT RRAs by default.
- Graphite: whether 1.1.10 has the same `holtWintersAnalysis` as master.
- Checkmk: whether the GPL edition runs predictive levels; the alarm-side delays; the age resolution of RRD data feeding a 90-day horizon.
- Skyline: Ionosphere learning code (whether auto-learned profiles can be seeded from unlabelled flagged periods); a supported container setup.
- SkyPredictor: OAP default TTL; Prophet interval width; SkyWalking alarm-rule semantics.
