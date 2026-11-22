from __future__ import annotations

import pytest

from demand_forecast_kit.calibration_inventory import compare_calibration_inventory_costs
from demand_forecast_kit.inventory import InventoryScenario


def test_calibration_cost_comparison_reports_service_cost_and_width_tradeoff() -> None:
    baseline = [
        InventoryScenario(
            scenario_id="sku-a-origin-1",
            lead_time_demand_quantiles={0.1: 2, 0.5: 5, 0.9: 8},
            realized_lead_time_demand=9,
            inventory_position=2,
        )
    ]
    calibrated = [
        InventoryScenario(
            scenario_id="sku-a-origin-1",
            lead_time_demand_quantiles={0.1: 1, 0.5: 5, 0.9: 10},
            realized_lead_time_demand=9,
            inventory_position=2,
        )
    ]

    result = compare_calibration_inventory_costs(
        baseline,
        calibrated,
        underage_cost=9,
        overage_cost=1,
        holding_cost_per_unit=1,
        shortage_cost_per_unit=10,
    )

    assert result.baseline.total_cost == 10
    assert result.calibrated.total_cost == 1
    assert result.cost_delta == -9
    assert result.fill_rate_delta > 0
    assert result.cycle_service_level_delta == 1
    assert result.calibrated_average_interval_width > result.baseline_average_interval_width


def test_calibration_cost_comparison_rejects_changed_realized_scenarios() -> None:
    baseline = InventoryScenario("sku-a", {0.1: 1, 0.5: 2, 0.9: 3}, 3, 0)
    calibrated = InventoryScenario("sku-a", {0.1: 0, 0.5: 2, 0.9: 4}, 4, 0)

    with pytest.raises(ValueError, match="scenario identity"):
        compare_calibration_inventory_costs(
            [baseline],
            [calibrated],
            underage_cost=1,
            overage_cost=1,
            holding_cost_per_unit=1,
            shortage_cost_per_unit=1,
        )
