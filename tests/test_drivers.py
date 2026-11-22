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
        DemandDriverObservation(12.0, 5.0, False),
        DemandDriverObservation(14.0, 6.0, True),
        DemandDriverObservation(16.0, 6.0, True),
    ]
    with pytest.raises(ValueError, match="collinear"):
        estimate_demand_driver_effects(collinear)


def test_driver_effects_handle_constant_demand_with_full_rank_features() -> None:
    observations = [
        DemandDriverObservation(5.0, price, promoted)
        for promoted in (False, True)
        for price in (1.0, 2.0, 3.0)
    ]

    result = estimate_demand_driver_effects(observations)

    assert result.intercept == pytest.approx(5.0)
    assert result.price_effect == pytest.approx(0.0)
    assert result.promotion_effect == pytest.approx(0.0)
    assert result.r_squared == 1.0


def test_driver_effects_validate_driver_values_and_feature_variation() -> None:
    valid = [
        DemandDriverObservation(5.0, price, promoted)
        for promoted in (False, True)
        for price in (1.0, 2.0)
    ]
    with pytest.raises(ValueError, match="demand must be finite"):
        estimate_demand_driver_effects(
            [DemandDriverObservation(float("nan"), item.price, item.promoted) for item in valid]
        )
    with pytest.raises(ValueError, match="price must be finite"):
        estimate_demand_driver_effects(
            [DemandDriverObservation(item.demand, 0.0, item.promoted) for item in valid]
        )
    with pytest.raises(ValueError, match="both promotion states"):
        estimate_demand_driver_effects(
            [DemandDriverObservation(item.demand, item.price, False) for item in valid]
        )
    with pytest.raises(ValueError, match="promoted must be boolean"):
        estimate_demand_driver_effects(
            [
                DemandDriverObservation(item.demand, item.price, 1)  # type: ignore[arg-type]
                for item in valid
            ]
        )
