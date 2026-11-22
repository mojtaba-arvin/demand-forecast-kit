"""Seeded synthetic retail demand generator for tests and local evaluation."""

from __future__ import annotations

import random
from datetime import date, timedelta

import polars as pl


def generate_synthetic_history(
    *,
    series_count: int = 4,
    periods: int = 120,
    seed: int = 42,
) -> pl.DataFrame:
    """Generate reproducible daily demand with trend, weekly seasonality, and noise."""
    for name, value in (("series_count", series_count), ("periods", periods)):
        if type(value) is not int or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a non-negative integer")

    rng = random.Random(seed)
    weekly_pattern = (0.78, 0.84, 0.91, 0.98, 1.04, 1.24, 1.21)
    start = date(2024, 1, 1)
    rows: list[dict[str, object]] = []

    for series_index in range(series_count):
        series_id = f"sku-{series_index + 1:04d}"
        base_demand = 18.0 + 4.0 * series_index
        for day_index in range(periods):
            trend = 1.0 + 0.0015 * day_index
            seasonal = weekly_pattern[day_index % len(weekly_pattern)]
            noisy_demand = base_demand * trend * seasonal + rng.gauss(0.0, 1.8)
            rows.append(
                {
                    "series_id": series_id,
                    "timestamp": start + timedelta(days=day_index),
                    "demand": float(max(0, round(noisy_demand))),
                }
            )

    return pl.DataFrame(
        rows,
        schema={
            "series_id": pl.String,
            "timestamp": pl.Date,
            "demand": pl.Float64,
        },
    )
