# tw1c: signal-level targets in local containers (development plan)

Written 2026-11-12 and committed before any campaign was fed to any target. Status of everything this
round produces: **exploratory**. Workstream T2 of `ferrumos_followups_fi2_plan.md`.

Parent documents: `thresholds_in_the_wild_tw1_catalogue_plan.md`, `thresholds_in_the_wild_tw1_catalogue.md`
and its readings under `tw1_catalogue_readings/`, and `thresholds_in_the_wild_tw1a_dev_plan.md` (the
score-level round, its campaigns and its section "After this round").

## Question

When a monitoring product watches a metric that an attacker can write, and the product learns its normal
behaviour from that metric, can the three tt1 campaigns blind it to a later step, as the catalogue reading
of the product predicts? And do the two library targets that tw1a could not run (StreamAD, htm.core's
likelihood) behave under tw1a's score-level protocol as tw1a predicted?

## The monitored signal

No dataset is opened. The metric is the D1 monitor score of the spent Tennessee Eastman runs, read from
the tt1f score cache (`target/real-telemetry/tt1f/mode_<m>.npz`, copied read-only into
`target/tw1c/input/`) with the placement table of tw1a (`target/tw1/tep_setup.json`). The score stands for
any metric a product is asked to watch; it is non-negative, its median is about 0.39 tau0 and its 99.9th
percentile about tau0, where tau0 is the frozen threshold of the study in each mode.

**Placements.** One per mode, the first registered sealed run of the mode at its registered terminal start:
seven placements. The stream is the mode's calibration scores followed by the sealed run; the first ten
steps of every sealed run are not finite and are dropped (the terminal start is moved accordingly). tw1a
showed that its 56 placements behave as seven mode-level outcomes, which is why one per mode is used here.

**Campaigns.** The products expose no reading of their own threshold, so the tw1a campaigns are translated
open-loop, with tau0 as the reference that a static rule would use (code: `scripts/tw1c_signals.py`):

| Campaign | Injected value during the campaign window |
|---|---|
| control | the score as recorded |
| frog | max(score, floor), the floor rising linearly from the median of the series' history to 0.97 tau0 over the campaign |
| frog_hold | max(score, 0.97 tau0) for the whole campaign (tw1a's frog against a static reading) |
| loud | 33 steps at 2 tau0 every 2,000 steps (as tw1a) |
| subl | 12 steps at 2 tau0 every 500 steps (tw1a's sub-event pulses against a static reading) |

The campaign ends at the registered lead (1,000 steps) before the registered terminal start, as in tt1d.
A **terminal step** max(score, k tau0) with k in 1.05, 1.25, 1.5 and 2 lasts 167 steps and starts either
directly after the campaign (lead 0) or after the 1,000 steps of the lead. A series with magnitude
"none" has no terminal step. Each (campaign, magnitude, lead) is its own series, so that the four
magnitudes are tested from the same state, as tw1a did with copies of a target. That is 5 x (1 + 4 x 2) =
45 series per placement and 315 in all for a product.

**Outcome.** For each series: whether the product's own alarm fires on any step of the terminal window
(hit), counted per campaign, magnitude and lead over the seven placements; the product's alarms during the
campaign; and, for the series without a terminal step, alarms in the terminal window and in the whole
series (the control false alarms). The comparison that matters is a campaign against the control at the
same magnitude and lead. The static reference (an alarm when the score exceeds tau0) catches every
terminal step by construction and never alarms during the frog campaigns.

## Products and time

All three products work in wall-clock time. For each, the plan says how the series reaches the product's
clock. A run that would need more than about six hours of real time is tried once with a documented
setting that compresses time, if one exists, and is otherwise reported as not feasible here.

Resource rules for every container: official image pinned by tag and recorded by digest; `--memory` on
every container (at most 3 GB in total); ports published on 127.0.0.1 only; no host mounts except
directories under `target/tw1c/`; no privileges, no host network, no Docker socket. All names start with
`tw1c-`, and every container, network and volume is removed when the product is done. One product at a
time. Generated passwords are kept in files under `target/tw1c/` and never printed.

Images, pinned by tag and by the registry's manifest-list digest (Docker Hub, read 2026-11-12); containers
are started from `tag@digest`:

| Image | Digest |
|---|---|
| `opensearchproject/opensearch:3.9.0` | `sha256:3b55f6b6249cfdb92b52ee59adc8a266203ba9ef9f5d82544fad6f1af2f3609e` |
| `netdata/netdata:v2.12.3` | `sha256:c7eab00e20901eb60595ebae0fbfe88e59464e663924461874719d40de0735d2` |
| `zabbix/zabbix-server-pgsql:alpine-8.0.0` | `sha256:27a82a0d504e63943697bdccc964e0a8270d7c0176f4f922161bd482eec5b95c` |
| `zabbix/zabbix-web-nginx-pgsql:alpine-8.0.0` | `sha256:ed54de937d313cabb653464d0b5356c03a325ab44ee67a1784e881962382b113` |
| `postgres:16.15-alpine3.23` | `sha256:8dc5ce2495b2aeafbf033e4be590764f611248e9eb8495b5202170a6afcb64a4` |
| `python:3.10-slim` | `sha256:6ff506466f8b1e981719b468cc0023b8ef000b983cdec0eafe119d01f379e31d` |

### 1. OpenSearch anomaly detection

- **Image.** `opensearchproject/opensearch:3.9.0` (digest recorded in the results), single node,
  `DISABLE_SECURITY_PLUGIN=true`, `DISABLE_INSTALL_DEMO_CONFIG=true`, heap 1 GB, container memory 2 GB.
  The anomaly-detection plugin ships in this image. The catalogue read the plugin at main (3.10.0-SNAPSHOT,
  RCF 4.4.0); the version in the image is recorded.
- **Feature under test.** A high-cardinality detector (category field `series`) on an index of
  `{timestamp, series, value}` documents, one document per step, with one feature `max(value)`, detector
  interval 1 minute, window delay 0, and everything else at the plugin's defaults: shingle size 8,
  recency emphasis 2,560, the default suppression rule (anomalies within 20% of the expected value are
  ignored), Thresholded RCF with NORMALIZE, alertOnce and autoAdjust (catalogue rows "real-time
  thresholder", "RCF forest model", "input normaliser").
- **Time.** One step is one 1-minute interval with synthetic timestamps (series begin on 2026-01-01T00:00Z).
  Real-time detection would need 34,000 minutes per series, so the plugin's documented **historical
  analysis** (`_start` with a date range) runs the series as backfilled history. The batch path builds its
  own ThresholdedRandomCutForest with the same settings as the real-time cold start (time decay, NORMALIZE,
  alertOnce, autoAdjust, anomaly rate, rules; `ADBatchTaskCache.java`, read) and scores every interval in
  order. The batch scheduling settings (`batch_task_piece_size` up to 10,000, `batch_task_piece_interval_seconds`
  1, `max_top_entities_for_historical_analysis` at least 315) change only how fast the pieces are run.
  History before the campaign: 8,000 intervals (three times the recency emphasis of 2,560).
- **Outcome read.** The plugin's own anomaly results (`anomaly_grade > 0` per interval and entity, from the
  results index), read after the task reports FINISHED. The grade and confidence are kept, so the alerting
  plugin's default monitor trigger (grade > 0.7 and confidence > 0.7) can be read from the same results.
- **Predictions** (catalogue: EWMA-like thresholder with memory of about 2,560 intervals that learns from
  every scored point including flagged ones; forest and normaliser with time decay 1/2,560; alertOnce and
  DATA_DRIFT silence later points of a sustained run but not the learning):
  - control: every terminal step from 1.25 tau0 caught at both leads; 1.05 tau0 caught in most placements.
  - frog and frog_hold: the normaliser and the forest follow the raised level; at lead 0 the steps to
    1.05 and 1.25 tau0 are missed, 2 tau0 is caught. After the lead the model still holds the raised level
    (1,000 intervals against a memory of 2,560) and the steps to 1.05 and 1.25 tau0 are missed.
  - subl (48 pulses at 2 tau0) and loud (12 pulses): the forest samples the pulses and the thresholder rises
    with them; after subl the steps up to 1.5 tau0 are missed at lead 0 and partly recovered after the lead;
    loud has a smaller effect.
- **Not testable here if** the image does not start within 2 GB, historical analysis rejects a
  high-cardinality detector or more than 300 entities (then the series are split over several detectors),
  or the task fails for lack of heap.

### 2. Netdata

- **Image.** `netdata/netdata:v2.12.3` (catalogue: nightly v2.12.0-497 at 034d079; latest release v2.12.3),
  container memory 1 GB, no host mounts, no added capabilities, cloud features off
  (`DISABLE_TELEMETRY=1`, no claim token). The documented run command's host mounts and capabilities are
  not granted: the product only collects its own container and the metric fed to it.
- **Feature under test.** The per-dimension machine-learning anomaly bit (k-means on differenced, smoothed,
  lagged values; a point is anomalous when every model scores it at or above 99% of its training range;
  self-silencing after 450 anomalous of 900 samples), on by default with dbengine. The shipped alert
  `ml_1min_node_ar` (node anomaly rate over 1 minute above 1%) is read too, but it pools all dimensions of
  the node and cannot be attributed to one series.
- **Feed.** One statsd gauge per series, sent over UDP from a feeder container (`python:3.10-slim`,
  `tools/tw1c/netdata_feeder.py`) on a `tw1c-` network, one value per second, so that Netdata's own
  statsd collector writes the chart.
- **Time.** Netdata takes data only in real time; history cannot be backfilled with timestamps. At the
  defaults (training window 6 h, retraining every 3 h) one step per second would need 24,000 s of history
  and 25,167 s of campaign, lead and terminal step: about 13.7 h, beyond the six hours. The run therefore
  uses the documented minimums **training window 1 h** and **train every 1 h** (`[ml]` section of
  `netdata.conf`, clamped to at least 1 h in `ml_config.cc`), which shorten the product's memory six-fold,
  and scales the campaign by the same factor: campaign 4,000 steps, history 4,000 steps, pulses and the
  terminal step unchanged (loud: 2 pulses, subl: 8 pulses), lead 0 or 1,000 steps. All 315 series run in
  parallel; the run takes about 2.6 h. Every other ML setting stays at its default. The defaults themselves
  are reported as not run, with this reason.
- **Outcome read.** The anomaly bit of each dimension per second from the agent's own API
  (`/api/v1/data` with `options=anomaly-bit`), and the alert log for `ml_1min_node_ar`.
- **Predictions** (catalogue: retrained on all recent data, flagged or not; "the newest model will learn
  it as normal within 3 hours" in the documentation; differenced features make a held level anomalous only
  near its onset; unanimity lets the newest model veto):
  - control: every terminal step flagged at its onset (and at its end), at all magnitudes and both leads.
  - frog: the slow ramp is never flagged; at lead 0 the step from 0.97 to 1.05 tau0 is missed, larger steps
    are caught; after the lead the return to the normal level is flagged and the terminal step is caught.
  - frog_hold: flagged at the onset of the hold and then quiet; terminal as for frog.
  - subl and loud: models trained during the campaign hold jumps of about 1.6 tau0 in their training range,
    so terminal steps up to 1.5 tau0 are missed at both leads while those models are in the set; the 2 tau0
    step is at the edge. subl (8 pulses) poisons more reliably than loud (2 pulses), whose pulses may be
    left out of the training subsample.
- **Not testable here if** the ML engine does not train statsd charts in this image, the feeder cannot hold
  one value per second for 315 gauges, or the run is interrupted (it is then restarted from the beginning,
  once).

### 3. Zabbix

- **Images.** `zabbix/zabbix-server-pgsql:alpine-8.0.0`, `zabbix/zabbix-web-nginx-pgsql:alpine-8.0.0` (the
  frontend serves the API) and `postgres:16.15-alpine3.23`, on a `tw1c-` network, memory 1 GB, 512 MB and
  1 GB. The catalogue read master (8.2.0alpha1); `baselinewma`, `baselinedev` and `trendstl` are in 8.0.
  The database password and the API password are generated and kept under `target/tw1c/zabbix/`.
- **Feature under test.** The three opt-in trend functions in trigger expressions on a trapper item per
  series. No shipped template uses them and the documentation gives no threshold, so the expressions take
  the documentation's examples where they exist and a plain choice otherwise:
  - `baselinedev(/tw1c/<s>,1h:now/h-Nh,"d",10) > 3` (documentation example `1h:now/h,"d",10`; three
    deviations),
  - `trendavg(/tw1c/<s>,1h:now/h-Nh) > 1.2 * baselinewma(/tw1c/<s>,1h:now/h-Nh,"d",3)` (documentation
    example `1h:now/h,"d",3`; 20% above the baseline, the same ratio as OpenSearch's default rule),
  - `trendstl(/tw1c/<s>,100h:now/h-Nh,1h,2h) > 0` (documentation example `100h:now/h,10h,2h` with the
    detection period cut to the hour under test, 3 MAD by default).
- **Time.** One step is 3.6 s, the Tennessee Eastman sampling time, so an hour is 1,000 steps and a day
  24,000. These functions read only hourly averages from the trends table, so each series is sent as one
  value per hour, the mean of its 1,000 steps, with timestamps through the documented `history.push` API
  (Zabbix 7.0 and later), ending two hours before the evaluation. The time shift N of every expression is
  set so that the evaluated hour is the hour holding the terminal step; a second set of triggers with
  N + 1 reads the hour before it. Trend-only triggers are evaluated by the server once an hour; the trigger
  values are read after the first scheduled evaluation. History: ten days of calibration scores and the
  sealed run before the campaign (11 days in all), then the 24-hour campaign, the lead and the terminal
  hour. Because the product's resolution is one hour, a 167-step terminal step is diluted six-fold in its
  hour, so each terminal series is sent twice: with the 167-step step of the protocol and with a step that
  fills the hour (1,000 steps). That is 5 x (1 + 4 x 2 x 2) = 85 series per placement, 595 items.
- **Outcome read.** The trigger's own value (OK or PROBLEM) through `trigger.get` after the evaluation, and
  the problem events with their clocks. The hourly trends are read back with `trend.get` to check that the
  product holds what was sent.
- **Predictions** (catalogue: all three recompute from past periods with no exclusion; baselinedev
  includes the hour under test in its own mean and deviation):
  - baselinedev: with ten seasons and the hour under test inside its own statistics the value cannot exceed
    the square root of ten (3.16), so the trigger at 3 fires only when the other hours are nearly equal. The
    167-step terminal hour is missed in every condition; the full-hour step is caught in the control at
    the larger magnitudes. frog_hold places a raised hour in the seasons of the terminal hour and blinds it;
    frog (whose first campaign hours, the ones a day before the terminal hour, are barely raised), loud and
    subl change little.
  - baselinewma: control catches the full-hour step at every magnitude and the 167-step step at the larger
    ones; frog_hold raises the newest season, which has the largest weight, and blinds the trigger at all
    magnitudes; frog, loud and subl change little.
  - trendstl: control catches the full-hour step; frog_hold and frog are taken into the trend of the
    non-robust decomposition and weaken it at lead 0; pulses change little.
- **Not testable here if** pushed values with past timestamps do not produce trends, trend-only triggers
  are not evaluated within three hours of real time, or `history.push` is missing from this release.

## The two library targets (tw1a's score-level protocol in a container)

Both are run with tw1a's harness (`scripts/tw1a_score_level_dev.py`) and its protocol unchanged: seven
modes, the 56 registered placements, full and young history, the campaigns control, frog, loud, subl and
their capped variants, terminal steps at 1.05 to 2 tau0 at lead 0 and after the lead, the 142 recorded
attack runs of the cache, and the consistency check of every reading against the target's own decision.
A container runner (`scripts/tw1c_score_level_container.py`) supplies the new adapters and paths; the
harness file itself is not changed. The container mounts only `target/tw1c/<target>/` (code copy, cache
copy, output).

### 4. StreamAD 0.3.1

- **Image.** `python:3.10-slim`, memory 2 GB; StreamAD 0.3.1 from PyPI with the versions it pins
  (numpy below 2, pandas below 2, statsmodels 0.13.5); a C compiler is installed inside the container for
  the t-digest dependency. The installed files under test are compared by hash with the catalogued clone
  at `d2e38f4`.
- **Targets** in their documented settings (notebook `calibrator_usage.ipynb` and README):
  `ZScoreCalibrator(sigma=3, extreme_sigma=5)` alarming when its output is 1.0;
  `TDigestCalibrator(percentile_up=99, percentile_down=0)` alarming when its output is 1.0;
  `SpotDetector()` given the score as its series, alarming when its score is 1.0. Readings bisect the
  target's own call on copies; a target whose reading disagrees with its decision outside the band of
  tw1a is run open-loop only (control, loud, attack runs), as tw1a did with the Telemanom port.
- **Predictions** (tw1a plan): z-score and t-digest have global, count-based memory: little movement
  with full history, clear absorption when young. SpotDetector keeps every value above its initial
  threshold in its peaks (global memory): absorbing, moved by loud and sub-event pulses, and by the frog
  wherever the frog lies above its initial threshold.

### 5. htm.core AnomalyLikelihood

- **Build.** `python:3.10-slim` with build tools, memory 2.5 GB: htm.core built and installed from the
  catalogued commit `0cab77fa638925e0c84a1b2aa6c7cc1258cb66f1` (the owner approved running htm.core in a
  container). The last release with a Linux wheel (2.1.15, 2020) ships an older likelihood file than the one
  the catalogue read, so it is not used. If the build cannot finish within 2.5 GB and two hours, the target
  file is taken from the same commit inside the container (it imports only `math`) and the row is marked.
- **Target.** `AnomalyLikelihood(period=1000)`, alarm when `compute` returns more than 0.25 (class
  docstring), with tw1a's adapter.
- **Prediction** (tw1a plan, short-window class): the alarm stops within about one period of a sustained
  exceedance; the terminal step is missed at lead 0 when it is no larger than the campaign's level, and
  caught after the registered lead.

## Reading the results

Seven placements per product are seven mode-level outcomes; counts are given per campaign, magnitude and
lead, with no test statistics. A prediction that fails is reported as failed. Each product's result says
what was read from the product's own alarm state and what was inferred.

## Where results go

Results stay under `target/tw1c/` on the development machine and are not committed or pushed: no attack
result against a named product is published before its maintainers are told. This plan, the series
builder, the drivers and their tests are committed. Findings: `target/tw1c/tw1c_findings_local.md` and
`target/tw1c/tw1c_summary.json`.

## Not in this round

Netdata at its default training window, real-time OpenSearch detection, closed-loop campaigns against the
products (they expose no threshold reading), the Zabbix functions in shipped templates (none use them),
Elastic ML (licence), and budget-matched settings for the products.
