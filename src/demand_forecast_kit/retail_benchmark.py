"""Shared preprocessing and frozen cohort selection for UCI retail benchmarks."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path

import polars as pl


INITIAL_TRAIN_SIZE = 180
COHORTS = ("dense", "intermittent", "very-intermittent")


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
    if invoice_column is None:
        missing.append("InvoiceNo or Invoice")
    if missing:
        raise ValueError(f"UCI workbook is missing columns: {', '.join(missing)}")

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

    first_day = daily.get_column("day").min()
    last_day = daily.get_column("day").max()
    if first_day is None or last_day is None:
        raise ValueError("daily demand must contain valid dates")
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
