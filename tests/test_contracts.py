import pytest

from demand_forecast_kit.contracts import QuantileForecast


def test_quantile_forecast_accepts_ordered_horizons() -> None:
    forecast = QuantileForecast(
        "sku-1",
        {0.9: (12.0, 14.0), 0.1: (5.0, 7.0), 0.5: (9.0, 10.0)},
    )

    assert forecast.horizon == 2
    assert tuple(forecast.quantiles) == (0.1, 0.5, 0.9)
    assert forecast.quantiles[0.5] == (9.0, 10.0)


@pytest.mark.parametrize(
    ("series_id", "quantiles", "message"),
    [
        (" ", {0.5: (1.0,)}, "series_id"),
        ("sku", {}, "at least one"),
        ("sku", {0.0: (1.0,)}, "quantile levels"),
        ("sku", {float("nan"): (1.0,)}, "quantile levels"),
        ("sku", {0.5: ()}, "at least one horizon"),
        ("sku", {0.5: (1.0,), 0.9: (1.0, 2.0)}, "same forecast horizon"),
        ("sku", {0.5: (-1.0,)}, "non-negative"),
        ("sku", {0.5: (float("inf"),)}, "finite"),
        ("sku", {0.1: (8.0,), 0.9: (4.0,)}, "non-decreasing"),
        ("sku", {"0.5": (1.0,), 0.5: (2.0,)}, "unique"),
    ],
)
def test_quantile_forecast_rejects_invalid_contracts(
    series_id: str, quantiles: dict[float, tuple[float, ...]], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        QuantileForecast(series_id, quantiles)


def test_quantile_forecast_is_immutable() -> None:
    source = {0.5: (3.0,)}
    forecast = QuantileForecast("sku-1", source)
    source[0.5] = (9.0,)

    assert forecast.quantiles[0.5] == (3.0,)
