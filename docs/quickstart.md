# Quick start

Demand Forecast Kit requires Python 3.13 or newer.

## Install

```bash
python -m pip install "demand-forecast-kit[dev]"
```

For a local checkout:

```bash
python -m pip install -e ".[dev]"
```

## Validate a history file

A CSV or Parquet input must contain `series_id`, `timestamp`, and `demand`.
Demand must be finite and non-negative. Timestamps must be normalized to one
timezone before entering the canonical contract.

```python
from demand_forecast_kit.data import scan_history, validate_history

history = scan_history("sales.parquet")
quality = validate_history(history)
if not quality.is_valid:
    raise ValueError("; ".join(quality.issues))
```

## Run a chronological backtest

```python
from demand_forecast_kit.backtesting import BacktestConfig, run_backtest
from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter

report = run_backtest(
    history,
    [SeasonalNaiveAdapter(season_length=7)],
    BacktestConfig(initial_train_size=56, horizon=14, step=7, season_length=7),
)
print(report.model_summaries)
```

## Generate a replenishment recommendation

The quantiles supplied to the decision layer must represent cumulative demand
over the full lead time. Do not sum marginal daily quantiles.

```python
from demand_forecast_kit.decisions import newsvendor_order

recommendation = newsvendor_order(
    {0.1: 8.0, 0.5: 12.0, 0.9: 18.0},
    underage_cost=9.0,
    overage_cost=1.0,
    inventory_position=4.0,
    pack_size=2,
)
print(recommendation.quantity)
```

## Optional integrations

- `.[stats]`: StatsForecast adapters.
- `.[io]`: DuckDB and PyArrow integration dependencies.
- `.[benchmark]`: UCI Online Retail workbook support.
- `.[api]`: FastAPI runtime (API workstream).

Optional dependencies are not installed by the core package. Install only the
extras required by the selected workflow.
