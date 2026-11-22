"""Validated public data contracts shared by forecasting adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class QuantileForecast:
    """Quantile forecasts for one series, with one value per horizon step."""

    series_id: str
    quantiles: Mapping[float, tuple[float, ...]]

    def __post_init__(self) -> None:
        if not self.series_id.strip():
            raise ValueError("series_id must not be blank")
        if not self.quantiles:
            raise ValueError("at least one quantile level is required")

        normalized: dict[float, tuple[float, ...]] = {}
        for raw_level, raw_values in self.quantiles.items():
            level = float(raw_level)
            if not isfinite(level) or not 0.0 < level < 1.0:
                raise ValueError("quantile levels must be finite and strictly between 0 and 1")
            if level in normalized:
                raise ValueError("quantile levels must be unique")
            values = tuple(float(value) for value in raw_values)
            if not values:
                raise ValueError("each quantile must contain at least one horizon value")
            if any(not isfinite(value) or value < 0.0 for value in values):
                raise ValueError("forecast values must be finite and non-negative")
            normalized[level] = values

        lengths = {len(values) for values in normalized.values()}
        if len(lengths) != 1:
            raise ValueError("all quantiles must have the same forecast horizon")

        ordered = dict(sorted(normalized.items()))
        levels = tuple(ordered)
        for step in range(next(iter(lengths))):
            step_values = tuple(ordered[level][step] for level in levels)
            if any(left > right for left, right in zip(step_values, step_values[1:], strict=False)):
                raise ValueError("forecast values must be non-decreasing across quantile levels")

        object.__setattr__(self, "quantiles", MappingProxyType(ordered))

    @property
    def horizon(self) -> int:
        """Return the number of forecast steps."""
        return len(next(iter(self.quantiles.values())))
