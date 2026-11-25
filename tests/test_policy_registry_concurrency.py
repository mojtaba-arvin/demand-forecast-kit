from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from demand_forecast_kit.policy_registry import ReplenishmentPolicyRegistry


def test_concurrent_initial_activation_has_one_compare_and_swap_winner(tmp_path) -> None:
    registry = ReplenishmentPolicyRegistry(tmp_path / "policies.sqlite")
    definition = {
        "policy_type": "newsvendor",
        "underage_cost": 9,
        "overage_cost": 1,
        "pack_size": 6,
    }
    registry.register_policy("tenant-a", "service-level", "v1", definition)
    registry.register_policy("tenant-a", "service-level", "v2", {**definition, "underage_cost": 4})
    barrier = Barrier(2)

    def activate(version: str) -> str:
        barrier.wait()
        try:
            result = registry.activate(
                "tenant-a",
                "service-level",
                version,
                expected_active_version=None,
            )
        except ValueError:
            return "conflict"
        return result.active_policy_version

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(activate, ("v1", "v2")))

    assert outcomes.count("conflict") == 1
    winner = next(value for value in outcomes if value != "conflict")
    active = registry.get_active("tenant-a", "service-level")
    assert active is not None and active.policy_version == winner
    assert len(registry.activation_history("tenant-a", "service-level")) == 1
