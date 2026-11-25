"""Run M5/Walmart prequential calibration and a chronological demand holdout."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import polars as pl

from demand_forecast_kit.backtesting import BacktestConfig, run_backtest
from demand_forecast_kit.lead_time import (
    backtest_lead_time_calibration,
    calibrate_lead_time_demand,
    to_inventory_scenario,
)
from demand_forecast_kit.models.base import ForecastAdapter
from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter
from demand_forecast_kit.models.statistical import CrostonAdapter, TSBAdapter
from demand_forecast_kit.policy_comparison import InventoryPolicy, compare_inventory_policies
from demand_forecast_kit.retail_benchmark import (
    COHORTS,
    build_cohort_panel,
    prepare_m5_daily_demand,
)

QUANTILE_LEVELS = (0.1, 0.5, 0.9)
LEAD_TIMES = (7, 14)
BOOTSTRAP_SAMPLES = 250
MIN_CALIBRATION_PATHS = 5
SEED = 42


def _stringify_levels(values: Mapping[float, float]) -> dict[str, float]:
    return {str(level): value for level, value in values.items()}


def _summarize_calibration(
    rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str, int], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["cohort"]), str(row["model_id"]), int(row["lead_time"]))].append(row)

    summaries: list[dict[str, object]] = []
    for (cohort, model_id, lead_time), items in sorted(grouped.items()):
        p80 = [
            float(cast(dict[str, float], item["interval_coverage"])["0.8"])
            for item in items
            if "0.8" in cast(dict[str, float], item["interval_coverage"])
        ]
        if not p80:
            continue
        summaries.append(
            {
                "cohort": cohort,
                "model_id": model_id,
                "lead_time": lead_time,
                "series_count": len(items),
                "mean_origin_count": sum(int(item["origin_count"]) for item in items) / len(items),
                "macro_p80_interval_coverage": sum(p80) / len(p80),
                "min_series_p80_coverage": min(p80),
                "max_series_p80_coverage": max(p80),
                "series_below_nominal_p80": sum(value < 0.8 for value in p80),
            }
        )
    return summaries


def run_m5_walmart_benchmark(
    sales_file: Path,
    calendar_file: Path,
    *,
    max_series_per_cohort: int = 20,
    holdout_days: int = 28,
    output: Path = Path("artifacts/m5-walmart-benchmark.json"),
    adapters: Sequence[ForecastAdapter] | None = None,
) -> dict[str, object]:
    """Run training-only calibration and a final rolling-origin demand holdout.

    The holdout is demand-only. Inventory position and cost parameters are explicit
    synthetic scenario assumptions, not observed Walmart inventory or cost data.
    """
    if type(max_series_per_cohort) is not int or max_series_per_cohort < 1:
        raise ValueError("max_series_per_cohort must be a positive integer")
    if type(holdout_days) is not int or holdout_days < 14 or holdout_days % 14 != 0:
        raise ValueError("holdout_days must be a positive multiple of 14")

    daily, source_cohort_counts, provenance = prepare_m5_daily_demand(
        sales_file,
        calendar_file,
        max_series_per_cohort=max_series_per_cohort,
    )
    panel, panel_cohort_counts = build_cohort_panel(
        daily,
        max_skus_per_cohort=max_series_per_cohort,
        cohort_window_days=180,
    )
    if source_cohort_counts != panel_cohort_counts:
        raise RuntimeError("M5 adapter and panel builder selected different cohort counts")

    first_day = panel.get_column("timestamp").min()
    last_day = panel.get_column("timestamp").max()
    if first_day is None or last_day is None:
        raise ValueError("M5 panel has no calendar dates")
    holdout_start = last_day - timedelta(days=holdout_days - 1)
    training_end = holdout_start - timedelta(days=1)
    train_panel = panel.filter(pl.col("timestamp") < holdout_start)
    holdout_panel = panel.filter(pl.col("timestamp") >= holdout_start)
    series_count = panel.get_column("series_id").n_unique()
    if holdout_panel.height != series_count * holdout_days:
        raise ValueError("M5 panel does not contain a complete final holdout for every series")
    if train_panel.get_column("timestamp").max() != training_end:
        raise ValueError("M5 training history does not end immediately before the holdout")

    selected_adapters = list(adapters) if adapters is not None else [
        SeasonalNaiveAdapter(season_length=7),
        CrostonAdapter(variant="sba", conformal_windows=2),
        TSBAdapter(conformal_windows=2),
    ]
    if not selected_adapters:
        raise ValueError("at least one forecasting adapter is required")
    config = BacktestConfig(
        initial_train_size=180,
        horizon=14,
        step=7,
        season_length=7,
        quantile_levels=QUANTILE_LEVELS,
        coverage_levels=(0.8,),
        seed=SEED,
    )
    policies = {
        "baseline": InventoryPolicy(
            underage_cost=3.0,
            overage_cost=1.0,
            holding_cost_per_unit=0.25,
            shortage_cost_per_unit=4.0,
        ),
        "high_service": InventoryPolicy(
            underage_cost=9.0,
            overage_cost=1.0,
            holding_cost_per_unit=0.25,
            shortage_cost_per_unit=4.0,
        ),
    }

    model_summaries: list[dict[str, object]] = []
    calibration_rows: list[dict[str, object]] = []
    calibration_skipped: list[dict[str, str]] = []
    holdout_scenarios: list[dict[str, object]] = []
    policy_results: list[dict[str, object]] = []
    holdout_skipped: list[dict[str, str]] = []
    fingerprints: dict[str, str] = {}

    for cohort in COHORTS:
        cohort_train = train_panel.filter(pl.col("cohort") == cohort).drop("cohort")
        cohort_full = panel.filter(pl.col("cohort") == cohort).drop("cohort")
        cohort_holdout = holdout_panel.filter(pl.col("cohort") == cohort).drop("cohort")
        if cohort_train.is_empty():
            continue
        series_ids = sorted(
            cast(list[str], cohort_train.get_column("series_id").unique().to_list())
        )

        for adapter in selected_adapters:
            report = run_backtest(cohort_train, [adapter], config)
            fingerprints[f"{cohort}:{adapter.model_id}"] = report.dataset_fingerprint
            for summary in report.model_summaries:
                model_summaries.append(
                    {
                        "cohort": cohort,
                        "model_id": summary.model_id,
                        "model_version": summary.model_version,
                        "series_count": summary.series_count,
                        "fold_count": summary.fold_count,
                        "mean_mase": summary.mean_mase,
                        "mean_wql": summary.mean_wql,
                        "mean_pinball_loss": summary.mean_pinball_loss,
                        "interval_coverages": _stringify_levels(summary.interval_coverages),
                    }
                )

            scenarios_by_lead_time: dict[int, list[Any]] = {
                lead_time: [] for lead_time in LEAD_TIMES
            }
            for series_id in series_ids:
                for lead_time in LEAD_TIMES:
                    try:
                        diagnostic = backtest_lead_time_calibration(
                            report,
                            series_id=series_id,
                            model_id=adapter.model_id,
                            lead_time=lead_time,
                            quantile_levels=QUANTILE_LEVELS,
                            bootstrap_samples=BOOTSTRAP_SAMPLES,
                            min_calibration_paths=MIN_CALIBRATION_PATHS,
                            seed=SEED,
                        )
                    except ValueError as exc:
                        calibration_skipped.append(
                            {
                                "cohort": cohort,
                                "series_id": series_id,
                                "model_id": adapter.model_id,
                                "lead_time": str(lead_time),
                                "reason": str(exc),
                            }
                        )
                    else:
                        calibration_rows.append(
                            {
                                "cohort": cohort,
                                "series_id": series_id,
                                "model_id": adapter.model_id,
                                "model_version": adapter.model_version,
                                "lead_time": lead_time,
                                "origin_count": diagnostic.origin_count,
                                "quantile_coverage": _stringify_levels(
                                    diagnostic.quantile_coverage
                                ),
                                "mean_pinball_loss": _stringify_levels(
                                    diagnostic.mean_pinball_loss
                                ),
                                "interval_coverage": _stringify_levels(
                                    diagnostic.interval_coverage
                                ),
                            }
                        )

                    for offset in range(0, holdout_days, lead_time):
                        origin = holdout_start + timedelta(days=offset)
                        window_end = origin + timedelta(days=lead_time)
                        future = cohort_holdout.filter(
                            (pl.col("series_id") == series_id)
                            & (pl.col("timestamp") >= origin)
                            & (pl.col("timestamp") < window_end)
                        ).sort("timestamp")
                        if future.height != lead_time:
                            holdout_skipped.append(
                                {
                                    "cohort": cohort,
                                    "series_id": series_id,
                                    "model_id": adapter.model_id,
                                    "lead_time": str(lead_time),
                                    "origin": origin.isoformat(),
                                    "reason": "incomplete realized holdout window",
                                }
                            )
                            continue

                        history = cohort_full.filter(
                            (pl.col("series_id") == series_id) & (pl.col("timestamp") < origin)
                        ).sort("timestamp")
                        history_values = [
                            float(value) for value in history.get_column("demand").to_list()
                        ]
                        forecast = adapter.predict(
                            series_id,
                            history_values,
                            horizon=lead_time,
                            quantile_levels=QUANTILE_LEVELS,
                            seed=SEED,
                        )
                        baseline_median = tuple(float(value) for value in forecast.quantiles[0.5])
                        try:
                            distribution = calibrate_lead_time_demand(
                                report,
                                series_id=series_id,
                                model_id=adapter.model_id,
                                forecast_origin=origin,
                                baseline_median=baseline_median,
                                expected_model_version=adapter.model_version,
                                lead_time=lead_time,
                                quantile_levels=QUANTILE_LEVELS,
                                bootstrap_samples=BOOTSTRAP_SAMPLES,
                                min_calibration_paths=MIN_CALIBRATION_PATHS,
                                seed=SEED,
                            )
                        except ValueError as exc:
                            holdout_skipped.append(
                                {
                                    "cohort": cohort,
                                    "series_id": series_id,
                                    "model_id": adapter.model_id,
                                    "lead_time": str(lead_time),
                                    "origin": origin.isoformat(),
                                    "reason": str(exc),
                                }
                            )
                            continue

                        realized_demand = float(future.get_column("demand").sum())
                        inventory_position = max(0.0, 0.5 * sum(baseline_median))
                        scenario_id = (
                            f"{cohort}:{adapter.model_id}:{series_id}:"
                            f"{lead_time}:{origin.isoformat()}"
                        )
                        scenario = to_inventory_scenario(
                            distribution,
                            scenario_id=scenario_id,
                            realized_lead_time_demand=realized_demand,
                            inventory_position=inventory_position,
                        )
                        scenarios_by_lead_time[lead_time].append(scenario)
                        holdout_scenarios.append(
                            {
                                "cohort": cohort,
                                "series_id": series_id,
                                "model_id": adapter.model_id,
                                "lead_time": lead_time,
                                "forecast_origin": origin.isoformat(),
                                "realized_lead_time_demand": realized_demand,
                                "baseline_median_demand": sum(baseline_median),
                                "inventory_position_assumption": inventory_position,
                                "calibration_path_count": distribution.calibration_path_count,
                                "calibrated_quantiles": _stringify_levels(distribution.quantiles),
                            }
                        )

            for lead_time, scenarios in scenarios_by_lead_time.items():
                if not scenarios:
                    continue
                evaluations = compare_inventory_policies(scenarios, policies)
                for policy_name, evaluation in evaluations.items():
                    result = asdict(evaluation)
                    result.pop("scenarios", None)
                    policy_results.append(
                        {
                            "cohort": cohort,
                            "model_id": adapter.model_id,
                            "lead_time": lead_time,
                            "policy": policy_name,
                            **result,
                        }
                    )

    if not model_summaries:
        raise RuntimeError("no M5 training evaluations were produced")
    payload: dict[str, object] = {
        "schema_version": 1,
        "benchmark": "m5-walmart-prequential-lead-time-and-chronological-demand-holdout",
        "provenance": provenance,
        "cohort_counts": panel_cohort_counts,
        "dataset_fingerprints": fingerprints,
        "windows": {
            "history_start": first_day.isoformat(),
            "training_end": training_end.isoformat(),
            "holdout_start": holdout_start.isoformat(),
            "holdout_end": last_day.isoformat(),
            "holdout_days": holdout_days,
            "holdout_protocol": (
                "Rolling-origin evaluation; later origins may use earlier realized holdout "
                "days as history, but calibration and model selection use training history only."
            ),
        },
        "configuration": {
            "initial_train_size": config.initial_train_size,
            "backtest_horizon": config.horizon,
            "backtest_step": config.step,
            "lead_times": list(LEAD_TIMES),
            "quantile_levels": list(QUANTILE_LEVELS),
            "bootstrap_samples": BOOTSTRAP_SAMPLES,
            "min_calibration_paths": MIN_CALIBRATION_PATHS,
            "seed": SEED,
            "global_calibration_correction_enabled": False,
        },
        "training_model_summaries": model_summaries,
        "training_lead_time_calibration": calibration_rows,
        "training_calibration_macro_summary": _summarize_calibration(calibration_rows),
        "training_calibration_skipped": calibration_skipped,
        "holdout_inventory_scenarios": holdout_scenarios,
        "holdout_policy_results": policy_results,
        "holdout_skipped": holdout_skipped,
        "policy_assumptions": {
            "inventory_position": (
                "50% of the uncalibrated baseline median cumulative demand for each "
                "series/origin/lead-time; not observed Walmart stock"
            ),
            "baseline": {
                "underage_cost": 3.0,
                "overage_cost": 1.0,
                "holding_cost_per_unit": 0.25,
                "shortage_cost_per_unit": 4.0,
            },
            "high_service": {
                "underage_cost": 9.0,
                "overage_cost": 1.0,
                "holding_cost_per_unit": 0.25,
                "shortage_cost_per_unit": 4.0,
            },
            "limitations": [
                "M5 provides sales demand, not on-hand inventory, purchase orders, or receipts.",
                "Cost and inventory-position inputs are sensitivity assumptions, "
                "not retailer facts.",
                "This is a demand-only policy simulation, not a production replenishment backtest.",
            ],
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sales-file", type=Path, required=True)
    parser.add_argument("--calendar-file", type=Path, required=True)
    parser.add_argument("--max-series-per-cohort", type=int, default=20)
    parser.add_argument("--holdout-days", type=int, default=28)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/m5-walmart-benchmark.json"),
    )
    args = parser.parse_args()
    result = run_m5_walmart_benchmark(
        args.sales_file,
        args.calendar_file,
        max_series_per_cohort=args.max_series_per_cohort,
        holdout_days=args.holdout_days,
        output=args.output,
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "cohort_counts": result["cohort_counts"],
                "training_calibration_groups": len(result["training_calibration_macro_summary"]),
                "holdout_scenarios": len(result["holdout_inventory_scenarios"]),
                "holdout_policy_groups": len(result["holdout_policy_results"]),
                "holdout_skipped": len(result["holdout_skipped"]),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
