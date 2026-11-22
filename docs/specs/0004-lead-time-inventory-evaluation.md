# SPEC 0004: Lead-time inventory decision evaluation

- Status: implemented on `work/lead-time-inventory-evaluation`; CI verification pending.
- Scope: evaluate a replenishment policy against realized cumulative lead-time demand and report service/cost outcomes.
- Non-goals: infer joint demand paths from marginal quantiles, estimate lead-time distributions, simulate intra-lead-time inventory dynamics, optimize policy parameters, or claim business savings.

## Contract

1. Each scenario represents one independent replenishment origin and supplies a quantile curve for cumulative demand over the full lead time.
2. The quantile curve is passed to the existing newsvendor decision primitive; daily marginal quantiles are not aggregated.
3. Inventory position is interpreted as on-hand plus confirmed inbound stock minus backorders at the decision origin.
4. Order quantities are rounded up to pack size by the existing decision primitive.
5. Realized available supply is inventory position plus the recommended order. No intra-window replenishment, substitution, lost-sales recovery, or salvage value is modeled.
6. Report holding cost on positive ending inventory and shortage cost on unfulfilled demand using explicit realized per-unit rates.
7. Report unit fill rate (fulfilled / demand) and cycle service level (share of scenarios with no shortage) separately.
8. Scenario IDs must be unique; invalid demand, inventory, costs, and quantile curves are rejected.

## Acceptance

- Deterministic unit tests cover shortages, excess, existing inventory, zero demand, duplicate IDs, and invalid inputs.
- Base CI runs a synthetic policy smoke and uploads its JSON artifact.
- Synthetic output proves calculation and serialization plumbing only; it is not a model benchmark or evidence of savings.
