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

## Real-data run: 2026-11-22

The dedicated workflow completed successfully on commit
`da76574a901e72a31caba96d60c53a53cca57b86`:

- [GitHub Actions run #45036995061](https://github.com/mojtaba-arvin/demand-forecast-kit/actions/runs/45036995061)
- [JSON artifact](https://github.com/mojtaba-arvin/demand-forecast-kit/actions/runs/45036995061/artifacts/14760177282)
- Official UCI workbook extracted by the runner: 23,715,344 bytes.
- Source workbook SHA-256: `43465a06f2ccf7c8b5bd2892bc7defb52f97487934fe93b16ae4c3936424676d`.
- Panel: 374 calendar days (2010-12-01 through 2011-12-09), 30 selected SKUs
  (10 per cohort), 16 rolling origins per SKU/model/lead-time evaluation.
- Evaluations: 180 (30 SKUs × 3 models × 2 lead times); none skipped.

Macro-average results (lower pinball loss is better; P80 interval coverage has
an 0.80 nominal target):

| Cohort | Lead days | Model | P50 pinball | P80 coverage | P10 pinball | P90 pinball |
|---|---:|---|---:|---:|---:|---:|
| Dense | 7 | Croston SBA | 36.962 | 0.600 | 16.189 | 27.227 |
| Dense | 7 | Seasonal Naive | 44.450 | 0.494 | 29.716 | 26.994 |
| Dense | 7 | TSB | 37.143 | 0.681 | 16.008 | 26.443 |
| Dense | 14 | Croston SBA | 64.994 | 0.594 | 28.858 | 51.367 |
| Dense | 14 | Seasonal Naive | 82.753 | 0.469 | 57.749 | 52.398 |
| Dense | 14 | TSB | 66.170 | 0.594 | 28.919 | 51.007 |
| Intermittent | 7 | Croston SBA | 24.417 | 0.613 | 9.917 | 26.972 |
| Intermittent | 7 | Seasonal Naive | 31.041 | 0.506 | 27.151 | 26.902 |
| Intermittent | 7 | TSB | 25.595 | 0.544 | 16.069 | 27.083 |
| Intermittent | 14 | Croston SBA | 42.315 | 0.600 | 16.232 | 43.633 |
| Intermittent | 14 | Seasonal Naive | 60.366 | 0.512 | 53.660 | 43.980 |
| Intermittent | 14 | TSB | 45.323 | 0.531 | 30.082 | 40.896 |
| Very intermittent | 7 | Croston SBA | 1.487 | 0.800 | 0.366 | 2.742 |
| Very intermittent | 7 | Seasonal Naive | 2.594 | 0.756 | 2.484 | 2.892 |
| Very intermittent | 7 | TSB | 1.884 | 0.775 | 0.979 | 2.692 |
| Very intermittent | 14 | Croston SBA | 2.884 | 0.738 | 0.732 | 4.679 |
| Very intermittent | 14 | Seasonal Naive | 4.358 | 0.713 | 4.236 | 4.363 |
| Very intermittent | 14 | TSB | 3.354 | 0.750 | 1.916 | 4.411 |

### Findings

- Croston SBA has the lowest P50 pinball loss in all six cohort/lead-time
  slices. Seasonal Naive is consistently weakest on P50 loss in this sample.
- P80 interval coverage is materially below its 0.80 target for dense and
  intermittent SKUs (roughly 0.47–0.68 and 0.51–0.61 respectively). The
  intervals are therefore under-covering in these cohorts and should not be
  treated as calibrated inventory protection bounds.
- Very-intermittent SKUs are closer to the nominal interval target: Croston
  SBA reaches 0.800 at seven days, while coverage is 0.713–0.756 for the
  14-day horizon.
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
