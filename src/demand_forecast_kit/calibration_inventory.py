"""Evaluate calibration's downstream inventory-cost trade-off on fixed scenarios."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from demand_forecast_kit.inventory import (
    InventoryEvaluationReport,
    InventoryScenario,
    evaluate_inventory_policy,
)


@dataclass(frozen=True, slots=True)
class CalibrationInventoryComparison:
    """Baseline versus calibrated policy cost and service deltas."""

    baseline: InventoryEvaluationReport
    calibrated: InventoryEvaluationReport
    baseline_average_interval_width: float
    calibrated_average_interval_width: float
    cost_delta: float
    fill_rate_delta: float
    cycle_service_level_delta: float


def compare_calibration_inventory_costs(
    baseline_scenarios: Sequence[InventoryScenario],
    calibrated_scenarios: Sequence[InventoryScenario],
    *,
    underage_cost: float,
    overage_cost: float,
    holding_cost_per_unit: float,
    shortage_cost_per_unit: float,
    pack_size: int = 1,
) -> CalibrationInventoryComparison:
    """Compare frozen baseline/calibrated forecasts on identical realized demand.

    Scenario IDs, realized lead-time demand, inventory position, and quantile
    levels must match. Only forecast quantile values may differ. Fit the
    calibrator on an earlier calibration partition, then pass its frozen
    forecasts and the untouched temporal evaluation scenarios here.
    """
    baseline = tuple(baseline_scenarios)
    calibrated = tuple(calibrated_scenarios)
    if not baseline or len(baseline) != len(calibrated):
        raise ValueError("baseline and calibrated scenarios must have equal non-zero lengths")

    baseline_widths: list[float] = []
    calibrated_widths: list[float] = []
    for original, adjusted in zip(baseline, calibrated, strict=True):
        if (
            original.scenario_id != adjusted.scenario_id
            or original.realized_lead_time_demand != adjusted.realized_lead_time_demand
            or original.inventory_position != adjusted.inventory_position
            or set(original.lead_time_demand_quantiles)
            != set(adjusted.lead_time_demand_quantiles)
        ):
            raise ValueError(
                "scenario identity, realized demand, inventory position, and quantile levels "
                "must match between baseline and calibrated inputs"
            )
        baseline_values = tuple(original.lead_time_demand_quantiles.values())
        calibrated_values = tuple(adjusted.lead_time_demand_quantiles.values())
        baseline_widths.append(max(baseline_values) - min(baseline_values))
        calibrated_widths.append(max(calibrated_values) - min(calibrated_values))

    baseline_report = evaluate_inventory_policy(
        baseline,
        underage_cost=underage_cost,
        overage_cost=overage_cost,
        holding_cost_per_unit=holding_cost_per_unit,
        shortage_cost_per_unit=shortage_cost_per_unit,
        pack_size=pack_size,
    )
    calibrated_report = evaluate_inventory_policy(
        calibrated,
        underage_cost=underage_cost,
        overage_cost=overage_cost,
        holding_cost_per_unit=holding_cost_per_unit,
        shortage_cost_per_unit=shortage_cost_per_unit,
        pack_size=pack_size,
    )
    count = len(baseline)
    return CalibrationInventoryComparison(
        baseline=baseline_report,
        calibrated=calibrated_report,
        baseline_average_interval_width=sum(baseline_widths) / count,
        calibrated_average_interval_width=sum(calibrated_widths) / count,
        cost_delta=calibrated_report.total_cost - baseline_report.total_cost,
        fill_rate_delta=calibrated_report.fill_rate - baseline_report.fill_rate,
        cycle_service_level_delta=(
            calibrated_report.cycle_service_level - baseline_report.cycle_service_level
        ),
    )
