# SPDX-FileCopyrightText: 2026 Mojtaba Arvin
# SPDX-License-Identifier: MIT
"""Run a deterministic synthetic replenishment-policy evaluation."""

from __future__ import annotations

import json
from pathlib import Path

from demand_forecast_kit.inventory import InventoryScenario, evaluate_inventory_policy


def main() -> None:
    quantiles = {0.1: 8.0, 0.5: 12.0, 0.9: 18.0}
    scenarios = [
        InventoryScenario(f"origin-{index:02d}", quantiles, actual, position)
        for index, (actual, position) in enumerate(
            [(10.0, 4.0), (17.0, 2.0), (7.0, 8.0), (22.0, 1.0), (13.0, 5.0)],
            start=1,
        )
    ]
    report = evaluate_inventory_policy(
        scenarios,
        underage_cost=9.0,
        overage_cost=1.0,
        holding_cost_per_unit=0.5,
        shortage_cost_per_unit=4.0,
        pack_size=2,
    )
    payload = {
        "schema_version": 1,
        "provenance": "synthetic-policy-plumbing-only",
        "scenario_count": report.scenario_count,
        "total_demand": report.total_demand,
        "total_ordered_units": report.total_ordered_units,
        "total_shortage_units": report.total_shortage_units,
        "total_ending_inventory": report.total_ending_inventory,
        "total_holding_cost": report.total_holding_cost,
        "total_shortage_cost": report.total_shortage_cost,
        "total_cost": report.total_cost,
        "fill_rate": report.fill_rate,
        "cycle_service_level": report.cycle_service_level,
        "average_cost_per_scenario": report.average_cost_per_scenario,
    }
    destination = Path("artifacts/synthetic-inventory-evaluation.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
