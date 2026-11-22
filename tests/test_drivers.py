from __future__ import annotations

import pytest

from demand_forecast_kit.drivers import (
    DemandDriverObservation,
    estimate_demand_driver_effects,
)


def test_driver_effects_recover_known_linear_associations() -> None:
    observations = [
        DemandDriverObservation(
            demand=100.0 - 2.0 * price + (20.0 if promoted else 0.0),
            price=price,
            promoted=promoted,
        )
        for promoted in (False, True)
        for price in (10.0, 12.0, 14.0, 16.0)
    ]

    result = estimate_demand_driver_effects(observations)

    assert result.intercept == pytest.approx(100.0)
    assert result.price_effect == pytest.approx(-2.0)
    assert result.promotion_effect == pytest.approx(20.0)
    assert result.r_squared == pytest.approx(1.0)


def test_driver_effects_reject_invalid_or_collinear_training_data() -> None:
    with pytest.raises(ValueError, match="at least four"):
        estimate_demand_driver_effects([])
    collinear = [
        DemandDriverObservation(10.0, 5.0, False),
        DemandDriverObservation(12.0, 6.0, False),
        DemandDriverObservation(14.0, 7.0, True),
        DemandDriverObservation(16.0, 8.0, True),
    ]
    with pytest.raises(ValueError, match="collinear"):
        estimate_demand_driver_effects(collinear)
