"""Dependency-free tests for the optional statistical adapter boundary."""

from __future__ import annotations

from typing import NoReturn

import pytest

import demand_forecast_kit.models.statistical as statistical
from demand_forecast_kit import (
    AutoARIMAAdapter,
    AutoETSAdapter,
    CrostonAdapter,
    ThetaAdapter,
    TSBAdapter,
)


def test_statistical_adapters_are_public_without_importing_statsforecast() -> None:
    assert AutoETSAdapter().model_id == "auto-ets"
    assert AutoARIMAAdapter().model_id == "auto-arima"
    assert ThetaAdapter().model_id == "theta"
    assert CrostonAdapter().model_id == "croston-optimized"
    assert TSBAdapter().model_id == "tsb"


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: AutoETSAdapter(season_length=0), "season_length"),
        (lambda: AutoETSAdapter(model="ZZ"), "three-character"),
        (lambda: AutoARIMAAdapter(nmodels=0), "nmodels"),
        (lambda: AutoARIMAAdapter(max_p=-1), "max_p"),
        (lambda: AutoARIMAAdapter(seasonal=1), "booleans"),
        (lambda: ThetaAdapter(season_length=0), "season_length"),
        (lambda: ThetaAdapter(decomposition_type="unknown"), "decomposition_type"),
        (lambda: CrostonAdapter(variant="unknown"), "variant"),
        (lambda: CrostonAdapter(conformal_windows=1), "at least 2"),
        (lambda: TSBAdapter(alpha_d=0.0), "alpha_d"),
        (lambda: TSBAdapter(alpha_p=1.1), "alpha_p"),
    ],
)
def test_invalid_statistical_adapter_configuration_is_rejected(
    factory: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        factory()  # type: ignore[operator]


def test_adapter_validates_input_before_loading_optional_backend() -> None:
    adapter = AutoETSAdapter()
    with pytest.raises(ValueError, match="series_id"):
        adapter.predict(
            " ",
            [1.0, 2.0, 3.0],
            horizon=2,
            quantile_levels=(0.1, 0.5, 0.9),
            seed=1,
        )
    with pytest.raises(ValueError, match="finite and non-negative"):
        adapter.predict(
            "sku",
            [1.0, float("nan")],
            horizon=2,
            quantile_levels=(0.1, 0.5, 0.9),
            seed=1,
        )
    with pytest.raises(ValueError, match="quantile levels"):
        adapter.predict(
            "sku",
            [1.0, 2.0, 3.0],
            horizon=2,
            quantile_levels=(0.0, 0.5, 1.0),
            seed=1,
        )


def test_intermittent_adapter_requires_enough_history_before_backend_import() -> None:
    with pytest.raises(ValueError, match="at least 15"):
        CrostonAdapter().predict(
            "sku",
            [1.0] * 14,
            horizon=7,
            quantile_levels=(0.1, 0.5, 0.9),
            seed=1,
        )


def test_missing_statsforecast_extra_has_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(_: str) -> NoReturn:
        raise ModuleNotFoundError("simulated missing StatsForecast")

    monkeypatch.setattr(statistical, "import_module", unavailable)
    with pytest.raises(ImportError, match=r"demand-forecast-kit\[stats\]"):
        AutoETSAdapter().predict(
            "sku",
            [12.0, 14.0, 11.0, 13.0, 15.0, 14.0, 12.0],
            horizon=2,
            quantile_levels=(0.1, 0.5, 0.9),
            seed=1,
        )
