"""SKU/location hierarchical rollups with collision-safe series identifiers."""

from __future__ import annotations

import json

import polars as pl


def _identifier(level: str, *parts: str) -> str:
    """Encode hierarchy keys without delimiter-collision ambiguity."""
    return f"{level}:{json.dumps(parts, ensure_ascii=False, separators=(',', ':'))}"


def build_hierarchical_history(
    frame: pl.DataFrame,
    *,
    sku_column: str = "sku_id",
    location_column: str = "location_id",
    timestamp_column: str = "timestamp",
    demand_column: str = "demand",
) -> pl.DataFrame:
    """Return leaf, SKU-total, and location-total histories.

    Leaf series have two parent aggregate IDs (SKU and location), so the output
    represents a hierarchy DAG rather than forcing a misleading single-parent
    tree. Duplicate SKU/location/timestamp observations are rejected instead
    of silently summed. The output includes canonical series_id/timestamp/
    demand columns plus hierarchy_level and parent_series_ids.
    """
    required = {sku_column, location_column, timestamp_column, demand_column}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"missing hierarchy columns: {', '.join(missing)}")

    normalized = frame.select(
        pl.col(sku_column).cast(pl.String, strict=False).alias("sku_id"),
        pl.col(location_column).cast(pl.String, strict=False).alias("location_id"),
        pl.col(timestamp_column).cast(pl.Datetime, strict=False).alias("timestamp"),
        pl.col(demand_column).cast(pl.Float64, strict=False).alias("demand"),
    )
    if normalized.is_empty():
        raise ValueError("hierarchical history must contain at least one row")
    if normalized.select(
        pl.any_horizontal(
            pl.col("sku_id").is_null() | (pl.col("sku_id").str.strip_chars() == ""),
            pl.col("location_id").is_null() | (pl.col("location_id").str.strip_chars() == ""),
            pl.col("timestamp").is_null(),
            pl.col("demand").is_null() | ~pl.col("demand").is_finite() | (pl.col("demand") < 0),
        ).any()
    ).item():
        raise ValueError("hierarchy keys, timestamps, and demand must be valid and finite")
    if normalized.select(
        pl.struct(["sku_id", "location_id", "timestamp"]).is_duplicated().any()
    ).item():
        raise ValueError("duplicate SKU/location/timestamp observations are not allowed")

    leaves = normalized.with_columns(
        pl.struct(["sku_id", "location_id"])
        .map_elements(
            lambda item: _identifier("sku-location", item["sku_id"], item["location_id"]),
            return_dtype=pl.String,
        )
        .alias("series_id"),
        pl.struct(["sku_id", "location_id"])
        .map_elements(
            lambda item: [
                _identifier("sku", item["sku_id"]),
                _identifier("location", item["location_id"]),
            ],
            return_dtype=pl.List(pl.String),
        )
        .alias("parent_series_ids"),
        pl.lit("sku-location").alias("hierarchy_level"),
    ).select("series_id", "parent_series_ids", "timestamp", "demand", "hierarchy_level")

    sku_totals = (
        normalized.group_by("sku_id", "timestamp")
        .agg(pl.col("demand").sum())
        .with_columns(
            pl.col("sku_id")
            .map_elements(lambda value: _identifier("sku", value), return_dtype=pl.String)
            .alias("series_id"),
            pl.lit([], dtype=pl.List(pl.String)).alias("parent_series_ids"),
            pl.lit("sku").alias("hierarchy_level"),
        )
        .select("series_id", "parent_series_ids", "timestamp", "demand", "hierarchy_level")
    )
    location_totals = (
        normalized.group_by("location_id", "timestamp")
        .agg(pl.col("demand").sum())
        .with_columns(
            pl.col("location_id")
            .map_elements(lambda value: _identifier("location", value), return_dtype=pl.String)
            .alias("series_id"),
            pl.lit([], dtype=pl.List(pl.String)).alias("parent_series_ids"),
            pl.lit("location").alias("hierarchy_level"),
        )
        .select("series_id", "parent_series_ids", "timestamp", "demand", "hierarchy_level")
    )
    return pl.concat([leaves, sku_totals, location_totals]).sort(
        ["hierarchy_level", "series_id", "timestamp"]
    )
