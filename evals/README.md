# Evaluation

Evaluation is separate from unit tests and model training. The repository contains deterministic synthetic smoke evaluations plus opt-in third-party dataset benchmarks. The latter download source data only in dedicated workflows; raw third-party datasets and model weights are not committed or fetched by regular quality CI.

## Rolling-origin evaluation

Run the deterministic baseline smoke evaluation locally with:

```bash
python evals/run_synthetic_smoke.py
```

It creates `artifacts/synthetic-baseline-evaluation.json`. GitHub Actions uploads the same generated report as the `synthetic-evaluation-report` artifact. It is a pipeline smoke artifact, not a benchmark result or a claim of forecasting quality.

## Statistical-adapter comparison

Install the optional StatsForecast dependency and run the dense/intermittent adapter comparison:

```bash
python -m pip install -e ".[stats]"
python evals/run_statistical_smoke.py
```

The command compares the seasonal-naive reference against AutoETS, AutoARIMA, and Theta on one deterministic dense synthetic series, then compares the baseline against CrostonOptimized and TSB on a deterministic intermittent synthetic series. It writes separate JSON reports under `artifacts/`. CI uploads both reports as the `statistical-adapter-evaluation` artifact.

These synthetic comparisons verify adapter execution, rolling-origin integration, and artifact serialization only. They are not evidence that one model is more accurate than another and must not be presented as benchmark performance.

Use `demand_forecast_kit.backtesting.run_backtest` for user datasets and compare models only with matching dataset fingerprints, split settings, quantile levels, and seeds.

## Independent real-data benchmarks

### UCI Electricity Load Diagrams 2011–2014

This benchmark evaluates daily energy demand across up to 370 independent client series using Seasonal Naive, AutoETS, and Theta. It downloads the official UCI archive in a dedicated GitHub Actions workflow and records the source-file SHA-256, selected series IDs, preprocessing summary, runtime versions, and rolling-origin metrics in its artifact.

Run locally after extracting `LD2011_2014.txt`:

```bash
python -m pip install -e ".[benchmark,dev]"
python evals/run_uci_electricity_benchmark.py LD2011_2014.txt \
  --max-series 370 \
  --output artifacts/uci-electricity-benchmark.json
```

This is cross-domain evidence for dense multi-series forecasting and data handling. Electricity consumption is not retail SKU sales, so it cannot validate intermittent retail performance, inventory costs, or replenishment service levels. See [the benchmark protocol](../docs/benchmarks/uci-electricity-load.md).

### UCI Online Retail

The UCI Online Retail workflow evaluates dense, intermittent, and very-intermittent SKU cohorts with prequential cumulative lead-time calibration. It is the retail-specific evidence source; see [the benchmark protocol](../docs/benchmarks/uci-online-retail.md).

## Per-series model routing

Run the deterministic model-routing smoke locally with:

```bash
python evals/run_routing_smoke.py
```

It creates `artifacts/synthetic-model-routing.json`. GitHub Actions uploads the same report as the `synthetic-model-routing-report` artifact. The script demonstrates per-series WQL selection, minimum evidence folds, explicit forecast-origin cutoffs, and deterministic routing artifact output. It is a pipeline smoke test, not proof of model superiority.

A routing report must end strictly before the forecast origin for the target series. Rebuild evaluation evidence whenever the forecast origin advances beyond the report's observed history. The caller remains responsible for passing only pre-origin observations to the selected adapter.

## Metrics and interpretation

- MASE is the median-forecast MAE divided by the in-sample seasonal-naive scale. A zero or unavailable scale is undefined (null).
- WQL is twice the sum of pinball losses across the requested quantiles and observations divided by total absolute actual demand. A zero denominator is undefined (null).
- Pinball loss is reported per quantile.
- Central interval coverage is reported for symmetric quantile pairs (default 80% and 90%).
- Model summaries macro-average series/folds; they are not volume-weighted pooled metrics.

Future evaluations should report these metrics by dataset, horizon, and series segment, plus inventory decision cost under documented lead-time and cost assumptions. Record data provenance in datasets/DATASETS.lock. Do not compare results across different splits, frequencies, quantile sets, or leakage policies as if they were equivalent.

## Dataset leakage

Do not bundle external evaluation or training datasets until source terms, content hash, retrieval date, and intended use have been verified and locked. Report cold-start/post-release datasets separately when foundation-model pretraining overlap is plausible.
