"""Shared preprocessing and frozen cohort selection for UCI retail benchmarks."""

from __future__ import annotations

import hashlib
import math
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast

import polars as pl

INITIAL_TRAIN_SIZE = 180
COHORTS = ("dense", "intermittent", "very-intermittent")
MIN_ACTIVE_DAYS = 8


def _as_date(value: object) -> date:
    if isinstance(value, date):
        return date(value.year, value.month, value.day)
    raise ValueError("daily demand must contain valid dates")


def prepare_daily_demand(transactions: pl.DataFrame) -> pl.DataFrame:
    """Aggregate positive, non-cancelled invoice quantities to SKU/day demand.

    Returns are deliberately excluded rather than netted against sales: this
    benchmark measures gross outbound unit demand, not net accounting movement.
    """
    required = {"StockCode", "Quantity", "InvoiceDate"}
    missing = sorted(required - set(transactions.columns))
    invoice_column = next(
        (name for name in ("InvoiceNo", "Invoice") if name in transactions.columns),
        None,
    )
    if missing:
        raise ValueError(f"UCI workbook is missing columns: {', '.join(missing)}")
    if invoice_column is None:
        raise ValueError("UCI workbook is missing columns: InvoiceNo or Invoice")

    normalized = transactions.select(
        pl.col(invoice_column).cast(pl.String, strict=False).alias("invoice_no"),
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
    cohort_window_days: int = INITIAL_TRAIN_SIZE,
) -> tuple[pl.DataFrame, dict[str, int]]:
    """Create daily histories with cohorts frozen from the initial training window.

    Cohort membership is determined only from the first cohort_window_days
    calendar days. Later observations are retained for backtesting but cannot
    change a series' cohort, preventing evaluation-period information from
    influencing benchmark stratification.
    """
    if type(max_skus_per_cohort) is not int or max_skus_per_cohort < 1:
        raise ValueError("max_skus_per_cohort must be a positive integer")
    if type(cohort_window_days) is not int or cohort_window_days < 1:
        raise ValueError("cohort_window_days must be a positive integer")
    if daily.is_empty():
        raise ValueError("daily demand must not be empty")

    daily = daily.with_columns(pl.col("day").cast(pl.Date, strict=False))
    first_day = _as_date(cast(object, daily.get_column("day").min()))
    last_day = _as_date(cast(object, daily.get_column("day").max()))
    day_count = (last_day - first_day).days + 1
    if day_count < cohort_window_days:
        raise ValueError(
            f"daily demand spans {day_count} calendar days; "
            f"at least {cohort_window_days} are required for cohort assignment"
        )
    cohort_cutoff = first_day + timedelta(days=cohort_window_days)
    cohort_history = daily.filter(pl.col("day") < cohort_cutoff)
    summary = (
        cohort_history.group_by("series_id")
        .agg(pl.len().alias("active_days"))
        .with_columns((pl.col("active_days") / cohort_window_days).alias("activity_rate"))
        .filter(pl.col("active_days") >= MIN_ACTIVE_DAYS)
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

        series_ids = [str(value) for value in candidates.get_column("series_id").to_list()]
        ranked = sorted(
            series_ids,
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
        .join(
            daily.filter(pl.col("series_id").is_in(selected_ids)),
            on=["series_id", "day"],
            how="left",
        )
        .with_columns(pl.col("demand").fill_null(0.0))
        .rename({"day": "timestamp"})
        .sort(["series_id", "timestamp"])
    )
    cohort_by_id = {series_id: cohort for cohort in COHORTS for series_id in selected[cohort]}
    panel = panel.with_columns(pl.col("series_id").replace_strict(cohort_by_id).alias("cohort"))
    return panel, {cohort: len(selected[cohort]) for cohort in COHORTS}


def sha256_file(path: str | Path) -> str:
    """Hash a source dataset in bounded memory for reproducible benchmark manifests."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


M5_DATASET_URL = "https://www.kaggle.com/competitions/m5-forecasting-accuracy/data"
M5_DATASET_LICENSE = "Kaggle competition rules; not a general redistribution license"


def prepare_m5_daily_demand(
    sales_path: str | Path,
    calendar_path: str | Path,
    *,
    max_series_per_cohort: int = 20,
    cohort_window_days: int = INITIAL_TRAIN_SIZE,
) -> tuple[pl.DataFrame, dict[str, int], dict[str, Any]]:
    """Read an authorized local M5 copy and select deterministic item/store histories.

    The M5 sales file is wide (one column per day). Cohorts are frozen from the
    first cohort_window_days only, then a deterministic SHA-256 sample is
    unpivoted to positive daily demand rows; build_cohort_panel reconstructs
    zero-sales dates on the complete calendar. The source files are never
    downloaded or copied
    by this function; callers must obtain them under the Kaggle competition
    rules and keep the raw data outside source control.
    """
    sales_file = Path(sales_path)
    calendar_file = Path(calendar_path)
    if not sales_file.is_file():
        raise FileNotFoundError(sales_file)
    if not calendar_file.is_file():
        raise FileNotFoundError(calendar_file)
    if type(max_series_per_cohort) is not int or max_series_per_cohort < 1:
        raise ValueError("max_series_per_cohort must be a positive integer")
    if type(cohort_window_days) is not int or cohort_window_days < MIN_ACTIVE_DAYS:
        raise ValueError(f"cohort_window_days must be at least {MIN_ACTIVE_DAYS}")

    sales = pl.scan_csv(sales_file, infer_schema_length=1000)
    names = sales.collect_schema().names()
    required = {"id", "item_id", "store_id"}
    missing = sorted(required - set(names))
    if missing:
        raise ValueError(f"M5 sales file is missing columns: {', '.join(missing)}")
    day_columns = sorted(
        (name for name in names if re.fullmatch(r"d_\d+", name)),
        key=lambda name: int(name[2:]),
    )
    if not day_columns or day_columns != [f"d_{index}" for index in range(1, len(day_columns) + 1)]:
        raise ValueError("M5 sales file must contain a contiguous d_1..d_N daily column range")
    if len(day_columns) < cohort_window_days:
        raise ValueError("M5 sales file is shorter than the requested cohort window")

    calendar = (
        pl.read_csv(calendar_file, columns=["d", "date"])
        .select(
            pl.col("d").cast(pl.String).alias("day_id"),
            pl.col("date")
            .cast(pl.String)
            .str.strptime(pl.Date, format="%Y-%m-%d", strict=True)
            .alias("day"),
        )
        .filter(pl.col("day_id").is_in(day_columns))
        .with_columns(pl.col("day_id").str.extract(r"d_(\d+)", 1).cast(pl.Int64).alias("day_index"))
        .sort("day_index")
    )
    calendar_day_count = calendar.get_column("day_id").n_unique()
    if calendar.height != len(day_columns) or calendar_day_count != len(day_columns):
        raise ValueError("M5 calendar must map every sales day column exactly once")
    calendar_dates = calendar.get_column("day").to_list()
    consecutive_days = all(
        (right - left).days == 1
        for left, right in zip(calendar_dates, calendar_dates[1:], strict=False)
    )
    if not consecutive_days:
        raise ValueError("M5 calendar dates must be consecutive and daily")

    series_id_expr = pl.concat_str(
        [pl.col("item_id").cast(pl.String), pl.col("store_id").cast(pl.String)],
        separator="::",
    )
    history_columns = day_columns[:cohort_window_days]
    metadata_source = sales.select("item_id", "store_id", *history_columns).collect()
    dense_threshold = (cohort_window_days + 1) // 2
    intermittent_threshold = (cohort_window_days + 19) // 20
    metadata_rows: list[tuple[str, str, int]] = []
    for row in metadata_source.iter_rows(named=True):
        item_id = str(row["item_id"])
        store_id = str(row["store_id"])
        if not item_id or item_id == "None" or not store_id or store_id == "None":
            raise ValueError("M5 sales file contains a blank item_id or store_id")
        active_days = 0
        for column in history_columns:
            raw_value = row[column]
            value = 0.0 if raw_value is None else float(raw_value)
            if not math.isfinite(value) or value < 0.0:
                raise ValueError("M5 cohort window contains invalid daily sales values")
            active_days += int(value > 0.0)
        if active_days < MIN_ACTIVE_DAYS:
            continue
        if active_days >= dense_threshold:
            cohort = "dense"
        elif active_days >= intermittent_threshold:
            cohort = "intermittent"
        else:
            cohort = "very-intermittent"
        metadata_rows.append((f"{item_id}::{store_id}", cohort, active_days))
    metadata = pl.DataFrame(
        {
            "series_id": [row[0] for row in metadata_rows],
            "cohort": [row[1] for row in metadata_rows],
            "active_days": [row[2] for row in metadata_rows],
        },
        schema={"series_id": pl.String, "cohort": pl.String, "active_days": pl.Int64},
    )
    if metadata.get_column("series_id").n_unique() != metadata.height:
        raise ValueError("M5 sales file contains duplicate item/store series")
    if metadata.is_empty():
        raise ValueError("no M5 item/store series meet the minimum activity threshold")

    selected_by_cohort: dict[str, list[str]] = {}
    for cohort in COHORTS:
        candidates = [
            str(value)
            for value in metadata.filter(pl.col("cohort") == cohort)
            .get_column("series_id")
            .to_list()
        ]
        selected_by_cohort[cohort] = sorted(
            candidates,
            key=lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest(),
        )[:max_series_per_cohort]
    selected_ids = [value for cohort in COHORTS for value in selected_by_cohort[cohort]]
    if not selected_ids:
        raise ValueError("no M5 item/store series were selected")

    selected = (
        sales.filter(series_id_expr.is_in(selected_ids))
        .select("item_id", "store_id", *day_columns)
        .collect()
    )
    if selected.height != len(selected_ids):
        raise ValueError("M5 selected item/store series could not be resolved uniquely")
    long = (
        selected.unpivot(
            on=day_columns,
            index=["item_id", "store_id"],
            variable_name="day_id",
            value_name="demand",
        )
        .with_columns(
            series_id_expr.alias("series_id"),
            pl.col("demand").cast(pl.Float64, strict=False),
        )
        .join(calendar.select("day_id", "day"), on="day_id", how="left")
    )
    invalid_count = (
        long.filter(
            pl.col("day").is_null()
            | pl.col("demand").is_null()
            | ~pl.col("demand").is_finite()
            | (pl.col("demand") < 0.0)
        )
        .select(pl.len())
        .item()
    )
    if invalid_count:
        raise ValueError(f"M5 selected series contain {invalid_count} invalid daily sales values")
    daily = (
        long.filter(pl.col("demand") > 0.0)
        .group_by(["series_id", "day"])
        .agg(pl.col("demand").sum())
        .sort(["series_id", "day"])
    )
    summary = {
        "source": M5_DATASET_URL,
        "license": M5_DATASET_LICENSE,
        "sales_sha256": sha256_file(sales_file),
        "calendar_sha256": sha256_file(calendar_file),
        "series_count": len(selected_ids),
        "day_count": len(day_columns),
        "start_date": str(calendar_dates[0]),
        "end_date": str(calendar_dates[-1]),
        "selected_series_by_cohort": selected_by_cohort,
        "cohort_candidate_counts": {
            cohort: metadata.filter(pl.col("cohort") == cohort).height for cohort in COHORTS
        },
        "selected_active_days": {
            cohort: {
                str(row["series_id"]): int(row["active_days"])
                for row in metadata.filter(pl.col("series_id").is_in(selected_by_cohort[cohort]))
                .select("series_id", "active_days")
                .to_dicts()
            }
            for cohort in COHORTS
        },
    }
    return daily, {cohort: len(selected_by_cohort[cohort]) for cohort in COHORTS}, summary
