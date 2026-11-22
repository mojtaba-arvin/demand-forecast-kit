import pytest

from demand_forecast_kit.models.base import ForecastAdapter
from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter


def test_seasonal_naive_satisfies_adapter_protocol() -> None:
    adapter: ForecastAdapter = SeasonalNaiveAdapter(season_length=3)
    assert adapter.model_id == "seasonal-naive"
    assert adapter.model_version == "0.1.0"


def test_seasonal_naive_returns_reproducible_monotone_quantiles() -> None:
    adapter = SeasonalNaiveAdapter(season_length=3)
    history = [10, 12, 14, 11, 13, 15, 12, 14, 16]

    first = adapter.predict(
        "sku-1", history, horizon=5, quantile_levels=(0.9, 0.1, 0.5), seed=7
    )
    second = adapter.predict(
        "sku-1", history, horizon=5, quantile_levels=(0.1, 0.5, 0.9), seed=7
    )

    assert first == second
    assert first.horizon == 5
    assert first.quantiles[0.5] == (13.0, 15.0, 17.0, 13.0, 15.0)
    assert first.quantiles[0.1] == (13.0, 15.0, 17.0, 13.0, 15.0)


def test_seasonal_naive_interpolates_empirical_residual_quantiles() -> None:
    forecast = SeasonalNaiveAdapter(season_length=3).predict(
        "sku-1",
        [4, 3, 5, 8, 5, 10, 6, 9, 8],
        horizon=3,
        quantile_levels=(0.25, 0.75),
    )

    assert forecast.quantiles[0.25] == (5.0, 8.0, 7.0)
    assert forecast.quantiles[0.75] == (10.0, 13.0, 12.0)


def test_seasonal_naive_handles_short_history_and_zero_floor() -> None:
    forecast = SeasonalNaiveAdapter(season_length=7).predict(
        "sku-1", [0.0, 2.0], horizon=3, quantile_levels=(0.1, 0.9)
    )

    assert forecast.quantiles[0.1] == (0.0, 2.0, 0.0)
    assert forecast.quantiles[0.9] == (0.0, 2.0, 0.0)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"history": [], "horizon": 1, "quantile_levels": (0.5,)}, "history"),
        ({"history": [-1], "horizon": 1, "quantile_levels": (0.5,)}, "non-negative"),
        ({"history": [float("nan")], "horizon": 1, "quantile_levels": (0.5,)}, "finite"),
        ({"history": [1], "horizon": 0, "quantile_levels": (0.5,)}, "horizon"),
        ({"history": [1], "horizon": 1, "quantile_levels": ()}, "unique levels"),
        ({"history": [1], "horizon": 1, "quantile_levels": (0.5, 0.5)}, "unique levels"),
        ({"history": [1], "horizon": 1, "quantile_levels": (1.0,)}, "quantile levels"),
        ({"history": [1], "horizon": 1, "quantile_levels": (0.5,), "seed": -1}, "seed"),
    ],
)
def test_seasonal_naive_rejects_invalid_inputs(
    kwargs: dict[str, object], message: str
) -> None:
    adapter = SeasonalNaiveAdapter()
    with pytest.raises(ValueError, match=message):
        adapter.predict("sku", **kwargs)  # type: ignore[arg-type]


def test_seasonal_naive_rejects_invalid_season_length_and_horizon() -> None:
    with pytest.raises(ValueError, match="season_length"):
        SeasonalNaiveAdapter(season_length=0)
    with pytest.raises(ValueError, match="season_length"):
        SeasonalNaiveAdapter(season_length=1.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="horizon"):
        SeasonalNaiveAdapter().predict(
            "sku", [1.0], horizon=1.5, quantile_levels=(0.5,)  # type: ignore[arg-type]
        )
