import pytest
from hypothesis import given, strategies as st

from demand_forecast_kit.decisions import newsvendor_order


def test_newsvendor_interpolates_and_rounds_to_pack_size() -> None:
    result = newsvendor_order(
        {0.1: 5.0, 0.5: 10.0, 0.9: 15.0},
        underage_cost=9.0,
        overage_cost=1.0,
        inventory_position=0.0,
        pack_size=2,
    )

    assert result.target_service_level == pytest.approx(0.9)
    assert result.target_stock_level == pytest.approx(15.0)
    assert result.unrounded_quantity == pytest.approx(15.0)
    assert result.quantity == 16


def test_newsvendor_subtracts_inventory_position() -> None:
    result = newsvendor_order(
        {0.1: 5.0, 0.5: 10.0, 0.9: 15.0},
        underage_cost=9.0,
        overage_cost=1.0,
        inventory_position=11.0,
        pack_size=2,
    )
    assert result.unrounded_quantity == pytest.approx(4.0)
    assert result.quantity == 4


def test_newsvendor_does_not_order_when_inventory_exceeds_target() -> None:
    result = newsvendor_order(
        {0.1: 5.0, 0.5: 10.0, 0.9: 15.0},
        underage_cost=9.0,
        overage_cost=1.0,
        inventory_position=20.0,
    )
    assert result.quantity == 0
    assert result.unrounded_quantity == 0.0


def test_newsvendor_interpolates_between_quantiles() -> None:
    result = newsvendor_order(
        {0.1: 2.0, 0.9: 10.0},
        underage_cost=1.0,
        overage_cost=1.0,
        inventory_position=0.0,
    )
    assert result.target_stock_level == pytest.approx(6.0)
    assert result.quantity == 6


def test_newsvendor_rejects_unbracketed_service_level() -> None:
    with pytest.raises(ValueError, match="bracket"):
        newsvendor_order(
            {0.2: 2.0, 0.8: 10.0},
            underage_cost=99.0,
            overage_cost=1.0,
            inventory_position=0.0,
        )


@pytest.mark.parametrize(
    ("quantiles", "underage", "overage", "inventory", "pack", "message"),
    [
        ({}, 1.0, 1.0, 0.0, 1, "at least one"),
        ({0.0: 1.0}, 1.0, 1.0, 0.0, 1, "quantile levels"),
        ({0.5: -1.0}, 1.0, 1.0, 0.0, 1, "non-negative"),
        ({0.1: 4.0, 0.9: 2.0}, 1.0, 1.0, 0.0, 1, "non-decreasing"),
        ({0.1: 1.0, 0.9: 2.0}, 0.0, 1.0, 0.0, 1, "positive"),
        ({0.1: 1.0, 0.9: 2.0}, 1.0, 1.0, float("inf"), 1, "inventory_position"),
        ({0.1: 1.0, 0.9: 2.0}, 1.0, 1.0, 0.0, 0, "pack_size"),
    ],
)
def test_newsvendor_rejects_invalid_inputs(
    quantiles: dict[float, float],
    underage: float,
    overage: float,
    inventory: float,
    pack: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        newsvendor_order(
            quantiles,
            underage_cost=underage,
            overage_cost=overage,
            inventory_position=inventory,
            pack_size=pack,
        )


@given(
    first=st.floats(min_value=0.11, max_value=0.89, allow_nan=False, allow_infinity=False),
    second=st.floats(min_value=0.11, max_value=0.89, allow_nan=False, allow_infinity=False),
)
def test_newsvendor_quantity_is_monotone_in_target_service_level(
    first: float, second: float
) -> None:
    low, high = sorted((first, second))
    quantiles = {0.1: 1.0, 0.5: 5.0, 0.9: 9.0}
    low_result = newsvendor_order(
        quantiles,
        underage_cost=low,
        overage_cost=1.0 - low,
        inventory_position=0.0,
    )
    high_result = newsvendor_order(
        quantiles,
        underage_cost=high,
        overage_cost=1.0 - high,
        inventory_position=0.0,
    )

    assert low_result.quantity <= high_result.quantity
