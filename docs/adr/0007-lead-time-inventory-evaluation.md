# ADR 0007: Evaluate replenishment decisions on cumulative lead-time demand

- Status: accepted.
- Date: 2026-11-22

## Context

The forecasting contracts store marginal quantiles for each horizon step. Marginal distributions do not encode temporal dependence, so summing same-level daily quantiles does not produce a valid quantile of cumulative lead-time demand. Inventory decisions need a distribution for the cumulative lead-time total and must be evaluated against realized lead-time demand.

## Decision

- Keep cumulative lead-time demand quantiles as an explicit input to the inventory evaluator.
- Reuse the newsvendor order primitive for target-stock and pack-size decisions.
- Evaluate realized shortage and ending inventory with explicit holding and shortage cost rates.
- Report unit fill rate and cycle service level independently.
- Do not infer cumulative quantiles from marginal forecast curves or assume independent periods.

## Consequences

- Callers need a separately validated cumulative lead-time distribution (for example, from joint path samples or direct lead-time historical calibration).
- The evaluator is deterministic and auditable, but its scenario results depend on the quality and representativeness of caller-supplied distributions and realized outcomes.
- The current evaluator omits intra-lead-time replenishment dynamics, salvage value, lost-sales recovery, and multi-echelon constraints.
