"""CSV/Parquet scanning and explicit demand-history quality checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import isfinite
from pathlib import Path
from statistics import median

import polars as pl


@dataclass(frozen=True, slots=True)
class DataColumns:
    """Source column names mapped to the canonical history contract."""

    series_id: str = "series_id"
    timestamp: str = "timestamp"
    demand: str = "demand"

    def __post_init__(self) -> None:
        names = (self.series_id, self.timestamp, self.demand)
        if any(not name.strip() for name in names):
            raise ValueError("column names must not be blank")
        if len(set(names)) != len(names):
            raise ValueError("series_id, timestamp, and demand columns must be distinct")


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    """Aggregate validation results; no rows are silently discarded."""

    row_count: int
    series_count: int
    null_values: int
    duplicate_keys: int
    negative_demand: int
    non_finite_demand: int
    empty_series_ids: int

    @property
    def issues(self) -> tuple[str, ...]:
        """Return human-readable data defects."""
        issues: list[str] = []
        if self.row_count == 0:
            issues.append("history is empty")
        if self.null_values:
            issues.append(f"{self.null_values} required values are null or invalid")
        if self.duplicate_keys:
            issues.append(f"{self.duplicate_keys} duplicate series/timestamp keys")
        if self.negative_demand:
            issues.append(f"{self.negative_demand} negative demand values")
        if self.non_finite_demand:
            issues.append(f"{self.non_finite_demand} non-finite demand values")
        if self.empty_series_ids:
            issues.append(f"{self.empty_series_ids} blank series identifiers")
        return tuple(issues)

    @property
    def is_valid(self) -> bool:
        """Whether the scanned history satisfies the required contract."""
        return not self.issues


def scan_history(
    path: str | Path,
    *,
    columns: DataColumns = DataColumns(),
) -> pl.LazyFrame:
    """Scan a CSV or Parquet file and select canonical required columns."""
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".csv":
        frame = pl.scan_csv(source, try_parse_dates=True)
    elif suffix in {".parquet", ".pq"}:
        frame = pl.scan_parquet(source)
    else:
        raise ValueError("input file must have a .csv, .parquet, or .pq extension")

    schema = frame.collect_schema()
    available = set(schema.names())
    required = (columns.series_id, columns.timestamp, columns.demand)
    missing = tuple(name for name in required if name not in available)
    if missing:
        raise ValueError(f"missing required input columns: {', '.join(missing)}")
    if getattr(schema[columns.timestamp], "time_zone", None) is not None:
        raise ValueError(
            "timezone-aware timestamps are not supported; normalize timestamps "
            "to one timezone before scanning"
        )

    return frame.select(
        pl.col(columns.series_id).cast(pl.String, strict=False).alias("series_id"),
        pl.col(columns.timestamp).cast(pl.Datetime, strict=False).alias("timestamp"),
        pl.col(columns.demand).cast(pl.Float64, strict=False).alias("demand"),
    )


def validate_history(frame: pl.DataFrame | pl.LazyFrame) -> DataQualityReport:
    """Validate required canonical fields and return aggregate quality counts."""
    lazy = frame.lazy() if isinstance(frame, pl.DataFrame) else frame
    schema = lazy.collect_schema()
    available = set(schema.names())
    required = {"series_id", "timestamp", "demand"}
    missing = sorted(required - available)
    if missing:
        raise ValueError(f"missing canonical columns: {', '.join(missing)}")
    if getattr(schema["timestamp"], "time_zone", None) is not None:
        raise ValueError(
            "timezone-aware timestamps are not supported; normalize timestamps "
            "to one timezone before validation"
        )

    normalized = lazy.select(
        pl.col("series_id").cast(pl.String, strict=False).alias("series_id"),
        pl.col("timestamp").cast(pl.Datetime, strict=False).alias("timestamp"),
        pl.col("demand").cast(pl.Float64, strict=False).alias("demand"),
    )
    summary = (
        normalized.select(
            pl.len().alias("row_count"),
            pl.col("series_id").n_unique().alias("series_count"),
            (
                pl.col("series_id").null_count()
                + pl.col("timestamp").null_count()
                + pl.col("demand").null_count()
            ).alias("null_values"),
            (pl.col("demand") < 0.0).fill_null(False).sum().alias("negative_demand"),
            (~pl.col("demand").is_finite()).fill_null(False).sum().alias("non_finite_demand"),
            pl.col("series_id")
            .str.strip_chars()
            .eq("")
            .fill_null(False)
            .sum()
            .alias("empty_series_ids"),
        )
        .collect()
        .row(0, named=True)
    )

    duplicate_keys = (
        normalized.group_by(["series_id", "timestamp"])
        .len()
        .filter(pl.col("len") > 1)
        .select(pl.len().alias("duplicate_keys"))
        .collect()
        .item()
    )

    return DataQualityReport(
        row_count=int(summary["row_count"]),
        series_count=int(summary["series_count"]),
        null_values=int(summary["null_values"]),
        duplicate_keys=int(duplicate_keys),
        negative_demand=int(summary["negative_demand"]),
        non_finite_demand=int(summary["non_finite_demand"]),
        empty_series_ids=int(summary["empty_series_ids"]),
    )


def count_missing_periods(
    frame: pl.DataFrame,
    *,
    interval: timedelta = timedelta(days=1),
) -> dict[str, int]:
    """Count absent regular timestamps per series without inventing zero-demand rows.

    This diagnostic is deliberately separate from validation: a missing date
    may mean no sales, a data outage, or a calendar closure. Callers must decide
    whether a missing period represents zero demand before filling it.
    """
    if interval <= timedelta(0):
        raise ValueError("interval must be positive")
    required = {"series_id", "timestamp"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"missing canonical columns: {', '.join(missing)}")

    counts: dict[str, int] = {}
    for series in frame.partition_by("series_id", maintain_order=True):
        series_id = str(series["series_id"][0])
        timestamps = series.get_column("timestamp").drop_nulls().sort().to_list()
        if len(timestamps) < 2:
            counts[series_id] = 0
            continue
        absent = 0
        for previous, current in zip(timestamps, timestamps[1:], strict=True):
            if isinstance(previous, date) and not isinstance(previous, datetime):
                previous = datetime.combine(previous, datetime.min.time())
            if isinstance(current, date) and not isinstance(current, datetime):
                current = datetime.combine(current, datetime.min.time())
            if not isinstance(previous, datetime) or not isinstance(current, datetime):
                raise ValueError("timestamp values must be dates or datetimes")
            if previous.tzinfo is not None or current.tzinfo is not None:
                raise ValueError("timezone-aware timestamps must be normalized before diagnostics")
            gap = current - previous
            steps, remainder = divmod(gap, interval)
            if remainder:
                raise ValueError("timestamps do not align to the requested interval")
            absent += max(0, steps - 1)
        counts[series_id] = absent
    return dict(sorted(counts.items()))


def count_demand_outliers(
    frame: pl.DataFrame,
    *,
    threshold: float = 3.5,
) -> dict[str, int]:
    """Count robust median/MAD outliers per series without altering observations.

    Uses the modified z-score 0.6745 * (value - median) / MAD. If MAD is zero,
    values differing from the median are flagged; constant series have no
    outliers. This is a review signal, not an instruction to clip or delete data.
    """
    if type(threshold) not in (int, float) or not isfinite(threshold) or threshold <= 0.0:
        raise ValueError("threshold must be finite and positive")
    required = {"series_id", "demand"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"missing canonical columns: {', '.join(missing)}")

    results: dict[str, int] = {}
    for series in frame.partition_by("series_id", maintain_order=True):
        series_id = str(series["series_id"][0])
        values = [float(value) for value in series.get_column("demand").to_list()]
        if not values or any(not isfinite(value) for value in values):
            raise ValueError("demand must contain finite values")
        median_value = median(values)
        mad = median([abs(value - median_value) for value in values])
        if mad == 0.0:
            count = sum(value != median_value for value in values)
        else:
            count = sum(abs(0.6745 * (value - median_value) / mad) > threshold for value in values)
        results[series_id] = count
    return dict(sorted(results.items()))
