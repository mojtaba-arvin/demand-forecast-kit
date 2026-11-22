"""Framework-independent model adapter protocol."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from demand_forecast_kit.contracts import QuantileForecast


class ForecastAdapter(Protocol):
    """Contract implemented by every forecasting model integration."""

    @property
    def model_id(self) -> str:
        """Stable model identifier used in run metadata."""
        ...

    @property
    def model_version(self) -> str:
        """Adapter/model version used in run metadata."""
        ...

    def predict(
        self,
        series_id: str,
        history: Sequence[float],
        *,
        horizon: int,
        quantile_levels: Sequence[float],
        seed: int,
    ) -> QuantileForecast:
        """Return marginal demand quantiles for the requested horizon."""
        ...
