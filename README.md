# Demand Forecast Kit

**Probabilistic demand forecasting and inventory replenishment primitives for Python.**

Demand Forecast Kit is an open-source library and API for turning sales and inventory history into demand distributions and replenishment recommendations. It is designed for small and medium-sized businesses, product developers, and researchers who need a reproducible forecasting workflow without operating a distributed data platform.

> **Project status: early development.** The current code is a deliberately small foundation: canonical input validation, a model-adapter contract, a deterministic seasonal-naive reference adapter, and a newsvendor decision primitive. It is not yet an end-to-end production forecasting service. Performance targets in the engineering brief have not been measured.

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
- Run a deterministic seasonal-naive reference adapter.
- Convert a supplied lead-time demand quantile curve and inventory position into a pack-size-aware newsvendor order quantity.
- Generate deterministic synthetic daily demand for tests and examples.

Not implemented yet: automatic model routing, AutoETS/ARIMA/Theta/Croston adapters, foundation-model adapters, conformal calibration, hierarchical reconciliation, a persistent run registry, FastAPI endpoints, CLI commands, Rust extensions, and benchmark claims.

## Input contract

| Column | Required | Meaning |
| --- | --- | --- |
| `series_id` | yes | Stable identifier for a SKU/location series |
| `timestamp` | yes | Observation timestamp |
| `demand` | yes | Observed non-negative demand |
| `inventory` | no | Available inventory at the observation time |
| `unit_price` | no | Observed selling price |
| `promotion` | no | Promotion indicator or feature |

The first implementation validates the three required columns and normalizes them to `series_id`, `timestamp`, and `demand`. Inventory and external covariates are intentionally not interpreted yet. Duplicate series/timestamp keys, null required values, invalid timestamps, non-finite demand, negative demand, and blank series identifiers are reported as data-quality issues.

## Quick start

Python 3.13 or newer is required.

```bash
python -m pip install ".[dev]"
```

```python
from demand_forecast_kit.decisions import newsvendor_order
from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter

adapter = SeasonalNaiveAdapter(season_length=7)
forecast = adapter.predict(
    "sku-001",
    [12, 14, 13, 17, 21, 24, 19] * 8,
    horizon=7,
    quantile_levels=(0.1, 0.5, 0.9),
    seed=42,
)

# Each tuple contains one quantile value per forecast step.
p50_by_step = forecast.quantiles[0.5]

# This curve must describe cumulative demand over the replenishment lead time.
# Inventory position = on-hand + on-order - backorders.
recommendation = newsvendor_order(
    {0.1: 8.0, 0.5: 12.0, 0.9: 18.0},
    underage_cost=9.0,
    overage_cost=1.0,
    inventory_position=10.0,
    pack_size=2,
)
print(p50_by_step, recommendation.quantity)
```

The seasonal-naive adapter returns *marginal* quantiles by horizon step. It does not estimate a joint path distribution or cumulative lead-time distribution. Do not sum marginal quantiles and pass the result to the newsvendor function.

## Development

```bash
python -m pip install -e ".[dev]"
ruff check .
ruff format --check .
pyright
pytest
```

CI runs offline with respect to datasets: tests use generated fixtures and do not download evaluation data. Dependency installation still uses the package index. Dataset acquisition and model-weight downloads are separate, opt-in evaluation workflows and must be recorded in `datasets/DATASETS.lock` or the model registry before use.

## Repository map

- `src/demand_forecast_kit/`: installable Python package.
- `adapters/`: model-adapter policies and future external integrations.
- `calendars/`: country- and domain-specific calendar extension guidance.
- `bench/`: performance measurement methodology; no targets are claimed as achieved.
- `datasets/`: dataset provenance policy and lock file; no raw datasets.
- `docs/adr/`: architectural decision records.
- `docs/specs/`: executable work specifications.
- `evals/`: evaluation methodology and leakage controls.
- `rust/`: reserved for profiled hot paths; no Rust code is shipped yet.
- `tests/`: deterministic offline test suite.

## License

The repository currently contains an MIT license. The project brief leaves MIT versus Apache-2.0 open; that decision is recorded as unresolved in [ADR 0001](docs/adr/0001-project-identity-and-license.md). Do not assume this README settles a future license change.
