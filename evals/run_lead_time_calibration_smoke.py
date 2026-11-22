# SPDX-FileCopyrightText: 2026 Mojtaba Arvin
# SPDX-License-Identifier: MIT
"""Run a deterministic synthetic lead-time calibration and inventory smoke."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from demand_forecast_kit.backtesting import BacktestConfig, run_backtest
from demand_forecast_kit.inventory import evaluate_inventory_policy
from demand_forecast_kit.lead_time import (
    backtest_lead_time_calibration,
    calibrate_lead_time_demand,
    to_inventory_scenario,
)
from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter


def main() -> None:
    start = date(2024, 1, 1)
    rows = [
        {
            "series_id": "synthetic-sku",
            "timestamp": start + timedelta(days=day),
            "demand": float(12 + day % 7 + (day % 11 == 0) * 3),
        }
        for day in range(84)
    ]
    report = run_backtest(
        pl.DataFrame(rows),
        [SeasonalNaiveAdapter(season_length=7)],
        BacktestConfig(
            initial_train_size=28,
            horizon=7,
            step=7,
            season_length=7,
        ),
    )
    target = report.evaluations[-1]
    origin = date(2024, 3, 26)
    distribution = calibrate_lead_time_demand(
        report,
        series_id="synthetic-sku",
        model_id="seasonal-naive",
        forecast_origin=origin,
        baseline_median=target.quantile_forecasts[0.5],
        lead_time=7,
        quantile_levels=(0.1, 0.5, 0.9),
        bootstrap_samples=1000,
        min_calibration_paths=5,
        seed=42,
    )
    calibration = backtest_lead_time_calibration(
        report,
        series_id="synthetic-sku",
        model_id="seasonal-naive",
        lead_time=7,
        quantile_levels=(0.1, 0.5, 0.9),
        bootstrap_samples=500,
        min_calibration_paths=5,
        seed=42,
    )
    scenario = to_inventory_scenario(
        distribution,
        scenario_id="synthetic-sku-2024-03-26",
        realized_lead_time_demand=91.0,
        inventory_position=30.0,
    )
    inventory = evaluate_inventory_policy(
        [scenario],
        underage_cost=9.0,
        overage_cost=1.0,
        holding_cost_per_unit=0.5,
        shortage_cost_per_unit=4.0,
    )
    payload = {
        "schema_version": 1,
        "provenance": "synthetic-calibration-plumbing-only",
        "series_id": distribution.series_id,
        "model_id": distribution.model_id,
        "forecast_origin": distribution.forecast_origin,
        "lead_time": distribution.lead_time,
        "calibration_path_count": distribution.calibration_path_count,
        "bootstrap_sample_count": distribution.bootstrap_sample_count,
        "cumulative_demand_quantiles": {
            str(level): value for level, value in distribution.quantiles.items()
        },
        "prequential_backtest": {
            "origin_count": calibration.origin_count,
            "quantile_coverage": {
                str(level): value for level, value in calibration.quantile_coverage.items()
            },
            "mean_pinball_loss": {
                str(level): value for level, value in calibration.mean_pinball_loss.items()
            },
        },
        "inventory_policy": {
            "total_cost": inventory.total_cost,
            "fill_rate": inventory.fill_rate,
            "cycle_service_level": inventory.cycle_service_level,
        },
    }
    destination = Path("artifacts/synthetic-lead-time-calibration.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
