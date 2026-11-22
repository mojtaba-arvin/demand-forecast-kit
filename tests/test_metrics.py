import pytest

from demand_forecast_kit.metrics import (
    interval_coverage,
    mean_absolute_scaled_error,
    pinball_loss,
    weighted_quantile_loss,
)


def test_pinball_loss_uses_asymmetric_quantile_penalty() -> None:
    assert pinball_loss([1.0, 3.0], [2.0, 2.0], 0.5) == pytest.approx(0.5)
    assert pinball_loss([1.0], [2.0], 0.1) == pytest.approx(0.9)
    assert pinball_loss([3.0], [2.0], 0.9) == pytest.approx(0.9)


def test_pinball_loss_rejects_invalid_arguments() -> None:
    with pytest.raises(ValueError, match="quantile_level"):
        pinball_loss([1.0], [1.0], 1.0)
    with pytest.raises(ValueError, match="empty"):
        pinball_loss([], [], 0.5)
    with pytest.raises(ValueError, match="same length"):
        pinball_loss([1.0], [], 0.5)
    with pytest.raises(ValueError, match="finite"):
        pinball_loss([float("nan")], [1.0], 0.5)


def test_weighted_quantile_loss_is_normalized_across_levels() -> None:
    score = weighted_quantile_loss(
        [1.0, 3.0],
        {0.1: [2.0, 2.0], 0.9: [2.0, 2.0]},
    )
    assert score == pytest.approx(1.0)


def test_weighted_quantile_loss_reports_undefined_zero_demand() -> None:
    assert weighted_quantile_loss([0.0, 0.0], {0.5: [0.0, 0.0]}) is None


def test_weighted_quantile_loss_rejects_invalid_quantiles() -> None:
    with pytest.raises(ValueError, match="at least one"):
        weighted_quantile_loss([1.0], {})
    with pytest.raises(ValueError, match="strictly between"):
        weighted_quantile_loss([1.0], {1.0: [1.0]})
    with pytest.raises(ValueError, match="unique"):
        weighted_quantile_loss([1.0], {"0.5": [1.0], 0.5: [1.0]})
    with pytest.raises(ValueError, match="same length"):
        weighted_quantile_loss([1.0], {0.5: []})
    with pytest.raises(ValueError, match="non-decreasing"):
        weighted_quantile_loss([1.0], {0.1: [3.0], 0.9: [2.0]})


def test_mase_uses_training_seasonal_scale() -> None:
    score = mean_absolute_scaled_error(
        [2.0, 4.0],
        [3.0, 3.0],
        [1.0, 2.0, 3.0, 4.0],
        season_length=1,
    )
    assert score == pytest.approx(1.0)


def test_mase_returns_none_when_scale_is_undefined() -> None:
    assert mean_absolute_scaled_error([0.0], [1.0], [0.0, 0.0, 0.0]) is None
    assert mean_absolute_scaled_error([1.0], [1.0], [1.0], season_length=1) is None


def test_mase_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="season_length"):
        mean_absolute_scaled_error([1.0], [1.0], [1.0, 2.0], season_length=0)
    with pytest.raises(ValueError, match="same length"):
        mean_absolute_scaled_error([1.0], [], [1.0, 2.0])
    with pytest.raises(ValueError, match="finite"):
        mean_absolute_scaled_error([1.0], [1.0], [1.0, float("inf")])


def test_interval_coverage_is_inclusive() -> None:
    assert interval_coverage([1.0, 2.0, 3.0], [1.0, 1.5, 2.0], [1.0, 2.5, 3.0]) == pytest.approx(
        2.0 / 3.0
    )


def test_interval_coverage_rejects_invalid_bounds() -> None:
    with pytest.raises(ValueError, match="same length"):
        interval_coverage([1.0], [0.0], [])
    with pytest.raises(ValueError, match="must not exceed"):
        interval_coverage([1.0], [2.0], [1.0])
