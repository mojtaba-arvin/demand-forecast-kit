# SPDX-FileCopyrightText: 2026 Mojtaba Arvin
# SPDX-License-Identifier: MIT
"""Run an opt-in, reproducible calibration benchmark on UCI Online Retail."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from demand_forecast_kit.backtesting import BacktestConfig, run_backtest
from demand_forecast_kit.lead_time import backtest_lead_time_calibration
from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter
from demand_forecast_kit.models.statistical import CrostonAdapter, TSBAdapter

DATASET_DOI = "https://doi.org/10.24432/C5BW33"
DATASET_URL = "https://archive.ics.uci.edu/dataset/352/online-retail"
QUANTILES = (0.1, 0.5, 0.9)
LEAD_TIMES = (7, 14)
COHORTS = ("dense", "intermittent", "very-intermittent")


def sha256_file(path: Path) -> str:
    """Hash the original source file without loading it into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_daily_demand(transactions: pl.DataFrame) -> pl.DataFrame:
    """Aggregate positive, non-cancelled invoice quantities to SKU/day demand.

    Returns are deliberately excluded rather than netted against sales: this
    benchmark measures gross outbound unit demand, not net accounting movement.
    """
    required = {"InvoiceNo", "StockCode", "Quantity", "InvoiceDate"}
    missing = sorted(required - set(transactions.columns))
    if missing:
        raise ValueError(f"UCI workbook is missing columns: {', '.join(missing)}")

    normalized = transactions.select(
        pl.col("InvoiceNo").cast(pl.String, strict=False).alias("invoice_no"),
        pl.col("StockCode").cast(pl.String, strict=False).str.strip_chars().alias("series_id"),
        pl.col("Quantity").cast(pl.Float64, strict=False).alias("quantity"),
        pl.col("InvoiceDate").cast(pl.Datetime, strict=False).dt.date().alias("day"),
    )
    sales = normalized.filter(
        pl.col("invoice_no").is_not_null()
        & ~pl.col("invoice_no").str.to_uppercase().str.starts_with("C")
        & pl.col("series_id").is_not_null()
        & (pl.col("series_id") != "")
        & pl.col("quantity").is_finite()
        & (pl.col("quantity") > 0.0)
        & pl.col("day").is_not_null()
    )
    if sales.is_empty():
        raise ValueError("no valid positive, non-cancelled sales remain after preprocessing")

    return (
        sales.group_by(["series_id", "day"])
        .agg(pl.col("quantity").sum().alias("demand"))
        .sort(["series_id", "day"])
    )


def build_cohort_panel(
    daily: pl.DataFrame,
    *,
    max_skus_per_cohort: int = 10,
) -> tuple[pl.DataFrame, dict[str, int]]:
    """Create complete daily histories for deterministic SKU-frequency cohorts."""
    if type(max_skus_per_cohort) is not int or max_skus_per_cohort < 1:
        raise ValueError("max_skus_per_cohort must be a positive integer")
    if daily.is_empty():
        raise ValueError("daily demand must not be empty")

    first_day = daily.get_column("day").min()
    last_day = daily.get_column("day").max()
    if first_day is None or last_day is None:
        raise ValueError("daily demand must contain valid dates")
    day_count = (last_day - first_day).days + 1
    summary = (
        daily.group_by("series_id")
        .agg(pl.len().alias("active_days"))
        .with_columns((pl.col("active_days") / day_count).alias("activity_rate"))
        .filter(pl.col("active_days") >= 8)
    )

    selected: dict[str, list[str]] = {}
    for cohort in COHORTS:
        if cohort == "dense":
            candidates = summary.filter(pl.col("activity_rate") >= 0.5)
        elif cohort == "intermittent":
            candidates = summary.filter(
                (pl.col("activity_rate") >= 0.05) & (pl.col("activity_rate") < 0.5)
            )
        else:
            candidates = summary.filter(pl.col("activity_rate") < 0.05)

        # Stable hash ordering avoids choosing SKUs by volume or source row order.
        ranked = sorted(
            candidates.get_column("series_id").to_list(),
            key=lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest(),
        )
        selected[cohort] = ranked[:max_skus_per_cohort]

    selected_ids = [series_id for cohort in COHORTS for series_id in selected[cohort]]
    if not selected_ids:
        raise ValueError("no SKUs meet the minimum activity threshold")

    calendar = pl.DataFrame(
        {"day": [first_day + timedelta(days=offset) for offset in range(day_count)]}
    )
    identifiers = pl.DataFrame({"series_id": selected_ids})
    panel = (
        identifiers.join(calendar, how="cross")
        .join(daily.filter(pl.col("series_id").is_in(selected_ids)), on=["series_id", "day"], how="left")
        .with_columns(pl.col("demand").fill_null(0.0))
        .rename({"day": "timestamp"})
        .sort(["series_id", "timestamp"])
    )
    cohort_by_id = {
        series_id: cohort for cohort in COHORTS for series_id in selected[cohort]
    }
    panel = panel.with_columns(
        pl.col("series_id").replace_strict(cohort_by_id).alias("cohort")
    )
    return panel, {cohort: len(selected[cohort]) for cohort in COHORTS}


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
        quantile_levels=QUANTILES,
        coverage_levels=(0.8,),
        seed=42,
    )

    results: list[dict[str, object]] = []
    skipped: list[dict[str, str]] = []
    for cohort in COHORTS:
        cohort_panel = panel.filter(pl.col("cohort") == cohort).drop("cohort")
        if cohort_panel.is_empty():
            continue
        report = run_backtest(cohort_panel, adapters, config)
        for series_id in cohort_panel.get_column("series_id").unique().sort().to_list():
            for adapter in adapters:
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
                    results.append(
                        {
                            "cohort": cohort,
                            "series_id": series_id,
                            "model_id": adapter.model_id,
                            "lead_time": lead_time,
                            "origin_count": diagnostic.origin_count,
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
                "mean_origin_count": sum(int(item["origin_count"]) for item in items) / len(items),
                "macro_quantile_coverage": {
                    level: sum(float(item["quantile_coverage"][level]) for item in items) / len(items)
                    for level in ("0.1", "0.5", "0.9")
                },
                "macro_mean_pinball_loss": {
                    level: sum(float(item["mean_pinball_loss"][level]) for item in items) / len(items)
                    for level in ("0.1", "0.5", "0.9")
                },
                "macro_interval_coverage": {
                    "0.8": sum(float(item["interval_coverage"]["0.8"]) for item in items) / len(items)
                },
            }
        )

    payload: dict[str, object] = {
        "schema_version": 1,
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
            "initial_train_size_days": 180,
            "forecast_horizon_days": 14,
            "origin_step_days": 7,
            "lead_times_days": list(LEAD_TIMES),
            "quantile_levels": list(QUANTILES),
            "bootstrap_samples": 250,
            "minimum_calibration_paths": 5,
            "seed": 42,
            "max_skus_per_cohort": max_skus_per_cohort,
        },
        "panel": {
            "start_date": str(panel.get_column("timestamp").min().date()),
            "end_date": str(panel.get_column("timestamp").max().date()),
            "calendar_days": panel.get_column("timestamp").n_unique(),
            "sku_counts": cohort_counts,
            "selected_series_count": panel.get_column("series_id").n_unique(),
            "panel_fingerprint": report.dataset_fingerprint if results else None,
        },
        "macro_summary": macro_summary,
        "per_series_results": results,
        "skipped_evaluations": skipped,
        "interpretation": (
            "Macro-averages weight each SKU equally within its cohort. Results are specific to "
            "this historical retailer and preprocessing policy; they are not universal accuracy "
            "claims or evidence of inventory savings. The SKU sample is a deterministic hash "
            "sample within each activity-frequency cohort."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
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
