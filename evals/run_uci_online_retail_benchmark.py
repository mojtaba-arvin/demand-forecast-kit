# SPDX-FileCopyrightText: 2026 Mojtaba Arvin
# SPDX-License-Identifier: MIT
"""Run an opt-in, reproducible calibration benchmark on UCI Online Retail."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import cast

import polars as pl

from demand_forecast_kit.backtesting import BacktestConfig, run_backtest
from demand_forecast_kit.lead_time import backtest_lead_time_calibration
from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter
from demand_forecast_kit.models.statistical import CrostonAdapter, TSBAdapter
from demand_forecast_kit.retail_benchmark import (
    COHORTS,
    build_cohort_panel,
    prepare_daily_demand,
    sha256_file,
)

DATASET_DOI = "https://doi.org/10.24432/C5BW33"
DATASET_URL = "https://archive.ics.uci.edu/dataset/352/online-retail"
QUANTILES = (0.1, 0.5, 0.9)
LEAD_TIMES = (7, 14)
INITIAL_TRAIN_SIZE = 180



def _baseline_error_summary(
    observations: list[dict[str, object]],
) -> dict[str, float | int]:
    """Summarize baseline errors on the exact prequential calibration-eligible origins."""
    errors = [float(item["actual"]) - float(item["baseline_median"]) for item in observations]
    if not errors:
        raise ValueError("at least one prequential observation is required")
    ordered = sorted(errors)
    middle = len(ordered) // 2
    median_error = (
        ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2.0
    )
    return {
        "origin_count": len(errors),
        "mean_error": sum(errors) / len(errors),
        "median_error": median_error,
        "mean_absolute_error": sum(abs(value) for value in errors) / len(errors),
        "underforecast_rate": sum(value > 0.0 for value in errors) / len(errors),
    }


def _pinball(actual: float, forecast: float, level: float) -> float:
    error = actual - forecast
    return max(level * error, (level - 1.0) * error)


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _evaluate_scaled_intervals(
    observations: list[dict[str, object]],
    *,
    scale: float,
    median_shift: float,
) -> dict[str, float | int]:
    if not observations:
        raise ValueError("at least one evaluation observation is required")
    interval_hits = 0
    quantile_hits = {0.1: 0, 0.5: 0, 0.9: 0}
    losses = {0.1: 0.0, 0.5: 0.0, 0.9: 0.0}
    widths: list[float] = []
    for item in observations:
        actual = float(item["actual"])
        q10 = float(item["q10"])
        q50 = float(item["q50"])
        q90 = float(item["q90"])
        median = max(0.0, q50 + median_shift)
        lower = max(0.0, median + scale * (q10 - q50))
        upper = max(lower, median + scale * (q90 - q50))
        interval_hits += int(lower <= actual <= upper)
        quantile_hits[0.1] += int(actual <= lower)
        quantile_hits[0.5] += int(actual <= median)
        quantile_hits[0.9] += int(actual <= upper)
        losses[0.1] += _pinball(actual, lower, 0.1)
        losses[0.5] += _pinball(actual, median, 0.5)
        losses[0.9] += _pinball(actual, upper, 0.9)
        widths.append(upper - lower)
    count = len(observations)
    return {
        "observation_count": count,
        "p80_coverage": interval_hits / count,
        "p10_coverage": quantile_hits[0.1] / count,
        "p50_coverage": quantile_hits[0.5] / count,
        "p90_coverage": quantile_hits[0.9] / count,
        "p10_pinball": losses[0.1] / count,
        "p50_pinball": losses[0.5] / count,
        "p90_pinball": losses[0.9] / count,
        "mean_interval_width": sum(widths) / count,
    }


def _fit_interval_scale(
    observations: list[dict[str, object]],
    *,
    median_shift: float,
) -> float:
    """Select interval width by calibration-block P10+P90 pinball loss only."""
    scale_grid = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0)
    candidates: list[tuple[float, float]] = []
    for scale in scale_grid:
        metrics = _evaluate_scaled_intervals(
            observations,
            scale=scale,
            median_shift=median_shift,
        )
        score = float(metrics["p10_pinball"]) + float(metrics["p90_pinball"])
        candidates.append((score, scale))
    return min(candidates)[1]


def _temporal_scale_experiment(
    origin_results: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Fit width/bias adjustments on early disjoint origins and score later disjoint origins.

    Per SKU, eligible origin offsets 0, 2, 4, and 6 form the calibration block.
    Offsets 10, 12, and 14 form the untouched holdout block. All other offsets
    are purged, ensuring no 14-day target windows overlap across the split.
    """
    grouped: dict[tuple[str, str, int], list[dict[str, object]]] = defaultdict(list)
    for item in origin_results:
        grouped[(str(item["cohort"]), str(item["model_id"]), int(item["lead_time"]))].append(item)

    calibration_offsets = (0, 2, 4, 6)
    holdout_offsets = (10, 12, 14)
    summaries: list[dict[str, object]] = []
    for (cohort, model_id, lead_time), items in sorted(grouped.items()):
        by_series: dict[str, list[dict[str, object]]] = defaultdict(list)
        for item in items:
            by_series[str(item["series_id"])].append(item)
        calibration: list[dict[str, object]] = []
        holdout: list[dict[str, object]] = []
        insufficient: list[str] = []
        for series_id, series_items in sorted(by_series.items()):
            ordered = sorted(series_items, key=lambda item: int(item["fold"]))
            if len(ordered) <= max(holdout_offsets):
                insufficient.append(series_id)
                continue
            selected_calibration = [ordered[index] for index in calibration_offsets]
            selected_holdout = [ordered[index] for index in holdout_offsets]
            selected_dates = [
                datetime.fromisoformat(str(item["forecast_origin"]))
                for item in selected_calibration + selected_holdout
            ]
            if any(
                (right - left).days < 14
                for left, right in zip(selected_dates, selected_dates[1:], strict=False)
            ):
                raise RuntimeError("temporal calibration and holdout origins must be disjoint")
            if str(selected_holdout[0]["forecast_origin"]) <= str(
                selected_calibration[-1]["forecast_origin"]
            ):
                raise RuntimeError("holdout origins must follow the calibration block")
            calibration.extend(selected_calibration)
            holdout.extend(selected_holdout)

        if insufficient or not calibration or not holdout:
            summaries.append(
                {
                    "cohort": cohort,
                    "model_id": model_id,
                    "lead_time": lead_time,
                    "status": "skipped",
                    "reason": "insufficient prequential origins for the fixed purged split",
                    "series_without_required_origins": insufficient,
                }
            )
            continue

        median_shift = _median([float(item["actual"]) - float(item["q50"]) for item in calibration])
        width_scale = _fit_interval_scale(calibration, median_shift=0.0)
        bias_width_scale = _fit_interval_scale(calibration, median_shift=median_shift)
        summaries.append(
            {
                "cohort": cohort,
                "model_id": model_id,
                "lead_time": lead_time,
                "status": "evaluated",
                "series_count": len(by_series),
                "calibration_observation_count": len(calibration),
                "holdout_observation_count": len(holdout),
                "calibration_origin_offsets_per_series": list(calibration_offsets),
                "holdout_origin_offsets_per_series": list(holdout_offsets),
                "purged_origin_count_per_series": 9,
                "fitted_width_scale": width_scale,
                "fitted_bias_and_width_scale": bias_width_scale,
                "fitted_median_shift": median_shift,
                "holdout_baseline": _evaluate_scaled_intervals(
                    holdout,
                    scale=1.0,
                    median_shift=0.0,
                ),
                "holdout_width_scaled": _evaluate_scaled_intervals(
                    holdout,
                    scale=width_scale,
                    median_shift=0.0,
                ),
                "holdout_bias_and_width_scaled": _evaluate_scaled_intervals(
                    holdout,
                    scale=bias_width_scale,
                    median_shift=median_shift,
                ),
            }
        )
    return summaries


def _coverage_diagnostics(results: list[dict[str, object]]) -> list[dict[str, object]]:
    """Expose SKU dispersion, tail-quantile bias, and baseline median bias."""
    grouped: dict[tuple[str, str, int], list[dict[str, object]]] = defaultdict(list)
    for item in results:
        grouped[(str(item["cohort"]), str(item["model_id"]), int(item["lead_time"]))].append(item)

    summaries: list[dict[str, object]] = []
    for (cohort, model_id, lead_time), items in sorted(grouped.items()):
        interval_values = [
            cast(dict[str, float], item["interval_coverage"])["0.8"] for item in items
        ]
        quantile_values = [cast(dict[str, float], item["quantile_coverage"]) for item in items]
        baseline_values = [
            cast(dict[str, float | int], item["baseline_median_error"]) for item in items
        ]
        summaries.append(
            {
                "cohort": cohort,
                "model_id": model_id,
                "lead_time": lead_time,
                "series_count": len(items),
                "macro_interval_coverage": sum(interval_values) / len(interval_values),
                "min_series_interval_coverage": min(interval_values),
                "max_series_interval_coverage": max(interval_values),
                "series_below_nominal_p80": sum(value < 0.8 for value in interval_values),
                "macro_quantile_coverage": {
                    level: sum(item[level] for item in quantile_values) / len(quantile_values)
                    for level in ("0.1", "0.5", "0.9")
                },
                "macro_baseline_median_error": (
                    sum(float(item["mean_error"]) for item in baseline_values)
                    / len(baseline_values)
                ),
                "macro_baseline_median_absolute_error": (
                    sum(float(item["mean_absolute_error"]) for item in baseline_values)
                    / len(baseline_values)
                ),
                "series_with_mean_underforecast": sum(
                    float(item["mean_error"]) > 0.0 for item in baseline_values
                ),
                "series_with_mean_overforecast": sum(
                    float(item["mean_error"]) < 0.0 for item in baseline_values
                ),
            }
        )
    return summaries


def run_benchmark(
    workbook: Path,
    *,
    max_skus_per_cohort: int = 10,
    output: Path = Path("artifacts/uci-online-retail-calibration.json"),
) -> dict[str, object]:
    """Execute the real-data benchmark and write a deterministic JSON report."""
    transactions = pl.read_excel(workbook, engine="calamine")
    daily = prepare_daily_demand(transactions)
    panel, cohort_counts = build_cohort_panel(
        daily,
        max_skus_per_cohort=max_skus_per_cohort,
        cohort_window_days=INITIAL_TRAIN_SIZE,
    )
    adapters = [
        SeasonalNaiveAdapter(season_length=7),
        CrostonAdapter(variant="sba", conformal_windows=2),
        TSBAdapter(conformal_windows=2),
    ]
    config = BacktestConfig(
        initial_train_size=INITIAL_TRAIN_SIZE,
        horizon=14,
        step=7,
        season_length=7,
        quantile_levels=QUANTILES,
        coverage_levels=(0.8,),
        seed=42,
    )

    results: list[dict[str, object]] = []
    origin_level_results: list[dict[str, object]] = []
    panel_fingerprints: dict[str, str] = {}
    skipped: list[dict[str, str]] = []
    for cohort in COHORTS:
        cohort_panel = panel.filter(pl.col("cohort") == cohort).drop("cohort")
        if cohort_panel.is_empty():
            continue
        for adapter in adapters:
            try:
                report = run_backtest(cohort_panel, [adapter], config)
            except Exception as exc:
                skipped.append(
                    {
                        "cohort": cohort,
                        "series_id": "*",
                        "model_id": adapter.model_id,
                        "lead_time": "all",
                        "reason": f"model backtest failed: {type(exc).__name__}: {exc}",
                    }
                )
                continue
            panel_fingerprints.setdefault(cohort, report.dataset_fingerprint)
            for series_id in cohort_panel.get_column("series_id").unique().sort().to_list():
                for lead_time in LEAD_TIMES:
                    try:
                        diagnostic = backtest_lead_time_calibration(
                            report,
                            series_id=series_id,
                            model_id=adapter.model_id,
                            lead_time=lead_time,
                            quantile_levels=QUANTILES,
                            bootstrap_samples=250,
                            min_calibration_paths=5,
                            seed=42,
                        )
                    except ValueError as exc:
                        skipped.append(
                            {
                                "cohort": cohort,
                                "series_id": series_id,
                                "model_id": adapter.model_id,
                                "lead_time": str(lead_time),
                                "reason": str(exc),
                            }
                        )
                        continue
                    origin_diagnostics = [
                        {
                            "cohort": cohort,
                            "series_id": series_id,
                            "model_id": adapter.model_id,
                            "lead_time": lead_time,
                            "fold": item.fold,
                            "forecast_origin": item.forecast_origin,
                            "actual": item.actual,
                            "baseline_median": item.baseline_median,
                            "q10": item.quantiles[0.1],
                            "q50": item.quantiles[0.5],
                            "q90": item.quantiles[0.9],
                            "calibration_path_count": item.calibration_path_count,
                        }
                        for item in diagnostic.observations
                    ]
                    if len(origin_diagnostics) != diagnostic.origin_count:
                        raise RuntimeError(
                            "detailed observations and calibrated coverage used "
                            "different evaluation origins"
                        )
                    origin_level_results.extend(origin_diagnostics)
                    baseline_error = _baseline_error_summary(origin_diagnostics)
                    results.append(
                        {
                            "cohort": cohort,
                            "series_id": series_id,
                            "model_id": adapter.model_id,
                            "lead_time": lead_time,
                            "origin_count": diagnostic.origin_count,
                            "baseline_median_error": baseline_error,
                            "quantile_coverage": {
                                str(level): value
                                for level, value in diagnostic.quantile_coverage.items()
                            },
                            "mean_pinball_loss": {
                                str(level): value
                                for level, value in diagnostic.mean_pinball_loss.items()
                            },
                            "interval_coverage": {
                                str(level): value
                                for level, value in diagnostic.interval_coverage.items()
                            },
                        }
                    )

    if not results:
        raise RuntimeError(
            "no lead-time calibration diagnostics were produced; inspect skipped_evaluations "
            "and verify that the source history contains enough completed rolling-origin paths"
        )

    grouped: dict[tuple[str, str, int], list[dict[str, object]]] = defaultdict(list)
    for item in results:
        grouped[(str(item["cohort"]), str(item["model_id"]), int(item["lead_time"]))].append(item)

    macro_summary: list[dict[str, object]] = []
    for (cohort, model_id, lead_time), items in sorted(grouped.items()):
        macro_summary.append(
            {
                "cohort": cohort,
                "model_id": model_id,
                "lead_time": lead_time,
                "series_count": len(items),
                "mean_origin_count": (
                    sum(int(item["origin_count"]) for item in items) / len(items)
                ),
                "macro_quantile_coverage": {
                    level: (
                        sum(float(item["quantile_coverage"][level]) for item in items) / len(items)
                    )
                    for level in ("0.1", "0.5", "0.9")
                },
                "macro_mean_pinball_loss": {
                    level: (
                        sum(float(item["mean_pinball_loss"][level]) for item in items) / len(items)
                    )
                    for level in ("0.1", "0.5", "0.9")
                },
                "macro_interval_coverage": {
                    "0.8": (
                        sum(float(item["interval_coverage"]["0.8"]) for item in items) / len(items)
                    )
                },
            }
        )

    payload: dict[str, object] = {
        "schema_version": 2,
        "benchmark": "uci-online-retail-lead-time-calibration",
        "provenance": {
            "dataset": "UCI Online Retail",
            "creator": "Daqing Chen",
            "citation": "Chen, D. (2015). Online Retail. UCI Machine Learning Repository.",
            "doi": DATASET_DOI,
            "source_url": DATASET_URL,
            "license": "CC BY 4.0",
            "source_file_sha256": sha256_file(workbook),
            "preprocessing": (
                "Exclude cancellation invoices and non-positive quantities; aggregate positive "
                "quantities by StockCode and calendar day; fill no-sale days with zero. "
                "This measures gross outbound unit demand, not net returns."
            ),
        },
        "configuration": {
            "initial_train_size_days": INITIAL_TRAIN_SIZE,
            "cohort_assignment_window_days": INITIAL_TRAIN_SIZE,
            "forecast_horizon_days": 14,
            "origin_step_days": 7,
            "lead_times_days": list(LEAD_TIMES),
            "quantile_levels": list(QUANTILES),
            "bootstrap_samples": 250,
            "minimum_calibration_paths": 5,
            "seed": 42,
            "max_skus_per_cohort": max_skus_per_cohort,
            "temporal_scale_experiment": {
                "calibration_origin_offsets_per_series": [0, 2, 4, 6],
                "holdout_origin_offsets_per_series": [10, 12, 14],
                "purged_origin_count_per_series": 9,
                "target_window_days": 14,
                "scale_grid": [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0],
            },
        },
        "panel": {
            "start_date": str(panel.get_column("timestamp").min()),
            "end_date": str(panel.get_column("timestamp").max()),
            "calendar_days": panel.get_column("timestamp").n_unique(),
            "sku_counts": cohort_counts,
            "selected_series_count": panel.get_column("series_id").n_unique(),
            "panel_fingerprints_by_cohort": panel_fingerprints,
        },
        "macro_summary": macro_summary,
        "coverage_diagnostics": _coverage_diagnostics(results),
        "origin_level_results": origin_level_results,
        "temporal_scale_experiment": _temporal_scale_experiment(origin_level_results),
        "per_series_results": results,
        "skipped_evaluations": skipped,
        "interpretation": (
            "Macro-averages weight each SKU equally within its cohort. Results are specific to "
            "this historical retailer and preprocessing policy; they are not universal accuracy "
            "claims or evidence of inventory savings. The SKU sample is a deterministic hash "
            "sample within each activity-frequency cohort. Cohort membership is frozen using "
            "only the initial training window; later observations cannot affect assignment."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
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
    parser.add_argument("workbook", type=Path, help="Path to the UCI Online Retail.xlsx file")
    parser.add_argument("--max-skus-per-cohort", type=int, default=10)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/uci-online-retail-calibration.json"),
    )
    args = parser.parse_args()
    result = run_benchmark(
        args.workbook,
        max_skus_per_cohort=args.max_skus_per_cohort,
        output=args.output,
    )
    print(json.dumps(result["macro_summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
