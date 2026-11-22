# Demand Forecast Kit

**Probabilistic demand forecasting and inventory replenishment primitives for Python.**

Demand Forecast Kit is an open-source library and API for turning sales and inventory history into demand distributions and replenishment recommendations. It is designed for small and medium-sized businesses, product developers, and researchers who need a reproducible forecasting workflow without operating a distributed data platform.

> **Project status: early development.** The package includes canonical input validation, a model-adapter contract, a deterministic seasonal-naive reference adapter, optional statistical forecasting adapters, a newsvendor decision primitive, and a rolling-origin evaluation engine. It is not yet an end-to-end production forecasting service. Performance and accuracy targets in the engineering brief have not been measured.

## Design principles

- **Probabilistic by default:** forecasts expose ordered quantiles rather than only a point estimate.
- **Country agnostic:** calendars and holiday logic belong in optional community extensions.
- **Reproducible:** seeds, model versions, and dataset fingerprints are explicit orchestration inputs; a persistent run ledger is planned.
- **Model agnostic:** forecasting implementations sit behind a stable adapter protocol.
- **Single-machine first:** CPU execution is the baseline; native acceleration is added only after profiling demonstrates a bottleneck.
- **License aware:** optional model weights and evaluation datasets must be reviewed before distribution.

## Current capabilities

- Scan CSV and Parquet input through Polars lazy frames.
- Validate required series, timestamp, and non-negative finite demand fields.
- Represent horizon-aligned, monotone quantile forecasts.
- Run a deterministic seasonal-naive reference adapter without scientific-model dependencies.
- Run optional StatsForecast-backed AutoETS, AutoARIMA, and Theta adapters for dense demand.
- Run CrostonClassic, CrostonOptimized, CrostonSBA, and TSB adapters for intermittent demand, with conformal prediction intervals.
- Convert a supplied lead-time demand quantile curve and inventory position into a pack-size-aware newsvendor order quantity.
- Generate deterministic synthetic daily demand for tests and examples.
- Run chronological rolling-origin backtests across multiple adapters and demand series.
- Report MASE, normalized WQL, per-quantile pinball loss, and central interval coverage.
- Write deterministic JSON evaluation artifacts with a SHA-256 dataset fingerprint and artifact digest.

Not implemented yet: automatic model routing, foundation-model adapters, conformal calibration outside the intermittent-model interval backend, hierarchical reconciliation, a persistent run registry, FastAPI endpoints, CLI commands, Rust extensions, and benchmark claims.

## Statistical adapters

The core install still requires only Polars. Install the optional statistical backend when you need the model adapters:

```bash
python -m pip install "demand-forecast-kit[stats]"
```

The adapters use [Nixtla StatsForecast](https://nixtlaverse.nixtla.io/statsforecast/src/core/models.html). AutoETS, AutoARIMA, and Theta use their native prediction intervals. Croston and TSB use StatsForecast conformal intervals fitted only on the training history. The package imports this backend lazily and raises an actionable installation message when the `stats` extra is missing.

Example:

```python
from demand_forecast_kit.backtesting import BacktestConfig, run_backtest
from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter
from demand_forecast_kit.models.statistical import AutoETSAdapter, ThetaAdapter
from demand_forecast_kit.data import scan_history

history = scan_history("sales.parquet")
report = run_backtest(
    history,
    [
        SeasonalNaiveAdapter(season_length=7),
        AutoETSAdapter(season_length=7),
        ThetaAdapter(season_length=7, decomposition_type="additive"),
    ],
    BacktestConfig(initial_train_size=56, horizon=14, step=7, season_length=7),
)
print(report.model_summaries)
```

StatsForecast interval bounds are mapped to marginal quantiles; negative lower bounds are clipped to zero. These forecasts do not encode dependence between future periods and must not be summed to obtain cumulative lead-time demand quantiles. Validate coverage and decision cost on the target dataset before operational use.

## Input contract

| Column | Required | Meaning |
| --- | --- | --- |
| series_id | yes | Stable identifier for a SKU/location series |
| timestamp | yes | Observation timestamp |
| demand | yes | Observed non-negative demand |
| inventory | no | Available inventory at the observation time |
| unit_price | no | Observed selling price |
| promotion | no | Promotion indicator or feature |

The first implementation validates the three required columns and normalizes them to series_id, timestamp, and demand. Inventory and external covariates are intentionally not interpreted yet. Duplicate series/timestamp keys, null required values, invalid timestamps, non-finite demand, negative demand, and blank series identifiers are reported as data-quality issues.

## Quick start

Python 3.13 or newer is required.

```bash
python -m pip install ".[dev]"
```

## Metric definitions

- **MASE:** mean absolute median-forecast error divided by the in-sample seasonal-naive scale. Undefined scales are reported as null.
- **WQL:** 2 × sum(pinball losses across requested quantiles and observations) / sum(abs(actual demand)). Undefined zero-demand denominators are reported as null.
- **Pinball loss:** reported separately for each requested quantile.
- **Coverage:** empirical inclusion rate for symmetric central intervals. Defaults are P10-P90 (80%) and P05-P95 (90%).

Model summaries are macro-averages over series/folds, not volume-weighted pooled metrics. Only compare results with matching dataset fingerprints, split configurations, quantile levels, and seeds. The seasonal-naive adapter's marginal quantiles are not a joint path or cumulative lead-time distribution. The same restriction applies to the marginal quantiles returned by the statistical adapters.

## Development

```bash
python -m pip install -e ".[dev]"
ruff check .
ruff format --check .
pyright
pytest
```

The core test suite does not require the optional StatsForecast extra. Its model-integration suite runs in a separate CI job with the `stats` extra installed. CI does not download evaluation datasets or model weights. Dependency installation uses the package index; external evaluation data and pretrained weights are outside the automated test workflow.

## Repository map

- src/demand_forecast_kit/: installable Python package.
- adapters/: model-adapter policies and future external integrations.
- calendars/: country- and domain-specific calendar extension guidance.
- bench/: performance measurement methodology; no targets are claimed as achieved.
- datasets/: dataset provenance policy and lock file; no raw datasets.
- docs/adr/: architectural decision records.
- docs/specs/: executable work specifications.
- evals/: evaluation methodology and leakage controls.
- rust/: reserved for profiled hot paths; no Rust code is shipped yet.
- tests/: deterministic offline test suite and optional-backend integration tests.

## License

The repository currently contains an MIT license. The project brief leaves MIT versus Apache-2.0 open; that decision is recorded as unresolved in ADR 0001. Do not assume this README settles a future license change.
