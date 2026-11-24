# Phase 7: UCI Online Retail empirical calibration benchmark

## Purpose

This is an opt-in empirical benchmark for the Phase 6 lead-time residual-path
calibrator. It evaluates dense, intermittent, and very-intermittent SKU cohorts
on a real transaction dataset and compares Seasonal Naive, Croston SBA, and TSB.

## Dataset and attribution

- Dataset: [UCI Online Retail](https://archive.ics.uci.edu/dataset/352/online-retail)
- Creator: Daqing Chen
- Citation: Chen, D. (2015). *Online Retail*. UCI Machine Learning Repository.
- DOI: https://doi.org/10.24432/C5BW33
- License: CC BY 4.0
- Original workbook: `Online Retail.xlsx`

The raw workbook is not committed. The dedicated GitHub Actions workflow
`.github/workflows/uci-online-retail-benchmark.yml` downloads the official UCI
archive at run time, extracts the workbook, executes this benchmark, and uploads
the JSON report as a 30-day artifact. For a local run, download the workbook
from UCI and install the optional benchmark dependencies:

```bash
python -m pip install -e ".[benchmark,dev]"
```

Run the benchmark:

```bash
python evals/run_uci_online_retail_benchmark.py /path/to/Online\\ Retail.xlsx
```

For a smaller development run, use `--max-skus-per-cohort 3`. The default is
10 SKUs per cohort.

## Preprocessing contract

- Exclude cancellation invoices (InvoiceNo beginning with `C`, case-insensitive).
- Exclude non-positive quantities, including returns. This is intentional:
  the target is gross outbound unit demand, not net accounting movement.
- Aggregate positive quantities by StockCode and calendar day.
- Fill days without a sale with zero after constructing a complete daily calendar.
- Freeze cohort membership using only the first 180 calendar days, matching the
  initial training window. No observations from later evaluation periods influence
  cohort assignment.
- Require at least eight active sales days within that initial window.
- Dense: activity on at least 50% of initial-window days.
- Intermittent: activity on 5% to less than 50% of initial-window days.
- Very intermittent: activity on less than 5% of initial-window days.
- Select up to 10 SKUs per cohort by stable SHA-256 ordering of StockCode.
  This is deterministic, not a volume-weighted or random sample.

## Evaluation design

- Cohort membership is frozen from the initial 180-day training window.
- 180-day expanding training window.
- 14-day forecast horizon, 7-day origin step.
- Lead times: 7 and 14 days.
- Quantiles: P10, P50, P90.
- Models: Seasonal Naive, Croston SBA, and TSB.
- Residual-path calibration: 250 bootstrap draws, at least five strictly earlier
  non-overlapping calibration paths, with Phase 6's model-version and leakage guards.
- Prequential evaluation reports per-SKU cumulative quantile coverage, P80
  interval coverage, and pinball loss. Cohort summaries are unweighted
  macro-averages across SKUs.


## SKU-level coverage and baseline-bias diagnostics

A follow-up run adds per-SKU dispersion and baseline median-error diagnostics to
the JSON report. It uses the same 30-SKU sample, model fits, rolling origins,
and prequential eligibility rule as the corrected benchmark. The diagnostic
runner was executed at commit `3f8197e0b58b7ea7ff71a2263c7dbc655a2d520d`:

- [Diagnostic benchmark workflow](https://github.com/mojtaba-arvin/demand-forecast-kit/actions/runs/45049056780)
- [Diagnostic JSON artifact](https://github.com/mojtaba-arvin/demand-forecast-kit/actions/runs/45049056780/artifacts/14764981545)

For every SKU/model/lead-time combination, the report now records the baseline
cumulative P50 error on exactly the forecast origins eligible for residual-path
calibration. Error is defined as actual cumulative lead-time demand minus the
uncalibrated model's cumulative median forecast; positive values indicate
underforecasting. It also records mean absolute error and the fraction of
eligible origins underforecast. The cohort diagnostics report the equal-SKU
macro error, P10/P50/P90 empirical coverage, P80 coverage range across SKUs,
and the number of SKUs below nominal P80.

| Cohort | Lead | Model | P80 macro (SKU min–max) | SKUs below 0.80 | P10 / P50 / P90 coverage | Baseline P50 bias |
|---|---:|---|---:|---:|---:|---:|
| Dense | 7 | Croston SBA | 0.656 (0.250–0.938) | 7/10 | 0.225 / 0.438 / 0.869 | +17.3 |
| Dense | 14 | Croston SBA | 0.625 (0.250–0.875) | 7/10 | 0.175 / 0.469 / 0.800 | +32.7 |
| Dense | 7 | Seasonal Naive | 0.500 (0.312–0.750) | 10/10 | 0.400 / 0.606 / 0.887 | +3.0 |
| Dense | 14 | Seasonal Naive | 0.469 (0.188–0.688) | 10/10 | 0.406 / 0.613 / 0.863 | +4.1 |
| Dense | 7 | TSB | 0.688 (0.438–0.938) | 7/10 | 0.212 / 0.494 / 0.887 | +17.8 |
| Dense | 14 | TSB | 0.600 (0.375–0.875) | 7/10 | 0.219 / 0.512 / 0.819 | +33.7 |
| Intermittent | 7 | Croston SBA | 0.669 (0.312–1.000) | 6/10 | 0.400 / 0.619 / 0.850 | +35.3 |
| Intermittent | 14 | Croston SBA | 0.631 (0.250–1.000) | 7/10 | 0.325 / 0.550 / 0.819 | +80.5 |
| Intermittent | 7 | Seasonal Naive | 0.544 (0.312–0.875) | 9/10 | 0.537 / 0.700 / 0.869 | +9.9 |
| Intermittent | 14 | Seasonal Naive | 0.544 (0.250–0.812) | 9/10 | 0.450 / 0.631 / 0.856 | +29.7 |
| Intermittent | 7 | TSB | 0.588 (0.250–0.938) | 8/10 | 0.481 / 0.662 / 0.856 | +30.1 |
| Intermittent | 14 | TSB | 0.575 (0.375–0.875) | 8/10 | 0.375 / 0.581 / 0.831 | +70.2 |
| Very intermittent | 7 | Croston SBA | 0.819 (0.375–1.000) | 4/10 | 0.719 / 0.788 / 0.912 | -0.2 |
| Very intermittent | 14 | Croston SBA | 0.775 (0.438–1.000) | 5/10 | 0.669 / 0.762 / 0.906 | -0.5 |
| Very intermittent | 7 | Seasonal Naive | 0.775 (0.438–1.000) | 5/10 | 0.794 / 0.825 / 0.944 | -0.1 |
| Very intermittent | 14 | Seasonal Naive | 0.750 (0.500–1.000) | 6/10 | 0.738 / 0.800 / 0.925 | -0.3 |
| Very intermittent | 7 | TSB | 0.725 (0.188–1.000) | 5/10 | 0.787 / 0.838 / 0.925 | +0.1 |
| Very intermittent | 14 | TSB | 0.750 (0.375–1.000) | 5/10 | 0.688 / 0.787 / 0.919 | +0.2 |

### Interpretation

- The dense and intermittent undercoverage is distributed across SKUs, not
  explained by one or two outliers. For dense SKUs, 7–10 of 10 series are below
  nominal P80 across the model/lead-time slices; for intermittent SKUs, 6–9 of
  10 are below nominal.
- In dense and intermittent cohorts, empirical P10 coverage is consistently
  above 0.10 while P90 coverage is generally below 0.90. The lower quantiles
  are too high and upper quantiles too low, indicating intervals that are too
  narrow. The baseline cumulative median error is also positive in every
  dense/intermittent model slice, indicating baseline underforecasting on
  average.
- The calibrated P50 coverage does not move uniformly with baseline bias:
  Croston SBA's intermittent P50 coverage is above 0.50 despite positive
  baseline median error. This is evidence that the residual-path adjustment
  can shift the center differently from the underlying model's baseline bias;
  it is not safe to apply one global additive correction.
- Very-intermittent baseline median bias is close to zero and P80 macro coverage
  is nearer nominal, but SKU-level ranges remain wide. Large point masses at
  zero and discrete cumulative demand also make quantile hit rates less smooth
  in this cohort.
- These diagnostics localize the problem but do not yet establish its cause.
  They are based on 10 deterministically selected SKUs per cohort and 16
  prequential evaluation origins per SKU. The origins overlap in calendar time,
  so they must not be treated as 16 independent observations for confidence
  intervals or significance tests.

No calibration parameter was tuned on these evaluation outcomes. The next
valid experiment must fit any bias/scale/conformal adjustment using only earlier
calibration origins and evaluate it on a later, untouched chronological block.


## Purged temporal holdout: residual-width and median-bias adjustments

The runner now exports each calibrated forecast origin and compares two
post-calibration adjustments without using the holdout outcomes for fitting.
The experiment ran successfully on commit
`5c9af0014c6854204fefd20fe5b21dd062eeb765`:

- [Temporal holdout workflow](https://github.com/mojtaba-arvin/demand-forecast-kit/actions/runs/45050049303)
- [Schema v2 JSON artifact](https://github.com/mojtaba-arvin/demand-forecast-kit/actions/runs/45050049303/artifacts/14765157630)

### Split and fitting protocol

For each SKU/model/lead-time series, the 16 eligible prequential origins are
ordered chronologically. The split is fixed before scoring:

- Calibration offsets: 0, 2, 4, and 6 (four non-overlapping 14-day target windows).
- Holdout offsets: 10, 12, and 14 (three non-overlapping 14-day target windows).
- The other nine offsets are purged. The gap between the final calibration
  origin and first holdout origin is also greater than the 14-day target horizon.
- Per cohort/model/lead-time slice this yields 40 calibration observations
  (10 SKUs × 4 origins) and 30 holdout observations (10 SKUs × 3 origins).

Two adjustments are fit on the calibration block only:

1. **Width scaling:** multiply the distances from calibrated P50 to P10/P90 by
   one factor selected from `[0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4]`, minimizing
   the combined P10 and P90 pinball loss on calibration observations.
2. **Median bias + width scaling:** shift all quantiles by the median
   `actual - calibrated P50` error from the calibration block, then fit the
   width factor using the same calibration-only pinball objective.

The fitted parameters remain fixed for the later holdout origins. The underlying
forecast and residual-path calibrator continue their normal prequential updates
using only observations available before each forecast origin.

### Holdout results

The table equally averages the six model/lead-time slices within each cohort.
Tail pinball is the sum of P10 and P90 pinball losses (lower is better).
Demand units differ substantially across cohorts, so compare methods within a
cohort, not across cohorts.

| Cohort | Baseline P80 | Width-scaled P80 | Bias+width P80 | Baseline tail pinball | Width-scaled tail pinball | Baseline / scaled interval width |
|---|---:|---:|---:|---:|---:|---:|
| Dense | 0.550 | 0.733 | 0.678 | 50.435 | 56.540 | 211.50 / 371.43 |
| Intermittent | 0.639 | 0.772 | 0.800 | 71.880 | 70.693 | 241.25 / 390.95 |
| Very intermittent | 0.839 | 0.861 | 0.861 | 2.755 | 2.986 | 12.74 / 16.84 |

Across the 18 cohort/model/lead-time slices:

- Width scaling increased holdout P80 coverage in 12/18 slices. However,
  P10+P90 pinball worsened in 8/18 slices and improved in only 5/18.
- Median-bias plus width scaling increased P80 coverage in 13/18 slices, but
  tail pinball worsened in 10/18 and improved in 6/18.
- Dense coverage improved on average, but tail pinball rose about 12% and
  mean interval width rose about 76% under width scaling. This is a substantial
  sharpness penalty, not a free calibration improvement.
- Intermittent results are the most promising: bias+width reached 0.800 mean
  P80 coverage versus 0.639 baseline, with a small reduction in mean tail
  pinball. But mean interval width increased about 62%, and each slice has only
  30 holdout observations.
- Very-intermittent coverage was already near nominal. Scaling increased width
  and tail pinball without a meaningful coverage need.

### Decision

**Do not enable a global scale or bias correction by default.** The holdout
shows a coverage/sharpness trade-off, not a uniformly superior calibration
method. Intermittent-specific scaling is a candidate for a larger follow-up,
but this sample is too small to promote it. The holdout is chronological and
purged within the same retailer/SKU sample; it is not an independent dataset.
The three non-overlapping holdout origins per SKU are insufficient for strong
significance claims, and common retailer-wide shocks can still correlate SKUs.
No inventory-policy savings or production-readiness claim follows from this
experiment.

## Real-data run: 2026-11-22

The first run on commit `da76574...` used full-history cohort assignment and is
superseded. After freezing cohorts to the initial training window, the corrected
workflow completed successfully on commit
`d25e8fd680cd2df212b4678fcee350f9adcb96d6`:

- [GitHub Actions run #45038895069](https://github.com/mojtaba-arvin/demand-forecast-kit/actions/runs/45038895069)
- [JSON artifact](https://github.com/mojtaba-arvin/demand-forecast-kit/actions/runs/45036995061/artifacts/14759959986)
- Official UCI workbook extracted by the runner: 23,715,344 bytes.
- Source workbook SHA-256: `43465a06f2ccf7c8b5bd2892bc7defb52f97487934fe93b16ae4c3936424676d`.
- Panel: 374 calendar days (2010-12-01 through 2011-12-09), 30 selected SKUs
  (10 per cohort), 16 rolling origins per SKU/model/lead-time evaluation.
- Evaluations: 180 (30 SKUs × 3 models × 2 lead times); none skipped.

Macro-average results (lower pinball loss is better; P80 interval coverage has
an 0.80 nominal target):

| Cohort | Lead days | Model | P50 pinball | P80 coverage | P10 pinball | P90 pinball |
|---|---:|---|---:|---:|---:|---:|
| Dense | 7 | Croston SBA | 33.612 | 0.656 | 14.869 | 26.341 |
| Dense | 7 | Seasonal Naive | 43.622 | 0.500 | 33.598 | 27.632 |
| Dense | 7 | TSB | 35.771 | 0.688 | 17.755 | 25.873 |
| Dense | 14 | Croston SBA | 57.057 | 0.625 | 25.729 | 47.891 |
| Dense | 14 | Seasonal Naive | 77.673 | 0.469 | 62.238 | 49.418 |
| Dense | 14 | TSB | 58.914 | 0.600 | 29.318 | 46.113 |
| Intermittent | 7 | Croston SBA | 37.506 | 0.669 | 14.087 | 34.261 |
| Intermittent | 7 | Seasonal Naive | 44.594 | 0.544 | 34.446 | 35.617 |
| Intermittent | 7 | TSB | 39.245 | 0.588 | 20.972 | 36.063 |
| Intermittent | 14 | Croston SBA | 70.714 | 0.631 | 25.352 | 61.296 |
| Intermittent | 14 | Seasonal Naive | 86.912 | 0.544 | 66.895 | 58.797 |
| Intermittent | 14 | TSB | 75.103 | 0.575 | 40.338 | 58.399 |
| Very intermittent | 7 | Croston SBA | 1.996 | 0.819 | 0.659 | 1.607 |
| Very intermittent | 7 | Seasonal Naive | 2.117 | 0.775 | 2.075 | 1.448 |
| Very intermittent | 7 | TSB | 1.766 | 0.725 | 1.074 | 1.383 |
| Very intermittent | 14 | Croston SBA | 3.900 | 0.775 | 1.253 | 2.115 |
| Very intermittent | 14 | Seasonal Naive | 4.967 | 0.750 | 4.178 | 2.575 |
| Very intermittent | 14 | TSB | 3.592 | 0.750 | 2.332 | 2.232 |

### Findings

- Croston SBA has the lowest P50 pinball loss in all four dense and
  intermittent cohort/lead-time slices. TSB has the lowest P50 loss in both
  very-intermittent slices; no single model wins every cohort.
- P80 interval coverage remains below its 0.80 target for dense and
  intermittent SKUs (0.469–0.688 and 0.544–0.669 respectively). These intervals
  should not be treated as calibrated inventory protection bounds.
- Very-intermittent coverage is closer to nominal: Croston SBA reaches 0.819
  at seven days and 0.775 at fourteen days. Other model/lead-time combinations
  range from 0.725 to 0.775.
- These are descriptive results for one deterministic 30-SKU sample, not proof
  of universal model superiority. Per-SKU outcomes vary; see the full artifact.

## Interpretation limits

This is a single retailer's 2010–2011 history, not a representative global
benchmark. Removing returns defines a gross-demand target and can change the
interpretation relative to net sales. The deterministic cohort sample is
small by design. Results must not be presented as universal forecast accuracy,
inventory savings, or causal business impact. Compare models only on identical
SKUs, origins, lead times, and preprocessing. The reported metrics are empirical
results from the exact source workbook identified by its SHA-256 above.


## Model comparison scope

The Online Retail lead-time benchmark evaluates Seasonal Naive, Croston SBA, and TSB on
all frozen activity cohorts. LightGBM quantile regression is additionally evaluated on
the dense cohort only: the adapter explicitly rejects histories above its configured
intermittent-zero threshold, while Croston and TSB remain the appropriate statistical
comparators for sparse demand. All included adapters use the same daily panel, initial
training window, 14-day horizon, 7-day origin step, quantile levels, and rolling-origin
split generator. Compare pinball loss and quantile coverage within the same cohort and
lead time; do not compare LightGBM's dense-only results with macro-averages spanning
all three cohorts.


## Initial dense-cohort model comparison (2026-11-24)

The first CI run with LightGBM enabled evaluated 10 deterministically selected dense SKUs,
with 16 eligible rolling-origin observations per SKU at each lead time. The same 180-day
initial window, 14-day horizon, 7-day origin step, and quantile levels were used for all
four models. Values below are equal-SKU macro summaries from that run.

| Lead time | Model | Median pinball loss | P80 interval coverage |
|---:|---|---:|---:|
| 7 days | LightGBM quantile | 30.33 | 64.38% |
| 7 days | Croston SBA | 33.61 | 65.63% |
| 7 days | TSB | 35.77 | 68.75% |
| 7 days | Seasonal Naive | 43.62 | 50.00% |
| 14 days | LightGBM quantile | 51.45 | 63.75% |
| 14 days | Croston SBA | 57.06 | 62.50% |
| 14 days | TSB | 58.91 | 60.00% |
| 14 days | Seasonal Naive | 77.67 | 46.88% |

LightGBM had the lowest median pinball loss in this dense-cohort sample at both lead
times. This is a preliminary, domain-specific comparison, not evidence of universal
model superiority. In particular, its nominal 80% interval coverage was only 64.38%
and 63.75%; the quantile intervals are under-covering and must not be treated as
calibrated inventory-risk bounds. The calibration/holdout experiment remains necessary
before using these forecasts for service-level decisions. The run is recorded at
[GitHub Actions run 45374212843](https://github.com/mojtaba-arvin/demand-forecast-kit/actions/runs/45374212843).
