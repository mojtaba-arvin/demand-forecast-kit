from __future__ import annotations

import pytest

from demand_forecast_kit.inventory import InventoryScenario
from demand_forecast_kit.policy_comparison import InventoryPolicy, compare_inventory_policies


def test_policies_are_compared_on_identical_scenarios() -> None:
    scenarios = [
        InventoryScenario(
            scenario_id="sku-1-origin-1",
            lead_time_demand_quantiles={0.1: 2, 0.5: 5, 0.9: 10},
            realized_lead_time_demand=8,
            inventory_position=2,
        )
    ]
    reports = compare_inventory_policies(
        scenarios,
        {
            "baseline": InventoryPolicy(1, 1, 0.5, 5),
            "high-service": InventoryPolicy(9, 1, 2, 10),
        },
    )

    assert reports["baseline"].scenario_count == reports["high-service"].scenario_count == 1
    assert reports["high-service"].total_cost < reports["baseline"].total_cost
    assert reports["baseline"].scenarios[0].scenario_id == "sku-1-origin-1"


def test_policy_comparison_requires_two_named_policies() -> None:
    with pytest.raises(ValueError, match="at least two"):
        compare_inventory_policies(
            [],
            {"baseline": InventoryPolicy(1, 1, 1, 1)},
        )
    with pytest.raises(ValueError, match="must not be blank"):
        compare_inventory_policies(
            [],
            {" ": InventoryPolicy(1, 1, 1, 1), "candidate": InventoryPolicy(1, 1, 1, 1)},
        )
