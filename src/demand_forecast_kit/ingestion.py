"""Deterministic incremental merging for canonical demand history."""

from __future__ import annotations

import polars as pl

_REQUIRED = ("series_id", "timestamp", "demand")


def merge_history_batches(
    existing: pl.DataFrame,
    incoming: pl.DataFrame,
) -> pl.DataFrame:
    """Merge a new batch into history; the incoming row wins duplicate keys.

    Both frames must use the canonical columns. Late-arriving observations are
    retained and corrected observations replace prior values. The function
    performs no implicit aggregation: duplicate resolution is explicitly
    last-write-wins in input order.
    """
    for label, frame in (("existing", existing), ("incoming", incoming)):
        missing = sorted(set(_REQUIRED) - set(frame.columns))
        if missing:
            raise ValueError(f"{label} batch is missing columns: {', '.join(missing)}")

    def normalize(frame: pl.DataFrame) -> pl.DataFrame:
        normalized = frame.select(
            pl.col("series_id").cast(pl.String, strict=False),
            pl.col("timestamp").cast(pl.Datetime, strict=False),
            pl.col("demand").cast(pl.Float64, strict=False),
        )
        invalid = normalized.filter(
            pl.col("series_id").is_null()
            | (pl.col("series_id").str.strip_chars() == "")
            | pl.col("timestamp").is_null()
            | pl.col("demand").is_null()
            | ~pl.col("demand").is_finite()
            | (pl.col("demand") < 0.0)
        )
        if invalid.height:
            raise ValueError("history batches contain invalid keys or demand values")
        return normalized

    old = normalize(existing)
    new = normalize(incoming)
    if new.is_empty():
        return old.sort(["series_id", "timestamp"])
    return (
        pl.concat([old, new], how="vertical")
        .unique(subset=["series_id", "timestamp"], keep="last", maintain_order=True)
        .sort(["series_id", "timestamp"])
    )
