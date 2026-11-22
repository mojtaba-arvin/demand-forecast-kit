from __future__ import annotations

import pytest

from demand_forecast_kit.simulation import (
    InventorySimulationConfig,
    simulate_inventory_policy,
)


def test_backorders_are_fulfilled_before_new_demand() -> None:
    report = simulate_inventory_policy(
        [5, 5, 2, 1],
        InventorySimulationConfig(
            initial_on_hand=3,
            reorder_point=0,
            order_quantity=20,
            lead_time_days=2,
            allow_backorders=True,
        ),
    )

    assert report.days[0].backorders == 2
    assert report.days[2].received == 20
    assert report.days[2].fulfilled == 9
    assert report.days[2].backorders == 0
    assert report.ending_backorders == 0
    assert report.total_demand == report.total_fulfilled
    assert report.fill_rate == 1.0


def test_lost_sales_do_not_carry_into_following_days() -> None:
    report = simulate_inventory_policy(
        [5, 1],
        InventorySimulationConfig(
            initial_on_hand=2,
            reorder_point=0,
            order_quantity=1,
            lead_time_days=1,
            allow_backorders=False,
        ),
    )

    assert report.days[0].lost_sales == 3
    assert report.days[1].received == 1
    assert report.days[1].fulfilled == 1
    assert report.ending_backorders == 0
    assert report.total_lost_sales == 3


def test_inventory_simulation_rejects_invalid_demand_and_policy() -> None:
    config = InventorySimulationConfig(10, 2, 5, 1)

    with pytest.raises(ValueError, match="finite and non-negative"):
        simulate_inventory_policy([1, float("nan")], config)
    with pytest.raises(ValueError, match="positive integer"):
        InventorySimulationConfig(10, 2, 5, 0)
    with pytest.raises(ValueError, match="positive"):
        InventorySimulationConfig(10, 2, 0, 1)


def test_no_demand_has_perfect_fill_rate_without_orders() -> None:
    report = simulate_inventory_policy(
        [0, 0, 0],
        InventorySimulationConfig(5, 2, 3, 1),
    )

    assert report.fill_rate == 1.0
    assert report.total_ordered == 0
    assert report.ending_on_hand == 5


def test_backorder_days_remain_stockout_days_without_new_demand() -> None:
    report = simulate_inventory_policy(
        [5, 0, 0],
        InventorySimulationConfig(
            initial_on_hand=0,
            reorder_point=0,
            order_quantity=1,
            lead_time_days=4,
            allow_backorders=True,
        ),
    )

    assert report.days[0].backorders == 5
    assert report.days[1].backorders == 5
    assert report.days[2].backorders == 5
    assert report.stockout_days == 3
