# SPDX-FileCopyrightText: 2026 Mojtaba Arvin
# SPDX-License-Identifier: MIT
"""Exercise forecast, rolling-origin evaluation, inventory simulation, and registry end to end."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import polars as pl

from demand_forecast_kit.artifacts import FileArtifactStore
from demand_forecast_kit.backtesting import BacktestConfig, run_backtest
from demand_forecast_kit.lead_time import calibrate_lead_time_demand, to_inventory_scenario
from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter
from demand_forecast_kit.policy_comparison import InventoryPolicy, compare_inventory_policies
from demand_forecast_kit.registry import SQLiteRunRegistry
from demand_forecast_kit.simulation import InventorySimulationConfig, simulate_inventory_policy


def run_end_to_end(output: Path) -> dict[str, object]:
    """Run a deterministic, leakage-aware synthetic decision pipeline."""
    start = date(2024, 1, 1)
    history_values = [float(12 + day % 7 + (day % 11 == 0) * 3) for day in range(120)]
    future_values = [float(12 + day % 7 + (day % 11 == 0) * 3) for day in range(120, 127)]
    history = pl.DataFrame(
        {
            "series_id": ["synthetic-sku"] * len(history_values),
            "timestamp": [start + timedelta(days=day) for day in range(len(history_values))],
            "demand": history_values,
        }
    )
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
        "synthetic-sku",
        history_values,
        horizon=7,
        quantile_levels=(0.1, 0.5, 0.9),
        seed=42,
    )
    forecast_origin = start + timedelta(days=len(history_values))
    distribution = calibrate_lead_time_demand(
        report,
        series_id="synthetic-sku",
        model_id=adapter.model_id,
        forecast_origin=forecast_origin,
        baseline_median=forecast.quantiles[0.5],
        expected_model_version=adapter.model_version,
        lead_time=7,
        quantile_levels=(0.1, 0.5, 0.9),
        bootstrap_samples=500,
        min_calibration_paths=5,
        seed=42,
    )
    scenario = to_inventory_scenario(
        distribution,
        scenario_id=f"synthetic-sku:{forecast_origin.isoformat()}",
        realized_lead_time_demand=sum(future_values),
        inventory_position=20.0,
    )
    policy_reports = compare_inventory_policies(
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
    selected = policy_reports["high-service"].scenarios[0].recommendation
    simulation = simulate_inventory_policy(
        future_values,
        InventorySimulationConfig(
            initial_on_hand=20.0,
            reorder_point=25.0,
            order_quantity=float(max(1, selected.quantity)),
            lead_time_days=3,
            allow_backorders=True,
        ),
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="demand-forecast-e2e-") as temporary:
        root = Path(temporary)
        registry = SQLiteRunRegistry(root / "runs.sqlite")
        artifact_store = FileArtifactStore(root / "artifacts")
        run = registry.create_run(
            idempotency_key=f"e2e:{report.dataset_fingerprint}:{forecast_origin.isoformat()}",
            dataset_fingerprint=report.dataset_fingerprint,
            model_id=adapter.model_id,
            model_version=adapter.model_version,
            config={
                "initial_train_size": config.initial_train_size,
                "horizon": config.horizon,
                "step": config.step,
                "seed": config.seed,
                "forecast_origin": forecast_origin.isoformat(),
            },
        )
        stored = artifact_store.put(report.to_json_bytes())
        if artifact_store.get(stored.sha256) != report.to_json_bytes():
            raise RuntimeError("stored evaluation artifact failed SHA-256 retrieval verification")
        completed = registry.complete_run(
            run.run_id,
            {
                "artifact_sha256": stored.sha256,
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
                "lead_time_demand_quantiles": {
                    str(level): value for level, value in distribution.quantiles.items()
                },
                "realized_lead_time_demand": scenario.realized_lead_time_demand,
                "inventory_position": scenario.inventory_position,
            },
        )
        assert registry.list_inventory_decisions(run.run_id) == (decision,)
        payload: dict[str, object] = {
            "schema_version": 1,
            "provenance": "synthetic-end-to-end-plumbing-only",
            "dataset_fingerprint": report.dataset_fingerprint,
            "model_id": adapter.model_id,
            "model_version": adapter.model_version,
            "forecast_origin": forecast_origin.isoformat(),
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
                "quantiles": {str(level): value for level, value in distribution.quantiles.items()},
            },
            "policy_comparison": {
                name: {
                    "total_cost": result.total_cost,
                    "fill_rate": result.fill_rate,
                    "cycle_service_level": result.cycle_service_level,
                    "order_quantity": result.scenarios[0].recommendation.quantity,
                }
                for name, result in policy_reports.items()
            },
            "inventory_simulation": {
                "days": len(simulation.days),
                "stockout_days": simulation.stockout_days,
                "total_fulfilled": simulation.total_fulfilled,
                "total_lost_sales": simulation.total_lost_sales,
                "ending_backorders": simulation.ending_backorders,
                "fill_rate": simulation.fill_rate,
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
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\\n",
            encoding="utf-8",
        )
    return payload


def main() -> None:
    payload = run_end_to_end(Path("artifacts/synthetic-end-to-end-decision.json"))
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
