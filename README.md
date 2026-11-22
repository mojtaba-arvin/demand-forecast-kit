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
- Select a model independently for each SKU from historical rolling-origin evidence, with a strict forecast-origin cutoff, model-version checks, minimum evidence folds, and an explicit Seasonal Naive fallback.
- Write auditable, deterministic routing decision artifacts.
- Calibrate cumulative lead-time demand from same-series, same-model out-of-sample residual paths, with strict forecast-origin filtering and prequential coverage diagnostics.\n- Evaluate replenishment policies against realized cumulative lead-time demand, reporting shortage/holding costs, unit fill rate, and cycle service level.
- Run an opt-in real-data benchmark on UCI Online Retail across dense, intermittent, and very-intermittent SKU cohorts.

## Empirical lead-time calibration benchmark

Phase 7 adds an opt-in benchmark using the [UCI Online Retail dataset](https://archive.ics.uci.edu/dataset/352/online-retail) (Daqing Chen, 2015; DOI [10.24432/C5BW33](https://doi.org/10.24432/C5BW33), CC BY 4.0). The raw workbook is not committed and CI does not download it.

Install the optional dependencies and download `Online Retail.xlsx` from UCI:

```bash
python -m pip install -e ".[benchmark,dev]"
python evals/run_uci_online_retail_benchmark.py "/path/to/Online Retail.xlsx"
```

The runner constructs complete daily SKU histories, excludes cancellation invoices and non-positive quantities (returns), samples deterministic dense/intermittent/very-intermittent cohorts, and compares Seasonal Naive, Croston SBA, and TSB with prequential lead-time calibration for 7- and 14-day lead times. It writes a provenance-rich JSON report under `artifacts/`. See [the benchmark protocol](docs/benchmarks/uci-online-retail.md) for preprocessing, evaluation settings, and interpretation limits. The benchmark is opt-in and has not been run by CI.

Not implemented yet: online model learning, automatic retraining, foundation-model adapters, conformal calibration outside the intermittent-model interval backend, hierarchical reconciliation, a persistent run registry, FastAPI endpoints, CLI commands, Rust extensions, and benchmark claims.

## Statistical adapters

The core install still requires only Polars. Install the optional statistical backend when you need the model adapters:

```bash
python -m pip install -e ".[stats]"
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

## Per-series model routing

Use a historical backtest report to select a model independently for each SKU. The report records the observed start/end timestamps for every series. Routing rejects a report unless the target series' complete history ends strictly before the forecast origin.

```python
from datetime import date

from demand_forecast_kit.backtesting import BacktestConfig, run_backtest
from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter
from demand_forecast_kit.models.statistical import AutoETSAdapter, ThetaAdapter
from demand_forecast_kit.routing import ModelRouter

adapters = [
    SeasonalNaiveAdapter(season_length=7),
    AutoETSAdapter(season_length=7),
    ThetaAdapter(season_length=7, decomposition_type="additive"),
]
report = run_backtest(
    history,
    adapters,
    BacktestConfig(initial_train_size=56, horizon=14, step=7, season_length=7),
)
router = ModelRouter(adapters, metric="wql", min_folds=3)
decision = router.select(
    report,
    series_id="sku-123",
    forecast_origin=date(2026, 1, 1),
)
selected_adapter = next(
    adapter for adapter in adapters if adapter.model_id == decision.chosen_model_id
)
```

Routing defaults to WQL; MASE and mean pinball loss are supported as explicit alternatives. Undefined metrics and candidates with fewer than the configured number of defined historical folds are excluded. Evidence must match the currently registered adapter version. Ties within a configurable tolerance prefer the Seasonal Naive fallback. When no candidate has enough evidence, the fallback is returned with `used_fallback=True` and a null score.

The caller must pass only observations available at the selected forecast origin when invoking the chosen adapter. Routing is a reproducible selector, not an automatic trainer or a guarantee of future model superiority.

## Inventory policy evaluation

Evaluate a replenishment policy using an independently validated quantile curve for cumulative demand over the full replenishment lead time. The evaluator deliberately does not sum daily marginal quantiles: the current forecast contract does not encode cross-period dependence.

```python
from demand_forecast_kit.inventory import InventoryScenario, evaluate_inventory_policy

report = evaluate_inventory_policy(
    [
        InventoryScenario(
            scenario_id="origin-001",
            lead_time_demand_quantiles={0.1: 8.0, 0.5: 12.0, 0.9: 18.0},
            realized_lead_time_demand=15.0,
            inventory_position=4.0,
        )
    ],
    underage_cost=9.0,
    overage_cost=1.0,
    holding_cost_per_unit=0.5,
    shortage_cost_per_unit=4.0,
    pack_size=2,
)
print(report.fill_rate, report.cycle_service_level, report.total_cost)
```

Inventory position means on-hand plus confirmed inbound stock minus backorders. The current evaluation assumes no intra-lead-time replenishment or salvage value. Holding/shortage costs are computed from realized ending inventory and unmet demand; the underage/overage ratio selects the target quantile. See SPEC 0004 and ADR 0007 for the complete assumptions. The synthetic CI report verifies calculation plumbing only, not forecast quality or business savings.

## Lead-time demand calibration

Build a cumulative lead-time distribution from rolling-origin out-of-sample residual trajectories. The calibration routine requires a caller-supplied median daily baseline for the target lead time and only admits completed historical folds for the same SKU and model.

```python
from datetime import date

from demand_forecast_kit.lead_time import (
    calibrate_lead_time_demand,
    to_inventory_scenario,
)

distribution = calibrate_lead_time_demand(
    report,
    series_id="sku-123",
    model_id="seasonal-naive",
    forecast_origin=date(2026, 1, 1),
    baseline_median=target_median_forecast[:14],
    expected_model_version=selected_adapter.model_version,
    lead_time=14,
    quantile_levels=(0.1, 0.5, 0.9),
    min_calibration_paths=5,
    seed=42,
)
scenario = to_inventory_scenario(
    distribution,
    scenario_id="sku-123-2026-01-01",
    realized_lead_time_demand=175.0,
    inventory_position=40.0,
)
```

The bootstrap resamples complete residual paths rather than individual daily errors, retaining within-horizon temporal dependence. Overlapping backtest windows are excluded, and every calibration window must end strictly before the target forecast origin. `backtest_lead_time_calibration` performs a prequential diagnostic: each later fold is calibrated only from earlier completed folds and reports cumulative quantile coverage and pinball loss. The method assumes historical residual paths remain representative; it does not guarantee calibration under regime shifts. See SPEC 0005 and ADR 0008. Synthetic CI output validates implementation plumbing only, not forecast accuracy or business savings.

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
