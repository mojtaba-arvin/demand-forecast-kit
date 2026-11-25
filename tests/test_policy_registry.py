import sqlite3

import pytest

from demand_forecast_kit.policy_registry import ReplenishmentPolicyRegistry


def _definition(underage: float = 9.0) -> dict[str, object]:
    return {
        "policy_type": "newsvendor",
        "underage_cost": underage,
        "overage_cost": 1.0,
        "pack_size": 6,
        "metadata": {"owner": "inventory"},
    }


def test_policy_versions_are_immutable_idempotent_and_tenant_scoped(tmp_path) -> None:
    registry = ReplenishmentPolicyRegistry(tmp_path / "policies.sqlite")
    first = registry.register_policy("tenant-a", "service-level", "v1", _definition())
    retry = registry.register_policy("tenant-a", "service-level", "v1", _definition())

    assert retry == first
    assert registry.get_policy("tenant-a", "service-level", "v1") == first
    with pytest.raises(ValueError, match="different definition"):
        registry.register_policy("tenant-a", "service-level", "v1", _definition(4.0))
    assert registry.list_policies("tenant-b", "service-level") == ()


def test_policy_activation_uses_compare_and_swap_and_supports_explicit_rollback(tmp_path) -> None:
    registry = ReplenishmentPolicyRegistry(tmp_path / "policies.sqlite")
    registry.register_policy("tenant-a", "service-level", "v1", _definition())
    registry.register_policy("tenant-a", "service-level", "v2", _definition(4.0))

    first = registry.activate("tenant-a", "service-level", "v1", expected_active_version=None)
    second = registry.activate("tenant-a", "service-level", "v2", expected_active_version="v1")
    with pytest.raises(ValueError, match="active policy version changed"):
        registry.activate("tenant-a", "service-level", "v1", expected_active_version=None)
    rollback = registry.rollback("tenant-a", "service-level", "v1", expected_active_version="v2")

    assert first.action == "activate"
    assert second.previous_policy_version == "v1"
    assert rollback.action == "rollback"
    active = registry.get_active("tenant-a", "service-level")
    assert active is not None and active.policy_version == "v1"
    assert [
        event.action for event in registry.activation_history("tenant-a", "service-level")
    ] == [
        "activate",
        "activate",
        "rollback",
    ]


def test_policy_definitions_reject_invalid_costs_pack_sizes_and_fields(tmp_path) -> None:
    registry = ReplenishmentPolicyRegistry(tmp_path / "policies.sqlite")
    for definition in (
        {"policy_type": "unknown", "underage_cost": 1, "overage_cost": 1},
        {"policy_type": "newsvendor", "underage_cost": 0, "overage_cost": 1},
        {"policy_type": "newsvendor", "underage_cost": float("nan"), "overage_cost": 1},
        {"policy_type": "newsvendor", "underage_cost": 1, "overage_cost": 1, "pack_size": True},
        {**_definition(), "unexpected": True},
    ):
        with pytest.raises(ValueError):
            registry.register_policy("tenant-a", "bad-policy", "v1", definition)


def test_policy_version_and_activation_history_are_immutable(tmp_path) -> None:
    database = tmp_path / "policies.sqlite"
    registry = ReplenishmentPolicyRegistry(database)
    registry.register_policy("tenant-a", "service-level", "v1", _definition())
    registry.activate("tenant-a", "service-level", "v1", expected_active_version=None)

    with sqlite3.connect(database) as db:
        with pytest.raises(sqlite3.IntegrityError, match="policy versions are immutable"):
            db.execute(
                "UPDATE replenishment_policy_versions SET definition_json='{}' "
                "WHERE tenant_id='tenant-a'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="policy events are immutable"):
            db.execute("DELETE FROM replenishment_policy_events")
