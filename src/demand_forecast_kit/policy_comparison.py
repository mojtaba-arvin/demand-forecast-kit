"""Comparable inventory-policy evaluation on identical realized scenarios."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from demand_forecast_kit.inventory import InventoryEvaluationReport, InventoryScenario, evaluate_inventory_policy


@dataclass(frozen=True, slots=True)
class InventoryPolicy:
    """Decision and realized-cost parameters for one replenishment policy."""

    underage_cost: float
    overage_cost: float
    holding_cost_per_unit: float
    shortage_cost_per_unit: float
    pack_size: int = 1


def compare_inventory_policies(
    scenarios: Sequence[InventoryScenario],
    policies: Mapping[str, InventoryPolicy],
) -> dict[str, InventoryEvaluationReport]:
    """Evaluate two or more policies against exactly the same scenario set."""
    if len(policies) < 2:
        raise ValueError("at least two named inventory policies are required")
    if any(not name.strip() for name in policies):
        raise ValueError("policy names must not be blank")
    return {
        name: evaluate_inventory_policy(
            scenarios,
            underage_cost=policy.underage_cost,
            overage_cost=policy.overage_cost,
            holding_cost_per_unit=policy.holding_cost_per_unit,
            shortage_cost_per_unit=policy.shortage_cost_per_unit,
            pack_size=policy.pack_size,
        )
        for name, policy in policies.items()
    }
