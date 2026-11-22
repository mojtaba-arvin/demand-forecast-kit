"""Preparation adapter for the independent UCI electricity load benchmark."""

from __future__ import annotations

from pathlib import Path
import polars as pl

UCI_ELECTRICITY_DOI = "https://doi.org/10.24432/C58C86"
UCI_ELECTRICITY_SOURCE = "https://archive.ics.uci.edu/ml/machine-learning-databases/00321/LD2011_2014.txt.zip"


def prepare_uci_electricity(
    source: str | Path,
    output: str | Path,
) -> dict[str, int | str]:
    """Convert 15-minute UCI client loads into daily kWh demand histories.

    The source records kW at 15-minute intervals. Dividing each observation by
    four converts it to kWh; daily aggregation then sums those energy values.
    Portuguese local-time labels are preserved as timezone-naive timestamps
    because the source does not provide UTC offsets. DST-adjusted source days
    are not normalized to a synthetic 96-row calendar.
    """
    input_path = Path(source)
    output_path = Path(output)
    if not input_path.is_file():
        raise FileNotFoundError(input_path)

    frame = pl.scan_csv(
        input_path,
        separator=";",
        decimal_comma=True,
        infer_schema_length=1000,
        try_parse_dates=False,
    )
    names = frame.collect_schema().names()
    if len(names) < 2:
        raise ValueError("UCI electricity source must contain a timestamp and client columns")
    timestamp_column = names[0]
    client_columns = names[1:]
    if len(client_columns) != 370:
        raise ValueError(f"expected 370 client series, found {len(client_columns)}")

    long = (
        frame.select(
            pl.col(timestamp_column)
            .cast(pl.String, strict=False)
            .str.strptime(pl.Datetime, format="%Y-%m-%d %H:%M:%S", strict=True)
            .alias("timestamp"),
            *[pl.col(name).cast(pl.Float64, strict=False).alias(name) for name in client_columns],
        )
        .unpivot(
            on=client_columns,
            index=["timestamp"],
            variable_name="series_id",
            value_name="kw",
        )
        .with_columns(
            (pl.col("kw") / 4.0).alias("quarter_hour_kwh"),
            pl.col("timestamp").dt.date().alias("day"),
        )
    )
    invalid = (
        long.filter(
            pl.col("timestamp").is_null()
            | pl.col("kw").is_null()
            | ~pl.col("kw").is_finite()
            | (pl.col("kw") < 0.0)
        )
        .select(pl.len())
        .collect()
        .item()
    )
    if invalid:
        raise ValueError(f"UCI electricity source contains {invalid} invalid observations")

    daily = (
        long.group_by(["series_id", "day"])
        .agg(pl.col("quarter_hour_kwh").sum().alias("demand"))
        .rename({"day": "timestamp"})
        .sort(["series_id", "timestamp"])
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    daily.sink_parquet(output_path)
    summary = (
        daily.select(
            pl.len().alias("row_count"),
            pl.col("series_id").n_unique().alias("series_count"),
            pl.col("timestamp").min().alias("start_date"),
            pl.col("timestamp").max().alias("end_date"),
        )
        .collect()
        .row(0, named=True)
    )
    return {
        "row_count": int(summary["row_count"]),
        "series_count": int(summary["series_count"]),
        "start_date": str(summary["start_date"]),
        "end_date": str(summary["end_date"]),
        "output": str(output_path),
    }
