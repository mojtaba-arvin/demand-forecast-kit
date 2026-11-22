# SPDX-FileCopyrightText: 2026 Mojtaba Arvin
# SPDX-License-Identifier: MIT
"""Evaluate replenishment decisions against realized lead-time demand."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import fsum, isfinite

from demand_forecast_kit.decisions import OrderRecommendation, newsvendor_order


@dataclass(frozen=True, slots=True)
class InventoryScenario:
    """One independent replenishment opportunity at a forecast origin.

    Quantiles must describe cumulative demand over the complete replenishment
    lead time. They must not be assembled by summing marginal daily quantiles.
    """

    scenario_id: str
    lead_time_demand_quantiles: Mapping[float, float]
    realized_lead_time_demand: float
    inventory_position: float


@dataclass(frozen=True, slots=True)
class ScenarioDecision:
    """Order and realized outcome for one scenario."""

    scenario_id: str
    recommendation: OrderRecommendation
    realized_demand: float
    available_supply: float
    fulfilled_demand: float
    ending_inventory: float
    shortage_units: float
    holding_cost: float
    shortage_cost: float
    total_cost: float
    cycle_service: bool


@dataclass(frozen=True, slots=True)
class InventoryEvaluationReport:
    """Aggregate, auditable inventory-policy outcomes."""

    scenarios: tuple[ScenarioDecision, ...]
    scenario_count: int
    total_demand: float
    total_fulfilled_demand: float
    total_ordered_units: int
    total_shortage_units: float
    total_ending_inventory: float
    total_holding_cost: float
    total_shortage_cost: float
    total_cost: float
    fill_rate: float
    cycle_service_level: float
    average_cost_per_scenario: float


def evaluate_inventory_policy(
    scenarios: Sequence[InventoryScenario],
    *,
    underage_cost: float,
    overage_cost: float,
    holding_cost_per_unit: float,
    shortage_cost_per_unit: float,
    pack_size: int = 1,
) -> InventoryEvaluationReport:
    """Evaluate a newsvendor replenishment policy on realized lead-time outcomes.

    Inventory position is treated as the available supply for the complete
    lead-time window (on-hand + confirmed inbound - backorders). The evaluator
    assumes no intra-window replenishment or salvage value. It reports
    cycle-service and unit fill-rate separately; neither is a substitute for
    the other. Scenario costs use explicit realized holding/shortage rates,
    while underage/overage costs determine the policy's target quantile.
    """
    if not scenarios:
        raise ValueError("at least one inventory scenario is required")
    for name, value in (
        ("holding_cost_per_unit", holding_cost_per_unit),
        ("shortage_cost_per_unit", shortage_cost_per_unit),
    ):
        if not isfinite(value) or value < 0.0:
            raise ValueError(f"{name} must be finite and non-negative")

    seen_ids: set[str] = set()
    outcomes: list[ScenarioDecision] = []
    for scenario in scenarios:
        if not scenario.scenario_id.strip():
            raise ValueError("scenario_id must not be blank")
        if scenario.scenario_id in seen_ids:
            raise ValueError(f"duplicate scenario_id: {scenario.scenario_id}")
        seen_ids.add(scenario.scenario_id)
        if (
            not isfinite(scenario.realized_lead_time_demand)
            or scenario.realized_lead_time_demand < 0.0
        ):
            raise ValueError("realized lead-time demand must be finite and non-negative")
        if not isfinite(scenario.inventory_position):
            raise ValueError("inventory_position must be finite")

        recommendation = newsvendor_order(
            scenario.lead_time_demand_quantiles,
            underage_cost=underage_cost,
            overage_cost=overage_cost,
            inventory_position=scenario.inventory_position,
            pack_size=pack_size,
        )
        available_supply = scenario.inventory_position + recommendation.quantity
        fulfilled = min(scenario.realized_lead_time_demand, max(0.0, available_supply))
        shortage = max(0.0, scenario.realized_lead_time_demand - available_supply)
        ending_inventory = max(0.0, available_supply - scenario.realized_lead_time_demand)
        holding_cost = ending_inventory * holding_cost_per_unit
        shortage_cost = shortage * shortage_cost_per_unit
        outcomes.append(
            ScenarioDecision(
                scenario_id=scenario.scenario_id,
                recommendation=recommendation,
                realized_demand=scenario.realized_lead_time_demand,
                available_supply=available_supply,
                fulfilled_demand=fulfilled,
                ending_inventory=ending_inventory,
                shortage_units=shortage,
                holding_cost=holding_cost,
                shortage_cost=shortage_cost,
                total_cost=holding_cost + shortage_cost,
                cycle_service=shortage == 0.0,
            )
        )

    total_demand = fsum(item.realized_demand for item in outcomes)
    total_fulfilled = fsum(item.fulfilled_demand for item in outcomes)
    total_shortage = fsum(item.shortage_units for item in outcomes)
    total_ending = fsum(item.ending_inventory for item in outcomes)
    total_holding = fsum(item.holding_cost for item in outcomes)
    total_shortage_cost = fsum(item.shortage_cost for item in outcomes)
    count = len(outcomes)
    return InventoryEvaluationReport(
        scenarios=tuple(outcomes),
        scenario_count=count,
        total_demand=total_demand,
        total_fulfilled_demand=total_fulfilled,
        total_ordered_units=sum(item.recommendation.quantity for item in outcomes),
        total_shortage_units=total_shortage,
        total_ending_inventory=total_ending,
        total_holding_cost=total_holding,
        total_shortage_cost=total_shortage_cost,
        total_cost=total_holding + total_shortage_cost,
        fill_rate=1.0 if total_demand == 0.0 else total_fulfilled / total_demand,
        cycle_service_level=sum(item.cycle_service for item in outcomes) / count,
        average_cost_per_scenario=(total_holding + total_shortage_cost) / count,
    )
