"""Run a second retail benchmark on the UCI Online Retail II workbook."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Mapping
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

DATASET_DOI = "https://doi.org/10.24432/C5CG6D"
DATASET_URL = "https://archive.ics.uci.edu/dataset/502/online+retail+ii"


def _stringify_levels(values: Mapping[float, float]) -> dict[str, float]:
    return {str(level): value for level, value in values.items()}


def _summarize_lead_time_calibration(
    results: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Summarize prequential lead-time coverage without treating folds as independent."""
    grouped: dict[tuple[str, str, int], list[dict[str, object]]] = defaultdict(list)
    for item in results:
        grouped[(str(item["cohort"]), str(item["model_id"]), int(item["lead_time"]))].append(item)

    summaries: list[dict[str, object]] = []
    for (cohort, model_id, lead_time), items in sorted(grouped.items()):
        p80_values = [
            float(cast(dict[str, float], item["interval_coverage"])["0.8"])
            for item in items
        ]
        quantile_values = [
            cast(dict[str, float], item["quantile_coverage"]) for item in items
        ]
        summaries.append(
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
                        sum(item[level] for item in quantile_values) / len(quantile_values)
                    )
                    for level in ("0.1", "0.5", "0.9")
                },
                "macro_p80_interval_coverage": sum(p80_values) / len(p80_values),
                "min_series_p80_coverage": min(p80_values),
                "max_series_p80_coverage": max(p80_values),
                "series_below_nominal_p80": sum(value < 0.8 for value in p80_values),
            }
        )
    return summaries


def _read_workbook(path: Path) -> tuple[pl.DataFrame, list[str]]:
    """Read and combine the two official historical worksheets."""
    loaded = pl.read_excel(path, sheet_id=0)
    if isinstance(loaded, dict):
        if not loaded:
            raise ValueError("Online Retail II workbook contains no worksheets")
        names = list(loaded)
        frames = [loaded[name] for name in names]
        return pl.concat(frames, how="diagonal_relaxed"), names
    return cast(pl.DataFrame, loaded), ["default"]


def run_benchmark(
    workbook: Path,
    *,
    max_skus_per_cohort: int = 20,
    output: Path = Path("artifacts/uci-online-retail-ii-benchmark.json"),
) -> dict[str, object]:
    """Run identical rolling-origin comparisons on frozen SKU frequency cohorts."""
    if type(max_skus_per_cohort) is not int or max_skus_per_cohort < 1:
        raise ValueError("max_skus_per_cohort must be a positive integer")
    transactions, worksheet_names = _read_workbook(workbook)
    daily = prepare_daily_demand(transactions)
    panel, cohort_counts = build_cohort_panel(
        daily,
        max_skus_per_cohort=max_skus_per_cohort,
        cohort_window_days=180,
    )
    adapters = [
        SeasonalNaiveAdapter(season_length=7),
        CrostonAdapter(variant="sba", conformal_windows=2),
        TSBAdapter(conformal_windows=2),
    ]
    config = BacktestConfig(
        initial_train_size=180,
        horizon=14,
        step=7,
        season_length=7,
        quantile_levels=(0.1, 0.5, 0.9),
        coverage_levels=(0.8,),
        seed=42,
    )

    macro_summary: list[dict[str, object]] = []
    per_series_summary: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    calibration_per_series: list[dict[str, object]] = []
    calibration_skipped: list[dict[str, str]] = []
    fingerprints: dict[str, str] = {}
    for cohort in COHORTS:
        cohort_panel = panel.filter(pl.col("cohort") == cohort).drop("cohort")
        if cohort_panel.is_empty():
            continue
        for adapter in adapters:
            report = run_backtest(cohort_panel, [adapter], config)
            fingerprints[cohort] = report.dataset_fingerprint
            for item in report.model_summaries:
                macro_summary.append(
                    {
                        "cohort": cohort,
                        "model_id": item.model_id,
                        "model_version": item.model_version,
                        "series_count": item.series_count,
                        "fold_count": item.fold_count,
                        "mean_mase": item.mean_mase,
                        "mean_wql": item.mean_wql,
                        "mean_pinball_loss": item.mean_pinball_loss,
                        "interval_coverages": _stringify_levels(item.interval_coverages),
                    }
                )
            for item in report.evaluations:
                per_series_summary.append(
                    {
                        "cohort": cohort,
                        "series_id": item.series_id,
                        "model_id": item.model_id,
                        "fold": item.fold,
                        "mase": item.mase,
                        "wql": item.wql,
                        "pinball_losses": {
                            str(level): value for level, value in item.pinball_losses.items()
                        },
                        "interval_coverages": {
                            str(level): value for level, value in item.interval_coverages.items()
                        },
                    }
                )
            for series_id in cohort_panel.get_column("series_id").unique().sort().to_list():
                for lead_time in (7, 14):
                    try:
                        diagnostic = backtest_lead_time_calibration(
                            report,
                            series_id=series_id,
                            model_id=adapter.model_id,
                            lead_time=lead_time,
                            quantile_levels=config.quantile_levels,
                            bootstrap_samples=250,
                            min_calibration_paths=5,
                            seed=42,
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
                        continue
                    calibration_per_series.append(
                        {
                            "cohort": cohort,
                            "series_id": series_id,
                            "model_id": adapter.model_id,
                            "model_version": report.model_summaries[0].model_version,
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
            skipped.extend(
                {
                    "cohort": cohort,
                    "model_id": adapter.model_id,
                    "series_id": item.series_id,
                    "observation_count": item.observation_count,
                    "required_observations": item.required_observations,
                }
                for item in report.skipped_series
            )

    if not macro_summary:
        raise RuntimeError("no model evaluations were produced for Online Retail II")
    payload: dict[str, object] = {
        "schema_version": 2,
        "benchmark": "uci-online-retail-ii-rolling-origin-and-lead-time-calibration",
        "provenance": {
            "dataset": "UCI Online Retail II",
            "creator": "Daqing Chen",
            "citation": ("Chen, D. (2012). Online Retail II. UCI Machine Learning Repository."),
            "doi": DATASET_DOI,
            "source_url": DATASET_URL,
            "license": "CC BY 4.0",
            "source_file_sha256": sha256_file(workbook),
            "worksheets": worksheet_names,
            "preprocessing": (
                "Exclude cancellation invoices and non-positive quantities; ignore rows "
                "with missing/blank StockCode or invalid date/quantity; aggregate positive "
                "quantities by StockCode and day; fill no-sale days with zero."
            ),
        },
        "configuration": {
            "initial_train_size_days": config.initial_train_size,
            "horizon_days": config.horizon,
            "origin_step_days": config.step,
            "season_length_days": config.season_length,
            "quantile_levels": list(config.quantile_levels),
            "coverage_levels": list(config.coverage_levels),
            "seed": config.seed,
            "max_skus_per_cohort": max_skus_per_cohort,
            "cohort_assignment_window_days": 180,
            "cohort_counts": cohort_counts,
            "lead_time_calibration": {
                "lead_times_days": [7, 14],
                "bootstrap_samples": 250,
                "minimum_calibration_paths": 5,
                "method": "prequential residual-path calibration using strictly earlier non-overlapping paths",
            },
        },
        "panel": {
            "start_date": str(panel.get_column("timestamp").min()),
            "end_date": str(panel.get_column("timestamp").max()),
            "calendar_days": panel.get_column("timestamp").n_unique(),
            "series_count": panel.get_column("series_id").n_unique(),
            "dataset_fingerprints_by_cohort": fingerprints,
        },
        "macro_summary": macro_summary,
        "per_series_fold_summary": per_series_summary,
        "skipped_series": skipped,
        "lead_time_calibration": {
            "macro_summary": _summarize_lead_time_calibration(calibration_per_series),
            "per_series": calibration_per_series,
            "skipped": calibration_skipped,
            "interpretation": (
                "Each lead-time target is calibrated only from strictly earlier completed, "
                "non-overlapping residual paths. Forecast origins overlap across the full "
                "prequential sequence and are not independent statistical observations. "
                "No calibration parameter is tuned on these outcomes."
            ),
        },
        "interpretation": (
            "Online Retail II is a second UCI release from the same retailer and creator, "
            "with an expanded two-year period. It is useful for larger and intermittent-SKU "
            "evaluation but is not an independent retailer. The UCI Electricity benchmark "
            "provides cross-domain multi-series evidence. Neither dataset alone proves "
            "generalization to arbitrary retailers or inventory savings."
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
    parser.add_argument("workbook", type=Path, help="Path to UCI online_retail_II.xlsx")
    parser.add_argument("--max-skus-per-cohort", type=int, default=20)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/uci-online-retail-ii-benchmark.json"),
    )
    args = parser.parse_args()
    result = run_benchmark(
        args.workbook,
        max_skus_per_cohort=args.max_skus_per_cohort,
        output=args.output,
    )
    print(
        json.dumps(
            {
                "rolling_origin_macro_summary": result["macro_summary"],
                "lead_time_calibration_macro_summary": result["lead_time_calibration"][
                    "macro_summary"
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
