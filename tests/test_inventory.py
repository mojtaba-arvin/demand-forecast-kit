# SPDX-FileCopyrightText: 2026 Mojtaba Arvin
# SPDX-License-Identifier: MIT
import pytest

from demand_forecast_kit.inventory import InventoryScenario, evaluate_inventory_policy


def _scenario(
    scenario_id: str,
    *,
    actual: float,
    inventory: float = 0.0,
) -> InventoryScenario:
    return InventoryScenario(
        scenario_id=scenario_id,
        lead_time_demand_quantiles={0.1: 5.0, 0.5: 10.0, 0.9: 15.0},
        realized_lead_time_demand=actual,
        inventory_position=inventory,
    )


def test_evaluation_reports_cost_service_and_fill_rate() -> None:
    report = evaluate_inventory_policy(
        [_scenario("short", actual=20), _scenario("balanced", actual=10)],
        underage_cost=9,
        overage_cost=1,
        holding_cost_per_unit=2,
        shortage_cost_per_unit=5,
    )
    assert report.scenario_count == 2
    assert report.total_ordered_units == 30
    assert report.total_shortage_units == 5
    assert report.total_ending_inventory == 5
    assert report.total_holding_cost == 10
    assert report.total_shortage_cost == 25
    assert report.total_cost == 35
    assert report.fill_rate == pytest.approx(25 / 30)
    assert report.cycle_service_level == pytest.approx(0.5)
    assert report.average_cost_per_scenario == pytest.approx(17.5)


def test_inventory_position_includes_existing_supply_before_order() -> None:
    report = evaluate_inventory_policy(
        [_scenario("covered", actual=12, inventory=12)],
        underage_cost=9,
        overage_cost=1,
        holding_cost_per_unit=1,
        shortage_cost_per_unit=4,
    )
    assert report.scenarios[0].recommendation.quantity == 3
    assert report.scenarios[0].available_supply == 15
    assert report.scenarios[0].ending_inventory == 3
    assert report.total_ordered_units == 3


def test_no_demand_has_defined_perfect_fill_rate() -> None:
    report = evaluate_inventory_policy(
        [_scenario("zero", actual=0)],
        underage_cost=1,
        overage_cost=1,
        holding_cost_per_unit=0,
        shortage_cost_per_unit=3,
    )
    assert report.fill_rate == 1.0
    assert report.cycle_service_level == 1.0


def test_duplicate_scenario_ids_are_rejected() -> None:
    scenario = _scenario("same", actual=2)
    with pytest.raises(ValueError, match="duplicate"):
        evaluate_inventory_policy(
            [scenario, scenario],
            underage_cost=1,
            overage_cost=1,
            holding_cost_per_unit=0,
            shortage_cost_per_unit=1,
        )


@pytest.mark.parametrize("actual", [-1.0, float("inf"), float("nan")])
def test_invalid_realized_demand_is_rejected(actual: float) -> None:
    with pytest.raises(ValueError, match="realized lead-time demand"):
        evaluate_inventory_policy(
            [_scenario("bad", actual=actual)],
            underage_cost=1,
            overage_cost=1,
            holding_cost_per_unit=0,
            shortage_cost_per_unit=1,
        )


@pytest.mark.parametrize("cost", [-1.0, float("inf"), float("nan")])
def test_invalid_realized_cost_is_rejected(cost: float) -> None:
    with pytest.raises(ValueError, match="finite and non-negative"):
        evaluate_inventory_policy(
            [_scenario("bad-cost", actual=1)],
            underage_cost=1,
            overage_cost=1,
            holding_cost_per_unit=cost,
            shortage_cost_per_unit=1,
        )


def test_empty_scenarios_are_rejected() -> None:
    with pytest.raises(ValueError, match="at least one"):
        evaluate_inventory_policy(
            [],
            underage_cost=1,
            overage_cost=1,
            holding_cost_per_unit=0,
            shortage_cost_per_unit=1,
        )
