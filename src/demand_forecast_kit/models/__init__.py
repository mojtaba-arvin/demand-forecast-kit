"""Forecast model adapters."""

from demand_forecast_kit.models.base import ForecastAdapter
from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter
from demand_forecast_kit.models.statistical import (
    AutoARIMAAdapter,
    AutoETSAdapter,
    CrostonAdapter,
    ThetaAdapter,
    TSBAdapter,
)

__all__ = [
    "AutoARIMAAdapter",
    "AutoETSAdapter",
    "CrostonAdapter",
    "ForecastAdapter",
    "SeasonalNaiveAdapter",
    "ThetaAdapter",
    "TSBAdapter",
]
