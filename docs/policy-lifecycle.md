# Versioned replenishment policies

`ReplenishmentPolicyRegistry` stores tenant-scoped immutable definitions in
SQLite. Each version is validated, canonicalized, and assigned a SHA-256 digest.
The active pointer is scoped by tenant and policy ID; activation uses
compare-and-swap, rollback requires an explicit target and expected active
version, and activation history is append-only.

The initial supported contract is Newsvendor:

- `policy_type`: `newsvendor`
- `underage_cost` and `overage_cost`: finite positive numbers
- `pack_size`: positive integer (defaults to 1)
- optional finite-JSON `metadata` and non-blank `description`

```python
from demand_forecast_kit.policy_registry import ReplenishmentPolicyRegistry

registry = ReplenishmentPolicyRegistry("state/policies.sqlite")
registry.register_policy(
    "tenant-a",
    "service-level-90",
    "v1",
    {"policy_type": "newsvendor", "underage_cost": 9, "overage_cost": 1, "pack_size": 6},
)
registry.activate("tenant-a", "service-level-90", "v1", expected_active_version=None)
```

Pass the registry to `OperationalWorker(policy_registry=registry)`. In this
mode, each replenishment schedule must name an active `policy_id`; the
registered definition supplies costs and pack size, and conflicting schedule
values are ignored. Decisions and runs record the exact policy version and
definition digest. If no version is active, the job fails and is retried rather
than silently executing a different policy.

Policy ranking remains advisory and never activates candidates automatically.
This is a single-host SQLite control plane, not distributed coordination.
