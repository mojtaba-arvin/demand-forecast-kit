"""Forecast model adapters."""

from demand_forecast_kit.models.base import ForecastAdapter
from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter

__all__ = ["ForecastAdapter", "SeasonalNaiveAdapter"]
