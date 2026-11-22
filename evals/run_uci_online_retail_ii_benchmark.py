"""Run a second retail benchmark on the UCI Online Retail II workbook."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import cast

import polars as pl

from run_uci_online_retail_benchmark import (
    COHORTS,
    build_cohort_panel,
    prepare_daily_demand,
)

from demand_forecast_kit.backtesting import BacktestConfig, run_backtest
from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter
from demand_forecast_kit.models.statistical import CrostonAdapter, TSBAdapter


DATASET_DOI = "https://doi.org/10.24432/C5CG6D"
DATASET_URL = "https://archive.ics.uci.edu/dataset/502/online+retail+ii"


def sha256_file(path: Path) -> str:
    """Hash the original workbook in bounded memory."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
                        "interval_coverages": {
                            str(level): value for level, value in item.interval_coverages.items()
                        },
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
                            str(level): value
                            for level, value in item.interval_coverages.items()
                        },
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
        "schema_version": 1,
        "benchmark": "uci-online-retail-ii-rolling-origin",
        "provenance": {
            "dataset": "UCI Online Retail II",
            "creator": "Daqing Chen",
            "citation": (
                "Chen, D. (2012). Online Retail II. UCI Machine Learning Repository."
            ),
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
    print(json.dumps(result["macro_summary"], indent=2))


if __name__ == "__main__":
    main()
