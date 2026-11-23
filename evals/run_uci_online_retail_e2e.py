# SPDX-FileCopyrightText: 2026 Mojtaba Arvin
# SPDX-License-Identifier: MIT
"""Run a real-demand UCI Online Retail forecast-to-inventory decision pipeline."""

from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path

import polars as pl

from demand_forecast_kit.artifacts import FileArtifactStore
from demand_forecast_kit.backtesting import BacktestConfig, run_backtest
from demand_forecast_kit.lead_time import calibrate_lead_time_demand, to_inventory_scenario
from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter
from demand_forecast_kit.policy_comparison import InventoryPolicy, compare_inventory_policies
from demand_forecast_kit.registry import SQLiteRunRegistry
from demand_forecast_kit.retail_benchmark import (
    build_cohort_panel,
    prepare_daily_demand,
    sha256_file,
)
from demand_forecast_kit.simulation import InventorySimulationConfig, simulate_inventory_policy

DATASET_DOI = "https://doi.org/10.24432/C5BW33"


def run_real_data_e2e(
    workbook: Path,
    output: Path,
    *,
    forecast_origin_offset_days: int = 300,
) -> dict[str, object]:
    """Use actual UCI sales for forecasting and demand outcomes.

    Inventory position, costs, and supplier lead time are explicit scenario
    assumptions because the public retail workbook does not contain stock or
    supplier receipt records.
    """
    if type(forecast_origin_offset_days) is not int or forecast_origin_offset_days < 60:
        raise ValueError("forecast_origin_offset_days must be an integer >= 60")
    if not workbook.is_file():
        raise FileNotFoundError(workbook)

    transactions = pl.read_excel(workbook)
    daily = prepare_daily_demand(transactions)
    panel, cohort_counts = build_cohort_panel(
        daily,
        max_skus_per_cohort=10,
        cohort_window_days=180,
    )
    dense_ids = (
        panel.filter(pl.col("cohort") == "dense")
        .select("series_id")
        .unique()
        .sort("series_id")
        .get_column("series_id")
        .to_list()
    )
    if not dense_ids:
        raise RuntimeError("UCI dataset produced no dense SKU cohort for the end-to-end run")

    series_id = str(dense_ids[0])
    series = panel.filter(pl.col("series_id") == series_id).sort("timestamp")
    first_day = series.get_column("timestamp").min()
    if first_day is None:
        raise RuntimeError("selected UCI SKU has no observations")
    forecast_origin = first_day + timedelta(days=forecast_origin_offset_days)
    holdout_end = forecast_origin + timedelta(days=7)
    history = series.filter(pl.col("timestamp") < forecast_origin).drop("cohort")
    future = series.filter(
        (pl.col("timestamp") >= forecast_origin) & (pl.col("timestamp") < holdout_end)
    )
    if future.height != 7 or history.height < 63:
        raise RuntimeError(
            "selected UCI SKU does not provide the required pre-origin history and "
            "seven-day untouched holdout; choose a different origin offset"
        )

    history_values = [float(value) for value in history.get_column("demand").to_list()]
    future_values = [float(value) for value in future.get_column("demand").to_list()]
    adapter = SeasonalNaiveAdapter(season_length=7)
    config = BacktestConfig(
        initial_train_size=28,
        horizon=7,
        step=7,
        season_length=7,
        quantile_levels=(0.1, 0.5, 0.9),
        coverage_levels=(0.8,),
        seed=42,
    )
    report = run_backtest(history, [adapter], config)
    forecast = adapter.predict(
        series_id,
        history_values,
        horizon=7,
        quantile_levels=(0.1, 0.5, 0.9),
        seed=42,
    )
    distribution = calibrate_lead_time_demand(
        report,
        series_id=series_id,
        model_id=adapter.model_id,
        forecast_origin=forecast_origin,
        baseline_median=forecast.quantiles[0.5],
        expected_model_version=adapter.model_version,
        lead_time=7,
        quantile_levels=(0.1, 0.5, 0.9),
        bootstrap_samples=1000,
        min_calibration_paths=5,
        seed=42,
    )

    inventory_position = max(0.0, sum(forecast.quantiles[0.5]) * 0.5)
    scenario = to_inventory_scenario(
        distribution,
        scenario_id=f"{series_id}:{forecast_origin.isoformat()}",
        realized_lead_time_demand=sum(future_values),
        inventory_position=inventory_position,
    )
    policies = compare_inventory_policies(
        [scenario],
        {
            "baseline": InventoryPolicy(
                underage_cost=3.0,
                overage_cost=1.0,
                holding_cost_per_unit=0.5,
                shortage_cost_per_unit=4.0,
            ),
            "high-service": InventoryPolicy(
                underage_cost=9.0,
                overage_cost=1.0,
                holding_cost_per_unit=0.5,
                shortage_cost_per_unit=4.0,
            ),
        },
    )
    selected = policies["high-service"].scenarios[0].recommendation
    simulation = simulate_inventory_policy(
        future_values,
        InventorySimulationConfig(
            initial_on_hand=inventory_position,
            reorder_point=inventory_position * 0.5,
            order_quantity=float(max(1, selected.quantity)),
            lead_time_days=3,
            allow_backorders=True,
        ),
    )
    source_sha256 = sha256_file(workbook)
    dataset_fingerprint = f"{source_sha256}:{report.dataset_fingerprint}"

    output.parent.mkdir(parents=True, exist_ok=True)
    registry_path = output.parent / "uci-online-retail-runs.sqlite"
    artifact_root = output.parent / "uci-online-retail-artifacts"
    registry = SQLiteRunRegistry(registry_path)
    artifact_store = FileArtifactStore(artifact_root)
    run = registry.create_run(
        idempotency_key=f"uci-e2e:{source_sha256}:{series_id}:{forecast_origin.isoformat()}",
        dataset_fingerprint=dataset_fingerprint,
        model_id=adapter.model_id,
        model_version=adapter.model_version,
        config={
            "forecast_origin": forecast_origin.isoformat(),
            "forecast_origin_offset_days": forecast_origin_offset_days,
            "initial_train_size": config.initial_train_size,
            "horizon": config.horizon,
            "step": config.step,
            "seed": config.seed,
        },
    )
    stored = artifact_store.put(report.to_json_bytes())
    if artifact_store.get(stored.sha256) != report.to_json_bytes():
        raise RuntimeError("stored evaluation artifact failed SHA-256 retrieval verification")
    completed = registry.complete_run(
        run.run_id,
        {
            "artifact_sha256": stored.sha256,
            "source_sha256": source_sha256,
            "forecast_quantiles": {
                str(level): list(values) for level, values in forecast.quantiles.items()
            },
            "rolling_origin_fold_count": len(report.evaluations),
        },
    )
    decision = registry.record_inventory_decision(
        run.run_id,
        decision_key=scenario.scenario_id,
        decision={
            "policy": "high-service",
            "order_quantity": selected.quantity,
            "target_stock_level": selected.target_stock_level,
            "realized_demand_from_uci": scenario.realized_lead_time_demand,
            "lead_time_demand_quantiles": {
                str(level): value for level, value in distribution.quantiles.items()
            },
            "inventory_position_assumption": inventory_position,
            "supplier_lead_time_days_assumption": 3,
        },
    )
    assert registry.list_inventory_decisions(run.run_id) == (decision,)
    payload: dict[str, object] = {
        "schema_version": 1,
        "provenance": {
            "dataset": "UCI Online Retail",
            "doi": DATASET_DOI,
            "source_sha256": source_sha256,
            "report_dataset_fingerprint": report.dataset_fingerprint,
            "cohort_counts": cohort_counts,
        },
        "series_id": series_id,
        "history_start": str(history.get_column("timestamp").min()),
        "forecast_origin": forecast_origin.isoformat(),
        "holdout_end_exclusive": holdout_end.isoformat(),
        "holdout_actual_demand": future_values,
        "rolling_origin": {
            "fold_count": len(report.evaluations),
            "mean_wql": report.model_summaries[0].mean_wql,
            "mean_mase": report.model_summaries[0].mean_mase,
        },
        "forecast_quantiles": {
            str(level): list(values) for level, values in forecast.quantiles.items()
        },
        "lead_time_calibration": {
            "path_count": distribution.calibration_path_count,
            "quantiles": {
                str(level): value for level, value in distribution.quantiles.items()
            },
        },
        "policy_comparison": {
            name: {
                "total_cost": result.total_cost,
                "fill_rate": result.fill_rate,
                "cycle_service_level": result.cycle_service_level,
                "order_quantity": result.scenarios[0].recommendation.quantity,
            }
            for name, result in policies.items()
        },
        "inventory_simulation": {
            "days": len(simulation.days),
            "stockout_days": simulation.stockout_days,
            "total_fulfilled": simulation.total_fulfilled,
            "total_lost_sales": simulation.total_lost_sales,
            "ending_backorders": simulation.ending_backorders,
            "fill_rate": simulation.fill_rate,
        },
        "assumptions": {
            "inventory_position": inventory_position,
            "supplier_lead_time_days": 3,
            "costs": "explicit synthetic scenario assumptions; not present in UCI source",
        },
        "registry": {
            "run_id": completed.run_id,
            "status": completed.status,
            "inventory_decision_id": decision.decision_id,
            "decision_key": decision.decision_key,
        },
        "artifact": {
            "sha256": stored.sha256,
            "size_bytes": stored.size_bytes,
            "path": stored.path,
        },
    }
    output.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path, help="Path to the official UCI Online Retail.xlsx")
    parser.add_argument("--origin-offset-days", type=int, default=300)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/uci-online-retail-end-to-end.json"),
    )
    args = parser.parse_args()
    result = run_real_data_e2e(
        args.workbook,
        args.output,
        forecast_origin_offset_days=args.origin_offset_days,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
