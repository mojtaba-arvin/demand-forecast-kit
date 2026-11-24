"""Live integration checks for the optional StatsForecast model adapters."""

from __future__ import annotations

from math import sin, tau

import pytest

from demand_forecast_kit.models.statistical import (
    AutoARIMAAdapter,
    AutoETSAdapter,
    CrostonAdapter,
    ThetaAdapter,
    TSBAdapter,
)

pytest.importorskip("statsforecast")


def dense_history() -> tuple[float, ...]:
    return tuple(24.0 + 0.08 * index + 3.0 * sin(tau * index / 7.0) for index in range(84))


def intermittent_history() -> tuple[float, ...]:
    return tuple(0.0 if index % 5 else float(6 + (index % 4) * 3) for index in range(84))


@pytest.mark.parametrize(
    "adapter",
    [
        AutoETSAdapter(season_length=7),
        AutoARIMAAdapter(
            season_length=7,
            max_p=2,
            max_q=2,
            max_P=1,
            max_Q=1,
            max_order=4,
            nmodels=20,
        ),
        ThetaAdapter(season_length=7, decomposition_type="additive"),
    ],
    ids=["auto-ets", "auto-arima", "theta"],
)
def test_native_statistical_models_return_ordered_probabilistic_forecasts(adapter: object) -> None:
    forecast = adapter.predict(  # type: ignore[attr-defined]
        "dense-sku",
        dense_history(),
        horizon=7,
        quantile_levels=(0.05, 0.1, 0.5, 0.9, 0.95),
        seed=2026,
    )

    assert forecast.series_id == "dense-sku"
    assert forecast.horizon == 7
    assert tuple(forecast.quantiles) == (0.05, 0.1, 0.5, 0.9, 0.95)
    for step in range(forecast.horizon):
        values = tuple(forecast.quantiles[level][step] for level in forecast.quantiles)
        assert all(value >= 0.0 for value in values)
        assert tuple(sorted(values)) == values


@pytest.mark.parametrize(
    "adapter",
    [
        CrostonAdapter(variant="classic"),
        CrostonAdapter(variant="optimized"),
        CrostonAdapter(variant="sba"),
        TSBAdapter(alpha_d=0.2, alpha_p=0.15),
    ],
    ids=["croston-classic", "croston-optimized", "croston-sba", "tsb"],
)
def test_intermittent_models_return_conformal_forecasts(adapter: object) -> None:
    forecast = adapter.predict(  # type: ignore[attr-defined]
        "intermittent-sku",
        intermittent_history(),
        horizon=7,
        quantile_levels=(0.1, 0.5, 0.9),
        seed=2026,
    )

    assert forecast.series_id == "intermittent-sku"
    assert forecast.horizon == 7
    assert tuple(forecast.quantiles) == (0.1, 0.5, 0.9)
    assert all(value >= 0.0 for values in forecast.quantiles.values() for value in values)
    for step in range(forecast.horizon):
        values = tuple(forecast.quantiles[level][step] for level in forecast.quantiles)
        assert tuple(sorted(values)) == values
