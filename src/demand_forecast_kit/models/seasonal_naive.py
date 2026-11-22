"""Deterministic seasonal-naive reference adapter."""

from __future__ import annotations

from collections.abc import Sequence
from math import floor, isfinite

from demand_forecast_kit.contracts import QuantileForecast


def _empirical_quantile(values: Sequence[float], probability: float) -> float:
    """Compute a deterministic linearly interpolated empirical quantile."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower_index = floor(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = position - lower_index
    return ordered[lower_index] + (ordered[upper_index] - ordered[lower_index]) * fraction


class SeasonalNaiveAdapter:
    """Repeat the latest seasonal profile and add empirical seasonal residual quantiles.

    This is a lightweight reference baseline. Its marginal intervals are not
    calibrated and it does not model dependence between future horizon steps.
    """

    def __init__(self, season_length: int = 7) -> None:
        if type(season_length) is not int or season_length < 1:
            raise ValueError("season_length must be a positive integer")
        self.season_length = season_length

    @property
    def model_id(self) -> str:
        return "seasonal-naive"

    @property
    def model_version(self) -> str:
        return "0.1.0"

    def predict(
        self,
        series_id: str,
        history: Sequence[float],
        *,
        horizon: int,
        quantile_levels: Sequence[float],
        seed: int = 0,
    ) -> QuantileForecast:
        if type(horizon) is not int or horizon < 1:
            raise ValueError("horizon must be a positive integer")
        if type(seed) is not int or seed < 0:
            raise ValueError("seed must be a non-negative integer")
        values = tuple(float(value) for value in history)
        if not values:
            raise ValueError("history must contain at least one observation")
        if any(not isfinite(value) or value < 0.0 for value in values):
            raise ValueError("history values must be finite and non-negative")

        levels = tuple(float(level) for level in quantile_levels)
        if not levels or len(set(levels)) != len(levels):
            raise ValueError("quantile_levels must contain unique levels")
        if any(not isfinite(level) or not 0.0 < level < 1.0 for level in levels):
            raise ValueError("quantile levels must be finite and strictly between 0 and 1")
        levels = tuple(sorted(levels))

        period = min(self.season_length, len(values))
        residuals = [
            values[index] - values[index - period] for index in range(period, len(values))
        ] or [0.0]
        seasonal_profile = values[-period:]
        baseline = tuple(seasonal_profile[(step - 1) % period] for step in range(1, horizon + 1))

        forecasts = {
            level: tuple(
                max(0.0, point + _empirical_quantile(residuals, level)) for point in baseline
            )
            for level in levels
        }
        return QuantileForecast(series_id=series_id, quantiles=forecasts)
