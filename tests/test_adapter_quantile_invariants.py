from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter


def test_seasonal_naive_quantiles_are_monotone_for_every_horizon_step() -> None:
    adapter = SeasonalNaiveAdapter(season_length=7)
    forecast = adapter.predict(
        "sku-zero-heavy",
        [0.0, 0.0, 3.0, 0.0, 8.0, 0.0, 1.0] * 4,
        horizon=28,
        quantile_levels=[0.99, 0.1, 0.5, 0.9, 0.01],
        seed=17,
    )

    levels = tuple(forecast.quantiles)
    assert levels == tuple(sorted(levels))
    for step in range(forecast.horizon):
        values = [forecast.quantiles[level][step] for level in levels]
        assert values == sorted(values)


def test_seasonal_naive_all_zero_history_has_valid_nonnegative_intervals() -> None:
    forecast = SeasonalNaiveAdapter().predict(
        "sku-zero",
        [0.0] * 21,
        horizon=14,
        quantile_levels=[0.1, 0.5, 0.9],
        seed=0,
    )

    assert all(value == 0.0 for values in forecast.quantiles.values() for value in values)
